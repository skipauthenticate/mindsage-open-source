# Image PII Redaction Architecture

This document describes the image PII redaction system for MindSage, including the end-to-end flow from ingestion to user display.

## Overview

MindSage processes images containing sensitive information (passports, ID cards, documents with SSNs, etc.) and must:

1. **Protect PII during LLM interactions** - Redacted images sent to external LLMs
2. **Preserve user access** - Original images available to the user in search results
3. **Maintain searchability** - Captions generated from originals for semantic search

## Architecture Summary

```
                         INGESTION FLOW
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│  ┌─────────────┐    ┌─────────────────┐    ┌─────────────────────────────┐ │
│  │   Upload    │───▶│ ImageProcessor  │───▶│  Parallel Processing        │ │
│  │   Image     │    │                 │    │                             │ │
│  └─────────────┘    └─────────────────┘    │  ┌─────────────────────┐    │ │
│                                            │  │ BLIP Caption        │    │ │
│                                            │  │ (original image)    │    │ │
│                                            │  └──────────┬──────────┘    │ │
│                                            │             │               │ │
│                                            │  ┌─────────────────────┐    │ │
│                                            │  │ OCR + PII Detection │    │ │
│                                            │  │ (EasyOCR/Tesseract) │    │ │
│                                            │  └──────────┬──────────┘    │ │
│                                            │             │               │ │
│                                            │  ┌─────────────────────┐    │ │
│                                            │  │ Image Redaction     │    │ │
│                                            │  │ (PIL black boxes)   │    │ │
│                                            │  └──────────┬──────────┘    │ │
│                                            └─────────────┼───────────────┘ │
│                                                          │                 │
│                                                          ▼                 │
│                                            ┌─────────────────────────────┐ │
│                                            │  Text PII Anonymization     │ │
│                                            │  (Presidio on caption)      │ │
│                                            └──────────────┬──────────────┘ │
│                                                           │                │
└───────────────────────────────────────────────────────────┼────────────────┘
                                                            │
                                                            ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                            STORAGE                                          │
│                                                                             │
│  data/                                                                      │
│  ├── uploads/images/          ← Original images (user access only)         │
│  │   └── img_abc123.jpg                                                    │
│  ├── redacted/images/         ← Redacted images (LLM-safe)                 │
│  │   └── img_abc123_redacted.jpg                                           │
│  └── vectordb/                ← txtai index with metadata                  │
│      └── documents contain:                                                │
│          - anonymized_caption: "Photo of <PII:PERSON:xyz> with passport"   │
│          - original_image_path: "uploads/images/img_abc123.jpg"            │
│          - redacted_image_path: "redacted/images/img_abc123_redacted.jpg"  │
│          - pii_regions: [{type, confidence, bbox}]                         │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Redaction Strategy: Upload-Time (Not On-Demand)

**Decision**: Redacted images are generated **at upload/ingestion time**, not on-demand when requested.

### Why Upload-Time Redaction

| Approach | Pros | Cons |
|----------|------|------|
| **Upload-time (chosen)** | Predictable latency on retrieval, simpler serving, one-time processing cost | Storage for both versions, redaction even if image never accessed by LLM |
| **On-demand** | Storage savings (only store original), redact only when needed | Latency spike on first LLM request, complex caching logic, repeated processing if cache evicted |

### Rationale

1. **User Experience**: Chat responses shouldn't be delayed by OCR + redaction processing (500-2000ms)
2. **Simplicity**: No cache invalidation logic or race conditions
3. **Predictability**: Same latency for first and subsequent requests
4. **Storage is cheap**: On Jetson with SD card, storing two versions is acceptable
5. **Audit trail**: Pre-computed redacted images can be verified offline

### When Redaction Occurs

**Async Redaction (Default)**: For fast uploads, PII redaction runs in the background:

```
User uploads image
        │
        ▼
