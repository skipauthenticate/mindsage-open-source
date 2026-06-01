# Audio PII Redaction Architecture

This document describes the audio PII redaction system for MindSage, including the end-to-end flow from ingestion to user display and LLM interactions.

## Overview

MindSage processes audio files containing sensitive information (voicemails with SSNs, recordings with names/addresses, etc.) and must:

1. **Protect PII during LLM interactions** - Redacted transcripts sent to external LLMs (GPT-4, Claude)
2. **Preserve user access** - Original transcripts available to the user in Explore tab
3. **Maintain searchability** - Embeddings generated from redacted transcripts for semantic search
4. **Audio file redaction (Phase 2)** - Muted/beeped audio file for playback and future audio-capable LLMs

## Architecture Summary

```
                         INGESTION FLOW
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│  ┌─────────────┐    ┌─────────────────┐    ┌─────────────────────────────┐ │
│  │   Upload    │───▶│ AudioProcessor  │───▶│  Sequential Processing      │ │
│  │   Audio     │    │                 │    │                             │ │
│  └─────────────┘    └─────────────────┘    │  ┌─────────────────────┐    │ │
│                                            │  │ whisper-timestamped │    │ │
│                                            │  │ (word-level times)  │    │ │
│                                            │  └──────────┬──────────┘    │ │
│                                            │             │               │ │
│                                            │  ┌─────────────────────┐    │ │
│                                            │  │ Presidio PII Detect │    │ │
│                                            │  │ (on transcript)     │    │ │
│                                            │  └──────────┬──────────┘    │ │
│                                            │             │               │ │
│                                            │  ┌─────────────────────┐    │ │
│                                            │  │ Transcript Redaction│    │ │
│                                            │  │ (replace with tags) │    │ │
│                                            │  └──────────┬──────────┘    │ │
│                                            │             │               │ │
│                                            │  ┌─────────────────────┐    │ │
│                                            │  │ Audio Redaction     │    │ │
│                                            │  │ (pydub silence)     │    │ │
│                                            │  └──────────┬──────────┘    │ │
│                                            └─────────────┼───────────────┘ │
│                                                          │                 │
└──────────────────────────────────────────────────────────┼─────────────────┘
                                                           │
                                                           ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                            STORAGE                                          │
│                                                                             │
│  data/                                                                      │
│  ├── uploads/audio/           ← Original audio files (user playback)       │
│  │   └── audio_abc123.mp3                                                  │
│  ├── redacted/audio/          ← Redacted audio files (optional)            │
│  │   └── audio_abc123_redacted.mp3                                         │
│  └── vectordb/                ← txtai index with metadata                  │
│      └── documents contain:                                                │
│          - original_transcript: "Hi, I'm John Smith, call me at 555-1234"  │
│          - redacted_transcript: "Hi, I'm [PERSON], call me at [PHONE]"     │
│          - pii_regions: [{type, start_time, end_time, text, confidence}]   │
│          - original_audio_path: "uploads/audio/audio_abc123.mp3"           │
│          - redacted_audio_path: "redacted/audio/audio_abc123_redacted.mp3" │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Data Flow: Original vs Redacted

### Critical Requirement: LLM Safety

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        USAGE CONTEXT ROUTING                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   EXPLORE TAB (User Viewing)           CHAT (LLM Context)                  │
│   ─────────────────────────           ──────────────────────               │
│                                                                             │
│   ┌─────────────────────┐             ┌─────────────────────┐              │
│   │  Original Audio     │             │  Redacted Audio     │              │
│   │  (playback)         │             │  (if transcribed    │              │
│   └─────────────────────┘             │   by LLM)           │              │
│                                       └─────────────────────┘              │
│   ┌─────────────────────┐             ┌─────────────────────┐              │
│   │ Original Transcript │             │ Redacted Transcript │              │
│   │ "Hi, I'm John Smith │             │ "Hi, I'm [PERSON],  │              │
│   │  call me at         │             │  call me at         │              │
│   │  555-123-4567"      │             │  [PHONE_NUMBER]"    │              │
│   └─────────────────────┘             └─────────────────────┘              │
│                                                                             │
│   User sees full details              LLM never sees PII                   │
│   for their own files                 External APIs are safe               │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Why Two Transcripts?

| Field | Purpose | Stored In | Used By |
|-------|---------|-----------|---------|
| `original_transcript` | User viewing in Explore tab | Document metadata | Frontend DocumentViewer |
| `redacted_transcript` | LLM context, embeddings, search | Document content + embeddings | RAG pipeline, Chat |

**Security principle**: The `redacted_transcript` is what gets embedded and sent to LLMs. The `original_transcript` is metadata-only, never leaves the device for LLM processing.

### What Gets Sent to LLMs (by Phase)

| Phase | LLM Type | What's Sent | Example |
|-------|----------|-------------|---------|
| **Phase 1** | Text LLMs (GPT-4, Claude) | `redacted_transcript` | `"Hi, I'm [PERSON], call me at [PHONE_NUMBER]"` |
| **Phase 2** | Audio-capable LLMs (GPT-4o, Gemini) | `redacted_audio_path` | Audio file with beeps over PII |

**Phase 1 covers 99% of use cases** since most LLM interactions use text transcripts. Phase 2 adds audio file redaction for:
- User playback of redacted version
- Future audio-native LLM integrations
- Export/sharing without exposing PII

## Approach: whisper-timestamped

### Why whisper-timestamped (Not WhisperX)

| Criteria | whisper-timestamped | WhisperX |
|----------|---------------------|----------|
| **Additional VRAM** | 0 (uses existing model) | +0.5-1GB (wav2vec2) |
| **Jetson 8GB fit** | Yes | Risky |
| **Word timestamps** | Yes | Yes (more accurate) |
| **Speaker diarization** | No | Yes |
| **Complexity** | Low | Medium |

**Decision**: Use `whisper-timestamped` for Jetson compatibility. Same Whisper tiny.en model (~1GB VRAM), just different inference code for word-level timestamps.

### Memory Budget (Jetson Orin Nano 8GB)

| Component | GPU VRAM | Notes |
|-----------|----------|-------|
| Whisper (tiny.en) | ~1.0GB | Same as current |
| whisper-timestamped overhead | 0 | Wrapper only |
| pydub (audio processing) | 0 | CPU-only |
| **Total for audio PII** | **~1.0GB** | No change from current |

## Implementation Components

### 1. AudioPIIRedactor (NEW)

Location: `vector-store/mcp_vector_store/audio_pii_redactor.py`

```python
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
class AudioRedactionResult:
    """Result of audio PII redaction."""
    original_transcript: str           # Full transcript with PII
    redacted_transcript: str           # Transcript with PII replaced
    pii_regions: List[AudioPIIRegion]  # Detected regions with timestamps
    redacted_audio_path: Optional[str] # Path to muted audio (if enabled)
    has_pii: bool                      # Quick check flag
    processing_time_ms: float          # Performance tracking

