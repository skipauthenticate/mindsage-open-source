"""Tests for consent management module.

These tests verify the consent-based filtering, session management,
and PII protection integration.
"""

import pytest
import time
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

# Import the modules under test
from mcp_vector_store.consent_config import (
    CONSENT_PRESETS,
    DATA_CATEGORIES,
    CRITICAL_PII_TYPES,
    PII_TYPE_CONFIG,
    TOPIC_TO_CATEGORY_MAP,
    get_preset_config,
    get_categories_for_topics,
    is_category_allowed,
    is_pii_type_exposed,
    validate_pii_exposure,
)

from mcp_vector_store.consent_session import (
    Session,
    SessionManager,
    PIIMappings,
    PIIToken,
    DocumentRules,
    TimeRules,
    EntityRules,
    EntityDefinition,
    get_session_manager,
    reset_session_manager,
)

from mcp_vector_store.consent_manager import (
    ConsentManager,
    ConsentFilterStats,
    PIIFilterStats,
    get_consent_manager,
    reset_consent_manager,
)


class TestConsentConfig:
    """Test consent configuration module."""

    def test_presets_exist(self):
        """Test that all expected presets are defined."""
        expected_presets = [
            "strict", "balanced", "open",
            "health_focus", "work_only", "recent_only", "family_protected"
        ]
        for preset in expected_presets:
            assert preset in CONSENT_PRESETS

    def test_get_preset_config(self):
        """Test retrieving preset configuration."""
        config = get_preset_config("balanced")
        assert config is not None
        assert config.name == "balanced"
        assert "work" in config.allowed_categories
        assert "health" in config.blocked_categories

    def test_get_preset_config_invalid(self):
        """Test retrieving non-existent preset returns None."""
        config = get_preset_config("nonexistent")
        assert config is None

    def test_data_categories(self):
        """Test that all expected categories are defined."""
        expected = {"health", "finance", "work", "personal", "social", "legal", "travel", "education", "general"}
        assert DATA_CATEGORIES == expected

    def test_critical_pii_types(self):
        """Test that critical PII types are defined."""
        assert "US_SSN" in CRITICAL_PII_TYPES
        assert "CREDIT_CARD" in CRITICAL_PII_TYPES
        assert "US_BANK_NUMBER" in CRITICAL_PII_TYPES

    def test_get_categories_for_topics(self):
        """Test topic to category mapping."""
        # Single topic
        categories = get_categories_for_topics(["health"])
        assert "health" in categories

        # Multiple topics
        categories = get_categories_for_topics(["doctor", "budget"])
        assert "health" in categories
        assert "finance" in categories

        # Unknown topic defaults to general
        categories = get_categories_for_topics(["unknown_topic_xyz"])
        assert "general" in categories

    def test_is_category_allowed(self):
        """Test category permission checking."""
        # With explicit allowlist
        assert is_category_allowed("work", {"work", "general"}, set()) is True
        assert is_category_allowed("health", {"work", "general"}, set()) is False

        # With blocklist
        assert is_category_allowed("work", set(), {"health"}) is True
        assert is_category_allowed("health", set(), {"health"}) is False

        # Blocklist wins over allowlist
        assert is_category_allowed("health", {"health"}, {"health"}) is False

        # Empty means all allowed
        assert is_category_allowed("health", set(), set()) is True

        # Wildcard
        assert is_category_allowed("health", {"*"}, set()) is True

    def test_is_pii_type_exposed(self):
        """Test PII type exposure checking."""
        # Normal PII type
        assert is_pii_type_exposed("PERSON", {"PERSON"}) is True
        assert is_pii_type_exposed("PERSON", set()) is False

        # Critical PII is NEVER exposed
        assert is_pii_type_exposed("US_SSN", {"US_SSN"}) is False
        assert is_pii_type_exposed("CREDIT_CARD", {"CREDIT_CARD"}) is False

    def test_validate_pii_exposure(self):
        """Test that critical PII types are removed from exposure list."""
        exposed = {"PERSON", "US_SSN", "EMAIL_ADDRESS", "CREDIT_CARD"}
        validated = validate_pii_exposure(exposed)

        assert "PERSON" in validated
        assert "EMAIL_ADDRESS" in validated
        assert "US_SSN" not in validated
        assert "CREDIT_CARD" not in validated


