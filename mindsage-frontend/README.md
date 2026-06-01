# MindSage Frontend

Privacy-first personal data search interface built with React. This is a standalone frontend package that communicates with the MindSage backend API.

## Features

- Semantic search interface for personal data
- Knowledge graph visualization
- Document viewer with syntax highlighting
- **Image viewer** with Original/Redacted tabs and PII status badges
- **Auto-refresh** - UI updates automatically when async PII redaction completes
- File upload with drag-and-drop
- Real-time chat with RAG (Retrieval Augmented Generation)
- Dark mode by default

## Tech Stack

- **Framework**: React 18, TypeScript, Vite
- **Styling**: Tailwind CSS, shadcn/ui (Radix primitives)
- **State**: React Query for server state
- **Routing**: React Router v6
- **Visualization**: React Flow (knowledge graph), Recharts

## Quick Start

### Development (without Docker)

Requires Node.js 20.19+.

```bash
# Install dependencies
npm install

# Start development server (port 8080)
npm run dev
```

The dev server proxies `/api` requests to `http://localhost:3003` (backend).

### Production Build

```bash
npm run build
npm run preview
```

## Docker

### Standalone Frontend Container

Build and run the frontend container:

```bash
# Build the image
docker build -t mindsage-frontend .

# Run the container
docker run -d -p 8080:8080 --name mindsage-frontend mindsage-frontend
```

The container uses nginx to serve the built React app and proxy API requests.

### Full Stack with Docker Compose

For running frontend + backend + vector-store together, use the full-stack compose file in the `mindsage` (backend) repository:

```bash
# From the mindsage (backend) directory
cd ../mindsage
docker compose -f docker-compose.full.yml up -d --build
```

This starts all services with Jetson Orin Nano-like memory constraints:

| Service | Port | Memory Limit |
|---------|------|--------------|
| Frontend | 8080 | 256 MB |
| Backend | 3003 | 1 GB |
| Vector Store | 8085 | 6 GB |

### Docker Files

```
mindsage-frontend/
├── Dockerfile        # Multi-stage build (node + nginx)
├── nginx.conf        # Nginx config with API proxy
└── .dockerignore     # Build exclusions
```

## Configuration

### API URL

The frontend communicates with the backend via `/api` proxy.

**Development** (default - Vite proxies to localhost:3003):
```bash
# No configuration needed, uses vite.config.ts proxy
npm run dev
```

**Production** (Docker - nginx proxies to backend service):
```bash
# nginx.conf handles proxying to 'mindsage:3003'
docker compose -f docker-compose.full.yml up
```

**Custom API URL** (standalone deployment):
```bash
# Set environment variable before build
VITE_API_URL=http://your-backend:3003 npm run build
```

## Project Structure

```
src/
├── pages/              # Route components
│   ├── Index.tsx       # Main dashboard/search page
│   ├── Explore.tsx     # Knowledge graph exploration
│   └── NotFound.tsx    # 404 page
├── components/         # Feature components
│   ├── ui/             # shadcn/ui components
│   ├── knowledge-graph/  # React Flow graph components
│   └── document-viewer/  # Document display
├── lib/
│   ├── api.ts          # Type-safe API client
│   └── utils.ts        # Utility functions
└── hooks/              # Custom React hooks
```

## Testing

```bash
npm test              # Run once
npm run test:watch    # Watch mode
```

## License

MIT
