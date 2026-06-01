"""Dependency-light MindSage schema pack for agent intake planning."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence


PACK_ID = "mindsage-personal-v1"
MEMORY_KINDS = ["decision", "claim", "task", "artifact", "entity", "relation", "summary"]

DOCUMENT_CATEGORIES: List[Dict[str, Any]] = [
    {
        "id": "ai_chat",
        "label": "AI chat export",
        "signals": ["chatgpt", "claude", "gemini", "conversation", "transcript"],
        "recommended_memory_kind": "summary",
        "risk_level": "medium",
    },
    {
        "id": "finance",
        "label": "Financial record",
        "signals": ["bank", "statement", "w2", "tax", "invoice", "receipt", "investment", "credit"],
        "recommended_memory_kind": "claim",
        "risk_level": "high",
    },
    {
        "id": "health",
        "label": "Health record",
        "signals": ["health", "medical", "prescription", "dental", "vision", "lab", "therapy", "doctor"],
        "recommended_memory_kind": "claim",
        "risk_level": "high",
    },
    {
        "id": "identity",
        "label": "Identity document",
        "signals": ["passport", "license", "ssn", "identity", "id-card", "insurance-card"],
        "recommended_memory_kind": "artifact",
        "risk_level": "high",
    },
    {
        "id": "travel",
        "label": "Travel record",
        "signals": ["travel", "booking", "reservation", "flight", "hotel", "itinerary"],
        "recommended_memory_kind": "artifact",
        "risk_level": "medium",
    },
    {
        "id": "project_notes",
        "label": "Project notes",
        "signals": ["readme", "notes", "decision", "todo", "task", "adr"],
        "recommended_memory_kind": "decision",
        "risk_level": "low",
    },
    {
        "id": "generic_text",
        "label": "Generic text",
        "signals": [],
        "recommended_memory_kind": "summary",
        "risk_level": "low",
    },
]


def build_schema_pack() -> Dict[str, Any]:
    """Return the built-in schema pack without inspecting user content."""

    return {
        "schema_version": 1,
        "pack_id": PACK_ID,
        "product": "MindSage",
        "purpose": "Classify local personal-data sources into safe intake routes and typed-memory defaults.",
        "memory_kinds": list(MEMORY_KINDS),
        "document_categories": [dict(category) for category in DOCUMENT_CATEGORIES],
        "recommended_intake": {
            "preview_first": "npm run agent:import -- --dry-run <path>",
            "capture_memory": "npm --silent run agent:capture -- --dry-run --mode memory --kind <kind>",
            "ask_with_citations": "npm run agent:think -- <question>",
        },
        "safety": {
            "llm_context": "redacted",
            "path_content_policy": "Do not echo raw file paths, filenames, document text, or bearer tokens in reports.",
            "default_write_mode": "dry-run",
            "high_risk_categories": [
                category["id"] for category in DOCUMENT_CATEGORIES
                if category["risk_level"] == "high"
            ],
        },
    }


def classify_path(path: str) -> Dict[str, Any]:
    """Classify a path from its sanitized name signals without returning the path."""

    cleaned = str(path or "").strip()
    if not cleaned:
        raise ValueError("path must be a non-empty string")

    path_obj = Path(cleaned)
    extension = path_obj.suffix.lower()
    signal_text = _normalize_signal_text(path_obj.name)
    category, match_count = _best_category(signal_text)
    confidence = 0.8 if match_count else 0.35
    return {
        "schema_version": 1,
        "pack_id": PACK_ID,
        "path_fingerprint": hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:12],
        "extension": extension,
        "category_id": category["id"],
        "recommended_memory_kind": category["recommended_memory_kind"],
        "risk_level": category["risk_level"],
        "confidence": confidence,
        "matched_signal_count": match_count,
        "llm_safe": True,
        "path_exposed": False,
        "recommended_commands": _recommended_commands(category),
    }


def detect_schema_candidates(paths: Sequence[str], *, max_files: int = 500) -> Dict[str, Any]:
    """Detect corpus-level schema candidates without exposing paths or reading content."""

    if not paths:
        raise ValueError("at least one path is required")

    category_counts: Counter[str] = Counter()
    memory_kind_counts: Counter[str] = Counter()
    extension_counts: Counter[str] = Counter()
    risk_counts: Counter[str] = Counter()
    signal_counts: Counter[str] = Counter()
    scanned_directories = 0
    scanned_files = 0
    skipped_files = 0

    for raw_path in paths:
        cleaned = str(raw_path or "").strip()
        if not cleaned:
            continue
        path = Path(cleaned)
        if path.is_dir():
            scanned_directories += 1
            candidates = sorted(
                (child for child in path.rglob("*") if child.is_file() and not _is_hidden_path(child)),
                key=lambda child: child.as_posix(),
            )
        elif path.is_file():
            candidates = [path]
        else:
            skipped_files += 1
            continue

        for child in candidates:
            if scanned_files >= max_files:
                skipped_files += 1
                continue
            classification = classify_path(child.name)
            scanned_files += 1
            category_counts[classification["category_id"]] += 1
            memory_kind_counts[classification["recommended_memory_kind"]] += 1
            extension_counts[classification["extension"] or "<none>"] += 1
            risk_counts[classification["risk_level"]] += 1
            signal_counts[classification["category_id"]] += int(classification["matched_signal_count"] or 0)

    schema_candidates = [
        _schema_candidate(
            category_id=category_id,
            file_count=count,
            matched_signal_count=signal_counts[category_id],
        )
        for category_id, count in sorted(category_counts.items())
    ]
    detection = {
        "schema_version": 1,
        "pack_id": PACK_ID,
        "input_fingerprint": _input_fingerprint(paths),
        "scanned": {
            "directory_count": scanned_directories,
            "file_count": scanned_files,
            "skipped_count": skipped_files,
            "max_files": max_files,
        },
        "summary": {
            "category_counts": dict(sorted(category_counts.items())),
            "recommended_memory_kind_counts": dict(sorted(memory_kind_counts.items())),
            "extension_counts": dict(sorted(extension_counts.items())),
            "risk_counts": dict(sorted(risk_counts.items())),
            "high_risk_file_count": sum(
                count for risk, count in risk_counts.items()
                if risk == "high"
            ),
        },
        "schema_candidates": schema_candidates,
        "review": {
            "default_action": "review_before_import",
            "recommended_commands": [
                "npm run agent:pack -- --detect <path> --json",
                "npm run agent:import -- --dry-run <path>",
                "npm run maintenance:plan -- --json",
            ],
        },
        "privacy": {
            "llm_context": "redacted",
            "paths_exposed": False,
            "filenames_exposed": False,
            "document_text_exposed": False,
        },
    }
    return detection


def format_pack_report(pack: Dict[str, Any]) -> str:
    """Format a compact pack report without private path or content data."""

    return (
        f"MindSage schema pack {pack['pack_id']}: "
        f"categories={len(pack['document_categories'])}, memory_kinds={len(pack['memory_kinds'])}"
    )


def format_classification_report(classification: Dict[str, Any]) -> str:
    """Format a compact classification report without path data."""

    return (
        "MindSage schema pack: "
        f"{classification['category_id']} -> {classification['recommended_memory_kind']} "
        f"(risk={classification['risk_level']}, confidence={classification['confidence']:.2f})"
    )


def format_detection_report(detection: Dict[str, Any]) -> str:
    """Format corpus-level detection without path, filename, or content data."""

    scanned = detection["scanned"]
    summary = detection["summary"]
    return (
        "MindSage schema pack detection: "
        f"files={scanned['file_count']}, categories={len(summary['category_counts'])}, "
        f"high_risk={summary['high_risk_file_count']}, candidates={len(detection['schema_candidates'])}"
    )


def main(argv: Optional[List[str]] = None, *, stdout: Any = sys.stdout) -> int:
    parser = argparse.ArgumentParser(description="Inspect MindSage's built-in agent schema pack")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of a compact report")
    parser.add_argument("--classify", default=None, help="Classify a path without echoing the path or filename")
    parser.add_argument("--detect", action="append", default=[], help="Detect safe schema candidates for a file or directory")
    parser.add_argument("--max-files", type=int, default=500, help="Maximum files to inspect by name")

    args = parser.parse_args(argv)
    if args.detect:
        output = detect_schema_candidates(args.detect, max_files=args.max_files)
        if args.json:
            stdout.write(json.dumps(output, indent=2, sort_keys=True) + "\n")
        else:
            stdout.write(format_detection_report(output) + "\n")
        return 0

    if args.classify:
        output = classify_path(args.classify)
        if args.json:
            stdout.write(json.dumps(output, indent=2, sort_keys=True) + "\n")
        else:
            stdout.write(format_classification_report(output) + "\n")
        return 0

    pack = build_schema_pack()
    if args.json:
        stdout.write(json.dumps(pack, indent=2, sort_keys=True) + "\n")
    else:
        stdout.write(format_pack_report(pack) + "\n")
    return 0


def _normalize_signal_text(filename: str) -> str:
    return "".join(character.lower() if character.isalnum() else " " for character in filename)


def _best_category(signal_text: str) -> tuple[Dict[str, Any], int]:
    best_category = DOCUMENT_CATEGORIES[-1]
    best_count = 0
    padded = f" {signal_text} "
    for category in DOCUMENT_CATEGORIES:
        signals = category.get("signals", [])
        match_count = sum(1 for signal in signals if _signal_matches(padded, signal))
        if match_count > best_count:
            best_category = category
            best_count = match_count
    return best_category, best_count


def _signal_matches(padded_text: str, signal: str) -> bool:
    normalized = _normalize_signal_text(signal).strip()
    if not normalized:
        return False
    return f" {normalized} " in padded_text


def _schema_candidate(
    *,
    category_id: str,
    file_count: int,
    matched_signal_count: int,
) -> Dict[str, Any]:
    category = _category_by_id(category_id)
    return {
        "id": f"schema_candidate:{category_id}",
        "category_id": category_id,
        "label": category["label"],
        "recommended_memory_kind": category["recommended_memory_kind"],
        "risk_level": category["risk_level"],
        "file_count": file_count,
        "matched_signal_count": matched_signal_count,
        "confidence": 0.8 if matched_signal_count else 0.35,
        "review_required": category["risk_level"] == "high",
        "path_examples_exposed": False,
        "content_examples_exposed": False,
    }


def _category_by_id(category_id: str) -> Dict[str, Any]:
    for category in DOCUMENT_CATEGORIES:
        if category["id"] == category_id:
            return category
    return DOCUMENT_CATEGORIES[-1]


def _is_hidden_path(path: Path) -> bool:
    return any(part.startswith(".") for part in path.parts)


def _input_fingerprint(paths: Sequence[str]) -> str:
    seed = "\n".join(sorted(str(path or "").strip() for path in paths if str(path or "").strip()))
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]


def _recommended_commands(category: Dict[str, Any]) -> List[str]:
    commands = ["npm run agent:import -- --dry-run <path>"]
    if category["recommended_memory_kind"] != "summary":
        commands.append(
            "npm --silent run agent:capture -- --dry-run "
            f"--mode memory --kind {category['recommended_memory_kind']}"
        )
    return commands


if __name__ == "__main__":
    raise SystemExit(main())
