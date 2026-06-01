# MindSage Backend

Express API server for the MindSage privacy-first data platform. Runs on Jetson Orin Nano edge hardware.

## Hardware Environment

This project runs on a **Jetson Orin Nano** edge device with significant resource constraints:

- **RAM/VRAM**: ~7.4GB shared memory (CPU and GPU share the same pool)
- **GPU**: NVIDIA Orin (Ampere architecture, CUDA capable)
- **Storage**: Limited, prefer efficient data structures
- **Network**: Local network deployment, no cloud dependencies

## Services

- **Express API** (port 3003) - REST endpoints for connectors, files, and proxying to vector store
- **Vector Store** (port 8085) - Python/FastAPI ML service for semantic search
- **LocalSend** (port 53317) - File transfer protocol for receiving files from mobile devices

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│         Frontend (separate package: mindsage-frontend)       │
│                    http://localhost:8080                     │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                 Express API (this package)                   │
│                    http://localhost:3003                     │
│         Connectors, Files, LocalSend, Vector Store Proxy     │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│              Vector Store (Python/FastAPI)                   │
│                    http://localhost:8085                     │
│  ┌──────────┐  ┌─────────┐  ┌────────┐  ┌──────┐  ┌──────┐  │
│  │Embedding │  │Reranker │  │Whisper │  │ BLIP │  │spaCy │  │
│  │  Model   │  │ (Cross- │  │ (Audio │  │(Image│  │ NER  │  │
│  │(GPU/CPU) │  │encoder) │  │ STT)   │  │ Cap) │  │(CPU) │  │
│  └──────────┘  └─────────┘  └────────┘  └──────┘  └──────┘  │
│       │             │            │          │                │
│       └─────────────┴────────────┴──────────┘                │
│          Only ONE on GPU at a time                            │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│              txtai (SQLite FTS5 + Vector Search)             │
│                     data/vectordb/                           │
└─────────────────────────────────────────────────────────────┘
```

## Development

```bash
npm install
npm run dev          # Backend only (port 3003)
npm run dev:all      # Backend + Vector Store
```

## Project Structure

```
mindsage/
├── server/
│   ├── index.ts              # Express server (all API endpoints)
│   ├── chat-service.ts       # Chat service with OpenAI/Anthropic integration
│   ├── localsend-server.ts   # LocalSend protocol implementation
│   ├── vector-store-client.ts # Vector store API client
│   ├── browser-connector/    # Persistent browser for AI chat capture
│   │   ├── manager.ts        # Chrome launch via child_process (not Playwright)
│   │   ├── processor.ts      # Capture processing & indexing
│   │   ├── api.ts            # Express routes
│   │   └── extension/        # Chrome extension (API-based, not DOM scraping)
│   └── scripts/              # Export scripts (chatgpt, readwise, etc.)
├── vector-store/             # Python ML service (see vector-store/CLAUDE.md)
│   └── mcp_vector_store/     # Main package
│       ├── audio_processor.py    # Whisper speech-to-text (file upload transcription)
│       ├── image_processor.py    # BLIP image captioning
│       ├── voice_rtc_handler.py  # Voice pipeline (All-Groq cloud: STT→RAG→PII→LLM→TTS)
│       ├── groq_stt_service.py   # Groq Whisper STT (cloud, voice mode)
│       └── groq_tts_service.py   # Groq Orpheus TTS (cloud, voice mode)
├── data/                     # Runtime data
│   ├── connectors.json       # Connector configurations
│   ├── uploads/              # Received files (LocalSend, HTTP upload)
│   ├── imports/              # Files queued for indexing
│   ├── exports/              # Connector export data
│   ├── vectordb/             # txtai vector database (SQLite FTS5)
│   └── browser-connector/    # Browser profiles & captured conversations
├── dist-server/              # Compiled JavaScript output
├── docs/                     # Design documents
└── novnc-web/                # noVNC web interface
```

## API Endpoints

All endpoints are prefixed with `/api/`:

### Core
- `GET /api/stats` - Storage statistics
- `GET /api/server-info` - Network info (IP, port)

### Connectors
- `GET /api/connectors` - List all connectors
- `POST /api/connectors` - Create connector
- `PUT /api/connectors/:id` - Update connector
- `DELETE /api/connectors/:id` - Delete connector
- `POST /api/connectors/:id/sync` - Start sync
- `GET /api/connectors/:id/status` - Get sync status
- `POST /api/connectors/:id/stop` - Stop sync
- `POST /api/connectors/:id/upload` - Upload file for connector
- `GET /api/connectors/:id/exports` - List export files

### Files
- `GET /api/files` - List uploaded files
- `POST /api/files/upload` - Upload files (auto-imports for indexing)
- `DELETE /api/files/:filename` - Delete file
- `POST /api/files/:filename/import` - Import file for indexing

### Browser Connector
- `POST /api/browser-connector/launch` - Start Chromium with persistent profile (supports VNC mode)
- `POST /api/browser-connector/close` - Close browser gracefully (also stops VNC session)
- `GET /api/browser-connector/status` - Running state, active URL, VNC info, capture stats
- `POST /api/browser-connector/navigate` - Navigate to URL
- `POST /api/browser-connector/capture` - Receive captured data from extension
- `GET /api/browser-connector/conversations` - List captured conversations
- `GET /api/browser-connector/conversations/:id` - Get conversation with messages
- `DELETE /api/browser-connector/conversations/:id` - Delete conversation
- `GET /api/browser-connector/config` - Get configuration
- `PUT /api/browser-connector/config` - Update configuration
- `GET /api/browser-connector/stats` - Capture statistics
- `POST /api/browser-connector/reindex` - Re-index all conversations
- `GET /api/browser-connector/vnc/status` - Get VNC status and connection URL
- `GET /api/browser-connector/vnc/check` - Check if VNC dependencies are installed

#### Authentication & Sync (for headless operation)
- `GET /api/browser-connector/auth-status` - Check if user has logged in before
- `POST /api/browser-connector/report-auth` - Extension reports successful login
- `DELETE /api/browser-connector/auth` - Clear authentication (force re-login)
- `POST /api/browser-connector/sync` - Trigger headless sync (requires prior auth)
- `POST /api/browser-connector/sync-complete` - Extension reports sync completion

#### Auto-Sync Scheduling
- `GET /api/browser-connector/auto-sync` - Get auto-sync status and schedule
- `POST /api/browser-connector/auto-sync/start` - Enable automatic sync
- `POST /api/browser-connector/auto-sync/stop` - Disable automatic sync
- `PUT /api/browser-connector/auto-sync/interval` - Update sync interval (1-24 hours)

### Vector Store (proxied to Python service)
- `GET /api/vector-store/status` - Vector store health
- `POST /api/vector-store/search` - Basic vector search
- `POST /api/vector-store/search/enhanced` - Search with passage extraction
- `POST /api/vector-store/documents` - Add document
- `POST /api/vector-store/documents/batch` - Add multiple documents
- `GET /api/vector-store/documents` - List documents
- `GET /api/vector-store/documents/:id` - Get document
- `DELETE /api/vector-store/documents/:id` - Delete document
- `POST /api/vector-store/index-uploads` - Index all uploads
- `POST /api/vector-store/index-file/:filename` - Index specific file
- `POST /api/vector-store/index-connector/:connectorId` - Index connector exports
- `POST /api/vector-store/media/upload` - Upload audio/image for transcription/captioning and indexing (500MB limit)
- `GET /api/vector-store/media/status` - Check which media processors are available

### Topics
- `GET /api/vector-store/topics` - List all topics
- `GET /api/vector-store/topics/:topic/documents` - Documents by topic
- `GET /api/vector-store/documents/:id/topics` - Document's topics
- `PUT /api/vector-store/documents/:id/topics` - Update document topics
- `POST /api/vector-store/documents/:id/topics/generate` - Generate topics
- `POST /api/vector-store/search/with-topic` - Search with topic filter

### Knowledge Graph
- `POST /api/vector-store/graph` - Get graph data
- `GET /api/vector-store/graph/node/:nodeId` - Get node details

### PII Protection (Vector Store)
- `POST /api/pii/deanonymize` - De-anonymize text containing PII tokens
- `GET /api/pii/status` - Get PII protection status and statistics
- `GET /api/pii/session/:sessionId` - Get PII session info
- `DELETE /api/pii/session/:sessionId` - Clear PII session

### Chat (External LLM)
- `GET /api/chat/status` - Get chat service status (LLM availability, model info)
- `POST /api/chat` - Send message and get response (non-streaming)
- `POST /api/chat/stream` - Stream chat response via SSE (Server-Sent Events)
- `GET /api/chat/config` - Get LLM configuration (masked API keys)
- `PUT /api/chat/config` - Update LLM configuration (API keys, provider preference)
- `POST /api/chat/config/test` - Test an API key validity

### LocalSend
- `GET /api/localsend/status` - LocalSend server status
- `POST /api/localsend/start` - Start LocalSend
- `POST /api/localsend/stop` - Stop LocalSend

### Indexing Jobs
- `GET /api/indexing/status` - Background indexing summary
- `GET /api/indexing/jobs` - List all indexing jobs
- `GET /api/indexing/jobs/:jobId` - Get job status

### Ingest (Universal Push Endpoint)
- `POST /api/ingest` - Push single item (JSON, text, or file upload)
- `POST /api/ingest/batch` - Push multiple items at once (max 100)

### Voice (WebRTC, proxied to Vector Store)
- `POST /api/voice/webrtc/offer` - WebRTC SDP offer for voice connection
- `POST /api/voice/disconnect` - Disconnect voice session
- `GET /api/voice/status` - Voice pipeline status (Groq STT/TTS availability)
- `GET /api/voice/config` - Get voice configuration (TTS voice name)
- `PUT /api/voice/config` - Update voice configuration

## Environment Variables

```bash
PORT=3003                    # API server port
VECTOR_STORE_HOST=localhost  # Vector store host
VECTOR_STORE_PORT=8085       # Vector store port
VECTOR_STORE_API_KEY=        # Optional API key

