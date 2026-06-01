"""Lightweight word embeddings for LPRAG semantic similarity.

Provides word-level embeddings for finding semantically similar replacement
words during LPRAG perturbation. Supports both GloVe (CPU) and Sentence
Transformers (GPU) backends.

Memory footprint:
- GloVe 50-dim: ~50MB (400K words)
- GloVe 100-dim: ~128MB (400K words)
- Sentence Transformers: Uses existing model (~90MB VRAM)

Usage:
    embeddings = LPRAGEmbeddings()
    similar = embeddings.get_similar_words("john", top_k=10)
    # Returns: [("james", 0.89), ("michael", 0.85), ...]
"""

import os
import threading
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
import numpy as np

# Optional imports for different backends
try:
    import gensim.downloader as gensim_api
    GENSIM_AVAILABLE = True
except ImportError:
    GENSIM_AVAILABLE = False
    gensim_api = None


class LPRAGEmbeddings:
    """Manages word embeddings for LPRAG semantic similarity.

    Supports two backends:
    - GloVe (CPU): Pre-computed word vectors, fast lookup
    - Sentence Transformers (GPU): Higher quality, uses existing model

    The GloVe backend is recommended for edge devices due to lower
    memory usage and no GPU contention.
    """

    # Available GloVe models with dimensions and approximate sizes
    GLOVE_MODELS = {
        "glove-wiki-gigaword-50": {"dims": 50, "size_mb": 66},
        "glove-wiki-gigaword-100": {"dims": 100, "size_mb": 128},
        "glove-wiki-gigaword-200": {"dims": 200, "size_mb": 252},
        "glove-wiki-gigaword-300": {"dims": 300, "size_mb": 376},
        "glove-twitter-25": {"dims": 25, "size_mb": 104},
        "glove-twitter-50": {"dims": 50, "size_mb": 199},
    }

    # Default model for edge devices (smallest, fastest)
    DEFAULT_MODEL = "glove-wiki-gigaword-50"

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        use_gpu: bool = False,
        cache_dir: Optional[str] = None,
        verbose: bool = False,
    ):
        """Initialize embeddings manager.

        Args:
            model_name: GloVe model name (for CPU mode)
            use_gpu: If True, use Sentence Transformers on GPU
            cache_dir: Directory to cache downloaded models
            verbose: Enable debug logging
        """
        self.model_name = model_name
        self.use_gpu = use_gpu
        self.cache_dir = cache_dir or self._default_cache_dir()
        self.verbose = verbose

        # Lazy-loaded model components
        self._glove_model: Optional[Any] = None
        self._sentence_transformer: Optional[Any] = None
        self._vocab_embeddings: Optional[np.ndarray] = None
        self._vocab_words: Optional[List[str]] = None

        # Thread safety
        self._lock = threading.Lock()
        self._initialized = False
        self._init_error: Optional[str] = None

        # Statistics
        self._cache_hits = 0
        self._cache_misses = 0

        # LRU cache for similarity results
        self._similarity_cache: Dict[str, List[Tuple[str, float]]] = {}
        self._cache_max_size = 1000

    def _default_cache_dir(self) -> str:
        """Get default cache directory for models."""
        # Use project's models directory
        project_root = Path(__file__).parent.parent.parent
        return str(project_root / "models" / "lprag")

    @property
    def is_available(self) -> bool:
        """Check if embeddings backend is available."""
        if self.use_gpu:
            # GPU mode uses sentence transformers (assumed available)
            return True
        return GENSIM_AVAILABLE

    @property
    def is_loaded(self) -> bool:
        """Check if embeddings are loaded."""
        return self._initialized and self._init_error is None

    def _log(self, msg: str) -> None:
        """Log message if verbose mode enabled."""
        if self.verbose:
            print(f"LPRAGEmbeddings: {msg}")

    def _ensure_initialized(self) -> bool:
        """Lazy initialization of embeddings.

        Returns:
            True if initialization succeeded, False otherwise.
        """
        if self._initialized:
            return self._init_error is None

        with self._lock:
            if self._initialized:
                return self._init_error is None

            try:
                if self.use_gpu:
                    self._init_sentence_transformer()
                else:
                    self._init_glove()
                self._initialized = True
                self._init_error = None
                return True
            except Exception as e:
                self._initialized = True
                self._init_error = str(e)
                self._log(f"Initialization failed: {e}")
                return False

    def _init_glove(self) -> None:
        """Initialize GloVe embeddings."""
        if not GENSIM_AVAILABLE:
            raise ImportError(
                "gensim is required for GloVe embeddings. "
                "Install with: pip install gensim"
            )

        self._log(f"Loading GloVe model: {self.model_name}")

        # Download and load model
        self._glove_model = gensim_api.load(self.model_name)

        # Build vocabulary list for fast iteration
        self._vocab_words = list(self._glove_model.key_to_index.keys())

        self._log(f"Loaded {len(self._vocab_words):,} words")

    def _init_sentence_transformer(self) -> None:
        """Initialize Sentence Transformers for GPU mode."""
        try:
            from .embeddings import get_embedding_model
            self._sentence_transformer = get_embedding_model()
            self._log("Using existing Sentence Transformers model")
        except ImportError:
            raise ImportError(
                "Sentence Transformers not available. "
                "Either install it or set use_gpu=False"
            )

    def get_embedding(self, word: str) -> Optional[np.ndarray]:
        """Get embedding vector for a word.

        Args:
            word: Word to get embedding for

        Returns:
            Embedding vector as numpy array, or None if word not in vocabulary.
        """
        if not self._ensure_initialized():
            return None

        word_lower = word.lower()

        if self.use_gpu:
            # Use Sentence Transformers
            if self._sentence_transformer:
                return self._sentence_transformer.embed_query(word_lower)
        else:
            # Use GloVe
            if self._glove_model and word_lower in self._glove_model:
                return self._glove_model[word_lower]

        return None

    def get_similar_words(
        self,
        word: str,
        top_k: int = 10,
        exclude_original: bool = True,
        min_similarity: float = 0.3,
    ) -> List[Tuple[str, float]]:
        """Get semantically similar words with similarity scores.

        Args:
            word: Word to find similar words for
            top_k: Number of similar words to return
            exclude_original: Exclude the input word from results
            min_similarity: Minimum similarity threshold (0-1)

        Returns:
            List of (word, similarity_score) tuples, sorted by similarity descending.
            Returns empty list if word not in vocabulary or embeddings unavailable.
        """
        if not self._ensure_initialized():
            return []

        word_lower = word.lower()

        # Check cache
        cache_key = f"{word_lower}:{top_k}"
        if cache_key in self._similarity_cache:
            self._cache_hits += 1
            return self._similarity_cache[cache_key]

        self._cache_misses += 1

        try:
            if self.use_gpu:
                similar = self._get_similar_gpu(word_lower, top_k, min_similarity)
            else:
                similar = self._get_similar_glove(word_lower, top_k, min_similarity)
        except Exception as e:
            self._log(f"Error getting similar words: {e}")
            return []

        # Filter out original word if requested
        if exclude_original:
            similar = [(w, s) for w, s in similar if w.lower() != word_lower]

        # Cache result
        if len(self._similarity_cache) >= self._cache_max_size:
            # Simple eviction: clear half the cache
            keys_to_remove = list(self._similarity_cache.keys())[
                : self._cache_max_size // 2
            ]
            for key in keys_to_remove:
                del self._similarity_cache[key]

        self._similarity_cache[cache_key] = similar

        return similar

    def _get_similar_glove(
        self, word: str, top_k: int, min_similarity: float
    ) -> List[Tuple[str, float]]:
        """Get similar words using GloVe model."""
        if not self._glove_model or word not in self._glove_model:
            return []

        # gensim's most_similar returns list of (word, similarity) tuples
        try:
            similar = self._glove_model.most_similar(word, topn=top_k)
            # Filter by minimum similarity
            return [(w, s) for w, s in similar if s >= min_similarity]
        except KeyError:
            return []

    def _get_similar_gpu(
        self, word: str, top_k: int, min_similarity: float
    ) -> List[Tuple[str, float]]:
        """Get similar words using Sentence Transformers.

        Note: This is a simplified implementation. For production,
        you would pre-encode a vocabulary and store on GPU.
        """
        # For now, fall back to a basic word list
        # In production, this would use pre-encoded vocabulary
        self._log("GPU similarity not fully implemented, using fallback")
        return []

    def compute_similarity(self, word1: str, word2: str) -> float:
        """Compute cosine similarity between two words.

        Args:
            word1: First word
            word2: Second word

        Returns:
            Cosine similarity score (0-1), or 0 if either word not in vocabulary.
        """
        emb1 = self.get_embedding(word1)
        emb2 = self.get_embedding(word2)

        if emb1 is None or emb2 is None:
            return 0.0

        # Cosine similarity
        dot_product = np.dot(emb1, emb2)
        norm1 = np.linalg.norm(emb1)
        norm2 = np.linalg.norm(emb2)

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return float(dot_product / (norm1 * norm2))

    def has_word(self, word: str) -> bool:
        """Check if word exists in vocabulary.

        Args:
            word: Word to check

        Returns:
            True if word is in vocabulary.
        """
        if not self._ensure_initialized():
            return False

        word_lower = word.lower()

        if self.use_gpu:
            return True  # Sentence Transformers can encode any word
        else:
            return self._glove_model is not None and word_lower in self._glove_model

    def get_vocabulary_size(self) -> int:
        """Get number of words in vocabulary."""
        if not self._ensure_initialized():
            return 0

        if self.use_gpu:
            return -1  # Sentence Transformers has no fixed vocabulary
        elif self._glove_model:
            return len(self._glove_model.key_to_index)
        return 0

    def get_embedding_dimension(self) -> int:
        """Get dimension of embedding vectors."""
        if not self._ensure_initialized():
            return 0

        if self.use_gpu and self._sentence_transformer:
            # Get dimension from a sample embedding
            sample = self._sentence_transformer.embed_query("test")
            return len(sample)
        elif self._glove_model:
            return self._glove_model.vector_size
        return 0

    def unload(self) -> None:
        """Unload embeddings to free memory."""
        with self._lock:
            self._glove_model = None
            self._sentence_transformer = None
            self._vocab_embeddings = None
            self._vocab_words = None
            self._similarity_cache.clear()
            self._initialized = False
            self._init_error = None
            self._log("Embeddings unloaded")

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about embeddings."""
        return {
            "is_available": self.is_available,
            "is_loaded": self.is_loaded,
            "use_gpu": self.use_gpu,
            "model_name": self.model_name,
            "vocabulary_size": self.get_vocabulary_size(),
            "embedding_dimension": self.get_embedding_dimension(),
            "cache_size": len(self._similarity_cache),
            "cache_hits": self._cache_hits,
            "cache_misses": self._cache_misses,
            "init_error": self._init_error,
        }


# Curated name lists for fallback when embeddings unavailable
# These are common names that can be used for random replacement
COMMON_FIRST_NAMES = [
    "James", "John", "Robert", "Michael", "William", "David", "Richard", "Joseph",
    "Thomas", "Charles", "Christopher", "Daniel", "Matthew", "Anthony", "Mark",
    "Donald", "Steven", "Paul", "Andrew", "Joshua", "Kenneth", "Kevin", "Brian",
    "George", "Timothy", "Ronald", "Edward", "Jason", "Jeffrey", "Ryan",
    "Mary", "Patricia", "Jennifer", "Linda", "Elizabeth", "Barbara", "Susan",
    "Jessica", "Sarah", "Karen", "Lisa", "Nancy", "Betty", "Margaret", "Sandra",
    "Ashley", "Kimberly", "Emily", "Donna", "Michelle", "Dorothy", "Carol",
    "Amanda", "Melissa", "Deborah", "Stephanie", "Rebecca", "Sharon", "Laura",
]

COMMON_LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis",
    "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson",
    "Thomas", "Taylor", "Moore", "Jackson", "Martin", "Lee", "Perez", "Thompson",
    "White", "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson",
    "Walker", "Young", "Allen", "King", "Wright", "Scott", "Torres", "Nguyen",
    "Hill", "Flores", "Green", "Adams", "Nelson", "Baker", "Hall", "Rivera",
]

COMMON_LOCATIONS = [
    "New York", "Los Angeles", "Chicago", "Houston", "Phoenix", "Philadelphia",
    "San Antonio", "San Diego", "Dallas", "San Jose", "Austin", "Jacksonville",
    "Fort Worth", "Columbus", "Indianapolis", "Charlotte", "San Francisco",
    "Seattle", "Denver", "Boston", "Nashville", "Portland", "Las Vegas", "Miami",
    "Atlanta", "Minneapolis", "Cleveland", "Detroit", "Pittsburgh", "Baltimore",
]


def get_random_name(
    first_name: bool = True,
    last_name: bool = True,
    exclude: Optional[str] = None
) -> str:
    """Get a random name from curated lists.

    Useful as fallback when embeddings are unavailable.

    Args:
        first_name: Include first name
        last_name: Include last name
        exclude: Name to exclude from selection

    Returns:
        Random name string.
    """
    import random

    parts = []

    if first_name:
        choices = [n for n in COMMON_FIRST_NAMES if n.lower() != (exclude or "").lower()]
        if choices:
            parts.append(random.choice(choices))

    if last_name:
        choices = [n for n in COMMON_LAST_NAMES if n.lower() != (exclude or "").lower()]
        if choices:
            parts.append(random.choice(choices))

    return " ".join(parts)


def get_random_location(exclude: Optional[str] = None) -> str:
    """Get a random location from curated list.

    Args:
        exclude: Location to exclude from selection

    Returns:
        Random location string.
    """
    import random

    choices = [loc for loc in COMMON_LOCATIONS if loc.lower() != (exclude or "").lower()]
    return random.choice(choices) if choices else "Unknown City"


# Global embeddings instance
_global_embeddings: Optional[LPRAGEmbeddings] = None
_global_lock = threading.Lock()


def get_lprag_embeddings(
    model_name: str = LPRAGEmbeddings.DEFAULT_MODEL,
    use_gpu: bool = False,
    verbose: bool = False,
) -> LPRAGEmbeddings:
    """Get or create the global embeddings instance.

    Args:
        model_name: GloVe model name
        use_gpu: Use GPU-accelerated similarity
        verbose: Enable debug logging

    Returns:
        LPRAGEmbeddings instance.
    """
    global _global_embeddings

    with _global_lock:
        if _global_embeddings is None:
            _global_embeddings = LPRAGEmbeddings(
                model_name=model_name,
                use_gpu=use_gpu,
                verbose=verbose,
            )
        return _global_embeddings


def reset_lprag_embeddings() -> None:
    """Reset the global embeddings instance (for testing)."""
    global _global_embeddings

    with _global_lock:
        if _global_embeddings:
            _global_embeddings.unload()
        _global_embeddings = None
