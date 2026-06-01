# MindSage

Your private memory layer for AI tools.

MindSage gives assistants, coding agents, and personal AI workflows a place to remember the useful stuff: project notes, docs, AI conversations, files, images, audio, connector exports, and quick decisions you do not want to paste into every chat again.

It is local-first, citation-heavy, and built for sensitive personal data. Ask a question, get an answer with sources, see what is stale or missing, and keep the raw private context on your machine by default.

## The Short Version

MindSage is for you if you want AI tools that can:

- Search your private context without dumping raw data into every tool.
- Answer with citations, source coverage, gaps, contradictions, and freshness warnings.
- Remember decisions, tasks, claims, entities, relations, artifacts, and summaries.
- Connect through MCP, REST, shell commands, or a full React UI.
- Work with real personal inputs, including notes, markdown folders, JSON exports, images, audio, LocalSend, browser connector flows, and AI chat captures.
- Stay testable, benchmarked, and open-source ready.

Think of it as the calm, local brain behind the tools you already use.

## What Is In The Box

```text
mindsage-open-source/
├── mindsage/             # Express backend, connectors, Python vector store, MCP
├── mindsage-frontend/    # React/Vite app for search, chat, consent, media, graphs
├── docs/                 # Public readiness, strategy, and comparison docs
└── scripts/              # Open-source safety checks
```

The stack includes:

- An Express backend for documents, chat, connectors, media, graph APIs, and consent flows.
- A Python vector store with MCP, cited `think`, search, typed memory, evals, and maintenance tools.
- A React/Vite frontend for search, chat, document review, media review, and knowledge graph exploration.
- Agent-friendly CLIs for setup, schema discovery, health checks, import, search, capture, and benchmarks.
- Safety gates for tests, evals, benchmarks, dependency audits, builds, lint, and open-source leak checks.

For the competitive roadmap, read [docs/COMPETITIVE-ANALYSIS.md](docs/COMPETITIVE-ANALYSIS.md).

## Quick Start

You need Node.js 20.19+ and Python 3.10+. Node 22 LTS is the smooth path. Chrome or Chromium is needed for browser connector flows.

Start the backend and vector store:

```bash
cd mindsage
npm install
npm run vector-store:setup
npm run dev:all
```

Start the frontend in another terminal:

```bash
cd mindsage-frontend
npm install
npm run dev
```

Open `http://localhost:8080`.

Local services:

- Frontend: `http://localhost:8080`
- Backend API: `http://localhost:3003`
- Vector store and MCP SSE: `http://localhost:8085`

## Docker

Prefer containers? From the repository root:

```bash
docker compose up -d --build
```

Docker services:

- Frontend: `http://localhost:8080`
- Backend API: `http://localhost:3003`
- Vector store and MCP SSE: `http://localhost:8085`
- noVNC browser access: `http://localhost:6080/vnc.html`

## Connect AI Tools

MindSage speaks MCP, so coding agents and desktop assistants can use it as a memory server.

Local MCP endpoint:

```text
http://localhost:8085/sse
```

Generate setup snippets instead of hand-editing config files:

```bash
npm run agent:setup -- claude-code
npm run agent:setup -- cursor
npm run agent:setup -- codex
npm run agent:setup -- gemini-cli
npm run agent:setup -- vscode
npm run agent:setup -- windsurf
npm run agent:setup -- claude-desktop --mode remote --server-name mindsage-remote --base-url https://mindsage.example.com
npm run agent:doctor
npm run agent:schema -- --json
npm run agent:pack -- --json
npm run agent:health -- --json
```

Claude Code can connect directly:

```bash
claude mcp add mindsage-search --transport sse-only http://localhost:8085/sse
```

Codex gets a `config.toml` block. Claude Desktop, Cursor, Gemini CLI, VS Code, Windsurf, Zed, Continue, Trae, and other MCP JSON clients can use the generated `mcpServers` config with `mcp-remote`:

```json
{
  "mcpServers": {
    "mindsage-search": {
      "command": "npx",
      "args": [
        "-y",
        "mcp-remote",
        "http://localhost:8085/sse",
        "--transport",
        "sse-only",
        "--allow-http"
      ]
    }
  }
}
```

Once connected, start with `think`. It returns grounded answers with redacted evidence, citations, source coverage, graph links, freshness warnings, contradictions, gaps, and maintenance hints.

Use `write_memory` for durable decisions, claims, tasks, artifacts, entities, relations, and summaries. Use `search_memory`, `memory_workspace_info`, `memory_actor_activity`, `memory_timeline`, and `memory_graph` when an agent needs governed memory reads, workspace health, actor audit activity, version history, or relation traversal.

For lower-level ingestion and retrieval, use `enhanced_search`, `search_documents`, and `add_document`.

## Bring In Context

Import a notes folder, markdown archive, JSON export, log bundle, or small text corpus:

```bash
npm run agent:import -- ./notes
```

The importer posts to `/api/documents/batch`, skips duplicates by default, ignores hidden files, and supports `.txt`, `.md`, `.markdown`, `.json`, `.csv`, and `.log`.

Useful options:

```bash
npm run agent:import -- ./notes --metadata source=notebook --extensions md,txt
npm run agent:import -- --dry-run ./notes
```

Classify a path without echoing the filename or absolute path:

```bash
npm run agent:pack -- --classify ./notes/chatgpt-export.json
```

Detect corpus-level schema candidates without returning filenames, paths, or document text:

```bash
npm run agent:pack -- --detect ./notes --json
```

## Ask With Receipts

Use search when you want evidence first:

```bash
npm run agent:search -- "remote MCP auth"
```

Use `think` when you want synthesis:

