"""Security tests for PII fail-closed behavior (RT-03, RT-03b).

These tests verify that PII protection NEVER silently passes raw PII through
to external LLMs. When Presidio is unavailable or throws exceptions, the system
must redact all content rather than returning it unprotected.

These are security-critical tests. A failure here means PII can leak to external LLMs.
"""

import os
import time
import pytest
from unittest.mock import patch, MagicMock, PropertyMock

# Import pii_protection directly to avoid txtai dependency via __init__.py
import importlib.util
import sys

_spec = importlib.util.spec_from_file_location(
    'mcp_vector_store.pii_protection',
    os.path.join(os.path.dirname(__file__), '..', 'mcp_vector_store', 'pii_protection.py')
)
_mod = importlib.util.module_from_spec(_spec)
sys.modules['mcp_vector_store.pii_protection'] = _mod
_spec.loader.exec_module(_mod)

PIIProtector = _mod.PIIProtector
PIIProtectorMode = _mod.PIIProtectorMode
AnonymizationResult = _mod.AnonymizationResult
PRESIDIO_AVAILABLE = _mod.PRESIDIO_AVAILABLE
reset_pii_protector = _mod.reset_pii_protector


# ───────────────────────────────────────────────────────────────────
# Helper: text with known PII for testing
# ───────────────────────────────────────────────────────────────────

PII_TEXT = "John Smith emailed jane.doe@example.com from 555-123-4567."
PII_INDICATORS = ["John Smith", "jane.doe@example.com", "555-123-4567"]


def contains_raw_pii(text: str) -> bool:
    """Check if any known PII values appear in the text (case-insensitive)."""
    return any(indicator.lower() in text.lower() for indicator in PII_INDICATORS)


# ───────────────────────────────────────────────────────────────────
# RT-03b: anonymize() fails closed when Presidio is unavailable
# ───────────────────────────────────────────────────────────────────

class TestAnonymizeFailClosedPresidioUnavailable:
    """When Presidio cannot initialize, anonymize() must NOT return raw text."""

    @pytest.fixture(autouse=True)
    def setup(self):
        reset_pii_protector()
        # Clean env
        os.environ.pop("PII_FAIL_OPEN", None)
        yield
        os.environ.pop("PII_FAIL_OPEN", None)

    def test_redacts_when_presidio_unavailable(self):
        """CRITICAL: Raw PII must never reach an external LLM when Presidio is down."""
        protector = PIIProtector()
        # Force _ensure_initialized to return False
        protector._initialized = True
        protector._init_error = "simulated failure"

        result = protector.anonymize(PII_TEXT)

        assert not contains_raw_pii(result.anonymized_text), \
            f"SECURITY VIOLATION: Raw PII leaked when Presidio unavailable: {result.anonymized_text}"
        assert "PII_PROTECTION_UNAVAILABLE" in result.anonymized_text

    def test_fail_open_requires_explicit_env_var(self):
        """PII_FAIL_OPEN=true must be explicitly set to allow raw text through."""
        os.environ["PII_FAIL_OPEN"] = "true"

        protector = PIIProtector()
        protector._initialized = True
        protector._init_error = "simulated failure"

        result = protector.anonymize(PII_TEXT)

        # With explicit opt-in, raw text IS allowed (dev-only mode)
        assert result.anonymized_text == PII_TEXT

    def test_fail_open_false_still_redacts(self):
        """PII_FAIL_OPEN=false must still redact content."""
        os.environ["PII_FAIL_OPEN"] = "false"

        protector = PIIProtector()
        protector._initialized = True
        protector._init_error = "simulated failure"

        result = protector.anonymize(PII_TEXT)

        assert not contains_raw_pii(result.anonymized_text)
        assert "PII_PROTECTION_UNAVAILABLE" in result.anonymized_text

    def test_empty_fail_open_env_still_redacts(self):
        """Empty PII_FAIL_OPEN value must default to fail-closed."""
        os.environ["PII_FAIL_OPEN"] = ""

        protector = PIIProtector()
        protector._initialized = True
        protector._init_error = "simulated failure"

        result = protector.anonymize(PII_TEXT)

        assert not contains_raw_pii(result.anonymized_text)