# LLM Configuration (set one or more, or configure via UI)
ANTHROPIC_API_KEY=           # Anthropic API key for Claude models
GROQ_API_KEY=                # Groq API key for LLaMA/Mixtral (fast inference)
OPENAI_API_KEY=              # OpenAI API key for GPT models
```

## System Dependencies

### Required
- **Node.js 18+** - Runtime
- **Chrome/Chromium** - Browser Connector uses system Chrome (not Playwright)
  ```bash
  sudo apt install chromium-browser
  ```

### Optional (for VNC remote access)
For headless deployments (e.g., Jetson Orin Nano without a monitor), install VNC dependencies to access the browser remotely:
```bash
sudo apt install xvfb x11vnc novnc websockify
```

This enables launching the browser in VNC mode and accessing it via `http://<device-ip>:6080/vnc.html` from any device on the local network.

## Browser Connector (ChatGPT Sync)

The browser connector captures conversations from ChatGPT (and other AI chat services) using a persistent Chromium browser with a custom extension. It supports two operational modes:

### Authentication Flow

**First-Time Setup (VNC Required):**
```
1. User opens ChatGPT connector dialog in frontend
2. Clicks "Launch VNC Login" button
3. Backend launches Chrome with VNC mode (Xvfb + x11vnc + websockify)
4. User connects via noVNC at http://<device-ip>:6080/vnc.html
5. User logs into ChatGPT in the browser
6. Extension detects auth token and reports to backend via POST /report-auth
7. Backend saves authenticatedAt timestamp to config
8. Extension auto-syncs all conversations
9. User closes VNC when done
```

