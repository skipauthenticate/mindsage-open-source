"""Deterministic, PII-safe evidence shaping for the MindSage think tool."""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

try:
    from .entity_graph import build_entity_graph
    from .maintenance_tool import build_citation_maintenance
except ImportError:  # Allows direct file loading in lightweight unit tests.
    try:
        from entity_graph import build_entity_graph
        from maintenance_tool import build_citation_maintenance
    except ImportError:
        _ENTITY_GRAPH_PATH = Path(__file__).resolve().with_name("entity_graph.py")
        _ENTITY_GRAPH_SPEC = importlib.util.spec_from_file_location("entity_graph", _ENTITY_GRAPH_PATH)
        entity_graph = importlib.util.module_from_spec(_ENTITY_GRAPH_SPEC)
        assert _ENTITY_GRAPH_SPEC and _ENTITY_GRAPH_SPEC.loader
        _ENTITY_GRAPH_SPEC.loader.exec_module(entity_graph)
        build_entity_graph = entity_graph.build_entity_graph

        _MAINTENANCE_TOOL_PATH = Path(__file__).resolve().with_name("maintenance_tool.py")
        _MAINTENANCE_SPEC = importlib.util.spec_from_file_location("maintenance_tool", _MAINTENANCE_TOOL_PATH)
        maintenance_tool = importlib.util.module_from_spec(_MAINTENANCE_SPEC)
        assert _MAINTENANCE_SPEC and _MAINTENANCE_SPEC.loader
        _MAINTENANCE_SPEC.loader.exec_module(maintenance_tool)
        build_citation_maintenance = maintenance_tool.build_citation_maintenance


STOP_WORDS = {
    "about",
    "after",
    "again",
    "being",
    "could",
    "decided",
    "does",
    "from",
    "have",
    "into",
    "should",
    "that",
    "their",
    "there",
    "this",
    "what",
    "when",
    "where",
    "which",
    "with",
    "would",
}

POSITIVE_TERMS = {"allow", "allowed", "enable", "enabled", "yes", "use", "ship"}
NEGATIVE_TERMS = {"block", "blocked", "deny", "denied", "disable", "disabled", "no", "not"}
PII_SESSION_KEYS = {"pii_session_id", "piiSessionId"}


def build_think_response(
    question: str,
    results: Sequence[Any],
    *,
    top_k: int = 8,
    freshness_days: int = 90,
    include_gaps: bool = True,
    reference_date: Optional[dt.date] = None,
) -> Dict[str, Any]:
    """Build a stable, redacted reasoning packet from retrieved search results.

    The function does not call an LLM. It prepares evidence in a shape that an
    MCP client or coding agent can safely synthesize from.
    """

    today = reference_date or dt.date.today()
    citations = [_to_citation(result) for result in list(results)[:top_k]]
    citations = [citation for citation in citations if citation["excerpt"]]

    coverage = _build_coverage(question, citations)
    freshness = _build_freshness(citations, freshness_days, today)
    gaps = _build_gaps(citations, coverage, include_gaps)
    contradictions = _detect_contradictions(question, citations)
    citation_graph = _build_citation_graph(question, citations, coverage, contradictions)
    entity_graph = build_entity_graph(question, citations)
    maintenance = build_citation_maintenance(
        question=question,
        citations=citations,
        coverage=coverage,
        freshness=freshness,
        contradictions=contradictions,
        freshness_days=freshness_days,
        reference_date=today,
    )

    response: Dict[str, Any] = {
        "question": question,
        "answer_brief": _build_answer_brief(citations),
        "citations": citations,
        "citation_graph": citation_graph,
        "entity_graph": entity_graph,
        "coverage": coverage,
        "gaps": gaps,
        "contradictions": contradictions,
        "freshness": freshness,
        "maintenance": maintenance,
        "privacy": {
            "llm_context": "redacted",
            "pii_session_ids_exposed": False,
        },
    }
    response["privacy"]["pii_session_ids_exposed"] = _contains_pii_session_key(response)
    return response


