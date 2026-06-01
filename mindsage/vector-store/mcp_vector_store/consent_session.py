"""
Unified Session Management for MindSage Consent System

Combines consent rules with PII token mappings in a single session.
Sessions are ephemeral (in-memory only) with sliding TTL.
"""

import secrets
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Tuple

from .consent_config import (
    CRITICAL_PII_TYPES,
    get_default_consent_config,
    get_preset_config,
    validate_pii_exposure,
)


@dataclass
class PIIToken:
    """Individual PII token mapping."""
    token_id: str
    pii_type: str
    original_value: str
    perturbed_value: Optional[str] = None  # Set for LPRAG hybrid mode
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class DocumentRules:
    """Per-document consent rules."""
    blocked_ids: Set[int] = field(default_factory=set)
    allowed_ids: Set[int] = field(default_factory=set)
    priority_ids: Set[int] = field(default_factory=set)
    blocked_sources: Set[str] = field(default_factory=set)
    allowed_sources: Set[str] = field(default_factory=set)


@dataclass
class TimeRules:
    """Time-based consent rules."""
    after: Optional[datetime] = None
    before: Optional[datetime] = None
    relative: Optional[str] = None  # e.g., "-6m", "-30d", "-1y"
    date_field: str = "created_at"
    include_ranges: List[Tuple[datetime, datetime]] = field(default_factory=list)
    exclude_ranges: List[Tuple[datetime, datetime]] = field(default_factory=list)

    def get_effective_range(self) -> Tuple[Optional[datetime], Optional[datetime]]:
        """Calculate effective date range including relative time."""
        after = self.after
        before = self.before

        if self.relative:
            now = datetime.now()
            after = self._parse_relative_time(self.relative, now)

        return after, before

    def _parse_relative_time(self, relative: str, now: datetime) -> Optional[datetime]:
        """Parse relative time string like '-6m', '-30d', '-1y'."""
        if not relative or len(relative) < 2:
            return None

        try:
            sign = relative[0]
            value = int(relative[1:-1])
            unit = relative[-1].lower()

            if sign == '-':
                if unit == 'd':
                    return now - timedelta(days=value)
                elif unit == 'm':
                    return now - timedelta(days=value * 30)  # Approximate
                elif unit == 'y':
                    return now - timedelta(days=value * 365)  # Approximate
        except (ValueError, IndexError):
            pass

        return None


@dataclass
class EntityDefinition:
    """Definition of a known entity for consent purposes."""
    name: str
    aliases: Set[str] = field(default_factory=set)
    pii_values: Dict[str, str] = field(default_factory=dict)
    relationship: Optional[str] = None
    entity_type: str = "PERSON"


@dataclass
class EntityRules:
    """Entity-specific consent rules."""
    protect_entities: List[EntityDefinition] = field(default_factory=list)
    expose_entities: List[EntityDefinition] = field(default_factory=list)
    protect_relationships: Set[str] = field(default_factory=set)
    expose_relationships: Set[str] = field(default_factory=set)
    default_protect: bool = True


class PIIMappings:
    """PII token and perturbed value mappings for de-anonymization."""

    def __init__(self):
        # Token-based mappings (traditional: <PII:TYPE:token_id>)
        self._tokens: Dict[str, PIIToken] = {}
        self._value_to_token: Dict[Tuple[str, str], str] = {}  # (type, original_lower) → token_id

        # LPRAG perturbed value mappings (for hybrid mode)
        self._perturbed_to_token: Dict[str, str] = {}  # perturbed_value_lower → token_id

    def add_token(self, token: PIIToken) -> None:
        """Add a token with optional perturbed value mapping."""
        self._tokens[token.token_id] = token
        key = (token.pii_type, token.original_value.lower())
        self._value_to_token[key] = token.token_id

        if token.perturbed_value:
            self._perturbed_to_token[token.perturbed_value.lower()] = token.token_id

    def get_token(self, token_id: str) -> Optional[PIIToken]:
        """Get token by ID."""
        return self._tokens.get(token_id)

    def get_token_for_value(self, pii_type: str, original_value: str) -> Optional[PIIToken]:
        """Get existing token for a PII value (for deduplication)."""
        key = (pii_type, original_value.lower())
        token_id = self._value_to_token.get(key)
        return self._tokens.get(token_id) if token_id else None

    def get_original(self, token_id: str) -> Optional[str]:
        """Get original value for a token ID."""
        token = self._tokens.get(token_id)
        return token.original_value if token else None

    def get_original_for_perturbed(self, perturbed: str) -> Optional[str]:
        """Get original value for a perturbed value (LPRAG)."""
        token_id = self._perturbed_to_token.get(perturbed.lower())
        return self.get_original(token_id) if token_id else None

    def get_all_perturbed_mappings(self) -> Dict[str, str]:
        """Get all perturbed → original mappings for de-anonymization."""
        result = {}
        for perturbed_lower, token_id in self._perturbed_to_token.items():
            token = self._tokens.get(token_id)
            if token and token.perturbed_value:
                # Use original case of perturbed value
                result[token.perturbed_value] = token.original_value
        return result

    @property
    def token_count(self) -> int:
        return len(self._tokens)

    @property
    def perturbed_count(self) -> int:
        return len(self._perturbed_to_token)

    def get_types_seen(self) -> Set[str]:
        """Get all PII types that have been tokenized."""
        return {token.pii_type for token in self._tokens.values()}


