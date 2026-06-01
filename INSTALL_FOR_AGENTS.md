# MindSage Installation Guide For AI Agents

Read this file before installing, verifying, or connecting MindSage to an AI coding tool.

## 1. Install Backend And Vector Store

Required runtime: Node.js 20.19+ (Node 22 LTS recommended) and Python 3.10+.

```bash
cd mindsage
npm install
npm run vector-store:setup
npm run dev:all
```

Expected services:

- Backend API: `http://localhost:3003`
- Vector store: `http://localhost:8085`
- MCP SSE: `http://localhost:8085/sse`

## 2. Install Frontend

```bash
cd ../mindsage-frontend
npm install
npm run dev
```

Open `http://localhost:8080`.

## 3. Connect AI Coding Tools

Generate the exact setup snippet when possible:

```bash
npm run agent:setup -- claude-code
npm run agent:setup -- cursor
npm run agent:setup -- codex
npm run agent:setup -- gemini-cli
npm run agent:setup -- vscode
npm run agent:setup -- windsurf
npm run agent:setup -- claude-desktop --mode remote --server-name mindsage-remote --base-url https://your-host
npm run agent:doctor
npm run agent:schema -- --json
npm run agent:pack -- --json
npm run agent:health -- --json
```

Claude Code:

```bash
claude mcp add mindsage-search --transport sse-only http://localhost:8085/sse
```

MCP clients that need a stdio bridge:

`agent:setup` supports Claude Code, Claude Desktop, Codex, Cursor, Gemini CLI, VS Code, Windsurf, Zed, Continue, Trae, and generic `mcp-json`. Codex prints a `config.toml` block under `[mcp_servers."mindsage-search"]`; the other JSON-style clients print an `mcpServers` object.

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

Remote MCP clients should use a private tunnel or HTTPS gateway plus bearer-token auth:

```bash
export MCP_VECTOR_STORE_API_KEY="$(python3 -c 'import secrets; print("ms_" + secrets.token_urlsafe(32))')"
PYTHONPATH=mindsage/vector-store MCP_VECTOR_STORE_PUBLIC=true VECTOR_STORE_API_KEY="$MCP_VECTOR_STORE_API_KEY" \
  python3 -m mcp_vector_store.mcp_server_http --host 0.0.0.0 --port 8085 --db-path mindsage/data/vectordb
```

For stdio-based AI tools connecting to that remote endpoint, use `mcp_server_stdio.py --url https://your-host --api-key "$MCP_VECTOR_STORE_API_KEY"` or set `MCP_VECTOR_STORE_API_KEY` in the tool environment. Do not expose local ports directly to the public internet without this protection.

## 4. Use The Agent Tools

Start with `think` when an AI coding tool needs an answer grounded in private memory. It returns cited redacted evidence, answer/source/concept/contradiction links, a safe entity graph, source coverage, freshness warnings, explicit gaps, and citation-maintenance actions without exposing PII session IDs.

Use `write_memory` for durable agent-owned facts such as decisions, claims, tasks, artifacts, entities, relations, and thought summaries. Use `search_memory` when the agent needs structured memory rather than raw documents. Use `memory_workspace_info` for workspace-level memory counts by kind, lifecycle state, actor, retention status, and audit window. Use `memory_actor_activity` for bounded append-only audit activity by actor or workspace. Use `memory_timeline` to inspect version history and audit events for one stable memory key. Use `memory_graph` to traverse declared memory relations and source-document links. Memory reads default to accepted, non-expired records and return redacted previews for LLM-facing clients.

Use `enhanced_search` for focused passage retrieval, `search_documents` for direct semantic search, and `add_document` for agent-written notes or imported context.

Use `npm run agent:schema -- --json` from the public monorepo root when an AI coding tool needs a machine-readable contract for MindSage. It lists MCP tools, REST endpoints, CLI commands, typed-memory fields, and safety defaults without requiring vector-store dependencies or exposing tokens.

Use `npm run agent:pack -- --json` from the public monorepo root when an AI coding tool needs MindSage's built-in schema pack for intake planning. Use `npm run agent:pack -- --classify <path>` to classify a local path into a document category and recommended typed-memory kind without echoing the filename, absolute path, or document text. Use `npm run agent:pack -- --detect <path> --json` to summarize corpus-level schema candidates, category counts, and high-risk review needs without reading or returning document text.

Use `npm run agent:health -- --json` from the public monorepo root when an agent needs a 0-100 memory health gate for freshness, undated sources, duplicate groups, safe entity consolidation, and replacement candidates. It is read-only and reports recommended maintenance commands without raw document content.

Use `npm run agent:search -- "remote MCP auth"` from the public monorepo root when an agent needs ranked passage evidence through a shell-friendly REST client instead of a synthesized answer. The command targets `/api/search/enhanced`, defaults to LLM-safe metadata, supports `--json`, `--top-k`, `--min-score`, `--base-url`, and `--api-key`, and does not echo bearer tokens in its report.

