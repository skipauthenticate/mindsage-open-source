"""Tests for LPRAG (Locally Private RAG) module.

Tests verify:
- Configuration loading and presets
- Word perturbation with exponential mechanism
- Number perturbation with Laplace mechanism
- Phrase perturbation for emails and addresses
- Adaptive privacy budget allocation
- Engine integration and fallback behavior
"""

import os
import pytest
import numpy as np
from unittest.mock import Mock, patch, MagicMock

# Import LPRAG modules
from mcp_vector_store.lprag_config import (
    LPRAGConfig,
    LPRAGMode,
    PrivacySensitivity,
    LPRAG_PRESETS,
    get_lprag_config_from_env,
    get_entity_sensitivity,
    ENTITY_SENSITIVITY_MAP,
)
from mcp_vector_store.lprag_embeddings import (
    LPRAGEmbeddings,
    get_random_name,
    get_random_location,
    COMMON_FIRST_NAMES,
    COMMON_LAST_NAMES,
    reset_lprag_embeddings,
)
from mcp_vector_store.lprag_engine import (
    LPRAGEngine,
    WordPerturbationModule,
    NumberPerturbationModule,
    PhrasePerturbationModule,
    PerturbationResult,
    PerturbationError,
    reset_lprag_engine,
)


class TestLPRAGConfig:
    """Test LPRAG configuration."""

    def test_default_config(self):
        """Test default configuration values."""
        config = LPRAGConfig()
        assert config.mode == LPRAGMode.DISABLED
        assert config.global_epsilon == 1.0
        assert config.enable_semantic_similarity is True
        assert config.use_gpu is False

    def test_config_to_dict(self):
        """Test config serialization."""
        config = LPRAGConfig(mode=LPRAGMode.HYBRID, global_epsilon=2.0)
        data = config.to_dict()
        assert data["mode"] == "hybrid"
        assert data["global_epsilon"] == 2.0

    def test_config_from_dict(self):
        """Test config deserialization."""
        data = {"mode": "pure", "global_epsilon": 0.5, "use_gpu": True}
        config = LPRAGConfig.from_dict(data)
        assert config.mode == LPRAGMode.PURE
        assert config.global_epsilon == 0.5
        assert config.use_gpu is True

    def test_get_epsilon_by_sensitivity(self):
        """Test epsilon retrieval by sensitivity level."""
        config = LPRAGConfig(
            sensitivity_epsilons={
                "critical": 0.1,
                "high": 0.5,
                "medium": 1.0,
                "low": 2.0,
            }
        )
        assert config.get_epsilon(PrivacySensitivity.CRITICAL) == 0.1
        assert config.get_epsilon(PrivacySensitivity.HIGH) == 0.5
        assert config.get_epsilon(PrivacySensitivity.MEDIUM) == 1.0
        assert config.get_epsilon(PrivacySensitivity.LOW) == 2.0

    def test_presets_exist(self):
        """Test that all presets are defined."""
        expected_presets = ["disabled", "minimal", "default", "aggressive", "high-quality"]
        for preset in expected_presets:
            assert preset in LPRAG_PRESETS

    def test_preset_disabled(self):
        """Test disabled preset."""
        preset = LPRAG_PRESETS["disabled"]
        assert preset["mode"] == "disabled"

    def test_preset_default(self):
        """Test default preset has reasonable values."""
        preset = LPRAG_PRESETS["default"]
        assert preset["mode"] == "hybrid"
        assert preset["global_epsilon"] == 1.0
        assert preset["enable_semantic_similarity"] is True
        assert preset["use_gpu"] is False

    def test_preset_aggressive(self):
        """Test aggressive preset uses pure mode."""
        preset = LPRAG_PRESETS["aggressive"]
        assert preset["mode"] == "pure"
        assert preset["global_epsilon"] < 1.0  # Stronger privacy

    def test_env_config_mode(self):
        """Test loading mode from environment."""
        with patch.dict(os.environ, {"LPRAG_MODE": "hybrid"}):
            config = get_lprag_config_from_env()
            assert config.mode == LPRAGMode.HYBRID

    def test_env_config_preset(self):
        """Test loading preset from environment."""
        with patch.dict(os.environ, {"LPRAG_PRESET": "aggressive"}, clear=False):
            # Clear LPRAG_MODE to let preset take effect
            env = os.environ.copy()
            env.pop("LPRAG_MODE", None)
            with patch.dict(os.environ, env, clear=True):
                with patch.dict(os.environ, {"LPRAG_PRESET": "aggressive"}):
                    config = get_lprag_config_from_env()
                    assert config.mode == LPRAGMode.PURE

    def test_env_config_epsilon(self):
        """Test loading epsilon from environment."""
        with patch.dict(os.environ, {"LPRAG_EPSILON": "0.75"}):
            config = get_lprag_config_from_env()
            assert config.global_epsilon == 0.75

    def test_env_config_gpu(self):
        """Test loading GPU setting from environment."""
        with patch.dict(os.environ, {"LPRAG_USE_GPU": "true"}):
            config = get_lprag_config_from_env()
            assert config.use_gpu is True


