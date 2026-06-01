# MindSage Product Strategy: Personal Data Hub

## Vision

A local-first device that aggregates your entire digital life — photos, texts, emails, documents, AI conversations, social media — and makes it all semantically searchable. Not just storage (a NAS does that), but **intelligent retrieval** across everything you've ever created, received, or interacted with.

The killer use case isn't "find file X." It's:

> "What was that restaurant my wife texted me about the same week I was researching Italian trips?"

— and it pulls together a text message, a Google search history entry, and a Google Photos image. No single platform can answer that today. MindSage can.

## Current State (Honest Assessment)

### What Works
- AI conversation capture (ChatGPT, Claude, Gemini) via browser extension
- Facebook data import (posts, comments, messages, media storage)
- File upload with background indexing to vector store
- Semantic search with passage extraction and reranking
- Knowledge graph visualization (documents, topics, entities)
- PII protection with differential privacy (LPRAG)
- LocalSend file transfer from mobile
- Polished React frontend with search, graph, chat

### What Doesn't Work Yet
- PDF/DOCX text extraction (`extractTextFromFile()` is called but not defined)
- Readwise, GitHub, Todoist connectors (documented, 0% implemented)
- Notion sync (script exists, not wired into sync flow)
- Photo understanding (no CLIP, no scene recognition, no face detection)
- Multi-modal search (text-only embeddings today)
- Cross-source temporal correlation
- Mobile companion app
- Plug-and-play setup experience

### Data Ingestion Coverage: ~15% of Vision

| Data Type | Status | Notes |
|-----------|--------|-------|
| AI conversations | Working | ChatGPT, Claude, Gemini via extension |
| Text files / markdown | Working | Direct upload + indexing |
| Facebook export | Working | Posts, comments, messages, media stored |
| PDF / DOCX | Broken | Text extraction not implemented |
| Photos | Not started | Needs CLIP embeddings, EXIF, face recognition |
| Text messages | Not started | iMessage backup parsing, Android SMS export |
| Email (Gmail/Outlook) | Not started | IMAP/OAuth well-understood |
| Cloud storage (Drive/Dropbox) | Not started | OAuth + incremental sync |
| Browser history | Not started | Chrome history DB or extension capture |
| Calendar events | Not started | CalDAV / Google Calendar API |
| Notes (Apple Notes/Notion) | Notion partial | Apple Notes requires macOS APIs |
| WhatsApp/Signal | Not started | Encrypted backup parsing |
| Social media exports | Partial | Facebook done, Instagram/Twitter not started |
| Health data | Not started | Apple Health XML export |
| Music/podcast history | Not started | Spotify API, Apple Music |

## Why This Can Work

### 1. The Market Exists

Synology sells millions of NAS devices at $300-800. People **do** pay for local storage with smart features. Synology's annual revenue exceeds $1B. The gap: a NAS stores files. MindSage **understands** them.

### 2. The Timing Is Right

- Google routinely kills products (people lose data)
- Social media platforms are unstable (Twitter/X, TikTok bans)
- AI companies train on user data (opt-out is hard)
- EU Digital Markets Act and GDPR push data portability
- "Own your data" is shifting from niche to mainstream

### 3. AI Is the Differentiator

Without AI, this is just another NAS with sync. With AI, this is a personal search engine that correlates your texts, emails, photos, and documents into a unified, queryable knowledge base. The pitch: **"Your personal AI that knows everything about your life, running entirely on your hardware."**

### 4. The Business Model Is Proven

Hardware ($200-400) + optional subscription ($5-10/month for cloud connector updates, premium features). This is the Synology/Plex model. Plex has 30M+ users on a similar "free software + premium features" model.

---

## Phase 1: Prove the Core Loop (Months 1-3)

### Goal

Make semantic search feel **magical** across 3 universal data sources. If searching across email + photos + AI conversations isn't noticeably better than searching each platform individually, nothing else matters.

### Data Sources

Pick 3 that everyone has and that together test cross-source correlation:

#### 1a. Email (Gmail via OAuth)

**Why first:** Everyone has email. Huge data volume. Well-understood APIs. High-value search use case ("find that email from Sarah about the budget").

