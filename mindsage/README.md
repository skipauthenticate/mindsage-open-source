# MindSage

A privacy-first data aggregation platform that centralizes and protects your personal data from multiple sources, including AI conversation exports.

## Features

- **Custom Script Connectors**: Run custom data export scripts (like ChatGPT conversation export)
- **Multiple Data Sources**: Connect to APIs, webhooks, file imports, and custom scripts
- **Semantic Search**: AI-powered search across all your data using MCP Vector Store integration
- **Typed Agent Memory**: Versioned claims, decisions, tasks, artifacts, entities, relations, and summaries with audit timelines and relation graphs
- **LocalSend**: Built-in LocalSend protocol server for receiving files from mobile devices
- **Browser Connector**: Persistent Chrome browser with extension for capturing AI chat conversations
- **Storage Management**: Track storage usage, item counts, and sync status across all data sources
- **PII Protection**: On-device PII anonymization with LPRAG differential privacy
- **Image PII Redaction**: Async OCR-based PII detection with automatic redaction for images
- **Privacy-First**: All data stored locally, no cloud dependencies

## Architecture

MindSage consists of two backend services and a separate frontend:

1. **Backend** (Node.js + Express): API server that handles data connectors, file management, and proxies to the vector store
2. **Vector Store** (Python + FastAPI): ML service for semantic search, topic classification, passage extraction, and PII protection
3. **Frontend** (React + Vite): Separate repo ([mindsage-frontend](https://github.com/skipauthenticate/mindsage-frontend))

```
workspace/
├── mindsage/              # This repo (backend + vector store)
└── mindsage-frontend/     # Frontend repo (separate)
```

## Getting Started

### Prerequisites

- Node.js 18+
- Python 3.8+ with pip
- Chrome/Chromium (for Browser Connector)

### Installation

```bash
# Install Node.js dependencies
npm install

# Install Python dependencies for vector store
npm run vector-store:setup
```

### Development

Run backend and vector store together:

```bash
npm run dev:all
```

This starts:
- **Backend** at http://localhost:3003 (with auto-restart via tsx watch)
- **Vector Store** at http://localhost:8085 (Python FastAPI)

Or run services separately:

```bash
# Terminal 1 - Backend (port 3003)
npm run dev:server

# Terminal 2 - Vector Store (port 8085)
npm run vector-store:start
```

For detailed development instructions, see [DEVELOPMENT.md](DEVELOPMENT.md).

### Production Build

```bash
# Build backend
npm run build

# Start production server
npm start
```

## Docker

MindSage can be run entirely in Docker containers, with memory limits that simulate Jetson Orin Nano 8GB hardware constraints.

### Quick Start with Docker

```bash
# Full stack (frontend + backend + vector store)
docker compose -f docker-compose.full.yml up -d --build

# Backend + vector store only (no frontend)
docker compose up -d --build
```

Access points:
- **Frontend**: http://localhost:8080
- **Backend API**: http://localhost:3003
- **Vector Store**: http://localhost:8085
- **noVNC** (Browser Connector): http://localhost:6080/vnc.html (when VNC mode enabled)

### Docker Compose Files

| File | Services | Use Case |
|------|----------|----------|
| `docker-compose.yml` | Backend + Vector Store | Backend-only deployment |
| `docker-compose.jetson.yml` | Override for Jetson | GPU support, host networking |
| `docker-compose.full.yml` | Frontend + Backend + Vector Store | Full stack deployment |

### Full Stack Deployment

The `docker-compose.full.yml` includes all services with Jetson-like memory constraints:

```bash
# Start all services
docker compose -f docker-compose.full.yml up -d --build

# View logs
docker compose -f docker-compose.full.yml logs -f

# Stop all services
docker compose -f docker-compose.full.yml down
```

**Memory Limits** (simulating Jetson Orin Nano ~7.4GB shared RAM):

| Service | Port | Memory Limit | Description |
|---------|------|--------------|-------------|
| Frontend | 8080 | 256 MB | Nginx serving React app |
| Backend | 3003, 6080 | 1.5 GB | Node.js Express API + VNC + Browser |
| Vector Store | 8085 | 6 GB | Python ML service |

**Note**: Backend memory increased to 1.5 GB to accommodate Chromium browser (~500MB) and VNC stack (~45MB) when using Browser Connector.

**Prerequisites**: The frontend repo must be cloned as a sibling directory:
```
workspace/
├── mindsage/           # This repo (backend)
└── mindsage-frontend/  # Frontend repo
```

### Backend-Only Deployment

For running without the frontend (API-only mode):

```bash
# Standard deployment
docker compose up -d --build

# On Jetson with GPU support
docker compose -f docker-compose.yml -f docker-compose.jetson.yml up -d --build
```

### Jetson Orin Nano Deployment

For actual Jetson hardware with GPU acceleration:

```bash
# Uses NVIDIA L4T base image and GPU runtime
docker compose -f docker-compose.yml -f docker-compose.jetson.yml up -d --build
```

Features:
- NVIDIA L4T base image for GPU support
- Host networking for LocalSend UDP multicast
- CUDA-accelerated PyTorch for ML models

### Building Individual Images

```bash
# Backend
docker build -t mindsage .

# Vector Store (CPU)
docker build -t mindsage-vector-store ./vector-store

# Vector Store (Jetson GPU)
docker build -f ./vector-store/Dockerfile.jetson -t mindsage-vector-store ./vector-store
```

### Docker Files

```
mindsage/
├── Dockerfile                  # Backend (Node.js)
├── docker-compose.yml          # Backend + Vector Store
├── docker-compose.jetson.yml   # Jetson GPU override
├── docker-compose.full.yml     # Full stack with frontend
└── vector-store/
    ├── Dockerfile              # Vector Store (CPU)
    └── Dockerfile.jetson       # Vector Store (Jetson GPU)
```

### Environment Variables

Configure via docker-compose environment section or `.env` file:

```bash
# Backend
PORT=3003
NODE_ENV=production
VECTOR_STORE_HOST=vector-store  # Use 'localhost' with host networking
VECTOR_STORE_PORT=8085

# Vector Store
PII_ENTITIES=strict  # Options: minimal, default, strict

# LLM (optional)
ANTHROPIC_API_KEY=your-key
OPENAI_API_KEY=your-key
GROQ_API_KEY=your-key
```

### Troubleshooting Docker

**Container name conflict**:
```bash
docker stop mindsage mindsage-vector-store mindsage-frontend
docker rm mindsage mindsage-vector-store mindsage-frontend
docker compose -f docker-compose.full.yml up -d
```

**View container logs**:
```bash
docker compose -f docker-compose.full.yml logs -f vector-store
```

**Check memory usage**:
```bash
docker stats --no-stream
```

**Rebuild without cache**:
```bash
docker compose -f docker-compose.full.yml build --no-cache
```

## Browser Connector (Recommended)

The Browser Connector is the recommended way to capture ChatGPT conversations. It uses a persistent browser with a Chrome extension that captures conversations via ChatGPT's internal API.

**Key Features:**
- **One-time VNC login**: Log in once via VNC, then sync works automatically
- **Headless sync**: After initial login, syncs run in the background without needing VNC
- **Auto-sync**: Configurable automatic sync (default: every 5 hours)
- **Manual sync**: Trigger sync anytime via UI button or API
- Handles 2FA naturally (you login yourself)
- No bot detection issues (uses real Chrome with persistent profile)

For architecture details, see [docs/BROWSER-CONNECTOR-DESIGN.md](docs/BROWSER-CONNECTOR-DESIGN.md).

### Quick Start

**First-Time Setup (VNC login required):**

1. Open MindSage UI at `http://localhost:8080`
2. Click on the **ChatGPT** connector card in Data Connectors
3. Click **Launch VNC Login** button
4. Connect to noVNC at the displayed URL (password: `mindsage`)
5. Log into ChatGPT in the browser
6. Extension automatically syncs all your conversations
7. Close the browser when done

**Subsequent Syncs (headless - no VNC needed):**

1. Click on the **ChatGPT** connector card
2. Click **Sync Now** to trigger a manual sync
3. Or enable **Auto-Sync** toggle to sync automatically every few hours
4. Syncs run in the background using your saved session

### VNC Remote Access

For headless deployments (like Jetson Orin Nano without a monitor), VNC mode lets you access the browser from any device on your network:

```bash
# Install VNC dependencies (on host or already included in Docker)
sudo apt install xvfb x11vnc novnc websockify

# Launch browser via API with VNC (first-time login)
curl -X POST http://localhost:3003/api/browser-connector/launch \
  -H "Content-Type: application/json" \
  -d '{"vnc": true, "startUrl": "https://chatgpt.com"}'

# Access from any device: http://<device-ip>:6080/vnc.html
# Password: mindsage
```

### Headless Sync API

After initial VNC login, use these endpoints for headless operation:

```bash
# Check if authenticated (has logged in before)
curl http://localhost:3003/api/browser-connector/auth-status

# Trigger manual sync (runs headlessly using saved session)
curl -X POST http://localhost:3003/api/browser-connector/sync

# Enable auto-sync (every 5 hours)
curl -X POST http://localhost:3003/api/browser-connector/auto-sync/start \
  -H "Content-Type: application/json" \
  -d '{"intervalHours": 5}'

# Check auto-sync status
curl http://localhost:3003/api/browser-connector/auto-sync
```

### How It Works

1. **Persistent Profile**: Chrome stores session cookies in `data/browser-connector/chromium-profile/`
2. **Extension**: Custom Chrome extension captures conversations via ChatGPT's API
3. **Virtual Display**: Headless syncs use Xvfb (virtual framebuffer) so extensions work properly
4. **Inactivity Detection**: Sync completes after 30 seconds of no new captures

### Docker Support

Browser Connector with VNC is fully supported in Docker. The Dockerfile includes Chromium and all VNC dependencies:

```bash
# Start containers
docker compose up -d

# Browser connector is ready - use VNC mode for first-time login
```

---

## ChatGPT Export (Legacy - Custom Script)

The ChatGPT export functionality is also available as a custom script connector that uses Playwright to automate conversation exports. **Note: Browser Connector above is now the recommended approach.**

For detailed information, see [CUSTOM_SCRIPTS.md](CUSTOM_SCRIPTS.md).

### How It Works

- Uses Playwright with stealth plugin to avoid detection
- Logs into ChatGPT using your credentials
- Saves browser session for future runs (no need to login again)
- Extracts conversation list from sidebar
- Exports each conversation as JSON with messages
- Tracks exported IDs to avoid duplicates
- Stores exports in `data/exports/{connector-id}/`

### Data Format

Each exported conversation is saved as JSON:

```json
{
  "id": "conversation-uuid",
  "title": "Conversation Title",
  "messages": [
    {
      "role": "user",
      "content": "User message..."
    },
    {
      "role": "assistant",
      "content": "Assistant response..."
    }
  ],
  "exportedAt": "2026-01-18T12:00:00.000Z"
}
```

## API Endpoints

### Connectors

- `GET /api/connectors` - List all connectors
- `POST /api/connectors` - Add new connector
- `PUT /api/connectors/:id` - Update connector
- `DELETE /api/connectors/:id` - Remove connector
- `POST /api/connectors/:id/sync` - Trigger sync
- `GET /api/connectors/:id/status` - Get sync status
- `POST /api/connectors/:id/stop` - Stop running sync

### Stats

- `GET /api/stats` - Get storage and usage statistics

### Exports

- `GET /api/connectors/:id/exports` - List exported files
- `GET /api/connectors/:id/exports/:filename` - Get export content

## Project Structure

```
mindsage/
├── server/                # Backend source
│   ├── index.ts           # Express server (all API endpoints)
│   ├── chat-service.ts    # LLM integration (OpenAI/Anthropic/Groq)
│   ├── vector-store-client.ts # Vector store API client
│   ├── localsend-server.ts    # LocalSend protocol implementation
│   ├── browser-connector/     # Persistent browser for AI chat capture
│   │   ├── manager.ts        # Chrome launch & lifecycle
│   │   ├── processor.ts      # Capture processing & indexing
│   │   ├── api.ts            # Express routes
│   │   └── extension/        # Chrome extension source
│   └── scripts/               # Export scripts (Browser Connector handles AI chat capture)
│       ├── export-facebook.ts
│       └── export-notion.ts
├── vector-store/          # Python ML service (see vector-store/CLAUDE.md)
│   └── mcp_vector_store/  # Main package
├── data/                  # Data storage (created at runtime)
│   ├── connectors.json    # Connector configurations
│   ├── llm-config.json    # LLM provider settings
│   ├── vectordb/          # txtai vector database (SQLite FTS5)
│   ├── uploads/           # Received files (LocalSend, HTTP upload)
│   ├── imports/           # Files queued for indexing
│   ├── exports/           # Connector export data
│   ├── models/            # Downloaded ML models
│   └── browser-connector/ # Browser profiles & captured conversations
├── dist-server/           # Compiled JavaScript output
├── docs/                  # Design documents
└── novnc-web/             # noVNC web interface
```

## Tech Stack

### Backend
- Node.js with Express
- TypeScript
- Playwright for browser automation (legacy export scripts)
- Built-in LocalSend protocol server

### Vector Store
- Python with FastAPI/Starlette
- txtai (hybrid search: BM25 + vectors, SQLite FTS5)
- ONNX Runtime for model inference
- sentence-transformers for embeddings
- spaCy for NER
- Microsoft Presidio for PII detection
- MCP (Model Context Protocol) support

## Environment Variables

Create a `.env` file in the root directory:

```env
PORT=3003
VITE_API_URL=http://localhost:3003
VECTOR_STORE_HOST=localhost
VECTOR_STORE_PORT=8085
```

## Scripts Reference

```bash
# Development
npm run dev:server          # Backend only (port 3003)
npm run dev:all             # Backend + Vector Store

# Build
npm run build               # Build backend (TypeScript -> JavaScript)

# Production
npm start                   # Run production server
npm run start:all           # Run production + Vector Store

# Vector Store
npm run vector-store:start  # Start vector store service
npm run vector-store:setup  # Install Python deps + download models

# Data Management
npm run data:clean          # Clear vectordb, uploads, and imports
```

## MCP Vector Store Integration

MindSage includes a vector store powered by txtai and sentence-transformers for AI-powered semantic search across all your indexed data. Agent clients should start with the MCP `think` tool when they need cited, PII-safe reasoning context with answer/source/concept/contradiction graph links, safe entity graph links, source coverage, freshness warnings, gaps, and citation-maintenance actions for stale, undated, weak, or conflicted evidence. For structured agent memory, use `write_memory`, `search_memory`, `memory_workspace_info`, `memory_actor_activity`, `memory_timeline`, and `memory_graph` to store typed/versioned claims, decisions, tasks, artifacts, entities, relations, and summaries with workspace scope, lifecycle state, retention, workspace summaries, actor activity, audit events, and relation/source-document traversal. Remote MCP access is supported only through public mode with a 32+ character bearer token and a private tunnel or HTTPS gateway. Retrieval quality is guarded by fixture-corpus evals that exercise named-thing lookup, cross-source citations, and PII-safe excerpts over the tracked synthetic personal-data corpus.

### Prerequisites

- Python 3.8+ installed
- pip (Python package manager)

### Setup Vector Store

1. **Install vector store dependencies** (first time only):
   ```bash
   npm run vector-store:setup
   ```
   This installs the required Python packages and downloads the embedding model.

2. **Start the vector store server**:
   ```bash
   npm run vector-store:start
   ```

   Or run everything together (backend + vector store):
   ```bash
   npm run dev:all
   ```

3. **Index your data**: After syncing connectors, data can be indexed via the API:
   ```bash
   curl -X POST http://localhost:3003/api/vector-store/index-connector/{connectorId}
   ```

4. **Search**: Use the Semantic Search panel in the frontend UI to search across all your indexed data.

### How It Works

The vector store uses:
- **txtai**: Hybrid search engine combining BM25 text search + vector similarity search, backed by SQLite FTS5
- **sentence-transformers**: Pre-trained models for generating semantic embeddings
  - GPU: `all-mpnet-base-v2` (768 dims, higher quality)
  - CPU/Jetson: `all-MiniLM-L6-v2` (384 dims, faster)

All processing happens locally - no data leaves your machine.

### Configuration

Set these environment variables in `.env` (optional, defaults work for local setup):

```env
VECTOR_STORE_HOST=localhost
VECTOR_STORE_PORT=8085
```

### Vector Store API Endpoints

- `GET /api/vector-store/status` - Check vector store connection status
- `POST /api/vector-store/search` - Semantic search (`{ query, topK }`)
- `POST /api/vector-store/search/enhanced` - Search with passage extraction
- `POST /api/vector-store/documents` - Add document (`{ text, metadata }`)
- `POST /api/vector-store/documents/batch` - Add multiple documents
- `GET /api/vector-store/documents` - List documents (paginated)
- `DELETE /api/vector-store/documents/:id` - Delete document
- `POST /api/vector-store/index-connector/:connectorId` - Index connector exports

## Security Notes

- Credentials are stored locally in `data/` directory
- Browser sessions are saved to avoid repeated logins
- All data stays on your machine
- No telemetry or external API calls (except to ChatGPT for sync)
- PII protection anonymizes sensitive data before sending to external LLMs

## Roadmap

- [x] LocalSend - Built-in file transfer protocol
- [x] Semantic search via MCP Vector Store integration
- [x] Browser Connector for ChatGPT sync
- [x] PII protection with LPRAG differential privacy
- [x] Image PII redaction with OCR (EasyOCR/Tesseract) + Presidio
- [x] Multimodal LLM support (Claude, GPT-4V) with PII-safe images
- [ ] Add more AI platform connectors (Claude, Perplexity, etc.)
- [ ] Data visualization and analytics
- [ ] Export to various formats (PDF, Markdown, etc.)
- [ ] Scheduled automatic syncs
- [ ] Mobile app
- [ ] End-to-end encryption for all data

## License

MIT

## Contributing

Contributions welcome! Please open an issue or PR.