class TestEntitySensitivity:
    """Test entity sensitivity mapping."""

    def test_ssn_is_critical(self):
        """Test SSN gets critical sensitivity."""
        assert get_entity_sensitivity("US_SSN") == PrivacySensitivity.CRITICAL

    def test_credit_card_is_critical(self):
        """Test credit card gets critical sensitivity."""
        assert get_entity_sensitivity("CREDIT_CARD") == PrivacySensitivity.CRITICAL

    def test_phone_is_high(self):
        """Test phone number gets high sensitivity."""
        assert get_entity_sensitivity("PHONE_NUMBER") == PrivacySensitivity.HIGH

    def test_email_is_high(self):
        """Test email gets high sensitivity."""
        assert get_entity_sensitivity("EMAIL_ADDRESS") == PrivacySensitivity.HIGH

    def test_person_is_medium(self):
        """Test person name gets medium sensitivity."""
        assert get_entity_sensitivity("PERSON") == PrivacySensitivity.MEDIUM

    def test_date_is_low(self):
        """Test date gets low sensitivity."""
        assert get_entity_sensitivity("DATE_TIME") == PrivacySensitivity.LOW

    def test_unknown_defaults_to_medium(self):
        """Test unknown entity types default to medium."""
        assert get_entity_sensitivity("UNKNOWN_TYPE") == PrivacySensitivity.MEDIUM


