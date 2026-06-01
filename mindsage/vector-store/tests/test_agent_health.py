import datetime as dt
import importlib.util
import io
import json
import sys
import unittest
from pathlib import Path


MODULE_DIR = Path(__file__).resolve().parents[1] / "mcp_vector_store"
sys.path.insert(0, str(MODULE_DIR))

AGENT_HEALTH_PATH = MODULE_DIR / "agent_health.py"
SPEC = importlib.util.spec_from_file_location("agent_health", AGENT_HEALTH_PATH)
agent_health = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(agent_health)


class AgentHealthTest(unittest.TestCase):
    def test_build_agent_health_scores_maintenance_snapshot_without_pii(self):
        report = agent_health.build_agent_health(
            documents=[
                {
                    "id": 1,
                    "text": "Remote MCP access requires bearer auth and a private tunnel.",
                    "metadata": {
                        "title": "January remote MCP policy",
                        "date": "2026-01-01",
                        "structured_metadata": {
                            "organizations": ["MindSage"],
                            "technologies": ["MCP"],
                            "persons": ["Private User"],
                        },
                        "pii_session_id": "must-not-leak",
                    },
                },
                {
                    "id": 2,
                    "text": "Remote MCP access requires bearer auth and a private tunnel.",
                    "metadata": {
                        "title": "January remote MCP policy copy",
                        "date": "2026-01-05",
                        "structured_metadata": {
                            "organizations": ["Mind Sage"],
                            "technologies": ["MCP"],
                        },
                    },
                },
                {
                    "id": 3,
                    "text": "Remote MCP access should be reviewed weekly.",
                    "metadata": {"title": "Undated MCP note"},
                },
                {
                    "id": 4,
                    "text": "Remote MCP access requires bearer auth, a private tunnel, and audit logs.",
                    "metadata": {
                        "title": "May remote MCP policy",
                        "date": "2026-05-31",
                        "structured_metadata": {
                            "organizations": ["MindSage"],
                            "technologies": ["MCP"],
                        },
                    },
                },
            ],
            reference_date=dt.date(2026, 6, 1),
            freshness_days=30,
        )

        gates = {gate["id"]: gate for gate in report["gates"]}
        serialized = json.dumps(report)

        self.assertEqual(report["health_score"], 58)
        self.assertEqual(report["status"], "needs_attention")
        self.assertEqual(report["snapshot_summary"]["document_count"], 4)
        self.assertFalse(gates["freshness"]["passed"])
        self.assertFalse(gates["dates"]["passed"])
        self.assertFalse(gates["duplicates"]["passed"])
        self.assertFalse(gates["entity_consolidation"]["passed"])
        self.assertIn("npm run maintenance:snapshot", report["recommended_commands"])
        self.assertFalse(report["privacy"]["pii_session_ids_exposed"])
        self.assertFalse(report["privacy"]["person_entities_exposed"])
        self.assertNotIn("must-not-leak", serialized)
        self.assertNotIn("Private User", serialized)

    def test_empty_health_report_is_excellent(self):
        report = agent_health.build_agent_health(
            documents=[],
            reference_date=dt.date(2026, 6, 1),
        )

        self.assertEqual(report["health_score"], 100)
        self.assertEqual(report["status"], "excellent")
        self.assertTrue(all(gate["passed"] for gate in report["gates"]))

    def test_format_agent_health_report_is_compact(self):
        report = agent_health.build_agent_health(
            documents=[
                {"id": 1, "text": "Old source", "metadata": {"date": "2026-01-01"}},
            ],
            reference_date=dt.date(2026, 6, 1),
            freshness_days=30,
        )
        formatted = agent_health.format_agent_health_report(report)

        self.assertIn("MindSage agent health:", formatted)
        self.assertIn("freshness: FAIL", formatted)
        self.assertIn("Next:", formatted)
        self.assertNotIn("Old source", formatted)

    def test_main_can_emit_json_for_synthetic_corpus(self):
        stdout = io.StringIO()

        exit_code = agent_health.main(
            [
                "--json",
                "--reference-date",
                "2026-06-01",
                "--freshness-days",
                "90",
            ],
            stdout=stdout,
        )

        self.assertEqual(exit_code, 0)
        output = json.loads(stdout.getvalue())
        self.assertEqual(output["snapshot_summary"]["document_count"], 30)
        self.assertIn(output["status"], {"excellent", "good", "needs_attention", "critical"})


if __name__ == "__main__":
    unittest.main()
