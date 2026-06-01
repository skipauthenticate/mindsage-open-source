# MindSage Vector Store

Python FastAPI service for semantic search and ML features. Runs on Jetson Orin Nano with GPU acceleration.

## GPU Memory Management

**Critical**: Jetson Orin Nano has ~7.4GB shared RAM/VRAM. Only one large model can be on GPU at a time.

| Model | Type Enum | Size on GPU | Purpose |
|-------|-----------|-------------|---------|
| Embedding Model | EMBEDDING | ~90MB | Generates embeddings for search/indexing |
| Reranker | RERANKER | ~250MB | Search quality improvement (cross-encoder) |
| Whisper Tiny | TRANSCRIPTION | ~1GB | Audio transcription (speech-to-text) |
| BLIP Base | CAPTION | ~1.5GB | Image captioning (vision-to-text) |
| LPRAG Vocab | LPRAG_VOCAB | ~50MB | Privacy perturbation vocabulary |
| spaCy NER | N/A (CPU only) | ~50MB (CPU) | Entity extraction (shared with PII) |

### Model Manager Pattern

```python
from .model_manager import get_model_manager, ModelType

manager = get_model_manager()

# Before reranker operations (search reranking)
# This will unload the embedding model from GPU if needed
manager.ensure_loaded(ModelType.RERANKER)

# Before audio transcription
manager.ensure_loaded(ModelType.TRANSCRIPTION)

# Before image captioning
manager.ensure_loaded(ModelType.CAPTION)
```

Available model types: `EMBEDDING`, `RERANKER`, `TRANSCRIPTION`, `CAPTION`, `LPRAG_VOCAB`. The manager automatically unloads conflicting models before loading.

## Development

```bash
cd vector-store
source .venv/bin/activate
python -m mcp_vector_store.mcp_server_http --port 8085 --db-path ../data/vectordb
```

Or from the parent directory:
```bash
npm run vector-store:start
```

## Project Structure

```
vector-store/
├── mcp_vector_store/
│   ├── mcp_server_http.py    # HTTP server + REST API (main entry point)
│   ├── mcp_server_stdio.py   # MCP stdio transport wrapper
│   ├── mcp_client.py         # Client for MCP protocol
│   ├── txtai_store.py        # txtai vector store backend
│   ├── txtai_adapter.py      # API compatibility adapter
│   ├── txtai_endpoints.py    # txtai-specific endpoints
│   ├── model_manager.py      # GPU memory management (EMBEDDING, RERANKER, TRANSCRIPTION, CAPTION, LPRAG_VOCAB)
│   ├── async_extractor.py    # Background extraction queue
│   ├── embeddings.py         # Embedding model wrapper (auto-selects by device)
│   ├── topic_labeler.py      # Keyword + embedding topic classification
│   ├── passage_extractor.py  # Embedding-based passage extraction
│   ├── ner_extractor.py      # spaCy NER wrapper for entity extraction
│   ├── reranker.py           # Cross-encoder reranker
│   ├── audio_processor.py    # Whisper audio transcription (speech-to-text)
│   ├── image_processor.py    # BLIP image captioning (vision-to-text)
│   ├── file_processor.py     # File parsing (PDF, text, markdown, audio, image)
│   ├── file_upload.py        # Upload handling
│   ├── markdown_converter.py # Markdown utilities
│   ├── pii_protection.py     # PII detection/anonymization (Presidio)
│   ├── consent_manager.py    # Consent session management
│   ├── consent_config.py     # Consent rules
│   ├── consent_session.py    # Session tracking
│   ├── lprag_config.py       # LPRAG configuration and presets
│   ├── lprag_embeddings.py   # GloVe embeddings for LPRAG
│   ├── lprag_engine.py       # LPRAG perturbation engine
│   ├── voice_rtc_handler.py  # Voice pipeline: STT → RAG → PII → LLM → TTS (All-Groq cloud)
│   ├── groq_stt_service.py   # Groq Whisper STT (cloud transcription)
│   └── groq_tts_service.py   # Groq Orpheus TTS (cloud speech synthesis)
├── tests/
│   ├── test_pii_protection.py       # PII protection tests
│   ├── test_topic_identification.py # Topic classification tests
│   ├── test_topic_identification_integration.py # Topic integration tests
│   ├── test_lprag.py                # LPRAG unit tests
│   ├── test_consent.py              # Consent system tests
│   ├── test_async_extractor.py      # Async extraction tests
│   ├── test_enhanced_search.py      # Enhanced search tests
│   └── test_txtai_integration.py    # txtai integration tests
├── requirements.txt          # Python dependencies
├── download_models.py        # Model download script
├── verify_setup.py           # Environment verification
├── Dockerfile                # Container config (CPU)
└── Dockerfile.jetson         # Container config (Jetson GPU)
```

