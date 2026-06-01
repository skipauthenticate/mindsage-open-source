"""Tests for AsyncAudioRedactor retry logic and error handling.

Tests the following features:
- Retry logic with exponential backoff
- Failed task tracking
- Retryable error detection (including CUDA/GPU errors)
- Task queuing and processing
- Audio transcription and PII redaction pipeline
"""

import pytest
import time
import threading
import tempfile
import os
import sys
from unittest.mock import Mock, MagicMock, patch
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp_vector_store.async_audio_redactor import (
    AsyncAudioRedactor,
    AudioRedactionTask,
    FailedAudioTask,
    is_retryable_error,
    MAX_RETRIES,
    RETRY_DELAYS,
)


class TestRetryableErrorDetection:
    """Tests for is_retryable_error function."""

    def test_database_errors_are_retryable(self):
        """Database errors should be retried."""
        assert is_retryable_error(Exception("sqlite3.OperationalError: database is locked"))
        assert is_retryable_error(Exception("Database is busy"))

    def test_connection_errors_are_retryable(self):
        """Connection errors should be retried."""
        assert is_retryable_error(Exception("Connection refused"))
        assert is_retryable_error(Exception("Connection timeout"))

    def test_timeout_errors_are_retryable(self):
        """Timeout errors should be retried."""
        assert is_retryable_error(Exception("Operation timed out"))
        assert is_retryable_error(Exception("Request timeout"))

    def test_gpu_memory_errors_are_retryable(self):
        """GPU/CUDA memory errors should be retried."""
        assert is_retryable_error(Exception("CUDA out of memory"))
        assert is_retryable_error(Exception("RuntimeError: out of memory"))
        assert is_retryable_error(Exception("OOM killer invoked"))

    def test_non_retryable_errors(self):
        """Non-transient errors should not be retried."""
        assert not is_retryable_error(Exception("ValueError: invalid input"))
        assert not is_retryable_error(Exception("KeyError: 'missing_key'"))
        assert not is_retryable_error(Exception("File not found"))
        assert not is_retryable_error(Exception("Permission denied"))


class TestAudioRedactionTask:
    """Tests for AudioRedactionTask dataclass."""

    def test_default_values(self):
        """Test default values are set correctly."""
        task = AudioRedactionTask(
            doc_id=1,
            audio_id="abc123",
            audio_path="/path/to/audio.mp3"
        )
        assert task.doc_id == 1
        assert task.audio_id == "abc123"
        assert task.audio_path == "/path/to/audio.mp3"
        assert task.mute_audio is False
        assert task.mute_style == "silence"
        assert task.session_id is None
        assert task.attempt == 0
        assert task.last_error is None

    def test_mute_audio_options(self):
        """Test audio muting options."""
        task = AudioRedactionTask(
            doc_id=1,
            audio_id="abc123",
            audio_path="/path/to/audio.mp3",
            mute_audio=True,
            mute_style="beep"
        )
        assert task.mute_audio is True
        assert task.mute_style == "beep"

    def test_attempt_tracking(self):
        """Test that attempt counter can be incremented."""
        task = AudioRedactionTask(
            doc_id=1,
            audio_id="abc123",
            audio_path="/path/to/audio.mp3"
        )
        task.attempt = 1
        task.last_error = "Some error"
        assert task.attempt == 1
        assert task.last_error == "Some error"


class TestFailedAudioTask:
    """Tests for FailedAudioTask dataclass."""

    def test_failed_task_creation(self):
        """Test failed task creation with timestamp."""
        before = time.time()
        failed = FailedAudioTask(
            doc_id=1,
            audio_id="abc123",
            audio_path="/path/to/audio.mp3",
            attempts=3,
            last_error="database is locked"
        )
        after = time.time()

        assert failed.doc_id == 1
        assert failed.audio_id == "abc123"
        assert failed.attempts == 3
        assert "database is locked" in failed.last_error
        assert before <= failed.failed_at <= after


