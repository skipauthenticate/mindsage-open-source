"""Tests for PII protection module.

These tests verify the PII detection, anonymization, and de-anonymization
functionality. Tests run without Presidio installed will be skipped.
"""

import pytest
import time
from unittest.mock import MagicMock, patch

# Import the module under test
from mcp_vector_store.pii_protection import (
    PIIProtector,
    PIIProtectorMode,
    PIIToken,
    PIIType,
    TokenSession,
    AnonymizationResult,
    DeanonymizationResult,
    get_pii_protector,
    reset_pii_protector,
    get_configured_entities,
    ALL_PII_ENTITIES,
    PII_ENTITY_PRESETS,
    PRESIDIO_AVAILABLE,
)


# Skip all tests if Presidio is not installed
pytestmark = pytest.mark.skipif(
    not PRESIDIO_AVAILABLE,
    reason="Presidio not installed"
)


class TestTokenSession:
    """Test TokenSession class."""

    def test_create_session(self):
        """Test session creation with default TTL."""
        session = TokenSession("test-session", ttl_seconds=3600)
        assert session.session_id == "test-session"
        assert session.token_count == 0
        assert not session.is_expired()

    def test_add_and_get_token(self):
        """Test adding and retrieving tokens."""
        session = TokenSession("test-session")
        token = PIIToken(
            token_id="abc123",
            pii_type="PERSON",
            original_value="John Smith",
            created_at=time.time()
        )
        session.add_token(token)

        assert session.token_count == 1
        retrieved = session.get_token("abc123")
        assert retrieved is not None
        assert retrieved.original_value == "John Smith"
        assert retrieved.pii_type == "PERSON"

    def test_get_nonexistent_token(self):
        """Test getting a token that doesn't exist."""
        session = TokenSession("test-session")
        assert session.get_token("nonexistent") is None

    def test_session_expiration(self):
        """Test session expiration with short TTL."""
        session = TokenSession("test-session", ttl_seconds=0)
        # With TTL=0, session should expire immediately
        assert session.is_expired()

    def test_get_token_by_value(self):
        """Test retrieving tokens by PII type and value."""
        from datetime import datetime
        session = TokenSession("test-session")
        token = PIIToken(
            token_id="abc123",
            pii_type="PERSON",
            original_value="John Smith",
            created_at=datetime.now()
        )
        session.add_token(token)

        # Should find the token by value
        retrieved = session.get_token_by_value("PERSON", "John Smith")
        assert retrieved is not None
        assert retrieved.token_id == "abc123"

        # Should not find with different type
        retrieved = session.get_token_by_value("EMAIL_ADDRESS", "John Smith")
        assert retrieved is None

        # Should not find non-existent value
        retrieved = session.get_token_by_value("PERSON", "Jane Doe")
        assert retrieved is None

    def test_get_token_by_value_case_insensitive(self):
        """Test that value lookup is case-insensitive."""
        from datetime import datetime
        session = TokenSession("test-session")
        token = PIIToken(
            token_id="abc123",
            pii_type="EMAIL_ADDRESS",
            original_value="John.Smith@Example.COM",
            created_at=datetime.now()
        )
        session.add_token(token)

        # Should find with different casing
        retrieved = session.get_token_by_value("EMAIL_ADDRESS", "john.smith@example.com")
        assert retrieved is not None
        assert retrieved.token_id == "abc123"

    def test_get_token_by_value_whitespace_normalized(self):
        """Test that value lookup normalizes whitespace."""
        from datetime import datetime
        session = TokenSession("test-session")
        token = PIIToken(
            token_id="abc123",
            pii_type="PERSON",
            original_value="John  Smith",  # double space
            created_at=datetime.now()
        )
        session.add_token(token)

        # Should find with single space
        retrieved = session.get_token_by_value("PERSON", "John Smith")
        assert retrieved is not None
        assert retrieved.token_id == "abc123"


class TestPIIToken:
    """Test PIIToken dataclass."""

    def test_token_string_format(self):
        """Test that token_string produces correct format."""
        from datetime import datetime
        token = PIIToken(
            token_id="xYz123",
            pii_type="EMAIL_ADDRESS",
            original_value="test@example.com",
            created_at=datetime.now()
        )
        assert token.token_string == "<PII:EMAIL_ADDRESS:xYz123>"