# ───────────────────────────────────────────────────────────────────
# RT-03b: anonymize() fails closed when _analyzer.analyze() throws
# ───────────────────────────────────────────────────────────────────

class TestAnonymizeFailClosedAnalyzerException:
    """When Presidio's analyzer crashes, anonymize() must NOT return raw text."""

    @pytest.fixture(autouse=True)
    def setup(self):
        reset_pii_protector()
        os.environ.pop("PII_FAIL_OPEN", None)
        yield
        os.environ.pop("PII_FAIL_OPEN", None)

    @pytest.mark.skipif(not PRESIDIO_AVAILABLE, reason="Presidio needed to test analyzer exceptions")
    def test_redacts_when_analyzer_throws_runtime_error(self):
        """CRITICAL: Runtime error in analyzer must not leak PII."""
        protector = PIIProtector()
        # Force initialization so _analyzer exists
        protector._ensure_initialized()

        # Replace analyzer with one that throws
        protector._analyzer = MagicMock()
        protector._analyzer.analyze.side_effect = RuntimeError("Simulated spaCy crash")

        result = protector.anonymize(PII_TEXT)

        assert not contains_raw_pii(result.anonymized_text), \
            f"SECURITY VIOLATION: Raw PII leaked on analyzer exception: {result.anonymized_text}"
        assert "PII_PROTECTION_ERROR" in result.anonymized_text

    @pytest.mark.skipif(not PRESIDIO_AVAILABLE, reason="Presidio needed to test analyzer exceptions")
    def test_redacts_when_analyzer_throws_memory_error(self):
        """Memory errors (common on Jetson) must not leak PII."""
        protector = PIIProtector()
        protector._ensure_initialized()

        protector._analyzer = MagicMock()
        protector._analyzer.analyze.side_effect = MemoryError("CUDA out of memory")

        result = protector.anonymize(PII_TEXT)

        assert not contains_raw_pii(result.anonymized_text), \
            f"SECURITY VIOLATION: Raw PII leaked on MemoryError: {result.anonymized_text}"

    @pytest.mark.skipif(not PRESIDIO_AVAILABLE, reason="Presidio needed to test analyzer exceptions")
    def test_fail_open_env_allows_through_on_exception(self):
        """With PII_FAIL_OPEN=true, exceptions pass raw text through (dev mode)."""
        os.environ["PII_FAIL_OPEN"] = "true"

        protector = PIIProtector()
        protector._ensure_initialized()

        protector._analyzer = MagicMock()
        protector._analyzer.analyze.side_effect = RuntimeError("crash")

        result = protector.anonymize(PII_TEXT)

        # In dev mode, raw text passes through
        assert result.anonymized_text == PII_TEXT


# ───────────────────────────────────────────────────────────────────
# RT-03: anonymize_with_consent() fails closed
# ───────────────────────────────────────────────────────────────────

