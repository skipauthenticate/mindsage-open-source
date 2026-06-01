"""Configuration management for LPRAG (Locally Private RAG).

LPRAG provides Local Differential Privacy (LDP) for PII protection by perturbing
sensitive entities with semantically similar values instead of opaque tokens.

Environment variables:
    LPRAG_MODE: Operating mode - "disabled", "pure", "hybrid" (default: "hybrid")
        - disabled: No LPRAG, use standard token-based anonymization
        - pure: Perturbation only, no reversibility (maximum privacy)
        - hybrid: Perturbation with token mapping for de-anonymization (recommended)

    LPRAG_PRESET: Configuration preset - "minimal", "default", "aggressive", "high-quality"

    LPRAG_EPSILON: Global epsilon override (default: 1.0)
        Lower values = stronger privacy (more noise), less utility
        Higher values = weaker privacy, better utility

    LPRAG_USE_GPU: Use GPU-accelerated semantic similarity (default: "false")
        - false: Use GloVe embeddings on CPU (~50MB, ~10-15ms per perturbation)
        - true: Use Sentence Transformers on GPU (~100MB VRAM, higher quality)

Example usage:
    # Use default hybrid mode with GloVe
    export LPRAG_MODE=hybrid
    export LPRAG_PRESET=default

    # Use aggressive privacy mode
    export LPRAG_MODE=pure
    export LPRAG_PRESET=aggressive

    # Use high-quality GPU mode
    export LPRAG_MODE=hybrid
    export LPRAG_PRESET=high-quality
    export LPRAG_USE_GPU=true
"""

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional, Any


class LPRAGMode(Enum):
    """Operating modes for LPRAG."""
    DISABLED = "disabled"  # No LPRAG, use token-based anonymization
    PURE = "pure"          # Perturbation only, no reversibility
    HYBRID = "hybrid"      # Perturbation with token mapping for de-anonymization


class PrivacySensitivity(Enum):
    """Sensitivity levels for adaptive privacy budget allocation.

    Lower epsilon = stronger privacy (more noise/randomness)
    """
    CRITICAL = "critical"  # SSN, credit cards, bank accounts - epsilon ~0.1
    HIGH = "high"          # Phone numbers, emails - epsilon ~0.5
    MEDIUM = "medium"      # Names, addresses - epsilon ~1.0
    LOW = "low"            # Dates, locations - epsilon ~2.0


