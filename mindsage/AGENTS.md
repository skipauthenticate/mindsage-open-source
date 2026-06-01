# Agent Instructions

MindSage backend contains the Express API, connector workers, LocalSend integration, browser connector, and Python vector store.

## Start Here

1. Read `README.md`, `SECURITY.md`, and this file.
2. Keep runtime data out of git. Only `data/test-pii-docs/` is tracked, and it contains synthetic fixtures.
3. Prefer narrow tests before broad suites. Always run the relevant verification command before claiming success.

## Common Commands

```bash
npm install
npm run vector-store:setup
npm run dev:all
npm test
npm run build
npm run check:oss
```

Vector-store tests run from `vector-store/` with `pytest`.

## Security Notes For Agents

- Do not print or commit API keys, cookies, browser profiles, captures, uploads, vector databases, or user exports.
- Treat MCP output as LLM-visible. It must be redacted or anonymized unless a local-only path is explicitly tested.
- Do not widen CORS, auth, filesystem, or de-anonymization behavior without tests and an explicit security rationale.
- When adding a connector, use least-privilege scopes and document the data that will be imported.

## Integration Goal

MindSage should be easy to connect to Claude Code, Cursor, Codex, ChatGPT, Gemini, and other MCP-compatible tools while preserving local ownership and PII protection. Prefer documented MCP/HTTP surfaces over client-specific hacks.
