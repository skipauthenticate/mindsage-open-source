#!/usr/bin/env python3
"""Generate test audio files with PII scenarios for integration testing.

Creates test audio files in tests/fixtures/audio/ and their redacted
versions in tests/fixtures/redacted/audio/.

Uses edge-tts to generate actual speech audio that Whisper can transcribe.
Each fixture includes JSON metadata describing expected transcripts and PII
regions for test verification.

Requirements:
    pip install edge-tts pydub

Usage:
    python tests/fixtures/generate_test_audio.py
"""

import asyncio
import json
import math
import os
import struct
import tempfile
import wave
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Optional

try:
    import edge_tts
    EDGE_TTS_AVAILABLE = True
except ImportError:
    EDGE_TTS_AVAILABLE = False
    print("Warning: edge-tts not installed. Install with: pip install edge-tts")

try:
    from pydub import AudioSegment
    PYDUB_AVAILABLE = True
except ImportError:
    PYDUB_AVAILABLE = False
    print("Warning: pydub not installed. Install with: pip install pydub")


# Output directories
FIXTURES_DIR = Path(__file__).parent
AUDIO_DIR = FIXTURES_DIR / "audio"
REDACTED_DIR = FIXTURES_DIR / "redacted" / "audio"


@dataclass
class PIIRegion:
    """A PII region in the audio."""
    start_time: float
    end_time: float
    pii_type: str
    original_text: str
    replacement_text: str
    confidence: float = 0.95


@dataclass
class WordTimestamp:
    """A word with timestamp."""
    word: str
    start: float
    end: float


@dataclass
class AudioFixtureMetadata:
    """Metadata for an audio test fixture."""
    filename: str
    description: str
    duration_seconds: float
    sample_rate: int
    transcript: str
    words: List[dict]
    pii_regions: List[dict]
    has_pii: bool
    pii_types: List[str]


def generate_sine_wave(
    duration_seconds: float,
    frequency: int = 440,
    sample_rate: int = 16000,
    amplitude: float = 0.5,
) -> bytes:
    """Generate sine wave audio data."""
    num_samples = int(duration_seconds * sample_rate)
    samples = []
    for i in range(num_samples):
        t = i / sample_rate
        sample = amplitude * math.sin(2 * math.pi * frequency * t)
        samples.append(int(sample * 32767))
    return struct.pack(f'{num_samples}h', *samples)


def generate_silence(duration_seconds: float, sample_rate: int = 16000) -> bytes:
    """Generate silence audio data."""
    num_samples = int(duration_seconds * sample_rate)
    return struct.pack('h', 0) * num_samples


def generate_beep(
    duration_seconds: float,
    frequency: int = 1000,
    sample_rate: int = 16000,
    amplitude: float = 0.3,
) -> bytes:
    """Generate beep tone audio data."""
    return generate_sine_wave(duration_seconds, frequency, sample_rate, amplitude)


async def generate_speech_tts(
    text: str,
    output_path: Path,
    voice: str = "en-US-ChristopherNeural",
) -> bool:
    """Generate speech audio using edge-tts.

    Args:
        text: Text to convert to speech
        output_path: Path to save the WAV file
        voice: TTS voice to use (default: en-US-ChristopherNeural)

    Returns:
        True if successful, False otherwise
    """
    if not EDGE_TTS_AVAILABLE:
        return False

    try:
        # Generate MP3 with edge-tts
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp_mp3:
            tmp_mp3_path = tmp_mp3.name

        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(tmp_mp3_path)

        # Convert MP3 to WAV (16kHz mono) using pydub
        if PYDUB_AVAILABLE:
            audio = AudioSegment.from_mp3(tmp_mp3_path)
            audio = audio.set_frame_rate(16000).set_channels(1)
            audio.export(str(output_path), format="wav")
        else:
            # Fallback: just rename the mp3 (won't work well with Whisper)
            os.rename(tmp_mp3_path, str(output_path).replace(".wav", ".mp3"))
            print(f"  Warning: pydub not available, saved as MP3")
            return False

        # Clean up temp file
        if os.path.exists(tmp_mp3_path):
            os.unlink(tmp_mp3_path)

        return True
    except Exception as e:
        print(f"  TTS error: {e}")
        return False


