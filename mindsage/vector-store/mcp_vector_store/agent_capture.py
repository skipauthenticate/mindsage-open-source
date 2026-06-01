"""Dependency-light CLI for capturing agent notes into MindSage."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib import error, request

try:
    from .remote_auth import build_auth_headers, resolve_remote_api_key
except ImportError:  # Allows direct execution from the source checkout.
    from remote_auth import build_auth_headers, resolve_remote_api_key


DEFAULT_BASE_URL = "http://localhost:8085"
CAPTURE_TOOL_NAME = "mindsage-agent-capture"
PII_SESSION_KEYS = {"pii_session_id", "piiSessionId"}


def build_capture_request(
    text: str,
    *,
    mode: str = "document",
    metadata: Optional[Dict[str, Any]] = None,
    kind: str = "note",
    workspace: str = "default",
    actor: str = "agent",
    memory_key: Optional[str] = None,
    state: str = "accepted",
    source_document_id: Optional[int] = None,
    relations: Optional[List[Dict[str, Any]]] = None,
    ttl_days: Optional[int] = None,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a REST capture request for a document or typed memory."""

    normalized_text = _clean_text(text)
    normalized_mode = _normalize_mode(mode)
    safe_metadata = _sanitize_metadata(metadata or {})
    safe_metadata.setdefault("capture_tool", CAPTURE_TOOL_NAME)

    if normalized_mode == "document":
        return {
            "type": "document",
            "endpoint": "/api/documents",
            "payload": {
                "text": normalized_text,
                "metadata": safe_metadata,
            },
        }

    return {
        "type": "memory",
        "endpoint": "/api/memory",
        "payload": {
            "kind": _clean_required(kind, "kind"),
            "content": normalized_text,
            "workspace": _clean_required(workspace, "workspace"),
            "actor": _clean_required(actor, "actor"),
            "memory_key": _clean_optional(memory_key),
            "state": _clean_required(state, "state"),
            "source_document_id": source_document_id,
            "relations": relations,
            "ttl_days": ttl_days,
            "metadata": safe_metadata,
            "reason": _clean_optional(reason),
        },
    }


def read_capture_text(
    text_args: List[str],
    *,
    stdin: Any = None,
    file_path: Optional[str] = None,
    encoding: str = "utf-8",
) -> str:
    """Read capture text from positional args, a file, or stdin."""

    if text_args:
        return _clean_text(" ".join(text_args))

    if file_path:
        return _clean_text(Path(file_path).read_text(encoding=encoding))

    stream = stdin if stdin is not None else sys.stdin
    return _clean_text(stream.read())


def send_capture(
    capture_request: Dict[str, Any],
    *,
    base_url: str = DEFAULT_BASE_URL,
    api_key: Optional[str] = None,
    timeout_seconds: float = 10.0,
    urlopen: Any = request.urlopen,
) -> Dict[str, Any]:
    """POST a capture request to a local or remote MindSage server."""

    endpoint = capture_request["endpoint"]
    payload = capture_request["payload"]
    url = f"{_clean_base_url(base_url)}{endpoint}"
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        **build_auth_headers(resolve_remote_api_key(api_key)),
    }
    req = request.Request(url, data=body, headers=headers, method="POST")

    try:
        with urlopen(req, timeout=timeout_seconds) as response:
            raw = response.read()
            status = int(getattr(response, "status", getattr(response, "code", 200)))
    except error.HTTPError as exc:
        try:
            raw = exc.read()
        finally:
            exc.close()
        status = int(exc.code)

    response_body = _decode_response_body(raw)
    return {
        "status_code": status,
        "ok": 200 <= status < 300,
        "type": capture_request.get("type"),
        "endpoint": endpoint,
        "body": response_body,
    }


def build_capture_dry_run(capture_request: Dict[str, Any]) -> Dict[str, Any]:
    """Build a safe capture preview without raw captured content."""

    payload = capture_request.get("payload") if isinstance(capture_request.get("payload"), dict) else {}
    capture_type = capture_request.get("type") or "capture"
    content = payload.get("content") if capture_type == "memory" else payload.get("text")
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    summary: Dict[str, Any] = {
        "content_bytes": len(str(content or "").encode("utf-8")),
        "metadata_keys": sorted(str(key) for key in metadata.keys()),
    }
    if capture_type == "memory":
        summary.update({
            "kind": payload.get("kind"),
            "workspace": payload.get("workspace"),
            "actor": payload.get("actor"),
            "memory_key": payload.get("memory_key"),
            "state": payload.get("state"),
            "relation_count": len(payload.get("relations") or []),
            "ttl_days": payload.get("ttl_days"),
        })

    return {
        "status_code": 0,
        "ok": True,
        "dry_run": True,
        "type": capture_type,
        "endpoint": capture_request.get("endpoint"),
        "payload_summary": summary,
        "body": {},
    }


