# Development Guide

Quick guide to running MindSage in development mode.

## Quick Start

### Option 1: Run Everything (Recommended)

Run backend and vector store together:

```bash
cd mindsage
npm run dev:all
```

This starts:
- **Backend** (Express): http://localhost:3003
- **Vector Store** (FastAPI): http://localhost:8085

### Option 2: Run Separately

**Terminal 1 - Backend:**
```bash
cd mindsage
npm run dev:server
```

**Terminal 2 - Vector Store:**
```bash
cd mindsage
npm run vector-store:start
```

## Accessing the Application

Once services are running:

- **Backend API**: http://localhost:3003
- **Vector Store API**: http://localhost:8085
- **Frontend UI**: http://localhost:8080 (requires running [mindsage-frontend](https://github.com/skipauthenticate/mindsage-frontend) separately)

### Access from Other Devices

Use Caddy reverse proxy for easy access without port numbers.

#### Install Caddy

```bash
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update
sudo apt install caddy
```

#### Configure Caddy

Edit `/etc/caddy/Caddyfile`:

```bash
sudo nano /etc/caddy/Caddyfile
```

Add this configuration:

```
:80 {
    # Auto-detect dev (8080) or production (3003)
    reverse_proxy localhost:8080 localhost:3003 {
        lb_policy first
        fail_duration 2s
        unhealthy_status 502 503 504
    }
}
```

Restart Caddy:

```bash
sudo systemctl restart caddy
```

#### Access MindSage

From any device on your network:

- **Using mDNS**: `http://<hostname>.local` (e.g., `http://ubuntu.local`)
- **Using IP**: `http://<jetson-ip>`

No port numbers needed! Works seamlessly in both dev and production mode.

## Common Issues

### Issue 1: Connection Refused

**Error**: `Failed to fetch` or `ERR_CONNECTION_REFUSED`

**Solution**: Backend server isn't running
```bash
npm run dev:server
```

### Issue 2: Vector Store Not Available

**Error**: Search/indexing endpoints return errors

**Solution**: Vector store service needs to be started
```bash
npm run vector-store:start
```

## Development Workflow

### 1. Start Development Servers

```bash
npm run dev:all
```

### 2. Start Frontend (separate repo)

```bash
cd ../mindsage-frontend
npm run dev
```

Then open http://localhost:8080

### 3. Make Changes

- **Backend changes**: Auto-restart (tsx watch)
- **Frontend changes**: Auto-reload (Vite HMR, in the frontend repo)

## Production Build

### Build Backend

```bash
# Build backend
npm run build
```

### Run Production Server

```bash
# Backend only
npm start

# Backend + Vector Store
npm run start:all
```

## Port Configuration

### Development Ports

- **3003**: Backend API (Express)
- **8085**: Vector Store (FastAPI)
- **8080**: Frontend (Vite dev server, separate repo)

### Production Ports

- **3003**: Backend API
- **8085**: Vector Store

## Environment Variables

Create `.env` file (optional, defaults shown):

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
npm start                   # Run production server (port 3003)
npm run start:all           # Run production + Vector Store

# Vector Store
npm run vector-store:start  # Start vector store service (port 8085)
npm run vector-store:setup  # Install Python deps + download models

# Data Management
npm run data:clean          # Clear vectordb, uploads, and imports
```

## Troubleshooting

### Backend Won't Start

**Check if port 3003 is in use:**
```bash
lsof -i :3003
# or
netstat -an | grep 3003
```

**Kill process if needed:**
```bash
kill -9 <PID>
```

### Vector Store Won't Start

**Check Python venv exists:**
```bash
ls vector-store/.venv/bin/python
```

**Recreate venv if needed:**
```bash
cd vector-store
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Frontend Can't Connect to Backend

- Ensure backend is running on port 3003
- Check CORS settings if accessing from different origin
- Verify the frontend's API URL is configured to http://localhost:3003

## Development Tips

### 1. Use Separate Terminals

Keep terminals organized:
- Terminal 1: `npm run dev:all` (backend + vector store)
- Terminal 2: Frontend dev server (in mindsage-frontend/)
- Terminal 3: Git commands

### 2. Watch the Logs

Both servers show helpful logs:
- Backend: API requests, errors
- Vector Store: Model loading, search queries

### 3. API Testing

Test backend endpoints directly:
```bash
# Get connectors
curl http://localhost:3003/api/connectors

# Get stats
curl http://localhost:3003/api/stats

# Check vector store health
curl http://localhost:8085/health

# Search
curl -X POST http://localhost:3003/api/vector-store/search \
  -H "Content-Type: application/json" \
  -d '{"query": "machine learning", "topK": 5}'
```

## MCP Vector Store Integration

