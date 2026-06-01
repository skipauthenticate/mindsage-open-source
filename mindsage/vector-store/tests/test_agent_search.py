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

AGENT_SEARCH_PATH = MODULE_DIR / "agent_search.py"
SPEC = importlib.util.spec_from_file_location("agent_search", AGENT_SEARCH_PATH)
agent_search = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(agent_search)


class AgentSearchTest(unittest.TestCase):
    def test_build_search_request_targets_enhanced_search_endpoint(self):
        request = agent_search.build_search_request(
            "remote MCP auth",
            top_k=4,
            min_score=0.25,
            extract_passages=True,
            max_excerpt_length=300,
            context="llm",
        )

        self.assertEqual(request["endpoint"], "/api/search/enhanced")
        self.assertEqual(
            request["payload"],
            {
                "query": "remote MCP auth",
                "top_k": 4,
                "min_score": 0.25,
                "extract_passages": True,
                "max_excerpt_length": 300,
                "context": "llm",
            },
        )

    def test_read_query_supports_args_stdin_and_file(self):
        self.assertEqual(
            agent_search.read_query(["remote", "auth"], stdin=io.StringIO("ignored")),
            "remote auth",
        )
        self.assertEqual(
            agent_search.read_query([], stdin=io.StringIO("from stdin\n")),
            "from stdin",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "query.txt"
            path.write_text("from file\n", encoding="utf-8")
            self.assertEqual(agent_search.read_query([], file_path=str(path)), "from file")

        with self.assertRaises(ValueError):
            agent_search.read_query([], stdin=io.StringIO("   "))

    def test_send_search_posts_json_with_bearer_auth(self):
        seen = {}

        def fake_urlopen(request, timeout):
            seen["url"] = request.full_url
            seen["headers"] = dict(request.header_items())
            seen["body"] = json.loads(request.data.decode("utf-8"))
            return FakeResponse(
                200,
                json.dumps(
                    {
                        "results": [
                            {
                                "id": 7,
                                "excerpt": "Bearer auth is required for remote MCP.",
                                "score": 0.91,
                                "excerpt_method": "passage",
                                "primary_topic": "remote mcp",
                                "metadata": {"title": "Remote MCP policy", "filename": "policy.md"},
                            }
                        ]
                    }
                ).encode("utf-8"),
            )

        response = agent_search.send_search(
            {"endpoint": "/api/search/enhanced", "payload": {"query": "remote auth?", "top_k": 3}},
            base_url="https://mindsage.example.com/",
            api_key="ms_" + "j" * 30,
            urlopen=fake_urlopen,
        )

        self.assertEqual(response["status_code"], 200)
        self.assertEqual(seen["url"], "https://mindsage.example.com/api/search/enhanced")
        self.assertEqual(seen["headers"]["Content-type"], "application/json")
        self.assertEqual(seen["headers"]["Authorization"], "Bearer " + "ms_" + "j" * 30)
        self.assertEqual(seen["body"]["query"], "remote auth?")
        report = agent_search.format_search_report(response)
        self.assertIn("MindSage search: 1 result", report)
        self.assertIn("- Remote MCP policy (#7, score 0.91)", report)
        self.assertIn("Bearer auth is required for remote MCP.", report)
        self.assertNotIn("ms_" + "j" * 30, report)

    def test_send_search_returns_failure_for_http_error_without_leaking_request(self):
        def fake_urlopen(request, timeout):
            raise error.HTTPError(
                request.full_url,
                403,
                "Forbidden",
                {},
                io.BytesIO(b'{"error": "invalid_bearer_token"}'),
            )

        response = agent_search.send_search(
            {
                "endpoint": "/api/search/enhanced",
                "payload": {"query": "private search phrase"},
            },
            base_url="https://mindsage.example.com/",
            api_key="ms_" + "k" * 30,
            urlopen=fake_urlopen,
        )

        self.assertEqual(response["status_code"], 403)
        self.assertFalse(response["ok"])
        report = agent_search.format_search_report(response)
        self.assertEqual(report, "MindSage search: failed (403)")
        self.assertNotIn("private search phrase", report)
        self.assertNotIn("ms_" + "k" * 30, report)

    def test_main_can_emit_json(self):
        seen = {}
        stdout = io.StringIO()

        def fake_urlopen(request, timeout):
            seen["url"] = request.full_url
            seen["body"] = json.loads(request.data.decode("utf-8"))
            return FakeResponse(200, b'{"results": []}')

        exit_code = agent_search.main(
            [
                "--top-k",
                "3",
                "--base-url",
                "http://localhost:8085",
                "--json",
                "remote auth",
            ],
            urlopen=fake_urlopen,
            stdout=stdout,
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(seen["url"], "http://localhost:8085/api/search/enhanced")
        self.assertEqual(seen["body"]["query"], "remote auth")
        self.assertEqual(seen["body"]["top_k"], 3)
        self.assertEqual(json.loads(stdout.getvalue())["body"]["results"], [])


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
