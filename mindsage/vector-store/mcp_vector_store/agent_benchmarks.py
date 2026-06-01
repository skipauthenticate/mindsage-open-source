"""Dependency-light benchmarks for MindSage agent-facing features."""

from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import math
import statistics
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Dict, List

try:
    from .agent_capture import build_capture_dry_run, build_capture_request, format_capture_report, read_capture_text, send_capture
    from .agent_health import build_agent_health, format_agent_health_report, main as health_main
    from .agent_import import build_import_dry_run, build_import_request, collect_import_documents, format_import_report, send_import
    from .agent_pack import build_schema_pack, classify_path, detect_schema_candidates, format_classification_report, format_detection_report, format_pack_report
    from .agent_search import build_search_request, format_search_report, read_query, send_search
    from .agent_schema import build_agent_schema, format_schema_report, main as schema_main
    from .agent_think import build_think_request, format_think_report, read_question, send_think
    from .agent_setup import generate_setup, run_doctor
    from .corpus_evals import run_fixture_corpus_evals
    from .maintenance_tool import append_maintenance_ledger_event, build_maintenance_apply_batch, build_maintenance_plan, build_maintenance_snapshot, load_maintenance_ledger
    from .memory_tool import (
        build_actor_activity,
        build_memory_graph,
        build_memory_record,
        build_memory_timeline,
        build_workspace_info,
        filter_memory_records,
    )
    from .remote_auth import authorize_bearer_header, build_auth_headers, normalize_remote_api_key
    from .think_tool import build_think_response
except ImportError:  # Allows direct execution from the source checkout.
    from agent_capture import build_capture_dry_run, build_capture_request, format_capture_report, read_capture_text, send_capture
    from agent_health import build_agent_health, format_agent_health_report, main as health_main
    from agent_import import build_import_dry_run, build_import_request, collect_import_documents, format_import_report, send_import
    from agent_pack import build_schema_pack, classify_path, detect_schema_candidates, format_classification_report, format_detection_report, format_pack_report
    from agent_search import build_search_request, format_search_report, read_query, send_search
    from agent_schema import build_agent_schema, format_schema_report, main as schema_main
    from agent_think import build_think_request, format_think_report, read_question, send_think
    from agent_setup import generate_setup, run_doctor
    from corpus_evals import run_fixture_corpus_evals
    from maintenance_tool import append_maintenance_ledger_event, build_maintenance_apply_batch, build_maintenance_plan, build_maintenance_snapshot, load_maintenance_ledger
    from memory_tool import (
        build_actor_activity,
        build_memory_graph,
        build_memory_record,
        build_memory_timeline,
        build_workspace_info,
        filter_memory_records,
    )
    from remote_auth import authorize_bearer_header, build_auth_headers, normalize_remote_api_key
    from think_tool import build_think_response


BenchmarkExercise = Callable[[], List[tuple[bool, str]]]


def run_agent_feature_benchmarks(iterations: int = 3) -> Dict[str, Any]:
    """Benchmark and validate the public, dependency-light agent feature surface."""

    if iterations < 1:
        raise ValueError("iterations must be at least 1")

    cases = [
        _benchmark_case(
            "think.citations",
            "cited, PII-safe reasoning context",
            _exercise_think_citations,
            iterations=iterations,
            budget_ms=500,
        ),
        _benchmark_case(
            "think.citation_graph",
            "answer/source/concept/contradiction graph",
            _exercise_think_citation_graph,
            iterations=iterations,
            budget_ms=500,
        ),
        _benchmark_case(
            "think.entity_graph",
            "PII-safe entity graph over cited evidence",
            _exercise_think_entity_graph,
            iterations=iterations,
            budget_ms=500,
        ),
        _benchmark_case(
            "think.maintenance",
            "citation freshness and repair guidance",
            _exercise_think_maintenance,
            iterations=iterations,
            budget_ms=500,
        ),
        _benchmark_case(
            "maintenance.snapshot",
            "background stale, duplicate, and entity maintenance snapshot",
            _exercise_maintenance_snapshot,
            iterations=iterations,
            budget_ms=500,
        ),
        _benchmark_case(
            "maintenance.plan",
            "schedulable review plan for recurring freshness and maintenance writes",
            _exercise_maintenance_plan,
            iterations=iterations,
            budget_ms=500,
        ),
        _benchmark_case(
            "maintenance.apply",
            "reviewable dry-run apply batches for maintenance writes",
            _exercise_maintenance_apply,
            iterations=iterations,
            budget_ms=500,
        ),
        _benchmark_case(
            "maintenance.ledger",
            "append-only redacted maintenance apply audit ledger",
            _exercise_maintenance_ledger,
            iterations=iterations,
            budget_ms=500,
        ),
        _benchmark_case(
            "memory.governance",
            "typed-memory default visibility policy",
            _exercise_memory_governance,
            iterations=iterations,
            budget_ms=200,
        ),
        _benchmark_case(
            "memory.workspace_activity",
            "workspace summary and actor audit activity",
            _exercise_memory_workspace_activity,
            iterations=iterations,
            budget_ms=200,
        ),
        _benchmark_case(
            "memory.timeline",
            "versioned memory audit timeline",
            _exercise_memory_timeline,
            iterations=iterations,
            budget_ms=200,
        ),
        _benchmark_case(
            "memory.graph",
            "typed-memory relation graph traversal",
            _exercise_memory_graph,
            iterations=iterations,
            budget_ms=200,
        ),
        _benchmark_case(
            "remote_auth.bearer",
            "remote MCP bearer-token authorization helpers",
            _exercise_remote_auth,
            iterations=iterations,
            budget_ms=100,
        ),
        _benchmark_case(
            "agent_setup.config_generation",
            "AI coding tool MCP config generation and doctor checks",
            _exercise_agent_setup,
            iterations=iterations,
            budget_ms=100,
        ),
        _benchmark_case(
            "agent_pack.schema_pack",
            "agent schema-pack taxonomy and safe path classification",
            _exercise_agent_pack,
            iterations=iterations,
            budget_ms=100,
        ),
        _benchmark_case(
            "agent_pack.schema_detect",
            "privacy-safe corpus schema detection for agent intake planning",
            _exercise_agent_pack_detect,
            iterations=iterations,
            budget_ms=100,
        ),
        _benchmark_case(
            "agent_capture.rest_cli",
            "agent capture CLI REST payloads and auth",
            _exercise_agent_capture,
            iterations=iterations,
            budget_ms=100,
        ),
        _benchmark_case(
            "agent_think.rest_cli",
            "agent think CLI cited-answer payloads and auth",
            _exercise_agent_think,
            iterations=iterations,
            budget_ms=100,
        ),
        _benchmark_case(
            "agent_import.rest_cli",
            "agent import CLI corpus payloads and auth",
            _exercise_agent_import,
            iterations=iterations,
            budget_ms=100,
        ),
        _benchmark_case(
            "agent_search.rest_cli",
            "agent search CLI ranked evidence payloads and auth",
            _exercise_agent_search,
            iterations=iterations,
            budget_ms=100,
        ),
        _benchmark_case(
            "agent_schema.contract_cli",
            "agent schema CLI integration contract",
            _exercise_agent_schema,
            iterations=iterations,
            budget_ms=100,
        ),
        _benchmark_case(
            "agent_health.score_cli",
            "agent health score CLI maintenance gate",
            _exercise_agent_health,
            iterations=iterations,
            budget_ms=100,
        ),
        _benchmark_case(
            "eval.fixture_corpus",
            "synthetic fixture-corpus retrieval evals",
            _exercise_fixture_corpus_eval,
            iterations=iterations,
            budget_ms=5000,
        ),
    ]
    passed = sum(1 for case in cases if case["passed"])
    failed = len(cases) - passed
    return {
        "suite": "mindsage-agent-features",
        "version": 1,
        "summary": {
            "total": len(cases),
            "passed": passed,
            "failed": failed,
            "score": round(passed / len(cases), 4) if cases else 0.0,
        },
        "cases": cases,
    }