class TestPIIProtector:
    """Test PIIProtector class."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Reset global protector before each test."""
        reset_pii_protector()

    def test_protector_initialization(self):
        """Test protector initializes correctly."""
        protector = PIIProtector(verbose=True)
        assert protector.is_available
        stats = protector.get_stats()
        assert stats["presidio_available"] is True

    def test_anonymize_person_name(self):
        """Test detection and anonymization of person names."""
        protector = PIIProtector(mode=PIIProtectorMode.TOKEN_ONLY)
        text = "Meeting with John Smith scheduled for tomorrow."

        result = protector.anonymize(text)

        assert "John Smith" not in result.anonymized_text
        assert "<PII:PERSON:" in result.anonymized_text
        assert result.token_count >= 1
        assert "PERSON" in result.pii_types_found

    def test_anonymize_email(self):
        """Test detection and anonymization of email addresses."""
        # Use specific entities to avoid overlap between EMAIL_ADDRESS and URL
        protector = PIIProtector(mode=PIIProtectorMode.TOKEN_ONLY, entities=["EMAIL_ADDRESS"])
        text = "Contact john.smith@example.com for details."

        result = protector.anonymize(text)

        assert "john.smith@example.com" not in result.anonymized_text
        assert "<PII:EMAIL_ADDRESS:" in result.anonymized_text
        assert "EMAIL_ADDRESS" in result.pii_types_found

    def test_anonymize_phone_number(self):
        """Test detection of phone numbers."""
        protector = PIIProtector(mode=PIIProtectorMode.TOKEN_ONLY)
        text = "Call me at 555-123-4567 for more info."

        result = protector.anonymize(text)

        assert "555-123-4567" not in result.anonymized_text
        assert "<PII:PHONE_NUMBER:" in result.anonymized_text

    def test_anonymize_multiple_pii(self):
        """Test anonymization of multiple PII types in one text."""
        protector = PIIProtector()
        text = "John Smith (john@example.com) called from 555-123-4567."

        result = protector.anonymize(text)

        assert "John Smith" not in result.anonymized_text
        assert "john@example.com" not in result.anonymized_text
        assert "555-123-4567" not in result.anonymized_text
        assert result.token_count >= 3

    def test_deanonymize_restores_original(self):
        """Test that de-anonymization restores original text."""
        # Use specific entities to avoid overlap between EMAIL_ADDRESS and URL
        protector = PIIProtector(mode=PIIProtectorMode.TOKEN_ONLY, entities=["EMAIL_ADDRESS"])
        original = "Email john.doe@example.com about the project."

        anon_result = protector.anonymize(original)
        deanon_result = protector.deanonymize(
            anon_result.anonymized_text,
            anon_result.session_id
        )

        assert deanon_result.deanonymized_text == original
        assert deanon_result.tokens_replaced == anon_result.token_count

    def test_session_isolation(self):
        """Test that sessions are isolated."""
        protector = PIIProtector()

        result1 = protector.anonymize("Contact alice@example.com")
        result2 = protector.anonymize("Contact bob@example.com")

        # Different sessions
        assert result1.session_id != result2.session_id

        # Cannot de-anonymize with wrong session
        wrong_session = protector.deanonymize(
            result1.anonymized_text,
            result2.session_id
        )
        # Tokens should not be found in wrong session
        assert wrong_session.tokens_replaced == 0

    def test_same_session_multiple_anonymizations(self):
        """Test using same session for multiple anonymizations."""
        protector = PIIProtector()

        result1 = protector.anonymize("Contact alice@example.com")
        session_id = result1.session_id

        # Use same session for second anonymization
        result2 = protector.anonymize("Call bob@example.com", session_id=session_id)

        assert result2.session_id == session_id

        # Can de-anonymize both with same session
        combined_text = result1.anonymized_text + " and " + result2.anonymized_text
        deanon = protector.deanonymize(combined_text, session_id)

        assert "alice@example.com" in deanon.deanonymized_text
        assert "bob@example.com" in deanon.deanonymized_text

    def test_anonymize_search_results(self):
        """Test anonymization of search result objects."""
        protector = PIIProtector()
        results = [
            {"id": 1, "text": "Meeting with John Smith", "score": 0.9},
            {"id": 2, "text": "Call jane.doe@company.com", "score": 0.8}
        ]

        anon_results, session_id, total_tokens = protector.anonymize_search_results(results)

        assert len(anon_results) == 2
        assert "John Smith" not in anon_results[0]["text"]
        assert "jane.doe@company.com" not in anon_results[1]["text"]
        assert session_id is not None
        assert total_tokens >= 2

    def test_anonymize_search_results_with_excerpts(self):
        """Test anonymization of search results with excerpt field."""
        protector = PIIProtector()
        results = [
            {
                "id": 1,
                "text": "Full document with John Smith",
                "excerpt": "Relevant part about John Smith",
                "score": 0.9
            }
        ]

        anon_results, session_id, _ = protector.anonymize_search_results(
            results,
            text_fields=["excerpt"]  # Only anonymize excerpts
        )

        # Text field should NOT be anonymized (not in text_fields)
        assert "John Smith" in anon_results[0]["text"]
        # Excerpt should be anonymized
        assert "John Smith" not in anon_results[0]["excerpt"]

    def test_no_pii_in_text(self):
        """Test handling of text without PII."""
        protector = PIIProtector(mode=PIIProtectorMode.TOKEN_ONLY)
        # Use text with no PII entities (avoid "today" which is detected as DATE_TIME)
        text = "The sky is blue and grass is green."

        result = protector.anonymize(text)

        assert result.anonymized_text == text
        assert result.token_count == 0
        assert len(result.pii_types_found) == 0

    def test_duplicate_pii_same_token(self):
        """Test that duplicate PII values get the same token ID."""
        protector = PIIProtector(mode=PIIProtectorMode.TOKEN_ONLY)
        text = "John Smith met with John Smith to discuss the project."

        result = protector.anonymize(text)

        # Should have 2 replacements
        assert result.token_count == 2

        # Both occurrences should use the same token
        import re
        tokens = re.findall(r'<PII:PERSON:([a-zA-Z0-9_-]+)>', result.anonymized_text)
        assert len(tokens) == 2
        assert tokens[0] == tokens[1], "Duplicate PII should use same token ID"

        # De-anonymization should work correctly
        deanon = protector.deanonymize(result.anonymized_text, result.session_id)
        assert deanon.deanonymized_text == text
        assert deanon.tokens_replaced == 2

    def test_duplicate_pii_across_calls_same_session(self):
        """Test that duplicate PII across multiple calls in same session gets same token."""
        # Use specific entities to avoid overlap between EMAIL_ADDRESS and URL
        protector = PIIProtector(mode=PIIProtectorMode.TOKEN_ONLY, entities=["EMAIL_ADDRESS"])

        # First call
        result1 = protector.anonymize("Contact john@example.com for help.")
        session_id = result1.session_id

        # Second call with same email in same session
        result2 = protector.anonymize("Email john@example.com again.", session_id=session_id)

        # Extract token IDs
        import re
        token1 = re.search(r'<PII:EMAIL_ADDRESS:([a-zA-Z0-9_-]+)>', result1.anonymized_text)
        token2 = re.search(r'<PII:EMAIL_ADDRESS:([a-zA-Z0-9_-]+)>', result2.anonymized_text)

        assert token1 is not None
        assert token2 is not None
        assert token1.group(1) == token2.group(1), "Same PII across calls should use same token"

        # Session should only have 1 unique token
        info = protector.get_session_info(session_id)
        assert info["token_count"] == 1

    def test_different_pii_different_tokens(self):
        """Test that different PII values get different token IDs."""
        protector = PIIProtector(mode=PIIProtectorMode.TOKEN_ONLY)
        text = "John Smith emailed Jane Doe about the meeting."

        result = protector.anonymize(text)

        # Extract all PERSON tokens
        import re
        tokens = re.findall(r'<PII:PERSON:([a-zA-Z0-9_-]+)>', result.anonymized_text)

        # Should have 2 different tokens for 2 different people
        assert len(tokens) == 2
        assert tokens[0] != tokens[1], "Different PII should use different token IDs"

    def test_duplicate_pii_case_insensitive(self):
        """Test that PII deduplication is case-insensitive."""
        # Use specific entities to avoid overlap between EMAIL_ADDRESS and URL
        protector = PIIProtector(mode=PIIProtectorMode.TOKEN_ONLY, entities=["EMAIL_ADDRESS"])

        result1 = protector.anonymize("Contact JOHN@EXAMPLE.COM for help.")
        session_id = result1.session_id

        # Same email with different case
        result2 = protector.anonymize("Email john@example.com again.", session_id=session_id)

        # Extract token IDs
        import re
        token1 = re.search(r'<PII:EMAIL_ADDRESS:([a-zA-Z0-9_-]+)>', result1.anonymized_text)
        token2 = re.search(r'<PII:EMAIL_ADDRESS:([a-zA-Z0-9_-]+)>', result2.anonymized_text)

        assert token1 is not None
        assert token2 is not None
        assert token1.group(1) == token2.group(1), "Case-different PII should use same token"

    def test_authorization_required(self):
        """Test that authorization is enforced when required."""
        protector = PIIProtector()

        # Anonymize some text
        result = protector.anonymize("Contact john@example.com")

        # Try to de-anonymize with require_auth but no token
        deanon = protector.deanonymize(
            result.anonymized_text,
            result.session_id,
            require_auth=True
        )

        assert "UNAUTHORIZED" in deanon.tokens_not_found
        assert deanon.tokens_replaced == 0

    def test_authorization_with_valid_token(self):
        """Test de-anonymization with valid auth token."""
        # Use TOKEN_ONLY mode for predictable token-based anonymization
        protector = PIIProtector(mode=PIIProtectorMode.TOKEN_ONLY, entities=["EMAIL_ADDRESS"])

        # Generate auth token
        auth_token = protector.generate_auth_token()

        # Anonymize some text
        original = "Contact john@example.com"
        result = protector.anonymize(original)

        # De-anonymize with valid auth token
        deanon = protector.deanonymize(
            result.anonymized_text,
            result.session_id,
            auth_token=auth_token,
            require_auth=True
        )

        assert "UNAUTHORIZED" not in deanon.tokens_not_found
        assert deanon.deanonymized_text == original

    def test_authorization_with_invalid_token(self):
        """Test de-anonymization with invalid auth token."""
        protector = PIIProtector()

        result = protector.anonymize("Contact john@example.com")

        # Try with invalid token
        deanon = protector.deanonymize(
            result.anonymized_text,
            result.session_id,
            auth_token="invalid-token",
            require_auth=True
        )

        assert "UNAUTHORIZED" in deanon.tokens_not_found

    def test_session_not_found(self):
        """Test de-anonymization with non-existent session."""
        protector = PIIProtector()

        deanon = protector.deanonymize(
            "Some text with <PII:PERSON:abc123>",
            "nonexistent-session-id"
        )

        assert "SESSION_NOT_FOUND" in deanon.tokens_not_found
        assert deanon.tokens_replaced == 0

    def test_clear_session(self):
        """Test clearing a session."""
        protector = PIIProtector()

        result = protector.anonymize("Contact john@example.com")
        session_id = result.session_id

        # Verify session exists
        info = protector.get_session_info(session_id)
        assert info is not None

        # Clear session
        cleared = protector.clear_session(session_id)
        assert cleared is True

        # Verify session is gone
        info = protector.get_session_info(session_id)
        assert info is None

    def test_get_stats(self):
        """Test getting protector statistics."""
        protector = PIIProtector()

        # Anonymize some text to create sessions
        protector.anonymize("Contact john@example.com")
        protector.anonymize("Contact jane@example.com")

        stats = protector.get_stats()

        assert stats["presidio_available"] is True
        assert stats["total_sessions"] >= 2
        assert stats["total_tokens"] >= 2

    def test_max_sessions_eviction(self):
        """Test LRU eviction when max sessions reached."""
        protector = PIIProtector(max_sessions=3)

        # Create 4 sessions (exceeds max of 3)
        sessions = []
        for i in range(4):
            result = protector.anonymize(f"Contact user{i}@example.com")
            sessions.append(result.session_id)

        stats = protector.get_stats()
        # Should have max 3 sessions
        assert stats["total_sessions"] <= 3

        # First session should have been evicted
        info = protector.get_session_info(sessions[0])
        assert info is None


