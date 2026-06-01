import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from urllib import error


MODULE_DIR = Path(__file__).resolve().parents[1] / "mcp_vector_store"
sys.path.insert(0, str(MODULE_DIR))

AGENT_IMPORT_PATH = MODULE_DIR / "agent_import.py"
SPEC = importlib.util.spec_from_file_location("agent_import", AGENT_IMPORT_PATH)
agent_import = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(agent_import)


class AgentImportTest(unittest.TestCase):
    def test_collect_import_documents_reads_text_files_with_safe_metadata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "notes").mkdir()
            (root / "notes" / "plan.md").write_text("# Launch plan\nShip safely.\n", encoding="utf-8")
            (root / "notes" / "decision.txt").write_text("Use bearer auth.\n", encoding="utf-8")
            (root / ".hidden.md").write_text("ignored", encoding="utf-8")
            (root / "image.png").write_bytes(b"\x89PNG")

            documents = agent_import.collect_import_documents(
                [str(root)],
                metadata={"source": "manual", "pii_session_id": "must-not-leak"},
                extensions={".md", ".txt"},
            )

        self.assertEqual([doc["metadata"]["filename"] for doc in documents], ["decision.txt", "plan.md"])
        self.assertEqual([doc["text"] for doc in documents], ["Use bearer auth.", "# Launch plan\nShip safely."])
        for doc in documents:
            self.assertEqual(doc["metadata"]["source"], "manual")
            self.assertEqual(doc["metadata"]["import_tool"], "mindsage-agent-import")
            self.assertIn("relative_path", doc["metadata"])
            self.assertNotIn("pii_session_id", doc["metadata"])

    def test_build_import_request_targets_batch_endpoint(self):
        request = agent_import.build_import_request(
            [
                {"text": "One", "metadata": {"filename": "one.txt"}},
                {"text": "Two", "metadata": {"filename": "two.txt"}},
            ],
            skip_duplicates=True,
            extract_key_passages=False,
        )

        self.assertEqual(request["endpoint"], "/api/documents/batch")
        self.assertEqual(request["payload"]["documents"][0]["text"], "One")
        self.assertTrue(request["payload"]["skip_duplicates"])
        self.assertFalse(request["payload"]["extract_key_passages"])

    def test_send_import_posts_json_with_bearer_auth_without_leaking_text(self):
        seen = {}

        def fake_urlopen(request, timeout):
            seen["url"] = request.full_url
            seen["headers"] = dict(request.header_items())
            seen["body"] = json.loads(request.data.decode("utf-8"))
            return FakeResponse(
                200,
                b'{"success": true, "count": 2, "duplicates_skipped": 1, "document_ids": [11, 12]}',
            )

        response = agent_import.send_import(
            {
                "endpoint": "/api/documents/batch",
                "payload": {
                    "documents": [{"text": "private import body", "metadata": {"filename": "note.txt"}}],
                    "skip_duplicates": True,
                    "extract_key_passages": False,
                },
            },
            base_url="https://mindsage.example.com/",
            api_key="ms_" + "e" * 30,
            urlopen=fake_urlopen,
        )

        self.assertEqual(response["status_code"], 200)
        self.assertEqual(seen["url"], "https://mindsage.example.com/api/documents/batch")
        self.assertEqual(seen["headers"]["Content-type"], "application/json")
        self.assertEqual(seen["headers"]["Authorization"], "Bearer " + "ms_" + "e" * 30)
        self.assertEqual(seen["body"]["documents"][0]["text"], "private import body")
        report = agent_import.format_import_report(response)
        self.assertEqual(report, "MindSage import: imported 2 documents, skipped 1 duplicate")
        self.assertNotIn("private import body", report)
        self.assertNotIn("ms_" + "e" * 30, report)

    def test_send_import_returns_failure_for_http_error_without_leaking_payload(self):
        def fake_urlopen(request, timeout):
            raise error.HTTPError(
                request.full_url,
                413,
                "Payload Too Large",
                {},
                io.BytesIO(b'{"success": false, "error": "payload_too_large"}'),
            )

        response = agent_import.send_import(
            {
                "endpoint": "/api/documents/batch",
                "payload": {"documents": [{"text": "private corpus", "metadata": {}}]},
            },
            base_url="https://mindsage.example.com/",
            api_key="ms_" + "f" * 30,
            urlopen=fake_urlopen,
        )

        self.assertEqual(response["status_code"], 413)
        self.assertFalse(response["ok"])
        report = agent_import.format_import_report(response)
        self.assertEqual(report, "MindSage import: failed (413)")
        self.assertNotIn("private corpus", report)
        self.assertNotIn("ms_" + "f" * 30, report)

    def test_main_can_emit_json_for_directory_import(self):
        seen = {}
        stdout = io.StringIO()

        def fake_urlopen(request, timeout):
            seen["url"] = request.full_url
            seen["body"] = json.loads(request.data.decode("utf-8"))
            return FakeResponse(200, b'{"success": true, "count": 1, "duplicates_skipped": 0}')

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "note.md"
            path.write_text("Agent import note.\n", encoding="utf-8")
            exit_code = agent_import.main(
                [
                    "--base-url",
                    "http://localhost:8085",
                    "--metadata",
                    "workspace=ops",
                    "--json",
                    str(path),
                ],
                urlopen=fake_urlopen,
                stdout=stdout,
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(seen["url"], "http://localhost:8085/api/documents/batch")
        self.assertEqual(seen["body"]["documents"][0]["text"], "Agent import note.")
        self.assertEqual(seen["body"]["documents"][0]["metadata"]["workspace"], "ops")
        self.assertEqual(json.loads(stdout.getvalue())["body"]["count"], 1)

    def test_main_dry_run_does_not_post_or_echo_imported_text(self):
        stdout = io.StringIO()

        def forbidden_urlopen(request, timeout):
            raise AssertionError("dry run must not call urlopen")

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "private.md"
            path.write_text("private import body\n", encoding="utf-8")
            exit_code = agent_import.main(
                [
                    "--dry-run",
                    "--json",
                    "--metadata",
                    "workspace=ops",
                    str(path),
                ],
                urlopen=forbidden_urlopen,
                stdout=stdout,
            )

        output = json.loads(stdout.getvalue())
        serialized = json.dumps(output)
        self.assertEqual(exit_code, 0)
        self.assertTrue(output["dry_run"])
        self.assertEqual(output["endpoint"], "/api/documents/batch")
        self.assertEqual(output["payload_summary"]["document_count"], 1)
        self.assertEqual(output["payload_summary"]["filenames"], ["private.md"])
        self.assertGreater(output["payload_summary"]["total_text_bytes"], 0)
        self.assertNotIn("private import body", serialized)

    def test_format_import_dry_run_report_is_compact(self):
        preview = agent_import.build_import_dry_run(
            agent_import.build_import_request(
                [{"text": "private import body", "metadata": {"filename": "private.md"}}]
            )
        )

        report = agent_import.format_import_report(preview)

        self.assertEqual(report, "MindSage import dry run: would import 1 document (19 bytes)")
        self.assertNotIn("private import body", json.dumps(preview))


class FakeResponse:
    def __init__(self, status, body):
        self.status = status
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self._body


if __name__ == "__main__":
    unittest.main()
