"""Dynamic model manager for GPU memory optimization.

On memory-constrained devices like Jetson, this manager ensures only one
heavy model is loaded at a time, dynamically loading/unloading as needed.

GPU models (embedding, reranker, transcription, caption) can be swapped based on memory constraints.
"""

import gc
import threading
from enum import Enum
from typing import Optional, Any, Callable, TYPE_CHECKING
from dataclasses import dataclass, field

if TYPE_CHECKING:
    from .reranker import Reranker


class ModelType(Enum):
    """Types of models that can be managed."""
    EMBEDDING = "embedding"      # GPU, swappable - needed for search/indexing
    RERANKER = "reranker"        # GPU, swappable - needed for search reranking
    LPRAG_VOCAB = "lprag_vocab"  # GPU, swappable - needed for LPRAG
    TRANSCRIPTION = "transcription"  # GPU, swappable - Whisper for audio-to-text
    CAPTION = "caption"          # GPU, swappable - BLIP for image captioning
    OCR = "ocr"                  # GPU, swappable - EasyOCR for image PII detection


@dataclass
class ManagedModel:
    """A model managed by the ModelManager."""
    model_type: ModelType
    instance: Any = None
    is_loaded: bool = False
    on_gpu: bool = True
    _refcount: int = 0  # Active users of this model (prevent unload while in use)

    # Callbacks for loading/unloading
    _load_fn: Optional[Callable[[], None]] = field(default=None, repr=False)
    _unload_fn: Optional[Callable[[], None]] = field(default=None, repr=False)
    _get_instance_fn: Optional[Callable[[], Any]] = field(default=None, repr=False)


# Heavy models that are used infrequently and should be unloaded after use
# to free memory. Embedding/reranker stay resident for fast search.
TRANSIENT_MODELS = {
    ModelType.CAPTION,        # BLIP ~1-1.5GB, used only during image upload
    ModelType.TRANSCRIPTION,  # Whisper ~1GB, used only during audio upload
    ModelType.OCR,            # EasyOCR ~600-900MB, used only during PII redaction
}

