# MindSage Frontend Installation Guide For AI Agents

Read this before installing or verifying the frontend.

## 1. Expected Layout

```text
workspace/
├── mindsage/            # backend + vector store
└── mindsage-frontend/   # this repo
```

The frontend proxies `/api` calls to the backend on `http://localhost:3003`.

## 2. Start Backend First

```bash
cd ../mindsage
npm install
npm run vector-store:setup
npm run dev:all
```

Expected services:

- Backend API: `http://localhost:3003`
- Vector store: `http://localhost:8085`

## 3. Start Frontend

```bash
cd ../mindsage-frontend
npm install
npm run dev
```

Open `http://localhost:8080`.

## 4. Verify

```bash
npm test
npm run build
npm run lint
```

## 5. MCP Setup

The MCP endpoint is served by the vector store in the backend repo:

```text
http://localhost:8085/sse
```

The frontend includes an MCP setup panel that renders copyable client configuration for Claude Desktop and Claude CLI.

## 6. Data Safety

Never commit screenshots, fixtures, logs, or generated assets containing user content. Use synthetic data for tests.
