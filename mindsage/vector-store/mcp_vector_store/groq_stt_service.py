"""Cloud STT service using Groq Whisper API.

When Groq STT is selected, audio is transcribed in the cloud instead of
using local faster-whisper, saving ~400MB GPU memory on Jetson.
"""

import io
import os
import tempfile
from typing import Optional

import numpy as np


class GroqSTT:
    """Cloud STT using Groq's Whisper API.

    Accepts audio as numpy array (from FastRTC) or WAV bytes,
    sends to Groq for transcription.
    """

    def __init__(self, api_key: Optional[str] = None):
        self._api_key = api_key or os.environ.get("GROQ_API_KEY")
        self._client = None

    def _ensure_client(self) -> None:
        """Lazily initialize the Groq client."""
        if self._client is not None:
            return

        if not self._api_key:
            # Try reading from llm-config.json
            self._api_key = self._read_api_key_from_config()

        if not self._api_key:
            raise RuntimeError(
                "Groq API key not configured. Set GROQ_API_KEY or configure in LLM settings."
            )

        from groq import Groq
        self._client = Groq(api_key=self._api_key)

    def _read_api_key_from_config(self) -> Optional[str]:
        """Read Groq API key from llm-config.json."""
        import json
        config_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..", "..", "data", "llm-config.json",
        )
        try:
            with open(config_path) as f:
                config = json.load(f)
            return config.get("groqApiKey")
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    def transcribe_audio_array(
        self,
        sample_rate: int,
        audio: np.ndarray,
        language: str = "en",
    ) -> str:
        """Transcribe audio numpy array via Groq Whisper API.

        Args:
            sample_rate: Audio sample rate (e.g., 16000, 48000)
            audio: Audio samples as float32 or int16 numpy array
            language: Language code

        Returns:
            Transcribed text string
        """
        import soundfile as sf

        self._ensure_client()

        # Convert to WAV bytes in memory
        buf = io.BytesIO()
        # FastRTC ReplyOnPause passes audio as shape (1, N) — squeeze to 1D
        audio = np.squeeze(audio)
        # Ensure float32 for soundfile
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32) / 32768.0
        sf.write(buf, audio, sample_rate, format="WAV")
        buf.seek(0)

        # Call Groq Whisper API
        transcription = self._client.audio.transcriptions.create(
            file=("audio.wav", buf.read()),
            model="whisper-large-v3",
            language=language,
            response_format="text",
        )

        return transcription.strip() if isinstance(transcription, str) else str(transcription).strip()

    def transcribe_bytes(
        self,
        audio_bytes: bytes,
        content_type: str = "audio/wav",
        language: str = "en",
    ) -> str:
        """Transcribe audio bytes via Groq Whisper API.

        Args:
            audio_bytes: Raw audio file bytes
            content_type: MIME type
            language: Language code

        Returns:
            Transcribed text string
        """
        self._ensure_client()

        ext_map = {
            "audio/webm": "webm",
            "audio/ogg": "ogg",
            "audio/wav": "wav",
            "audio/x-wav": "wav",
            "audio/mpeg": "mp3",
            "audio/mp4": "m4a",
            "audio/flac": "flac",
        }
        ext = ext_map.get(content_type, "wav")

        transcription = self._client.audio.transcriptions.create(
            file=(f"audio.{ext}", audio_bytes),
            model="whisper-large-v3",
            language=language,
            response_format="text",
        )

        return transcription.strip() if isinstance(transcription, str) else str(transcription).strip()
