"""Tests for AsyncExtractor retry logic and error handling.

Tests the following features:
- Retry logic with exponential backoff
- Failed task tracking
- Retryable error detection
- Manual retry of failed tasks
"""

import pytest
import time
import threading
from unittest.mock import Mock, MagicMock, patch
from dataclasses import dataclass

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp_vector_store.async_extractor import (
    AsyncExtractor,
    ExtractionTask,
    FailedTask,
    is_retryable_error,
    MAX_RETRIES,
    RETRY_DELAYS,
)


class TestRetryableErrorDetection:
    """Tests for is_retryable_error function."""

    def test_sqlite_errors_are_retryable(self):
        """SQLite errors should be retried."""
        assert is_retryable_error(Exception("sqlite3.OperationalError: database is locked"))
        assert is_retryable_error(Exception("UNIQUE constraint failed: sections.indexid"))
        assert is_retryable_error(Exception("Recursive use of cursors not allowed"))

    def test_connection_errors_are_retryable(self):
        """Connection errors should be retried."""
        assert is_retryable_error(Exception("Connection refused"))
        assert is_retryable_error(Exception("Connection timeout"))

    def test_timeout_errors_are_retryable(self):
        """Timeout errors should be retried."""
        assert is_retryable_error(Exception("Operation timed out"))
        assert is_retryable_error(Exception("Request timeout"))

    def test_busy_errors_are_retryable(self):
        """Busy errors should be retried."""
        assert is_retryable_error(Exception("Database is busy"))

    def test_non_retryable_errors(self):
        """Non-transient errors should not be retried."""
        assert not is_retryable_error(Exception("ValueError: invalid input"))
        assert not is_retryable_error(Exception("KeyError: 'missing_key'"))
        assert not is_retryable_error(Exception("File not found"))
        assert not is_retryable_error(Exception("Permission denied"))


class TestExtractionTask:
    """Tests for ExtractionTask dataclass."""

    def test_default_values(self):
        """Test default values are set correctly."""
        task = ExtractionTask(doc_id=1, text="test")
        assert task.doc_id == 1
        assert task.text == "test"
        assert task.extract_key_passages is True
        assert task.extract_key_entities is True
        assert task.extract_topics is True
        assert task.attempt == 0
        assert task.last_error is None

    def test_attempt_tracking(self):
        """Test that attempt counter can be incremented."""
        task = ExtractionTask(doc_id=1, text="test")
        task.attempt = 1
        task.last_error = "Some error"
        assert task.attempt == 1
        assert task.last_error == "Some error"


