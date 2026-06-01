"""Audio PII detection and redaction using whisper-timestamped + Presidio.

Provides on-device audio PII protection for MindSage. Transcribes audio with
word-level timestamps, detects PII in the transcript using Presidio, and
produces both original and redacted transcripts.

Phase 1: Transcript redaction (text replacement with [PII_TYPE] tags)
Phase 2: Audio file redaction (silence/beep over PII segments)
Phase 3: Async execution for parallel CPU/GPU operations

Memory footprint:
    - whisper-timestamped: Same as Whisper (~1GB VRAM for tiny.en)
    - pydub: CPU-only audio processing (~50MB)
    - No additional GPU models required

Configuration:
    AUDIO_PII_ENABLED: Enable/disable audio PII redaction (default: true)
    AUDIO_PII_REDACTION_STYLE: Transcript redaction style (default: brackets)
        - "brackets": Replace with [PII_TYPE] tags, e.g., [PERSON]
        - "placeholder": Replace with generic [REDACTED] tag
        - "lprag": Use LPRAG semantic perturbation for reversible anonymization
                  that preserves meaning for LLM reasoning (requires gensim)
    AUDIO_PII_MUTE_AUDIO: Create redacted audio file (default: false)
    AUDIO_PII_MUTE_STYLE: "silence", "beep", or "noise" (default: silence)

Async Execution:
    The pipeline supports async execution to parallelize CPU-bound tasks:
    - Transcription (GPU) must complete first
    - PII detection (CPU) depends on transcription
    - Audio redaction (CPU) and transcript redaction (CPU) can run in parallel
"""

import asyncio
import hashlib
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

# Type checking imports
if TYPE_CHECKING:
    from .pii_protection import PIIProtector


# Check for whisper-timestamped availability
try:
    import whisper_timestamped as whisper
    WHISPER_TIMESTAMPED_AVAILABLE = True
except ImportError:
    WHISPER_TIMESTAMPED_AVAILABLE = False
    whisper = None

# Check for standard whisper (fallback)
try:
    import whisper as openai_whisper
    OPENAI_WHISPER_AVAILABLE = True
except ImportError:
    OPENAI_WHISPER_AVAILABLE = False
    openai_whisper = None

# PyTorch for GPU detection
try:
    import torch
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False
    torch = None

# pydub for audio file manipulation (Phase 2)
try:
    from pydub import AudioSegment
    from pydub.generators import Sine, WhiteNoise
    PYDUB_AVAILABLE = True
except ImportError:
    PYDUB_AVAILABLE = False
    AudioSegment = None
    Sine = None
    WhiteNoise = None


@dataclass
class WordTimestamp:
    """A word with its timing information from transcription."""
    word: str
    start: float  # Start time in seconds
    end: float    # End time in seconds
    confidence: float

    # Character position in full transcript (populated during processing)
    char_start: int = 0
    char_end: int = 0


@dataclass
class AudioPIIRegion:
    """A detected PII region in audio with timestamps."""
    start_time: float      # Start time in seconds
    end_time: float        # End time in seconds
    pii_type: str          # PERSON, EMAIL_ADDRESS, PHONE_NUMBER, etc.
    original_text: str     # The actual PII text
    replacement_text: str  # [PERSON], [PHONE_NUMBER], etc.
    confidence: float      # Detection confidence (0-1)


@dataclass
class TranscriptionResult:
    """Result from audio transcription with timestamps."""
    text: str                           # Full transcript
    words: List[WordTimestamp]          # Word-level timestamps
    language: str                       # Detected language
    duration_seconds: float             # Audio duration
    processing_time_ms: float           # Time taken


@dataclass
class AudioRedactionResult:
    """Result of audio PII redaction."""
    original_transcript: str           # Full transcript with PII
    redacted_transcript: str           # Transcript with PII replaced
    pii_regions: List[AudioPIIRegion]  # Detected regions with timestamps
    redacted_audio_path: Optional[str] # Path to muted audio (Phase 2)
    has_pii: bool                      # Quick check flag
    pii_types_found: List[str]         # List of unique PII types
    processing_time_ms: float          # Performance tracking
    word_count: int                    # Number of words in transcript
    # LPRAG support
    session_id: Optional[str] = None   # PII session ID for de-anonymization
    lprag_enabled: bool = False        # Whether LPRAG perturbation was used