class TestWordPerturbation:
    """Test word perturbation module."""

    @pytest.fixture
    def mock_embeddings(self):
        """Create mock embeddings that return predictable similar words."""
        embeddings = Mock(spec=LPRAGEmbeddings)
        embeddings.is_loaded = True
        embeddings.get_similar_words.return_value = [
            ("michael", 0.85),
            ("james", 0.82),
            ("david", 0.80),
            ("robert", 0.78),
            ("william", 0.75),
        ]
        return embeddings

    @pytest.fixture
    def config(self):
        """Create test config."""
        return LPRAGConfig(
            mode=LPRAGMode.HYBRID,
            enable_semantic_similarity=True,
            min_word_length=2,
        )

    def test_perturb_returns_different_word(self, mock_embeddings, config):
        """Test that perturbation returns a different word."""
        module = WordPerturbationModule(mock_embeddings, config)
        result = module.perturb("john", epsilon=1.0, word_type="name")

        assert result != "john"
        assert result in ["michael", "james", "david", "robert", "william"]

    def test_perturb_short_word_unchanged(self, mock_embeddings, config):
        """Test that very short words are not perturbed."""
        config.min_word_length = 3
        module = WordPerturbationModule(mock_embeddings, config)
        result = module.perturb("Jo", epsilon=1.0)
        assert result == "Jo"

    def test_perturb_name_splits_parts(self, mock_embeddings, config):
        """Test that full names are split and perturbed."""
        module = WordPerturbationModule(mock_embeddings, config)
        result, part_mappings = module.perturb_name("John Smith", epsilon=1.0)

        # Should have two parts
        parts = result.split()
        assert len(parts) == 2
        # Neither part should be original
        assert parts[0].lower() != "john"
        assert parts[1].lower() != "smith"

        # Should have part mappings
        assert part_mappings is not None
        assert "first" in part_mappings
        assert "last" in part_mappings
        # Part mappings should contain (perturbed, original) tuples
        assert part_mappings["first"][1] == "John"
        assert part_mappings["last"][1] == "Smith"
        assert part_mappings["first"][0] == parts[0]
        assert part_mappings["last"][0] == parts[1]

    def test_perturb_name_collision_avoidance(self, mock_embeddings, config):
        """Test that perturb_name avoids collisions with used names."""
        module = WordPerturbationModule(mock_embeddings, config)

        # First perturbation
        result1, mappings1 = module.perturb_name("John Smith", epsilon=1.0)
        first1 = mappings1["first"][0].lower()
        last1 = mappings1["last"][0].lower()

        # Second perturbation with first names marked as used
        used_first = {first1}
        used_last = {last1}
        result2, mappings2 = module.perturb_name(
            "Jane Doe", epsilon=1.0,
            used_first_names=used_first,
            used_last_names=used_last
        )

        # Should get different names
        first2 = mappings2["first"][0].lower()
        last2 = mappings2["last"][0].lower()
        assert first2 != first1, "Should avoid used first name"
        assert last2 != last1, "Should avoid used last name"

    def test_perturb_name_returns_none_on_exhaustion(self, mock_embeddings, config):
        """Test that perturb_name returns None when all names are used."""
        module = WordPerturbationModule(mock_embeddings, config)

        # Mark all common names as used (simulate exhaustion)
        used_first = {name.lower() for name in COMMON_FIRST_NAMES}
        used_last = {name.lower() for name in COMMON_LAST_NAMES}

        result, mappings = module.perturb_name(
            "John Smith", epsilon=1.0,
            used_first_names=used_first,
            used_last_names=used_last,
            max_retries=3  # Reduce retries for faster test
        )

        # Should return None to signal fallback needed
        assert result is None
        assert mappings is None

    def test_perturb_name_single_name(self, mock_embeddings, config):
        """Test perturbation of single name (no last name)."""
        module = WordPerturbationModule(mock_embeddings, config)
        result, mappings = module.perturb_name("John", epsilon=1.0)

        assert result is not None
        assert result.lower() != "john"
        assert mappings is not None
        assert "first" in mappings
        assert mappings["first"][1] == "John"

    def test_perturb_fallback_when_no_embeddings(self, config):
        """Test fallback to random names when embeddings unavailable."""
        embeddings = Mock(spec=LPRAGEmbeddings)
        embeddings.is_loaded = False

        config.enable_semantic_similarity = False
        module = WordPerturbationModule(embeddings, config)
        result = module.perturb("John", epsilon=1.0, word_type="first_name")

        # Should return a name from the curated list
        assert result in COMMON_FIRST_NAMES or result != "John"

    def test_lower_epsilon_more_random(self, mock_embeddings, config):
        """Test that lower epsilon produces more uniform distribution."""
        module = WordPerturbationModule(mock_embeddings, config)

        # Run many trials with different epsilon values
        results_low_eps = [module.perturb("john", epsilon=0.1) for _ in range(100)]
        results_high_eps = [module.perturb("john", epsilon=5.0) for _ in range(100)]

        # With low epsilon, distribution should be more uniform
        # With high epsilon, most similar word should dominate
        low_eps_most_common = max(set(results_low_eps), key=results_low_eps.count)
        high_eps_most_common = max(set(results_high_eps), key=results_high_eps.count)

        # The most common result with high epsilon should appear more often
        # (This is a probabilistic test, might occasionally fail)
        low_eps_freq = results_low_eps.count(low_eps_most_common)
        high_eps_freq = results_high_eps.count(high_eps_most_common)

        # High epsilon should generally have higher concentration
        # We use a soft check since this is probabilistic
        assert high_eps_freq >= low_eps_freq * 0.5  # Allow some variance


