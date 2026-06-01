"""GPU scheduling primitives for memory-constrained devices.

Provides pre-flight memory checks, circuit breaking for OOM prevention,
and backpressure signaling for async worker queues on Jetson Orin Nano
(7.4GB shared CPU/GPU memory).

Components:
    MODEL_SIZE_ESTIMATES_MB: Expected GPU memory per model type
    MemoryMonitor: System memory checks and watermark-based backpressure
    GPUCircuitBreaker: Prevents repeated OOM by tracking GPU load failures
"""

import os
import time
import threading
from enum import Enum
from typing import Dict, Optional

import psutil


# Estimated GPU memory usage per model type (MB)
# Used for pre-flight checks before loading a model onto GPU
MODEL_SIZE_ESTIMATES_MB: Dict[str, int] = {
    "embedding": 90,
    "reranker": 250,
    "transcription": 1000,
    "caption": 1500,
    "lprag_vocab": 50,
    "ocr": 900,
}


class MemoryMonitor:
    """Monitor system memory for Jetson unified memory architecture.

    On Jetson, CPU and GPU share the same physical memory pool, so
    psutil.virtual_memory() accurately reflects available memory for
    both CPU and GPU allocations.
    """

    def __init__(
        self,
        high_watermark_pct: float = 85.0,
        low_watermark_pct: float = 70.0,
    ):
        self.high_watermark_pct = high_watermark_pct
        self.low_watermark_pct = low_watermark_pct

    def get_available_mb(self) -> float:
        """Get available system memory in MB (correct for Jetson unified memory)."""
        return psutil.virtual_memory().available / (1024 * 1024)

    def get_used_pct(self) -> float:
        """Get system memory usage percentage."""
        return psutil.virtual_memory().percent

    def has_headroom_for(self, model_size_mb: int, safety_margin_mb: int = 200) -> bool:
        """Pre-flight check: is there enough memory to load a model?

        Args:
            model_size_mb: Estimated model size in MB
            safety_margin_mb: Extra margin to keep free (default 200MB)

        Returns:
            True if there's enough memory for the model + safety margin
        """
        available = self.get_available_mb()
        return available >= (model_size_mb + safety_margin_mb)

    def is_above_high_watermark(self) -> bool:
        """Check if memory usage is above the high watermark (pause threshold)."""
        return self.get_used_pct() >= self.high_watermark_pct

    def is_below_low_watermark(self) -> bool:
        """Check if memory usage is below the low watermark (resume threshold)."""
        return self.get_used_pct() <= self.low_watermark_pct

    def wait_for_memory(self, timeout: float = 60.0) -> bool:
        """Block until memory drops below low watermark or timeout.

        Args:
            timeout: Maximum seconds to wait

        Returns:
            True if memory dropped below low watermark, False if timeout
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.is_below_low_watermark():
                return True
            time.sleep(1.0)
        return False

    def get_status(self) -> dict:
        """Get memory status for debug endpoint."""
        return {
            "available_mb": round(self.get_available_mb(), 1),
            "used_pct": round(self.get_used_pct(), 1),
            "high_watermark_pct": self.high_watermark_pct,
            "low_watermark_pct": self.low_watermark_pct,
            "above_high_watermark": self.is_above_high_watermark(),
        }


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"       # Normal operation, GPU loads allowed
    OPEN = "open"           # GPU loads rejected, falling back to CPU
    HALF_OPEN = "half_open"  # Testing one GPU load to see if recovered


# Error patterns that indicate OOM or GPU memory exhaustion
OOM_ERROR_PATTERNS = [
    "out of memory",
    "oom",
    "nvmapmemalloc",
    "cuda error",
    "cuda out of memory",
    "cudnn error",
    "cudaruntimeerror",
    "memory allocation",
    "alloc",
    "error 12",  # NvMapMemAllocInternalTagged error 12
]


def _is_oom_error(error: Exception) -> bool:
    """Check if an exception is an OOM-like GPU memory error."""
    error_str = str(error).lower()
    return any(pattern in error_str for pattern in OOM_ERROR_PATTERNS)


class GPUCircuitBreaker:
    """Circuit breaker for GPU model loading to prevent OOM crash loops.

    States:
        CLOSED: Normal operation. GPU loads are allowed.
        OPEN: GPU loads are rejected (callers should fall back to CPU).
              Transitions to HALF_OPEN after cooldown period.
        HALF_OPEN: One test GPU load is allowed. Success closes the
                   circuit, failure reopens it.

    Only OOM-like errors count toward the failure threshold.
    Non-memory errors (e.g., model not found) are ignored.
    """

    def __init__(
        self,
        failure_threshold: int = 3,
        cooldown_seconds: float = 30.0,
    ):
        self._failure_threshold = failure_threshold
        self._cooldown_seconds = cooldown_seconds
        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._last_failure_time: Optional[float] = None
        self._last_error: Optional[str] = None
        self._lock = threading.Lock()

    @property
    def state(self) -> CircuitState:
        with self._lock:
            return self._get_effective_state()

    def _get_effective_state(self) -> CircuitState:
        """Get effective state, considering cooldown expiry (must hold lock)."""
        if self._state == CircuitState.OPEN and self._last_failure_time is not None:
            elapsed = time.monotonic() - self._last_failure_time
            if elapsed >= self._cooldown_seconds:
                self._state = CircuitState.HALF_OPEN
        return self._state

    def allows_gpu_load(self) -> bool:
        """Check if GPU loads are currently allowed.

        Returns:
            True if CLOSED or HALF_OPEN (test load), False if OPEN
        """
        with self._lock:
            state = self._get_effective_state()
            return state != CircuitState.OPEN

    def record_success(self) -> None:
        """Record a successful GPU load. Resets failure count and closes circuit."""
        with self._lock:
            self._consecutive_failures = 0
            self._state = CircuitState.CLOSED
            self._last_error = None

    def record_failure(self, error: Exception) -> None:
        """Record a GPU load failure. Only OOM-like errors count.

        Args:
            error: The exception from the failed GPU load
        """
        if not _is_oom_error(error):
            return

        with self._lock:
            self._consecutive_failures += 1
            self._last_failure_time = time.monotonic()
            self._last_error = str(error)[:200]

            if self._state == CircuitState.HALF_OPEN:
                # Test load failed, reopen
                self._state = CircuitState.OPEN
            elif self._consecutive_failures >= self._failure_threshold:
                self._state = CircuitState.OPEN
                print(f"GPUCircuitBreaker: OPENED after {self._consecutive_failures} "
                      f"consecutive OOM failures (cooldown: {self._cooldown_seconds}s)")

    def get_status(self) -> dict:
        """Get circuit breaker status for debug endpoint."""
        with self._lock:
            state = self._get_effective_state()
            result = {
                "state": state.value,
                "consecutive_failures": self._consecutive_failures,
                "failure_threshold": self._failure_threshold,
                "cooldown_seconds": self._cooldown_seconds,
            }
            if self._last_error:
                result["last_error"] = self._last_error
            if self._last_failure_time is not None and state == CircuitState.OPEN:
                remaining = self._cooldown_seconds - (time.monotonic() - self._last_failure_time)
                result["cooldown_remaining_seconds"] = round(max(0, remaining), 1)
            return result


def create_memory_monitor() -> MemoryMonitor:
    """Create a MemoryMonitor with configuration from environment variables."""
    high = float(os.environ.get("GPU_MEMORY_HIGH_WATERMARK", "85"))
    low = float(os.environ.get("GPU_MEMORY_LOW_WATERMARK", "70"))
    return MemoryMonitor(high_watermark_pct=high, low_watermark_pct=low)


def create_circuit_breaker() -> GPUCircuitBreaker:
    """Create a GPUCircuitBreaker with configuration from environment variables."""
    threshold = int(os.environ.get("GPU_CIRCUIT_BREAKER_THRESHOLD", "3"))
    cooldown = float(os.environ.get("GPU_CIRCUIT_BREAKER_COOLDOWN", "30"))
    return GPUCircuitBreaker(failure_threshold=threshold, cooldown_seconds=cooldown)