## API Endpoints (port 8085)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/stats` | Database stats + extraction queue |
| GET | `/api/models` | GPU model loading status |
| POST | `/api/documents` | Add document (async extraction) |
| POST | `/api/documents/batch` | Add multiple documents |
| GET | `/api/documents` | List documents (paginated) |
| GET | `/api/documents/{id}` | Get single document |
| DELETE | `/api/documents/{id}` | Delete document |
| POST | `/api/search` | Vector search |
| POST | `/api/search/enhanced` | Search with passage extraction |
| POST | `/api/graph` | Knowledge graph data |
| GET | `/api/graph/node/{id}` | Get node details |
| GET | `/api/topics` | List all topics |
| GET | `/api/topics/{topic}/documents` | Documents by topic |
| POST | `/api/topics/generate/{doc_id}` | Generate topics |
| POST | `/api/pii/deanonymize` | De-anonymize text with PII tokens |
| GET | `/api/pii/status` | PII protection status |
| GET | `/api/pii/session/{id}` | Get session info (incl. TTL remaining) |
| POST | `/api/pii/session/{id}/refresh` | Refresh session TTL |
| DELETE | `/api/pii/session/{id}` | Clear session |
| POST | `/api/media/upload` | Upload audio/image for transcription/captioning and indexing (500MB limit) |
| GET | `/api/media/status` | Check which media processors are available |
| GET | `/health` | Health check (includes PII status) |
| GET | `/health/pii` | Detailed PII health check |
| GET | `/health/lprag` | LPRAG subsystem health check |
| GET | `/api/lprag/status` | LPRAG status and statistics |
| GET | `/api/lprag/config` | LPRAG configuration info |
| POST | `/api/voice/webrtc/offer` | WebRTC SDP offer for voice connection |
| POST | `/api/voice/disconnect` | Disconnect voice session (close peer connections) |
| GET | `/api/voice/status` | Voice pipeline status (STT/TTS availability) |
| GET | `/api/voice/config` | Get voice configuration (TTS voice) |
| PUT | `/api/voice/config` | Update voice configuration |
| GET | `/api/voice/outputs` | SSE stream for voice text events |

## Voice Pipeline (All-Groq Cloud)

Real-time voice interaction using WebRTC with all processing done via Groq cloud APIs.
No local voice models required — zero GPU overhead for voice mode.

### Architecture

```
Mic → WebRTC → Groq Whisper STT → PII Anonymize → RAG Search → Groq LLM → Groq Orpheus TTS → WebRTC → Speaker
                                        ↓                                         ↓
                                  LPRAG perturbs                          TTS speaks perturbed
                                  names/numbers                           names/numbers (private)
                                        ↓
                                  De-anonymize ONLY for chat UI text display
```

### PII Protection in Voice

The entire system prompt (including RAG excerpts, source names, and filenames) is
anonymized in a single pass before sending to the LLM. This prevents PII leaking
through metadata fields. The LLM responds with perturbed values, TTS speaks them,
and de-anonymization only happens for the chat UI text.

### Key Components

| Component | File | Purpose |
|-----------|------|---------|
| VoiceRTCHandler | `voice_rtc_handler.py` | FastRTC handler: STT → RAG → PII → LLM → TTS pipeline |
| GroqSTT | `groq_stt_service.py` | Cloud STT via Groq Whisper API (`whisper-large-v3`) |
| GroqTTS | `groq_tts_service.py` | Cloud TTS via Groq Orpheus (`canopylabs/orpheus-v1-english`) |

### Configuration

- **TTS Voice**: Configurable via `/api/voice/config` (default: `troy`, options: `troy`, `hannah`, `austin`, etc.)
- **TTS Model**: `canopylabs/orpheus-v1-english` (Groq Orpheus)
- **STT Model**: `whisper-large-v3` (Groq Whisper)
- **Requires**: `GROQ_API_KEY` environment variable or `groqApiKey` in `llm-config.json`

