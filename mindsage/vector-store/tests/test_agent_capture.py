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

AGENT_CAPTURE_PATH = MODULE_DIR / "agent_capture.py"
SPEC = importlib.util.spec_from_file_location("agent_capture", AGENT_CAPTURE_PATH)
agent_capture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(agent_capture)


class AgentCaptureTest(unittest.TestCase):
    def test_build_document_capture_request_targets_documents_endpoint(self):
        request = agent_capture.build_capture_request(
            "Remember the local-first release note.",
            mode="document",
            metadata={"source": "manual", "pii_session_id": "must-not-leak"},
        )

        self.assertEqual(request["endpoint"], "/api/documents")
        self.assertEqual(request["payload"]["text"], "Remember the local-first release note.")
        self.assertEqual(request["payload"]["metadata"]["source"], "manual")
        self.assertEqual(request["payload"]["metadata"]["capture_tool"], "mindsage-agent-capture")
        self.assertNotIn("pii_session_id", request["payload"]["metadata"])

    def test_build_memory_capture_request_targets_typed_memory_endpoint(self):
        request = agent_capture.build_capture_request(
            "Use authenticated private tunnels for remote MCP.",
            mode="memory",
            kind="decision",
            workspace="ops",
            actor="codex",
            memory_key="decision:remote-mcp",
            state="accepted",
            reason="ADR-003",
            ttl_days=30,
        )

        self.assertEqual(request["endpoint"], "/api/memory")
        self.assertEqual(
            request["payload"],
            {
                "kind": "decision",
                "content": "Use authenticated private tunnels for remote MCP.",
                "workspace": "ops",
                "actor": "codex",
                "memory_key": "decision:remote-mcp",
                "state": "accepted",
                "source_document_id": None,
                "relations": None,
                "ttl_days": 30,
                "metadata": {"capture_tool": "mindsage-agent-capture"},
                "reason": "ADR-003",
            },
        )

    def test_read_capture_text_supports_args_stdin_and_file(self):
        self.assertEqual(
            agent_capture.read_capture_text(["one", "two"], stdin=io.StringIO("ignored")),
            "one two",
        )
        self.assertEqual(
            agent_capture.read_capture_text([], stdin=io.StringIO("from stdin\n")),
            "from stdin",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "note.txt"
            path.write_text("from file\n", encoding="utf-8")
            self.assertEqual(agent_capture.read_capture_text([], file_path=str(path)), "from file")

        with self.assertRaises(ValueError):
            agent_capture.read_capture_text([], stdin=io.StringIO("   "))

    def test_send_capture_posts_json_with_bearer_auth_without_leaking_token(self):
        seen = {}

        def fake_urlopen(request, timeout):
            seen["url"] = request.full_url
            seen["headers"] = dict(request.header_items())
            seen["body"] = json.loads(request.data.decode("utf-8"))
            return FakeResponse(201, b'{"success": true, "document_id": 42}')

        response = agent_capture.send_capture(
            {
                "endpoint": "/api/documents",
                "payload": {"text": "secret note", "metadata": {}},
            },
            base_url="https://mindsage.example.com/",
            api_key="ms_" + "a" * 30,
            urlopen=fake_urlopen,
        )

        self.assertEqual(response["status_code"], 201)
        self.assertEqual(seen["url"], "https://mindsage.example.com/api/documents")
        self.assertEqual(seen["headers"]["Content-type"], "application/json")
        self.assertEqual(seen["headers"]["Authorization"], "Bearer " + "ms_" + "a" * 30)
        self.assertEqual(seen["body"]["text"], "secret note")
        report = agent_capture.format_capture_report(response, request_type="document")
        self.assertIn("MindSage capture: stored document 42", report)
        self.assertNotIn("secret note", report)
        self.assertNotIn("ms_" + "a" * 30, report)

    def test_send_capture_returns_failure_for_http_error_without_leaking_content(self):
        seen = {}

        def fake_urlopen(request, timeout):
            seen["url"] = request.full_url
            seen["headers"] = dict(request.header_items())
            raise error.HTTPError(
                request.full_url,
                403,
                "Forbidden",
                {},
                io.BytesIO(b'{"success": false, "error": "forbidden"}'),
            )

        response = agent_capture.send_capture(
            {
                "endpoint": "/api/documents",
                "payload": {"text": "do not print this", "metadata": {}},
            },
            base_url="https://mindsage.example.com/",
            api_key="ms_" + "b" * 30,
            urlopen=fake_urlopen,
        )

        self.assertEqual(response["status_code"], 403)
        self.assertFalse(response["ok"])
        self.assertEqual(response["body"]["error"], "forbidden")
        report = agent_capture.format_capture_report(response, request_type="document")
        self.assertEqual(report, "MindSage capture: failed (403)")
        self.assertNotIn("do not print this", report)
        self.assertNotIn("ms_" + "b" * 30, report)

    def test_main_can_emit_json_for_memory_capture(self):
        seen = {}

        def fake_urlopen(request, timeout):
            seen["url"] = request.full_url
            seen["body"] = json.loads(request.data.decode("utf-8"))
            return FakeResponse(201, b'{"success": true, "memory": {"memory_key": "decision:remote-mcp"}}')

        exit_code = agent_capture.main(
            [
                "--mode",
                "memory",
                "--kind",
                "decision",
                "--workspace",
                "ops",
                "--memory-key",
                "decision:remote-mcp",
                "--base-url",
                "http://localhost:8085",
                "--json",
                "Use remote bearer auth.",
            ],
            urlopen=fake_urlopen,
            stdout=io.StringIO(),
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(seen["url"], "http://localhost:8085/api/memory")
        self.assertEqual(seen["body"]["kind"], "decision")
        self.assertEqual(seen["body"]["workspace"], "ops")
        self.assertEqual(seen["body"]["memory_key"], "decision:remote-mcp")

    def test_main_dry_run_does_not_post_or_echo_capture_text(self):
        stdout = io.StringIO()

        def forbidden_urlopen(request, timeout):
            raise AssertionError("dry run must not call urlopen")

        exit_code = agent_capture.main(
            [
                "--mode",
                "memory",
                "--kind",
                "decision",
                "--workspace",
                "ops",
                "--memory-key",
                "decision:remote-mcp",
                "--dry-run",
                "--json",
                "private launch decision",
            ],
            urlopen=forbidden_urlopen,
            stdout=stdout,
        )

        output = json.loads(stdout.getvalue())
        serialized = json.dumps(output)
        self.assertEqual(exit_code, 0)
        self.assertTrue(output["dry_run"])
        self.assertEqual(output["endpoint"], "/api/memory")
        self.assertEqual(output["type"], "memory")
        self.assertEqual(output["payload_summary"]["kind"], "decision")
        self.assertEqual(output["payload_summary"]["memory_key"], "decision:remote-mcp")
        self.assertGreater(output["payload_summary"]["content_bytes"], 0)
        self.assertNotIn("private launch decision", serialized)

    def test_format_capture_dry_run_report_is_compact(self):
        preview = agent_capture.build_capture_dry_run(
            agent_capture.build_capture_request(
                "do not print this",
                mode="document",
                metadata={"source": "test", "pii_session_id": "must-not-leak"},
            )
        )

        report = agent_capture.format_capture_report(preview, request_type="document")

        self.assertEqual(report, "MindSage capture dry run: would store document (17 bytes)")
        self.assertNotIn("do not print this", json.dumps(preview))
        self.assertNotIn("must-not-leak", json.dumps(preview))


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
