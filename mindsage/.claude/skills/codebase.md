# MindSage Codebase Overview

Privacy-first data aggregation platform for Jetson Orin Nano.

## Architecture

```
Frontend (8080)  →  Backend (3003)  →  Vector Store (8085)
   React/Vite        Express API        Python/FastAPI
                                        TinyLlama, Reranker
```

## Repositories

### mindsage-frontend (React)
- Chat interface with semantic search
- Browser connector panel
- PII consent management
- Knowledge graph visualization

Key paths:
- `src/components/chat/` - Chat UI
- `src/components/consent/` - PII controls
- `src/hooks/use-backend-chat.ts` - Chat streaming
- `src/lib/api.ts` - API client

### mindsage (Backend + Vector Store)
- Express API with data connectors
- LocalSend file transfer
- Browser connector (Chrome extension)
- Python ML service (embeddings, TinyLlama, reranker)

Key paths:
- `server/index.ts` - Express routes
- `server/chat-service.ts` - LLM integration
- `server/browser-connector/` - Chrome capture
- `vector-store/mcp_vector_store/` - ML service

## API Patterns

All endpoints: `/api/*`

- Connectors: `/api/connectors/*`
- Files: `/api/files/*`
- Browser: `/api/browser-connector/*`
- Vector Store: `/api/vector-store/*`
- Chat: `/api/chat/*`
- PII: `/api/pii/*`

## Data Flow

1. Files/exports → Backend receives
2. Backend → Vector Store indexes
3. User query → Chat service
4. Chat → Vector Store search
5. Results → PII anonymization
6. Response → Frontend de-anonymizes

## Hardware Constraints

Jetson Orin Nano: ~7.4GB shared CPU/GPU memory
- Only ONE large model on GPU at a time
- TinyLlama OR Reranker, not both
- Embedding model always loaded (~90MB)
