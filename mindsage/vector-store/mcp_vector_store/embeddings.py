"""Embedding model wrapper with GPU acceleration support for edge devices.

Optimized for NVIDIA Jetson devices (Orin Nano, AGX Orin, etc.) with:
- CUDA acceleration when available
- FP16 inference for better performance on Jetson
- Unified memory awareness
"""

import os
import time
import hashlib
from collections import OrderedDict
from typing import List, Union, Optional, Tuple
import numpy as np
import torch
from sentence_transformers import SentenceTransformer


def is_jetson_device() -> bool:
    """Detect if running on NVIDIA Jetson device."""
    try:
        # Check for Jetson-specific files
        if os.path.exists('/etc/nv_tegra_release'):
            return True
        # Check for tegra in device tree
        if os.path.exists('/proc/device-tree/compatible'):
            with open('/proc/device-tree/compatible', 'rb') as f:
                content = f.read().decode('utf-8', errors='ignore')
                if 'tegra' in content.lower() or 'jetson' in content.lower():
                    return True
        # Check uname for tegra
        import platform
        if 'tegra' in platform.release().lower():
            return True
    except Exception:
        pass
    return False


def get_jetson_info() -> Optional[dict]:
    """Get Jetson device information if available."""
    if not is_jetson_device():
        return None

    info = {"is_jetson": True}

    try:
        # Get Jetson model from device tree
        if os.path.exists('/proc/device-tree/model'):
            with open('/proc/device-tree/model', 'rb') as f:
                info["model"] = f.read().decode('utf-8', errors='ignore').strip('\x00')
    except Exception:
        pass

    try:
        # Get CUDA info
        if torch.cuda.is_available():
            info["cuda_available"] = True
            info["gpu_name"] = torch.cuda.get_device_name(0)
            info["cuda_capability"] = torch.cuda.get_device_capability(0)
            props = torch.cuda.get_device_properties(0)
            info["gpu_memory_gb"] = props.total_memory / (1024**3)
    except Exception:
        pass

    return info


class EmbeddingCache:
    """LRU cache for query embeddings with TTL support.

    Caches computed embeddings to avoid re-computing for repeated queries.
    Uses an OrderedDict for O(1) LRU operations.
    """

    def __init__(self, max_size: int = 1000, ttl_seconds: int = 3600):
        """Initialize the embedding cache.

        Args:
            max_size: Maximum number of embeddings to cache (default: 1000, ~1.5MB for 384-dim)
            ttl_seconds: Time-to-live in seconds for cache entries (default: 1 hour)
        """
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self._cache: OrderedDict[str, Tuple[np.ndarray, float]] = OrderedDict()
        self._hits = 0
        self._misses = 0

    def _make_key(self, text: str) -> str:
        """Create a cache key from text using MD5 hash."""
        return hashlib.md5(text.encode('utf-8')).hexdigest()

    def get(self, text: str) -> Optional[np.ndarray]:
        """Get cached embedding for text if available and not expired.

        Args:
            text: The text to look up

        Returns:
            Cached embedding array or None if not found/expired
        """
        key = self._make_key(text)
        if key not in self._cache:
            self._misses += 1
            return None

        embedding, timestamp = self._cache[key]
        if time.time() - timestamp > self.ttl_seconds:
            # Expired, remove and return None
            del self._cache[key]
            self._misses += 1
            return None

        # Move to end (most recently used)
        self._cache.move_to_end(key)
        self._hits += 1
        return embedding

    def put(self, text: str, embedding: np.ndarray) -> None:
        """Store embedding in cache.

        Args:
            text: The text key
            embedding: The embedding array to cache
        """
        key = self._make_key(text)

        # If key exists, update and move to end
        if key in self._cache:
            self._cache[key] = (embedding.copy(), time.time())
            self._cache.move_to_end(key)
            return

        # Evict oldest if at capacity
        while len(self._cache) >= self.max_size:
            self._cache.popitem(last=False)

        self._cache[key] = (embedding.copy(), time.time())

    def clear(self) -> None:
        """Clear all cached embeddings."""
        self._cache.clear()
        self._hits = 0
        self._misses = 0

    def stats(self) -> dict:
        """Get cache statistics.

        Returns:
            Dict with hits, misses, size, and hit_rate
        """
        total = self._hits + self._misses
        hit_rate = self._hits / total if total > 0 else 0.0
        return {
            "hits": self._hits,
            "misses": self._misses,
            "size": len(self._cache),
            "max_size": self.max_size,
            "hit_rate": hit_rate,
            "ttl_seconds": self.ttl_seconds
        }

    def __len__(self) -> int:
        return len(self._cache)


