# Agent Instructions

MindSage frontend is the React UI for the local-first MindSage backend and vector store.

## Start Here

1. Read `README.md`, `SECURITY.md`, and this file.
2. Assume UI data is sensitive. Do not create fixtures, screenshots, or logs from real user content.
3. Match existing React, Tailwind, shadcn/ui, TanStack Query, and route patterns.

## Common Commands

```bash
npm install
npm run dev
npm test
npm run build
npm run lint
```

The backend should be running from `../mindsage` with `npm run dev:all`.

## UI Security Notes

- LLM keys and de-anonymization stay server-side.
- Redacted/original media states must remain clear to the user.
- Connector setup should describe scopes and never expose stored tokens.
- Do not add third-party telemetry that sends content, filenames, queries, or graph data off-device without explicit opt-in.

## Integration Goal

The UI should make MindSage easy to connect to AI coding tools through MCP while preserving local ownership, consent, and PII protection.
