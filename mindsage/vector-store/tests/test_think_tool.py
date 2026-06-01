import datetime as dt
import importlib.util
import json
from pathlib import Path
import unittest


THINK_TOOL_PATH = Path(__file__).resolve().parents[1] / "mcp_vector_store" / "think_tool.py"
SPEC = importlib.util.spec_from_file_location("think_tool", THINK_TOOL_PATH)
think_tool = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(think_tool)
build_think_response = think_tool.build_think_response


class ThinkToolTests(unittest.TestCase):
    def test_empty_results_return_no_answer_and_evidence_gap(self):
        response = build_think_response(
            question="What did I decide about the vector store?",
            results=[],
            reference_date=dt.date(2026, 6, 1),
        )

        self.assertIsNone(response["answer_brief"])
        self.assertEqual(response["citations"], [])
        self.assertIn("No supporting sources were found.", response["gaps"])
        self.assertEqual(response["coverage"]["source_count"], 0)
        self.assertEqual(response["privacy"]["llm_context"], "redacted")
        self.assertFalse(response["privacy"]["pii_session_ids_exposed"])

    def test_citations_strip_pii_session_ids(self):
        response = build_think_response(
            question="What was decided about local search?",
            results=[
                {
                    "id": 7,
                    "excerpt": "Local search should use redacted snippets for agent tools.",
                    "score": 0.91,
                    "metadata": {
                        "filename": "search-design.md",
                        "source": "notes",
                        "date": "2026-05-15",
                        "pii_session_id": "session-secret",
                    },
                    "pii_session_id": "top-level-secret",
                }
            ],
            reference_date=dt.date(2026, 6, 1),
        )

        self.assertEqual(response["citations"][0]["doc_id"], 7)
        self.assertEqual(response["citations"][0]["title"], "search-design.md")
        serialized = json.dumps(response)
        self.assertNotIn("session-secret", serialized)
        self.assertNotIn("top-level-secret", serialized)
        self.assertFalse(response["privacy"]["pii_session_ids_exposed"])

    def test_coverage_reports_found_and_missing_query_terms(self):
        response = build_think_response(
            question="vector store decision",
            results=[
                {
                    "id": 1,
                    "excerpt": "The vector store uses local embeddings and redacted MCP output.",
                    "score": 0.8,
                    "metadata": {"date": "2026-05-20"},
                }
            ],
            reference_date=dt.date(2026, 6, 1),
        )

        self.assertIn("vector", response["coverage"]["query_terms_found"])
        self.assertIn("store", response["coverage"]["query_terms_found"])
        self.assertIn("decision", response["coverage"]["query_terms_missing"])
        self.assertTrue(any("decision" in gap for gap in response["gaps"]))

    def test_freshness_marks_stale_and_undated_sources(self):
        response = build_think_response(
            question="What is the release status?",
            results=[
                {
                    "id": 1,
                    "excerpt": "The release was prepared in January.",
                    "score": 0.7,
                    "metadata": {"date": "2026-01-01"},
                },
                {
                    "id": 2,
                    "excerpt": "A later note has no explicit date.",
                    "score": 0.6,
                    "metadata": {},
                },
            ],
            freshness_days=90,
            reference_date=dt.date(2026, 6, 1),
        )

        self.assertEqual(response["freshness"]["stale_source_count"], 1)
        self.assertEqual(response["freshness"]["undated_source_count"], 1)
        self.assertIn("1 source is older than 90 days", response["freshness"]["warnings"])
        self.assertIn("1 source has no date metadata", response["freshness"]["warnings"])

    def test_think_response_includes_actionable_citation_maintenance(self):
        response = build_think_response(
            question="Should remote MCP access be enabled?",
            results=[
                {
                    "id": 1,
                    "excerpt": "Remote MCP access should be enabled for demo environments.",
                    "score": 0.66,
                    "topics": ["remote MCP"],
                    "metadata": {
                        "title": "Old remote MCP policy",
                        "date": "2026-01-01",
                        "pii_session_id": "must-not-leak",
                    },
                },
                {
                    "id": 2,
                    "excerpt": "Remote MCP access requires bearer authentication.",
                    "score": 0.72,
                    "topics": ["remote MCP"],
                    "metadata": {"title": "Undated remote MCP note"},
                },
                {
                    "id": 3,
                    "excerpt": "Remote MCP access should be disabled without bearer authentication.",
                    "score": 0.85,
                    "topics": ["remote MCP"],
                    "metadata": {
                        "title": "Remote MCP safety update",
                        "date": "2026-05-31",
                    },
                },
            ],
            freshness_days=30,
            reference_date=dt.date(2026, 6, 1),
        )

        maintenance = response["maintenance"]
        action_types = {action["type"] for action in maintenance["actions"]}
        serialized = json.dumps(maintenance)

        self.assertTrue(maintenance["found"])
        self.assertIn("refresh_stale_citation", action_types)
        self.assertIn("add_source_date", action_types)
        self.assertIn("resolve_contradiction", action_types)
        self.assertIn("Should remote MCP access be enabled?", serialized)
        self.assertNotIn("must-not-leak", serialized)
        self.assertFalse(maintenance["privacy"]["pii_session_ids_exposed"])
        self.assertGreaterEqual(maintenance["maintenance_graph"]["edge_count"], 3)

    def test_simple_positive_negative_conflict_becomes_contradiction(self):
        response = build_think_response(
            question="Should remote access be enabled?",
            results=[
                {
                    "id": 1,
                    "excerpt": "We should enable remote access for controlled MCP deployments.",
                    "score": 0.78,
                    "metadata": {"date": "2026-05-01"},
                },
                {
                    "id": 2,
                    "excerpt": "We should disable remote access by default for personal data safety.",
                    "score": 0.81,
                    "metadata": {"date": "2026-05-02"},
                },
            ],
            reference_date=dt.date(2026, 6, 1),
        )

        self.assertGreaterEqual(len(response["contradictions"]), 1)
        self.assertIn("remote access", response["contradictions"][0]["topic"])

    def test_cited_answer_graph_links_answer_citations_concepts_and_contradictions(self):
        response = build_think_response(
            question="Should remote access be enabled for MCP?",
            results=[
                {
                    "id": 1,
                    "excerpt": "We should enable remote access for authenticated MCP deployments.",
                    "score": 0.89,
                    "topics": ["remote access", "mcp"],
                    "metadata": {
                        "title": "Remote MCP decision",
                        "date": "2026-05-01",
                    },
                },
                {
                    "id": 2,
                    "excerpt": "We should disable remote access unless the MCP endpoint is private.",
                    "score": 0.84,
                    "primary_topic": "private endpoint",
                    "metadata": {
                        "title": "Private endpoint policy",
                        "date": "2026-05-02",
                    },
                },
            ],
            reference_date=dt.date(2026, 6, 1),
        )

        graph = response["citation_graph"]
        node_ids = {node["id"] for node in graph["nodes"]}
        edge_ids = {edge["id"] for edge in graph["edges"]}

        self.assertTrue(graph["found"])
        self.assertIn(graph["answer_node_id"], node_ids)
        self.assertIn("citation:1", node_ids)
        self.assertIn("citation:2", node_ids)
        self.assertIn("concept:remote-access", node_ids)
        self.assertIn("concept:mcp", node_ids)
        self.assertIn(f"{graph['answer_node_id']}->citation:1:cites", edge_ids)
        self.assertIn("citation:1->concept:remote-access:mentions", edge_ids)
        self.assertIn("citation:1->concept:mcp:mentions", edge_ids)
        self.assertIn("citation:1->citation:2:contradicts", edge_ids)

    def test_think_response_includes_pii_safe_entity_graph(self):
        response = build_think_response(
            question="What did NVIDIA announce in San Jose?",
            results=[
                {
                    "id": 77,
                    "excerpt": "NVIDIA announced Jetson Orin in San Jose during the keynote by [PERSON].",
                    "score": 0.93,
                    "metadata": {
                        "title": "Jetson launch notes",
                        "structured_metadata": {
                            "persons": ["Jensen Huang"],
                            "organizations": ["NVIDIA"],
                            "locations": ["San Jose"],
                            "technologies": ["Jetson Orin"],
                        },
                        "pii_session_id": "must-not-leak",
                    },
                }
            ],
            reference_date=dt.date(2026, 6, 1),
        )

        entity_graph = response["entity_graph"]
        node_ids = {node["id"] for node in entity_graph["nodes"]}
        edge_ids = {edge["id"] for edge in entity_graph["edges"]}
        serialized = json.dumps(response)

        self.assertTrue(entity_graph["found"])
        self.assertIn("entity:organization:nvidia", node_ids)
        self.assertIn("entity:location:san-jose", node_ids)
        self.assertIn("entity:technology:jetson-orin", node_ids)
        self.assertIn("citation:77->entity:organization:nvidia:mentions_entity", edge_ids)
        self.assertIn("entity:organization:nvidia->entity:location:san-jose:co_occurs", edge_ids)
        self.assertNotIn("Jensen Huang", serialized)
        self.assertNotIn("must-not-leak", serialized)
        self.assertFalse(entity_graph["privacy"]["person_entities_exposed"])

    def test_cited_answer_graph_omits_pii_session_identifiers(self):
        response = build_think_response(
            question="What did we decide about private indexing?",
            results=[
                {
                    "id": 9,
                    "excerpt": "Private indexing should keep agent context redacted.",
                    "score": 0.91,
                    "topics": ["private indexing"],
                    "metadata": {
                        "title": "Private indexing policy",
                        "pii_session_id": "secret-session",
                        "nested": {"piiSessionId": "secret-session-2"},
                    },
                }
            ],
            reference_date=dt.date(2026, 6, 1),
        )

        serialized = json.dumps(response["citation_graph"])
        self.assertNotIn("secret-session", serialized)
        self.assertNotIn("secret-session-2", serialized)
        self.assertFalse(response["privacy"]["pii_session_ids_exposed"])


if __name__ == "__main__":
    unittest.main()
