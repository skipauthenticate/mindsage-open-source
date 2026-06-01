# PII Protection Architecture

This document explains the architectural reasoning behind MindSage's PII (Personally Identifiable Information) protection system, comparing it with alternative approaches and documenting design decisions.

## Overview

MindSage uses a **client-side de-anonymization** architecture where:
- PII is detected and tokenized at search time (not ingestion time)
- Token-to-value mappings exist only in on-device memory
- External LLMs never see original PII values
- Only the on-device frontend can restore original values

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│  ON-DEVICE (Jetson Orin Nano)                                           │
│  ┌──────────────┐  ┌────────────────┐  ┌──────────────────────────────┐ │
│  │   Frontend   │  │  Express API   │  │  Vector Store (Python)       │ │
│  │   (Browser)  │  │  (port 3003)   │  │  (port 8085)                 │ │
│  └──────┬───────┘  └───────┬────────┘  │  ┌────────────────────────┐  │ │
│         │                  │           │  │  Presidio PII Detector │  │ │
│         │                  │           │  │  Session Token Store   │  │ │
│         │                  │           │  └────────────────────────┘  │ │
│         │                  │           └──────────────────────────────┘ │
└─────────┼──────────────────┼────────────────────────────────────────────┘
          │                  │
          │     ┌────────────┼────────────────────────────────────────────┐
          │     │            │            EXTERNAL (CLOUD)                │
          │     │            │    ┌────────────────────────────────────┐  │
          │     │            │    │  External LLM API                  │  │
          │     │            │    │  (Claude, GPT, Groq)               │  │
          │     │            │    │                                    │  │
          │     │            │    │  Only sees: <PII:PERSON:abc>       │  │
          │     │            │    │  NEVER sees: "John Smith"          │  │
          │     │            │    └────────────────────────────────────┘  │
          │     └────────────┼────────────────────────────────────────────┘
          │                  │
          ▼                  ▼
    De-anonymized       Anonymized
    display to user     data to LLM
```

## Data Flow

| Step | Direction | Data | PII Status |
|------|-----------|------|------------|
| 1 | User → Web App → LLM | User query | N/A |
| 2 | LLM (via MCP) → Vector Store | Search call | N/A |
| 3 | Vector Store → LLM | Search results | **Anonymized** (tokens) |
| 4 | LLM → Web App | Response | Contains tokens |
| 5 | Web App → Vector Store | De-anonymize API | Tokens + session_id |
| 6 | Vector Store → Web App | Restored text | **Original PII** |

## Why This Architecture

### Core Principle: Zero PII Leaves the Device

Token-to-value mappings exist **only** in Vector Store memory on the local device:

```python
class TokenSession:
    """Session-scoped token storage with sliding TTL."""
    _tokens: Dict[str, PIIToken]  # In-memory only, never persisted
```

External LLMs see one of two formats (depending on mode):
```
# Token-only mode:
"Based on <PII:PERSON:xYz12AbC>'s email, the meeting is at 3pm"

# LPRAG hybrid mode (default):
"Based on Michael Chen's email, the meeting is at 3pm"
```

Only the on-device frontend can restore:
```
"Based on John Smith's email, the meeting is at 3pm"
```

### Privacy by Architecture, Not Policy

| Server-Side Approach | This Implementation |
|---------------------|---------------------|
| "We promise not to read your PII" | **PII physically cannot leave** |
| Requires trust in operator | **Zero trust required** |
| Policy can change | **Architecture enforces privacy** |

---

## Comparison with Alternative Approaches

### Alternative 1: Server-Side De-anonymization (Cloud Proxy)

```
User → Cloud Proxy → LLM
              ↓
       De-anonymize before
       sending to user
