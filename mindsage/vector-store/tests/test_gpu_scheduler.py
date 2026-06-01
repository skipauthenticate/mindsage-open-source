"""Tests for GPU scheduler: MemoryMonitor, GPUCircuitBreaker, and ModelManager integration."""

import time
import threading
from unittest.mock import patch, MagicMock, call

import pytest

from mcp_vector_store.gpu_scheduler import (
    MemoryMonitor,
    GPUCircuitBreaker,
    CircuitState,
    MODEL_SIZE_ESTIMATES_MB,
    _is_oom_error,
    create_memory_monitor,
    create_circuit_breaker,
)
from mcp_vector_store.model_manager import (
    ModelManager,
    ModelType,
    ManagedModel,
    ModelContext,
    TRANSIENT_MODELS,
)


# --- MemoryMonitor Tests ---


class TestMemoryMonitor:
    """Tests for MemoryMonitor class."""

    def test_default_watermarks(self):
        monitor = MemoryMonitor()
        assert monitor.high_watermark_pct == 85.0
        assert monitor.low_watermark_pct == 70.0

    def test_custom_watermarks(self):
        monitor = MemoryMonitor(high_watermark_pct=90.0, low_watermark_pct=60.0)
        assert monitor.high_watermark_pct == 90.0
        assert monitor.low_watermark_pct == 60.0

    @patch("mcp_vector_store.gpu_scheduler.psutil")
    def test_get_available_mb(self, mock_psutil):
        mock_psutil.virtual_memory.return_value = MagicMock(
            available=2 * 1024 * 1024 * 1024  # 2GB
        )
        monitor = MemoryMonitor()
        assert monitor.get_available_mb() == pytest.approx(2048.0)

    @patch("mcp_vector_store.gpu_scheduler.psutil")
    def test_get_used_pct(self, mock_psutil):
        mock_psutil.virtual_memory.return_value = MagicMock(percent=72.5)
        monitor = MemoryMonitor()
        assert monitor.get_used_pct() == 72.5

    @patch("mcp_vector_store.gpu_scheduler.psutil")
    def test_has_headroom_for_sufficient(self, mock_psutil):
        mock_psutil.virtual_memory.return_value = MagicMock(
            available=2 * 1024 * 1024 * 1024  # 2GB
        )
        monitor = MemoryMonitor()
        # 500MB model + 200MB margin = 700MB needed, 2048MB available
        assert monitor.has_headroom_for(500) is True

    @patch("mcp_vector_store.gpu_scheduler.psutil")
    def test_has_headroom_for_insufficient(self, mock_psutil):
        mock_psutil.virtual_memory.return_value = MagicMock(
            available=200 * 1024 * 1024  # 200MB
        )
        monitor = MemoryMonitor()
        # 500MB model + 200MB margin = 700MB needed, 200MB available
        assert monitor.has_headroom_for(500) is False

    @patch("mcp_vector_store.gpu_scheduler.psutil")
    def test_has_headroom_for_custom_margin(self, mock_psutil):
        mock_psutil.virtual_memory.return_value = MagicMock(
            available=400 * 1024 * 1024  # 400MB
        )
        monitor = MemoryMonitor()
        # 300MB model + 50MB margin = 350MB needed, 400MB available
        assert monitor.has_headroom_for(300, safety_margin_mb=50) is True

    @patch("mcp_vector_store.gpu_scheduler.psutil")
    def test_has_headroom_for_exact_boundary(self, mock_psutil):
        """Edge case: exactly enough memory (boundary condition)."""
        mock_psutil.virtual_memory.return_value = MagicMock(
            available=700 * 1024 * 1024  # 700MB
        )
        monitor = MemoryMonitor()
        # 500MB model + 200MB margin = 700MB needed, 700MB available
        assert monitor.has_headroom_for(500) is True

    @patch("mcp_vector_store.gpu_scheduler.psutil")
    def test_has_headroom_for_one_byte_short(self, mock_psutil):
        """Edge case: one byte less than needed."""
        needed_bytes = (500 + 200) * 1024 * 1024 - 1
        mock_psutil.virtual_memory.return_value = MagicMock(available=needed_bytes)
        monitor = MemoryMonitor()
        assert monitor.has_headroom_for(500) is False

    @patch("mcp_vector_store.gpu_scheduler.psutil")
    def test_is_above_high_watermark(self, mock_psutil):
        mock_psutil.virtual_memory.return_value = MagicMock(percent=90.0)
        monitor = MemoryMonitor(high_watermark_pct=85.0)
        assert monitor.is_above_high_watermark() is True

    @patch("mcp_vector_store.gpu_scheduler.psutil")
    def test_is_above_high_watermark_exact(self, mock_psutil):
        """Edge case: exactly at high watermark (should trigger)."""
        mock_psutil.virtual_memory.return_value = MagicMock(percent=85.0)
        monitor = MemoryMonitor(high_watermark_pct=85.0)
        assert monitor.is_above_high_watermark() is True

    @patch("mcp_vector_store.gpu_scheduler.psutil")
    def test_is_below_low_watermark(self, mock_psutil):
        mock_psutil.virtual_memory.return_value = MagicMock(percent=60.0)
        monitor = MemoryMonitor(low_watermark_pct=70.0)
        assert monitor.is_below_low_watermark() is True

    @patch("mcp_vector_store.gpu_scheduler.psutil")
    def test_is_below_low_watermark_exact(self, mock_psutil):
        """Edge case: exactly at low watermark (should resume)."""
        mock_psutil.virtual_memory.return_value = MagicMock(percent=70.0)
        monitor = MemoryMonitor(low_watermark_pct=70.0)
        assert monitor.is_below_low_watermark() is True

    @patch("mcp_vector_store.gpu_scheduler.psutil")
    def test_wait_for_memory_already_below(self, mock_psutil):
        mock_psutil.virtual_memory.return_value = MagicMock(percent=50.0)
        monitor = MemoryMonitor(low_watermark_pct=70.0)
        assert monitor.wait_for_memory(timeout=1.0) is True

    @patch("mcp_vector_store.gpu_scheduler.psutil")
    def test_wait_for_memory_timeout(self, mock_psutil):
        mock_psutil.virtual_memory.return_value = MagicMock(percent=90.0)
        monitor = MemoryMonitor(low_watermark_pct=70.0)
        # Should timeout quickly
        assert monitor.wait_for_memory(timeout=1.5) is False

    @patch("mcp_vector_store.gpu_scheduler.psutil")
    def test_wait_for_memory_drops_during_wait(self, mock_psutil):
        """Edge case: memory drops below watermark during wait."""
        # First call: above watermark, second call: below
        mock_psutil.virtual_memory.side_effect = [
            MagicMock(percent=90.0),  # is_below_low_watermark check -> False
            MagicMock(percent=50.0),  # next check -> True
        ]
        monitor = MemoryMonitor(low_watermark_pct=70.0)
        assert monitor.wait_for_memory(timeout=5.0) is True

    @patch("mcp_vector_store.gpu_scheduler.psutil")
    def test_get_status(self, mock_psutil):
        mock_psutil.virtual_memory.return_value = MagicMock(
            available=3 * 1024 * 1024 * 1024, percent=60.0
        )
        monitor = MemoryMonitor()
        status = monitor.get_status()
        assert "available_mb" in status
        assert "used_pct" in status
        assert "high_watermark_pct" in status
        assert "above_high_watermark" in status
        assert status["above_high_watermark"] is False


