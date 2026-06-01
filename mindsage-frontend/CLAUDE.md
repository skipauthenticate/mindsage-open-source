# MindSage Frontend

React + TypeScript app for MindSage privacy-first data platform.

## Quick Start

```bash
npm install
npm run dev          # Starts on port 8080
npm run build        # Production build
npm run lint         # Check for errors
```

## Stack

- **React 18** + TypeScript
- **Vite** (dev server, build)
- **Tailwind CSS** + shadcn/ui
- **TanStack Query** for API calls
- **React Router** for navigation

## Project Structure

```
src/
├── components/       # UI components
│   ├── chat/         # Chat panel, sources list
│   ├── consent/      # PII consent management
│   ├── home/         # Browser connector panel
│   └── ui/           # shadcn primitives
├── hooks/            # Custom React hooks
├── lib/              # Utilities (api.ts, utils.ts)
└── pages/            # Route pages
```

## API Proxy

All `/api/*` requests proxy to backend at `localhost:3003`.

**Media Upload Routing**: The frontend automatically detects media files (audio/image by extension) and routes them to `/api/vector-store/media/upload` while text files go to `/api/files/upload`. This is handled transparently in `src/lib/api.ts`.

## Key Files

- `src/lib/api.ts` - API client functions (includes media upload routing, voice WebRTC, `uploadMedia()`, `getMediaStatus()`)
- `src/hooks/use-backend-chat.ts` - Chat hook with streaming
- `src/hooks/use-voice-rtc.ts` - Voice mode WebRTC hook (connect/disconnect, SSE text events)
- `src/components/chat/ChatPanel.tsx` - Main chat interface
- `src/components/chat/LLMConfigDialog.tsx` - LLM settings (API keys, model selection)
- `src/components/home/ChatGPTConnectorDialog.tsx` - ChatGPT sync dialog
- `src/components/home/ConnectorGrid.tsx` - Data connector cards
- `src/components/home/FileTransferPanel.tsx` - File upload panel with audio/image capability badges

## Browser Connector (ChatGPT Sync)

The ChatGPT connector is integrated into the Data Connectors section as a card that opens a dialog:

**Dialog Features:**
- Auth status display (logged in / not logged in)
- VNC login button (first-time setup)
- Manual sync button (after auth)
- Auto-sync toggle with interval slider (1-24 hours)
- Capture statistics (conversations, messages, last sync)
- Recent conversations list with re-index option

**API Hooks Used:**
```typescript
// Auth status
useQuery(['browserAuthStatus'], api.getAuthStatus)

// Auto-sync status
useQuery(['autoSyncStatus'], api.getAutoSyncStatus)

// Browser status (VNC info)
useQuery(['browserConnectorStatus'], api.getBrowserConnectorStatus)

// Captured conversations
useQuery(['capturedConversations'], api.getCapturedConversations)

// Mutations
useMutation(api.launchBrowser)       // VNC launch
useMutation(api.triggerSync)         // Manual sync
useMutation(api.startAutoSync)       // Enable auto-sync
useMutation(api.stopAutoSync)        // Disable auto-sync
```

## Voice Mode (WebRTC)

Real-time voice interaction via WebRTC. The `useVoiceRTC` hook manages the connection lifecycle:

- **Connect**: Requests mic access, creates RTCPeerConnection, exchanges SDP offer/answer with backend
- **Disconnect**: Closes peer connection, notifies server to release resources
- **Page unload**: Uses `navigator.sendBeacon` for reliable disconnect on refresh/close
- **Stale cleanup**: Each `connect()` calls `disconnectVoice()` first to clear stale server-side sessions
- **Text events**: SSE stream delivers transcript, response, and sources events to the chat UI

```typescript
const { state, connect, disconnect, toggleConnection } = useVoiceRTC({
  onTranscript: (text) => { /* user speech transcribed */ },
  onResponse: (text) => { /* assistant response (de-anonymized for display) */ },
  onSources: (sources) => { /* RAG sources used */ },
  onError: (msg) => { /* error */ },
});
```

## Patterns

- Use `@/` import alias for src directory
- Components use shadcn/ui primitives
- API calls use TanStack Query mutations/queries