┌───────────────────────────────────────────────────────────────┐
│  IMMEDIATE (sync) - Fast Upload Response                      │
│  1. BLIP caption (original image)                             │
│  2. Save original image to disk                               │
│  3. Add document to vector index (with redaction_pending=true)│
│  4. Return success response immediately                       │
└───────────────────────────────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────────────────────────────┐
│  BACKGROUND (async) - AsyncImageRedactor Worker               │
│  1. OCR text extraction (EasyOCR/Tesseract)                   │
│  2. PII detection (Presidio)                                  │
│  3. Generate redacted image                                   │
│  4. Update document metadata (has_pii, pii_types_found, etc.) │
└───────────────────────────────────────────────────────────────┘
        │
        ▼
Both images available, metadata complete
```

The `AsyncImageRedactor` processes images in a background thread:
- No upload blocking - response returns immediately after image storage
- Automatic retry with exponential backoff for transient failures
- Document metadata updated when redaction completes
- Graceful degradation if redaction fails

### Frontend Auto-Refresh

The DocumentViewer component automatically polls for updates while PII redaction is pending:

```tsx
const { data: selectedDoc } = useQuery({
  queryKey: ['document', selectedId],
  queryFn: () => getVectorDocument(selectedId),
  enabled: !!selectedId,
  // Auto-refresh every 2 seconds while PII redaction is pending
  refetchInterval: (query) => query.state.data?.redactionPending ? 2000 : false,
});
```

**User Experience Flow:**
1. User uploads image → Upload returns immediately
2. DocumentViewer shows "Scanning for PII..." badge with spinner
3. "Redacted" tab is disabled during processing
4. Background: `AsyncImageRedactor` processes image
5. Background: Document metadata updated (`redaction_pending=false`, `redaction_complete=true`)
6. Frontend: React Query polls and fetches updated metadata
7. UI updates automatically:
   - Spinner stops
   - PII status badge shows "PII Detected" or "No PII"
   - "Redacted" tab becomes enabled
   - User can switch between Original/Redacted views

### Storage Impact

For a typical image:
- Original: ~500KB-2MB (user's photo)
- Redacted: ~500KB-2MB (same dimensions, black rectangles added)
- **Total**: ~2x storage per image with PII

For images with no detected PII:
- Option A: Store duplicate (simpler code path)
- Option B: Store only original, set `redacted_image_path = original_image_path` (storage optimization)

Current implementation uses **Option B** - no duplicate storage when no PII detected.

## Image Flow by Feature

### 1. Chat Feature (LLM Interaction)

When user asks about content in an image:

```
┌───────────────┐     ┌───────────────┐     ┌─────────────────────────────────┐
│   Frontend    │────▶│  Express API  │────▶│  External LLM API               │
│   Chat UI     │     │  /api/chat    │     │  (Claude, GPT-4V, Gemini)       │
└───────────────┘     └───────┬───────┘     └─────────────────────────────────┘
                              │                          ▲
                              │   buildRAGContext()      │ Multimodal messages
                              ▼                          │ (text + images)
                      ┌───────────────┐                  │
                      │ Vector Store  │ ─────────────────┘
                      │ enhancedSearch│   Returns:
                      └───────────────┘   - anonymized_caption
                              │           - redacted_image (base64)
                              ▼           - NO original_image to LLM
                      ┌───────────────┐
                      │ /api/image/   │
                      │ base64/{id}   │
                      └───────────────┘
