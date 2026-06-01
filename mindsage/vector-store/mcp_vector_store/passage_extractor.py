"""Passage extraction and query enhancement using embeddings and heuristics.

This module provides functionality to:
1. Extract relevant passages from documents based on a query
2. Extract key entities using spaCy NER
3. Generate structured metadata for search filtering

Optimized for edge devices - no LLM required.
"""

import re
from typing import List, Optional, Dict, Any, TYPE_CHECKING
from dataclasses import dataclass

if TYPE_CHECKING:
    from .ner_extractor import SpaCyEntityExtractor


@dataclass
class ExtractedPassage:
    """Result of passage extraction from a document."""
    excerpt: str
    relevance_reasoning: str
    confidence: float
    method: str  # "embedding_extract", "window", "full"


@dataclass
class QueryAnalysis:
    """Analysis of a search query to determine filtering/boosting strategy.

    Used by smart_search to automatically apply appropriate filters or boosts.
    """
    # Detected entities in the query
    persons: List[str]
    organizations: List[str]
    locations: List[str]
    technologies: List[str]
    dates: List[str]
    doc_type_hint: Optional[str]  # Inferred document type from query

    # Strategy recommendations
    use_person_filter: bool
    use_organization_filter: bool
    use_location_filter: bool
    use_technology_filter: bool
    use_doc_type_filter: bool

    # Confidence that these are filter-worthy (vs just boost-worthy)
    filter_confidence: float  # 0.0 = just boost, 1.0 = definitely filter

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "persons": self.persons,
            "organizations": self.organizations,
            "locations": self.locations,
            "technologies": self.technologies,
            "dates": self.dates,
            "doc_type_hint": self.doc_type_hint,
            "use_person_filter": self.use_person_filter,
            "use_organization_filter": self.use_organization_filter,
            "use_location_filter": self.use_location_filter,
            "use_technology_filter": self.use_technology_filter,
            "use_doc_type_filter": self.use_doc_type_filter,
            "filter_confidence": self.filter_confidence,
        }


@dataclass
class StructuredMetadata:
    """Structured metadata extracted from a document for search filtering and boosting.

    Categories:
    - persons: Named people (e.g., "John Smith", "Dr. Chen")
    - organizations: Companies, institutions (e.g., "Google", "MIT")
    - locations: Geographic places (e.g., "New York", "Building 5")
    - dates: Explicit dates (e.g., "January 15, 2024", "2023")
    - times: Time references (e.g., "3pm", "morning")
    - temporal_refs: Relative time references (e.g., "last week", "Q3 2024")
    - quantities: Numbers with context (e.g., "500 users", "$1M")
    - activities: Key actions/verbs (e.g., "deployed", "reviewed", "analyzed")
    - technologies: Programming languages, frameworks (e.g., "Python", "React")
    - document_type: Inferred document type (e.g., "meeting_notes", "code", "email")
    """
    persons: List[str]
    organizations: List[str]
    locations: List[str]
    dates: List[str]
    times: List[str]
    temporal_refs: List[str]
    quantities: List[str]
    activities: List[str]
    technologies: List[str]
    document_type: str
    extraction_method: str  # "heuristic", "spacy", or "hybrid"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "persons": self.persons,
            "organizations": self.organizations,
            "locations": self.locations,
            "dates": self.dates,
            "times": self.times,
            "temporal_refs": self.temporal_refs,
            "quantities": self.quantities,
            "activities": self.activities,
            "technologies": self.technologies,
            "document_type": self.document_type,
            "extraction_method": self.extraction_method,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StructuredMetadata":
        """Create from dictionary."""
        return cls(
            persons=data.get("persons", []),
            organizations=data.get("organizations", []),
            locations=data.get("locations", []),
            dates=data.get("dates", []),
            times=data.get("times", []),
            temporal_refs=data.get("temporal_refs", []),
            quantities=data.get("quantities", []),
            activities=data.get("activities", []),
            technologies=data.get("technologies", []),
            document_type=data.get("document_type", "unknown"),
            extraction_method=data.get("extraction_method", "unknown"),
        )

    def is_empty(self) -> bool:
        """Check if no metadata was extracted."""
        return (
            not self.persons and
            not self.organizations and
            not self.locations and
            not self.dates and
            not self.times and
            not self.temporal_refs and
            not self.quantities and
            not self.activities and
            not self.technologies and
            self.document_type == "unknown"
        )


