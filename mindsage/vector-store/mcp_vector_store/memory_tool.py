"""Typed memory records and audit timelines for MindSage agent tools.

This module is intentionally dependency-light. It stores OpenBrain-style typed
memory as ordinary MindSage documents with structured metadata, so existing
local vector storage remains the source of truth.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from typing import Any, Dict, Iterable, List, Optional, Sequence


MEMORY_KINDS = {
    "artifact",
    "claim",
    "decision",
    "entity",
    "note",
    "pattern",
    "policy",
    "preference",
    "relation",
    "task",
    "thought_summary",
}
MEMORY_STATES = {"scratch", "candidate", "accepted", "deprecated"}
DEFAULT_INCLUDE_STATES = {"accepted"}
PII_SESSION_KEYS = {"pii_session_id", "piiSessionId"}


def build_memory_record(
    *,
    kind: str,
    content: str,
    workspace: str = "default",
    actor: str = "agent",
    memory_key: Optional[str] = None,
    state: str = "accepted",
    source_document_id: Optional[int] = None,
    relations: Optional[Sequence[Dict[str, Any]]] = None,
    ttl_days: Optional[int] = None,
    metadata: Optional[Dict[str, Any]] = None,
    reason: Optional[str] = None,
    existing_records: Optional[Sequence[Any]] = None,
    reference_datetime: Optional[dt.datetime] = None,
) -> Dict[str, Any]:
    """Build a typed memory document payload for storage in the vector index."""

    normalized_kind = _normalize_kind(kind)
    normalized_state = _normalize_state(state)
    normalized_content = _normalize_content(content)
    normalized_workspace = _clean_required(workspace, "workspace")
    normalized_actor = _clean_required(actor, "actor")
    now = _coerce_datetime(reference_datetime) or dt.datetime.now(dt.timezone.utc)
    created_at = _isoformat(now)
    expires_at = _isoformat(now + dt.timedelta(days=ttl_days)) if ttl_days else None
    key = _clean_memory_key(memory_key) if memory_key else _default_memory_key(
        normalized_workspace,
        normalized_kind,
        normalized_content,
    )
    value_hash = _value_hash(normalized_content)
    version = _next_version(existing_records or [], normalized_workspace, key)
    event_type = "memory.created" if version == 1 else "memory.revised"

    event = {
        "event_id": _event_id(
            workspace=normalized_workspace,
            memory_key=key,
            version=version,
            event_type=event_type,
            timestamp=created_at,
            value_hash=value_hash,
        ),
        "event_type": event_type,
        "timestamp": created_at,
        "actor": normalized_actor,
        "workspace": normalized_workspace,
        "memory_key": key,
        "version": version,
        "state": normalized_state,
        "value_hash": value_hash,
        "reason": reason,
    }

    memory = {
        "kind": normalized_kind,
        "workspace": normalized_workspace,
        "memory_key": key,
        "state": normalized_state,
        "version": version,
        "value_hash": value_hash,
        "created_at": created_at,
        "expires_at": expires_at,
        "source_document_id": source_document_id,
        "relations": list(relations or []),
    }

    safe_extra_metadata = _sanitize_metadata(metadata or {})
    typed_metadata = {
        **safe_extra_metadata,
        "content_type": "typed_memory",
        "source": f"typed_memory:{normalized_workspace}:{key}",
        "memory_kind": normalized_kind,
        "memory_key": key,
        "workspace": normalized_workspace,
        "memory_state": normalized_state,
        "value_hash": value_hash,
        "memory": memory,
        "memory_events": [event],
        "topics": _memory_topics(normalized_kind, normalized_state, safe_extra_metadata),
    }

    return {
        "text": _memory_text(
            kind=normalized_kind,
            state=normalized_state,
            workspace=normalized_workspace,
            memory_key=key,
            version=version,
            content=normalized_content,
        ),
        "metadata": typed_metadata,
    }


def filter_memory_records(
    documents: Sequence[Any],
    *,
    workspace: Optional[str] = None,
    kind: Optional[str] = None,
    memory_key: Optional[str] = None,
    include_states: Optional[Sequence[str]] = None,
    include_expired: bool = False,
    limit: int = 20,
    reference_datetime: Optional[dt.datetime] = None,
) -> List[Dict[str, Any]]:
    """Filter typed memory documents with OpenBrain-style governed defaults."""

    now = _coerce_datetime(reference_datetime) or dt.datetime.now(dt.timezone.utc)
    normalized_workspace = workspace.strip() if workspace else None
    normalized_kind = _normalize_kind(kind) if kind else None
    normalized_key = _clean_memory_key(memory_key) if memory_key else None
    allowed_states = {
        _normalize_state(state)
        for state in (include_states or DEFAULT_INCLUDE_STATES)
    }

    records: List[Dict[str, Any]] = []
    for document in documents:
        record = _memory_record_from_document(document, now)
        if not record:
            continue
        if normalized_workspace and record["workspace"] != normalized_workspace:
            continue
        if normalized_kind and record["kind"] != normalized_kind:
            continue
        if normalized_key and record["memory_key"] != normalized_key:
            continue
        if record["state"] not in allowed_states:
            continue
        if record["expired"] and not include_expired:
            continue

        records.append(record)
        if len(records) >= limit:
            break

    return records


def build_memory_timeline(
    documents: Sequence[Any],
    *,
    workspace: str,
    memory_key: str,
    include_content: bool = False,
    reference_datetime: Optional[dt.datetime] = None,
) -> Dict[str, Any]:
    """Build an audit timeline for a memory key across document versions."""

    now = _coerce_datetime(reference_datetime) or dt.datetime.now(dt.timezone.utc)
    records = filter_memory_records(
        documents,
        workspace=workspace,
        memory_key=memory_key,
        include_states=sorted(MEMORY_STATES),
        include_expired=True,
        limit=1000,
        reference_datetime=now,
    )

    if not records:
        return {
            "found": False,
            "workspace": workspace,
            "memory_key": memory_key,
            "reason_code": "memory_key_not_found",
            "policy_rule_id": "memory.timeline.memory_key",
            "events": [],
            "versions": [],
        }

    records.sort(key=lambda record: (record["version"], record.get("created_at") or ""))
    events: List[Dict[str, Any]] = []
    versions: List[Dict[str, Any]] = []

    for record in records:
        version = {
            "doc_id": record["doc_id"],
            "kind": record["kind"],
            "workspace": record["workspace"],
            "memory_key": record["memory_key"],
            "state": record["state"],
            "version": record["version"],
            "value_hash": record["value_hash"],
            "created_at": record.get("created_at"),
            "expires_at": record.get("expires_at"),
            "expired": record["expired"],
            "content_preview": record["content_preview"],
        }
        if include_content:
            version["content"] = record["text"]
        versions.append(version)

        for event in record.get("events", []):
            event_copy = dict(event)
            event_copy["doc_id"] = record["doc_id"]
            events.append(event_copy)

    events.sort(key=lambda event: (event.get("timestamp") or "", event.get("version") or 0))
    current = _current_record(records)

    return {
        "found": True,
        "workspace": workspace,
        "memory_key": memory_key,
        "current_version": current["version"] if current else None,
        "current_state": current["state"] if current else None,
        "events": events,
        "versions": versions,
    }


def build_memory_graph(
    documents: Sequence[Any],
    *,
    workspace: str,
    center_memory_key: Optional[str] = None,
    include_states: Optional[Sequence[str]] = None,
    include_expired: bool = False,
    limit: int = 100,
    reference_datetime: Optional[dt.datetime] = None,
) -> Dict[str, Any]:
    """Build a typed-memory relation graph from stored memory metadata."""

    now = _coerce_datetime(reference_datetime) or dt.datetime.now(dt.timezone.utc)
    records = filter_memory_records(
        documents,
        workspace=workspace,
        include_states=include_states,
        include_expired=include_expired,
        limit=limit,
        reference_datetime=now,
    )

    if center_memory_key:
        records = _filter_centered_graph_records(records, _clean_memory_key(center_memory_key))

    if not records:
        return {
            "found": False,
            "workspace": workspace,
            "center_memory_key": center_memory_key,
            "nodes": [],
            "edges": [],
            "governance": {
                "include_states": list(include_states or DEFAULT_INCLUDE_STATES),
                "include_expired": include_expired,
                "default_policy": "accepted_non_expired_only",
            },
        }

    nodes: Dict[str, Dict[str, Any]] = {}
    edges: Dict[str, Dict[str, Any]] = {}
    memory_keys = {record["memory_key"] for record in records}

    for record in records:
        source_id = _memory_node_id(record["memory_key"])
        nodes[source_id] = _memory_node(record)

        source_document_id = record.get("metadata", {}).get("memory", {}).get("source_document_id")
        if source_document_id is not None:
            document_id = _document_node_id(source_document_id)
            nodes.setdefault(document_id, _document_node(source_document_id))
            _add_edge(
                edges,
                source=source_id,
                target=document_id,
                edge_type="source_document",
                label="source document",
                metadata={"source_document_id": source_document_id},
            )

        for relation in _record_relations(record):
            target_key = _relation_target_key(relation)
            if not target_key:
                continue
            target_id = _memory_node_id(target_key)
            if target_key in memory_keys:
                target_record = next(item for item in records if item["memory_key"] == target_key)
                nodes.setdefault(target_id, _memory_node(target_record))
            else:
                nodes.setdefault(target_id, _external_memory_node(target_key, relation))

            edge_type = _relation_type(relation)
            _add_edge(
                edges,
                source=source_id,
                target=target_id,
                edge_type=edge_type,
                label=_relation_label(relation, edge_type),
                metadata=_sanitize_metadata(relation),
            )

    return {
        "found": True,
        "workspace": workspace,
        "center_memory_key": center_memory_key,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "nodes": sorted(nodes.values(), key=lambda node: (node["type"], node["id"])),
        "edges": sorted(edges.values(), key=lambda edge: edge["id"]),
        "governance": {
            "include_states": list(include_states or DEFAULT_INCLUDE_STATES),
            "include_expired": include_expired,
            "default_policy": "accepted_non_expired_only",
        },
    }


def build_workspace_info(
    documents: Sequence[Any],
    *,
    workspace: str,
    reference_datetime: Optional[dt.datetime] = None,
) -> Dict[str, Any]:
    """Summarize typed-memory governance state for one workspace."""

    now = _coerce_datetime(reference_datetime) or dt.datetime.now(dt.timezone.utc)
    normalized_workspace = _clean_required(workspace, "workspace")
    records = _all_memory_records(documents, now, workspace=normalized_workspace)

    if not records:
        return {
            "found": False,
            "workspace": normalized_workspace,
            "reason_code": "workspace_not_found",
            "policy_rule_id": "memory.workspace.info",
            "summary": {
                "total_record_count": 0,
                "active_record_count": 0,
                "expired_record_count": 0,
                "event_count": 0,
            },
            "kind_counts": {},
            "state_counts": {},
            "actor_counts": {},
            "governance": _memory_governance_summary(),
        }

    events = _activity_events(records)
    return {
        "found": True,
        "workspace": normalized_workspace,
        "summary": {
            "total_record_count": len(records),
            "active_record_count": sum(
                1 for record in records
                if record["state"] in DEFAULT_INCLUDE_STATES and not record["expired"]
            ),
            "expired_record_count": sum(1 for record in records if record["expired"]),
            "event_count": len(events),
            "oldest_event_at": _first_timestamp(events),
            "newest_event_at": _last_timestamp(events),
        },
        "kind_counts": _count_by(records, "kind"),
        "state_counts": _count_by(records, "state"),
        "actor_counts": _count_events_by(events, "actor"),
        "governance": _memory_governance_summary(),
    }


def build_actor_activity(
    documents: Sequence[Any],
    *,
    workspace: Optional[str] = None,
    actor: Optional[str] = None,
    limit: int = 50,
    reference_datetime: Optional[dt.datetime] = None,
) -> Dict[str, Any]:
    """Return bounded append-only memory audit activity for an actor or workspace."""

    if limit < 1:
        raise ValueError("limit must be at least 1")

    now = _coerce_datetime(reference_datetime) or dt.datetime.now(dt.timezone.utc)
    normalized_workspace = _clean_required(workspace, "workspace") if workspace else None
    normalized_actor = _clean_required(actor, "actor") if actor else None
    records = _all_memory_records(documents, now, workspace=normalized_workspace)
    events = _activity_events(records)

    if normalized_actor:
        events = [event for event in events if event.get("actor") == normalized_actor]

    events.sort(key=lambda event: (event.get("timestamp") or "", event.get("version") or 0), reverse=True)
    bounded_events = events[:limit]

    if not bounded_events:
        return {
            "found": False,
            "workspace": normalized_workspace,
            "actor": normalized_actor,
            "reason_code": "actor_activity_not_found",
            "policy_rule_id": "memory.audit.actor_activity",
            "summary": {
                "event_count": 0,
                "actor_count": 0,
                "memory_count": 0,
            },
            "events": [],
            "governance": _memory_governance_summary(),
        }

    return {
        "found": True,
        "workspace": normalized_workspace,
        "actor": normalized_actor,
        "summary": {
            "event_count": len(bounded_events),
            "actor_count": len({event.get("actor") for event in bounded_events if event.get("actor")}),
            "memory_count": len({event.get("memory_key") for event in bounded_events if event.get("memory_key")}),
            "oldest_event_at": _first_timestamp(bounded_events),
            "newest_event_at": _last_timestamp(bounded_events),
        },
        "events": bounded_events,
        "governance": _memory_governance_summary(),
    }


def _all_memory_records(
    documents: Sequence[Any],
    now: dt.datetime,
    *,
    workspace: Optional[str] = None,
) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for document in documents:
        record = _memory_record_from_document(document, now)
        if not record:
            continue
        if workspace and record["workspace"] != workspace:
            continue
        records.append(record)
    return records


def _activity_events(records: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    for record in records:
        for event in record.get("events", []):
            event_copy = dict(event)
            event_copy["doc_id"] = record["doc_id"]
            event_copy["kind"] = record["kind"]
            event_copy["expires_at"] = record.get("expires_at")
            event_copy["expired"] = record["expired"]
            events.append(event_copy)
    events.sort(key=lambda event: (event.get("timestamp") or "", event.get("version") or 0))
    return events


def _count_by(rows: Sequence[Dict[str, Any]], key: str) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for row in rows:
        value = row.get(key)
        if value is None:
            continue
        text = str(value)
        counts[text] = counts.get(text, 0) + 1
    return dict(sorted(counts.items()))


def _count_events_by(events: Sequence[Dict[str, Any]], key: str) -> Dict[str, int]:
    return _count_by(events, key)


def _first_timestamp(events: Sequence[Dict[str, Any]]) -> Optional[str]:
    timestamps = sorted(event.get("timestamp") for event in events if event.get("timestamp"))
    return timestamps[0] if timestamps else None


def _last_timestamp(events: Sequence[Dict[str, Any]]) -> Optional[str]:
    timestamps = sorted(event.get("timestamp") for event in events if event.get("timestamp"))
    return timestamps[-1] if timestamps else None


def _memory_governance_summary() -> Dict[str, Any]:
    return {
        "default_policy": "accepted_non_expired_only",
        "retention": "ttl_enforced_when_present",
        "audit": "append_only_memory_events",
        "content_included": False,
    }


def _memory_record_from_document(document: Any, now: dt.datetime) -> Optional[Dict[str, Any]]:
    metadata = _get_value(document, "metadata", {}) or {}
    memory = metadata.get("memory", {})
    if metadata.get("content_type") != "typed_memory" or not memory:
        return None

    expires_at = _parse_datetime(memory.get("expires_at"))
    expired = bool(expires_at and expires_at < now)
    text = _get_value(document, "text", "") or ""
    doc_id = _get_value(document, "id", _get_value(document, "doc_id", _get_value(document, "document_id")))

    return {
        "doc_id": doc_id,
        "kind": memory.get("kind") or metadata.get("memory_kind"),
        "workspace": memory.get("workspace") or metadata.get("workspace"),
        "memory_key": memory.get("memory_key") or metadata.get("memory_key"),
        "state": memory.get("state") or metadata.get("memory_state"),
        "version": int(memory.get("version") or 1),
        "value_hash": memory.get("value_hash") or metadata.get("value_hash"),
        "created_at": memory.get("created_at"),
        "expires_at": memory.get("expires_at"),
        "expired": expired,
        "score": _get_value(document, "score"),
        "text": text,
        "content_preview": _preview(_content_from_memory_text(text)),
        "metadata": _sanitize_metadata(metadata),
        "events": _sanitize_metadata(metadata.get("memory_events", [])),
    }


def _filter_centered_graph_records(records: Sequence[Dict[str, Any]], center_key: str) -> List[Dict[str, Any]]:
    related_keys = {center_key}
    for record in records:
        record_key = record["memory_key"]
        for relation in _record_relations(record):
            target_key = _relation_target_key(relation)
            if record_key == center_key and target_key:
                related_keys.add(target_key)
            if target_key == center_key:
                related_keys.add(record_key)
    return [record for record in records if record["memory_key"] in related_keys]


def _memory_node(record: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": _memory_node_id(record["memory_key"]),
        "type": "memory",
        "kind": record["kind"],
        "workspace": record["workspace"],
        "memory_key": record["memory_key"],
        "state": record["state"],
        "version": record["version"],
        "value_hash": record["value_hash"],
        "expired": record["expired"],
        "content_preview": record["content_preview"],
        "doc_id": record["doc_id"],
    }


def _external_memory_node(memory_key: str, relation: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": _memory_node_id(memory_key),
        "type": "external_memory",
        "kind": relation.get("target_kind"),
        "workspace": relation.get("target_workspace"),
        "memory_key": memory_key,
        "state": "unknown",
        "version": None,
        "value_hash": None,
        "expired": None,
        "content_preview": relation.get("target_label") or relation.get("label") or memory_key,
        "doc_id": None,
    }


def _document_node(source_document_id: Any) -> Dict[str, Any]:
    return {
        "id": _document_node_id(source_document_id),
        "type": "source_document",
        "document_id": source_document_id,
        "label": f"Source document {source_document_id}",
    }


def _add_edge(
    edges: Dict[str, Dict[str, Any]],
    *,
    source: str,
    target: str,
    edge_type: str,
    label: str,
    metadata: Dict[str, Any],
) -> None:
    edge_id = f"{source}->{target}:{edge_type}"
    edges[edge_id] = {
        "id": edge_id,
        "source": source,
        "target": target,
        "type": edge_type,
        "label": label,
        "metadata": metadata,
    }


def _record_relations(record: Dict[str, Any]) -> List[Dict[str, Any]]:
    relations = record.get("metadata", {}).get("memory", {}).get("relations", [])
    return [relation for relation in relations if isinstance(relation, dict)]


def _relation_target_key(relation: Dict[str, Any]) -> Optional[str]:
    value = relation.get("target_key") or relation.get("target_memory_key") or relation.get("memory_key")
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _relation_type(relation: Dict[str, Any]) -> str:
    value = relation.get("type") or relation.get("relation_type") or "related_to"
    if not isinstance(value, str) or not value.strip():
        return "related_to"
    return value.strip().lower().replace(" ", "_")


def _relation_label(relation: Dict[str, Any], edge_type: str) -> str:
    label = relation.get("label") or relation.get("description") or edge_type.replace("_", " ")
    return str(label)


def _memory_node_id(memory_key: str) -> str:
    return f"memory:{memory_key}"


def _document_node_id(source_document_id: Any) -> str:
    return f"document:{source_document_id}"


def _current_record(records: Sequence[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    accepted = [
        record for record in records
        if record["state"] == "accepted" and not record["expired"]
    ]
    candidates = accepted or [record for record in records if not record["expired"]] or list(records)
    if not candidates:
        return None
    return max(candidates, key=lambda record: (record["version"], record.get("created_at") or ""))


def _next_version(records: Sequence[Any], workspace: str, memory_key: str) -> int:
    max_version = 0
    now = dt.datetime.now(dt.timezone.utc)
    for document in records:
        record = _memory_record_from_document(document, now)
        if not record:
            continue
        if record["workspace"] == workspace and record["memory_key"] == memory_key:
            max_version = max(max_version, record["version"])
    return max_version + 1


def _normalize_kind(kind: str) -> str:
    normalized = _clean_required(kind, "kind").lower().replace("-", "_")
    if normalized not in MEMORY_KINDS:
        allowed = ", ".join(sorted(MEMORY_KINDS))
        raise ValueError(f"Unsupported memory kind '{kind}'. Allowed kinds: {allowed}")
    return normalized


def _normalize_state(state: str) -> str:
    normalized = _clean_required(state, "state").lower().replace("-", "_")
    if normalized not in MEMORY_STATES:
        allowed = ", ".join(sorted(MEMORY_STATES))
        raise ValueError(f"Unsupported memory state '{state}'. Allowed states: {allowed}")
    return normalized


def _normalize_content(content: str) -> str:
    if not isinstance(content, str) or not content.strip():
        raise ValueError("content must be a non-empty string")
    return content.strip()


def _clean_required(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _clean_memory_key(memory_key: str) -> str:
    key = _clean_required(memory_key, "memory_key")
    if len(key) > 240:
        raise ValueError("memory_key must be 240 characters or fewer")
    return key


def _default_memory_key(workspace: str, kind: str, content: str) -> str:
    digest = hashlib.sha256(f"{workspace}:{kind}:{content}".encode("utf-8")).hexdigest()[:12]
    return f"{kind}:{digest}"


def _value_hash(content: str) -> str:
    normalized = " ".join(content.split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _event_id(
    *,
    workspace: str,
    memory_key: str,
    version: int,
    event_type: str,
    timestamp: str,
    value_hash: str,
) -> str:
    seed = f"{workspace}:{memory_key}:{version}:{event_type}:{timestamp}:{value_hash}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]


def _memory_text(
    *,
    kind: str,
    state: str,
    workspace: str,
    memory_key: str,
    version: int,
    content: str,
) -> str:
    label = kind.replace("_", " ").title()
    return "\n".join([
        f"{label} memory ({state})",
        f"Workspace: {workspace}",
        f"Memory key: {memory_key}",
        f"Version: {version}",
        "",
        content,
    ])


def _memory_topics(kind: str, state: str, metadata: Dict[str, Any]) -> List[str]:
    existing = metadata.get("topics", [])
    topics = [topic for topic in existing if isinstance(topic, str)]
    topics.extend(["typed-memory", kind, state])
    return sorted(set(topics))


def _content_from_memory_text(text: str) -> str:
    if "\n\n" not in text:
        return text
    return text.split("\n\n", 1)[1]


def _preview(text: str, limit: int = 500) -> str:
    compact = " ".join((text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


def _sanitize_metadata(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _sanitize_metadata(child)
            for key, child in value.items()
            if key not in PII_SESSION_KEYS
        }
    if isinstance(value, list):
        return [_sanitize_metadata(item) for item in value]
    return value


def _coerce_datetime(value: Optional[dt.datetime]) -> Optional[dt.datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(dt.timezone.utc)


def _parse_datetime(value: Any) -> Optional[dt.datetime]:
    if not value:
        return None
    if isinstance(value, dt.datetime):
        return _coerce_datetime(value)
    if isinstance(value, str):
        try:
            parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
            return _coerce_datetime(parsed)
        except ValueError:
            return None
    return None


def _isoformat(value: dt.datetime) -> str:
    return _coerce_datetime(value).isoformat().replace("+00:00", "Z")


def _get_value(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)