**Subsequent Syncs (Headless):**
```
1. User clicks "Sync Now" or auto-sync triggers
2. Backend checks authenticatedAt → exists (user has logged in before)
3. Backend launches Chrome with virtual display (Xvfb only, no VNC needed)
4. Extension loads with ?mindsage-sync=true URL parameter to force sync
5. Extension syncs conversations via ChatGPT's internal API
6. Captures sent to backend via POST /capture endpoint
7. Sync completes via inactivity detection (30s of no new captures)
8. Backend closes browser and returns results
```

### Launch Modes

| Mode | Display | VNC Access | Use Case |
|------|---------|------------|----------|
| `vnc: true` | Xvfb + x11vnc + websockify | Yes (port 6080) | First-time login, debugging |
| `virtualDisplay: true` | Xvfb only | No | Background sync (headless) |
| `headed: true` | Native display | No | Local development with monitor |

### Auto-Sync

When enabled, the browser connector automatically syncs conversations at a configurable interval (default: 5 hours):

- Requires prior authentication via VNC
- Skips sync if browser is already running (user might be using VNC)
- Stores last sync time and result in config
- Can be enabled/disabled via API or frontend toggle

### Configuration

Stored in `data/browser-connector/config.json`:
```json
{
  "autoStart": false,
  "defaultUrl": "https://chatgpt.com",
  "headed": true,
  "authenticatedAt": "2025-01-29T21:45:00.000Z",
  "autoSyncEnabled": true,
  "autoSyncIntervalHours": 5,
  "lastSyncAt": "2025-01-29T22:00:00.000Z",
  "lastSyncResult": {
    "success": true,
    "synced": 16,
    "failed": 0,
    "total": 16
  }
}
```