def generate_speech_sync(text: str, output_path: Path, voice: str = "en-US-ChristopherNeural") -> bool:
    """Synchronous wrapper for generate_speech_tts."""
    return asyncio.run(generate_speech_tts(text, output_path, voice))


def write_wav(filename: Path, audio_data: bytes, sample_rate: int = 16000):
    """Write audio data to a WAV file."""
    with wave.open(str(filename), 'w') as wav:
        wav.setnchannels(1)  # Mono
        wav.setsampwidth(2)  # 16-bit
        wav.setframerate(sample_rate)
        wav.writeframes(audio_data)


def create_audio_with_pii_regions(
    duration: float,
    pii_regions: List[PIIRegion],
    sample_rate: int = 16000,
    base_frequency: int = 440,
) -> tuple:
    """Create original and redacted audio with PII regions (sine wave fallback).

    Returns:
        Tuple of (original_audio_data, redacted_audio_data)
    """
    # Generate original as continuous sine wave
    original_data = generate_sine_wave(duration, base_frequency, sample_rate)

    # Generate redacted version with silence in PII regions
    num_samples = int(duration * sample_rate)
    original_samples = list(struct.unpack(f'{num_samples}h', original_data))
    redacted_samples = original_samples.copy()

    # Mute PII regions
    for region in pii_regions:
        start_sample = int(region.start_time * sample_rate)
        end_sample = int(region.end_time * sample_rate)
        for i in range(start_sample, min(end_sample, num_samples)):
            redacted_samples[i] = 0

    redacted_data = struct.pack(f'{num_samples}h', *redacted_samples)
    return original_data, redacted_data


def create_redacted_audio_from_wav(
    original_path: Path,
    redacted_path: Path,
    pii_regions: List[PIIRegion],
) -> bool:
    """Create redacted version of audio by muting PII regions.

    Args:
        original_path: Path to original WAV file
        redacted_path: Path to save redacted WAV file
        pii_regions: List of PII regions to mute

    Returns:
        True if successful
    """
    if not PYDUB_AVAILABLE:
        return False

    try:
        # Load the original audio
        audio = AudioSegment.from_wav(str(original_path))
        sample_rate = audio.frame_rate

        # If no PII regions, just copy the file
        if not pii_regions:
            audio.export(str(redacted_path), format="wav")
            return True

        # Create silence segment for muting
        # Mute each PII region by overlaying silence
        for region in pii_regions:
            start_ms = int(region.start_time * 1000)
            end_ms = int(region.end_time * 1000)
            duration_ms = end_ms - start_ms

            # Create silence for this region
            silence = AudioSegment.silent(duration=duration_ms, frame_rate=sample_rate)

            # Replace the PII region with silence
            audio = audio[:start_ms] + silence + audio[end_ms:]

        # Export redacted audio
        audio.export(str(redacted_path), format="wav")
        return True

    except Exception as e:
        print(f"  Error creating redacted audio: {e}")
        return False


def create_words_from_transcript(
    transcript: str,
    start_time: float,
    words_per_second: float = 2.5,
) -> List[WordTimestamp]:
    """Create word timestamps from transcript text."""
    words = transcript.split()
    word_duration = 1.0 / words_per_second
    timestamps = []
    current_time = start_time

    for word in words:
        timestamps.append(WordTimestamp(
            word=word,
            start=round(current_time, 2),
            end=round(current_time + word_duration, 2),
        ))
        current_time += word_duration

    return timestamps


# ============================================================================
# Test Fixtures - Audio files with specific PII scenarios
# ============================================================================