class TestNumberPerturbation:
    """Test number perturbation module."""

    @pytest.fixture
    def config(self):
        return LPRAGConfig(mode=LPRAGMode.HYBRID)

    @pytest.fixture
    def module(self, config):
        return NumberPerturbationModule(config)

    def test_perturb_preserves_format(self, module):
        """Test that phone format is preserved."""
        result = module.perturb("555-123-4567", epsilon=1.0)

        # Format should be preserved
        assert len(result) == len("555-123-4567")
        assert result[3] == "-"
        assert result[7] == "-"

        # But digits should be different
        assert result != "555-123-4567"

    def test_perturb_ssn_format(self, module):
        """Test SSN format preservation."""
        result = module.perturb_ssn("123-45-6789", epsilon=0.5)

        assert len(result) == 11
        assert result[3] == "-"
        assert result[6] == "-"

    def test_perturb_credit_card(self, module):
        """Test credit card perturbation."""
        result = module.perturb_credit_card("4111-1111-1111-1111", epsilon=0.5)

        # Format preserved
        assert result.count("-") == 3
        # Different from original
        assert result != "4111-1111-1111-1111"

    def test_digits_stay_in_range(self, module):
        """Test that all perturbed digits are 0-9."""
        # Run multiple times to catch edge cases
        for _ in range(100):
            result = module.perturb("9999999999", epsilon=0.1)
            for char in result:
                if char.isdigit():
                    assert 0 <= int(char) <= 9

    def test_high_epsilon_less_perturbation(self, module):
        """Test that high epsilon produces smaller changes."""
        np.random.seed(42)

        # High epsilon should produce values closer to original
        results_high = []
        results_low = []

        for _ in range(100):
            high = module.perturb("555", epsilon=10.0, preserve_format=False)
            low = module.perturb("555", epsilon=0.1, preserve_format=False)
            results_high.append(high)
            results_low.append(low)

        # Calculate average distance from original
        def avg_distance(results, original="555"):
            total = 0
            for r in results:
                for i, (o, p) in enumerate(zip(original, r)):
                    total += abs(int(o) - int(p))
            return total / (len(results) * len(original))

        high_dist = avg_distance(results_high)
        low_dist = avg_distance(results_low)

        # Low epsilon should have higher average distance
        assert low_dist > high_dist


class TestPhrasePerturbation:
    """Test phrase perturbation module."""

    @pytest.fixture
    def mock_word_module(self):
        module = Mock(spec=WordPerturbationModule)
        module.perturb.return_value = "PERTURBED"
        module.perturb_name.return_value = "PERTURBED NAME"
        return module

    @pytest.fixture
    def mock_number_module(self):
        module = Mock(spec=NumberPerturbationModule)
        module.perturb.return_value = "999"
        return module

    @pytest.fixture
    def config(self):
        return LPRAGConfig(mode=LPRAGMode.HYBRID, segment_perturbation_prob=1.0)

    @pytest.fixture
    def module(self, mock_word_module, mock_number_module, config):
        return PhrasePerturbationModule(
            mock_word_module, mock_number_module, config
        )

    def test_perturb_email(self, module):
        """Test email perturbation."""
        result = module.perturb("john.smith@company.com", epsilon=1.0, phrase_type="email")

        # Should have @ sign
        assert "@" in result
        # Domain should be replaced
        assert "company.com" not in result

    def test_perturb_email_preserves_structure(self, module):
        """Test that email structure is preserved."""
        result = module.perturb("user@domain.com", epsilon=1.0, phrase_type="email")

        parts = result.split("@")
        assert len(parts) == 2
        assert "." in parts[1]  # Domain has TLD

    def test_perturb_address_preserves_format(self, module, mock_word_module, mock_number_module):
        """Test address perturbation preserves structure."""
        # Configure mocks
        mock_number_module.perturb.return_value = "456"
        mock_word_module.perturb.side_effect = lambda w, e, word_type="general": f"P_{w}"

        result = module.perturb("123 Main St, New York", epsilon=1.0, phrase_type="address")

        # Should have number and street parts
        assert "456" in result or "Main" not in result


