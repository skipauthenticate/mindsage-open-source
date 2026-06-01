"""PII-safe entity graph construction for MindSage cited reasoning."""

from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence


PII_SESSION_KEYS = {"pii_session_id", "piiSessionId"}
SAFE_STRUCTURED_ENTITY_FIELDS = {
    "organizations": "organization",
    "locations": "location",
    "technologies": "technology",
    "activities": "activity",
    "dates": "date",
}
PERSON_ENTITY_FIELDS = {"person", "persons", "people"}


def build_entity_graph(question: str, citations: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Build a compact graph of safe entities mentioned by cited evidence."""

    answer_node_id = _answer_node_id(question)
    nodes: Dict[str, Dict[str, Any]] = {
        answer_node_id: {
            "id": answer_node_id,
            "type": "answer",
            "label": "Think answer",
        }
    }
    edges: Dict[str, Dict[str, Any]] = {}
    entity_counts: Dict[str, int] = {}
    redacted_person_count = 0

    for rank, raw_citation in enumerate(citations, start=1):
        raw_person_count = _person_entity_count(raw_citation)
        citation = _sanitize_metadata(raw_citation)
        citation_doc_id = citation.get("doc_id", citation.get("id"))
        citation_node_id = _citation_node_id(citation_doc_id, rank)
        nodes[citation_node_id] = {
            "id": citation_node_id,
            "type": "citation",
            "label": _first_text(citation.get("title"), "Untitled source"),
            "doc_id": citation_doc_id,
            "rank": rank,
        }
        _add_edge(
            edges,
            source=answer_node_id,
            target=citation_node_id,
            edge_type="cites",
            metadata={"rank": rank},
        )

        citation_entities, person_count = _citation_entities(citation)
        redacted_person_count += raw_person_count + person_count
        entity_node_ids: List[str] = []
        for entity in citation_entities:
            entity_node_id = _entity_node_id(entity["entity_type"], entity["label"])
            entity_node_ids.append(entity_node_id)
            entity_counts[entity["entity_type"]] = entity_counts.get(entity["entity_type"], 0) + 1
            nodes.setdefault(entity_node_id, {
                "id": entity_node_id,
                "type": "entity",
                "entity_type": entity["entity_type"],
                "label": entity["label"],
            })
            _add_edge(
                edges,
                source=citation_node_id,
                target=entity_node_id,
                edge_type="mentions_entity",
                metadata={
                    "entity_type": entity["entity_type"],
                    "source": entity["source"],
                },
            )
            _add_edge(
                edges,
                source=answer_node_id,
                target=entity_node_id,
                edge_type="answers_with_entity",
                metadata={"entity_type": entity["entity_type"]},
            )

        for left_index, left_id in enumerate(entity_node_ids):
            for right_id in entity_node_ids[left_index + 1:]:
                _add_edge(
                    edges,
                    source=left_id,
                    target=right_id,
                    edge_type="co_occurs",
                    metadata={"citation_doc_id": citation_doc_id},
                )

    graph = {
        "found": any(node.get("type") == "entity" for node in nodes.values()),
        "answer_node_id": answer_node_id,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "entity_counts": entity_counts,
        "nodes": sorted(nodes.values(), key=lambda node: (node["type"], node["id"])),
        "edges": sorted(edges.values(), key=lambda edge: edge["id"]),
        "privacy": {
            "person_entities_exposed": False,
            "pii_session_ids_exposed": False,
            "redacted_person_entity_count": redacted_person_count,
        },
        "governance": {
            "source": "think.safe_entities",
            "content": "redacted_entity_metadata_only",
            "default_policy": "exclude_person_entities_and_high_risk_identifiers",
        },
    }
    graph["privacy"]["person_entities_exposed"] = _contains_person_entity(graph)
    graph["privacy"]["pii_session_ids_exposed"] = _contains_pii_session_key(graph)
    return graph


def _citation_entities(citation: Dict[str, Any]) -> tuple[List[Dict[str, str]], int]:
    metadata = citation.get("metadata") if isinstance(citation.get("metadata"), dict) else {}
    structured = metadata.get("structured_metadata") if isinstance(metadata.get("structured_metadata"), dict) else {}
    entities: List[Dict[str, str]] = []
    redacted_person_count = 0

    for field_name in PERSON_ENTITY_FIELDS:
        redacted_person_count += len(_string_list(structured.get(field_name)))
        redacted_person_count += len(_string_list(metadata.get(field_name)))
        redacted_person_count += len(_string_list(citation.get(field_name)))

    for field_name, entity_type in SAFE_STRUCTURED_ENTITY_FIELDS.items():
        for value in _string_list(structured.get(field_name)):
            if _safe_entity_label(value):
                entities.append({
                    "label": _normalize_label(value),
                    "entity_type": entity_type,
                    "source": f"structured_metadata.{field_name}",
                })

    for value in _string_list(metadata.get("entities")) + _string_list(citation.get("entities")):
        inferred_type = _infer_safe_entity_type(value)
        if inferred_type and _safe_entity_label(value):
            entities.append({
                "label": _normalize_label(value),
                "entity_type": inferred_type,
                "source": "entities",
            })

    return _dedupe_entities(entities), redacted_person_count


def _infer_safe_entity_type(value: str) -> Optional[str]:
    label = value.strip()
    lower_label = label.lower()
    if not _safe_entity_label(label):
        return None
    if any(token in lower_label for token in ("inc", "corp", "llc", "foundation", "bank", "university")):
        return "organization"
    if any(token in lower_label for token in ("api", "mcp", "sdk", "gpu", "cpu", "llm", "python", "typescript")):
        return "technology"
    if re.search(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3}\b", label):
        return None
    return "named_entity"


def _safe_entity_label(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    label = value.strip()
    if len(label) < 2 or len(label) > 100:
        return False
    lower_label = label.lower()
    if any(key.lower() in lower_label for key in PII_SESSION_KEYS):
        return False
    if "@" in label:
        return False
    if re.search(r"\b\d{3}[-.\s]?\d{2}[-.\s]?\d{4}\b", label):
        return False
    if re.search(r"\(\d{3}\)\s*\d{3}-\d{4}", label):
        return False
    if re.search(r"\b(?:\d{4}[-\s]){2,4}\d{3,4}\b", label):
        return False
    if re.search(r"\b\d{6,}\b", label):
        return False
    if label.startswith("[") and label.endswith("]") and "PERSON" not in label.upper():
        return False
    return bool(re.search(r"[a-zA-Z]", label))


def _sanitize_metadata(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: Dict[str, Any] = {}
        for key, item in value.items():
            if key in PII_SESSION_KEYS:
                continue
            if key in PERSON_ENTITY_FIELDS:
                continue
            sanitized[key] = _sanitize_metadata(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_metadata(item) for item in value]
    return value


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


def _contains_pii_session_key(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            key in PII_SESSION_KEYS or _contains_pii_session_key(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_pii_session_key(item) for item in value)
    return False


def _contains_person_entity(value: Any) -> bool:
    if isinstance(value, dict):
        if value.get("entity_type") == "person":
            return True
        return any(_contains_person_entity(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_person_entity(item) for item in value)
    return False


def _string_list(value: Any) -> List[str]:
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    if isinstance(value, list):
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]
    return []


def _dedupe_entities(entities: Iterable[Dict[str, str]]) -> List[Dict[str, str]]:
    deduped: List[Dict[str, str]] = []
    seen = set()
    for entity in entities:
        key = (entity["entity_type"], entity["label"].lower())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(entity)
    return deduped


def _normalize_label(label: str) -> str:
    return " ".join(label.strip().split())


def _first_text(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _answer_node_id(question: str) -> str:
    digest = hashlib.sha256(question.strip().encode("utf-8")).hexdigest()[:16]
    return f"answer:{digest}"


def _citation_node_id(doc_id: Any, rank: int) -> str:
    if doc_id is None or doc_id == "":
        return f"citation:rank-{rank}"
    return f"citation:{doc_id}"


def _entity_node_id(entity_type: str, label: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")
    return f"entity:{entity_type}:{slug[:80] or 'unknown'}"


def _add_edge(
    edges: Dict[str, Dict[str, Any]],
    *,
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
