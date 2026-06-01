# Open Source Readiness

MindSage is published as a single public repository containing backend, vector store, frontend, docs, and agent integration guidance.

## Current Status

- Backend and frontend are current with their `origin/main` branches as of 2026-06-01.
- Core security and red-team reports are present under `docs/`.
- Top-level license, security policy, contributing guide, code of conduct, agent install guide, CI, and LLM doc map are part of the public repo.
- The tracked `data/test-pii-docs/` corpus is synthetic and documented.
- The public repo is `https://github.com/skipauthenticate/mindsage-open-source`.

## Public Release Gate

- Keep the public history to one initial commit unless intentionally cutting a follow-up release.
- Run backend and frontend tests/builds from the final repo before publishing amendments.
- Run the open-source readiness check and dependency audits before publishing amendments.
- Confirm no runtime data is tracked outside approved synthetic fixtures.
- Keep CI green for backend test/build, frontend lint/test/build, vector-store syntax, agent-tool unit tests, remote-auth tests, agent-setup generator tests, agent-schema tests, agent-health tests, agent-capture tests, agent-think tests, agent-import tests, agent-search tests, safe-entity-graph tests, citation-maintenance and maintenance-snapshot tests, workspace/actor governance tests, replayable agent evals including cited-answer graph checks, fixture-corpus evals, dependency-light agent feature benchmarks, and open-source readiness checks.

## Release Gate

From the public repo root:

```bash
npm run check:oss
npm run verify
(cd mindsage && npm audit --audit-level=moderate)
(cd mindsage-frontend && npm audit --audit-level=moderate)
```

For Python changes:

```bash
python3 -m compileall -q mindsage/vector-store/mcp_vector_store
PYTHONPATH=mindsage/vector-store python3 -m unittest discover -s mindsage/vector-store/tests -p 'test_think_tool.py'
PYTHONPATH=mindsage/vector-store python3 -m unittest discover -s mindsage/vector-store/tests -p 'test_memory_tool.py'
PYTHONPATH=mindsage/vector-store python3 -m unittest discover -s mindsage/vector-store/tests -p 'test_remote_auth.py'
PYTHONPATH=mindsage/vector-store python3 -m unittest discover -s mindsage/vector-store/tests -p 'test_agent_setup.py'
PYTHONPATH=mindsage/vector-store python3 -m unittest discover -s mindsage/vector-store/tests -p 'test_agent_schema.py'
PYTHONPATH=mindsage/vector-store python3 -m unittest discover -s mindsage/vector-store/tests -p 'test_agent_health.py'
PYTHONPATH=mindsage/vector-store python3 -m unittest discover -s mindsage/vector-store/tests -p 'test_agent_capture.py'
PYTHONPATH=mindsage/vector-store python3 -m unittest discover -s mindsage/vector-store/tests -p 'test_agent_think.py'
PYTHONPATH=mindsage/vector-store python3 -m unittest discover -s mindsage/vector-store/tests -p 'test_agent_import.py'
PYTHONPATH=mindsage/vector-store python3 -m unittest discover -s mindsage/vector-store/tests -p 'test_agent_search.py'
PYTHONPATH=mindsage/vector-store python3 -m unittest discover -s mindsage/vector-store/tests -p 'test_entity_graph.py'
PYTHONPATH=mindsage/vector-store python3 -m unittest discover -s mindsage/vector-store/tests -p 'test_maintenance_tool.py'
PYTHONPATH=mindsage/vector-store python3 -m unittest discover -s mindsage/vector-store/tests -p 'test_agent_evals.py'
PYTHONPATH=mindsage/vector-store python3 -m unittest discover -s mindsage/vector-store/tests -p 'test_corpus_evals.py'
PYTHONPATH=mindsage/vector-store python3 -m unittest discover -s mindsage/vector-store/tests -p 'test_agent_benchmarks.py'
python3 mindsage/vector-store/mcp_vector_store/agent_evals.py
python3 mindsage/vector-store/mcp_vector_store/corpus_evals.py
python3 mindsage/vector-store/mcp_vector_store/agent_benchmarks.py
npm run maintenance:snapshot -- --reference-date 2026-06-01 --freshness-days 90
```
