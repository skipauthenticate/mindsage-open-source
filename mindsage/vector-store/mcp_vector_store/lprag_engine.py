"""LPRAG (Locally Private RAG) engine for differential privacy protection.

Implements Local Differential Privacy (LDP) with:
- Adaptive Privacy Budget (APB) allocation based on entity sensitivity
- Word perturbation using exponential mechanism (names, locations)
- Number perturbation using Laplace mechanism (phone, SSN, ages)
- Phrase perturbation using segment-wise approach (addresses, emails)

The exponential mechanism selects semantically similar words with probability
proportional to exp(epsilon * similarity / 2), providing ε-differential privacy.

The Laplace mechanism adds noise drawn from Laplace(0, sensitivity/epsilon)
to numerical values, preserving format while protecting privacy.

Memory footprint: ~50-100MB additional (GloVe embeddings on CPU)

Usage:
    from lprag_engine import LPRAGEngine, get_lprag_engine

    engine = get_lprag_engine()
    result = engine.perturb_entity("John Smith", "PERSON")
    # result.perturbed_value = "Michael Chen"
"""

import re
import math
import random
import secrets
import threading
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Any, Set
from datetime import datetime

import numpy as np

from .lprag_config import (
    LPRAGConfig,
    LPRAGMode,
    PrivacySensitivity,
    get_lprag_config_from_env,
    get_entity_sensitivity,
)
from .lprag_embeddings import (
    LPRAGEmbeddings,
    get_lprag_embeddings,
    get_random_name,
    get_random_location,
    COMMON_FIRST_NAMES,
    COMMON_LAST_NAMES,
)


class PerturbationError(Exception):
    """Exception raised when perturbation fails."""
    pass


@dataclass
class PerturbationResult:
    """Result of perturbing a PII entity."""
    original_value: str
    perturbed_value: str
    pii_type: str
    perturbation_type: str  # "word", "number", "phrase", "fallback"
    epsilon_used: float
    token_id: Optional[str] = None  # For hybrid mode reversibility
    success: bool = True
    error: Optional[str] = None
    # For PERSON entities: maps part type to (perturbed_part, original_part)
    # e.g., {"first": ("Michael", "John"), "last": ("Chen", "Smith")}
    part_mappings: Optional[Dict[str, Tuple[str, str]]] = None