## Async Extraction Flow

```
Document Added
      │
      ▼
┌─────────────────┐
│ Generate embed  │ ← Fast (~100ms)
│ Store in DB     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Queue for       │ ← Returns immediately
│ extraction      │
└────────┬────────┘
         │
         ▼ (background thread)
┌──────────────────┐
│ Extract:         │ ← Uses embedding model + spaCy NER
│ - key_passages   │   (embedding similarity, heuristics)
│ - key_entities   │   (spaCy NER)
│ - topics         │   (weighted keywords + embedding similarity)
│ - doc_filters    │   (heuristics)
│ Update document  │
└──────────────────┘
```

## Media Processing

MindSage supports automatic processing of audio and image files for semantic search. Media files are transcribed/captioned, then indexed into the vector store.

### Supported Media Types

| Type | Extensions | Processor | Model | Output |
|------|------------|-----------|-------|--------|
| Audio | `.mp3`, `.wav`, `.m4a`, `.flac`, `.ogg` | AudioProcessor | Whisper Tiny EN | Transcribed text |
| Image | `.jpg`, `.jpeg`, `.png`, `.gif`, `.bmp`, `.webp` | ImageProcessor | BLIP Base | Caption text |

### Audio Processing (Whisper)

- **Model**: `openai/whisper-tiny.en` (~1GB on GPU)
- **GPU Retry Logic**: 3 attempts with 5s delays if CUDA memory unavailable
- **Features**: Automatic language detection, timestamp support
- **Performance**: ~10x faster on GPU vs CPU

```python
from .audio_processor import AudioProcessor

processor = AudioProcessor()
result = processor.process_audio("audio.mp3")
# result.text = "This is the transcribed text"
# result.processing_time = 2.5
```

### Image Processing (BLIP)

- **Model**: `Salesforce/blip-image-captioning-base` (~1.5GB on GPU)
- **GPU Retry Logic**: 3 attempts with 5s delays if CUDA memory unavailable
- **Decompression Bomb Protection**: PIL.Image.MAX_IMAGE_PIXELS limit
- **Features**: Automatic image resizing, format conversion

```python
from .image_processor import ImageProcessor

processor = ImageProcessor()
result = processor.process_image("photo.jpg")
# result.text = "a person standing on a beach at sunset"
# result.processing_time = 1.2
```

### Upload Flow

```
Media File Upload
      │
      ▼
┌─────────────────┐
│ Detect file type│ ← audio/* or image/* MIME type
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Route to        │ ← AudioProcessor or ImageProcessor
│ media processor │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ ModelManager    │ ← Swap GPU model (TRANSCRIPTION or CAPTION)
│ ensures loaded  │   Retry 3x with 5s delays
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Transcribe/     │ ← Whisper (STT) or BLIP (VTT)
│ Caption         │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Index text into │ ← Standard document indexing flow
│ vector store    │
└─────────────────┘
```

### API Usage

**Upload Media:**
```bash
curl -X POST http://localhost:8085/api/media/upload \
  -F "file=@audio.mp3" \
  -F "source=mobile_recording"
```

**Check Status:**
```bash
curl http://localhost:8085/api/media/status
```

**Response:**
```json
{
  "audio_available": true,
  "image_available": true,
  "audio_model": "openai/whisper-tiny.en",
  "image_model": "Salesforce/blip-image-captioning-base"
}
```

### GPU Memory Management

Media models are managed by ModelManager and automatically swap on/off GPU:

1. **Before processing**: `manager.ensure_loaded(ModelType.TRANSCRIPTION)` or `ModelType.CAPTION`
2. **Automatic unload**: Conflicting models (embedding, reranker) unloaded from GPU
3. **Retry logic**: If CUDA memory unavailable, retry 3x with 5s delays
4. **Fallback to CPU**: If GPU loading fails after retries, uses CPU (slower)

### File Size Limits

- **Max file size**: 500MB (configurable in mcp_server_http.py)
- **Recommended**: Audio <100MB, Images <10MB for optimal performance

## Key Classes

### TopicLabeler
Classifies documents into topics using weighted keyword matching + embedding similarity fallback.