class TestAnonymizeWithConsentFailClosed:
    """anonymize_with_consent() must have identical fail-closed behavior."""

    @pytest.fixture(autouse=True)
    def setup(self):
        reset_pii_protector()
        os.environ.pop("PII_FAIL_OPEN", None)
        yield
        os.environ.pop("PII_FAIL_OPEN", None)

    def _make_consent_session(self):
        """Create a minimal consent session mock for testing."""
        consent = MagicMock()
        consent.get_consent.return_value = "anonymize"
        return consent

    def test_redacts_when_presidio_unavailable(self):
        """CRITICAL: anonymize_with_consent must fail-closed like anonymize()."""
        protector = PIIProtector()
        protector._initialized = True
        protector._init_error = "simulated failure"

        consent = self._make_consent_session()
        result = protector.anonymize_with_consent(PII_TEXT, consent)

        assert not contains_raw_pii(result.anonymized_text), \
            f"SECURITY VIOLATION: anonymize_with_consent leaked PII when Presidio unavailable: {result.anonymized_text}"
        assert "PII_PROTECTION_UNAVAILABLE" in result.anonymized_text

    @pytest.mark.skipif(not PRESIDIO_AVAILABLE, reason="Presidio needed")
    def test_redacts_when_analyzer_throws(self):
        """CRITICAL: analyzer exceptions in consent path must not leak PII."""
        protector = PIIProtector()
        protector._ensure_initialized()

        protector._analyzer = MagicMock()
        protector._analyzer.analyze.side_effect = RuntimeError("crash")

        consent = self._make_consent_session()
        result = protector.anonymize_with_consent(PII_TEXT, consent)

        assert not contains_raw_pii(result.anonymized_text), \
            f"SECURITY VIOLATION: anonymize_with_consent leaked PII on exception: {result.anonymized_text}"

    def test_fail_open_with_consent_allows_through(self):
        """PII_FAIL_OPEN=true overrides fail-closed in consent path too."""
        os.environ["PII_FAIL_OPEN"] = "true"

        protector = PIIProtector()
        protector._initialized = True
        protector._init_error = "simulated failure"

        consent = self._make_consent_session()
        result = protector.anonymize_with_consent(PII_TEXT, consent)

        assert result.anonymized_text == PII_TEXT


# ───────────────────────────────────────────────────────────────────
# RT-02: anonymize_search_results() covers all text fields
# ───────────────────────────────────────────────────────────────────