**Implementation:**
- OAuth2 flow for Gmail (or generic IMAP for any provider)
- Incremental sync using Gmail's `historyId` (only fetch new messages since last sync)
- Parse email headers (from, to, date, subject) into structured metadata
- Extract body text (handle HTML emails via `cheerio` or similar)
- Handle attachments: store as files, index text-extractable ones (PDF, DOCX)
- Store thread structure for conversation context

**Connector architecture:**
```
Gmail OAuth → Fetch messages (batched, incremental)
  → Parse headers + body
  → Extract attachments → store in data/imports/
  → Index to vector store with metadata:
    {source: "gmail", from: "...", to: "...", date: "...", subject: "...", thread_id: "..."}
```

**API scope needed:** `gmail.readonly` (read-only, never sends email)

**Effort:** ~2 weeks for basic Gmail connector. IMAP fallback adds another week.

#### 1b. Photos (Google Photos Export / Local Library)

**Why:** Photos are the most emotionally valuable data people have. "Find that photo from our trip to Italy" is a search that everyone wants.

**Implementation — start with import, add sync later:**

**Phase 1a — Photo import (EXIF + basic classification):**
- Accept photo library imports (drag-and-drop folder, Google Takeout ZIP, Apple Photos export)
- Extract EXIF metadata: date taken, GPS coordinates, camera model
- Reverse-geocode GPS to location names (offline database or simple API)
- Generate text description from metadata: "Photo taken on 2024-03-15 in Florence, Italy"
- Index the text description + metadata to vector store
- Store thumbnail for search result display

**Phase 1b — CLIP embeddings for visual search (stretch goal):**
- Add CLIP (or SigLIP) model for image embeddings
- Enable queries like "sunset on a beach" matching actual photo content
- This requires either GPU (CLIP is ~400MB) or cloud API (OpenAI vision, cheap)
- On hardware-constrained devices, defer to cloud API with user opt-in

**Photo metadata alone is surprisingly powerful.** "Photos from March 2024 in Italy" works with just EXIF data, no image understanding needed. Ship that first.

**Effort:** ~2 weeks for EXIF-based photo import. CLIP integration adds 2-3 weeks.

#### 1c. AI Conversations (Already Working)

Keep the existing browser connector. Polish rough edges:
- Fix content script auto-sync for Claude and Gemini (ChatGPT is solid)
- Publish Companion Extension to Chrome Web Store (plan already written)
- Ensure conversation metadata includes timestamps for temporal correlation

### Search Experience Upgrades

The search must work **across** sources, not just within them. Key capabilities to add:

#### Temporal Correlation

Add a time-based correlation layer. When a user searches, also fetch results from the same time period across other sources:

```
User searches: "Italian restaurant recommendation"
  → Vector search finds: Email from Sarah mentioning "Trattoria Roma" (March 12)
  → Temporal correlation finds:
    - Photo from Florence (March 10-17)
    - ChatGPT conversation about "best restaurants in Tuscany" (March 8)
  → Present as a unified timeline
```

**Implementation:**
- Add `timestamp` as a first-class indexed field on all documents
- After primary search, do a secondary time-window query (e.g., +/- 7 days from top result dates)
- Group results by time clusters in the UI
- New search mode: "timeline view" showing results ordered chronologically across all sources

#### Cross-Source Context Cards

When displaying a search result, show related items from other sources in the same time window:

```
[Email] Sarah → you, March 12
"Check out Trattoria Roma, they have amazing pasta"

  Related:
  [Photo] Florence, Italy — March 14 (3 photos)
  [ChatGPT] "Best restaurants in Tuscany" — March 8
```

This is where the magic happens. No single platform can show this view.

#### Unified Search API

Extend the existing search endpoint to support:
```json
POST /api/search
{
  "query": "Italian restaurant",
  "sources": ["gmail", "photos", "chatgpt"],  // optional filter
  "time_range": { "from": "2024-03-01", "to": "2024-03-31" },  // optional
  "include_temporal_context": true,  // fetch related items from same time period
  "limit": 20
}
```

