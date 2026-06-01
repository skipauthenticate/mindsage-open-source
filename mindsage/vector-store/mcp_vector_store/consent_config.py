"""
Consent Configuration for MindSage

Provides presets and configuration for the consent management system.
Users can control which data categories, PII types, documents, time ranges,
and entities are exposed to external LLMs.
"""

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set


class ConsentPreset(Enum):
    """Predefined consent configurations."""
    STRICT = "strict"
    BALANCED = "balanced"
    OPEN = "open"
    HEALTH_FOCUS = "health_focus"
    WORK_ONLY = "work_only"
    RECENT_ONLY = "recent_only"
    FAMILY_PROTECTED = "family_protected"


# Data categories that can be controlled
# Aligned with topic_labeler.py DEFAULT_TOPICS for consistent filtering
DATA_CATEGORIES = {
    "health",
    "finance",
    "work",
    "personal",
    "social",
    "legal",
    "travel",
    "education",
    "programming",
    "sports",
    "technology",
    "shopping",
    "medical",
    "family",
    "general",
}

# Default category settings (True = allowed by default)
DEFAULT_CATEGORY_ALLOWED = {
    "health": False,      # Blocked by default - sensitive
    "finance": False,     # Blocked by default - sensitive
    "work": True,         # Allowed by default
    "personal": False,    # Blocked by default - sensitive
    "social": False,      # Blocked by default - sensitive
    "legal": False,       # Blocked by default - sensitive
    "travel": False,      # Blocked by default - contains PII
    "education": True,    # Allowed by default
    "programming": True,  # Allowed by default
    "sports": True,       # Allowed by default
    "technology": True,   # Allowed by default
    "shopping": False,    # Blocked by default - contains purchase history
    "medical": False,     # Blocked by default - sensitive health data
    "family": False,      # Blocked by default - sensitive personal data
    "general": True,      # Allowed by default
}

# PII types that can NEVER be exposed (critical PII)
CRITICAL_PII_TYPES = {
    "US_SSN",
    "CREDIT_CARD",
    "US_BANK_NUMBER",
    "IBAN_CODE",
    "IN_AADHAAR",
    "AU_TFN",
    "CRYPTO",
}

# PII types with their default exposure setting and risk level
PII_TYPE_CONFIG = {
    # Low risk - often exposed
    "DATE_TIME": {"default_expose": True, "risk": "low"},
    "URL": {"default_expose": True, "risk": "low"},

    # Medium risk - anonymized by default
    "PERSON": {"default_expose": False, "risk": "medium"},
    "EMAIL_ADDRESS": {"default_expose": False, "risk": "medium"},
    "PHONE_NUMBER": {"default_expose": False, "risk": "medium"},
    "LOCATION": {"default_expose": False, "risk": "medium"},
    "IP_ADDRESS": {"default_expose": False, "risk": "medium"},

    # High risk - always anonymized (but not critical)
    "US_DRIVER_LICENSE": {"default_expose": False, "risk": "high"},
    "US_PASSPORT": {"default_expose": False, "risk": "high"},

    # Critical - NEVER exposed
    "US_SSN": {"default_expose": False, "risk": "critical"},
    "CREDIT_CARD": {"default_expose": False, "risk": "critical"},
    "US_BANK_NUMBER": {"default_expose": False, "risk": "critical"},
    "IBAN_CODE": {"default_expose": False, "risk": "critical"},
}