### Data Storage

- **Browser Profile**: `data/browser-connector/chromium-profile/` - Persistent Chrome profile with session cookies
- **Conversations**: `data/browser-connector/conversations/` - JSON files for each captured conversation
- **Extension**: `server/browser-connector/extension/` - Chrome extension source (loaded unpacked)

### Extension Architecture

The extension uses ChatGPT's internal API (not DOM scraping) for reliable data extraction:

1. **Content Script** (`content/chatgpt.js`): Runs on chatgpt.com, fetches conversations via `/backend-api/*` endpoints
2. **Background Script** (`background.js`): Relays captured data to MindSage backend
3. **Sync Detection**: URL parameter `?mindsage-sync=true` triggers force sync in headless mode

## Connector Types

- **api** - API-based data sources (token auth)
- **webhook** - Webhook receivers
- **file** - File import connectors
- **custom** - Custom scripts (ChatGPT, Readwise, Todoist, GitHub, Notion, Facebook)

### Facebook Connector

The Facebook connector processes ZIP exports from Facebook's "Download Your Information" feature.

**Supported Data Types (Indexed):**
- Posts (`posts/your_posts_1.json`) - Text content and attachment descriptions
- Comments (`comments/comments.json`) - Comment text
- Messages (`messages/inbox/*/message_*.json`) - Messenger conversations
- Profile data, search history, ad interests, liked pages

**Pending Media (Stored for Future):**
- Photos (`.jpg`, `.png`, `.gif`, etc.)
- Videos (`.mp4`, `.mov`, etc.)
- Audio (`.mp3`, `.m4a`, etc.)

Media files are extracted to `exports/{connectorId}/pending-media/` with a registry (`.registry.json`) tracking:
- Original path in export
- File type and size
- Context (messages, posts, profile)
- Storage timestamp

**API Endpoints:**
- `GET /api/connectors/:id/pending-media` - View pending media for a connector
- `GET /api/pending-media` - View all pending media across connectors

**Usage:**
1. Download your Facebook data at https://accountscenter.facebook.com/info_and_permissions/dyi
2. Select JSON format
3. Create a Facebook connector (type: custom, script: facebook-import)
4. Upload the ZIP file via the connector upload endpoint

## Key Patterns

### Background Indexing
File indexing runs in a background queue to avoid blocking uploads:
1. File uploaded/received via LocalSend
2. Moved to imports directory
3. Queued for background indexing
4. Extraction runs asynchronously (embedding similarity + spaCy NER)

### LocalSend Protocol
Built-in LocalSend server for receiving files from mobile devices:
- mDNS/Bonjour discovery on local network
- Compatible with LocalSend mobile app
- Auto-imports received files for indexing

### Vector Store Client
All vector store operations go through `server/vector-store-client.ts`:
```typescript
import { getVectorStoreClient, isVectorStoreAvailable } from './vector-store-client.js';

const available = await isVectorStoreAvailable();
const client = getVectorStoreClient();
const results = await client.search(query, topK);
```

## GPU Memory Management

Due to limited shared memory, **only one large model can be on GPU at a time**:

| Model | Type Enum | Size on GPU | Purpose |
|-------|-----------|-------------|---------|
| Embedding | EMBEDDING | ~90MB | Search/indexing embeddings |
| Reranker | RERANKER | ~250MB | Search quality |
| Whisper | TRANSCRIPTION | ~1GB | Audio file transcription (file upload only) |
| BLIP | CAPTION | ~1.5GB | Image captioning |
| LPRAG Vocab | LPRAG_VOCAB | ~50MB | Privacy perturbation |
| spaCy NER | N/A (CPU only) | ~50MB (CPU) | Entity extraction |

The ModelManager swaps models on/off GPU as needed. Media models (Whisper, BLIP) automatically retry GPU loading up to 3 times with 5s delays if CUDA memory is unavailable.

**Note:** Voice mode uses Groq cloud APIs (STT + TTS) and requires **zero GPU memory**. The local Whisper model above is only for file upload transcription, not voice.

See `vector-store/CLAUDE.md` for details on model management.

## Performance Considerations

- **Avoid loading multiple models on GPU simultaneously** - will cause OOM (ModelManager automatically swaps models)
- **Media processing is GPU-intensive** - Whisper (~1GB) and BLIP (~1.5GB) require model swapping
- **Use async extraction** - don't block document addition on extraction
- **Prefer batch operations** - reduces model loading overhead
- **Monitor `/api/stats`** - shows extraction queue and cache status
- **Media files auto-retry GPU loading** - 3 retries with 5s delays handle memory contention