class TestGlobalProtector:
    """Test global singleton protector functions."""

    def setup_method(self):
        """Reset before each test."""
        reset_pii_protector()

    def test_get_pii_protector_singleton(self):
        """Test that get_pii_protector returns same instance."""
        protector1 = get_pii_protector()
        protector2 = get_pii_protector()
        assert protector1 is protector2

    def test_reset_pii_protector(self):
        """Test that reset creates new instance."""
        protector1 = get_pii_protector()
        reset_pii_protector()
        protector2 = get_pii_protector()
        assert protector1 is not protector2


class TestWithoutPresidio:
    """Test graceful degradation when Presidio is not installed."""

    def test_graceful_degradation(self):
        """Test that anonymization works without Presidio (returns original text)."""
        # Create a protector that simulates Presidio being unavailable
        protector = PIIProtector()

        # Mock the _ensure_initialized to return False
        protector._ensure_initialized = lambda: False
        protector._init_error = "Presidio not installed"

        text = "Contact john@example.com"
        result = protector.anonymize(text)

        # Should return original text unchanged
        assert result.anonymized_text == text
        assert result.token_count == 0


class TestTokenPattern:
    """Test the token pattern regex."""

    def test_token_pattern_matches(self):
        """Test that token pattern correctly identifies tokens."""
        text = "Hello <PII:PERSON:abc123> called from <PII:PHONE_NUMBER:xyz789>"
        matches = list(PIIProtector.TOKEN_PATTERN.finditer(text))

        assert len(matches) == 2
        assert matches[0].group(1) == "PERSON"
        assert matches[0].group(2) == "abc123"
        assert matches[1].group(1) == "PHONE_NUMBER"
        assert matches[1].group(2) == "xyz789"

    def test_token_pattern_no_match(self):
        """Test that invalid formats don't match."""
        invalid_texts = [
            "<PII:person:abc123>",  # lowercase type
            "<PII:PERSON>",  # missing token ID
            "PII:PERSON:abc123",  # missing brackets
            "<PII:PERSON:abc 123>",  # space in token
        ]

        for text in invalid_texts:
            matches = list(PIIProtector.TOKEN_PATTERN.finditer(text))
            assert len(matches) == 0, f"Should not match: {text}"