# Topic to category mapping
# Maps document topics to consent categories for filtering
TOPIC_TO_CATEGORY_MAP = {
    # Health (fitness, wellness)
    "health": "health",
    "wellness": "health",
    "fitness": "health",
    "nutrition": "health",
    "diet": "health",
    "exercise": "health",
    "gym": "health",
    "workout": "health",

    # Medical (clinical, doctors)
    "medical": "medical",
    "doctor": "medical",
    "prescription": "medical",
    "hospital": "medical",
    "healthcare": "medical",
    "diagnosis": "medical",
    "treatment": "medical",
    "medication": "medical",
    "clinic": "medical",

    # Finance
    "finance": "finance",
    "banking": "finance",
    "investment": "finance",
    "tax": "finance",
    "budget": "finance",
    "insurance": "finance",
    "crypto": "finance",
    "money": "finance",
    "payment": "finance",
    "salary": "finance",

    # Work
    "work": "work",
    "business": "work",
    "meeting": "work",
    "project": "work",
    "email": "work",
    "corporate": "work",
    "office": "work",
    "colleague": "work",
    "professional": "work",
    "boss": "work",
    "career": "work",
    "job": "work",

    # Personal
    "personal": "personal",
    "diary": "personal",
    "journal": "personal",
    "thoughts": "personal",
    "feelings": "personal",
    "private": "personal",
    "reflection": "personal",

    # Family
    "family": "family",
    "parents": "family",
    "children": "family",
    "siblings": "family",
    "relatives": "family",
    "grandparents": "family",
    "cousins": "family",
    "reunion": "family",

    # Social
    "social": "social",
    "message": "social",
    "chat": "social",
    "friend": "social",
    "party": "social",
    "networking": "social",
    "socializing": "social",

    # Legal
    "legal": "legal",
    "contract": "legal",
    "agreement": "legal",
    "court": "legal",
    "lawyer": "legal",
    "lawsuit": "legal",

    # Travel
    "travel": "travel",
    "flight": "travel",
    "hotel": "travel",
    "vacation": "travel",
    "trip": "travel",
    "booking": "travel",
    "destination": "travel",

    # Education
    "education": "education",
    "school": "education",
    "course": "education",
    "learning": "education",
    "university": "education",
    "study": "education",
    "college": "education",
    "teacher": "education",
    "student": "education",

    # Programming
    "programming": "programming",
    "code": "programming",
    "software": "programming",
    "coding": "programming",
    "developer": "programming",
    "algorithm": "programming",
    "python": "programming",
    "javascript": "programming",

    # Sports
    "sports": "sports",
    "game": "sports",
    "team": "sports",
    "athletics": "sports",
    "basketball": "sports",
    "football": "sports",
    "soccer": "sports",
    "tennis": "sports",

    # Technology
    "technology": "technology",
    "tech": "technology",
    "gadget": "technology",
    "device": "technology",
    "smartphone": "technology",
    "laptop": "technology",
    "computer": "technology",
    "hardware": "technology",

    # Shopping
    "shopping": "shopping",
    "purchase": "shopping",
    "store": "shopping",
    "mall": "shopping",
    "buy": "shopping",
    "order": "shopping",
    "sale": "shopping",
}


@dataclass
class PresetConfig:
    """Configuration for a consent preset."""
    name: str
    description: str
    allowed_categories: Set[str]
    blocked_categories: Set[str]
    exposed_pii_types: Set[str]
    time_rules: Optional[Dict] = None
    entity_rules: Optional[Dict] = None