class TestSessionManager:
    """Test SessionManager class."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Reset session manager before each test."""
        reset_session_manager()

    def test_create_session(self):
        """Test session creation."""
        manager = SessionManager()
        session = manager.create_session()

        assert session is not None
        assert session.session_id is not None
        assert len(session.session_id) > 0

    def test_create_session_with_preset(self):
        """Test session creation with preset."""
        manager = SessionManager()
        session = manager.create_session(preset="strict")

        # Strict preset has no allowed categories
        assert len(session.allowed_categories) == 0

    def test_get_session(self):
        """Test retrieving a session."""
        manager = SessionManager()
        session = manager.create_session()
        session_id = session.session_id

        retrieved = manager.get_session(session_id)
        assert retrieved is not None
        assert retrieved.session_id == session_id

    def test_get_nonexistent_session(self):
        """Test retrieving non-existent session returns None."""
        manager = SessionManager()
        assert manager.get_session("nonexistent") is None

    def test_session_expiration(self):
        """Test session expiration."""
        manager = SessionManager(session_ttl_seconds=0)
        session = manager.create_session()
        session_id = session.session_id

        # Session should be expired immediately
        retrieved = manager.get_session(session_id)
        assert retrieved is None  # Expired sessions are removed

    def test_session_lru_eviction(self):
        """Test LRU eviction when max sessions reached."""
        manager = SessionManager(max_sessions=2)

        s1 = manager.create_session()
        s2 = manager.create_session()

        # Both should exist
        assert manager.get_session(s1.session_id) is not None
        assert manager.get_session(s2.session_id) is not None

        # Create third - should evict oldest (s1)
        s3 = manager.create_session()

        assert manager.get_session(s1.session_id) is None  # Evicted
        assert manager.get_session(s2.session_id) is not None
        assert manager.get_session(s3.session_id) is not None

    def test_delete_session(self):
        """Test session deletion."""
        manager = SessionManager()
        session = manager.create_session()
        session_id = session.session_id

        assert manager.delete_session(session_id) is True
        assert manager.get_session(session_id) is None
        assert manager.delete_session(session_id) is False  # Already deleted

    def test_get_or_create_session(self):
        """Test get_or_create_session method."""
        manager = SessionManager()

        # Create new session
        session1 = manager.get_or_create_session()
        assert session1 is not None

        # Get existing session
        session2 = manager.get_or_create_session(session_id=session1.session_id)
        assert session2.session_id == session1.session_id

        # Create new with specific ID
        session3 = manager.get_or_create_session(session_id="custom-id")
        assert session3.session_id == "custom-id"


