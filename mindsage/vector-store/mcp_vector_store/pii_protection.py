"""PII detection and anonymization using Microsoft Presidio.

Provides on-device PII protection for MCP search results before
sending to external LLMs, with reversible tokenization for
de-anonymization of LLM responses.

Supports two anonymization modes:
1. Token-based (default): PII replaced with tokens like <PII:PERSON:abc123>
2. LPRAG (optional): PII perturbed to semantically similar values using
   differential privacy, providing mathematical privacy guarantees.

Memory footprint: ~150-200MB with en_core_web_sm (+50MB if LPRAG enabled)

Configuration:
    PII_ENTITIES: Comma-separated list of entity types to detect, or a preset name.
                  Presets: "minimal", "default", "strict"
                  Example: PII_ENTITIES=PERSON,EMAIL_ADDRESS,PHONE_NUMBER
                  Default: All supported Presidio entity types (strict)

    LPRAG_MODE: Operating mode for LPRAG - "disabled", "pure", "hybrid"
                See lprag_config.py for details.
"""

import os
import secrets
import re
import threading
import hashlib
import time
from typing import Dict, List, Optional, Tuple, Set, Any, TYPE_CHECKING
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

# Type checking imports for consent integration
if TYPE_CHECKING:
    from .consent_session import Session as ConsentSession
    from .consent_manager import ConsentManager

# Presidio imports - optional, graceful degradation if not installed
try:
    from presidio_analyzer import AnalyzerEngine, RecognizerResult, Pattern, PatternRecognizer
    from presidio_analyzer.nlp_engine import NlpEngineProvider
    from presidio_anonymizer import AnonymizerEngine
    PRESIDIO_AVAILABLE = True
except ImportError:
    PRESIDIO_AVAILABLE = False
    AnalyzerEngine = None
    RecognizerResult = None
    NlpEngineProvider = None
    AnonymizerEngine = None
    Pattern = None
    PatternRecognizer = None

# LPRAG imports - optional, graceful degradation if not installed
try:
    from .lprag_config import LPRAGConfig, LPRAGMode, get_lprag_config_from_env
    from .lprag_engine import LPRAGEngine, get_lprag_engine, PerturbationResult
    LPRAG_AVAILABLE = True
except ImportError:
    LPRAG_AVAILABLE = False
    LPRAGConfig = None
    LPRAGMode = None
    LPRAGEngine = None
    get_lprag_config_from_env = None
    get_lprag_engine = None
    PerturbationResult = None

# Consent integration - optional
try:
    from .consent_config import CRITICAL_PII_TYPES, is_pii_type_exposed
    from .consent_session import Session as ConsentSession, get_session_manager
    from .consent_manager import ConsentManager, get_consent_manager
    CONSENT_AVAILABLE = True
except ImportError:
    CONSENT_AVAILABLE = False
    CRITICAL_PII_TYPES = set()
    is_pii_type_exposed = None
    ConsentSession = None
    get_session_manager = None
    ConsentManager = None
    get_consent_manager = None


class PIIProtectorMode(Enum):
    """Operating modes for PII protection."""
    TOKEN_ONLY = "token_only"      # Current behavior: replace PII with tokens
    LPRAG_PURE = "lprag_pure"      # LPRAG perturbation, no reversibility
    LPRAG_HYBRID = "lprag_hybrid"  # LPRAG perturbation with token mapping for de-anonymization


class PIIType(Enum):
    """Supported PII entity types.

    This enum includes all entity types supported by Microsoft Presidio.
    See: https://microsoft.github.io/presidio/supported_entities/
    """
    # Core PII types
    PERSON = "PERSON"
    EMAIL_ADDRESS = "EMAIL_ADDRESS"
    PHONE_NUMBER = "PHONE_NUMBER"
    CREDIT_CARD = "CREDIT_CARD"
    CRYPTO = "CRYPTO"  # Cryptocurrency wallet addresses
    DATE_TIME = "DATE_TIME"
    DOMAIN_NAME = "DOMAIN_NAME"
    IBAN_CODE = "IBAN_CODE"
    IP_ADDRESS = "IP_ADDRESS"
    LOCATION = "LOCATION"
    NRP = "NRP"  # National Registration/ID number (generic)
    MEDICAL_LICENSE = "MEDICAL_LICENSE"
    URL = "URL"

    # US-specific
    US_BANK_NUMBER = "US_BANK_NUMBER"
    US_DRIVER_LICENSE = "US_DRIVER_LICENSE"
    US_ITIN = "US_ITIN"  # Individual Taxpayer Identification Number
    US_PASSPORT = "US_PASSPORT"
    US_SSN = "US_SSN"

    # UK-specific
    UK_NHS = "UK_NHS"  # National Health Service number

    # Australia-specific
    AU_ABN = "AU_ABN"  # Australian Business Number
    AU_ACN = "AU_ACN"  # Australian Company Number
    AU_TFN = "AU_TFN"  # Australian Tax File Number
    AU_MEDICARE = "AU_MEDICARE"

    # Spain-specific
    ES_NIF = "ES_NIF"  # Número de Identificación Fiscal

    # Italy-specific
    IT_FISCAL_CODE = "IT_FISCAL_CODE"
    IT_DRIVER_LICENSE = "IT_DRIVER_LICENSE"
    IT_VAT_CODE = "IT_VAT_CODE"
    IT_PASSPORT = "IT_PASSPORT"
    IT_IDENTITY_CARD = "IT_IDENTITY_CARD"

    # Singapore-specific
    SG_NRIC_FIN = "SG_NRIC_FIN"  # National Registration Identity Card / Foreign ID

    # Poland-specific
    PL_PESEL = "PL_PESEL"  # Polish national ID number

    # India-specific
    IN_PAN = "IN_PAN"  # Permanent Account Number
    IN_AADHAAR = "IN_AADHAAR"  # Aadhaar number
    IN_VEHICLE_REGISTRATION = "IN_VEHICLE_REGISTRATION"

    # Custom recognizers for image PII (document IDs)
    VEHICLE_ID = "VEHICLE_ID"  # VIN numbers
    LICENSE_PLATE = "LICENSE_PLATE"  # License plate numbers
    MEMBER_ID = "MEMBER_ID"  # Member/Account IDs


# All supported entity types as strings (for Presidio API)
ALL_PII_ENTITIES = [e.value for e in PIIType]

