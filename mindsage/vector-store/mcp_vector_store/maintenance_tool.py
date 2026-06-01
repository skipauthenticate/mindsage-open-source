"""Actionable citation maintenance reports for MindSage agent tools."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence


PII_SESSION_KEYS = {"pii_session_id", "piiSessionId"}
APPLY_PREVIEW_DENYLIST = {
    "absolute_path",
    "body",
    "content",
    "excerpt",
    "file",
    "file_name",
    "filename",
    "path",
    "raw",
    "text",
    "title",
    "titles",
}
SAFE_ENTITY_FIELDS = {
    "organizations": "organization",
    "locations": "location",
    "technologies": "technology",
    "activities": "activity",
    "dates": "date",
}
PERSON_ENTITY_FIELDS = {"person", "persons", "people"}
DEFAULT_CORPUS_DIR = Path(__file__).resolve().parents[2] / "data" / "test-pii-docs"


def build_maintenance_snapshot(
    documents: Sequence[Any],
    *,
    reference_date: Optional[dt.date] = None,
    freshness_days: int = 90,
) -> Dict[str, Any]:
    """Build a background maintenance snapshot for stored documents."""

    today = reference_date or dt.date.today()
    normalized_documents = [
        _maintenance_document(document, index)
        for index, document in enumerate(documents, start=1)
    ]
    stale_sources = [
        document for document in normalized_documents
        if document["date"] and _is_stale(document, freshness_days, today)
    ]
    undated_sources = [
        document for document in normalized_documents
        if not document["date"]
    ]
    duplicate_groups = _duplicate_groups(normalized_documents)
    entity_consolidations, redacted_person_count = _entity_consolidation_candidates(normalized_documents)
    replacement_candidates = _snapshot_replacement_candidates(
        stale_sources=stale_sources,
        documents=normalized_documents,
        reference_date=today,
        freshness_days=freshness_days,
    )

    jobs = _snapshot_jobs(
        stale_sources=stale_sources,
        undated_sources=undated_sources,
        duplicate_groups=duplicate_groups,
        entity_consolidations=entity_consolidations,
        replacement_candidates=replacement_candidates,
    )
    snapshot = {
        "found": bool(jobs),
        "priority": _priority(jobs),
        "summary": {
            "document_count": len(normalized_documents),
            "stale_source_count": len(stale_sources),
            "undated_source_count": len(undated_sources),
            "duplicate_group_count": len(duplicate_groups),
            "entity_consolidation_count": len(entity_consolidations),
            "replacement_candidate_count": len(replacement_candidates),
        },
        "jobs": jobs,
        "stale_sources": [
            _snapshot_source(source, reference_date=today)
            for source in stale_sources
        ],
        "undated_sources": [
            _snapshot_source(source, reference_date=today)
            for source in undated_sources
        ],
        "duplicate_groups": duplicate_groups,
        "entity_consolidation_candidates": entity_consolidations,
        "replacement_candidates": replacement_candidates,
        "privacy": {
            "llm_context": "redacted",
            "pii_session_ids_exposed": False,
            "person_entities_exposed": False,
            "redacted_person_entity_count": redacted_person_count,
        },
        "governance": {
            "source": "maintenance.snapshot",
            "content": "redacted_document_metadata_only",
            "default_policy": "refresh_dedupe_and_consolidate_before_reuse",
            "freshness_days": freshness_days,
        },
    }
    snapshot["privacy"]["pii_session_ids_exposed"] = _contains_pii_session_key(snapshot)
    snapshot["privacy"]["person_entities_exposed"] = _contains_person_entity(snapshot)
    return snapshot


def format_maintenance_snapshot_report(snapshot: Dict[str, Any]) -> str:
    """Format a background maintenance snapshot for humans and CI logs."""

    summary = snapshot["summary"]
    lines = [
        "MindSage maintenance snapshot: "
        f"{snapshot['priority']} priority "
        f"(documents={summary['document_count']}, stale={summary['stale_source_count']}, "
        f"undated={summary['undated_source_count']}, duplicate_groups={summary['duplicate_group_count']}, "
        f"entity_consolidations={summary['entity_consolidation_count']})"
    ]
    for job in snapshot["jobs"]:
        lines.append(
            f"JOB {job['type']} - {job['severity']} "
            f"({job['item_count']} items, suggested_tool={job['suggested_tool']})"
        )
    return "\n".join(lines)


def build_maintenance_plan(
    snapshot: Dict[str, Any],
    *,
    schedule_days: int = 7,
    reference_date: Optional[dt.date] = None,
) -> Dict[str, Any]:
    """Turn a maintenance snapshot into a schedulable, reviewable job plan."""

    cadence_days = max(int(schedule_days or 7), 1)
    today = reference_date or dt.date.today()
    snapshot_summary = snapshot.get("summary", {})
    snapshot_jobs = list(snapshot.get("jobs") or [])
    jobs = [
        _maintenance_plan_job(
            job_type="recurring_freshness_scan",
            execution_mode="read_only",
            severity="medium" if snapshot_jobs else "low",
            reason="Re-run maintenance health checks on a fixed cadence.",
            command=(
                "npm run maintenance:snapshot -- "
                f"--reference-date {today.isoformat()} --freshness-days "
                f"{snapshot.get('governance', {}).get('freshness_days', 90)}"
            ),
            source_job_ids=[],
            item_count=int(snapshot_summary.get("document_count") or 0),
        )
    ]

    connector_sources = _connector_sources(snapshot)
    if connector_sources:
        jobs.append(_maintenance_plan_job(
            job_type="connector_sync_review",
            execution_mode="review_required",
            severity="medium",
            reason="Connector-backed sources should be refreshed before stale evidence is reused.",
            command="npm run agent:health -- --json",
            source_job_ids=[],
            item_count=len(connector_sources),
            write_intent={
                "target": "connector_sources",
                "operation": "sync_after_operator_review",
                "source_count": len(connector_sources),
                "sources": connector_sources,
            },
        ))

    for snapshot_job in snapshot_jobs:
        jobs.append(_maintenance_plan_job(
            job_type=str(snapshot_job.get("type") or "maintenance_job"),
            execution_mode="review_required",
            severity=str(snapshot_job.get("severity") or "medium"),
            reason=str(snapshot_job.get("reason") or "Review and apply maintenance change."),
            command=_plan_command_for_snapshot_job(snapshot_job),
            source_job_ids=[snapshot_job.get("id")] if snapshot_job.get("id") else [],
            item_count=int(snapshot_job.get("item_count") or 0),
            write_intent=_write_intent_for_snapshot_job(snapshot_job, snapshot),
        ))

    plan = {
        "found": bool(jobs),
        "priority": _priority(jobs),
        "summary": {
            "job_count": len(jobs),
            "review_required_count": sum(1 for job in jobs if job["requires_review"]),
            "read_only_count": sum(1 for job in jobs if not job["requires_review"]),
            "source_snapshot_priority": snapshot.get("priority", "none"),
            "source_document_count": int(snapshot_summary.get("document_count") or 0),
        },
        "schedule": {
            "cadence_days": cadence_days,
            "cron_hint": f"0 3 */{cadence_days} * *",
            "reference_date": today.isoformat(),
        },
        "jobs": jobs,
        "privacy": {
            "llm_context": "redacted",
            "pii_session_ids_exposed": False,
            "person_entities_exposed": False,
        },
        "governance": {
            "source": "maintenance.plan",
            "content": "redacted_snapshot_metadata_only",
            "default_policy": "review_before_mutation",
        },
    }
    plan["privacy"]["pii_session_ids_exposed"] = _contains_pii_session_key(plan)
    plan["privacy"]["person_entities_exposed"] = _contains_person_entity(plan)
    return plan


def format_maintenance_plan_report(plan: Dict[str, Any]) -> str:
    """Format a maintenance plan for humans and CI logs."""

    summary = plan["summary"]
    schedule = plan["schedule"]
    lines = [
        "MindSage maintenance plan: "
        f"{plan['priority']} priority "
        f"(jobs={summary['job_count']}, review_required={summary['review_required_count']}, "
        f"read_only={summary['read_only_count']}, cadence={schedule['cadence_days']}d)"
    ]
    for job in plan["jobs"]:
        lines.append(
            f"JOB {job['type']} - {job['execution_mode']} "
            f"({job['item_count']} items, command={job['command']})"
        )
    return "\n".join(lines)


def build_maintenance_apply_batch(
    plan: Dict[str, Any],
    *,
    approve: bool = False,
) -> Dict[str, Any]:
    """Turn a maintenance plan into a reviewable, non-mutating apply batch."""

    jobs = list(plan.get("jobs") or [])
    items = [
        _maintenance_apply_item(job, execution_order=index, approve=approve)
        for index, job in enumerate(jobs, start=1)
    ]
    review_item_count = sum(1 for item in items if item["requires_review"])
    approved_item_count = sum(1 for item in items if item["status"] == "approved_for_execution")
    pending_review_count = sum(1 for item in items if item["status"] == "pending_review")
    read_only_item_count = sum(1 for item in items if not item["requires_review"])
    batch = {
        "found": bool(items),
        "mode": "approved" if approve else "dry_run",
        "priority": _priority(items),
        "summary": {
            "total_item_count": len(items),
            "review_item_count": review_item_count,
            "read_only_item_count": read_only_item_count,
            "approved_item_count": approved_item_count,
            "pending_review_count": pending_review_count,
            "source_plan_job_count": int(plan.get("summary", {}).get("job_count") or len(jobs)),
        },
        "items": items,
        "privacy": {
            "llm_context": "redacted",
            "pii_session_ids_exposed": False,
            "person_entities_exposed": False,
            "raw_document_text_exposed": False,
            "filenames_or_paths_exposed": False,
        },
        "governance": {
            "source": "maintenance.apply",
            "content": "redacted_plan_metadata_only",
            "default_policy": "dry_run_unless_approved",
            "mutated_data": False,
            "approval_required_for_mutation": True,
            "executor_required": True,
        },
    }
    batch["privacy"]["pii_session_ids_exposed"] = _contains_pii_session_key(batch)
    batch["privacy"]["person_entities_exposed"] = _contains_person_entity(batch)
    return batch


def format_maintenance_apply_report(batch: Dict[str, Any]) -> str:
    """Format a maintenance apply batch for humans and CI logs."""

    summary = batch["summary"]
    lines = [
        "MindSage maintenance apply batch: "
        f"{batch['priority']} priority "
        f"(mode={batch['mode']}, items={summary['total_item_count']}, "
        f"review={summary['review_item_count']}, approved={summary['approved_item_count']}, "
        f"pending={summary['pending_review_count']})"
    ]
    for item in batch["items"]:
        lines.append(
            f"ITEM {item['job_type']} - {item['status']} "
            f"(target={item['target']}, operation={item['operation']})"
        )
    return "\n".join(lines)


def append_maintenance_ledger_event(
    batch: Dict[str, Any],
    *,
    ledger_path: Path | str,
    actor: str = "operator",
    reference_datetime: Optional[dt.datetime] = None,
) -> Dict[str, Any]:
    """Append a redacted maintenance apply audit event to a JSONL ledger."""

    path = Path(ledger_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    event = _maintenance_ledger_event(
        batch,
        actor=actor,
        reference_datetime=reference_datetime,
    )
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")
    return event


def load_maintenance_ledger(ledger_path: Path | str, *, limit: int = 50) -> Dict[str, Any]:
    """Load a redacted maintenance ledger summary and recent events."""

    path = Path(ledger_path)
    events: List[Dict[str, Any]] = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            events.append(_sanitize_metadata(json.loads(line)))

    recent_events = events[-max(int(limit or 50), 1):]
    last_event = events[-1] if events else {}
    ledger = {
        "found": bool(events),
        "summary": {
            "event_count": len(events),
            "returned_event_count": len(recent_events),
            "last_event_id": last_event.get("event_id"),
            "last_recorded_at": last_event.get("recorded_at"),
            "last_mode": last_event.get("mode"),
            "approved_item_count": sum(int(event.get("approved_item_count") or 0) for event in events),
            "pending_review_count": sum(int(event.get("pending_review_count") or 0) for event in events),
        },
        "events": recent_events,
        "privacy": {
            "llm_context": "redacted",
            "pii_session_ids_exposed": False,
            "person_entities_exposed": False,
            "raw_document_text_exposed": False,
            "filenames_or_paths_exposed": False,
        },
        "governance": {
            "source": "maintenance.ledger",
            "content": "redacted_apply_batch_audit_events",
            "append_only": True,
            "mutated_data": False,
        },
    }
    ledger["privacy"]["pii_session_ids_exposed"] = _contains_pii_session_key(ledger)
    ledger["privacy"]["person_entities_exposed"] = _contains_person_entity(ledger)
    return ledger


def format_maintenance_ledger_report(ledger: Dict[str, Any]) -> str:
    """Format a maintenance ledger summary for humans and CI logs."""

    summary = ledger["summary"]
    lines = [
        "MindSage maintenance ledger: "
        f"events={summary['event_count']}, returned={summary['returned_event_count']}, "
        f"last_mode={summary.get('last_mode') or 'none'}"
    ]
    for event in ledger["events"]:
        lines.append(
            f"EVENT {event['event_id']} - {event['mode']} "
            f"(approved={event['approved_item_count']}, pending={event['pending_review_count']})"
        )
    return "\n".join(lines)


def build_citation_maintenance(
    *,
    question: str,
    citations: Sequence[Dict[str, Any]],
    coverage: Optional[Dict[str, Any]] = None,
    freshness: Optional[Dict[str, Any]] = None,
    contradictions: Optional[Sequence[Dict[str, Any]]] = None,
    replacement_candidates: Optional[Sequence[Dict[str, Any]]] = None,
    freshness_days: Optional[int] = None,
    reference_date: Optional[dt.date] = None,
) -> Dict[str, Any]:
    """Build an agent-actionable plan for stale, weak, or conflicted citations."""

    today = reference_date or dt.date.today()
    sanitized_citations = [_sanitize_citation(citation) for citation in citations]
    sanitized_contradictions = _sanitize_metadata(list(contradictions or []))
    sanitized_coverage = _sanitize_metadata(coverage or {})
    sanitized_freshness = _sanitize_metadata(freshness or {})
    stale_after_days = int(
        freshness_days
        or sanitized_freshness.get("freshness_days")
        or 90
    )

    actions: List[Dict[str, Any]] = []
    for citation in sanitized_citations:
        citation_date = _parse_date(citation.get("date"))
        if citation_date and (today - citation_date).days > stale_after_days:
            actions.append(_action(
                action_type="refresh_stale_citation",
                severity="high",
                reason=f"Source is older than {stale_after_days} days",
                question=question,
                citation_doc_ids=[citation.get("doc_id")],
                citation_titles=[citation.get("title")],
                repair_terms=[citation.get("title"), *_citation_concepts(citation)],
                suggested_tool="search_documents",
            ))
        elif not citation_date:
            actions.append(_action(
                action_type="add_source_date",
                severity="medium",
                reason="Source has no date metadata",
                question=question,
                citation_doc_ids=[citation.get("doc_id")],
                citation_titles=[citation.get("title")],
                repair_terms=[citation.get("title"), citation.get("source")],
                suggested_tool="write_memory",
            ))

    missing_terms = [
        str(term)
        for term in sanitized_coverage.get("query_terms_missing", [])
        if isinstance(term, str) and term.strip()
    ]
    if missing_terms:
        actions.append(_action(
            action_type="retrieve_missing_context",
            severity="medium",
            reason=f"No source explicitly covers: {', '.join(missing_terms)}",
            question=question,
            citation_doc_ids=[],
            citation_titles=[],
            repair_terms=missing_terms,
            suggested_tool="think",
        ))

    if sanitized_coverage.get("source_count", 0) and sanitized_coverage.get("strong_source_count", 0) == 0:
        actions.append(_action(
            action_type="improve_low_confidence_evidence",
            severity="medium",
            reason="No cited source crossed the strong evidence threshold",
            question=question,
            citation_doc_ids=[citation.get("doc_id") for citation in sanitized_citations],
            citation_titles=[citation.get("title") for citation in sanitized_citations],
            repair_terms=list(sanitized_coverage.get("query_terms_found", [])),
            suggested_tool="search_documents",
        ))

    for contradiction in sanitized_contradictions:
        cited_doc_ids = list(contradiction.get("citations", []))
        actions.append(_action(
            action_type="resolve_contradiction",
            severity="high",
            reason=f"Sources disagree on {contradiction.get('topic') or 'the answer'}",
            question=question,
            citation_doc_ids=cited_doc_ids,
            citation_titles=_titles_for_doc_ids(sanitized_citations, cited_doc_ids),
            repair_terms=[contradiction.get("topic")],
            suggested_tool="think",
        ))

    replacements = _replacement_candidates(
        stale_citations=[
            citation for citation in sanitized_citations
            if _is_stale(citation, stale_after_days, today)
        ],
        candidates=[
            _sanitize_citation(candidate)
            for candidate in (replacement_candidates or [])
        ],
    )
    graph = _maintenance_graph(question, sanitized_citations, actions, replacements)

    report = {
        "found": bool(actions or replacements),
        "priority": _priority(actions),
        "action_count": len(actions),
        "actions": actions,
        "replacement_candidates": replacements,
        "maintenance_graph": graph,
        "privacy": {
            "llm_context": "redacted",
            "pii_session_ids_exposed": False,
        },
        "governance": {
            "source": "think.citation_maintenance",
            "content": "redacted_citation_metadata_only",
            "default_policy": "repair_before_reuse_when_stale_undated_or_conflicted",
        },
    }
    report["privacy"]["pii_session_ids_exposed"] = _contains_pii_session_key(report)
    return report


def _action(
    *,
    action_type: str,
    severity: str,
    reason: str,
    question: str,
    citation_doc_ids: Sequence[Any],
    citation_titles: Sequence[Any],
    repair_terms: Sequence[Any],
    suggested_tool: str,
) -> Dict[str, Any]:
    normalized_terms = _dedupe_preserve_order(
        str(term).strip()
        for term in repair_terms
        if term is not None and str(term).strip()
    )
    normalized_doc_ids = [doc_id for doc_id in citation_doc_ids if doc_id is not None]
    normalized_titles = [
        str(title).strip()
        for title in citation_titles
        if title is not None and str(title).strip()
    ]
    repair_query = " ".join([question.strip(), *normalized_terms]).strip()
    action_id = _stable_id(action_type, normalized_doc_ids, repair_query)
    return {
        "id": action_id,
        "type": action_type,
        "severity": severity,
        "status": "open",
        "reason": reason,
        "suggested_tool": suggested_tool,
        "citation_doc_ids": normalized_doc_ids,
        "citation_titles": normalized_titles,
        "repair_query": repair_query,
    }


def _replacement_candidates(
    *,
    stale_citations: Sequence[Dict[str, Any]],
    candidates: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    replacements: List[Dict[str, Any]] = []
    for stale in stale_citations:
        stale_date = _parse_date(stale.get("date"))
        if not stale_date:
            continue
        best = None
        best_score = -1.0
        for candidate in candidates:
            candidate_date = _parse_date(candidate.get("date"))
            if not candidate_date or candidate_date <= stale_date:
                continue
            overlap = _citation_overlap(stale, candidate)
            if overlap <= 0:
                continue
            score = float(candidate.get("score") or 0) + overlap
            if score > best_score:
                best = candidate
                best_score = score
        if not best:
            continue
        best_date = _parse_date(best.get("date"))
        replacements.append({
            "candidate_doc_id": best.get("doc_id"),
            "replaces_doc_id": stale.get("doc_id"),
            "title": best.get("title"),
            "date": best.get("date"),
            "score": best.get("score"),
            "reason": "newer_candidate_for_stale_citation",
            "freshness_delta_days": (best_date - stale_date).days if best_date else None,
        })
    return replacements


def _maintenance_graph(
    question: str,
    citations: Sequence[Dict[str, Any]],
    actions: Sequence[Dict[str, Any]],
    replacements: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    answer_node_id = _answer_node_id(question)
    nodes: Dict[str, Dict[str, Any]] = {
        answer_node_id: {
            "id": answer_node_id,
            "type": "answer",
            "label": "Think answer",
        }
    }
    edges: Dict[str, Dict[str, Any]] = {}

    citation_by_doc_id = {str(citation.get("doc_id")): citation for citation in citations}
    for citation in citations:
        citation_node_id = _citation_node_id(citation.get("doc_id"))
        nodes[citation_node_id] = {
            "id": citation_node_id,
            "type": "citation",
            "label": citation.get("title") or "Untitled source",
            "doc_id": citation.get("doc_id"),
            "date": citation.get("date"),
            "score": citation.get("score"),
        }

    for action in actions:
        action_node_id = _action_node_id(action["id"])
        nodes[action_node_id] = {
            "id": action_node_id,
            "type": "maintenance_action",
            "label": action["type"],
            "severity": action["severity"],
            "suggested_tool": action["suggested_tool"],
        }
        _add_edge(edges, answer_node_id, action_node_id, "needs_maintenance", {"severity": action["severity"]})
        for doc_id in action.get("citation_doc_ids", []):
            if str(doc_id) not in citation_by_doc_id:
                continue
            _add_edge(edges, action_node_id, _citation_node_id(doc_id), "repairs", {"action_type": action["type"]})

    for replacement in replacements:
        candidate_doc_id = replacement.get("candidate_doc_id")
        replaces_doc_id = replacement.get("replaces_doc_id")
        candidate_node_id = _candidate_node_id(candidate_doc_id)
        nodes[candidate_node_id] = {
            "id": candidate_node_id,
            "type": "replacement_candidate",
            "label": replacement.get("title") or "Replacement candidate",
            "doc_id": candidate_doc_id,
            "date": replacement.get("date"),
            "score": replacement.get("score"),
        }
        _add_edge(
            edges,
            candidate_node_id,
            _citation_node_id(replaces_doc_id),
            "can_replace",
            {"freshness_delta_days": replacement.get("freshness_delta_days")},
        )

    return {
        "found": bool(actions or replacements),
        "answer_node_id": answer_node_id,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "nodes": sorted(nodes.values(), key=lambda node: (node["type"], node["id"])),
        "edges": sorted(edges.values(), key=lambda edge: edge["id"]),
        "governance": {
            "source": "citation_maintenance",
            "content": "redacted_citation_metadata_only",
        },
    }


def _sanitize_citation(citation: Dict[str, Any]) -> Dict[str, Any]:
    sanitized = _sanitize_metadata(citation)
    metadata = sanitized.get("metadata") if isinstance(sanitized.get("metadata"), dict) else {}
    return {
        "doc_id": sanitized.get("doc_id", sanitized.get("id")),
        "title": _first_text(sanitized.get("title"), metadata.get("title"), "Untitled source"),
        "excerpt": _first_text(sanitized.get("excerpt"), sanitized.get("text"), sanitized.get("content")),
        "score": _coerce_score(sanitized.get("score")),
        "date": _first_text(
            sanitized.get("date"),
            sanitized.get("created_at"),
            sanitized.get("modified_at"),
            metadata.get("date"),
            metadata.get("created_at"),
            metadata.get("modified_at"),
        ) or None,
        "source": _first_text(sanitized.get("source"), metadata.get("source"), metadata.get("connector"), "unknown"),
        "topics": _string_list(sanitized.get("topics") or metadata.get("topics")),
        "primary_topic": _first_text(sanitized.get("primary_topic"), metadata.get("primary_topic")),
        "metadata": metadata,
    }


def _sanitize_metadata(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: Dict[str, Any] = {}
        for key, item in value.items():
            if key in PII_SESSION_KEYS:
                continue
            sanitized[key] = _sanitize_metadata(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_metadata(item) for item in value]
    return value


def _contains_pii_session_key(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            key in PII_SESSION_KEYS or _contains_pii_session_key(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_pii_session_key(item) for item in value)
    return False


def _is_stale(citation: Dict[str, Any], freshness_days: int, reference_date: dt.date) -> bool:
    citation_date = _parse_date(citation.get("date"))
    return bool(citation_date and (reference_date - citation_date).days > freshness_days)


def _parse_date(value: Any) -> Optional[dt.date]:
    if value is None or value == "":
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    text = str(value).strip()
    match = re.search(r"\d{4}-\d{2}-\d{2}", text)
    if not match:
        return None
    try:
        return dt.date.fromisoformat(match.group(0))
    except ValueError:
        return None


def _citation_concepts(citation: Dict[str, Any]) -> List[str]:
    values = list(citation.get("topics") or [])
    if citation.get("primary_topic"):
        values.append(citation["primary_topic"])
    return _dedupe_preserve_order(values)


def _citation_overlap(left: Dict[str, Any], right: Dict[str, Any]) -> int:
    left_terms = _citation_terms(left)
    right_terms = _citation_terms(right)
    return len(left_terms & right_terms)


def _citation_terms(citation: Dict[str, Any]) -> set[str]:
    text = " ".join([
        str(citation.get("title") or ""),
        str(citation.get("excerpt") or ""),
        " ".join(_citation_concepts(citation)),
    ])
    return {term for term in re.findall(r"[a-z0-9]+", text.lower()) if len(term) >= 3}


def _titles_for_doc_ids(citations: Sequence[Dict[str, Any]], doc_ids: Sequence[Any]) -> List[str]:
    by_doc_id = {str(citation.get("doc_id")): citation for citation in citations}
    titles = []
    for doc_id in doc_ids:
        citation = by_doc_id.get(str(doc_id))
        if citation and citation.get("title"):
            titles.append(citation["title"])
    return titles


def _priority(actions: Sequence[Dict[str, Any]]) -> str:
    if any(action.get("severity") == "high" for action in actions):
        return "high"
    if actions:
        return "medium"
    return "none"


def _first_text(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _coerce_score(value: Any) -> Optional[float]:
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return None


def _string_list(value: Any) -> List[str]:
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    if isinstance(value, list):
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]
    return []


def _stable_id(action_type: str, doc_ids: Sequence[Any], repair_query: str) -> str:
    seed = f"{action_type}:{','.join(str(doc_id) for doc_id in doc_ids)}:{repair_query}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
    return f"{action_type}:{digest}"


def _answer_node_id(question: str) -> str:
    digest = hashlib.sha256(question.strip().encode("utf-8")).hexdigest()[:16]
    return f"answer:{digest}"


def _citation_node_id(doc_id: Any) -> str:
    return f"citation:{doc_id}" if doc_id is not None else "citation:unknown"


def _candidate_node_id(doc_id: Any) -> str:
    return f"candidate:{doc_id}" if doc_id is not None else "candidate:unknown"


def _action_node_id(action_id: str) -> str:
    return f"action:{action_id}"


def _add_edge(
    edges: Dict[str, Dict[str, Any]],
    source: str,
    target: str,
    edge_type: str,
    metadata: Dict[str, Any],
) -> None:
    edge_id = f"{source}->{target}:{edge_type}"
    edges[edge_id] = {
        "id": edge_id,
        "source": source,
        "target": target,
        "type": edge_type,
        "label": edge_type.replace("_", " "),
        "metadata": _sanitize_metadata(metadata),
    }


def _dedupe_preserve_order(values: Iterable[str]) -> List[str]:
    deduped: List[str] = []
    seen = set()
    for value in values:
        normalized = " ".join(str(value).split()).strip()
        key = normalized.lower()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(normalized)
    return deduped


def _maintenance_document(document: Any, index: int) -> Dict[str, Any]:
    sanitized = _sanitize_metadata(_document_to_dict(document))
    metadata = sanitized.get("metadata") if isinstance(sanitized.get("metadata"), dict) else {}
    text = _first_text(sanitized.get("text"), sanitized.get("content"), sanitized.get("excerpt"))
    title = _first_text(sanitized.get("title"), metadata.get("title"), f"Document {index}")
    date = _first_text(
        sanitized.get("date"),
        sanitized.get("created_at"),
        sanitized.get("modified_at"),
        metadata.get("date"),
        metadata.get("created_at"),
        metadata.get("modified_at"),
    ) or None
    source = _first_text(sanitized.get("source"), metadata.get("source"), metadata.get("connector"), "unknown")
    topics = _string_list(sanitized.get("topics") or metadata.get("topics"))
    structured = metadata.get("structured_metadata") if isinstance(metadata.get("structured_metadata"), dict) else {}
    return {
        "doc_id": sanitized.get("doc_id", sanitized.get("id", index)),
        "title": title,
        "text": text,
        "excerpt": _preview(text),
        "score": _coerce_score(sanitized.get("score")),
        "date": date,
        "source": source,
        "topics": topics,
        "structured_metadata": _sanitize_metadata(structured),
        "fingerprint": _document_fingerprint(title, text),
        "terms": _document_terms(title, text, topics),
    }


def _document_to_dict(document: Any) -> Dict[str, Any]:
    if isinstance(document, dict):
        return dict(document)
    return {
        "id": getattr(document, "id", getattr(document, "doc_id", None)),
        "text": getattr(document, "text", ""),
        "metadata": getattr(document, "metadata", {}) or {},
        "score": getattr(document, "score", None),
    }


def _snapshot_source(source: Dict[str, Any], *, reference_date: dt.date) -> Dict[str, Any]:
    source_date = _parse_date(source.get("date"))
    return {
        "doc_id": source.get("doc_id"),
        "title": source.get("title"),
        "date": source.get("date"),
        "source": source.get("source"),
        "age_days": (reference_date - source_date).days if source_date else None,
    }


def _duplicate_groups(documents: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_fingerprint: Dict[str, List[Dict[str, Any]]] = {}
    for document in documents:
        fingerprint = document.get("fingerprint")
        if not fingerprint:
            continue
        by_fingerprint.setdefault(fingerprint, []).append(document)

    groups = []
    for fingerprint, items in by_fingerprint.items():
        if len(items) < 2:
            continue
        groups.append({
            "id": f"duplicate_group:{fingerprint[:12]}",
            "fingerprint": fingerprint[:16],
            "doc_ids": [item.get("doc_id") for item in items],
            "titles": [item.get("title") for item in items],
            "reason": "same_normalized_text",
            "recommended_action": "keep_newest_or_highest_quality_source",
        })
    return sorted(groups, key=lambda group: group["id"])


def _entity_consolidation_candidates(documents: Sequence[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], int]:
    entities_by_key: Dict[str, Dict[str, Any]] = {}
    redacted_person_count = 0
    for document in documents:
        structured = document.get("structured_metadata", {})
        redacted_person_count += _person_entity_count(structured)
        for field, entity_type in SAFE_ENTITY_FIELDS.items():
            for label in _string_list(structured.get(field)):
                canonical_key = _entity_canonical_key(label)
                if not canonical_key:
                    continue
                bucket = entities_by_key.setdefault(canonical_key, {
                    "canonical_key": canonical_key,
                    "entity_type": entity_type,
                    "labels": [],
                    "doc_ids": [],
                })
                bucket["labels"].append(_normalize_entity_label(label))
                bucket["doc_ids"].append(document.get("doc_id"))

    candidates = []
    for bucket in entities_by_key.values():
        labels = _dedupe_preserve_order(bucket["labels"])
        doc_ids = _dedupe_preserve_order(str(doc_id) for doc_id in bucket["doc_ids"] if doc_id is not None)
        if len(labels) < 2:
            continue
        candidates.append({
            "id": f"entity_consolidation:{bucket['canonical_key']}",
            "entity_type": bucket["entity_type"],
            "canonical_label": _preferred_entity_label(labels),
            "labels": labels,
            "doc_ids": doc_ids,
            "reason": "same_entity_with_variant_labels",
            "suggested_tool": "write_memory",
        })
    return sorted(candidates, key=lambda candidate: candidate["id"]), redacted_person_count


def _snapshot_replacement_candidates(
    *,
    stale_sources: Sequence[Dict[str, Any]],
    documents: Sequence[Dict[str, Any]],
    reference_date: dt.date,
    freshness_days: int,
) -> List[Dict[str, Any]]:
    replacements: List[Dict[str, Any]] = []
    for stale in stale_sources:
        stale_date = _parse_date(stale.get("date"))
        if not stale_date:
            continue
        best = None
        best_score = -1.0
        for candidate in documents:
            if candidate.get("doc_id") == stale.get("doc_id"):
                continue
            candidate_date = _parse_date(candidate.get("date"))
            if not candidate_date or candidate_date <= stale_date:
                continue
            if (reference_date - candidate_date).days > freshness_days:
                continue
            overlap = len(stale.get("terms", set()) & candidate.get("terms", set()))
            if overlap <= 0:
                continue
            score = overlap + float(candidate.get("score") or 0)
            if score > best_score:
                best_score = score
                best = candidate
        if not best:
            continue
        best_date = _parse_date(best.get("date"))
        replacements.append({
            "candidate_doc_id": best.get("doc_id"),
            "replaces_doc_id": stale.get("doc_id"),
            "title": best.get("title"),
            "date": best.get("date"),
            "reason": "newer_document_overlaps_stale_source",
            "freshness_delta_days": (best_date - stale_date).days if best_date else None,
        })
    return replacements


def _snapshot_jobs(
    *,
    stale_sources: Sequence[Dict[str, Any]],
    undated_sources: Sequence[Dict[str, Any]],
    duplicate_groups: Sequence[Dict[str, Any]],
    entity_consolidations: Sequence[Dict[str, Any]],
    replacement_candidates: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    jobs: List[Dict[str, Any]] = []
    if stale_sources:
        jobs.append(_snapshot_job(
            "refresh_stale_sources",
            "high",
            "Search for newer evidence and update stale citations.",
            "think",
            [source.get("doc_id") for source in stale_sources],
            extra={"replacement_candidate_count": len(replacement_candidates)},
        ))
    if undated_sources:
        jobs.append(_snapshot_job(
            "add_source_dates",
            "medium",
            "Add created_at/date metadata so freshness can be enforced.",
            "write_memory",
            [source.get("doc_id") for source in undated_sources],
        ))
    if duplicate_groups:
        jobs.append(_snapshot_job(
            "deduplicate_documents",
            "medium",
            "Merge or remove exact duplicate document bodies.",
            "write_memory",
            [doc_id for group in duplicate_groups for doc_id in group.get("doc_ids", [])],
            extra={"duplicate_group_count": len(duplicate_groups)},
        ))
    if entity_consolidations:
        jobs.append(_snapshot_job(
            "consolidate_entities",
            "medium",
            "Normalize variant safe-entity labels into canonical typed memory.",
            "write_memory",
            [doc_id for group in entity_consolidations for doc_id in group.get("doc_ids", [])],
            extra={"entity_consolidation_count": len(entity_consolidations)},
        ))
    return jobs


def _snapshot_job(
    job_type: str,
    severity: str,
    reason: str,
    suggested_tool: str,
    doc_ids: Sequence[Any],
    *,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    normalized_doc_ids = _dedupe_preserve_order(str(doc_id) for doc_id in doc_ids if doc_id is not None)
    job = {
        "id": _stable_id(job_type, normalized_doc_ids, reason),
        "type": job_type,
        "severity": severity,
        "status": "open",
        "reason": reason,
        "suggested_tool": suggested_tool,
        "doc_ids": normalized_doc_ids,
        "item_count": len(normalized_doc_ids),
    }
    if extra:
        job.update(_sanitize_metadata(extra))
    return job


def _maintenance_plan_job(
    *,
    job_type: str,
    execution_mode: str,
    severity: str,
    reason: str,
    command: str,
    source_job_ids: Sequence[Any],
    item_count: int,
    write_intent: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    requires_review = execution_mode != "read_only"
    job = {
        "id": _stable_id(job_type, source_job_ids, command),
        "type": job_type,
        "severity": severity,
        "status": "planned",
        "execution_mode": execution_mode,
        "requires_review": requires_review,
        "reason": reason,
        "command": command,
        "source_job_ids": [str(job_id) for job_id in source_job_ids if job_id is not None],
        "item_count": item_count,
    }
    if write_intent:
        job["write_intent"] = _sanitize_metadata(write_intent)
    return job


def _maintenance_apply_item(
    job: Dict[str, Any],
    *,
    execution_order: int,
    approve: bool,
) -> Dict[str, Any]:
    requires_review = bool(job.get("requires_review"))
    write_intent = job.get("write_intent") if isinstance(job.get("write_intent"), dict) else {}
    target = str(write_intent.get("target") or ("maintenance_check" if not requires_review else "maintenance_review_queue"))
    operation = str(write_intent.get("operation") or ("run_command" if not requires_review else job.get("type") or "maintenance_job"))
    status = "ready"
    if requires_review:
        status = "approved_for_execution" if approve else "pending_review"

    item = {
        "id": _stable_id("maintenance_apply", [job.get("id"), execution_order], operation),
        "execution_order": execution_order,
        "job_id": str(job.get("id") or ""),
        "job_type": str(job.get("type") or "maintenance_job"),
        "severity": str(job.get("severity") or "medium"),
        "requires_review": requires_review,
        "status": status,
        "target": target,
        "operation": operation,
        "command": str(job.get("command") or ""),
        "source_job_ids": [str(job_id) for job_id in job.get("source_job_ids") or []],
        "item_count": int(job.get("item_count") or 0),
        "executor_required": requires_review,
        "payload_preview": _apply_payload_preview(write_intent),
    }
    if requires_review:
        item["write_request"] = {
            "target": target,
            "operation": operation,
            "doc_ids": list(_apply_payload_preview(write_intent.get("doc_ids") or [])),
            "payload_preview": item["payload_preview"],
        }
    return item


def _maintenance_ledger_event(
    batch: Dict[str, Any],
    *,
    actor: str,
    reference_datetime: Optional[dt.datetime],
) -> Dict[str, Any]:
    recorded_at = _ledger_timestamp(reference_datetime)
    items = list(batch.get("items") or [])
    summary = batch.get("summary", {})
    status_counts = _count_by_key(items, "status")
    target_counts = _count_by_key(items, "target")
    operations = sorted({
        str(item.get("operation"))
        for item in items
        if item.get("operation")
    })
    batch_id = _stable_id(
        "maintenance_batch",
        [item.get("id") for item in items],
        str(batch.get("mode") or "dry_run"),
    )
    event = {
        "event_id": _stable_id("maintenance_ledger", [batch_id, actor, recorded_at], "record"),
        "event_type": "maintenance_apply_batch_recorded",
        "recorded_at": recorded_at,
        "actor": _clean_ledger_actor(actor),
        "batch_id": batch_id,
        "mode": str(batch.get("mode") or "dry_run"),
        "priority": str(batch.get("priority") or "none"),
        "total_item_count": int(summary.get("total_item_count") or len(items)),
        "review_item_count": int(summary.get("review_item_count") or 0),
        "approved_item_count": int(summary.get("approved_item_count") or 0),
        "pending_review_count": int(summary.get("pending_review_count") or 0),
        "item_status_counts": status_counts,
        "target_counts": target_counts,
        "operations": operations,
        "mutated_data": False,
        "privacy": {
            "llm_context": "redacted",
            "pii_session_ids_exposed": False,
            "person_entities_exposed": False,
            "raw_document_text_exposed": False,
            "filenames_or_paths_exposed": False,
        },
        "governance": {
            "source": "maintenance.ledger",
            "content": "redacted_apply_batch_summary_only",
            "append_only": True,
            "default_policy": "audit_before_executor_mutation",
        },
    }
    event["privacy"]["pii_session_ids_exposed"] = _contains_pii_session_key(event)
    event["privacy"]["person_entities_exposed"] = _contains_person_entity(event)
    return event


def _ledger_timestamp(value: Optional[dt.datetime]) -> str:
    timestamp = value or dt.datetime.now(dt.timezone.utc)
    if timestamp.tzinfo is not None:
        timestamp = timestamp.astimezone(dt.timezone.utc).replace(tzinfo=None)
    return timestamp.isoformat(timespec="seconds") + "Z"


def _clean_ledger_actor(actor: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.:-]+", "-", str(actor or "operator").strip())
    cleaned = cleaned.strip("-._:")
    return cleaned[:80] or "operator"


def _count_by_key(items: Sequence[Dict[str, Any]], key: str) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for item in items:
        value = str(item.get(key) or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def _apply_payload_preview(value: Any) -> Any:
    if isinstance(value, dict):
        preview: Dict[str, Any] = {}
        for key, item in value.items():
            normalized_key = str(key)
            lowered = normalized_key.lower()
            if (
                lowered in APPLY_PREVIEW_DENYLIST
                or lowered in PERSON_ENTITY_FIELDS
                or "path" in lowered
            ):
                continue
            preview_item = _apply_payload_preview(item)
            if preview_item in ({}, [], None, ""):
                continue
            preview[normalized_key] = preview_item
        return preview
    if isinstance(value, list):
        return [
            item
            for item in (_apply_payload_preview(item) for item in value[:50])
            if item not in ({}, [], None, "")
        ]
    if isinstance(value, str):
        return "[redacted-label]" if _looks_like_filename_or_path(value) else value
    return value


def _looks_like_filename_or_path(value: str) -> bool:
    text = value.strip()
    if not text:
        return False
    if text.startswith(("~", ".", "/")) or "/" in text or "\\" in text:
        return True
    return bool(re.search(r"\.[A-Za-z0-9]{1,8}$", text))


def _connector_sources(snapshot: Dict[str, Any]) -> List[str]:
    sources = [
        source.get("source")
        for source in [
            *(snapshot.get("stale_sources") or []),
            *(snapshot.get("undated_sources") or []),
        ]
        if isinstance(source, dict)
    ]
    return [
        source for source in _dedupe_preserve_order(str(source) for source in sources if source)
        if source not in {"unknown", "notes", "security", "synthetic-fixture-corpus"}
    ]


def _plan_command_for_snapshot_job(snapshot_job: Dict[str, Any]) -> str:
    job_type = snapshot_job.get("type")
    if job_type == "refresh_stale_sources":
        return "npm run agent:search -- --json \"refresh stale evidence\""
    if job_type == "add_source_dates":
        return "npm run agent:capture -- --dry-run --mode memory --kind artifact"
    if job_type == "deduplicate_documents":
        return "npm run agent:health -- --json"
    if job_type == "consolidate_entities":
        return "npm run agent:capture -- --dry-run --mode memory --kind entity"
    return "npm run agent:health -- --json"


def _write_intent_for_snapshot_job(snapshot_job: Dict[str, Any], snapshot: Dict[str, Any]) -> Dict[str, Any]:
    job_type = snapshot_job.get("type")
    base = {
        "target": "maintenance_review_queue",
        "operation": job_type,
        "doc_ids": list(snapshot_job.get("doc_ids") or []),
    }
    if job_type == "refresh_stale_sources":
        base.update({
            "target": "documents",
            "operation": "refresh_or_link_newer_evidence",
            "replacement_candidate_count": int(snapshot_job.get("replacement_candidate_count") or 0),
            "replacement_candidates": list(snapshot.get("replacement_candidates") or []),
        })
    elif job_type == "add_source_dates":
        base.update({
            "target": "typed_memory",
            "operation": "add_missing_source_date_metadata",
        })
    elif job_type == "deduplicate_documents":
        base.update({
            "target": "documents",
            "operation": "merge_or_hide_duplicate_documents",
            "duplicate_groups": list(snapshot.get("duplicate_groups") or []),
        })
    elif job_type == "consolidate_entities":
        base.update({
            "target": "typed_memory",
            "operation": "write_canonical_safe_entity_records",
            "entity_consolidation_candidates": list(snapshot.get("entity_consolidation_candidates") or []),
        })
    return _sanitize_metadata(base)


def _document_fingerprint(title: str, text: str) -> str:
    normalized_text = " ".join((text or title).lower().split())
    if not normalized_text:
        return ""
    return hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()


def _document_terms(title: str, text: str, topics: Sequence[str]) -> set[str]:
    joined = " ".join([title or "", text or "", " ".join(topics or [])])
    return {
        term
        for term in re.findall(r"[a-z0-9]+", joined.lower())
        if len(term) >= 3
    }


def _entity_canonical_key(label: str) -> str:
    if not isinstance(label, str):
        return ""
    compact = re.sub(r"[^a-z0-9]+", "", label.lower())
    return compact if len(compact) >= 2 else ""


def _normalize_entity_label(label: str) -> str:
    return " ".join(str(label).split()).strip()


def _preferred_entity_label(labels: Sequence[str]) -> str:
    return sorted(labels, key=lambda label: (-sum(1 for char in label if char.isupper()), len(label), label))[0]


def _preview(text: str, limit: int = 280) -> str:
    compact = " ".join((text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


def _contains_person_entity(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            key in PERSON_ENTITY_FIELDS or _contains_person_entity(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_person_entity(item) for item in value)
    return False


def _person_entity_count(value: Any) -> int:
    if isinstance(value, dict):
        total = 0
        for key, item in value.items():
            if key in PERSON_ENTITY_FIELDS:
                total += len(_string_list(item))
            else:
                total += _person_entity_count(item)
        return total
    if isinstance(value, list):
        return sum(_person_entity_count(item) for item in value)
    return 0


def _load_fixture_snapshot_documents(corpus_dir: Path) -> List[Dict[str, Any]]:
    documents: List[Dict[str, Any]] = []
    for index, path in enumerate(sorted(corpus_dir.glob("*.txt")), start=1):
        text = path.read_text(encoding="utf-8")
        documents.append({
            "id": index,
            "text": text,
            "metadata": {
                "title": path.name,
                "source": "synthetic-fixture-corpus",
                "date": _fixture_date(path.name),
            },
        })
    return documents


def _fixture_date(title: str) -> str:
    if "2025" in title:
        return "2025-01-31"
    if "2024" in title:
        return "2024-12-31"
    return "2026-01-01"


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run a MindSage background maintenance snapshot")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text")
    parser.add_argument("--plan", action="store_true", help="Emit a schedulable maintenance plan")
    parser.add_argument("--apply", action="store_true", help="Emit a reviewable maintenance apply batch")
    parser.add_argument("--approve", action="store_true", help="Mark review-required apply items as approved for an executor")
    parser.add_argument("--ledger-path", default=None, help="Append a redacted apply audit event to this JSONL ledger")
    parser.add_argument("--ledger-report", default=None, help="Load and report a maintenance JSONL ledger")
    parser.add_argument("--actor", default="operator", help="Actor name for maintenance ledger events")
    parser.add_argument(
        "--corpus-dir",
        default=str(DEFAULT_CORPUS_DIR),
        help="Path to a directory of .txt documents to scan",
    )
    parser.add_argument("--freshness-days", type=int, default=90)
    parser.add_argument("--schedule-days", type=int, default=7, help="Cadence for maintenance plans")
    parser.add_argument("--reference-date", default=None, help="YYYY-MM-DD reference date")
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.ledger_report:
        ledger = load_maintenance_ledger(Path(args.ledger_report))
        if args.json:
            print(json.dumps(ledger, indent=2, sort_keys=True))
        else:
            print(format_maintenance_ledger_report(ledger))
        return 0

    reference_date = _parse_date(args.reference_date) if args.reference_date else None
    documents = _load_fixture_snapshot_documents(Path(args.corpus_dir))
    snapshot = build_maintenance_snapshot(
        documents,
        reference_date=reference_date,
        freshness_days=args.freshness_days,
    )
    if args.plan:
        plan = build_maintenance_plan(
            snapshot,
            schedule_days=args.schedule_days,
            reference_date=reference_date,
        )
        if args.apply:
            batch = build_maintenance_apply_batch(plan, approve=args.approve)
            if args.ledger_path:
                batch["ledger_event"] = append_maintenance_ledger_event(
                    batch,
                    ledger_path=Path(args.ledger_path),
                    actor=args.actor,
                )
            if args.json:
                print(json.dumps(batch, indent=2, sort_keys=True))
            else:
                print(format_maintenance_apply_report(batch))
            return 0
        if args.json:
            print(json.dumps(plan, indent=2, sort_keys=True))
        else:
            print(format_maintenance_plan_report(plan))
        return 0

    if args.apply:
        plan = build_maintenance_plan(
            snapshot,
            schedule_days=args.schedule_days,
            reference_date=reference_date,
        )
        batch = build_maintenance_apply_batch(plan, approve=args.approve)
        if args.ledger_path:
            batch["ledger_event"] = append_maintenance_ledger_event(
                batch,
                ledger_path=Path(args.ledger_path),
                actor=args.actor,
            )
        if args.json:
            print(json.dumps(batch, indent=2, sort_keys=True))
        else:
            print(format_maintenance_apply_report(batch))
        return 0

    if args.json:
        print(json.dumps(snapshot, indent=2, sort_keys=True))
    else:
        print(format_maintenance_snapshot_report(snapshot))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