class ModelManager:
    """Manages GPU memory by dynamically loading/unloading models.

    On Jetson devices with limited GPU memory (~7GB shared), this ensures
    only one heavy model is loaded at any time to prevent OOM errors.

    Transient models (CAPTION, TRANSCRIPTION, OCR) are automatically unloaded
    after use via the require() context manager to reclaim memory.

    Usage:
        manager = ModelManager(verbose=True)

        # Register models with their load/unload callbacks
        manager.register_reranker(reranker)
        manager.register_embedding(embedding_model)

        # Request a model - others will be unloaded automatically
        with manager.require(ModelType.RERANKER):
            result = reranker.rerank(query, docs)
    """

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self._models: dict[ModelType, ManagedModel] = {}
        self._lock = threading.RLock()
        self._current_gpu_model: Optional[ModelType] = None

        # GPU scheduling: circuit breaker + memory monitor
        from .gpu_scheduler import (
            create_circuit_breaker,
            create_memory_monitor,
            MODEL_SIZE_ESTIMATES_MB,
        )
        self._circuit_breaker = create_circuit_breaker()
        self._memory_monitor = create_memory_monitor()
        self._model_sizes = MODEL_SIZE_ESTIMATES_MB

    def register_embedding(self, embedding_model: Any) -> None:
        """Register embedding model for management.

        The embedding model is now swappable like other GPU models.
        When TinyLlama needs GPU, embeddings will be unloaded.
        """
        self._models[ModelType.EMBEDDING] = ManagedModel(
            model_type=ModelType.EMBEDDING,
            instance=embedding_model,
            is_loaded=embedding_model.is_loaded(),
            on_gpu=embedding_model.device == "cuda",
            _load_fn=embedding_model.reload,
            _unload_fn=embedding_model.unload,
            _get_instance_fn=lambda: embedding_model.model
        )
        if embedding_model.is_loaded() and embedding_model.device == "cuda":
            self._current_gpu_model = ModelType.EMBEDDING
        if self.verbose:
            print(f"ModelManager: Registered Embedding (GPU: {embedding_model.device == 'cuda'})")

    def register_reranker(self, reranker: "Reranker") -> None:
        """Register reranker for management."""
        self._models[ModelType.RERANKER] = ManagedModel(
            model_type=ModelType.RERANKER,
            instance=reranker,
            is_loaded=reranker.is_available(),
            on_gpu=reranker.device == "cuda",
            _load_fn=reranker.reload,
            _unload_fn=reranker.unload,
            _get_instance_fn=lambda: reranker.model
        )
        if reranker.is_available():
            self._current_gpu_model = ModelType.RERANKER
        if self.verbose:
            print(f"ModelManager: Registered Reranker (GPU: {reranker.device == 'cuda'})")

    def register_transcription(self, audio_processor: Any) -> None:
        """Register Whisper audio transcription model for management."""
        self._models[ModelType.TRANSCRIPTION] = ManagedModel(
            model_type=ModelType.TRANSCRIPTION,
            instance=audio_processor,
            is_loaded=audio_processor.is_loaded(),
            on_gpu=audio_processor.device == "cuda",
            _load_fn=audio_processor._load_model,
            _unload_fn=audio_processor._unload_model,
            _get_instance_fn=lambda: audio_processor._pipeline
        )
        if audio_processor.is_loaded() and audio_processor.device == "cuda":
            self._current_gpu_model = ModelType.TRANSCRIPTION
        if self.verbose:
            print(f"ModelManager: Registered Transcription (GPU: {audio_processor.device == 'cuda'})")

    def register_caption(self, image_processor: Any) -> None:
        """Register BLIP image captioning model for management."""
        self._models[ModelType.CAPTION] = ManagedModel(
            model_type=ModelType.CAPTION,
            instance=image_processor,
            is_loaded=image_processor.is_loaded(),
            on_gpu=image_processor.device == "cuda",
            _load_fn=image_processor._load_model,
            _unload_fn=image_processor._unload_model,
            _get_instance_fn=lambda: image_processor._pipeline
        )
        if image_processor.is_loaded() and image_processor.device == "cuda":
            self._current_gpu_model = ModelType.CAPTION
        if self.verbose:
            print(f"ModelManager: Registered Caption (GPU: {image_processor.device == 'cuda'})")

    def register_lprag_vocab(self, lprag_engine: Any) -> None:
        """Register LPRAG vocabulary for GPU-based semantic similarity.

        When use_gpu=True, LPRAG uses Sentence Transformers for higher quality
        semantic similarity. The vocabulary can be pre-encoded and stored on GPU
        for fast lookup during perturbation.

        Args:
            lprag_engine: LPRAGEngine instance configured with use_gpu=True.
        """
        # Check if LPRAG engine has GPU vocabulary support
        is_loaded = getattr(lprag_engine, 'is_vocab_loaded', lambda: False)()
        use_gpu = getattr(lprag_engine, 'use_gpu', False)

        self._models[ModelType.LPRAG_VOCAB] = ManagedModel(
            model_type=ModelType.LPRAG_VOCAB,
            instance=lprag_engine,
            is_loaded=is_loaded,
            on_gpu=use_gpu,
            _load_fn=getattr(lprag_engine, 'load_vocabulary', None),
            _unload_fn=getattr(lprag_engine, 'unload_vocabulary', None),
            _get_instance_fn=lambda: lprag_engine
        )
        if self.verbose:
            print(f"ModelManager: Registered LPRAG vocabulary (GPU: {use_gpu})")

    def register_ocr(self, image_pii_redactor: Any) -> None:
        """Register EasyOCR model for image PII detection.

        When GPU is available, EasyOCR uses CUDA for faster inference.
        The model can be swapped with other GPU models to manage memory.

        Args:
            image_pii_redactor: ImagePIIRedactor instance with EasyOCR.
        """
        is_loaded = getattr(image_pii_redactor, 'is_loaded', lambda: False)()
        use_gpu = getattr(image_pii_redactor, '_use_gpu', False)

        self._models[ModelType.OCR] = ManagedModel(
            model_type=ModelType.OCR,
            instance=image_pii_redactor,
            is_loaded=is_loaded,
            on_gpu=use_gpu,
            _load_fn=getattr(image_pii_redactor, '_load_easyocr_reader', None),
            _unload_fn=getattr(image_pii_redactor, '_unload_easyocr_reader', None),
            _get_instance_fn=lambda: image_pii_redactor._easyocr_reader
        )
        if is_loaded and use_gpu:
            self._current_gpu_model = ModelType.OCR
        if self.verbose:
            print(f"ModelManager: Registered OCR (GPU: {use_gpu})")

    def _clear_gpu_memory(self) -> None:
        """Force GPU memory cleanup."""
        import time
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.synchronize()
                # On Jetson, unified memory needs extra time to fully deallocate
                time.sleep(0.5)
        except ImportError:
            pass

    def _unload_model(self, model_type: ModelType, force: bool = False) -> None:
        """Unload a specific model.

        Args:
            model_type: Which model to unload
            force: If True, unload even if refcount > 0
        """
        model = self._models.get(model_type)
        if not model or not model.is_loaded:
            return

        # Skip unload if model is actively in use (unless forced)
        if model._refcount > 0 and not force:
            if self.verbose:
                print(f"ModelManager: Skipping unload of {model_type.value} "
                      f"(refcount={model._refcount})")
            return

        if self.verbose:
            print(f"ModelManager: Unloading {model_type.value}...")

        try:
            if model._unload_fn:
                model._unload_fn()
        except Exception as e:
            if self.verbose:
                print(f"ModelManager: Warning - error unloading {model_type.value}: {e}")

        model.is_loaded = False

        if self._current_gpu_model == model_type:
            self._current_gpu_model = None

        self._clear_gpu_memory()

        if self.verbose:
            print(f"ModelManager: Unloaded {model_type.value}")

    def _load_model(self, model_type: ModelType) -> None:
        """Load a specific model, unloading conflicting GPU models first.

        Integrates with GPUCircuitBreaker and MemoryMonitor for safe loading:
        1. Check circuit breaker — if OPEN, raise immediately (caller handles CPU fallback)
        2. Evict other GPU models (skip those with refcount > 0, wait up to 30s)
        3. Post-eviction memory pre-flight check
        4. Attempt load, recording success/failure with circuit breaker
        """
        model = self._models.get(model_type)
        if not model:
            raise ValueError(f"Model {model_type.value} not registered")

        if model.is_loaded:
            return

        # Step 1: Circuit breaker check for GPU loads
        if model.on_gpu and not self._circuit_breaker.allows_gpu_load():
            raise RuntimeError(
                f"GPU circuit breaker is OPEN — refusing to load {model_type.value} on GPU. "
                f"Too many recent OOM failures. Will retry after cooldown."
            )

        # Step 2: Evict other GPU models to free memory
        if model.on_gpu:
            for other_type, other_model in list(self._models.items()):
                if other_type == model_type or not other_model.on_gpu or not other_model.is_loaded:
                    continue

                # If model is in use, wait for it to finish (up to 30s)
                if other_model._refcount > 0:
                    if self.verbose:
                        print(f"ModelManager: Waiting for {other_type.value} "
                              f"(refcount={other_model._refcount}) to release...")
                    waited = 0.0
                    while other_model._refcount > 0 and waited < 30.0:
                        # Release lock while waiting to avoid deadlock
                        self._lock.release()
                        try:
                            import time
                            time.sleep(0.5)
                            waited += 0.5
                        finally:
                            self._lock.acquire()

                    # After reacquiring lock, check if our target model was loaded
                    # by another thread while we were waiting
                    if model.is_loaded:
                        return

                self._unload_model(other_type)

            # Step 3: Post-eviction memory pre-flight check
            model_size = self._model_sizes.get(model_type.value, 500)
            if not self._memory_monitor.has_headroom_for(model_size):
                self._circuit_breaker.record_failure(
                    MemoryError(f"Out of memory: cannot load {model_type.value} "
                                f"({model_size}MB needed, "
                                f"{self._memory_monitor.get_available_mb():.0f}MB available)")
                )
                raise MemoryError(
                    f"Insufficient memory to load {model_type.value}: "
                    f"need {model_size}MB + 200MB margin, "
                    f"have {self._memory_monitor.get_available_mb():.0f}MB available"
                )

        if self.verbose:
            print(f"ModelManager: Loading {model_type.value}...")

        try:
            if model._load_fn:
                model._load_fn()
            model.is_loaded = True

            if model.on_gpu:
                self._current_gpu_model = model_type
                self._circuit_breaker.record_success()

            if self.verbose:
                print(f"ModelManager: Loaded {model_type.value}")
        except Exception as e:
            if model.on_gpu:
                self._circuit_breaker.record_failure(e)
            if self.verbose:
                print(f"ModelManager: Failed to load {model_type.value}: {e}")
            raise

    def _load_model_no_evict(self, model_type: ModelType) -> None:
        """Load a model WITHOUT evicting other models (for voice mode coexistence).

        Still checks circuit breaker and memory to prevent OOM, but doesn't
        unload other models first.
        """
        model = self._models.get(model_type)
        if not model:
            return
        if model.is_loaded:
            return

        # Safety checks (even in no-evict mode, OOM is still dangerous)
        if model.on_gpu:
            if not self._circuit_breaker.allows_gpu_load():
                raise RuntimeError(
                    f"GPU circuit breaker is OPEN — refusing to load {model_type.value} (no-evict). "
                    f"Too many recent OOM failures."
                )
            model_size = self._model_sizes.get(model_type.value, 500)
            if not self._memory_monitor.has_headroom_for(model_size):
                raise MemoryError(
                    f"Insufficient memory to load {model_type.value} (no-evict): "
                    f"need {model_size}MB + 200MB margin, "
                    f"have {self._memory_monitor.get_available_mb():.0f}MB available"
                )

        if self.verbose:
            print(f"ModelManager: Loading {model_type.value} (no-evict)...")

        try:
            if model._load_fn:
                model._load_fn()
            model.is_loaded = True

            if model.on_gpu:
                self._circuit_breaker.record_success()

            if self.verbose:
                print(f"ModelManager: Loaded {model_type.value}")
        except Exception as e:
            if model.on_gpu:
                self._circuit_breaker.record_failure(e)
            if self.verbose:
                print(f"ModelManager: Failed to load {model_type.value}: {e}")
            raise

    def require(self, model_type: ModelType) -> "ModelContext":
        """Context manager to ensure a model is loaded.

        Usage:
            with manager.require(ModelType.TINYLLAMA):
                # TinyLlama is guaranteed to be loaded here
                # Reranker has been unloaded if it was using GPU
                result = topic_labeler.generate_topics(text)
            # Model stays loaded after context exits
        """
        return ModelContext(self, model_type)

    def ensure_loaded(self, model_type: ModelType) -> None:
        """Ensure a model is loaded, unloading others if needed."""
        with self._lock:
            self._load_model(model_type)

    def unload(self, model_type: ModelType) -> None:
        """Explicitly unload a model."""
        with self._lock:
            self._unload_model(model_type)

    def unload_all(self) -> None:
        """Unload all managed models."""
        with self._lock:
            for model_type in list(self._models.keys()):
                if model_type != ModelType.EMBEDDING:
                    self._unload_model(model_type)

    def is_loaded(self, model_type: ModelType) -> bool:
        """Check if a model is currently loaded."""
        model = self._models.get(model_type)
        return model.is_loaded if model else False

    def get_status(self) -> dict:
        """Get status of all managed models."""
        return {
            model_type.value: {
                "is_loaded": model.is_loaded,
                "on_gpu": model.on_gpu
            }
            for model_type, model in self._models.items()
        }

    def get_current_gpu_model(self) -> Optional[str]:
        """Get the currently loaded GPU model (excluding embedding)."""
        return self._current_gpu_model.value if self._current_gpu_model else None

    def get_scheduler_status(self) -> dict:
        """Get GPU scheduler status (circuit breaker + memory monitor) for debug endpoint."""
        return {
            "circuit_breaker": self._circuit_breaker.get_status(),
            "memory": self._memory_monitor.get_status(),
            "refcounts": {
                model_type.value: model._refcount
                for model_type, model in self._models.items()
            },
        }


