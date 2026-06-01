"""Replayable, dependency-light evals for MindSage agent memory tools."""

from __future__ import annotations

import argparse
import datetime as dt
import json
from typing import Any, Callable, Dict, List

try:
    from .memory_tool import (
        build_actor_activity,
        build_memory_graph,
        build_memory_record,
        build_memory_timeline,
        build_workspace_info,
        filter_memory_records,
    )
    from .think_tool import build_think_response
except ImportError:  # Allows direct file loading in lightweight unit tests.
    from memory_tool import (
        build_actor_activity,
        build_memory_graph,
        build_memory_record,
        build_memory_timeline,
        build_workspace_info,
        filter_memory_records,
    )
    from think_tool import build_think_response


EvalCase = Callable[[], Dict[str, Any]]


def run_agent_memory_evals() -> Dict[str, Any]:
    """Run deterministic evals covering the core agent memory surfaces."""

    cases = [
        _eval_think_citations_privacy(),
        _eval_think_citation_graph(),
        _eval_think_entity_graph(),
        _eval_think_maintenance_actions(),
        _eval_memory_governance_defaults(),
        _eval_memory_workspace_activity(),
        _eval_memory_graph_relations(),
        _eval_memory_timeline_versions(),
    ]
    passed = sum(1 for case in cases if case["passed"])
    failed = len(cases) - passed
    return {
        "suite": "mindsage-agent-memory",
        "version": 1,
        "summary": {
            "total": len(cases),
            "passed": passed,
            "failed": failed,
            "score": round(passed / len(cases), 4) if cases else 0.0,
        },
        "cases": cases,
    }


def format_eval_report(report: Dict[str, Any]) -> str:
    """Format the eval report for humans and CI logs."""

    summary = report["summary"]
    lines = [
        f"MindSage agent evals: {summary['passed']}/{summary['total']} passed (score={summary['score']:.4f})"
    ]
    for case in report["cases"]:
        status = "PASS" if case["passed"] else "FAIL"
        lines.append(f"{status} {case['id']} - {case['description']}")
        if case.get("failures"):
            for failure in case["failures"]:
                lines.append(f"  - {failure}")
    return "\n".join(lines)


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run MindSage agent memory evals")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text")
    args = parser.parse_args(argv)

    report = run_agent_memory_evals()
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(format_eval_report(report))
    return 0 if report["summary"]["failed"] == 0 else 1


