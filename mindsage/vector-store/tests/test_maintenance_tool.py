import datetime as dt
import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_DIR = Path(__file__).resolve().parents[1] / "mcp_vector_store"
sys.path.insert(0, str(MODULE_DIR))

MAINTENANCE_TOOL_PATH = MODULE_DIR / "maintenance_tool.py"
SPEC = importlib.util.spec_from_file_location("maintenance_tool", MAINTENANCE_TOOL_PATH)
maintenance_tool = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(maintenance_tool)

build_citation_maintenance = maintenance_tool.build_citation_maintenance
build_maintenance_apply_batch = maintenance_tool.build_maintenance_apply_batch
append_maintenance_ledger_event = maintenance_tool.append_maintenance_ledger_event
build_maintenance_plan = maintenance_tool.build_maintenance_plan
build_maintenance_snapshot = maintenance_tool.build_maintenance_snapshot
format_maintenance_apply_report = maintenance_tool.format_maintenance_apply_report
format_maintenance_ledger_report = maintenance_tool.format_maintenance_ledger_report
format_maintenance_plan_report = maintenance_tool.format_maintenance_plan_report
format_maintenance_snapshot_report = maintenance_tool.format_maintenance_snapshot_report
load_maintenance_ledger = maintenance_tool.load_maintenance_ledger
maintenance_main = maintenance_tool.main


