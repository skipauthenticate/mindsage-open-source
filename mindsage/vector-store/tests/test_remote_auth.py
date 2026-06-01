import importlib.util
import unittest
from pathlib import Path


REMOTE_AUTH_PATH = Path(__file__).resolve().parents[1] / "mcp_vector_store" / "remote_auth.py"
SPEC = importlib.util.spec_from_file_location("remote_auth", REMOTE_AUTH_PATH)
remote_auth = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(remote_auth)


class RemoteAuthTest(unittest.TestCase):
    def test_normalize_remote_api_key_accepts_strong_tokens_and_rejects_weak_tokens(self):
        strong = "ms_" + "a" * 30

        self.assertEqual(remote_auth.normalize_remote_api_key(f"  {strong}  "), strong)

        with self.assertRaises(ValueError):
            remote_auth.normalize_remote_api_key("short")

        with self.assertRaises(ValueError):
            remote_auth.normalize_remote_api_key("   ")

    def test_resolve_remote_api_key_prefers_explicit_then_environment(self):
        env = {
            "VECTOR_STORE_API_KEY": "ms_" + "b" * 30,
            "MCP_VECTOR_STORE_API_KEY": "ms_" + "c" * 30,
        }

        self.assertEqual(
            remote_auth.resolve_remote_api_key("ms_" + "d" * 30, env=env),
            "ms_" + "d" * 30,
        )
        self.assertEqual(
            remote_auth.resolve_remote_api_key(None, env=env),
            "ms_" + "b" * 30,
        )
        self.assertEqual(
            remote_auth.resolve_remote_api_key(None, env={"MCP_VECTOR_STORE_API_KEY": "ms_" + "c" * 30}),
            "ms_" + "c" * 30,
        )
        self.assertIsNone(remote_auth.resolve_remote_api_key(None, env={}))

    def test_authorize_bearer_header_uses_constant_time_checks_and_precise_status(self):
        expected = "ms_" + "e" * 30

        self.assertEqual(
            remote_auth.authorize_bearer_header(f"Bearer {expected}", expected),
            remote_auth.AuthDecision(True, 200, "authorized"),
        )
        self.assertEqual(
            remote_auth.authorize_bearer_header(None, expected),
            remote_auth.AuthDecision(False, 401, "missing_bearer_token"),
        )
        self.assertEqual(
            remote_auth.authorize_bearer_header("Basic abc", expected),
            remote_auth.AuthDecision(False, 401, "missing_bearer_token"),
        )
        self.assertEqual(
            remote_auth.authorize_bearer_header("Bearer wrong-token-value", expected),
            remote_auth.AuthDecision(False, 403, "invalid_bearer_token"),
        )

    def test_build_auth_headers_supports_remote_stdio_bridge_requests(self):
        token = "ms_" + "f" * 30

        self.assertEqual(
            remote_auth.build_auth_headers(token),
            {"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(remote_auth.build_auth_headers(None), {})


if __name__ == "__main__":
    unittest.main()