```

**Multimodal LLM Support (ENABLE_IMAGE_RAG=true)**:

When images are found in RAG context, they are sent directly to multimodal LLMs:

| Provider | Multimodal Support | Image Format |
|----------|-------------------|--------------|
| **Claude** (Anthropic) | Yes | Base64 source block |
| **GPT-4V** (OpenAI) | Yes | Data URL in image_url |
| **Groq** | No | Falls back to caption text only |

The chat service automatically:
1. Fetches base64 images via `/api/image/base64/{id}?context=llm`
2. Uses redacted versions (PII-safe)
3. Builds multimodal messages for Claude/OpenAI
4. Falls back to text-only for Groq

**Security Guarantee**: The LLM only receives:
- Anonymized caption text (LPRAG-protected)
- Redacted image (base64, PII blacked out)
- Never the original image content

### 2. Explore Feature (User Search)

When user searches and browses results:

```
┌───────────────┐     ┌───────────────┐     ┌───────────────┐
│   Frontend    │────▶│  Express API  │────▶│ Vector Store  │
│   Explore UI  │     │  /api/search  │     │ search()      │
└───────────────┘     └───────┬───────┘     └───────┬───────┘
        ▲                     │                     │
        │                     │                     │
        │                     ▼                     ▼
        │             ┌───────────────┐     Returns to API:
        │             │ De-anonymize  │     - original_caption (de-anon)
        │             │ (on-device)   │     - original_image_path
        │             └───────────────┘     - For user's eyes only
        │                     │
        │                     │
        └─────────────────────┘
              Display to user:
              - Original image
              - Original text (de-anonymized)
```

**User Access Guarantee**: The user sees:
- Original image (not redacted) - they own their data
- De-anonymized caption text
- Full search result context

## Component Details

### ImagePIIRedactor

Location: `vector-store/mcp_vector_store/image_pii_redactor.py`

Responsibilities:
1. **OCR Text Extraction** - EasyOCR (GPU) or Tesseract (CPU fallback)
2. **PII Detection** - Presidio with custom recognizers
3. **Bounding Box Calculation** - Full OCR box redaction (recommended) or proportional positioning (legacy)
4. **Image Redaction** - PIL drawing black rectangles over PII regions

```python
@dataclass
class ImagePIIRegion:
    x: int           # Top-left X coordinate
    y: int           # Top-left Y coordinate
    width: int       # Region width in pixels
    height: int      # Region height in pixels
    pii_type: str    # PERSON, SSN, PASSPORT, etc.
    original_text: str
    confidence: float

@dataclass
class RedactionResult:
    redacted_image_path: str
    original_image_path: Optional[str]
    regions_redacted: List[ImagePIIRegion]
    session_id: str
    processing_time_ms: float
```

### OCR Engines

| Engine | Environment | GPU Memory | Accuracy | Best For |
|--------|-------------|------------|----------|----------|
| **EasyOCR** | Jetson (GPU) | ~500-800MB | Higher | Complex layouts, multilingual |
| **EasyOCR** | Mac (CPU) | 0 (CPU RAM ~600MB) | Higher | Development |
| **Tesseract** | Any (CPU) | 0 (CPU RAM ~35MB) | Good | Lightweight fallback |

Configuration via environment variables:
```yaml
IMAGE_PII_ENABLED: "true"
IMAGE_PII_OCR_ENGINE: "easyocr"      # or "tesseract"
IMAGE_REDACTION_COLOR: "black"       # or "white", hex color
IMAGE_PII_REDACT_FULL_BOX: "true"    # Recommended: redact entire OCR box
```

**Redaction Mode** (`IMAGE_PII_REDACT_FULL_BOX`):
- `"true"` (default, recommended): Redacts the entire OCR bounding box when PII is detected. More reliable coverage since proportional fonts have variable character widths.
- `"false"`: Attempts to calculate precise PII position within the OCR box using proportional character positioning. Less reliable, may leave gaps with proportional fonts.

### PII Types Detected

| Category | Types | Custom Recognizers |
|----------|-------|-------------------|
| Identity | PERSON, US_SSN, US_PASSPORT | Yes - improved passport pattern |
| Financial | CREDIT_CARD, IBAN_CODE, US_BANK_NUMBER | Built-in Presidio |
| Contact | EMAIL_ADDRESS, PHONE_NUMBER, IP_ADDRESS | Built-in Presidio |
| Location | LOCATION, US_DRIVER_LICENSE | Built-in Presidio |
| Custom | VEHICLE_ID, LICENSE_PLATE, MEMBER_ID | Yes - added patterns |

### Storage Layout

```
data/
├── uploads/
│   └── images/
│       ├── img_abc123.jpg          # Original uploaded image
│       ├── img_def456.png          # Another original
│       └── ...
├── redacted/
│   └── images/
│       ├── img_abc123_redacted.jpg # PII regions blacked out
│       ├── img_def456_redacted.png # PII regions blacked out
│       └── ...
└── vectordb/
    └── index/                      # txtai vector index
