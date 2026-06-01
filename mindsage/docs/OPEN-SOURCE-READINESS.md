# Open Source Readiness

MindSage is moving toward a single public repository containing backend, vector store, frontend, docs, and agent integration guidance.

## Current Status

- Backend and frontend are current with their `origin/main` branches as of 2026-06-01.
- Core security and red-team reports are present under `docs/`.
- Top-level license, security policy, contributing guide, code of conduct, agent install guide, and LLM doc map are now part of the backend repo.
- The tracked `data/test-pii-docs/` corpus is synthetic and documented.

## Required Before Public Release

- Build the final single-repo layout and commit it as one initial public commit.
- Run backend and frontend tests/builds from the final repo.
- Run an actual secret scan over the final repo.
- Confirm no runtime data is tracked outside approved synthetic fixtures.
- Decide the public repository name, owner, issue templates, and vulnerability reporting path.
- Add CI for backend test/build, frontend test/build, vector-store targeted tests, agent-tool unit tests, remote-auth tests, safe-entity-graph tests, citation-maintenance tests, replayable agent evals including cited-answer graph checks, fixture-corpus evals, and open-source readiness checks.

## Release Gate

From the backend repo:

```bash
npm run check:oss
npm test
npm run build
```

From the frontend repo:

```bash
npm test
npm run build
```

From the final single-repo root, run `npm run test:python` for vector-store syntax plus lightweight agent-tool, safe-entity-graph, and citation-maintenance tests, and `npm run eval:agents` for replayable agent-memory quality gates.
