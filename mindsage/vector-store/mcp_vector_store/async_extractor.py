"""Async background extraction for metadata extraction.

Allows fast document indexing while extraction runs in the background.
Uses embedding-based and spaCy NER extraction (no LLM required).

Features:
- Retry logic with exponential backoff for transient failures
- Failed task tracking for debugging
- Graceful degradation on persistent failures
"""

import threading
import time
from queue import Queue, Empty
from typing import Optional, TYPE_CHECKING, Dict, Any, List
from dataclasses import dataclass, field
from collections import deque

if TYPE_CHECKING:
    from .txtai_adapter import TxtaiAdapter as VectorStore
    from .passage_extractor import PassageExtractor
    from .topic_labeler import TopicLabeler
    from .gpu_scheduler import MemoryMonitor


# Retry configuration
MAX_RETRIES = 3
RETRY_DELAYS = [1.0, 2.0, 4.0]  # Exponential backoff in seconds

# Errors that are likely transient and worth retrying
RETRYABLE_ERROR_PATTERNS = [
    "database is locked",
    "recursive use of cursors",
    "unique constraint failed",
    "sqlite",
    "connection",
    "timeout",
    "timed out",
    "busy",
]


def is_retryable_error(error: Exception) -> bool:
    """Check if an error is likely transient and worth retrying."""
    error_str = str(error).lower()
    return any(pattern in error_str for pattern in RETRYABLE_ERROR_PATTERNS)


@dataclass
class ExtractionTask:
    """A document extraction task."""
    doc_id: int
    text: str
    extract_key_passages: bool = True
    extract_key_entities: bool = True
    extract_structured_metadata: bool = True
    extract_filters: bool = True
    extract_topics: bool = True  # Generate topics for the document
    source: Optional[str] = None  # Data source hint (e.g., 'chatgpt', 'readwise')
    filename: Optional[str] = None  # Filename for context
    media_type: Optional[str] = None  # 'audio', 'image', or None for text
    attempt: int = 0  # Current retry attempt (0 = first try)
    last_error: Optional[str] = None  # Last error message for debugging


@dataclass
class FailedTask:
    """A task that exhausted all retries."""
    doc_id: int
    filename: Optional[str]
    attempts: int
    last_error: str
    failed_at: float = field(default_factory=time.time)