class TestAsyncExtractorRetry:
    """Tests for AsyncExtractor retry logic."""

    @pytest.fixture
    def mock_vector_store(self):
        """Create a mock vector store."""
        store = Mock()
        store.update_document_metadata = Mock()
        store.update_document_topics = Mock()
        store.get_document = Mock(return_value=Mock(text="test text"))
        return store

    @pytest.fixture
    def mock_passage_extractor(self):
        """Create a mock passage extractor."""
        extractor = Mock()
        extractor.extract_key_sentences = Mock(return_value=["sentence 1"])
        extractor.extract_key_entities = Mock(return_value={"persons": ["John"]})
        extractor.extract_structured_metadata = Mock(return_value=None)
        extractor.generate_document_filters = Mock(return_value={"content_type": "document"})
        return extractor

    @pytest.fixture
    def mock_topic_labeler(self):
        """Create a mock topic labeler."""
        labeler = Mock()
        result = Mock()
        result.topics = ["programming"]
        result.primary_topic = "programming"
        labeler.generate_topics = Mock(return_value=result)
        return labeler

    def test_successful_extraction_no_retry(self, mock_vector_store, mock_passage_extractor, mock_topic_labeler):
        """Test that successful extraction doesn't trigger retry."""
        extractor = AsyncExtractor(
            vector_store=mock_vector_store,
            passage_extractor=mock_passage_extractor,
            topic_labeler=mock_topic_labeler,
            verbose=False
        )

        task = ExtractionTask(doc_id=1, text="test content")
        extractor._process_task(task)

        # Should have called update methods
        mock_vector_store.update_document_metadata.assert_called_once()
        mock_vector_store.update_document_topics.assert_called_once()

    def test_retryable_error_increments_attempt(self, mock_vector_store, mock_passage_extractor):
        """Test that retryable errors increment attempt counter."""
        # Make update_document_metadata raise a retryable error
        mock_vector_store.update_document_metadata.side_effect = Exception("database is locked")

        extractor = AsyncExtractor(
            vector_store=mock_vector_store,
            passage_extractor=mock_passage_extractor,
            verbose=False
        )

        task = ExtractionTask(doc_id=1, text="test content")

        with pytest.raises(Exception):
            extractor._process_task(task)

    def test_non_retryable_error_not_retried(self, mock_vector_store, mock_passage_extractor):
        """Test that non-retryable errors are not retried."""
        # Make update_document_metadata raise a non-retryable error
        mock_vector_store.update_document_metadata.side_effect = ValueError("invalid input")

        extractor = AsyncExtractor(
            vector_store=mock_vector_store,
            passage_extractor=mock_passage_extractor,
            verbose=False
        )

        task = ExtractionTask(doc_id=1, text="test content")

        # Should raise ValueError (not retryable)
        with pytest.raises(ValueError):
            extractor._process_task(task)

    def test_get_status_includes_retry_info(self, mock_vector_store):
        """Test that get_status includes retry information."""
        extractor = AsyncExtractor(
            vector_store=mock_vector_store,
            passage_extractor=None,
            verbose=False
        )

        status = extractor.get_status()
        assert "pending" in status
        assert "running" in status
        assert "total_retries" in status
        assert "failed_count" in status

    def test_failed_tasks_tracking(self, mock_vector_store):
        """Test that failed tasks are tracked."""
        extractor = AsyncExtractor(
            vector_store=mock_vector_store,
            passage_extractor=None,
            verbose=False
        )

        # Manually add a failed task
        from mcp_vector_store.async_extractor import FailedTask
        extractor._failed_tasks.append(FailedTask(
            doc_id=1,
            filename="test.txt",
            attempts=3,
            last_error="database is locked"
        ))

        failed = extractor.get_failed_tasks()
        assert len(failed) == 1
        assert failed[0]["doc_id"] == 1
        assert failed[0]["attempts"] == 3
        assert "database is locked" in failed[0]["last_error"]

    def test_retry_failed_task(self, mock_vector_store):
        """Test manual retry of a failed task."""
        mock_vector_store.get_document.return_value = Mock(text="test text")

        extractor = AsyncExtractor(
            vector_store=mock_vector_store,
            passage_extractor=None,
            verbose=False
        )

        # Add a failed task
        from mcp_vector_store.async_extractor import FailedTask
        extractor._failed_tasks.append(FailedTask(
            doc_id=42,
            filename="test.txt",
            attempts=3,
            last_error="database is locked"
        ))

        # Retry the failed task
        result = extractor.retry_failed_task(42)
        assert result is True
        assert extractor.get_pending_count() == 1
        assert len(extractor.get_failed_tasks()) == 0

    def test_retry_nonexistent_task_returns_false(self, mock_vector_store):
        """Test that retrying a non-existent task returns False."""
        extractor = AsyncExtractor(
            vector_store=mock_vector_store,
            passage_extractor=None,
            verbose=False
        )

        result = extractor.retry_failed_task(999)
        assert result is False