class TestPIIEntityConfiguration:
    """Test PII entity type configuration."""

    def setup_method(self):
        """Reset environment and global protector before each test."""
        reset_pii_protector()
        # Clear any PII_ENTITIES env var
        if "PII_ENTITIES" in os.environ:
            del os.environ["PII_ENTITIES"]

    def teardown_method(self):
        """Clean up after each test."""
        if "PII_ENTITIES" in os.environ:
            del os.environ["PII_ENTITIES"]

    def test_all_pii_entities_defined(self):
        """Test that ALL_PII_ENTITIES contains all PIIType enum values."""
        enum_values = [e.value for e in PIIType]
        assert set(ALL_PII_ENTITIES) == set(enum_values)

    def test_presets_contain_valid_entities(self):
        """Test that all preset configurations contain valid entity names."""
        for preset_name, entities in PII_ENTITY_PRESETS.items():
            for entity in entities:
                assert entity in ALL_PII_ENTITIES, (
                    f"Preset '{preset_name}' contains invalid entity: {entity}"
                )

    def test_default_entities_is_all_types(self):
        """Test that default (no env var) returns all entity types."""
        entities = get_configured_entities()
        assert set(entities) == set(ALL_PII_ENTITIES)

    def test_env_var_preset_minimal(self):
        """Test PII_ENTITIES=minimal preset."""
        os.environ["PII_ENTITIES"] = "minimal"
        entities = get_configured_entities()

        assert "PERSON" in entities
        assert "EMAIL_ADDRESS" in entities
        assert "PHONE_NUMBER" in entities
        assert len(entities) == 3

    def test_env_var_preset_default(self):
        """Test PII_ENTITIES=default preset."""
        os.environ["PII_ENTITIES"] = "default"
        entities = get_configured_entities()

        assert "PERSON" in entities
        assert "EMAIL_ADDRESS" in entities
        assert "CREDIT_CARD" in entities
        assert "US_SSN" in entities
        # Should not include all types
        assert len(entities) < len(ALL_PII_ENTITIES)

    def test_env_var_preset_strict(self):
        """Test PII_ENTITIES=strict preset (all types)."""
        os.environ["PII_ENTITIES"] = "strict"
        entities = get_configured_entities()

        assert set(entities) == set(ALL_PII_ENTITIES)

    def test_env_var_preset_case_insensitive(self):
        """Test that preset names are case-insensitive."""
        os.environ["PII_ENTITIES"] = "MINIMAL"
        entities1 = get_configured_entities()

        os.environ["PII_ENTITIES"] = "Minimal"
        entities2 = get_configured_entities()

        assert entities1 == entities2

    def test_env_var_custom_list(self):
        """Test custom comma-separated entity list."""
        os.environ["PII_ENTITIES"] = "PERSON,EMAIL_ADDRESS,IBAN_CODE"
        entities = get_configured_entities()

        assert entities == ["PERSON", "EMAIL_ADDRESS", "IBAN_CODE"]

    def test_env_var_custom_list_with_whitespace(self):
        """Test custom list handles whitespace."""
        os.environ["PII_ENTITIES"] = " PERSON , EMAIL_ADDRESS , PHONE_NUMBER "
        entities = get_configured_entities()

        assert entities == ["PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER"]

    def test_env_var_custom_list_case_normalized(self):
        """Test custom list normalizes case to uppercase."""
        os.environ["PII_ENTITIES"] = "person,Email_Address,phone_NUMBER"
        entities = get_configured_entities()

        assert entities == ["PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER"]

    def test_protector_uses_configured_entities(self):
        """Test that PIIProtector uses entities from configuration."""
        os.environ["PII_ENTITIES"] = "EMAIL_ADDRESS"
        protector = PIIProtector()

        assert protector.entities == ["EMAIL_ADDRESS"]

    def test_protector_explicit_entities_override_env(self):
        """Test that explicit entities parameter overrides env var."""
        os.environ["PII_ENTITIES"] = "PERSON"
        protector = PIIProtector(entities=["EMAIL_ADDRESS", "PHONE_NUMBER"])

        assert protector.entities == ["EMAIL_ADDRESS", "PHONE_NUMBER"]

    def test_protector_detects_only_configured_entities(self):
        """Test that protector only detects configured entity types."""
        # Configure to only detect emails (with TOKEN_ONLY mode for predictable token format)
        protector = PIIProtector(entities=["EMAIL_ADDRESS"], mode=PIIProtectorMode.TOKEN_ONLY)

        # Text with both person name and email
        text = "John Smith can be reached at john@example.com"
        result = protector.anonymize(text)

        # Email should be anonymized
        assert "john@example.com" not in result.anonymized_text
        assert "<PII:EMAIL_ADDRESS:" in result.anonymized_text

        # Person name should NOT be anonymized (not in configured entities)
        assert "John Smith" in result.anonymized_text
        assert "<PII:PERSON:" not in result.anonymized_text


