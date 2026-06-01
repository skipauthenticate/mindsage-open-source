"""
Consent Manager for MindSage

Orchestrates consent-based filtering across all 5 dimensions:
1. Category Filter - by document topics
2. Document Filter - by ID/source blocklist
3. Time Filter - by document timestamp
4. Entity Filter - per-person protection
5. PII Anonymization - per PII type rules

"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

from .consent_config import (
    CRITICAL_PII_TYPES,
    get_categories_for_topics,
    is_category_allowed,
    is_pii_type_exposed,
)
from .consent_session import (
    EntityDefinition,
    Session,
    SessionManager,
    get_session_manager,
)

logger = logging.getLogger(__name__)


@dataclass
class ConsentFilterStats:
    """Statistics about consent filtering applied."""
    documents_input: int = 0
    documents_filtered_by_category: int = 0
    documents_filtered_by_id: int = 0
    documents_filtered_by_time: int = 0
    documents_output: int = 0
    categories_allowed: List[str] = None
    documents_blocked: List[int] = None
    time_range_applied: Optional[Dict] = None

    def __post_init__(self):
        if self.categories_allowed is None:
            self.categories_allowed = []
        if self.documents_blocked is None:
            self.documents_blocked = []


@dataclass
class PIIFilterStats:
    """Statistics about PII anonymization applied."""
    entities_protected: List[str] = None
    entities_exposed: List[str] = None
    entity_anonymizations: int = 0
    pii_types_exposed: List[str] = None
    pii_types_anonymized: List[str] = None
    total_pii_anonymized: int = 0
    total_pii_exposed: int = 0

    def __post_init__(self):
        if self.entities_protected is None:
            self.entities_protected = []
        if self.entities_exposed is None:
            self.entities_exposed = []
        if self.pii_types_exposed is None:
            self.pii_types_exposed = []
        if self.pii_types_anonymized is None:
            self.pii_types_anonymized = []


class ConsentManager:
    """
    Manages consent-based filtering and PII protection.

    Applies all 5 dimensions of consent:
    1. Category - filter documents by topic category
    2. Document - block/allow specific documents
    3. Time - filter by document timestamp
    4. Entity - protect/expose specific people
    5. PII Type - control which PII types are anonymized
    """

    def __init__(self, session_manager: Optional[SessionManager] = None):
        self._session_manager = session_manager or get_session_manager()

    def get_or_create_session(
        self,
        session_id: Optional[str] = None,
        preset: Optional[str] = None,
    ) -> Session:
        """Get existing session or create new one."""
        return self._session_manager.get_or_create_session(
            session_id=session_id,
            preset=preset,
        )

    def get_session(self, session_id: str) -> Optional[Session]:
        """Get session by ID."""
        return self._session_manager.get_session(session_id)

    def filter_documents(
        self,
        documents: List[Dict[str, Any]],
        session: Session,
    ) -> Tuple[List[Dict[str, Any]], ConsentFilterStats]:
        """
        Apply consent filters to documents.

        Filter order:
        1. Category filter (by topics)
        2. Document filter (by ID/source)
        3. Time filter (by timestamp)

        Returns filtered documents and statistics.
        """
        stats = ConsentFilterStats(documents_input=len(documents))
        stats.categories_allowed = list(session.allowed_categories)

        filtered = documents

        # 1. Category filter
        filtered, cat_filtered = self._filter_by_category(filtered, session)
        stats.documents_filtered_by_category = cat_filtered

        # 2. Document filter
        filtered, doc_filtered, blocked_ids = self._filter_by_document(filtered, session)
        stats.documents_filtered_by_id = doc_filtered
        stats.documents_blocked = blocked_ids

        # 3. Time filter
        filtered, time_filtered, time_range = self._filter_by_time(filtered, session)
        stats.documents_filtered_by_time = time_filtered
        stats.time_range_applied = time_range

        stats.documents_output = len(filtered)
        return filtered, stats

    def _filter_by_category(
        self,
        documents: List[Dict[str, Any]],
        session: Session,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Filter documents by category consent."""
        if not session.allowed_categories and not session.blocked_categories:
            # No category rules - allow all
            return documents, 0

        filtered = []
        removed = 0

        for doc in documents:
            # Get document topics and map to categories
            topics = doc.get("topics", []) or doc.get("metadata", {}).get("topics", [])
            if not topics:
                # No topics - treat as "general"
                categories = {"general"}
            else:
                categories = get_categories_for_topics(topics)

            # Check if ALL categories are allowed
            # (document must have all its categories allowed)
            all_allowed = all(
                is_category_allowed(
                    cat,
                    session.allowed_categories,
                    session.blocked_categories,
                )
                for cat in categories
            )

            if all_allowed:
                filtered.append(doc)
            else:
                removed += 1

        return filtered, removed

    def _filter_by_document(
        self,
        documents: List[Dict[str, Any]],
        session: Session,
    ) -> Tuple[List[Dict[str, Any]], int, List[int]]:
        """Filter documents by document ID/source rules."""
        rules = session.document_rules
        blocked_ids = []

        # If allowlist mode (allowed_ids is non-empty), only allow those
        if rules.allowed_ids:
            filtered = [
                doc for doc in documents
                if doc.get("id") in rules.allowed_ids
            ]
            removed = len(documents) - len(filtered)
            return filtered, removed, []

        # Otherwise, apply blocklist
        filtered = []
        removed = 0

        for doc in documents:
            doc_id = doc.get("id")
            doc_source = doc.get("source") or doc.get("metadata", {}).get("source")

            # Check blocklist
            if doc_id in rules.blocked_ids:
                removed += 1
                blocked_ids.append(doc_id)
                continue

            # Check source blocklist
            if doc_source and rules.blocked_sources:
                if doc_source in rules.blocked_sources:
                    removed += 1
                    continue

            # Check source allowlist (if set)
            if rules.allowed_sources and doc_source:
                if doc_source not in rules.allowed_sources:
                    removed += 1
                    continue

            filtered.append(doc)

        return filtered, removed, blocked_ids

    def _filter_by_time(
        self,
        documents: List[Dict[str, Any]],
        session: Session,
    ) -> Tuple[List[Dict[str, Any]], int, Optional[Dict]]:
        """Filter documents by time rules."""
        time_rules = session.time_rules
        after, before = time_rules.get_effective_range()

        if after is None and before is None:
            return documents, 0, None

        time_range = {}
        if after:
            time_range["from"] = after.isoformat()
        if before:
            time_range["to"] = before.isoformat()

        filtered = []
        removed = 0
        date_field = time_rules.date_field

        for doc in documents:
            # Get document timestamp
            doc_date = None
            if date_field in doc:
                doc_date = doc[date_field]
            elif "metadata" in doc and date_field in doc["metadata"]:
                doc_date = doc["metadata"][date_field]

            # Parse date if string
            if isinstance(doc_date, str):
                try:
                    doc_date = datetime.fromisoformat(doc_date.replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    doc_date = None

            # If no date, include by default (can't filter)
            if doc_date is None:
                filtered.append(doc)
                continue

            # Make naive if comparing with naive datetime
            if doc_date.tzinfo is not None:
                doc_date = doc_date.replace(tzinfo=None)

            # Check range
            if after and doc_date < after:
                removed += 1
                continue
            if before and doc_date > before:
                removed += 1
                continue

            filtered.append(doc)

        return filtered, removed, time_range if time_range else None

    def should_anonymize_pii(
        self,
        pii_type: str,
        pii_value: str,
        session: Session,
    ) -> Tuple[bool, str]:
        """
        Check if a PII value should be anonymized based on consent rules.

        Returns (should_anonymize, reason).

        Priority:
        1. Critical PII - always anonymize
        2. Entity-specific rules - protect/expose specific entities
        3. PII type rules - per-type exposure settings
        """
        # 1. Critical PII is always anonymized
        if pii_type in CRITICAL_PII_TYPES:
            return True, "critical_pii"

        # 2. Check entity-specific rules (for PERSON type)
        if pii_type == "PERSON":
            entity_result = self._check_entity_rules(pii_value, session)
            if entity_result is not None:
                return entity_result

        # 3. Check PII type exposure rules
        if is_pii_type_exposed(pii_type, session.exposed_pii_types):
            return False, "pii_type_exposed"

        return True, "pii_type_anonymized"

    def _check_entity_rules(
        self,
        name: str,
        session: Session,
    ) -> Optional[Tuple[bool, str]]:
        """
        Check entity-specific rules for a name.

        Returns (should_anonymize, reason) or None if no specific rule matches.
        """
        name_lower = name.lower()
        entity_rules = session.entity_rules

        # Check explicit protect list
        for entity in entity_rules.protect_entities:
            if self._entity_matches(name_lower, entity):
                return True, f"entity_protected:{entity.name}"

        # Check explicit expose list
        for entity in entity_rules.expose_entities:
            if self._entity_matches(name_lower, entity):
                return False, f"entity_exposed:{entity.name}"

        # Check relationship-based rules
        # (Would need entity registry to resolve relationships)
        # For now, fall through to PII type rules

        return None  # No specific entity rule

    def _entity_matches(self, name_lower: str, entity: EntityDefinition) -> bool:
        """Check if a name matches an entity definition."""
        # Exact match on name
        if name_lower == entity.name.lower():
            return True

        # Check aliases
        for alias in entity.aliases:
            if name_lower == alias.lower():
                return True

        # Partial match (name contains entity name)
        if entity.name.lower() in name_lower:
            return True
        if name_lower in entity.name.lower():
            return True

        return False

    def get_pii_filter_stats(
        self,
        session: Session,
        pii_results: List[Dict[str, Any]],
    ) -> PIIFilterStats:
        """Generate PII filter statistics from anonymization results."""
        stats = PIIFilterStats()

        # Get protected/exposed entity names
        stats.entities_protected = [e.name for e in session.entity_rules.protect_entities]
        stats.entities_exposed = [e.name for e in session.entity_rules.expose_entities]

        # Get PII type settings
        stats.pii_types_exposed = list(session.exposed_pii_types)

        # Count from results
        anonymized_types = set()
        for result in pii_results:
            if result.get("anonymized", True):
                stats.total_pii_anonymized += 1
                anonymized_types.add(result.get("pii_type", "UNKNOWN"))
            else:
                stats.total_pii_exposed += 1

        stats.pii_types_anonymized = list(anonymized_types)
        stats.entity_anonymizations = sum(
            1 for r in pii_results
            if r.get("pii_type") == "PERSON" and r.get("anonymized", True)
        )

        return stats


# Global consent manager instance
_consent_manager: Optional[ConsentManager] = None


def get_consent_manager() -> ConsentManager:
    """Get the global consent manager instance."""
    global _consent_manager

    if _consent_manager is None:
        _consent_manager = ConsentManager()
    return _consent_manager


def reset_consent_manager() -> None:
    """Reset the global consent manager (for testing)."""
    global _consent_manager
    _consent_manager = None
