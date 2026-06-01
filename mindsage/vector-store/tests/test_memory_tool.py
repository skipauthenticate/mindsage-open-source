import datetime as dt
import importlib.util
import unittest
from pathlib import Path


MEMORY_TOOL_PATH = Path(__file__).resolve().parents[1] / "mcp_vector_store" / "memory_tool.py"
SPEC = importlib.util.spec_from_file_location("memory_tool", MEMORY_TOOL_PATH)
memory_tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(memory_tool)

build_memory_record = memory_tool.build_memory_record
filter_memory_records = memory_tool.filter_memory_records
build_memory_timeline = memory_tool.build_memory_timeline
build_memory_graph = memory_tool.build_memory_graph
build_workspace_info = memory_tool.build_workspace_info
build_actor_activity = memory_tool.build_actor_activity


class MemoryToolTest(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime(2026, 6, 1, 12, 0, tzinfo=dt.timezone.utc)

    def test_build_memory_record_creates_typed_metadata_and_audit_event(self):
        record = build_memory_record(
            kind="decision",
            content="Use Redis for session caching because it supports expiry.",
            workspace="checkout-api",
            actor="codex",
            memory_key="architecture/session-cache",
            state="accepted",
            reason="ADR-001",
            reference_datetime=self.now,
        )

        metadata = record["metadata"]
        memory = metadata["memory"]
        event = metadata["memory_events"][0]

        self.assertEqual(record["text"].splitlines()[0], "Decision memory (accepted)")
        self.assertEqual(metadata["content_type"], "typed_memory")
        self.assertEqual(metadata["source"], "typed_memory:checkout-api:architecture/session-cache")
        self.assertEqual(metadata["memory_kind"], "decision")
        self.assertEqual(memory["workspace"], "checkout-api")
        self.assertEqual(memory["memory_key"], "architecture/session-cache")
        self.assertEqual(memory["version"], 1)
        self.assertEqual(memory["state"], "accepted")
        self.assertEqual(memory["value_hash"], metadata["value_hash"])
        self.assertEqual(event["event_type"], "memory.created")
        self.assertEqual(event["actor"], "codex")
        self.assertEqual(event["reason"], "ADR-001")
        self.assertEqual(event["version"], 1)

    def test_build_memory_record_increments_version_for_existing_key(self):
        first = build_memory_record(
            kind="claim",
            content="The signup flow uses email verification.",
            workspace="growth",
            actor="agent",
            memory_key="signup/email-verification",
            reference_datetime=self.now,
        )

        second = build_memory_record(
            kind="claim",
            content="The signup flow uses email verification before workspace creation.",
            workspace="growth",
            actor="agent",
            memory_key="signup/email-verification",
            existing_records=[first],
            reference_datetime=self.now + dt.timedelta(minutes=5),
        )

        self.assertEqual(second["metadata"]["memory"]["version"], 2)
        self.assertEqual(second["metadata"]["memory_events"][0]["event_type"], "memory.revised")

    def test_filter_memory_records_defaults_to_accepted_non_expired(self):
        accepted = build_memory_record(
            kind="task",
            content="Rotate the webhook signing key.",
            workspace="ops",
            actor="agent",
            memory_key="security/webhook-key",
            state="accepted",
            reference_datetime=self.now,
        )
        candidate = build_memory_record(
            kind="task",
            content="Consider replacing the webhook provider.",
            workspace="ops",
            actor="agent",
            memory_key="security/webhook-provider",
            state="candidate",
            reference_datetime=self.now,
        )
        expired = build_memory_record(
            kind="task",
            content="Temporary migration freeze.",
            workspace="ops",
            actor="agent",
            memory_key="release/freeze",
            ttl_days=1,
            reference_datetime=self.now - dt.timedelta(days=3),
        )

        docs = [
            {"id": 11, "text": accepted["text"], "score": 0.91, "metadata": accepted["metadata"]},
            {"id": 12, "text": candidate["text"], "score": 0.88, "metadata": candidate["metadata"]},
            {"id": 13, "text": expired["text"], "score": 0.77, "metadata": expired["metadata"]},
        ]

        results = filter_memory_records(
            docs,
            workspace="ops",
            kind="task",
            reference_datetime=self.now,
        )

        self.assertEqual([result["doc_id"] for result in results], [11])
        self.assertEqual(results[0]["state"], "accepted")
        self.assertFalse(results[0]["expired"])
        self.assertIn("Rotate the webhook signing key", results[0]["content_preview"])

    def test_filter_memory_records_can_include_candidate_and_expired_states(self):
        candidate = build_memory_record(
            kind="claim",
            content="Candidate hypothesis about activation.",
            workspace="growth",
            actor="agent",
            state="candidate",
            reference_datetime=self.now,
        )
        expired = build_memory_record(
            kind="claim",
            content="Expired claim about old pricing.",
            workspace="growth",
            actor="agent",
            ttl_days=1,
            reference_datetime=self.now - dt.timedelta(days=5),
        )

        docs = [
            {"id": 21, "text": candidate["text"], "metadata": candidate["metadata"]},
            {"id": 22, "text": expired["text"], "metadata": expired["metadata"]},
        ]

        results = filter_memory_records(
            docs,
            workspace="growth",
            include_states=["accepted", "candidate"],
            include_expired=True,
            reference_datetime=self.now,
        )

        self.assertEqual([result["doc_id"] for result in results], [21, 22])
        self.assertTrue(results[1]["expired"])

    def test_build_memory_timeline_sorts_events_and_omits_content_by_default(self):
        first = build_memory_record(
            kind="decision",
            content="Ship the local-only prototype.",
            workspace="desktop",
            actor="codex",
            memory_key="release/channel",
            reference_datetime=self.now,
        )
        second = build_memory_record(
            kind="decision",
            content="Ship the local-only prototype, then add authenticated remote access.",
            workspace="desktop",
            actor="codex",
            memory_key="release/channel",
            existing_records=[first],
            reference_datetime=self.now + dt.timedelta(hours=1),
        )

        timeline = build_memory_timeline(
            [
                {"id": 32, "text": second["text"], "metadata": second["metadata"]},
                {"id": 31, "text": first["text"], "metadata": first["metadata"]},
            ],
            workspace="desktop",
            memory_key="release/channel",
            reference_datetime=self.now + dt.timedelta(hours=2),
        )

        self.assertTrue(timeline["found"])
        self.assertEqual(timeline["current_version"], 2)
        self.assertEqual([event["version"] for event in timeline["events"]], [1, 2])
        self.assertEqual([version["doc_id"] for version in timeline["versions"]], [31, 32])
        self.assertNotIn("content", timeline["versions"][0])
        self.assertIn("content_preview", timeline["versions"][0])

    def test_build_memory_record_removes_pii_session_identifiers_from_metadata(self):
        record = build_memory_record(
            kind="artifact",
            content="Redacted output was generated.",
            workspace="privacy",
            actor="agent",
            metadata={
                "pii_session_id": "secret-session",
                "nested": {"piiSessionId": "secret-session-2", "safe": "kept"},
            },
            reference_datetime=self.now,
        )

        metadata = record["metadata"]
        self.assertNotIn("pii_session_id", metadata)
        self.assertNotIn("piiSessionId", metadata["nested"])
        self.assertEqual(metadata["nested"]["safe"], "kept")

    def test_build_memory_graph_links_memory_relations_and_source_documents(self):
        decision = build_memory_record(
            kind="decision",
            content="Use Redis for session caching.",
            workspace="checkout-api",
            actor="codex",
            memory_key="architecture/session-cache",
            source_document_id=44,
            relations=[
                {
                    "target_key": "artifact:adr-001",
                    "type": "supported_by",
                    "label": "ADR-001",
                    "pii_session_id": "hidden",
                }
            ],
            reference_datetime=self.now,
        )
        artifact = build_memory_record(
            kind="artifact",
            content="ADR-001 documents the Redis decision.",
            workspace="checkout-api",
            actor="codex",
            memory_key="artifact:adr-001",
            reference_datetime=self.now,
        )

        graph = build_memory_graph(
            [
                {"id": 41, "text": decision["text"], "metadata": decision["metadata"]},
                {"id": 42, "text": artifact["text"], "metadata": artifact["metadata"]},
            ],
            workspace="checkout-api",
            reference_datetime=self.now,
        )

        node_ids = {node["id"] for node in graph["nodes"]}
        edge_ids = {edge["id"] for edge in graph["edges"]}

        self.assertTrue(graph["found"])
        self.assertIn("memory:architecture/session-cache", node_ids)
        self.assertIn("memory:artifact:adr-001", node_ids)
        self.assertIn("document:44", node_ids)
        self.assertIn("memory:architecture/session-cache->memory:artifact:adr-001:supported_by", edge_ids)
        self.assertIn("memory:architecture/session-cache->document:44:source_document", edge_ids)
        relation_edge = next(edge for edge in graph["edges"] if edge["type"] == "supported_by")
        self.assertNotIn("pii_session_id", relation_edge["metadata"])

    def test_build_memory_graph_respects_default_governance_filters(self):
        accepted = build_memory_record(
            kind="claim",
            content="Accepted evidence about onboarding.",
            workspace="growth",
            actor="agent",
            memory_key="claim:onboarding",
            reference_datetime=self.now,
        )
        candidate = build_memory_record(
            kind="claim",
            content="Candidate evidence about activation.",
            workspace="growth",
            actor="agent",
            memory_key="claim:activation",
            state="candidate",
            reference_datetime=self.now,
        )
        expired = build_memory_record(
            kind="claim",
            content="Expired evidence about old pricing.",
            workspace="growth",
            actor="agent",
            memory_key="claim:old-pricing",
            ttl_days=1,
            reference_datetime=self.now - dt.timedelta(days=5),
        )

        docs = [
            {"id": 51, "text": accepted["text"], "metadata": accepted["metadata"]},
            {"id": 52, "text": candidate["text"], "metadata": candidate["metadata"]},
            {"id": 53, "text": expired["text"], "metadata": expired["metadata"]},
        ]

        default_graph = build_memory_graph(
            docs,
            workspace="growth",
            reference_datetime=self.now,
        )
        broad_graph = build_memory_graph(
            docs,
            workspace="growth",
            include_states=["accepted", "candidate"],
            include_expired=True,
            reference_datetime=self.now,
        )

        self.assertEqual({node["memory_key"] for node in default_graph["nodes"]}, {"claim:onboarding"})
        self.assertEqual(
            {node["memory_key"] for node in broad_graph["nodes"] if node["type"] == "memory"},
            {"claim:onboarding", "claim:activation", "claim:old-pricing"},
        )

    def test_build_memory_graph_can_center_on_one_memory_key(self):
        root = build_memory_record(
            kind="decision",
            content="Use local-first storage.",
            workspace="desktop",
            actor="agent",
            memory_key="decision:local-first",
            relations=[{"target_key": "task:encrypt-index", "type": "requires"}],
            reference_datetime=self.now,
        )
        neighbor = build_memory_record(
            kind="task",
            content="Encrypt the local index.",
            workspace="desktop",
            actor="agent",
            memory_key="task:encrypt-index",
            relations=[{"target_key": "decision:local-first", "type": "implements"}],
            reference_datetime=self.now,
        )
        unrelated = build_memory_record(
            kind="claim",
            content="Unrelated claim.",
            workspace="desktop",
            actor="agent",
            memory_key="claim:unrelated",
            reference_datetime=self.now,
        )

        graph = build_memory_graph(
            [
                {"id": 61, "text": root["text"], "metadata": root["metadata"]},
                {"id": 62, "text": neighbor["text"], "metadata": neighbor["metadata"]},
                {"id": 63, "text": unrelated["text"], "metadata": unrelated["metadata"]},
            ],
            workspace="desktop",
            center_memory_key="decision:local-first",
            reference_datetime=self.now,
        )

        self.assertEqual(
            {node["memory_key"] for node in graph["nodes"] if node["type"] == "memory"},
            {"decision:local-first", "task:encrypt-index"},
        )

    def test_build_workspace_info_summarizes_governed_memory_without_content(self):
        accepted = build_memory_record(
            kind="decision",
            content="Keep bearer-token protected remote MCP access.",
            workspace="ops",
            actor="codex",
            memory_key="decision:remote-mcp",
            metadata={"pii_session_id": "must-not-leak"},
            reference_datetime=self.now,
        )
        candidate = build_memory_record(
            kind="task",
            content="Evaluate hosted connector sync.",
            workspace="ops",
            actor="agent",
            memory_key="task:connector-sync",
            state="candidate",
            reference_datetime=self.now + dt.timedelta(minutes=5),
        )
        expired = build_memory_record(
            kind="claim",
            content="Legacy token rotation window.",
            workspace="ops",
            actor="agent",
            memory_key="claim:legacy-token-window",
            ttl_days=1,
            reference_datetime=self.now - dt.timedelta(days=5),
        )

        info = build_workspace_info(
            [
                {"id": 71, "text": accepted["text"], "metadata": accepted["metadata"]},
                {"id": 72, "text": candidate["text"], "metadata": candidate["metadata"]},
                {"id": 73, "text": expired["text"], "metadata": expired["metadata"]},
            ],
            workspace="ops",
            reference_datetime=self.now,
        )

        self.assertTrue(info["found"])
        self.assertEqual(info["workspace"], "ops")
        self.assertEqual(info["summary"]["total_record_count"], 3)
        self.assertEqual(info["summary"]["active_record_count"], 1)
        self.assertEqual(info["summary"]["expired_record_count"], 1)
        self.assertEqual(info["kind_counts"], {"claim": 1, "decision": 1, "task": 1})
        self.assertEqual(info["state_counts"], {"accepted": 2, "candidate": 1})
        self.assertEqual(info["actor_counts"], {"agent": 2, "codex": 1})
        serialized = str(info)
        self.assertNotIn("must-not-leak", serialized)
        self.assertNotIn("Keep bearer-token protected remote MCP access", serialized)
        self.assertEqual(info["governance"]["default_policy"], "accepted_non_expired_only")

    def test_build_actor_activity_returns_bounded_audit_events_without_content(self):
        first = build_memory_record(
            kind="decision",
            content="Ship local-first memory.",
            workspace="desktop",
            actor="codex",
            memory_key="decision:local-first",
            reason="ADR-002",
            reference_datetime=self.now,
        )
        second = build_memory_record(
            kind="task",
            content="Add encrypted index backups.",
            workspace="desktop",
            actor="agent",
            memory_key="task:index-backups",
            reason="follow-up",
            metadata={"nested": {"piiSessionId": "must-not-leak"}},
            reference_datetime=self.now + dt.timedelta(minutes=10),
        )

        activity = build_actor_activity(
            [
                {"id": 81, "text": first["text"], "metadata": first["metadata"]},
                {"id": 82, "text": second["text"], "metadata": second["metadata"]},
            ],
            workspace="desktop",
            actor="agent",
            limit=5,
            reference_datetime=self.now + dt.timedelta(hours=1),
        )

        self.assertTrue(activity["found"])
        self.assertEqual(activity["summary"]["event_count"], 1)
        self.assertEqual(activity["summary"]["actor_count"], 1)
        self.assertEqual(activity["events"][0]["actor"], "agent")
        self.assertEqual(activity["events"][0]["memory_key"], "task:index-backups")
        self.assertEqual(activity["events"][0]["kind"], "task")
        self.assertEqual(activity["events"][0]["doc_id"], 82)
        serialized = str(activity)
        self.assertNotIn("must-not-leak", serialized)
        self.assertNotIn("Add encrypted index backups", serialized)

    def test_build_actor_activity_reports_empty_workspace_with_reason_code(self):
        activity = build_actor_activity([], workspace="missing", actor="agent", reference_datetime=self.now)

        self.assertFalse(activity["found"])
        self.assertEqual(activity["reason_code"], "actor_activity_not_found")
        self.assertEqual(activity["policy_rule_id"], "memory.audit.actor_activity")
        self.assertEqual(activity["events"], [])


if __name__ == "__main__":
    unittest.main()