class PassageExtractor:
    """Extract relevant passages from documents using embeddings and heuristics.

    This class provides methods to extract the most relevant portions
    of documents based on a user query, using:
    - Embedding similarity for query-relevant passage extraction
    - spaCy NER for entity extraction
    - Heuristic patterns for metadata extraction

    No LLM required - optimized for edge devices.
    """

    # Maximum characters to process at once
    MAX_CONTEXT_LENGTH = 1000

    # Maximum excerpt length to return
    MAX_EXCERPT_LENGTH = 500

    def __init__(
        self,
        embedding_model: Optional[Any] = None,
        ner_extractor: Optional["SpaCyEntityExtractor"] = None,
        verbose: bool = False,
        **kwargs  # Accept legacy parameters for backward compatibility
    ):
        """Initialize the passage extractor.

        Args:
            embedding_model: Embedding model for similarity-based extraction.
            ner_extractor: SpaCy entity extractor for NER.
            verbose: Whether to print debug information.
            **kwargs: Ignored (for backward compatibility).
        """
        self.embedding_model = embedding_model
        self._ner_extractor = ner_extractor
        self.verbose = verbose

        # Legacy compatibility - accept topic_labeler parameter
        if 'topic_labeler' in kwargs:
            topic_labeler = kwargs['topic_labeler']
            if topic_labeler:
                # Extract embedding model from topic_labeler if available
                if hasattr(topic_labeler, 'embedding_model') and topic_labeler.embedding_model:
                    self.embedding_model = topic_labeler.embedding_model
                elif self.embedding_model is None:
                    # topic_labeler presence indicates a model is available
                    # Use topic_labeler itself as a marker for availability
                    self.embedding_model = topic_labeler

    @property
    def ner_extractor(self) -> Optional["SpaCyEntityExtractor"]:
        """Get the NER extractor (lazy initialization)."""
        if self._ner_extractor is None:
            try:
                from .ner_extractor import SpaCyEntityExtractor
                self._ner_extractor = SpaCyEntityExtractor(verbose=self.verbose)
            except Exception as e:
                if self.verbose:
                    print(f"PassageExtractor: Failed to initialize NER: {e}")
        return self._ner_extractor

    def set_embedding_model(self, model: Any) -> None:
        """Set or update the embedding model."""
        self.embedding_model = model

    def set_ner_extractor(self, extractor: "SpaCyEntityExtractor") -> None:
        """Set or update the NER extractor."""
        self._ner_extractor = extractor

    def is_available(self) -> bool:
        """Check if enhanced extraction is available.

        Returns True when an embedding model is set, enabling
        similarity-based passage extraction (beyond basic heuristics).
        """
        return self.embedding_model is not None

    def extract_passage(
        self,
        query: str,
        document_text: str,
        max_excerpt_length: int = MAX_EXCERPT_LENGTH
    ) -> ExtractedPassage:
        """Extract the most relevant passage from a document.

        Uses embedding similarity when available, falls back to keyword matching.

        Args:
            query: The user's search query
            document_text: Full text of the document
            max_excerpt_length: Maximum length of the extracted excerpt

        Returns:
            ExtractedPassage with the relevant excerpt
        """
        # If document is short enough, return it entirely
        if len(document_text) <= max_excerpt_length:
            return ExtractedPassage(
                excerpt=document_text,
                relevance_reasoning="Document is short enough to include entirely",
                confidence=1.0,
                method="full"
            )

        # Try embedding-based extraction if available
        if self.embedding_model is not None:
            result = self._extract_with_embeddings(query, document_text, max_excerpt_length)
            if result.confidence > 0.3:
                return result

        # Fall back to window-based extraction
        return self._extract_window(query, document_text, max_excerpt_length)

    def _extract_with_embeddings(
        self,
        query: str,
        document_text: str,
        max_excerpt_length: int
    ) -> ExtractedPassage:
        """Extract passage using embedding similarity."""
        try:
            import numpy as np

            # Split document into sentences
            sentences = re.split(r'(?<=[.!?])\s+', document_text)
            sentences = [s.strip() for s in sentences if len(s.strip()) > 20]

            if not sentences:
                return self._extract_window(query, document_text, max_excerpt_length)

            # Get query embedding
            query_embedding = self.embedding_model.embed(query)
            if query_embedding is None:
                return self._extract_window(query, document_text, max_excerpt_length)

            # Handle batch results
            if hasattr(query_embedding, 'shape') and len(query_embedding.shape) > 1:
                query_embedding = query_embedding[0]
            query_embedding = np.array(query_embedding)

            # Get sentence embeddings (batch for efficiency)
            sentence_embeddings = []
            for sent in sentences:
                emb = self.embedding_model.embed(sent)
                if emb is not None:
                    if hasattr(emb, 'shape') and len(emb.shape) > 1:
                        emb = emb[0]
                    sentence_embeddings.append(np.array(emb))
                else:
                    sentence_embeddings.append(np.zeros_like(query_embedding))

            # Compute similarities
            similarities = []
            for sent_emb in sentence_embeddings:
                norm_q = np.linalg.norm(query_embedding)
                norm_s = np.linalg.norm(sent_emb)
                if norm_q > 0 and norm_s > 0:
                    sim = float(np.dot(query_embedding, sent_emb) / (norm_q * norm_s))
                else:
                    sim = 0.0
                similarities.append(sim)

            # Get top 3 sentences by similarity
            indexed_sims = list(enumerate(similarities))
            indexed_sims.sort(key=lambda x: x[1], reverse=True)
            top_indices = [idx for idx, _ in indexed_sims[:3]]

            # Sort by original position for coherence
            top_indices.sort()

            # Build excerpt from top sentences
            excerpt_parts = [sentences[i] for i in top_indices]
            excerpt = ' '.join(excerpt_parts)

            # Truncate if needed
            if len(excerpt) > max_excerpt_length:
                excerpt = excerpt[:max_excerpt_length].rstrip() + "..."

            avg_similarity = np.mean([similarities[i] for i in top_indices])

            return ExtractedPassage(
                excerpt=excerpt,
                relevance_reasoning=f"Top sentences by embedding similarity (avg: {avg_similarity:.2f})",
                confidence=float(avg_similarity),
                method="embedding_extract"
            )

        except Exception as e:
            if self.verbose:
                print(f"PassageExtractor: Embedding extraction failed: {e}")
            return self._extract_window(query, document_text, max_excerpt_length)

    def _extract_window(
        self,
        query: str,
        document_text: str,
        max_excerpt_length: int
    ) -> ExtractedPassage:
        """Extract passage using keyword matching and windowing.

        Falls back to this method when embedding extraction is not available.
        """
        # Tokenize query into keywords
        query_words = set(re.findall(r'\b\w+\b', query.lower()))
        query_words = {w for w in query_words if len(w) > 2}  # Filter short words

        # Find sentences with query terms
        sentences = re.split(r'(?<=[.!?])\s+', document_text)
        scored_sentences = []

        for i, sentence in enumerate(sentences):
            sentence_lower = sentence.lower()
            score = sum(1 for word in query_words if word in sentence_lower)
            if score > 0:
                scored_sentences.append((i, sentence, score))

        # If no matching sentences, return first portion
        if not scored_sentences:
            excerpt = document_text[:max_excerpt_length]
            if len(document_text) > max_excerpt_length:
                # Try to end at sentence boundary
                last_period = excerpt.rfind('.')
                if last_period > max_excerpt_length // 2:
                    excerpt = excerpt[:last_period + 1]
                else:
                    excerpt = excerpt.rstrip() + "..."

            return ExtractedPassage(
                excerpt=excerpt,
                relevance_reasoning="No query terms found; returning document start",
                confidence=0.3,
                method="window"
            )

        # Sort by score and build excerpt around best matches
        scored_sentences.sort(key=lambda x: x[2], reverse=True)
        best_idx = scored_sentences[0][0]

        # Build context window around best sentence
        start_idx = max(0, best_idx - 1)
        end_idx = min(len(sentences), best_idx + 3)

        excerpt_sentences = sentences[start_idx:end_idx]
        excerpt = ' '.join(excerpt_sentences)

        # Truncate if still too long
        if len(excerpt) > max_excerpt_length:
            excerpt = excerpt[:max_excerpt_length].rstrip() + "..."

        return ExtractedPassage(
            excerpt=excerpt,
            relevance_reasoning=f"Found {scored_sentences[0][2]} query terms in context",
            confidence=min(0.7, 0.3 + scored_sentences[0][2] * 0.1),
            method="window"
        )

    def extract_key_sentences(
        self,
        text: str,
        max_sentences: int = 3
    ) -> List[str]:
        """Extract key sentences from a document at storage time.

        This method extracts the most important sentences from a document
        without requiring a specific query. Uses heuristics with optional
        embedding-based diversity selection.

        Args:
            text: Document text to extract from
            max_sentences: Maximum number of key sentences to extract

        Returns:
            List of key sentence strings
        """
        # For very short documents, return as single passage
        if len(text) < 200:
            return [text.strip()]

        # For large documents, use chunked extraction
        if len(text) > self.MAX_CONTEXT_LENGTH:
            return self._extract_key_sentences_chunked(text, max_sentences)

        # Use heuristic extraction with optional embedding diversity
        return self._extract_key_sentences_heuristic(text, max_sentences)

    def _extract_key_sentences_chunked(
        self,
        text: str,
        max_sentences: int
    ) -> List[str]:
        """Extract key sentences from large documents using chunking."""
        # Calculate chunk parameters
        chunk_size = self.MAX_CONTEXT_LENGTH
        overlap = 100

        # Split into chunks
        chunks = []
        start = 0
        while start < len(text):
            end = start + chunk_size
            chunk = text[start:end]

            # Try to end at sentence boundary
            if end < len(text):
                last_period = chunk.rfind('.')
                last_question = chunk.rfind('?')
                last_exclaim = chunk.rfind('!')
                boundary = max(last_period, last_question, last_exclaim)
                if boundary > chunk_size // 2:
                    chunk = chunk[:boundary + 1]
                    end = start + boundary + 1

            chunks.append((start, chunk))
            start = end - overlap if end < len(text) else end

        # Extract candidate sentences from each chunk
        all_candidates = []
        for chunk_start, chunk in chunks:
            candidates = self._extract_key_sentences_heuristic(chunk, max_sentences)
            for sent in candidates:
                position = chunk_start / len(text)
                all_candidates.append((sent, position))

        # Deduplicate
        seen = set()
        unique_candidates = []
        for sent, pos in all_candidates:
            normalized = sent.strip().lower()
            if normalized not in seen:
                seen.add(normalized)
                unique_candidates.append((sent, pos))

        if len(unique_candidates) <= max_sentences:
            return [sent for sent, _ in unique_candidates]

        # Select with position diversity
        selected = []
        num_sections = min(max_sentences, 3)

        for section in range(num_sections):
            section_start = section / num_sections
            section_end = (section + 1) / num_sections

            section_candidates = [
                (sent, pos) for sent, pos in unique_candidates
                if section_start <= pos < section_end and sent not in selected
            ]

            if section_candidates:
                selected.append(section_candidates[0][0])

        # Fill remaining
        remaining = [sent for sent, _ in unique_candidates if sent not in selected]
        while len(selected) < max_sentences and remaining:
            selected.append(remaining.pop(0))

        return selected[:max_sentences]

    def _extract_key_sentences_heuristic(
        self,
        text: str,
        max_sentences: int
    ) -> List[str]:
        """Extract key sentences using heuristics."""
        # Split into sentences
        sentences = re.split(r'(?<=[.!?])\s+', text)
        sentences = [s.strip() for s in sentences if len(s.strip()) > 20]

        if not sentences:
            return [text[:500]]

        total_sentences = len(sentences)

        # Score sentences
        scored = []
        for i, sent in enumerate(sentences):
            score = 0

            # Position bonus
            if i < 3:
                score += 3 - i
            if total_sentences > 5 and i >= total_sentences - 2:
                score += 2

            # Length bonus
            if 50 < len(sent) < 200:
                score += 2
            elif len(sent) > 200:
                score += 1

            # Key indicator words
            key_words = ['important', 'key', 'main', 'conclusion', 'summary',
                        'result', 'finding', 'therefore', 'thus', 'shows',
                        'demonstrates', 'reveals', 'significant', 'notably']
            matches = sum(1 for word in key_words if word in sent.lower())
            score += matches * 2

            # Capitalized words (entities)
            words = sent.split()
            capitalized = sum(1 for w in words[1:] if w and w[0].isupper())
            if capitalized > 0:
                score += min(capitalized, 3)

            # Technical terms
            if re.search(r'\b[a-z]+[A-Z][a-zA-Z]*\b', sent):
                score += 1
            if re.search(r'\b[a-z]+_[a-z]+\b', sent):
                score += 1

            scored.append((score, i, sent))

        scored.sort(key=lambda x: x[0], reverse=True)

        # Select with diversity for large documents
        if total_sentences > 10 and max_sentences >= 3:
            selected = []
            third = total_sentences // 3

            first_third = [(s, i, sent) for s, i, sent in scored if i < third]
            if first_third:
                selected.append(first_third[0][2])

            middle_third = [(s, i, sent) for s, i, sent in scored
                           if third <= i < 2 * third and sent not in selected]
            if middle_third:
                selected.append(middle_third[0][2])

            last_third = [(s, i, sent) for s, i, sent in scored
                         if i >= 2 * third and sent not in selected]
            if last_third:
                selected.append(last_third[0][2])

            for s, i, sent in scored:
                if len(selected) >= max_sentences:
                    break
                if sent not in selected:
                    selected.append(sent)

            return selected[:max_sentences]

        return [sent for _, _, sent in scored[:max_sentences]]

    def extract_key_entities(
        self,
        text: str,
        max_entities: int = 10
    ) -> List[str]:
        """Extract key entities from text using spaCy NER.

        Args:
            text: Document text to extract from
            max_entities: Maximum number of entities to extract

        Returns:
            List of key entity strings
        """
        if len(text) < 20:
            return []

        # Try spaCy NER first
        if self.ner_extractor and self.ner_extractor.is_available():
            entities = self.ner_extractor.extract_entities(text, max_per_category=max_entities)
            # Flatten all entity categories
            all_entities = []
            for category in ['persons', 'organizations', 'locations', 'dates']:
                all_entities.extend(entities.get(category, []))
            if all_entities:
                return all_entities[:max_entities]

        # Fall back to heuristic extraction
        return self._extract_entities_heuristic(text, max_entities)

    def _extract_entities_heuristic(
        self,
        text: str,
        max_entities: int
    ) -> List[str]:
        """Extract key entities using heuristics (no NER)."""
        entities = set()

        # Find capitalized words (likely proper nouns)
        sentences = re.split(r'(?<=[.!?])\s+', text)
        for sentence in sentences:
            words = sentence.split()
            for i, word in enumerate(words):
                if i > 0 and len(word) > 2:
                    cleaned = re.sub(r'[^\w]', '', word)
                    if cleaned and cleaned[0].isupper() and not cleaned.isupper():
                        entities.add(cleaned)

        # Find technical terms
        technical_patterns = [
            r'\b[a-z]+[A-Z][a-zA-Z]*\b',  # camelCase
            r'\b[a-z]+_[a-z_]+\b',  # snake_case
            r'\b[A-Z][A-Z_]{2,}\b',  # CONSTANTS
        ]
        for pattern in technical_patterns:
            matches = re.findall(pattern, text)
            entities.update(matches)

        # Find quoted terms
        quoted = re.findall(r'["\']([^"\']{2,30})["\']', text)
        entities.update(quoted)

        entity_list = list(entities)
        entity_list.sort(key=lambda e: text.lower().count(e.lower()), reverse=True)

        return entity_list[:max_entities]

    def extract_structured_metadata(
        self,
        text: str,
        max_per_category: int = 10
    ) -> StructuredMetadata:
        """Extract structured metadata from text using spaCy NER and heuristics.

        Args:
            text: Document text to extract from
            max_per_category: Maximum items per category

        Returns:
            StructuredMetadata with categorized entities
        """
        # Get heuristic results as baseline
        heuristic_result = self._extract_structured_metadata_heuristic(text, max_per_category)

        # Enhance with spaCy NER if available
        if self.ner_extractor and self.ner_extractor.is_available():
            try:
                spacy_entities = self.ner_extractor.extract_entities(text, max_per_category)

                # Merge spaCy results with heuristic results
                persons = list(dict.fromkeys(
                    spacy_entities.get("persons", []) + heuristic_result.persons
                ))[:max_per_category]

                organizations = list(dict.fromkeys(
                    spacy_entities.get("organizations", []) + heuristic_result.organizations
                ))[:max_per_category]

                locations = list(dict.fromkeys(
                    spacy_entities.get("locations", []) + heuristic_result.locations
                ))[:max_per_category]

                dates = list(dict.fromkeys(
                    spacy_entities.get("dates", []) + heuristic_result.dates
                ))[:max_per_category]

                times = list(dict.fromkeys(
                    spacy_entities.get("times", []) + heuristic_result.times
                ))[:max_per_category]

                return StructuredMetadata(
                    persons=persons,
                    organizations=organizations,
                    locations=locations,
                    dates=dates,
                    times=times,
                    temporal_refs=heuristic_result.temporal_refs,
                    quantities=heuristic_result.quantities,
                    activities=heuristic_result.activities,
                    technologies=heuristic_result.technologies,
                    document_type=heuristic_result.document_type,
                    extraction_method="hybrid",
                )
            except Exception as e:
                if self.verbose:
                    print(f"PassageExtractor: spaCy enhancement failed: {e}")

        return heuristic_result

    def _extract_structured_metadata_heuristic(
        self,
        text: str,
        max_per_category: int
    ) -> StructuredMetadata:
        """Extract structured metadata using regex patterns."""
        # Date patterns
        date_patterns = [
            r'\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}(?:st|nd|rd|th)?,?\s*\d{4}\b',
            r'\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?\s+\d{1,2}(?:st|nd|rd|th)?,?\s*\d{4}\b',
            r'\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b',
            r'\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b',
            r'\b(?:Q[1-4])\s*\d{4}\b',
            r'\b\d{4}\b(?=\s|$|[,.])',
        ]
        dates = []
        for pattern in date_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            dates.extend(matches)
        dates = list(dict.fromkeys(dates))[:max_per_category]

        # Time patterns
        time_patterns = [
            r'\b\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?\b',
            r'\b\d{1,2}\s*(?:AM|PM|am|pm)\b',
            r'\b(?:morning|afternoon|evening|night|noon|midnight)\b',
        ]
        times = []
        for pattern in time_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            times.extend(matches)
        times = list(dict.fromkeys(times))[:max_per_category]

        # Temporal references
        temporal_patterns = [
            r'\b(?:last|next|this|previous|upcoming)\s+(?:week|month|year|quarter|day|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b',
            r'\b(?:yesterday|today|tomorrow)\b',
            r'\b(?:recently|soon|earlier|later)\b',
            r'\bQ[1-4]\s*(?:\d{4})?\b',
            r'\b(?:FY|fiscal year)\s*\d{2,4}\b',
        ]
        temporal_refs = []
        for pattern in temporal_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            temporal_refs.extend(matches)
        temporal_refs = list(dict.fromkeys(temporal_refs))[:max_per_category]

        # Quantities
        quantity_patterns = [
            r'\$[\d,]+(?:\.\d{2})?\s*(?:million|billion|M|B|K)?\b',
            r'\b\d+(?:,\d{3})*(?:\.\d+)?\s*(?:users|customers|employees|people|items|orders|requests|GB|MB|KB|TB|ms|seconds|minutes|hours|days|%|percent)\b',
            r'\b\d+(?:\.\d+)?[xX]\b',
        ]
        quantities = []
        for pattern in quantity_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            quantities.extend(matches)
        quantities = list(dict.fromkeys(quantities))[:max_per_category]

        # Technologies
        tech_keywords = [
            'Python', 'JavaScript', 'TypeScript', 'Java', 'C++', 'C#', 'Go', 'Rust', 'Ruby', 'PHP', 'Swift', 'Kotlin',
            'React', 'Angular', 'Vue', 'Node.js', 'Django', 'Flask', 'FastAPI', 'Spring', 'Rails',
            'PostgreSQL', 'MySQL', 'MongoDB', 'Redis', 'Elasticsearch', 'SQLite',
            'Docker', 'Kubernetes', 'AWS', 'Azure', 'GCP', 'Terraform', 'Ansible',
            'Git', 'GitHub', 'GitLab', 'Jenkins', 'CircleCI', 'Travis',
            'TensorFlow', 'PyTorch', 'Keras', 'scikit-learn', 'pandas', 'numpy',
            'REST', 'GraphQL', 'gRPC', 'WebSocket', 'HTTP', 'HTTPS', 'API',
            'Linux', 'Windows', 'macOS', 'Ubuntu', 'Debian',
            'OAuth', 'JWT', 'SSL', 'TLS',
            'Kafka', 'RabbitMQ', 'Celery',
            'VS Code', 'IntelliJ', 'Vim', 'Emacs',
            'Jira', 'Confluence', 'Slack', 'Teams',
        ]
        technologies = []
        for tech in tech_keywords:
            if re.search(r'\b' + re.escape(tech) + r'\b', text, re.IGNORECASE):
                technologies.append(tech)
        tech_patterns = [
            r'\b[a-z]+(?:[A-Z][a-z]+)+\b',
            r'\b[a-z]+(?:_[a-z]+)+\b',
        ]
        for pattern in tech_patterns:
            matches = re.findall(pattern, text)
            for match in matches:
                if match not in technologies and len(match) > 3:
                    technologies.append(match)
        technologies = technologies[:max_per_category]

        # Activities
        activity_patterns = [
            r'\b(?:deployed|released|launched|shipped|implemented|developed|built|created|designed|reviewed|analyzed|tested|fixed|updated|migrated|refactored|optimized|integrated|configured|monitored|debugged|resolved|completed|approved|merged|committed)\b',
            r'\b(?:deploying|releasing|launching|shipping|implementing|developing|building|creating|designing|reviewing|analyzing|testing|fixing|updating|migrating|refactoring|optimizing|integrating|configuring|monitoring|debugging|resolving|completing|approving|merging|committing)\b',
        ]
        activities = []
        for pattern in activity_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            activities.extend([m.lower() for m in matches])
        activities = list(dict.fromkeys(activities))[:max_per_category]

        # NER heuristic
        persons, organizations, locations = self._extract_ner_heuristic(text, max_per_category)

        # Document type
        document_type = self._classify_document_type_heuristic(text)

        return StructuredMetadata(
            persons=persons,
            organizations=organizations,
            locations=locations,
            dates=dates,
            times=times,
            temporal_refs=temporal_refs,
            quantities=quantities,
            activities=activities,
            technologies=technologies,
            document_type=document_type,
            extraction_method="heuristic",
        )

    def _extract_ner_heuristic(
        self,
        text: str,
        max_per_category: int
    ) -> tuple:
        """Extract persons, organizations, and locations using heuristics."""
        persons = []
        organizations = []
        locations = []

        # Person patterns
        person_prefixes = r'(?:Mr\.|Mrs\.|Ms\.|Dr\.|Prof\.|Sir|Madam|Captain|General)'
        person_pattern = rf'{person_prefixes}\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)'
        matches = re.findall(person_pattern, text)
        persons.extend(matches)

        name_context_patterns = [
            r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s+(?:said|wrote|mentioned|reported|noted|stated|explained|asked|replied|confirmed|suggested)',
            r'(?:by|from|with|to)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b',
            r'@([A-Za-z][A-Za-z0-9_]+)\b',
        ]
        common_words = {'The', 'This', 'That', 'These', 'Those', 'There', 'Here', 'What', 'When', 'Where', 'Why', 'How', 'All', 'Some', 'Any', 'None', 'Each', 'Every', 'Both', 'Few', 'Many', 'Most', 'Other', 'Another', 'Such', 'No', 'Not', 'Only', 'Same', 'So', 'Than', 'Too', 'Very', 'Just', 'Also', 'Now', 'Then', 'Once'}
        for pattern in name_context_patterns:
            matches = re.findall(pattern, text)
            for match in matches:
                if match and len(match) > 2 and match not in persons and match not in common_words:
                    persons.append(match)

        # Organization patterns
        org_suffixes = r'(?:Inc\.|Corp\.|LLC|Ltd\.|Company|Corporation|Foundation|Institute|University|College|Association|Organization|Group|Team|Department|Division)'
        org_pattern = rf'([A-Z][A-Za-z]*(?:\s+[A-Z][A-Za-z]*)*)\s+{org_suffixes}'
        matches = re.findall(org_pattern, text)
        organizations.extend(matches)

        org_context_patterns = [
            r'\b(?:at|from|with|by)\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*)\s+(?:company|team|department|organization)',
            r'(?:joined|left|works at|working at|employed by)\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*)',
        ]
        for pattern in org_context_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                if match and match not in organizations:
                    organizations.append(match)

        # Location patterns
        location_prefixes = r'(?:in|at|from|to|near|around)\s+'
        location_suffixes = r'(?:City|Town|County|State|Province|Country|Street|Avenue|Road|Building|Campus|Office|Room|Floor)'
        location_pattern = rf'{location_prefixes}([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*(?:\s+{location_suffixes})?)'
        matches = re.findall(location_pattern, text)
        for match in matches:
            if match and len(match) > 2 and match not in locations:
                if match not in persons and match not in organizations:
                    locations.append(match)

        persons = list(dict.fromkeys(persons))[:max_per_category]
        organizations = list(dict.fromkeys(organizations))[:max_per_category]
        locations = list(dict.fromkeys(locations))[:max_per_category]

        return persons, organizations, locations

    def _classify_document_type_heuristic(self, text: str) -> str:
        """Classify document type based on content patterns."""
        text_lower = text.lower()

        # Code indicators
        code_patterns = [
            r'(?:def |class |function |const |let |var |import |from |export |public |private |protected )',
            r'(?:\{|\}|;|\(\)|\[\])',
            r'(?:if\s*\(|for\s*\(|while\s*\(|switch\s*\()',
        ]
        code_score = sum(1 for p in code_patterns if re.search(p, text))
        if code_score >= 2:
            return "code"

        # Meeting notes
        meeting_patterns = [
            r'\b(?:attendees|participants|agenda|action items|minutes|meeting|discussion|decided|next steps)\b',
            r'\b(?:present|absent|invited)\b',
        ]
        meeting_score = sum(1 for p in meeting_patterns if re.search(p, text_lower))
        if meeting_score >= 2:
            return "meeting_notes"

        # Email
        email_patterns = [
            r'\b(?:from:|to:|cc:|bcc:|subject:|sent:|dear|regards|sincerely|best regards)\b',
            r'@[\w.]+\.\w+',
        ]
        email_score = sum(1 for p in email_patterns if re.search(p, text_lower))
        if email_score >= 2:
            return "email"

        # Documentation
        doc_patterns = [
            r'\b(?:overview|introduction|getting started|installation|usage|api reference|configuration|example|note:|warning:|tip:)\b',
            r'(?:#{1,6}\s+\w+)',
        ]
        doc_score = sum(1 for p in doc_patterns if re.search(p, text_lower))
        if doc_score >= 2:
            return "documentation"

        # Report
        report_patterns = [
            r'\b(?:summary|conclusion|findings|recommendations|analysis|results|overview|executive summary)\b',
            r'\b(?:figure|table|chart|graph)\s+\d+',
        ]
        report_score = sum(1 for p in report_patterns if re.search(p, text_lower))
        if report_score >= 2:
            return "report"

        # Specification
        spec_patterns = [
            r'\b(?:requirements|specification|shall|must|should|acceptance criteria|user story|use case)\b',
            r'\b(?:FR-|NFR-|REQ-|US-)\d+',
        ]
        spec_score = sum(1 for p in spec_patterns if re.search(p, text_lower))
        if spec_score >= 2:
            return "specification"

        # Log
        log_patterns = [
            r'\b(?:ERROR|WARN|INFO|DEBUG|TRACE)\b',
            r'\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}',
            r'\[[\w.]+\]',
        ]
        log_score = sum(1 for p in log_patterns if re.search(p, text))
        if log_score >= 2:
            return "log"

        return "general"

    def analyze_query(self, query: str) -> QueryAnalysis:
        """Analyze a search query to determine optimal filtering/boosting strategy."""
        query_lower = query.lower()

        # Detect filter intent
        filter_phrases = [
            r'\bonly\b', r'\bjust\b', r'\bexclusively\b',
            r'\bfrom\s+\w+\b', r'\bby\s+\w+\b', r'\babout\s+\w+\b',
            r'\bin\s+\w+\b', r'\bat\s+\w+\b',
            r'\b\w+\s+only\b', r'\b\w+\s+specific\b',
        ]
        has_filter_intent = any(re.search(p, query_lower) for p in filter_phrases)

        # Detect technologies
        tech_keywords = [
            'Python', 'JavaScript', 'TypeScript', 'Java', 'C++', 'Go', 'Rust', 'Ruby',
            'React', 'Angular', 'Vue', 'Node.js', 'Django', 'Flask', 'FastAPI',
            'PostgreSQL', 'MySQL', 'MongoDB', 'Redis', 'Elasticsearch',
            'Docker', 'Kubernetes', 'AWS', 'Azure', 'GCP',
            'Git', 'GitHub', 'GitLab',
            'TensorFlow', 'PyTorch',
            'REST', 'GraphQL', 'API',
        ]
        detected_technologies = []
        for tech in tech_keywords:
            if re.search(r'\b' + re.escape(tech) + r'\b', query, re.IGNORECASE):
                detected_technologies.append(tech)

        # Detect persons
        person_patterns = [
            r'(?:Mr\.|Mrs\.|Ms\.|Dr\.|Prof\.)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)',
            r'\b([A-Z][a-z]+\s+[A-Z][a-z]+)\b',
            r'(?:by|from|with)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)',
        ]
        detected_persons = []
        common = {'The', 'This', 'That', 'What', 'When', 'Where', 'How', 'Why'}
        for pattern in person_patterns:
            matches = re.findall(pattern, query)
            for match in matches:
                if match and len(match) > 2 and match not in common and match not in detected_persons:
                    detected_persons.append(match)

        # Detect organizations
        org_patterns = [
            r'([A-Z][A-Za-z]*(?:\s+[A-Z][A-Za-z]*)*)\s+(?:Inc\.|Corp\.|LLC|Company|Team)',
            r'(?:at|from|by)\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)?)\b',
        ]
        detected_organizations = []
        for pattern in org_patterns:
            matches = re.findall(pattern, query)
            for match in matches:
                if match and len(match) > 2 and match not in detected_persons:
                    detected_organizations.append(match)

        # Detect locations
        location_patterns = [
            r'(?:in|at|from|to)\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)?)',
        ]
        detected_locations = []
        for pattern in location_patterns:
            matches = re.findall(pattern, query)
            for match in matches:
                if match and len(match) > 2:
                    if match not in detected_persons and match not in detected_organizations:
                        detected_locations.append(match)

        # Detect dates
        date_patterns = [
            r'\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}(?:st|nd|rd|th)?,?\s*\d{4}\b',
            r'\b\d{4}\b',
            r'\bQ[1-4]\s*\d{4}\b',
            r'\b(?:last|this|next)\s+(?:week|month|year|quarter)\b',
        ]
        detected_dates = []
        for pattern in date_patterns:
            matches = re.findall(pattern, query, re.IGNORECASE)
            detected_dates.extend(matches)

        # Detect document type hints
        doc_type_hint = None
        doc_type_patterns = {
            'meeting_notes': [r'\bmeeting\b', r'\bminutes\b', r'\bnotes\b', r'\bagenda\b'],
            'code': [r'\bcode\b', r'\bfunction\b', r'\bclass\b', r'\bimplementation\b'],
            'email': [r'\bemail\b', r'\bmessage\b', r'\bcorrespondence\b'],
            'documentation': [r'\bdocs?\b', r'\bdocumentation\b', r'\bguide\b', r'\breadme\b'],
            'report': [r'\breport\b', r'\banalysis\b', r'\bfindings\b'],
            'specification': [r'\bspec\b', r'\brequirements?\b', r'\buser story\b'],
        }
        for doc_type, patterns in doc_type_patterns.items():
            if any(re.search(p, query_lower) for p in patterns):
                doc_type_hint = doc_type
                break

        # Calculate filter confidence
        filter_confidence = 0.0
        if has_filter_intent:
            filter_confidence += 0.4
        if detected_persons:
            filter_confidence += 0.2
        if detected_technologies and len(detected_technologies) == 1:
            filter_confidence += 0.15
        if doc_type_hint:
            filter_confidence += 0.15
        if detected_organizations:
            filter_confidence += 0.1

        word_count = len(query.split())
        if word_count <= 5 and (detected_persons or detected_technologies):
            filter_confidence += 0.2

        filter_confidence = min(filter_confidence, 1.0)
        use_filters = filter_confidence > 0.5

        return QueryAnalysis(
            persons=detected_persons,
            organizations=detected_organizations,
            locations=detected_locations,
            technologies=detected_technologies,
            dates=detected_dates,
            doc_type_hint=doc_type_hint,
            use_person_filter=use_filters and len(detected_persons) > 0,
            use_organization_filter=use_filters and len(detected_organizations) > 0,
            use_location_filter=use_filters and len(detected_locations) > 0,
            use_technology_filter=use_filters and len(detected_technologies) == 1,
            use_doc_type_filter=use_filters and doc_type_hint is not None,
            filter_confidence=filter_confidence,
        )

    def batch_extract_passages(
        self,
        query: str,
        documents: List[Dict[str, Any]],
        max_excerpt_length: int = MAX_EXCERPT_LENGTH
    ) -> List[ExtractedPassage]:
        """Extract passages from multiple documents."""
        results = []
        for doc in documents:
            text = doc.get('text', '')
            if text:
                passage = self.extract_passage(query, text, max_excerpt_length)
                results.append(passage)
            else:
                results.append(ExtractedPassage(
                    excerpt="",
                    relevance_reasoning="Empty document",
                    confidence=0.0,
                    method="full"
                ))
        return results

    # ==========================================================================
    # Dynamic Filter Generation
    # ==========================================================================

    FILTER_CATEGORIES = {
        "content_type": [
            "conversation", "note", "code", "article", "highlight",
            "email", "documentation", "meeting", "list", "research",
        ],
        "domain": [
            "work", "personal", "learning", "creative",
            "technical", "finance", "health", "social",
        ]
    }

    def generate_document_filters(
        self,
        text: str,
        source: Optional[str] = None,
        filename: Optional[str] = None
    ) -> Dict[str, Any]:
        """Generate high-level filter categories for a document."""
        return self._generate_filters_heuristic(text, source, filename)

    def _generate_filters_heuristic(
        self,
        text: str,
        source: Optional[str] = None,
        filename: Optional[str] = None
    ) -> Dict[str, Any]:
        """Generate filters using heuristic rules."""
        text_lower = text.lower()
        filename_lower = (filename or "").lower()

        # Determine content_type
        content_type = "note"

        # Source-based hints
        if source == "chatgpt":
            content_type = "conversation"
        elif source == "readwise":
            content_type = "highlight"
        elif source == "github":
            content_type = "code"
        elif source == "notion":
            content_type = "note"
        elif source == "todoist":
            content_type = "list"

        # Pattern-based detection
        conversation_patterns = [
            r'\b(user|assistant|human|ai|you|i said|they said)\s*:',
            r'^(q:|a:|question:|answer:)',
            r'\[message\]|\[reply\]',
        ]
        if any(re.search(p, text_lower, re.MULTILINE) for p in conversation_patterns):
            content_type = "conversation"

        code_patterns = [
            r'```[\w]*\n',
            r'def\s+\w+\s*\(|function\s+\w+\s*\(|class\s+\w+',
            r'import\s+[\w.]+|from\s+[\w.]+\s+import',
            r'\{\s*\n\s*["\']?\w+["\']?\s*:',
        ]
        if any(re.search(p, text, re.MULTILINE) for p in code_patterns):
            content_type = "code"

        doc_patterns = [
            r'^#+\s+\w+',
            r'readme|documentation|api\s+reference|getting\s+started',
        ]
        if any(re.search(p, text_lower, re.MULTILINE) for p in doc_patterns):
            if "readme" in filename_lower or "doc" in filename_lower:
                content_type = "documentation"

        meeting_patterns = [
            r'meeting\s+notes?|agenda|attendees|action\s+items',
            r'discussed|agreed|decided|next\s+steps',
        ]
        if any(re.search(p, text_lower) for p in meeting_patterns):
            content_type = "meeting"

        list_patterns = [
            r'^\s*[-*]\s+\[[ x]\]',
            r'^\s*\d+\.\s+\w+',
            r'todo|task|checklist',
        ]
        if any(re.search(p, text_lower, re.MULTILINE) for p in list_patterns):
            content_type = "list"

        email_patterns = [
            r'from:\s*\S+@\S+|to:\s*\S+@\S+|subject:',
            r'dear\s+\w+|hi\s+\w+,|regards,|sincerely,',
        ]
        if any(re.search(p, text_lower) for p in email_patterns):
            content_type = "email"

        # Determine domain
        domain = "personal"

        work_keywords = ['project', 'deadline', 'client', 'meeting', 'team', 'report',
                        'quarterly', 'kpi', 'revenue', 'stakeholder', 'deliverable',
                        'sprint', 'standup', 'roadmap', 'milestone']
        work_score = sum(1 for kw in work_keywords if kw in text_lower)

        tech_keywords = ['code', 'api', 'database', 'server', 'deploy', 'bug', 'feature',
                        'function', 'class', 'variable', 'algorithm', 'architecture',
                        'docker', 'kubernetes', 'python', 'javascript', 'git']
        tech_score = sum(1 for kw in tech_keywords if kw in text_lower)

        learning_keywords = ['learn', 'study', 'course', 'tutorial', 'lesson', 'chapter',
                            'concept', 'understand', 'example', 'practice', 'exercise']
        learning_score = sum(1 for kw in learning_keywords if kw in text_lower)

        creative_keywords = ['idea', 'story', 'write', 'draft', 'creative', 'inspiration',
                            'brainstorm', 'imagine', 'design', 'concept', 'sketch']
        creative_score = sum(1 for kw in creative_keywords if kw in text_lower)

        personal_keywords = ['journal', 'diary', 'today i', 'feeling', 'thought', 'memory',
                            'family', 'friend', 'weekend', 'vacation', 'birthday']
        personal_score = sum(1 for kw in personal_keywords if kw in text_lower)

        finance_keywords = ['budget', 'expense', 'income', 'investment', 'savings', 'tax',
                           'payment', 'invoice', 'salary', 'cost', 'price', 'money']
        finance_score = sum(1 for kw in finance_keywords if kw in text_lower)

        scores = {
            'work': work_score,
            'technical': tech_score,
            'learning': learning_score,
            'creative': creative_score,
            'personal': personal_score,
            'finance': finance_score,
        }
        max_score = max(scores.values())
        if max_score >= 2:
            domain = max(scores, key=scores.get)

        return {
            "content_type": content_type,
            "domain": domain,
            "extraction_method": "heuristic",
        }