```

**Problems:**

| Issue | Impact |
|-------|--------|
| **PII leaves device** | Token mappings would exist in cloud proxy memory |
| **Trust requirement** | Must trust cloud proxy operator with all PII |
| **Compliance risk** | GDPR/CCPA violations - PII crosses boundaries |
| **Single point of failure** | Cloud proxy compromise = all PII exposed |
| **Latency** | Extra network hop for every response |

### Alternative 2: LLM-Side De-anonymization

```
User → LLM (with de-anonymize tool) → User
```

**Problems:**

| Issue | Impact |
|-------|--------|
| **LLM sees mappings** | Must give LLM access to token→PII mappings |
| **No control** | Can't revoke access once LLM has the mapping |
| **Training risk** | PII could end up in LLM training data |
| **Tool abuse** | LLM could call de-anonymize unnecessarily |

### Alternative 3: Store Tokens in LLM Context

```
System prompt: "PERSON:abc123 = John Smith"
```

**Problems:**

| Issue | Impact |
|-------|--------|
| **Context pollution** | Wastes tokens on mapping table |
| **Prompt injection risk** | Attacker could extract mappings |
| **No isolation** | All PII in every request context |
| **Logging exposure** | LLM provider logs contain mappings |

### Comparison Summary

| Criterion | Server-Side | LLM-Side | Implemented (Edge) |
|-----------|-------------|----------|-------------------|
| **PII exposure** | Cloud sees all | LLM sees all | **None leaves device** |
| **Trust model** | Trust cloud | Trust LLM provider | **Zero trust** |
| **Compliance** | Complex | Complex | **Simple (data stays local)** |
| **Latency** | +1 hop | Same | **Same** |
| **Revocation** | Difficult | Impossible | **Session expires (1hr)** |
| **Audit** | Cloud logs | LLM logs | **Local only** |
| **Offline capable** | No | No | **Yes** |

---

## Why NOT Anonymize Before Embedding

An alternative approach would be to anonymize documents at ingestion time, before generating embeddings. This would be problematic for several reasons:

### Current Flow (Anonymize at Search Time)

```
INGESTION:
  Document "Email from John Smith <john@example.com>"
      → Embed original text → Store with original text

SEARCH:
  Query → Retrieve original → Anonymize → Send to LLM
      → LLM sees: "Email from <PII:PERSON:abc> <PII:EMAIL:xyz>"

DISPLAY:
  De-anonymize → User sees original
```

### Alternative: Anonymize Before Embedding

```
INGESTION:
  Document "Email from John Smith <john@example.com>"
      → Anonymize first → "Email from <PII:PERSON:abc> <PII:EMAIL:xyz>"
      → Embed anonymized text → Store anonymized text

SEARCH:
  Query → Retrieve (already anonymized) → Send to LLM

DISPLAY:
  De-anonymize → User sees original (if mapping still exists)
```

### Problem 1: Semantic Destruction - Embeddings Lose Meaning

Embedding models encode semantic relationships. Anonymizing before embedding destroys this:

```python
# Original text - rich semantic content
"John Smith discussed the merger with Sarah Johnson at Microsoft"
# Embedding captures: person relationships, company context, business action

# Anonymized text
"<PII:PERSON:abc> discussed the merger with <PII:PERSON:def> at <PII:ORG:xyz>"
# Embedding captures: generic tokens, no semantic meaning
```

**Impact on search quality:**

| Query | Original Embedding | Anonymized Embedding |
|-------|-------------------|---------------------|
| "John Smith emails" | High relevance | No match (no "John Smith" in embedding) |
| "Microsoft meetings" | High relevance | No match (no "Microsoft") |
| "people discussing mergers" | Good match | Weak match (generic tokens) |

The embedding model has never seen `<PII:PERSON:abc>` during training - it's meaningless noise to the model.

### Problem 2: Query-Document Mismatch

Users search with real names, but documents contain tokens:

```
User query: "What did John Smith say about the budget?"

Document (anonymized): "<PII:PERSON:abc> mentioned the budget was approved"

Embedding similarity: VERY LOW (different vector spaces)
```

You'd need to also anonymize the query, but:
- You don't know which "John Smith" the user means
- Multiple documents might have different tokens for the same person
- Cross-document entity resolution becomes impossible

### Problem 3: Token Persistence Requirement

Tokens must be **permanent** if embedded:

```python
# Current: Session-scoped, 1-hour TTL
session.tokens["abc123"] = "John Smith"  # Expires in 1 hour

# Pre-embedding: Must be permanent
permanent_store["abc123"] = "John Smith"  # Forever, or data is lost
```

**This creates a permanent PII database** - the exact thing the current architecture avoids:

| Current Design | Pre-Embedding Design |
|----------------|---------------------|
| Tokens ephemeral (1hr) | Tokens permanent |
| No persistent PII store | Permanent PII mapping DB |
| Server restart = clean slate | Must persist mappings forever |
| Breach = 1hr of sessions | Breach = all historical PII |

### Problem 4: Cross-Document Entity Inconsistency

Same person in different documents would get different tokens:

```
Document 1 (ingested Monday):   "John Smith" → <PII:PERSON:abc>
Document 2 (ingested Tuesday):  "John Smith" → <PII:PERSON:xyz>
Document 3 (ingested Wednesday): "John Smith" → <PII:PERSON:def>
```

Consequences:
- Search can't correlate "John Smith" across documents
- Knowledge graph can't link the same person
- LLM sees three "different people"

The current design handles this with **session-scoped deduplication**:

```python
# All "John Smith" instances in ONE search get the SAME token
def get_token_by_value(self, pii_type: str, original_value: str):
    normalized = self._normalize_value(original_value)
    return self._value_to_token.get((pii_type, normalized))