AUDIO_FIXTURES = [
    # Simple name
    {
        "filename": "conversation_with_name.wav",
        "description": "Conversation mentioning a person's name",
        "transcript": "Hello my name is John Smith and I am calling about my order",
        "pii_regions": [
            PIIRegion(
                start_time=1.2,
                end_time=2.0,
                pii_type="PERSON",
                original_text="John Smith",
                replacement_text="[PERSON]",
            )
        ],
    },
    # Email address
    {
        "filename": "conversation_with_email.wav",
        "description": "Conversation mentioning an email address",
        "transcript": "You can reach me at john.smith@example.com for any questions",
        "pii_regions": [
            PIIRegion(
                start_time=1.6,
                end_time=3.0,
                pii_type="EMAIL_ADDRESS",
                original_text="john.smith@example.com",
                replacement_text="[EMAIL]",
            )
        ],
    },
    # Phone number
    {
        "filename": "conversation_with_phone.wav",
        "description": "Conversation mentioning a phone number",
        "transcript": "Please call me back at 555-123-4567 when you get a chance",
        "pii_regions": [
            PIIRegion(
                start_time=2.0,
                end_time=3.2,
                pii_type="PHONE_NUMBER",
                original_text="555-123-4567",
                replacement_text="[PHONE]",
            )
        ],
    },
    # SSN (Note: 123-45-6789 is invalidated by Presidio as a known test SSN.
    #      We use 529-38-4271 which has no zeros - TTS pronounces it clearly
    #      and Whisper transcribes it accurately)
    {
        "filename": "conversation_with_ssn.wav",
        "description": "Conversation mentioning a social security number",
        "transcript": "My social security number is 529-38-4271 for verification",
        "pii_regions": [
            PIIRegion(
                start_time=2.0,
                end_time=3.5,
                pii_type="US_SSN",
                original_text="529-38-4271",
                replacement_text="[SSN]",
            )
        ],
    },
    # Multiple PII
    {
        "filename": "conversation_with_multiple_pii.wav",
        "description": "Conversation with multiple PII types",
        "transcript": "Hi I am Jane Doe my email is jane@test.com and phone is 555-999-8888",
        "pii_regions": [
            PIIRegion(
                start_time=0.8,
                end_time=1.6,
                pii_type="PERSON",
                original_text="Jane Doe",
                replacement_text="[PERSON]",
            ),
            PIIRegion(
                start_time=2.4,
                end_time=3.6,
                pii_type="EMAIL_ADDRESS",
                original_text="jane@test.com",
                replacement_text="[EMAIL]",
            ),
            PIIRegion(
                start_time=4.4,
                end_time=5.6,
                pii_type="PHONE_NUMBER",
                original_text="555-999-8888",
                replacement_text="[PHONE]",
            ),
        ],
    },
    # No PII
    {
        "filename": "conversation_no_pii.wav",
        "description": "Conversation with no PII",
        "transcript": "The weather today is sunny and warm with a high of seventy degrees",
        "pii_regions": [],
    },
    # Credit card
    {
        "filename": "conversation_with_credit_card.wav",
        "description": "Conversation mentioning a credit card number",
        "transcript": "My card number is 4111 1111 1111 1111 expiring next year",
        "pii_regions": [
            PIIRegion(
                start_time=1.2,
                end_time=3.0,
                pii_type="CREDIT_CARD",
                original_text="4111 1111 1111 1111",
                replacement_text="[CREDIT_CARD]",
            )
        ],
    },
    # Medical
    {
        "filename": "medical_intake.wav",
        "description": "Medical intake recording",
        "transcript": "Patient Robert Johnson date of birth March 15 1985 presenting with symptoms",
        "pii_regions": [
            PIIRegion(
                start_time=0.4,
                end_time=1.2,
                pii_type="PERSON",
                original_text="Robert Johnson",
                replacement_text="[PERSON]",
            ),
            PIIRegion(
                start_time=1.6,
                end_time=2.8,
                pii_type="DATE_TIME",
                original_text="March 15 1985",
                replacement_text="[DATE]",
            ),
        ],
    },
    # Banking
    {
        "filename": "banking_call.wav",
        "description": "Banking support call",
        "transcript": "Account number 9876543210 for customer Michael Brown address 123 Main Street",
        "pii_regions": [
            PIIRegion(
                start_time=0.8,
                end_time=2.0,
                pii_type="US_BANK_NUMBER",
                original_text="9876543210",
                replacement_text="[ACCOUNT]",
            ),
            PIIRegion(
                start_time=2.8,
                end_time=3.6,
                pii_type="PERSON",
                original_text="Michael Brown",
                replacement_text="[PERSON]",
            ),
            PIIRegion(
                start_time=4.0,
                end_time=5.2,
                pii_type="LOCATION",
                original_text="123 Main Street",
                replacement_text="[ADDRESS]",
            ),
        ],
    },
    # IP Address
    {
        "filename": "tech_support.wav",
        "description": "Tech support call with IP address",
        "transcript": "The server IP address is 192.168.1.100 showing connection errors",
        "pii_regions": [
            PIIRegion(
                start_time=1.6,
                end_time=2.8,
                pii_type="IP_ADDRESS",
                original_text="192.168.1.100",
                replacement_text="[IP_ADDRESS]",
            )
        ],
    },
]