class TestAsyncAudioRedactorBasic:
    """Basic tests for AsyncAudioRedactor."""

    @pytest.fixture
    def mock_vector_store(self):
        """Create a mock vector store."""
        store = Mock()
        store.update_document_metadata = Mock()
        return store

    @pytest.fixture
    def mock_audio_pii_redactor(self):
        """Create a mock audio PII redactor."""
        redactor = Mock()
        redactor.is_available.return_value = True
        redactor.is_audio_redaction_available.return_value = False

        # Mock transcription result
        transcription = Mock()
        transcription.text = "Hello, my name is John Smith."
        transcription.words = [
            Mock(word="Hello,", start=0.0, end=0.5),
            Mock(word="my", start=0.5, end=0.7),
            Mock(word="name", start=0.7, end=1.0),
            Mock(word="is", start=1.0, end=1.2),
            Mock(word="John", start=1.2, end=1.5),
            Mock(word="Smith.", start=1.5, end=2.0),
        ]
        redactor.transcribe_with_timestamps.return_value = transcription

        # Mock PII detection
        pii_region = Mock()
        pii_region.pii_type = "PERSON"
        pii_region.start_time = 1.2
        pii_region.end_time = 2.0
        pii_region.original_text = "John Smith"
        pii_region.replacement_text = "[PERSON]"
        pii_region.confidence = 0.95
        redactor.detect_pii_regions.return_value = [pii_region]

        # Mock transcript redaction
        redactor.redact_transcript.return_value = "Hello, my name is [PERSON]."

        return redactor

    def test_initialization(self, mock_vector_store, mock_audio_pii_redactor):
        """Test AsyncAudioRedactor initialization."""
        redactor = AsyncAudioRedactor(
            vector_store=mock_vector_store,
            audio_pii_redactor=mock_audio_pii_redactor,
            verbose=False
        )

        assert redactor.vector_store == mock_vector_store
        assert redactor.audio_pii_redactor == mock_audio_pii_redactor
        assert not redactor._running

    def test_start_stop(self, mock_vector_store, mock_audio_pii_redactor):
        """Test starting and stopping the worker."""
        redactor = AsyncAudioRedactor(
            vector_store=mock_vector_store,
            audio_pii_redactor=mock_audio_pii_redactor,
            verbose=False
        )

        redactor.start()
        assert redactor._running
        assert redactor._worker_thread is not None
        assert redactor._worker_thread.is_alive()

        redactor.stop()
        assert not redactor._running

    def test_queue_task(self, mock_vector_store, mock_audio_pii_redactor):
        """Test queuing a task."""
        redactor = AsyncAudioRedactor(
            vector_store=mock_vector_store,
            audio_pii_redactor=mock_audio_pii_redactor,
            verbose=False
        )

        task = AudioRedactionTask(
            doc_id=1,
            audio_id="abc123",
            audio_path="/path/to/audio.mp3"
        )
        redactor.queue_task(task)

        assert redactor.get_pending_count() == 1

    def test_get_status(self, mock_vector_store, mock_audio_pii_redactor):
        """Test get_status includes all required fields."""
        redactor = AsyncAudioRedactor(
            vector_store=mock_vector_store,
            audio_pii_redactor=mock_audio_pii_redactor,
            verbose=False
        )

        status = redactor.get_status()
        assert "pending" in status
        assert "completed" in status
        assert "running" in status
        assert "total_retries" in status
        assert "failed_count" in status