class EmbeddingModel:
    """Lightweight embedding model using sentence-transformers.

    Automatically selects the best model based on available hardware:
    - Desktop GPU: Uses bge-small-en-v1.5 (384 dims, good quality)
    - Jetson GPU: Uses bge-small-en-v1.5 (384 dims, +6 MTEB pts vs MiniLM, 512 token context)
    - CPU only: Uses bge-small-en-v1.5 (384 dims, slightly slower than MiniLM but better quality)

    Jetson-specific optimizations:
    - FP16 inference for faster GPU execution
    - Smaller batch sizes to fit in unified memory
    - 384-dimension model to reduce memory pressure
    """

    # Model recommendations based on hardware
    # bge-small-en-v1.5: 33M params, 384-dim, 512 token context, ~62 MTEB retrieval
    # (upgraded from all-MiniLM-L6-v2: 22M params, 384-dim, 256 token context, ~56 MTEB)
    RECOMMENDED_MODELS = {
        "cpu": "BAAI/bge-small-en-v1.5",                     # Better quality than MiniLM, 384-dim
        "cuda": "BAAI/bge-small-en-v1.5",                    # Same model, GPU accelerated
        "jetson": "BAAI/bge-small-en-v1.5"                   # Optimized for Jetson edge (~100MB GPU)
    }

    def __init__(
        self,
        model_name: Optional[str] = None,
        cache_dir: str = "./models",
        device: Optional[str] = None,
        enable_query_cache: bool = True,
        query_cache_size: int = 1000,
        query_cache_ttl: int = 3600
    ):
        """Initialize the embedding model.

        Args:
            model_name: HuggingFace model identifier. If None, auto-selects based on hardware:
                       - Desktop GPU: all-mpnet-base-v2 (768 dims, better quality)
                       - Jetson GPU: all-MiniLM-L6-v2 (384 dims, edge optimized)
                       - CPU only: all-MiniLM-L6-v2 (384 dims, faster)
            cache_dir: Directory to cache downloaded models
            device: Device to run inference on ('cpu', 'cuda', or None for auto-detect)
                   If None, automatically uses CUDA if available, otherwise CPU
            enable_query_cache: If True (default), cache query embeddings for faster repeated queries
            query_cache_size: Maximum number of query embeddings to cache (default: 1000)
            query_cache_ttl: Time-to-live in seconds for cached embeddings (default: 3600 = 1 hour)
        """
        self.cache_dir = cache_dir
        self.is_jetson = is_jetson_device()
        self.jetson_info = get_jetson_info() if self.is_jetson else None

        # Log Jetson detection
        if self.is_jetson:
            print(f"🚀 Jetson device detected!")
            if self.jetson_info:
                print(f"   Model: {self.jetson_info.get('model', 'Unknown')}")
                if 'gpu_name' in self.jetson_info:
                    print(f"   GPU: {self.jetson_info['gpu_name']}")
                    print(f"   Memory: {self.jetson_info.get('gpu_memory_gb', 0):.1f}GB")

        # Auto-detect device if not specified
        if device is None:
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
            print(f"Auto-detected device: {self.device}")
        else:
            self.device = device

        # Verify CUDA availability if requested
        if self.device == "cuda" and not torch.cuda.is_available():
            print("CUDA requested but not available. Falling back to CPU.")
            self.device = "cpu"

        # Auto-select model based on device and platform
        if model_name is None:
            if self.is_jetson and self.device == "cuda":
                # Use smaller model on Jetson for better performance
                model_name = self.RECOMMENDED_MODELS["jetson"]
                print(f"Auto-selected model: {model_name}")
                print(f"  Reason: Optimized for Jetson edge device")
                print(f"  Benefits: Fast GPU inference (384 dims), low memory footprint")
            elif self.device == "cuda":
                model_name = self.RECOMMENDED_MODELS["cuda"]
                print(f"Auto-selected model: {model_name}")
                print(f"  Reason: Optimized for desktop GPU")
                print(f"  Benefits: Better quality (768 dims), GPU makes it fast (~10-15ms)")
            else:
                model_name = self.RECOMMENDED_MODELS["cpu"]
                print(f"Auto-selected model: {model_name}")
                print(f"  Reason: Optimized for CPU")
                print(f"  Benefits: Fast on CPU (~20ms), minimal memory (22MB)")

        self.model_name = model_name

        # Create cache directory if it doesn't exist
        os.makedirs(cache_dir, exist_ok=True)

        print(f"Loading embedding model: {model_name}")
        self.model = SentenceTransformer(
            model_name,
            cache_folder=cache_dir,
            device=self.device
        )

        # Apply Jetson optimizations: use FP16 for faster inference
        if self.is_jetson and self.device == "cuda":
            try:
                self.model = self.model.half()  # Convert to FP16
                print("  Jetson optimization: FP16 inference enabled")
            except Exception as e:
                print(f"  FP16 conversion failed, using FP32: {e}")

        self.embedding_dim = self.model.get_sentence_embedding_dimension()

        # Set batch size based on device (smaller for Jetson due to memory)
        self._batch_size = 8 if self.is_jetson else 32

        # Initialize query embedding cache
        self._query_cache: Optional[EmbeddingCache] = None
        if enable_query_cache:
            self._query_cache = EmbeddingCache(max_size=query_cache_size, ttl_seconds=query_cache_ttl)
            print(f"Query embedding cache enabled: max_size={query_cache_size}, ttl={query_cache_ttl}s")

        # Show device info
        if self.device == "cuda":
            gpu_name = torch.cuda.get_device_name(0)
            gpu_memory = torch.cuda.get_device_properties(0).total_memory / (1024**3)
            print(f"Model loaded on GPU: {gpu_name} ({gpu_memory:.1f}GB)")
        else:
            print(f"Model loaded on CPU")

        print(f"Embedding dimension: {self.embedding_dim}")
        self._is_loaded = True

    def unload(self) -> None:
        """Unload the model from GPU to free memory for other models."""
        if not self._is_loaded:
            return

        print(f"Unloading embedding model from {self.device}...")
        if self.model is not None:
            del self.model
            self.model = None

        self._is_loaded = False

        # Force garbage collection and clear CUDA cache
        import gc
        gc.collect()
        if self.device == "cuda" and torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()

        print("Embedding model unloaded")

    def reload(self) -> None:
        """Reload the model onto GPU."""
        if self._is_loaded:
            return

        print(f"Reloading embedding model: {self.model_name}")
        self.model = SentenceTransformer(
            self.model_name,
            cache_folder=self.cache_dir,
            device=self.device
        )

        # Re-apply Jetson optimizations
        if self.is_jetson and self.device == "cuda":
            try:
                self.model = self.model.half()
                print("  Jetson optimization: FP16 inference enabled")
            except Exception as e:
                print(f"  FP16 conversion failed, using FP32: {e}")

        self._is_loaded = True
        print(f"Embedding model reloaded on {self.device}")

    def is_loaded(self) -> bool:
        """Check if the model is currently loaded."""
        return self._is_loaded and self.model is not None

    def embed(self, texts: Union[str, List[str]]) -> np.ndarray:
        """Generate embeddings for text(s).

        Args:
            texts: Single text string or list of text strings

        Returns:
            numpy array of shape (n, embedding_dim) where n is number of texts

        Raises:
            RuntimeError: If model is not loaded (call reload() first)
        """
        if not self._is_loaded or self.model is None:
            raise RuntimeError(
                "Embedding model is not loaded. "
                "Call model_manager.ensure_loaded(ModelType.EMBEDDING) first."
            )

        if isinstance(texts, str):
            texts = [texts]

        # Generate embeddings with device-appropriate batch size
        embeddings = self.model.encode(
            texts,
            convert_to_numpy=True,
            show_progress_bar=len(texts) > 10,
            batch_size=self._batch_size
        )

        return embeddings

    def embed_query(self, query: str, use_cache: bool = True) -> np.ndarray:
        """Generate embedding for a search query with optional caching.

        Args:
            query: Search query text
            use_cache: If True (default), check cache before computing and cache result

        Returns:
            numpy array of shape (embedding_dim,)
        """
        # Check cache first if enabled
        if use_cache and self._query_cache is not None:
            cached = self._query_cache.get(query)
            if cached is not None:
                return cached

        # Compute embedding
        embedding = self.embed(query)[0]

        # Store in cache if enabled
        if use_cache and self._query_cache is not None:
            self._query_cache.put(query, embedding)

        return embedding

    def get_dimension(self) -> int:
        """Get the embedding dimension."""
        return self.embedding_dim

    def get_cache_stats(self) -> Optional[dict]:
        """Get query cache statistics.

        Returns:
            Dict with cache stats or None if caching is disabled
        """
        if self._query_cache is None:
            return None
        return self._query_cache.stats()

    def clear_cache(self) -> None:
        """Clear the query embedding cache."""
        if self._query_cache is not None:
            self._query_cache.clear()

    def __repr__(self) -> str:
        cache_info = ""
        if self._query_cache is not None:
            stats = self._query_cache.stats()
            cache_info = f", cache_size={stats['size']}/{stats['max_size']}"
        return f"EmbeddingModel(model='{self.model_name}', dim={self.embedding_dim}, device='{self.device}'{cache_info})"
