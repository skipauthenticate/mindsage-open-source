"""Dependency-light MindSage health score for AI coding tools."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

try:
    from .maintenance_tool import (
        DEFAULT_CORPUS_DIR,
        build_maintenance_snapshot,
        format_maintenance_snapshot_report,
    )
except ImportError:  # Allows direct execution from the source checkout.
    from maintenance_tool import DEFAULT_CORPUS_DIR, build_maintenance_snapshot, format_maintenance_snapshot_report


def build_agent_health(
    documents: Sequence[Any],
    *,
    reference_date: Optional[dt.date] = None,
    freshness_days: int = 90,
) -> Dict[str, Any]:
    """Build a PII-safe health score from the maintenance snapshot."""

    snapshot = build_maintenance_snapshot(
        documents,
        reference_date=reference_date,
        freshness_days=freshness_days,
    )
    summary = snapshot["summary"]
    penalties = _health_penalties(summary)
    health_score = max(0, 100 - sum(penalty["points"] for penalty in penalties))
    gates = _health_gates(summary)
    report = {
        "schema_version": 1,
        "health_score": health_score,
        "status": _health_status(health_score),
        "snapshot_summary": summary,
        "gates": gates,
        "penalties": penalties,
        "jobs": snapshot.get("jobs", []),
        "recommended_commands": _recommended_commands(snapshot),
        "privacy": {
            "llm_context": "redacted",
            "pii_session_ids_exposed": bool(snapshot["privacy"].get("pii_session_ids_exposed")),
            "person_entities_exposed": bool(snapshot["privacy"].get("person_entities_exposed")),
        },
        "governance": {
            "source": "agent.health",
            "content": "redacted_maintenance_metadata_only",
            "freshness_days": freshness_days,
        },
    }
    return report


def format_agent_health_report(report: Dict[str, Any]) -> str:
    """Format a compact health report without raw document content."""

    lines = [
        f"MindSage agent health: {report['health_score']}/100 ({report['status']})",
        _summary_line(report["snapshot_summary"]),
    ]
    for gate in report["gates"]:
        status = "PASS" if gate["passed"] else "FAIL"
        lines.append(f"{gate['id']}: {status} - {gate['message']}")
    if report["recommended_commands"]:
        lines.append("Next:")
        lines.extend(f"- {command}" for command in report["recommended_commands"])
    return "\n".join(lines)


def load_text_corpus(corpus_dir: Path) -> List[Dict[str, Any]]:
    """Load a small text corpus as maintenance documents."""

    root = corpus_dir.expanduser()
    if not root.exists():
        raise FileNotFoundError(str(root))
    if root.is_file():
        paths = [root]
    else:
        paths = sorted(
            path for path in root.rglob("*.txt")
            if path.is_file() and not any(part.startswith(".") for part in path.parts)
        )
    documents = []
    for index, path in enumerate(paths, start=1):
        documents.append({
            "id": index,
            "text": path.read_text(encoding="utf-8"),
            "metadata": {
                "title": path.stem.replace("-", " ").replace("_", " ").title(),
                "source": "corpus",
                "relative_path": str(path.relative_to(root)) if root.is_dir() else path.name,
            },
        })
    return documents


def main(argv: Optional[List[str]] = None, *, stdout: Any = sys.stdout) -> int:
    parser = argparse.ArgumentParser(description="Score MindSage memory health for AI coding tools")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of a compact report")
    parser.add_argument("--corpus-dir", default=str(DEFAULT_CORPUS_DIR), help="Text corpus directory to inspect")
    parser.add_argument("--reference-date", default=None, help="YYYY-MM-DD reference date for freshness checks")
    parser.add_argument("--freshness-days", type=int, default=90)
    parser.add_argument("--include-snapshot", action="store_true", help="Append the raw maintenance snapshot report")

    args = parser.parse_args(argv)
    reference_date = _parse_reference_date(args.reference_date)
    documents = load_text_corpus(Path(args.corpus_dir))
    health = build_agent_health(
        documents,
        reference_date=reference_date,
        freshness_days=args.freshness_days,
    )

    if args.json:
        stdout.write(json.dumps(health, indent=2, sort_keys=True) + "\n")
    else:
        stdout.write(format_agent_health_report(health) + "\n")
        if args.include_snapshot:
            snapshot = build_maintenance_snapshot(
                documents,
                reference_date=reference_date,
                freshness_days=args.freshness_days,
            )
            stdout.write(format_maintenance_snapshot_report(snapshot) + "\n")
    return 0


def _health_penalties(summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    document_count = max(1, int(summary.get("document_count", 0)))
    stale_count = int(summary.get("stale_source_count", 0))
    undated_count = int(summary.get("undated_source_count", 0))
    duplicate_count = int(summary.get("duplicate_group_count", 0))
    entity_count = int(summary.get("entity_consolidation_count", 0))
    replacement_count = int(summary.get("replacement_candidate_count", 0))
    penalties = [
        _penalty("stale_sources", round(min(35, 35 * stale_count / document_count)), stale_count),
        _penalty("undated_sources", round(min(20, 20 * undated_count / document_count)), undated_count),
        _penalty("duplicate_groups", min(20, duplicate_count * 10), duplicate_count),
        _penalty("entity_consolidations", min(15, entity_count * 5), entity_count),
        _penalty("replacement_candidates", min(10, replacement_count * 2), replacement_count),
    ]
    return [penalty for penalty in penalties if penalty["points"] > 0]


def _penalty(reason: str, points: int, item_count: int) -> Dict[str, Any]:
    return {
        "reason": reason,
        "points": int(points),
        "item_count": int(item_count),
    }


def _health_gates(summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        _gate("freshness", summary.get("stale_source_count", 0) == 0, "stale sources need refresh"),
        _gate("dates", summary.get("undated_source_count", 0) == 0, "undated sources need date metadata"),
        _gate("duplicates", summary.get("duplicate_group_count", 0) == 0, "duplicate groups need consolidation"),
        _gate(
            "entity_consolidation",
            summary.get("entity_consolidation_count", 0) == 0,
            "safe entity label variants need consolidation",
        ),
        _gate(
            "replacement_candidates",
            summary.get("replacement_candidate_count", 0) == 0,
            "fresh replacement candidates should be reviewed",
        ),
    ]


def _gate(gate_id: str, passed: bool, failure_message: str) -> Dict[str, Any]:
    return {
        "id": gate_id,
        "passed": bool(passed),
        "message": "healthy" if passed else failure_message,
    }


def _recommended_commands(snapshot: Dict[str, Any]) -> List[str]:
    commands = []
    if snapshot.get("jobs"):
        commands.append("npm run maintenance:snapshot")
    if snapshot["summary"].get("replacement_candidate_count", 0):
        commands.append('npm run agent:search -- "fresh replacement evidence"')
    if snapshot["summary"].get("undated_source_count", 0):
        commands.append('npm run agent:capture -- --mode memory --kind claim "Add source dates for undated evidence."')
    return commands


def _summary_line(summary: Dict[str, Any]) -> str:
    return (
        "documents={document_count}, stale={stale_source_count}, undated={undated_source_count}, "
        "duplicate_groups={duplicate_group_count}, entity_consolidations={entity_consolidation_count}, "
        "replacement_candidates={replacement_candidate_count}"
    ).format(**summary)


def _health_status(score: int) -> str:
    if score >= 90:
        return "excellent"
    if score >= 75:
        return "good"
    if score >= 50:
        return "needs_attention"
    return "critical"


def _parse_reference_date(value: Optional[str]) -> Optional[dt.date]:
    if value is None or not str(value).strip():
        return None
    return dt.date.fromisoformat(str(value).strip())


if __name__ == "__main__":
    raise SystemExit(main())
