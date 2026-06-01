# Contributing

MindSage contributions should preserve local control, explicit consent, safe AI-tool integration, and privacy-first defaults.

## Setup

```bash
cd mindsage
npm install
npm run vector-store:setup
npm run dev:all
```

```bash
cd ../mindsage-frontend
npm install
npm run dev
```

## Quality Gates

From the root:

```bash
npm run check:oss
npm run test
npm run build
npm run lint
```

For Python/vector-store changes, run targeted `pytest` commands from `mindsage/vector-store/`.

## Privacy Rules

- Do not commit real user data or secrets.
- Keep LLM/MCP outputs redacted or anonymized by default.
- Add tests for PII redaction, consent, path validation, auth checks, connector ingestion, and file handling when changing those areas.
- New fixture data must be synthetic and documented.

## Pull Requests

Include:

- What changed and why.
- Commands run and results.
- Any privacy/security boundary affected.
- Migration notes for data, environment variables, or deployment.