# Import os for the configuration tests
import os


class TestSlidingTTL:
    """Test sliding TTL / activity-based session expiration."""

    def setup_method(self):
        """Reset before each test."""
        reset_pii_protector()

    def test_session_touch_extends_expiration(self):
        """Test that touch() extends session expiration."""
        session = TokenSession("test-session", ttl_seconds=3600)
        original_expires = session.expires_at

        # Wait a tiny bit and touch
        time.sleep(0.01)
        session.touch()

        # Expiration should be extended
        assert session.expires_at > original_expires
        assert session.last_accessed > session.created_at

    def test_session_ttl_remaining(self):
        """Test ttl_remaining_seconds property."""
        session = TokenSession("test-session", ttl_seconds=10)

        # Should have close to 10 seconds remaining
        assert 8 <= session.ttl_remaining_seconds <= 10

        # After expiration, should be 0
        session_expired = TokenSession("test-expired", ttl_seconds=0)
        assert session_expired.ttl_remaining_seconds == 0

    def test_add_token_refreshes_ttl(self):
        """Test that adding a token refreshes the session TTL."""
        from datetime import datetime
        session = TokenSession("test-session", ttl_seconds=3600)
        original_expires = session.expires_at

        # Wait and add token
        time.sleep(0.01)
        token = PIIToken(
            token_id="abc123",
            pii_type="PERSON",
            original_value="John Smith",
            created_at=datetime.now()
        )
        session.add_token(token)

        # TTL should be refreshed
        assert session.expires_at > original_expires

    def test_deanonymize_refreshes_session(self):
        """Test that deanonymize() refreshes the session TTL."""
        protector = PIIProtector(session_ttl_seconds=3600)

        # Anonymize some text
        result = protector.anonymize("Contact john@example.com")
        session_id = result.session_id

        # Get initial session info
        info1 = protector.get_session_info(session_id)
        original_expires = info1["expires_at"]

        # Wait a tiny bit
        time.sleep(0.01)

        # De-anonymize (should refresh TTL)
        protector.deanonymize(result.anonymized_text, session_id)

        # Get updated session info
        info2 = protector.get_session_info(session_id)

        # Expiration should be extended
        assert info2["expires_at"] > original_expires
        assert info2["last_accessed"] > info2["created_at"]

    def test_get_session_info_includes_ttl_remaining(self):
        """Test that get_session_info returns TTL remaining."""
        protector = PIIProtector(session_ttl_seconds=60)

        result = protector.anonymize("Contact john@example.com")
        info = protector.get_session_info(result.session_id)

        assert "ttl_remaining_seconds" in info
        assert "last_accessed" in info
        assert 50 <= info["ttl_remaining_seconds"] <= 60

    def test_refresh_session_method(self):
        """Test the explicit refresh_session method."""
        protector = PIIProtector(session_ttl_seconds=3600)

        result = protector.anonymize("Contact john@example.com")
        session_id = result.session_id

        info1 = protector.get_session_info(session_id)
        original_expires = info1["expires_at"]

        time.sleep(0.01)

        # Explicitly refresh the session
        info2 = protector.refresh_session(session_id)

        assert info2 is not None
        assert info2["refreshed"] if "refreshed" in info2 else True
        assert info2["expires_at"] > original_expires

    def test_refresh_session_nonexistent(self):
        """Test refresh_session with non-existent session."""
        protector = PIIProtector()

        result = protector.refresh_session("nonexistent-session")
        assert result is None

    def test_refresh_session_expired(self):
        """Test refresh_session with expired session."""
        protector = PIIProtector(session_ttl_seconds=0)

        # Create session that immediately expires
        result = protector.anonymize("Contact john@example.com")

        # Try to refresh expired session
        refresh_result = protector.refresh_session(result.session_id)
        assert refresh_result is None

    def test_session_stays_alive_with_activity(self):
        """Test that sessions stay alive with continuous activity."""
        # Use a very short TTL
        protector = PIIProtector(session_ttl_seconds=1)

        result = protector.anonymize("Contact john@example.com")
        session_id = result.session_id

        # Session should be alive
        assert protector.get_session_info(session_id) is not None

        # Touch repeatedly to keep alive
        for _ in range(3):
            time.sleep(0.3)  # Less than TTL
            protector.refresh_session(session_id)

        # Session should still be alive after 0.9s (less than TTL from last touch)
        info = protector.get_session_info(session_id)
        assert info is not None
        assert not info["is_expired"]