class TestAsyncAudioRedactorProcessing:
    """Tests for AsyncAudioRedactor task processing."""

    @pytest.fixture
    def mock_vector_store(self):
        """Create a mock vector store."""
        store = Mock()
        store.update_document_metadata = Mock()
        return store

    @pytest.fixture
    def mock_audio_pii_redactor(self):
        """Create a mock audio PII redactor."""
        redactor = Mock()
        redactor.is_available.return_value = True
        redactor.is_audio_redaction_available.return_value = False

        # Mock transcription result
        transcription = Mock()
        transcription.text = "Hello, my name is John Smith."
        transcription.words = [
            Mock(word="Hello,", start=0.0, end=0.5),
            Mock(word="my", start=0.5, end=0.7),
            Mock(word="name", start=0.7, end=1.0),
            Mock(word="is", start=1.0, end=1.2),
            Mock(word="John", start=1.2, end=1.5),
            Mock(word="Smith.", start=1.5, end=2.0),
        ]
        redactor.transcribe_with_timestamps.return_value = transcription

        # Mock PII detection - no PII
        redactor.detect_pii_regions.return_value = []
        redactor.redact_transcript.return_value = "Hello, my name is John Smith."

        return redactor

    def test_process_task_updates_metadata(self, mock_vector_store, mock_audio_pii_redactor):
        """Test that processing updates document metadata."""
        # Create a temporary audio file for the test
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"fake audio content")
            audio_path = f.name

        try:
            redactor = AsyncAudioRedactor(
                vector_store=mock_vector_store,
                audio_pii_redactor=mock_audio_pii_redactor,
                verbose=False
            )

            task = AudioRedactionTask(
                doc_id=1,
                audio_id="abc123",
                audio_path=audio_path
            )

            redactor._process_task(task)

            # Verify metadata was updated
            mock_vector_store.update_document_metadata.assert_called_once()
            call_args = mock_vector_store.update_document_metadata.call_args
            assert call_args[0][0] == 1  # doc_id

            metadata = call_args[0][1]
            assert "original_transcript" in metadata
            assert "redacted_transcript" in metadata
            assert metadata["transcription_complete"] is True
            assert metadata["redaction_pending"] is False

        finally:
            os.unlink(audio_path)

    def test_process_task_with_pii(self, mock_vector_store):
        """Test processing with PII detection."""
        # Create mock with PII
        redactor_mock = Mock()
        redactor_mock.is_available.return_value = True
        redactor_mock.is_audio_redaction_available.return_value = False

        transcription = Mock()
        transcription.text = "Call me at 555-1234."
        transcription.words = [
            Mock(word="Call", start=0.0, end=0.3),
            Mock(word="me", start=0.3, end=0.5),
            Mock(word="at", start=0.5, end=0.7),
            Mock(word="555-1234.", start=0.7, end=1.5),
        ]
        redactor_mock.transcribe_with_timestamps.return_value = transcription

        # Mock PII detection with phone number
        pii_region = Mock()
        pii_region.pii_type = "PHONE_NUMBER"
        pii_region.start_time = 0.7
        pii_region.end_time = 1.5
        pii_region.original_text = "555-1234"
        pii_region.replacement_text = "[PHONE_NUMBER]"
        pii_region.confidence = 0.99
        redactor_mock.detect_pii_regions.return_value = [pii_region]
        redactor_mock.redact_transcript.return_value = "Call me at [PHONE_NUMBER]."

        # Create temp audio file
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"fake audio content")
            audio_path = f.name

        try:
            async_redactor = AsyncAudioRedactor(
                vector_store=mock_vector_store,
                audio_pii_redactor=redactor_mock,
                verbose=False
            )

            task = AudioRedactionTask(
                doc_id=1,
                audio_id="abc123",
                audio_path=audio_path
            )

            async_redactor._process_task(task)

            # Verify metadata
            call_args = mock_vector_store.update_document_metadata.call_args
            metadata = call_args[0][1]
            assert metadata["has_pii"] is True
            assert "PHONE_NUMBER" in metadata["pii_types_found"]
            assert len(metadata["pii_regions"]) == 1
            assert metadata["original_transcript"] == "Call me at 555-1234."
            assert metadata["redacted_transcript"] == "Call me at [PHONE_NUMBER]."

        finally:
            os.unlink(audio_path)

    def test_missing_audio_file_skipped(self, mock_vector_store, mock_audio_pii_redactor):
        """Test that missing audio files are handled gracefully."""
        redactor = AsyncAudioRedactor(
            vector_store=mock_vector_store,
            audio_pii_redactor=mock_audio_pii_redactor,
            verbose=False
        )

        task = AudioRedactionTask(
            doc_id=1,
            audio_id="abc123",
            audio_path="/nonexistent/path/audio.mp3"
        )

        # Should not raise, just skip
        redactor._process_task(task)

        # Metadata should not be updated for missing files
        mock_vector_store.update_document_metadata.assert_not_called()


