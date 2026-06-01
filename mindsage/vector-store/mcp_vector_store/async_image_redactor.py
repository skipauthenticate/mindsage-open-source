"""Async background image PII redaction.

Allows fast image upload while PII detection and redaction runs in the background.
Uses EasyOCR/Tesseract OCR + Presidio for PII detection.

Features:
- Non-blocking image uploads
- Retry logic with exponential backoff for transient failures
- Updates document metadata when redaction completes
- Failed task tracking for debugging
"""

import threading
import time
from queue import Queue, Empty
from typing import Optional, TYPE_CHECKING, Dict, Any, List
from dataclasses import dataclass, field
from collections import deque
from pathlib import Path

if TYPE_CHECKING:
    from .txtai_adapter import TxtaiAdapter as VectorStore
    from .image_pii_redactor import ImagePIIRedactor
    from .gpu_scheduler import MemoryMonitor


# Retry configuration
MAX_RETRIES = 2
RETRY_DELAYS = [1.0, 3.0]  # Exponential backoff in seconds


def is_retryable_error(error: Exception) -> bool:
    """Check if an error is likely transient and worth retrying."""
    error_str = str(error).lower()
    retryable_patterns = [
        "database is locked",
        "timeout",
        "timed out",
        "busy",
        "connection",
        "memory",
    ]
    return any(pattern in error_str for pattern in retryable_patterns)


@dataclass
class ImageRedactionTask:
    """A background image redaction task."""
    doc_id: int
    image_id: str
    original_image_path: str
    redacted_image_path: str  # Where to save the redacted version
    session_id: Optional[str] = None
    attempt: int = 0
    last_error: Optional[str] = None


@dataclass
class FailedRedactionTask:
    """A redaction task that exhausted all retries."""
    doc_id: int
    image_id: str
    attempts: int
    last_error: str
    failed_at: float = field(default_factory=time.time)


