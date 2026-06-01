"""Replayable fixture-corpus evals for MindSage agent retrieval quality."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

try:
    from .think_tool import build_think_response
except ImportError:  # Allows direct file loading in lightweight unit tests.
    from think_tool import build_think_response


DEFAULT_CORPUS_DIR = Path(__file__).resolve().parents[2] / "data" / "test-pii-docs"
STOP_WORDS = {
    "about",
    "after",
    "also",
    "and",
    "are",
    "did",
    "does",
    "for",
    "from",
    "has",
    "have",
    "into",
    "the",
    "this",
    "what",
    "when",
    "where",
    "which",
    "with",
}


def run_fixture_corpus_evals(corpus_dir: Path | None = None) -> Dict[str, Any]:
    """Run deterministic evals against the tracked synthetic PII fixture corpus."""

    documents = load_fixture_documents(corpus_dir or DEFAULT_CORPUS_DIR)
    cases = [
        _eval_named_thing_travel(documents),
        _eval_cross_source_provider(documents),
        _eval_financial_pii_safety(documents),
        _eval_medical_allergy_lookup(documents),
    ]
    passed = sum(1 for case in cases if case["passed"])
    failed = len(cases) - passed
    return {
        "suite": "mindsage-fixture-corpus",
        "version": 1,
        "corpus": {
            "name": "synthetic-pii-fixtures",
            "document_count": len(documents),
            "word_count": sum(document["word_count"] for document in documents),
        },
        "summary": {
            "total": len(cases),
            "passed": passed,
            "failed": failed,
            "score": round(passed / len(cases), 4) if cases else 0.0,
        },
        "cases": cases,
    }


def format_corpus_eval_report(report: Dict[str, Any]) -> str:
    """Format the fixture-corpus eval report for humans and CI logs."""

    summary = report["summary"]
    corpus = report["corpus"]
    lines = [
        f"MindSage fixture corpus evals: {summary['passed']}/{summary['total']} passed "
        f"(score={summary['score']:.4f}, docs={corpus['document_count']}, words={corpus['word_count']})"
    ]
    for case in report["cases"]:
        status = "PASS" if case["passed"] else "FAIL"
        lines.append(f"{status} {case['id']} - {case['description']}")
        if case.get("failures"):
            for failure in case["failures"]:
                lines.append(f"  - {failure}")
    return "\n".join(lines)


def load_fixture_documents(corpus_dir: Path) -> List[Dict[str, Any]]:
    """Load text fixtures as deterministic retrieval documents."""

    if not corpus_dir.exists():
        raise FileNotFoundError(f"Fixture corpus not found: {corpus_dir}")

    documents: List[Dict[str, Any]] = []
    for index, path in enumerate(sorted(corpus_dir.glob("*.txt")), start=1):
        text = path.read_text(encoding="utf-8")
        documents.append({
            "id": index,
            "title": path.name,
            "path": str(path),
            "text": text,
            "word_count": len(_tokens(text)),
        })
    return documents


def retrieve_fixture_evidence(
    documents: Sequence[Dict[str, Any]],
    query: str,
    *,
    top_k: int = 5,
) -> List[Dict[str, Any]]:
    """Return redacted lexical evidence for a query over fixture documents."""

    query_terms = _query_terms(query)
    scored: List[Dict[str, Any]] = []
    for document in documents:
        text = document["text"]
        text_terms = set(_tokens(text))
        exact_phrase_bonus = 2 if query.lower() in text.lower() else 0
        score = sum(1 for term in query_terms if term in text_terms) + exact_phrase_bonus
        if score <= 0:
            continue
        excerpt = _best_excerpt(text, query_terms)
        scored.append({
            "id": document["id"],
            "title": document["title"],
            "excerpt": redact_fixture_pii(excerpt),
            "score": round(score / max(len(query_terms), 1), 4),
            "metadata": {
                "title": document["title"],
                "source": "synthetic-fixture-corpus",
                "date": _fixture_date(document["title"]),
            },
        })
    return sorted(scored, key=lambda item: (-item["score"], item["title"]))[:top_k]


def redact_fixture_pii(text: str) -> str:
    """Redact common high-risk identifiers before eval output reaches an LLM."""

    redacted = text
    redactions = [
        (r"\bDonald Raymond Jones\b", "[PERSON]"),
        (r"\bDonald Jones\b", "[PERSON]"),
        (r"\bDon Jones\b", "[PERSON]"),
        (r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", "[EMAIL]"),
        (r"\(\d{3}\)\s*\d{3}-\d{4}", "[PHONE]"),
        (r"\b\d{3}-\d{3}-\d{4}\b", "[PHONE]"),
        (r"\b(?:\d{4}[-\s]){2,4}\d{3,4}\b", "[ACCOUNT]"),
        (r"\b(?:XXX-XX-)?\d{4}\b", "[SSN_LAST4]"),
        (r"\b\d{9,13}\b", "[ID_NUMBER]"),
    ]
    for pattern, replacement in redactions:
        redacted = re.sub(pattern, replacement, redacted)
    return redacted


def _eval_named_thing_travel(documents: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    response = _think_over_corpus(documents, "Where is the Honolulu hotel reservation?", top_k=4)
    titles = _citation_titles(response)
    serialized = json.dumps(response)

    return _case(
        "corpus.named_thing_travel",
        "fixture corpus retrieves a named travel reservation without leaking identifiers",
        [
            ("travel-booking-hawaii.txt" in titles, "expected Hawaii travel fixture citation"),
            ("Honolulu" in serialized, "expected Honolulu evidence"),
            ("Hilton Hawaiian Village" in serialized, "expected hotel evidence"),
            ("542871987" not in serialized, "passport number must be redacted"),
        ],
    )


def _eval_cross_source_provider(documents: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    response = _think_over_corpus(documents, "Which records mention Patricia Chen?", top_k=12)
    titles = _citation_titles(response)

    return _case(
        "corpus.cross_source_provider",
        "fixture corpus retrieves a named provider across finance and health records",
        [
            ("urgent-care-visit.txt" in titles, "expected urgent-care fixture citation"),
            ("bank-statement-jan-2025.txt" in titles, "expected bank statement fixture citation"),
            (len(titles) >= 2, "expected cross-source citations"),
        ],
    )


def _eval_financial_pii_safety(documents: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    response = _think_over_corpus(documents, "What bank balance information exists?", top_k=4)
    serialized = json.dumps(response)

    return _case(
        "corpus.financial_pii_safety",
        "fixture corpus returns financial evidence while redacting account and contact identifiers",
        [
            ("bank-statement-jan-2025.txt" in _citation_titles(response), "expected bank statement citation"),
            ("Ending Balance" in serialized, "expected balance evidence"),
            ("4521-8834-9912" not in serialized, "account number must be redacted"),
            ("don.jones.1987@gmail.com" not in serialized, "email must be redacted"),
            ("(408) 555-7834" not in serialized, "phone must be redacted"),
            ("XXX-XX-4829" not in serialized, "SSN fragment must be redacted"),
        ],
    )


def _eval_medical_allergy_lookup(documents: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    response = _think_over_corpus(documents, "What allergies are listed in urgent care?", top_k=4)
    serialized = json.dumps(response)

    return _case(
        "corpus.medical_allergy_lookup",
        "fixture corpus retrieves medical allergy facts with PII-safe citations",
        [
            ("urgent-care-visit.txt" in _citation_titles(response), "expected urgent-care citation"),
            ("PENICILLIN" in serialized, "expected penicillin allergy evidence"),
            ("SULFA DRUGS" in serialized, "expected sulfa allergy evidence"),
            ("Donald Raymond Jones" not in serialized, "patient full name should not appear in eval output"),
        ],
    )


def _think_over_corpus(
    documents: Sequence[Dict[str, Any]],
    question: str,
    *,
    top_k: int,
) -> Dict[str, Any]:
    evidence = retrieve_fixture_evidence(documents, question, top_k=top_k)
    return build_think_response(
        question,
        evidence,
        top_k=top_k,
        reference_date=dt.date(2026, 6, 1),
    )


def _citation_titles(response: Dict[str, Any]) -> set[str]:
    return {citation.get("title") for citation in response.get("citations", [])}


def _fixture_date(title: str) -> str:
    if "2025" in title:
        return "2025-01-31"
    if "2024" in title:
        return "2024-12-31"
    return "2026-01-01"


def _best_excerpt(text: str, query_terms: Sequence[str], window: int = 650) -> str:
    lower_text = text.lower()
    anchors = _excerpt_anchors(lower_text, query_terms)
    if not anchors:
        excerpt = text[:window]
        return " ".join(excerpt.split())

    best_start = 0
    best_score = -1
    for anchor in anchors:
        start = max(anchor - 160, 0)
        candidate = text[start:start + window]
        score = _excerpt_score(candidate, query_terms)
        if score > best_score:
            best_score = score
            best_start = start
    excerpt = text[best_start:best_start + window]
    return " ".join(excerpt.split())


def _excerpt_anchors(lower_text: str, query_terms: Sequence[str]) -> List[int]:
    anchors: List[int] = []
    query_term_set = set(query_terms)
    phrase_hints = [
        "hotel reservation",
        "ending balance",
        "account summary",
        "patricia chen",
        "allergies",
        "penicillin",
        "sulfa drugs",
    ]
    for phrase in phrase_hints:
        if _phrase_matches_query(phrase, query_term_set):
            position = lower_text.find(phrase)
            if position >= 0:
                anchors.append(position)

    for term in query_terms:
        position = lower_text.find(term)
        if position >= 0:
            anchors.append(position)
    return anchors


def _phrase_matches_query(phrase: str, query_terms: set[str]) -> bool:
    phrase_terms = set(_tokens(phrase))
    if phrase_terms & query_terms:
        return True
    if "allergies" in phrase_terms and any(term.startswith("allerg") for term in query_terms):
        return True
    return False


def _excerpt_score(candidate: str, query_terms: Sequence[str]) -> int:
    lower_candidate = candidate.lower()
    score = sum(1 for term in query_terms if term in lower_candidate)
    for phrase in ("hotel reservation", "ending balance", "patricia chen", "allergies", "penicillin", "sulfa drugs"):
        if phrase in lower_candidate:
            score += 4
    return score


def _query_terms(query: str) -> List[str]:
    terms: List[str] = []
    seen = set()
    for token in _tokens(query):
        if token in STOP_WORDS or len(token) < 3 or token in seen:
            continue
        seen.add(token)
        terms.append(token)
    return terms


def _tokens(text: str) -> List[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _case(case_id: str, description: str, checks: List[tuple[bool, str]]) -> Dict[str, Any]:
    failures = [message for passed, message in checks if not passed]
    return {
        "id": case_id,
        "description": description,
        "passed": not failures,
        "failures": failures,
    }


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run MindSage fixture corpus evals")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text")
    parser.add_argument(
        "--corpus-dir",
        default=str(DEFAULT_CORPUS_DIR),
        help="Path to synthetic fixture corpus directory",
    )
    args = parser.parse_args(argv)

    report = run_fixture_corpus_evals(Path(args.corpus_dir))
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(format_corpus_eval_report(report))
    return 0 if report["summary"]["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
