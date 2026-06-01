"""Dependency-light MindSage integration schema for AI coding tools."""

from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from typing import Any, Dict, List, Optional

try:
    from .agent_setup import supported_clients
except ImportError:  # Allows direct execution from the source checkout.
    from agent_setup import supported_clients


DEFAULT_BASE_URL = "http://localhost:8085"
DEFAULT_SERVER_NAME = "mindsage-search"
REMOTE_API_KEY_ENV = "MCP_VECTOR_STORE_API_KEY"
SECTIONS = {"all", "cli", "mcp", "memory", "rest", "safety"}


def build_agent_schema(
    *,
    base_url: str = DEFAULT_BASE_URL,
    server_name: str = DEFAULT_SERVER_NAME,
    section: str = "all",
) -> Dict[str, Any]:
    """Build a versioned integration contract for agent clients."""

    normalized_section = _normalize_section(section)
    normalized_base_url = _clean_base_url(base_url)
    normalized_server_name = _clean_text(server_name, "server_name")

    full_schema: Dict[str, Any] = {
        "schema_version": 1,
        "product": "MindSage",
        "generated_for": "ai-coding-tools",
        "mcp": _mcp_schema(normalized_base_url, normalized_server_name),
        "rest": _rest_schema(normalized_base_url),
        "cli": _cli_schema(),
        "memory": _memory_schema(),
        "safety": _safety_schema(),
    }
    if normalized_section == "all":
        return full_schema

    return {
        "schema_version": full_schema["schema_version"],
        "product": full_schema["product"],
        "generated_for": full_schema["generated_for"],
        normalized_section: full_schema[normalized_section],
    }


def format_schema_report(schema: Dict[str, Any]) -> str:
    """Format a compact report that does not echo secrets or user content."""

    lines = [
        f"MindSage agent schema: version {schema['schema_version']}",
        "Preferred answer path: think",
    ]
    if "mcp" in schema:
        tools = schema["mcp"].get("tools", [])
        lines.append(f"MCP tools: {len(tools)}")
        lines.extend(f"- {tool['name']}: {tool['purpose']}" for tool in tools[:8])
    if "rest" in schema:
        endpoints = schema["rest"].get("endpoints", [])
        lines.append(f"REST endpoints: {len(endpoints)}")
        lines.extend(f"- {endpoint['method']} {endpoint['path']}: {endpoint['purpose']}" for endpoint in endpoints[:8])
    if "cli" in schema:
        commands = schema["cli"].get("commands", [])
        lines.append(f"CLI commands: {len(commands)}")
        lines.extend(f"- npm run {command['name']}: {command['purpose']}" for command in commands[:8])
    if "memory" in schema:
        lines.append("Memory kinds: " + ", ".join(schema["memory"].get("kinds", [])))
    if "safety" in schema:
        safety = schema["safety"]
        lines.append(f"Safety: default context={safety['default_context']}, auth={safety['remote_auth_required']}")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None, *, stdout: Any = sys.stdout) -> int:
    parser = argparse.ArgumentParser(description="Print the MindSage agent integration schema")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of a compact report")
    parser.add_argument("--section", choices=sorted(SECTIONS), default="all")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--server-name", default=DEFAULT_SERVER_NAME)

    args = parser.parse_args(argv)
    schema = build_agent_schema(
        base_url=args.base_url,
        server_name=args.server_name,
        section=args.section,
    )
    if args.json:
        stdout.write(json.dumps(schema, indent=2, sort_keys=True) + "\n")
    else:
        stdout.write(format_schema_report(schema) + "\n")
    return 0


def _mcp_schema(base_url: str, server_name: str) -> Dict[str, Any]:
    return {
        "server_name": server_name,
        "transport": "sse",
        "sse_url": f"{base_url}/sse",
        "stdio_bridge": {
            "command": "python3",
            "args": [
                "mindsage/vector-store/mcp_vector_store/mcp_server_stdio.py",
                "--url",
                base_url,
            ],
            "env": {REMOTE_API_KEY_ENV: f"${{{REMOTE_API_KEY_ENV}}}"},
        },
        "auth": {
            "scheme": "bearer",
            "env": REMOTE_API_KEY_ENV,
            "required_when": "MCP_VECTOR_STORE_PUBLIC=true or any non-local public exposure",
            "minimum_length": 32,
        },
        "tools": deepcopy(MCP_TOOLS),
    }