# --- GPUCircuitBreaker Tests ---


class TestGPUCircuitBreaker:
    """Tests for GPUCircuitBreaker state transitions."""

    def test_initial_state_closed(self):
        cb = GPUCircuitBreaker()
        assert cb.state == CircuitState.CLOSED
        assert cb.allows_gpu_load() is True

    def test_single_failure_stays_closed(self):
        cb = GPUCircuitBreaker(failure_threshold=3)
        cb.record_failure(MemoryError("CUDA out of memory"))
        assert cb.state == CircuitState.CLOSED
        assert cb.allows_gpu_load() is True

    def test_threshold_failures_opens_circuit(self):
        cb = GPUCircuitBreaker(failure_threshold=3)
        for _ in range(3):
            cb.record_failure(MemoryError("CUDA out of memory"))
        assert cb.state == CircuitState.OPEN
        assert cb.allows_gpu_load() is False

    def test_non_oom_errors_ignored(self):
        cb = GPUCircuitBreaker(failure_threshold=2)
        cb.record_failure(ValueError("model not found"))
        cb.record_failure(ValueError("model not found"))
        cb.record_failure(ValueError("model not found"))
        # Non-OOM errors should not count
        assert cb.state == CircuitState.CLOSED
        assert cb.allows_gpu_load() is True

    def test_mixed_oom_and_non_oom_errors(self):
        """Edge case: non-OOM errors interleaved with OOM don't affect count."""
        cb = GPUCircuitBreaker(failure_threshold=3)
        cb.record_failure(MemoryError("CUDA out of memory"))
        cb.record_failure(ValueError("model not found"))  # ignored
        cb.record_failure(MemoryError("CUDA out of memory"))
        cb.record_failure(RuntimeError("file not found"))  # ignored
        cb.record_failure(MemoryError("CUDA out of memory"))
        assert cb.state == CircuitState.OPEN

    def test_success_resets_failure_count(self):
        cb = GPUCircuitBreaker(failure_threshold=3)
        cb.record_failure(MemoryError("CUDA out of memory"))
        cb.record_failure(MemoryError("CUDA out of memory"))
        cb.record_success()
        # After success, need 3 more failures to open
        cb.record_failure(MemoryError("CUDA out of memory"))
        assert cb.state == CircuitState.CLOSED

    def test_cooldown_transitions_to_half_open(self):
        cb = GPUCircuitBreaker(failure_threshold=2, cooldown_seconds=0.1)
        cb.record_failure(MemoryError("out of memory"))
        cb.record_failure(MemoryError("out of memory"))
        assert cb.state == CircuitState.OPEN

        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN
        assert cb.allows_gpu_load() is True

    def test_half_open_success_closes(self):
        cb = GPUCircuitBreaker(failure_threshold=2, cooldown_seconds=0.1)
        cb.record_failure(MemoryError("out of memory"))
        cb.record_failure(MemoryError("out of memory"))

        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN

        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_half_open_failure_reopens(self):
        cb = GPUCircuitBreaker(failure_threshold=2, cooldown_seconds=0.1)
        cb.record_failure(MemoryError("out of memory"))
        cb.record_failure(MemoryError("out of memory"))

        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN

        cb.record_failure(MemoryError("still out of memory"))
        assert cb.state == CircuitState.OPEN

    def test_multiple_cooldown_cycles(self):
        """Edge case: circuit opens, cools down, fails again, reopens, cools down."""
        cb = GPUCircuitBreaker(failure_threshold=1, cooldown_seconds=0.1)

        # First cycle: fail -> open -> cooldown -> half_open -> fail -> open
        cb.record_failure(MemoryError("OOM"))
        assert cb.state == CircuitState.OPEN

        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN

        cb.record_failure(MemoryError("OOM again"))
        assert cb.state == CircuitState.OPEN

        # Second cycle: cooldown -> half_open -> success -> closed
        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN

        cb.record_success()
        assert cb.state == CircuitState.CLOSED
        assert cb._consecutive_failures == 0

    def test_threshold_of_one(self):
        """Edge case: threshold=1, single failure opens circuit."""
        cb = GPUCircuitBreaker(failure_threshold=1)
        cb.record_failure(MemoryError("OOM"))
        assert cb.state == CircuitState.OPEN

    def test_get_status(self):
        cb = GPUCircuitBreaker(failure_threshold=3, cooldown_seconds=30)
        status = cb.get_status()
        assert status["state"] == "closed"
        assert status["consecutive_failures"] == 0
        assert status["failure_threshold"] == 3

    def test_get_status_open_shows_cooldown(self):
        cb = GPUCircuitBreaker(failure_threshold=2, cooldown_seconds=30)
        cb.record_failure(MemoryError("OOM"))
        cb.record_failure(MemoryError("OOM"))
        status = cb.get_status()
        assert status["state"] == "open"
        assert "cooldown_remaining_seconds" in status
        assert status["cooldown_remaining_seconds"] > 0

    def test_get_status_shows_last_error(self):
        """Edge case: status includes truncated error message."""
        cb = GPUCircuitBreaker(failure_threshold=1)
        # Error must match OOM patterns to be counted
        long_error = "CUDA out of memory " + "x" * 500
        cb.record_failure(MemoryError(long_error))
        status = cb.get_status()
        assert "last_error" in status
        assert len(status["last_error"]) <= 200