def get_audio_pii_config() -> Dict[str, Any]:
    """Get audio PII configuration from environment.

    Configuration options:
        AUDIO_PII_ENABLED: Enable/disable audio PII redaction (default: true)
        AUDIO_PII_REDACTION_STYLE: How to replace PII in transcripts:
            - "brackets": Replace with [PII_TYPE] tags, e.g., [PERSON] (default)
            - "placeholder": Replace with generic [REDACTED] tag
            - "lprag": Use LPRAG semantic perturbation, e.g., "John Smith" -> "Michael Chen"
                      Preserves semantic meaning for LLM reasoning while protecting privacy.
                      Falls back to brackets if LPRAG unavailable.
        AUDIO_PII_MUTE_AUDIO: Create redacted audio file (default: false)
        AUDIO_PII_MUTE_STYLE: How to mute PII in audio: "silence", "beep", or "noise"
    """
    return {
        "enabled": os.environ.get("AUDIO_PII_ENABLED", "true").lower() == "true",
        "redaction_style": os.environ.get("AUDIO_PII_REDACTION_STYLE", "brackets").lower(),
        # Phase 2 options (audio file redaction)
        "mute_audio": os.environ.get("AUDIO_PII_MUTE_AUDIO", "false").lower() == "true",
        "mute_style": os.environ.get("AUDIO_PII_MUTE_STYLE", "silence").lower(),
    }