class AsyncImageRedactor:
    """Background image PII redactor.

    Images are stored immediately, then PII redaction runs in the background
    without blocking the upload API. Document metadata is updated when
    redaction completes.

    Usage:
        redactor = AsyncImageRedactor(
            vector_store=vs,
            pii_redactor=pii_redactor,
        )
        redactor.start()

        # Queue a redaction task
        redactor.queue_redaction(ImageRedactionTask(
            doc_id=123,
            image_id="abc123",
            original_image_path="/app/data/uploads/images/img_abc123.jpg",
            redacted_image_path="/app/data/redacted/images/img_abc123_redacted.jpg",
        ))
    """

    def __init__(
        self,
        vector_store: "VectorStore",
        pii_redactor: Optional["ImagePIIRedactor"],
        verbose: bool = False,
        max_failed_history: int = 50,
        memory_monitor: Optional["MemoryMonitor"] = None,
    ):
        """Initialize the async image redactor.

        Args:
            vector_store: Vector store for updating document metadata.
            pii_redactor: Image PII redactor for OCR + detection.
            verbose: Whether to print debug information.
            max_failed_history: Maximum number of failed tasks to keep.
            memory_monitor: Optional MemoryMonitor for backpressure.
        """
        self.vector_store = vector_store
        self.pii_redactor = pii_redactor
        self.verbose = verbose
        self.max_failed_history = max_failed_history
        self._memory_monitor = memory_monitor

        self._queue: Queue[ImageRedactionTask] = Queue()
        self._running = False
        self._worker_thread: Optional[threading.Thread] = None
        self._pending_count = 0
        self._completed_count = 0
        self._retry_count = 0
        self._failed_tasks: deque[FailedRedactionTask] = deque(maxlen=max_failed_history)
        self._lock = threading.Lock()

        # Current processing state
        self._current_image_id: Optional[str] = None
        self._current_doc_id: Optional[int] = None

    def start(self):
        """Start the background redaction worker."""
        if self._running:
            return

        self._running = True
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker_thread.start()
        if self.verbose:
            print("AsyncImageRedactor: Background worker started")

    def stop(self):
        """Stop the background redaction worker."""
        self._running = False
        if self._worker_thread:
            self._worker_thread.join(timeout=5)
        if self.verbose:
            print("AsyncImageRedactor: Background worker stopped")

    def queue_redaction(self, task: ImageRedactionTask):
        """Queue an image for background PII redaction."""
        with self._lock:
            self._pending_count += 1
        self._queue.put(task)
        if self.verbose:
            print(f"AsyncImageRedactor: Queued image {task.image_id} for redaction (pending: {self._pending_count})")

    def get_pending_count(self) -> int:
        """Get the number of pending redaction tasks."""
        with self._lock:
            return self._pending_count

    def get_status(self) -> Dict[str, Any]:
        """Get detailed redaction queue status."""
        with self._lock:
            status = {
                "pending": self._pending_count,
                "completed": self._completed_count,
                "running": self._running,
                "total_retries": self._retry_count,
                "failed_count": len(self._failed_tasks),
            }
            if self._current_image_id is not None:
                status["current"] = {
                    "doc_id": self._current_doc_id,
                    "image_id": self._current_image_id,
                }
            return status

    def get_failed_tasks(self) -> List[Dict[str, Any]]:
        """Get list of failed tasks for debugging."""
        with self._lock:
            return [
                {
                    "doc_id": t.doc_id,
                    "image_id": t.image_id,
                    "attempts": t.attempts,
                    "last_error": t.last_error,
                    "failed_at": t.failed_at,
                }
                for t in self._failed_tasks
            ]

    def _worker_loop(self):
        """Background worker that processes redaction tasks."""
        while self._running:
            # Memory backpressure: pause if system memory is critically high
            if self._memory_monitor and self._memory_monitor.is_above_high_watermark():
                if self.verbose:
                    print(f"AsyncImageRedactor: Memory above high watermark "
                          f"({self._memory_monitor.get_used_pct():.0f}%), "
                          f"waiting for memory...")
                self._memory_monitor.wait_for_memory(timeout=60)
                # Re-check after waiting: if still above watermark, skip this cycle
                if self._memory_monitor.is_above_high_watermark():
                    if self.verbose:
                        print(f"AsyncImageRedactor: Still above watermark after wait, "
                              f"deferring processing")
                    continue

            try:
                task = self._queue.get(timeout=1.0)
            except Empty:
                continue

            try:
                self._process_task(task)
                with self._lock:
                    self._pending_count -= 1
                    self._completed_count += 1
                self._queue.task_done()
            except Exception as e:
                error_msg = str(e)
                task.last_error = error_msg

                # Check if we should retry
                if task.attempt < MAX_RETRIES and is_retryable_error(e):
                    task.attempt += 1
                    delay = RETRY_DELAYS[min(task.attempt - 1, len(RETRY_DELAYS) - 1)]

                    with self._lock:
                        self._retry_count += 1

                    print(f"AsyncImageRedactor: Retrying image {task.image_id} "
                          f"(attempt {task.attempt}/{MAX_RETRIES}) after {delay}s - {error_msg}")

                    time.sleep(delay)
                    self._queue.put(task)
                    self._queue.task_done()
                else:
                    # Exhausted retries or non-retryable error
                    print(f"AsyncImageRedactor: Failed image {task.image_id} after {task.attempt + 1} attempts: {error_msg}")

                    with self._lock:
                        self._failed_tasks.append(FailedRedactionTask(
                            doc_id=task.doc_id,
                            image_id=task.image_id,
                            attempts=task.attempt + 1,
                            last_error=error_msg,
                        ))
                        self._pending_count -= 1
                    self._queue.task_done()

    def _process_task(self, task: ImageRedactionTask):
        """Process a single redaction task.

        Steps:
        1. Run OCR + PII detection on the original image
        2. If PII found, generate redacted image
        3. Update document metadata with redaction results
        """
        if not self.pii_redactor:
            if self.verbose:
                print(f"AsyncImageRedactor: No PII redactor available, skipping {task.image_id}")
            return

        with self._lock:
            self._current_image_id = task.image_id
            self._current_doc_id = task.doc_id

        try:
            if self.verbose:
                attempt_str = f" (attempt {task.attempt + 1})" if task.attempt > 0 else ""
                print(f"AsyncImageRedactor: Processing image {task.image_id}{attempt_str}...")

            # Check if original image still exists
            if not Path(task.original_image_path).exists():
                print(f"AsyncImageRedactor: Original image not found: {task.original_image_path}")
                return

            # Detect PII regions
            regions, ocr_result = self.pii_redactor.detect_pii_regions(task.original_image_path)

            has_pii = bool(regions)
            pii_types_found = list(set(r.pii_type for r in regions)) if regions else []
            pii_regions_count = len(regions) if regions else 0

            if has_pii:
                # Generate redacted image
                redaction_result = self.pii_redactor.redact_image(
                    task.original_image_path,
                    output_path=task.redacted_image_path,
                    session_id=task.session_id,
                )
                if self.verbose:
                    print(f"  - Redacted {pii_regions_count} PII regions: {pii_types_found}")
            else:
                if self.verbose:
                    print("  - No PII detected")

            # Update document metadata
            metadata_updates = {
                "has_pii": has_pii,
                "pii_types_found": pii_types_found,
                "pii_regions_count": pii_regions_count,
                "redaction_complete": True,
                "redaction_pending": False,  # Clear the pending flag
            }

            if has_pii:
                metadata_updates["redacted_image_path"] = task.redacted_image_path

            self.vector_store.update_document_metadata(task.doc_id, metadata_updates)

            if self.verbose:
                print(f"AsyncImageRedactor: Image {task.image_id} redaction complete")

        finally:
            with self._lock:
                self._current_image_id = None
                self._current_doc_id = None
