import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_DIR = Path(__file__).resolve().parents[1] / "mcp_vector_store"
sys.path.insert(0, str(MODULE_DIR))

AGENT_PACK_PATH = MODULE_DIR / "agent_pack.py"
SPEC = importlib.util.spec_from_file_location("agent_pack", AGENT_PACK_PATH)
agent_pack = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(agent_pack)


class AgentPackTest(unittest.TestCase):
    def test_build_schema_pack_exports_personal_data_taxonomy(self):
        pack = agent_pack.build_schema_pack()

        self.assertEqual(pack["schema_version"], 1)
        self.assertEqual(pack["pack_id"], "mindsage-personal-v1")
        self.assertIn("decision", pack["memory_kinds"])
        self.assertIn("summary", pack["memory_kinds"])
        category_ids = {category["id"] for category in pack["document_categories"]}
        self.assertIn("ai_chat", category_ids)
        self.assertIn("health", category_ids)
        self.assertIn("finance", category_ids)
        self.assertTrue(pack["safety"]["path_content_policy"].startswith("Do not echo"))

    def test_classify_path_returns_safe_category_without_path_leak(self):
        result = agent_pack.classify_path("/Users/alice/private/therapy-session-notes.txt")
        serialized = json.dumps(result)

        self.assertEqual(result["category_id"], "health")
        self.assertEqual(result["recommended_memory_kind"], "claim")
        self.assertEqual(result["risk_level"], "high")
        self.assertEqual(result["extension"], ".txt")
        self.assertNotIn("/Users/alice/private", serialized)
        self.assertNotIn("therapy-session-notes", serialized)
        self.assertNotIn("alice", serialized)

    def test_classify_ai_chat_export_prefers_summary_memory(self):
        result = agent_pack.classify_path("chatgpt-conversation-export.json")

        self.assertEqual(result["category_id"], "ai_chat")
        self.assertEqual(result["recommended_memory_kind"], "summary")
        self.assertIn("agent:import", result["recommended_commands"][0])

    def test_format_reports_are_compact(self):
        pack_report = agent_pack.format_pack_report(agent_pack.build_schema_pack())
        classify_report = agent_pack.format_classification_report(agent_pack.classify_path("bank-statement.txt"))

        self.assertIn("MindSage schema pack mindsage-personal-v1", pack_report)
        self.assertIn("categories=", pack_report)
        self.assertEqual(
            classify_report,
            "MindSage schema pack: finance -> claim (risk=high, confidence=0.80)",
        )

    def test_main_emits_safe_classification_json(self):
        stdout = io.StringIO()

        exit_code = agent_pack.main(
            ["--json", "--classify", "/Users/alice/private/passport-scan.pdf"],
            stdout=stdout,
        )

        output = json.loads(stdout.getvalue())
        serialized = json.dumps(output)
        self.assertEqual(exit_code, 0)
        self.assertEqual(output["category_id"], "identity")
        self.assertEqual(output["risk_level"], "high")
        self.assertNotIn("/Users/alice/private", serialized)
        self.assertNotIn("passport-scan", serialized)

    def test_detect_schema_candidates_summarizes_corpus_without_path_or_content_leaks(self):
        with tempfile.TemporaryDirectory(prefix="alice-private-") as tmpdir:
            root = Path(tmpdir)
            (root / "therapy-session-notes.txt").write_text(
                "Private therapist note with secret phrase do-not-read-me",
                encoding="utf-8",
            )
            (root / "bank-statement-2025.csv").write_text(
                "Account number should never appear",
                encoding="utf-8",
            )
            (root / "chatgpt-conversation-export.json").write_text(
                "{\"conversation\": \"private prompt text\"}",
                encoding="utf-8",
            )
            (root / "project" / "adr-decision.md").parent.mkdir()
            (root / "project" / "adr-decision.md").write_text(
                "Architecture decision content",
                encoding="utf-8",
            )

            result = agent_pack.detect_schema_candidates([str(root)])

        serialized = json.dumps(result)
        category_ids = {candidate["category_id"] for candidate in result["schema_candidates"]}

        self.assertEqual(result["schema_version"], 1)
        self.assertEqual(result["scanned"]["file_count"], 4)
        self.assertEqual(result["scanned"]["directory_count"], 1)
        self.assertIn("health", category_ids)
        self.assertIn("finance", category_ids)
        self.assertIn("ai_chat", category_ids)
        self.assertIn("project_notes", category_ids)
        self.assertGreaterEqual(result["summary"]["high_risk_file_count"], 2)
        self.assertFalse(result["privacy"]["paths_exposed"])
        self.assertFalse(result["privacy"]["document_text_exposed"])
        self.assertNotIn("alice-private", serialized)
        self.assertNotIn("therapy-session-notes", serialized)
        self.assertNotIn("bank-statement", serialized)
        self.assertNotIn("do-not-read-me", serialized)
        self.assertNotIn("private prompt text", serialized)

    def test_main_emits_safe_detection_json(self):
        with tempfile.TemporaryDirectory(prefix="alice-private-") as tmpdir:
            root = Path(tmpdir)
            (root / "passport-scan.pdf").write_text("secret passport body", encoding="utf-8")
            stdout = io.StringIO()

            exit_code = agent_pack.main(
                ["--json", "--detect", str(root)],
                stdout=stdout,
            )

        output = json.loads(stdout.getvalue())
        serialized = json.dumps(output)

        self.assertEqual(exit_code, 0)
        self.assertEqual(output["summary"]["high_risk_file_count"], 1)
        self.assertIn("schema_candidates", output)
        self.assertNotIn("passport-scan", serialized)
        self.assertNotIn("secret passport body", serialized)


if __name__ == "__main__":
    unittest.main()