class AsyncExtractor:
    """Background extractor that processes documents asynchronously.

    Documents are indexed immediately with just embeddings, then
    extraction (key_passages, key_entities, structured_metadata)
    happens in the background without blocking the API.

    Uses embedding-based and spaCy NER extraction which is lightweight
    and doesn't require GPU memory management.

    Features:
    - Automatic retry with exponential backoff for transient failures
    - Tracks failed tasks for debugging and manual recovery
    - Graceful degradation when extraction fails
    """

    def __init__(
        self,
        vector_store: "VectorStore",
        passage_extractor: Optional["PassageExtractor"],
        topic_labeler: Optional["TopicLabeler"] = None,
        verbose: bool = False,
        max_failed_history: int = 100,
        memory_monitor: Optional["MemoryMonitor"] = None,
        **kwargs  # Accept and ignore legacy parameters
    ):
        """Initialize the async extractor.

        Args:
            vector_store: Vector store for updating document metadata.
            passage_extractor: Passage extractor for key sentences and entities.
            topic_labeler: Topic labeler for generating topics.
            verbose: Whether to print debug information.
            max_failed_history: Maximum number of failed tasks to keep in history.
            memory_monitor: Optional MemoryMonitor for backpressure.
            **kwargs: Ignored (for backward compatibility with model_manager).
        """
        self.vector_store = vector_store
        self.passage_extractor = passage_extractor
        self.topic_labeler = topic_labeler
        self.verbose = verbose
        self.max_failed_history = max_failed_history
        self._memory_monitor = memory_monitor

        self._queue: Queue[ExtractionTask] = Queue()
        self._running = False
        self._worker_thread: Optional[threading.Thread] = None
        self._pending_count = 0
        self._retry_count = 0  # Total retries performed
        self._failed_tasks: deque[FailedTask] = deque(maxlen=max_failed_history)
        self._lock = threading.Lock()

        # Current processing state (for debug panel)
        self._current_doc_id: Optional[int] = None
        self._current_stage: Optional[str] = None  # e.g. "passages", "entities", "metadata", "filters", "topics"
        self._current_filename: Optional[str] = None

        # Ignore legacy parameters
        if 'model_manager' in kwargs and verbose:
            print("AsyncExtractor: model_manager parameter ignored (no longer needed)")

    def start(self):
        """Start the background extraction worker."""
        if self._running:
            return

        self._running = True
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker_thread.start()
        if self.verbose:
            print("AsyncExtractor: Background worker started")

    def stop(self):
        """Stop the background extraction worker."""
        self._running = False
        if self._worker_thread:
            self._worker_thread.join(timeout=5)
        if self.verbose:
            print("AsyncExtractor: Background worker stopped")

    def queue_extraction(self, task: ExtractionTask):
        """Queue a document for background extraction."""
        with self._lock:
            self._pending_count += 1
        self._queue.put(task)
        if self.verbose:
            print(f"AsyncExtractor: Queued doc {task.doc_id} for extraction (pending: {self._pending_count})")

    def get_pending_count(self) -> int:
        """Get the number of pending extractions."""
        with self._lock:
            return self._pending_count

    def get_status(self) -> Dict[str, Any]:
        """Get detailed extraction queue status."""
        with self._lock:
            # Check memory state for frontend debug panel
            waiting_for_memory = False
            memory_constrained = False
            if self._memory_monitor:
                memory_constrained = self._memory_monitor.is_above_high_watermark()
                waiting_for_memory = memory_constrained

            status = {
                "pending": self._pending_count,
                "running": self._running,
                "total_retries": self._retry_count,
                "failed_count": len(self._failed_tasks),
                "waiting_for_memory": waiting_for_memory,
                "memory_constrained": memory_constrained,
            }
            if self._current_doc_id is not None:
                status["current"] = {
                    "doc_id": self._current_doc_id,
                    "stage": self._current_stage,
                    "filename": self._current_filename,
                }
            return status

    def get_failed_tasks(self) -> List[Dict[str, Any]]:
        """Get list of failed tasks for debugging."""
        with self._lock:
            return [
                {
                    "doc_id": t.doc_id,
                    "filename": t.filename,
                    "attempts": t.attempts,
                    "last_error": t.last_error,
                    "failed_at": t.failed_at,
                }
                for t in self._failed_tasks
            ]

    def retry_failed_task(self, doc_id: int) -> bool:
        """Manually retry a failed task by doc_id.

        Returns True if task was found and requeued, False otherwise.
        """
        with self._lock:
            for i, task in enumerate(self._failed_tasks):
                if task.doc_id == doc_id:
                    # Get document text from vector store
                    doc = self.vector_store.get_document(doc_id)
                    if doc:
                        # Create new task and queue it
                        new_task = ExtractionTask(
                            doc_id=doc_id,
                            text=doc.text,
                            filename=task.filename,
                        )
                        self._failed_tasks.remove(task)
                        self._pending_count += 1
                        self._queue.put(new_task)
                        if self.verbose:
                            print(f"AsyncExtractor: Requeued failed doc {doc_id}")
                        return True
            return False

    def _worker_loop(self):
        """Background worker that processes extraction tasks."""
        while self._running:
            # Memory backpressure: pause if system memory is critically high
            # AsyncExtractor is mostly CPU-bound, but on Jetson unified memory
            # CPU pressure affects GPU availability too
            if self._memory_monitor and self._memory_monitor.is_above_high_watermark():
                if self.verbose:
                    print(f"AsyncExtractor: Memory above high watermark "
                          f"({self._memory_monitor.get_used_pct():.0f}%), "
                          f"waiting for memory...")
                self._memory_monitor.wait_for_memory(timeout=60)
                # Re-check after waiting: if still above watermark, skip this cycle
                if self._memory_monitor.is_above_high_watermark():
                    if self.verbose:
                        print(f"AsyncExtractor: Still above watermark after wait, "
                              f"deferring processing")
                    continue

            try:
                task = self._queue.get(timeout=1.0)
            except Empty:
                continue

            requeued = False
            try:
                self._process_task(task)
                # Success - decrement pending and mark done
                with self._lock:
                    self._pending_count -= 1
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

                    print(f"AsyncExtractor: Retrying doc {task.doc_id} "
                          f"(attempt {task.attempt}/{MAX_RETRIES}) after {delay}s - {error_msg}")

                    # Sleep before retry (in worker thread, so it's ok)
                    time.sleep(delay)

                    # Requeue the task (don't decrement pending_count, don't call task_done yet)
                    self._queue.put(task)
                    self._queue.task_done()
                    requeued = True
                else:
                    # Exhausted retries or non-retryable error
                    print(f"AsyncExtractor: Failed doc {task.doc_id} after {task.attempt + 1} attempts: {error_msg}")

                    with self._lock:
                        self._failed_tasks.append(FailedTask(
                            doc_id=task.doc_id,
                            filename=task.filename,
                            attempts=task.attempt + 1,
                            last_error=error_msg,
                        ))
                        self._pending_count -= 1
                    self._queue.task_done()

    def _set_stage(self, doc_id: int, stage: Optional[str], filename: Optional[str] = None):
        """Update current processing stage for debug visibility."""
        with self._lock:
            self._current_doc_id = doc_id if stage else None
            self._current_stage = stage
            self._current_filename = filename if stage else None

    def _process_task(self, task: ExtractionTask):
        """Process a single extraction task.

        Raises exception on failure to trigger retry logic.
        """
        if self.verbose:
            attempt_str = f" (attempt {task.attempt + 1})" if task.attempt > 0 else ""
            print(f"AsyncExtractor: Processing doc {task.doc_id}{attempt_str}...")

        updates = {}
        errors = []

        # Extract key passages
        if task.extract_key_passages and self.passage_extractor:
            self._set_stage(task.doc_id, "passages", task.filename)
            try:
                passages = self.passage_extractor.extract_key_sentences(
                    task.text,
                    max_sentences=5
                )
                if passages:
                    updates['key_passages'] = passages
                    if self.verbose:
                        print(f"  - Extracted {len(passages)} key passages")
            except Exception as e:
                errors.append(f"key_passages: {e}")
                if self.verbose:
                    print(f"  - Key passages failed: {e}")

        # Extract key entities
        if task.extract_key_entities and self.passage_extractor:
            self._set_stage(task.doc_id, "entities", task.filename)
            try:
                entities = self.passage_extractor.extract_key_entities(task.text)
                if entities:
                    updates['key_entities'] = entities
                    if self.verbose:
                        print(f"  - Extracted {len(entities)} key entities")
            except Exception as e:
                errors.append(f"key_entities: {e}")
                if self.verbose:
                    print(f"  - Key entities failed: {e}")

        # Extract structured metadata
        if task.extract_structured_metadata and self.passage_extractor:
            self._set_stage(task.doc_id, "metadata", task.filename)
            try:
                structured = self.passage_extractor.extract_structured_metadata(task.text)
                if structured:
                    updates['structured_metadata'] = structured.to_dict()
                    if self.verbose:
                        print(f"  - Extracted structured metadata")
            except Exception as e:
                errors.append(f"structured_metadata: {e}")
                if self.verbose:
                    print(f"  - Structured metadata failed: {e}")

        # Extract document filters for knowledge graph browsing
        if task.extract_filters and self.passage_extractor:
            self._set_stage(task.doc_id, "filters", task.filename)
            try:
                filters = self.passage_extractor.generate_document_filters(
                    task.text,
                    source=task.source,
                    filename=task.filename
                )
                if filters:
                    updates['document_filters'] = filters
                    if self.verbose:
                        print(f"  - Generated filters: {filters.get('content_type')}/{filters.get('domain')}")
            except Exception as e:
                errors.append(f"filters: {e}")
                if self.verbose:
                    print(f"  - Filter generation failed: {e}")

        # Generate topics for the document
        if task.extract_topics and self.topic_labeler:
            self._set_stage(task.doc_id, "topics", task.filename)
            try:
                topic_result = self.topic_labeler.generate_topics(
                    text=task.text,
                    num_topics=3
                )
                if topic_result and topic_result.topics:
                    # Update topics via vector_store method (handles chunk propagation)
                    self.vector_store.update_document_topics(
                        doc_id=task.doc_id,
                        topics=topic_result.topics,
                        primary_topic=topic_result.primary_topic
                    )
                    if self.verbose:
                        print(f"  - Generated topics: {topic_result.topics}")
            except Exception as e:
                errors.append(f"topics: {e}")
                if self.verbose:
                    print(f"  - Topic generation failed: {e}")
                # Re-raise database errors to trigger retry
                if is_retryable_error(e):
                    self._set_stage(task.doc_id, None)
                    raise

        # Update document with extracted metadata
        if updates:
            self._set_stage(task.doc_id, "saving", task.filename)
            # This is the critical write operation - let it raise for retry
            self.vector_store.update_document_metadata(task.doc_id, updates)
            if self.verbose:
                print(f"AsyncExtractor: Doc {task.doc_id} extraction complete")
        elif not errors:
            if self.verbose:
                print(f"AsyncExtractor: Doc {task.doc_id} - no updates needed")

        # Clear stage
        self._set_stage(task.doc_id, None)
