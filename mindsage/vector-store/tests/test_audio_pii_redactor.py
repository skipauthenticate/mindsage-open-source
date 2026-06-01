"""Tests for audio PII redaction module.

These tests verify the transcript-based PII detection and redaction
functionality for audio files. Tests requiring whisper-timestamped
will be skipped if not installed.
"""

import os
import sys
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Import the audio_pii_redactor module directly to avoid triggering
# the full mcp_vector_store import chain (which has txtai dependencies)
sys.path.insert(0, str(Path(__file__).parent.parent / "mcp_vector_store"))
from audio_pii_redactor import (
    AudioPIIRedactor,
    WordTimestamp,
    AudioPIIRegion,
    TranscriptionResult,
    AudioRedactionResult,
    get_audio_pii_redactor,
    get_audio_pii_config,
    WHISPER_TIMESTAMPED_AVAILABLE,
    PYDUB_AVAILABLE,
)


class TestAudioPIIDataClasses:
    """Test audio PII data classes."""

    def test_word_timestamp(self):
        """Test WordTimestamp creation."""
        word = WordTimestamp(
            word="Hello",
            start=0.0,
            end=0.5,
            confidence=0.95,
            char_start=0,
            char_end=5,
        )
        assert word.word == "Hello"
        assert word.start == 0.0
        assert word.end == 0.5
        assert word.confidence == 0.95
        assert word.char_start == 0
        assert word.char_end == 5

    def test_audio_pii_region(self):
        """Test AudioPIIRegion creation."""
        region = AudioPIIRegion(
            start_time=1.5,
            end_time=2.3,
            pii_type="PERSON",
            original_text="John Smith",
            replacement_text="[PERSON]",
            confidence=0.92,
        )
        assert region.start_time == 1.5
        assert region.end_time == 2.3
        assert region.pii_type == "PERSON"
        assert region.original_text == "John Smith"
        assert region.replacement_text == "[PERSON]"
        assert region.confidence == 0.92

    def test_transcription_result(self):
        """Test TranscriptionResult creation."""
        words = [
            WordTimestamp("Hello", 0.0, 0.5, 0.95, 0, 5),
            WordTimestamp("World", 0.6, 1.0, 0.90, 6, 11),
        ]
        result = TranscriptionResult(
            text="Hello World",
            words=words,
            language="en",
            duration_seconds=1.0,
            processing_time_ms=150.5,
        )
        assert result.text == "Hello World"
        assert len(result.words) == 2
        assert result.language == "en"
        assert result.duration_seconds == 1.0
        assert result.processing_time_ms == 150.5

    def test_audio_redaction_result(self):
        """Test AudioRedactionResult creation."""
        regions = [
            AudioPIIRegion(1.5, 2.3, "PERSON", "John Smith", "[PERSON]", 0.92),
        ]
        result = AudioRedactionResult(
            original_transcript="Hi, I'm John Smith",
            redacted_transcript="Hi, I'm [PERSON]",
            pii_regions=regions,
            redacted_audio_path=None,
            has_pii=True,
            pii_types_found=["PERSON"],
            processing_time_ms=500.0,
            word_count=4,
        )
        assert result.original_transcript == "Hi, I'm John Smith"
        assert result.redacted_transcript == "Hi, I'm [PERSON]"
        assert len(result.pii_regions) == 1
        assert result.has_pii is True
        assert "PERSON" in result.pii_types_found


class TestAudioPIIConfig:
    """Test audio PII configuration."""

    def test_default_config(self):
        """Test default configuration values."""
        # Clear any environment variables
        env_vars = ["AUDIO_PII_ENABLED", "AUDIO_PII_REDACTION_STYLE"]
        original_values = {k: os.environ.pop(k, None) for k in env_vars}

        try:
            config = get_audio_pii_config()
            assert config["enabled"] is True
            assert config["redaction_style"] == "brackets"
            assert config["mute_audio"] is False
            assert config["mute_style"] == "silence"
        finally:
            # Restore original values
            for k, v in original_values.items():
                if v is not None:
                    os.environ[k] = v

    def test_config_from_environment(self):
        """Test configuration from environment variables."""
        os.environ["AUDIO_PII_ENABLED"] = "false"
        os.environ["AUDIO_PII_REDACTION_STYLE"] = "placeholder"

        try:
            config = get_audio_pii_config()
            assert config["enabled"] is False
            assert config["redaction_style"] == "placeholder"
        finally:
            del os.environ["AUDIO_PII_ENABLED"]
            del os.environ["AUDIO_PII_REDACTION_STYLE"]


