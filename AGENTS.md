# Agent Instructions

This repo contains the complete MindSage stack:

- `mindsage/`: backend, connectors, browser connector, LocalSend, vector store.
- `mindsage-frontend/`: React frontend.

## Required Reading

1. `README.md`
2. `SECURITY.md`
3. `INSTALL_FOR_AGENTS.md`
4. `docs/COMPETITIVE-ANALYSIS.md`
5. Relevant subproject `AGENTS.md` files.

## Common Commands

```bash
npm run check:oss
npm run test
npm run test:python
npm run benchmark:agents
npm run maintenance:snapshot
npm run build
npm run lint
```

Backend dev:

```bash
cd mindsage && npm run dev:all
```

Frontend dev:

```bash
cd mindsage-frontend && npm run dev
```

## Safety Rules

- Do not print or commit secrets, cookies, browser profiles, captures, uploads, exports, vector databases, or runtime `data/` content.
- Treat MCP responses as LLM-visible. Keep them redacted/anonymized unless a local-only flow is explicitly documented and tested.
- Do not widen CORS, filesystem, auth, or de-anonymization behavior without tests and a security rationale.
- Prefer structured parsers and existing APIs over ad hoc string manipulation.
- Before claiming success, run the relevant verification command and inspect the output.

## Product Direction

MindSage should compete with GBrain by being easier to connect to AI tools, stronger on local multimodal personal data, and safer by default for PII-heavy workflows. OpenBrain’s typed memory, lifecycle, audit, actor activity, and workspace governance model should guide future memory-layer work.