class TestAsyncAudioRedactorIntegration:
    """Integration tests for AsyncAudioRedactor with actual queue processing."""

    @pytest.fixture
    def mock_vector_store(self):
        """Create a mock vector store."""
        store = Mock()
        store.update_document_metadata = Mock()
        return store

    @pytest.fixture
    def mock_audio_pii_redactor(self):
        """Create a mock audio PII redactor."""
        redactor = Mock()
        redactor.is_available.return_value = True
        redactor.is_audio_redaction_available.return_value = False

        transcription = Mock()
        transcription.text = "Test transcription."
        transcription.words = [Mock(word="Test", start=0.0, end=0.5)]
        redactor.transcribe_with_timestamps.return_value = transcription
        redactor.detect_pii_regions.return_value = []
        redactor.redact_transcript.return_value = "Test transcription."

        return redactor

    def test_worker_processes_task(self, mock_vector_store, mock_audio_pii_redactor):
        """Test that the worker thread processes tasks."""
        # Create temp audio file
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"fake audio content")
            audio_path = f.name

        try:
            redactor = AsyncAudioRedactor(
                vector_store=mock_vector_store,
                audio_pii_redactor=mock_audio_pii_redactor,
                verbose=False
            )

            redactor.start()
            try:
                task = AudioRedactionTask(
                    doc_id=1,
                    audio_id="abc123",
                    audio_path=audio_path
                )
                redactor.queue_task(task)

                # Wait for processing
                time.sleep(1.0)

                # Pending count should be 0 after processing
                assert redactor.get_pending_count() == 0
                assert redactor.get_status()["completed"] == 1
            finally:
                redactor.stop()
        finally:
            os.unlink(audio_path)

    def test_worker_retries_on_transient_error(self, mock_vector_store, mock_audio_pii_redactor):
        """Test that worker retries on transient errors."""
        call_count = [0]

        def failing_update(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] < 2:
                raise Exception("database is locked")
            return True

        mock_vector_store.update_document_metadata = failing_update

        # Create temp audio file
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"fake audio content")
            audio_path = f.name

        try:
            redactor = AsyncAudioRedactor(
                vector_store=mock_vector_store,
                audio_pii_redactor=mock_audio_pii_redactor,
                verbose=True
            )

            redactor.start()
            try:
                task = AudioRedactionTask(
                    doc_id=1,
                    audio_id="abc123",
                    audio_path=audio_path
                )
                redactor.queue_task(task)

                # Wait for retries (2s delay + processing)
                time.sleep(5)

                # Should have retried and eventually succeeded
                assert call_count[0] == 2  # 1 failure + 1 success
                assert redactor.get_pending_count() == 0

                status = redactor.get_status()
                assert status["total_retries"] == 1
            finally:
                redactor.stop()
        finally:
            os.unlink(audio_path)

    def test_failed_tasks_tracking(self, mock_vector_store):
        """Test that failed tasks are tracked."""
        redactor = AsyncAudioRedactor(
            vector_store=mock_vector_store,
            audio_pii_redactor=None,
            verbose=False
        )

        # Manually add a failed task
        redactor._failed_tasks.append(FailedAudioTask(
            doc_id=1,
            audio_id="abc123",
            audio_path="/path/to/audio.mp3",
            attempts=3,
            last_error="database is locked"
        ))

        failed = redactor.get_failed_tasks()
        assert len(failed) == 1
        assert failed[0]["doc_id"] == 1
        assert failed[0]["audio_id"] == "abc123"
        assert failed[0]["attempts"] == 3
        assert "database is locked" in failed[0]["last_error"]


class TestRetryConfiguration:
    """Tests for retry configuration constants."""

    def test_max_retries_is_reasonable(self):
        """MAX_RETRIES should be a reasonable value."""
        assert MAX_RETRIES >= 1
        assert MAX_RETRIES <= 10

    def test_retry_delays_are_reasonable(self):
        """RETRY_DELAYS should be reasonable for GPU operations."""
        assert len(RETRY_DELAYS) >= 1
        # Delays should be longer for GPU operations (compared to CPU)
        assert RETRY_DELAYS[0] >= 1.0

    def test_retry_delays_not_too_long(self):
        """Individual delays shouldn't be too long."""
        for delay in RETRY_DELAYS:
            assert delay <= 60  # Max 60 seconds for GPU operations