def _rest_schema(base_url: str) -> Dict[str, Any]:
    return {
        "base_url": base_url,
        "auth": {
            "scheme": "bearer",
            "header": "Authorization: Bearer ${MCP_VECTOR_STORE_API_KEY}",
            "required_for_public_mode": True,
        },
        "endpoints": deepcopy(REST_ENDPOINTS),
    }


def _cli_schema() -> Dict[str, Any]:
    return {
        "working_directory": "public monorepo root",
        "supported_clients": supported_clients(),
        "commands": deepcopy(CLI_COMMANDS),
    }


def _memory_schema() -> Dict[str, Any]:
    return {
        "kinds": ["decision", "claim", "task", "artifact", "entity", "relation", "summary"],
        "lifecycle_states": ["scratch", "candidate", "accepted", "deprecated"],
        "core_fields": [
            "kind",
            "content",
            "workspace",
            "actor",
            "memory_key",
            "source_document_id",
            "relations",
            "retention_expires_at",
            "metadata",
        ],
        "graph_edges": ["declared relation", "source document", "workspace", "actor", "version"],
        "default_read_policy": "accepted, non-expired records with redacted previews",
    }


def _safety_schema() -> Dict[str, Any]:
    return {
        "default_context": "llm",
        "remote_auth_required": "bearer token for public HTTP/SSE mode",
        "never_commit": [
            "api keys",
            "cookies",
            "browser profiles",
            "uploads",
            "captures",
            "connector exports",
            "vector databases",
            "model caches",
            "generated redactions",
        ],
        "pii_controls": [
            "text anonymization",
            "LLM-safe metadata context",
            "consent filtering",
            "image redaction",
            "audio redaction",
            "PII-safe entity graph",
        ],
        "reporting_rule": "CLI reports must not echo bearer tokens or private request text unless returning requested search evidence.",
    }


def _normalize_section(section: str) -> str:
    normalized = str(section or "").strip().lower()
    if normalized not in SECTIONS:
        allowed = ", ".join(sorted(SECTIONS))
        raise ValueError(f"section must be one of: {allowed}")
    return normalized


def _clean_base_url(base_url: str) -> str:
    cleaned = _clean_text(base_url, "base_url").rstrip("/")
    if not cleaned.startswith(("http://", "https://")):
        raise ValueError("base_url must start with http:// or https://")
    return cleaned