Use `npm run agent:think -- "What changed?"` from the public monorepo root when an agent needs the cited `think` response through a shell-friendly REST client. Add `--json` for machine-readable output, or `--base-url` and `--api-key` for protected remote servers.

Use `npm run agent:import -- ./notes` from the public monorepo root when an agent needs to bulk-import a local text corpus into `/api/documents/batch`. The importer skips duplicates by default, ignores hidden files, supports `--metadata key=value`, `--extensions md,txt`, `--json`, `--dry-run`, and remote `--base-url` plus `--api-key`.

Use `npm run agent:capture -- "Remember this"` from the public monorepo root for one-shot capture into the REST API without opening an MCP client. Add `--mode memory --kind decision --workspace <name> --memory-key <key>` when the note should become typed memory. The command supports `--dry-run`, `--base-url`, and `--api-key` for protected remote servers and does not echo captured text or bearer tokens in its report. For sensitive note text, prefer stdin with `npm --silent run agent:capture -- ...` so npm does not print the command banner.

Use `npm run maintenance:snapshot` when an agent needs a background report for stale sources, undated records, duplicate documents, safe entity label consolidation, and fresher replacement candidates over the tracked synthetic corpus or a compatible `.txt` corpus directory.

Use `npm run maintenance:plan -- --json` when an agent needs a schedulable maintenance loop. The plan turns snapshot findings into read-only recurring scans and review-required refresh/date/dedupe/entity/connector-sync jobs without echoing raw document text, PII session IDs, or person entities.

Use `npm run maintenance:apply -- --json` when an agent needs to convert a maintenance plan into reviewable write requests. The command is dry-run by default, requires approval before any executor can mutate data, and omits raw document text, filenames, paths, PII session IDs, and person entities from the batch.

Add `--ledger-path /tmp/mindsage-maintenance-ledger.jsonl` to append a redacted audit event for the batch, then inspect it with `npm run maintenance:apply -- --ledger-report /tmp/mindsage-maintenance-ledger.jsonl`. Use an explicit path outside the repo unless the user has intentionally configured a private runtime data directory.

## 5. Verify

From the repo root:

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

For Python/vector-store changes:

```bash
cd mindsage/vector-store
pytest tests/<targeted-suite>.py
```

The lightweight agent-tool unit tests can run without installing the full vector-store stack:

```bash
PYTHONPATH=mindsage/vector-store python3 -m unittest discover -s mindsage/vector-store/tests -p 'test_think_tool.py'
PYTHONPATH=mindsage/vector-store python3 -m unittest discover -s mindsage/vector-store/tests -p 'test_memory_tool.py'
PYTHONPATH=mindsage/vector-store python3 -m unittest discover -s mindsage/vector-store/tests -p 'test_remote_auth.py'
PYTHONPATH=mindsage/vector-store python3 -m unittest discover -s mindsage/vector-store/tests -p 'test_agent_setup.py'
PYTHONPATH=mindsage/vector-store python3 -m unittest discover -s mindsage/vector-store/tests -p 'test_agent_schema.py'
PYTHONPATH=mindsage/vector-store python3 -m unittest discover -s mindsage/vector-store/tests -p 'test_agent_pack.py'
PYTHONPATH=mindsage/vector-store python3 -m unittest discover -s mindsage/vector-store/tests -p 'test_agent_health.py'
PYTHONPATH=mindsage/vector-store python3 -m unittest discover -s mindsage/vector-store/tests -p 'test_agent_capture.py'
PYTHONPATH=mindsage/vector-store python3 -m unittest discover -s mindsage/vector-store/tests -p 'test_agent_think.py'
PYTHONPATH=mindsage/vector-store python3 -m unittest discover -s mindsage/vector-store/tests -p 'test_agent_import.py'
PYTHONPATH=mindsage/vector-store python3 -m unittest discover -s mindsage/vector-store/tests -p 'test_agent_search.py'
PYTHONPATH=mindsage/vector-store python3 -m unittest discover -s mindsage/vector-store/tests -p 'test_entity_graph.py'
PYTHONPATH=mindsage/vector-store python3 -m unittest discover -s mindsage/vector-store/tests -p 'test_maintenance_tool.py'
PYTHONPATH=mindsage/vector-store python3 -m unittest discover -s mindsage/vector-store/tests -p 'test_agent_evals.py'
PYTHONPATH=mindsage/vector-store python3 -m unittest discover -s mindsage/vector-store/tests -p 'test_corpus_evals.py'
PYTHONPATH=mindsage/vector-store python3 -m unittest discover -s mindsage/vector-store/tests -p 'test_agent_benchmarks.py'
python3 mindsage/vector-store/mcp_vector_store/agent_evals.py
python3 mindsage/vector-store/mcp_vector_store/corpus_evals.py
python3 mindsage/vector-store/mcp_vector_store/agent_benchmarks.py
```

## 6. Data Safety

Only `mindsage/data/test-pii-docs/` should be tracked under runtime data. It is a synthetic fixture corpus. Never commit real uploads, exports, captures, profiles, redactions, vector databases, or API keys.