### Infrastructure Changes

#### Drop Jetson Requirement

Ship as **Docker Compose** that runs on any machine with 8GB+ RAM:

```yaml
# docker-compose.yml
services:
  backend:
    build: ./mindsage
    ports: ["3003:3003"]
    volumes: ["./data:/app/data"]

  vector-store:
    build: ./mindsage/vector-store
    ports: ["8085:8085"]
    volumes: ["./data/vectordb:/app/data/vectordb"]
    environment:
      - EMBEDDING_MODE=api  # Use OpenAI embeddings by default
      - LOCAL_GPU=false      # No GPU required

  frontend:
    build: ./mindsage-frontend
    ports: ["8080:8080"]
```

#### Tiered ML Strategy

Not everyone has a GPU. Support three tiers:

| Tier | Hardware | Embeddings | Extraction | Search Quality |
|------|----------|------------|------------|----------------|
| Cloud-assisted | Any machine, 4GB+ RAM | OpenAI API ($0.0001/1K tokens) | Claude Haiku API | Best (~90%) |
| Local GPU | 8GB+ VRAM | all-mpnet-base-v2 (local) | TinyLlama (local) | Good (~75%) |
| CPU-only | 8GB+ RAM, no GPU | all-MiniLM-L6-v2 (local, slow) | Heuristic fallback | Acceptable (~60%) |

Default to **cloud-assisted** tier. It's cheap ($1-2/month for typical personal use), gives the best results, and requires zero GPU setup. Let privacy purists opt into fully local processing.

#### Fix Text Extraction

This is blocking basic functionality. Implement `extractTextFromFile()`:

```
PDF  → pdf-parse (npm package, works well)
DOCX → mammoth (npm package, extracts text + basic formatting)
HTML → cheerio (already a dependency pattern in the codebase)
CSV  → parse headers + first N rows as text
Images → EXIF text fields (for now), OCR later (Tesseract.js)
```

**Effort:** 1-2 days. This should have been done already.

### Phase 1 Deliverables

By end of month 3:
- [ ] Gmail connector (OAuth, incremental sync, attachment extraction)
- [ ] Photo import (EXIF metadata, folder/ZIP upload, thumbnail generation)
- [ ] Text extraction working for PDF, DOCX, HTML, CSV
- [ ] Temporal correlation in search results
- [ ] Cross-source context cards in search UI
- [ ] Docker Compose deployment (no Jetson required)
- [ ] Cloud-assisted ML tier as default (OpenAI embeddings)
- [ ] Chrome extension published to Chrome Web Store

### Phase 1 Validation

**The test:** Give MindSage to 10 people. Have them import their Gmail, a photo folder, and connect their ChatGPT. After a week of use, ask:

1. Did you search for something in MindSage instead of searching Gmail/Photos/ChatGPT directly?
2. Did MindSage find something you couldn't easily find on the original platform?
3. Would you pay $10/month for this?

If the answer to #2 is consistently "yes," proceed to Phase 2. If not, the core search experience needs more work before adding more connectors.

---

## Phase 2: Expand the Data Universe (Months 4-8)

### Goal

Go from 3 data sources to 10+. Each new source makes the existing ones more valuable (network effect of personal data).

### Connector Priority (ordered by reach x effort)

#### Tier 1 — Add Next (Months 4-5)

**Browser History & Bookmarks**
- Chrome history is a SQLite database (`~/.config/google-chrome/Default/History`)
- Alternatively, capture via the existing Chrome extension (add `history` permission)
- Extremely high value: "what was that website I was looking at last week?"
- **Effort:** 1 week

**Google Calendar / CalDAV**
- OAuth for Google Calendar, CalDAV for Apple/others
- Events become searchable: "when was my dentist appointment?"
- Critical for temporal correlation (events anchor time periods)
- **Effort:** 1-2 weeks

**Cloud Storage Sync (Google Drive)**
- OAuth + Drive API for file listing and download
- Incremental sync (use `changes` API)
- Download + index text-extractable files
- Store file metadata for non-extractable files (video, audio — index by filename + folder structure)
- **Effort:** 2-3 weeks