class TestSession:
    """Test Session class."""

    def test_apply_preset(self):
        """Test applying preset to session."""
        session = Session()
        session.apply_preset("strict")

        assert len(session.allowed_categories) == 0
        assert len(session.blocked_categories) == len(DATA_CATEGORIES)

    def test_apply_preset_invalid(self):
        """Test applying invalid preset returns False."""
        session = Session()
        result = session.apply_preset("nonexistent")
        assert result is False

    def test_update_categories(self):
        """Test updating category rules."""
        session = Session()
        session.update_categories(
            allowed={"work", "education"},
            blocked={"health", "finance"}
        )

        assert "work" in session.allowed_categories
        assert "health" in session.blocked_categories

    def test_update_pii_types(self):
        """Test updating PII type exposure."""
        session = Session()
        session.update_pii_types(exposed={"PERSON", "LOCATION"})

        assert "PERSON" in session.exposed_pii_types
        assert "LOCATION" in session.exposed_pii_types

    def test_critical_pii_never_exposed(self):
        """Test that critical PII types are filtered from exposure."""
        session = Session()
        session.update_pii_types(exposed={"PERSON", "US_SSN", "CREDIT_CARD"})

        assert "PERSON" in session.exposed_pii_types
        assert "US_SSN" not in session.exposed_pii_types
        assert "CREDIT_CARD" not in session.exposed_pii_types

    def test_protect_entity(self):
        """Test protecting an entity."""
        session = Session()
        session.protect_entity("John Smith", aliases=["Johnny", "JS"])

        assert len(session.entity_rules.protect_entities) == 1
        entity = session.entity_rules.protect_entities[0]
        assert entity.name == "John Smith"
        assert "Johnny" in entity.aliases

    def test_expose_entity(self):
        """Test exposing an entity."""
        session = Session()
        session.expose_entity("Self", relationship="self")

        assert len(session.entity_rules.expose_entities) == 1
        entity = session.entity_rules.expose_entities[0]
        assert entity.name == "Self"
        assert entity.relationship == "self"

    def test_block_document(self):
        """Test blocking a document."""
        session = Session()
        session.block_document(123)
        session.block_document(456)

        assert 123 in session.document_rules.blocked_ids
        assert 456 in session.document_rules.blocked_ids

    def test_set_time_rules(self):
        """Test setting time rules."""
        session = Session()

        # With datetime objects
        after = datetime.now() - timedelta(days=30)
        before = datetime.now()
        session.set_time_rules(after=after, before=before)

        assert session.time_rules.after is not None
        assert session.time_rules.before is not None

    def test_set_time_rules_relative(self):
        """Test setting relative time rules."""
        session = Session()
        session.set_time_rules(relative="-30d")

        after, before = session.time_rules.get_effective_range()
        assert after is not None
        # after should be ~30 days ago

    def test_session_to_dict(self):
        """Test session serialization to dict."""
        session = Session()
        session.apply_preset("balanced")
        session.protect_entity("John")

        data = session.to_dict()

        # Consent settings are nested under "consent" key
        assert "consent" in data
        assert "allowed_categories" in data["consent"]
        assert "blocked_categories" in data["consent"]
        assert "exposed_pii_types" in data["consent"]
        assert "entity_rules" in data["consent"]
        assert "document_rules" in data["consent"]
        assert "time_rules" in data["consent"]


class TestPIIMappings:
    """Test PIIMappings class."""

    def test_add_and_get_token(self):
        """Test adding and retrieving tokens."""
        mappings = PIIMappings()
        token = PIIToken(
            token_id="abc123",
            pii_type="PERSON",
            original_value="John Smith"
        )
        mappings.add_token(token)

        retrieved = mappings.get_token("abc123")
        assert retrieved is not None
        assert retrieved.original_value == "John Smith"

    def test_get_token_by_value(self):
        """Test getting token by PII type and value."""
        mappings = PIIMappings()
        token = PIIToken(
            token_id="abc123",
            pii_type="PERSON",
            original_value="John Smith"
        )
        mappings.add_token(token)

        retrieved = mappings.get_token_for_value("PERSON", "John Smith")
        assert retrieved is not None
        assert retrieved.token_id == "abc123"

    def test_get_token_by_perturbed_value(self):
        """Test getting original value by perturbed value (LPRAG)."""
        mappings = PIIMappings()
        token = PIIToken(
            token_id="abc123",
            pii_type="PERSON",
            original_value="John Smith",
            perturbed_value="Michael Chen"
        )
        mappings.add_token(token)

        original = mappings.get_original_for_perturbed("Michael Chen")
        assert original == "John Smith"