```

### Problem 5: Reranker and Passage Extraction Break

The vector store uses TinyLlama for passage extraction and cross-encoder for reranking:

```python
# Passage extraction prompt
"Extract the most relevant passage about: {query}"
```

If the document is anonymized:
- TinyLlama can't understand context
- Reranker can't score semantic relevance
- Passage extraction becomes random

### When Pre-Anonymization Could Work

The only scenario where it might be acceptable: **if you never need to search by PII**:

```
Use case: "Search my documents for topics, never by person names"

Documents about: cooking recipes, technical tutorials, general knowledge
PII present: author names, email footers (irrelevant to search)
```

In this case, stripping PII before embedding wouldn't hurt search quality because users never search for those entities anyway.

But for MindSage's use case (personal data platform with emails, notes, contacts), searching by person name is a core feature.

### Pre-Embedding vs Search-Time Comparison

| Aspect | Anonymize at Search (Current) | Anonymize Before Embedding |
|--------|------------------------------|---------------------------|
| **Embedding quality** | Full semantic meaning | Meaningless tokens |
| **Search by name** | Works naturally | Impossible |
| **Cross-doc entities** | Session deduplication | Inconsistent tokens |
| **Token lifetime** | Ephemeral (1hr) | Permanent (security risk) |
| **Reranking/extraction** | Full context | Broken |
| **Storage security** | Original on device | Tokens on device + mapping DB |

---

## Implementation Details

### Session Management

- **Sliding TTL**: Sessions expire 1 hour after last activity, not creation time
- **Deduplication**: Same PII value within session gets same token (case-insensitive, whitespace-normalized)
- **LRU Eviction**: When max sessions (100) reached, oldest session is evicted
- **Thread Safety**: All operations use locks for concurrent access

### Token Format

```
<PII:TYPE:TOKEN_ID>

Examples:
  <PII:PERSON:xYz12AbC>        - Person name
  <PII:EMAIL_ADDRESS:pQr34StU> - Email address
  <PII:PHONE_NUMBER:vWx56YzA>  - Phone number
```

### Security Boundaries

1. **De-anonymize API**: Localhost-only (network-isolated)
2. **MCP Tool**: `deanonymize_text` only visible to localhost clients
3. **Session Storage**: In-memory only, never persisted to disk
4. **Token IDs**: Cryptographically random (`secrets.token_urlsafe(8)`)

### Resource Usage

- **Memory**: ~150MB (Presidio + spaCy on CPU)
- **CPU**: NLP processing on CPU, preserves GPU for embedding/LLM
- **Latency**: ~50-100ms per document for PII detection

---

## Trade-offs Accepted

The implementation accepts these trade-offs:

| Trade-off | Mitigation |
|-----------|------------|
| Frontend must track session_id | Simple: capture from response, pass to de-anonymize |
| Sessions are ephemeral | By design: no persistent PII store to breach |
| CPU overhead (~50-100ms) | Negligible compared to LLM API latency |
| 150MB memory for spaCy | Small relative to embedding/LLM models |

---

## LPRAG: Enhanced Privacy with Differential Privacy

LPRAG (Locally Private RAG) is an enhancement to the base token-based anonymization that provides mathematical privacy guarantees while enabling better LLM reasoning.

### The Problem with Token-Only Anonymization

While token-based anonymization protects PII, it has limitations:

```
Input:  "Email from John Smith discussing the budget"
Output: "Email from <PII:PERSON:abc123> discussing the budget"
```

**Issues:**
1. **LLM can't reason semantically** - `<PII:PERSON:abc123>` is meaningless
2. **Awkward responses** - LLM may repeat the token verbatim
3. **Context loss** - "John" vs "Dr. John Smith, CEO" treated identically

### LPRAG Solution: Semantic Perturbation

Instead of opaque tokens, LPRAG perturbs PII to **semantically similar** but **different** values:

```
Input:  "Email from John Smith discussing the budget"
Output: "Email from Michael Chen discussing the budget"  (LPRAG)
```

**Benefits:**
1. **LLM reasons naturally** - "Michael Chen" is a valid name
2. **Natural responses** - "Based on Michael Chen's email..."
3. **Context preserved** - Structure and relationships maintained

### Differential Privacy Guarantees

LPRAG uses Local Differential Privacy (LDP) mechanisms:

| Mechanism | Used For | How It Works |
|-----------|----------|--------------|
| **Exponential** | Names, locations | Sample from vocabulary weighted by similarity |
| **Laplace** | Phone, SSN, numbers | Add calibrated noise to digits |
| **Segment-wise** | Email, addresses | Perturb each segment appropriately |

**Key property**: With probability controlled by ε (epsilon), the perturbed value is semantically similar. Lower ε = stronger privacy (more random).

```
Privacy Budget (ε):
  Critical (SSN):     ε = 0.1  →  Nearly random output
  High (phone):       ε = 0.5  →  Some similarity
  Medium (names):     ε = 1.0  →  Similar names
  Low (dates):        ε = 2.0  →  Close dates