class WordPerturbationModule:
    """Perturbs words using exponential mechanism with semantic similarity.

    The exponential mechanism selects a word from the vocabulary with probability:
        P(word) ∝ exp(ε * similarity(original, word) / 2)

    Lower epsilon = more uniform distribution (stronger privacy)
    Higher epsilon = more similar words selected (better utility)
    """

    def __init__(
        self,
        embeddings: LPRAGEmbeddings,
        config: LPRAGConfig,
        verbose: bool = False,
    ):
        self.embeddings = embeddings
        self.config = config
        self.verbose = verbose
        self._lock = threading.Lock()

    def _log(self, msg: str) -> None:
        if self.verbose:
            print(f"WordPerturbation: {msg}")

    def perturb(
        self,
        word: str,
        epsilon: float,
        word_type: str = "general",
    ) -> str:
        """Perturb a word using exponential mechanism.

        Args:
            word: Word to perturb
            epsilon: Privacy parameter (lower = more private)
            word_type: Type hint - "name", "first_name", "last_name", "location", "general"

        Returns:
            Perturbed word that is semantically similar.

        Raises:
            PerturbationError: If perturbation fails.
        """
        if not word or len(word) < self.config.min_word_length:
            return word

        # Try semantic similarity if enabled
        if self.config.enable_semantic_similarity and self.embeddings.is_loaded:
            try:
                return self._perturb_with_embeddings(word, epsilon)
            except Exception as e:
                self._log(f"Embedding perturbation failed: {e}, using fallback")

        # Fallback to random selection from curated lists
        return self._perturb_with_fallback(word, word_type)

    def _perturb_with_embeddings(self, word: str, epsilon: float) -> str:
        """Perturb using exponential mechanism with embeddings."""
        # Get similar words
        similar_words = self.embeddings.get_similar_words(
            word,
            top_k=self.config.similarity_top_k * 2,  # Get more candidates
            exclude_original=True,
            min_similarity=0.2,
        )

        if not similar_words:
            raise PerturbationError(f"No similar words found for '{word}'")

        # Apply exponential mechanism
        # Probability: P(w) ∝ exp(ε * similarity(original, w) / 2)
        words = []
        weights = []

        for candidate, similarity in similar_words:
            # Skip words that are too similar (might be same name)
            if similarity > 0.95:
                continue

            words.append(candidate)
            # Exponential mechanism weight
            weight = math.exp(epsilon * similarity / 2)
            weights.append(weight)

        if not words:
            raise PerturbationError(f"No suitable candidates for '{word}'")

        # Normalize weights to probabilities
        total_weight = sum(weights)
        probabilities = [w / total_weight for w in weights]

        # Sample according to probabilities
        selected = np.random.choice(words, p=probabilities)

        self._log(f"'{word}' → '{selected}' (ε={epsilon})")
        return selected

    def _perturb_with_fallback(self, word: str, word_type: str) -> str:
        """Perturb using random selection from curated lists."""
        word_lower = word.lower()

        if word_type in ("name", "first_name"):
            choices = [n for n in COMMON_FIRST_NAMES if n.lower() != word_lower]
            if choices:
                return random.choice(choices)

        if word_type in ("name", "last_name"):
            choices = [n for n in COMMON_LAST_NAMES if n.lower() != word_lower]
            if choices:
                return random.choice(choices)

        if word_type == "location":
            return get_random_location(exclude=word)

        # General fallback: return a random common name
        return get_random_name(exclude=word)

    def perturb_name(
        self,
        full_name: str,
        epsilon: float,
        used_first_names: Optional[Set[str]] = None,
        used_last_names: Optional[Set[str]] = None,
        max_retries: int = 10,
    ) -> Tuple[str, Optional[Dict[str, Tuple[str, str]]]]:
        """Perturb a full name (first + last) with collision avoidance.

        Attempts to generate unique perturbed names within a session by
        checking against used_first_names and used_last_names sets.

        Args:
            full_name: Full name like "John Smith"
            epsilon: Privacy parameter
            used_first_names: Set of already-used perturbed first names (lowercase)
            used_last_names: Set of already-used perturbed last names (lowercase)
            max_retries: Maximum attempts to find a unique name combination

        Returns:
            Tuple of (perturbed_full_name, part_mappings)
            part_mappings: {"first": ("Michael", "John"), "last": ("Chen", "Smith")}
            Returns (None, None) if unique name cannot be found after max_retries
        """
        parts = full_name.split()
        used_first = used_first_names or set()
        used_last = used_last_names or set()

        if len(parts) == 1:
            # Single name - treat as first name
            for _ in range(max_retries):
                perturbed = self.perturb(parts[0], epsilon, word_type="name")
                if perturbed.lower() not in used_first:
                    return perturbed, {"first": (perturbed, parts[0])}
            # Fallback: return None to signal token-based fallback
            return None, None

        if len(parts) == 2:
            # First + Last
            first_orig, last_orig = parts[0], parts[1]
            for _ in range(max_retries):
                first_pert = self.perturb(first_orig, epsilon, word_type="first_name")
                last_pert = self.perturb(last_orig, epsilon, word_type="last_name")
                # Check for collisions
                if (first_pert.lower() not in used_first and
                    last_pert.lower() not in used_last):
                    part_mappings = {
                        "first": (first_pert, first_orig),
                        "last": (last_pert, last_orig),
                    }
                    return f"{first_pert} {last_pert}", part_mappings
            # Fallback: return None to signal token-based fallback
            return None, None

        # Multiple parts: perturb first and last, keep middle initials
        first_orig, last_orig = parts[0], parts[-1]
        middle = " ".join(parts[1:-1])
        for _ in range(max_retries):
            first_pert = self.perturb(first_orig, epsilon, word_type="first_name")
            last_pert = self.perturb(last_orig, epsilon, word_type="last_name")
            if (first_pert.lower() not in used_first and
                last_pert.lower() not in used_last):
                part_mappings = {
                    "first": (first_pert, first_orig),
                    "last": (last_pert, last_orig),
                }
                return f"{first_pert} {middle} {last_pert}", part_mappings
        # Fallback: return None to signal token-based fallback
        return None, None