class TestConsentManager:
    """Test ConsentManager class."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Reset managers before each test."""
        reset_session_manager()
        reset_consent_manager()

    def test_filter_documents_by_category(self):
        """Test document filtering by category."""
        manager = ConsentManager()
        session = manager.get_or_create_session(preset="work_only")

        documents = [
            {"id": 1, "text": "Work document", "topics": ["work", "meeting"]},
            {"id": 2, "text": "Health record", "topics": ["medical", "doctor"]},
            {"id": 3, "text": "General info", "topics": ["general"]},
        ]

        filtered, stats = manager.filter_documents(documents, session)

        # Should only include work-related documents
        assert len(filtered) == 1  # Only work doc (general is not in work_only preset)
        assert filtered[0]["id"] == 1
        assert stats.documents_filtered_by_category == 2

    def test_filter_documents_by_id(self):
        """Test document filtering by ID blocklist."""
        manager = ConsentManager()
        session = manager.get_or_create_session(preset="open")
        session.block_document(2)

        documents = [
            {"id": 1, "text": "Doc 1"},
            {"id": 2, "text": "Doc 2"},
            {"id": 3, "text": "Doc 3"},
        ]

        filtered, stats = manager.filter_documents(documents, session)

        assert len(filtered) == 2
        assert all(d["id"] != 2 for d in filtered)
        assert stats.documents_filtered_by_id == 1
        assert 2 in stats.documents_blocked

    def test_filter_documents_by_time(self):
        """Test document filtering by time range."""
        manager = ConsentManager()
        session = manager.get_or_create_session(preset="open")

        # Set time filter for last 7 days
        session.set_time_rules(relative="-7d")

        now = datetime.now()
        documents = [
            {"id": 1, "text": "Recent", "created_at": now.isoformat()},
            {"id": 2, "text": "Old", "created_at": (now - timedelta(days=30)).isoformat()},
            {"id": 3, "text": "No date"},  # Should be included (can't filter)
        ]

        filtered, stats = manager.filter_documents(documents, session)

        assert len(filtered) == 2
        assert stats.documents_filtered_by_time == 1

    def test_should_anonymize_pii_critical(self):
        """Test that critical PII is always anonymized."""
        manager = ConsentManager()
        session = manager.get_or_create_session(preset="open")
        session.update_pii_types(exposed={"US_SSN"})  # Try to expose critical

        should_anon, reason = manager.should_anonymize_pii("US_SSN", "123-45-6789", session)

        assert should_anon is True
        assert reason == "critical_pii"

    def test_should_anonymize_pii_type_exposed(self):
        """Test PII type exposure setting."""
        manager = ConsentManager()
        session = manager.get_or_create_session()
        session.update_pii_types(exposed={"PERSON", "LOCATION"})

        should_anon, reason = manager.should_anonymize_pii("PERSON", "John", session)
        assert should_anon is False
        assert reason == "pii_type_exposed"

        should_anon, reason = manager.should_anonymize_pii("EMAIL_ADDRESS", "test@example.com", session)
        assert should_anon is True
        assert reason == "pii_type_anonymized"

    def test_should_anonymize_entity_protected(self):
        """Test entity-specific protection."""
        manager = ConsentManager()
        session = manager.get_or_create_session()
        session.update_pii_types(exposed={"PERSON"})  # Allow PERSON by default
        session.protect_entity("John Smith")  # But protect this specific person

        should_anon, reason = manager.should_anonymize_pii("PERSON", "John Smith", session)
        assert should_anon is True
        assert "entity_protected" in reason

    def test_should_anonymize_entity_exposed(self):
        """Test entity-specific exposure."""
        manager = ConsentManager()
        session = manager.get_or_create_session()
        # Don't expose PERSON type by default, but expose specific entity
        session.expose_entity("Self")

        should_anon, reason = manager.should_anonymize_pii("PERSON", "Self", session)
        assert should_anon is False
        assert "entity_exposed" in reason


