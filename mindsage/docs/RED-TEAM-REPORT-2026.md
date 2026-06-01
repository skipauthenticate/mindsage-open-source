# Red Team Report: Post-Hardening Penetration Test

**Date**: 2026-03-03
**Role**: Principal Security QA Engineer (adversarial/red team)
**Objective**: Break every fix from the initial audit, find all remaining gaps
**Classification**: CRITICAL — Multiple complete bypasses found

---

## Executive Summary

The initial audit (SECURITY-AUDIT-2026.md) fixed 7 vulnerabilities in the vector store's Python layer. However, **the Express proxy layer at port 3003 completely bypasses every localhost restriction** because it is unauthenticated and makes requests to the vector store from 127.0.0.1. An attacker with network access to port 3003 can de-anonymize all PII, wipe all data, steal API keys, and abuse the victim's LLM quota — all without authentication.

Additionally, **4 MCP tools return raw PII without anonymization**, the `anonymize_with_consent()` method still fails open, and there's a path traversal in the Express connector exports endpoint.

**Bottom line**: The vector store Python layer is now well-hardened, but the Express layer is a wide-open back door that renders most of the hardening moot.

---

## Complete Attack Chain: Full PII Exfiltration

```
Attacker (remote)
    │
    │ POST /api/pii/deanonymize
    │ {"text": "<PII:PERSON:abc123>", "session_id": "xyz..."}
    │ (NO authentication required)
    ▼
Express (port 3003)
    │
    │ client.deanonymize(text, session_id)
    │ (Express → Vector Store is localhost-to-localhost)
    ▼
Vector Store (port 8085)
    │ _get_client_ip_secure() → "127.0.0.1"
    │ _is_localhost("127.0.0.1") → TRUE ✓
    │ deanonymize proceeds
    ▼
Returns real PII to Express → Returns to Attacker
```

**Result**: Localhost enforcement is completely bypassed.

---

## Red Team Findings

### RT-01: Express Proxy Bypasses ALL Localhost Restrictions [CRITICAL]

**Severity**: CRITICAL (complete bypass of V-01 fix)

Express server at port 3003 proxies these PII-sensitive endpoints to the vector store at port 8085 **without any authentication**:

| Express Endpoint | Vector Store Endpoint | Impact |
|---|---|---|
| `POST /api/pii/deanonymize` | `POST /api/pii/deanonymize` | Reverse all PII anonymization |
| `GET /api/pii/session/:id` | `GET /api/pii/session/:id` | Enumerate PII sessions |
| `DELETE /api/pii/session/:id` | `DELETE /api/pii/session/:id` | Destroy PII sessions |
| `POST /api/pii/anonymize`* | `POST /api/pii/anonymize` | Create sessions with known IDs |
| `GET /api/pii/status` | `GET /api/pii/status` | Recon: session counts, config |

Since Express connects to the vector store from localhost (127.0.0.1), the vector store's `_get_client_ip_secure()` sees a legitimate localhost connection and passes the check.

**File**: `server/index.ts:3224-3246`

---

### RT-02: 4 MCP Tools Return Raw PII Without Anonymization [CRITICAL]

**Severity**: CRITICAL (complete PII bypass without needing de-anonymize)

These MCP tools return document text directly to external LLMs with **zero PII anonymization**:

| Tool | File:Line | Returns |
|---|---|---|
| `list_documents` | `mcp_server_http.py:877` | `doc.text` (full raw text) |
| `get_document` | `mcp_server_http.py:911` | `doc.text` (full raw text) |
| `search_with_topic` | `mcp_server_http.py:1461` | `r.text` (full raw text) |
| `get_documents_by_topic` | `mcp_server_http.py:1497` | `doc.text[:200]` (truncated but raw) |

**Attack**: An LLM (or attacker via prompt injection) can simply call `get_document(doc_id=1)` to get raw PII instead of using the anonymized search tools.

---

### RT-03: `anonymize_with_consent()` Still Fails Open [HIGH]

**Severity**: HIGH

**File**: `pii_protection.py:1085-1092`

The `anonymize_with_consent()` method was NOT updated with the fail-closed fix. When Presidio is unavailable, it returns the original text:

```python
if not self._ensure_initialized():
    return AnonymizationResult(
        anonymized_text=text,  # ❌ RAW PII returned
        ...
    )
```

Additionally, the main `anonymize()` method has the same fail-open behavior in its `_analyzer.analyze()` exception handler at line 884-893.

---

### RT-04: Path Traversal in Connector Exports [HIGH]

**Severity**: HIGH

**File**: `server/index.ts:1446-1453`

```typescript
app.get('/api/connectors/:id/exports/:filename', (req, res) => {
  const filePath = path.join(EXPORTS_DIR, req.params.id, req.params.filename);
  // ❌ No path.resolve() check — path.join doesn't prevent traversal
```

**Attack**:
```
GET /api/connectors/x/exports/../../llm-config.json
```

Returns contents of `data/llm-config.json` containing all plaintext API keys.

---

### RT-05: `/api/data/clear-all` Deletes Everything Without Auth [CRITICAL]

**Severity**: CRITICAL

**File**: `server/index.ts:2069-2111`

A single unauthenticated POST call wipes:
- All vector store documents
- All uploaded files
- All import files

```bash
curl -X POST http://jetson-ip:3003/api/data/clear-all
```