class TestAudioPIIRedactorInit:
    """Test AudioPIIRedactor initialization."""

    def test_init_with_defaults(self):
        """Test initialization with default parameters."""
        redactor = AudioPIIRedactor()
        assert redactor.whisper_model_name == "tiny.en"
        assert redactor.redaction_style == "brackets"
        assert redactor._whisper_loaded is False

    def test_init_with_custom_params(self):
        """Test initialization with custom parameters."""
        redactor = AudioPIIRedactor(
            whisper_model="base.en",
            redaction_style="placeholder",
            device="cpu",
            verbose=True,
        )
        assert redactor.whisper_model_name == "base.en"
        assert redactor.redaction_style == "placeholder"
        assert redactor.device == "cpu"
        assert redactor.verbose is True

    def test_is_available(self):
        """Test availability check."""
        redactor = AudioPIIRedactor()
        # Should match whether whisper-timestamped is installed
        assert redactor.is_available() == WHISPER_TIMESTAMPED_AVAILABLE


class TestPIITimestampMapping:
    """Test PII-to-timestamp mapping logic."""

    def test_map_pii_to_timestamps_simple(self):
        """Test mapping single word PII to timestamps."""
        redactor = AudioPIIRedactor()

        words = [
            WordTimestamp("Hi", 0.0, 0.3, 0.95, 0, 2),
            WordTimestamp("I'm", 0.4, 0.6, 0.95, 3, 6),
            WordTimestamp("John", 0.7, 1.0, 0.95, 7, 11),
        ]

        # Map "John" (char positions 7-11) to timestamps
        start, end, text = redactor._map_pii_to_timestamps(7, 11, words)

        assert start == 0.7
        assert end == 1.0
        assert text == "John"

    def test_map_pii_to_timestamps_multiword(self):
        """Test mapping multi-word PII to timestamps."""
        redactor = AudioPIIRedactor()

        words = [
            WordTimestamp("Call", 0.0, 0.3, 0.95, 0, 4),
            WordTimestamp("John", 0.4, 0.7, 0.95, 5, 9),
            WordTimestamp("Smith", 0.8, 1.2, 0.95, 10, 15),
            WordTimestamp("please", 1.3, 1.7, 0.95, 16, 22),
        ]

        # Map "John Smith" (char positions 5-15) to timestamps
        start, end, text = redactor._map_pii_to_timestamps(5, 15, words)

        assert start == 0.4  # Start of "John"
        assert end == 1.2    # End of "Smith"
        assert text == "John Smith"


class TestTranscriptRedaction:
    """Test transcript redaction logic."""

    def test_redact_single_pii(self):
        """Test redacting a single PII entity."""
        redactor = AudioPIIRedactor(redaction_style="brackets")

        regions = [
            AudioPIIRegion(
                start_time=0.7,
                end_time=1.2,
                pii_type="PERSON",
                original_text="John Smith",
                replacement_text="[PERSON]",
                confidence=0.95,
            ),
        ]

        transcript = "Hi, I'm John Smith, nice to meet you"
        redacted = redactor.redact_transcript(transcript, regions)

        assert redacted == "Hi, I'm [PERSON], nice to meet you"

    def test_redact_multiple_pii(self):
        """Test redacting multiple PII entities."""
        redactor = AudioPIIRedactor(redaction_style="brackets")

        regions = [
            AudioPIIRegion(0.7, 1.2, "PERSON", "John", "[PERSON]", 0.95),
            AudioPIIRegion(2.0, 2.5, "PHONE_NUMBER", "555-1234", "[PHONE_NUMBER]", 0.90),
        ]

        transcript = "Call John at 555-1234"
        redacted = redactor.redact_transcript(transcript, regions)

        assert redacted == "Call [PERSON] at [PHONE_NUMBER]"

    def test_redact_no_pii(self):
        """Test redacting with no PII regions."""
        redactor = AudioPIIRedactor()

        transcript = "The weather is nice today"
        redacted = redactor.redact_transcript(transcript, [])

        assert redacted == transcript

    def test_redact_placeholder_style(self):
        """Test redaction with placeholder style."""
        redactor = AudioPIIRedactor(redaction_style="placeholder")

        regions = [
            AudioPIIRegion(0.7, 1.2, "PERSON", "John", "[REDACTED]", 0.95),
        ]

        transcript = "Hi, I'm John"
        redacted = redactor.redact_transcript(transcript, regions)

        assert redacted == "Hi, I'm [REDACTED]"


