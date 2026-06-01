# Security Policy

MindSage is local-first software for sensitive personal data. Treat all connector outputs, uploads, captures, browser profiles, transcripts, images, vectors, and LLM configuration as private.

## Reporting

Do not open a public issue for vulnerabilities that could expose private data, credentials, browser sessions, vector databases, or de-anonymization paths. Use GitHub private vulnerability reporting after the repository is public.

## Supported Versions

Security fixes target the current `main` branch until versioned releases are cut.

## Boundaries

- Runtime data under `mindsage/data/` is ignored by git except `mindsage/data/test-pii-docs/`, which contains synthetic fixtures.
- Real API keys, cookies, browser profiles, uploads, exports, captures, vector databases, and generated redactions must never be committed.
- MCP and LLM-facing responses must default to redacted or anonymized content.
- De-anonymization must stay server-side and local-only; bearer-token remote MCP access does not grant de-anonymization.
- Public exposure of backend/vector-store ports without network controls and bearer-token authentication is unsupported.
- Remote vector-store MCP access must use `--public` or `MCP_VECTOR_STORE_PUBLIC=true` with `VECTOR_STORE_API_KEY` or `MCP_VECTOR_STORE_API_KEY` set to a 32+ character token.

## Maintainer Gate

Run before publishing or merging sensitive changes:

```bash
npm run check:oss
npm run test
npm run build
npm run lint
```

For Python/vector-store changes, also run targeted `pytest` suites from `mindsage/vector-store/`.