@pytest.mark.skipif(not PRESIDIO_AVAILABLE, reason="Presidio not installed")
class TestAnonymizeSearchResults:
    """Search results returned to external LLMs must have PII anonymized."""

    @pytest.fixture(autouse=True)
    def setup(self):
        reset_pii_protector()

    def test_anonymizes_text_field(self):
        """Text field in search results must be anonymized."""
        protector = PIIProtector(mode=PIIProtectorMode.TOKEN_ONLY)
        results = [
            {"id": 1, "text": "Meeting with John Smith at 10am.", "score": 0.95},
            {"id": 2, "text": "Email from jane.doe@example.com about project.", "score": 0.87},
        ]

        anon_results, session_id, total_tokens = protector.anonymize_search_results(
            results, text_fields=["text"]
        )

        assert len(anon_results) == 2
        assert "John Smith" not in anon_results[0]["text"]
        assert "jane.doe@example.com" not in anon_results[1]["text"]
        assert total_tokens >= 2
        assert session_id is not None

    def test_preserves_non_text_fields(self):
        """Non-text fields (id, score, metadata) must pass through unchanged."""
        protector = PIIProtector(mode=PIIProtectorMode.TOKEN_ONLY)
        results = [
            {"id": 42, "text": "Call John Smith", "score": 0.9, "metadata": {"source": "test"}},
        ]

        anon_results, _, _ = protector.anonymize_search_results(results, text_fields=["text"])

        assert anon_results[0]["id"] == 42
        assert anon_results[0]["score"] == 0.9
        assert anon_results[0]["metadata"] == {"source": "test"}

    def test_only_specified_fields_anonymized(self):
        """Only fields in text_fields list should be anonymized."""
        protector = PIIProtector(mode=PIIProtectorMode.TOKEN_ONLY)
        results = [
            {"id": 1, "text": "John Smith sent an email", "excerpt": "John Smith sent an email"},
        ]

        anon_results, _, _ = protector.anonymize_search_results(
            results, text_fields=["excerpt"]
        )

        # Text field NOT in text_fields -> should still contain raw PII
        assert "John Smith" in anon_results[0]["text"]
        # Excerpt IS in text_fields -> should be anonymized
        assert "John Smith" not in anon_results[0]["excerpt"]

    def test_empty_results_handled(self):
        """Empty result list should work without error."""
        protector = PIIProtector()
        anon_results, session_id, total = protector.anonymize_search_results([])

        assert anon_results == []
        assert total == 0

    def test_none_text_fields_skipped(self):
        """Results with None text values should be skipped without error."""
        protector = PIIProtector(mode=PIIProtectorMode.TOKEN_ONLY)
        results = [
            {"id": 1, "text": None, "score": 0.5},
            {"id": 2, "text": "John Smith is here", "score": 0.8},
        ]

        anon_results, _, _ = protector.anonymize_search_results(results, text_fields=["text"])

        assert anon_results[0]["text"] is None
        assert "John Smith" not in anon_results[1]["text"]

    def test_consistent_tokens_within_batch(self):
        """Same PII across multiple results in same batch must get same token."""
        protector = PIIProtector(mode=PIIProtectorMode.TOKEN_ONLY, entities=["EMAIL_ADDRESS"])
        results = [
            {"id": 1, "text": "Contact alice@example.com for info."},
            {"id": 2, "text": "alice@example.com sent the report."},
        ]

        anon_results, session_id, _ = protector.anonymize_search_results(
            results, text_fields=["text"]
        )

        import re
        tokens_1 = re.findall(r'<PII:EMAIL_ADDRESS:([a-zA-Z0-9_-]+)>', anon_results[0]["text"])
        tokens_2 = re.findall(r'<PII:EMAIL_ADDRESS:([a-zA-Z0-9_-]+)>', anon_results[1]["text"])

        assert len(tokens_1) >= 1
        assert len(tokens_2) >= 1
        assert tokens_1[0] == tokens_2[0], \
            "Same PII across batch results must use the same token for consistency"

    def test_deanonymization_after_batch(self):
        """Tokens from batch anonymization must be de-anonymizable."""
        protector = PIIProtector(mode=PIIProtectorMode.TOKEN_ONLY, entities=["EMAIL_ADDRESS"])
        results = [
            {"id": 1, "text": "Contact alice@example.com"},
        ]

        anon_results, session_id, _ = protector.anonymize_search_results(
            results, text_fields=["text"]
        )

        deanon = protector.deanonymize(anon_results[0]["text"], session_id)
        assert "alice@example.com" in deanon.deanonymized_text

    def test_truncated_text_still_anonymized(self):
        """Truncated text (e.g., 200 or 500 chars) must still be scanned for PII."""
        protector = PIIProtector(mode=PIIProtectorMode.TOKEN_ONLY)
        long_text = "John Smith " * 100  # 1100 chars
        truncated = long_text[:200] + "..."

        results = [{"id": 1, "text": truncated}]
        anon_results, _, total = protector.anonymize_search_results(results, text_fields=["text"])

        assert "John Smith" not in anon_results[0]["text"], \
            "PII in truncated text must still be anonymized"


# ───────────────────────────────────────────────────────────────────
# Session isolation and token entropy
# ───────────────────────────────────────────────────────────────────

