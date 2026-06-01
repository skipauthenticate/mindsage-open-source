# Contributing

MindSage is a privacy-first local knowledge system. Contributions should preserve local control, explicit consent, and safe defaults for AI tool integration.

## Development Setup

```bash
npm install
npm run vector-store:setup
npm run dev:all
```

The backend runs on `http://localhost:3003`; the vector store runs on `http://localhost:8085`. The frontend lives in the sibling `mindsage-frontend` repository and runs on `http://localhost:8080`.

## Quality Gates

Run the narrowest relevant checks while developing, then run the full gate before submitting:

```bash
npm run check:oss
npm test
npm run build
```

For vector store changes, run targeted `pytest` tests from `vector-store/`. For frontend-impacting API changes, run the frontend test/build commands in the sibling repo.

## Privacy Rules

- Do not commit real user data, exports, captures, cookies, browser profiles, vector databases, or API keys.
- Keep LLM-facing and MCP-facing responses anonymized unless a local-only endpoint is explicitly designed for de-anonymization.
- Add regression tests for security-sensitive behavior, especially PII redaction, path validation, auth checks, and connector ingestion.
- The files under `data/test-pii-docs/` are synthetic fixtures. New fixtures must be synthetic and documented as such.

## Pull Requests

Keep changes focused. Include:

- What changed and why.
- Commands run and their results.
- Any privacy or security boundary affected.
- Migration notes for data, environment variables, or deployment.
