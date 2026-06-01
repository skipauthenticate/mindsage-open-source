"""Named Entity Recognition using spaCy.

Reuses the spaCy model already loaded for PII protection.
No additional memory required.
"""

from typing import List, Dict, Set, Optional, Any


class SpaCyEntityExtractor:
    """Extract named entities using spaCy.

    Leverages the en_core_web_sm model that is already loaded for PII detection,
    so this adds no additional memory overhead.

    Entity type mapping from spaCy to our categories:
    - PERSON -> persons
    - ORG -> organizations
    - GPE (geopolitical entity), LOC, FAC -> locations
    - DATE -> dates
    - TIME -> times
    - MONEY, QUANTITY, PERCENT -> quantities
    """

    ENTITY_TYPE_MAP = {
        "PERSON": "persons",
        "ORG": "organizations",
        "GPE": "locations",
        "LOC": "locations",
        "FAC": "locations",
        "DATE": "dates",
        "TIME": "times",
        "MONEY": "quantities",
        "QUANTITY": "quantities",
        "PERCENT": "quantities",
    }

    def __init__(self, spacy_model: Optional[Any] = None, verbose: bool = False):
        """Initialize the entity extractor.

        Args:
            spacy_model: Pre-loaded spaCy model instance. If None, will load on first use.
            verbose: Whether to print debug information.
        """
        self._nlp = spacy_model
        self.verbose = verbose
        self._load_attempted = False

    def _ensure_model(self) -> bool:
        """Ensure spaCy model is loaded.

        Returns:
            True if model is available, False otherwise.
        """
        if self._nlp is not None:
            return True

        if self._load_attempted:
            return False

        self._load_attempted = True

        try:
            import spacy
            self._nlp = spacy.load("en_core_web_sm")
            if self.verbose:
                print("SpaCyEntityExtractor: Loaded en_core_web_sm model")
            return True
        except Exception as e:
            if self.verbose:
                print(f"SpaCyEntityExtractor: Failed to load spaCy model: {e}")
            return False

    def set_model(self, spacy_model: Any) -> None:
        """Set or update the spaCy model instance.

        Args:
            spacy_model: A loaded spaCy model.
        """
        self._nlp = spacy_model

    def is_available(self) -> bool:
        """Check if the extractor is ready to use."""
        return self._ensure_model()

    def extract_entities(
        self,
        text: str,
        max_per_category: int = 10,
        max_text_length: int = 10000
    ) -> Dict[str, List[str]]:
        """Extract named entities from text.

        Args:
            text: Text to extract entities from.
            max_per_category: Maximum entities per category.
            max_text_length: Maximum text length to process (for performance).

        Returns:
            Dictionary with entity categories as keys and lists of entities as values.
            Categories: persons, organizations, locations, dates, times, quantities.
        """
        if not self._ensure_model():
            return self._empty_result()

        # Truncate text for performance
        text_to_process = text[:max_text_length] if len(text) > max_text_length else text

        try:
            doc = self._nlp(text_to_process)
        except Exception as e:
            if self.verbose:
                print(f"SpaCyEntityExtractor: Processing error: {e}")
            return self._empty_result()

        entities: Dict[str, Set[str]] = {
            "persons": set(),
            "organizations": set(),
            "locations": set(),
            "dates": set(),
            "times": set(),
            "quantities": set(),
        }

        for ent in doc.ents:
            category = self.ENTITY_TYPE_MAP.get(ent.label_)
            if category:
                text_clean = ent.text.strip()
                # Filter out very short or very long entities
                if 2 <= len(text_clean) <= 100:
                    entities[category].add(text_clean)

        # Convert sets to sorted lists (by frequency in text for relevance)
        result = {}
        for key, values in entities.items():
            value_list = list(values)
            # Sort by frequency in text (higher count = more relevant)
            value_list.sort(key=lambda v: text.lower().count(v.lower()), reverse=True)
            result[key] = value_list[:max_per_category]

        return result

    def extract_persons(self, text: str, max_count: int = 10) -> List[str]:
        """Extract person names from text.

        Args:
            text: Text to extract from.
            max_count: Maximum number of persons to return.

        Returns:
            List of person names.
        """
        result = self.extract_entities(text, max_per_category=max_count)
        return result.get("persons", [])

    def extract_organizations(self, text: str, max_count: int = 10) -> List[str]:
        """Extract organization names from text.

        Args:
            text: Text to extract from.
            max_count: Maximum number of organizations to return.

        Returns:
            List of organization names.
        """
        result = self.extract_entities(text, max_per_category=max_count)
        return result.get("organizations", [])

    def extract_locations(self, text: str, max_count: int = 10) -> List[str]:
        """Extract location names from text.

        Args:
            text: Text to extract from.
            max_count: Maximum number of locations to return.

        Returns:
            List of location names.
        """
        result = self.extract_entities(text, max_per_category=max_count)
        return result.get("locations", [])

    def extract_dates(self, text: str, max_count: int = 10) -> List[str]:
        """Extract date mentions from text.

        Args:
            text: Text to extract from.
            max_count: Maximum number of dates to return.

        Returns:
            List of date strings.
        """
        result = self.extract_entities(text, max_per_category=max_count)
        return result.get("dates", [])

    def _empty_result(self) -> Dict[str, List[str]]:
        """Return an empty result structure."""
        return {
            "persons": [],
            "organizations": [],
            "locations": [],
            "dates": [],
            "times": [],
            "quantities": [],
        }

    def __repr__(self) -> str:
        loaded = "loaded" if self._nlp is not None else "not loaded"
        return f"SpaCyEntityExtractor(model={loaded})"
