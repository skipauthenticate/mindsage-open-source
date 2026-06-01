"""Dependency-light CLI for importing local text corpora into MindSage."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set
from urllib import error, request

try:
    from .remote_auth import build_auth_headers, resolve_remote_api_key
except ImportError:  # Allows direct execution from the source checkout.
    from remote_auth import build_auth_headers, resolve_remote_api_key


DEFAULT_BASE_URL = "http://localhost:8085"
IMPORT_TOOL_NAME = "mindsage-agent-import"
DEFAULT_EXTENSIONS = {".csv", ".json", ".log", ".markdown", ".md", ".txt"}
PII_SESSION_KEYS = {"pii_session_id", "piiSessionId"}


def collect_import_documents(
    paths: List[str],
    *,
    metadata: Optional[Dict[str, Any]] = None,
    extensions: Optional[Set[str]] = None,
    recursive: bool = True,
    encoding: str = "utf-8",
) -> List[Dict[str, Any]]:
    """Collect supported text files as MindSage batch-import documents."""

    safe_metadata = _sanitize_metadata(metadata or {})
    allowed_extensions = _normalize_extensions(extensions or DEFAULT_EXTENSIONS)
    documents: List[Dict[str, Any]] = []
    for raw_path in paths:
        root = Path(raw_path).expanduser()
        if not root.exists():
            raise FileNotFoundError(str(root))
        for file_path in _iter_import_files(root, allowed_extensions, recursive=recursive):
            text = _clean_text(file_path.read_text(encoding=encoding))
            doc_metadata = {
                **safe_metadata,
                "import_tool": IMPORT_TOOL_NAME,
                "filename": file_path.name,
                "extension": file_path.suffix.lower(),
                "relative_path": _relative_path(file_path, root),
            }
            documents.append({"text": text, "metadata": doc_metadata})

    if not documents:
        raise ValueError("no supported text files found to import")
    return documents


def build_import_request(
    documents: List[Dict[str, Any]],
    *,
    skip_duplicates: bool = True,
    extract_key_passages: bool = False,
) -> Dict[str, Any]:
    """Build a REST batch-import request."""

    if not documents:
        raise ValueError("documents must not be empty")
    return {
        "type": "import",
        "endpoint": "/api/documents/batch",
        "payload": {
            "documents": [
                {
                    "text": _clean_text(str(document.get("text", ""))),
                    "metadata": _sanitize_metadata(document.get("metadata") or {}),
                }
                for document in documents
            ],
            "skip_duplicates": bool(skip_duplicates),
            "extract_key_passages": bool(extract_key_passages),
        },
    }


def send_import(
    import_request: Dict[str, Any],
    *,
    base_url: str = DEFAULT_BASE_URL,
    api_key: Optional[str] = None,
    timeout_seconds: float = 30.0,
    urlopen: Any = request.urlopen,
) -> Dict[str, Any]:
    """POST a batch import request to a local or remote MindSage server."""

    endpoint = import_request["endpoint"]
    payload = import_request["payload"]
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
        "type": import_request.get("type", "import"),
        "endpoint": endpoint,
        "body": _decode_response_body(raw),
    }


def build_import_dry_run(import_request: Dict[str, Any]) -> Dict[str, Any]:
    """Build a safe import preview without raw document text."""

    payload = import_request.get("payload") if isinstance(import_request.get("payload"), dict) else {}
    documents = payload.get("documents") if isinstance(payload.get("documents"), list) else []
    filenames = []
    extensions = set()
    total_text_bytes = 0
    metadata_keys = set()
    for document in documents:
        if not isinstance(document, dict):
            continue
        text = str(document.get("text", ""))
        total_text_bytes += len(text.encode("utf-8"))
        metadata = document.get("metadata") if isinstance(document.get("metadata"), dict) else {}
        filename = metadata.get("filename")
        if filename:
            filenames.append(str(filename))
        extension = metadata.get("extension")
        if extension:
            extensions.add(str(extension))
        metadata_keys.update(str(key) for key in metadata.keys())

    return {
        "status_code": 0,
        "ok": True,
        "dry_run": True,
        "type": import_request.get("type", "import"),
        "endpoint": import_request.get("endpoint"),
        "payload_summary": {
            "document_count": len(documents),
            "filenames": sorted(filenames),
            "extensions": sorted(extensions),
            "metadata_keys": sorted(metadata_keys),
            "total_text_bytes": total_text_bytes,
            "skip_duplicates": bool(payload.get("skip_duplicates", True)),
            "extract_key_passages": bool(payload.get("extract_key_passages", False)),
        },
        "body": {},
    }


def format_import_report(response: Dict[str, Any]) -> str:
    """Format a batch import response without echoing imported text or tokens."""

    if response.get("dry_run"):
        summary = response.get("payload_summary") or {}
        count = _nonnegative_int(summary.get("document_count", 0))
        byte_count = _nonnegative_int(summary.get("total_text_bytes", 0))
        document_word = "document" if count == 1 else "documents"
        return f"MindSage import dry run: would import {count} {document_word} ({byte_count} bytes)"

    if not response.get("ok", True):
        return f"MindSage import: failed ({response.get('status_code')})"

    body = response.get("body") or {}
    count = _nonnegative_int(body.get("count", len(body.get("document_ids", []) or [])))
    duplicates = _nonnegative_int(body.get("duplicates_skipped", 0))
    duplicate_word = "duplicate" if duplicates == 1 else "duplicates"
    return f"MindSage import: imported {count} documents, skipped {duplicates} {duplicate_word}"


def main(
    argv: Optional[List[str]] = None,
    *,
    urlopen: Any = request.urlopen,
    stdout: Any = None,
) -> int:
    import sys

    parser = argparse.ArgumentParser(description="Import local text files into MindSage")
    parser.add_argument("paths", nargs="+", help="File or directory paths to import")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--api-key", default=None, help="Bearer token for protected remote servers")
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--json", action="store_true", help="Emit JSON response instead of text")
    parser.add_argument("--dry-run", action="store_true", help="Preview the import without posting to MindSage")
    parser.add_argument("--metadata", action="append", default=[], help="Extra metadata as key=value")
    parser.add_argument("--extensions", default=",".join(sorted(DEFAULT_EXTENSIONS)))
    parser.add_argument("--encoding", default="utf-8")
    parser.add_argument("--no-recursive", action="store_true")
    parser.add_argument("--allow-duplicates", action="store_true")
    parser.add_argument("--extract-key-passages", action="store_true")

    args = parser.parse_args(argv)
    output = stdout if stdout is not None else sys.stdout
    documents = collect_import_documents(
        args.paths,
        metadata=_parse_metadata(args.metadata),
        extensions=_parse_extensions_arg(args.extensions),
        recursive=not args.no_recursive,
        encoding=args.encoding,
    )
    import_request = build_import_request(
        documents,
        skip_duplicates=not args.allow_duplicates,
        extract_key_passages=args.extract_key_passages,
    )
    if args.dry_run:
        response = build_import_dry_run(import_request)
    else:
        response = send_import(
            import_request,
            base_url=args.base_url,
            api_key=args.api_key,
            timeout_seconds=args.timeout_seconds,
            urlopen=urlopen,
        )

    if args.json:
        output.write(json.dumps(response, indent=2, sort_keys=True) + "\n")
    else:
        output.write(format_import_report(response) + "\n")
    return 0 if response.get("ok") else 1


def _iter_import_files(root: Path, extensions: Set[str], *, recursive: bool) -> Iterable[Path]:
    if root.is_file():
        if _is_supported_file(root, extensions):
            yield root
        return

    iterator = root.rglob("*") if recursive else root.glob("*")
    for path in sorted(iterator, key=lambda item: str(item).lower()):
        if _is_supported_file(path, extensions):
            yield path


def _is_supported_file(path: Path, extensions: Set[str]) -> bool:
    if not path.is_file() or path.name.startswith("."):
        return False
    if any(part.startswith(".") for part in path.parts):
        return False
    return path.suffix.lower() in extensions


def _relative_path(file_path: Path, root: Path) -> str:
    base = root if root.is_dir() else root.parent
    try:
        return str(file_path.relative_to(base))
    except ValueError:
        return file_path.name


def _parse_metadata(items: List[str]) -> Dict[str, str]:
    metadata: Dict[str, str] = {}
    for item in items:
        key, separator, value = str(item).partition("=")
        if not separator or not key.strip():
            raise ValueError("metadata entries must use key=value")
        metadata[key.strip()] = value.strip()
    return _sanitize_metadata(metadata)


def _parse_extensions_arg(value: str) -> Set[str]:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("extensions must be a comma-separated list")
    return _normalize_extensions({part.strip() for part in value.split(",") if part.strip()})


def _normalize_extensions(values: Set[str]) -> Set[str]:
    extensions = set()
    for value in values:
        extension = str(value).strip().lower()
        if not extension:
            continue
        extensions.add(extension if extension.startswith(".") else f".{extension}")
    if not extensions:
        raise ValueError("at least one extension is required")
    return extensions


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


def _decode_response_body(raw: bytes) -> Dict[str, Any]:
    if not raw:
        return {}
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"raw_body_present": True}
    return decoded if isinstance(decoded, dict) else {"value": decoded}


def _clean_base_url(base_url: str) -> str:
    cleaned = _clean_text(base_url).rstrip("/")
    if not cleaned.startswith(("http://", "https://")):
        raise ValueError("base_url must start with http:// or https://")
    return cleaned


def _clean_text(text: str) -> str:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("text must be a non-empty string")
    return text.strip()


def _nonnegative_int(value: Any) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, number)


if __name__ == "__main__":
    raise SystemExit(main())