## Voice Mode (All-Groq Cloud Pipeline)

Real-time voice interaction using WebRTC. All voice processing runs via Groq cloud APIs — no local voice models needed, zero GPU overhead.

### Pipeline

```
Mic → WebRTC → Groq Whisper STT → PII Anonymize → RAG → Groq LLM → Groq TTS → WebRTC → Speaker
```

### Components

| Component | Service | Model |
|-----------|---------|-------|
| Speech-to-Text | Groq Whisper | `whisper-large-v3` |
| Text-to-Speech | Groq Orpheus | `canopylabs/orpheus-v1-english` |
| LLM | Groq/Anthropic/OpenAI | Configurable (default: `llama-3.3-70b-versatile`) |

### PII in Voice

PII protection is fully integrated into the voice pipeline:
- The **entire system prompt** (RAG excerpts + source names + filenames) is anonymized in one pass via LPRAG
- The LLM only sees perturbed names/numbers and responds with them
- **TTS speaks perturbed values** — audio never contains real PII
- **De-anonymization** only happens for the chat UI text display
- Result: what you hear (audio) is privacy-safe, what you see (screen) shows real data

### WebRTC Connection Lifecycle

- Frontend sends `sendBeacon` on page unload for reliable disconnect
- Each new connection calls disconnect first to clear stale sessions
- Server force-closes all peer connections on disconnect
- FastRTC `concurrency_limit=1` ensures single active session

### Requirements

- `GROQ_API_KEY` environment variable or `groqApiKey` in `data/llm-config.json`
- Groq Orpheus model terms accepted at Groq console

## PII Protection

MindSage includes on-device PII (Personally Identifiable Information) protection using Microsoft Presidio. When search results are returned via MCP tools, PII is automatically detected and replaced with tokens.

> **Architecture Deep Dive**: For detailed analysis of why this architecture was chosen over alternatives (server-side, LLM-side, pre-embedding anonymization), see [docs/PII-ARCHITECTURE.md](docs/PII-ARCHITECTURE.md).

### How It Works

1. **Outbound (Search → LLM)**: Search results are scanned for PII (names, emails, phones, SSN, etc.)
2. **Tokenization**: PII is replaced with tokens like `<PII:PERSON:abc123>`
3. **Session Storage**: Original values stored in session-scoped memory (1-hour TTL)
4. **Inbound (LLM → User)**: De-anonymize API restores original values for user display

### PII Protection Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  SEARCH FLOW (Steps 1-4)                                                    │
│                                                                             │
│  ┌──────────────┐      ┌──────────────┐      ┌──────────────────────────┐  │
│  │     USER     │      │   WEB APP    │      │      EXTERNAL LLM        │  │
│  │  (on-device) │      │  (on-device) │      │  (Claude, GPT, Ollama)   │  │
│  └──────┬───────┘      └──────┬───────┘      └────────────┬─────────────┘  │
│         │                     │                           │                 │
│         │  1. "What did       │                           │                 │
│         │     John email?"    │   2. Forward query        │                 │
│         │────────────────────>│──────────────────────────>│                 │
│         │                     │                           │                 │
│         │                     │                           │  3. LLM calls   │
│         │                     │                           │     MCP tool    │
│         │                     │                           │        │        │
│         │                     │              ┌────────────┼────────┘        │
│         │                     │              │            │                 │
│         │                     │              ▼            │                 │
│         │                     │   ┌──────────────────┐    │                 │
│         │                     │   │   VECTOR STORE   │    │                 │
│         │                     │   │    (port 8085)   │    │                 │
│         │                     │   │                  │    │                 │
│         │                     │   │  PII Protector   │    │                 │
│         │                     │   │  anonymizes:     │    │                 │
│         │                     │   │  "John Smith" →  │    │                 │
│         │                     │   │  <PII:PERSON:x>  │    │                 │
│         │                     │   └────────┬─────────┘    │                 │
│         │                     │            │              │                 │
│         │                     │            │ Returns      │                 │
│         │                     │            │ anonymized   │                 │
│         │                     │            │ results      │                 │
│         │                     │            └─────────────>│                 │
│         │                     │                           │                 │
│         │                     │   4. LLM response         │                 │
│         │                     │      (contains tokens)    │                 │
│         │                     │<──────────────────────────┤                 │
│         │                     │                           │                 │
└─────────┼─────────────────────┼───────────────────────────┼─────────────────┘
          │                     │                           │