class Session:
    """
    Unified session containing consent rules + PII token mappings.

    Single session ID for both consent and de-anonymization.
    """

    def __init__(
        self,
        session_id: Optional[str] = None,
        ttl_seconds: int = 3600,  # 1 hour default
    ):
        self.session_id = session_id or self._generate_session_id()
        self.created_at = datetime.now()
        self.last_accessed = self.created_at
        self._ttl_seconds = ttl_seconds

        # === CONSENT RULES (5 Dimensions) ===
        self.allowed_categories: Set[str] = set()
        self.blocked_categories: Set[str] = set()
        self.exposed_pii_types: Set[str] = set()
        self.document_rules = DocumentRules()
        self.time_rules = TimeRules()
        self.entity_rules = EntityRules()

        # === PII MAPPINGS ===
        self.pii_mappings = PIIMappings()

        # === METADATA ===
        self.consent_source: str = "api"  # "ui", "natural_language", "api"
        self.consent_expression: Optional[str] = None
        self.preset_applied: Optional[str] = None

        # Apply default consent config
        self._apply_default_config()

    def _generate_session_id(self) -> str:
        """Generate a unique session ID."""
        return f"sess_{secrets.token_urlsafe(16)}"

    def _apply_default_config(self):
        """Apply default consent configuration."""
        config = get_default_consent_config()
        self.allowed_categories = set(config.get("allowed_categories", []))
        self.blocked_categories = set(config.get("blocked_categories", []))
        self.exposed_pii_types = validate_pii_exposure(
            set(config.get("exposed_pii_types", []))
        )

        entity_rules = config.get("entity_rules", {})
        if entity_rules:
            self.entity_rules.default_protect = entity_rules.get("default_protect", True)
            self.entity_rules.expose_relationships = set(
                entity_rules.get("expose_relationships", [])
            )

    @property
    def expires_at(self) -> datetime:
        """Calculate expiration time based on last access + TTL."""
        return self.last_accessed + timedelta(seconds=self._ttl_seconds)

    @property
    def is_expired(self) -> bool:
        """Check if session has expired."""
        return datetime.now() > self.expires_at

    @property
    def ttl_remaining_seconds(self) -> int:
        """Get remaining TTL in seconds."""
        remaining = (self.expires_at - datetime.now()).total_seconds()
        return max(0, int(remaining))

    def touch(self) -> None:
        """Update last accessed time (refresh TTL)."""
        self.last_accessed = datetime.now()

    def apply_preset(self, preset_name: str) -> bool:
        """Apply a consent preset configuration."""
        preset = get_preset_config(preset_name)
        if not preset:
            return False

        self.allowed_categories = preset.allowed_categories.copy()
        self.blocked_categories = preset.blocked_categories.copy()
        self.exposed_pii_types = validate_pii_exposure(preset.exposed_pii_types.copy())

        if preset.time_rules:
            self.time_rules.relative = preset.time_rules.get("relative")

        if preset.entity_rules:
            self.entity_rules.default_protect = preset.entity_rules.get("default_protect", True)
            self.entity_rules.protect_relationships = set(
                preset.entity_rules.get("protect_relationships", [])
            )
            self.entity_rules.expose_relationships = set(
                preset.entity_rules.get("expose_relationships", [])
            )

        self.preset_applied = preset_name
        self.touch()
        return True

    def update_categories(
        self,
        allowed: Optional[Set[str]] = None,
        blocked: Optional[Set[str]] = None,
        add_allowed: Optional[Set[str]] = None,
        remove_allowed: Optional[Set[str]] = None,
        add_blocked: Optional[Set[str]] = None,
        remove_blocked: Optional[Set[str]] = None,
    ) -> None:
        """Update category consent rules.

        Args:
            allowed: Set allowed categories (replaces existing)
            blocked: Set blocked categories (replaces existing)
            add_allowed: Add to allowed categories
            remove_allowed: Remove from allowed categories
            add_blocked: Add to blocked categories
            remove_blocked: Remove from blocked categories
        """
        # Replace if provided
        if allowed is not None:
            self.allowed_categories = allowed
        if blocked is not None:
            self.blocked_categories = blocked

        # Incremental updates
        if add_allowed:
            self.allowed_categories.update(add_allowed)
        if remove_allowed:
            self.allowed_categories -= remove_allowed
        if add_blocked:
            self.blocked_categories.update(add_blocked)
        if remove_blocked:
            self.blocked_categories -= remove_blocked
        self.touch()

    def update_pii_types(
        self,
        exposed: Optional[Set[str]] = None,
        add_exposed: Optional[Set[str]] = None,
        remove_exposed: Optional[Set[str]] = None,
    ) -> None:
        """Update PII type exposure rules.

        Args:
            exposed: Set exposed PII types (replaces existing)
            add_exposed: Add to exposed PII types
            remove_exposed: Remove from exposed PII types
        """
        # Replace if provided
        if exposed is not None:
            safe_expose = validate_pii_exposure(exposed)
            self.exposed_pii_types = safe_expose

        # Incremental updates
        if add_exposed:
            safe_expose = validate_pii_exposure(add_exposed)
            self.exposed_pii_types.update(safe_expose)
        if remove_exposed:
            self.exposed_pii_types -= remove_exposed
        self.touch()

    def block_document(self, doc_id: int) -> None:
        """Add document to blocklist."""
        self.document_rules.blocked_ids.add(doc_id)
        self.document_rules.allowed_ids.discard(doc_id)
        self.touch()

    def unblock_document(self, doc_id: int) -> None:
        """Remove document from blocklist."""
        self.document_rules.blocked_ids.discard(doc_id)
        self.touch()

    def set_time_rules(
        self,
        relative: Optional[str] = None,
        after: Optional[datetime] = None,
        before: Optional[datetime] = None,
    ) -> None:
        """Set time-based consent rules."""
        if relative:
            self.time_rules.relative = relative
        if after:
            self.time_rules.after = after
        if before:
            self.time_rules.before = before
        self.touch()

    def clear_time_rules(self) -> None:
        """Clear all time-based rules."""
        self.time_rules = TimeRules()
        self.touch()

    def protect_entity(
        self,
        name: str,
        aliases: Optional[List[str]] = None,
        relationship: Optional[str] = None,
    ) -> None:
        """Add entity to protection list.

        Args:
            name: Entity name (e.g., "John Smith")
            aliases: Optional list of aliases (e.g., ["Johnny", "JS"])
            relationship: Optional relationship type (e.g., "family", "colleague")
        """
        entity = EntityDefinition(
            name=name,
            aliases=set(aliases) if aliases else set(),
            relationship=relationship,
        )
        # Remove from expose list if present
        self.entity_rules.expose_entities = [
            e for e in self.entity_rules.expose_entities
            if e.name.lower() != entity.name.lower()
        ]
        # Add to protect list
        self.entity_rules.protect_entities.append(entity)
        self.touch()

    def expose_entity(
        self,
        name: str,
        aliases: Optional[List[str]] = None,
        relationship: Optional[str] = None,
    ) -> None:
        """Add entity to exposure list.

        Args:
            name: Entity name (e.g., "Self")
            aliases: Optional list of aliases
            relationship: Optional relationship type (e.g., "self")
        """
        entity = EntityDefinition(
            name=name,
            aliases=set(aliases) if aliases else set(),
            relationship=relationship,
        )
        # Remove from protect list if present
        self.entity_rules.protect_entities = [
            e for e in self.entity_rules.protect_entities
            if e.name.lower() != entity.name.lower()
        ]
        # Add to expose list
        self.entity_rules.expose_entities.append(entity)
        self.touch()

    def to_dict(self) -> Dict:
        """Serialize session to dictionary."""
        return {
            "session_id": self.session_id,
            "created_at": self.created_at.isoformat(),
            "last_accessed": self.last_accessed.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "ttl_remaining_seconds": self.ttl_remaining_seconds,
            "is_expired": self.is_expired,
            "consent": {
                "allowed_categories": list(self.allowed_categories),
                "blocked_categories": list(self.blocked_categories),
                "exposed_pii_types": list(self.exposed_pii_types),
                "document_rules": {
                    "blocked_ids": list(self.document_rules.blocked_ids),
                    "allowed_ids": list(self.document_rules.allowed_ids),
                    "priority_ids": list(self.document_rules.priority_ids),
                },
                "time_rules": {
                    "relative": self.time_rules.relative,
                    "after": self.time_rules.after.isoformat() if self.time_rules.after else None,
                    "before": self.time_rules.before.isoformat() if self.time_rules.before else None,
                },
                "entity_rules": {
                    "protect_entities": [e.name for e in self.entity_rules.protect_entities],
                    "expose_entities": [e.name for e in self.entity_rules.expose_entities],
                    "protect_relationships": list(self.entity_rules.protect_relationships),
                    "expose_relationships": list(self.entity_rules.expose_relationships),
                    "default_protect": self.entity_rules.default_protect,
                },
            },
            "pii_mappings": {
                "token_count": self.pii_mappings.token_count,
                "perturbed_count": self.pii_mappings.perturbed_count,
                "types_seen": list(self.pii_mappings.get_types_seen()),
            },
            "metadata": {
                "consent_source": self.consent_source,
                "consent_expression": self.consent_expression,
                "preset_applied": self.preset_applied,
            },
        }