class AudioPIIRedactor:
    """Detect and redact PII from audio transcriptions."""

    def __init__(
        self,
        pii_protector: PIIProtector,
        whisper_model: str = "tiny.en",
        redaction_style: str = "brackets",  # "brackets" or "placeholder"
        mute_audio: bool = False,           # Create muted audio file
        mute_style: str = "silence",        # "silence", "beep", "noise"
    ): ...

    def transcribe_with_timestamps(
        self,
        audio_path: str
    ) -> Tuple[str, List[WordTimestamp]]:
        """Transcribe audio with word-level timestamps."""
        ...

    def detect_pii_regions(
        self,
        transcript: str,
        word_timestamps: List[WordTimestamp]
    ) -> List[AudioPIIRegion]:
        """Detect PII and map to audio timestamps."""
        ...

    def redact_transcript(
        self,
        transcript: str,
        pii_regions: List[AudioPIIRegion]
    ) -> str:
        """Replace PII in transcript with redaction tags."""
        ...

    def redact_audio(
        self,
        audio_path: str,
        pii_regions: List[AudioPIIRegion],
        output_path: str
    ) -> str:
        """Create audio file with PII segments muted."""
        ...

    def process(
        self,
        audio_path: str
    ) -> AudioRedactionResult:
        """Full pipeline: transcribe, detect, redact."""
        ...
```

### 2. Word Timestamp Structure

```python
@dataclass
class WordTimestamp:
    """A word with its timing information."""
    word: str
    start: float  # seconds
    end: float    # seconds
    confidence: float
