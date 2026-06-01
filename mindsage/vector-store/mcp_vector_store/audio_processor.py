"""Audio processing for transcription and indexing.

Uses Whisper (via transformers) for speech-to-text transcription.
Integrates with ModelManager for GPU memory swapping on Jetson.

Default model: openai/whisper-tiny.en (~150MB disk, ~1GB VRAM)

PII Redaction (Phase 1):
    When AUDIO_PII_ENABLED=true, audio transcripts are processed with
    AudioPIIRedactor to produce both original and redacted versions:
    - original_transcript: Full text (for Explore tab viewing)
    - redacted_transcript: PII replaced with [TYPE] tags (for LLM/embeddings)
"""

import gc
import os
import time
from dataclasses import asdict
from typing import Optional, Dict, Any, List

from .model_manager import get_model_manager, ModelType


# Supported audio formats
AUDIO_EXTENSIONS = {'.wav', '.mp3', '.flac', '.ogg', '.m4a', '.wma', '.aac', '.webm'}

# Default model - tiny.en is fastest and fits Jetson well
DEFAULT_WHISPER_MODEL = "openai/whisper-tiny.en"


class AudioProcessor:
    """Transcribe audio files to text using Whisper.

    Designed for batch processing on Jetson Orin Nano.
    Uses ModelManager to swap GPU models (unloads embedding before loading Whisper).

    Usage:
        processor = AudioProcessor()
        result = processor.process("recording.wav")
        # result = {"text": "transcribed text...", "metadata": {...}}
    """

    def __init__(
        self,
        model_name: str = DEFAULT_WHISPER_MODEL,
        device: Optional[str] = None,
        verbose: bool = False
    ):
        self.model_name = model_name
        self.verbose = verbose
        self._pipeline = None
        self._is_loaded = False

        # Auto-detect device
        if device is None:
            try:
                import torch
                self.device = "cuda" if torch.cuda.is_available() else "cpu"
            except ImportError:
                self.device = "cpu"
        else:
            self.device = device

        # Register with ModelManager
        self._register_with_manager()

    def _register_with_manager(self):
        """Register this processor with the global ModelManager."""
        manager = get_model_manager()
        manager.register_transcription(self)

    def _load_model(self):
        """Load the Whisper pipeline.

        ModelManager handles pre-flight memory checks and circuit breaking.
        On GPU failure, falls back to CPU automatically.
        """
        if self._is_loaded:
            return

        if self.verbose:
            print(f"AudioProcessor: Loading {self.model_name} on {self.device}...")
            start = time.time()

        from transformers import pipeline

        try:
            self._pipeline = pipeline(
                "automatic-speech-recognition",
                model=self.model_name,
                device=0 if self.device == "cuda" else -1,
            )
            self._is_loaded = True
            if self.verbose:
                elapsed = time.time() - start
                print(f"AudioProcessor: Loaded on {self.device} in {elapsed:.1f}s")
        except Exception as e:
            if self.device == "cuda":
                print(f"AudioProcessor: GPU load failed ({e}), falling back to CPU...")
                self.device = "cpu"
                self._pipeline = pipeline(
                    "automatic-speech-recognition",
                    model=self.model_name,
                    device=-1,
                )
                self._is_loaded = True
                if self.verbose:
                    elapsed = time.time() - start
                    print(f"AudioProcessor: Loaded on CPU (fallback) in {elapsed:.1f}s")
            else:
                raise RuntimeError(
                    f"Failed to load Whisper on {self.device}: {e}"
                ) from e

    def _unload_model(self):
        """Unload the Whisper pipeline to free memory."""
        if not self._is_loaded:
            return

        if self.verbose:
            print("AudioProcessor: Unloading Whisper model...")

        del self._pipeline
        self._pipeline = None
        self._is_loaded = False
        gc.collect()

        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass

    def is_loaded(self) -> bool:
        return self._is_loaded

    @staticmethod
    def is_supported(file_path: str) -> bool:
        """Check if file is a supported audio format."""
        ext = os.path.splitext(file_path)[1].lower()
        return ext in AUDIO_EXTENSIONS

    @staticmethod
    def get_audio_metadata(file_path: str) -> Dict[str, Any]:
        """Extract audio metadata (duration, sample rate, channels)."""
        metadata: Dict[str, Any] = {
            "media_type": "audio",
            "format": os.path.splitext(file_path)[1].lower().lstrip('.'),
            "file_size_bytes": os.path.getsize(file_path),
        }

        try:
            import soundfile as sf
            info = sf.info(file_path)
            metadata["duration_seconds"] = round(info.duration, 2)
            metadata["sample_rate"] = info.samplerate
            metadata["channels"] = info.channels
        except Exception:
            # soundfile may not support all formats (e.g., mp3)
            # Fall back to trying librosa or just skip
            try:
                import librosa
                duration = librosa.get_duration(path=file_path)
                metadata["duration_seconds"] = round(duration, 2)
            except Exception:
                pass

        return metadata

    def transcribe(self, file_path: str, chunk_length_s: int = 30) -> str:
        """Transcribe an audio file to text.

        Uses ModelManager to ensure GPU is available (swaps out other models).

        Args:
            file_path: Path to audio file
            chunk_length_s: Chunk length for long audio files (seconds, 5-300)

        Returns:
            Transcribed text

        Raises:
            FileNotFoundError: If audio file doesn't exist
            RuntimeError: If transcription fails
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Audio file not found: {file_path}")

        if not 5 <= chunk_length_s <= 300:
            raise ValueError(f"chunk_length_s must be between 5 and 300, got {chunk_length_s}")

        manager = get_model_manager()

        with manager.require(ModelType.TRANSCRIPTION):
            if self.verbose:
                print(f"AudioProcessor: Transcribing {os.path.basename(file_path)}...")
                start = time.time()

            try:
                result = self._pipeline(
                    file_path,
                    chunk_length_s=chunk_length_s,
                    return_timestamps=False,
                )
            except Exception as e:
                raise RuntimeError(
                    f"Whisper transcription failed for {os.path.basename(file_path)}: {e}"
                ) from e

            text = result["text"].strip()

            if self.verbose:
                elapsed = time.time() - start
                print(f"AudioProcessor: Transcribed {len(text)} chars in {elapsed:.1f}s")

            return text

    def process(self, file_path: str) -> Dict[str, Any]:
        """Process an audio file: transcribe and extract metadata.

        Args:
            file_path: Path to audio file

        Returns:
            Dict with 'text' (transcription) and 'metadata' (audio info)
        """
        metadata = self.get_audio_metadata(file_path)
        text = self.transcribe(file_path)

        # Add source info
        metadata["original_filename"] = os.path.basename(file_path)
        metadata["transcription_model"] = self.model_name

        duration_str = ""
        if "duration_seconds" in metadata:
            mins, secs = divmod(int(metadata["duration_seconds"]), 60)
            duration_str = f" ({mins}:{secs:02d})"

        # Prefix transcription with context
        prefixed_text = f"[Audio transcription{duration_str}]\n\n{text}"

        return {
            "text": prefixed_text,
            "metadata": metadata,
        }

    def process_with_pii_redaction(
        self,
        file_path: str,
        redact_pii: bool = True,
    ) -> Dict[str, Any]:
        """Process audio with optional PII redaction.

        When PII redaction is enabled, uses AudioPIIRedactor with
        whisper-timestamped for word-level timestamps, allowing precise
        mapping of PII entities to audio segments.

        Returns both original and redacted transcripts:
        - original_transcript: For user viewing in Explore tab
        - redacted_transcript: For LLM context and embeddings (PII replaced)

        Args:
            file_path: Path to audio file
            redact_pii: Whether to detect and redact PII

        Returns:
            Dict with:
            - 'text': Redacted transcript (for embeddings/LLM)
            - 'metadata': Audio info plus PII fields:
                - original_transcript: Full text
                - redacted_transcript: PII replaced
                - has_pii: Boolean
                - pii_types_found: List of PII types
                - pii_regions: List of detected regions with timestamps
        """
        metadata = self.get_audio_metadata(file_path)
        metadata["original_filename"] = os.path.basename(file_path)
        metadata["transcription_model"] = self.model_name

        if not redact_pii:
            # Use standard processing without PII detection
            result = self.process(file_path)
            # Add PII fields with defaults
            result["metadata"]["original_transcript"] = result["text"]
            result["metadata"]["redacted_transcript"] = result["text"]
            result["metadata"]["has_pii"] = False
            result["metadata"]["pii_types_found"] = []
            result["metadata"]["pii_regions"] = []
            return result

        # Use AudioPIIRedactor for PII-aware transcription
        try:
            from .audio_pii_redactor import get_audio_pii_redactor, get_audio_pii_config

            config = get_audio_pii_config()
            if not config["enabled"]:
                # PII redaction disabled, fall back to standard processing
                result = self.process(file_path)
                result["metadata"]["original_transcript"] = result["text"]
                result["metadata"]["redacted_transcript"] = result["text"]
                result["metadata"]["has_pii"] = False
                result["metadata"]["pii_types_found"] = []
                result["metadata"]["pii_regions"] = []
                return result

            # Get the AudioPIIRedactor (uses whisper-timestamped)
            redactor = get_audio_pii_redactor(verbose=self.verbose)

            if not redactor.is_available():
                if self.verbose:
                    print("AudioProcessor: whisper-timestamped not available, "
                          "falling back to standard processing")
                result = self.process(file_path)
                result["metadata"]["original_transcript"] = result["text"]
                result["metadata"]["redacted_transcript"] = result["text"]
                result["metadata"]["has_pii"] = False
                result["metadata"]["pii_types_found"] = []
                result["metadata"]["pii_regions"] = []
                return result

            # Process with PII redaction
            redaction_result = redactor.process(file_path)

            # Build duration string
            duration_str = ""
            if "duration_seconds" in metadata:
                mins, secs = divmod(int(metadata["duration_seconds"]), 60)
                duration_str = f" ({mins}:{secs:02d})"

            # CRITICAL: Use redacted transcript for embeddings/LLM
            # The 'text' field is what gets embedded and sent to LLM
            prefixed_redacted = (
                f"[Audio transcription{duration_str}]\n\n"
                f"{redaction_result.redacted_transcript}"
            )

            # Store both transcripts in metadata
            metadata["original_transcript"] = redaction_result.original_transcript
            metadata["redacted_transcript"] = redaction_result.redacted_transcript
            metadata["has_pii"] = redaction_result.has_pii
            metadata["pii_types_found"] = redaction_result.pii_types_found
            metadata["pii_regions"] = [
                {
                    "start_time": r.start_time,
                    "end_time": r.end_time,
                    "pii_type": r.pii_type,
                    "original_text": r.original_text,
                    "replacement_text": r.replacement_text,
                    "confidence": r.confidence,
                }
                for r in redaction_result.pii_regions
            ]
            metadata["word_count"] = redaction_result.word_count
            metadata["pii_processing_time_ms"] = redaction_result.processing_time_ms

            return {
                "text": prefixed_redacted,  # Redacted version for LLM
                "metadata": metadata,
            }

        except ImportError as e:
            if self.verbose:
                print(f"AudioProcessor: PII redaction not available: {e}")
            # Fall back to standard processing
            result = self.process(file_path)
            result["metadata"]["original_transcript"] = result["text"]
            result["metadata"]["redacted_transcript"] = result["text"]
            result["metadata"]["has_pii"] = False
            result["metadata"]["pii_types_found"] = []
            result["metadata"]["pii_regions"] = []
            return result