┌─────────┼─────────────────────┼───────────────────────────┼─────────────────┐
│  DE-ANONYMIZE FLOW (Steps 5-6)│                           │                 │
│         │                     │                           │                 │
│         │                     │  5. Web app calls         │                 │
│         │                     │     de-anonymize API      │                 │
│         │                     │     (localhost only)      │                 │
│         │                     │              │            │                 │
│         │                     │              ▼            │                 │
│         │                     │   ┌──────────────────┐    │                 │
│         │                     │   │   VECTOR STORE   │    │                 │
│         │                     │   │                  │    │                 │
│         │                     │   │  Token Session:  │    │                 │
│         │                     │   │  x → "John Smith"│    │                 │
│         │                     │   │                  │    │                 │
│         │                     │   │  Restores:       │    │                 │
│         │                     │   │  <PII:PERSON:x> →│    │                 │
│         │                     │   │  "John Smith"    │    │                 │
│         │                     │   └────────┬─────────┘    │                 │
│         │                     │            │              │                 │
│         │                     │<───────────┘              │                 │
│         │                     │                           │                 │
│         │  6. Display with    │                           │                 │
│         │     real PII        │                           │                 │
│         │<────────────────────┤                           │                 │
│         │                     │                           │                 │
│  "Based on John Smith's email, the meeting is at 3pm..."  │                 │
│         │                     │                           │                 │
└─────────┴─────────────────────┴───────────────────────────┴─────────────────┘

KEY: The LLM only ever sees tokens like <PII:PERSON:x>, never real PII.
     Only the on-device web app can call the de-anonymize API.
```

### Data Flow Summary

| Step | Direction | Data | PII Status |
|------|-----------|------|------------|
| 1 | User → Web App → LLM | User query | N/A |
| 2 | LLM (via MCP Client) → Vector Store | MCP search call | N/A |
| 3 | Vector Store → LLM | Search results | **Anonymized** (tokens) |
| 4 | LLM → Web App | Response | Contains tokens |
| 5 | Web App → Vector Store | De-anonymize REST API | Tokens + session_id |
| 6 | Vector Store → Web App | Restored text | **Original PII** |

**Key Architecture Points:**
- The **LLM** (via its MCP Client) makes the `search_documents` tool call - NOT the web app
- The **Web Application** only sends user queries to the LLM and receives responses
- The **Web Application** calls the de-anonymize REST API (localhost-only) to restore PII
- The **LLM never sees real PII** - only tokens like `<PII:PERSON:x>`

**Security Note:** The de-anonymize API is restricted to localhost/on-device clients only. External LLMs cannot access original PII values.

### Token Format
```
<PII:TYPE:TOKEN_ID>
Examples:
  <PII:PERSON:xYz12AbC>       - Person name
  <PII:EMAIL_ADDRESS:pQr34StU> - Email address
  <PII:PHONE_NUMBER:vWx56YzA>  - Phone number
```

### Supported PII Types

By default, all Presidio-supported entity types are detected:

**Core Types:**
- PERSON, EMAIL_ADDRESS, PHONE_NUMBER, CREDIT_CARD
- CRYPTO, DATE_TIME, DOMAIN_NAME, IBAN_CODE, IP_ADDRESS
- LOCATION, NRP, MEDICAL_LICENSE, URL

**US-specific:** US_BANK_NUMBER, US_DRIVER_LICENSE, US_ITIN, US_PASSPORT, US_SSN

**UK-specific:** UK_NHS

**Australia:** AU_ABN, AU_ACN, AU_TFN, AU_MEDICARE

**Europe:** ES_NIF, IT_FISCAL_CODE, IT_DRIVER_LICENSE, IT_VAT_CODE, IT_PASSPORT, IT_IDENTITY_CARD, PL_PESEL

**Asia:** SG_NRIC_FIN, IN_PAN, IN_AADHAAR, IN_VEHICLE_REGISTRATION

### Configuring PII Entity Types

Use the `PII_ENTITIES` environment variable to customize which types are detected:

```bash
# Use a preset
PII_ENTITIES=minimal   # PERSON, EMAIL_ADDRESS, PHONE_NUMBER only
PII_ENTITIES=default   # Common types (names, contact, financial)
PII_ENTITIES=strict    # All supported types (default behavior)

