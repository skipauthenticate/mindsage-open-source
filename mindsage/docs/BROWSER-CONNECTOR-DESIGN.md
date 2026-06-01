# Browser Connector Architecture

This document explains the architectural design of MindSage's Browser Connector system, which captures AI conversations from ChatGPT using the platform's internal API.

## Overview

The Browser Connector provides a **persistent, user-controlled browser** where:
- Login sessions survive server restarts (cookies/sessions stored locally)
- Users login naturally to AI chat sites (including 2FA)
- Conversations are fetched via ChatGPT's internal API (not DOM scraping)
- All past conversations are automatically synced on first login
- New conversations are captured as you navigate to them

## Key Design Decision: API vs DOM Scraping

Inspired by [chatgpt-exporter](https://github.com/pionxzh/chatgpt-exporter), this implementation uses ChatGPT's internal backend API rather than DOM observation:

| Aspect | DOM Scraping | API-Based (Current) |
|--------|--------------|---------------------|
| **Reliability** | Breaks when UI changes | Stable API endpoints |
| **Data completeness** | Visible content only | Full message history with metadata |
| **Performance** | Requires page navigation | Fast parallel API calls |
| **Timestamps** | Estimated | Actual from API |
| **Model info** | Not available | Included in response |

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  CHROMIUM BROWSER (System Chrome, Persistent Profile)                        │
│  Profile stored in: data/browser-connector/chromium-profile/                 │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │  MindSage Capture Extension (auto-loaded via --load-extension)         │ │
│  │                                                                        │ │
│  │  ┌──────────────────────────────────────────────────────────────────┐ │ │
│  │  │  Content Script (chatgpt.js)                                     │ │ │
│  │  │                                                                  │ │ │
│  │  │  1. Get access token from /api/auth/session                      │ │ │
│  │  │  2. Fetch conversations via /backend-api/conversations           │ │ │
│  │  │  3. Fetch full data via /backend-api/conversation/:id            │ │ │
│  │  │  4. Send to background worker                                    │ │ │
│  │  └──────────────────────────────────────────────────────────────────┘ │ │
│  │                                 │                                      │ │
│  │                                 ▼                                      │ │
│  │  ┌──────────────────────────────────────────────────────────────────┐ │ │
│  │  │  Background Worker (background.js)                               │ │ │
│  │  │  - Relays captures to MindSage backend                           │ │ │
│  │  │  - Stores sync progress                                          │ │ │
│  │  └──────────────────────────────────────────────────────────────────┘ │ │
│  │                                 │                                      │ │
│  └─────────────────────────────────┼──────────────────────────────────────┘ │
│                                    │                                        │
└────────────────────────────────────┼────────────────────────────────────────┘
                                     │ HTTP POST
                                     │ localhost:3003/api/browser-connector/capture
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  MINDSAGE BACKEND (Express Server - port 3003)                               │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │  Browser Connector Module                                              │ │
│  │                                                                        │ │
│  │  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐     │ │
│  │  │  Manager         │  │  API Routes      │  │  Processor       │     │ │
│  │  │                  │  │                  │  │                  │     │ │
│  │  │  - Find Chrome   │  │  - /launch       │  │  - Deduplicate   │     │ │
│  │  │  - Spawn process │  │  - /close        │  │  - Normalize     │     │ │
│  │  │  - Profile mgmt  │  │  - /status       │  │  - Index to VS   │     │ │
│  │  │                  │  │  - /capture      │  │  - Save to disk  │     │ │
│  │  └──────────────────┘  └──────────────────┘  └────────┬─────────┘     │ │
│  │                                                       │                │ │
│  └───────────────────────────────────────────────────────┼────────────────┘ │
│                                                          │                  │
└──────────────────────────────────────────────────────────┼──────────────────┘
                                                           │
                                                           ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  VECTOR STORE (port 8085)                                                    │
│                                                                              │
│  - Indexes conversation as searchable document                               │
│  - Metadata: site, conversation_id, title, url, timestamps                   │
│  - Searchable via MindSage search/chat interface                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Data Flow

### Auto-Sync Flow (First Login)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Step 1: User logs into ChatGPT                                              │
│                                                                              │
│  Browser opens → User navigates to chatgpt.com → Logs in (handles 2FA)       │
│                                                                              │
├─────────────────────────────────────────────────────────────────────────────┤
│  Step 2: Extension detects login                                             │
│                                                                              │
│  Content script calls /api/auth/session → Gets access token                  │
│  Checks chrome.storage for initialSyncComplete flag                          │
│                                                                              │
├─────────────────────────────────────────────────────────────────────────────┤
│  Step 3: Fetch all conversations                                             │
│                                                                              │
│  GET /backend-api/conversations?offset=0&limit=100                           │
│  → Paginate until all conversations fetched                                  │
│  → Returns: [{id, title, create_time, update_time}, ...]                     │
│                                                                              │
├─────────────────────────────────────────────────────────────────────────────┤
│  Step 4: Fetch each conversation's full data                                 │
│                                                                              │
│  For each conversation:                                                      │
│    GET /backend-api/conversation/:id                                         │
│    → Returns full message tree with content, timestamps, model info          │
│    → Convert to MindSage format                                              │
│    → Send to backend via background worker                                   │
│                                                                              │
├─────────────────────────────────────────────────────────────────────────────┤
│  Step 5: Backend processes and indexes                                       │
│                                                                              │
│  Processor receives capture → Deduplicates → Saves to disk → Indexes         │
│                                                                              │
├─────────────────────────────────────────────────────────────────────────────┤
│  Step 6: Mark sync complete                                                  │
│                                                                              │
│  Set initialSyncComplete=true in chrome.storage                              │
│  Future visits only capture current conversation on navigation               │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### API Endpoints Used

| Endpoint | Purpose |
|----------|---------|
| `GET /api/auth/session` | Get access token for API calls |
| `GET /backend-api/conversations` | List all conversations (paginated) |
| `GET /backend-api/conversation/:id` | Get full conversation with messages |

## Component Details

### 1. Browser Manager (`manager.ts`)

Uses system Chrome/Chromium directly (not Playwright) to avoid bot detection:

```typescript
// Find system Chrome binary
function findChromeBinary(): string | null {
  const paths = [
    '/usr/bin/chromium-browser',
    '/usr/bin/google-chrome',
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  ];
  return paths.find(p => fs.existsSync(p)) || null;
}

// Launch with persistent profile + extension
spawn(chromeBinary, [
  `--user-data-dir=${PROFILE_DIR}`,
  `--load-extension=${EXTENSION_DIR}`,
  '--no-first-run',
  '--disable-gpu',
  startUrl,
]);
```

**Why System Chrome?**
- Playwright's Chromium has automation markers that trigger bot detection
- System Chrome is indistinguishable from user-launched browser
- Persistent profile preserves login sessions across restarts

### 2. Content Script (`chatgpt.js`)

Fetches data via ChatGPT's internal API:

```javascript
// Get access token
async function getAccessToken() {
  const response = await fetch('https://chatgpt.com/api/auth/session', {
    credentials: 'include',
  });
  const data = await response.json();
  return data.accessToken;
}

// Fetch all conversations with pagination
async function fetchAllConversations() {
  const conversations = [];
  let offset = 0;

  while (true) {
    const data = await apiRequest(`/conversations?offset=${offset}&limit=100`);
    conversations.push(...data.items);
    if (data.items.length < 100) break;
    offset += 100;
  }

  return conversations;
}

// Fetch single conversation
async function fetchConversation(id) {
  return apiRequest(`/conversation/${id}`);
}

// Convert API response to MindSage format
function convertConversation(apiData) {
  const messages = Object.values(apiData.mapping)
    .filter(node => node.message?.author?.role in ['user', 'assistant'])
    .map(node => ({
      id: node.message.id,
      role: node.message.author.role,
      content: extractContent(node.message.content),
      timestamp: new Date(node.message.create_time * 1000).toISOString(),
      model: node.message.metadata?.model_slug,
    }));

  return { conversationId: apiData.conversation_id, title: apiData.title, messages };
}
```

### 3. Background Worker (`background.js`)

Simple relay to backend:

```javascript
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === 'capture') {
    fetch('http://localhost:3003/api/browser-connector/capture', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(message.payload),
    })
    .then(r => r.json())
    .then(sendResponse);
    return true;
  }

  if (message.type === 'syncProgress') {
    chrome.storage.local.set({ syncProgress: message.payload });
  }
});
```

### 4. Processor (`processor.ts`)

Handles deduplication and indexing:

```typescript
async function processCapture(capture: CapturePayload) {
  // Load or create conversation
  const conversation = await loadConversation(capture.conversationId)
    || createConversation(capture);

  // Deduplicate messages by ID
  const existingIds = new Set(conversation.messages.map(m => m.id));
  const newMessages = capture.messages.filter(m => !existingIds.has(m.id));

  // Update conversation
  conversation.messages.push(...newMessages);
  conversation.updatedAt = new Date().toISOString();

  // Save and index
  await saveConversation(conversation);
  await indexToVectorStore(conversation);

  return { newMessages: newMessages.length };
}
```

## Data Storage

### Directory Structure

```
data/browser-connector/
├── chromium-profile/          # Chrome user data (cookies, localStorage)
├── captures/                  # Captured conversation JSON files
│   ├── chatgpt_abc-123.json
│   └── chatgpt_def-456.json
└── config.json                # User configuration
```

### Conversation File Format

```json
{
  "id": "abc-123-def-456",
  "site": "chatgpt",
  "title": "Quantum Computing Discussion",
  "url": "https://chatgpt.com/c/abc-123-def-456",
  "messages": [
    {
      "id": "msg-uuid-1",
      "role": "user",
      "content": "What is quantum computing?",
      "timestamp": "2024-01-27T12:00:00Z",
      "model": null
    },
    {
      "id": "msg-uuid-2",
      "role": "assistant",
      "content": "Quantum computing is...",
      "timestamp": "2024-01-27T12:00:05Z",
      "model": "gpt-4"
    }
  ],
  "createdAt": "2024-01-27T12:00:00Z",
  "updatedAt": "2024-01-27T12:00:05Z",
  "indexed": true
}
```

## API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/browser-connector/launch` | POST | Start Chrome with persistent profile |
| `/api/browser-connector/close` | POST | Close browser gracefully |
| `/api/browser-connector/status` | GET | Running state, capture stats |
| `/api/browser-connector/capture` | POST | Receive data from extension |
| `/api/browser-connector/conversations` | GET | List captured conversations |
| `/api/browser-connector/conversations/:id` | GET | Get conversation with messages |
| `/api/browser-connector/stats` | GET | Total conversations and messages |

## Extension Popup

The popup provides:
- Backend connection status
- Last sync time
- Indexed conversation/message counts
- Manual sync/re-sync button

## Security

| Aspect | Implementation |
|--------|---------------|
| **Profile storage** | Local only (`data/browser-connector/chromium-profile/`) |
| **API calls** | Use user's existing session cookies |
| **Extension permissions** | Only chatgpt.com and localhost:3003 |
| **Data transmission** | localhost only, never external |

## Memory Considerations (Jetson Orin Nano)

| Component | Memory Usage |
|-----------|-------------|
| Chrome browser | 300-600 MB |
| Extension | < 10 MB |
| API calls | Minimal (JSON only) |

Chrome flags for memory optimization:
```
--disable-gpu
--disable-software-rasterizer
--renderer-process-limit=2
```

## VNC Remote Access (noVNC)

For headless deployments (like Jetson Orin Nano without a monitor), VNC mode allows accessing the browser remotely via a web browser.

### VNC Architecture

```
┌───────────────────────────────────────────────────────────────┐
│  User's Browser (any device on local network)                  │
│  http://<nano-ip>:6080/vnc.html                                │
└────────────────────────────┬──────────────────────────────────┘
                             │ WebSocket (port 6080)
                             ▼
┌───────────────────────────────────────────────────────────────┐
│  JETSON ORIN NANO                                              │
│                                                                │
│  ┌────────────────────────────────────────────────────────┐   │
│  │  websockify (port 6080)                                │   │
│  │  Translates WebSocket → VNC protocol                   │   │
│  │  Serves noVNC web files                                │   │
│  └────────────────────────────┬───────────────────────────┘   │
│                               │ VNC (port 5901)               │
│                               ▼                               │
│  ┌────────────────────────────────────────────────────────┐   │
│  │  x11vnc (port 5901)                                    │   │
│  │  VNC server capturing Xvfb display                     │   │
│  │  Password: mindsage                                    │   │
│  └────────────────────────────┬───────────────────────────┘   │
│                               │ X11 (display :99)             │
│                               ▼                               │
│  ┌────────────────────────────────────────────────────────┐   │
│  │  Xvfb (virtual framebuffer)                            │   │
│  │  1280x720x24 virtual display                           │   │
│  └────────────────────────────┬───────────────────────────┘   │
│                               │ DISPLAY=:99                   │
│                               ▼                               │
│  ┌────────────────────────────────────────────────────────┐   │
│  │  Chromium Browser                                      │   │
│  │  Running with MindSage capture extension               │   │
│  └────────────────────────────────────────────────────────┘   │
│                                                                │
└───────────────────────────────────────────────────────────────┘
```

### VNC Dependencies

Install VNC dependencies on the Jetson:
```bash
sudo apt install xvfb x11vnc novnc websockify
```

### VNC API Endpoints

| Endpoint | Purpose |
|----------|---------|
| `POST /api/browser-connector/launch` | Launch with `vnc: true` option |
| `GET /api/browser-connector/vnc/status` | VNC connection URL and status |
| `GET /api/browser-connector/vnc/check` | Check if dependencies installed |

### Launch with VNC

```bash
curl -X POST http://localhost:3003/api/browser-connector/launch \
  -H "Content-Type: application/json" \
  -d '{"vnc": true, "startUrl": "https://chatgpt.com"}'
```

Response includes VNC URL:
```json
{
  "success": true,
  "status": {
    "running": true,
    "vnc": {
      "enabled": true,
      "wsPort": 6080,
      "vncPort": 5901,
      "display": ":99"
    }
  }
}
```

**VNC Password**: `mindsage` (required when connecting via noVNC)

### VNC Memory Usage

| Component | Memory Usage |
|-----------|-------------|
| Xvfb | ~20 MB |
| x11vnc | ~10 MB |
| websockify | ~15 MB |
| **Total VNC overhead** | ~45 MB |

### Stopping VNC

VNC processes are automatically cleaned up when the browser is closed:
```bash
curl -X POST http://localhost:3003/api/browser-connector/close
```

### VNC in Docker

When running MindSage in Docker, VNC is fully supported. The Dockerfile includes all necessary dependencies (Chromium, Xvfb, x11vnc, websockify, noVNC).

**Port Mapping**: The noVNC port (6080) is exposed in docker-compose files:
```yaml
ports:
  - "6080:6080"  # noVNC web interface
```

**Docker Access Example**:
```bash
# Start the container
docker compose up -d

# Launch browser in VNC mode via API
curl -X POST http://localhost:3003/api/browser-connector/launch \
  -H "Content-Type: application/json" \
  -d '{"vnc": true, "startUrl": "https://chatgpt.com"}'

# Access browser from any device
# Open: http://<host-ip>:6080/vnc.html
# Password: mindsage
```

**Jetson with Host Networking**: When using `docker-compose.jetson.yml` (host networking mode), all ports are directly accessible without explicit port mapping.

## Headless Sync (Background Operation)

After the initial VNC login, subsequent syncs can run headlessly without requiring VNC access. This enables automatic background sync scheduling.

### Authentication Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  FIRST-TIME LOGIN (VNC Required)                                            │
│                                                                             │
│  1. User launches browser with VNC mode                                     │
│  2. User logs into ChatGPT via noVNC                                        │
│  3. Extension detects access token via /api/auth/session                    │
│  4. Extension reports auth to backend: POST /api/browser-connector/report-auth
│  5. Backend saves authenticatedAt timestamp to config.json                  │
│  6. Extension syncs all conversations                                       │
│  7. User closes browser when done                                           │
│                                                                             │
│  Result: authenticatedAt is now set, headless sync is enabled               │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│  SUBSEQUENT SYNCS (Headless - No VNC)                                       │
│                                                                             │
│  1. User clicks "Sync Now" or auto-sync timer fires                         │
│  2. Backend checks authenticatedAt → exists                                 │
│  3. Backend launches Chrome with virtual display (Xvfb only)                │
│  4. URL includes ?mindsage-sync=true to force sync                          │
│  5. Extension loads, detects force sync parameter                           │
│  6. Extension syncs conversations (session cookies still valid)             │
│  7. Captures sent to backend via POST /capture                              │
│  8. Sync completes via inactivity detection (30s of no captures)            │
│  9. Backend closes browser and returns results                              │
│                                                                             │
│  Result: Conversations synced without any user interaction                  │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Virtual Display Mode

For headless sync, we use Xvfb (virtual framebuffer) WITHOUT the VNC components:

| Mode | Components | Remote Access | Use Case |
|------|------------|---------------|----------|
| VNC | Xvfb + x11vnc + websockify | Yes | First-time login, debugging |
| Virtual Display | Xvfb only | No | Background sync |

**Why Xvfb instead of `--headless`?**
Chrome's headless mode (`--headless=new`) doesn't properly load extensions. Using a virtual display ensures extensions work correctly.

### Inactivity-Based Completion Detection

The extension sends a `syncComplete` message when sync finishes, but this can sometimes fail to reach the backend. As a fallback, the backend uses inactivity detection:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Sync Completion Detection                                                   │
│                                                                             │
│  Primary: Extension POST /sync-complete with results                        │
│           → Backend resolves sync promise immediately                       │
│                                                                             │
│  Fallback: Inactivity detection                                             │
│           → Backend tracks each capture received                            │
│           → If no captures for 30 seconds, consider sync complete           │
│           → Return results based on capture count                           │
│                                                                             │
│  Timeout: 5 minutes overall                                                 │
│           → If no captures at all, return error                             │
│           → If some captures received, return partial success               │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Auto-Sync Scheduling

```typescript
// Configuration (in config.json)
{
  "autoSyncEnabled": true,
  "autoSyncIntervalHours": 5,  // 1-24 hours
  "lastSyncAt": "2025-01-29T22:00:00.000Z",
  "lastSyncResult": {
    "success": true,
    "synced": 16,
    "failed": 0
  }
}
```

**API Endpoints:**
| Endpoint | Purpose |
|----------|---------|
| `GET /auto-sync` | Get auto-sync status and schedule |
| `POST /auto-sync/start` | Enable auto-sync |
| `POST /auto-sync/stop` | Disable auto-sync |
| `PUT /auto-sync/interval` | Update interval (1-24 hours) |

**Behavior:**
- Starts automatically on server boot if enabled and authenticated
- Skips sync if browser is already running (user might be using VNC)
- Runs initial sync on startup if last sync was over interval ago
- Stores results in config for UI display

### Headless Sync API

```bash
# Check authentication status
curl http://localhost:3003/api/browser-connector/auth-status
# {"authenticated":true,"authenticatedAt":"2025-01-29T21:45:00.000Z"}

# Trigger manual sync (requires prior auth)
curl -X POST http://localhost:3003/api/browser-connector/sync
# {"success":true,"synced":16,"failed":0,"total":16}

# Clear authentication (force re-login via VNC)
curl -X DELETE http://localhost:3003/api/browser-connector/auth
```

## Future Enhancements

| Feature | Status |
|---------|--------|
| ChatGPT support | ✅ Implemented |
| VNC remote access | ✅ Implemented |
| Headless sync | ✅ Implemented |
| Auto-sync scheduling | ✅ Implemented |
| Claude.ai support | Planned |
| Gemini support | Planned |
| Selective sync | Planned |
