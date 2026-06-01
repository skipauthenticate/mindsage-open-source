import importlib.util
import json
import sys
import unittest
from pathlib import Path


MODULE_DIR = Path(__file__).resolve().parents[1] / "mcp_vector_store"
sys.path.insert(0, str(MODULE_DIR))

ENTITY_GRAPH_PATH = MODULE_DIR / "entity_graph.py"
SPEC = importlib.util.spec_from_file_location("entity_graph", ENTITY_GRAPH_PATH)
entity_graph = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(entity_graph)

build_entity_graph = entity_graph.build_entity_graph


class EntityGraphTest(unittest.TestCase):
    def test_build_entity_graph_links_safe_entities_and_redacts_people(self):
        graph = build_entity_graph(
            "What does the Jetson note say about NVIDIA in San Jose?",
            [
                {
                    "doc_id": 44,
                    "title": "Jetson launch notes",
                    "excerpt": "NVIDIA announced Jetson Orin in San Jose. [PERSON] led the keynote.",
                    "score": 0.91,
                    "metadata": {
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
        )

        node_ids = {node["id"] for node in graph["nodes"]}
        edge_ids = {edge["id"] for edge in graph["edges"]}
        serialized = json.dumps(graph)

        self.assertTrue(graph["found"])
        self.assertIn("entity:organization:nvidia", node_ids)
        self.assertIn("entity:location:san-jose", node_ids)
        self.assertIn("entity:technology:jetson-orin", node_ids)
        self.assertIn("citation:44->entity:organization:nvidia:mentions_entity", edge_ids)
        self.assertIn("entity:organization:nvidia->entity:location:san-jose:co_occurs", edge_ids)
        self.assertNotIn("Jensen Huang", serialized)
        self.assertNotIn("must-not-leak", serialized)
        self.assertFalse(graph["privacy"]["person_entities_exposed"])
        self.assertFalse(graph["privacy"]["pii_session_ids_exposed"])
        self.assertEqual(graph["privacy"]["redacted_person_entity_count"], 1)

    def test_build_entity_graph_rejects_high_risk_identifiers(self):
        graph = build_entity_graph(
            "Which entities are safe?",
            [
                {
                    "doc_id": 50,
                    "title": "Unsafe identifiers",
                    "excerpt": "Contact alice@example.com or account 4521-8834-9912.",
                    "metadata": {
                        "structured_metadata": {
                            "organizations": ["alice@example.com", "Acme Bank"],
                            "locations": ["4521-8834-9912"],
                            "technologies": ["MCP"],
                        }
                    },
                }
            ],
        )

        serialized = json.dumps(graph)

        self.assertIn("Acme Bank", serialized)
        self.assertIn("MCP", serialized)
        self.assertNotIn("alice@example.com", serialized)
        self.assertNotIn("4521-8834-9912", serialized)


if __name__ == "__main__":
    unittest.main()
