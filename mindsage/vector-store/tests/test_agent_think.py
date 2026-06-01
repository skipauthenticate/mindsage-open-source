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

AGENT_THINK_PATH = MODULE_DIR / "agent_think.py"
SPEC = importlib.util.spec_from_file_location("agent_think", AGENT_THINK_PATH)
agent_think = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(agent_think)


class AgentThinkTest(unittest.TestCase):
    def test_build_think_request_targets_think_endpoint(self):
        request = agent_think.build_think_request(
            "What changed in the release plan?",
            top_k=6,
            min_score=0.25,
            freshness_days=45,
            include_gaps=False,
            max_excerpt_length=400,
        )

        self.assertEqual(request["endpoint"], "/api/think")
        self.assertEqual(
            request["payload"],
            {
                "question": "What changed in the release plan?",
                "top_k": 6,
                "min_score": 0.25,
                "freshness_days": 45,
                "include_gaps": False,
                "max_excerpt_length": 400,
            },
        )

    def test_read_question_supports_args_stdin_and_file(self):
        self.assertEqual(
            agent_think.read_question(["what", "changed?"], stdin=io.StringIO("ignored")),
            "what changed?",
        )
        self.assertEqual(
            agent_think.read_question([], stdin=io.StringIO("from stdin\n")),
            "from stdin",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "question.txt"
            path.write_text("from file\n", encoding="utf-8")
            self.assertEqual(agent_think.read_question([], file_path=str(path)), "from file")

        with self.assertRaises(ValueError):
            agent_think.read_question([], stdin=io.StringIO("   "))

    def test_send_think_posts_json_with_bearer_auth(self):
        seen = {}

        def fake_urlopen(request, timeout):
            seen["url"] = request.full_url
            seen["headers"] = dict(request.header_items())
            seen["body"] = json.loads(request.data.decode("utf-8"))
            return FakeResponse(
                200,
                json.dumps(
                    {
                        "answer_brief": "Remote MCP must require bearer auth.",
                        "citations": [
                            {
                                "doc_id": 7,
                                "title": "Remote MCP policy",
                                "score": 0.92,
                                "excerpt": "Bearer auth is required.",
                            }
                        ],
                        "gaps": [{"type": "missing_evidence"}],
                        "freshness": {"status": "fresh"},
                        "privacy": {"pii_session_ids_exposed": False},
                    }
                ).encode("utf-8"),
            )

        response = agent_think.send_think(
            {"endpoint": "/api/think", "payload": {"question": "remote auth?"}},
            base_url="https://mindsage.example.com/",
            api_key="ms_" + "c" * 30,
            urlopen=fake_urlopen,
        )

        self.assertEqual(response["status_code"], 200)
        self.assertEqual(seen["url"], "https://mindsage.example.com/api/think")
        self.assertEqual(seen["headers"]["Content-type"], "application/json")
        self.assertEqual(seen["headers"]["Authorization"], "Bearer " + "ms_" + "c" * 30)
        self.assertEqual(seen["body"]["question"], "remote auth?")
        report = agent_think.format_think_report(response)
        self.assertIn("MindSage think: Remote MCP must require bearer auth.", report)
        self.assertIn("Citations: 1 | Gaps: 1 | Freshness: fresh", report)
        self.assertIn("- Remote MCP policy (#7, score 0.92)", report)
        self.assertNotIn("ms_" + "c" * 30, report)

    def test_send_think_returns_failure_for_http_error_without_leaking_request(self):
        def fake_urlopen(request, timeout):
            raise error.HTTPError(
                request.full_url,
                401,
                "Unauthorized",
                {},
                io.BytesIO(b'{"error": "missing_bearer_token"}'),
            )

        response = agent_think.send_think(
            {
                "endpoint": "/api/think",
                "payload": {"question": "private roadmap question"},
            },
            base_url="https://mindsage.example.com/",
            api_key="ms_" + "d" * 30,
            urlopen=fake_urlopen,
        )

        self.assertEqual(response["status_code"], 401)
        self.assertFalse(response["ok"])
        report = agent_think.format_think_report(response)
        self.assertEqual(report, "MindSage think: failed (401)")
        self.assertNotIn("private roadmap question", report)
        self.assertNotIn("ms_" + "d" * 30, report)

    def test_main_can_emit_json(self):
        seen = {}
        stdout = io.StringIO()

        def fake_urlopen(request, timeout):
            seen["url"] = request.full_url
            seen["body"] = json.loads(request.data.decode("utf-8"))
            return FakeResponse(200, b'{"answer_brief": "Use cited evidence.", "citations": []}')

        exit_code = agent_think.main(
            [
                "--top-k",
                "3",
                "--base-url",
                "http://localhost:8085",
                "--json",
                "How should agents query memory?",
            ],
            urlopen=fake_urlopen,
            stdout=stdout,
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(seen["url"], "http://localhost:8085/api/think")
        self.assertEqual(seen["body"]["question"], "How should agents query memory?")
        self.assertEqual(seen["body"]["top_k"], 3)
        self.assertEqual(json.loads(stdout.getvalue())["body"]["answer_brief"], "Use cited evidence.")


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