# --- OOM Error Detection Tests ---


class TestOOMErrorDetection:
    """Tests for OOM error pattern matching."""

    def test_cuda_out_of_memory(self):
        assert _is_oom_error(RuntimeError("CUDA out of memory")) is True

    def test_nvmap_error(self):
        assert _is_oom_error(RuntimeError("NvMapMemAllocInternalTagged error 12")) is True

    def test_generic_oom(self):
        assert _is_oom_error(MemoryError("out of memory")) is True

    def test_alloc_error(self):
        assert _is_oom_error(RuntimeError("memory allocation failed")) is True

    def test_non_oom_error(self):
        assert _is_oom_error(ValueError("model not found")) is False
        assert _is_oom_error(FileNotFoundError("no such file")) is False

    def test_case_insensitive(self):
        """Edge case: OOM patterns should match case-insensitively."""
        assert _is_oom_error(RuntimeError("CUDA OUT OF MEMORY")) is True
        assert _is_oom_error(RuntimeError("Out Of Memory")) is True

    def test_empty_error_message(self):
        """Edge case: empty error message."""
        assert _is_oom_error(RuntimeError("")) is False

    def test_cudnn_error(self):
        """Edge case: cuDNN error should be detected."""
        assert _is_oom_error(RuntimeError("cuDNN error: out of resources")) is True

    def test_error_12_pattern(self):
        """Edge case: Jetson-specific NvMapMemAlloc error 12."""
        assert _is_oom_error(RuntimeError("NvMapMemAllocInternalTagged: FAILED with error 12")) is True


# --- Environment Variable Configuration Tests ---