```bash
npm run agent:think -- "What do I need to know before touching remote MCP auth?"
```

Both commands can target a protected remote server with `--base-url` and `--api-key`. Add `--json` when another tool should consume the full response.

## Capture Decisions

Save a quick note:

```bash
npm run agent:capture -- "Remember that the remote MCP endpoint must require bearer auth."
```

Save typed memory:

```bash
npm run agent:capture -- \
  --mode memory \
  --kind decision \
  --workspace ops \
  --memory-key decision:remote-mcp \
  "Use authenticated private tunnels for remote MCP."
```

Reports are intentionally quiet. They confirm storage without echoing captured content or bearer tokens.

For sensitive note text, prefer stdin with `npm --silent`:

```bash
printf '%s\n' "Use bearer auth for remote MCP." | npm --silent run agent:capture -- --mode memory --kind decision
```

Preview without posting:

```bash
npm run agent:capture -- --dry-run "Check bearer auth before remote MCP launch."
```

## Keep Memory Healthy

MindSage includes maintenance tools for stale sources, undated records, duplicate documents, safe entity label variants, and fresher replacement candidates.

Run a snapshot:

```bash
npm run maintenance:snapshot -- --reference-date 2026-06-01 --freshness-days 90
```

Turn it into a schedulable review plan:

```bash
npm run maintenance:plan -- --reference-date 2026-06-01 --freshness-days 90
```

Turn the plan into a reviewable dry-run apply batch:

```bash
npm run maintenance:apply -- --reference-date 2026-06-01 --freshness-days 90
```

Record the apply batch in an append-only redacted ledger:

```bash
npm run maintenance:apply -- --reference-date 2026-06-01 --freshness-days 90 --ledger-path /tmp/mindsage-maintenance-ledger.jsonl
npm run maintenance:apply -- --ledger-report /tmp/mindsage-maintenance-ledger.jsonl
```

Check whether retrieved memory is healthy enough for an agent to trust:

```bash
npm run agent:health -- --reference-date 2026-06-01 --freshness-days 90
```

Maintenance output is designed to be reviewable and PII-safe. Apply batches default to `dry_run`, ledger entries are redacted audit summaries, and neither one mutates data by itself. They do not dump raw document text, filenames, paths, PII session IDs, or person entities into agent-facing reports.

## Remote MCP

Remote access should be private by design. Put the server behind a private tunnel or HTTPS gateway, require a strong bearer token, and never commit the token.

```bash
export MCP_VECTOR_STORE_API_KEY="$(python3 -c 'import secrets; print("ms_" + secrets.token_urlsafe(32))')"
PYTHONPATH=mindsage/vector-store MCP_VECTOR_STORE_PUBLIC=true VECTOR_STORE_API_KEY="$MCP_VECTOR_STORE_API_KEY" \
  python3 -m mcp_vector_store.mcp_server_http --host 0.0.0.0 --port 8085 --db-path mindsage/data/vectordb
```

Stdio-based AI tools can forward the same bearer token:

```json
{
  "mcpServers": {
    "mindsage-remote": {
      "command": "python3",
      "args": [
        "mindsage/vector-store/mcp_vector_store/mcp_server_stdio.py",
        "--url",
        "https://mindsage.example.com",
        "--api-key",
        "YOUR_32_PLUS_CHARACTER_TOKEN"
      ]
    }
  }
}
```

Do not expose MCP or backend ports publicly without network controls and bearer-token authentication.

## Test, Eval, Benchmark

The fastest confidence check:

```bash
npm run verify
```

That runs:

```bash
npm run check:oss
npm run test
npm run test:python
npm run eval:agents
npm run eval:corpus
npm run benchmark:agents
npm run maintenance:snapshot
npm run maintenance:plan
npm run maintenance:apply
npm run maintenance:apply -- --ledger-report /tmp/mindsage-maintenance-ledger.jsonl
npm run build
npm run lint
```

Coverage includes backend and frontend tests, Python agent-tool tests, replayable agent evals, fixture-corpus evals, feature benchmarks, production builds, frontend lint, dependency audits, and open-source safety checks.

Current benchmark coverage includes cited `think`, citation graphs, entity graphs, citation maintenance, background maintenance snapshots, maintenance plans, dry-run maintenance apply batches, append-only maintenance ledgers, typed memory, workspace summaries, actor activity, remote bearer auth, MCP setup generation, agent schema, schema-pack classification and corpus detection, agent health, agent capture, agent think, agent import, agent search, and fixture-corpus retrieval.

Dependency audits currently report 0 moderate-or-higher vulnerabilities in both subprojects:

```bash
(cd mindsage && npm audit --audit-level=moderate)
(cd mindsage-frontend && npm audit --audit-level=moderate)
```

## Security

MindSage handles sensitive personal data. Runtime data is ignored by git. The only tracked `data/` content is the synthetic `mindsage/data/test-pii-docs/` fixture corpus.

Read [SECURITY.md](SECURITY.md) before exposing the service beyond localhost or adding connectors/tools that return user content.

## Docs Worth Reading

- [INSTALL_FOR_AGENTS.md](INSTALL_FOR_AGENTS.md) - installation and MCP setup for coding agents.
- [docs/OPEN-SOURCE-READINESS.md](docs/OPEN-SOURCE-READINESS.md) - release gates and public repo checklist.
- [docs/COMPETITIVE-ANALYSIS.md](docs/COMPETITIVE-ANALYSIS.md) - how MindSage compares with GBrain and OpenBrain ideas.
- [mindsage/docs/SEARCH-PERFORMANCE.md](mindsage/docs/SEARCH-PERFORMANCE.md) - deeper search benchmark notes.

## License

MIT