**Notes (Notion API)**
- Notion connector script already exists (~500 lines), just needs sync flow integration
- Wire `export-notion.ts` into `runCustomScript()`
- **Effort:** 3-5 days (mostly integration work)

#### Tier 2 — Platform Exports (Months 5-7)

These follow the same pattern as the existing Facebook import: user downloads their data export ZIP, uploads to MindSage.

**Instagram Data Export**
- Download from Instagram settings → "Download Your Information"
- Structure: `media/`, `messages/`, `likes/`, `comments/`, `profile/`
- Parse JSON files, store media with EXIF, index text content
- **Effort:** 1-2 weeks (similar to Facebook connector)

**Twitter/X Data Export**
- Download from Twitter settings → "Download an archive of your data"
- Structure: `tweets.js`, `direct-messages.js`, `like.js`, `following.js`
- Parse JS files (they're actually JSON with a variable assignment prefix)
- Index tweets, DMs, likes as documents
- **Effort:** 1 week

**WhatsApp Export**
- WhatsApp → Settings → Chats → Export Chat (per-chat, text + media)
- Parse the `.txt` format: `[MM/DD/YY, HH:MM:SS] Sender: Message`
- Also support WhatsApp's Google Drive/iCloud backup format for bulk import
- **Effort:** 1-2 weeks

**Apple Health Export**
- Settings → Health → Export All Health Data → `export.xml`
- Parse XML for workouts, steps, heart rate, sleep
- Index as structured documents with temporal metadata
- "When did I last go running?" becomes searchable
- **Effort:** 1 week

#### Tier 3 — Live Sync Connectors (Months 6-8)

These require ongoing sync, not one-time import:

**Text Messages (iMessage)**
- macOS: iMessage stores in `~/Library/Messages/chat.db` (SQLite)
- Read-only access to the database, incremental sync by `ROWID`
- Handles text, attachments (images stored separately)
- **Limitation:** macOS only. Android SMS requires a companion app or ADB backup parsing
- **Effort:** 2 weeks (macOS), 3-4 weeks (Android companion app)

**Spotify/Apple Music Listening History**
- Spotify API: OAuth + `recently-played` endpoint (limited to last 50 tracks)
- For full history: Spotify data export (Account → Privacy → Download your data)
- Index as temporal events: "what was I listening to in March?"
- **Effort:** 1 week

**Contacts**
- CardDAV sync or Google People API
- Enrich other data sources (match email senders to names, match phone numbers in texts)
- This makes search results more useful: "emails from Sarah" instead of "emails from sarah.jones@company.com"
- **Effort:** 1 week

### Multi-Modal Search

#### Photo Understanding (Phase 2 focus)

**CLIP Integration:**
- Add OpenAI CLIP (ViT-B/32) or SigLIP for image embeddings
- Store image embeddings alongside text embeddings in vector store
- Enable visual search: "sunset on a beach" → matches photos by visual content
- **Memory:** ~400MB for CLIP on GPU, or use OpenAI vision API ($0.01/image)

**OCR for Screenshots:**
- Tesseract.js for on-device OCR (no GPU needed)
- Automatically OCR screenshots and index the text
- High value: people screenshot important things constantly
- **Effort:** 1 week

**Face Recognition (stretch):**
- face-api.js (runs in Node.js, no GPU required)
- Detect and cluster faces, let users name them
- "Photos of Sarah" becomes a real query
- **Effort:** 3-4 weeks
- **Privacy note:** Face embeddings stored locally only, never transmitted

#### Audio Transcription

**Whisper Integration:**
- For voice memos, podcast clips, video audio tracks
- Use OpenAI Whisper API ($0.006/minute) or local whisper.cpp
- Transcriptions become searchable text documents
- **Effort:** 1-2 weeks

### Phase 2 Deliverables

By end of month 8:
- [ ] 10+ data sources working (email, photos, AI chats, browser history, calendar, cloud storage, notes, social media exports, texts, contacts)
- [ ] CLIP-based image search (cloud API or local GPU)
- [ ] OCR for screenshots
- [ ] Audio transcription for voice memos
- [ ] Connector management UI (add/remove/configure sources, view sync status)
- [ ] Mobile companion app v1 (photo sync + notification access for text capture on Android)
- [ ] Automated incremental sync for live connectors (email, calendar, cloud storage)

---

## Phase 3: The Personal AI (Months 9-14)

### Goal

With enough data ingested, MindSage becomes your **personal AI assistant** that can answer questions about your life.

### Intelligent Query Understanding

Move beyond simple semantic search to **agentic retrieval:**

```
User: "What did I do for my birthday last year?"

MindSage agent:
  1. Determine user's birthday (from calendar events or profile)
  2. Search photos from that date range (+/- 3 days)
  3. Search text messages mentioning "birthday" or "happy bday"
  4. Search emails for restaurant reservations, party invites
  5. Search calendar for events that week
  6. Compile into a narrative summary with photos
```

This requires:
- An LLM that can decompose queries into search plans
- Tool-use / function-calling to execute multiple searches
- A synthesis step that combines results into a coherent answer
- The existing chat infrastructure (OpenAI/Anthropic/Groq) handles this

### Proactive Insights

Instead of only responding to queries, surface interesting connections:

- **"On this day"** — show what you were doing 1 year ago (like Facebook Memories, but across all sources)
- **Weekly digest** — "This week you had 3 meetings about Project X, exchanged 12 emails with the design team, and saved 2 articles about React performance"
- **Relationship context** — Before a meeting with someone, show recent emails, shared documents, and last conversation topics
- **Travel summaries** — Auto-detect trips from photos/calendar/location and create trip journals

### Hardware Appliance (If Validated)

If Phase 1-2 validation is positive, design the hardware product:

**Specifications:**
- Mini-PC form factor (Intel N100 or AMD Ryzen embedded, fanless)
- 16-32GB RAM (enough for local ML without GPU memory tricks)
- 2x M.2 NVMe slots (OS + data, expandable)
- USB-C for external storage expansion
- WiFi 6 + Ethernet
- Pre-installed MindSage OS (minimal Linux + Docker)
- Setup via mobile app (QR code scan, account linking wizard)

**Price target:** $299 (8GB/256GB) to $499 (16GB/1TB)

**Comparison to Synology:**
- Synology DS224+ (2-bay NAS): $300 + drives
- MindSage appliance: $299-499, all-inclusive
- Synology: stores files, basic search
- MindSage: stores files, understands them, AI-powered retrieval

### Phase 3 Deliverables

By end of month 14:
- [ ] Agentic query decomposition (multi-step search plans)
- [ ] Proactive insights ("On this day," weekly digests, relationship context)
- [ ] Hardware appliance prototype (if demand validated)
- [ ] Mobile app v2 (full search + insights + photo sync + text capture)
- [ ] Setup wizard (QR code → account linking → initial sync)
- [ ] Auto-backup from mobile (photos, texts, contacts sync continuously)

---

## Business Model

### Pricing

**Software (Docker, self-hosted):**
- Free tier: 3 data sources, 10GB indexed, local ML only
- Pro ($10/month): Unlimited sources, unlimited storage, cloud ML tier, priority support
- Family ($20/month): Up to 5 users, shared device

**Hardware appliance (if built):**
- MindSage Home: $299 (8GB RAM, 256GB NVMe)
- MindSage Home+: $499 (16GB RAM, 1TB NVMe)
- Includes 1 year of Pro subscription
- Renewals at $60/year (maintenance updates, cloud connector updates)

### Revenue Targets

| Phase | Timeline | Target |
|-------|----------|--------|
| Phase 1 | Months 1-3 | 100 beta users, 10 paying ($10/mo) |
| Phase 2 | Months 4-8 | 1,000 users, 200 paying ($2K/mo) |
| Phase 3 | Months 9-14 | 5,000 users, 1,000 paying ($10K/mo) |
| Hardware launch | Month 15+ | First batch of 500 devices ($150K revenue) |

These are modest targets. The goal isn't hockey-stick growth — it's validating that people use it daily and willingly pay.

---

## Technical Decisions

### Why Docker-First, Not Jetson-First

| Factor | Jetson Orin Nano | Docker on any hardware |
|--------|------------------|----------------------|
| Addressable users | ~10K (Jetson owners) | Millions (any PC/Mac/Linux) |
| RAM | 7.4GB shared (GPU+CPU) | 8-32GB typical |
| Storage expansion | USB only, no NVMe bays | Depends on host hardware |
| Setup complexity | Flash JetPack, configure CUDA | `docker compose up` |
| GPU access | Yes (NVIDIA only) | Optional (NVIDIA, AMD, Apple Silicon) |
| Cloud ML fallback | Possible but defeats purpose | Natural default |

**Decision:** Ship software-first. Docker Compose on any machine. Keep the Jetson config as a supported target but not the primary one. Design the custom appliance later if demand justifies it.

### Why Cloud-Assisted ML by Default

Local-only ML on constrained hardware produces 60-75% search quality. Cloud-assisted (OpenAI embeddings + Claude Haiku extraction) produces ~90% quality at negligible cost (~$1-2/month for personal use).

Most users care about **results**, not where the computation happens. Default to the best experience. Let privacy-conscious users opt into fully local processing.

**Cost estimate for cloud-assisted tier:**
- Embedding generation: ~$0.10/month (10K documents, ada-002 at $0.0001/1K tokens)
- Extraction (topics, entities): ~$1.00/month (Claude Haiku at $0.25/M input tokens)
- Image understanding: ~$0.50/month (100 photos/month, GPT-4o mini vision)
- **Total: ~$1.60/month per user** (well within a $10/month subscription)

### Why Not Open Source (Yet)

Open sourcing could accelerate adoption and build trust, but:
- The codebase has incomplete features that would frustrate contributors
- No tests, no CI/CD — contributions would break things
- Premature open sourcing diffuses focus

**Plan:** Open source **after** Phase 1 validation. Once the core loop works and there are paying users, open source the core engine. Keep the hardware firmware, mobile app, and cloud connectors as the commercial offering.

---

## Immediate Next Steps (This Week)

1. **Fix text extraction** — implement `extractTextFromFile()` for PDF, DOCX, HTML, CSV. This is a 1-2 day fix that unblocks basic file indexing.

2. **Add Docker Compose for full stack** — make `docker compose up` work on any machine with 8GB RAM. Add OpenAI API key as the only required config.

3. **Start Gmail connector** — OAuth2 flow, incremental message sync, body text extraction. This is the highest-value new data source.

4. **Remove documented-but-unimplemented connectors** — take Readwise, GitHub, Todoist out of documentation until they're actually built. Honest docs build trust.

5. **Publish Chrome extension** — execute the existing Chrome Web Store plan. This is the easiest distribution win.

---

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Core search isn't "magical" enough | High | Fatal | Phase 1 validation gate — don't proceed if search doesn't wow users |
| Platform API changes break connectors | Medium | High | Build on data exports (user-controlled) first, live APIs second |
| Cloud ML dependency contradicts privacy pitch | Medium | Medium | Always offer local-only tier; cloud is opt-in |
| Single developer bandwidth | High | High | Focus ruthlessly; 3 sources done well > 10 sources done poorly |
| User data loss (corruption, bugs) | Low | Fatal | Automated backups of vector DB; import is idempotent (can re-run) |
| Chrome extension rejected by CWS | Low | Medium | Permission narrowing plan already written; similar extensions exist |
| Hardware appliance logistics | Medium | Medium | Defer until software validated; partner with ODM for manufacturing |

---

## Success Criteria

**Phase 1 is successful if:**
- 10+ people use MindSage weekly for 30+ days
- At least 3 people report finding something via MindSage they couldn't easily find on the original platform
- At least 5 people say they'd pay $10/month

**Phase 2 is successful if:**
- 200+ paying subscribers
- Average user has 5+ data sources connected
- Monthly churn < 5%

**Phase 3 is successful if:**
- Users describe MindSage as "indispensable" or "my second brain"
- 1,000+ paying subscribers
- Clear demand signal for hardware appliance (500+ pre-orders)