The MindSage Vector Store exposes MCP (Model Context Protocol) tools for semantic search. This allows AI assistants like Claude and ChatGPT to search your document library.

### Starting the MCP Server

```bash
# Navigate to vector-store directory
cd vector-store

# Activate virtual environment
source .venv/bin/activate

# Start HTTP server (local network access)
python -m mcp_vector_store.mcp_server_http --port 8085 --host 0.0.0.0

# Or with public access (API key authentication)
python -m mcp_vector_store.mcp_server_http --port 8085 --public
```

The server exposes:
- **SSE Endpoint**: `http://localhost:8085/sse` (MCP protocol)
- **REST API**: `http://localhost:8085/api/*` (direct HTTP access)
- **Health Check**: `http://localhost:8085/health`

### Configuring Claude Code (CLI)

**Option 1: Quick setup via command line**

```bash
# Add MCP server using SSE transport
claude mcp add --transport sse mindsage-search http://YOUR-SERVER-IP:8085/sse

# Or with authentication header (for public mode)
claude mcp add --transport sse mindsage-search https://your-domain.com/sse \
  --header "Authorization: Bearer YOUR_API_KEY"
```

**Option 2: Manual configuration**

Add to your `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "mindsage-search": {
      "command": "/path/to/mindsage/vector-store/.venv/bin/python",
      "args": ["-m", "mcp_vector_store.mcp_server_stdio", "--url", "http://localhost:8085"]
    }
  }
}
```

This uses the stdio transport which wraps the HTTP API.

### Configuring Claude Desktop App

Claude Desktop requires `mcp-remote` to connect to HTTP/SSE servers. Edit your config file:

**Config file location:**
- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

**Basic configuration (local network):**

```json
{
  "mcpServers": {
    "mindsage-search": {
      "command": "npx",
      "args": [
        "-y",
        "mcp-remote",
        "http://YOUR-SERVER-IP:8085/sse",
        "--transport",
        "sse-only",
        "--allow-http"
      ]
    }
  }
}
```

Replace `YOUR-SERVER-IP` with your server's IP address (e.g., `192.168.1.100`).

**With authentication (public mode):**

```json
{
  "mcpServers": {
    "mindsage-search": {
      "command": "npx",
      "args": [
        "-y",
        "mcp-remote",
        "https://your-domain.com/sse",
        "--transport",
        "sse-only",
        "--header",
        "Authorization: Bearer ${MCP_API_KEY}"
      ],
      "env": {
        "MCP_API_KEY": "your-api-key-here"
      }
    }
  }
}
```

### Configuring ChatGPT (via OpenAI Agents SDK)

ChatGPT and OpenAI Agents can connect to MCP servers:

```python
from agents import Agent
from agents.mcp import MCPServerSse

# Connect to MindSage MCP server
mcp_server = MCPServerSse(
    url="http://your-server-ip:8085/sse",
    headers={"Authorization": "Bearer YOUR_API_KEY"}  # if using public mode
)

agent = Agent(
    name="research-agent",
    mcp_servers=[mcp_server]
)
```

### Available MCP Tools

| Tool | Description |
|------|-------------|
| `search_documents` | Semantic search with similarity scores |
| `enhanced_search` | Advanced search with passage extraction |
| `add_document` | Add document to vector store |
| `list_documents` | List all documents with pagination |
| `get_document` | Get specific document by ID |
| `search_with_topic` | Search filtered by topic |
| `list_all_topics` | List all topics with document counts |
| `get_stats` | Get database statistics |

### Testing MCP Tools

Test via REST API:

```bash
# Search documents
curl -X POST http://localhost:8085/api/search \
  -H "Content-Type: application/json" \
  -d '{"query": "machine learning", "top_k": 5}'

# Get stats
curl http://localhost:8085/api/stats

# List documents
curl "http://localhost:8085/api/documents?page=1&page_size=10"
```

### Exposing to Internet (Optional)

For remote AI client access:

1. **Use ngrok** (quick testing):
   ```bash
   ngrok http 8085
   ```

2. **Use Cloudflare Tunnel** (production):
   ```bash
   cloudflared tunnel --url http://localhost:8085
   ```

3. **Use Caddy reverse proxy** (with HTTPS):
   ```
   mcp.yourdomain.com {
       reverse_proxy localhost:8085
   }
   ```

Always use `--public` mode with a secure API key when exposing to the internet.

## Quick Reference

| What | Command | URL |
|------|---------|-----|
| Start dev servers | `npm run dev:all` | - |
| Backend API | - | http://localhost:3003 |
| Vector Store | `npm run vector-store:start` | http://localhost:8085 |
| Frontend (separate repo) | `cd ../mindsage-frontend && npm run dev` | http://localhost:8080 |
| Production | `npm run start:all` | http://localhost:3003 |