@pytest.mark.skipif(not PRESIDIO_AVAILABLE, reason="Presidio not installed")
class TestSessionSecurity:
    """Token and session security properties."""

    @pytest.fixture(autouse=True)
    def setup(self):
        reset_pii_protector()

    def test_session_ids_are_unique(self):
        """Each new session must get a cryptographically unique ID."""
        protector = PIIProtector()
        sessions = set()
        for _ in range(50):
            result = protector.anonymize("Test text with John Smith")
            sessions.add(result.session_id)

        assert len(sessions) == 50, "Session IDs must be unique across calls"

    def test_token_ids_are_unique_across_sessions(self):
        """Different PII values must produce different token IDs."""
        protector = PIIProtector(mode=PIIProtectorMode.TOKEN_ONLY, entities=["PERSON"])
        import re

        token_ids = set()
        for name in ["Alice Johnson", "Bob Williams", "Charlie Brown", "Diana Prince"]:
            result = protector.anonymize(f"Meeting with {name}")
            tokens = re.findall(r'<PII:PERSON:([a-zA-Z0-9_-]+)>', result.anonymized_text)
            for t in tokens:
                token_ids.add(t)

        assert len(token_ids) >= 4, "Different PII values must produce unique tokens"

    def test_cross_session_deanonymization_fails(self):
        """Tokens from one session must NOT be resolvable in another session."""
        protector = PIIProtector(mode=PIIProtectorMode.TOKEN_ONLY, entities=["EMAIL_ADDRESS"])

        result1 = protector.anonymize("Contact alice@example.com")
        result2 = protector.anonymize("Contact bob@example.com")

        # Try to deanonymize result1's text using result2's session
        cross_deanon = protector.deanonymize(result1.anonymized_text, result2.session_id)

        assert "alice@example.com" not in cross_deanon.deanonymized_text, \
            "SECURITY: Cross-session de-anonymization must not reveal PII"

    def test_session_expiry_prevents_deanonymization(self):
        """Expired sessions must not allow de-anonymization."""
        protector = PIIProtector(
            mode=PIIProtectorMode.TOKEN_ONLY,
            entities=["EMAIL_ADDRESS"],
            session_ttl_seconds=0  # Expire immediately
        )

        result = protector.anonymize("Contact alice@example.com")
        time.sleep(0.1)  # Ensure expiration

        deanon = protector.deanonymize(result.anonymized_text, result.session_id)

        assert "alice@example.com" not in deanon.deanonymized_text, \
            "Expired session must not reveal PII"


# ───────────────────────────────────────────────────────────────────
# Fail-closed with search results (integration-level)
# ───────────────────────────────────────────────────────────────────

class TestSearchResultsFailClosed:
    """anonymize_search_results must fail-closed when Presidio is unavailable."""

    @pytest.fixture(autouse=True)
    def setup(self):
        reset_pii_protector()
        os.environ.pop("PII_FAIL_OPEN", None)
        yield
        os.environ.pop("PII_FAIL_OPEN", None)

    def test_search_results_redacted_when_presidio_down(self):
        """CRITICAL: Batch anonymization must redact all text when Presidio is down."""
        protector = PIIProtector()
        protector._initialized = True
        protector._init_error = "simulated failure"

        results = [
            {"id": 1, "text": "John Smith's credit card is 4111-1111-1111-1111"},
            {"id": 2, "text": "SSN: 123-45-6789 for Jane Doe"},
        ]

        anon_results, session_id, total = protector.anonymize_search_results(
            results, text_fields=["text"]
        )

        for r in anon_results:
            assert "John Smith" not in r["text"], \
                f"SECURITY VIOLATION: PII leaked in search results when Presidio unavailable"
            assert "4111-1111-1111-1111" not in r["text"]
            assert "123-45-6789" not in r["text"]
            assert "Jane Doe" not in r["text"]
            assert "PII_PROTECTION_UNAVAILABLE" in r["text"]

    @pytest.mark.skipif(not PRESIDIO_AVAILABLE, reason="Presidio needed")
    def test_search_results_redacted_when_analyzer_crashes(self):
        """Batch anonymization must redact text when analyzer throws per-document."""
        protector = PIIProtector()
        protector._ensure_initialized()

        protector._analyzer = MagicMock()
        protector._analyzer.analyze.side_effect = RuntimeError("spaCy OOM")

        results = [
            {"id": 1, "text": "John Smith (john@example.com)"},
        ]

        anon_results, _, _ = protector.anonymize_search_results(results, text_fields=["text"])

        assert "John Smith" not in anon_results[0]["text"], \
            "SECURITY VIOLATION: PII leaked when analyzer crashed during batch"
        assert "john@example.com" not in anon_results[0]["text"]
