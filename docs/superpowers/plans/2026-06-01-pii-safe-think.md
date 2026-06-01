# PII-Safe Think Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a PII-safe MindSage `think` tool that returns citations, coverage, freshness, contradictions, gaps, and privacy metadata for agent clients.

**Architecture:** Implement deterministic result shaping in `mcp_vector_store.think_tool`, then wire it into the HTTP MCP server, the REST API, and the stdio MCP proxy. Keep LLM-facing output redacted by reusing the existing `context="llm"` retrieval path and removing any PII session identifiers before response construction.

**Tech Stack:** Python 3, stdlib `unittest`, existing MCP Python server, existing Starlette HTTP routes.

---

### Task 1: Pure Think Engine

**Files:**
- Create: `mindsage/vector-store/mcp_vector_store/think_tool.py`
- Create: `mindsage/vector-store/tests/test_think_tool.py`

- [ ] **Step 1: Write failing tests**

Create `mindsage/vector-store/tests/test_think_tool.py` with tests for empty evidence, citation privacy, coverage, freshness, and simple contradictions.

- [ ] **Step 2: Verify red**

Run:

```bash
PYTHONPATH=mindsage/vector-store python3 -m unittest discover -s mindsage/vector-store/tests -p 'test_think_tool.py'
```

Expected: fail because `mcp_vector_store.think_tool` does not exist.

- [ ] **Step 3: Implement engine**

Create `mindsage/vector-store/mcp_vector_store/think_tool.py` with:

- `build_think_response(question, results, top_k=8, freshness_days=90, include_gaps=True)`
- citation normalization from common result keys: `id`, `doc_id`, `text`, `content`, `passage`, `metadata`, `score`
- date extraction from `date`, `created_at`, `modified_at`, `source_date`, and metadata equivalents
- PII session ID removal
- coverage, freshness, contradiction, and gap generation

- [ ] **Step 4: Verify green**

Run:

```bash
PYTHONPATH=mindsage/vector-store python3 -m unittest discover -s mindsage/vector-store/tests -p 'test_think_tool.py'
```

Expected: all tests pass.

### Task 2: HTTP MCP And REST Wiring

**Files:**
- Modify: `mindsage/vector-store/mcp_vector_store/mcp_server_http.py`

- [ ] **Step 1: Add `ThinkInput` schema**

Add a Pydantic model with `question`, `top_k`, `freshness_days`, and `include_gaps`.

- [ ] **Step 2: Add `think` tool listing**

Add `Tool(name="think", ...)` to the MCP tool list.

- [ ] **Step 3: Add tool dispatcher branch**

Route MCP calls named `think` to `_think(arguments)`.

- [ ] **Step 4: Implement `_think`**

Use `self.vector_store.enhanced_search(query=question, top_k=top_k)` when available, fall back to `self.vector_store.search(query=question, top_k=top_k)`, apply the same PII-safe output handling pattern used by `_enhanced_search`, then call `build_think_response()`.

- [ ] **Step 5: Add REST route**

Add `POST /api/think` that validates JSON, retrieves results with LLM-safe context, and returns the same JSON shape as the MCP tool.

### Task 3: Stdio MCP Proxy

**Files:**
- Modify: `mindsage/vector-store/mcp_vector_store/mcp_server_stdio.py`

- [ ] **Step 1: Add `ThinkInput` schema**

Mirror the HTTP input fields.

- [ ] **Step 2: Add `think` to list_tools**

Expose `think` to stdio MCP clients.

- [ ] **Step 3: Forward tool call**

POST arguments to `{base_url}/api/think` and return the response text.

### Task 4: Docs, CI, Verification, And Publish

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `README.md`
- Modify: `docs/COMPETITIVE-ANALYSIS.md`
- Modify: `INSTALL_FOR_AGENTS.md`

- [ ] **Step 1: Add Python unit test to CI**

Add:

```bash
PYTHONPATH=mindsage/vector-store python3 -m unittest discover -s mindsage/vector-store/tests -p 'test_think_tool.py'
```

- [ ] **Step 2: Document the `think` tool**

Mention `think` in the root README and agent install guide MCP tool list.

- [ ] **Step 3: Run release gate**

Run:

```bash
npm run verify
(cd mindsage && npm audit --audit-level=moderate)
(cd mindsage-frontend && npm audit --audit-level=moderate)
python3 -m compileall -q mindsage/vector-store/mcp_vector_store
PYTHONPATH=mindsage/vector-store python3 -m unittest discover -s mindsage/vector-store/tests -p 'test_think_tool.py'
```

- [ ] **Step 4: Amend and push single commit**

Run:

```bash
git add .
git commit --amend --no-edit
git push --force-with-lease origin main
gh run watch --repo skipauthenticate/mindsage-open-source --exit-status
```