def format_capture_report(response: Dict[str, Any], *, request_type: Optional[str] = None) -> str:
    """Format a capture response without echoing captured content or tokens."""

    if response.get("dry_run"):
        capture_type = request_type or response.get("type") or "capture"
        byte_count = (response.get("payload_summary") or {}).get("content_bytes", 0)
        return f"MindSage capture dry run: would store {capture_type} ({byte_count} bytes)"

    body = response.get("body") or {}
    capture_type = request_type or response.get("type") or "capture"
    if capture_type == "document" and body.get("document_id") is not None:
        return f"MindSage capture: stored document {body['document_id']}"
    memory = body.get("memory") if isinstance(body.get("memory"), dict) else {}
    memory_key = memory.get("memory_key")
    if capture_type == "memory" and memory_key:
        return f"MindSage capture: stored memory {memory_key}"
    if body.get("success") is False or not response.get("ok", True):
        return f"MindSage capture: failed ({response.get('status_code')})"
    return f"MindSage capture: stored {capture_type}"


def main(
    argv: Optional[List[str]] = None,
    *,
    urlopen: Any = request.urlopen,
    stdout: Any = sys.stdout,
) -> int:
    parser = argparse.ArgumentParser(description="Capture a note or typed memory into MindSage")
    parser.add_argument("text", nargs="*", help="Text to capture. If omitted, stdin is read.")
    parser.add_argument("--mode", choices=["document", "memory"], default="document")
    parser.add_argument("--file", help="Read capture text from a file when no text args are supplied")
    parser.add_argument("--encoding", default="utf-8")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--api-key", default=None, help="Bearer token for protected remote servers")
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    parser.add_argument("--json", action="store_true", help="Emit JSON response instead of text")
    parser.add_argument("--dry-run", action="store_true", help="Preview the write without posting to MindSage")
    parser.add_argument("--metadata", action="append", default=[], help="Extra metadata as key=value")

    parser.add_argument("--kind", default="note")
    parser.add_argument("--workspace", default="default")
    parser.add_argument("--actor", default="agent")
    parser.add_argument("--memory-key", default=None)
    parser.add_argument("--state", default="accepted")
    parser.add_argument("--source-document-id", type=int, default=None)
    parser.add_argument("--ttl-days", type=int, default=None)
    parser.add_argument("--reason", default=None)

    args = parser.parse_args(argv)
    text = read_capture_text(args.text, file_path=args.file, encoding=args.encoding)
    capture_request = build_capture_request(
        text,
        mode=args.mode,
        metadata=_parse_metadata(args.metadata),
        kind=args.kind,
        workspace=args.workspace,
        actor=args.actor,
        memory_key=args.memory_key,
        state=args.state,
        source_document_id=args.source_document_id,
        ttl_days=args.ttl_days,
        reason=args.reason,
    )
    if args.dry_run:
        response = build_capture_dry_run(capture_request)
    else:
        response = send_capture(
            capture_request,
            base_url=args.base_url,
            api_key=args.api_key,
            timeout_seconds=args.timeout_seconds,
            urlopen=urlopen,
        )

    if args.json:
        stdout.write(json.dumps(response, indent=2, sort_keys=True) + "\n")
    else:
        stdout.write(format_capture_report(response, request_type=args.mode) + "\n")
    return 0 if response.get("ok") else 1


def _parse_metadata(items: List[str]) -> Dict[str, str]:
    metadata: Dict[str, str] = {}
    for item in items:
        key, separator, value = str(item).partition("=")
        if not separator or not key.strip():
            raise ValueError("metadata entries must use key=value")
        metadata[key.strip()] = value.strip()
    return _sanitize_metadata(metadata)


def _decode_response_body(raw: bytes) -> Dict[str, Any]:
    if not raw:
        return {}
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"raw_body_present": True}
    return decoded if isinstance(decoded, dict) else {"value": decoded}


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


def _normalize_mode(mode: str) -> str:
    normalized = _clean_required(mode, "mode").lower().replace("_", "-")
    aliases = {"doc": "document", "note": "document", "typed-memory": "memory"}
    normalized = aliases.get(normalized, normalized)
    if normalized not in {"document", "memory"}:
        raise ValueError("mode must be document or memory")
    return normalized


def _clean_base_url(base_url: str) -> str:
    cleaned = _clean_required(base_url, "base_url").rstrip("/")
    if not cleaned.startswith(("http://", "https://")):
        raise ValueError("base_url must start with http:// or https://")
    return cleaned


def _clean_text(text: str) -> str:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("capture text must be a non-empty string")
    return text.strip()


def _clean_required(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _clean_optional(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


if __name__ == "__main__":
    raise SystemExit(main())
