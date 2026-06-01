import importlib.util
import json
import sys
import unittest
from pathlib import Path


MODULE_DIR = Path(__file__).resolve().parents[1] / "mcp_vector_store"
sys.path.insert(0, str(MODULE_DIR))

AGENT_SETUP_PATH = MODULE_DIR / "agent_setup.py"
SPEC = importlib.util.spec_from_file_location("agent_setup", AGENT_SETUP_PATH)
agent_setup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(agent_setup)


class AgentSetupTest(unittest.TestCase):
    def test_claude_code_local_setup_prints_one_command(self):
        output = agent_setup.generate_setup("claude-code", mode="local")

        self.assertEqual(
            output,
            "claude mcp add mindsage-search --transport sse-only http://localhost:8085/sse",
        )

    def test_json_clients_get_local_mcp_remote_config(self):
        output = agent_setup.generate_setup("cursor", mode="local")
        config = json.loads(output)

        server = config["mcpServers"]["mindsage-search"]
        self.assertEqual(server["command"], "npx")
        self.assertEqual(
            server["args"],
            [
                "-y",
                "mcp-remote",
                "http://localhost:8085/sse",
                "--transport",
                "sse-only",
                "--allow-http",
            ],
        )

    def test_mcp_json_aliases_get_local_config(self):
        for client in ["gemini-cli", "vscode", "zed"]:
            with self.subTest(client=client):
                output = agent_setup.generate_setup(client, mode="local")
                config = json.loads(output)
                server = config["mcpServers"]["mindsage-search"]

                self.assertEqual(server["command"], "npx")
                self.assertIn("mcp-remote", server["args"])
                self.assertIn("http://localhost:8085/sse", server["args"])

    def test_codex_setup_prints_config_toml(self):
        output = agent_setup.generate_setup(
            "codex",
            mode="remote",
            server_name="mindsage-remote",
            base_url="https://mindsage.example.com",
        )

        self.assertIn('[mcp_servers."mindsage-remote"]', output)
        self.assertIn('command = "python3"', output)
        self.assertIn('args = [', output)
        self.assertIn('"mindsage/vector-store/mcp_vector_store/mcp_server_stdio.py"', output)
        self.assertIn('"--url"', output)
        self.assertIn('"https://mindsage.example.com"', output)
        self.assertIn('[mcp_servers."mindsage-remote".env]', output)
        self.assertIn('MCP_VECTOR_STORE_API_KEY = "${MCP_VECTOR_STORE_API_KEY}"', output)
        self.assertNotIn("YOUR_32_PLUS_CHARACTER_TOKEN", output)

    def test_remote_json_config_uses_stdio_bridge_and_env_placeholder(self):
        output = agent_setup.generate_setup(
            "claude-desktop",
            mode="remote",
            server_name="mindsage-remote",
            base_url="https://mindsage.example.com",
        )
        config = json.loads(output)

        server = config["mcpServers"]["mindsage-remote"]
        self.assertEqual(server["command"], "python3")
        self.assertIn("mindsage/vector-store/mcp_vector_store/mcp_server_stdio.py", server["args"])
        self.assertIn("--url", server["args"])
        self.assertIn("https://mindsage.example.com", server["args"])
        self.assertEqual(server["env"], {"MCP_VECTOR_STORE_API_KEY": "${MCP_VECTOR_STORE_API_KEY}"})
        self.assertNotIn("YOUR_32_PLUS_CHARACTER_TOKEN", output)

    def test_doctor_reports_health_and_sse_without_network_dependency(self):
        seen_urls = []

        def fake_urlopen(request, timeout):
            seen_urls.append(request.full_url)
            return FakeResponse(200, b'{"ok": true}')

        report = agent_setup.run_doctor("http://localhost:8085", urlopen=fake_urlopen)

        self.assertEqual(
            [check["id"] for check in report["checks"]],
            ["health", "mcp_sse"],
        )
        self.assertTrue(all(check["passed"] for check in report["checks"]))
        self.assertEqual(
            seen_urls,
            ["http://localhost:8085/health", "http://localhost:8085/sse"],
        )

    def test_unsupported_client_names_are_rejected(self):
        with self.assertRaises(ValueError):
            agent_setup.generate_setup("unknown-tool")


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