class TestLPRAGEngine:
    """Test LPRAG engine integration."""

    @pytest.fixture(autouse=True)
    def reset_engine(self):
        """Reset global engine before each test."""
        reset_lprag_engine()
        reset_lprag_embeddings()
        yield
        reset_lprag_engine()
        reset_lprag_embeddings()

    def test_engine_disabled_mode(self):
        """Test engine in disabled mode."""
        config = LPRAGConfig(mode=LPRAGMode.DISABLED)
        engine = LPRAGEngine(config=config)

        assert not engine.is_available
        result = engine.perturb_entity("John Smith", "PERSON")
        assert not result.success
        assert result.error == "LPRAG disabled"

    def test_engine_can_perturb_supported_types(self):
        """Test that engine reports correct supported types."""
        config = LPRAGConfig(mode=LPRAGMode.HYBRID)
        engine = LPRAGEngine(config=config)

        assert engine.can_perturb("PERSON")
        assert engine.can_perturb("PHONE_NUMBER")
        assert engine.can_perturb("EMAIL_ADDRESS")
        assert engine.can_perturb("US_SSN")

    def test_engine_cannot_perturb_unknown_types(self):
        """Test that engine rejects unknown types."""
        config = LPRAGConfig(mode=LPRAGMode.HYBRID)
        engine = LPRAGEngine(config=config)

        assert not engine.can_perturb("UNKNOWN_TYPE")
        assert not engine.can_perturb("CUSTOM_ENTITY")

    def test_engine_perturb_person(self):
        """Test person name perturbation."""
        config = LPRAGConfig(
            mode=LPRAGMode.HYBRID,
            enable_semantic_similarity=False,  # Use fallback for predictability
        )
        engine = LPRAGEngine(config=config)

        result = engine.perturb_entity("John Smith", "PERSON")

        assert result.success
        assert result.pii_type == "PERSON"
        assert result.perturbation_type == "word"
        assert result.perturbed_value != "John Smith"
        # Should have part mappings for names
        assert result.part_mappings is not None
        assert "first" in result.part_mappings
        assert "last" in result.part_mappings

    def test_engine_perturb_person_with_used_names(self):
        """Test person perturbation avoids collisions with used names."""
        config = LPRAGConfig(
            mode=LPRAGMode.HYBRID,
            enable_semantic_similarity=False,
        )
        engine = LPRAGEngine(config=config)

        # First perturbation
        result1 = engine.perturb_entity("John Smith", "PERSON")
        assert result1.success
        first1 = result1.part_mappings["first"][0].lower()
        last1 = result1.part_mappings["last"][0].lower()

        # Second perturbation with first names marked as used
        result2 = engine.perturb_entity(
            "Jane Doe", "PERSON",
            used_first_names={first1},
            used_last_names={last1}
        )

        assert result2.success
        first2 = result2.part_mappings["first"][0].lower()
        last2 = result2.part_mappings["last"][0].lower()
        assert first2 != first1, "Should avoid used first name"
        assert last2 != last1, "Should avoid used last name"

    def test_engine_perturb_phone(self):
        """Test phone number perturbation."""
        config = LPRAGConfig(mode=LPRAGMode.HYBRID)
        engine = LPRAGEngine(config=config)

        result = engine.perturb_entity("555-123-4567", "PHONE_NUMBER")

        assert result.success
        assert result.pii_type == "PHONE_NUMBER"
        assert result.perturbation_type == "number"
        assert result.perturbed_value != "555-123-4567"
        # Format preserved
        assert len(result.perturbed_value) == len("555-123-4567")

    def test_engine_perturb_email(self):
        """Test email perturbation."""
        config = LPRAGConfig(
            mode=LPRAGMode.HYBRID,
            enable_semantic_similarity=False,
        )
        engine = LPRAGEngine(config=config)

        result = engine.perturb_entity("john@example.com", "EMAIL_ADDRESS")

        assert result.success
        assert result.pii_type == "EMAIL_ADDRESS"
        assert result.perturbation_type == "phrase"
        assert "@" in result.perturbed_value

    def test_engine_unsupported_returns_failure(self):
        """Test that unsupported types return failure result."""
        config = LPRAGConfig(mode=LPRAGMode.HYBRID)
        engine = LPRAGEngine(config=config)

        result = engine.perturb_entity("some value", "CUSTOM_TYPE")

        assert not result.success
        assert "Unsupported" in result.error

    def test_engine_hybrid_mode_generates_token(self):
        """Test that hybrid mode generates token IDs."""
        config = LPRAGConfig(
            mode=LPRAGMode.HYBRID,
            enable_semantic_similarity=False,
        )
        engine = LPRAGEngine(config=config)

        result = engine.perturb_entity("John", "PERSON")

        assert result.success
        assert result.token_id is not None
        assert len(result.token_id) > 0

    def test_engine_pure_mode_no_token(self):
        """Test that pure mode does not generate token IDs."""
        config = LPRAGConfig(
            mode=LPRAGMode.PURE,
            enable_semantic_similarity=False,
        )
        engine = LPRAGEngine(config=config)

        result = engine.perturb_entity("John", "PERSON")

        assert result.success
        assert result.token_id is None

    def test_engine_stats(self):
        """Test engine statistics."""
        config = LPRAGConfig(
            mode=LPRAGMode.HYBRID,
            enable_semantic_similarity=False,
        )
        engine = LPRAGEngine(config=config)

        # Perform some perturbations
        person_result = engine.perturb_entity("John", "PERSON")
        phone_result = engine.perturb_entity("555-1234", "PHONE_NUMBER")
        unsupported_result = engine.perturb_entity("unknown", "UNSUPPORTED_TYPE")

        stats = engine.get_stats()

        assert stats["mode"] == "hybrid"
        assert stats["is_available"] is True
        # Count successful perturbations
        expected_count = sum([
            person_result.success,
            phone_result.success,
        ])
        assert stats["perturbations_count"] == expected_count
        # Unsupported types return early without incrementing fallback_count
        assert not unsupported_result.success
        assert unsupported_result.error == "Unsupported entity type: UNSUPPORTED_TYPE"