class TestTimeRules:
    """Test TimeRules class."""

    def test_relative_time_days(self):
        """Test relative time parsing for days."""
        rules = TimeRules()
        rules.relative = "-30d"

        after, before = rules.get_effective_range()

        assert after is not None
        assert before is None
        # after should be approximately 30 days ago
        expected = datetime.now() - timedelta(days=30)
        assert abs((after - expected).total_seconds()) < 60  # Within 1 minute

    def test_relative_time_months(self):
        """Test relative time parsing for months."""
        rules = TimeRules()
        rules.relative = "-3m"

        after, before = rules.get_effective_range()

        assert after is not None
        # ~90 days ago
        expected = datetime.now() - timedelta(days=90)
        assert abs((after - expected).total_seconds()) < 60

    def test_relative_time_years(self):
        """Test relative time parsing for years."""
        rules = TimeRules()
        rules.relative = "-1y"

        after, before = rules.get_effective_range()

        assert after is not None
        # ~365 days ago
        expected = datetime.now() - timedelta(days=365)
        assert abs((after - expected).total_seconds()) < 60

    def test_explicit_datetime_range(self):
        """Test explicit datetime range."""
        rules = TimeRules()
        rules.after = datetime(2024, 1, 1)
        rules.before = datetime(2024, 12, 31)

        after, before = rules.get_effective_range()

        assert after == datetime(2024, 1, 1)
        assert before == datetime(2024, 12, 31)


class TestEntityMatching:
    """Test entity matching logic."""

    def test_entity_exact_match(self):
        """Test exact name match."""
        manager = ConsentManager()
        session = manager.get_or_create_session()
        session.protect_entity("John Smith")

        # Exact match
        should_anon, _ = manager.should_anonymize_pii("PERSON", "John Smith", session)
        assert should_anon is True

    def test_entity_case_insensitive(self):
        """Test case-insensitive matching."""
        manager = ConsentManager()
        session = manager.get_or_create_session()
        session.protect_entity("John Smith")

        # Different case
        should_anon, _ = manager.should_anonymize_pii("PERSON", "john smith", session)
        assert should_anon is True

    def test_entity_alias_match(self):
        """Test alias matching."""
        manager = ConsentManager()
        session = manager.get_or_create_session()
        session.protect_entity("John Smith", aliases=["Johnny", "J. Smith"])

        # Alias match
        should_anon, _ = manager.should_anonymize_pii("PERSON", "Johnny", session)
        assert should_anon is True

    def test_entity_partial_match(self):
        """Test partial name matching."""
        manager = ConsentManager()
        session = manager.get_or_create_session()
        session.protect_entity("John")

        # Name contains protected entity
        should_anon, _ = manager.should_anonymize_pii("PERSON", "John Smith", session)
        assert should_anon is True


class TestPresetConfigurations:
    """Test that preset configurations are correctly applied."""

    def test_strict_preset(self):
        """Test strict preset blocks everything."""
        config = get_preset_config("strict")
        assert len(config.allowed_categories) == 0
        assert len(config.blocked_categories) == len(DATA_CATEGORIES)
        assert len(config.exposed_pii_types) == 0

    def test_open_preset(self):
        """Test open preset allows most things."""
        config = get_preset_config("open")
        assert len(config.allowed_categories) == len(DATA_CATEGORIES)
        assert len(config.blocked_categories) == 0
        assert "PERSON" in config.exposed_pii_types

    def test_balanced_preset(self):
        """Test balanced preset allows work-related content."""
        config = get_preset_config("balanced")
        assert "work" in config.allowed_categories
        assert "health" in config.blocked_categories
        assert "DATE_TIME" in config.exposed_pii_types

    def test_health_focus_preset(self):
        """Test health focus preset allows health data."""
        config = get_preset_config("health_focus")
        assert "health" in config.allowed_categories
        assert "finance" in config.blocked_categories

    def test_work_only_preset(self):
        """Test work only preset restricts to work content."""
        config = get_preset_config("work_only")
        assert "work" in config.allowed_categories
        assert "health" in config.blocked_categories
        assert "personal" in config.blocked_categories