def _to_citation(result: Any) -> Dict[str, Any]:
    metadata = _sanitize_metadata(_get_value(result, "metadata", {}) or {})
    excerpt = _first_text(
        _get_value(result, "excerpt"),
        _get_value(result, "passage"),
        _get_value(result, "text"),
        _get_value(result, "content"),
    )
    date_value = _first_text(
        _get_value(result, "date"),
        _get_value(result, "created_at"),
        _get_value(result, "modified_at"),
        _get_value(result, "source_date"),
        metadata.get("date"),
        metadata.get("created_at"),
        metadata.get("modified_at"),
        metadata.get("source_date"),
    )
    parsed_date = _parse_date(date_value)

    return {
        "doc_id": _get_value(result, "doc_id", _get_value(result, "id", _get_value(result, "document_id"))),
        "title": _first_text(
            _get_value(result, "title"),
            metadata.get("title"),
            metadata.get("filename"),
            metadata.get("path"),
            "Untitled source",
        ),
        "excerpt": _clean_excerpt(excerpt),
        "score": _coerce_score(_get_value(result, "score")),
        "date": parsed_date.isoformat() if parsed_date else None,
        "source": _first_text(_get_value(result, "source"), metadata.get("source"), metadata.get("connector"), "unknown"),
        "topics": _citation_topics(result, metadata),
        "primary_topic": _first_text(_get_value(result, "primary_topic"), metadata.get("primary_topic")),
        "metadata": metadata,
    }