class TestTokenSessionNameTracking:
    """Test TokenSession name tracking for collision avoidance."""

    def test_used_names_initially_empty(self):
        """Test that used name sets are empty initially."""
        session = TokenSession("test-session")
        used_first, used_last = session.get_used_names()
        assert len(used_first) == 0
        assert len(used_last) == 0

    def test_add_token_with_part_mappings_tracks_names(self):
        """Test that adding token with part_mappings tracks used names."""
        from datetime import datetime
        session = TokenSession("test-session")

        token = PIIToken(
            token_id="test-token-1",
            pii_type="PERSON",
            original_value="John Smith",
            created_at=datetime.now(),
            perturbed_value="Michael Chen",
            part_mappings={
                "first": ("Michael", "John"),
                "last": ("Chen", "Smith"),
            }
        )
        session.add_token(token)

        # Check used names are tracked
        used_first, used_last = session.get_used_names()
        assert "michael" in used_first
        assert "chen" in used_last

    def test_is_first_name_used(self):
        """Test is_first_name_used check."""
        from datetime import datetime
        session = TokenSession("test-session")

        token = PIIToken(
            token_id="test-token-1",
            pii_type="PERSON",
            original_value="John Smith",
            created_at=datetime.now(),
            perturbed_value="Michael Chen",
            part_mappings={
                "first": ("Michael", "John"),
                "last": ("Chen", "Smith"),
            }
        )
        session.add_token(token)

        assert session.is_first_name_used("Michael")
        assert session.is_first_name_used("MICHAEL")  # Case insensitive
        assert not session.is_first_name_used("David")

    def test_is_last_name_used(self):
        """Test is_last_name_used check."""
        from datetime import datetime
        session = TokenSession("test-session")

        token = PIIToken(
            token_id="test-token-1",
            pii_type="PERSON",
            original_value="John Smith",
            created_at=datetime.now(),
            perturbed_value="Michael Chen",
            part_mappings={
                "first": ("Michael", "John"),
                "last": ("Chen", "Smith"),
            }
        )
        session.add_token(token)

        assert session.is_last_name_used("Chen")
        assert session.is_last_name_used("CHEN")  # Case insensitive
        assert not session.is_last_name_used("Wong")

    def test_part_mappings_added_to_perturbed_lookup(self):
        """Test that part mappings are added to perturbed_to_token lookup."""
        from datetime import datetime
        session = TokenSession("test-session")

        token = PIIToken(
            token_id="test-token-1",
            pii_type="PERSON",
            original_value="John Smith",
            created_at=datetime.now(),
            perturbed_value="Michael Chen",
            part_mappings={
                "first": ("Michael", "John"),
                "last": ("Chen", "Smith"),
            }
        )
        session.add_token(token)

        # Full name and parts should all be in perturbed mappings
        mappings = session.get_perturbed_mappings()
        assert "Michael Chen" in mappings
        assert "Michael" in mappings
        assert "Chen" in mappings


