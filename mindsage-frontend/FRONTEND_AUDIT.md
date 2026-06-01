# MindSage Frontend Feature Audit

**Date:** 2026-03-09
**Scope:** Complete granular breakdown of all frontend features, components, hooks, API endpoints, and pages.

---

## Table of Contents

1. [Pages & Routing](#1-pages--routing)
2. [Chat System](#2-chat-system)
3. [Voice Mode (WebRTC)](#3-voice-mode-webrtc)
4. [Privacy & Consent Layer](#4-privacy--consent-layer)
5. [Data Connectors](#5-data-connectors)
6. [File Transfer & Upload](#6-file-transfer--upload)
7. [Knowledge Graph Explorer](#7-knowledge-graph-explorer)
8. [Browser Automation (VNC)](#8-browser-automation-vnc)
9. [MCP Integration](#9-mcp-integration)
10. [Theme & Layout](#10-theme--layout)
11. [Debug & Monitoring](#11-debug--monitoring)
12. [API Surface (Full Listing)](#12-api-surface-full-listing)

---

## 1. Pages & Routing

**Router:** React Router with two routing groups (headerless and with-header).

| Route | Component | Header | Purpose |
|-------|-----------|--------|---------|
| `/` | `Landing` | No | Public marketing/onboarding page |
| `/vnc` | `VncViewer` | No | Standalone remote browser viewer |
| `/dashboard` | `Index` | Yes | Main application dashboard |
| `/explore` | `Explore` | Yes | Knowledge graph full-screen view |
| `*` | `NotFound` | Yes | 404 catch-all |

### 1.1 Landing Page (`/`)
- **Navigation bar** with logo, dashboard link, and CTA button
- **Hero section** with headline "Index everything. Expose nothing." and animated terminal preview
- **Stats ribbon**: 4 metrics (100% Local Processing, <50ms Search Latency, 10k+ Documents Indexed, 0 Data Sent to Cloud)
- **Features grid**: 6 cards (Semantic Search, Knowledge Graph, Multi-Source Indexing, Privacy First, Lightning Fast, Rich Previews)
- **Privacy superpowers section**: 3 deep-dive cards
  - Data Liberation Service (Google, Meta, Amazon integration)
  - AI Without PII Exposure (local PII stripping, BYOK)
  - Granular Data Control (per-field visibility, recipient permissions, time-limited tokens)
- **How it works**: 3-step flow (Connect Sources → Index Everything → Search & Explore)
- **CTA section** and footer
- Uses Framer Motion throughout for scroll-triggered animations

### 1.2 Dashboard (`/dashboard`)
- 3-column responsive grid layout with staggered Framer Motion animations
- **Left column**: FileTransferPanel, ConnectorGrid, MCPSetupPanel
- **Right column** (spans 2): ChatPanel (600px height)

### 1.3 Explore (`/explore`)
- Full-viewport KnowledgeGraph component (`calc(100vh - 3.5rem)`)
- Fade-in animation on mount

### 1.4 VNC Viewer (`/vnc`)
- Connection state machine: disconnected → connecting → connected (also `password` and `failed` states)
- Login card with server address, password input (default hint: "mindsage"), show/hide toggle
- VNC canvas via noVNC library (dynamic import)
- Header controls: connection badge, fullscreen toggle, disconnect button
- Auto-refetches VNC status every 5 seconds when disconnected

### 1.5 NotFound
- Centered 404 display with link back to home
- Console logging of attempted route

---

## 2. Chat System

### 2.1 ChatPanel Component
**File:** `src/components/chat/ChatPanel.tsx`

- **Message history** with animated user/assistant message bubbles (role-based icons)
- **Markdown rendering** in assistant responses
- **Text input** with send button; placeholder text changes based on state (unconfigured / configured / voice active)
- **Voice mode toggle**: Microphone button to enable/disable WebRTC voice
- **Auto-scrolling** to latest message
- **Configuration gate**: Shows "Get Started" prompt when LLM is not configured
- **Error banner** display
- **Automatic consent session creation** when LLM becomes configured

### 2.2 LLM Configuration Dialog
**File:** `src/components/chat/LLMConfigDialog.tsx`

- **3-tab provider interface**: OpenAI, Anthropic, Groq
- **API key input** with show/hide toggle per provider
- **Model selection dropdown** with provider-specific model lists
- **"Test Key" button** to validate API keys server-side before saving
- **Server-side key storage** with checkmark indicators for configured providers
- **Preferred provider selector** (auto vs manual)
- **Legacy localStorage migration** for backward compatibility
- **Active provider status display**

### 2.3 Sources List
**File:** `src/components/chat/SourcesList.tsx`

- **Collapsible panel** with file count badge
- **Per-source relevance score** (0–100%)
- **PII protection highlighting**: Dotted underlines on anonymized spans
- **Tooltips** showing PII type (e.g., "personal name", "financial info")
- **LPRAG indicator**: Shows when a similar value replaced the original
- **Click-to-expand** for full context view
- **Non-overlapping span matching** to prevent nested highlights
- Max 300px scrollable height for expanded sources

### 2.4 Chat Hook (`use-backend-chat`)
**File:** `src/hooks/use-backend-chat.ts`

**State:** messages, isLoading, error, isAvailable, isConfigured, provider, model

- **SSE streaming** of chat responses with real-time token display
- **RAG context injection** from vector store
- **Server-side de-anonymization** support
- **Voice-initiated message tracking** (distinguishes typed vs spoken messages)
- **Conversation history management** (send, add voice messages, clear)
- **PII consent session** passed with every request
- **Health polling** every 30 seconds via `getChatStatus()`

---

## 3. Voice Mode (WebRTC)

### 3.1 Voice RTC Hook (`use-voice-rtc`)
**File:** `src/hooks/use-voice-rtc.ts`

**State machine:** `disconnected` → `connecting` → `connected` → `error`

- **Browser capability check**: Verifies `getUserMedia` and `RTCPeerConnection` support
- **Mic access**: Requests audio with constraints (16kHz, mono, echo/noise cancellation)
- **SDP exchange**: Sends offer to backend, receives answer
- **ICE candidate gathering** with 5-second timeout
- **Remote audio playback** via hidden `<audio>` element
- **SSE event stream** for text outputs:
  - `transcript` — user speech transcription
  - `response` — assistant response (de-anonymized for display)
  - `sources` — RAG sources used in response
  - `error` — error messages
- **Stale session cleanup**: Every `connect()` calls `disconnectVoice()` first
- **Page unload handling**: Uses `navigator.sendBeacon` for reliable disconnect on refresh/close
- **Automatic cleanup** on component unmount

---

## 4. Privacy & Consent Layer

### 4.1 Consent Dialog
**File:** `src/components/consent/ConsentDialog.tsx`

- **Shield icon button** in chat panel, color-coded by preset level:
  - Red = strict, Blue = balanced, Green = open
- **Quick preset selector** with 3 main + 4 specialized presets
- **Fine-grained controls** in tabbed interface (PII Types tab, Topics tab)
- **Auto-creates session** with "balanced" preset when LLM is configured
- Changes apply only to the current conversation
- Fallback message when consent backend is unavailable

### 4.2 Preset Selector
**File:** `src/components/consent/ConsentPresetSelector.tsx`

- **3×3 button grid**: Strict (Lock icon), Balanced (Scale icon), Open (Unlock icon)
- Checkmark on selected preset
- Color-coded backgrounds per security level
- Loading spinner support

### 4.3 PII Type Filter
**File:** `src/components/consent/PIITypeFilter.tsx`

- **13 PII type toggles**: PERSON, EMAIL, PHONE, LOCATION, DATE_TIME, ORGANIZATION, MEDICAL, FINANCIAL, ADDRESS, IP_ADDRESS, SSN, CREDIT_CARD, PASSPORT
- **Risk level badges**: low / medium / high / critical (color-coded)
- **Critical PII always protected** (SSN, Credit Card locked/disabled)
- **Examples** showing original → anonymized transformation
- Toggle labels: "Show original" vs "Anonymize"
- Icons for each PII type

### 4.4 Category/Topic Filter
**File:** `src/components/consent/CategoryFilter.tsx`

- **14 data category toggles**: Health, Finance, Work, Personal, Legal, Family, Education, Travel, Shopping, Social, Technology, Entertainment, Political, Religious
- Risk badges (low/medium/high) per category
- Category icons and descriptions
- Switch controls to enable/disable
- Documents with disabled topics are excluded from LLM context

### 4.5 Consent Badge
**File:** `src/components/consent/ConsentBadge.tsx`

- Small inline 2×2px dot indicator
- Color-coded by preset
- Tooltip showing preset name

---

## 5. Data Connectors

### 5.1 Connector Grid
**File:** `src/components/home/ConnectorGrid.tsx`

- **Card layout** for each connected data source
- **Item count badges** per connector
- **Dropdown actions**: Sync Now, Disconnect
- **Settings button** for AI connectors (ChatGPT, Claude, Gemini)
- **"Add Connector" button** with popover selector
- **ConnectorConfigModal** for non-AI connectors (token-based setup, e.g., Notion)
- **File upload modal** for Facebook/ChatGPT ZIP imports
- Error handling and loading states
- AI connector detection from backend registry

### 5.2 AI Connector Dialog
**File:** `src/components/home/AIConnectorDialog.tsx`

Shared dialog for ChatGPT, Claude, and Gemini connectors:

- **Dual authentication paths**:
  - Companion Browser Extension (primary) — shows server URL for extension configuration
  - VNC Browser Automation (fallback) — launches headless browser with VNC access
- **Login status badge** (logged in / not logged in)
- **VNC browser launch** with dependency check
- **Navigate to site** button when VNC browser is running
- **Manual sync** button
- **Auto-sync toggle** with interval slider (1–24 hours)
- **Conversation statistics**: count, messages, last sync timestamp
- **Recent conversations list** with:
  - Indexed status badge
  - Re-index individual conversation
  - Delete individual conversation
- **Re-index all** conversations button
- Site-specific configuration per platform

### 5.3 Browser Connector Panel
**File:** `src/components/home/BrowserConnectorPanel.tsx`

- Card-based UI showing browser running status
- **Platform selector** dropdown (ChatGPT/Claude/Gemini)
- Play/Stop buttons for browser process
- **Settings dialog**: auto-start toggle, headed mode toggle
- **VNC mode toggle** for remote desktop access
- Quick-navigation buttons to AI sites (when browser running)
- VNC URL display with copy/open-in-new-tab
- Capture statistics (conversations, messages, last capture)
- Recent conversations with indexed status badges
- Re-index all and delete individual actions

### 5.4 Connector Logos
**File:** `src/components/home/ConnectorLogos.tsx`

- SVG logos: ChatGPT, Claude, Gemini, Notion, Facebook, DefaultConnector
- `connectorLogos` map for lookup by type
- `getConnectorLogo(type)` function with fallback

---

## 6. File Transfer & Upload

### 6.1 File Transfer Panel
**File:** `src/components/home/FileTransferPanel.tsx`

**3 transfer methods** (tabbed interface):

#### Tab 1: LocalSend
- LocalSend daemon status indicator (running/stopped)
- Start/Stop controls
- App download links (iOS, Android, Desktop)

#### Tab 2: HTTP Upload
- **Drag-and-drop** file upload zone
- **Progress bar** during upload
- **Automatic media detection**: Audio/image files route to `/api/vector-store/media/upload`, text files to `/api/files/upload`
- **Capability badges**: Audio processing, Image processing availability

#### Tab 3: Mobile QR
- QR code for direct mobile upload to server

**Post-upload behavior:**
- Indexing status polling
- Background toast notifications on indexing completion

### 6.2 Smart Upload Routing (api.ts)
- `uploadFiles()` inspects file extensions
- Audio extensions (`.mp3`, `.wav`, `.m4a`, `.ogg`, `.flac`, `.aac`, `.wma`, `.opus`) → media endpoint
- Image extensions (`.jpg`, `.jpeg`, `.png`, `.gif`, `.bmp`, `.webp`, `.tiff`, `.svg`, `.heic`, `.heif`) → media endpoint
- All other files → standard upload endpoint
- `uploadMedia()` uses XHR with progress callback
- `getMediaStatus()` checks audio/image processor availability

---

## 7. Knowledge Graph Explorer

### 7.1 Knowledge Graph
**File:** `src/components/graph/KnowledgeGraph.tsx`

**Core visualization** (React Flow-based DAG):

- **6 node types**: Documents, Topics, Persons, Organizations, Locations, Technologies
- **Semantic search** with full document highlighting
- **Browse mode**: Search results as clean cards
- **Focus mode**: Expanded document with connection graph
- **Manual edge creation**: Draw node-to-node connections
- **Connection density control**: Sparse / Normal / Dense slider
- **Snap-to-grid** toggle
- **Lock view** toggle (prevents dragging)
- **Multi-select** with toolbar

**Saved Views:**
- Store, load, and delete canvas layouts
- Persistent named configurations

**Detail Panel** (right side):
- Full document content (text/code/markdown)
- Audio documents: Transcript with original/redacted tabs, PII region timestamps
- Image documents: Original/redacted image tabs, PII detection status
- Non-document nodes: Related documents, entities, organizations

**Canvas overlays:**
- Empty state (search prompt)
- Searching state (spinner)
- No results state (with query display)

### 7.2 File Explorer Sidebar
**File:** `src/components/graph/FileExplorer.tsx`

- **Folder management**: Create, rename, delete folders
- **Drag/drop to folder** via context menu
- **"Unfiled" section** for orphaned documents
- **Filter/search** by filename or topic
- **File type icons**: Code, document, data, text, audio, image
- **Folder expand/collapse** with item counts
- **Context menu actions** per item
- **Collapsible panel** with toggle button
- Scroll-to-selected on document update

### 7.3 Document Viewer
**File:** `src/components/explore/DocumentViewer.tsx`

- **Resizable split pane** (35% list / 65% detail)
- **Left panel**: Document list with search/filtering, pagination (10/page)
- **Right panel**: Full document viewer
- **Document metadata**: Word count, creation date, source
- **Topic filters** with AI extraction badge
- **Image documents**: Original/redacted tabs, PII scanning badges (Scanning/Detected/No PII)
- **Audio documents**: Full playback with transcript
- **Delete document** with confirmation dialog
- **Semantic search badge** indicator

### 7.4 Audio Document Viewer
**File:** `src/components/explore/AudioDocumentViewer.tsx`

- HTML5 audio player with play/pause
- Timeline slider with seek
- Time display (MM:SS)
- Mute toggle
- **Original/Redacted transcript tabs**
- **PII region badges** with click-to-seek
- PII type color coding
- Audio metadata (format, duration, sample rate, channels, word count)
- PII types found list

### 7.5 Graph Node Components
- **DocumentCardNode.tsx**: Card-style node showing filename, topic badges, word count
- **EntityPillNode.tsx**: Pill-shaped node for persons and organizations
- **TopicBadgeNode.tsx**: Badge-style node for topics

### 7.6 Markdown Viewer
**File:** `src/components/graph/MarkdownViewer.tsx`

- Code syntax highlighting
- Markdown rendering
- Responsive layout

---

## 8. Browser Automation (VNC)

### 8.1 VNC Viewer Page
**File:** `src/pages/VncViewer.tsx`

- Full-page remote browser view via noVNC
- Connection state machine with visual indicators
- Password authentication (default: "mindsage")
- Fullscreen toggle
- Auto-reconnect polling every 5 seconds
- Server info queries for IP/port resolution

### 8.2 Browser Connector APIs
- `launchBrowser(options)` — Start browser with optional VNC, site, and headed/headless mode
- `closeBrowser()` — Kill browser process
- `navigateBrowser(url)` — Navigate browser to URL
- `getBrowserConnectorConfig()` / `updateBrowserConnectorConfig()` — Auto-start, VNC settings
- `getVncStatus()` — VNC enabled, ports, display info
- `checkVncAvailable()` — Dependency check

### 8.3 Auth Management
- `getAuthStatus(site)` — Per-site authentication status
- `clearAuth(site)` — Clear cookies for a site
- `getSites()` — All available sites with auth status
- `navigateToSite(site, forSync)` — Navigate browser for auth or sync

### 8.4 Sync System
- `triggerSync(site)` — Manual headless sync
- `getAutoSyncStatus()` — Current auto-sync config
- `startAutoSync(intervalHours)` / `stopAutoSync()` — Enable/disable auto-sync
- `setAutoSyncInterval(hours)` — Update interval (1–24 hours)

---

## 9. MCP Integration

### 9.1 MCP Setup Panel
**File:** `src/components/home/MCPSetupPanel.tsx`

- **MCP status badge**: Ready / Offline
- **Document count** display
- **Dynamic MCP URL** based on server IP
- **Claude Desktop config JSON** (copyable code block)
- **Claude CLI setup command** (copyable)
- **Documentation link**
- **Collapsible sections** for setup instructions
- **Copy-to-clipboard** buttons with visual feedback (checkmark icon)

---

## 10. Theme & Layout

### 10.1 Theme Provider
**File:** `src/components/ThemeProvider.tsx`

- **4 themes**: Light, Dark, Cyber, System
- Persists selection to localStorage
- Applies CSS class to document root
- System preference detection via media query listener
- `useTheme()` hook for all components

### 10.2 Header
**File:** `src/components/layout/Header.tsx`

- MindSage logo (brain icon)
- Navigation links: Dashboard, Explore
- **Theme selector dropdown** (Light/Dark/Cyber with icons and checkmarks)
- Settings button placeholder
- **ExtractionStatus** indicator for indexing progress
- Sticky positioning with backdrop blur

### 10.3 Page Container
**File:** `src/components/layout/PageContainer.tsx`

- Framer Motion fade-in animation wrapper
- Responsive padding (`px-4 md:px-6`, `py-6 md:py-8`)
- Centered container with max-width

---

## 11. Debug & Monitoring

### 11.1 Debug Panel
**File:** `src/components/DebugPanel.tsx`

- **Floating panel** (bottom-right corner)
- Collapsible/minimizable
- **System memory**: Usage bar + percentage
- **Swap usage** display
- **GPU info**: CUDA availability, device name, memory allocation/reserved/peak
- **OOM error banner**
- **Model loading status**: Loaded / Unloaded / Error
- **GPU model indicator**
- **Vector store stats**: Document count, PII protection status
- **Extraction activity**: Current stage, memory-constrained waiting state
- **"Clear all data" button** with confirmation dialog

### 11.2 Extraction Status
**File:** `src/components/ExtractionStatus.tsx`

- Header badge showing pending extraction count
- **Memory-constrained warning** state (yellow)
- **Processing state** (blue with spinner)
- Tooltip with detailed status
- Required GPU memory display
- Auto-hides when no pending work

---

## 12. API Surface (Full Listing)

### Health & Status
| Function | Method | Endpoint | Description |
|----------|--------|----------|-------------|
| `checkHealth()` | GET | `/api/stats` | 3s timeout health check |

### Connectors
| Function | Method | Endpoint | Description |
|----------|--------|----------|-------------|
| `getConnectors()` | GET | `/api/connectors` | List all connectors |
| `addConnector(data)` | POST | `/api/connectors` | Create connector |
| `updateConnector(id, data)` | PUT | `/api/connectors/{id}` | Update connector |
| `connectConnector(type, name, config)` | POST/PUT | `/api/connectors/*` | Create or update with type mapping |
| `deleteConnector(id)` | DELETE | `/api/connectors/{id}` | Remove connector |
| `syncConnector(id)` | POST | `/api/connectors/{id}/sync` | Trigger sync |
| `getSyncStatus(id)` | GET | `/api/connectors/{id}/status` | Get sync status |
| `stopSync(id)` | POST | `/api/connectors/{id}/stop` | Stop running sync |
| `uploadConnectorFile(connectorId, file)` | POST | `/api/connectors/{connectorId}/upload` | Upload file to connector |

### Stats & Server
| Function | Method | Endpoint | Description |
|----------|--------|----------|-------------|
| `getStats()` | GET | `/api/stats` | Storage/document stats |
| `getServerInfo()` | GET | `/api/server-info` | Server IP, port, URL |

### File Transfer
| Function | Method | Endpoint | Description |
|----------|--------|----------|-------------|
| `getReceivedFiles()` | GET | `/api/files` | List received files |
| `deleteReceivedFile(filename)` | DELETE | `/api/files/{filename}` | Delete received file |
| `importReceivedFile(filename)` | POST | `/api/files/{filename}/import` | Import to vector store |

### Indexing
| Function | Method | Endpoint | Description |
|----------|--------|----------|-------------|
| `getIndexingStatus()` | GET | `/api/indexing/status` | Background indexing status |
| `getIndexingJobs()` | GET | `/api/indexing/jobs` | All indexing jobs |
| `getIndexingJob(jobId)` | GET | `/api/indexing/jobs/{jobId}` | Specific job details |

### LocalSend
| Function | Method | Endpoint | Description |
|----------|--------|----------|-------------|
| `getLocalSendStatus()` | GET | `/api/localsend/status` | Daemon status |
| `startLocalSend()` | POST | `/api/localsend/start` | Start daemon |
| `stopLocalSend()` | POST | `/api/localsend/stop` | Stop daemon |
| `setupLocalSend()` | POST | `/api/localsend/setup` | Initial setup |
| `configureLocalSend(deviceName)` | POST | `/api/localsend/configure` | Set device name |

### Vector Store
| Function | Method | Endpoint | Description |
|----------|--------|----------|-------------|
| `getVectorStoreStatus()` | GET | `/api/vector-store/status` | Check availability |
| `searchVectorStore(query, topK, minScore)` | POST | `/api/vector-store/search` | Basic vector search |
| `enhancedSearch(query, options)` | POST | `/api/vector-store/search/enhanced` | Search with passage extraction |
| `addVectorDocument(text, metadata)` | POST | `/api/vector-store/documents` | Add document |
| `listVectorDocuments(page, pageSize)` | GET | `/api/vector-store/documents` | Paginated list |
| `getVectorDocument(docId)` | GET | `/api/vector-store/documents/{docId}` | Get document |
| `deleteVectorDocument(docId)` | DELETE | `/api/vector-store/documents/{docId}` | Delete document |
| `indexConnectorToVectorStore(connectorId)` | POST | `/api/vector-store/index-connector/{connectorId}` | Index connector data |
| `indexUploadsToVectorStore()` | POST | `/api/vector-store/index-uploads` | Index received files |
| `indexFileToVectorStore(filename)` | POST | `/api/vector-store/index-file/{filename}` | Index specific file |

### Topics
| Function | Method | Endpoint | Description |
|----------|--------|----------|-------------|
| `getAllTopics()` | GET | `/api/vector-store/topics` | List all topics |
| `getDocumentsByTopic(topic, page, pageSize)` | GET | `/api/vector-store/topics/{topic}/documents` | Documents by topic |
| `getDocumentTopics(docId)` | GET | `/api/documents/{docId}/topics` | Document's topics |
| `updateDocumentTopics(docId, topics, primaryTopic)` | PUT | `/api/documents/{docId}/topics` | Update topics |
| `generateTopics(docId, numTopics, predefinedTopics)` | POST | `/api/documents/{docId}/topics/generate` | Auto-generate topics |
| `searchWithTopic(query, topic, topK, minScore)` | POST | `/api/vector-store/search/with-topic` | Topic-filtered search |

### Knowledge Graph
| Function | Method | Endpoint | Description |
|----------|--------|----------|-------------|
| `getKnowledgeGraph(options)` | POST | `/api/vector-store/graph` | Get graph nodes/edges |
| `getGraphNodeDetails(nodeId)` | GET | `/api/vector-store/graph/node/{nodeId}` | Node details |
| `createManualConnection(source, target)` | POST | `/api/vector-store/graph/connections` | Create manual edge |
| `deleteManualConnection(connectionId)` | DELETE | `/api/vector-store/graph/connections/{connectionId}` | Delete edge |

### Saved Views
| Function | Method | Endpoint | Description |
|----------|--------|----------|-------------|
| `getSavedViews()` | GET | `/api/vector-store/graph/views` | List saved views |
| `getSavedView(viewId)` | GET | `/api/vector-store/graph/views/{viewId}` | Get view |
| `saveView(view)` | POST | `/api/vector-store/graph/views` | Save view |
| `deleteSavedView(viewId)` | DELETE | `/api/vector-store/graph/views/{viewId}` | Delete view |

### Data Management
| Function | Method | Endpoint | Description |
|----------|--------|----------|-------------|
| `getDebugInfo()` | GET | `/api/vector-store/debug` | System/GPU/extraction info |
| `clearAllData()` | POST | `/api/data/clear-all` | Wipe all data |

### File Upload
| Function | Method | Endpoint | Description |
|----------|--------|----------|-------------|
| `uploadFiles(files, onProgress)` | POST | `/api/files/upload` or `/api/vector-store/media/upload` | Smart-routed upload |
| `uploadMedia(file, onProgress)` | POST | `/api/vector-store/media/upload` | Direct media upload |
| `getMediaStatus()` | GET | `/api/vector-store/media/status` | Media processor status |

### Chat
| Function | Method | Endpoint | Description |
|----------|--------|----------|-------------|
| `getChatStatus()` | GET | `/api/chat/status` | LLM availability/config |
| `sendChatMessage(request)` | POST | `/api/chat` | Non-streaming chat |
| `streamChatMessage(request)` | POST | `/api/chat/stream` | SSE streaming chat |

### LLM Configuration
| Function | Method | Endpoint | Description |
|----------|--------|----------|-------------|
| `getLLMConfig()` | GET | `/api/chat/config` | Get provider config |
| `updateLLMConfig(update)` | PUT | `/api/chat/config` | Update keys/models |
| `testApiKey(provider, apiKey)` | POST | `/api/chat/config/test` | Validate API key |

### PII Protection
| Function | Method | Endpoint | Description |
|----------|--------|----------|-------------|
| `getPIIStatus()` | GET | `/api/pii/status` | PII detection status |
| `deanonymize(text, sessionId)` | POST | `/api/pii/deanonymize` | Replace tokens with originals |

### Voice (WebRTC)
| Function | Method | Endpoint | Description |
|----------|--------|----------|-------------|
| `getVoiceStatus()` | GET | `/api/voice/status` | WebRTC/STT/TTS status |
| `getVoiceConfig()` | GET | `/api/voice/config` | Current voice settings |
| `updateVoiceConfig(config)` | PUT | `/api/voice/config` | Update voice settings |
| `sendWebRTCOffer(offer)` | POST | `/api/voice/webrtc/offer` | Exchange SDP |
| `connectVoiceOutputs(webrtcId)` | GET | `/api/voice/outputs` | SSE text events |
| `disconnectVoice()` | POST | `/api/voice/disconnect` | Close session |

### Extraction Queue
| Function | Method | Endpoint | Description |
|----------|--------|----------|-------------|
| `getExtractionQueueStatus()` | GET | `/api/vector-store/extraction/status` | Extraction task queue |

### Browser Connector
| Function | Method | Endpoint | Description |
|----------|--------|----------|-------------|
| `getBrowserConnectorStatus()` | GET | `/api/browser-connector/status` | Browser/VNC status |
| `launchBrowser(options)` | POST | `/api/browser-connector/launch` | Start browser |
| `closeBrowser()` | POST | `/api/browser-connector/close` | Kill browser |
| `navigateBrowser(url)` | POST | `/api/browser-connector/navigate` | Navigate browser |
| `getBrowserConnectorConfig()` | GET | `/api/browser-connector/config` | Get config |
| `updateBrowserConnectorConfig(config)` | PUT | `/api/browser-connector/config` | Update config |
| `getBrowserCaptureStats()` | GET | `/api/browser-connector/stats` | Capture stats |
| `getCapturedConversations(options)` | GET | `/api/browser-connector/conversations` | List conversations |
| `getCapturedConversation(id)` | GET | `/api/browser-connector/conversations/{id}` | Get conversation |
| `deleteCapturedConversation(id)` | DELETE | `/api/browser-connector/conversations/{id}` | Delete conversation |
| `reindexCapturedConversations()` | POST | `/api/browser-connector/reindex` | Re-index all |

### VNC
| Function | Method | Endpoint | Description |
|----------|--------|----------|-------------|
| `getVncStatus()` | GET | `/api/browser-connector/vnc/status` | VNC status/ports |
| `checkVncAvailable()` | GET | `/api/browser-connector/vnc/check` | Check dependencies |

### Browser Auth
| Function | Method | Endpoint | Description |
|----------|--------|----------|-------------|
| `getAuthStatus(site)` | GET | `/api/browser-connector/auth-status` | Per-site auth status |
| `clearAuth(site)` | DELETE | `/api/browser-connector/auth` | Clear site cookies |
| `getSites()` | GET | `/api/browser-connector/sites` | All sites with auth |
| `navigateToSite(site, forSync)` | POST | `/api/browser-connector/navigate-to-site` | Navigate for auth |

### Browser Sync
| Function | Method | Endpoint | Description |
|----------|--------|----------|-------------|
| `triggerSync(site)` | POST | `/api/browser-connector/sync` | Manual sync |
| `getAutoSyncStatus()` | GET | `/api/browser-connector/auto-sync` | Auto-sync config |
| `startAutoSync(intervalHours)` | POST | `/api/browser-connector/auto-sync/start` | Enable auto-sync |
| `stopAutoSync()` | POST | `/api/browser-connector/auto-sync/stop` | Disable auto-sync |
| `setAutoSyncInterval(hours)` | PUT | `/api/browser-connector/auto-sync/interval` | Update interval |

---

## Summary Statistics

| Category | Count |
|----------|-------|
| Pages/Routes | 5 |
| Custom Components | ~30 |
| shadcn/ui Primitives | ~30 |
| Custom Hooks | 4 |
| API Functions | 80+ |
| API Endpoint Groups | 22 |
| Themes | 4 (Light, Dark, Cyber, System) |
| LLM Providers | 3 (OpenAI, Anthropic, Groq) |
| AI Connector Platforms | 3 (ChatGPT, Claude, Gemini) |
| PII Types Managed | 13 |
| Topic Categories | 14 |
| File Transfer Methods | 3 (LocalSend, HTTP Upload, Mobile QR) |
| Knowledge Graph Node Types | 6 |