```python
from .topic_labeler import TopicLabeler, DEFAULT_TOPICS

labeler = TopicLabeler(embedding_model=embedding_model, verbose=True)

# Generate topics for text
result = labeler.generate_topics(
    text="Python programming tutorial",
    num_topics=3,
    predefined_topics=DEFAULT_TOPICS
)
# result.topics = ["programming", "education"]
# result.primary_topic = "programming"
# result.confidence = 0.85
# result.method = "weighted_keyword_match"
```

**Classification Flow**:
1. **Weighted keyword matching** - Fast, uses ~300+ keywords with weights (1.0-3.0)
2. **Ambiguity detection** - If confidence < 0.6, triggers ML fallback
3. **Embedding similarity** - Compares document embedding to topic embeddings
4. **Result merging** - Combines keyword and embedding results

### PassageExtractor
Extracts key sentences using embedding similarity (query-time) or heuristics (storage-time).

```python
from .passage_extractor import PassageExtractor

extractor = PassageExtractor(embedding_model=embedding_model, verbose=True)

# Query-time extraction (with search query)
passages = extractor.extract_relevant_passages(
    query="how to sort arrays",
    document_text="...",
    max_excerpt_length=500
)

# Storage-time key sentences (no query)
sentences = extractor.extract_key_sentences(text, max_sentences=5)
```

### SpaCyEntityExtractor
Extracts named entities using spaCy NER (reuses model loaded for PII).

```python
from .ner_extractor import SpaCyEntityExtractor

extractor = SpaCyEntityExtractor(nlp=spacy_model)
entities = extractor.extract_entities("John Smith works at Google")
# entities = {"persons": ["John Smith"], "organizations": ["Google"]}
```

### AudioProcessor
Transcribes audio files using Whisper (speech-to-text).

```python
from .audio_processor import AudioProcessor

processor = AudioProcessor()
result = processor.process_audio("meeting_recording.mp3")
# result.text = "Transcribed text from audio"
# result.processing_time = 2.5
# result.model_name = "openai/whisper-tiny.en"
```

**Features:**
- GPU retry logic (3 attempts, 5s delays)
- Automatic format conversion via ffmpeg
- Integrates with ModelManager for GPU swapping

### ImageProcessor
Generates captions for images using BLIP (vision-to-text).

```python
from .image_processor import ImageProcessor

processor = ImageProcessor()
result = processor.process_image("vacation_photo.jpg")
# result.text = "a beach with palm trees at sunset"
# result.processing_time = 1.2
# result.model_name = "Salesforce/blip-image-captioning-base"
```

**Features:**
- GPU retry logic (3 attempts, 5s delays)
- Decompression bomb protection
- Automatic image resizing and format handling

### AsyncExtractor
Background extraction queue. Documents are indexed immediately, extraction runs async.

```python
# Queue a document for extraction
extractor.queue_extraction(ExtractionTask(
    doc_id=123,
    text="document content...",
    extract_key_passages=True,
    extract_key_entities=True,
    extract_structured_metadata=True,
    extract_topics=True
))

# Check pending count
pending = extractor.get_pending_count()
```

### VectorStore
txtai-based vector store with hybrid search, topic indexing, and pagination.

```python
# Add document (use async extraction pattern in mcp_server_http.py)
result = store.add_document(
    text=text,
    embedding_model=model,
    metadata=metadata,
    skip_duplicates=True,
    extract_key_passages=False,  # Skip sync extraction
    extract_key_entities=False,
)

# Update metadata after async extraction
store.update_document_metadata(doc_id, {
    "key_passages": [...],
    "key_entities": [...],
})

# Update topics (propagates to chunks)
store.update_document_topics(doc_id, topics=["programming"], primary_topic="programming")

# Search
results = store.enhanced_search(query, embedding_model, top_k=10)
```

### ModelManager
Singleton that manages GPU memory by swapping models.

```python
manager = get_model_manager(verbose=True)
manager.register_embedding(embedding_model)
manager.register_reranker(reranker)

# Check status
status = manager.get_status()
# {'embedding': {'is_loaded': True, 'on_gpu': True}, 'reranker': {...}, 'lprag_vocab': {...}}

current = manager.get_current_gpu_model()  # 'embedding' or 'reranker'
```

## Common Issues

### OOM During Model Loading
**Symptom**: `NvMapMemAllocInternalTagged error 12`
**Cause**: Multiple large models loaded simultaneously
**Fix**: Use `model_manager.ensure_loaded()` before model operations