class TestPartialNameDeanonymization:
    """Test partial name deanonymization."""

    def test_pii_token_has_part_mappings(self):
        """Test PIIToken.has_part_mappings property."""
        from datetime import datetime

        # Without part mappings
        token1 = PIIToken(
            token_id="test-1",
            pii_type="PERSON",
            original_value="John Smith",
            created_at=datetime.now(),
        )
        assert not token1.has_part_mappings

        # With empty part mappings
        token2 = PIIToken(
            token_id="test-2",
            pii_type="PERSON",
            original_value="John Smith",
            created_at=datetime.now(),
            part_mappings={}
        )
        assert not token2.has_part_mappings

        # With actual part mappings
        token3 = PIIToken(
            token_id="test-3",
            pii_type="PERSON",
            original_value="John Smith",
            created_at=datetime.now(),
            part_mappings={"first": ("Michael", "John")}
        )
        assert token3.has_part_mappings

    def test_deanonymize_partial_first_name(self):
        """Test deanonymizing just the first name."""
        from datetime import datetime
        session = TokenSession("test-session")

        token = PIIToken(
            token_id="test-token-1",
            pii_type="PERSON",
            original_value="John Smith",
            created_at=datetime.now(),
            perturbed_value="Michael Chen",
            part_mappings={
                "first": ("Michael", "John"),
                "last": ("Chen", "Smith"),
            }
        )
        session.add_token(token)

        protector = PIIProtector()
        # Manually add the session
        protector._sessions["test-session"] = session

        # Deanonymize text with just first name
        result = protector.deanonymize("Michael said hello.", "test-session")

        assert result.deanonymized_text == "John said hello."
        assert result.tokens_replaced == 1

    def test_deanonymize_partial_last_name(self):
        """Test deanonymizing just the last name."""
        from datetime import datetime
        session = TokenSession("test-session")

        token = PIIToken(
            token_id="test-token-1",
            pii_type="PERSON",
            original_value="John Smith",
            created_at=datetime.now(),
            perturbed_value="Michael Chen",
            part_mappings={
                "first": ("Michael", "John"),
                "last": ("Chen", "Smith"),
            }
        )
        session.add_token(token)

        protector = PIIProtector()
        protector._sessions["test-session"] = session

        # Deanonymize text with just last name
        result = protector.deanonymize("Mr. Chen arrived.", "test-session")

        assert result.deanonymized_text == "Mr. Smith arrived."
        assert result.tokens_replaced == 1

    def test_deanonymize_full_name_still_works(self):
        """Test that full name deanonymization still works with part mappings."""
        from datetime import datetime
        session = TokenSession("test-session")

        token = PIIToken(
            token_id="test-token-1",
            pii_type="PERSON",
            original_value="John Smith",
            created_at=datetime.now(),
            perturbed_value="Michael Chen",
            part_mappings={
                "first": ("Michael", "John"),
                "last": ("Chen", "Smith"),
            }
        )
        session.add_token(token)

        protector = PIIProtector()
        protector._sessions["test-session"] = session

        # Full name should be replaced
        result = protector.deanonymize("Contact Michael Chen.", "test-session")

        assert result.deanonymized_text == "Contact John Smith."
        assert result.tokens_replaced == 1

    def test_deanonymize_mixed_full_and_partial(self):
        """Test deanonymizing mix of full name and partial names."""
        from datetime import datetime
        session = TokenSession("test-session")

        token = PIIToken(
            token_id="test-token-1",
            pii_type="PERSON",
            original_value="John Smith",
            created_at=datetime.now(),
            perturbed_value="Michael Chen",
            part_mappings={
                "first": ("Michael", "John"),
                "last": ("Chen", "Smith"),
            }
        )
        session.add_token(token)

        protector = PIIProtector()
        protector._sessions["test-session"] = session

        # Mix of full name and partials
        result = protector.deanonymize(
            "Michael Chen called Michael, and Chen responded.",
            "test-session"
        )

        assert result.deanonymized_text == "John Smith called John, and Smith responded."
        assert result.tokens_replaced == 3

    def test_deanonymize_multiple_people_same_last_name(self):
        """Test deanonymizing multiple people who share last name."""
        from datetime import datetime
        session = TokenSession("test-session")

        # Two people with same last name
        token1 = PIIToken(
            token_id="test-token-1",
            pii_type="PERSON",
            original_value="John Smith",
            created_at=datetime.now(),
            perturbed_value="Michael Chen",
            part_mappings={
                "first": ("Michael", "John"),
                "last": ("Chen", "Smith"),
            }
        )
        token2 = PIIToken(
            token_id="test-token-2",
            pii_type="PERSON",
            original_value="Jane Smith",
            created_at=datetime.now(),
            perturbed_value="Sarah Wong",
            part_mappings={
                "first": ("Sarah", "Jane"),
                "last": ("Wong", "Smith"),
            }
        )
        session.add_token(token1)
        session.add_token(token2)

        protector = PIIProtector()
        protector._sessions["test-session"] = session

        # Both should deanonymize correctly
        result = protector.deanonymize(
            "Michael and Sarah discussed the project.",
            "test-session"
        )

        assert "John" in result.deanonymized_text
        assert "Jane" in result.deanonymized_text
        assert result.tokens_replaced == 2

    def test_deanonymize_case_insensitive_llm_capitalization(self):
        """Test deanonymizing when LLM changes capitalization of perturbed names.

        This tests the fix for the bug where "ellen cheng" was perturbed but
        the LLM responded with "Ellen Cheng" and deanonymization failed.
        """
        from datetime import datetime
        session = TokenSession("test-session")

        # Original: "Dr. ellen cheng" -> perturbed to lowercase
        token = PIIToken(
            token_id="test-token-1",
            pii_type="PERSON",
            original_value="Dr. ellen cheng",
            created_at=datetime.now(),
            perturbed_value="sarah wong",  # lowercase perturbed value
            part_mappings={
                "first": ("sarah", "ellen"),
                "last": ("wong", "cheng"),
            }
        )
        session.add_token(token)

        protector = PIIProtector()
        protector._sessions["test-session"] = session

        # LLM responds with capitalized version
        result = protector.deanonymize(
            "Dr. Sarah Wong is the lead researcher.",
            "test-session"
        )

        # Should still deanonymize despite case difference
        assert "ellen" in result.deanonymized_text.lower()
        assert "cheng" in result.deanonymized_text.lower()
        assert result.tokens_replaced >= 1

    def test_deanonymize_mixed_case_perturbed_values(self):
        """Test deanonymizing with various case combinations."""
        from datetime import datetime
        session = TokenSession("test-session")

        token = PIIToken(
            token_id="test-token-1",
            pii_type="PERSON",
            original_value="John Smith",
            created_at=datetime.now(),
            perturbed_value="Michael Chen",
            part_mappings={
                "first": ("Michael", "John"),
                "last": ("Chen", "Smith"),
            }
        )
        session.add_token(token)

        protector = PIIProtector()
        protector._sessions["test-session"] = session

        # Test various case combinations that LLM might produce
        test_cases = [
            ("MICHAEL CHEN said hello.", "JOHN SMITH said hello."),
            ("michael chen said hello.", "John Smith said hello."),
            ("Michael CHEN said hello.", "John Smith said hello."),
        ]

        for input_text, expected_substring in test_cases:
            result = protector.deanonymize(input_text, "test-session")
            # Check that original names appear (case may vary due to replacement)
            assert "john" in result.deanonymized_text.lower(), f"Failed for: {input_text}"
            assert "smith" in result.deanonymized_text.lower(), f"Failed for: {input_text}"