```

### LPRAG Modes

| Mode | Description | Reversible | Use Case |
|------|-------------|------------|----------|
| `token_only` | Original behavior (`<PII:PERSON:abc>`) | Yes | Maximum control |
| `lprag_pure` | Perturbation, no mapping stored | No | Strongest privacy |
| `lprag_hybrid` | Perturbation + bidirectional mapping | Yes | **Default** - Best balance |

### Hybrid Mode: Best of Both Worlds

LPRAG hybrid mode maintains bidirectional mappings for de-anonymization:

```python
# Session stores:
#   original → perturbed (for deduplication)
#   perturbed → original (for de-anonymization)

session._value_to_token[("PERSON", "john smith")] = "token_abc"
session._perturbed_to_token["Michael Chen"] = "token_abc"
```

**De-anonymization flow:**
```
LLM output: "Based on Michael Chen's email..."
                      ↓
Scan session for perturbed values
                      ↓
"Michael Chen" found → restore "John Smith"
                      ↓
User sees: "Based on John Smith's email..."
```

### Fallback Mechanism

LPRAG gracefully falls back to tokens for unsupported cases:

```
"John Smith" → "Michael Chen"    (LPRAG perturbs PERSON)
"ABC-CUSTOM-ID" → "<PII:CUSTOM:xyz>"  (Token fallback)
```

Fallback triggers:
- Entity type not supported by LPRAG modules
- No similar words found in vocabulary
- Perturbation produces invalid output
- gensim/embeddings not available

### Architecture with LPRAG

```
┌─────────────────────────────────────────────────────────────────────────┐
│  PII Detection (Presidio)                                               │
│  "John Smith" detected as PERSON                                        │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  LPRAG Engine (if enabled)                                              │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐         │
│  │  Word Module    │  │  Number Module  │  │  Phrase Module  │         │
│  │  exponential    │  │  Laplace        │  │  segment-wise   │         │
│  │  mechanism      │  │  mechanism      │  │  perturbation   │         │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘         │
│           │                    │                    │                   │
│           │    Can perturb? ───┴─────────── No ─────┼─────────────────┐ │
│           │         │                               │                 │ │
│           │        Yes                              ▼                 │ │
│           │         │                     ┌─────────────────┐         │ │
│           │         ▼                     │ Token Fallback  │         │ │
│           │   "Michael Chen"              │ <PII:TYPE:abc>  │         │ │
│           │                               └────────┬────────┘         │ │
│           │                                        │                   │ │
└───────────┼────────────────────────────────────────┼───────────────────┘ │
            │                                        │                     │
            └──────────────────┬─────────────────────┘                     │
                               │                                           │
                               ▼                                           │
┌─────────────────────────────────────────────────────────────────────────┐
│  Session Storage (bidirectional)                                        │
│  token_abc: original="John Smith", perturbed="Michael Chen"             │
│  "Michael Chen" → token_abc (for de-anonymization)                      │
└─────────────────────────────────────────────────────────────────────────┘
```

### Memory and Performance

| Component | Memory | Latency |
|-----------|--------|---------|
| Presidio + spaCy | ~150MB | ~50ms base |
| GloVe 50-dim (LPRAG) | ~50MB | +10-15ms per perturbation |
| **Total with LPRAG** | **~205MB** | ~65-80ms |

### Why LPRAG is Enabled by Default

1. **Better LLM reasoning** - Semantic values vs opaque tokens
2. **Natural language output** - No awkward token repetition
3. **Automatic fallback** - Unsupported cases still protected
4. **Same security** - PII still never leaves device
5. **Mathematical guarantee** - ε-differential privacy

---

## Conclusion

The implemented architecture is a **privacy-by-design pattern** optimized for edge computing with external LLM integration. Rather than relying on policies or trust, it makes PII leakage **architecturally impossible** - the token mappings physically cannot leave the device.

This is essential for MindSage's use case as a personal data platform where users store sensitive documents (emails, notes, personal files) and want to use powerful cloud LLMs without exposing that data to third parties.

**Key insight**: PII protection is about **external data flows** (to LLMs), not about on-device storage where the user already has physical access to their own data.