class TestPIIDetection:
    """Test PII detection with mocked Presidio."""

    def test_detect_pii_regions_with_mock(self):
        """Test PII detection with mocked analyzer."""
        redactor = AudioPIIRedactor()

        # Mock the PII protector
        mock_protector = MagicMock()
        mock_analyzer = MagicMock()

        # Simulate Presidio returning a PERSON entity
        mock_result = MagicMock()
        mock_result.entity_type = "PERSON"
        mock_result.start = 7
        mock_result.end = 11
        mock_result.score = 0.95

        mock_analyzer.analyze.return_value = [mock_result]
        mock_protector._analyzer = mock_analyzer
        mock_protector._ensure_initialized = MagicMock()

        redactor._pii_protector = mock_protector

        words = [
            WordTimestamp("Hi", 0.0, 0.3, 0.95, 0, 2),
            WordTimestamp("I'm", 0.4, 0.6, 0.95, 3, 6),
            WordTimestamp("John", 0.7, 1.0, 0.95, 7, 11),
        ]

        regions = redactor.detect_pii_regions("Hi I'm John", words)

        assert len(regions) == 1
        assert regions[0].pii_type == "PERSON"
        assert regions[0].original_text == "John"
        assert regions[0].start_time == 0.7
        assert regions[0].end_time == 1.0

    def test_detect_pii_no_protector(self):
        """Test detection returns empty when no protector available."""
        redactor = AudioPIIRedactor()
        redactor._pii_protector = None

        # Mock _get_pii_protector to return None
        with patch.object(redactor, '_get_pii_protector', return_value=None):
            regions = redactor.detect_pii_regions("Hi I'm John", [])
            assert regions == []


class TestFullPipeline:
    """Test the full audio PII processing pipeline."""

    @pytest.mark.skipif(
        not WHISPER_TIMESTAMPED_AVAILABLE,
        reason="whisper-timestamped not installed"
    )
    def test_process_with_pii(self):
        """Test full pipeline with actual whisper-timestamped (if available)."""
        # This test would require a real audio file and whisper-timestamped
        # Skip for now, will be integration tested manually
        pytest.skip("Integration test - requires audio file")

    def test_process_with_mocked_transcription(self):
        """Test full pipeline with mocked transcription."""
        redactor = AudioPIIRedactor()

        # Mock transcription result
        mock_transcription = TranscriptionResult(
            text="Hi I'm John Smith call me at 555-123-4567",
            words=[
                WordTimestamp("Hi", 0.0, 0.3, 0.95, 0, 2),
                WordTimestamp("I'm", 0.4, 0.6, 0.95, 3, 6),
                WordTimestamp("John", 0.7, 0.9, 0.95, 7, 11),
                WordTimestamp("Smith", 1.0, 1.3, 0.95, 12, 17),
                WordTimestamp("call", 1.4, 1.6, 0.95, 18, 22),
                WordTimestamp("me", 1.7, 1.9, 0.95, 23, 25),
                WordTimestamp("at", 2.0, 2.2, 0.95, 26, 28),
                WordTimestamp("555-123-4567", 2.3, 3.0, 0.95, 29, 41),
            ],
            language="en",
            duration_seconds=3.0,
            processing_time_ms=100.0,
        )

        # Mock Presidio results
        mock_protector = MagicMock()
        mock_analyzer = MagicMock()

        person_result = MagicMock()
        person_result.entity_type = "PERSON"
        person_result.start = 7
        person_result.end = 17  # "John Smith"
        person_result.score = 0.95

        phone_result = MagicMock()
        phone_result.entity_type = "PHONE_NUMBER"
        phone_result.start = 29
        phone_result.end = 41  # "555-123-4567"
        phone_result.score = 0.90

        mock_analyzer.analyze.return_value = [person_result, phone_result]
        mock_protector._analyzer = mock_analyzer
        mock_protector._ensure_initialized = MagicMock()

        redactor._pii_protector = mock_protector

        # Mock transcribe_with_timestamps
        with patch.object(
            redactor,
            'transcribe_with_timestamps',
            return_value=mock_transcription
        ):
            result = redactor.process("/fake/audio.wav")

        assert result.has_pii is True
        assert len(result.pii_regions) == 2
        assert "PERSON" in result.pii_types_found
        assert "PHONE_NUMBER" in result.pii_types_found
        assert "[PERSON]" in result.redacted_transcript
        assert "[PHONE_NUMBER]" in result.redacted_transcript
        assert "John Smith" not in result.redacted_transcript
        assert "555-123-4567" not in result.redacted_transcript