```

### 3. PII-to-Timestamp Mapping

The key challenge is mapping text PII positions to audio timestamps:

```
Transcript: "Hi, I'm John Smith, call me at 555-123-4567"
                   ^^^^^^^^^^              ^^^^^^^^^^^^
                   PERSON (0.8-1.4s)       PHONE (2.1-2.8s)

Word timestamps from whisper-timestamped:
  [0.0-0.2] "Hi,"
  [0.2-0.4] "I'm"
  [0.5-0.8] "John"      ← PII start
  [0.8-1.4] "Smith,"    ← PII end
  [1.4-1.6] "call"
  [1.6-1.8] "me"
  [1.8-2.0] "at"
  [2.1-2.8] "555-123-4567"  ← PHONE PII

Redacted transcript: "Hi, I'm [PERSON], call me at [PHONE_NUMBER]"
Audio mute regions: [(0.5, 1.4), (2.1, 2.8)]
```

## Integration with Existing AudioProcessor

### Current audio_processor.py

```python
# Current implementation (line 192-197)
result = self._pipeline(
    file_path,
    chunk_length_s=chunk_length_s,
    return_timestamps=False,  # Currently disabled
)
```

### Modified audio_processor.py

```python
def transcribe_with_pii_redaction(
    self,
    file_path: str,
    redact_pii: bool = True
) -> Dict[str, Any]:
    """Transcribe audio with optional PII redaction.

    Returns:
        Dict with:
        - original_transcript: Full text (for Explore tab)
        - redacted_transcript: PII replaced (for LLM/embeddings)
        - pii_regions: List of detected PII with timestamps
        - has_pii: Boolean flag
    """
    if not redact_pii:
        # Existing behavior
        return {"text": self.transcribe(file_path)}

    # Use AudioPIIRedactor for full pipeline
    redactor = get_audio_pii_redactor()
    result = redactor.process(file_path)

    return {
        "original_transcript": result.original_transcript,
        "redacted_transcript": result.redacted_transcript,
        "pii_regions": [asdict(r) for r in result.pii_regions],
        "has_pii": result.has_pii,
        "redacted_audio_path": result.redacted_audio_path,
    }
```

## Document Metadata Schema

### Vector Document Fields (Audio)

```json
{
  "id": "audio_abc123",
  "content": "[Audio transcription (2:34)]\n\nHi, I'm [PERSON], call me at [PHONE_NUMBER]...",
  "metadata": {
    "media_type": "audio",
    "format": "mp3",
    "duration_seconds": 154,
    "sample_rate": 44100,
    "channels": 2,
    "transcription_model": "openai/whisper-tiny.en",

    "original_transcript": "Hi, I'm John Smith, call me at 555-123-4567...",
    "redacted_transcript": "Hi, I'm [PERSON], call me at [PHONE_NUMBER]...",

    "has_pii": true,
    "pii_types_found": ["PERSON", "PHONE_NUMBER"],
    "pii_regions": [
      {
        "start_time": 0.5,
        "end_time": 1.4,
        "pii_type": "PERSON",
        "original_text": "John Smith",
        "replacement_text": "[PERSON]",
        "confidence": 0.95
      },
      {
        "start_time": 2.1,
        "end_time": 2.8,
        "pii_type": "PHONE_NUMBER",
        "original_text": "555-123-4567",
        "replacement_text": "[PHONE_NUMBER]",
        "confidence": 0.98
      }
    ],

    "original_audio_path": "uploads/audio/audio_abc123.mp3",
    "redacted_audio_path": "redacted/audio/audio_abc123_redacted.mp3",

    "redaction_pending": false,
    "redaction_complete": true
  }
}
```

### Key Distinction

| Field | Location | Purpose |
|-------|----------|---------|
| `content` | Document body | Contains `redacted_transcript` - used for embeddings and LLM |
| `original_transcript` | Metadata only | Never embedded, only for user display in Explore |

## RAG Pipeline Integration

### buildRAGContext() Modification

```typescript
// In server/services/rag.ts

async function buildRAGContext(documents: VectorDocument[]): Promise<ChatContext> {
  const context: ChatContext = { texts: [], images: [], audio: [] };

  for (const doc of documents) {
    if (doc.metadata.media_type === 'audio') {
      // CRITICAL: Use redacted_transcript for LLM, never original
      context.texts.push({
        source: doc.metadata.original_filename,
        content: doc.metadata.redacted_transcript || doc.content,
        // Note: original_transcript is NOT included here
      });

      // If audio-capable LLM (future), use redacted audio path
      if (ENABLE_AUDIO_RAG && doc.metadata.redacted_audio_path) {
        context.audio.push({
          path: doc.metadata.redacted_audio_path,
          // Never send original_audio_path to LLM
        });
      }
    }
  }

  return context;
}
```

## Frontend Integration

### DocumentViewer for Audio

```tsx
// In components/explore/DocumentViewer.tsx