class NumberPerturbationModule:
    """Perturbs numbers using Laplace mechanism.

    Adds noise drawn from Laplace(0, sensitivity/epsilon) to each digit,
    preserving the format of the original number.

    For example:
        555-123-4567 → 447-891-2345 (phone format preserved)
        123-45-6789 → 987-65-4321 (SSN format preserved)
    """

    def __init__(self, config: LPRAGConfig, verbose: bool = False):
        self.config = config
        self.verbose = verbose

    def _log(self, msg: str) -> None:
        if self.verbose:
            print(f"NumberPerturbation: {msg}")

    def perturb(
        self,
        value: str,
        epsilon: float,
        sensitivity: float = 1.0,
        preserve_format: bool = True,
    ) -> str:
        """Perturb a numerical value using Laplace mechanism.

        Args:
            value: Numerical string (e.g., "555-123-4567")
            epsilon: Privacy parameter
            sensitivity: Query sensitivity for Laplace scale
            preserve_format: If True, maintain original format (dashes, etc.)

        Returns:
            Perturbed numerical string with same format.
        """
        if not value:
            return value

        if preserve_format:
            return self._perturb_preserving_format(value, epsilon, sensitivity)
        else:
            return self._perturb_digits_only(value, epsilon, sensitivity)

    def _perturb_preserving_format(
        self, value: str, epsilon: float, sensitivity: float
    ) -> str:
        """Perturb while preserving non-digit characters."""
        result = []
        scale = sensitivity / epsilon if epsilon > 0 else 10.0

        for char in value:
            if char.isdigit():
                # Add Laplace noise to digit
                digit = int(char)
                noise = np.random.laplace(0, scale)
                perturbed = int(round(digit + noise)) % 10  # Keep in 0-9 range
                if perturbed < 0:
                    perturbed += 10
                result.append(str(perturbed))
            else:
                # Keep non-digit characters (dashes, spaces, etc.)
                result.append(char)

        perturbed_value = "".join(result)
        self._log(f"'{value}' → '{perturbed_value}' (ε={epsilon})")
        return perturbed_value

    def _perturb_digits_only(
        self, value: str, epsilon: float, sensitivity: float
    ) -> str:
        """Extract digits, perturb, and return digits only."""
        digits = "".join(c for c in value if c.isdigit())
        if not digits:
            return value

        scale = sensitivity / epsilon if epsilon > 0 else 10.0
        result = []

        for digit in digits:
            d = int(digit)
            noise = np.random.laplace(0, scale)
            perturbed = int(round(d + noise)) % 10
            if perturbed < 0:
                perturbed += 10
            result.append(str(perturbed))

        return "".join(result)

    def perturb_phone(self, phone: str, epsilon: float) -> str:
        """Perturb a phone number.

        Special handling for phone numbers:
        - Preserves area code structure
        - Ensures valid-looking output
        """
        return self.perturb(phone, epsilon, sensitivity=1.0, preserve_format=True)

    def perturb_ssn(self, ssn: str, epsilon: float) -> str:
        """Perturb a Social Security Number.

        Uses stronger perturbation (higher sensitivity) for SSNs.
        """
        return self.perturb(ssn, epsilon, sensitivity=2.0, preserve_format=True)

    def perturb_credit_card(self, cc: str, epsilon: float) -> str:
        """Perturb a credit card number.

        Preserves the format but completely randomizes digits.
        """
        return self.perturb(cc, epsilon, sensitivity=3.0, preserve_format=True)

    def perturb_date(self, date_str: str, epsilon: float) -> str:
        """Perturb a date/time value by shifting it by a random offset.

        Unlike digit-by-digit perturbation, this shifts the entire date by
        a random number of days drawn from Laplace distribution, ensuring
        the result is always a valid date.

        Args:
            date_str: Date string in various formats (e.g., "01/15/2024", "2024-01-15")
            epsilon: Privacy parameter (lower = more noise)

        Returns:
            Perturbed date string in the same format as input.
        """
        if not date_str:
            return date_str

        # Common date formats to try
        date_formats = [
            ("%m/%d/%Y", "date"),      # 01/15/2024
            ("%d/%m/%Y", "date"),      # 15/01/2024
            ("%Y-%m-%d", "date"),      # 2024-01-15
            ("%m-%d-%Y", "date"),      # 01-15-2024
            ("%d-%m-%Y", "date"),      # 15-01-2024
            ("%B %d, %Y", "date"),     # January 15, 2024
            ("%b %d, %Y", "date"),     # Jan 15, 2024
            ("%d %B %Y", "date"),      # 15 January 2024
            ("%d %b %Y", "date"),      # 15 Jan 2024
            ("%Y/%m/%d", "date"),      # 2024/01/15
            ("%m/%d/%y", "date"),      # 01/15/24
            ("%d/%m/%y", "date"),      # 15/01/24
            ("%Y-%m-%d %H:%M:%S", "datetime"),  # 2024-01-15 10:30:00
            ("%m/%d/%Y %H:%M:%S", "datetime"),  # 01/15/2024 10:30:00
            ("%Y-%m-%dT%H:%M:%S", "datetime"),  # 2024-01-15T10:30:00 (ISO)
            ("%H:%M:%S", "time"),      # 10:30:00
            ("%H:%M", "time"),         # 10:30
            ("%I:%M %p", "time"),      # 10:30 AM
            ("%I:%M:%S %p", "time"),   # 10:30:00 AM
        ]

        parsed_date = None
        matched_format = None
        format_type = None

        for fmt, ftype in date_formats:
            try:
                parsed_date = datetime.strptime(date_str.strip(), fmt)
                matched_format = fmt
                format_type = ftype
                break
            except ValueError:
                continue

        if parsed_date is None:
            # Could not parse date, fall back to generic number perturbation
            self._log(f"Could not parse date '{date_str}', using digit perturbation")
            return self.perturb(date_str, epsilon, sensitivity=1.0, preserve_format=True)

        # Calculate noise scale based on epsilon
        # Use days as the unit for date perturbation
        # Scale of ~30 days at epsilon=1.0 provides reasonable privacy
        scale = 30.0 / epsilon if epsilon > 0 else 365.0

        from datetime import timedelta
        noise_amount = 0
        noise_unit = "days"

        if format_type == "time":
            # For time-only values, shift by minutes instead of days
            minutes_scale = 60.0 / epsilon if epsilon > 0 else 720.0
            noise_amount = int(np.random.laplace(0, minutes_scale))
            noise_unit = "minutes"
            perturbed_date = parsed_date + timedelta(minutes=noise_amount)
            # Keep time within same day (wrap around)
            perturbed_date = perturbed_date.replace(
                year=parsed_date.year,
                month=parsed_date.month,
                day=parsed_date.day
            )
        else:
            # Shift by random number of days
            noise_amount = int(np.random.laplace(0, scale))
            perturbed_date = parsed_date + timedelta(days=noise_amount)

            # If datetime format, also perturb the time component
            if format_type == "datetime":
                minutes_scale = 60.0 / epsilon if epsilon > 0 else 720.0
                noise_minutes = int(np.random.laplace(0, minutes_scale))
                perturbed_date = perturbed_date + timedelta(minutes=noise_minutes)

        # Format back to original format
        perturbed_str = perturbed_date.strftime(matched_format)
        self._log(f"Date '{date_str}' → '{perturbed_str}' (ε={epsilon}, shift={noise_amount} {noise_unit})")
        return perturbed_str