def format_benchmark_report(report: Dict[str, Any]) -> str:
    """Format benchmark output for humans and CI logs."""

    summary = report["summary"]
    lines = [
        "MindSage agent feature benchmarks: "
        f"{summary['passed']}/{summary['total']} passed (score={summary['score']:.4f})"
    ]
    for case in report["cases"]:
        status = "PASS" if case["passed"] else "FAIL"
        metrics = case["metrics"]
        lines.append(
            f"{status} {case['id']} - {case['description']} "
            f"(mean={metrics['mean_ms']:.2f}ms, p95={metrics['p95_ms']:.2f}ms, "
            f"budget={metrics['budget_ms']:.0f}ms)"
        )
        for failure in case.get("failures", []):
            lines.append(f"  - {failure}")
    return "\n".join(lines)


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Benchmark MindSage agent-facing features")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text")
    parser.add_argument("--iterations", type=int, default=3, help="Iterations per benchmark case")
    args = parser.parse_args(argv)

    report = run_agent_feature_benchmarks(iterations=args.iterations)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(format_benchmark_report(report))
    return 0 if report["summary"]["failed"] == 0 else 1


def _benchmark_case(
    case_id: str,
    description: str,
    exercise: BenchmarkExercise,
    *,
    iterations: int,
    budget_ms: float,
) -> Dict[str, Any]:
    timings: List[float] = []
    failures: List[str] = []
    for _ in range(iterations):
        start = time.perf_counter()
        checks = exercise()
        timings.append((time.perf_counter() - start) * 1000)
        for passed, message in checks:
            if not passed and message not in failures:
                failures.append(message)

    metrics = _timing_metrics(timings, budget_ms)
    if not metrics["within_budget"]:
        failures.append(
            f"p95 latency {metrics['p95_ms']:.2f}ms exceeded budget {budget_ms:.0f}ms"
        )

    return {
        "id": case_id,
        "description": description,
        "passed": not failures,
        "failures": failures,
        "metrics": metrics,
    }


def _timing_metrics(timings: List[float], budget_ms: float) -> Dict[str, Any]:
    p95_index = min(math.ceil(len(timings) * 0.95) - 1, len(timings) - 1)
    p95_ms = sorted(timings)[p95_index]
    return {
        "iterations": len(timings),
        "mean_ms": round(statistics.mean(timings), 3),
        "median_ms": round(statistics.median(timings), 3),
        "p95_ms": round(p95_ms, 3),
        "min_ms": round(min(timings), 3),
        "max_ms": round(max(timings), 3),
        "budget_ms": budget_ms,
        "within_budget": p95_ms <= budget_ms,
    }


def _exercise_think_citations() -> List[tuple[bool, str]]:
    response = build_think_response(
        "What did we decide about remote access?",
        [
            {
                "id": 101,
                "excerpt": "Remote access should require authenticated private tunnels before public exposure.",
                "score": 0.91,
                "metadata": {
                    "title": "Remote access decision",
                    "source": "typed_memory",
                    "created_at": "2026-05-30T12:00:00Z",
                    "pii_session_id": "must-not-leak",
                },
            },
            {
                "id": 102,
                "excerpt": "Do not expose the local MCP endpoint directly to the public internet.",
                "score": 0.86,
                "metadata": {
                    "title": "Security policy",
                    "source": "security",
                    "created_at": "2026-05-31T12:00:00Z",
                },
            },
        ],
        reference_date=dt.date(2026, 6, 1),
    )
    serialized = json.dumps(response)
    return [
        (len(response["citations"]) == 2, "expected two citations"),
        (response["privacy"]["pii_session_ids_exposed"] is False, "PII session IDs must not be exposed"),
        ("remote" in response["coverage"]["query_terms_found"], "expected query-term coverage"),
        ("must-not-leak" not in serialized, "secret token must not appear in benchmark output"),
    ]


