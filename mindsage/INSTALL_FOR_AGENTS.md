# MindSage Installation Guide For AI Agents

Use this when an AI coding tool is installing or verifying MindSage for a user. Read the whole file before running commands.

## 1. Clone Layout

MindSage currently uses two sibling repos:

```text
workspace/
├── mindsage/            # backend + vector store
└── mindsage-frontend/   # React frontend
```

If the frontend is missing, clone it next to this repo.

## 2. Install Backend

```bash
cd mindsage
npm install
npm run vector-store:setup
```

The vector setup downloads local ML models. On constrained hardware, tell the user before starting large downloads.

## 3. Configure Environment

Copy `.env.example` to `.env` only when the user wants local overrides. Never invent or commit real credentials.

Useful variables:

```env
PORT=3003
VECTOR_STORE_HOST=localhost
VECTOR_STORE_PORT=8085
PII_ENTITIES=strict
```

LLM keys are optional and can also be configured through the UI.

## 4. Start Services

```bash
npm run dev:all
```

Expected local services:

- Backend API: `http://localhost:3003`
- Vector store: `http://localhost:8085`
- MCP SSE endpoint: `http://localhost:8085/sse`

## 5. Install Frontend

```bash
cd ../mindsage-frontend
npm install
npm run dev
```

Open `http://localhost:8080`.

## 6. Connect AI Coding Tools

From the public monorepo root, generate setup snippets with:

```bash
npm run agent:setup -- claude-code
npm run agent:setup -- cursor
npm run agent:setup -- codex
npm run agent:setup -- gemini-cli
npm run agent:setup -- vscode
npm run agent:setup -- windsurf
npm run agent:doctor
npm run agent:schema -- --json
npm run agent:pack -- --json
npm run agent:health -- --json
```

Run `npm run maintenance:snapshot` from the public monorepo root for a PII-safe background report on stale sources, undated records, duplicate documents, safe entity label variants, and fresher replacement candidates.

Run `npm run maintenance:plan -- --json` from the public monorepo root when an agent needs a schedulable maintenance loop. Plans include recurring read-only scans and review-required refresh/date/dedupe/entity/connector-sync jobs without raw document text, PII session IDs, or person entities.

Run `npm run maintenance:apply -- --json` from the public monorepo root when an agent needs a dry-run apply batch. Batches include read-only jobs, pending maintenance write requests, optional approval marking, and no raw document text, filenames, paths, PII session IDs, or person entities.

Add `--ledger-path /tmp/mindsage-maintenance-ledger.jsonl` to record a redacted append-only audit event for the batch, and inspect that history with `npm run maintenance:apply -- --ledger-report /tmp/mindsage-maintenance-ledger.jsonl`.

Use `npm run agent:schema -- --json` from the public monorepo root when an AI coding tool needs a machine-readable contract for MCP tools, REST endpoints, CLI commands, typed-memory fields, and safety defaults.

Use `npm run agent:pack -- --json` from the public monorepo root when an AI coding tool needs MindSage's built-in schema pack for intake planning. Use `npm run agent:pack -- --classify <path>` to classify a path into a document category and recommended typed-memory kind without echoing filenames, absolute paths, or document text. Use `npm run agent:pack -- --detect <path> --json` to summarize corpus-level schema candidates without reading or returning document text.

Use `npm run agent:health -- --json` from the public monorepo root when an agent needs a 0-100 memory health gate for freshness, undated sources, duplicate groups, safe entity consolidation, and replacement candidates before trusting retrieved context.

Use `npm run agent:search -- "remote MCP auth"` from the public monorepo root when an agent needs ranked passage evidence from `/api/search/enhanced` without opening an MCP client. Add `--json`, `--top-k`, `--min-score`, `--base-url`, and `--api-key` for machine-readable or protected remote workflows.

Use `npm run agent:think -- "What changed?"` from the public monorepo root when an agent needs a shell-native cited `think` query without opening an MCP client. Add `--json` for machine-readable output, or `--base-url` plus `--api-key` for protected remote servers.

