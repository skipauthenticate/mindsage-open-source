"""Dependency-light CLI for searching MindSage from agent shells."""

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
VALID_CONTEXTS = {"llm", "user"}


def build_search_request(
    query: str,
    *,
    top_k: int = 5,
    min_score: Optional[float] = 0.5,
    extract_passages: bool = True,
    max_excerpt_length: int = 500,
    context: str = "llm",
) -> Dict[str, Any]:
    """Build a REST request for enhanced MindSage search."""

    normalized_context = _clean_text(context, "context")
    if normalized_context not in VALID_CONTEXTS:
        raise ValueError("context must be 'llm' or 'user'")

    return {
        "type": "search",
        "endpoint": "/api/search/enhanced",
        "payload": {
            "query": _clean_text(query, "query"),
            "top_k": _bounded_int(top_k, "top_k", 1, 20),
            "min_score": _bounded_float(min_score, "min_score", 0.0, 1.0)
            if min_score is not None
            else None,
            "extract_passages": bool(extract_passages),
            "max_excerpt_length": _bounded_int(max_excerpt_length, "max_excerpt_length", 50, 2000),
            "context": normalized_context,
        },
    }


def read_query(
    query_args: List[str],
    *,
    stdin: Any = None,
    file_path: Optional[str] = None,
    encoding: str = "utf-8",
) -> str:
    """Read a search query from positional args, a file, or stdin."""

    if query_args:
        return _clean_text(" ".join(query_args), "query")

    if file_path:
        return _clean_text(Path(file_path).read_text(encoding=encoding), "query")

    stream = stdin if stdin is not None else sys.stdin
    return _clean_text(stream.read(), "query")


def send_search(
    search_request: Dict[str, Any],
    *,
    base_url: str = DEFAULT_BASE_URL,
    api_key: Optional[str] = None,
    timeout_seconds: float = 10.0,
    urlopen: Any = request.urlopen,
) -> Dict[str, Any]:
    """POST an enhanced search request to a local or remote MindSage server."""

    endpoint = search_request["endpoint"]
    payload = search_request["payload"]
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

    return {
        "status_code": status,
        "ok": 200 <= status < 300,
        "type": search_request.get("type", "search"),
        "endpoint": endpoint,
        "body": _decode_response_body(raw),
    }


def format_search_report(response: Dict[str, Any]) -> str:
    """Format ranked search results without echoing request text or tokens."""

    if not response.get("ok", True):
        return f"MindSage search: failed ({response.get('status_code')})"

    results = _response_results(response.get("body") or {})
    result_word = "result" if len(results) == 1 else "results"
    lines = [f"MindSage search: {len(results)} {result_word}"]
    for result in results:
        if not isinstance(result, dict):
            continue
        lines.append(_format_result_header(result))
        excerpt = _clean_optional_text(result.get("excerpt") or result.get("text"))
        if excerpt:
            lines.append(f"  {excerpt}")
    return "\n".join(lines)


def main(
    argv: Optional[List[str]] = None,
    *,
    urlopen: Any = request.urlopen,
    stdout: Any = sys.stdout,
) -> int:
    parser = argparse.ArgumentParser(description="Search MindSage for ranked, passage-sized evidence")
    parser.add_argument("query", nargs="*", help="Search query. If omitted, stdin is read.")
    parser.add_argument("--file", help="Read the query from a file when no args are supplied")
    parser.add_argument("--encoding", default="utf-8")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--api-key", default=None, help="Bearer token for protected remote servers")
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    parser.add_argument("--json", action="store_true", help="Emit JSON response instead of text")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--min-score", type=float, default=0.5)
    parser.add_argument("--no-passages", action="store_true", help="Return full matching text instead of excerpts")
    parser.add_argument("--max-excerpt-length", type=int, default=500)
    parser.add_argument(
        "--context",
        choices=sorted(VALID_CONTEXTS),
        default="llm",
        help="Use llm for redacted metadata or user for original metadata",
    )

    args = parser.parse_args(argv)
    query = read_query(args.query, file_path=args.file, encoding=args.encoding)
    search_request = build_search_request(
        query,
        top_k=args.top_k,
        min_score=args.min_score,
        extract_passages=not args.no_passages,
        max_excerpt_length=args.max_excerpt_length,
        context=args.context,
    )
    response = send_search(
        search_request,
        base_url=args.base_url,
        api_key=args.api_key,
        timeout_seconds=args.timeout_seconds,
        urlopen=urlopen,
    )

    if args.json:
        stdout.write(json.dumps(response, indent=2, sort_keys=True) + "\n")
    else:
        stdout.write(format_search_report(response) + "\n")
    return 0 if response.get("ok") else 1


def _response_results(body: Dict[str, Any]) -> List[Any]:
    if isinstance(body.get("results"), list):
        return body["results"]
    if isinstance(body.get("value"), list):
        return body["value"]
    return []


def _format_result_header(result: Dict[str, Any]) -> str:
    title = _result_title(result)
    doc_id = result.get("id", result.get("doc_id"))
    score = result.get("score")
    suffix = ""
    if doc_id is not None and isinstance(score, (int, float)):
        suffix = f" (#{doc_id}, score {score:.2f})"
    elif doc_id is not None:
        suffix = f" (#{doc_id})"
    elif isinstance(score, (int, float)):
        suffix = f" (score {score:.2f})"
    return f"- {title}{suffix}"


def _result_title(result: Dict[str, Any]) -> str:
    metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
    for key in ("title", "name", "filename", "relative_path", "source"):
        title = _clean_optional_text(metadata.get(key))
        if title:
            return title
    title = _clean_optional_text(result.get("title")) or _clean_optional_text(result.get("primary_topic"))
    return title or "Untitled result"


def _decode_response_body(raw: bytes) -> Dict[str, Any]:
    if not raw:
        return {}
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"raw_body_present": True}
    return decoded if isinstance(decoded, dict) else {"value": decoded}


def _clean_base_url(base_url: str) -> str:
    cleaned = _clean_text(base_url, "base_url").rstrip("/")
    if not cleaned.startswith(("http://", "https://")):
        raise ValueError("base_url must start with http:// or https://")
    return cleaned


def _clean_text(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _clean_optional_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _bounded_int(value: int, name: str, minimum: int, maximum: int) -> int:
    if not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    if value < minimum or value > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _bounded_float(value: float, name: str, minimum: float, maximum: float) -> float:
    if not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    normalized = float(value)
    if normalized < minimum or normalized > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return normalized


if __name__ == "__main__":
    raise SystemExit(main())