def _exercise_think_citation_graph() -> List[tuple[bool, str]]:
    response = build_think_response(
        "Should remote MCP access be enabled?",
        [
            {
                "id": 111,
                "excerpt": "Remote MCP access should be enabled only behind authenticated private tunnels.",
                "score": 0.9,
                "topics": ["remote mcp", "private tunnel"],
                "metadata": {"title": "Remote MCP access decision", "created_at": "2026-05-30T12:00:00Z"},
            },
            {
                "id": 112,
                "excerpt": "Remote MCP access should be disabled when no private tunnel exists.",
                "score": 0.85,
                "primary_topic": "remote mcp",
                "metadata": {"title": "Remote MCP safety policy", "created_at": "2026-05-31T12:00:00Z"},
            },
        ],
        reference_date=dt.date(2026, 6, 1),
    )
    graph = response["citation_graph"]
    node_ids = {node["id"] for node in graph["nodes"]}
    edge_ids = {edge["id"] for edge in graph["edges"]}
    return [
        (graph["found"] is True, "expected citation graph"),
        ("citation:111" in node_ids and "citation:112" in node_ids, "expected citation nodes"),
        ("concept:remote-mcp" in node_ids, "expected concept node"),
        ("citation:111->citation:112:contradicts" in edge_ids, "expected contradiction edge"),
    ]