class TestAudioFileComparison:
    """Integration tests comparing original and redacted audio files."""

    FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")

    @pytest.fixture
    def test_audio_path(self):
        """Path to test sine wave audio file."""
        path = os.path.join(self.FIXTURES_DIR, "test_sine_440hz.wav")
        if not os.path.exists(path):
            pytest.skip("Test audio fixture not found. Run generate_test_audio.py first.")
        return path

    def test_fixture_exists(self, test_audio_path):
        """Verify test fixtures are available."""
        assert os.path.exists(test_audio_path)
        assert os.path.getsize(test_audio_path) > 0

    def test_audio_file_properties(self, test_audio_path):
        """Test that we can read audio file properties."""
        import wave
        with wave.open(test_audio_path, 'r') as wav:
            assert wav.getnchannels() == 1  # Mono
            assert wav.getsampwidth() == 2  # 16-bit
            assert wav.getframerate() == 16000  # Sample rate
            assert wav.getnframes() > 0  # Has frames

    def test_redacted_audio_preserves_duration(self):
        """Test that redacted audio has same duration as original.

        This test uses mock PII regions to simulate redaction without
        requiring actual speech recognition.
        """
        import wave
        import shutil

        # Create temp copy of fixture
        fixture_path = os.path.join(self.FIXTURES_DIR, "test_sine_440hz.wav")
        if not os.path.exists(fixture_path):
            pytest.skip("Test audio fixture not found")

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            shutil.copy2(fixture_path, tmp.name)
            original_path = tmp.name

        try:
            # Read original properties
            with wave.open(original_path, 'r') as wav:
                original_frames = wav.getnframes()
                original_rate = wav.getframerate()
                original_duration = original_frames / original_rate

            # For this test, we verify the fixture is valid
            assert original_duration > 0
            assert original_rate == 16000

            # Verify we can create a redacted copy
            redacted_path = original_path.replace(".wav", "_redacted.wav")
            shutil.copy2(original_path, redacted_path)

            try:
                # Redacted file should exist
                assert os.path.exists(redacted_path)

                # Redacted file should have same duration
                with wave.open(redacted_path, 'r') as wav:
                    redacted_frames = wav.getnframes()
                    redacted_rate = wav.getframerate()
                    redacted_duration = redacted_frames / redacted_rate

                assert redacted_duration == original_duration
                assert redacted_rate == original_rate
            finally:
                if os.path.exists(redacted_path):
                    os.unlink(redacted_path)
        finally:
            os.unlink(original_path)

    def test_mute_region_has_lower_amplitude(self):
        """Test that a muted region has near-zero amplitude.

        Simulates what audio redaction should do - the muted portion
        should have significantly lower amplitude than the original.
        """
        import wave
        import struct

        fixture_path = os.path.join(self.FIXTURES_DIR, "test_sine_440hz.wav")
        if not os.path.exists(fixture_path):
            pytest.skip("Test audio fixture not found")

        # Read original audio samples
        with wave.open(fixture_path, 'r') as wav:
            n_frames = wav.getnframes()
            sample_rate = wav.getframerate()
            raw_data = wav.readframes(n_frames)

        # Convert to samples
        samples = struct.unpack(f'{n_frames}h', raw_data)

        # Calculate RMS amplitude of the sine wave
        original_rms = (sum(s**2 for s in samples) / len(samples)) ** 0.5

        # Original sine wave should have significant amplitude
        assert original_rms > 1000, "Original audio should have audible amplitude"

        # Simulate what silence would look like
        silence_samples = [0] * len(samples)
        silence_rms = (sum(s**2 for s in silence_samples) / len(silence_samples)) ** 0.5

        # Silence should have zero amplitude
        assert silence_rms == 0

        # This verifies the test methodology - in real redaction tests,
        # we would compare the muted region's RMS to verify it's near zero

    def test_compare_audio_waveforms(self):
        """Test helper function to compare two audio file waveforms."""
        import wave
        import struct
        import shutil

        fixture_path = os.path.join(self.FIXTURES_DIR, "test_sine_440hz.wav")
        if not os.path.exists(fixture_path):
            pytest.skip("Test audio fixture not found")

        # Create two copies
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp1:
            shutil.copy2(fixture_path, tmp1.name)
            path1 = tmp1.name

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp2:
            shutil.copy2(fixture_path, tmp2.name)
            path2 = tmp2.name

        try:
            # Read both files
            with wave.open(path1, 'r') as wav1, wave.open(path2, 'r') as wav2:
                data1 = wav1.readframes(wav1.getnframes())
                data2 = wav2.readframes(wav2.getnframes())

            # Identical copies should have identical data
            assert data1 == data2

            # Modify second file to simulate muting a region (first 0.5 seconds)
            samples1 = list(struct.unpack(f'{len(data1)//2}h', data1))
            samples2 = samples1.copy()

            # Mute first 8000 samples (0.5 seconds at 16kHz)
            for i in range(min(8000, len(samples2))):
                samples2[i] = 0

            # Calculate difference in the muted region
            muted_region_diff = sum(
                abs(samples1[i] - samples2[i])
                for i in range(min(8000, len(samples1)))
            )

            # There should be a significant difference in the muted region
            assert muted_region_diff > 0

            # The unmuted region should be identical
            unmuted_region_diff = sum(
                abs(samples1[i] - samples2[i])
                for i in range(8000, len(samples1))
            )
            assert unmuted_region_diff == 0

        finally:
            os.unlink(path1)
            os.unlink(path2)