class TestConfiguration:
    """Tests for environment variable configuration."""

    @patch.dict("os.environ", {"GPU_MEMORY_HIGH_WATERMARK": "90", "GPU_MEMORY_LOW_WATERMARK": "60"})
    def test_create_memory_monitor_from_env(self):
        monitor = create_memory_monitor()
        assert monitor.high_watermark_pct == 90.0
        assert monitor.low_watermark_pct == 60.0

    @patch.dict("os.environ", {"GPU_CIRCUIT_BREAKER_THRESHOLD": "5", "GPU_CIRCUIT_BREAKER_COOLDOWN": "60"})
    def test_create_circuit_breaker_from_env(self):
        cb = create_circuit_breaker()
        assert cb._failure_threshold == 5
        assert cb._cooldown_seconds == 60.0

    def test_model_size_estimates(self):
        assert "embedding" in MODEL_SIZE_ESTIMATES_MB
        assert "reranker" in MODEL_SIZE_ESTIMATES_MB
        assert "transcription" in MODEL_SIZE_ESTIMATES_MB
        assert "caption" in MODEL_SIZE_ESTIMATES_MB
        assert MODEL_SIZE_ESTIMATES_MB["caption"] == 1500

    def test_model_size_estimates_all_types(self):
        """Verify all ModelType enum values have size estimates."""
        for mt in ModelType:
            assert mt.value in MODEL_SIZE_ESTIMATES_MB, (
                f"Missing size estimate for {mt.value}"
            )


# --- ModelManager Integration Tests ---