def _exercise_think_entity_graph() -> List[tuple[bool, str]]:
    response = build_think_response(
        "What did NVIDIA announce in San Jose?",
        [
            {
                "id": 115,
                "excerpt": "NVIDIA announced Jetson Orin in San Jose during a redacted keynote.",
                "score": 0.91,
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
    graph = response["entity_graph"]
    node_ids = {node["id"] for node in graph["nodes"]}
    serialized = json.dumps(response)
    return [
        (graph["found"] is True, "expected entity graph"),
        ("entity:organization:nvidia" in node_ids, "expected organization node"),
        ("entity:location:san-jose" in node_ids, "expected location node"),
        ("entity:technology:jetson-orin" in node_ids, "expected technology node"),
        ("Jensen Huang" not in serialized, "person entity should be redacted"),
        ("must-not-leak" not in serialized, "secret token must not appear in graph output"),
    ]


def _exercise_think_maintenance() -> List[tuple[bool, str]]:
    response = build_think_response(
        "Should remote MCP access be enabled?",
        [
            {
                "id": 121,
                "excerpt": "Remote MCP access should be enabled for internal demos.",
                "score": 0.66,
                "topics": ["remote mcp"],
                "metadata": {"title": "Old note", "created_at": "2026-01-01T12:00:00Z"},
            },
            {
                "id": 122,
                "excerpt": "Remote MCP access should be disabled unless bearer auth is configured.",
                "score": 0.88,
                "topics": ["remote mcp"],
                "metadata": {"title": "Fresh policy", "created_at": "2026-05-31T12:00:00Z"},
            },
            {
                "id": 123,
                "excerpt": "Remote MCP access needs an operator-reviewed access log.",
                "score": 0.72,
                "topics": ["remote mcp"],
                "metadata": {"title": "Undated note"},
            },
        ],
        freshness_days=30,
        reference_date=dt.date(2026, 6, 1),
    )
    maintenance = response["maintenance"]
    action_types = {action["type"] for action in maintenance["actions"]}
    return [
        (maintenance["found"] is True, "expected maintenance actions"),
        ("refresh_stale_citation" in action_types, "expected stale citation action"),
        ("add_source_date" in action_types, "expected undated source action"),
        ("resolve_contradiction" in action_types, "expected contradiction repair action"),
        (maintenance["maintenance_graph"]["found"] is True, "expected maintenance graph"),
    ]


def _exercise_maintenance_snapshot() -> List[tuple[bool, str]]:
    snapshot = build_maintenance_snapshot(
        [
            {
                "id": 131,
                "text": "Remote MCP access requires bearer auth and a private tunnel.",
                "metadata": {
                    "title": "January remote MCP policy",
                    "date": "2026-01-01",
                    "structured_metadata": {
                        "organizations": ["MindSage"],
                        "technologies": ["MCP"],
                        "persons": ["Private User"],
                    },
                    "pii_session_id": "must-not-leak",
                },
            },
            {
                "id": 132,
                "text": "Remote MCP access requires bearer auth and a private tunnel.",
                "metadata": {
                    "title": "January remote MCP policy copy",
                    "date": "2026-01-05",
                    "structured_metadata": {
                        "organizations": ["Mind Sage"],
                        "technologies": ["MCP"],
                    },
                },
            },
            {
                "id": 133,
                "text": "Remote MCP access should be reviewed weekly.",
                "metadata": {"title": "Undated MCP note"},
            },
            {
                "id": 134,
                "text": "Remote MCP access requires bearer auth, a private tunnel, and audit logs.",
                "metadata": {
                    "title": "May remote MCP policy",
                    "date": "2026-05-31",
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
    serialized = json.dumps(snapshot)
    job_types = {job["type"] for job in snapshot["jobs"]}
    return [
        (snapshot["found"] is True, "expected maintenance snapshot work"),
        (snapshot["summary"]["stale_source_count"] == 2, "expected stale source count"),
        (snapshot["summary"]["undated_source_count"] == 1, "expected undated source count"),
        (snapshot["summary"]["duplicate_group_count"] == 1, "expected duplicate group"),
        (snapshot["summary"]["entity_consolidation_count"] == 1, "expected entity consolidation"),
        ("refresh_stale_sources" in job_types, "expected refresh job"),
        ("deduplicate_documents" in job_types, "expected dedupe job"),
        ("consolidate_entities" in job_types, "expected entity consolidation job"),
        (snapshot["replacement_candidates"][0]["candidate_doc_id"] == 134, "expected fresh replacement candidate"),
        ("must-not-leak" not in serialized, "secret token must not appear in maintenance snapshot"),
        ("Private User" not in serialized, "person entity must not appear in maintenance snapshot"),
    ]


def _exercise_maintenance_plan() -> List[tuple[bool, str]]:
    snapshot = build_maintenance_snapshot(
        [
            {
                "id": 135,
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
                "id": 136,
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
                "id": 137,
                "text": "Remote MCP access should be reviewed weekly.",
                "metadata": {"title": "Undated MCP note"},
            },
            {
                "id": 138,
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
    serialized = json.dumps(plan)
    job_types = {job["type"] for job in plan["jobs"]}
    review_jobs = [job for job in plan["jobs"] if job["execution_mode"] == "review_required"]
    return [
        (plan["found"] is True, "expected maintenance plan"),
        (plan["schedule"]["cron_hint"] == "0 3 */7 * *", "expected weekly cron hint"),
        ("recurring_freshness_scan" in job_types, "expected recurring freshness scan"),
        ("connector_sync_review" in job_types, "expected connector sync review"),
        ("deduplicate_documents" in job_types, "expected dedupe write plan"),
        ("consolidate_entities" in job_types, "expected entity consolidation write plan"),
        (all(job["requires_review"] for job in review_jobs), "write plans must require review"),
        (plan["governance"]["default_policy"] == "review_before_mutation", "expected review-before-mutation policy"),
        ("must-not-leak" not in serialized, "secret token must not appear in maintenance plan"),
        ("Private User" not in serialized, "person entity must not appear in maintenance plan"),
    ]


def _exercise_maintenance_apply() -> List[tuple[bool, str]]:
    snapshot = build_maintenance_snapshot(
        [
            {
                "id": 141,
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
                "id": 142,
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
                "id": 143,
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
    plan = build_maintenance_plan(snapshot, schedule_days=7, reference_date=dt.date(2026, 6, 1))
    batch = build_maintenance_apply_batch(plan)
    approved = build_maintenance_apply_batch(plan, approve=True)
    serialized = json.dumps(batch)
    targets = {item.get("target") for item in batch["items"]}
    statuses = {item.get("status") for item in batch["items"]}
    return [
        (batch["mode"] == "dry_run", "expected dry-run apply batch by default"),
        (batch["summary"]["total_item_count"] == plan["summary"]["job_count"], "expected one item per plan job"),
        (batch["summary"]["pending_review_count"] >= 3, "expected review-required maintenance writes"),
        ("ready" in statuses and "pending_review" in statuses, "expected ready read-only and pending review items"),
        ("documents" in targets, "expected document write target"),
        ("typed_memory" in targets, "expected typed-memory write target"),
        ("connector_sources" in targets, "expected connector sync target"),
        (approved["summary"]["approved_item_count"] == approved["summary"]["review_item_count"], "approve should mark review items"),
        (batch["governance"]["mutated_data"] is False, "apply batch builder must not mutate data"),
        ("must-not-leak" not in serialized, "secret token must not appear in maintenance apply batch"),
        ("Private User" not in serialized, "person entity must not appear in maintenance apply batch"),
        ("January remote MCP policy" not in serialized, "document titles must not appear in maintenance apply batch"),
    ]


def _exercise_maintenance_ledger() -> List[tuple[bool, str]]:
    snapshot = build_maintenance_snapshot(
        [
            {
                "id": 145,
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
                "id": 146,
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
    batch = build_maintenance_apply_batch(
        build_maintenance_plan(snapshot, reference_date=dt.date(2026, 6, 1)),
        approve=True,
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        ledger_path = Path(tmpdir) / "maintenance-ledger.jsonl"
        event = append_maintenance_ledger_event(
            batch,
            ledger_path=ledger_path,
            actor="bench",
            reference_datetime=dt.datetime(2026, 6, 1, 12, 0, 0),
        )
        ledger = load_maintenance_ledger(ledger_path)
        serialized = ledger_path.read_text(encoding="utf-8")
    return [
        (event["event_type"] == "maintenance_apply_batch_recorded", "expected ledger event type"),
        (ledger["summary"]["event_count"] == 1, "expected one ledger event"),
        (ledger["events"][0]["event_id"] == event["event_id"], "expected returned event"),
        (ledger["events"][0]["mutated_data"] is False, "ledger recording must not mutate data"),
        (ledger["privacy"]["pii_session_ids_exposed"] is False, "ledger must not expose PII session IDs"),
        (ledger["privacy"]["person_entities_exposed"] is False, "ledger must not expose person entities"),
        ("must-not-leak" not in serialized, "secret token must not appear in maintenance ledger"),
        ("Private User" not in serialized, "person entity must not appear in maintenance ledger"),
        ("January remote MCP policy" not in serialized, "document titles must not appear in maintenance ledger"),
    ]


def _exercise_memory_governance() -> List[tuple[bool, str]]:
    now = _reference_datetime()
    accepted = build_memory_record(
        kind="claim",
        content="Accepted memory should be visible.",
        workspace="bench",
        actor="bench",
        memory_key="claim:accepted",
        reference_datetime=now,
    )
    candidate = build_memory_record(
        kind="claim",
        content="Candidate memory should be hidden by default.",
        workspace="bench",
        actor="bench",
        memory_key="claim:candidate",
        state="candidate",
        reference_datetime=now,
    )
    expired = build_memory_record(
        kind="claim",
        content="Expired memory should be hidden by default.",
        workspace="bench",
        actor="bench",
        memory_key="claim:expired",
        ttl_days=1,
        reference_datetime=now - dt.timedelta(days=4),
    )
    results = filter_memory_records(
        [_doc(201, accepted), _doc(202, candidate), _doc(203, expired)],
        workspace="bench",
        reference_datetime=now,
    )
    return [
        ([result["memory_key"] for result in results] == ["claim:accepted"], "expected accepted non-expired memory only"),
    ]


def _exercise_memory_workspace_activity() -> List[tuple[bool, str]]:
    now = _reference_datetime()
    decision = build_memory_record(
        kind="decision",
        content="Authenticated remote access is required.",
        workspace="bench",
        actor="codex",
        memory_key="decision:remote-access",
        reference_datetime=now,
    )
    task = build_memory_record(
        kind="task",
        content="Rotate the connector token.",
        workspace="bench",
        actor="agent",
        memory_key="task:rotate-token",
        ttl_days=1,
        reference_datetime=now - dt.timedelta(days=3),
    )
    docs = [_doc(251, decision), _doc(252, task)]
    workspace_info = build_workspace_info(docs, workspace="bench", reference_datetime=now)
    activity = build_actor_activity(docs, workspace="bench", actor="agent", reference_datetime=now)
    serialized = json.dumps({"workspace_info": workspace_info, "activity": activity})
    return [
        (workspace_info["found"] is True, "expected workspace info"),
        (workspace_info["summary"]["total_record_count"] == 2, "expected two workspace records"),
        (workspace_info["summary"]["active_record_count"] == 1, "expected one active accepted record"),
        (workspace_info["summary"]["expired_record_count"] == 1, "expected one expired record"),
        (activity["found"] is True, "expected actor activity"),
        (activity["summary"]["event_count"] == 1, "expected one actor event"),
        (activity["events"][0]["memory_key"] == "task:rotate-token", "expected actor event memory key"),
        ("Rotate the connector token" not in serialized, "activity must not include raw content"),
    ]


def _exercise_memory_timeline() -> List[tuple[bool, str]]:
    now = _reference_datetime()
    first = build_memory_record(
        kind="decision",
        content="Start with local-only MCP.",
        workspace="bench",
        actor="bench",
        memory_key="decision:mcp-access",
        reference_datetime=now,
    )
    second = build_memory_record(
        kind="decision",
        content="Add authenticated remote MCP after local-only MCP.",
        workspace="bench",
        actor="bench",
        memory_key="decision:mcp-access",
        existing_records=[first],
        reference_datetime=now + dt.timedelta(hours=1),
    )
    timeline = build_memory_timeline(
        [_doc(401, first), _doc(402, second)],
        workspace="bench",
        memory_key="decision:mcp-access",
        reference_datetime=now + dt.timedelta(hours=2),
    )
    return [
        (timeline["found"] is True, "expected timeline"),
        (timeline["current_version"] == 2, "expected current version 2"),
        ([event["version"] for event in timeline["events"]] == [1, 2], "expected ordered events"),
        (all("content" not in version for version in timeline["versions"]), "timeline should omit full content"),
    ]


def _exercise_memory_graph() -> List[tuple[bool, str]]:
    now = _reference_datetime()
    decision = build_memory_record(
        kind="decision",
        content="Use authenticated remote access.",
        workspace="bench",
        actor="bench",
        memory_key="decision:remote-access",
        source_document_id=310,
        relations=[{"target_key": "task:private-tunnel", "type": "requires", "label": "private tunnel"}],
        reference_datetime=now,
    )
    task = build_memory_record(
        kind="task",
        content="Set up private tunnel for MCP.",
        workspace="bench",
        actor="bench",
        memory_key="task:private-tunnel",
        reference_datetime=now,
    )
    graph = build_memory_graph(
        [_doc(301, decision), _doc(302, task)],
        workspace="bench",
        reference_datetime=now,
    )
    edge_ids = {edge["id"] for edge in graph["edges"]}
    return [
        (graph["found"] is True, "expected memory graph"),
        ("memory:decision:remote-access->memory:task:private-tunnel:requires" in edge_ids, "expected relation edge"),
        ("memory:decision:remote-access->document:310:source_document" in edge_ids, "expected source document edge"),
    ]


def _exercise_remote_auth() -> List[tuple[bool, str]]:
    token = normalize_remote_api_key("ms_" + "a" * 40)
    headers = build_auth_headers(token)
    allowed = authorize_bearer_header(headers.get("Authorization"), token)
    missing = authorize_bearer_header(None, token)
    invalid = authorize_bearer_header("Bearer " + ("b" * len(token)), token)
    return [
        (headers.get("Authorization") == f"Bearer {token}", "expected bearer header"),
        (allowed.authorized is True and allowed.status_code == 200, "expected authorized decision"),
        (missing.authorized is False and missing.status_code == 401, "expected missing-token rejection"),
        (invalid.authorized is False and invalid.status_code == 403, "expected invalid-token rejection"),
    ]


def _exercise_agent_setup() -> List[tuple[bool, str]]:
    local_command = generate_setup("claude-code", mode="local")
    cursor_config = json.loads(generate_setup("cursor", mode="local"))
    gemini_config = json.loads(generate_setup("gemini-cli", mode="local"))
    codex_config = generate_setup("codex", mode="remote", server_name="mindsage-remote", base_url="https://mindsage.example.com")
    remote_config = json.loads(
        generate_setup(
            "claude-desktop",
            mode="remote",
            server_name="mindsage-remote",
            base_url="https://mindsage.example.com",
        )
    )

    def fake_urlopen(req, timeout):
        return _FakeResponse(200)

    doctor = run_doctor("http://localhost:8085", urlopen=fake_urlopen)
    serialized = json.dumps({
        "local_command": local_command,
        "cursor_config": cursor_config,
        "gemini_config": gemini_config,
        "codex_config": codex_config,
        "remote_config": remote_config,
        "doctor": doctor,
    })

    remote_server = remote_config["mcpServers"]["mindsage-remote"]
    return [
        ("claude mcp add mindsage-search" in local_command, "expected Claude Code command"),
        (
            cursor_config["mcpServers"]["mindsage-search"]["args"][:3]
            == ["-y", "mcp-remote", "http://localhost:8085/sse"],
            "expected mcp-remote local config",
        ),
        ("mcp-remote" in gemini_config["mcpServers"]["mindsage-search"]["args"], "expected Gemini CLI alias config"),
        ('[mcp_servers."mindsage-remote"]' in codex_config, "expected Codex config.toml block"),
        ("MCP_VECTOR_STORE_API_KEY" in codex_config, "expected Codex API key environment placeholder"),
        (remote_server["command"] == "python3", "expected stdio bridge command"),
        ("--url" in remote_server["args"], "expected remote URL argument"),
        (
            remote_server["env"] == {"MCP_VECTOR_STORE_API_KEY": "${MCP_VECTOR_STORE_API_KEY}"},
            "expected API key environment placeholder",
        ),
        (doctor["passed"] is True, "expected doctor checks to pass"),
        ("YOUR_32_PLUS_CHARACTER_TOKEN" not in serialized, "setup output must not include raw token placeholders"),
    ]


def _exercise_agent_pack() -> List[tuple[bool, str]]:
    pack = build_schema_pack()
    health = classify_path("/Users/alice/private/therapy-session-notes.txt")
    finance = classify_path("bank-statement.txt")
    chat = classify_path("chatgpt-conversation-export.json")
    pack_report = format_pack_report(pack)
    classification_report = format_classification_report(finance)
    serialized = json.dumps({
        "pack": pack,
        "health": health,
        "finance": finance,
        "chat": chat,
        "pack_report": pack_report,
        "classification_report": classification_report,
    })
    return [
        (pack["pack_id"] == "mindsage-personal-v1", "expected built-in schema pack id"),
        ("health" in {category["id"] for category in pack["document_categories"]}, "expected health category"),
        (health["category_id"] == "health", "expected health classification"),
        (health["path_exposed"] is False, "expected path to stay hidden"),
        (finance["recommended_memory_kind"] == "claim", "expected finance claim memory kind"),
        (chat["recommended_memory_kind"] == "summary", "expected AI chat summary memory kind"),
        ("MindSage schema pack mindsage-personal-v1" in pack_report, "expected stable pack report"),
        ("MindSage schema pack: finance -> claim" in classification_report, "expected stable classification report"),
        ("therapy-session-notes" not in serialized, "schema pack must not echo private filenames"),
        ("/Users/alice/private" not in serialized, "schema pack must not echo private paths"),
    ]


def _exercise_agent_pack_detect() -> List[tuple[bool, str]]:
    with tempfile.TemporaryDirectory(prefix="alice-private-") as tmpdir:
        root = Path(tmpdir)
        (root / "therapy-session-notes.txt").write_text(
            "Private therapist note with secret phrase do-not-read-me",
            encoding="utf-8",
        )
        (root / "bank-statement-2025.csv").write_text(
            "Account number should never appear",
            encoding="utf-8",
        )
        (root / "chatgpt-conversation-export.json").write_text(
            "{\"conversation\": \"private prompt text\"}",
            encoding="utf-8",
        )
        detection = detect_schema_candidates([str(root)])

    serialized = json.dumps(detection)
    categories = set(detection["summary"]["category_counts"])
    detection_report = format_detection_report(detection)
    return [
        (detection["scanned"]["file_count"] == 3, "expected three detected files"),
        ("health" in categories, "expected health category"),
        ("finance" in categories, "expected finance category"),
        ("ai_chat" in categories, "expected AI chat category"),
        (detection["summary"]["high_risk_file_count"] == 2, "expected high-risk count"),
        (detection["privacy"]["paths_exposed"] is False, "paths must not be exposed"),
        (detection["privacy"]["document_text_exposed"] is False, "document text must not be exposed"),
        ("alice-private" not in serialized, "root path must not be exposed"),
        ("therapy-session-notes" not in serialized, "file name must not be exposed"),
        ("do-not-read-me" not in serialized, "document content must not be exposed"),
        ("MindSage schema pack detection:" in detection_report, "expected stable detection report"),
    ]


def _exercise_agent_capture() -> List[tuple[bool, str]]:
    seen: Dict[str, Any] = {}

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        seen["headers"] = dict(req.header_items())
        seen["body"] = json.loads(req.data.decode("utf-8"))
        return _FakeResponse(201, b'{"success": true, "memory": {"memory_key": "decision:remote-mcp"}}')

    capture_request = build_capture_request(
        read_capture_text(["Use", "remote", "bearer", "auth."]),
        mode="memory",
        kind="decision",
        workspace="bench",
        actor="agent",
        memory_key="decision:remote-mcp",
        metadata={"pii_session_id": "must-not-leak"},
    )
    response = send_capture(
        capture_request,
        base_url="https://mindsage.example.com",
        api_key="ms_" + "g" * 30,
        urlopen=fake_urlopen,
    )
    report = format_capture_report(response, request_type="memory")
    dry_run = build_capture_dry_run(capture_request)
    dry_run_report = format_capture_report(dry_run, request_type="memory")
    serialized = json.dumps({
        "response": response,
        "report": report,
        "payload": capture_request["payload"],
        "dry_run": dry_run,
        "dry_run_report": dry_run_report,
    })
    return [
        (capture_request["endpoint"] == "/api/memory", "expected memory endpoint"),
        (capture_request["payload"]["kind"] == "decision", "expected typed-memory payload"),
        ("pii_session_id" not in capture_request["payload"]["metadata"], "PII session key must be removed from metadata"),
        (dry_run["dry_run"] is True, "expected capture dry-run preview"),
        (dry_run["payload_summary"]["content_bytes"] > 0, "expected capture dry-run content size"),
        ("Use remote bearer auth." not in json.dumps(dry_run), "capture dry-run must not echo captured text"),
        ("MindSage capture dry run: would store memory" in dry_run_report, "expected stable capture dry-run report"),
        (seen["url"] == "https://mindsage.example.com/api/memory", "expected clean capture URL"),
        (seen["headers"].get("Authorization") == "Bearer " + "ms_" + "g" * 30, "expected bearer auth header"),
        (response["status_code"] == 201 and response["ok"] is True, "expected successful capture response"),
        ("MindSage capture: stored memory decision:remote-mcp" == report, "expected stable capture report"),
        ("must-not-leak" not in serialized, "benchmark output must not leak PII session value"),
        ("Use remote bearer auth." in seen["body"]["content"], "expected captured content to be sent to server"),
    ]


def _exercise_agent_think() -> List[tuple[bool, str]]:
    seen: Dict[str, Any] = {}

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        seen["headers"] = dict(req.header_items())
        seen["body"] = json.loads(req.data.decode("utf-8"))
        return _FakeResponse(
            200,
            b'{"answer_brief": "Remote MCP should require bearer auth.", "citations": [{"doc_id": 3, "title": "Remote MCP policy", "score": 0.91}], "gaps": [], "freshness": {"status": "fresh"}, "privacy": {"pii_session_ids_exposed": false}}',
        )

    private_question = "Should remote MCP allow anonymous access?"
    think_request = build_think_request(
        read_question(private_question.split(" ")),
        top_k=4,
        min_score=0.2,
        freshness_days=45,
        include_gaps=True,
        max_excerpt_length=500,
    )
    response = send_think(
        think_request,
        base_url="https://mindsage.example.com",
        api_key="ms_" + "h" * 30,
        urlopen=fake_urlopen,
    )
    report = format_think_report(response)
    serialized_response = json.dumps({"response": response, "report": report})
    return [
        (think_request["endpoint"] == "/api/think", "expected think endpoint"),
        (think_request["payload"]["top_k"] == 4, "expected top_k passthrough"),
        (think_request["payload"]["include_gaps"] is True, "expected gap reporting enabled"),
        (seen["url"] == "https://mindsage.example.com/api/think", "expected clean think URL"),
        (seen["headers"].get("Authorization") == "Bearer " + "ms_" + "h" * 30, "expected bearer auth header"),
        (seen["body"]["question"] == private_question, "expected question to be sent to server"),
        (response["status_code"] == 200 and response["ok"] is True, "expected successful think response"),
        ("MindSage think: Remote MCP should require bearer auth." in report, "expected stable think report"),
        ("Remote MCP policy (#3, score 0.91)" in report, "expected compact cited source"),
        ("ms_" + "h" * 30 not in serialized_response, "think report must not leak bearer token"),
        (private_question not in report, "think report must not echo the private question"),
    ]


def _exercise_agent_import() -> List[tuple[bool, str]]:
    seen: Dict[str, Any] = {}

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        seen["headers"] = dict(req.header_items())
        seen["body"] = json.loads(req.data.decode("utf-8"))
        return _FakeResponse(200, b'{"success": true, "count": 2, "duplicates_skipped": 1, "document_ids": [21, 22]}')

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "runbook.md").write_text("# Runbook\nUse cited imports.\n", encoding="utf-8")
        (root / "decision.txt").write_text("Remote MCP uses bearer auth.\n", encoding="utf-8")
        documents = collect_import_documents(
            [str(root)],
            metadata={"source": "benchmark", "pii_session_id": "must-not-leak"},
            extensions={".md", ".txt"},
        )

    import_request = build_import_request(
        documents,
        skip_duplicates=True,
        extract_key_passages=False,
    )
    response = send_import(
        import_request,
        base_url="https://mindsage.example.com",
        api_key="ms_" + "i" * 30,
        urlopen=fake_urlopen,
    )
    report = format_import_report(response)
    dry_run = build_import_dry_run(import_request)
    dry_run_report = format_import_report(dry_run)
    serialized_response = json.dumps({"response": response, "report": report, "dry_run": dry_run, "dry_run_report": dry_run_report})
    return [
        (import_request["endpoint"] == "/api/documents/batch", "expected batch import endpoint"),
        (len(import_request["payload"]["documents"]) == 2, "expected two collected documents"),
        (import_request["payload"]["skip_duplicates"] is True, "expected duplicate skipping enabled"),
        (import_request["payload"]["extract_key_passages"] is False, "expected async extraction import mode"),
        ("pii_session_id" not in json.dumps(import_request["payload"]["documents"]), "PII session key must be removed from import metadata"),
        (dry_run["dry_run"] is True, "expected import dry-run preview"),
        (dry_run["payload_summary"]["document_count"] == 2, "expected import dry-run document count"),
        ("Remote MCP uses bearer auth." not in json.dumps(dry_run), "import dry-run must not echo imported text"),
        ("MindSage import dry run: would import 2 documents" in dry_run_report, "expected stable import dry-run report"),
        (seen["url"] == "https://mindsage.example.com/api/documents/batch", "expected clean import URL"),
        (seen["headers"].get("Authorization") == "Bearer " + "ms_" + "i" * 30, "expected bearer auth header"),
        (len(seen["body"]["documents"]) == 2, "expected import documents to be sent to server"),
        (response["status_code"] == 200 and response["ok"] is True, "expected successful import response"),
        (report == "MindSage import: imported 2 documents, skipped 1 duplicate", "expected stable import report"),
        ("ms_" + "i" * 30 not in serialized_response, "import report must not leak bearer token"),
        ("Remote MCP uses bearer auth." not in report, "import report must not echo imported text"),
    ]


def _exercise_agent_search() -> List[tuple[bool, str]]:
    seen: Dict[str, Any] = {}

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        seen["headers"] = dict(req.header_items())
        seen["body"] = json.loads(req.data.decode("utf-8"))
        return _FakeResponse(
            200,
            b'{"results": [{"id": 31, "excerpt": "Remote MCP requires bearer auth before access.", "score": 0.94, "metadata": {"title": "Remote MCP policy"}}, {"id": 32, "excerpt": "Use private tunnels for demos.", "score": 0.81, "metadata": {"filename": "demo-runbook.md"}}]}',
        )

    private_query = "Find private remote MCP auth policy"
    search_request = build_search_request(
        read_query(private_query.split(" ")),
        top_k=2,
        min_score=0.3,
        extract_passages=True,
        max_excerpt_length=350,
        context="llm",
    )
    response = send_search(
        search_request,
        base_url="https://mindsage.example.com",
        api_key="ms_" + "j" * 30,
        urlopen=fake_urlopen,
    )
    report = format_search_report(response)
    serialized_response = json.dumps({"response": response, "report": report})
    return [
        (search_request["endpoint"] == "/api/search/enhanced", "expected enhanced search endpoint"),
        (search_request["payload"]["top_k"] == 2, "expected top_k passthrough"),
        (search_request["payload"]["extract_passages"] is True, "expected passage extraction enabled"),
        (search_request["payload"]["context"] == "llm", "expected LLM-safe metadata context"),
        (seen["url"] == "https://mindsage.example.com/api/search/enhanced", "expected clean search URL"),
        (seen["headers"].get("Authorization") == "Bearer " + "ms_" + "j" * 30, "expected bearer auth header"),
        (seen["body"]["query"] == private_query, "expected query to be sent to server"),
        (response["status_code"] == 200 and response["ok"] is True, "expected successful search response"),
        ("MindSage search: 2 results" in report, "expected stable search count"),
        ("Remote MCP policy (#31, score 0.94)" in report, "expected compact ranked result"),
        ("Remote MCP requires bearer auth before access." in report, "expected passage-sized evidence"),
        ("ms_" + "j" * 30 not in serialized_response, "search report must not leak bearer token"),
        (private_query not in report, "search report must not echo the private query"),
    ]


def _exercise_agent_schema() -> List[tuple[bool, str]]:
    stdout = io.StringIO()
    exit_code = schema_main(
        [
            "--json",
            "--section",
            "mcp",
            "--base-url",
            "https://mindsage.example.com/",
            "--server-name",
            "bench-memory",
        ],
        stdout=stdout,
    )
    mcp_schema = json.loads(stdout.getvalue())
    full_schema = build_agent_schema(base_url="https://mindsage.example.com/", server_name="bench-memory")
    report = format_schema_report(full_schema)
    tool_names = {tool["name"] for tool in full_schema["mcp"]["tools"]}
    command_names = {command["name"] for command in full_schema["cli"]["commands"]}
    endpoints = {endpoint["path"] for endpoint in full_schema["rest"]["endpoints"]}
    serialized = json.dumps({"schema": full_schema, "mcp_schema": mcp_schema, "report": report})
    return [
        (exit_code == 0, "expected schema CLI success"),
        (mcp_schema["mcp"]["sse_url"] == "https://mindsage.example.com/sse", "expected clean schema URL"),
        (mcp_schema["mcp"]["server_name"] == "bench-memory", "expected server name passthrough"),
        ("think" in tool_names and "enhanced_search" in tool_names, "expected read-path MCP tools"),
        ("write_memory" in tool_names and "memory_graph" in tool_names, "expected typed-memory MCP tools"),
        ("agent:schema" in command_names and "agent:search" in command_names, "expected agent CLI commands"),
        ("/api/think" in endpoints and "/api/search/enhanced" in endpoints, "expected reasoning/search endpoints"),
        ("MindSage agent schema: version 1" in report, "expected stable schema report"),
        ("MCP_VECTOR_STORE_API_KEY=" not in serialized, "schema must not print env assignments with secrets"),
        ("YOUR_32_PLUS_CHARACTER_TOKEN" not in serialized, "schema must not include raw token placeholders"),
    ]


def _exercise_agent_health() -> List[tuple[bool, str]]:
    stdout = io.StringIO()
    exit_code = health_main(
        [
            "--json",
            "--reference-date",
            "2026-06-01",
            "--freshness-days",
            "90",
        ],
        stdout=stdout,
    )
    cli_report = json.loads(stdout.getvalue())
    fixture_report = build_agent_health(
        [
            {
                "id": 151,
                "text": "Remote MCP access requires bearer auth and a private tunnel.",
                "metadata": {
                    "title": "January remote MCP policy",
                    "date": "2026-01-01",
                    "structured_metadata": {
                        "organizations": ["MindSage"],
                        "technologies": ["MCP"],
                        "persons": ["Private User"],
                    },
                    "pii_session_id": "must-not-leak",
                },
            },
            {
                "id": 152,
                "text": "Remote MCP access requires bearer auth and a private tunnel.",
                "metadata": {"title": "January remote MCP policy copy", "date": "2026-01-05"},
            },
            {
                "id": 153,
                "text": "Remote MCP access requires bearer auth, a private tunnel, and audit logs.",
                "metadata": {"title": "May remote MCP policy", "date": "2026-05-31"},
            },
        ],
        reference_date=dt.date(2026, 6, 1),
        freshness_days=30,
    )
    report_text = format_agent_health_report(fixture_report)
    serialized = json.dumps({"cli": cli_report, "fixture": fixture_report, "report": report_text})
    gate_ids = {gate["id"] for gate in fixture_report["gates"]}
    return [
        (exit_code == 0, "expected health CLI success"),
        (cli_report["snapshot_summary"]["document_count"] >= 25, "expected synthetic corpus health coverage"),
        (fixture_report["health_score"] < 100, "expected maintenance issues to lower health score"),
        (fixture_report["status"] in {"good", "needs_attention", "critical"}, "expected actionable health status"),
        ({"freshness", "duplicates", "replacement_candidates"}.issubset(gate_ids), "expected core health gates"),
        ("MindSage agent health:" in report_text, "expected stable health report"),
        ("npm run maintenance:snapshot" in fixture_report["recommended_commands"], "expected maintenance recommendation"),
        ("must-not-leak" not in serialized, "health report must not leak PII session values"),
        ("Private User" not in serialized, "health report must not expose person entities"),
    ]


def _exercise_fixture_corpus_eval() -> List[tuple[bool, str]]:
    report = run_fixture_corpus_evals()
    serialized = json.dumps(report)
    return [
        (report["summary"]["failed"] == 0, "expected fixture corpus evals to pass"),
        (report["corpus"]["document_count"] >= 25, "expected tracked synthetic corpus"),
        ("don.jones.1987@gmail.com" not in serialized, "email fixture value must be redacted"),
        ("(408) 555-7834" not in serialized, "phone fixture value must be redacted"),
        ("4521-8834-9912" not in serialized, "account fixture value must be redacted"),
    ]


def _doc(doc_id: int, record: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": doc_id,
        "text": record["text"],
        "metadata": record["metadata"],
        "score": 1.0,
    }


def _reference_datetime() -> dt.datetime:
    return dt.datetime(2026, 6, 1, 12, 0, tzinfo=dt.timezone.utc)


class _FakeResponse:
    def __init__(self, status: int, body: bytes = b""):
        self.status = status
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self._body


if __name__ == "__main__":
    raise SystemExit(main())
