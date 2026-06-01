# Security Policy

The MindSage frontend displays and controls sensitive local knowledge, consent, connector, browser, media, and chat workflows. Treat all data shown by the UI as private.

## Supported Versions

Security fixes target the current `main` branch until versioned releases are cut.

## Reporting

Do not file public issues for vulnerabilities that could expose private data, credentials, browser sessions, source documents, or de-anonymization flows. Use GitHub private vulnerability reporting after the public repository is created.

## Frontend Security Rules

- Never store real API keys, tokens, cookies, captures, uploads, exports, or user documents in frontend code or fixtures.
- Keep LLM provider keys server-side. The UI may display configured/not-configured state, but must not reveal stored secrets.
- Preserve PII consent and redaction states in document, image, audio, chat, and graph views.
- Do not add telemetry or analytics that sends user content off-device without explicit opt-in and documentation.
- Avoid widening API access from the browser without matching backend authorization and tests.

## Maintainer Checklist

Before publishing or accepting a PR, run:

```bash
npm test
npm run build
npm run lint
```