class TestModelManagerRefcount:
    """Tests for ModelManager refcount behavior."""

    def _make_manager(self, on_gpu=True):
        """Create a ModelManager with a mock model."""
        manager = ModelManager(verbose=False)
        model = ManagedModel(
            model_type=ModelType.CAPTION,
            instance=MagicMock(),
            is_loaded=False,
            on_gpu=on_gpu,
            _load_fn=lambda: None,
            _unload_fn=lambda: None,
            _get_instance_fn=lambda: None,
        )
        manager._models[ModelType.CAPTION] = model
        return manager, model

    def _make_manager_two_models(self):
        """Create a ModelManager with two GPU models for eviction tests."""
        manager = ModelManager(verbose=False)
        embedding = ManagedModel(
            model_type=ModelType.EMBEDDING,
            instance=MagicMock(),
            is_loaded=True,
            on_gpu=True,
            _load_fn=lambda: None,
            _unload_fn=lambda: None,
            _get_instance_fn=lambda: None,
        )
        caption = ManagedModel(
            model_type=ModelType.CAPTION,
            instance=MagicMock(),
            is_loaded=False,
            on_gpu=True,
            _load_fn=lambda: None,
            _unload_fn=lambda: None,
            _get_instance_fn=lambda: None,
        )
        manager._models[ModelType.EMBEDDING] = embedding
        manager._models[ModelType.CAPTION] = caption
        manager._current_gpu_model = ModelType.EMBEDDING
        return manager, embedding, caption

    @patch("mcp_vector_store.gpu_scheduler.psutil")
    def test_require_increments_refcount(self, mock_psutil):
        mock_psutil.virtual_memory.return_value = MagicMock(
            available=4 * 1024 * 1024 * 1024, percent=50.0
        )
        manager, model = self._make_manager()
        assert model._refcount == 0

        with manager.require(ModelType.CAPTION):
            assert model._refcount == 1

        # CAPTION is transient, so after exit with refcount=0 it gets unloaded
        # refcount should be 0 after exit
        assert model._refcount == 0

    @patch("mcp_vector_store.gpu_scheduler.psutil")
    def test_require_nested_increments(self, mock_psutil):
        """Edge case: nested require() calls increment refcount correctly."""
        mock_psutil.virtual_memory.return_value = MagicMock(
            available=4 * 1024 * 1024 * 1024, percent=50.0
        )
        manager, model = self._make_manager()

        with manager.require(ModelType.CAPTION):
            assert model._refcount == 1
            with manager.require(ModelType.CAPTION):
                assert model._refcount == 2
            # Inner exit decrements but doesn't unload (refcount=1 > 0)
            assert model._refcount == 1
            assert model.is_loaded is True

        # Outer exit: refcount=0, transient model auto-unloads
        assert model._refcount == 0

    @patch("mcp_vector_store.gpu_scheduler.psutil")
    def test_refcount_never_goes_negative(self, mock_psutil):
        """Edge case: refcount should never go below 0."""
        mock_psutil.virtual_memory.return_value = MagicMock(
            available=4 * 1024 * 1024 * 1024, percent=50.0
        )
        manager, model = self._make_manager()
        model.is_loaded = True

        # Manually set refcount to 0 and decrement via __exit__
        model._refcount = 0
        ctx = ModelContext(manager, ModelType.CAPTION)
        # Simulate __exit__ without __enter__ (abnormal usage)
        ctx.__exit__(None, None, None)
        assert model._refcount == 0  # Should not go negative

    @patch("mcp_vector_store.gpu_scheduler.psutil")
    def test_unload_skips_model_with_refcount(self, mock_psutil):
        mock_psutil.virtual_memory.return_value = MagicMock(
            available=4 * 1024 * 1024 * 1024, percent=50.0
        )
        manager, model = self._make_manager()
        # Simulate model loaded with active user
        model.is_loaded = True
        model._refcount = 1

        manager._unload_model(ModelType.CAPTION)
        # Should NOT unload because refcount > 0
        assert model.is_loaded is True

    @patch("mcp_vector_store.gpu_scheduler.psutil")
    def test_unload_force_ignores_refcount(self, mock_psutil):
        mock_psutil.virtual_memory.return_value = MagicMock(
            available=4 * 1024 * 1024 * 1024, percent=50.0
        )
        manager, model = self._make_manager()
        model.is_loaded = True
        model._refcount = 1

        manager._unload_model(ModelType.CAPTION, force=True)
        assert model.is_loaded is False

    @patch("mcp_vector_store.gpu_scheduler.psutil")
    def test_circuit_breaker_blocks_gpu_load(self, mock_psutil):
        mock_psutil.virtual_memory.return_value = MagicMock(
            available=4 * 1024 * 1024 * 1024, percent=50.0
        )
        manager, model = self._make_manager()

        # Force circuit breaker open
        for _ in range(3):
            manager._circuit_breaker.record_failure(MemoryError("CUDA out of memory"))

        with pytest.raises(RuntimeError, match="circuit breaker is OPEN"):
            manager.ensure_loaded(ModelType.CAPTION)

    @patch("mcp_vector_store.gpu_scheduler.psutil")
    def test_memory_preflight_blocks_load(self, mock_psutil):
        mock_psutil.virtual_memory.return_value = MagicMock(
            available=100 * 1024 * 1024, percent=95.0  # Only 100MB available
        )
        manager, model = self._make_manager()

        with pytest.raises(MemoryError, match="Insufficient memory"):
            manager.ensure_loaded(ModelType.CAPTION)

    @patch("mcp_vector_store.gpu_scheduler.psutil")
    def test_memory_preflight_records_circuit_breaker_failure(self, mock_psutil):
        """Edge case: memory preflight failure should count toward circuit breaker."""
        mock_psutil.virtual_memory.return_value = MagicMock(
            available=100 * 1024 * 1024, percent=95.0
        )
        manager, model = self._make_manager()

        # 3 memory failures should open circuit breaker
        for _ in range(3):
            try:
                manager.ensure_loaded(ModelType.CAPTION)
            except MemoryError:
                pass

        assert manager._circuit_breaker.state == CircuitState.OPEN

    @patch("mcp_vector_store.gpu_scheduler.psutil")
    def test_cpu_model_skips_gpu_checks(self, mock_psutil):
        """Edge case: CPU-only models should skip circuit breaker and memory checks."""
        mock_psutil.virtual_memory.return_value = MagicMock(
            available=100 * 1024 * 1024, percent=95.0  # Low memory
        )
        manager, model = self._make_manager(on_gpu=False)

        # Circuit breaker open
        for _ in range(3):
            manager._circuit_breaker.record_failure(MemoryError("OOM"))

        # CPU model should still load despite open circuit breaker and low memory
        manager.ensure_loaded(ModelType.CAPTION)
        assert model.is_loaded is True

    @patch("mcp_vector_store.gpu_scheduler.psutil")
    def test_eviction_respects_refcount(self, mock_psutil):
        """Edge case: evicting a model with refcount>0 waits, then succeeds when released."""
        mock_psutil.virtual_memory.return_value = MagicMock(
            available=4 * 1024 * 1024 * 1024, percent=50.0
        )
        manager, embedding, caption = self._make_manager_two_models()
        embedding._refcount = 1  # Embedding is in use

        # Release refcount from another thread after a short delay
        def release_refcount():
            time.sleep(0.3)
            embedding._refcount = 0

        t = threading.Thread(target=release_refcount)
        t.start()

        # This should wait for embedding refcount to drop, then evict it
        manager.ensure_loaded(ModelType.CAPTION)
        t.join()

        assert caption.is_loaded is True
        assert embedding.is_loaded is False

    @patch("mcp_vector_store.gpu_scheduler.psutil")
    def test_load_already_loaded_is_noop(self, mock_psutil):
        """Edge case: loading an already-loaded model is a no-op."""
        mock_psutil.virtual_memory.return_value = MagicMock(
            available=4 * 1024 * 1024 * 1024, percent=50.0
        )
        manager, model = self._make_manager()
        model.is_loaded = True

        load_fn = MagicMock()
        model._load_fn = load_fn

        manager.ensure_loaded(ModelType.CAPTION)
        load_fn.assert_not_called()

    @patch("mcp_vector_store.gpu_scheduler.psutil")
    def test_load_failure_records_circuit_breaker(self, mock_psutil):
        """Edge case: load function raising OOM records with circuit breaker."""
        mock_psutil.virtual_memory.return_value = MagicMock(
            available=4 * 1024 * 1024 * 1024, percent=50.0
        )
        manager, model = self._make_manager()
        model._load_fn = MagicMock(side_effect=MemoryError("CUDA out of memory"))

        with pytest.raises(MemoryError):
            manager.ensure_loaded(ModelType.CAPTION)

        assert manager._circuit_breaker._consecutive_failures == 1

    @patch("mcp_vector_store.gpu_scheduler.psutil")
    def test_load_success_records_circuit_breaker(self, mock_psutil):
        """Edge case: successful GPU load records success with circuit breaker."""
        mock_psutil.virtual_memory.return_value = MagicMock(
            available=4 * 1024 * 1024 * 1024, percent=50.0
        )
        manager, model = self._make_manager()

        # Put 2 failures on circuit breaker (below threshold of 3)
        manager._circuit_breaker.record_failure(MemoryError("OOM"))
        manager._circuit_breaker.record_failure(MemoryError("OOM"))
        assert manager._circuit_breaker._consecutive_failures == 2

        manager.ensure_loaded(ModelType.CAPTION)

        # Successful load should reset failure count
        assert manager._circuit_breaker._consecutive_failures == 0

    def test_get_scheduler_status(self):
        manager = ModelManager(verbose=False)
        status = manager.get_scheduler_status()
        assert "circuit_breaker" in status
        assert "memory" in status
        assert "refcounts" in status
        assert status["circuit_breaker"]["state"] == "closed"

    def test_unload_unregistered_model_is_noop(self):
        """Edge case: unloading unregistered model doesn't crash."""
        manager = ModelManager(verbose=False)
        manager._unload_model(ModelType.CAPTION)  # Should not raise

    def test_load_unregistered_model_raises(self):
        """Edge case: loading unregistered model raises ValueError."""
        manager = ModelManager(verbose=False)
        with pytest.raises(ValueError, match="not registered"):
            manager._load_model(ModelType.CAPTION)

    @patch("mcp_vector_store.gpu_scheduler.psutil")
    def test_transient_model_auto_unloads_on_context_exit(self, mock_psutil):
        """Verify transient models unload when refcount drops to 0."""
        mock_psutil.virtual_memory.return_value = MagicMock(
            available=4 * 1024 * 1024 * 1024, percent=50.0
        )
        manager, model = self._make_manager()

        unload_fn = MagicMock()
        model._unload_fn = unload_fn

        with manager.require(ModelType.CAPTION):
            assert model.is_loaded is True
            unload_fn.assert_not_called()

        # After context exit, transient model should auto-unload
        unload_fn.assert_called_once()

    @patch("mcp_vector_store.gpu_scheduler.psutil")
    def test_non_transient_model_stays_loaded_on_context_exit(self, mock_psutil):
        """Verify non-transient models stay loaded after context exit."""
        mock_psutil.virtual_memory.return_value = MagicMock(
            available=4 * 1024 * 1024 * 1024, percent=50.0
        )
        manager = ModelManager(verbose=False)
        model = ManagedModel(
            model_type=ModelType.EMBEDDING,
            instance=MagicMock(),
            is_loaded=False,
            on_gpu=True,
            _load_fn=lambda: None,
            _unload_fn=MagicMock(),
            _get_instance_fn=lambda: None,
        )
        manager._models[ModelType.EMBEDDING] = model

        with manager.require(ModelType.EMBEDDING):
            pass

        # EMBEDDING is not transient, should stay loaded
        assert model.is_loaded is True
        model._unload_fn.assert_not_called()