# Or specify a custom list
PII_ENTITIES=PERSON,EMAIL_ADDRESS,IBAN_CODE,UK_NHS
```

### De-anonymization

**REST API** (for any on-device app):
```bash
curl -X POST http://localhost:8085/api/pii/deanonymize \
  -H "Content-Type: application/json" \
  -d '{"text": "Response with <PII:PERSON:abc123>", "session_id": "xyz..."}'
```

**MCP Tool** (localhost clients only):
The `deanonymize_text` MCP tool is only visible to clients connecting from localhost (127.0.0.1, ::1). Remote LLM applications will not see this tool in the tool list.

```json
{
  "tool": "deanonymize_text",
  "arguments": {
    "text": "Response with <PII:PERSON:abc123>",
    "session_id": "xyz..."
  }
}
```

### Installation

PII protection requires additional dependencies:
```bash
pip install presidio-analyzer presidio-anonymizer spacy
python -m spacy download en_core_web_sm
```

If dependencies are not installed, search works normally without PII protection (graceful degradation).

### Session Management

PII tokens are stored in sessions that map token IDs back to original values.

**Session Lifecycle:**
- **Creation**: A new session is created automatically on the first search (if no `session_id` provided)
- **Reuse**: Pass `session_id` from a previous search response to accumulate tokens in the same session
- **Sliding TTL**: Sessions expire 1 hour after their **last activity** (not creation time)
- **Activity Refresh**: TTL is automatically extended on every deanonymize call or explicit refresh
- **Eviction**: When max sessions (100) is reached, oldest session is evicted (LRU)
- **Storage**: In-memory only - sessions are lost on server restart

**Sliding TTL Behavior:**
Sessions use activity-based expiration to avoid expiring while the user is actively using the app:
1. Initial TTL: 1 hour from session creation
2. Each `deanonymize` call refreshes the TTL to 1 hour from that moment
3. Clients can explicitly refresh TTL via `/api/pii/session/{id}/refresh`

**Search Response:**
```json
{
  "pii_session_id": "aBcDeFgH...",
  "results": [...]
}
```

**Session Info Response:**
```json
{
  "session_id": "aBcDeFgH...",
  "created_at": "2025-01-24T10:00:00",
  "last_accessed": "2025-01-24T10:30:00",
  "expires_at": "2025-01-24T11:30:00",
  "ttl_remaining_seconds": 3540,
  "is_expired": false,
  "token_count": 15
}
```

**Client Responsibility:**
1. Capture `pii_session_id` from search responses
2. Store it for the duration of the conversation
3. Pass it to de-anonymize API when restoring PII in LLM responses
4. Optionally call `/api/pii/session/{id}/refresh` to keep sessions alive during long idle periods
5. Optionally call `DELETE /api/pii/session/{id}` to explicitly end a session

**Explicit Session Refresh:**
```bash
# Refresh session TTL without deanonymizing
curl -X POST http://localhost:8085/api/pii/session/{session_id}/refresh
```

**Important:** If the client doesn't track the session_id, tokens from previous searches cannot be de-anonymized.

### Health Checks

The vector store `/health` endpoint now includes PII subsystem status:
```bash
curl http://localhost:8085/health
```
```json
{
  "status": "healthy",
  "service": "mcp-vector-store",
  "pii_protection": {
    "available": true,
    "initialized": true
  }
}
```

For detailed PII health information, use the dedicated endpoint:
```bash
curl http://localhost:8085/health/pii
```
```json
{
  "status": "healthy",
  "healthy": true,
  "presidio_available": true,
  "analyzer_initialized": true,
  "spacy_model": "en_core_web_sm",
  "active_sessions": 5,
  "entities_configured": 31
}
```

Returns HTTP 503 if PII protection is unavailable or degraded.

### Docker Deployment

PII protection is included in Docker images. Configure via environment variable:

```yaml
# docker-compose.yml
services:
  vector-store:
    environment:
      # Options: "minimal", "default", "strict", or comma-separated list
      - PII_ENTITIES=strict