```

## Document Metadata Schema

Each indexed image document includes:

```python
{
    # Existing fields
    "id": "doc_abc123",
    "type": "image",
    "text": "Photo of person holding passport...",  # Anonymized caption
    "embedding": [...],  # Vector from anonymized caption

    # Image-specific fields (NEW)
    "original_image_path": "uploads/images/img_abc123.jpg",
    "redacted_image_path": "redacted/images/img_abc123_redacted.jpg",
    "has_pii": True,
    "pii_regions": [
        {
            "type": "US_PASSPORT",
            "confidence": 0.95,
            "bbox": [120, 340, 200, 30]  # x, y, width, height
        },
        {
            "type": "PERSON",
            "confidence": 0.87,
            "bbox": [50, 100, 180, 40]
        }
    ],
    "pii_session_id": "session_xyz",  # For text de-anonymization

    # Processing metadata
    "processed_at": "2024-01-15T10:30:00Z",
    "ocr_engine": "easyocr",
    "caption_model": "BLIP"
}
```

## API Endpoints

### Existing Endpoints (Modified)

#### POST `/api/media/upload`

Processes uploaded image with optional PII redaction.

**Request**: multipart/form-data with `file`

**Response** (enhanced):
```json
{
  "success": true,
  "document_id": "doc_abc123",
  "caption": "Photo of <PII:PERSON:xyz> holding a document",
  "pii_redaction": {
    "enabled": true,
    "regions_found": 3,
    "redacted_image_path": "redacted/images/img_abc123_redacted.jpg",
    "original_stored": true
  }
}
```

#### GET `/api/search`

Returns search results with appropriate image paths.

**For LLM context** (internal MCP call):
```json
{
  "results": [{
    "text": "Photo of <PII:PERSON:xyz> holding document",
    "image_path": "redacted/images/img_abc123_redacted.jpg"
  }]
}
```

**For user display** (Explore UI):
```json
{
  "results": [{
    "text": "Photo of John Smith holding document",
    "image_path": "uploads/images/img_abc123.jpg",
    "has_pii": true,
    "pii_warning": "This image contains detected PII"
  }]
}
```

### New Endpoints

#### POST `/api/image/pii/detect`

Preview PII detection without redaction.

**Request**: multipart/form-data with `file`

**Response**:
```json
{
  "success": true,
  "regions": [
    {
      "type": "US_SSN",
      "text": "123-45-****",  # Partially masked
      "confidence": 0.95,
      "bbox": [100, 200, 150, 25]
    }
  ],
  "ocr_text": "Full extracted text..."
}
```

#### POST `/api/image/pii/redact`

Perform redaction and return result.

**Request**: multipart/form-data
- `file`: Image file
- `redaction_color`: "black" | "white" | hex
- `store_original`: boolean

**Response**:
```json
{
  "success": true,
  "redacted_image_url": "/api/files/redacted/img_abc123_redacted.jpg",
  "regions_redacted": 3,
  "pii_types": ["US_SSN", "PERSON", "EMAIL_ADDRESS"]
}
```

#### GET `/api/image/pii/status`

Check OCR/redaction system status.

**Response**:
```json
{
  "enabled": true,
  "ocr_engine": "easyocr",
  "ocr_available": true,
  "gpu_available": true,
  "presidio_ready": true
}
```

#### GET `/api/image/serve/{image_id}`

Serve stored images based on context.

**Query Parameters**:
- `context`: `user` (default) returns original, `llm` returns redacted
- `type`: `original` or `redacted` (overrides context)

**Response**: Image file (JPEG, PNG, etc.)

#### GET `/api/image/base64/{image_id}`

Get base64-encoded image data for multimodal LLM input.

**Query Parameters**:
- `context`: `llm` (default) returns redacted, `user` returns original
- `max_size`: Optional max dimension to resize (useful for token limits)

**Response**:
```json
{
  "success": true,
  "image_id": "abc123",
  "media_type": "image/jpeg",
  "base64_data": "/9j/4AAQSkZJRg...",
  "context": "llm",
  "size_bytes": 245632
}
```

## Memory Budget (Jetson Orin Nano 8GB)

| Component | GPU VRAM | CPU RAM | Notes |
|-----------|----------|---------|-------|
| BLIP (captioning) | ~1.0-1.5GB | - | Swappable via ModelManager |
| EasyOCR | ~500-800MB | ~100MB | Swappable via ModelManager |
| Embeddings | ~0.5-1.0GB | - | Swappable via ModelManager |
| Presidio + spaCy | - | ~150MB | CPU-only |
| **Active at once** | ~1.5GB | ~250MB | Only 1 GPU model loaded |

EasyOCR is registered with ModelManager as `ModelType.OCR` to swap with BLIP/Whisper, ensuring the system stays within the 8GB shared memory budget.

## Security Considerations

### LLM Safety Mechanism (IMPLEMENTED)

**Critical Requirement**: External LLMs must NEVER receive original images with PII.

The enforcement mechanism uses these components:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  DOCUMENT METADATA (stored in vector index)                                 │
│                                                                             │
│  {                                                                          │
│    "has_pii": true,                    ← Flag: PII was detected            │
│    "original_image_path": "uploads/...",  ← For user display only          │
│    "redacted_image_path": "redacted/...", ← For LLM + user display         │
│    "image_id": "img_abc123",           ← Unique identifier                 │
│    "pii_types_found": ["PERSON", "SSN"] ← Types of PII detected            │
│  }                                                                          │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  SEARCH API - Context-Aware Path Selection                                  │
│  (mcp_server_http.py: transform_metadata_for_context())                     │
│                                                                             │
│  def transform_metadata_for_context(metadata, context: str) -> dict:       │
│      if context == "llm" and metadata.get("has_pii"):                      │
│          # Return redacted path, hide original from LLM                    │
│          safe = dict(metadata)                                             │
│          safe["image_path"] = safe["redacted_image_path"]                  │
│          safe.pop("original_image_path", None)  # Remove original path    │
│          return safe                                                        │
│      return metadata  # User context: return original                      │
└─────────────────────────────────────────────────────────────────────────────┘
```