---

### RT-06: `PUT /api/chat/config` Accepts API Keys Without Auth [CRITICAL]

**Severity**: CRITICAL (API key theft AND injection)

**File**: `server/index.ts:3519-3532`

An attacker can:
1. **Read config**: `GET /api/chat/config` — reveals which providers are configured
2. **Overwrite keys**: `PUT /api/chat/config` with attacker-controlled API keys
3. **Intercept all chat**: After key injection, all user queries go through attacker's API account

```bash
# Inject attacker's key — all future chats routed through attacker
curl -X PUT http://jetson-ip:3003/api/chat/config \
  -H "Content-Type: application/json" \
  -d '{"anthropicApiKey":"ATTACKER_KEY_PLACEHOLDER"}'
```

---

### RT-07: Express CORS Still Wildcard [HIGH]

**Severity**: HIGH

**File**: `server/index.ts:41`

```typescript
app.use(cors());  // Default: allow ALL origins
```

The CORS fix was only applied to the Python vector store, not the Express server. A malicious website can make cross-origin requests to all Express endpoints.

---

### RT-08: Browser Connector Conversations Exposed [HIGH]

**Severity**: HIGH

**File**: `server/index.ts` — browser connector endpoints

Without authentication, an attacker can:
```bash
# List all captured ChatGPT conversations
curl http://jetson-ip:3003/api/browser-connector/conversations

# Read full conversation with messages
curl http://jetson-ip:3003/api/browser-connector/conversations/conv-123
```

These conversations contain the user's actual ChatGPT chat history — highly sensitive.

---

### RT-09: VNC Password Hardcoded as "mindsage" [MEDIUM]

**File**: `server/browser-connector/manager.ts:179`

Anyone on the network can connect to VNC at port 6080 with password `mindsage` and see/control the browser window, including any logged-in sessions.

---

## Remediation Plan

### Phase 1: IMMEDIATE — IMPLEMENTED

All Phase 1 fixes have been implemented and committed.

#### 1A. Express authentication middleware [IMPLEMENTED]

**Blocks**: RT-01, RT-04, RT-05, RT-06, RT-07, RT-08

**Implementation** (`server/index.ts`):
- Bearer token generated on first startup, stored in `data/.api-token` (256-bit, `crypto.randomBytes(32)`)
- All endpoints require authentication except `/health` and `/api/health`
- Localhost requests pass through without token (on-device frontend/services)
- Remote requests require `Authorization: Bearer <token>` header or `?token=` query param
- Timing-safe comparison (`crypto.timingSafeEqual`) prevents timing attacks
- Direct socket IP used — X-Forwarded-For headers are never trusted
- Localhost-only `/api/auth/token` endpoint for frontend bootstrapping

**Memory impact**: Negligible (<1KB)

#### 1B. PII anonymization on ALL MCP tools [IMPLEMENTED]

**Blocks**: RT-02

Applied `pii_protector.anonymize_search_results()` to all 4 tools that previously returned raw text:
- `_list_documents()` (`mcp_server_http.py`) — now anonymizes `doc.text`
- `_get_document()` (`mcp_server_http.py`) — now anonymizes `doc.text`
- `_search_with_topic()` (`mcp_server_http.py`) — now anonymizes `r.text`
- `_get_documents_by_topic()` (`mcp_server_http.py`) — now anonymizes `doc.text`

#### 1C. `anonymize_with_consent()` fail-closed [IMPLEMENTED]

**Blocks**: RT-03

Applied fail-closed pattern to both:
- Presidio unavailable check (was returning raw text)
- `_analyzer.analyze()` exception handler (was returning raw text)

Both now redact content unless `PII_FAIL_OPEN=true` is explicitly set.

#### 1D. Express connector exports path traversal [IMPLEMENTED]

**Blocks**: RT-04

Added `path.resolve()` + `startsWith()` check to `/api/connectors/:id/exports/:filename`.
Resolved path must remain within `EXPORTS_DIR`.

#### 1E. Express CORS restriction [IMPLEMENTED]

**Blocks**: RT-07

Replaced `app.use(cors())` with origin validation function:
- Allows localhost, 127.0.0.1, and RFC 1918 private networks (192.168.x.x, 10.x.x.x, 172.16-31.x.x)
- All other origins are rejected
- `credentials: true` enabled for cookie/header passthrough

#### 1F. `anonymize()` analyzer exception handler fail-closed [IMPLEMENTED]

**Blocks**: RT-03 (additional fix)

The `_analyzer.analyze()` exception handler in the main `anonymize()` method was also failing open. Now redacts content on analysis failure unless `PII_FAIL_OPEN=true`.

### Phase 2: HIGH PRIORITY (1-2 weeks)

- Rate limiting on Express (blocks DoS, API key abuse)
- VNC password randomization per session
- Restrict `/api/data/clear-all` to require confirmation token
- Add audit logging to all sensitive operations
- Restrict Express `PUT /api/chat/config` to localhost only
- Encrypt API keys at rest in `llm-config.json`

### Phase 3: HARDENING (2-4 weeks)

- TLS between Express and Vector Store
- Input size limits on all endpoints (reject >10MB bodies)
- File type validation on uploads
- Prompt injection detection in RAG context
- Remove `deanonymize_text` from MCP tool listing entirely (per initial audit recommendation)