class TestAsyncExtractorIntegration:
    """Integration tests for AsyncExtractor with actual queue processing."""

    @pytest.fixture
    def mock_vector_store(self):
        """Create a mock vector store."""
        store = Mock()
        store.update_document_metadata = Mock()
        store.update_document_topics = Mock()
        return store

    def test_worker_processes_task(self, mock_vector_store):
        """Test that the worker thread processes tasks."""
        extractor = AsyncExtractor(
            vector_store=mock_vector_store,
            passage_extractor=None,
            topic_labeler=None,
            verbose=False
        )

        extractor.start()
        try:
            task = ExtractionTask(doc_id=1, text="test content")
            extractor.queue_extraction(task)

            # Wait for processing
            time.sleep(0.5)

            # Pending count should be 0 after processing
            assert extractor.get_pending_count() == 0
        finally:
            extractor.stop()

    def test_worker_retries_on_transient_error(self, mock_vector_store):
        """Test that worker retries on transient errors."""
        call_count = [0]

        def failing_update(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] < 3:
                raise Exception("database is locked")
            return True

        mock_vector_store.update_document_metadata = failing_update

        # Create a mock passage extractor that returns data
        mock_passage_extractor = Mock()
        mock_passage_extractor.extract_key_sentences = Mock(return_value=["test"])
        mock_passage_extractor.extract_key_entities = Mock(return_value={})
        mock_passage_extractor.extract_structured_metadata = Mock(return_value=None)
        mock_passage_extractor.generate_document_filters = Mock(return_value=None)

        extractor = AsyncExtractor(
            vector_store=mock_vector_store,
            passage_extractor=mock_passage_extractor,
            topic_labeler=None,
            verbose=True
        )

        extractor.start()
        try:
            task = ExtractionTask(doc_id=1, text="test content")
            extractor.queue_extraction(task)

            # Wait for retries (1s + 2s delays plus processing time)
            time.sleep(5)

            # Should have retried and eventually succeeded
            assert call_count[0] == 3  # 2 failures + 1 success
            assert extractor.get_pending_count() == 0

            status = extractor.get_status()
            assert status["total_retries"] == 2  # 2 retries before success
        finally:
            extractor.stop()

    def test_worker_gives_up_after_max_retries(self, mock_vector_store):
        """Test that worker gives up after MAX_RETRIES."""
        mock_vector_store.update_document_metadata.side_effect = Exception("database is locked")

        mock_passage_extractor = Mock()
        mock_passage_extractor.extract_key_sentences = Mock(return_value=["test"])
        mock_passage_extractor.extract_key_entities = Mock(return_value={})
        mock_passage_extractor.extract_structured_metadata = Mock(return_value=None)
        mock_passage_extractor.generate_document_filters = Mock(return_value=None)

        extractor = AsyncExtractor(
            vector_store=mock_vector_store,
            passage_extractor=mock_passage_extractor,
            topic_labeler=None,
            verbose=False
        )

        extractor.start()
        try:
            task = ExtractionTask(doc_id=1, text="test content")
            extractor.queue_extraction(task)

            # Wait for all retries (1s + 2s + 4s = 7s plus processing)
            time.sleep(10)

            # Should be in failed tasks
            failed = extractor.get_failed_tasks()
            assert len(failed) == 1
            assert failed[0]["doc_id"] == 1
            assert failed[0]["attempts"] == MAX_RETRIES + 1  # Initial + retries
        finally:
            extractor.stop()


class TestRetryConfiguration:
    """Tests for retry configuration constants."""

    def test_max_retries_is_reasonable(self):
        """MAX_RETRIES should be a reasonable value."""
        assert MAX_RETRIES >= 1
        assert MAX_RETRIES <= 10

    def test_retry_delays_are_exponential(self):
        """RETRY_DELAYS should increase exponentially."""
        assert len(RETRY_DELAYS) >= 1
        for i in range(1, len(RETRY_DELAYS)):
            assert RETRY_DELAYS[i] > RETRY_DELAYS[i-1]

    def test_retry_delays_not_too_long(self):
        """Individual delays shouldn't be too long."""
        for delay in RETRY_DELAYS:
            assert delay <= 30  # Max 30 seconds


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
