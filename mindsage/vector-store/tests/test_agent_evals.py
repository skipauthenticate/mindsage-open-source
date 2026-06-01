import importlib.util
import json
import sys
import unittest
from pathlib import Path


MODULE_DIR = Path(__file__).resolve().parents[1] / "mcp_vector_store"
sys.path.insert(0, str(MODULE_DIR))

AGENT_EVALS_PATH = MODULE_DIR / "agent_evals.py"
SPEC = importlib.util.spec_from_file_location("agent_evals", AGENT_EVALS_PATH)
agent_evals = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(agent_evals)

run_agent_memory_evals = agent_evals.run_agent_memory_evals
format_eval_report = agent_evals.format_eval_report


class AgentEvalsTest(unittest.TestCase):
    def test_run_agent_memory_evals_returns_passing_summary(self):
        report = run_agent_memory_evals()

        self.assertEqual(report["summary"]["total"], 8)
        self.assertEqual(report["summary"]["passed"], 8)
        self.assertEqual(report["summary"]["failed"], 0)
        self.assertEqual(report["summary"]["score"], 1.0)
        self.assertEqual(
            {case["id"] for case in report["cases"]},
            {
                "think.citations_privacy",
                "think.citation_graph",
                "think.entity_graph",
                "think.maintenance_actions",
                "memory.governance_defaults",
                "memory.workspace_activity",
                "memory.graph_relations",
                "memory.timeline_versions",
            },
        )

    def test_eval_report_has_no_pii_session_identifiers(self):
        report_json = json.dumps(run_agent_memory_evals())

        self.assertNotIn("pii_session_id", report_json)
        self.assertNotIn("piiSessionId", report_json)

    def test_format_eval_report_is_stable_and_human_readable(self):
        output = format_eval_report(run_agent_memory_evals())

        self.assertIn("MindSage agent evals: 8/8 passed", output)
        self.assertIn("PASS think.citations_privacy", output)
        self.assertIn("PASS think.citation_graph", output)
        self.assertIn("PASS think.entity_graph", output)
        self.assertIn("PASS think.maintenance_actions", output)
        self.assertIn("PASS memory.workspace_activity", output)
        self.assertIn("PASS memory.graph_relations", output)


if __name__ == "__main__":
    unittest.main()
