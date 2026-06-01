# Competitive Analysis: GBrain, OpenBrain, And MindSage

Observed via GitHub on 2026-06-01 and refreshed after the first public MindSage release:

- GBrain: `https://github.com/garrytan/gbrain`
- OpenBrain structured memory: `https://github.com/rinfa0108/openbrain`
- Open Brain self-hosted memory: `https://github.com/srnichols/OpenBrain`
- Local OpenBrain: `https://github.com/Sneezembop/openbrain`

## What GBrain Gets Right

GBrain is strongest as an agent-native brain layer. Its advantages are:

- A polished CLI with capture, import, search, synthesis, serve, schema, eval, and maintenance commands.
- Clear agent installation via `INSTALL_FOR_AGENTS.md`, `AGENTS.md`, `llms.txt`, and per-client MCP guides.
- Local stdio MCP and remote HTTP/OAuth MCP paths that cover Claude Code, Cursor, Windsurf, ChatGPT, Claude Desktop, and Perplexity.
- A `think` layer that returns cited synthesis, freshness warnings, contradictions, explicit gaps, and maintenance guidance instead of raw search results.
- Hybrid retrieval that combines vector search, BM25, reciprocal-rank fusion, source-tier boosts, reranking, graph signals, evidence tags, and named-page safety hints.
- A self-wiring typed knowledge graph based on wikilinks/typed links, zero-LLM entity/edge extraction, schema packs, and auto-maintenance jobs.
- A strong operator-maintenance surface: onboard recommendations, explicit apply policies, recurring sync, and nightly dream-cycle maintenance.
- A strong quality culture: evals, privacy checks, migration checks, search diagnostics, schema docs, skill optimization, and many targeted scripts.
- Current public traction is substantial: the GitHub page shows roughly 20k stars, 2.9k forks, 282 commits, and README claims of 146k+ pages in Garry Tan's production brain.

## What OpenBrain Gets Right

The most relevant OpenBrain repos focus on portable memory infrastructure:

- Typed memory objects such as claims, decisions, tasks, artifacts, entities, relations, and thought summaries.
- Workspaces as isolation boundaries for ownership, policy, and role-based access.
- Append-only event/audit trails for object history and actor activity.
- Lifecycle states such as scratch, candidate, accepted, and deprecated.
- Retention policy, conflict metadata, idempotency, and deterministic semantic search.
- Simple MCP and mirrored HTTP surfaces that make the memory layer usable from many AI clients and SDKs.
- Explainable policy denials via reason codes and policy rule IDs.
- Lightweight local variants based on SQLite/sqlite-vec or Postgres/pgvector.

## MindSage Advantages

MindSage already has a differentiated wedge:

- Local-first deployment aimed at personal data, not just markdown notes.
- Multimodal ingestion: files, images, audio, LocalSend, AI chat capture, and browser connector flows.
- PII protection is a core system, including text anonymization, LPRAG perturbation, image redaction, audio redaction, consent sessions, and server-side de-anonymization.
- A full React UI for search, chat, consent, document viewing, media review, and knowledge graph exploration.
- Jetson/resource-aware operation for constrained local hardware.
- Connector foundations for Readwise, Notion, Facebook exports, webhooks, AI chats, and custom imports.

## What To Port Next

Priority order:

1. Shipped: agent-ready distribution with a single repo, license, security policy, contributing guide, `AGENTS.md`, `INSTALL_FOR_AGENTS.md`, `llms.txt`, CI, dependency audits, local readiness checks, and a tested setup generator for Claude Code, Claude Desktop, Codex, Cursor, Gemini CLI, VS Code, Windsurf, Zed, Continue, Trae, and generic MCP JSON clients.
2. Shipped first agent schema slice: `npm run agent:schema -- --json` prints a versioned machine-readable contract for MCP tools, REST endpoints, CLI commands, typed-memory fields, and safety defaults with unit and benchmark coverage.
3. Shipped schema-pack slice: `npm run agent:pack -- --json` exposes a MindSage personal-data taxonomy, `--classify <path>` maps paths to intake categories and typed-memory defaults, and `--detect <path> --json` summarizes corpus-level schema candidates without echoing filenames, absolute paths, or document text.
4. Shipped first agent health slice: `npm run agent:health -- --json` scores freshness, undated sources, duplicate groups, safe entity consolidation, and replacement candidates as a 0-100 agent gate with unit and benchmark coverage.
5. Shipped first shell-native reasoning slice: `npm run agent:think` posts questions to local/remote `/api/think`, returns compact cited answers without echoing private questions or bearer tokens, and has unit plus benchmark coverage.
6. Shipped first shell-native import slice: `npm run agent:import -- ./notes` recursively imports local text corpora through `/api/documents/batch` with duplicate skipping, metadata, token-safe `--dry-run`, bearer auth, unit tests, and benchmark coverage.
7. Shipped first shell-native search slice: `npm run agent:search -- "remote MCP auth"` posts to local/remote `/api/search/enhanced`, returns ranked passage evidence with LLM-safe metadata defaults, bearer auth, unit tests, and benchmark coverage.
8. Shipped first capture CLI slice: `npm run agent:capture` posts documents or typed memory to local/remote REST endpoints with bearer auth, token-safe `--dry-run`, PII-session metadata stripping, unit tests, and agent-feature benchmark coverage.
9. Shipped: a MindSage `think` tool that returns cited evidence, a cited-answer graph, a PII-safe entity graph, source coverage, stale-source warnings, contradictions, explicit gaps, and citation-maintenance actions while preserving PII-safe MCP output.
10. Shipped: typed memory records for decisions, claims, tasks, entities, relations, artifacts, and summaries without losing existing document search.
11. Shipped first governance slice: workspace scopes, lifecycle states, retention TTLs, value hashes, version numbers, and audit timelines through MCP, REST, and the Python client.
12. Shipped first graph-assisted typed-memory slice: `memory_graph` links typed memories, declared relations, and source documents through MCP, REST, stdio, and Python client surfaces.
13. Shipped first workspace/actor governance slice: `memory_workspace_info` and `memory_actor_activity` expose OpenBrain-style workspace summaries and append-only actor activity through MCP, REST, stdio, the Python client, evals, and benchmarks without raw memory content.
14. Shipped first cited-answer graph slice: `think` now links answer, citation, concept, and contradiction nodes so cited responses can feed graph exploration and agent context planning.
15. Shipped first replayable eval slice: deterministic agent-memory evals cover cited `think`, cited-answer graphs, safe entity graphs, citation-maintenance actions, typed-memory governance, workspace summaries, actor activity, graph traversal, audit timelines, and PII-session safety.
16. Shipped authenticated remote MCP slice: HTTP/SSE public mode requires bearer tokens, the stdio bridge forwards tokens, and docs cover private-tunnel/HTTPS deployment.
17. Shipped first real-corpus eval slice: replayable fixture-corpus evals cover named-thing lookup, cross-source retrieval, and PII-safe citations over the tracked synthetic personal-data corpus.
18. Shipped first safe entity graph slice: `think` now links cited evidence to organization, location, technology, activity, date, and safe named-entity nodes while redacting person entities and high-risk identifiers.
19. Shipped first maintenance loop slice: `think` now emits actionable refresh/date/re-query/contradiction-repair actions and a maintenance graph for stale, undated, weak, or conflicted citations.
20. Shipped first background maintenance snapshot: `npm run maintenance:snapshot` scans document sets for stale sources, undated records, duplicate bodies, safe entity label variants, and fresher replacement candidates with PII-safe output.
21. Shipped first maintenance planning slice: `npm run maintenance:plan -- --json` turns snapshot findings into recurring freshness scans plus review-required refresh/date/dedupe/entity/connector-sync jobs without raw document text, PII session IDs, or person entities.
22. Shipped first maintenance apply slice: `npm run maintenance:apply -- --json` turns maintenance plans into dry-run review batches with read-only jobs, pending write requests, optional approval marking, and no raw document text, filenames, paths, PII session IDs, or person entities in agent-facing output.
23. Shipped first maintenance ledger slice: `npm run maintenance:apply -- --ledger-path <path>` appends redacted audit events for review/apply batches, and `--ledger-report <path>` summarizes that append-only history without raw document text, filenames, paths, PII session IDs, or person entities.
24. Remaining maintenance loop: automatic connector refresh execution, cross-connector deduplication writes, extracted-entity consolidation writes, and recurring source freshness jobs wired to persistent storage.

## Positioning

GBrain is strongest for agent-operated markdown/company memory. OpenBrain is strongest for typed, governed memory infrastructure. MindSage should become the local-first personal intelligence layer: broader data capture, stronger privacy controls, richer media support, and agent integration that works with any coding tool.

The near-term path is not to copy every GBrain surface. The winning path is to combine:

- GBrain-grade agent onboarding and synthesis.
- OpenBrain-grade typed memory, lifecycle, and auditability.
- MindSage-grade local multimodal ingestion and PII protection.