class MaintenanceToolTest(unittest.TestCase):
    def test_build_citation_maintenance_prioritizes_stale_undated_and_gaps(self):
        report = build_citation_maintenance(
            question="What is the production MCP access policy?",
            citations=[
                {
                    "doc_id": 10,
                    "title": "Old access policy",
                    "excerpt": "Production MCP access was enabled for early testers.",
                    "score": 0.61,
                    "date": "2026-01-01",
                    "source": "typed_memory",
                    "topics": ["mcp access"],
                    "metadata": {"pii_session_id": "secret-session"},
                },
                {
                    "doc_id": 11,
                    "title": "Undated auth note",
                    "excerpt": "MCP access requires a bearer token.",
                    "score": 0.79,
                    "date": None,
                    "source": "notes",
                },
            ],
            coverage={
                "source_count": 2,
                "strong_source_count": 1,
                "query_terms_found": ["mcp", "access"],
                "query_terms_missing": ["production", "policy"],
            },
            freshness={
                "freshness_days": 30,
                "stale_source_count": 1,
                "undated_source_count": 1,
            },
            contradictions=[],
            reference_date=dt.date(2026, 6, 1),
        )

        action_types = [action["type"] for action in report["actions"]]
        serialized = json.dumps(report)

        self.assertTrue(report["found"])
        self.assertEqual(action_types[:3], [
            "refresh_stale_citation",
            "add_source_date",
            "retrieve_missing_context",
        ])
        self.assertEqual(report["priority"], "high")
        self.assertIn("production policy", report["actions"][2]["repair_query"])
        self.assertNotIn("secret-session", serialized)
        self.assertFalse(report["privacy"]["pii_session_ids_exposed"])

    def test_replacement_candidates_link_newer_evidence_to_stale_citations(self):
        report = build_citation_maintenance(
            question="Should remote MCP access be enabled?",
            citations=[
                {
                    "doc_id": 20,
                    "title": "January remote MCP policy",
                    "excerpt": "Remote MCP access should be enabled.",
                    "score": 0.64,
                    "date": "2026-01-01",
                    "source": "typed_memory",
                    "topics": ["remote mcp"],
                }
            ],
            coverage={
                "source_count": 1,
                "strong_source_count": 0,
                "query_terms_found": ["remote", "mcp", "access"],
                "query_terms_missing": [],
            },
            freshness={
                "freshness_days": 30,
                "stale_source_count": 1,
                "undated_source_count": 0,
            },
            contradictions=[],
            replacement_candidates=[
                {
                    "doc_id": 21,
                    "title": "May remote MCP policy",
                    "excerpt": "Remote MCP access should be enabled only with bearer auth.",
                    "score": 0.93,
                    "date": "2026-05-31",
                    "source": "security",
                    "topics": ["remote mcp"],
                    "metadata": {"piiSessionId": "secret-session"},
                }
            ],
            reference_date=dt.date(2026, 6, 1),
        )

        replacements = report["replacement_candidates"]
        graph = report["maintenance_graph"]
        edge_ids = {edge["id"] for edge in graph["edges"]}
        serialized = json.dumps(report)

        self.assertEqual(len(replacements), 1)
        self.assertEqual(replacements[0]["replaces_doc_id"], 20)
        self.assertEqual(replacements[0]["candidate_doc_id"], 21)
        self.assertIn("candidate:21->citation:20:can_replace", edge_ids)
        self.assertNotIn("secret-session", serialized)

    def test_build_maintenance_snapshot_detects_background_jobs_without_pii(self):
        snapshot = build_maintenance_snapshot(
            documents=[
                {
                    "id": 31,
                    "text": "Remote MCP access requires bearer auth and a private tunnel.",
                    "metadata": {
                        "title": "January remote MCP policy",
                        "date": "2026-01-01",
                        "source": "typed_memory",
                        "structured_metadata": {
                            "organizations": ["MindSage"],
                            "technologies": ["MCP"],
                            "persons": ["Private User"],
                        },
                        "pii_session_id": "must-not-leak",
                    },
                },
                {
                    "id": 32,
                    "text": "Remote MCP access requires bearer auth and a private tunnel.",
                    "metadata": {
                        "title": "January remote MCP policy copy",
                        "date": "2026-01-05",
                        "source": "import",
                        "structured_metadata": {
                            "organizations": ["Mind Sage"],
                            "technologies": ["MCP"],
                        },
                    },
                },
                {
                    "id": 33,
                    "text": "Remote MCP access should be checked every week.",
                    "metadata": {
                        "title": "Undated remote MCP note",
                        "source": "notes",
                    },
                },
                {
                    "id": 34,
                    "text": "Remote MCP access requires bearer auth, a private tunnel, and audit logs.",
                    "metadata": {
                        "title": "May remote MCP policy",
                        "date": "2026-05-31",
                        "source": "security",
                        "structured_metadata": {
                            "organizations": ["MindSage"],
                            "technologies": ["MCP"],
                        },
                    },
                },
            ],
            reference_date=dt.date(2026, 6, 1),
            freshness_days=30,
        )

        job_types = {job["type"] for job in snapshot["jobs"]}
        serialized = json.dumps(snapshot)

        self.assertTrue(snapshot["found"])
        self.assertEqual(snapshot["summary"]["document_count"], 4)
        self.assertEqual(snapshot["summary"]["stale_source_count"], 2)
        self.assertEqual(snapshot["summary"]["undated_source_count"], 1)
        self.assertEqual(snapshot["summary"]["duplicate_group_count"], 1)
        self.assertEqual(snapshot["summary"]["entity_consolidation_count"], 1)
        self.assertIn("refresh_stale_sources", job_types)
        self.assertIn("add_source_dates", job_types)
        self.assertIn("deduplicate_documents", job_types)
        self.assertIn("consolidate_entities", job_types)
        self.assertEqual(snapshot["replacement_candidates"][0]["candidate_doc_id"], 34)
        self.assertFalse(snapshot["privacy"]["pii_session_ids_exposed"])
        self.assertFalse(snapshot["privacy"]["person_entities_exposed"])
        self.assertNotIn("must-not-leak", serialized)
        self.assertNotIn("Private User", serialized)

    def test_format_maintenance_snapshot_report_is_stable(self):
        snapshot = build_maintenance_snapshot(
            documents=[
                {
                    "id": 41,
                    "text": "Old policy says local MCP only.",
                    "metadata": {
                        "title": "Old local MCP policy",
                        "date": "2026-01-01",
                    },
                },
                {
                    "id": 42,
                    "text": "Current policy says authenticated remote MCP is allowed.",
                    "metadata": {
                        "title": "Current remote MCP policy",
                        "date": "2026-05-31",
                    },
                },
            ],
            reference_date=dt.date(2026, 6, 1),
            freshness_days=30,
        )

        output = format_maintenance_snapshot_report(snapshot)

        self.assertIn("MindSage maintenance snapshot: high priority", output)
        self.assertIn("documents=2", output)
        self.assertIn("JOB refresh_stale_sources", output)

    def test_build_maintenance_plan_schedules_reviewable_jobs_without_pii(self):
        snapshot = build_maintenance_snapshot(
            documents=[
                {
                    "id": 51,
                    "text": "Remote MCP access requires bearer auth and a private tunnel.",
                    "metadata": {
                        "title": "January remote MCP policy",
                        "date": "2026-01-01",
                        "source": "readwise",
                        "structured_metadata": {
                            "organizations": ["MindSage"],
                            "technologies": ["MCP"],
                            "persons": ["Private User"],
                        },
                        "pii_session_id": "must-not-leak",
                    },
                },
                {
                    "id": 52,
                    "text": "Remote MCP access requires bearer auth and a private tunnel.",
                    "metadata": {
                        "title": "January remote MCP policy copy",
                        "date": "2026-01-05",
                        "source": "notion",
                        "structured_metadata": {
                            "organizations": ["Mind Sage"],
                            "technologies": ["MCP"],
                        },
                    },
                },
                {
                    "id": 53,
                    "text": "Remote MCP access should be checked every week.",
                    "metadata": {
                        "title": "Undated remote MCP note",
                        "source": "notes",
                    },
                },
                {
                    "id": 54,
                    "text": "Remote MCP access requires bearer auth, a private tunnel, and audit logs.",
                    "metadata": {
                        "title": "May remote MCP policy",
                        "date": "2026-05-31",
                        "source": "security",
                    },
                },
            ],
            reference_date=dt.date(2026, 6, 1),
            freshness_days=30,
        )

        plan = build_maintenance_plan(
            snapshot,
            schedule_days=7,
            reference_date=dt.date(2026, 6, 1),
        )
        job_types = {job["type"] for job in plan["jobs"]}
        review_jobs = [
            job for job in plan["jobs"]
            if job["execution_mode"] == "review_required"
        ]
        serialized = json.dumps(plan)

        self.assertTrue(plan["found"])
        self.assertEqual(plan["schedule"]["cadence_days"], 7)
        self.assertEqual(plan["schedule"]["cron_hint"], "0 3 */7 * *")
        self.assertIn("recurring_freshness_scan", job_types)
        self.assertIn("connector_sync_review", job_types)
        self.assertIn("refresh_stale_sources", job_types)
        self.assertIn("add_source_dates", job_types)
        self.assertIn("deduplicate_documents", job_types)
        self.assertIn("consolidate_entities", job_types)
        self.assertGreaterEqual(len(review_jobs), 4)
        self.assertTrue(all(job["requires_review"] for job in review_jobs))
        self.assertEqual(plan["governance"]["default_policy"], "review_before_mutation")
        self.assertFalse(plan["privacy"]["pii_session_ids_exposed"])
        self.assertFalse(plan["privacy"]["person_entities_exposed"])
        self.assertNotIn("must-not-leak", serialized)
        self.assertNotIn("Private User", serialized)

    def test_format_maintenance_plan_report_is_stable(self):
        snapshot = build_maintenance_snapshot(
            documents=[
                {
                    "id": 61,
                    "text": "Old policy says local MCP only.",
                    "metadata": {
                        "title": "Old local MCP policy",
                        "date": "2026-01-01",
                        "source": "readwise",
                    },
                },
                {
                    "id": 62,
                    "text": "Current policy says authenticated remote MCP is allowed.",
                    "metadata": {
                        "title": "Current remote MCP policy",
                        "date": "2026-05-31",
                        "source": "security",
                    },
                },
            ],
            reference_date=dt.date(2026, 6, 1),
            freshness_days=30,
        )

        output = format_maintenance_plan_report(
            build_maintenance_plan(snapshot, schedule_days=14)
        )

        self.assertIn("MindSage maintenance plan:", output)
        self.assertIn("cadence=14d", output)
        self.assertIn("JOB recurring_freshness_scan - read_only", output)
        self.assertIn("JOB refresh_stale_sources - review_required", output)

    def test_main_can_emit_plan_json(self):
        stdout = io.StringIO()

        with contextlib.redirect_stdout(stdout):
            exit_code = maintenance_main([
                "--plan",
                "--json",
                "--reference-date",
                "2026-06-01",
                "--freshness-days",
                "90",
            ])

        payload = json.loads(stdout.getvalue())

        self.assertEqual(exit_code, 0)
        self.assertIn("schedule", payload)
        self.assertIn("jobs", payload)
        self.assertEqual(payload["governance"]["source"], "maintenance.plan")

    def test_build_maintenance_apply_batch_previews_reviewable_writes_without_mutation_or_pii(self):
        snapshot = build_maintenance_snapshot(
            documents=[
                {
                    "id": 71,
                    "text": "Remote MCP access requires bearer auth and a private tunnel.",
                    "metadata": {
                        "title": "January remote MCP policy",
                        "date": "2026-01-01",
                        "source": "readwise",
                        "structured_metadata": {
                            "organizations": ["MindSage"],
                            "technologies": ["MCP"],
                            "persons": ["Private User"],
                        },
                        "pii_session_id": "must-not-leak",
                    },
                },
                {
                    "id": 72,
                    "text": "Remote MCP access requires bearer auth and a private tunnel.",
                    "metadata": {
                        "title": "January remote MCP policy copy",
                        "date": "2026-01-05",
                        "source": "notion",
                        "structured_metadata": {
                            "organizations": ["Mind Sage"],
                            "technologies": ["MCP"],
                        },
                    },
                },
                {
                    "id": 73,
                    "text": "Remote MCP access should be checked every week.",
                    "metadata": {
                        "title": "Undated remote MCP note",
                        "source": "notes",
                    },
                },
                {
                    "id": 74,
                    "text": "Remote MCP access requires bearer auth, a private tunnel, and audit logs.",
                    "metadata": {
                        "title": "May remote MCP policy",
                        "date": "2026-05-31",
                        "source": "security",
                    },
                },
            ],
            reference_date=dt.date(2026, 6, 1),
            freshness_days=30,
        )
        plan = build_maintenance_plan(
            snapshot,
            schedule_days=7,
            reference_date=dt.date(2026, 6, 1),
        )

        batch = build_maintenance_apply_batch(plan)
        serialized = json.dumps(batch)
        targets = {item.get("target") for item in batch["items"]}
        statuses = {item["status"] for item in batch["items"]}

        self.assertTrue(batch["found"])
        self.assertEqual(batch["mode"], "dry_run")
        self.assertEqual(batch["summary"]["total_item_count"], plan["summary"]["job_count"])
        self.assertGreaterEqual(batch["summary"]["review_item_count"], 4)
        self.assertGreaterEqual(batch["summary"]["pending_review_count"], 4)
        self.assertEqual(batch["governance"]["source"], "maintenance.apply")
        self.assertEqual(batch["governance"]["default_policy"], "dry_run_unless_approved")
        self.assertFalse(batch["governance"]["mutated_data"])
        self.assertIn("ready", statuses)
        self.assertIn("pending_review", statuses)
        self.assertIn("documents", targets)
        self.assertIn("typed_memory", targets)
        self.assertIn("connector_sources", targets)
        self.assertNotIn("must-not-leak", serialized)
        self.assertNotIn("Private User", serialized)
        self.assertNotIn("January remote MCP policy", serialized)
        self.assertNotIn("Remote MCP access requires bearer auth", serialized)
        self.assertFalse(batch["privacy"]["pii_session_ids_exposed"])
        self.assertFalse(batch["privacy"]["person_entities_exposed"])

    def test_build_maintenance_apply_batch_can_mark_reviewed_jobs_as_approved(self):
        snapshot = build_maintenance_snapshot(
            documents=[
                {
                    "id": 81,
                    "text": "Old policy says local MCP only.",
                    "metadata": {
                        "title": "Old local MCP policy",
                        "date": "2026-01-01",
                    },
                },
                {
                    "id": 82,
                    "text": "Current policy says authenticated remote MCP is allowed.",
                    "metadata": {
                        "title": "Current remote MCP policy",
                        "date": "2026-05-31",
                    },
                },
            ],
            reference_date=dt.date(2026, 6, 1),
            freshness_days=30,
        )
        plan = build_maintenance_plan(snapshot, schedule_days=14)

        batch = build_maintenance_apply_batch(plan, approve=True)
        review_items = [item for item in batch["items"] if item["requires_review"]]

        self.assertEqual(batch["mode"], "approved")
        self.assertEqual(batch["summary"]["approved_item_count"], len(review_items))
        self.assertTrue(all(item["status"] == "approved_for_execution" for item in review_items))
        self.assertTrue(all(item["executor_required"] for item in review_items))
        self.assertFalse(batch["governance"]["mutated_data"])

    def test_format_maintenance_apply_report_is_stable(self):
        snapshot = build_maintenance_snapshot(
            documents=[
                {
                    "id": 91,
                    "text": "Old policy says local MCP only.",
                    "metadata": {
                        "title": "Old local MCP policy",
                        "date": "2026-01-01",
                    },
                },
                {
                    "id": 92,
                    "text": "Current policy says authenticated remote MCP is allowed.",
                    "metadata": {
                        "title": "Current remote MCP policy",
                        "date": "2026-05-31",
                    },
                },
            ],
            reference_date=dt.date(2026, 6, 1),
            freshness_days=30,
        )

        output = format_maintenance_apply_report(
            build_maintenance_apply_batch(build_maintenance_plan(snapshot))
        )

        self.assertIn("MindSage maintenance apply batch:", output)
        self.assertIn("mode=dry_run", output)
        self.assertIn("ITEM recurring_freshness_scan - ready", output)
        self.assertIn("ITEM refresh_stale_sources - pending_review", output)

    def test_main_can_emit_apply_json(self):
        stdout = io.StringIO()

        with contextlib.redirect_stdout(stdout):
            exit_code = maintenance_main([
                "--apply",
                "--json",
                "--reference-date",
                "2026-06-01",
                "--freshness-days",
                "90",
            ])

        payload = json.loads(stdout.getvalue())

        self.assertEqual(exit_code, 0)
        self.assertIn("items", payload)
        self.assertEqual(payload["mode"], "dry_run")
        self.assertEqual(payload["governance"]["source"], "maintenance.apply")

    def test_append_maintenance_ledger_event_records_redacted_audit_history(self):
        snapshot = build_maintenance_snapshot(
            documents=[
                {
                    "id": 101,
                    "text": "Remote MCP access requires bearer auth and a private tunnel.",
                    "metadata": {
                        "title": "January remote MCP policy",
                        "date": "2026-01-01",
                        "source": "readwise",
                        "structured_metadata": {
                            "organizations": ["MindSage"],
                            "persons": ["Private User"],
                        },
                        "pii_session_id": "must-not-leak",
                    },
                },
                {
                    "id": 102,
                    "text": "Current policy says authenticated remote MCP is allowed.",
                    "metadata": {
                        "title": "Current remote MCP policy",
                        "date": "2026-05-31",
                        "source": "security",
                    },
                },
            ],
            reference_date=dt.date(2026, 6, 1),
            freshness_days=30,
        )
        batch = build_maintenance_apply_batch(build_maintenance_plan(snapshot), approve=True)

        with tempfile.TemporaryDirectory() as tmpdir:
            ledger_path = Path(tmpdir) / "maintenance-ledger.jsonl"
            event = append_maintenance_ledger_event(
                batch,
                ledger_path=ledger_path,
                actor="codex",
                reference_datetime=dt.datetime(2026, 6, 1, 12, 0, 0),
            )
            ledger = load_maintenance_ledger(ledger_path)
            serialized = ledger_path.read_text(encoding="utf-8")

        self.assertEqual(event["event_type"], "maintenance_apply_batch_recorded")
        self.assertEqual(event["actor"], "codex")
        self.assertEqual(event["mode"], "approved")
        self.assertEqual(event["approved_item_count"], batch["summary"]["approved_item_count"])
        self.assertFalse(event["mutated_data"])
        self.assertEqual(ledger["summary"]["event_count"], 1)
        self.assertEqual(ledger["events"][0]["event_id"], event["event_id"])
        self.assertIn("item_status_counts", ledger["events"][0])
        self.assertNotIn("must-not-leak", serialized)
        self.assertNotIn("Private User", serialized)
        self.assertNotIn("January remote MCP policy", serialized)
        self.assertNotIn("Remote MCP access requires bearer auth", serialized)
        self.assertFalse(ledger["privacy"]["pii_session_ids_exposed"])
        self.assertFalse(ledger["privacy"]["person_entities_exposed"])

    def test_format_maintenance_ledger_report_is_stable(self):
        batch = build_maintenance_apply_batch({
            "summary": {"job_count": 1},
            "jobs": [
                {
                    "id": "job:1",
                    "type": "refresh_stale_sources",
                    "severity": "high",
                    "requires_review": True,
                    "command": "npm run agent:search",
                    "item_count": 2,
                    "write_intent": {
                        "target": "documents",
                        "operation": "refresh_or_link_newer_evidence",
                        "doc_ids": ["1", "2"],
                    },
                }
            ],
        })

        with tempfile.TemporaryDirectory() as tmpdir:
            ledger_path = Path(tmpdir) / "maintenance-ledger.jsonl"
            append_maintenance_ledger_event(
                batch,
                ledger_path=ledger_path,
                actor="operator",
                reference_datetime=dt.datetime(2026, 6, 1, 12, 0, 0),
            )
            output = format_maintenance_ledger_report(load_maintenance_ledger(ledger_path))

        self.assertIn("MindSage maintenance ledger:", output)
        self.assertIn("events=1", output)
        self.assertIn("last_mode=dry_run", output)

    def test_main_can_record_apply_ledger_json(self):
        stdout = io.StringIO()

        with tempfile.TemporaryDirectory() as tmpdir:
            ledger_path = Path(tmpdir) / "maintenance-ledger.jsonl"
            with contextlib.redirect_stdout(stdout):
                exit_code = maintenance_main([
                    "--apply",
                    "--json",
                    "--ledger-path",
                    str(ledger_path),
                    "--actor",
                    "codex",
                    "--reference-date",
                    "2026-06-01",
                    "--freshness-days",
                    "90",
                ])
            payload = json.loads(stdout.getvalue())
            ledger = load_maintenance_ledger(ledger_path)

        self.assertEqual(exit_code, 0)
        self.assertIn("ledger_event", payload)
        self.assertEqual(payload["ledger_event"]["actor"], "codex")
        self.assertEqual(ledger["summary"]["event_count"], 1)


if __name__ == "__main__":
    unittest.main()