def _eval_think_citations_privacy() -> Dict[str, Any]:
    response = build_think_response(
        "What did we decide about remote access?",
        [
            {
                "id": 101,
                "excerpt": "Remote access should require an authenticated private tunnel before public exposure.",
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

    return _case(
        "think.citations_privacy",
        "think returns cited, fresh, PII-safe reasoning context",
        [
            (len(response["citations"]) == 2, "expected two citations"),
            (response["privacy"]["pii_session_ids_exposed"] is False, "PII session IDs must not be exposed"),
            ("remote" in response["coverage"]["query_terms_found"], "expected query-term coverage for remote"),
            (response["freshness"]["stale_source_count"] == 0, "fresh sources should not be marked stale"),
        ],
    )


def _eval_think_citation_graph() -> Dict[str, Any]:
    response = build_think_response(
        "Should remote MCP access be enabled?",
        [
            {
                "id": 111,
                "excerpt": "Remote MCP access should be enabled only behind authenticated private tunnels.",
                "score": 0.9,
                "topics": ["remote mcp", "private tunnel"],
                "metadata": {
                    "title": "Remote MCP access decision",
                    "created_at": "2026-05-30T12:00:00Z",
                },
            },
            {
                "id": 112,
                "excerpt": "Remote MCP access should be disabled when no private tunnel exists.",
                "score": 0.85,
                "primary_topic": "remote mcp",
                "metadata": {
                    "title": "Remote MCP safety policy",
                    "created_at": "2026-05-31T12:00:00Z",
                },
            },
        ],
        reference_date=dt.date(2026, 6, 1),
    )
    graph = response["citation_graph"]
    node_ids = {node["id"] for node in graph["nodes"]}
    edge_ids = {edge["id"] for edge in graph["edges"]}

    return _case(
        "think.citation_graph",
        "think returns a cited-answer graph linking answers, sources, concepts, and contradictions",
        [
            (graph["found"] is True, "expected citation graph to be found"),
            (graph["answer_node_id"] in node_ids, "expected answer node"),
            ("citation:111" in node_ids, "expected first citation node"),
            ("citation:112" in node_ids, "expected second citation node"),
            ("concept:remote-mcp" in node_ids, "expected remote MCP concept node"),
            (f"{graph['answer_node_id']}->citation:111:cites" in edge_ids, "expected answer-to-citation edge"),
            ("citation:111->concept:remote-mcp:mentions" in edge_ids, "expected citation-to-concept edge"),
            ("citation:111->citation:112:contradicts" in edge_ids, "expected contradiction edge"),
        ],
    )


def _eval_think_entity_graph() -> Dict[str, Any]:
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
    edge_ids = {edge["id"] for edge in graph["edges"]}
    serialized = json.dumps(response)

    return _case(
        "think.entity_graph",
        "think returns PII-safe entity links across cited evidence",
        [
            (graph["found"] is True, "expected entity graph to be found"),
            ("entity:organization:nvidia" in node_ids, "expected NVIDIA organization node"),
            ("entity:location:san-jose" in node_ids, "expected San Jose location node"),
            ("entity:technology:jetson-orin" in node_ids, "expected Jetson Orin technology node"),
            ("citation:115->entity:organization:nvidia:mentions_entity" in edge_ids, "expected citation-to-entity edge"),
            ("entity:organization:nvidia->entity:location:san-jose:co_occurs" in edge_ids, "expected entity co-occurrence edge"),
            ("Jensen Huang" not in serialized, "person entity should be redacted from LLM-facing graph"),
            ("must-not-leak" not in serialized, "PII session ID must not be exposed"),
        ],
    )


def _eval_think_maintenance_actions() -> Dict[str, Any]:
    response = build_think_response(
        "Should remote MCP access be enabled?",
        [
            {
                "id": 121,
                "excerpt": "Remote MCP access should be enabled for internal demos.",
                "score": 0.66,
                "topics": ["remote mcp"],
                "metadata": {
                    "title": "Old remote MCP note",
                    "created_at": "2026-01-01T12:00:00Z",
                    "pii_session_id": "must-not-leak",
                },
            },
            {
                "id": 122,
                "excerpt": "Remote MCP access should be disabled unless bearer auth is configured.",
                "score": 0.88,
                "topics": ["remote mcp"],
                "metadata": {
                    "title": "Fresh remote MCP policy",
                    "created_at": "2026-05-31T12:00:00Z",
                },
            },
            {
                "id": 123,
                "excerpt": "Remote MCP access needs an operator-reviewed access log.",
                "score": 0.72,
                "topics": ["remote mcp"],
                "metadata": {
                    "title": "Undated access-log note",
                },
            },
        ],
        freshness_days=30,
        reference_date=dt.date(2026, 6, 1),
    )
    maintenance = response["maintenance"]
    action_types = {action["type"] for action in maintenance["actions"]}

    return _case(
        "think.maintenance_actions",
        "think returns actionable citation refresh and repair guidance",
        [
            (maintenance["found"] is True, "expected maintenance actions"),
            ("refresh_stale_citation" in action_types, "expected stale citation refresh action"),
            ("add_source_date" in action_types, "expected undated source action"),
            ("resolve_contradiction" in action_types, "expected contradiction resolution action"),
            (maintenance["privacy"]["pii_session_ids_exposed"] is False, "PII session IDs must not be exposed"),
            (maintenance["maintenance_graph"]["found"] is True, "expected maintenance graph"),
        ],
    )


def _eval_memory_governance_defaults() -> Dict[str, Any]:
    now = _reference_datetime()
    accepted = build_memory_record(
        kind="claim",
        content="Accepted memory should be visible.",
        workspace="eval",
        actor="eval",
        memory_key="claim:accepted",
        reference_datetime=now,
    )
    candidate = build_memory_record(
        kind="claim",
        content="Candidate memory should be hidden by default.",
        workspace="eval",
        actor="eval",
        memory_key="claim:candidate",
        state="candidate",
        reference_datetime=now,
    )
    expired = build_memory_record(
        kind="claim",
        content="Expired memory should be hidden by default.",
        workspace="eval",
        actor="eval",
        memory_key="claim:expired",
        ttl_days=1,
        reference_datetime=now - dt.timedelta(days=4),
    )

    results = filter_memory_records(
        [
            _doc(201, accepted),
            _doc(202, candidate),
            _doc(203, expired),
        ],
        workspace="eval",
        reference_datetime=now,
    )

    return _case(
        "memory.governance_defaults",
        "typed memory defaults to accepted and non-expired records",
        [
            ([result["memory_key"] for result in results] == ["claim:accepted"], "expected only accepted non-expired memory"),
        ],
    )


def _eval_memory_workspace_activity() -> Dict[str, Any]:
    now = _reference_datetime()
    decision = build_memory_record(
        kind="decision",
        content="Authenticated remote access is required.",
        workspace="eval",
        actor="codex",
        memory_key="decision:remote-access",
        reference_datetime=now,
    )
    task = build_memory_record(
        kind="task",
        content="Rotate the connector token.",
        workspace="eval",
        actor="agent",
        memory_key="task:rotate-token",
        ttl_days=1,
        reference_datetime=now - dt.timedelta(days=3),
    )

    docs = [_doc(251, decision), _doc(252, task)]
    workspace_info = build_workspace_info(docs, workspace="eval", reference_datetime=now)
    activity = build_actor_activity(docs, workspace="eval", actor="agent", reference_datetime=now)
    serialized = json.dumps({"workspace_info": workspace_info, "activity": activity})

    return _case(
        "memory.workspace_activity",
        "typed memory exposes workspace summary and actor audit activity without content",
        [
            (workspace_info["found"] is True, "expected workspace info"),
            (workspace_info["summary"]["total_record_count"] == 2, "expected two workspace records"),
            (workspace_info["summary"]["active_record_count"] == 1, "expected one active accepted record"),
            (workspace_info["summary"]["expired_record_count"] == 1, "expected one expired record"),
            (activity["found"] is True, "expected actor activity"),
            (activity["summary"]["event_count"] == 1, "expected one actor event"),
            (activity["events"][0]["memory_key"] == "task:rotate-token", "expected actor event memory key"),
            ("Rotate the connector token" not in serialized, "activity must not include raw content"),
        ],
    )


def _eval_memory_graph_relations() -> Dict[str, Any]:
    now = _reference_datetime()
    decision = build_memory_record(
        kind="decision",
        content="Use authenticated remote access.",
        workspace="eval",
        actor="eval",
        memory_key="decision:remote-access",
        source_document_id=310,
        relations=[{"target_key": "task:private-tunnel", "type": "requires", "label": "private tunnel"}],
        reference_datetime=now,
    )
    task = build_memory_record(
        kind="task",
        content="Set up private tunnel for MCP.",
        workspace="eval",
        actor="eval",
        memory_key="task:private-tunnel",
        reference_datetime=now,
    )

    graph = build_memory_graph(
        [_doc(301, decision), _doc(302, task)],
        workspace="eval",
        reference_datetime=now,
    )
    edge_ids = {edge["id"] for edge in graph["edges"]}
    node_ids = {node["id"] for node in graph["nodes"]}

    return _case(
        "memory.graph_relations",
        "typed memory graph links relations and source documents",
        [
            ("memory:decision:remote-access" in node_ids, "expected decision node"),
            ("memory:task:private-tunnel" in node_ids, "expected task node"),
            ("document:310" in node_ids, "expected source document node"),
            (
                "memory:decision:remote-access->memory:task:private-tunnel:requires" in edge_ids,
                "expected declared relation edge",
            ),
            (
                "memory:decision:remote-access->document:310:source_document" in edge_ids,
                "expected source document edge",
            ),
        ],
    )


def _eval_memory_timeline_versions() -> Dict[str, Any]:
    now = _reference_datetime()
    first = build_memory_record(
        kind="decision",
        content="Start with local-only MCP.",
        workspace="eval",
        actor="eval",
        memory_key="decision:mcp-access",
        reference_datetime=now,
    )
    second = build_memory_record(
        kind="decision",
        content="Add authenticated remote MCP after local-only MCP.",
        workspace="eval",
        actor="eval",
        memory_key="decision:mcp-access",
        existing_records=[first],
        reference_datetime=now + dt.timedelta(hours=1),
    )

    timeline = build_memory_timeline(
        [_doc(401, first), _doc(402, second)],
        workspace="eval",
        memory_key="decision:mcp-access",
        reference_datetime=now + dt.timedelta(hours=2),
    )

    return _case(
        "memory.timeline_versions",
        "memory timeline preserves versioned audit history",
        [
            (timeline["found"] is True, "expected timeline to be found"),
            (timeline["current_version"] == 2, "expected current version 2"),
            ([event["version"] for event in timeline["events"]] == [1, 2], "expected ordered version events"),
            (all("content" not in version for version in timeline["versions"]), "timeline should omit full content by default"),
        ],
    )


def _case(case_id: str, description: str, checks: List[tuple[bool, str]]) -> Dict[str, Any]:
    failures = [message for passed, message in checks if not passed]
    return {
        "id": case_id,
        "description": description,
        "passed": not failures,
        "failures": failures,
    }


def _doc(doc_id: int, record: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": doc_id,
        "text": record["text"],
        "metadata": record["metadata"],
        "score": 1.0,
    }


def _reference_datetime() -> dt.datetime:
    return dt.datetime(2026, 6, 1, 12, 0, tzinfo=dt.timezone.utc)


if __name__ == "__main__":
    raise SystemExit(main())
