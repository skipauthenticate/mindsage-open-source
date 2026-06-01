"""Async background audio transcription and PII redaction.

Allows fast audio upload while transcription and PII redaction runs in the background.
Uses whisper-timestamped for transcription + Presidio for PII detection + pydub for
audio file redaction.

Features:
- Non-blocking audio uploads
- Background GPU transcription (Whisper)
- Parallel CPU operations (PII detection, audio file redaction)
- Retry logic with exponential backoff for transient failures
- Updates document metadata when processing completes
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
    from .audio_pii_redactor import AudioPIIRedactor
    from .gpu_scheduler import MemoryMonitor


# Retry configuration
MAX_RETRIES = 2
RETRY_DELAYS = [2.0, 5.0]  # Longer delays for GPU operations


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
        "cuda",  # GPU memory errors
        "out of memory",
        "oom",
    ]
    return any(pattern in error_str for pattern in retryable_patterns)


@dataclass
class AudioRedactionTask:
    """A background audio transcription and redaction task."""
    doc_id: int
    audio_id: str
    audio_path: str
    mute_audio: bool = False  # Whether to create redacted audio file
    mute_style: str = "silence"  # "silence", "beep", or "noise"
    session_id: Optional[str] = None
    attempt: int = 0
    last_error: Optional[str] = None


@dataclass
class FailedAudioTask:
    """An audio task that exhausted all retries."""
    doc_id: int
    audio_id: str
    audio_path: str
    attempts: int
    last_error: str
    failed_at: float = field(default_factory=time.time)


class AsyncAudioRedactor:
    """Background audio transcription and PII redactor.

    Audio files are stored immediately, then transcription and PII redaction
    runs in the background without blocking the upload API. Document metadata
    is updated when processing completes.

    Pipeline:
        1. Transcribe with word-level timestamps (GPU - Whisper)
        2. Detect PII regions (CPU - Presidio)
        3. Redact transcript (CPU - string ops)
        4. Optionally redact audio file (CPU - pydub)
        5. Update document metadata

    Usage:
        redactor = AsyncAudioRedactor(
            vector_store=vs,
            audio_pii_redactor=pii_redactor,
        )
        redactor.start()

        # Queue an audio task
        redactor.queue_task(AudioRedactionTask(
            doc_id=123,
            audio_id="abc123",
            audio_path="/app/data/uploads/audio/recording.mp3",
            mute_audio=True,
            mute_style="beep",
        ))
    """

    def __init__(
        self,
        vector_store: "VectorStore",
        audio_pii_redactor: Optional["AudioPIIRedactor"],
        verbose: bool = False,
        max_failed_history: int = 50,
        memory_monitor: Optional["MemoryMonitor"] = None,
    ):
        """Initialize the async audio redactor.

        Args:
            vector_store: Vector store for updating document metadata.
            audio_pii_redactor: Audio PII redactor for transcription + detection.
            verbose: Whether to print debug information.
            max_failed_history: Maximum number of failed tasks to keep.
            memory_monitor: Optional MemoryMonitor for backpressure.
        """
        self.vector_store = vector_store
        self.audio_pii_redactor = audio_pii_redactor
        self.verbose = verbose
        self.max_failed_history = max_failed_history
        self._memory_monitor = memory_monitor

        self._queue: Queue[AudioRedactionTask] = Queue()
        self._running = False
        self._worker_thread: Optional[threading.Thread] = None
        self._pending_count = 0
        self._completed_count = 0
        self._retry_count = 0
        self._failed_tasks: deque[FailedAudioTask] = deque(maxlen=max_failed_history)
        self._lock = threading.Lock()

        # Current processing state
        self._current_audio_id: Optional[str] = None
        self._current_doc_id: Optional[int] = None
        self._current_stage: Optional[str] = None  # "transcribing", "detecting_pii", "redacting_audio"

    def start(self):
        """Start the background audio processing worker."""
        if self._running:
            return

        self._running = True
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker_thread.start()
        if self.verbose:
            print("AsyncAudioRedactor: Background worker started")

    def stop(self):
        """Stop the background audio processing worker."""
        self._running = False
        if self._worker_thread:
            self._worker_thread.join(timeout=10)  # Longer timeout for GPU operations
        if self.verbose:
            print("AsyncAudioRedactor: Background worker stopped")

    def queue_task(self, task: AudioRedactionTask):
        """Queue an audio file for background transcription and PII redaction."""
        with self._lock:
            self._pending_count += 1
        self._queue.put(task)
        if self.verbose:
            print(f"AsyncAudioRedactor: Queued audio {task.audio_id} for processing "
                  f"(pending: {self._pending_count})")

    def get_pending_count(self) -> int:
        """Get the number of pending audio tasks."""
        with self._lock:
            return self._pending_count

    def get_status(self) -> Dict[str, Any]:
        """Get detailed audio processing queue status."""
        with self._lock:
            status = {
                "pending": self._pending_count,
                "completed": self._completed_count,
                "running": self._running,
                "total_retries": self._retry_count,
                "failed_count": len(self._failed_tasks),
            }
            if self._current_audio_id is not None:
                status["current"] = {
                    "doc_id": self._current_doc_id,
                    "audio_id": self._current_audio_id,
                    "stage": self._current_stage,
                }
            return status

    def get_failed_tasks(self) -> List[Dict[str, Any]]:
        """Get list of failed tasks for debugging."""
        with self._lock:
            return [
                {
                    "doc_id": t.doc_id,
                    "audio_id": t.audio_id,
                    "audio_path": t.audio_path,
                    "attempts": t.attempts,
                    "last_error": t.last_error,
                    "failed_at": t.failed_at,
                }
                for t in self._failed_tasks
            ]

    def _set_stage(self, stage: Optional[str]):
        """Update current processing stage for debug visibility."""
        with self._lock:
            self._current_stage = stage

    def _worker_loop(self):
        """Background worker that processes audio tasks."""
        while self._running:
            # Memory backpressure: pause if system memory is critically high
            if self._memory_monitor and self._memory_monitor.is_above_high_watermark():
                if self.verbose:
                    print(f"AsyncAudioRedactor: Memory above high watermark "
                          f"({self._memory_monitor.get_used_pct():.0f}%), "
                          f"waiting for memory...")
                self._memory_monitor.wait_for_memory(timeout=60)
                # Re-check after waiting: if still above watermark, skip this cycle
                if self._memory_monitor.is_above_high_watermark():
                    if self.verbose:
                        print(f"AsyncAudioRedactor: Still above watermark after wait, "
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

                    print(f"AsyncAudioRedactor: Retrying audio {task.audio_id} "
                          f"(attempt {task.attempt}/{MAX_RETRIES}) after {delay}s - {error_msg}")

                    time.sleep(delay)
                    self._queue.put(task)
                    self._queue.task_done()
                else:
                    # Exhausted retries or non-retryable error
                    print(f"AsyncAudioRedactor: Failed audio {task.audio_id} "
                          f"after {task.attempt + 1} attempts: {error_msg}")

                    with self._lock:
                        self._failed_tasks.append(FailedAudioTask(
                            doc_id=task.doc_id,
                            audio_id=task.audio_id,
                            audio_path=task.audio_path,
                            attempts=task.attempt + 1,
                            last_error=error_msg,
                        ))
                        self._pending_count -= 1
                    self._queue.task_done()

    def _process_task(self, task: AudioRedactionTask):
        """Process a single audio transcription and redaction task.

        Steps:
        1. Transcribe audio with word-level timestamps (GPU)
        2. Detect PII regions in transcript (CPU)
        3. Redact transcript (CPU)
        4. Optionally redact audio file (CPU)
        5. Update document metadata with results
        """
        if not self.audio_pii_redactor:
            if self.verbose:
                print(f"AsyncAudioRedactor: No audio PII redactor available, "
                      f"skipping {task.audio_id}")
            return

        with self._lock:
            self._current_audio_id = task.audio_id
            self._current_doc_id = task.doc_id

        try:
            if self.verbose:
                attempt_str = f" (attempt {task.attempt + 1})" if task.attempt > 0 else ""
                print(f"AsyncAudioRedactor: Processing audio {task.audio_id}{attempt_str}...")

            # Check if audio file still exists
            if not Path(task.audio_path).exists():
                print(f"AsyncAudioRedactor: Audio file not found: {task.audio_path}")
                return

            # Step 1: Transcribe with timestamps (GPU-bound)
            self._set_stage("transcribing")
            if self.verbose:
                print(f"  - Transcribing with Whisper...")
            start_time = time.time()

            transcription = self.audio_pii_redactor.transcribe_with_timestamps(task.audio_path)
            transcription_time = time.time() - start_time

            if self.verbose:
                print(f"  - Transcription complete: {len(transcription.words)} words "
                      f"in {transcription_time:.1f}s")

            # Step 2: Detect PII regions (CPU-bound)
            self._set_stage("detecting_pii")
            if self.verbose:
                print(f"  - Detecting PII regions...")

            pii_regions = self.audio_pii_redactor.detect_pii_regions(
                transcription.text,
                transcription.words,
            )

            has_pii = bool(pii_regions)
            pii_types_found = list(set(r.pii_type for r in pii_regions)) if pii_regions else []

            if self.verbose:
                if has_pii:
                    print(f"  - Found {len(pii_regions)} PII regions: {pii_types_found}")
                else:
                    print(f"  - No PII detected")

            # Step 3: Redact transcript (CPU-bound)
            self._set_stage("redacting_transcript")
            redacted_transcript = self.audio_pii_redactor.redact_transcript(
                transcription.text,
                pii_regions,
            )

            # Step 4: Optionally redact audio file (CPU-bound)
            redacted_audio_path = None
            if task.mute_audio and has_pii and self.audio_pii_redactor.is_audio_redaction_available():
                self._set_stage("redacting_audio")
                if self.verbose:
                    print(f"  - Creating redacted audio file ({task.mute_style})...")

                try:
                    redacted_audio_path = self.audio_pii_redactor.redact_audio(
                        task.audio_path,
                        pii_regions,
                        mute_style=task.mute_style,
                    )
                    if self.verbose:
                        print(f"  - Redacted audio saved: {redacted_audio_path}")
                except Exception as e:
                    # Audio redaction is optional, log but don't fail
                    print(f"AsyncAudioRedactor: Audio file redaction failed: {e}")

            # Step 5: Update document metadata
            self._set_stage("updating_metadata")
            metadata_updates = {
                "original_transcript": transcription.text,
                "redacted_transcript": redacted_transcript,
                "has_pii": has_pii,
                "pii_types_found": pii_types_found,
                "pii_regions": [
                    {
                        "start_time": r.start_time,
                        "end_time": r.end_time,
                        "pii_type": r.pii_type,
                        "original_text": r.original_text,
                        "replacement_text": r.replacement_text,
                        "confidence": r.confidence,
                    }
                    for r in pii_regions
                ],
                "word_count": len(transcription.words),
                "transcription_complete": True,
                "redaction_pending": False,
            }

            if redacted_audio_path:
                metadata_updates["redacted_audio_path"] = redacted_audio_path

            # Build formatted document text from transcription
            # (replaces the "[Transcription in progress...]" placeholder)
            duration_secs = transcription.words[-1].end if transcription.words else 0
            duration_str = f" ({duration_secs / 60:.0f}:{duration_secs % 60:02.0f})" if duration_secs > 0 else ""
            document_text = f"[Audio transcription{duration_str}]\n\n{transcription.text}"

            self.vector_store.update_document_metadata(
                task.doc_id, metadata_updates, text=document_text
            )

            if self.verbose:
                print(f"AsyncAudioRedactor: Audio {task.audio_id} processing complete")

        finally:
            with self._lock:
                self._current_audio_id = None
                self._current_doc_id = None
                self._current_stage = None


# Global instance (lazy initialization)
_global_async_audio_redactor: Optional[AsyncAudioRedactor] = None


def get_async_audio_redactor(
    vector_store: "VectorStore",
    audio_pii_redactor: Optional["AudioPIIRedactor"] = None,
    verbose: bool = False,
) -> AsyncAudioRedactor:
    """Get or create the global AsyncAudioRedactor instance.

    Args:
        vector_store: Vector store for metadata updates.
        audio_pii_redactor: Optional audio PII redactor.
        verbose: Enable verbose logging.

    Returns:
        Global AsyncAudioRedactor instance.
    """
    global _global_async_audio_redactor

    if _global_async_audio_redactor is None:
        _global_async_audio_redactor = AsyncAudioRedactor(
            vector_store=vector_store,
            audio_pii_redactor=audio_pii_redactor,
            verbose=verbose,
        )

    return _global_async_audio_redactor