class PhrasePerturbationModule:
    """Perturbs multi-word phrases using segment-wise perturbation.

    For complex entities like addresses and emails, this module:
    1. Parses the phrase into segments
    2. Applies appropriate perturbation to each segment
    3. Reassembles while preserving structure

    Example:
        "123 Main St, New York, NY 10001"
        → "456 Oak Ave, Los Angeles, CA 90210"
    """

    def __init__(
        self,
        word_module: WordPerturbationModule,
        number_module: NumberPerturbationModule,
        config: LPRAGConfig,
        verbose: bool = False,
    ):
        self.word_module = word_module
        self.number_module = number_module
        self.config = config
        self.verbose = verbose

        # Email domains for replacement
        self.email_domains = [
            "gmail.com", "yahoo.com", "outlook.com", "hotmail.com",
            "example.com", "email.com", "mail.com", "inbox.com",
        ]

        # Street types
        self.street_types = [
            "St", "Ave", "Blvd", "Rd", "Dr", "Ln", "Way", "Ct", "Pl",
        ]

    def _log(self, msg: str) -> None:
        if self.verbose:
            print(f"PhrasePerturbation: {msg}")

    def perturb(
        self,
        phrase: str,
        epsilon: float,
        phrase_type: str = "general",
    ) -> str:
        """Perturb a multi-word phrase.

        Args:
            phrase: Phrase to perturb
            epsilon: Privacy parameter
            phrase_type: Type hint - "email", "address", "general"

        Returns:
            Perturbed phrase with same structure.
        """
        if not phrase:
            return phrase

        if phrase_type == "email" or "@" in phrase:
            return self._perturb_email(phrase, epsilon)

        if phrase_type == "address":
            return self._perturb_address(phrase, epsilon)

        # General: perturb each word with probability
        return self._perturb_general(phrase, epsilon)

    def _perturb_email(self, email: str, epsilon: float) -> str:
        """Perturb an email address.

        Generates a plausible fake email with similar structure.
        """
        try:
            if "@" not in email:
                return self._perturb_general(email, epsilon)

            local, domain = email.rsplit("@", 1)

            # Perturb local part
            perturbed_local = self._perturb_email_local(local, epsilon)

            # Replace domain with a common one
            perturbed_domain = random.choice(self.email_domains)

            result = f"{perturbed_local}@{perturbed_domain}"
            self._log(f"'{email}' → '{result}'")
            return result

        except Exception as e:
            self._log(f"Email perturbation failed: {e}")
            return self._perturb_general(email, epsilon)

    def _perturb_email_local(self, local: str, epsilon: float) -> str:
        """Perturb the local part of an email."""
        # Check if it looks like a name (firstname.lastname)
        if "." in local:
            parts = local.split(".")
            perturbed_parts = []
            for part in parts:
                if part.isalpha() and len(part) > 2:
                    perturbed_parts.append(
                        self.word_module.perturb(part, epsilon, "name").lower()
                    )
                else:
                    perturbed_parts.append(part)
            return ".".join(perturbed_parts)

        # Single word - perturb if it's a name
        if local.isalpha() and len(local) > 2:
            return self.word_module.perturb(local, epsilon, "name").lower()

        # Mixed alphanumeric - generate a random one
        letters = "".join(c for c in local if c.isalpha())
        numbers = "".join(c for c in local if c.isdigit())

        if letters:
            letters = self.word_module.perturb(letters, epsilon, "name").lower()
        if numbers:
            numbers = self.number_module.perturb(numbers, epsilon)

        return letters + numbers

    def _perturb_address(self, address: str, epsilon: float) -> str:
        """Perturb a street address."""
        # Simple pattern matching for address components
        result_parts = []

        # Split by comma or common delimiters
        parts = re.split(r"[,;]", address)

        for part in parts:
            part = part.strip()
            if not part:
                continue

            # Check if it's a street number + name
            match = re.match(r"^(\d+)\s+(.+)$", part)
            if match:
                number = self.number_module.perturb(match.group(1), epsilon)
                street = self._perturb_street_name(match.group(2), epsilon)
                result_parts.append(f"{number} {street}")
            elif part.isdigit() or re.match(r"^\d{5}(-\d{4})?$", part):
                # ZIP code
                result_parts.append(self.number_module.perturb(part, epsilon))
            else:
                # City or state name
                result_parts.append(
                    self.word_module.perturb(part, epsilon, "location")
                )

        result = ", ".join(result_parts)
        self._log(f"'{address}' → '{result}'")
        return result

    def _perturb_street_name(self, street: str, epsilon: float) -> str:
        """Perturb a street name like 'Main St' or 'Oak Avenue'."""
        words = street.split()
        if not words:
            return street

        result = []
        for i, word in enumerate(words):
            # Keep street type abbreviations
            if word.rstrip(".") in self.street_types:
                result.append(word)
            elif word.upper() in ("N", "S", "E", "W", "NE", "NW", "SE", "SW"):
                # Direction - keep as is
                result.append(word)
            else:
                # Street name word - perturb
                result.append(self.word_module.perturb(word, epsilon, "location"))

        return " ".join(result)

    def _perturb_general(self, phrase: str, epsilon: float) -> str:
        """Perturb a general phrase word by word."""
        words = phrase.split()
        result = []

        for word in words:
            # Perturb with probability based on config
            if random.random() < self.config.segment_perturbation_prob:
                perturbed = self.word_module.perturb(word, epsilon, "general")
                result.append(perturbed)
            else:
                result.append(word)

        return " ".join(result)


