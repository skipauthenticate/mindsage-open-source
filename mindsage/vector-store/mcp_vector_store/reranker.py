"""Reranking module for improving search result quality.

Provides cross-encoder based reranking to improve precision after initial
vector retrieval. The reranker scores query-document pairs directly,
providing more accurate relevance scores than bi-encoder similarity alone.
"""

import os
from typing import List, Optional, Tuple, Any
from dataclasses import dataclass

# Cross-encoder support is optional
try:
    from sentence_transformers import CrossEncoder
    CROSS_ENCODER_AVAILABLE = True
except ImportError:
    CROSS_ENCODER_AVAILABLE = False


@dataclass
class RerankResult:
    """Result from reranking with original and new scores."""
    id: Any
    text: str
    original_score: float
    rerank_score: float
    metadata: Optional[dict] = None


class Reranker:
    """Cross-encoder based reranker for search results.

    Uses a cross-encoder model to score query-document pairs directly,
    which is more accurate than bi-encoder similarity but slower.
    Recommended for reranking top-k results (k=10-50) after initial retrieval.
    """

    # Recommended cross-encoder models
    # mxbai-rerank-xsmall-v1: ~100M params, Apache 2.0, 8192 token context, ~200MB GPU
    # (upgraded from ms-marco-MiniLM-L-6-v2: 22M params, MIT, 512 token context, ~250MB GPU)
    RECOMMENDED_MODELS = {
        "fast": "mixedbread-ai/mxbai-rerank-xsmall-v1",     # Best quality/size ratio, Apache 2.0
        "balanced": "cross-encoder/ms-marco-MiniLM-L-12-v2",  # Balance of speed and quality
        "accurate": "cross-encoder/ms-marco-distilbert-base-v3",  # Most accurate, slower
        "legacy": "cross-encoder/ms-marco-MiniLM-L-6-v2"    # Previous default, still works
    }

    def __init__(
        self,
        model_name: Optional[str] = None,
        device: Optional[str] = None,
        cache_dir: str = "./models",
        max_length: int = 512
    ):
        """Initialize the reranker.

        Args:
            model_name: Cross-encoder model name. If None, uses "fast" preset.
                       Can be a preset name ("fast", "balanced", "accurate") or
                       a HuggingFace model identifier.
            device: Device to run inference on ('cpu', 'cuda', or None for auto-detect)
            cache_dir: Directory to cache downloaded models
            max_length: Maximum sequence length for cross-encoder (default: 512)

        Raises:
            ImportError: If sentence-transformers is not installed
        """
        if not CROSS_ENCODER_AVAILABLE:
            raise ImportError(
                "Cross-encoder reranking requires sentence-transformers. "
                "Install with: pip install sentence-transformers"
            )

        self.cache_dir = cache_dir
        self.max_length = max_length

        # Auto-detect device
        if device is None:
            try:
                import torch
                self.device = "cuda" if torch.cuda.is_available() else "cpu"
            except ImportError:
                self.device = "cpu"
        else:
            self.device = device

        # Resolve model name from preset or use directly
        if model_name is None:
            model_name = self.RECOMMENDED_MODELS["fast"]
        elif model_name in self.RECOMMENDED_MODELS:
            model_name = self.RECOMMENDED_MODELS[model_name]

        self.model_name = model_name

        print(f"Loading reranker model: {model_name}")
        os.makedirs(cache_dir, exist_ok=True)

        self.model = CrossEncoder(
            model_name,
            max_length=max_length,
            device=self.device
        )

        print(f"Reranker loaded on {self.device}")

    def rerank(
        self,
        query: str,
        documents: List[Tuple[Any, str, float, Optional[dict]]],
        top_k: Optional[int] = None
    ) -> List[RerankResult]:
        """Rerank documents using cross-encoder scoring.

        Args:
            query: Search query text
            documents: List of (id, text, original_score, metadata) tuples
            top_k: Number of results to return after reranking (default: all)

        Returns:
            List of RerankResult objects sorted by rerank_score descending
        """
        if not documents:
            return []

        # Prepare query-document pairs for cross-encoder
        pairs = [(query, doc[1]) for doc in documents]

        # Score all pairs
        scores = self.model.predict(pairs)

        # Combine with original data and sort by rerank score
        results = []
        for i, (doc_id, text, orig_score, metadata) in enumerate(documents):
            results.append(RerankResult(
                id=doc_id,
                text=text,
                original_score=orig_score,
                rerank_score=float(scores[i]),
                metadata=metadata
            ))

        # Sort by rerank score
        results.sort(key=lambda r: r.rerank_score, reverse=True)

        # Limit to top_k if specified
        if top_k is not None:
            results = results[:top_k]

        return results

    def is_available(self) -> bool:
        """Check if the reranker is ready to use."""
        return self.model is not None

    def unload(self) -> None:
        """Unload the model to free GPU memory."""
        if self.model is not None:
            # Move model to CPU first to free GPU memory
            try:
                if hasattr(self.model, 'model') and hasattr(self.model.model, 'to'):
                    self.model.model.to('cpu')
            except Exception:
                pass

            del self.model
            self.model = None

            # Force garbage collection
            import gc
            gc.collect()

            # Clear CUDA cache and synchronize
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                    torch.cuda.synchronize()
            except ImportError:
                pass

            print("Reranker model unloaded")

    def reload(self) -> None:
        """Reload the model after it was unloaded."""
        if self.model is not None:
            return  # Already loaded

        print(f"Reloading reranker model: {self.model_name}")
        self.model = CrossEncoder(
            self.model_name,
            max_length=self.max_length,
            device=self.device
        )
        print(f"Reranker reloaded on {self.device}")

    def __repr__(self) -> str:
        return f"Reranker(model='{self.model_name}', device='{self.device}')"


def create_reranker(
    preset: str = "fast",
    device: Optional[str] = None,
    cache_dir: str = "./models"
) -> Optional[Reranker]:
    """Factory function to create a reranker with error handling.

    Args:
        preset: Model preset ("fast", "balanced", "accurate")
        device: Device for inference
        cache_dir: Model cache directory

    Returns:
        Reranker instance or None if dependencies not available
    """
    if not CROSS_ENCODER_AVAILABLE:
        print("Reranking disabled: sentence-transformers not installed")
        return None

    try:
        return Reranker(model_name=preset, device=device, cache_dir=cache_dir)
    except Exception as e:
        print(f"Failed to initialize reranker: {e}")
        return None