# Preset configurations
CONSENT_PRESETS: Dict[str, PresetConfig] = {
    "strict": PresetConfig(
        name="strict",
        description="Maximum privacy - all categories blocked, all PII anonymized",
        allowed_categories=set(),
        blocked_categories=DATA_CATEGORIES.copy(),
        exposed_pii_types=set(),
        entity_rules={"default_protect": True},
    ),
    "balanced": PresetConfig(
        name="balanced",
        description="Balanced - work/general allowed, sensitive PII anonymized",
        allowed_categories={"work", "general", "education", "programming", "sports", "technology"},
        blocked_categories={"health", "finance", "personal", "social", "legal", "shopping", "medical", "family"},
        exposed_pii_types={"DATE_TIME", "URL", "LOCATION"},
        entity_rules={"default_protect": True, "expose_relationships": ["self"]},
    ),
    "open": PresetConfig(
        name="open",
        description="Open - most data allowed, only critical PII anonymized",
        allowed_categories=DATA_CATEGORIES.copy(),  # All categories
        blocked_categories=set(),
        exposed_pii_types={"PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "LOCATION", "DATE_TIME", "URL"},
        entity_rules={"default_protect": False},
    ),
    "health_focus": PresetConfig(
        name="health_focus",
        description="Health access - health and medical data allowed, finances blocked",
        allowed_categories={"health", "medical", "personal", "family", "general"},
        blocked_categories={"finance", "legal", "shopping"},
        exposed_pii_types={"DATE_TIME"},
        entity_rules={"protect_relationships": ["family"], "expose_relationships": ["self"]},
    ),
    "work_only": PresetConfig(
        name="work_only",
        description="Work focus - only work-related data",
        allowed_categories={"work", "education", "programming", "technology"},
        blocked_categories={"health", "finance", "personal", "social", "legal", "travel", "sports", "shopping", "medical", "family"},
        exposed_pii_types={"PERSON", "DATE_TIME", "URL"},
        entity_rules={"expose_relationships": ["self", "colleagues"]},
    ),
    "recent_only": PresetConfig(
        name="recent_only",
        description="Recent data only - last 3 months",
        allowed_categories=DATA_CATEGORIES.copy(),
        blocked_categories=set(),
        exposed_pii_types={"DATE_TIME"},
        time_rules={"relative": "-3m"},
        entity_rules={"default_protect": True},
    ),
    "family_protected": PresetConfig(
        name="family_protected",
        description="Expose self, protect family members and family data",
        allowed_categories=DATA_CATEGORIES - {"family"},  # All except family
        blocked_categories={"family"},
        exposed_pii_types={"PERSON", "DATE_TIME"},
        entity_rules={
            "protect_relationships": ["spouse", "children", "parents", "siblings", "family"],
            "expose_relationships": ["self"],
            "default_protect": False,
        },
    ),
}


def get_default_consent_config() -> Dict:
    """Get the default consent configuration (balanced preset)."""
    preset = CONSENT_PRESETS["balanced"]
    return {
        "allowed_categories": list(preset.allowed_categories),
        "blocked_categories": list(preset.blocked_categories),
        "exposed_pii_types": list(preset.exposed_pii_types),
        "time_rules": preset.time_rules,
        "entity_rules": preset.entity_rules,
    }


def get_preset_config(preset_name: str) -> Optional[PresetConfig]:
    """Get configuration for a specific preset."""
    return CONSENT_PRESETS.get(preset_name)


def validate_pii_exposure(exposed_types: Set[str]) -> Set[str]:
    """
    Remove critical PII types from exposure list.
    Critical PII can NEVER be exposed regardless of user settings.
    """
    return exposed_types - CRITICAL_PII_TYPES


def get_categories_for_topics(topics: List[str]) -> Set[str]:
    """Map document topics to consent categories."""
    categories = set()
    for topic in topics:
        topic_lower = topic.lower()
        # Check exact match first
        if topic_lower in TOPIC_TO_CATEGORY_MAP:
            categories.add(TOPIC_TO_CATEGORY_MAP[topic_lower])
        else:
            # Check if any keyword is contained in the topic
            for keyword, category in TOPIC_TO_CATEGORY_MAP.items():
                if keyword in topic_lower:
                    categories.add(category)
                    break

    # Default to "general" if no category matched
    if not categories:
        categories.add("general")

    return categories


def is_category_allowed(
    category: str,
    allowed_categories: Set[str],
    blocked_categories: Set[str]
) -> bool:
    """
    Check if a category is allowed based on consent rules.

    Rules:
    1. If blocked_categories contains the category, it's blocked
    2. If allowed_categories is empty, everything not blocked is allowed
    3. If allowed_categories contains "*", everything not blocked is allowed
    4. Otherwise, category must be in allowed_categories
    """
    # Explicit blocks always win
    if category in blocked_categories:
        return False

    # Empty allowed = all allowed (except blocked)
    if not allowed_categories:
        return True

    # Wildcard = all allowed (except blocked)
    if "*" in allowed_categories:
        return True

    # Must be in allowed list
    return category in allowed_categories


def is_pii_type_exposed(
    pii_type: str,
    exposed_pii_types: Set[str]
) -> bool:
    """
    Check if a PII type should be exposed (not anonymized).

    Critical PII types are NEVER exposed regardless of settings.
    """
    # Critical PII is never exposed
    if pii_type in CRITICAL_PII_TYPES:
        return False

    return pii_type in exposed_pii_types


# Environment variable overrides
def get_consent_env_config() -> Dict:
    """Get consent configuration from environment variables."""
    config = {}

    # Default preset
    default_preset = os.environ.get("CONSENT_DEFAULT_PRESET", "balanced")
    if default_preset in CONSENT_PRESETS:
        config["default_preset"] = default_preset

    # Session TTL (in seconds)
    ttl = os.environ.get("CONSENT_SESSION_TTL")
    if ttl:
        try:
            config["session_ttl"] = int(ttl)
        except ValueError:
            pass

    # Max sessions
    max_sessions = os.environ.get("CONSENT_MAX_SESSIONS")
    if max_sessions:
        try:
            config["max_sessions"] = int(max_sessions)
        except ValueError:
            pass

    return config