# Preset configurations for common use cases
PII_ENTITY_PRESETS = {
    # Minimal: Only basic contact information
    "minimal": [
        "PERSON",
        "EMAIL_ADDRESS",
        "PHONE_NUMBER",
    ],
    # Default: Common PII types for general use
    "default": [
        "PERSON",
        "EMAIL_ADDRESS",
        "PHONE_NUMBER",
        "CREDIT_CARD",
        "US_SSN",
        "US_BANK_NUMBER",
        "IBAN_CODE",
        "IP_ADDRESS",
        "LOCATION",
        "DATE_TIME",
    ],
    # Strict: All supported entity types
    "strict": ALL_PII_ENTITIES,
}


def get_configured_entities() -> List[str]:
    """Get PII entity types from environment configuration.

    Reads PII_ENTITIES environment variable which can be:
    - A preset name: "minimal", "default", "strict"
    - A comma-separated list of entity types

    Returns:
        List of entity type strings to detect.
    """
    env_value = os.environ.get("PII_ENTITIES", "").strip()

    if not env_value:
        # Default to all supported types (strict)
        return ALL_PII_ENTITIES.copy()

    # Check for preset names (case-insensitive)
    preset_key = env_value.lower()
    if preset_key in PII_ENTITY_PRESETS:
        return PII_ENTITY_PRESETS[preset_key].copy()

    # Parse as comma-separated list
    entities = [e.strip().upper() for e in env_value.split(",") if e.strip()]

    # Validate entity names
    valid_entities = []
    for entity in entities:
        if entity in ALL_PII_ENTITIES:
            valid_entities.append(entity)
        else:
            # Log warning but don't fail - allow custom recognizers
            print(f"PIIProtector: Warning - Unknown entity type '{entity}', including anyway")
            valid_entities.append(entity)

    return valid_entities if valid_entities else ALL_PII_ENTITIES.copy()


@dataclass
class PIIToken:
    """Represents a tokenized PII entity.

    For LPRAG hybrid mode, stores both the original value and the perturbed
    value, enabling de-anonymization by matching perturbed values in LLM
    responses and restoring original values.

    For names, also stores part_mappings to handle partial name references
    in LLM responses (e.g., just "Michael" instead of "Michael Chen").
    """
    token_id: str
    pii_type: str
    original_value: str
    created_at: datetime
    perturbed_value: Optional[str] = None  # For LPRAG hybrid mode
    # Part mappings for names: {"first": ("Michael", "John"), "last": ("Chen", "Smith")}
    part_mappings: Optional[Dict[str, Tuple[str, str]]] = None

    @property
    def token_string(self) -> str:
        """Get the replacement token string."""
        return f"<PII:{self.pii_type}:{self.token_id}>"

    @property
    def has_perturbed_value(self) -> bool:
        """Check if this token has a perturbed value (LPRAG mode)."""
        return self.perturbed_value is not None

    @property
    def has_part_mappings(self) -> bool:
        """Check if this token has name part mappings."""
        return self.part_mappings is not None and len(self.part_mappings) > 0


@dataclass
class PerturbedValue:
    """Represents a perturbed/anonymized value for UI highlighting.

    Tracks the anonymized values in text, enabling the frontend to
    visually indicate which parts were anonymized using string matching.
    """
    pii_type: str           # e.g., "PERSON", "EMAIL_ADDRESS"
    perturbed_value: str    # The fake/anonymized value shown
    is_lprag: bool          # True if LPRAG-perturbed, False if token-based


@dataclass
class AnonymizationResult:
    """Result of anonymizing text."""
    anonymized_text: str
    session_id: str
    token_count: int
    pii_types_found: List[str]
    processing_time_ms: float
    perturbed_values: List[PerturbedValue] = field(default_factory=list)  # For UI highlighting


@dataclass
class DeanonymizationResult:
    """Result of de-anonymizing text."""
    deanonymized_text: str
    session_id: str
    tokens_replaced: int
    tokens_not_found: List[str]


class TokenSession:
    """Session-scoped storage for PII token mappings.

    Supports sliding TTL - session expiration is extended on each access.

    For LPRAG hybrid mode, maintains bidirectional mappings:
    - original_value -> token (for deduplication)
    - perturbed_value -> token (for de-anonymization of LLM responses)
    - name part mappings (for partial name references like just "Michael")

    Also tracks used perturbed name parts to avoid collisions within a session.
    """

    def __init__(
        self,
        session_id: str,
        ttl_seconds: int = 3600
    ):
        self.session_id = session_id
        self.ttl_seconds = ttl_seconds
        self.created_at = datetime.now()
        self.last_accessed = self.created_at
        self.expires_at = self.created_at + timedelta(seconds=ttl_seconds)
        self._tokens: Dict[str, PIIToken] = {}
        # Reverse lookup: (pii_type, normalized_value) -> token_id
        self._value_to_token: Dict[Tuple[str, str], str] = {}
        # LPRAG: perturbed_value -> token_id (for de-anonymization)
        self._perturbed_to_token: Dict[str, str] = {}
        # Track used perturbed name parts to avoid collisions
        self._used_first_names: Set[str] = set()
        self._used_last_names: Set[str] = set()
        self._lock = threading.Lock()

    def _normalize_value(self, value: str) -> str:
        """Normalize PII value for comparison (case-insensitive, whitespace-normalized)."""
        return " ".join(value.lower().split())

    def touch(self) -> None:
        """Refresh the session TTL (sliding expiration).

        Call this on any session access to keep active sessions alive.
        """
        with self._lock:
            self.last_accessed = datetime.now()
            self.expires_at = self.last_accessed + timedelta(seconds=self.ttl_seconds)

    def add_token(self, token: PIIToken) -> None:
        """Add a token to the session."""
        with self._lock:
            self._tokens[token.token_id] = token
            # Add reverse lookup for original value
            key = (token.pii_type, self._normalize_value(token.original_value))
            self._value_to_token[key] = token.token_id
            # Add reverse lookup for perturbed value (LPRAG hybrid mode)
            if token.perturbed_value:
                self._perturbed_to_token[token.perturbed_value] = token.token_id
            # Add part mappings for names (enables partial name deanonymization)
            if token.has_part_mappings:
                for part_type, (perturbed_part, original_part) in token.part_mappings.items():
                    # Store perturbed part -> (original_part, token_id, part_type)
                    # Using a tuple value allows us to return the specific part, not full name
                    self._perturbed_to_token[perturbed_part] = token.token_id
                    # Track used names
                    if part_type == "first":
                        self._used_first_names.add(perturbed_part.lower())
                    elif part_type == "last":
                        self._used_last_names.add(perturbed_part.lower())
            # Refresh TTL on write
            self.last_accessed = datetime.now()
            self.expires_at = self.last_accessed + timedelta(seconds=self.ttl_seconds)

    def get_token(self, token_id: str) -> Optional[PIIToken]:
        """Retrieve a token by ID."""
        with self._lock:
            return self._tokens.get(token_id)

    def get_token_by_value(self, pii_type: str, original_value: str) -> Optional[PIIToken]:
        """Retrieve an existing token by PII type and value.

        This enables deduplication - same PII value gets same token.
        """
        with self._lock:
            key = (pii_type, self._normalize_value(original_value))
            token_id = self._value_to_token.get(key)
            if token_id:
                return self._tokens.get(token_id)
            return None

    def get_token_by_perturbed(self, perturbed_value: str) -> Optional[PIIToken]:
        """Retrieve a token by its perturbed value (LPRAG hybrid mode).

        Used during de-anonymization to find original values when
        LLM responses contain perturbed PII.
        """
        with self._lock:
            token_id = self._perturbed_to_token.get(perturbed_value)
            if token_id:
                return self._tokens.get(token_id)
            return None

    def has_perturbed_mappings(self) -> bool:
        """Check if session has any perturbed value mappings (LPRAG mode)."""
        return len(self._perturbed_to_token) > 0

    def get_perturbed_mappings(self) -> Dict[str, str]:
        """Get all perturbed value to token_id mappings.

        Returns dict sorted by perturbed value length (longest first)
        to ensure longer matches are replaced before shorter ones.
        """
        with self._lock:
            # Sort by length descending
            return dict(sorted(
                self._perturbed_to_token.items(),
                key=lambda x: len(x[0]),
                reverse=True
            ))

    def is_first_name_used(self, name: str) -> bool:
        """Check if a perturbed first name is already used in this session."""
        with self._lock:
            return name.lower() in self._used_first_names

    def is_last_name_used(self, name: str) -> bool:
        """Check if a perturbed last name is already used in this session."""
        with self._lock:
            return name.lower() in self._used_last_names

    def get_used_names(self) -> Tuple[Set[str], Set[str]]:
        """Get copies of used first and last name sets.

        Returns:
            Tuple of (used_first_names, used_last_names) as lowercase sets.
        """
        with self._lock:
            return self._used_first_names.copy(), self._used_last_names.copy()

    def is_expired(self) -> bool:
        """Check if session has expired."""
        return datetime.now() > self.expires_at

    @property
    def token_count(self) -> int:
        """Get number of tokens in session."""
        return len(self._tokens)

    @property
    def ttl_remaining_seconds(self) -> int:
        """Get remaining TTL in seconds (0 if expired)."""
        remaining = (self.expires_at - datetime.now()).total_seconds()
        return max(0, int(remaining))