**How context is determined:**

| Caller | Context | Image Path Returned |
|--------|---------|---------------------|
| MCP tool call (LLM searching) | `llm` (hardcoded) | `redacted_image_path` |
| `/api/search` from frontend Explore | `user` (default) | `original_image_path` |
| `/api/chat` context building | `llm` (explicit) | `redacted_image_path` |

**Implementation (completed):**

1. [x] Store `has_pii` flag in document metadata during indexing
2. [x] Store both `original_image_path` and `redacted_image_path` in metadata
3. [x] Add `context` parameter to search API (`llm` or `user`)
4. [x] MCP tools ALWAYS pass `context=llm` (hardcoded in handlers)
5. [x] Frontend Explore uses `context=user` (default)
6. [x] Chat service passes `context=llm` for RAG queries
7. [x] Default to original metadata when no PII detected (no duplication)

**Fallback behavior:**
- If `has_pii=false`, both paths point to same file (no duplicate storage)
- If redaction failed, `redacted_image_path` is null → return `original_image_path` with warning logged

### What Leaves the Device

| Destination | Data Sent | Image Type |
|-------------|-----------|------------|
| External LLM | Anonymized caption | **Redacted** image path only |
| User Browser | De-anonymized caption | **Original** image |
| Vector DB (local) | Both versions | Both paths stored |