function AudioDocumentView({ doc }: { doc: VectorDocument }) {
  const [showRedacted, setShowRedacted] = useState(false);

  // Display the ORIGINAL transcript to the user
  const displayTranscript = showRedacted
    ? doc.metadata.redacted_transcript
    : doc.metadata.original_transcript;

  return (
    <div>
      {/* Audio Player - plays original audio */}
      <AudioPlayer src={`/api/files/${doc.metadata.original_audio_path}`} />

      {/* PII Status Badge */}
      {doc.metadata.redaction_pending ? (
        <Badge variant="warning">
          <Loader2 className="animate-spin" />
          Scanning for PII...
        </Badge>
      ) : doc.metadata.has_pii ? (
        <Badge variant="destructive">PII Detected ({doc.metadata.pii_types_found.join(', ')})</Badge>
      ) : (
        <Badge variant="success">No PII</Badge>
      )}

      {/* Transcript Toggle */}
      <Tabs value={showRedacted ? 'redacted' : 'original'}>
        <TabsList>
          <TabsTrigger value="original">Original</TabsTrigger>
          <TabsTrigger
            value="redacted"
            disabled={!doc.metadata.has_pii}
          >
            Redacted
          </TabsTrigger>
        </TabsList>
        <TabsContent>
          <TranscriptView
            text={displayTranscript}
            piiRegions={showRedacted ? [] : doc.metadata.pii_regions}
            highlightPii={!showRedacted}
          />
        </TabsContent>
      </Tabs>

      {/* Info: What LLM sees */}
      <Alert>
        <InfoIcon />
        <AlertDescription>
          Chat and search use the redacted version to protect your privacy.
        </AlertDescription>
      </Alert>
    </div>
  );
}
```

### PII Highlighting in Transcript

```tsx
function TranscriptView({ text, piiRegions, highlightPii }) {
  if (!highlightPii || piiRegions.length === 0) {
    return <p>{text}</p>;
  }

  // Highlight PII regions with colored backgrounds
  // Show tooltip with PII type on hover
  return (
    <p>
      {segments.map((segment, i) => (
        segment.isPii ? (
          <Tooltip key={i} content={`${segment.piiType} (redacted in chat)`}>
            <span className="bg-destructive/20 px-1 rounded">
              {segment.text}
            </span>
          </Tooltip>
        ) : (
          <span key={i}>{segment.text}</span>
        )
      ))}
    </p>
  );
}
```

## Environment Configuration

```yaml
# docker-compose.yml / docker-compose.jetson.yml

vector-store:
  environment:
    # PII Protection Configuration
    - PII_ENTITIES=strict                   # "minimal", "default", "strict", or list
    - LPRAG_MODE=hybrid                     # "disabled", "hybrid", "pure"

    # Audio PII Redaction
    - AUDIO_PII_ENABLED=true
    - AUDIO_PII_REDACTION_STYLE=lprag       # "brackets", "placeholder", or "lprag"
    - AUDIO_PII_MUTE_AUDIO=false            # Create muted audio file
    - AUDIO_PII_MUTE_STYLE=silence          # "silence", "beep", "noise"

    # Whisper settings (existing)
    - WHISPER_MODEL=openai/whisper-tiny.en
