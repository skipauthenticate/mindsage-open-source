"""Dependency-light CLI for asking MindSage for cited agent reasoning."""

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


def build_think_request(
    question: str,
    *,
    top_k: int = 8,
    min_score: Optional[float] = 0.5,
    freshness_days: int = 90,
    include_gaps: bool = True,
    max_excerpt_length: int = 700,
) -> Dict[str, Any]:
    """Build a REST request for the MindSage think endpoint."""

    return {
        "type": "think",
        "endpoint": "/api/think",
        "payload": {
            "question": _clean_text(question, "question"),
            "top_k": _bounded_int(top_k, "top_k", 1, 20),
            "min_score": _bounded_float(min_score, "min_score", 0.0, 1.0)
            if min_score is not None
            else None,
            "freshness_days": _bounded_int(freshness_days, "freshness_days", 1, 3650),
            "include_gaps": bool(include_gaps),
            "max_excerpt_length": _bounded_int(max_excerpt_length, "max_excerpt_length", 100, 2000),
        },
    }


def read_question(
    question_args: List[str],
    *,
    stdin: Any = None,
    file_path: Optional[str] = None,
    encoding: str = "utf-8",
) -> str:
    """Read a question from positional args, a file, or stdin."""

    if question_args:
        return _clean_text(" ".join(question_args), "question")

    if file_path:
        return _clean_text(Path(file_path).read_text(encoding=encoding), "question")

    stream = stdin if stdin is not None else sys.stdin
    return _clean_text(stream.read(), "question")


def send_think(
    think_request: Dict[str, Any],
    *,
    base_url: str = DEFAULT_BASE_URL,
    api_key: Optional[str] = None,
    timeout_seconds: float = 10.0,
    urlopen: Any = request.urlopen,
) -> Dict[str, Any]:
    """POST a think request to a local or remote MindSage server."""

    endpoint = think_request["endpoint"]
    payload = think_request["payload"]
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
        "type": think_request.get("type", "think"),
        "endpoint": endpoint,
        "body": _decode_response_body(raw),
    }


def format_think_report(response: Dict[str, Any]) -> str:
    """Format a compact think response without echoing request text or tokens."""

    if not response.get("ok", True):
        return f"MindSage think: failed ({response.get('status_code')})"

    body = response.get("body") or {}
    answer = _clean_optional_text(body.get("answer_brief")) or "No answer brief returned."
    citations = body.get("citations") if isinstance(body.get("citations"), list) else []
    gaps = body.get("gaps") if isinstance(body.get("gaps"), list) else []
    freshness = body.get("freshness") if isinstance(body.get("freshness"), dict) else {}
    freshness_status = _clean_optional_text(freshness.get("status")) or "unknown"

    lines = [
        f"MindSage think: {answer}",
        f"Citations: {len(citations)} | Gaps: {len(gaps)} | Freshness: {freshness_status}",
    ]
    source_lines = _format_source_lines(citations[:5])
    if source_lines:
        lines.append("Sources:")
        lines.extend(source_lines)
    return "\n".join(lines)


def main(
    argv: Optional[List[str]] = None,
    *,
    urlopen: Any = request.urlopen,
    stdout: Any = sys.stdout,
) -> int:
    parser = argparse.ArgumentParser(description="Ask MindSage for cited, PII-safe agent reasoning")
    parser.add_argument("question", nargs="*", help="Question to ask. If omitted, stdin is read.")
    parser.add_argument("--file", help="Read the question from a file when no args are supplied")
    parser.add_argument("--encoding", default="utf-8")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--api-key", default=None, help="Bearer token for protected remote servers")
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    parser.add_argument("--json", action="store_true", help="Emit JSON response instead of text")
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument("--min-score", type=float, default=0.5)
    parser.add_argument("--freshness-days", type=int, default=90)
    parser.add_argument("--no-gaps", action="store_true", help="Disable explicit gap reporting")
    parser.add_argument("--max-excerpt-length", type=int, default=700)

    args = parser.parse_args(argv)
    question = read_question(args.question, file_path=args.file, encoding=args.encoding)
    think_request = build_think_request(
        question,
        top_k=args.top_k,
        min_score=args.min_score,
        freshness_days=args.freshness_days,
        include_gaps=not args.no_gaps,
        max_excerpt_length=args.max_excerpt_length,
    )
    response = send_think(
        think_request,
        base_url=args.base_url,
        api_key=args.api_key,
        timeout_seconds=args.timeout_seconds,
        urlopen=urlopen,
    )

    if args.json:
        stdout.write(json.dumps(response, indent=2, sort_keys=True) + "\n")
    else:
        stdout.write(format_think_report(response) + "\n")
    return 0 if response.get("ok") else 1


def _format_source_lines(citations: List[Any]) -> List[str]:
    lines: List[str] = []
    for citation in citations:
        if not isinstance(citation, dict):
            continue
        title = _clean_optional_text(citation.get("title")) or "Untitled source"
        doc_id = citation.get("doc_id")
        score = citation.get("score")
        suffix = ""
        if doc_id is not None and isinstance(score, (int, float)):
            suffix = f" (#{doc_id}, score {score:.2f})"
        elif doc_id is not None:
            suffix = f" (#{doc_id})"
        elif isinstance(score, (int, float)):
            suffix = f" (score {score:.2f})"
        lines.append(f"- {title}{suffix}")
    return lines


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