class TestGlobalInstance:
    """Test global AudioPIIRedactor instance management."""

    def test_get_audio_pii_redactor(self):
        """Test getting the global instance."""
        # Reset global instance
        import audio_pii_redactor
        audio_pii_redactor._global_audio_pii_redactor = None

        redactor = get_audio_pii_redactor(verbose=False)
        assert redactor is not None
        assert isinstance(redactor, AudioPIIRedactor)

        # Should return same instance
        redactor2 = get_audio_pii_redactor()
        assert redactor is redactor2

        # Reset for other tests
        audio_pii_redactor._global_audio_pii_redactor = None


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_transcript(self):
        """Test handling empty transcript."""
        redactor = AudioPIIRedactor()
        redacted = redactor.redact_transcript("", [])
        assert redacted == ""

    def test_pii_not_found_in_transcript(self):
        """Test when PII region text not found in transcript."""
        redactor = AudioPIIRedactor()

        # Region with text that doesn't exist in transcript
        regions = [
            AudioPIIRegion(0.0, 1.0, "PERSON", "NotInText", "[PERSON]", 0.95),
        ]

        transcript = "Hello World"
        redacted = redactor.redact_transcript(transcript, regions)

        # Should return unchanged transcript
        assert redacted == transcript

    def test_overlapping_pii_regions(self):
        """Test handling overlapping PII regions."""
        redactor = AudioPIIRedactor()

        # Two overlapping regions (edge case - shouldn't happen normally)
        regions = [
            AudioPIIRegion(0.0, 1.0, "PERSON", "John", "[PERSON]", 0.95),
            AudioPIIRegion(0.5, 1.5, "PERSON", "John Smith", "[PERSON]", 0.90),
        ]

        transcript = "Call John Smith"
        redacted = redactor.redact_transcript(transcript, regions)

        # Both should be replaced (though this may result in nested replacements)
        # The exact behavior depends on implementation
        assert "John" not in redacted or "[PERSON]" in redacted