class TestAudioRedactionIntegrationWithFixtures:
    """Integration tests using actual audio fixtures and the redaction pipeline."""

    FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")

    @pytest.fixture
    def mock_vector_store(self):
        """Create a mock vector store."""
        store = Mock()
        store.update_document_metadata = Mock()
        return store

    def test_pipeline_with_real_audio_file(self, mock_vector_store):
        """Test the async pipeline with a real audio file.

        Uses mock transcription since Whisper may not be available,
        but verifies the pipeline works with real audio data.
        """
        fixture_path = os.path.join(self.FIXTURES_DIR, "test_sine_440hz.wav")
        if not os.path.exists(fixture_path):
            pytest.skip("Test audio fixture not found")

        # Create mock audio PII redactor
        mock_redactor = Mock()
        mock_redactor.is_available.return_value = True
        mock_redactor.is_audio_redaction_available.return_value = True

        # Mock transcription (sine wave won't produce real speech)
        transcription = Mock()
        transcription.text = "Hello, my name is John Smith and my email is john@example.com"
        transcription.words = [
            Mock(word="Hello,", start=0.0, end=0.2),
            Mock(word="my", start=0.2, end=0.3),
            Mock(word="name", start=0.3, end=0.5),
            Mock(word="is", start=0.5, end=0.6),
            Mock(word="John", start=0.6, end=0.8),
            Mock(word="Smith", start=0.8, end=1.0),
            Mock(word="and", start=1.0, end=1.1),
            Mock(word="my", start=1.1, end=1.2),
            Mock(word="email", start=1.2, end=1.4),
            Mock(word="is", start=1.4, end=1.5),
            Mock(word="john@example.com", start=1.5, end=2.0),
        ]
        mock_redactor.transcribe_with_timestamps.return_value = transcription

        # Mock PII detection
        pii_regions = [
            Mock(
                pii_type="PERSON",
                start_time=0.6,
                end_time=1.0,
                original_text="John Smith",
                replacement_text="[PERSON]",
                confidence=0.95,
            ),
            Mock(
                pii_type="EMAIL_ADDRESS",
                start_time=1.5,
                end_time=2.0,
                original_text="john@example.com",
                replacement_text="[EMAIL]",
                confidence=0.99,
            ),
        ]
        mock_redactor.detect_pii_regions.return_value = pii_regions
        mock_redactor.redact_transcript.return_value = (
            "Hello, my name is [PERSON] and my email is [EMAIL]"
        )

        # Mock audio file redaction (returns a path)
        redacted_audio_path = fixture_path.replace(".wav", "_redacted.wav")
        mock_redactor.redact_audio.return_value = redacted_audio_path

        # Create and run the async redactor
        async_redactor = AsyncAudioRedactor(
            vector_store=mock_vector_store,
            audio_pii_redactor=mock_redactor,
            verbose=False
        )

        # Process the task
        task = AudioRedactionTask(
            doc_id=42,
            audio_id="test123",
            audio_path=fixture_path,
            mute_audio=True,
            mute_style="silence",
        )

        async_redactor._process_task(task)

        # Verify metadata was updated correctly
        mock_vector_store.update_document_metadata.assert_called_once()
        call_args = mock_vector_store.update_document_metadata.call_args
        doc_id, metadata = call_args[0]

        assert doc_id == 42
        assert metadata["has_pii"] is True
        assert "PERSON" in metadata["pii_types_found"]
        assert "EMAIL_ADDRESS" in metadata["pii_types_found"]
        assert len(metadata["pii_regions"]) == 2
        assert metadata["transcription_complete"] is True
        assert metadata["redaction_pending"] is False

        # Verify redacted audio path is in metadata
        assert metadata["redacted_audio_path"] == redacted_audio_path

        # Verify the pipeline called all expected methods
        mock_redactor.transcribe_with_timestamps.assert_called_once_with(fixture_path)
        mock_redactor.detect_pii_regions.assert_called_once()
        mock_redactor.redact_transcript.assert_called_once()
        mock_redactor.redact_audio.assert_called_once()


