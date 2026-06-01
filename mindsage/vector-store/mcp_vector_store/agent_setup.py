"""Generate MCP setup snippets for AI coding tools."""

from __future__ import annotations

import argparse
import json
import socket
from typing import Any, Callable, Dict, List
from urllib import request


DEFAULT_BASE_URL = "http://localhost:8085"
DEFAULT_SERVER_NAME = "mindsage-search"
REMOTE_API_KEY_ENV = "MCP_VECTOR_STORE_API_KEY"

MCP_JSON_CLIENTS = {
    "continue",
    "claude-desktop",
    "cursor",
    "gemini-cli",
    "mcp-json",
    "trae",
    "vscode",
    "windsurf",
    "zed",
}
CODEX_CLIENTS = {"codex"}
SUPPORTED_CLIENTS = MCP_JSON_CLIENTS | CODEX_CLIENTS | {"claude-code"}


def supported_clients() -> List[str]:
    """Return supported client names for docs and schema generation."""

    return sorted(SUPPORTED_CLIENTS)


def generate_setup(
    client: str,
    *,
    mode: str = "local",
    server_name: str = DEFAULT_SERVER_NAME,
    base_url: str = DEFAULT_BASE_URL,
) -> str:
    """Return a ready-to-use MCP setup snippet for an AI coding tool."""

    normalized_client = _normalize_client(client)
    normalized_mode = _normalize_mode(mode)
    normalized_server_name = _clean_server_name(server_name)
    normalized_base_url = _clean_base_url(base_url)

    if normalized_client == "claude-code":
        return _claude_code_setup(
            mode=normalized_mode,
            server_name=normalized_server_name,
            base_url=normalized_base_url,
        )

    if normalized_client in CODEX_CLIENTS:
        return _codex_toml_config(
            mode=normalized_mode,
            server_name=normalized_server_name,
            base_url=normalized_base_url,
        )

    if normalized_mode == "local":
        return json.dumps(
            _local_mcp_remote_config(
                server_name=normalized_server_name,
                base_url=normalized_base_url,
            ),
            indent=2,
            sort_keys=True,
        )

    return json.dumps(
        _remote_stdio_config(
            server_name=normalized_server_name,
            base_url=normalized_base_url,
        ),
        indent=2,
        sort_keys=True,
    )


def run_doctor(
    base_url: str = DEFAULT_BASE_URL,
    *,
    timeout_seconds: float = 2.0,
    urlopen: Callable[..., Any] = request.urlopen,
) -> Dict[str, Any]:
    """Check whether the local vector-store HTTP and MCP endpoints are reachable."""

    normalized_base_url = _clean_base_url(base_url)
    checks = [
        _endpoint_check(
            "health",
            f"{normalized_base_url}/health",
            timeout_seconds=timeout_seconds,
            urlopen=urlopen,
        ),
        _endpoint_check(
            "mcp_sse",
            _sse_url(normalized_base_url),
            timeout_seconds=timeout_seconds,
            urlopen=urlopen,
        ),
    ]
    return {
        "base_url": normalized_base_url,
        "passed": all(check["passed"] for check in checks),
        "checks": checks,
    }


def format_doctor_report(report: Dict[str, Any]) -> str:
    """Format a doctor report for terminal output."""

    status = "PASS" if report["passed"] else "FAIL"
    lines = [f"MindSage agent setup doctor: {status} ({report['base_url']})"]
    for check in report["checks"]:
        check_status = "PASS" if check["passed"] else "FAIL"
        lines.append(f"{check_status} {check['id']} - {check['url']}")
        if check.get("error"):
            lines.append(f"  - {check['error']}")
    return "\n".join(lines)


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate MindSage MCP setup snippets")
    subparsers = parser.add_subparsers(dest="command", required=True)

    setup_parser = subparsers.add_parser("setup", help="Print an MCP setup snippet")
    setup_parser.add_argument(
        "client",
        choices=sorted(SUPPORTED_CLIENTS),
        help="AI coding tool or generic MCP JSON target",
    )
    setup_parser.add_argument("--mode", choices=["local", "remote"], default="local")
    setup_parser.add_argument("--server-name", default=DEFAULT_SERVER_NAME)
    setup_parser.add_argument("--base-url", default=DEFAULT_BASE_URL)

    doctor_parser = subparsers.add_parser("doctor", help="Check local MindSage endpoints")
    doctor_parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    doctor_parser.add_argument("--timeout-seconds", type=float, default=2.0)
    doctor_parser.add_argument("--json", action="store_true", help="Emit JSON instead of text")

    args = parser.parse_args(argv)
    if args.command == "setup":
        print(
            generate_setup(
                args.client,
                mode=args.mode,
                server_name=args.server_name,
                base_url=args.base_url,
            )
        )
        return 0

    report = run_doctor(args.base_url, timeout_seconds=args.timeout_seconds)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(format_doctor_report(report))
    return 0 if report["passed"] else 1