# --- _load_model_no_evict Tests ---


class TestLoadModelNoEvict:
    """Tests for _load_model_no_evict safety checks."""

    @patch("mcp_vector_store.gpu_scheduler.psutil")
    def test_no_evict_checks_circuit_breaker(self, mock_psutil):
        """_load_model_no_evict should check circuit breaker for GPU models."""
        mock_psutil.virtual_memory.return_value = MagicMock(
            available=4 * 1024 * 1024 * 1024, percent=50.0
        )
        manager = ModelManager(verbose=False)
        model = ManagedModel(
            model_type=ModelType.EMBEDDING,
            instance=MagicMock(),
            is_loaded=False,
            on_gpu=True,
            _load_fn=lambda: None,
            _unload_fn=lambda: None,
            _get_instance_fn=lambda: None,
        )
        manager._models[ModelType.EMBEDDING] = model

        # Open circuit breaker
        for _ in range(3):
            manager._circuit_breaker.record_failure(MemoryError("OOM"))

        with pytest.raises(RuntimeError, match="circuit breaker is OPEN"):
            manager._load_model_no_evict(ModelType.EMBEDDING)

    @patch("mcp_vector_store.gpu_scheduler.psutil")
    def test_no_evict_checks_memory(self, mock_psutil):
        """_load_model_no_evict should check available memory for GPU models."""
        mock_psutil.virtual_memory.return_value = MagicMock(
            available=50 * 1024 * 1024, percent=98.0  # Very low memory
        )
        manager = ModelManager(verbose=False)
        model = ManagedModel(
            model_type=ModelType.EMBEDDING,
            instance=MagicMock(),
            is_loaded=False,
            on_gpu=True,
            _load_fn=lambda: None,
            _unload_fn=lambda: None,
            _get_instance_fn=lambda: None,
        )
        manager._models[ModelType.EMBEDDING] = model

        with pytest.raises(MemoryError, match="Insufficient memory"):
            manager._load_model_no_evict(ModelType.EMBEDDING)

    @patch("mcp_vector_store.gpu_scheduler.psutil")
    def test_no_evict_cpu_model_skips_checks(self, mock_psutil):
        """_load_model_no_evict with CPU model skips GPU safety checks."""
        mock_psutil.virtual_memory.return_value = MagicMock(
            available=50 * 1024 * 1024, percent=98.0
        )
        manager = ModelManager(verbose=False)
        model = ManagedModel(
            model_type=ModelType.EMBEDDING,
            instance=MagicMock(),
            is_loaded=False,
            on_gpu=False,  # CPU model
            _load_fn=lambda: None,
            _unload_fn=lambda: None,
            _get_instance_fn=lambda: None,
        )
        manager._models[ModelType.EMBEDDING] = model

        # Open circuit breaker
        for _ in range(3):
            manager._circuit_breaker.record_failure(MemoryError("OOM"))

        # CPU model should load despite open circuit breaker and low memory
        manager._load_model_no_evict(ModelType.EMBEDDING)
        assert model.is_loaded is True

    @patch("mcp_vector_store.gpu_scheduler.psutil")
    def test_no_evict_already_loaded_is_noop(self, mock_psutil):
        """_load_model_no_evict with already loaded model is a no-op."""
        manager = ModelManager(verbose=False)
        load_fn = MagicMock()
        model = ManagedModel(
            model_type=ModelType.EMBEDDING,
            instance=MagicMock(),
            is_loaded=True,
            on_gpu=True,
            _load_fn=load_fn,
            _unload_fn=lambda: None,
            _get_instance_fn=lambda: None,
        )
        manager._models[ModelType.EMBEDDING] = model
        manager._load_model_no_evict(ModelType.EMBEDDING)
        load_fn.assert_not_called()

    def test_no_evict_unregistered_model_is_noop(self):
        """_load_model_no_evict with unregistered model doesn't crash."""
        manager = ModelManager(verbose=False)
        manager._load_model_no_evict(ModelType.CAPTION)  # Should not raise

    @patch("mcp_vector_store.gpu_scheduler.psutil")
    def test_no_evict_records_success_on_gpu_load(self, mock_psutil):
        """_load_model_no_evict records success with circuit breaker on GPU load."""
        mock_psutil.virtual_memory.return_value = MagicMock(
            available=4 * 1024 * 1024 * 1024, percent=50.0
        )
        manager = ModelManager(verbose=False)
        model = ManagedModel(
            model_type=ModelType.EMBEDDING,
            instance=MagicMock(),
            is_loaded=False,
            on_gpu=True,
            _load_fn=lambda: None,
            _unload_fn=lambda: None,
            _get_instance_fn=lambda: None,
        )
        manager._models[ModelType.EMBEDDING] = model

        # Add 2 failures
        manager._circuit_breaker.record_failure(MemoryError("OOM"))
        manager._circuit_breaker.record_failure(MemoryError("OOM"))

        manager._load_model_no_evict(ModelType.EMBEDDING)

        # Success should have reset failures
        assert manager._circuit_breaker._consecutive_failures == 0

    @patch("mcp_vector_store.gpu_scheduler.psutil")
    def test_no_evict_records_failure_on_gpu_load_error(self, mock_psutil):
        """_load_model_no_evict records failure with circuit breaker on GPU load error."""
        mock_psutil.virtual_memory.return_value = MagicMock(
            available=4 * 1024 * 1024 * 1024, percent=50.0
        )
        manager = ModelManager(verbose=False)
        model = ManagedModel(
            model_type=ModelType.EMBEDDING,
            instance=MagicMock(),
            is_loaded=False,
            on_gpu=True,
            _load_fn=MagicMock(side_effect=MemoryError("CUDA OOM")),
            _unload_fn=lambda: None,
            _get_instance_fn=lambda: None,
        )
        manager._models[ModelType.EMBEDDING] = model

        with pytest.raises(MemoryError):
            manager._load_model_no_evict(ModelType.EMBEDDING)

        assert manager._circuit_breaker._consecutive_failures == 1