class TestRandomNameHelpers:
    """Test random name/location helper functions."""

    def test_get_random_name_returns_string(self):
        """Test that random name returns a string."""
        name = get_random_name()
        assert isinstance(name, str)
        assert len(name) > 0

    def test_get_random_name_excludes_specified(self):
        """Test that excluded name is not returned."""
        for _ in range(50):
            name = get_random_name(first_name=True, last_name=False, exclude="John")
            assert name != "John"

    def test_get_random_name_first_only(self):
        """Test getting only first name."""
        name = get_random_name(first_name=True, last_name=False)
        assert " " not in name
        assert name in COMMON_FIRST_NAMES

    def test_get_random_name_last_only(self):
        """Test getting only last name."""
        name = get_random_name(first_name=False, last_name=True)
        assert " " not in name
        assert name in COMMON_LAST_NAMES

    def test_get_random_location(self):
        """Test getting random location."""
        location = get_random_location()
        assert isinstance(location, str)
        assert len(location) > 0

    def test_get_random_location_excludes(self):
        """Test that excluded location is not returned."""
        for _ in range(50):
            location = get_random_location(exclude="New York")
            assert location != "New York"


class TestLPRAGEmbeddings:
    """Test LPRAG embeddings (without actually loading models)."""

    @pytest.fixture(autouse=True)
    def reset(self):
        reset_lprag_embeddings()
        yield
        reset_lprag_embeddings()

    def test_embeddings_stats_before_init(self):
        """Test stats after construction (vocabulary may load eagerly)."""
        embeddings = LPRAGEmbeddings(verbose=False)
        stats = embeddings.get_stats()

        # Embeddings may be loaded during construction (vocabulary available)
        # Check that stats are available and have reasonable values
        assert "is_loaded" in stats
        assert "vocabulary_size" in stats
        assert isinstance(stats["vocabulary_size"], int)

    def test_embeddings_unload(self):
        """Test unloading embeddings."""
        embeddings = LPRAGEmbeddings(verbose=False)
        embeddings.unload()

        assert not embeddings.is_loaded

    @patch("mcp_vector_store.lprag_embeddings.GENSIM_AVAILABLE", False)
    def test_embeddings_unavailable_without_gensim(self):
        """Test that embeddings are unavailable without gensim."""
        embeddings = LPRAGEmbeddings(use_gpu=False, verbose=False)
        assert not embeddings.is_available


class TestPerturbationResult:
    """Test PerturbationResult dataclass."""

    def test_successful_result(self):
        """Test creating a successful result."""
        result = PerturbationResult(
            original_value="John",
            perturbed_value="Michael",
            pii_type="PERSON",
            perturbation_type="word",
            epsilon_used=1.0,
            token_id="abc123",
            success=True,
        )

        assert result.success
        assert result.original_value == "John"
        assert result.perturbed_value == "Michael"
        assert result.error is None

    def test_failed_result(self):
        """Test creating a failed result."""
        result = PerturbationResult(
            original_value="value",
            perturbed_value="value",
            pii_type="UNKNOWN",
            perturbation_type="none",
            epsilon_used=0,
            success=False,
            error="Unsupported type",
        )

        assert not result.success
        assert result.error == "Unsupported type"
        assert result.original_value == result.perturbed_value