def _local_mcp_remote_config(*, server_name: str, base_url: str) -> Dict[str, Any]:
    args = [
        "-y",
        "mcp-remote",
        _sse_url(base_url),
        "--transport",
        "sse-only",
    ]
    if base_url.startswith("http://"):
        args.append("--allow-http")
    return {
        "mcpServers": {
            server_name: {
                "command": "npx",
                "args": args,
            }
        }
    }


def _remote_stdio_config(*, server_name: str, base_url: str) -> Dict[str, Any]:
    return {
        "mcpServers": {
            server_name: {
                "command": "python3",
                "args": [
                    "mindsage/vector-store/mcp_vector_store/mcp_server_stdio.py",
                    "--url",
                    base_url,
                ],
                "env": {
                    REMOTE_API_KEY_ENV: f"${{{REMOTE_API_KEY_ENV}}}",
                },
            }
        }
    }


def _codex_toml_config(*, mode: str, server_name: str, base_url: str) -> str:
    args = [
        "mindsage/vector-store/mcp_vector_store/mcp_server_stdio.py",
        "--url",
        base_url,
    ]
    lines = [
        f"[mcp_servers.{_toml_key(server_name)}]",
        'command = "python3"',
        "args = [",
        *[f"  {_toml_string(arg)}," for arg in args],
        "]",
        "startup_timeout_ms = 20000",
    ]
    if mode == "remote":
        lines.extend([
            "",
            f"[mcp_servers.{_toml_key(server_name)}.env]",
            f"{REMOTE_API_KEY_ENV} = {_toml_string('${' + REMOTE_API_KEY_ENV + '}')}",
        ])
    return "\n".join(lines)


def _claude_code_setup(*, mode: str, server_name: str, base_url: str) -> str:
    if mode == "local":
        return f"claude mcp add {server_name} --transport sse-only {_sse_url(base_url)}"
    return (
        f"claude mcp add {server_name} -- python3 "
        "mindsage/vector-store/mcp_vector_store/mcp_server_stdio.py "
        f"--url {base_url}"
    )


def _endpoint_check(
    check_id: str,
    url: str,
    *,
    timeout_seconds: float,
    urlopen: Callable[..., Any],
) -> Dict[str, Any]:
    req = request.Request(url, headers={"Accept": "text/event-stream" if url.endswith("/sse") else "application/json"})
    try:
        with urlopen(req, timeout=timeout_seconds) as response:
            status = getattr(response, "status", 200)
        return {
            "id": check_id,
            "url": url,
            "passed": 200 <= int(status) < 400,
            "status_code": int(status),
        }
    except (OSError, socket.timeout, TimeoutError) as exc:
        return {
            "id": check_id,
            "url": url,
            "passed": False,
            "error": str(exc),
        }


def _normalize_client(client: str) -> str:
    normalized = str(client or "").strip().lower()
    aliases = {
        "claude": "claude-code",
        "claude_code": "claude-code",
        "claude desktop": "claude-desktop",
        "claude_desktop": "claude-desktop",
        "codex cli": "codex",
        "codex-cli": "codex",
        "openai-codex": "codex",
        "openai codex": "codex",
        "gemini": "gemini-cli",
        "gemini cli": "gemini-cli",
        "gemini_cli": "gemini-cli",
        "json": "mcp-json",
        "vs code": "vscode",
        "visual-studio-code": "vscode",
        "visual studio code": "vscode",
        "continue.dev": "continue",
        "continue-dev": "continue",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in SUPPORTED_CLIENTS:
        allowed = ", ".join(sorted(SUPPORTED_CLIENTS))
        raise ValueError(f"Unsupported client '{client}'. Supported clients: {allowed}")
    return normalized


def _normalize_mode(mode: str) -> str:
    normalized = str(mode or "").strip().lower()
    if normalized not in {"local", "remote"}:
        raise ValueError("mode must be 'local' or 'remote'")
    return normalized


def _clean_server_name(server_name: str) -> str:
    cleaned = str(server_name or "").strip()
    if not cleaned:
        raise ValueError("server_name must be a non-empty string")
    return cleaned


def _clean_base_url(base_url: str) -> str:
    cleaned = str(base_url or "").strip().rstrip("/")
    if not cleaned.startswith(("http://", "https://")):
        raise ValueError("base_url must start with http:// or https://")
    return cleaned[:-4] if cleaned.endswith("/sse") else cleaned


def _sse_url(base_url: str) -> str:
    return f"{_clean_base_url(base_url)}/sse"


def _toml_key(value: str) -> str:
    return _toml_string(value)


def _toml_string(value: str) -> str:
    return json.dumps(str(value))


if __name__ == "__main__":
    raise SystemExit(main())
