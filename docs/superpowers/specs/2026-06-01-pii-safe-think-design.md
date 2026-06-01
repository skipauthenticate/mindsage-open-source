# PII-Safe Think Tool Design

## Goal

Add a MindSage `think` capability that gives AI coding tools a GBrain-style answer surface without sending raw private memory into an external synthesizer. The tool should return structured evidence, citations, source coverage, freshness warnings, contradictions, explicit gaps, and privacy metadata so the calling agent can reason from redacted context.

## Scope

This iteration adds deterministic synthesis scaffolding, not a new LLM dependency. The output is intentionally conservative: it can produce a brief evidence-grounded summary from retrieved snippets, but its main value is the structured citation and gap report that an agent can use safely.

## Interfaces

- HTTP MCP tool: `think`
- Stdio MCP tool: `think`
- REST endpoint: `POST /api/think`
- Pure Python engine: `mcp_vector_store.think_tool`

Input:

```json
{
  "question": "What did I decide about the vector store?",
  "top_k": 8,
  "freshness_days": 90,
  "include_gaps": true
}
```

Output:

```json
{
  "question": "What did I decide about the vector store?",
  "answer_brief": "Evidence suggests ...",
  "citations": [
    {
      "doc_id": 42,
      "title": "design-notes.md",
      "excerpt": "Redacted excerpt...",
      "score": 0.82,
      "date": "2026-05-10",
      "source": "file"
    }
  ],
  "coverage": {
    "source_count": 3,
    "dated_source_count": 2,
    "strong_source_count": 2,
    "query_terms_found": ["vector", "store"],
    "query_terms_missing": ["decide"]
  },
  "gaps": ["No source explicitly mentions: decide"],
  "contradictions": [],
  "freshness": {
    "freshness_days": 90,
    "oldest_source_date": "2025-12-01",
    "newest_source_date": "2026-05-10",
    "stale_source_count": 1,
    "undated_source_count": 1,
    "warnings": ["1 source is older than 90 days", "1 source has no date metadata"]
  },
  "privacy": {
    "llm_context": "redacted",
    "pii_session_ids_exposed": false
  }
}
```

## Architecture

`think_tool.py` is a small, dependency-light module that normalizes existing search and enhanced-search results into a stable result model. The HTTP server uses existing `vector_store.enhanced_search()` retrieval, applies the same PII-safe LLM context used by `search_documents` and `enhanced_search`, then passes redacted results into the think engine. The stdio server forwards `think` calls to `/api/think` just like it forwards search calls today.

## Privacy And Security

- Always request retrieval with `context="llm"` for MCP/REST think responses.
- Never include `pii_session_id` in `think` output.
- Never call `deanonymize_text` or any local-only de-anonymization path.
- Emit explicit `privacy` metadata so agent clients can confirm the result is meant for LLM context.

## Error Handling

- Missing or blank question returns a validation error through the existing request/tool error path.
- Empty search results return `answer_brief: null`, empty citations, and a gap explaining that no supporting sources were found.
- Malformed or missing metadata is tolerated; the freshness report marks those sources as undated.

## Testing

Add pure Python unit tests for:

- Empty results produce no answer and an explicit evidence gap.
- Results produce citations without leaking `pii_session_id`.
- Query-term coverage reports found and missing meaningful terms.
- Stale and undated sources produce freshness warnings.
- Conflicting snippets produce contradiction entries for simple positive/negative conflicts.

The release gate remains `npm run verify`, both `npm audit --audit-level=moderate` checks, Python compile, and the new focused Python unit test.
