import importlib.util
import io
import json
import sys
import unittest
from pathlib import Path


MODULE_DIR = Path(__file__).resolve().parents[1] / "mcp_vector_store"
sys.path.insert(0, str(MODULE_DIR))

AGENT_SCHEMA_PATH = MODULE_DIR / "agent_schema.py"
SPEC = importlib.util.spec_from_file_location("agent_schema", AGENT_SCHEMA_PATH)
agent_schema = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(agent_schema)


class AgentSchemaTest(unittest.TestCase):
    def test_build_agent_schema_exports_ai_tool_contract(self):
        schema = agent_schema.build_agent_schema(
            base_url="https://mindsage.example.com/",
            server_name="team-memory",
        )

        self.assertEqual(schema["schema_version"], 1)
        self.assertEqual(schema["product"], "MindSage")
        self.assertEqual(schema["mcp"]["server_name"], "team-memory")
        self.assertEqual(schema["mcp"]["sse_url"], "https://mindsage.example.com/sse")
        self.assertEqual(schema["mcp"]["auth"]["env"], "MCP_VECTOR_STORE_API_KEY")
        self.assertIn("bearer", schema["mcp"]["auth"]["scheme"])
        self.assertIn("codex", schema["cli"]["supported_clients"])
        self.assertIn("gemini-cli", schema["cli"]["supported_clients"])
        self.assertIn("vscode", schema["cli"]["supported_clients"])

        tool_names = {tool["name"] for tool in schema["mcp"]["tools"]}
        self.assertIn("think", tool_names)
        self.assertIn("enhanced_search", tool_names)
        self.assertIn("write_memory", tool_names)
        self.assertIn("memory_graph", tool_names)

        command_names = {command["name"] for command in schema["cli"]["commands"]}
        commands = {command["name"]: command for command in schema["cli"]["commands"]}
        self.assertIn("agent:setup", command_names)
        self.assertIn("agent:think", command_names)
        self.assertIn("agent:search", command_names)
        self.assertIn("agent:schema", command_names)
        self.assertIn("agent:health", command_names)
        self.assertIn("agent:pack", command_names)
        self.assertIn("benchmark:agents", command_names)
        self.assertIn("maintenance:plan", command_names)
        self.assertIn("maintenance:apply", command_names)
        self.assertIn("--detect", commands["agent:pack"]["example"])
        self.assertIn("--json", commands["maintenance:apply"]["example"])
        self.assertTrue(commands["maintenance:apply"]["ledger_supported"])
        self.assertTrue(commands["agent:capture"]["dry_run_supported"])
        self.assertTrue(commands["agent:import"]["dry_run_supported"])

        endpoints = {endpoint["path"] for endpoint in schema["rest"]["endpoints"]}
        self.assertIn("/api/think", endpoints)
        self.assertIn("/api/search/enhanced", endpoints)
        self.assertIn("/api/documents/batch", endpoints)
        self.assertIn("/api/memory", endpoints)

        self.assertIn("decision", schema["memory"]["kinds"])
        self.assertIn("accepted", schema["memory"]["lifecycle_states"])
        self.assertIn("llm", schema["safety"]["default_context"])
        self.assertNotIn("YOUR_32_PLUS_CHARACTER_TOKEN", json.dumps(schema))

    def test_section_filter_returns_one_contract_section(self):
        schema = agent_schema.build_agent_schema(section="cli")

        self.assertEqual(set(schema), {"schema_version", "product", "generated_for", "cli"})
        self.assertIn("commands", schema["cli"])

    def test_format_schema_report_is_stable_and_compact(self):
        report = agent_schema.format_schema_report(agent_schema.build_agent_schema())

        self.assertIn("MindSage agent schema: version 1", report)
        self.assertIn("MCP tools:", report)
        self.assertIn("REST endpoints:", report)
        self.assertIn("CLI commands:", report)
        self.assertIn("Preferred answer path: think", report)
        self.assertNotIn("MCP_VECTOR_STORE_API_KEY=", report)

    def test_main_can_emit_filtered_json(self):
        stdout = io.StringIO()

        exit_code = agent_schema.main(
            ["--json", "--section", "rest", "--base-url", "http://localhost:8085/"],
            stdout=stdout,
        )

        self.assertEqual(exit_code, 0)
        output = json.loads(stdout.getvalue())
        self.assertEqual(output["rest"]["base_url"], "http://localhost:8085")
        self.assertIn("/api/search/enhanced", {endpoint["path"] for endpoint in output["rest"]["endpoints"]})
        self.assertNotIn("mcp", output)

    def test_invalid_base_url_is_rejected(self):
        with self.assertRaises(ValueError):
            agent_schema.build_agent_schema(base_url="localhost:8085")


if __name__ == "__main__":
    unittest.main()