```

### Configuration Options

| Variable | Values | Default | Description |
|----------|--------|---------|-------------|
| `LPRAG_MODE` | `disabled`, `hybrid`, `pure` | `hybrid` | Global LPRAG mode for semantic perturbation |
| `AUDIO_PII_ENABLED` | `true`, `false` | `true` | Enable audio PII detection |
| `AUDIO_PII_REDACTION_STYLE` | `brackets`, `placeholder`, `lprag` | `brackets` | How to replace PII in transcripts |
| `AUDIO_PII_MUTE_AUDIO` | `true`, `false` | `false` | Create redacted audio file |
| `AUDIO_PII_MUTE_STYLE` | `silence`, `beep`, `noise` | `silence` | How to mute PII in audio |

## Redaction Styles

### Transcript Redaction Styles

| Style | Example | Use Case |
|-------|---------|----------|
| `brackets` | `[PERSON]`, `[PHONE_NUMBER]` | Clear indication of redacted type |
| `placeholder` | `[REDACTED]`, `[REDACTED]` | Simpler, less information leakage |
| `lprag` | `"John Smith"` → `"Michael Chen"` | LPRAG semantic perturbation - preserves meaning for LLM reasoning while protecting privacy. Reversible via session-based de-anonymization. |

### LPRAG Mode (Recommended)

When `AUDIO_PII_REDACTION_STYLE=lprag`, the system uses LPRAG (Learned Privacy-Respecting Anonymization with Gensim) to replace PII with semantically similar fake values:

**Benefits**:
- **Preserves semantic meaning**: LLM can reason about "Michael Chen" the same way it would about "John Smith"
- **Better LLM responses**: Natural language flow is maintained, improving RAG quality
- **Reversible**: Session-based token mapping enables de-anonymization for authorized users
- **Automatic fallback**: Falls back to brackets `[PERSON]` if LPRAG unavailable

**Example**:
```
Original:    "Hi, I'm John Smith, call me at 555-123-4567"
Brackets:    "Hi, I'm [PERSON], call me at [PHONE_NUMBER]"
LPRAG:       "Hi, I'm Michael Chen, call me at 555-987-6543"
```

**Configuration**:
```yaml
# docker-compose.yml
environment:
  - LPRAG_MODE=hybrid                    # Enable LPRAG globally
  - AUDIO_PII_REDACTION_STYLE=lprag      # Use LPRAG for audio transcripts
```

**Session-based De-anonymization**:
When LPRAG is used, the `AudioRedactionResult` includes a `session_id` that can be used for de-anonymization:
```python
result = audio_redactor.process("recording.mp3", redaction_style="lprag")
print(result.redacted_transcript)  # "Hi, I'm Michael Chen..."
print(result.session_id)           # "abc123xyz..."  (for de-anonymization)
print(result.lprag_enabled)        # True
```

### Audio Redaction Styles (Optional)

| Style | Description | User Experience |
|-------|-------------|-----------------|
| `silence` | Replace with silence | Clean, but obvious gaps |
| `beep` | Replace with beep tone | Traditional redaction sound |
| `noise` | Replace with white/pink noise | Less jarring |

## Implementation Phases

### Phase 1: Core Transcript Redaction

**Goal**: Detect PII in audio transcripts, create redacted transcript for LLM safety.

| Task | File | Description |
|------|------|-------------|
| 1.1 | `audio_pii_redactor.py` (NEW) | Create `AudioPIIRedactor` class |
| 1.2 | `audio_pii_redactor.py` | Integrate `whisper-timestamped` for word-level timestamps |
| 1.3 | `audio_pii_redactor.py` | Implement PII detection with timestamp mapping |
| 1.4 | `audio_pii_redactor.py` | Implement transcript redaction (text replacement) |
| 1.5 | `audio_processor.py` | Add `transcribe_with_pii_redaction()` method |
| 1.6 | `mcp_server_http.py` | Update audio indexing to store both transcripts |
| 1.7 | `requirements.txt` | Add `whisper-timestamped>=1.15.0` |
| 1.8 | `tests/test_audio_pii_redactor.py` | Unit tests for redactor |

**Deliverables**:
- `original_transcript` and `redacted_transcript` stored in document metadata
- `redacted_transcript` used as document content (for embeddings)
- PII regions with timestamps stored for Phase 2

### Phase 2: Audio File Redaction

**Goal**: Create redacted audio files with beep/silence over PII segments.

| Task | File | Description |
|------|------|-------------|
| 2.1 | `audio_pii_redactor.py` | Implement `redact_audio()` with pydub |
| 2.2 | `audio_pii_redactor.py` | Support silence/beep/noise redaction styles |
| 2.3 | `audio_pii_redactor.py` | Generate and store redacted audio file |
| 2.4 | `mcp_server_http.py` | Store `redacted_audio_path` in metadata |
| 2.5 | `requirements.txt` | Add `pydub>=0.25.0` |
| 2.6 | `Dockerfile` / `Dockerfile.jetson` | Add `ffmpeg` system dependency |
| 2.7 | `tests/test_audio_pii_redactor.py` | Tests for audio muting |

**Deliverables**:
- Redacted audio files stored at `data/redacted/audio/`
- `redacted_audio_path` in document metadata
- Configurable redaction style (silence/beep/noise)

### Phase 3: RAG Integration

**Goal**: Ensure chat/LLM context uses only redacted content.

| Task | File | Description |
|------|------|-------------|
| 3.1 | `server/services/rag.ts` | Modify `buildRAGContext()` to use `redacted_transcript` |
| 3.2 | `server/services/rag.ts` | For audio-capable LLMs, use `redacted_audio_path` |
| 3.3 | `.env` / docker-compose | Add `AUDIO_PII_ENABLED` environment variable |
| 3.4 | `server/services/rag.ts` | Add tests verifying LLM never sees original transcript |

**Deliverables**:
- Chat responses use redacted content only
- Original transcript never sent to external LLMs

### Phase 4: Frontend

**Goal**: Display audio with transcript, PII highlighting, and playback controls.

| Task | File | Description |
|------|------|-------------|
| 4.1 | `DocumentViewer.tsx` | Add audio player component |
| 4.2 | `DocumentViewer.tsx` | Add Original/Redacted transcript tabs |
| 4.3 | `DocumentViewer.tsx` | Add PII highlighting with tooltips |
| 4.4 | `DocumentViewer.tsx` | Add auto-refresh while `redaction_pending` |
| 4.5 | `DocumentViewer.tsx` | Add Original/Redacted audio playback toggle |
| 4.6 | `DocumentViewer.tsx` | Add info banner about LLM privacy |

**Deliverables**:
- Audio player with waveform visualization
- Transcript view with PII regions highlighted
- Toggle between original (user) and redacted (what LLM sees) views

## Testing

### Unit Tests

```python
# tests/test_audio_pii_redactor.py