# --- Thread Safety Tests ---


class TestThreadSafety:
    """Thread safety tests for circuit breaker and ModelManager."""

    def test_concurrent_failures(self):
        cb = GPUCircuitBreaker(failure_threshold=10)
        errors = []

        def record_failures():
            try:
                for _ in range(5):
                    cb.record_failure(MemoryError("OOM"))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=record_failures) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        # 4 threads x 5 failures = 20, but only 10 needed to open
        assert cb.state == CircuitState.OPEN

    @patch("mcp_vector_store.gpu_scheduler.psutil")
    def test_concurrent_require(self, mock_psutil):
        """Edge case: multiple threads using require() simultaneously."""
        mock_psutil.virtual_memory.return_value = MagicMock(
            available=4 * 1024 * 1024 * 1024, percent=50.0
        )
        manager = ModelManager(verbose=False)

        # Use EMBEDDING (non-transient) to avoid auto-unload complications
        model = ManagedModel(
            model_type=ModelType.EMBEDDING,
            instance=MagicMock(),
            is_loaded=False,
            on_gpu=True,
            _load_fn=lambda: None,
            _unload_fn=lambda: None,
            _get_instance_fn=lambda: None,
        )
        manager._models[ModelType.EMBEDDING] = model
        errors = []
        max_refcount = [0]

        def use_model():
            try:
                with manager.require(ModelType.EMBEDDING):
                    # Record max refcount seen
                    with manager._lock:
                        if model._refcount > max_refcount[0]:
                            max_refcount[0] = model._refcount
                    time.sleep(0.05)  # Hold the model briefly
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=use_model) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert model._refcount == 0  # All references released
        # At least 2 threads should have been concurrent
        assert max_refcount[0] >= 1

    @patch("mcp_vector_store.gpu_scheduler.psutil")
    def test_concurrent_require_transient(self, mock_psutil):
        """Edge case: concurrent require() on transient model. Only unloads when last exits."""
        mock_psutil.virtual_memory.return_value = MagicMock(
            available=4 * 1024 * 1024 * 1024, percent=50.0
        )
        manager = ModelManager(verbose=False)
        unload_fn = MagicMock()
        model = ManagedModel(
            model_type=ModelType.CAPTION,
            instance=MagicMock(),
            is_loaded=False,
            on_gpu=True,
            _load_fn=lambda: None,
            _unload_fn=unload_fn,
            _get_instance_fn=lambda: None,
        )
        manager._models[ModelType.CAPTION] = model

        barrier = threading.Barrier(2)  # Synchronize entry

        def use_model():
            with manager.require(ModelType.CAPTION):
                barrier.wait(timeout=5)  # Both threads inside context
                time.sleep(0.1)

        t1 = threading.Thread(target=use_model)
        t2 = threading.Thread(target=use_model)
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        # Both exited, refcount should be 0
        assert model._refcount == 0
        # Unload should only happen after LAST context exits
        assert unload_fn.called


