"""Cloud TTS service using Groq PlayAI API.

Replaces local Kokoro TTS with Groq's PlayAI TTS, eliminating local
model overhead and providing low-latency cloud-based speech synthesis.
"""

import io
import os
from typing import Optional, Tuple

import numpy as np


class GroqTTS:
    """Cloud TTS using Groq's PlayAI API.

    Synthesizes text to audio via Groq, returns numpy array
    suitable for FastRTC WebRTC streaming.
    """

    MAX_TEXT_LENGTH = 2000  # Safety cap matching previous Kokoro limit

    def __init__(self, api_key: Optional[str] = None):
        self._api_key = api_key or os.environ.get("GROQ_API_KEY")
        self._client = None

    def _ensure_client(self) -> None:
        """Lazily initialize the Groq client."""
        if self._client is not None:
            return

        if not self._api_key:
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

    def synthesize(
        self,
        text: str,
        voice: str = "troy",
        model: str = "canopylabs/orpheus-v1-english",
        target_sr: int = 24000,
    ) -> Tuple[np.ndarray, int]:
        """Synthesize text to audio via Groq TTS (Orpheus).

        Args:
            text: Text to synthesize (capped at MAX_TEXT_LENGTH)
            voice: Orpheus voice name (troy, hannah, austin, etc.)
            model: TTS model name
            target_sr: Target sample rate for output

        Returns:
            (audio_int16, sample_rate) — int16 numpy array + sample rate
        """
        import soundfile as sf

        self._ensure_client()

        # Cap text length
        if len(text) > self.MAX_TEXT_LENGTH:
            text = text[:self.MAX_TEXT_LENGTH]

        # Call Groq TTS API
        response = self._client.audio.speech.create(
            model=model,
            voice=voice,
            input=text,
            response_format="wav",
        )

        # Decode WAV response to numpy array
        wav_bytes = response.read()
        buf = io.BytesIO(wav_bytes)
        samples, sr = sf.read(buf, dtype="float32")

        # Handle stereo → mono
        if samples.ndim > 1:
            samples = samples.mean(axis=1)

        # Resample to target rate if needed
        if sr != target_sr:
            from scipy.signal import resample
            num_samples = int(len(samples) * target_sr / sr)
            samples = resample(samples, num_samples).astype(np.float32)
            sr = target_sr

        # Convert to int16 for FastRTC
        audio_int16 = (samples * 32767).astype(np.int16)
        return audio_int16, sr