def _build_coverage(question: str, citations: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    terms = _query_terms(question)
    corpus = " ".join(
        f"{citation.get('title', '')} {citation.get('excerpt', '')}".lower()
        for citation in citations
    )
    found = [term for term in terms if term in corpus]
    missing = [term for term in terms if term not in corpus]

    return {
        "source_count": len(citations),
        "dated_source_count": sum(1 for citation in citations if citation.get("date")),
        "strong_source_count": sum(1 for citation in citations if (citation.get("score") or 0) >= 0.7),
        "query_terms_found": found,
        "query_terms_missing": missing,
    }


def _build_freshness(
    citations: Sequence[Dict[str, Any]],
    freshness_days: int,
    reference_date: dt.date,
) -> Dict[str, Any]:
    dates = [_parse_date(citation.get("date")) for citation in citations]
    dated = [date for date in dates if date]
    stale_count = sum(1 for date in dated if (reference_date - date).days > freshness_days)
    undated_count = len(citations) - len(dated)
    warnings: List[str] = []
    if stale_count:
        warnings.append(f"{stale_count} source{'s are' if stale_count != 1 else ' is'} older than {freshness_days} days")
    if undated_count:
        warnings.append(f"{undated_count} source{'s have' if undated_count != 1 else ' has'} no date metadata")

    return {
        "freshness_days": freshness_days,
        "oldest_source_date": min(dated).isoformat() if dated else None,
        "newest_source_date": max(dated).isoformat() if dated else None,
        "stale_source_count": stale_count,
        "undated_source_count": undated_count,
        "warnings": warnings,
    }


def _build_gaps(
    citations: Sequence[Dict[str, Any]],
    coverage: Dict[str, Any],
    include_gaps: bool,
) -> List[str]:
    if not include_gaps:
        return []
    if not citations:
        return ["No supporting sources were found."]

    gaps: List[str] = []
    missing_terms = coverage.get("query_terms_missing", [])
    if missing_terms:
        gaps.append(f"No source explicitly mentions: {', '.join(missing_terms)}")
    if coverage.get("strong_source_count", 0) == 0:
        gaps.append("No high-confidence source crossed the strong evidence threshold.")
    return gaps


def _detect_contradictions(
    question: str,
    citations: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    query_terms = _query_terms(question)
    query_term_set = set(query_terms)
    contradictions: List[Dict[str, Any]] = []

    for left_index, left in enumerate(citations):
        left_text = left.get("excerpt", "").lower()
        left_terms = _text_terms(left_text)
        for right in citations[left_index + 1:]:
            right_text = right.get("excerpt", "").lower()
            right_terms = _text_terms(right_text)
            shared = [
                term for term in query_terms
                if term in query_term_set and term in left_terms and term in right_terms
            ]
            if len(shared) < 2:
                continue
            if _has_positive_negative_conflict(left_text, right_text):
                contradictions.append({
                    "topic": " ".join(shared[:3]),
                    "citations": [left.get("doc_id"), right.get("doc_id")],
                    "excerpts": [left.get("excerpt"), right.get("excerpt")],
                })
    return contradictions


def _build_citation_graph(
    question: str,
    citations: Sequence[Dict[str, Any]],
    coverage: Dict[str, Any],
    contradictions: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """Build a compact cited-answer graph for agent and UI consumers."""

    answer_node_id = _answer_node_id(question)
    nodes: Dict[str, Dict[str, Any]] = {
        answer_node_id: {
            "id": answer_node_id,
            "type": "answer",
            "label": "Think answer",
            "question": question,
        }
    }
    edges: Dict[str, Dict[str, Any]] = {}
    citation_node_by_doc_id: Dict[str, str] = {}

    for rank, citation in enumerate(citations, start=1):
        citation_node_id = _citation_node_id(citation, rank)
        citation_node_by_doc_id[str(citation.get("doc_id"))] = citation_node_id
        nodes[citation_node_id] = {
            "id": citation_node_id,
            "type": "citation",
            "label": citation.get("title") or "Untitled source",
            "doc_id": citation.get("doc_id"),
            "source": citation.get("source"),
            "date": citation.get("date"),
            "score": citation.get("score"),
            "rank": rank,
        }
        _add_graph_edge(
            edges,
            source=answer_node_id,
            target=citation_node_id,
            edge_type="cites",
            label="cites",
            metadata={
                "rank": rank,
                "score": citation.get("score"),
                "date": citation.get("date"),
            },
        )

        for concept in _citation_concepts(citation, coverage):
            concept_node_id = _concept_node_id(concept)
            nodes.setdefault(concept_node_id, {
                "id": concept_node_id,
                "type": "concept",
                "label": concept,
            })
            _add_graph_edge(
                edges,
                source=citation_node_id,
                target=concept_node_id,
                edge_type="mentions",
                label="mentions",
                metadata={},
            )
            if concept in coverage.get("query_terms_found", []):
                _add_graph_edge(
                    edges,
                    source=answer_node_id,
                    target=concept_node_id,
                    edge_type="covers",
                    label="covers",
                    metadata={},
                )

    for contradiction in contradictions:
        cited_doc_ids = [str(doc_id) for doc_id in contradiction.get("citations", [])]
        if len(cited_doc_ids) < 2:
            continue
        left_id = citation_node_by_doc_id.get(cited_doc_ids[0])
        right_id = citation_node_by_doc_id.get(cited_doc_ids[1])
        if not left_id or not right_id:
            continue
        _add_graph_edge(
            edges,
            source=left_id,
            target=right_id,
            edge_type="contradicts",
            label="contradicts",
            metadata={"topic": contradiction.get("topic")},
        )

    return {
        "found": bool(citations),
        "answer_node_id": answer_node_id,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "nodes": sorted(nodes.values(), key=lambda node: (node["type"], node["id"])),
        "edges": sorted(edges.values(), key=lambda edge: edge["id"]),
        "governance": {
            "source": "think.citations",
            "content": "redacted_citation_metadata_only",
            "default_policy": "no_raw_document_text_in_graph_nodes",
        },
    }


def _build_answer_brief(citations: Sequence[Dict[str, Any]]) -> Optional[str]:
    if not citations:
        return None
    strongest = max(citations, key=lambda citation: citation.get("score") or 0)
    excerpt = strongest.get("excerpt", "")
    title = strongest.get("title", "the strongest source")
    sentence = re.split(r"(?<=[.!?])\s+", excerpt.strip())[0]
    return f"Found {len(citations)} supporting source(s). Strongest source, {title}, says: {sentence}"


def _get_value(result: Any, key: str, default: Any = None) -> Any:
    if isinstance(result, dict):
        return result.get(key, default)
    return getattr(result, key, default)


def _first_text(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _clean_excerpt(text: str, max_length: int = 700) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if len(cleaned) <= max_length:
        return cleaned
    return cleaned[: max_length - 1].rstrip() + "..."


def _coerce_score(value: Any) -> Optional[float]:
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return None


def _citation_topics(result: Any, metadata: Dict[str, Any]) -> List[str]:
    topics: List[str] = []
    for value in (
        _get_value(result, "topics"),
        metadata.get("topics"),
        _get_value(result, "primary_topic"),
        metadata.get("primary_topic"),
    ):
        if isinstance(value, list):
            topics.extend(item.strip() for item in value if isinstance(item, str) and item.strip())
        elif isinstance(value, str) and value.strip():
            topics.append(value.strip())
    return sorted(set(topic for topic in topics if _safe_concept_label(topic)))


def _sanitize_metadata(metadata: Any) -> Dict[str, Any]:
    if not isinstance(metadata, dict):
        return {}
    sanitized: Dict[str, Any] = {}
    for key, value in metadata.items():
        if key in PII_SESSION_KEYS:
            continue
        if key in {"person", "persons", "people"}:
            continue
        if isinstance(value, dict):
            sanitized[key] = _sanitize_metadata(value)
        elif isinstance(value, list):
            sanitized[key] = [
                _sanitize_metadata(item) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            sanitized[key] = value
    return sanitized


def _parse_date(value: Any) -> Optional[dt.date]:
    if value is None or value == "":
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    text = str(value).strip()
    if text.isdigit() and len(text) >= 10:
        try:
            return dt.datetime.fromtimestamp(int(text[:10])).date()
        except (OSError, OverflowError, ValueError):
            return None
    match = re.search(r"\d{4}-\d{2}-\d{2}", text)
    if not match:
        return None
    try:
        return dt.date.fromisoformat(match.group(0))
    except ValueError:
        return None


def _query_terms(question: str) -> List[str]:
    terms = []
    seen = set()
    for term in _tokens(question):
        if term in STOP_WORDS or len(term) < 3 or term in seen:
            continue
        seen.add(term)
        terms.append(term)
    return terms


def _text_terms(text: str) -> set[str]:
    return set(_tokens(text))


def _tokens(text: str) -> List[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _citation_concepts(citation: Dict[str, Any], coverage: Dict[str, Any]) -> List[str]:
    concepts: List[str] = []
    for topic in citation.get("topics", []):
        if _safe_concept_label(topic):
            concepts.append(str(topic).strip().lower())

    primary_topic = citation.get("primary_topic")
    if _safe_concept_label(primary_topic):
        concepts.append(str(primary_topic).strip().lower())

    citation_text = f"{citation.get('title', '')} {citation.get('excerpt', '')}".lower()
    for term in coverage.get("query_terms_found", []):
        if term in citation_text and _safe_concept_label(term):
            concepts.append(term)

    return _dedupe_preserve_order(concepts)


def _answer_node_id(question: str) -> str:
    digest = hashlib.sha256(question.strip().encode("utf-8")).hexdigest()[:16]
    return f"answer:{digest}"


def _citation_node_id(citation: Dict[str, Any], rank: int) -> str:
    doc_id = citation.get("doc_id")
    if doc_id is None or doc_id == "":
        return f"citation:rank-{rank}"
    return f"citation:{doc_id}"


def _concept_node_id(label: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")
    return f"concept:{slug[:80] or 'unknown'}"


def _add_graph_edge(
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
        "metadata": _sanitize_metadata(metadata),
    }


def _safe_concept_label(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    label = value.strip()
    if len(label) < 3 or len(label) > 120:
        return False
    lower_label = label.lower()
    if any(key.lower() in lower_label for key in PII_SESSION_KEYS):
        return False
    if "@" in label:
        return False
    if re.search(r"\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b", label):
        return False
    return bool(re.search(r"[a-zA-Z]", label))


def _dedupe_preserve_order(values: Iterable[str]) -> List[str]:
    deduped: List[str] = []
    seen = set()
    for value in values:
        normalized = " ".join(str(value).lower().split())
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def _has_positive_negative_conflict(left: str, right: str) -> bool:
    left_positive = any(term in left for term in POSITIVE_TERMS)
    left_negative = any(term in left for term in NEGATIVE_TERMS)
    right_positive = any(term in right for term in POSITIVE_TERMS)
    right_negative = any(term in right for term in NEGATIVE_TERMS)
    return (left_positive and right_negative) or (left_negative and right_positive)


def _contains_pii_session_key(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            key in PII_SESSION_KEYS or _contains_pii_session_key(child)
            for key, child in value.items()
        )
    if isinstance(value, list):
        return any(_contains_pii_session_key(item) for item in value)
    return False