class TestPerturbedValueTracking:
    """Test perturbed value tracking for UI highlighting."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Reset global protector before each test."""
        reset_pii_protector()

    def test_value_tracking_returns_values(self):
        """Test that anonymization returns perturbed_values."""
        protector = PIIProtector(mode=PIIProtectorMode.TOKEN_ONLY, entities=["PERSON"])
        text = "Contact John Smith for details."

        result = protector.anonymize(text)

        # Should have at least one perturbed value
        assert len(result.perturbed_values) >= 1

    def test_value_pii_type_is_set(self):
        """Test that perturbed_value pii_type is correctly set."""
        protector = PIIProtector(mode=PIIProtectorMode.TOKEN_ONLY, entities=["PERSON"])
        text = "Meet with Alice Johnson today."

        result = protector.anonymize(text)

        assert len(result.perturbed_values) >= 1
        for pv in result.perturbed_values:
            assert pv.pii_type == "PERSON"

    def test_value_is_lprag_flag_token_mode(self):
        """Test that is_lprag is False in token-only mode."""
        protector = PIIProtector(mode=PIIProtectorMode.TOKEN_ONLY, entities=["PERSON"])
        text = "Contact Bob Williams."

        result = protector.anonymize(text)

        for pv in result.perturbed_values:
            assert pv.is_lprag is False

    def test_value_tracking_env_var_disabled(self):
        """Test that value tracking can be disabled via environment variable."""
        import os
        original = os.environ.get("LPRAG_SHOW_SPANS")
        try:
            os.environ["LPRAG_SHOW_SPANS"] = "false"
            protector = PIIProtector(mode=PIIProtectorMode.TOKEN_ONLY, entities=["PERSON"])
            text = "Contact John Smith for details."

            result = protector.anonymize(text)

            # perturbed_values should be empty when disabled
            assert len(result.perturbed_values) == 0
        finally:
            if original is not None:
                os.environ["LPRAG_SHOW_SPANS"] = original
            elif "LPRAG_SHOW_SPANS" in os.environ:
                del os.environ["LPRAG_SHOW_SPANS"]
