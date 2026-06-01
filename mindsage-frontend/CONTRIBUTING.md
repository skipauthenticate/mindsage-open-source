# Contributing

MindSage frontend is a React and TypeScript interface for local-first personal AI memory.

## Development Setup

Run the backend and vector store from the sibling `mindsage` repo first:

```bash
cd ../mindsage
npm run dev:all
```

Then start the frontend:

```bash
cd ../mindsage-frontend
npm install
npm run dev
```

Open `http://localhost:8080`.

## Quality Gates

```bash
npm test
npm run build
npm run lint
```

## Privacy Rules

- Do not commit user data, real captures, browser sessions, credentials, uploads, exports, or screenshots containing private content.
- Preserve the visible distinction between original and redacted media.
- Keep de-anonymization and secret handling on the backend.
- Add tests for consent, redaction, connector, upload, chat, and graph behavior when changing those flows.

## Pull Requests

Include what changed, why, commands run, and any security or privacy boundary affected.