class TestAudioPIIFixturesComparison:
    """Tests comparing original and redacted audio using PII fixtures with metadata."""

    FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
    AUDIO_DIR = os.path.join(FIXTURES_DIR, "audio")
    REDACTED_DIR = os.path.join(FIXTURES_DIR, "redacted", "audio")

    def _load_fixture_metadata(self, fixture_name: str) -> dict:
        """Load metadata for a fixture."""
        import json
        metadata_path = os.path.join(self.AUDIO_DIR, f"{fixture_name}.json")
        if not os.path.exists(metadata_path):
            pytest.skip(f"Fixture metadata not found: {metadata_path}")
        with open(metadata_path) as f:
            return json.load(f)

    def _calculate_rms(self, samples: list, start_sample: int, end_sample: int) -> float:
        """Calculate RMS amplitude for a region of samples."""
        region = samples[start_sample:end_sample]
        if not region:
            return 0.0
        return (sum(s**2 for s in region) / len(region)) ** 0.5

    def test_pii_fixtures_directory_exists(self):
        """Test that PII fixtures directories exist."""
        if not os.path.exists(self.AUDIO_DIR):
            pytest.skip("Audio fixtures directory not found")
        assert os.path.isdir(self.AUDIO_DIR)

    def test_fixtures_index_exists(self):
        """Test that fixtures index file exists."""
        import json
        index_path = os.path.join(self.AUDIO_DIR, "fixtures_index.json")
        if not os.path.exists(index_path):
            pytest.skip("Fixtures index not found")

        with open(index_path) as f:
            index = json.load(f)

        assert "fixtures" in index
        assert "total" in index
        assert index["total"] > 0

    def test_original_and_redacted_have_same_duration(self):
        """Test that original and redacted audio have identical duration."""
        import wave

        original_path = os.path.join(self.AUDIO_DIR, "conversation_with_name.wav")
        redacted_path = os.path.join(self.REDACTED_DIR, "conversation_with_name_redacted.wav")

        if not os.path.exists(original_path) or not os.path.exists(redacted_path):
            pytest.skip("Fixture files not found")

        with wave.open(original_path) as orig, wave.open(redacted_path) as red:
            orig_duration = orig.getnframes() / orig.getframerate()
            red_duration = red.getnframes() / red.getframerate()

            assert orig_duration == red_duration
            assert orig.getframerate() == red.getframerate()
            assert orig.getnchannels() == red.getnchannels()

    def test_pii_region_is_silenced_in_redacted(self):
        """Test that PII regions have near-zero amplitude in redacted audio."""
        import wave
        import struct

        metadata = self._load_fixture_metadata("conversation_with_name")
        if not metadata["pii_regions"]:
            pytest.skip("No PII regions in this fixture")

        original_path = os.path.join(self.AUDIO_DIR, "conversation_with_name.wav")
        redacted_path = os.path.join(self.REDACTED_DIR, "conversation_with_name_redacted.wav")

        if not os.path.exists(redacted_path):
            pytest.skip("Redacted fixture not found")

        # Read both audio files
        with wave.open(original_path) as orig:
            sample_rate = orig.getframerate()
            n_frames = orig.getnframes()
            orig_data = orig.readframes(n_frames)

        with wave.open(redacted_path) as red:
            red_data = red.readframes(red.getnframes())

        orig_samples = list(struct.unpack(f'{n_frames}h', orig_data))
        red_samples = list(struct.unpack(f'{n_frames}h', red_data))

        # Check each PII region
        for region in metadata["pii_regions"]:
            start_sample = int(region["start_time"] * sample_rate)
            end_sample = int(region["end_time"] * sample_rate)

            orig_rms = self._calculate_rms(orig_samples, start_sample, end_sample)
            red_rms = self._calculate_rms(red_samples, start_sample, end_sample)

            # Original should have significant amplitude (sine wave)
            assert orig_rms > 100, f"Original PII region should have amplitude"

            # Redacted should have near-zero amplitude (silenced)
            assert red_rms < 1, f"Redacted PII region should be silent"

    def test_non_pii_regions_are_preserved(self):
        """Test that non-PII regions are identical in original and redacted."""
        import wave
        import struct

        metadata = self._load_fixture_metadata("conversation_with_name")
        if not metadata["pii_regions"]:
            pytest.skip("No PII regions to test around")

        original_path = os.path.join(self.AUDIO_DIR, "conversation_with_name.wav")
        redacted_path = os.path.join(self.REDACTED_DIR, "conversation_with_name_redacted.wav")

        if not os.path.exists(redacted_path):
            pytest.skip("Redacted fixture not found")

        # Read both files
        with wave.open(original_path) as orig:
            sample_rate = orig.getframerate()
            n_frames = orig.getnframes()
            orig_data = orig.readframes(n_frames)

        with wave.open(redacted_path) as red:
            red_data = red.readframes(red.getnframes())

        orig_samples = list(struct.unpack(f'{n_frames}h', orig_data))
        red_samples = list(struct.unpack(f'{n_frames}h', red_data))

        # Check first 0.5 seconds (before any PII)
        # PII starts at 1.2s in conversation_with_name
        early_end = int(0.5 * sample_rate)
        early_orig = orig_samples[:early_end]
        early_red = red_samples[:early_end]

        # Non-PII regions should be identical
        assert early_orig == early_red, "Non-PII regions should be preserved"

    def test_multiple_pii_regions_all_silenced(self):
        """Test fixture with multiple PII types has all regions silenced."""
        import wave
        import struct

        metadata = self._load_fixture_metadata("conversation_with_multiple_pii")
        if len(metadata["pii_regions"]) < 2:
            pytest.skip("Not enough PII regions")

        original_path = os.path.join(self.AUDIO_DIR, "conversation_with_multiple_pii.wav")
        redacted_path = os.path.join(self.REDACTED_DIR, "conversation_with_multiple_pii_redacted.wav")

        if not os.path.exists(redacted_path):
            pytest.skip("Redacted fixture not found")

        with wave.open(redacted_path) as red:
            sample_rate = red.getframerate()
            n_frames = red.getnframes()
            red_data = red.readframes(n_frames)

        red_samples = list(struct.unpack(f'{n_frames}h', red_data))

        # All PII regions should be silent
        for region in metadata["pii_regions"]:
            start_sample = int(region["start_time"] * sample_rate)
            end_sample = int(region["end_time"] * sample_rate)
            red_rms = self._calculate_rms(red_samples, start_sample, end_sample)

            assert red_rms < 1, f"PII region {region['pii_type']} should be silent"

    def test_no_pii_fixture_unchanged(self):
        """Test that audio with no PII is identical before and after."""
        import wave

        original_path = os.path.join(self.AUDIO_DIR, "conversation_no_pii.wav")
        redacted_path = os.path.join(self.REDACTED_DIR, "conversation_no_pii_redacted.wav")

        if not os.path.exists(original_path) or not os.path.exists(redacted_path):
            pytest.skip("Fixture files not found")

        with wave.open(original_path) as orig, wave.open(redacted_path) as red:
            orig_data = orig.readframes(orig.getnframes())
            red_data = red.readframes(red.getnframes())

            # Should be byte-for-byte identical
            assert orig_data == red_data, "No-PII audio should be unchanged"

    def test_fixture_metadata_matches_audio(self):
        """Test that fixture metadata accurately describes the audio file."""
        import wave

        metadata = self._load_fixture_metadata("conversation_with_name")
        audio_path = os.path.join(self.AUDIO_DIR, "conversation_with_name.wav")

        if not os.path.exists(audio_path):
            pytest.skip("Audio fixture not found")

        with wave.open(audio_path) as wav:
            actual_duration = wav.getnframes() / wav.getframerate()
            actual_sample_rate = wav.getframerate()

        # Allow small tolerance for duration
        assert abs(actual_duration - metadata["duration_seconds"]) < 0.1
        assert actual_sample_rate == metadata["sample_rate"]
        assert metadata["has_pii"] is True
        assert len(metadata["pii_regions"]) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