def generate_fixture(fixture_config: dict, use_tts: bool = True) -> AudioFixtureMetadata:
    """Generate a single audio fixture with original and redacted versions.

    Args:
        fixture_config: Configuration dict with filename, transcript, pii_regions
        use_tts: If True, generate actual speech using edge-tts. If False, use sine waves.
    """
    filename = fixture_config["filename"]
    transcript = fixture_config["transcript"]
    pii_regions = fixture_config["pii_regions"]

    # Calculate duration based on word count (estimate for metadata)
    words = transcript.split()
    words_per_second = 2.5
    estimated_duration = len(words) / words_per_second + 0.5

    sample_rate = 16000
    original_path = AUDIO_DIR / filename
    redacted_filename = filename.replace(".wav", "_redacted.wav")
    redacted_path = REDACTED_DIR / redacted_filename

    # Try TTS first if requested and available
    tts_success = False
    actual_duration = estimated_duration

    if use_tts and EDGE_TTS_AVAILABLE and PYDUB_AVAILABLE:
        print(f"Generating speech: {filename}")
        tts_success = generate_speech_sync(transcript, original_path)

        if tts_success:
            # Get actual duration from generated file
            try:
                audio = AudioSegment.from_wav(str(original_path))
                actual_duration = len(audio) / 1000.0  # ms to seconds
                sample_rate = audio.frame_rate
                print(f"  Duration: {actual_duration:.2f}s")

                # Create redacted version by muting PII regions
                if create_redacted_audio_from_wav(original_path, redacted_path, pii_regions):
                    print(f"  Created redacted: {redacted_path}")
                else:
                    # Fallback: copy original as redacted
                    audio.export(str(redacted_path), format="wav")
                    print(f"  Created redacted (no muting): {redacted_path}")
            except Exception as e:
                print(f"  Error processing audio: {e}")
                tts_success = False

    # Fallback to sine waves if TTS failed
    if not tts_success:
        print(f"Generating sine wave fallback: {filename}")
        original_data, redacted_data = create_audio_with_pii_regions(
            estimated_duration, pii_regions, sample_rate
        )
        write_wav(original_path, original_data, sample_rate)
        write_wav(redacted_path, redacted_data, sample_rate)
        actual_duration = estimated_duration
        print(f"  Created: {original_path}")
        print(f"  Created: {redacted_path}")

    # Create word timestamps (estimated - actual timing varies with TTS)
    word_timestamps = create_words_from_transcript(transcript, 0.0, words_per_second)

    # Create metadata
    pii_types = list(set(r.pii_type for r in pii_regions))
    metadata = AudioFixtureMetadata(
        filename=filename,
        description=fixture_config["description"],
        duration_seconds=round(actual_duration, 2),
        sample_rate=sample_rate,
        transcript=transcript,
        words=[asdict(w) for w in word_timestamps],
        pii_regions=[asdict(r) for r in pii_regions],
        has_pii=bool(pii_regions),
        pii_types=pii_types,
    )

    # Write metadata
    metadata_path = AUDIO_DIR / filename.replace(".wav", ".json")
    with open(metadata_path, 'w') as f:
        json.dump(asdict(metadata), f, indent=2)
    print(f"  Metadata: {metadata_path}")

    return metadata