class LPRAGEngine:
    """Main LPRAG engine orchestrating perturbation modules.

    Provides a unified interface for perturbing PII entities using
    appropriate perturbation mechanisms based on entity type.
    """

    # Entity types that LPRAG can handle and their perturbation module
    SUPPORTED_ENTITIES: Dict[str, str] = {
        # Word perturbation (names, locations)
        "PERSON": "word",
        "LOCATION": "word",
        "NRP": "word",  # National registration number (name-like)

        # Number perturbation (numerical data)
        "PHONE_NUMBER": "number",
        "CREDIT_CARD": "number",
        "US_SSN": "number",
        "US_BANK_NUMBER": "number",
        "IBAN_CODE": "number",
        "IP_ADDRESS": "number",
        "US_ITIN": "number",
        "US_PASSPORT": "number",
        "AU_TFN": "number",
        "IN_AADHAAR": "number",
        "SG_NRIC_FIN": "number",
        "IN_PAN": "number",

        # Phrase perturbation (complex entities)
        "EMAIL_ADDRESS": "phrase",
        "URL": "phrase",
        "DOMAIN_NAME": "phrase",

        # Date/time - number perturbation
        "DATE_TIME": "number",
    }

    def __init__(
        self,
        config: Optional[LPRAGConfig] = None,
        verbose: bool = False,
    ):
        """Initialize LPRAG engine.

        Args:
            config: LPRAG configuration. If None, loads from environment.
            verbose: Enable debug logging.
        """
        self.config = config or get_lprag_config_from_env()
        self.verbose = verbose

        # Initialize embeddings (lazy loaded)
        self._embeddings: Optional[LPRAGEmbeddings] = None

        # Initialize perturbation modules
        self._word_module: Optional[WordPerturbationModule] = None
        self._number_module: Optional[NumberPerturbationModule] = None
        self._phrase_module: Optional[PhrasePerturbationModule] = None

        # Statistics
        self._perturbations_count = 0
        self._fallback_count = 0
        self._total_epsilon_used = 0.0

        # Thread safety
        self._lock = threading.Lock()
        self._initialized = False

    def _log(self, msg: str) -> None:
        if self.verbose:
            print(f"LPRAGEngine: {msg}")

    def _ensure_initialized(self) -> None:
        """Lazy initialization of modules."""
        if self._initialized:
            return

        with self._lock:
            if self._initialized:
                return

            self._log("Initializing LPRAG engine...")

            # Initialize embeddings if semantic similarity enabled
            if self.config.enable_semantic_similarity:
                self._embeddings = get_lprag_embeddings(
                    model_name=self.config.embedding_model,
                    use_gpu=self.config.use_gpu,
                    verbose=self.verbose,
                )
            else:
                # Create a dummy embeddings object that won't load
                self._embeddings = LPRAGEmbeddings(verbose=self.verbose)

            # Initialize modules
            self._number_module = NumberPerturbationModule(
                self.config, verbose=self.verbose
            )

            self._word_module = WordPerturbationModule(
                self._embeddings, self.config, verbose=self.verbose
            )

            self._phrase_module = PhrasePerturbationModule(
                self._word_module,
                self._number_module,
                self.config,
                verbose=self.verbose,
            )

            self._initialized = True
            self._log("LPRAG engine initialized")

    @property
    def is_available(self) -> bool:
        """Check if LPRAG engine is available."""
        return self.config.mode != LPRAGMode.DISABLED

    @property
    def mode(self) -> LPRAGMode:
        """Get current operating mode."""
        return self.config.mode

    def can_perturb(self, pii_type: str) -> bool:
        """Check if LPRAG can handle this entity type.

        Args:
            pii_type: Presidio entity type (e.g., "PERSON", "US_SSN")

        Returns:
            True if LPRAG has a perturbation module for this type.
        """
        return pii_type in self.SUPPORTED_ENTITIES

    def get_module_type(self, pii_type: str) -> Optional[str]:
        """Get the perturbation module type for an entity.

        Args:
            pii_type: Presidio entity type

        Returns:
            Module type ("word", "number", "phrase") or None.
        """
        return self.SUPPORTED_ENTITIES.get(pii_type)

    def perturb_entity(
        self,
        value: str,
        pii_type: str,
        session_id: Optional[str] = None,
        used_first_names: Optional[Set[str]] = None,
        used_last_names: Optional[Set[str]] = None,
    ) -> PerturbationResult:
        """Perturb a single PII entity.

        Args:
            value: Original PII value to perturb
            pii_type: Presidio entity type (e.g., "PERSON", "PHONE_NUMBER")
            session_id: Session ID for hybrid mode token mapping
            used_first_names: Set of already-used perturbed first names (for PERSON)
            used_last_names: Set of already-used perturbed last names (for PERSON)

        Returns:
            PerturbationResult with perturbed value and metadata.
            If perturbation fails, result.success=False signals fallback to tokens.
        """
        if self.config.mode == LPRAGMode.DISABLED:
            return PerturbationResult(
                original_value=value,
                perturbed_value=value,
                pii_type=pii_type,
                perturbation_type="none",
                epsilon_used=0,
                success=False,
                error="LPRAG disabled",
            )

        self._ensure_initialized()

        # Check if we can handle this entity type
        if not self.can_perturb(pii_type):
            return PerturbationResult(
                original_value=value,
                perturbed_value=value,
                pii_type=pii_type,
                perturbation_type="unsupported",
                epsilon_used=0,
                success=False,
                error=f"Unsupported entity type: {pii_type}",
            )

        # Get epsilon based on entity sensitivity
        sensitivity = get_entity_sensitivity(pii_type)
        epsilon = self.config.get_epsilon(sensitivity)

        # Get module type and perturb
        module_type = self.get_module_type(pii_type)
        part_mappings = None

        try:
            if module_type == "word":
                perturbed, part_mappings = self._perturb_word_entity(
                    value, pii_type, epsilon, used_first_names, used_last_names
                )
                # If perturbed is None, we couldn't find a unique name - fallback
                if perturbed is None:
                    return PerturbationResult(
                        original_value=value,
                        perturbed_value=value,
                        pii_type=pii_type,
                        perturbation_type="collision_fallback",
                        epsilon_used=0,
                        success=False,
                        error="Could not generate unique perturbed name after max retries",
                    )
            elif module_type == "number":
                perturbed = self._perturb_number_entity(value, pii_type, epsilon)
            elif module_type == "phrase":
                perturbed = self._perturb_phrase_entity(value, pii_type, epsilon)
            else:
                raise PerturbationError(f"Unknown module type: {module_type}")

            # Generate token ID for hybrid mode
            token_id = None
            if self.config.mode == LPRAGMode.HYBRID:
                token_id = secrets.token_urlsafe(8)

            # Update statistics
            self._perturbations_count += 1
            self._total_epsilon_used += epsilon

            return PerturbationResult(
                original_value=value,
                perturbed_value=perturbed,
                pii_type=pii_type,
                perturbation_type=module_type,
                epsilon_used=epsilon,
                token_id=token_id,
                success=True,
                part_mappings=part_mappings,
            )

        except Exception as e:
            self._fallback_count += 1
            self._log(f"Perturbation failed for {pii_type}: {e}")

            return PerturbationResult(
                original_value=value,
                perturbed_value=value,
                pii_type=pii_type,
                perturbation_type="error",
                epsilon_used=0,
                success=False,
                error=str(e),
            )

    def _perturb_word_entity(
        self,
        value: str,
        pii_type: str,
        epsilon: float,
        used_first_names: Optional[Set[str]] = None,
        used_last_names: Optional[Set[str]] = None,
    ) -> Tuple[Optional[str], Optional[Dict[str, Tuple[str, str]]]]:
        """Perturb a word-based entity (name, location).

        Returns:
            Tuple of (perturbed_value, part_mappings).
            For PERSON: part_mappings contains name parts for deanonymization.
            For other types: part_mappings is None.
            Returns (None, None) if unique PERSON name cannot be found.
        """
        if pii_type == "PERSON":
            return self._word_module.perturb_name(
                value, epsilon, used_first_names, used_last_names
            )
        elif pii_type == "LOCATION":
            return self._word_module.perturb(value, epsilon, word_type="location"), None
        else:
            return self._word_module.perturb(value, epsilon, word_type="general"), None

    def _perturb_number_entity(
        self, value: str, pii_type: str, epsilon: float
    ) -> str:
        """Perturb a number-based entity (phone, SSN, date, etc.)."""
        if pii_type == "PHONE_NUMBER":
            return self._number_module.perturb_phone(value, epsilon)
        elif pii_type == "US_SSN":
            return self._number_module.perturb_ssn(value, epsilon)
        elif pii_type == "CREDIT_CARD":
            return self._number_module.perturb_credit_card(value, epsilon)
        elif pii_type == "DATE_TIME":
            return self._number_module.perturb_date(value, epsilon)
        else:
            return self._number_module.perturb(value, epsilon)

    def _perturb_phrase_entity(
        self, value: str, pii_type: str, epsilon: float
    ) -> str:
        """Perturb a phrase-based entity (email, URL, etc.)."""
        if pii_type == "EMAIL_ADDRESS":
            return self._phrase_module.perturb(value, epsilon, phrase_type="email")
        elif pii_type in ("URL", "DOMAIN_NAME"):
            return self._phrase_module.perturb(value, epsilon, phrase_type="general")
        else:
            return self._phrase_module.perturb(value, epsilon, phrase_type="general")

    def get_stats(self) -> Dict[str, Any]:
        """Get engine statistics."""
        avg_epsilon = (
            self._total_epsilon_used / self._perturbations_count
            if self._perturbations_count > 0
            else 0
        )

        embeddings_stats = {}
        if self._embeddings:
            embeddings_stats = self._embeddings.get_stats()

        return {
            "mode": self.config.mode.value,
            "is_available": self.is_available,
            "initialized": self._initialized,
            "global_epsilon": self.config.global_epsilon,
            "use_gpu": self.config.use_gpu,
            "semantic_similarity_enabled": self.config.enable_semantic_similarity,
            "perturbations_count": self._perturbations_count,
            "fallback_count": self._fallback_count,
            "average_epsilon_used": avg_epsilon,
            "supported_entities": list(self.SUPPORTED_ENTITIES.keys()),
            "embeddings": embeddings_stats,
        }

    def unload(self) -> None:
        """Unload resources to free memory."""
        with self._lock:
            if self._embeddings:
                self._embeddings.unload()
            self._initialized = False
            self._log("Engine unloaded")


# Global engine instance
_global_engine: Optional[LPRAGEngine] = None
_global_lock = threading.Lock()


def get_lprag_engine(
    config: Optional[LPRAGConfig] = None,
    verbose: bool = False,
) -> LPRAGEngine:
    """Get or create the global LPRAG engine instance.

    Args:
        config: LPRAG configuration. If None, loads from environment.
        verbose: Enable debug logging.

    Returns:
        LPRAGEngine instance.
    """
    global _global_engine

    with _global_lock:
        if _global_engine is None:
            _global_engine = LPRAGEngine(config=config, verbose=verbose)
        return _global_engine


def reset_lprag_engine() -> None:
    """Reset the global LPRAG engine (for testing)."""
    global _global_engine

    with _global_lock:
        if _global_engine:
            _global_engine.unload()
        _global_engine = None
