import importlib.util
import json
import sys
import unittest
from pathlib import Path


MODULE_DIR = Path(__file__).resolve().parents[1] / "mcp_vector_store"
sys.path.insert(0, str(MODULE_DIR))

AGENT_BENCHMARKS_PATH = MODULE_DIR / "agent_benchmarks.py"
SPEC = importlib.util.spec_from_file_location("agent_benchmarks", AGENT_BENCHMARKS_PATH)
agent_benchmarks = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(agent_benchmarks)

run_agent_feature_benchmarks = agent_benchmarks.run_agent_feature_benchmarks
format_benchmark_report = agent_benchmarks.format_benchmark_report


class AgentBenchmarksTest(unittest.TestCase):
    def test_run_agent_feature_benchmarks_covers_public_agent_features(self):
        report = run_agent_feature_benchmarks(iterations=1)

        self.assertEqual(report["summary"]["total"], 23)
        self.assertEqual(report["summary"]["passed"], 23)
        self.assertEqual(report["summary"]["failed"], 0)
        self.assertEqual(report["summary"]["score"], 1.0)
        self.assertEqual(
            {case["id"] for case in report["cases"]},
            {
                "think.citations",
                "think.citation_graph",
                "think.entity_graph",
                "think.maintenance",
                "maintenance.snapshot",
                "maintenance.plan",
                "maintenance.apply",
                "maintenance.ledger",
                "memory.governance",
                "memory.workspace_activity",
                "memory.timeline",
                "memory.graph",
                "remote_auth.bearer",
                "agent_setup.config_generation",
                "agent_pack.schema_pack",
                "agent_pack.schema_detect",
                "agent_capture.rest_cli",
                "agent_think.rest_cli",
                "agent_import.rest_cli",
                "agent_search.rest_cli",
                "agent_schema.contract_cli",
                "agent_health.score_cli",
                "eval.fixture_corpus",
            },
        )
        for case in report["cases"]:
            self.assertIn("metrics", case)
            self.assertIn("mean_ms", case["metrics"])
            self.assertIn("p95_ms", case["metrics"])
            self.assertIn("budget_ms", case["metrics"])
            self.assertGreaterEqual(case["metrics"]["iterations"], 1)
            self.assertTrue(case["metrics"]["within_budget"], case)

    def test_agent_feature_benchmarks_do_not_expose_sensitive_values(self):
        report_json = json.dumps(run_agent_feature_benchmarks(iterations=1))

        self.assertNotIn("pii_session_id", report_json)
        self.assertNotIn("piiSessionId", report_json)
        self.assertNotIn("must-not-leak", report_json)
        self.assertNotIn("don.jones.1987@gmail.com", report_json)
        self.assertNotIn("(408) 555-7834", report_json)
        self.assertNotIn("4521-8834-9912", report_json)

    def test_format_benchmark_report_is_stable_and_human_readable(self):
        output = format_benchmark_report(run_agent_feature_benchmarks(iterations=1))

        self.assertIn("MindSage agent feature benchmarks: 23/23 passed", output)
        self.assertIn("PASS think.citations", output)
        self.assertIn("PASS maintenance.snapshot", output)
        self.assertIn("PASS maintenance.plan", output)
        self.assertIn("PASS maintenance.apply", output)
        self.assertIn("PASS maintenance.ledger", output)
        self.assertIn("PASS think.entity_graph", output)
        self.assertIn("PASS memory.workspace_activity", output)
        self.assertIn("PASS memory.graph", output)
        self.assertIn("PASS remote_auth.bearer", output)
        self.assertIn("PASS agent_setup.config_generation", output)
        self.assertIn("PASS agent_pack.schema_pack", output)
        self.assertIn("PASS agent_pack.schema_detect", output)
        self.assertIn("PASS agent_capture.rest_cli", output)
        self.assertIn("PASS agent_think.rest_cli", output)
        self.assertIn("PASS agent_import.rest_cli", output)
        self.assertIn("PASS agent_search.rest_cli", output)
        self.assertIn("PASS agent_schema.contract_cli", output)
        self.assertIn("PASS agent_health.score_cli", output)
        self.assertIn("PASS eval.fixture_corpus", output)


if __name__ == "__main__":
    unittest.main()