### What Never Leaves

1. Original images with PII - stored locally, served only to local user
2. Token-to-PII mappings - in-memory only, never persisted
3. Full PII region details - stored locally for audit

### Access Control

```
Original images:  User only (browser on device)
Redacted images:  User + LLM (safe for external APIs)
Caption text:     LPRAG-anonymized for LLM, de-anonymized for user
```

## Configuration

### Environment Variables

```yaml
# Enable/disable image PII redaction
IMAGE_PII_ENABLED: "true"

# OCR engine selection
IMAGE_PII_OCR_ENGINE: "easyocr"  # easyocr | tesseract

# Redaction appearance
IMAGE_REDACTION_COLOR: "black"   # black | white | #RRGGBB

# Storage paths
IMAGE_UPLOAD_PATH: "/app/data/uploads/images"
IMAGE_REDACTED_PATH: "/app/data/redacted/images"

# Processing options
IMAGE_PII_STORE_ORIGINAL: "true"   # Keep original after processing
IMAGE_PII_DELETE_ON_EMPTY: "false" # Delete original if no PII found

# Image RAG options (chat service)
ENABLE_IMAGE_RAG: "true"           # Send images to multimodal LLMs (default: true)
IMAGE_RAG_MAX_SIZE: "1024"         # Max dimension for LLM images (default: 1024px)
```

### Docker Compose

```yaml
vector-store:
  environment:
    - IMAGE_PII_ENABLED=true
    - IMAGE_PII_OCR_ENGINE=easyocr
    - IMAGE_REDACTION_COLOR=black
  volumes:
    - ./data/uploads:/app/data/uploads
    - ./data/redacted:/app/data/redacted
    - ./data/vectordb:/app/data/vectordb
```

## Implementation Status

### Completed

- [x] `ImagePIIRedactor` class with OCR + detection + redaction
- [x] EasyOCR and Tesseract backend support
- [x] Presidio integration with custom recognizers (passport, VIN, etc.)
- [x] Proportional bounding box calculation for precise redaction
- [x] Unit tests for image PII redaction
- [x] Docker configuration with Tesseract system packages
- [x] Environment variable configuration
- [x] `ImageStorageManager` for persistent image storage with redaction
- [x] Document metadata schema with `has_pii`, `original_image_path`, `redacted_image_path`, `image_id`, `pii_types_found`
- [x] Upload API integration - images stored and metadata saved during `/api/upload/media`
- [x] **`AsyncImageRedactor`** - Background worker for non-blocking PII redaction
- [x] **Deferred redaction flow** - Uploads return immediately, redaction queued
- [x] **Automatic retry** - Exponential backoff for transient failures
- [x] **Metadata updates** - Document updated when redaction completes

### LLM Safety (IMPLEMENTED)

- [x] **`transform_metadata_for_context()` function** - Transforms metadata based on access context
- [x] **Search API context parameter** - Both `/api/search` and `/api/search/enhanced` accept `context` param
- [x] **MCP tool handlers** - All MCP search tools (`_search_documents`, `_enhanced_search`, `_list_documents`, `_get_document`, `_search_with_topic`) use `context=llm`
- [x] **MCP stdio server** - `search_documents` passes `context=llm`
- [x] **Chat service** - RAG queries pass `context=llm` to enhanced search
- [x] **Path selection logic** - LLM context removes `original_image_path` from metadata, sets `image_path` to redacted version
- [x] **Default-safe behavior** - REST APIs default to `context=user` (for direct user access via Explore)

### Image RAG (IMPLEMENTED)