class ModelContext:
    """Context manager for requiring a model to be loaded."""

    def __init__(self, manager: ModelManager, model_type: ModelType):
        self.manager = manager
        self.model_type = model_type

    def __enter__(self):
        self.manager.ensure_loaded(self.model_type)
        # Increment refcount to prevent eviction while in use
        with self.manager._lock:
            model = self.manager._models.get(self.model_type)
            if model:
                model._refcount += 1
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        should_unload = False

        # Decrement refcount and check if transient model should be unloaded,
        # all in a single lock acquisition to prevent races.
        with self.manager._lock:
            model = self.manager._models.get(self.model_type)
            if model:
                model._refcount = max(0, model._refcount - 1)
                # Unload transient models (BLIP, Whisper, OCR) after use to free memory,
                # but only when no other users hold a reference (refcount == 0).
                if self.model_type in TRANSIENT_MODELS and model._refcount == 0:
                    should_unload = True

        if should_unload:
            if self.manager.verbose:
                print(f"ModelManager: Auto-unloading transient model {self.model_type.value}")
            self.manager.unload(self.model_type)


# Global model manager instance
_global_manager: Optional[ModelManager] = None


def get_model_manager(verbose: bool = False) -> ModelManager:
    """Get or create the global model manager."""
    global _global_manager
    if _global_manager is None:
        _global_manager = ModelManager(verbose=verbose)
    return _global_manager


def reset_model_manager() -> None:
    """Reset the global model manager (for testing)."""
    global _global_manager
    if _global_manager:
        _global_manager.unload_all()
    _global_manager = None