class SessionManager:
    """
    Manages consent sessions with LRU eviction and TTL expiration.

    Thread-safe session storage.
    """

    def __init__(
        self,
        max_sessions: int = 100,
        session_ttl_seconds: int = 3600,  # 1 hour
    ):
        self._sessions: Dict[str, Session] = {}
        self._access_order: List[str] = []  # For LRU eviction
        self._lock = threading.RLock()
        self._max_sessions = max_sessions
        self._session_ttl_seconds = session_ttl_seconds
        self._total_sessions_created = 0

    def create_session(
        self,
        session_id: Optional[str] = None,
        preset: Optional[str] = None,
    ) -> Session:
        """Create a new session."""
        with self._lock:
            # Clean up expired sessions first
            self._cleanup_expired()

            # Evict oldest if at capacity
            while len(self._sessions) >= self._max_sessions:
                self._evict_oldest()

            session = Session(
                session_id=session_id,
                ttl_seconds=self._session_ttl_seconds,
            )

            if preset:
                session.apply_preset(preset)

            self._sessions[session.session_id] = session
            self._access_order.append(session.session_id)
            self._total_sessions_created += 1

            return session

    def get_session(self, session_id: str) -> Optional[Session]:
        """Get a session by ID, refreshing TTL."""
        with self._lock:
            session = self._sessions.get(session_id)

            if session is None:
                return None

            if session.is_expired:
                self._remove_session(session_id)
                return None

            # Refresh TTL and update access order
            session.touch()
            self._update_access_order(session_id)

            return session

    def get_or_create_session(
        self,
        session_id: Optional[str] = None,
        preset: Optional[str] = None,
    ) -> Session:
        """Get existing session or create new one."""
        if session_id:
            session = self.get_session(session_id)
            if session:
                return session

        return self.create_session(session_id=session_id, preset=preset)

    def delete_session(self, session_id: str) -> bool:
        """Delete a session."""
        with self._lock:
            if session_id in self._sessions:
                self._remove_session(session_id)
                return True
            return False

    def refresh_session(self, session_id: str) -> Optional[Session]:
        """Refresh session TTL without modifying consent."""
        return self.get_session(session_id)  # get_session already refreshes

    def get_session_count(self) -> int:
        """Get number of active sessions."""
        with self._lock:
            self._cleanup_expired()
            return len(self._sessions)

    def get_stats(self) -> Dict:
        """Get session manager statistics."""
        with self._lock:
            self._cleanup_expired()
            return {
                "active_sessions": len(self._sessions),
                "total_sessions_created": self._total_sessions_created,
                "max_sessions": self._max_sessions,
                "session_ttl_seconds": self._session_ttl_seconds,
            }

    def _remove_session(self, session_id: str) -> None:
        """Remove a session (internal, must hold lock)."""
        self._sessions.pop(session_id, None)
        if session_id in self._access_order:
            self._access_order.remove(session_id)

    def _update_access_order(self, session_id: str) -> None:
        """Update access order for LRU (internal, must hold lock)."""
        if session_id in self._access_order:
            self._access_order.remove(session_id)
        self._access_order.append(session_id)

    def _evict_oldest(self) -> None:
        """Evict the oldest session (internal, must hold lock)."""
        if self._access_order:
            oldest_id = self._access_order[0]
            self._remove_session(oldest_id)

    def _cleanup_expired(self) -> None:
        """Remove all expired sessions (internal, must hold lock)."""
        expired = [
            sid for sid, session in self._sessions.items()
            if session.is_expired
        ]
        for sid in expired:
            self._remove_session(sid)


# Global session manager instance
_session_manager: Optional[SessionManager] = None
_manager_lock = threading.Lock()


def get_session_manager() -> SessionManager:
    """Get the global session manager instance."""
    global _session_manager

    with _manager_lock:
        if _session_manager is None:
            _session_manager = SessionManager()
        return _session_manager


def reset_session_manager() -> None:
    """Reset the global session manager (for testing)."""
    global _session_manager

    with _manager_lock:
        _session_manager = None