```

The Dockerfiles automatically:
- Install Presidio dependencies from requirements.txt
- Download the spaCy `en_core_web_sm` model during build

### Memory Footprint
- **spaCy + Presidio**: ~150MB (runs on CPU, not GPU)
- **Token sessions**: ~1KB per 100 tokens

## LPRAG (Locally Private RAG)

LPRAG provides Local Differential Privacy (LDP) for PII protection. Instead of just replacing PII with opaque tokens, LPRAG perturbs values to semantically similar alternatives using differential privacy, so the LLM can still reason about the data while mathematical privacy guarantees are maintained.

### Token-based vs LPRAG Comparison

| Approach | Example Output | LLM Reasoning | Reversibility | Privacy Guarantee |
|----------|---------------|---------------|---------------|-------------------|
| Token-based | `<PII:PERSON:abc>` | Limited - opaque token | ✓ Full | Information hidden |
| LPRAG Hybrid | `Michael Chen` | ✓ Full - semantic | ✓ Full | ε-differential privacy |
| LPRAG Pure | `Michael Chen` | ✓ Full - semantic | ✗ None | ε-differential privacy |

### How LPRAG Works

1. **PII Detection**: Same as token-based (Presidio detects PII entities)
2. **Adaptive Privacy Budget**: Assigns epsilon (ε) based on sensitivity
   - Critical (SSN, credit cards): ε=0.1 (strongest privacy)
   - High (phone, email): ε=0.5
   - Medium (names): ε=1.0
   - Low (dates): ε=2.0
3. **Perturbation**: Three modules based on PII type
   - **Word Module**: Names/locations → semantically similar words (exponential mechanism)
   - **Number Module**: Phone/SSN → noisy numbers (Laplace mechanism)
   - **Phrase Module**: Email/addresses → segment-wise perturbation
4. **Session Mapping**: Hybrid mode stores bidirectional mapping for de-anonymization

### Configuration

**LPRAG hybrid mode is enabled by default** for best balance of privacy and usability.
To disable and use token-only anonymization, set `LPRAG_MODE=disabled`.

```bash
# Environment variables
LPRAG_MODE=hybrid              # disabled | pure | hybrid (default: hybrid)
LPRAG_PRESET=default           # minimal | default | aggressive | high-quality
LPRAG_EPSILON=1.0              # Global epsilon override
LPRAG_USE_GPU=false            # true = use Sentence Transformers (GPU)
```

### Presets

| Preset | Mode | Global ε | Semantic Similarity | GPU | Memory |
|--------|------|----------|---------------------|-----|--------|
| disabled | token-only | - | No | - | 0 MB |
| minimal | hybrid | 2.0 | No (random) | No | ~10 MB |
| default | hybrid | 1.0 | GloVe | No | ~50 MB CPU |
| aggressive | pure | 0.5 | GloVe | No | ~50 MB CPU |
| high-quality | hybrid | 1.0 | Sentence Transformers | Yes | ~100 MB VRAM |

### LPRAG Flow (Hybrid Mode)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  SEARCH: Document contains "Email from John Smith (john@example.com)"       │
│                                                                             │
│  1. Presidio Detection:                                                     │
│     PERSON: "John Smith"                                                    │
│     EMAIL: "john@example.com"                                               │
│                                                                             │
│  2. LPRAG Perturbation (ε-differential privacy):                            │
│     "John Smith" → "Michael Chen" (word module, ε=1.0)                      │
│     "john@example.com" → "mike@sample.org" (phrase module, ε=0.5)           │
│                                                                             │
│  3. Session stores bidirectional mapping:                                   │
│     token_abc: original="John Smith", perturbed="Michael Chen"              │
│                                                                             │
│  Output to LLM: "Email from Michael Chen (mike@sample.org)"                 │
├─────────────────────────────────────────────────────────────────────────────┤
│  DE-ANONYMIZE: LLM generates "Based on Michael Chen's email..."             │
│                                                                             │
│  4. Scan for perturbed values in session, replace with originals:           │
│     "Michael Chen" → "John Smith"                                           │
│                                                                             │
│  User sees: "Based on John Smith's email..."                                │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Fallback to Tokens

LPRAG gracefully falls back to token-based anonymization when:
- Entity type not supported by LPRAG (e.g., custom recognizers)
- No similar words found in vocabulary
- Embeddings not loaded (memory constraint)
- gensim not installed

### API Endpoints

**Health Check:**
```bash
curl http://localhost:8085/health/lprag
```

**Status:**
```bash
curl http://localhost:8085/api/lprag/status
```

**Configuration:**
```bash
curl http://localhost:8085/api/lprag/config
```

### Installation

LPRAG requires additional dependencies for GloVe embeddings:
```bash
pip install gensim>=4.3.0
```

The first time LPRAG runs, it will download GloVe embeddings (~66MB for glove-wiki-gigaword-50).

### Memory Footprint with LPRAG
- **spaCy + Presidio**: ~150MB (runs on CPU)
- **GloVe 50-dim embeddings**: ~50MB (CPU, lazy loaded)
- **Total with LPRAG enabled**: ~205MB