def test_transcribe_with_timestamps():
    """Test whisper-timestamped returns word-level times."""
    ...

def test_pii_detection_person():
    """Test PERSON detection maps to correct timestamps."""
    ...

def test_pii_detection_phone():
    """Test PHONE_NUMBER detection maps to correct timestamps."""
    ...

def test_transcript_redaction_brackets():
    """Test transcript redaction with bracket style."""
    transcript = "Hi, I'm John Smith, call me at 555-123-4567"
    expected = "Hi, I'm [PERSON], call me at [PHONE_NUMBER]"
    ...

def test_audio_muting():
    """Test audio file has silence in PII regions."""
    ...

def test_rag_uses_redacted():
    """Test RAG context uses redacted transcript, not original."""
    ...
```

### Integration Tests

```bash
# Test full pipeline
curl -X POST http://localhost:8085/api/audio/process \
  -F "file=@test_audio_with_pii.mp3"

# Verify response has both transcripts
{
  "original_transcript": "Hi, I'm John Smith...",
  "redacted_transcript": "Hi, I'm [PERSON]...",
  "has_pii": true
}

# Verify chat uses redacted
curl -X POST http://localhost:3003/api/chat \
  -d '{"message": "What did the person say?", "documents": ["audio_abc123"]}'
# LLM should see "[PERSON]" not "John Smith"
```

## Dependencies

### New Dependencies

```
# requirements.txt additions
whisper-timestamped>=1.15.0  # Word-level timestamps for Whisper
pydub>=0.25.0                # Audio manipulation (muting)
```

### System Dependencies

```dockerfile
# Dockerfile additions
RUN apt-get update && apt-get install -y \
    ffmpeg \  # Required by pydub for audio processing
    && rm -rf /var/lib/apt/lists/*
```

## Security Considerations

1. **Original transcript storage**: Stored in metadata, never in document content that gets embedded
2. **API boundaries**: `/api/chat` endpoints only return redacted content
3. **File serving**: Original audio served only via authenticated `/api/files/` endpoint
4. **Logs**: Original transcripts should not be logged; use redacted versions

## Limitations

1. **Whisper accuracy**: PII detection depends on transcription accuracy
2. **Timestamp precision**: Word boundaries may not be exact (±100ms typical)
3. **Context loss**: Some PII context may be lost (e.g., "Smith" without "John")
4. **Language support**: Currently English only (tiny.en model)
5. **No speaker diarization**: Cannot redact specific speakers (would need WhisperX)