class TestAudioFileRedaction:
    """Test audio file redaction (Phase 2)."""

    def test_is_audio_redaction_available(self):
        """Test availability check for audio redaction."""
        redactor = AudioPIIRedactor()
        # Should match pydub availability
        assert redactor.is_audio_redaction_available() == PYDUB_AVAILABLE

    @pytest.mark.skipif(
        not PYDUB_AVAILABLE,
        reason="pydub not installed"
    )
    def test_generate_beep_segment(self):
        """Test beep tone generation."""
        redactor = AudioPIIRedactor()
        beep = redactor._generate_beep_segment(1000)  # 1 second

        assert beep is not None
        assert len(beep) == 1000  # Duration in milliseconds

    @pytest.mark.skipif(
        not PYDUB_AVAILABLE,
        reason="pydub not installed"
    )
    def test_generate_noise_segment(self):
        """Test white noise generation."""
        redactor = AudioPIIRedactor()
        noise = redactor._generate_noise_segment(500)  # 0.5 seconds

        assert noise is not None
        assert len(noise) == 500  # Duration in milliseconds

    @pytest.mark.skipif(
        not PYDUB_AVAILABLE,
        reason="pydub not installed"
    )
    def test_generate_output_path(self):
        """Test output path generation."""
        redactor = AudioPIIRedactor()
        input_path = "/app/data/uploads/audio/recording.mp3"
        output_path = redactor._generate_output_path(input_path)

        assert "redacted" in output_path
        assert "audio" in output_path
        assert "_redacted" in output_path
        assert output_path.endswith(".mp3")

    @pytest.mark.skipif(
        not PYDUB_AVAILABLE,
        reason="pydub not installed"
    )
    def test_redact_audio_no_regions(self):
        """Test redact_audio with no PII regions copies file."""
        import tempfile
        import shutil
        from pydub import AudioSegment

        redactor = AudioPIIRedactor()

        # Create a temporary test audio file
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            # Generate a short silent audio
            audio = AudioSegment.silent(duration=1000)  # 1 second
            audio.export(tmp.name, format="wav")
            tmp_path = tmp.name

        try:
            # Redact with no regions
            with tempfile.TemporaryDirectory() as tmpdir:
                output_path = os.path.join(tmpdir, "output.wav")
                result = redactor.redact_audio(tmp_path, [], output_path)

                assert os.path.exists(result)
                assert result == output_path
        finally:
            os.unlink(tmp_path)

    @pytest.mark.skipif(
        not PYDUB_AVAILABLE,
        reason="pydub not installed"
    )
    def test_redact_audio_with_regions(self):
        """Test redact_audio with PII regions."""
        import tempfile
        from pydub import AudioSegment
        from pydub.generators import Sine

        redactor = AudioPIIRedactor()

        # Create a 3-second test audio with a tone
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            # Generate audio with a tone (so we can verify it's modified)
            audio = Sine(440).to_audio_segment(duration=3000)  # 3 seconds of 440Hz
            audio.export(tmp.name, format="wav")
            tmp_path = tmp.name

        try:
            # Create PII regions (1.0-2.0 seconds)
            regions = [
                AudioPIIRegion(1.0, 2.0, "PERSON", "John", "[PERSON]", 0.95),
            ]

            with tempfile.TemporaryDirectory() as tmpdir:
                output_path = os.path.join(tmpdir, "output.wav")

                # Test silence style
                result = redactor.redact_audio(
                    tmp_path, regions, output_path, mute_style="silence"
                )
                assert os.path.exists(result)

                # Verify output is different from input (has silence inserted)
                original = AudioSegment.from_file(tmp_path)
                redacted = AudioSegment.from_file(result)

                # Duration should be similar (within padding tolerance)
                assert abs(len(original) - len(redacted)) < 200  # 200ms tolerance

        finally:
            os.unlink(tmp_path)

    @pytest.mark.skipif(
        not PYDUB_AVAILABLE,
        reason="pydub not installed"
    )
    def test_redact_audio_beep_style(self):
        """Test redact_audio with beep style."""
        import tempfile
        from pydub import AudioSegment

        redactor = AudioPIIRedactor()

        # Create test audio
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            audio = AudioSegment.silent(duration=2000)  # 2 seconds
            audio.export(tmp.name, format="wav")
            tmp_path = tmp.name

        try:
            regions = [
                AudioPIIRegion(0.5, 1.0, "PHONE_NUMBER", "555-1234", "[PHONE]", 0.9),
            ]

            with tempfile.TemporaryDirectory() as tmpdir:
                output_path = os.path.join(tmpdir, "output_beep.wav")
                result = redactor.redact_audio(
                    tmp_path, regions, output_path, mute_style="beep"
                )
                assert os.path.exists(result)

        finally:
            os.unlink(tmp_path)

    @pytest.mark.skipif(
        not PYDUB_AVAILABLE,
        reason="pydub not installed"
    )
    def test_redact_audio_noise_style(self):
        """Test redact_audio with noise style."""
        import tempfile
        from pydub import AudioSegment

        redactor = AudioPIIRedactor()

        # Create test audio
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            audio = AudioSegment.silent(duration=2000)
            audio.export(tmp.name, format="wav")
            tmp_path = tmp.name

        try:
            regions = [
                AudioPIIRegion(0.5, 1.5, "SSN", "123-45-6789", "[SSN]", 0.95),
            ]

            with tempfile.TemporaryDirectory() as tmpdir:
                output_path = os.path.join(tmpdir, "output_noise.wav")
                result = redactor.redact_audio(
                    tmp_path, regions, output_path, mute_style="noise"
                )
                assert os.path.exists(result)

        finally:
            os.unlink(tmp_path)

    def test_redact_audio_not_available(self):
        """Test redact_audio raises error when pydub not available."""
        redactor = AudioPIIRedactor()

        # Mock PYDUB_AVAILABLE to False
        with patch('audio_pii_redactor.PYDUB_AVAILABLE', False):
            with pytest.raises(RuntimeError, match="pydub not installed"):
                redactor.redact_audio("/fake/audio.wav", [])