Use `npm run agent:import -- ./notes` from the public monorepo root when an agent needs to bulk-import a local text corpus into `/api/documents/batch`. The importer skips duplicates by default, ignores hidden files, supports `--metadata key=value`, `--extensions md,txt`, `--json`, `--dry-run`, and remote `--base-url` plus `--api-key`.

Use `npm run agent:capture -- "Remember this"` from the public monorepo root when an agent needs a one-shot REST write path without opening an MCP client. Add `--mode memory --kind decision --workspace <name> --memory-key <key>` for typed memory, and use `--dry-run`, `--base-url`, plus `--api-key` for protected remote servers. For sensitive note text, prefer stdin with `npm --silent run agent:capture -- ...` so npm does not print the command banner.

### Claude Code

Use the local MCP endpoint:

```bash
claude mcp add mindsage-search --transport sse-only http://localhost:8085/sse
```

### Codex, Gemini CLI, VS Code, And Other MCP Clients

Use `agent:setup` for Claude Code, Claude Desktop, Codex, Cursor, Gemini CLI, VS Code, Windsurf, Zed, Continue, Trae, and generic `mcp-json`. Codex prints a `config.toml` block under `[mcp_servers."mindsage-search"]`; JSON-style clients print an `mcpServers` object. Use an MCP remote bridge such as `mcp-remote` if the client does not support SSE directly:

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

### Remote Clients

Do not expose `8085` publicly without network controls and bearer-token authentication. If a remote AI client needs access, place MindSage behind a private tunnel or HTTPS gateway, then run the vector store with `MCP_VECTOR_STORE_PUBLIC=true` and a 32+ character `VECTOR_STORE_API_KEY` or `MCP_VECTOR_STORE_API_KEY`. Stdio bridges can pass the same token with `mcp_server_stdio.py --url https://your-host --api-key "$MCP_VECTOR_STORE_API_KEY"`.

### Core Agent Tools

- `think` returns cited, redacted reasoning context with answer/source/concept/contradiction graph links, safe entity graph links, source coverage, freshness warnings, gaps, and citation-maintenance actions.
- `write_memory` stores typed, versioned memory records for decisions, claims, tasks, artifacts, entities, relations, and summaries.
- `search_memory` retrieves typed memory with accepted/non-expired defaults and redacted previews.
- `memory_workspace_info` summarizes typed-memory counts by workspace, kind, lifecycle state, actor, retention status, and audit window.
- `memory_actor_activity` returns bounded append-only audit activity for an actor or workspace.
- `memory_timeline` returns audit events and versions for one stable memory key.
- `memory_graph` traverses declared typed-memory relations and source-document links for graph-assisted context.
- `enhanced_search` and `search_documents` remain available for document-level retrieval.
- `npm run agent:schema` prints the versioned AI-tool integration contract without requiring the full vector-store stack.
- `npm run agent:pack` prints the built-in schema pack, classifies paths, and detects corpus-level schema candidates without echoing filenames, absolute paths, or document text.
- `npm run agent:health` reports a read-only memory health score and next maintenance commands without raw document content.
- `npm run agent:search` asks `/api/search/enhanced` from a shell and reports ranked passage evidence without echoing bearer tokens.
- `npm run agent:think` asks `/api/think` from a shell and reports compact cited answers without echoing private questions or bearer tokens.
- `npm run agent:import` imports local text corpora through `/api/documents/batch` without echoing imported text or bearer tokens.
- `npm run agent:capture` writes quick notes or typed memory through the REST API and reports storage without echoing captured content or bearer tokens.
- `npm run maintenance:apply` converts maintenance plans into reviewable dry-run write batches without mutating data by default.
- `npm run maintenance:apply -- --ledger-path <path>` appends redacted audit events for maintenance batches without storing raw document text.

## 7. Verify

From `mindsage/`:

```bash
npm run check:oss
npm test
npm run build
```

From the combined open-source repo root, also run:

```bash
npm run test:python
npm run eval:corpus
```

From `mindsage-frontend/`:

```bash
npm test
npm run build
```

## 8. Data Safety

The only tracked `data/` content should be the synthetic `data/test-pii-docs/` fixture corpus. Never commit user uploads, connector exports, browser sessions, vector databases, or generated redactions.