def generate_all_fixtures(use_tts: bool = True):
    """Generate all audio test fixtures.

    Args:
        use_tts: If True, use edge-tts for real speech. If False, use sine waves.
    """
    # Create directories
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    REDACTED_DIR.mkdir(parents=True, exist_ok=True)

    mode = "TTS speech" if (use_tts and EDGE_TTS_AVAILABLE) else "sine waves"
    print(f"\nGenerating audio fixtures ({mode}) in: {AUDIO_DIR}")
    print(f"Generating redacted audio in: {REDACTED_DIR}\n")

    all_metadata = []
    for fixture_config in AUDIO_FIXTURES:
        metadata = generate_fixture(fixture_config, use_tts=use_tts)
        all_metadata.append(asdict(metadata))
        print()  # Blank line between fixtures

    # Write index file
    index_path = AUDIO_DIR / "fixtures_index.json"
    with open(index_path, 'w') as f:
        json.dump({
            "fixtures": all_metadata,
            "total": len(all_metadata),
            "pii_types": list(set(
                pii_type
                for m in all_metadata
                for pii_type in m["pii_types"]
            )),
            "generated_with": "tts" if use_tts else "sine_waves",
        }, f, indent=2)
    print(f"Created index: {index_path}")

    print(f"\n{'='*60}")
    print(f"Generated {len(all_metadata)} audio fixtures using {mode}")
    print(f"Original audio: {AUDIO_DIR}")
    print(f"Redacted audio: {REDACTED_DIR}")
    print(f"{'='*60}")


# Also generate basic test files (for backward compatibility)
def generate_test_fixtures():
    """Generate basic test audio files (sine waves)."""
    # Ensure directories exist
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

    # Simple sine wave for basic pipeline testing
    sine_data = generate_sine_wave(2.0, frequency=440)
    sine_path = FIXTURES_DIR / "test_sine_440hz.wav"
    write_wav(sine_path, sine_data)
    print(f"Generated: {sine_path}")

    # Longer sine wave for async processing tests
    long_sine_data = generate_sine_wave(5.0, frequency=880)
    long_sine_path = FIXTURES_DIR / "test_sine_long.wav"
    write_wav(long_sine_path, long_sine_data)
    print(f"Generated: {long_sine_path}")

    # Silent audio for edge case testing
    silence_data = generate_silence(1.0)
    silence_path = FIXTURES_DIR / "test_silence.wav"
    write_wav(silence_path, silence_data)
    print(f"Generated: {silence_path}")

    print("\nBasic test fixtures generated successfully!")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate test audio files for PII detection testing"
    )
    parser.add_argument(
        "--no-tts",
        action="store_true",
        help="Use sine waves instead of TTS-generated speech"
    )
    parser.add_argument(
        "--basic-only",
        action="store_true",
        help="Only generate basic test fixtures (sine waves)"
    )
    args = parser.parse_args()

    if args.basic_only:
        generate_test_fixtures()
    else:
        generate_test_fixtures()  # Basic test files (always sine waves)
        generate_all_fixtures(use_tts=not args.no_tts)  # PII scenario fixtures
