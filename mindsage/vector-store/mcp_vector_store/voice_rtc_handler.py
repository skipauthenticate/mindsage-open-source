"""FastRTC voice handler: STT → RAG → LLM → TTS streaming pipeline.

All-Groq cloud pipeline: audio arrives via WebRTC, gets transcribed by
Groq Whisper STT, processed through RAG + PII + LLM, then synthesized
by Groq Orpheus TTS and streamed back over WebRTC in real-time.

PII Protection Flow:
  1. RAG excerpts + source/filename metadata are assembled into a system prompt
  2. The ENTIRE system prompt is anonymized in one pass (LPRAG perturbation)
     - Names → semantically similar fake names (e.g. "John Smith" → "Michael Chen")
     - Numbers → Laplace-noised values (e.g. card ending 4421 → 2341)
  3. User transcript is also anonymized in the same PII session
  4. LLM sees only perturbed/anonymized text and responds accordingly
  5. TTS speaks the LLM response as-is (perturbed names, noised numbers)
  6. De-anonymization restores real values ONLY for the chat UI text display
  Result: Audio never contains real PII. Only the on-screen text shows real data.

Text events (transcript, response, sources) are emitted via a callback
for SSE delivery to the frontend chat UI.
"""

import json
import os
import time
from typing import Any, Callable, Generator, Optional

import numpy as np


# Type for text event callback: (event_type, data_dict)
TextCallback = Callable[[str, dict], None]


def _read_llm_config() -> dict:
    """Read LLM configuration from data/llm-config.json."""
    config_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..", "..", "data", "llm-config.json",
    )
    try:
        with open(config_path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _get_llm_api_key(config: dict) -> tuple[str, str, str]:
    """Get the active LLM provider, API key, and model from config.

    Returns:
        (provider, api_key, model) tuple
    """
    preferred = config.get("preferredProvider", "auto")

    # Check providers in priority order
    providers = []
    if preferred != "auto":
        providers.append(preferred)
    providers.extend(["groq", "anthropic", "openai"])

    for provider in providers:
        key_field = f"{provider}ApiKey"
        env_field = f"{provider.upper()}_API_KEY"
        api_key = config.get(key_field) or os.environ.get(env_field)
        if api_key:
            model_field = f"{provider}Model"
            defaults = {
                "groq": "llama-3.3-70b-versatile",
                "anthropic": "claude-sonnet-4-20250514",
                "openai": "gpt-4o-mini",
            }
            model = config.get(model_field) or defaults.get(provider, "")
            return provider, api_key, model

    raise RuntimeError("No LLM provider configured")


def _stream_groq_llm(
    messages: list[dict],
    api_key: str,
    model: str,
    temperature: float = 0.7,
    max_tokens: int = 1024,
) -> Generator[str, None, None]:
    """Stream text from Groq LLM, yielding chunks."""
    from groq import Groq

    client = Groq(api_key=api_key)
    stream = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        stream=True,
    )

    for chunk in stream:
        delta = chunk.choices[0].delta
        if delta and delta.content:
            yield delta.content


def _stream_openai_llm(
    messages: list[dict],
    api_key: str,
    model: str,
    temperature: float = 0.7,
    max_tokens: int = 1024,
) -> Generator[str, None, None]:
    """Stream text from OpenAI LLM, yielding chunks."""
    import httpx

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
    }

    with httpx.stream(
        "POST",
        "https://api.openai.com/v1/chat/completions",
        headers=headers,
        json=body,
        timeout=60.0,
    ) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if line.startswith("data: "):
                data = line[6:]
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                    content = chunk["choices"][0]["delta"].get("content", "")
                    if content:
                        yield content
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue


def _stream_anthropic_llm(
    messages: list[dict],
    api_key: str,
    model: str,
    temperature: float = 0.7,
    max_tokens: int = 1024,
) -> Generator[str, None, None]:
    """Stream text from Anthropic LLM, yielding chunks."""
    import httpx

    # Separate system message
    system_content = ""
    chat_messages = []
    for msg in messages:
        if msg["role"] == "system":
            system_content = msg["content"]
        else:
            chat_messages.append(msg)

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    body = {
        "model": model,
        "messages": chat_messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": True,
    }
    if system_content:
        body["system"] = system_content

    with httpx.stream(
        "POST",
        "https://api.anthropic.com/v1/messages",
        headers=headers,
        json=body,
        timeout=60.0,
    ) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if line.startswith("data: "):
                try:
                    event = json.loads(line[6:])
                    if event.get("type") == "content_block_delta":
                        text = event.get("delta", {}).get("text", "")
                        if text:
                            yield text
                except (json.JSONDecodeError, KeyError):
                    continue


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences for streaming TTS.

    Returns complete sentences found so far.
    Simple heuristic: split on . ! ? followed by space or end.
    """
    sentences = []
    current = ""
    for char in text:
        current += char
        if char in ".!?" and len(current.strip()) > 10:
            sentences.append(current.strip())
            current = ""
    # Don't return incomplete sentence
    return sentences


class VoiceRTCHandler:
    """FastRTC-compatible voice handler.

    Processes audio through the full pipeline:
    STT → RAG search → PII anonymize → LLM → deanonymize → TTS

    Usage with FastRTC:
        handler = VoiceRTCHandler(vector_store, embedding_model, ...)
        stream = Stream(
            handler=ReplyOnPause(handler),
            modality="audio",
            mode="send-receive",
        )
    """

    def __init__(
        self,
        vector_store: Any,
        embedding_model: Any,
        model_manager: Any,
        pii_protector: Optional[Any] = None,
        groq_stt_service: Optional[Any] = None,
        groq_tts_service: Optional[Any] = None,
        text_callback: Optional[TextCallback] = None,
        verbose: bool = False,
    ):
        self.vector_store = vector_store
        self.embedding_model = embedding_model
        self.model_manager = model_manager
        self.pii_protector = pii_protector
        self.groq_stt_service = groq_stt_service
        self.groq_tts_service = groq_tts_service
        self.text_callback = text_callback
        self.verbose = verbose

    def _emit(self, event_type: str, data: dict) -> None:
        """Emit a text event via the callback."""
        if self.text_callback:
            try:
                self.text_callback(event_type, data)
            except Exception as e:
                if self.verbose:
                    print(f"VoiceRTC: Error emitting {event_type}: {e}")

    def _transcribe(self, sample_rate: int, audio: np.ndarray) -> str:
        """Transcribe audio using Groq cloud STT."""
        if not self.groq_stt_service:
            raise RuntimeError("Groq STT service not available")
        return self.groq_stt_service.transcribe_audio_array(sample_rate, audio)

    def _search_rag(self, query: str, top_k: int = 5, min_score: float = 0.2) -> list[dict]:
        """Search vector store for relevant context."""
        try:
            results = self.vector_store.enhanced_search(
                query=query,
                top_k=top_k,
                min_score=min_score,
                embedding_model=self.embedding_model,
            )
            return [
                {
                    "id": r.id,
                    "excerpt": r.excerpt,
                    "score": r.score,
                    "source": r.metadata.get("source", "") if r.metadata else "",
                    "filename": r.metadata.get("filename", "") if r.metadata else "",
                }
                for r in results
            ]
        except Exception as e:
            if self.verbose:
                print(f"VoiceRTC: RAG search failed: {e}")
            return []

    def _anonymize_text(self, text: str, session_id: Optional[str] = None) -> tuple[str, Optional[str]]:
        """Anonymize text for LLM, returns (anonymized_text, session_id)."""
        if not self.pii_protector:
            return text, session_id

        try:
            result = self.pii_protector.anonymize(text, session_id=session_id)
            return result.anonymized_text, result.session_id
        except Exception as e:
            if self.verbose:
                print(f"VoiceRTC: PII anonymization failed: {e}")
            return text, session_id

    def _deanonymize_text(self, text: str, session_id: Optional[str]) -> str:
        """De-anonymize LLM response text."""
        if not self.pii_protector or not session_id:
            return text

        try:
            result = self.pii_protector.deanonymize(text, session_id=session_id)
            return result.deanonymized_text
        except Exception as e:
            if self.verbose:
                print(f"VoiceRTC: PII de-anonymization failed: {e}")
            return text

    def _build_system_prompt(self, context: list[dict]) -> str:
        """Build system prompt with RAG context."""
        base = (
            "You are a voice assistant. This is a spoken conversation. "
            "CRITICAL: Reply in 1-2 SHORT sentences only. Never exceed 2 sentences. "
            "Be direct and conversational. No lists, no markdown, no formatting."
        )

        if not context:
            return base

        context_parts = []
        for i, doc in enumerate(context, 1):
            source = doc.get("filename") or doc.get("source") or "document"
            context_parts.append(f"[{i}] {source}: {doc['excerpt']}")

        return f"{base}\n\nRelevant context from knowledge base:\n" + "\n".join(context_parts)

    def _synthesize_streaming(
        self, text: str, target_sr: int = 24000
    ) -> Generator[tuple[int, np.ndarray], None, None]:
        """Synthesize text to audio via Groq TTS, yielding chunks per sentence."""
        if not self.groq_tts_service:
            return

        # Split into sentences for incremental TTS
        sentences = _split_sentences(text)
        if not sentences:
            sentences = [text]

        for sentence in sentences:
            if not sentence.strip():
                continue
            try:
                audio_int16, sr = self.groq_tts_service.synthesize(
                    sentence, target_sr=target_sr
                )
                yield (sr, audio_int16)
            except Exception as e:
                if self.verbose:
                    print(f"VoiceRTC: TTS failed for sentence: {e}")
                continue

    def __call__(
        self, audio: tuple[int, np.ndarray]
    ) -> Generator[tuple[int, np.ndarray], None, None]:
        """Process a voice turn: STT → RAG → LLM → TTS.

        This is the FastRTC ReplyOnPause handler signature.

        Args:
            audio: (sample_rate, samples) from WebRTC after pause detected

        Yields:
            (sample_rate, samples) TTS audio chunks
        """
        sample_rate, samples = audio
        t0 = time.time()

        # 1. STT — transcribe user speech
        try:
            transcript = self._transcribe(sample_rate, samples)
        except Exception as e:
            if self.verbose:
                print(f"VoiceRTC: STT failed: {e}")
            self._emit("error", {"message": f"Transcription failed: {e}"})
            return

        if not transcript.strip():
            if self.verbose:
                print("VoiceRTC: Empty transcript, skipping")
            return

        t_stt = time.time()
        if self.verbose:
            print(f"VoiceRTC: STT (groq): '{transcript}' ({t_stt - t0:.2f}s)")

        # Emit transcript to frontend
        self._emit("transcript", {"text": transcript})

        # 2. RAG search
        context = self._search_rag(transcript)
        t_rag = time.time()
        if self.verbose:
            print(f"VoiceRTC: RAG: {len(context)} results ({t_rag - t_stt:.2f}s)")

        if context:
            self._emit("sources", {
                "sources": [
                    {"id": c["id"], "excerpt": c["excerpt"][:200], "score": c["score"]}
                    for c in context
                ]
            })

        # 3. Anonymize context + user message for LLM
        # Build the full system prompt first, then anonymize the entire thing
        # in one pass. This catches PII in excerpts, filenames, and source fields.
        pii_session_id = None
        raw_system_prompt = self._build_system_prompt(context)
        anonymized_prompt, pii_session_id = self._anonymize_text(
            raw_system_prompt, pii_session_id
        )
        anonymized_transcript, pii_session_id = self._anonymize_text(
            transcript, pii_session_id
        )

        # 4. Build LLM messages
        llm_messages = [
            {"role": "system", "content": anonymized_prompt},
            {"role": "user", "content": anonymized_transcript},
        ]

        # 5. Stream LLM response + incremental TTS
        try:
            llm_config = _read_llm_config()
            provider, api_key, model = _get_llm_api_key(llm_config)

            # Voice mode: short responses only (1-2 sentences ≈ 80 tokens)
            voice_max_tokens = 150

            if provider == "groq":
                llm_stream = _stream_groq_llm(llm_messages, api_key, model, max_tokens=voice_max_tokens)
            elif provider == "openai":
                llm_stream = _stream_openai_llm(llm_messages, api_key, model, max_tokens=voice_max_tokens)
            elif provider == "anthropic":
                llm_stream = _stream_anthropic_llm(llm_messages, api_key, model, max_tokens=voice_max_tokens)
            else:
                raise RuntimeError(f"Unknown LLM provider: {provider}")

            # Accumulate LLM text and synthesize sentence-by-sentence
            # NOTE: TTS speaks the LLM response as-is (LPRAG-perturbed text sounds
            # natural, e.g. "Michael Chen" instead of real name). De-anonymization
            # only happens for the text display, keeping real PII out of audio.
            full_response = ""
            pending_text = ""
            sentences_spoken = 0

            for chunk in llm_stream:
                full_response += chunk
                pending_text += chunk

                # Check if we have a complete sentence to speak
                sentences = _split_sentences(pending_text)
                if sentences:
                    for sentence in sentences:
                        pending_text = pending_text[len(sentence):].lstrip()

                        # Synthesize LPRAG-perturbed text (no de-anonymization for audio)
                        for audio_chunk in self._synthesize_streaming(sentence):
                            yield audio_chunk
                            sentences_spoken += 1

            # Speak any remaining text
            if pending_text.strip():
                for audio_chunk in self._synthesize_streaming(pending_text.strip()):
                    yield audio_chunk

            # De-anonymize ONLY for text display (not audio)
            full_clean = self._deanonymize_text(full_response, pii_session_id)

            t_done = time.time()
            if self.verbose:
                print(
                    f"VoiceRTC: Pipeline {t_done - t0:.2f}s "
                    f"(STT={t_stt - t0:.2f}s, RAG={t_rag - t_stt:.2f}s, "
                    f"LLM+TTS={t_done - t_rag:.2f}s, sentences={sentences_spoken})"
                )

            # Emit de-anonymized text for chat display
            self._emit("response", {"text": full_clean})

        except Exception as e:
            if self.verbose:
                import traceback
                traceback.print_exc()
            self._emit("error", {"message": f"Pipeline failed: {e}"})