def _clean_text(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


MCP_TOOLS = [
    {
        "name": "think",
        "purpose": "cited, PII-safe answer synthesis with gaps, freshness, graph links, and maintenance actions",
        "preferred_for": "answering questions before calling external tools",
    },
    {
        "name": "enhanced_search",
        "purpose": "ranked passage retrieval from documents",
        "preferred_for": "finding evidence without synthesis",
    },
    {
        "name": "search_documents",
        "purpose": "direct semantic document retrieval with similarity scores",
        "preferred_for": "low-level document search",
    },
    {
        "name": "write_memory",
        "purpose": "typed, versioned memory writes for durable agent-owned facts",
        "preferred_for": "decisions, claims, tasks, artifacts, entities, relations, and summaries",
    },
    {
        "name": "search_memory",
        "purpose": "governed typed-memory retrieval",
        "preferred_for": "structured memory rather than raw documents",
    },
    {
        "name": "memory_workspace_info",
        "purpose": "workspace-level memory counts and retention/audit health",
        "preferred_for": "workspace summaries without raw content",
    },
    {
        "name": "memory_actor_activity",
        "purpose": "bounded append-only actor/workspace audit activity",
        "preferred_for": "audit history without raw memory content",
    },
    {
        "name": "memory_timeline",
        "purpose": "version timeline for one stable memory key",
        "preferred_for": "understanding memory evolution",
    },
    {
        "name": "memory_graph",
        "purpose": "typed-memory relation and source-document graph traversal",
        "preferred_for": "graph-assisted planning",
    },
    {
        "name": "add_document",
        "purpose": "add a text document to the vector store",
        "preferred_for": "quick unstructured notes",
    },
    {
        "name": "get_stats",
        "purpose": "vector-store document and embedding statistics",
        "preferred_for": "health checks",
    },
    {
        "name": "list_documents",
        "purpose": "paginated document browsing",
        "preferred_for": "local inspection",
    },
    {
        "name": "get_document",
        "purpose": "retrieve one document by ID",
        "preferred_for": "citation inspection",
    },
]


REST_ENDPOINTS = [
    {
        "method": "POST",
        "path": "/api/think",
        "purpose": "cited answer synthesis",
        "request": ["question", "top_k", "min_score", "freshness_days", "include_gaps", "max_excerpt_length"],
    },
    {
        "method": "POST",
        "path": "/api/search/enhanced",
        "purpose": "ranked passage search",
        "request": ["query", "top_k", "min_score", "extract_passages", "max_excerpt_length", "context"],
    },
    {
        "method": "POST",
        "path": "/api/documents/batch",
        "purpose": "bulk import local text corpora",
        "request": ["documents", "skip_duplicates", "extract_key_passages"],
    },
    {
        "method": "POST",
        "path": "/api/memory",
        "purpose": "write typed memory",
        "request": ["kind", "content", "workspace", "actor", "memory_key", "relations", "metadata"],
    },
    {
        "method": "POST",
        "path": "/api/memory/search",
        "purpose": "search governed typed memory",
        "request": ["query", "workspace", "kind", "include_expired", "top_k"],
    },
    {
        "method": "POST",
        "path": "/api/memory/timeline",
        "purpose": "inspect typed-memory audit timeline",
        "request": ["workspace", "memory_key"],
    },
    {
        "method": "POST",
        "path": "/api/memory/graph",
        "purpose": "traverse typed-memory relation graph",
        "request": ["workspace", "memory_key", "depth"],
    },
    {
        "method": "GET",
        "path": "/health",
        "purpose": "vector-store readiness",
        "request": [],
    },
]


CLI_COMMANDS = [
    {
        "name": "agent:setup",
        "purpose": "generate MCP setup snippets for AI coding tools",
        "example": "npm run agent:setup -- claude-code",
    },
    {
        "name": "agent:doctor",
        "purpose": "check vector-store HTTP and MCP endpoints",
        "example": "npm run agent:doctor",
    },
    {
        "name": "agent:schema",
        "purpose": "print this AI-tool integration schema",
        "example": "npm run agent:schema -- --json",
    },
    {
        "name": "agent:health",
        "purpose": "score freshness, duplicate, entity, and replacement-candidate health for agent gates",
        "example": "npm run agent:health -- --json",
    },
    {
        "name": "agent:pack",
        "purpose": "inspect the built-in schema pack, safely classify paths, and detect corpus-level intake candidates",
        "example": "npm run agent:pack -- --detect ./notes --json",
    },
    {
        "name": "agent:think",
        "purpose": "ask for cited, PII-safe answer synthesis",
        "example": 'npm run agent:think -- "What changed?"',
    },
    {
        "name": "agent:search",
        "purpose": "search for ranked passage evidence",
        "example": 'npm run agent:search -- "remote MCP auth"',
    },
    {
        "name": "agent:import",
        "purpose": "bulk-import local text corpora",
        "example": "npm run agent:import -- ./notes",
        "dry_run_supported": True,
    },
    {
        "name": "agent:capture",
        "purpose": "capture one document or typed-memory record",
        "example": 'npm run agent:capture -- "Remember this"',
        "dry_run_supported": True,
    },
    {
        "name": "benchmark:agents",
        "purpose": "benchmark dependency-light agent features",
        "example": "npm run benchmark:agents",
    },
    {
        "name": "maintenance:snapshot",
        "purpose": "report stale, duplicate, and entity-maintenance candidates",
        "example": "npm run maintenance:snapshot",
    },
    {
        "name": "maintenance:plan",
        "purpose": "turn maintenance findings into a schedulable, review-required job plan",
        "example": "npm run maintenance:plan -- --json",
    },
    {
        "name": "maintenance:apply",
        "purpose": "turn a maintenance plan into a reviewable dry-run apply batch",
        "example": "npm run maintenance:apply -- --json --ledger-path /tmp/mindsage-maintenance.jsonl",
        "dry_run_supported": True,
        "ledger_supported": True,
    },
]


if __name__ == "__main__":
    raise SystemExit(main())