class PIIProtector:
    """Main PII protection service using Microsoft Presidio.

    Handles detection, anonymization, and de-anonymization of PII
    in MCP search results. Uses session-scoped token storage to
    enable reversible anonymization.

    Memory Usage:
    - Analyzer with en_core_web_sm: ~150MB
    - Token sessions: ~1KB per 100 tokens (negligible)

    Configuration:
    - Set PII_ENTITIES env var to customize which entity types to detect
    - Presets: "minimal", "default", "strict" (all types)
    - Or comma-separated list: "PERSON,EMAIL_ADDRESS,PHONE_NUMBER"
    """

    # Token format regex for identifying tokens in text
    TOKEN_PATTERN = re.compile(r'<PII:([A-Z_]+):([a-zA-Z0-9_-]+)>')

    def __init__(
        self,
        entities: Optional[List[str]] = None,
        language: str = "en",
        session_ttl_seconds: int = 3600,
        max_sessions: int = 100,
        spacy_model: str = "en_core_web_sm",
        verbose: bool = False,
        authorized_tokens: Optional[List[str]] = None,
        mode: Optional[PIIProtectorMode] = None,
        lprag_config: Optional[Any] = None  # Type hint as Any to avoid import issues
    ):
        """Initialize the PII protector.

        Args:
            entities: PII entity types to detect. If None, reads from PII_ENTITIES
                     env var or defaults to all supported types.
            language: Language for NLP processing
            session_ttl_seconds: TTL for token sessions
            max_sessions: Maximum concurrent sessions (LRU eviction)
            spacy_model: spaCy model to use (sm for edge devices)
            verbose: Enable debug logging
            authorized_tokens: List of tokens authorized to call deanonymize via MCP
            mode: Operating mode (TOKEN_ONLY, LPRAG_PURE, LPRAG_HYBRID).
                  If None, determined from LPRAG_MODE env var or defaults to TOKEN_ONLY.
            lprag_config: LPRAG configuration. If None and LPRAG mode enabled,
                         loads from environment variables.
        """
        self.entities = entities if entities is not None else get_configured_entities()
        self.language = language
        self.session_ttl_seconds = session_ttl_seconds
        self.max_sessions = max_sessions
        self.verbose = verbose
        self._spacy_model = spacy_model

        # Authorization tokens for MCP tool access
        self._authorized_tokens: Set[str] = set(authorized_tokens or [])
        self._auth_lock = threading.Lock()

        # Session storage
        self._sessions: Dict[str, TokenSession] = {}
        self._session_lock = threading.Lock()

        # Initialize Presidio engines lazily
        self._analyzer: Optional[AnalyzerEngine] = None
        self._anonymizer: Optional[AnonymizerEngine] = None
        self._init_lock = threading.Lock()
        self._initialized = False
        self._init_error: Optional[str] = None

        # LPRAG configuration
        self._mode = self._determine_mode(mode)
        self._lprag_config = lprag_config
        self._lprag_engine: Optional[Any] = None
        self._lprag_initialized = False
        self._lprag_init_error: Optional[str] = None

        if self.verbose:
            print(f"PIIProtector: Mode set to {self._mode.value}")

    def _determine_mode(self, mode: Optional[PIIProtectorMode]) -> PIIProtectorMode:
        """Determine operating mode from parameter or environment.

        Args:
            mode: Explicit mode, or None to read from environment.

        Returns:
            PIIProtectorMode to use.

        Note:
            Default is LPRAG_HYBRID for best balance of privacy and usability.
            LPRAG provides semantic perturbation with automatic fallback to
            token-based anonymization for unsupported entity types.
        """
        if mode is not None:
            return mode

        # Check LPRAG_MODE environment variable
        env_mode = os.environ.get("LPRAG_MODE", "").strip().lower()

        if env_mode == "disabled" or env_mode == "token_only":
            return PIIProtectorMode.TOKEN_ONLY
        elif env_mode == "pure":
            return PIIProtectorMode.LPRAG_PURE
        else:
            # Default to LPRAG_HYBRID for best balance of privacy and usability
            # Falls back to tokens automatically for unsupported entities
            return PIIProtectorMode.LPRAG_HYBRID

    def _ensure_lprag_initialized(self) -> bool:
        """Lazy initialization of LPRAG engine.

        Returns:
            True if LPRAG is initialized and available, False otherwise.
        """
        if self._mode == PIIProtectorMode.TOKEN_ONLY:
            return False  # LPRAG not needed in token-only mode

        if self._lprag_initialized:
            return self._lprag_init_error is None

        with self._init_lock:
            if self._lprag_initialized:
                return self._lprag_init_error is None

            if not LPRAG_AVAILABLE:
                self._lprag_initialized = True
                self._lprag_init_error = "LPRAG not available. Install gensim for LPRAG support."
                if self.verbose:
                    print(f"PIIProtector: {self._lprag_init_error}")
                return False

            try:
                if self.verbose:
                    print("PIIProtector: Initializing LPRAG engine...")

                # Load config from environment if not provided
                if self._lprag_config is None:
                    self._lprag_config = get_lprag_config_from_env()

                # Get or create LPRAG engine
                self._lprag_engine = get_lprag_engine(self._lprag_config)

                self._lprag_initialized = True
                self._lprag_init_error = None

                if self.verbose:
                    print("PIIProtector: LPRAG engine initialized successfully")

                return True

            except Exception as e:
                self._lprag_initialized = True
                self._lprag_init_error = str(e)
                if self.verbose:
                    print(f"PIIProtector: Failed to initialize LPRAG: {e}")
                return False

    @property
    def mode(self) -> PIIProtectorMode:
        """Get current operating mode."""
        return self._mode

    @property
    def is_lprag_available(self) -> bool:
        """Check if LPRAG is available and initialized."""
        if self._mode == PIIProtectorMode.TOKEN_ONLY:
            return False
        return self._ensure_lprag_initialized()

    @property
    def is_available(self) -> bool:
        """Check if Presidio is available."""
        return PRESIDIO_AVAILABLE

    def _ensure_initialized(self) -> bool:
        """Lazy initialization of Presidio engines.

        Returns:
            True if initialization succeeded, False otherwise.
        """
        if not PRESIDIO_AVAILABLE:
            self._init_error = "Presidio not installed. Install with: pip install presidio-analyzer presidio-anonymizer"
            return False

        if self._initialized:
            return self._init_error is None

        with self._init_lock:
            if self._initialized:
                return self._init_error is None

            try:
                if self.verbose:
                    print(f"PIIProtector: Initializing Presidio with {self._spacy_model}...")

                # Configure NLP engine for smaller memory footprint
                configuration = {
                    "nlp_engine_name": "spacy",
                    "models": [{"lang_code": self.language, "model_name": self._spacy_model}]
                }
                provider = NlpEngineProvider(nlp_configuration=configuration)
                nlp_engine = provider.create_engine()

                self._analyzer = AnalyzerEngine(nlp_engine=nlp_engine)
                self._anonymizer = AnonymizerEngine()

                # Add custom recognizers for document IDs commonly found in images
                self._add_custom_recognizers()

                self._initialized = True
                self._init_error = None

                if self.verbose:
                    print("PIIProtector: Presidio initialized successfully")

                return True

            except Exception as e:
                self._initialized = True
                self._init_error = str(e)
                if self.verbose:
                    print(f"PIIProtector: Failed to initialize Presidio: {e}")
                return False

    def _add_custom_recognizers(self) -> None:
        """Add custom pattern recognizers for document IDs commonly found in images.

        These recognizers detect IDs that Presidio's default recognizers miss:
        - Passport numbers (US, international)
        - Vehicle Identification Numbers (VINs)
        - License plate numbers
        - Member/Account IDs
        """
        if not PRESIDIO_AVAILABLE or self._analyzer is None:
            return

        try:
            # US Passport number: 9 alphanumeric, often starts with letters
            # Examples: US123456789, AB1234567, 123456789
            passport_patterns = [
                Pattern(
                    name="us_passport_alphanumeric",
                    regex=r"\b[A-Z]{1,2}\d{7,9}\b",  # US format: 1-2 letters + 7-9 digits
                    score=0.7,
                ),
                Pattern(
                    name="passport_9digit",
                    regex=r"\b\d{9}\b",  # 9 digits (common format)
                    score=0.4,  # Lower score - could be other IDs
                ),
            ]
            passport_recognizer = PatternRecognizer(
                supported_entity="US_PASSPORT",
                patterns=passport_patterns,
                name="CustomPassportRecognizer",
            )
            self._analyzer.registry.add_recognizer(passport_recognizer)

            # Vehicle Identification Number (VIN): 17 alphanumeric (no I, O, Q)
            vin_patterns = [
                Pattern(
                    name="vin_17char",
                    regex=r"\b[A-HJ-NPR-Z0-9]{17}\b",
                    score=0.85,
                ),
            ]
            vin_recognizer = PatternRecognizer(
                supported_entity="VEHICLE_ID",
                patterns=vin_patterns,
                name="CustomVINRecognizer",
            )
            self._analyzer.registry.add_recognizer(vin_recognizer)

            # License plate patterns (US states - common formats)
            plate_patterns = [
                Pattern(
                    name="plate_letters_digits",
                    regex=r"\b\d{1}[A-Z]{3}\d{3}\b",  # 1ABC234 format
                    score=0.6,
                ),
                Pattern(
                    name="plate_digits_letters",
                    regex=r"\b[A-Z]{3}\d{4}\b",  # ABC1234 format
                    score=0.6,
                ),
            ]
            plate_recognizer = PatternRecognizer(
                supported_entity="LICENSE_PLATE",
                patterns=plate_patterns,
                name="CustomLicensePlateRecognizer",
            )
            self._analyzer.registry.add_recognizer(plate_recognizer)

            # Member/Account ID patterns (alphanumeric with prefixes)
            member_id_patterns = [
                Pattern(
                    name="member_id_prefix",
                    regex=r"\b[A-Z]{2,4}[-]?\d{6,12}\b",  # XYZ-123456789 format
                    score=0.5,
                ),
                Pattern(
                    name="group_number",
                    regex=r"\bGRP[-]?\d{5,6}\b",  # GRP-12345 format
                    score=0.7,
                ),
            ]
            member_id_recognizer = PatternRecognizer(
                supported_entity="MEMBER_ID",
                patterns=member_id_patterns,
                name="CustomMemberIDRecognizer",
            )
            self._analyzer.registry.add_recognizer(member_id_recognizer)

            if self.verbose:
                print("PIIProtector: Added custom recognizers for document IDs")

        except Exception as e:
            if self.verbose:
                print(f"PIIProtector: Failed to add custom recognizers: {e}")

    def _get_or_create_session(self, session_id: Optional[str] = None) -> TokenSession:
        """Get existing session or create new one."""
        with self._session_lock:
            # Clean expired sessions
            self._cleanup_expired_sessions()

            if session_id and session_id in self._sessions:
                session = self._sessions[session_id]
                if not session.is_expired():
                    # Refresh TTL on session reuse (sliding expiration)
                    session.touch()
                    return session
                # Expired, remove and create new
                del self._sessions[session_id]

            # Create new session
            new_id = session_id or secrets.token_urlsafe(24)  # 192 bits for session IDs
            session = TokenSession(new_id, self.session_ttl_seconds)

            # Enforce max sessions (LRU eviction based on last access time)
            if len(self._sessions) >= self.max_sessions:
                oldest_id = min(self._sessions, key=lambda k: self._sessions[k].last_accessed)
                del self._sessions[oldest_id]

            self._sessions[new_id] = session
            return session

    def _cleanup_expired_sessions(self) -> None:
        """Remove expired sessions."""
        expired = [sid for sid, s in self._sessions.items() if s.is_expired()]
        for sid in expired:
            del self._sessions[sid]

    def add_authorized_token(self, token: str) -> None:
        """Add an authorization token for MCP tool access."""
        with self._auth_lock:
            self._authorized_tokens.add(token)

    def remove_authorized_token(self, token: str) -> bool:
        """Remove an authorization token."""
        with self._auth_lock:
            if token in self._authorized_tokens:
                self._authorized_tokens.remove(token)
                return True
            return False

    def is_authorized(self, token: str) -> bool:
        """Check if a token is authorized for MCP deanonymization."""
        with self._auth_lock:
            return token in self._authorized_tokens

    def generate_auth_token(self) -> str:
        """Generate a new authorization token."""
        token = secrets.token_urlsafe(32)
        self.add_authorized_token(token)
        return token

    def anonymize(
        self,
        text: str,
        session_id: Optional[str] = None,
        entities: Optional[List[str]] = None,
        exposed_pii_types: Optional[Set[str]] = None
    ) -> AnonymizationResult:
        """Detect and anonymize PII in text.

        Args:
            text: Text to anonymize
            session_id: Existing session ID or None for new session
            entities: Override default entities to detect
            exposed_pii_types: PII types to skip (not anonymize), from consent settings

        Returns:
            AnonymizationResult with anonymized text and session info
        """
        # Critical PII types that are NEVER exposed regardless of consent
        CRITICAL_PII = {"US_SSN", "CREDIT_CARD", "US_BANK_NUMBER", "IBAN_CODE", "IN_AADHAAR", "AU_TFN", "CRYPTO"}
        start_time = time.time()

        # Get or create session first (needed even if Presidio unavailable)
        session = self._get_or_create_session(session_id)

        # Check if Presidio is available
        if not self._ensure_initialized():
            # SECURITY: Fail-closed — do NOT pass raw PII to LLM when Presidio is unavailable.
            # Instead, redact all text to prevent silent PII leakage.
            # Operators should monitor /health/pii to ensure Presidio is running.
            fail_closed = os.environ.get("PII_FAIL_OPEN", "").lower() in ("true", "1", "yes")
            if not fail_closed:
                redacted_text = "[PII_PROTECTION_UNAVAILABLE: Content redacted for safety. Presidio is not initialized.]"
                print(f"PIIProtector: WARNING — Presidio unavailable, content redacted (fail-closed). "
                      f"Set PII_FAIL_OPEN=true to allow unprotected content through.")
                return AnonymizationResult(
                    anonymized_text=redacted_text,
                    session_id=session.session_id,
                    token_count=0,
                    pii_types_found=[],
                    processing_time_ms=(time.time() - start_time) * 1000
                )
            else:
                # Explicit opt-in to fail-open behavior (development only)
                print(f"PIIProtector: WARNING — Presidio unavailable, passing through raw text (PII_FAIL_OPEN=true)")
                return AnonymizationResult(
                    anonymized_text=text,
                    session_id=session.session_id,
                    token_count=0,
                    pii_types_found=[],
                    processing_time_ms=(time.time() - start_time) * 1000
                )

        # Analyze text for PII
        try:
            results = self._analyzer.analyze(
                text=text,
                entities=entities or self.entities,
                language=self.language
            )
        except Exception as e:
            # RT-03b: Fail-closed on analysis errors — do not return raw text
            print(f"PIIProtector: WARNING — Analysis failed: {e}. Redacting content (fail-closed).")
            fail_open = os.environ.get("PII_FAIL_OPEN", "").lower() in ("true", "1", "yes")
            redacted = text if fail_open else "[PII_PROTECTION_ERROR: Content redacted for safety. Presidio analysis failed.]"
            return AnonymizationResult(
                anonymized_text=redacted,
                session_id=session.session_id,
                token_count=0,
                pii_types_found=[],
                processing_time_ms=(time.time() - start_time) * 1000
            )

        if not results:
            # No PII found
            return AnonymizationResult(
                anonymized_text=text,
                session_id=session.session_id,
                token_count=0,
                pii_types_found=[],
                processing_time_ms=(time.time() - start_time) * 1000
            )

        # Sort results by start position (descending) to replace from end
        sorted_results = sorted(results, key=lambda r: r.start, reverse=True)

        anonymized = text
        pii_types_found: Set[str] = set()
        new_tokens_created = 0
        lprag_perturbed = 0
        lprag_fallbacks = 0
        perturbed_values_dict: Dict[str, PerturbedValue] = {}  # Dedupe by perturbed_value

        # Check if span tracking is enabled (default: true)
        track_spans = os.environ.get("LPRAG_SHOW_SPANS", "true").lower() != "false"

        # Determine if LPRAG should be used
        use_lprag = self._mode != PIIProtectorMode.TOKEN_ONLY and self._ensure_lprag_initialized()

        for result in sorted_results:
            pii_value = text[result.start:result.end]

            # Skip anonymization for exposed PII types (except critical PII which is always protected)
            if exposed_pii_types and result.entity_type in exposed_pii_types:
                if result.entity_type not in CRITICAL_PII:
                    # This PII type is allowed to be exposed - skip anonymization
                    pii_types_found.add(result.entity_type)
                    continue

            # Check if we already have a token for this PII value (deduplication)
            existing_token = session.get_token_by_value(result.entity_type, pii_value)

            if existing_token:
                # Reuse existing token for duplicate PII value
                token = existing_token
                # Use the appropriate replacement based on mode
                if existing_token.has_perturbed_value:
                    replacement = existing_token.perturbed_value
                else:
                    replacement = existing_token.token_string
            else:
                # Try LPRAG perturbation if enabled
                perturbed_value = None
                part_mappings = None
                if use_lprag and self._lprag_engine:
                    try:
                        # Get used names from session to avoid collisions
                        used_first, used_last = session.get_used_names()
                        perturb_result = self._lprag_engine.perturb_entity(
                            pii_value,
                            result.entity_type,
                            session_id=session.session_id,
                            used_first_names=used_first,
                            used_last_names=used_last,
                        )
                        if perturb_result.success:
                            perturbed_value = perturb_result.perturbed_value
                            part_mappings = perturb_result.part_mappings
                            lprag_perturbed += 1
                        else:
                            lprag_fallbacks += 1
                    except Exception as e:
                        if self.verbose:
                            print(f"PIIProtector: LPRAG perturbation failed for {result.entity_type}: {e}")
                        lprag_fallbacks += 1

                # Create token with or without perturbed value
                token = PIIToken(
                    token_id=secrets.token_urlsafe(16),
                    pii_type=result.entity_type,
                    original_value=pii_value,
                    created_at=datetime.now(),
                    perturbed_value=perturbed_value,
                    part_mappings=part_mappings,
                )

                # Determine replacement string
                if perturbed_value:
                    # LPRAG mode: use perturbed value
                    replacement = perturbed_value
                else:
                    # Token-only mode or LPRAG fallback: use token string
                    replacement = token.token_string

                # Store in session
                session.add_token(token)
                new_tokens_created += 1

            # Replace in text
            anonymized = anonymized[:result.start] + replacement + anonymized[result.end:]
            pii_types_found.add(result.entity_type)

            # Track perturbed value for UI highlighting (deduplicated)
            if track_spans and replacement not in perturbed_values_dict:
                is_lprag = token.has_perturbed_value if not existing_token else existing_token.has_perturbed_value
                perturbed_values_dict[replacement] = PerturbedValue(
                    pii_type=result.entity_type,
                    perturbed_value=replacement,
                    is_lprag=is_lprag
                )

        processing_time = (time.time() - start_time) * 1000

        if self.verbose:
            reused = len(sorted_results) - new_tokens_created
            if use_lprag:
                print(f"PIIProtector: Anonymized {len(sorted_results)} PII entities "
                      f"({new_tokens_created} unique, {reused} deduplicated, "
                      f"{lprag_perturbed} LPRAG perturbed, {lprag_fallbacks} token fallbacks) "
                      f"in {processing_time:.1f}ms")
            else:
                print(f"PIIProtector: Anonymized {len(sorted_results)} PII entities "
                      f"({new_tokens_created} unique, {reused} deduplicated) in {processing_time:.1f}ms")

        return AnonymizationResult(
            anonymized_text=anonymized,
            session_id=session.session_id,
            token_count=len(sorted_results),
            pii_types_found=list(pii_types_found),
            processing_time_ms=processing_time,
            perturbed_values=list(perturbed_values_dict.values())
        )

    def anonymize_search_results(
        self,
        results: List[Dict[str, Any]],
        session_id: Optional[str] = None,
        text_fields: Optional[List[str]] = None
    ) -> Tuple[List[Dict[str, Any]], str, int]:
        """Anonymize PII in search result objects.

        Args:
            results: List of search result dictionaries
            session_id: Session ID for token storage
            text_fields: Fields to anonymize (default: text, excerpt)

        Returns:
            Tuple of (anonymized results, session_id, total_tokens_replaced)
        """
        text_fields = text_fields or ["text", "excerpt"]
        session = self._get_or_create_session(session_id)
        total_tokens = 0

        anonymized_results = []
        for result in results:
            anon_result = result.copy()

            for field in text_fields:
                if field in anon_result and anon_result[field]:
                    anon_response = self.anonymize(
                        anon_result[field],
                        session_id=session.session_id
                    )
                    anon_result[field] = anon_response.anonymized_text
                    total_tokens += anon_response.token_count

            anonymized_results.append(anon_result)

        return anonymized_results, session.session_id, total_tokens

    def anonymize_with_consent(
        self,
        text: str,
        consent_session: Optional[Any] = None,
        session_id: Optional[str] = None,
        entities: Optional[List[str]] = None,
    ) -> AnonymizationResult:
        """Anonymize text respecting consent rules.

        Uses the consent session to determine which PII types should be
        exposed (not anonymized) vs anonymized.

        Args:
            text: Text to anonymize
            consent_session: Consent session with rules (from consent_session.py)
            session_id: PII session ID for token storage
            entities: Override default entities to detect

        Returns:
            AnonymizationResult with anonymized text and session info
        """
        start_time = time.time()

        # Get or create PII session
        pii_session = self._get_or_create_session(session_id)

        # RT-03: Fail-closed when Presidio is unavailable (same as anonymize())
        if not self._ensure_initialized():
            fail_open = os.environ.get("PII_FAIL_OPEN", "").lower() in ("true", "1", "yes")
            if not fail_open:
                redacted_text = "[PII_PROTECTION_UNAVAILABLE: Content redacted for safety. Presidio is not initialized.]"
                print(f"PIIProtector: WARNING — Presidio unavailable in anonymize_with_consent, content redacted (fail-closed).")
                return AnonymizationResult(
                    anonymized_text=redacted_text,
                    session_id=pii_session.session_id,
                    token_count=0,
                    pii_types_found=[],
                    processing_time_ms=(time.time() - start_time) * 1000
                )
            else:
                print(f"PIIProtector: WARNING — Presidio unavailable, passing through raw text (PII_FAIL_OPEN=true)")
                return AnonymizationResult(
                    anonymized_text=text,
                    session_id=pii_session.session_id,
                    token_count=0,
                    pii_types_found=[],
                    processing_time_ms=(time.time() - start_time) * 1000
                )

        # Analyze text for PII
        try:
            results = self._analyzer.analyze(
                text=text,
                entities=entities or self.entities,
                language=self.language
            )
        except Exception as e:
            # RT-03: Fail-closed on analysis errors (same as anonymize())
            print(f"PIIProtector: WARNING — Analysis failed in anonymize_with_consent: {e}. Redacting content (fail-closed).")
            fail_open = os.environ.get("PII_FAIL_OPEN", "").lower() in ("true", "1", "yes")
            redacted = text if fail_open else "[PII_PROTECTION_ERROR: Content redacted for safety. Presidio analysis failed.]"
            return AnonymizationResult(
                anonymized_text=redacted,
                session_id=pii_session.session_id,
                token_count=0,
                pii_types_found=[],
                processing_time_ms=(time.time() - start_time) * 1000
            )

        if not results:
            return AnonymizationResult(
                anonymized_text=text,
                session_id=pii_session.session_id,
                token_count=0,
                pii_types_found=[],
                processing_time_ms=(time.time() - start_time) * 1000
            )

        # Sort results by start position (descending) to replace from end
        sorted_results = sorted(results, key=lambda r: r.start, reverse=True)

        anonymized = text
        pii_types_found: Set[str] = set()
        new_tokens_created = 0
        pii_exposed = 0

        # Determine if LPRAG should be used
        use_lprag = self._mode != PIIProtectorMode.TOKEN_ONLY and self._ensure_lprag_initialized()

        # Get consent manager for checking consent rules
        consent_manager = None
        if CONSENT_AVAILABLE and consent_session is not None:
            try:
                consent_manager = get_consent_manager()
            except Exception:
                pass

        for result in sorted_results:
            pii_value = text[result.start:result.end]
            pii_type = result.entity_type
            pii_types_found.add(pii_type)

            # Check consent rules: should this PII be anonymized?
            should_anonymize = True
            if consent_manager and consent_session:
                should_anonymize, reason = consent_manager.should_anonymize_pii(
                    pii_type, pii_value, consent_session
                )
                if not should_anonymize:
                    pii_exposed += 1
                    continue  # Skip anonymization for this PII

            # Check if we already have a token for this PII value (deduplication)
            existing_token = pii_session.get_token_by_value(pii_type, pii_value)

            if existing_token:
                token = existing_token
                if existing_token.has_perturbed_value:
                    replacement = existing_token.perturbed_value
                else:
                    replacement = existing_token.token_string
            else:
                # Try LPRAG perturbation if enabled
                perturbed_value = None
                part_mappings = None
                if use_lprag and self._lprag_engine:
                    try:
                        # Get used names from session to avoid collisions
                        used_first, used_last = pii_session.get_used_names()
                        perturb_result = self._lprag_engine.perturb_entity(
                            pii_value,
                            pii_type,
                            session_id=pii_session.session_id,
                            used_first_names=used_first,
                            used_last_names=used_last,
                        )
                        if perturb_result.success:
                            perturbed_value = perturb_result.perturbed_value
                            part_mappings = perturb_result.part_mappings
                    except Exception:
                        pass

                # Create token
                token = PIIToken(
                    token_id=secrets.token_urlsafe(16),
                    pii_type=pii_type,
                    original_value=pii_value,
                    created_at=datetime.now(),
                    perturbed_value=perturbed_value,
                    part_mappings=part_mappings,
                )

                if perturbed_value:
                    replacement = perturbed_value
                else:
                    replacement = token.token_string

                pii_session.add_token(token)
                new_tokens_created += 1

            # Replace in text
            anonymized = anonymized[:result.start] + replacement + anonymized[result.end:]

        processing_time = (time.time() - start_time) * 1000

        if self.verbose:
            print(f"PIIProtector: Consent-aware anonymization: "
                  f"{len(sorted_results)} PII found, {pii_exposed} exposed, "
                  f"{new_tokens_created} anonymized in {processing_time:.1f}ms")

        return AnonymizationResult(
            anonymized_text=anonymized,
            session_id=pii_session.session_id,
            token_count=len(sorted_results) - pii_exposed,
            pii_types_found=list(pii_types_found),
            processing_time_ms=processing_time
        )

    def anonymize_search_results_with_consent(
        self,
        results: List[Dict[str, Any]],
        consent_session: Optional[Any] = None,
        session_id: Optional[str] = None,
        text_fields: Optional[List[str]] = None
    ) -> Tuple[List[Dict[str, Any]], str, int]:
        """Anonymize PII in search results respecting consent rules.

        Args:
            results: List of search result dictionaries
            consent_session: Consent session with rules
            session_id: PII session ID for token storage
            text_fields: Fields to anonymize (default: text, excerpt)

        Returns:
            Tuple of (anonymized results, session_id, total_tokens_replaced)
        """
        text_fields = text_fields or ["text", "excerpt"]
        pii_session = self._get_or_create_session(session_id)
        total_tokens = 0

        anonymized_results = []
        for result in results:
            anon_result = result.copy()

            for field in text_fields:
                if field in anon_result and anon_result[field]:
                    anon_response = self.anonymize_with_consent(
                        anon_result[field],
                        consent_session=consent_session,
                        session_id=pii_session.session_id
                    )
                    anon_result[field] = anon_response.anonymized_text
                    total_tokens += anon_response.token_count

            anonymized_results.append(anon_result)

        return anonymized_results, pii_session.session_id, total_tokens

    def deanonymize(
        self,
        text: str,
        session_id: str,
        auth_token: Optional[str] = None,
        require_auth: bool = False
    ) -> DeanonymizationResult:
        """De-anonymize text by replacing tokens with original PII.

        Args:
            text: Text containing PII tokens
            session_id: Session ID from anonymization
            auth_token: Authorization token (required if require_auth=True)
            require_auth: Whether to require authorization

        Returns:
            DeanonymizationResult with restored text
        """
        # Check authorization if required
        if require_auth:
            if not auth_token or not self.is_authorized(auth_token):
                return DeanonymizationResult(
                    deanonymized_text=text,
                    session_id=session_id,
                    tokens_replaced=0,
                    tokens_not_found=["UNAUTHORIZED"]
                )

        with self._session_lock:
            session = self._sessions.get(session_id)

        if not session:
            return DeanonymizationResult(
                deanonymized_text=text,
                session_id=session_id,
                tokens_replaced=0,
                tokens_not_found=["SESSION_NOT_FOUND"]
            )

        if session.is_expired():
            return DeanonymizationResult(
                deanonymized_text=text,
                session_id=session_id,
                tokens_replaced=0,
                tokens_not_found=["SESSION_EXPIRED"]
            )

        # Refresh session TTL on access (sliding expiration)
        session.touch()

        deanonymized = text
        tokens_replaced = 0
        tokens_not_found = []
        perturbed_replaced = 0

        # Step 1: Replace traditional tokens (e.g., <PII:PERSON:abc123>)
        matches = list(self.TOKEN_PATTERN.finditer(text))

        # Replace from end to preserve positions
        for match in reversed(matches):
            pii_type = match.group(1)
            token_id = match.group(2)

            token = session.get_token(token_id)
            if token:
                deanonymized = (
                    deanonymized[:match.start()] +
                    token.original_value +
                    deanonymized[match.end():]
                )
                tokens_replaced += 1
            else:
                tokens_not_found.append(f"{pii_type}:{token_id}")

        # Step 2: Replace perturbed values (LPRAG hybrid mode)
        # Only do this if the session has perturbed mappings
        if session.has_perturbed_mappings():
            # Get mappings sorted by length (longest first to avoid partial matches)
            perturbed_mappings = session.get_perturbed_mappings()
            import re as regex_module

            def normalize_phone(phone: str) -> str:
                """Extract just the digits from a phone number."""
                return ''.join(c for c in phone if c.isdigit())

            def make_phone_pattern(digits: str) -> str:
                """Create regex pattern matching digits with optional separators."""
                # Match each digit with optional separators (space, dash, dot, parens)
                # e.g., "5551234567" -> r"5[\s\-\.\(\)]*5[\s\-\.\(\)]*5..."
                parts = [regex_module.escape(d) for d in digits]
                return r'[\s\-\.\(\)]*'.join(parts)

            for perturbed_value, token_id in perturbed_mappings.items():
                token = session.get_token(token_id)
                if not token:
                    continue

                replacement = token.original_value  # Default to full original

                # Special handling for phone numbers - match any format
                if token.pii_type == "PHONE_NUMBER":
                    perturbed_digits = normalize_phone(perturbed_value)
                    if len(perturbed_digits) >= 7:  # Valid phone number
                        # Build pattern that matches the digits with any separators
                        phone_pattern = make_phone_pattern(perturbed_digits)
                        # Allow optional leading chars like + or (
                        pattern = regex_module.compile(
                            r'[\+\(]?' + phone_pattern + r'\)?',
                            regex_module.IGNORECASE
                        )
                        count_before = len(pattern.findall(deanonymized))
                        if count_before > 0:
                            deanonymized = pattern.sub(replacement, deanonymized)
                            perturbed_replaced += count_before
                        continue

                # Standard matching for non-phone values
                # Case-insensitive check to handle LLM capitalization changes
                if perturbed_value.lower() in deanonymized.lower():
                    # Check if this is a name part (not the full perturbed value)
                    if token.has_part_mappings and perturbed_value != token.perturbed_value:
                        # This is a name part, find the corresponding original part
                        for part_type, (pert_part, orig_part) in token.part_mappings.items():
                            if pert_part.lower() == perturbed_value.lower():
                                replacement = orig_part
                                break

                    # Use word boundary matching to avoid replacing partial words
                    # e.g., "Chen" shouldn't match "Chenault"
                    pattern = regex_module.compile(
                        r'\b' + regex_module.escape(perturbed_value) + r'\b',
                        regex_module.IGNORECASE
                    )
                    count_before = len(pattern.findall(deanonymized))
                    deanonymized = pattern.sub(replacement, deanonymized)
                    perturbed_replaced += count_before

        total_replaced = tokens_replaced + perturbed_replaced

        if self.verbose:
            if perturbed_replaced > 0:
                print(f"PIIProtector: De-anonymized {total_replaced} items "
                      f"({tokens_replaced} tokens, {perturbed_replaced} perturbed values)")
            else:
                print(f"PIIProtector: De-anonymized {tokens_replaced} tokens")

        return DeanonymizationResult(
            deanonymized_text=deanonymized,
            session_id=session_id,
            tokens_replaced=total_replaced,
            tokens_not_found=tokens_not_found
        )

    def get_session_info(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get information about a session."""
        with self._session_lock:
            session = self._sessions.get(session_id)

        if not session:
            return None

        return {
            "session_id": session.session_id,
            "created_at": session.created_at.isoformat(),
            "last_accessed": session.last_accessed.isoformat(),
            "expires_at": session.expires_at.isoformat(),
            "ttl_remaining_seconds": session.ttl_remaining_seconds,
            "is_expired": session.is_expired(),
            "token_count": session.token_count
        }

    def refresh_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Explicitly refresh a session's TTL.

        Useful for clients that want to keep a session alive without
        performing a deanonymize operation.

        Args:
            session_id: Session ID to refresh

        Returns:
            Updated session info dict, or None if session not found/expired
        """
        with self._session_lock:
            session = self._sessions.get(session_id)

        if not session:
            return None

        if session.is_expired():
            return None

        # Refresh the TTL
        session.touch()

        return {
            "session_id": session.session_id,
            "created_at": session.created_at.isoformat(),
            "last_accessed": session.last_accessed.isoformat(),
            "expires_at": session.expires_at.isoformat(),
            "ttl_remaining_seconds": session.ttl_remaining_seconds,
            "is_expired": False,
            "token_count": session.token_count
        }

    def clear_session(self, session_id: str) -> bool:
        """Explicitly clear a session."""
        with self._session_lock:
            if session_id in self._sessions:
                del self._sessions[session_id]
                return True
        return False

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about PII protection."""
        with self._session_lock:
            active_sessions = sum(1 for s in self._sessions.values() if not s.is_expired())
            total_tokens = sum(s.token_count for s in self._sessions.values())
            # Count perturbed values across sessions
            total_perturbed = sum(
                len(s._perturbed_to_token) for s in self._sessions.values()
                if not s.is_expired()
            )

        # LPRAG stats
        lprag_stats = {
            "available": LPRAG_AVAILABLE,
            "mode": self._mode.value,
            "initialized": self._lprag_initialized and self._lprag_init_error is None,
            "init_error": self._lprag_init_error,
        }

        # Add LPRAG engine stats if available
        if self._lprag_engine and hasattr(self._lprag_engine, 'get_stats'):
            try:
                lprag_stats["engine"] = self._lprag_engine.get_stats()
            except Exception:
                pass

        return {
            "presidio_available": PRESIDIO_AVAILABLE,
            "analyzer_initialized": self._analyzer is not None,
            "init_error": self._init_error,
            "active_sessions": active_sessions,
            "total_sessions": len(self._sessions),
            "total_tokens": total_tokens,
            "total_perturbed_values": total_perturbed,
            "max_sessions": self.max_sessions,
            "session_ttl_seconds": self.session_ttl_seconds,
            "entities_detected": self.entities,
            "spacy_model": self._spacy_model,
            "lprag": lprag_stats
        }


# Global instance for singleton pattern
_global_pii_protector: Optional[PIIProtector] = None
_global_lock = threading.Lock()


def get_pii_protector(
    verbose: bool = False,
    mode: Optional[PIIProtectorMode] = None,
    lprag_config: Optional[Any] = None,
    **kwargs
) -> PIIProtector:
    """Get or create the global PII protector instance.

    Args:
        verbose: Enable debug logging
        mode: Operating mode (TOKEN_ONLY, LPRAG_PURE, LPRAG_HYBRID)
        lprag_config: LPRAG configuration object
        **kwargs: Additional arguments passed to PIIProtector

    Returns:
        The global PIIProtector instance.
    """
    global _global_pii_protector
    with _global_lock:
        if _global_pii_protector is None:
            _global_pii_protector = PIIProtector(
                verbose=verbose,
                mode=mode,
                lprag_config=lprag_config,
                **kwargs
            )
        return _global_pii_protector


def reset_pii_protector() -> None:
    """Reset the global PII protector (for testing)."""
    global _global_pii_protector
    with _global_lock:
        _global_pii_protector = None