# --- unload_all Tests ---


class TestUnloadAll:
    """Tests for unload_all behavior."""

    @patch("mcp_vector_store.gpu_scheduler.psutil")
    def test_unload_all_skips_embedding(self, mock_psutil):
        """unload_all should skip embedding model (it's kept resident)."""
        mock_psutil.virtual_memory.return_value = MagicMock(
            available=4 * 1024 * 1024 * 1024, percent=50.0
        )
        manager = ModelManager(verbose=False)
        for mt in [ModelType.EMBEDDING, ModelType.RERANKER, ModelType.CAPTION]:
            model = ManagedModel(
                model_type=mt,
                instance=MagicMock(),
                is_loaded=True,
                on_gpu=True,
                _load_fn=lambda: None,
                _unload_fn=lambda: None,
                _get_instance_fn=lambda: None,
            )
            manager._models[mt] = model

        manager.unload_all()

        assert manager._models[ModelType.EMBEDDING].is_loaded is True
        assert manager._models[ModelType.RERANKER].is_loaded is False
        assert manager._models[ModelType.CAPTION].is_loaded is False

    @patch("mcp_vector_store.gpu_scheduler.psutil")
    def test_unload_all_respects_refcount(self, mock_psutil):
        """unload_all should skip models with active refcount."""
        mock_psutil.virtual_memory.return_value = MagicMock(
            available=4 * 1024 * 1024 * 1024, percent=50.0
        )
        manager = ModelManager(verbose=False)
        model = ManagedModel(
            model_type=ModelType.RERANKER,
            instance=MagicMock(),
            is_loaded=True,
            on_gpu=True,
            _refcount=1,  # Active user
            _load_fn=lambda: None,
            _unload_fn=lambda: None,
            _get_instance_fn=lambda: None,
        )
        manager._models[ModelType.RERANKER] = model

        manager.unload_all()

        # Should NOT unload because refcount > 0
        assert model.is_loaded is True


# --- Backpressure Tests ---


class TestBackpressure:
    """Tests for async worker backpressure with memory monitor."""

    @patch("mcp_vector_store.gpu_scheduler.psutil")
    def test_async_extractor_backpressure(self, mock_psutil):
        """AsyncExtractor should pause when memory is above high watermark."""
        from mcp_vector_store.async_extractor import AsyncExtractor

        # Create monitor that's above watermark
        mock_psutil.virtual_memory.return_value = MagicMock(percent=90.0)
        monitor = MemoryMonitor(high_watermark_pct=85.0)

        assert monitor.is_above_high_watermark() is True

        # Verify the AsyncExtractor accepts the monitor
        extractor = AsyncExtractor(
            vector_store=MagicMock(),
            passage_extractor=None,
            memory_monitor=monitor,
        )
        assert extractor._memory_monitor is monitor

    @patch("mcp_vector_store.gpu_scheduler.psutil")
    def test_memory_monitor_hysteresis(self, mock_psutil):
        """Verify hysteresis: high watermark triggers pause, low watermark resumes."""
        monitor = MemoryMonitor(high_watermark_pct=85.0, low_watermark_pct=70.0)

        # Memory at 80% — between watermarks
        mock_psutil.virtual_memory.return_value = MagicMock(percent=80.0)
        # Not above high watermark -> no pause
        assert monitor.is_above_high_watermark() is False
        # Not below low watermark -> don't resume yet
        assert monitor.is_below_low_watermark() is False