class AudioPIIRedactor:
    """Detect and redact PII from audio transcriptions.

    Uses whisper-timestamped for word-level timestamps, then Presidio for
    PII detection. Produces both original and redacted transcripts.

    Designed for Jetson Orin Nano - uses the same Whisper model as AudioProcessor
    with no additional GPU memory required.

    Usage:
        from mcp_vector_store.pii_protection import get_pii_protector

        pii_protector = get_pii_protector()
        redactor = AudioPIIRedactor(pii_protector=pii_protector)

        # Process audio
        result = redactor.process("recording.wav")
        print(result.original_transcript)  # "Hi, I'm John Smith"
        print(result.redacted_transcript)  # "Hi, I'm [PERSON]"
    """

    def __init__(
        self,
        pii_protector: Optional["PIIProtector"] = None,
        whisper_model: str = "tiny.en",
        redaction_style: str = "brackets",
        device: Optional[str] = None,
        verbose: bool = False,
    ):
        """Initialize the audio PII redactor.

        Args:
            pii_protector: PIIProtector instance for entity detection.
                          If None, will attempt to get the global instance.
            whisper_model: Whisper model size ("tiny.en", "base.en", "small.en")
            redaction_style: Redaction style for transcripts:
                - "brackets": Replace with [PII_TYPE] tags, e.g., [PERSON]
                - "placeholder": Replace with generic [REDACTED] tag
                - "lprag": Use LPRAG semantic perturbation for reversible
                          anonymization that preserves meaning for LLM reasoning
            device: Device to use ("cuda" or "cpu"). Auto-detected if None.
            verbose: Enable verbose logging
        """
        self.verbose = verbose
        self.whisper_model_name = whisper_model
        self.redaction_style = redaction_style

        # Auto-detect device
        if device is None:
            self.device = "cuda" if (TORCH_AVAILABLE and torch.cuda.is_available()) else "cpu"
        else:
            self.device = device

        # Whisper model (lazy loaded)
        self._whisper_model = None
        self._whisper_loaded = False

        # PII protector (lazy loaded if not provided)
        self._pii_protector = pii_protector

        if self.verbose:
            print(f"AudioPIIRedactor: model={whisper_model}, device={self.device}, "
                  f"style={redaction_style}")

    def _get_pii_protector(self) -> Optional["PIIProtector"]:
        """Get the PII protector, loading lazily if needed."""
        if self._pii_protector is None:
            try:
                from .pii_protection import get_pii_protector
                self._pii_protector = get_pii_protector(verbose=self.verbose)
            except ImportError:
                try:
                    from pii_protection import get_pii_protector
                    self._pii_protector = get_pii_protector(verbose=self.verbose)
                except ImportError:
                    if self.verbose:
                        print("AudioPIIRedactor: PII protection not available")
                    return None
        return self._pii_protector

    def _load_whisper_model(self):
        """Load the Whisper model for transcription.

        When loading on GPU, coordinates with ModelManager's circuit breaker
        and MemoryMonitor to prevent OOM. This is a separate Whisper instance
        from AudioProcessor (whisper-timestamped vs transformers pipeline),
        so it can't use manager.require(ModelType.TRANSCRIPTION) directly.
        """
        if self._whisper_loaded:
            return

        if not WHISPER_TIMESTAMPED_AVAILABLE:
            raise RuntimeError(
                "whisper-timestamped not installed. "
                "Install with: pip install whisper-timestamped"
            )

        # GPU coordination: check circuit breaker and memory before loading
        if self.device == "cuda":
            try:
                from .model_manager import get_model_manager
                manager = get_model_manager()

                # Check circuit breaker
                if not manager._circuit_breaker.allows_gpu_load():
                    print("AudioPIIRedactor: GPU circuit breaker OPEN, falling back to CPU")
                    self.device = "cpu"
                else:
                    # Clear other GPU models and check memory
                    manager._clear_gpu_memory()
                    if not manager._memory_monitor.has_headroom_for(1000):
                        print(f"AudioPIIRedactor: Insufficient GPU memory "
                              f"({manager._memory_monitor.get_available_mb():.0f}MB available), "
                              f"falling back to CPU")
                        self.device = "cpu"
            except ImportError:
                pass

        if self.verbose:
            print(f"AudioPIIRedactor: Loading Whisper {self.whisper_model_name} "
                  f"on {self.device}...")
            start = time.time()

        try:
            self._whisper_model = whisper.load_model(
                self.whisper_model_name,
                device=self.device,
            )
            self._whisper_loaded = True

            # Record success with circuit breaker if GPU
            if self.device == "cuda":
                try:
                    from .model_manager import get_model_manager
                    get_model_manager()._circuit_breaker.record_success()
                except ImportError:
                    pass

            if self.verbose:
                elapsed = time.time() - start
                print(f"AudioPIIRedactor: Whisper loaded in {elapsed:.1f}s")

        except Exception as e:
            # Record failure with circuit breaker if GPU
            if self.device == "cuda":
                try:
                    from .model_manager import get_model_manager
                    get_model_manager()._circuit_breaker.record_failure(e)
                except ImportError:
                    pass
                # Fall back to CPU
                print(f"AudioPIIRedactor: GPU Whisper load failed ({e}), falling back to CPU")
                self.device = "cpu"
                self._whisper_model = whisper.load_model(
                    self.whisper_model_name,
                    device="cpu",
                )
                self._whisper_loaded = True
                if self.verbose:
                    elapsed = time.time() - start
                    print(f"AudioPIIRedactor: Whisper loaded on CPU fallback in {elapsed:.1f}s")
            else:
                raise

    def _unload_whisper_model(self):
        """Unload the Whisper model to free memory."""
        if not self._whisper_loaded:
            return

        if self.verbose:
            print("AudioPIIRedactor: Unloading Whisper model...")

        del self._whisper_model
        self._whisper_model = None
        self._whisper_loaded = False

        if TORCH_AVAILABLE and torch.cuda.is_available():
            torch.cuda.empty_cache()

    def is_available(self) -> bool:
        """Check if audio PII redaction is available."""
        return WHISPER_TIMESTAMPED_AVAILABLE

    def is_loaded(self) -> bool:
        """Check if Whisper model is loaded."""
        return self._whisper_loaded

    def transcribe_with_timestamps(
        self,
        audio_path: str,
    ) -> TranscriptionResult:
        """Transcribe audio with word-level timestamps.

        Args:
            audio_path: Path to audio file

        Returns:
            TranscriptionResult with text and word timestamps
        """
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        start = time.time()

        # Load model if needed
        self._load_whisper_model()

        # Transcribe with whisper-timestamped
        audio = whisper.load_audio(audio_path)
        result = whisper.transcribe(
            self._whisper_model,
            audio,
            language="en",  # Force English for consistency
        )

        # Extract word timestamps
        words = []
        char_position = 0

        for segment in result.get("segments", []):
            for word_data in segment.get("words", []):
                word_text = word_data.get("text", "").strip()
                if not word_text:
                    continue

                # Calculate character positions in full transcript
                # Account for spaces between words
                if char_position > 0:
                    char_position += 1  # Space before word

                word = WordTimestamp(
                    word=word_text,
                    start=word_data.get("start", 0.0),
                    end=word_data.get("end", 0.0),
                    confidence=word_data.get("confidence", 0.0),
                    char_start=char_position,
                    char_end=char_position + len(word_text),
                )
                words.append(word)
                char_position = word.char_end

        elapsed = (time.time() - start) * 1000

        # Build full transcript from words
        full_text = " ".join(w.word for w in words)

        # Get duration from audio
        duration = len(audio) / 16000  # Whisper uses 16kHz

        return TranscriptionResult(
            text=full_text,
            words=words,
            language=result.get("language", "en"),
            duration_seconds=duration,
            processing_time_ms=elapsed,
        )

    @staticmethod
    def _normalize_transcript_for_detection(transcript: str) -> Tuple[str, List[Tuple[int, int, int, int]]]:
        """Normalize transcript for better PII detection.

        Whisper often breaks numbers with spaces (e.g., "4111 111 111 111 111"
        instead of "4111111111111111"). This finds sequences of space-separated
        digit groups and tries joining them to match credit card / phone patterns.

        Returns:
            Tuple of (normalized_text, mapping) where mapping is a list of
            (norm_start, norm_end, orig_start, orig_end) for each joined region.
        """
        # Find sequences of 3+ digit groups separated by spaces only (not commas)
        # Use commas and periods as boundaries
        pattern = re.compile(r'\b(\d{1,4}\s+){2,}\d{1,4}\b')

        normalized = transcript
        mappings = []
        offset = 0

        for match in pattern.finditer(transcript):
            orig_text = match.group()
            joined = re.sub(r'\s+', '', orig_text)

            # Only normalize if result is a plausible PII length
            # Credit cards: 13-19 digits, Phone: 10-15 digits, SSN: 9 digits
            if not (9 <= len(joined) <= 19):
                continue

            orig_start = match.start()
            orig_end = match.end()
            norm_start = orig_start + offset
            norm_end = norm_start + len(joined)

            normalized = normalized[:norm_start] + joined + normalized[norm_start + len(orig_text):]
            mappings.append((norm_start, norm_end, orig_start, orig_end))
            offset += len(joined) - len(orig_text)

        return normalized, mappings

    def _map_pii_to_timestamps(
        self,
        pii_start: int,
        pii_end: int,
        words: List[WordTimestamp],
    ) -> Tuple[float, float, str]:
        """Map character positions to audio timestamps.

        Args:
            pii_start: Start character index in transcript
            pii_end: End character index in transcript
            words: List of word timestamps

        Returns:
            Tuple of (start_time, end_time, matched_text)
        """
        start_time = None
        end_time = None
        matched_words = []

        for word in words:
            # Check if this word overlaps with the PII region
            word_overlaps = (
                word.char_start < pii_end and word.char_end > pii_start
            )

            if word_overlaps:
                if start_time is None:
                    start_time = word.start
                end_time = word.end
                matched_words.append(word.word)

        # Default to first/last word times if no match found
        if start_time is None and words:
            start_time = words[0].start
        if end_time is None and words:
            end_time = words[-1].end

        matched_text = " ".join(matched_words)
        return start_time or 0.0, end_time or 0.0, matched_text

    def detect_pii_regions(
        self,
        transcript: str,
        words: List[WordTimestamp],
    ) -> List[AudioPIIRegion]:
        """Detect PII regions in transcript and map to timestamps.

        Args:
            transcript: Full transcript text
            words: Word timestamps from transcription

        Returns:
            List of AudioPIIRegion with timestamps
        """
        pii_protector = self._get_pii_protector()
        if pii_protector is None:
            print("AudioPIIRedactor: No PII protector available")
            return []

        # Ensure Presidio is initialized
        if hasattr(pii_protector, '_ensure_initialized'):
            if not pii_protector._ensure_initialized():
                print(f"AudioPIIRedactor: PII protector init failed: {pii_protector._init_error}")
                return []

        regions = []

        # Run Presidio analyzer
        if hasattr(pii_protector, '_analyzer') and pii_protector._analyzer is not None:
            try:
                print(f"AudioPIIRedactor: Analyzing transcript ({len(transcript)} chars): "
                      f"\"{transcript[:200]}{'...' if len(transcript) > 200 else ''}\"")

                # Explicitly request common PII entity types including PERSON
                entities_to_detect = [
                    "PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD",
                    "DATE_TIME", "LOCATION", "URL", "US_SSN", "US_DRIVER_LICENSE",
                    "IBAN_CODE", "IP_ADDRESS",
                ]

                results = pii_protector._analyzer.analyze(
                    text=transcript,
                    language="en",
                    entities=entities_to_detect,
                    score_threshold=0.3,  # Lower threshold to catch more PII
                )

                print(f"AudioPIIRedactor: Presidio found {len(results)} entities: "
                      f"{[(r.entity_type, transcript[r.start:r.end], f'{r.score:.2f}') for r in results]}")

                for result in results:
                    # Map character positions to timestamps
                    start_time, end_time, matched_text = self._map_pii_to_timestamps(
                        result.start,
                        result.end,
                        words,
                    )

                    # Get the actual PII text
                    original_text = transcript[result.start:result.end]

                    # Determine replacement text based on style
                    if self.redaction_style == "placeholder":
                        replacement = "[REDACTED]"
                    else:
                        replacement = f"[{result.entity_type}]"

                    regions.append(AudioPIIRegion(
                        start_time=start_time,
                        end_time=end_time,
                        pii_type=result.entity_type,
                        original_text=original_text,
                        replacement_text=replacement,
                        confidence=result.score,
                    ))

                # Second pass: detect number-based PII (credit cards, phone numbers)
                # on normalized text where Whisper's space-separated digits are joined
                normalized, norm_mappings = self._normalize_transcript_for_detection(transcript)
                if normalized != transcript:
                    print(f"AudioPIIRedactor: Running 2nd pass on normalized text: "
                          f"\"{normalized[:200]}\"")

                    norm_results = pii_protector._analyzer.analyze(
                        text=normalized,
                        language="en",
                        entities=["CREDIT_CARD", "PHONE_NUMBER", "US_SSN", "IBAN_CODE"],
                        score_threshold=0.3,
                    )

                    # Only keep results that overlap with normalized regions
                    # (i.e., results that benefit from the normalization)
                    existing_types_and_times = {
                        (r.pii_type, round(r.start_time, 1), round(r.end_time, 1))
                        for r in regions
                    }

                    for result in norm_results:
                        # Map normalized position back to original text position
                        orig_start = result.start
                        orig_end = result.end
                        for norm_start, norm_end, os_start, os_end in norm_mappings:
                            if result.start >= norm_start and result.end <= norm_end:
                                orig_start = os_start
                                orig_end = os_end
                                break

                        original_text = transcript[orig_start:orig_end]
                        start_time, end_time, matched_text = self._map_pii_to_timestamps(
                            orig_start, orig_end, words,
                        )

                        # Skip if we already have this region
                        key = (result.entity_type, round(start_time, 1), round(end_time, 1))
                        if key in existing_types_and_times:
                            continue

                        if self.redaction_style == "placeholder":
                            replacement = "[REDACTED]"
                        else:
                            replacement = f"[{result.entity_type}]"

                        print(f"AudioPIIRedactor: 2nd pass found: {result.entity_type} "
                              f"\"{original_text}\" (score={result.score:.2f})")

                        regions.append(AudioPIIRegion(
                            start_time=start_time,
                            end_time=end_time,
                            pii_type=result.entity_type,
                            original_text=original_text,
                            replacement_text=replacement,
                            confidence=result.score,
                        ))

            except Exception as e:
                print(f"AudioPIIRedactor: PII detection error: {e}")
                import traceback
                traceback.print_exc()

        return regions

    def redact_transcript(
        self,
        transcript: str,
        pii_regions: List[AudioPIIRegion],
    ) -> str:
        """Replace PII in transcript with redaction tags.

        Args:
            transcript: Original transcript
            pii_regions: List of detected PII regions

        Returns:
            Redacted transcript with PII replaced
        """
        if not pii_regions:
            return transcript

        # Sort regions by position (reverse order to preserve indices)
        # We need to map from the original_text to find positions
        redacted = transcript

        # Process in reverse order to maintain string indices
        # Sort by finding position in string (later positions first)
        regions_with_pos = []
        for region in pii_regions:
            pos = transcript.find(region.original_text)
            if pos >= 0:
                regions_with_pos.append((pos, region))

        # Sort by position descending
        regions_with_pos.sort(key=lambda x: x[0], reverse=True)

        # Apply replacements
        for pos, region in regions_with_pos:
            redacted = (
                redacted[:pos] +
                region.replacement_text +
                redacted[pos + len(region.original_text):]
            )

        return redacted

    def redact_transcript_lprag(
        self,
        transcript: str,
        session_id: Optional[str] = None,
    ) -> Tuple[str, str, bool]:
        """Redact transcript using LPRAG semantic perturbation.

        Uses PIIProtector.anonymize() which applies LPRAG perturbation to replace
        PII with semantically similar fake values (e.g., "John Smith" -> "Michael Chen").
        This preserves meaning for LLM reasoning while protecting privacy.

        Args:
            transcript: Original transcript
            session_id: Optional session ID for token storage (enables de-anonymization)

        Returns:
            Tuple of (redacted_transcript, session_id, lprag_used)
            - redacted_transcript: Text with PII replaced
            - session_id: Session ID for de-anonymization
            - lprag_used: True if LPRAG was used, False if fell back to tokens
        """
        pii_protector = self._get_pii_protector()
        if pii_protector is None:
            return transcript, session_id or "", False

        try:
            # Use PIIProtector.anonymize() which handles LPRAG internally
            result = pii_protector.anonymize(
                text=transcript,
                session_id=session_id,
            )

            # Check if LPRAG was actually used (vs token fallback)
            # LPRAG mode produces perturbed values, not <PII:TYPE:token> strings
            lprag_used = (
                result.token_count > 0 and
                "<PII:" not in result.anonymized_text and
                hasattr(pii_protector, '_mode') and
                pii_protector._mode.value != "token_only"
            )

            if self.verbose:
                mode = "LPRAG" if lprag_used else "tokens"
                print(f"AudioPIIRedactor: Redacted {result.token_count} PII entities "
                      f"using {mode} in {result.processing_time_ms:.1f}ms")

            return result.anonymized_text, result.session_id, lprag_used

        except Exception as e:
            if self.verbose:
                print(f"AudioPIIRedactor: LPRAG redaction failed: {e}")
            return transcript, session_id or "", False

    def _generate_beep_segment(
        self,
        duration_ms: int,
        sample_rate: int = 44100,
        frequency: int = 1000,
        volume_db: float = -10.0,
    ) -> "AudioSegment":
        """Generate a beep tone for redaction.

        Args:
            duration_ms: Duration of beep in milliseconds
            sample_rate: Audio sample rate
            frequency: Beep frequency in Hz (default: 1000Hz)
            volume_db: Volume adjustment in dB (default: -10dB)

        Returns:
            AudioSegment containing the beep tone
        """
        if not PYDUB_AVAILABLE:
            raise RuntimeError("pydub not installed for audio redaction")

        # Generate sine wave beep
        beep = Sine(frequency).to_audio_segment(duration=duration_ms)
        beep = beep.apply_gain(volume_db)
        return beep

    def _generate_noise_segment(
        self,
        duration_ms: int,
        volume_db: float = -20.0,
    ) -> "AudioSegment":
        """Generate white noise for redaction.

        Args:
            duration_ms: Duration of noise in milliseconds
            volume_db: Volume adjustment in dB (default: -20dB)

        Returns:
            AudioSegment containing white noise
        """
        if not PYDUB_AVAILABLE:
            raise RuntimeError("pydub not installed for audio redaction")

        # Generate white noise
        noise = WhiteNoise().to_audio_segment(duration=duration_ms)
        noise = noise.apply_gain(volume_db)
        return noise

    def redact_audio(
        self,
        audio_path: str,
        pii_regions: List[AudioPIIRegion],
        output_path: Optional[str] = None,
        mute_style: str = "silence",
        padding_ms: int = 50,
    ) -> str:
        """Create a redacted audio file with PII segments replaced.

        Args:
            audio_path: Path to original audio file
            pii_regions: List of PII regions with timestamps
            output_path: Path for output file (auto-generated if None)
            mute_style: "silence", "beep", or "noise"
            padding_ms: Extra milliseconds around PII regions (default: 50ms)

        Returns:
            Path to the redacted audio file
        """
        if not PYDUB_AVAILABLE:
            raise RuntimeError(
                "pydub not installed. Install with: pip install pydub\n"
                "Also requires ffmpeg: sudo apt install ffmpeg"
            )

        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        if not pii_regions:
            # No PII to redact, just copy the file
            if output_path is None:
                output_path = self._generate_output_path(audio_path)
            import shutil
            shutil.copy2(audio_path, output_path)
            return output_path

        if self.verbose:
            print(f"AudioPIIRedactor: Redacting {len(pii_regions)} PII regions "
                  f"with style '{mute_style}'...")
            start = time.time()

        # Load the audio file
        audio = AudioSegment.from_file(audio_path)

        # Sort regions by start time
        sorted_regions = sorted(pii_regions, key=lambda r: r.start_time)

        # Build the redacted audio
        result = AudioSegment.empty()
        current_pos_ms = 0

        for region in sorted_regions:
            # Convert timestamps to milliseconds
            start_ms = max(0, int(region.start_time * 1000) - padding_ms)
            end_ms = min(len(audio), int(region.end_time * 1000) + padding_ms)

            # Skip if this region overlaps with previous (already processed)
            if start_ms < current_pos_ms:
                start_ms = current_pos_ms

            if start_ms >= end_ms:
                continue

            # Add audio before this PII region
            if start_ms > current_pos_ms:
                result += audio[current_pos_ms:start_ms]

            # Generate replacement segment
            duration_ms = end_ms - start_ms
            if mute_style == "beep":
                replacement = self._generate_beep_segment(duration_ms)
            elif mute_style == "noise":
                replacement = self._generate_noise_segment(duration_ms)
            else:  # silence
                replacement = AudioSegment.silent(duration=duration_ms)

            # Match the channel count and sample rate
            if audio.channels != replacement.channels:
                if audio.channels == 2:
                    replacement = replacement.set_channels(2)
                else:
                    replacement = replacement.set_channels(1)

            result += replacement
            current_pos_ms = end_ms

        # Add remaining audio after last PII region
        if current_pos_ms < len(audio):
            result += audio[current_pos_ms:]

        # Generate output path if not provided
        if output_path is None:
            output_path = self._generate_output_path(audio_path)

        # Ensure output directory exists
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        # Export with same format as input
        input_ext = Path(audio_path).suffix.lower()
        if input_ext in ['.mp3']:
            result.export(output_path, format="mp3")
        elif input_ext in ['.ogg']:
            result.export(output_path, format="ogg")
        elif input_ext in ['.flac']:
            result.export(output_path, format="flac")
        else:
            result.export(output_path, format="wav")

        if self.verbose:
            elapsed = time.time() - start
            print(f"AudioPIIRedactor: Redacted audio saved to {output_path} "
                  f"in {elapsed:.1f}s")

        return output_path

    def _generate_output_path(self, input_path: str) -> str:
        """Generate output path for redacted audio file.

        Args:
            input_path: Path to original audio file (in data/uploads/audio/)

        Returns:
            Path for redacted audio file in data/redacted/audio/
        """
        input_path_obj = Path(input_path)

        # Input is at data/uploads/audio/{audio_id}.ext
        # Output goes to data/redacted/audio/{audio_id}_redacted.ext
        # Go up 3 levels: audio/ -> uploads/ -> data/
        data_dir = input_path_obj.parent.parent.parent
        redacted_dir = data_dir / "redacted" / "audio"
        output_filename = f"{input_path_obj.stem}_redacted{input_path_obj.suffix}"

        return str(redacted_dir / output_filename)

    def is_audio_redaction_available(self) -> bool:
        """Check if audio file redaction is available."""
        return PYDUB_AVAILABLE

    def process(
        self,
        audio_path: str,
        mute_audio: Optional[bool] = None,
        mute_style: Optional[str] = None,
        redaction_style: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> AudioRedactionResult:
        """Full pipeline: transcribe, detect PII, redact transcript and optionally audio.

        Args:
            audio_path: Path to audio file
            mute_audio: Create redacted audio file (overrides env config if set)
            mute_style: "silence", "beep", or "noise" (overrides env config if set)
            redaction_style: Override redaction style ("brackets", "placeholder", "lprag")
            session_id: Session ID for LPRAG de-anonymization

        Returns:
            AudioRedactionResult with original and redacted transcripts,
            plus path to redacted audio if mute_audio is enabled.
            If LPRAG is used, includes session_id for de-anonymization.
        """
        start = time.time()

        # Get config from environment if not overridden
        config = get_audio_pii_config()
        if mute_audio is None:
            mute_audio = config["mute_audio"]
        if mute_style is None:
            mute_style = config["mute_style"]
        if redaction_style is None:
            redaction_style = config["redaction_style"]

        # Step 1: Transcribe with timestamps
        transcription = self.transcribe_with_timestamps(audio_path)

        # Step 2: Detect PII regions (always needed for audio muting and metadata)
        pii_regions = self.detect_pii_regions(
            transcription.text,
            transcription.words,
        )

        # Step 3: Redact transcript based on style
        lprag_used = False
        result_session_id = session_id

        if redaction_style == "lprag" and pii_regions:
            # Use LPRAG semantic perturbation
            redacted_transcript, result_session_id, lprag_used = self.redact_transcript_lprag(
                transcription.text,
                session_id=session_id,
            )
            # If LPRAG failed, fall back to brackets
            if not lprag_used and "<PII:" in redacted_transcript:
                if self.verbose:
                    print("AudioPIIRedactor: LPRAG unavailable, falling back to brackets")
                redacted_transcript = self.redact_transcript(
                    transcription.text,
                    pii_regions,
                )
        else:
            # Use standard bracket/placeholder redaction
            redacted_transcript = self.redact_transcript(
                transcription.text,
                pii_regions,
            )

        # Step 4: Optionally create redacted audio file
        redacted_audio_path = None
        if mute_audio and pii_regions and PYDUB_AVAILABLE:
            try:
                redacted_audio_path = self.redact_audio(
                    audio_path,
                    pii_regions,
                    mute_style=mute_style,
                )
            except Exception as e:
                if self.verbose:
                    print(f"AudioPIIRedactor: Audio redaction failed: {e}")
                # Continue without redacted audio

        # Collect unique PII types
        pii_types = list(set(r.pii_type for r in pii_regions))

        elapsed = (time.time() - start) * 1000

        return AudioRedactionResult(
            original_transcript=transcription.text,
            redacted_transcript=redacted_transcript,
            pii_regions=pii_regions,
            redacted_audio_path=redacted_audio_path,
            has_pii=len(pii_regions) > 0,
            pii_types_found=pii_types,
            processing_time_ms=elapsed,
            word_count=len(transcription.words),
            session_id=result_session_id,
            lprag_enabled=lprag_used,
        )


# Global instance (lazy initialization)
_global_audio_pii_redactor: Optional[AudioPIIRedactor] = None


def get_audio_pii_redactor(
    pii_protector: Optional["PIIProtector"] = None,
    verbose: bool = False,
) -> AudioPIIRedactor:
    """Get the global AudioPIIRedactor instance.

    Creates the instance on first call with configuration from environment.

    Args:
        pii_protector: Optional PIIProtector to use
        verbose: Enable verbose logging

    Returns:
        Global AudioPIIRedactor instance
    """
    global _global_audio_pii_redactor

    if _global_audio_pii_redactor is None:
        config = get_audio_pii_config()

        # Determine Whisper model from environment or default
        whisper_model = os.environ.get("WHISPER_MODEL", "tiny.en")
        # Handle full model names like "openai/whisper-tiny.en"
        if "/" in whisper_model:
            whisper_model = whisper_model.split("/")[-1].replace("whisper-", "")

        _global_audio_pii_redactor = AudioPIIRedactor(
            pii_protector=pii_protector,
            whisper_model=whisper_model,
            redaction_style=config["redaction_style"],
            verbose=verbose,
        )

    return _global_audio_pii_redactor
