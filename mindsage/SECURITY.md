# Security Policy

MindSage is designed for local-first personal data and AI memory. Treat every connector, document, capture, transcript, image, and vector record as sensitive by default.

## Supported Versions

Security fixes target the current `main` branch until versioned releases are cut.

## Reporting

Do not file a public issue for a vulnerability that could expose private data, credentials, browser sessions, or de-anonymization flows. Use GitHub private vulnerability reporting after the public repository is created. If private reporting is unavailable, contact the repository owner privately and include only the minimum reproduction details needed to confirm impact.

## Security Boundaries

- Runtime data lives under `data/` and is ignored by git except the synthetic `data/test-pii-docs/` fixture corpus.
- API keys can be configured with environment variables or through the UI. Do not commit real keys, cookies, browser profiles, exports, captures, vector databases, or uploaded files.
- MCP and LLM-facing outputs must default to redacted or anonymized content. Do not add tools that return raw PII unless they are local-only and covered by tests.
- Remote access should be behind trusted network controls or explicit bearer authentication. Public exposure of the backend or vector store without authentication is unsupported.
- Vector-store remote MCP access must use `--public` or `MCP_VECTOR_STORE_PUBLIC=true` with `VECTOR_STORE_API_KEY` or `MCP_VECTOR_STORE_API_KEY` set to a 32+ character token. De-anonymization remains local-only.
- Browser connector profiles may contain active sessions. Never commit `data/browser-connector/`.

## Maintainer Checklist

Before publishing or accepting a PR, run:

```bash
npm run check:oss
npm test
npm run build
```

For Python/vector-store changes, also run the relevant `pytest` target from `vector-store/`.