@dataclass
class LPRAGConfig:
    """Configuration for LPRAG engine.

    Attributes:
        mode: Operating mode (disabled, pure, hybrid)
        global_epsilon: Base epsilon value for differential privacy
        sensitivity_epsilons: Epsilon values per sensitivity level
        enable_semantic_similarity: Use embeddings for word similarity
        use_gpu: Use GPU-accelerated Sentence Transformers
        embedding_model: GloVe model name (for CPU mode)
        similarity_top_k: Number of similar words to consider
        laplace_scale_base: Base scale for Laplace noise on numbers
        segment_perturbation_prob: Probability of perturbing each phrase segment
        min_word_length: Minimum word length to consider for perturbation
    """
    mode: LPRAGMode = LPRAGMode.DISABLED
    global_epsilon: float = 1.0
    sensitivity_epsilons: Dict[str, float] = field(default_factory=lambda: {
        "critical": 0.1,
        "high": 0.5,
        "medium": 1.0,
        "low": 2.0
    })
    enable_semantic_similarity: bool = True
    use_gpu: bool = False
    embedding_model: str = "glove-wiki-gigaword-50"
    similarity_top_k: int = 10
    laplace_scale_base: float = 1.0
    segment_perturbation_prob: float = 0.3
    min_word_length: int = 2

    def get_epsilon(self, sensitivity: PrivacySensitivity) -> float:
        """Get epsilon value for a sensitivity level."""
        return self.sensitivity_epsilons.get(
            sensitivity.value,
            self.global_epsilon
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary for serialization."""
        return {
            "mode": self.mode.value,
            "global_epsilon": self.global_epsilon,
            "sensitivity_epsilons": self.sensitivity_epsilons,
            "enable_semantic_similarity": self.enable_semantic_similarity,
            "use_gpu": self.use_gpu,
            "embedding_model": self.embedding_model,
            "similarity_top_k": self.similarity_top_k,
            "laplace_scale_base": self.laplace_scale_base,
            "segment_perturbation_prob": self.segment_perturbation_prob,
            "min_word_length": self.min_word_length,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LPRAGConfig":
        """Create config from dictionary."""
        mode_str = data.get("mode", "disabled")
        try:
            mode = LPRAGMode(mode_str)
        except ValueError:
            mode = LPRAGMode.DISABLED

        return cls(
            mode=mode,
            global_epsilon=data.get("global_epsilon", 1.0),
            sensitivity_epsilons=data.get("sensitivity_epsilons", {
                "critical": 0.1, "high": 0.5, "medium": 1.0, "low": 2.0
            }),
            enable_semantic_similarity=data.get("enable_semantic_similarity", True),
            use_gpu=data.get("use_gpu", False),
            embedding_model=data.get("embedding_model", "glove-wiki-gigaword-50"),
            similarity_top_k=data.get("similarity_top_k", 10),
            laplace_scale_base=data.get("laplace_scale_base", 1.0),
            segment_perturbation_prob=data.get("segment_perturbation_prob", 0.3),
            min_word_length=data.get("min_word_length", 2),
        )


# Preset configurations for common use cases
LPRAG_PRESETS: Dict[str, Dict[str, Any]] = {
    # Disabled - no LPRAG, use standard token-based anonymization
    "disabled": {
        "mode": "disabled",
        "global_epsilon": float('inf'),
        "enable_semantic_similarity": False,
        "use_gpu": False,
    },

    # Minimal - basic perturbation with relaxed privacy
    # Fast, low memory, but less private
    "minimal": {
        "mode": "hybrid",
        "global_epsilon": 2.0,
        "sensitivity_epsilons": {
            "critical": 0.5,
            "high": 1.0,
            "medium": 2.0,
            "low": 4.0
        },
        "enable_semantic_similarity": False,  # Faster, random selection
        "use_gpu": False,
    },

    # Default - balanced privacy and utility with GloVe
    # Good for most use cases
    "default": {
        "mode": "hybrid",
        "global_epsilon": 1.0,
        "sensitivity_epsilons": {
            "critical": 0.1,
            "high": 0.5,
            "medium": 1.0,
            "low": 2.0
        },
        "enable_semantic_similarity": True,
        "use_gpu": False,
    },

    # Aggressive - strong privacy, pure mode (no reversibility)
    # Maximum privacy, but responses stay perturbed
    "aggressive": {
        "mode": "pure",
        "global_epsilon": 0.5,
        "sensitivity_epsilons": {
            "critical": 0.05,
            "high": 0.2,
            "medium": 0.5,
            "low": 1.0
        },
        "enable_semantic_similarity": True,
        "use_gpu": False,
    },

    # High-quality - uses GPU for better semantic similarity
    # Best quality replacements, requires GPU
    "high-quality": {
        "mode": "hybrid",
        "global_epsilon": 1.0,
        "sensitivity_epsilons": {
            "critical": 0.1,
            "high": 0.5,
            "medium": 1.0,
            "low": 2.0
        },
        "enable_semantic_similarity": True,
        "use_gpu": True,
    },
}


def get_lprag_config_from_env() -> LPRAGConfig:
    """Load LPRAG configuration from environment variables.

    Priority:
    1. Explicit environment variables (LPRAG_MODE, LPRAG_EPSILON, etc.)
    2. Preset values (LPRAG_PRESET)
    3. Defaults (hybrid mode for best balance of privacy and usability)

    Returns:
        LPRAGConfig instance based on environment settings.
    """
    # Start with hybrid mode as default (matches PIIProtector default)
    # This provides LPRAG perturbation with automatic fallback to tokens
    config_dict: Dict[str, Any] = {"mode": "hybrid"}

    # Check for preset first
    preset_name = os.environ.get("LPRAG_PRESET", "").strip().lower()
    if preset_name and preset_name in LPRAG_PRESETS:
        config_dict.update(LPRAG_PRESETS[preset_name])

    # Override with explicit environment variables
    mode_str = os.environ.get("LPRAG_MODE", "").strip().lower()
    if mode_str:
        config_dict["mode"] = mode_str

    epsilon_str = os.environ.get("LPRAG_EPSILON", "").strip()
    if epsilon_str:
        try:
            config_dict["global_epsilon"] = float(epsilon_str)
        except ValueError:
            pass  # Keep preset or default value

    use_gpu_str = os.environ.get("LPRAG_USE_GPU", "").strip().lower()
    if use_gpu_str:
        config_dict["use_gpu"] = use_gpu_str in ("true", "1", "yes")

    semantic_str = os.environ.get("LPRAG_SEMANTIC_SIMILARITY", "").strip().lower()
    if semantic_str:
        config_dict["enable_semantic_similarity"] = semantic_str in ("true", "1", "yes")

    embedding_model = os.environ.get("LPRAG_EMBEDDING_MODEL", "").strip()
    if embedding_model:
        config_dict["embedding_model"] = embedding_model

    # Build config from dict
    return LPRAGConfig.from_dict(config_dict)


def get_preset_names() -> list:
    """Get list of available preset names."""
    return list(LPRAG_PRESETS.keys())


def get_preset_config(preset_name: str) -> Optional[Dict[str, Any]]:
    """Get configuration dict for a preset."""
    return LPRAG_PRESETS.get(preset_name.lower())


# Entity type to sensitivity mapping
ENTITY_SENSITIVITY_MAP: Dict[str, PrivacySensitivity] = {
    # Critical - maximum protection (epsilon ~0.1)
    "US_SSN": PrivacySensitivity.CRITICAL,
    "CREDIT_CARD": PrivacySensitivity.CRITICAL,
    "US_BANK_NUMBER": PrivacySensitivity.CRITICAL,
    "IBAN_CODE": PrivacySensitivity.CRITICAL,
    "CRYPTO": PrivacySensitivity.CRITICAL,  # Cryptocurrency addresses
    "US_ITIN": PrivacySensitivity.CRITICAL,
    "US_PASSPORT": PrivacySensitivity.CRITICAL,
    "AU_TFN": PrivacySensitivity.CRITICAL,  # Australian Tax File Number
    "IN_AADHAAR": PrivacySensitivity.CRITICAL,  # Indian Aadhaar
    "SG_NRIC_FIN": PrivacySensitivity.CRITICAL,  # Singapore NRIC

    # High - strong protection (epsilon ~0.5)
    "PHONE_NUMBER": PrivacySensitivity.HIGH,
    "EMAIL_ADDRESS": PrivacySensitivity.HIGH,
    "IP_ADDRESS": PrivacySensitivity.HIGH,
    "MEDICAL_LICENSE": PrivacySensitivity.HIGH,
    "US_DRIVER_LICENSE": PrivacySensitivity.HIGH,
    "UK_NHS": PrivacySensitivity.HIGH,  # UK National Health Service number
    "IN_PAN": PrivacySensitivity.HIGH,  # Indian PAN

    # Medium - moderate protection (epsilon ~1.0)
    "PERSON": PrivacySensitivity.MEDIUM,
    "LOCATION": PrivacySensitivity.MEDIUM,
    "NRP": PrivacySensitivity.MEDIUM,  # National registration number

    # Low - basic protection (epsilon ~2.0)
    "DATE_TIME": PrivacySensitivity.LOW,
    "URL": PrivacySensitivity.LOW,
    "DOMAIN_NAME": PrivacySensitivity.LOW,
}


def get_entity_sensitivity(entity_type: str) -> PrivacySensitivity:
    """Get sensitivity level for a PII entity type.

    Args:
        entity_type: Presidio entity type (e.g., "PERSON", "US_SSN")

    Returns:
        PrivacySensitivity level for the entity type.
        Defaults to MEDIUM for unknown types.
    """
    return ENTITY_SENSITIVITY_MAP.get(entity_type, PrivacySensitivity.MEDIUM)