- [x] **`/api/image/serve/{image_id}` endpoint** - Serves images with context-aware path selection
- [x] **`/api/image/base64/{image_id}` endpoint** - Returns base64 for multimodal LLMs
- [x] **`ChatContext.imageData` field** - Includes base64, mediaType, imageId, caption
- [x] **`buildRAGContext()` image fetching** - Fetches base64 images for image documents
- [x] **Multimodal message builders** - `buildMultimodalUserContent()`, `toOpenAIMessages()`, `toAnthropicMessages()`
- [x] **`streamOpenAIMultimodal()` function** - Streams with image content for GPT-4V
- [x] **`streamAnthropicMultimodal()` function** - Streams with image content for Claude
- [x] **`ENABLE_IMAGE_RAG` environment variable** - Default: true
- [x] **`IMAGE_RAG_MAX_SIZE` environment variable** - Default: 1024px (limits token usage)
- [x] **Frontend DocumentViewer image display** - Shows images with captions, dimensions, PII badges
- [x] **Original/Redacted tabs** - User can switch between original and redacted image views
- [x] **PII status badges** - Shows "Scanning for PII...", "PII Detected", or "No PII" based on redaction state
- [x] **Auto-refresh while pending** - React Query polls every 2s while `redactionPending=true`
- [x] **Disabled state during processing** - Redacted tab disabled until async redaction completes

### Planned

- [ ] Image thumbnail generation for UI
- [ ] Batch redaction for existing images

## Testing

### Unit Tests

```bash
cd mindsage/vector-store
pytest tests/test_image_pii_redactor.py -v
```

### Manual Testing

```bash
# Start server
docker compose up vector-store

# Test detection
curl -X POST http://localhost:8085/api/image/pii/detect \
  -F "file=@test_image_with_ssn.jpg"

# Test redaction
curl -X POST http://localhost:8085/api/image/pii/redact \
  -F "file=@test_image_with_ssn.jpg" \
  -F "redaction_color=black"

# Check status
curl http://localhost:8085/api/image/pii/status
```

### Test Images

Generated test images available at:
```
vector-store/tests/test_images/
├── document_with_ssn.png
├── passport_photo.png
├── business_card.png
├── medical_document.png
└── ... (32 test images total)
```

## Related Documents

- [PII-ARCHITECTURE.md](PII-ARCHITECTURE.md) - Text PII anonymization architecture
- [CONSENT-DESIGN.md](CONSENT-DESIGN.md) - User consent flow design

## Appendix: OCR Accuracy Notes

### EasyOCR Strengths
- Better accuracy on photographs and complex backgrounds
- Handles rotated/skewed text
- Multilingual support (40+ languages)
- GPU acceleration on Jetson

### Tesseract Strengths
- Excellent on clean document scans
- Lower memory footprint
- No Python/PyTorch dependency
- Faster startup time

### Known Limitations
- Handwritten text: Poor accuracy on both engines
- Very small text (<8px): May be missed
- Low contrast: Adjust preprocessing thresholds
- Stylized fonts: May require custom training

## Appendix: Bounding Box Calculation

The redaction uses proportional calculation to cover only the PII portion within a larger text block:

```python
def calculate_pii_bbox(self, pii_start: int, pii_end: int) -> Tuple[int, int, int, int]:
    """Calculate pixel coordinates for PII within OCR text box."""
    text_len = len(self.text)

    # Character position ratios
    start_ratio = pii_start / text_len
    end_ratio = pii_end / text_len

    # Proportional X position
    pii_x = self.x + int(self.width * start_ratio)
    pii_width = int(self.width * (end_ratio - start_ratio))

    # Add small buffer for visual clarity
    buffer = int((self.width / text_len) * 0.3)
    pii_x = max(self.x, pii_x - buffer)
    pii_width = min(self.width, pii_width + 2 * buffer)

    return pii_x, self.y, pii_width, self.height
```

This ensures "SSN: 456-78-9012" in a text block only blacks out the number, not the label.