### Extraction Not Updating Documents
**Symptom**: Documents missing `key_entities`, `key_passages`
**Cause**: Async extractor thread crashed or queue backed up
**Fix**: Check `get_pending_count()`, restart server if needed

### Slow Document Addition
**Symptom**: Document add takes 5-10 seconds
**Cause**: Synchronous extraction (old pattern)
**Fix**: Use async extraction pattern - add without extraction, queue task

### Topic Classification Returns "general"
**Symptom**: All documents classified as "general"
**Cause**: Text doesn't contain keywords from WEIGHTED_KEYWORD_MAP
**Fix**: Check text content, add domain-specific keywords if needed

## Testing

```bash
# Activate venv
source .venv/bin/activate

# Run server
python -m mcp_vector_store.mcp_server_http --port 8085

# Test endpoints
curl http://localhost:8085/health
curl http://localhost:8085/api/stats
curl http://localhost:8085/api/models
```

## LPRAG (Locally Private RAG)

LPRAG provides Local Differential Privacy for PII protection. Instead of just replacing PII with opaque tokens, LPRAG perturbs values to semantically similar alternatives.

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    PIIProtector                              │
│  ┌─────────────┐    ┌─────────────┐    ┌──────────────────┐ │
│  │  Presidio   │───▶│ LPRAG Engine │───▶│ Token Session    │ │
│  │  Detection  │    │ Perturbation │    │ (bidirectional)  │ │
│  └─────────────┘    └─────────────┘    └──────────────────┘ │
│                            │                                 │
│           ┌────────────────┼────────────────┐               │
│           ▼                ▼                ▼               │
│    WordModule        NumberModule     PhraseModule          │
│    (exponential)     (Laplace)        (segment-wise)        │
│    names/locations   phone/SSN        email/address         │
└─────────────────────────────────────────────────────────────┘
```

### Perturbation Modules

| Module | PII Types | Mechanism | Example |
|--------|-----------|-----------|---------|
| Word | PERSON, LOCATION | Exponential (semantic similarity) | "John Smith" → "Michael Chen" |
| Number | PHONE, SSN, CREDIT_CARD | Laplace noise | "555-123-4567" → "447-891-2345" |
| Phrase | EMAIL, URL | Segment-wise | "john@example.com" → "mike@sample.org" |

### Configuration

**LPRAG hybrid mode is enabled by default.**

```bash
# Environment variables
LPRAG_MODE=hybrid        # disabled | pure | hybrid
LPRAG_PRESET=default     # minimal | default | aggressive
LPRAG_EPSILON=1.0        # Global epsilon override
LPRAG_USE_GPU=false      # GPU for semantic similarity
```

### Key Classes

#### LPRAGEngine

Orchestrates perturbation across modules with adaptive privacy budget.

```python
from mcp_vector_store.lprag_engine import get_lprag_engine

engine = get_lprag_engine()
result = engine.perturb_entity("John Smith", "PERSON")
# result.perturbed_value = "Michael Chen"
# result.epsilon_used = 1.0
```

#### PIIProtector (with LPRAG)

Integrates LPRAG into the PII anonymization flow.

```python
from mcp_vector_store.pii_protection import PIIProtector, PIIProtectorMode

protector = PIIProtector(mode=PIIProtectorMode.LPRAG_HYBRID)
result = protector.anonymize("Email from John Smith at john@example.com")
# result.anonymized_text = "Email from Michael Chen at mike@sample.org"
# Bidirectional session mapping stored for de-anonymization
```

### Memory Usage

| Component | Memory | Device |
|-----------|--------|--------|
| Presidio + spaCy | ~150MB | CPU |
| GloVe 50-dim | ~50MB | CPU (lazy loaded) |
| LPRAG Engine | ~5MB | CPU |
| **Total** | **~205MB** | CPU |

### Graceful Degradation

LPRAG falls back to token-based anonymization when:
- Entity type not supported (custom recognizers)
- No similar words in vocabulary
- gensim not installed
- Embeddings fail to load

```python
# Fallback example: unsupported entity type
"John Smith" → "Michael Chen"  # LPRAG perturbs PERSON
"ABC-CUSTOM-123" → "<PII:CUSTOM:xyz>"  # Falls back to token
```
