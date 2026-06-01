# MindSage Consent Feature Design

## Overview

This document describes a consent management system that gives users granular control over what personal data is shared with external LLMs during chat sessions.

**User Goals**:
- "I want Claude to see my health data but not my finances"
- "Only show documents from the last 6 months"
- "Hide my wife's information but show mine"
- "Don't include that embarrassing email I sent last week"

## Problem Statement

Currently, MindSage's PII protection is all-or-nothing:
- All search results are anonymized uniformly
- Users cannot selectively expose certain data types
- No way to say "show my name but hide my SSN"
- No way to say "include health documents but exclude financial ones"
- No way to exclude specific documents or time ranges
- No way to protect specific people's data differently

## Design Goals

1. **Five Dimensions of Consent**:
   - **Data Categories**: Which topics/categories of documents to include
   - **PII Types**: Which types of PII to anonymize vs pass through
   - **Per-Document**: Block/allow specific documents by ID
   - **Time-Based**: Temporal filters ("last 6 months", "before 2024")
   - **Entity-Specific**: Protect specific people's data ("hide my wife's info")

2. **Session-Scoped**: Consent applies per conversation, can change anytime

3. **Sensible Defaults**: Safe defaults with easy customization

4. **Natural Expression**: Support both UI toggles and natural language

5. **Privacy-First**: Default to maximum protection, require explicit consent to reduce

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           CONSENT MANAGEMENT SYSTEM                              │
│                                                                                  │
│  ┌───────────────────┐                                                          │
│  │  User Consent     │                                                          │
│  │  Preferences      │                                                          │
│  │  (persistent)     │                                                          │
│  └─────────┬─────────┘                                                          │
│            │                                                                     │
│            ▼                                                                     │
│  ┌───────────────────────────────────────────────────────────────────────────┐  │
│  │               Unified Session (consent + PII mappings)                     │  │
│  │                       session_id: "sess_abc123..."                         │  │
│  │                                                                            │  │
│  │  ┌─────────────────────────────────────────────────────────────────────┐  │  │
│  │  │                      CONSENT RULES                                   │  │  │
│  │  │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐   │  │  │
│  │  │  │  Category   │ │  Document   │ │  Time-Based │ │   Entity    │   │  │  │
│  │  │  │   Filter    │ │   Filter    │ │   Filter    │ │   Filter    │   │  │  │
│  │  │  │ health: ✓   │ │ block: [42] │ │ after: 6mo  │ │ protect:    │   │  │  │
│  │  │  │ finance: ✗  │ │ allow: [99] │ │ before: now │ │ "wife"      │   │  │  │
│  │  │  └─────────────┘ └─────────────┘ └─────────────┘ └─────────────┘   │  │  │
│  │  │  ┌─────────────────────────────────────────────────────────────┐   │  │  │
│  │  │  │  PII Type Filter                                             │   │  │  │
│  │  │  │  expose: [PERSON, DATE_TIME]  anonymize: [EMAIL, PHONE, SSN] │   │  │  │
│  │  │  └─────────────────────────────────────────────────────────────┘   │  │  │
│  │  └─────────────────────────────────────────────────────────────────────┘  │  │
│  │                                                                            │  │
│  │  ┌─────────────────────────────────────────────────────────────────────┐  │  │
│  │  │                      PII MAPPINGS                                    │  │  │
│  │  │  Tokens:     "abc123" → "John Smith" (PERSON)                       │  │  │
│  │  │  Perturbed:  "Michael Chen" → "John Smith" (LPRAG)                  │  │  │
│  │  └─────────────────────────────────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────────────────────────────┘  │
│                                      │                                           │
│                                      ▼                                           │
│  ┌───────────────────────────────────────────────────────────────────────────┐  │
│  │                         Search + PII Processing                            │  │
│  │                                                                            │  │
│  │  1. Vector Search → 2. Category Filter → 3. Document Filter →             │  │
│  │  4. Time Filter → 5. Entity Filter → 6. PII Anonymization                 │  │
│  │                                                                            │  │
│  └───────────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### Unified Session Design

The system uses a **single session ID** for both consent rules and PII token mappings:

```
┌─────────────────────────────────────────────────────────────┐
│  Session (session_id: "sess_abc123...")                     │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  Consent Rules (what to filter/anonymize)            │   │
│  │  - Category, Document, Time, Entity, PII Type rules  │   │
│  └─────────────────────────────────────────────────────┘   │
│                          │                                  │
│                          │ determines                       │
│                          ▼                                  │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  PII Mappings (how to de-anonymize)                  │   │
│  │  - Token → Original value                            │   │
│  │  - Perturbed value → Original value (LPRAG)          │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

**Why unified?**
- Consent rules determine WHAT gets anonymized
- PII mappings store HOW to restore original values
- Both are session-scoped with the same TTL
- Natural coupling: you can't de-anonymize without knowing what was anonymized
- Simpler API: one `session_id` to track

### Unified Session Lifecycle

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                        UNIFIED SESSION LIFECYCLE                                 │
│                                                                                  │
│  1. CREATE SESSION                                                               │
│  ────────────────                                                                │
│  POST /api/consent/session                                                       │
│  {                                                                               │
│    "allowed_categories": ["health"],                                             │
│    "exposed_pii_types": ["DATE_TIME"]                                            │
│  }                                                                               │
│                     ↓                                                            │
│  Response: { "session_id": "sess_abc123..." }                                    │
│                     │                                                            │
│                     │ (Client stores session_id for conversation)                │
│                     ↓                                                            │
│  2. SEARCH WITH SESSION                                                          │
│  ──────────────────────                                                          │
│  POST /api/search                                                                │
│  { "query": "...", "session_id": "sess_abc123..." }                              │
│                     │                                                            │
│                     │ ← Consent rules filter results                             │
│                     │ ← PII anonymized per rules                                 │
│                     │ ← Token mappings stored in session                         │
│                     ↓                                                            │
│  Response: { "results": [...], "session_id": "sess_abc123..." }                  │
│                     │                                                            │
│                     │ (Results sent to LLM, LLM responds)                        │
│                     ↓                                                            │
│  3. DE-ANONYMIZE LLM RESPONSE                                                    │
│  ────────────────────────────                                                    │
│  POST /api/pii/deanonymize                                                       │
│  { "text": "LLM response...", "session_id": "sess_abc123..." }                   │
│                     │                                                            │
│                     │ ← Tokens replaced using session mappings                   │
│                     │ ← Perturbed values replaced (LPRAG)                        │
│                     │ ← Session TTL refreshed                                    │
│                     ↓                                                            │
│  Response: { "deanonymized_text": "..." }                                        │
│                     │                                                            │
│                     │ (Repeat steps 2-3 for each turn)                           │
│                     ↓                                                            │
│  4. SESSION EXPIRY                                                               │
│  ────────────────────                                                            │
│  After 1 hour of inactivity:                                                     │
│  - Consent rules cleared                                                         │
│  - All PII mappings cleared                                                      │
│  - Session ID no longer valid                                                    │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

## Consent Dimensions

### Dimension 1: Data Category Consent

Controls which **documents** are included in search results based on their topic/category.

| Category | Description | Default |
|----------|-------------|---------|
| `health` | Medical records, health notes, prescriptions | **Blocked** |
| `finance` | Bank statements, investments, taxes | **Blocked** |
| `work` | Work documents, professional correspondence | Allowed |
| `personal` | Personal notes, journals, diaries | **Blocked** |
| `social` | Social media, messages, contacts | **Blocked** |
| `legal` | Contracts, legal documents | **Blocked** |
| `travel` | Itineraries, bookings, passport info | **Blocked** |
| `education` | Transcripts, certificates, courses | Allowed |
| `general` | Uncategorized documents | Allowed |

**Behavior**:
- Documents with blocked categories are **excluded from search results entirely**
- If a document has multiple categories, it's included only if ALL its categories are allowed
- Categories map to existing topic system (topics → categories)

### Dimension 2: PII Type Consent

Controls which **PII entity types** are anonymized vs passed through to the LLM.

| PII Type | Description | Default | Risk Level |
|----------|-------------|---------|------------|
| `PERSON` | Names | Anonymize | Medium |
| `EMAIL_ADDRESS` | Email addresses | Anonymize | Medium |
| `PHONE_NUMBER` | Phone numbers | Anonymize | Medium |
| `LOCATION` | Addresses, cities | Anonymize | Low |
| `DATE_TIME` | Dates, times | Pass Through | Low |
| `US_SSN` | Social Security Numbers | **Always Anonymize** | Critical |
| `CREDIT_CARD` | Credit card numbers | **Always Anonymize** | Critical |
| `US_BANK_NUMBER` | Bank account numbers | **Always Anonymize** | Critical |
| `IBAN_CODE` | International bank accounts | **Always Anonymize** | Critical |
| `URL` | Web addresses | Pass Through | Low |
| `IP_ADDRESS` | IP addresses | Anonymize | Medium |

**Behavior**:
- PII types marked "Pass Through" are NOT anonymized (LLM sees real value)
- PII types marked "Anonymize" use LPRAG perturbation or token replacement
- **Critical** PII types cannot be set to "Pass Through" (always anonymized)

### Dimension 3: Per-Document Consent

Controls access to **specific documents** by their ID.

**Use Cases**:
- "Don't show that embarrassing email I sent last week"
- "Always include my resume when discussing job topics"
- "Block all documents from my ex"

| Mode | Description | Example |
|------|-------------|---------|
| `blocklist` | Specific documents always excluded | `blocked_docs: [42, 156, 789]` |
| `allowlist` | Only specific documents included | `allowed_docs: [99, 100, 101]` |
| `priority` | Specific documents boosted in results | `priority_docs: [50, 51]` |

**Behavior**:
- Blocklist is checked AFTER category filter (can block within allowed categories)
- Allowlist mode overrides category filter (only these docs, regardless of category)
- Priority mode boosts document scores, doesn't filter

```python
# Example: Block specific documents
consent = {
    "document_rules": {
        "blocked_ids": [42, 156],  # Never include these
        "allowed_ids": [],         # Empty = no allowlist mode
        "priority_ids": [99],      # Boost this document's score
    }
}
```

### Dimension 4: Time-Based Consent

Controls access based on **document timestamp** or **date range**.

**Use Cases**:
- "Only show data from the last 6 months"
- "Don't include anything before 2024"
- "Show documents from my vacation (July 15-30)"

| Filter | Description | Example |
|--------|-------------|---------|
| `after` | Documents created/modified after date | `"after": "2024-07-01"` |
| `before` | Documents created/modified before date | `"before": "2025-01-01"` |
| `relative` | Relative time window | `"relative": "-6m"` (last 6 months) |
| `range` | Specific date range | `"range": ["2024-07-15", "2024-07-30"]` |

**Relative Time Syntax**:
- `-30d` = last 30 days
- `-6m` = last 6 months
- `-1y` = last 1 year
- `+7d` = next 7 days (for future-dated documents)

**Behavior**:
- Uses document's `created_at` timestamp by default
- Can optionally use `modified_at` or content-extracted dates
- Multiple time filters combine with AND logic

```python
# Example: Only last 6 months, excluding last week
consent = {
    "time_rules": {
        "relative": "-6m",           # Last 6 months
        "before": "2025-01-18",      # But not this week
        "date_field": "created_at",  # Use creation date
    }
}
```

### Dimension 5: Entity-Specific Consent

Controls protection for **specific people or entities** mentioned in documents.

**Use Cases**:
- "Hide my wife Sarah's information but show mine"
- "Protect all info about my kids"
- "Anonymize my boss's name in work documents"
- "Show my own contact info but hide everyone else's"

| Mode | Description | Example |
|------|-------------|---------|
| `protect_entities` | Always anonymize these specific entities | `["Sarah Smith", "wife"]` |
| `expose_entities` | Never anonymize these entities | `["John Smith", "me", "self"]` |
| `protect_relationships` | Anonymize by relationship | `["spouse", "children", "boss"]` |

**Entity Matching**:
- Exact match: `"Sarah Smith"` matches "Sarah Smith"
- Partial match: `"Sarah"` matches "Sarah", "Sarah Smith", "Sarah Jones"
- Alias support: `"wife"` → user-defined alias for "Sarah Smith"
- Relationship inference: `"spouse"` → detected via context/metadata

**Behavior**:
- Entity rules override PII type settings (more specific wins)
- Protected entities are ALWAYS anonymized, even if PERSON type is exposed
- Exposed entities are NEVER anonymized, even if PERSON type is hidden
- Relationship-based rules require entity extraction metadata

```python
# Example: Protect family, expose self
consent = {
    "entity_rules": {
        "protect_entities": [
            {"name": "Sarah Smith", "aliases": ["wife", "Sarah"]},
            {"name": "Emma Smith", "aliases": ["daughter", "Emma"]},
            {"name": "Jake Smith", "aliases": ["son", "Jake"]},
        ],
        "expose_entities": [
            {"name": "John Smith", "aliases": ["me", "myself", "I"]},
        ],
        "protect_relationships": ["spouse", "children", "family"],
        "expose_relationships": ["self"],
    }
}
```

**Entity Registry**:
Users can maintain a persistent entity registry:

```python
# Persistent entity definitions
entity_registry = {
    "self": {
        "name": "John Smith",
        "email": "john@example.com",
        "phone": "555-123-4567",
        "relationship": "self",
    },
    "wife": {
        "name": "Sarah Smith",
        "email": "sarah@example.com",
        "relationship": "spouse",
    },
    "daughter": {
        "name": "Emma Smith",
        "age": 12,
        "relationship": "child",
    },
}
```

### Combined Flow (All 5 Dimensions)

```
User Query: "What did Sarah email me about investments last month?"

User Consent:
  - categories: ["work", "personal", "finance"]
  - blocked_docs: [42]  # That embarrassing email
  - time_rules: {"relative": "-1m"}  # Last month only
  - entity_rules: {"protect_entities": ["Sarah Smith"]}  # Hide wife's info
  - exposed_pii: ["PERSON", "DATE_TIME"]  # Show names (except protected)

1. VECTOR SEARCH
   Raw results: [Doc 1, Doc 42, Doc 3, Doc 4, Doc 5]

2. CATEGORY FILTER
   After filter: [Doc 1, Doc 42, Doc 3, Doc 5]  # Doc 4 was "legal" category

3. DOCUMENT FILTER
   After filter: [Doc 1, Doc 3, Doc 5]  # Doc 42 explicitly blocked

4. TIME FILTER
   After filter: [Doc 1, Doc 5]  # Doc 3 was from 2 months ago

5. ENTITY FILTER + PII PROCESSING
   Doc 1: "Email from Sarah Smith about Q3 investments on Jan 10"

   PII Processing:
   - "Sarah Smith" → PROTECTED ENTITY → "Emily Johnson" (LPRAG)
   - "Jan 10" → EXPOSED (DATE_TIME exposed) → "Jan 10" (unchanged)
   - "Q3" → Not PII → unchanged

   Result: "Email from Emily Johnson about Q3 investments on Jan 10"

6. FINAL RESULTS
   [
     {
       "id": 1,
       "text": "Email from Emily Johnson about Q3 investments on Jan 10",
       "score": 0.92,
       "consent_applied": {
         "entities_protected": ["Sarah Smith"],
         "entities_exposed": [],
         "time_filter_applied": true,
         "documents_filtered": 3
       }
     },
     ...
   ]
```

### Combined Flow (Original Example)

```
User Query: "What did John email me about my investment portfolio?"

1. CATEGORY FILTER (before search)
   User consent: categories = ["work", "personal"]  (finance blocked)

   Search results BEFORE filter:
   - Doc 1: "Email from John about Q3 budget" [topics: work, finance]
   - Doc 2: "John's project update" [topics: work]
   - Doc 3: "Investment statement from John" [topics: finance]

   Search results AFTER filter:
   - Doc 2: "John's project update" [topics: work] ✓ (work allowed)
   - Doc 1: EXCLUDED (has finance topic)
   - Doc 3: EXCLUDED (has finance topic)

2. PII TYPE FILTER (during anonymization)
   User consent: expose = ["PERSON", "DATE_TIME"]  (email, phone anonymized)

   "John's project update from john@company.com on Jan 15"

   After PII processing:
   "John's project update from michael@sample.org on Jan 15"

   - PERSON "John" → NOT anonymized (user exposed PERSON)
   - EMAIL "john@company.com" → Anonymized (user didn't expose EMAIL)
   - DATE "Jan 15" → NOT anonymized (user exposed DATE_TIME)
```

## Data Model

### Session (Unified)

The system uses a **unified session** that combines consent rules with PII mappings:

```python
@dataclass
class Session:
    """Unified session containing consent rules + PII token mappings."""

    session_id: str
    created_at: datetime
    last_accessed: datetime
    expires_at: datetime  # Sliding TTL (1 hour from last access)

    # === CONSENT RULES (5 Dimensions) ===

    # Dimension 1: Category consent (which document categories to include)
    allowed_categories: Set[str]  # Empty = all blocked, {"*"} = all allowed
    blocked_categories: Set[str]  # Explicit blocks override allows

    # Dimension 2: PII type consent (which PII types to expose)
    exposed_pii_types: Set[str]   # PII types NOT anonymized

    # Dimension 3: Per-document consent
    document_rules: DocumentRules

    # Dimension 4: Time-based consent
    time_rules: TimeRules

    # Dimension 5: Entity-specific consent
    entity_rules: EntityRules

    # === PII MAPPINGS (for de-anonymization) ===

    pii_mappings: PIIMappings  # Token and perturbed value mappings

    # === METADATA ===

    consent_source: str  # "ui", "natural_language", "api"
    consent_expression: Optional[str]  # Original user expression


@dataclass
class PIIMappings:
    """PII token and perturbed value mappings for de-anonymization."""

    # Token-based mappings (traditional: <PII:TYPE:token_id>)
    tokens: Dict[str, PIIToken]           # token_id → PIIToken
    value_to_token: Dict[Tuple, str]      # (type, original) → token_id

    # LPRAG perturbed value mappings (for hybrid mode)
    perturbed_to_token: Dict[str, str]    # perturbed_value → token_id

    def add_token(self, token: PIIToken) -> None:
        """Add a token with optional perturbed value mapping."""
        self.tokens[token.token_id] = token
        self.value_to_token[(token.pii_type, token.original_value)] = token.token_id
        if token.perturbed_value:
            self.perturbed_to_token[token.perturbed_value] = token.token_id

    def get_original(self, token_id: str) -> Optional[str]:
        """Get original value for a token ID."""
        token = self.tokens.get(token_id)
        return token.original_value if token else None

    def get_original_for_perturbed(self, perturbed: str) -> Optional[str]:
        """Get original value for a perturbed value (LPRAG)."""
        token_id = self.perturbed_to_token.get(perturbed)
        return self.get_original(token_id) if token_id else None


@dataclass
class PIIToken:
    """Individual PII token mapping."""

    token_id: str
    pii_type: str
    original_value: str
    perturbed_value: Optional[str] = None  # Set for LPRAG hybrid mode
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class DocumentRules:
    """Per-document consent rules."""

    blocked_ids: Set[int]    # Documents always excluded
    allowed_ids: Set[int]    # If non-empty, ONLY these docs (overrides categories)
    priority_ids: Set[int]   # Documents with boosted scores

    # Optional: block by source/connector
    blocked_sources: Set[str]  # e.g., ["gmail", "slack"]
    allowed_sources: Set[str]  # If non-empty, only these sources


@dataclass
class TimeRules:
    """Time-based consent rules."""

    after: Optional[datetime]    # Only docs after this date
    before: Optional[datetime]   # Only docs before this date
    relative: Optional[str]      # Relative time like "-6m", "-30d"
    date_field: str = "created_at"  # Which timestamp to use

    # Optional: specific date ranges
    include_ranges: List[Tuple[datetime, datetime]]  # Include these ranges
    exclude_ranges: List[Tuple[datetime, datetime]]  # Exclude these ranges


@dataclass
class EntityRules:
    """Entity-specific consent rules."""

    # Specific entities to protect/expose
    protect_entities: List[EntityDefinition]  # Always anonymize
    expose_entities: List[EntityDefinition]   # Never anonymize

    # Relationship-based rules
    protect_relationships: Set[str]  # e.g., {"spouse", "children"}
    expose_relationships: Set[str]   # e.g., {"self", "colleagues"}

    # Default behavior for unknown entities
    default_protect: bool = True  # If True, unknown entities are anonymized


@dataclass
class EntityDefinition:
    """Definition of a known entity for consent purposes."""

    name: str                      # Primary name: "Sarah Smith"
    aliases: Set[str]              # Alternative names: {"wife", "Sarah"}
    pii_values: Dict[str, str]     # Known PII: {"email": "sarah@...", "phone": "555-..."}
    relationship: Optional[str]    # Relationship to user: "spouse"
    entity_type: str = "PERSON"    # PII type: PERSON, ORGANIZATION, etc.
```

### ConsentPreferences (Persistent)

```python
@dataclass
class ConsentPreferences:
    """User's persistent default consent settings."""

    user_id: str  # Optional, for multi-user scenarios

    # Dimension 1: Default category consent
    default_allowed_categories: Set[str]
    default_blocked_categories: Set[str]

    # Dimension 2: Default PII type consent
    default_exposed_pii_types: Set[str]

    # Dimension 3: Default document rules
    default_document_rules: DocumentRules

    # Dimension 4: Default time rules
    default_time_rules: Optional[TimeRules]

    # Dimension 5: Entity registry (persistent entity definitions)
    entity_registry: Dict[str, EntityDefinition]

    # Presets
    active_preset: Optional[str]  # "strict", "balanced", "open", None

    # Metadata
    updated_at: datetime
```

### EntityRegistry (Persistent)

```python
@dataclass
class EntityRegistry:
    """User's persistent entity definitions for entity-specific consent."""

    user_id: str
    entities: Dict[str, EntityDefinition]  # key = entity_id
    relationships: Dict[str, Set[str]]     # relationship → entity_ids

    def get_by_name(self, name: str) -> Optional[EntityDefinition]:
        """Find entity by name or alias."""
        name_lower = name.lower()
        for entity in self.entities.values():
            if entity.name.lower() == name_lower:
                return entity
            if name_lower in {a.lower() for a in entity.aliases}:
                return entity
        return None

    def get_by_relationship(self, relationship: str) -> List[EntityDefinition]:
        """Find all entities with a given relationship."""
        entity_ids = self.relationships.get(relationship, set())
        return [self.entities[eid] for eid in entity_ids if eid in self.entities]

    def is_protected(self, name: str, rules: EntityRules) -> bool:
        """Check if an entity should be protected based on rules."""
        entity = self.get_by_name(name)

        # Check explicit protection list
        for protected in rules.protect_entities:
            if self._matches(name, protected):
                return True

        # Check explicit exposure list (takes precedence)
        for exposed in rules.expose_entities:
            if self._matches(name, exposed):
                return False

        # Check relationship-based rules
        if entity and entity.relationship:
            if entity.relationship in rules.protect_relationships:
                return True
            if entity.relationship in rules.expose_relationships:
                return False

        # Default behavior
        return rules.default_protect
```

### ConsentPresets

```python
CONSENT_PRESETS = {
    "strict": {
        "description": "Maximum privacy - all categories blocked, all PII anonymized",
        "allowed_categories": set(),
        "exposed_pii_types": set(),
        "time_rules": None,
        "entity_rules": {"default_protect": True},
    },
    "balanced": {
        "description": "Balanced - work/general allowed, sensitive PII anonymized",
        "allowed_categories": {"work", "general", "education"},
        "exposed_pii_types": {"DATE_TIME", "URL", "LOCATION"},
        "time_rules": None,
        "entity_rules": {"default_protect": True, "expose_relationships": {"self"}},
    },
    "open": {
        "description": "Open - most data allowed, only critical PII anonymized",
        "allowed_categories": {"*"},  # All categories
        "exposed_pii_types": {"PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "LOCATION", "DATE_TIME", "URL"},
        "time_rules": None,
        "entity_rules": {"default_protect": False},
    },
    "health_focus": {
        "description": "Health access - health data allowed, finances blocked",
        "allowed_categories": {"health", "personal", "general"},
        "blocked_categories": {"finance", "legal"},
        "exposed_pii_types": {"DATE_TIME"},
        "entity_rules": {"protect_relationships": {"family"}, "expose_relationships": {"self"}},
    },
    "work_only": {
        "description": "Work focus - only work-related data",
        "allowed_categories": {"work", "education"},
        "exposed_pii_types": {"PERSON", "DATE_TIME", "URL"},
        "entity_rules": {"expose_relationships": {"self", "colleagues"}},
    },
    "recent_only": {
        "description": "Recent data only - last 3 months",
        "allowed_categories": {"*"},
        "exposed_pii_types": {"DATE_TIME"},
        "time_rules": {"relative": "-3m"},
        "entity_rules": {"default_protect": True},
    },
    "family_protected": {
        "description": "Expose self, protect family members",
        "allowed_categories": {"*"},
        "exposed_pii_types": {"PERSON", "DATE_TIME"},
        "entity_rules": {
            "protect_relationships": {"spouse", "children", "parents", "siblings"},
            "expose_relationships": {"self"},
            "default_protect": False,
        },
    },
}
```

## API Design

### REST Endpoints

#### Consent Session Management

```http
# Create/update consent for current session (all 5 dimensions)
POST /api/consent/session
{
  "session_id": "optional-existing-session",

  # Dimension 1: Categories
  "allowed_categories": ["health", "personal"],
  "blocked_categories": ["finance"],

  # Dimension 2: PII Types
  "exposed_pii_types": ["PERSON", "DATE_TIME"],

  # Dimension 3: Documents
  "document_rules": {
    "blocked_ids": [42, 156],
    "allowed_ids": [],
    "priority_ids": [99],
    "blocked_sources": ["old-email-backup"]
  },

  # Dimension 4: Time
  "time_rules": {
    "relative": "-6m",
    "before": null,
    "after": null,
    "exclude_ranges": [["2024-12-24", "2024-12-26"]]  # Exclude holiday
  },

  # Dimension 5: Entities
  "entity_rules": {
    "protect_entities": [
      {"name": "Sarah Smith", "aliases": ["wife", "Sarah"]}
    ],
    "expose_entities": [
      {"name": "John Smith", "aliases": ["me"]}
    ],
    "protect_relationships": ["family"],
    "expose_relationships": ["self"]
  },

  "preset": null  // Or "balanced", "strict", etc.
}

Response:
{
  "session_id": "sess_abc123...",  // Unified session ID for consent + PII mappings
  "created_at": "2025-01-25T10:00:00Z",
  "expires_at": "2025-01-25T11:00:00Z",  // 1-hour sliding TTL
  "allowed_categories": ["health", "personal"],
  "blocked_categories": ["finance"],
  "exposed_pii_types": ["PERSON", "DATE_TIME"],
  "document_rules": {...},
  "time_rules": {...},
  "entity_rules": {...},
  "pii_mappings": {
    "token_count": 0,  // Will populate as searches are performed
    "perturbed_count": 0
  },
  "effective_config": {
    "categories_mode": "allowlist",
    "pii_mode": "selective_exposure",
    "time_filter_active": true,
    "entity_protection_active": true,
    "documents_blocked": 2
  }
}

# Get current session consent
GET /api/consent/session/{session_id}

# Update session consent (partial update)
PATCH /api/consent/session/{session_id}
{
  # Category updates
  "add_categories": ["work"],
  "remove_categories": ["health"],

  # PII type updates
  "expose_pii_types": ["EMAIL_ADDRESS"],
  "hide_pii_types": ["PERSON"],

  # Document updates
  "block_documents": [789],
  "unblock_documents": [42],

  # Time updates
  "time_rules": {"relative": "-3m"},

  # Entity updates
  "protect_entity": {"name": "Boss Name", "aliases": ["boss"]},
  "expose_entity": {"name": "Colleague Name"}
}

# Delete session (revoke all consent)
DELETE /api/consent/session/{session_id}
```

#### Document-Specific Consent

```http
# Block a specific document
POST /api/consent/session/{session_id}/block-document
{
  "document_id": 42,
  "reason": "Contains sensitive personal info"  // Optional, for audit
}

# Unblock a document
DELETE /api/consent/session/{session_id}/block-document/{document_id}

# Get blocked documents
GET /api/consent/session/{session_id}/blocked-documents
Response:
{
  "blocked_ids": [42, 156, 789],
  "blocked_sources": ["old-backup"],
  "total_blocked": 3
}

# Set document priority (boost in results)
POST /api/consent/session/{session_id}/priority-document
{
  "document_id": 99,
  "boost_factor": 1.5  // 1.5x score multiplier
}
```

#### Time-Based Consent

```http
# Set time filter
PUT /api/consent/session/{session_id}/time-rules
{
  "relative": "-6m",           // Last 6 months
  "exclude_ranges": [
    ["2024-12-20", "2025-01-05"]  // Exclude holiday period
  ]
}

# Clear time filter
DELETE /api/consent/session/{session_id}/time-rules

# Preview time filter impact
POST /api/consent/session/{session_id}/time-rules/preview
{
  "relative": "-3m"
}
Response:
{
  "documents_included": 150,
  "documents_excluded": 342,
  "date_range": {
    "from": "2024-10-25",
    "to": "2025-01-25"
  }
}
```

#### Entity-Specific Consent

```http
# Add entity to protection list
POST /api/consent/session/{session_id}/protect-entity
{
  "name": "Sarah Smith",
  "aliases": ["wife", "Sarah", "honey"],
  "relationship": "spouse",
  "pii_values": {
    "email": "sarah@example.com",
    "phone": "555-987-6543"
  }
}

# Remove entity from protection
DELETE /api/consent/session/{session_id}/protect-entity/{entity_name}

# Add entity to exposure list (never anonymize)
POST /api/consent/session/{session_id}/expose-entity
{
  "name": "John Smith",
  "aliases": ["me", "myself", "John"],
  "relationship": "self"
}

# Get entity rules
GET /api/consent/session/{session_id}/entity-rules
Response:
{
  "protect_entities": [
    {"name": "Sarah Smith", "aliases": ["wife"], "relationship": "spouse"}
  ],
  "expose_entities": [
    {"name": "John Smith", "aliases": ["me"], "relationship": "self"}
  ],
  "protect_relationships": ["family", "children"],
  "expose_relationships": ["self"],
  "default_protect": true
}

# Set relationship-based rules
PUT /api/consent/session/{session_id}/entity-rules/relationships
{
  "protect_relationships": ["spouse", "children", "parents"],
  "expose_relationships": ["self", "colleagues"]
}
```

#### Entity Registry (Persistent)

```http
# Get user's entity registry
GET /api/consent/entities
Response:
{
  "entities": [
    {
      "id": "ent_001",
      "name": "Sarah Smith",
      "aliases": ["wife", "Sarah"],
      "relationship": "spouse",
      "pii_values": {"email": "sarah@...", "phone": "555-..."}
    },
    {
      "id": "ent_002",
      "name": "Emma Smith",
      "aliases": ["daughter", "Emma"],
      "relationship": "child"
    }
  ],
  "relationships": {
    "spouse": ["ent_001"],
    "child": ["ent_002"],
    "family": ["ent_001", "ent_002"]
  }
}

# Add entity to registry
POST /api/consent/entities
{
  "name": "Jake Smith",
  "aliases": ["son", "Jake"],
  "relationship": "child"
}

# Update entity
PUT /api/consent/entities/{entity_id}
{
  "aliases": ["son", "Jake", "buddy"]  // Add new alias
}

# Delete entity
DELETE /api/consent/entities/{entity_id}

# Import entities from contacts/documents
POST /api/consent/entities/import
{
  "source": "extracted",  // Or "contacts", "manual"
  "auto_classify": true   // Attempt to infer relationships
}
Response:
{
  "imported": 15,
  "entities": [
    {"name": "Sarah Smith", "inferred_relationship": "spouse", "confidence": 0.85},
    {"name": "Dr. Johnson", "inferred_relationship": "healthcare", "confidence": 0.92}
  ]
}
```

#### Consent Presets

```http
# List available presets
GET /api/consent/presets

Response:
{
  "presets": [
    {
      "name": "strict",
      "description": "Maximum privacy...",
      "allowed_categories": [],
      "exposed_pii_types": []
    },
    ...
  ]
}

# Apply preset to session
POST /api/consent/session/{session_id}/apply-preset
{
  "preset": "balanced"
}
```

#### Persistent Preferences

```http
# Get user's default preferences
GET /api/consent/preferences

# Update default preferences
PUT /api/consent/preferences
{
  "default_allowed_categories": ["work", "general"],
  "default_exposed_pii_types": ["DATE_TIME", "URL"],
  "active_preset": "balanced"
}
```

#### Natural Language Consent

```http
# Parse natural language consent expression
POST /api/consent/parse
{
  "expression": "I want you to see my health records but not my financial data. You can use my name."
}

Response:
{
  "parsed": {
    "allowed_categories": ["health"],
    "blocked_categories": ["finance"],
    "exposed_pii_types": ["PERSON"]
  },
  "confidence": 0.92,
  "interpretation": "Allow health category, block finance category, expose PERSON names"
}

# Apply parsed consent to session
POST /api/consent/session/{session_id}/apply-expression
{
  "expression": "Show my health data but hide my finances"
}
```

### Search with Consent

```http
# Search with unified session (consent rules + PII mappings)
POST /api/search
{
  "query": "doctor's appointment",
  "top_k": 5,
  "session_id": "sess_abc123..."  // Same session for consent and PII
}

# Or inline consent (creates temporary session)
POST /api/search
{
  "query": "doctor's appointment",
  "top_k": 5,
  "consent": {
    # Dimension 1: Categories
    "allowed_categories": ["health"],

    # Dimension 2: PII Types
    "exposed_pii_types": ["DATE_TIME"],

    # Dimension 3: Documents
    "document_rules": {
      "blocked_ids": [42]
    },

    # Dimension 4: Time
    "time_rules": {
      "relative": "-6m"
    },

    # Dimension 5: Entities
    "entity_rules": {
      "protect_entities": [{"name": "Sarah Smith"}],
      "expose_relationships": ["self"]
    }
  }
}

Response:
{
  "query": "doctor's appointment",
  "results": [...],
  "session_id": "sess_abc123...",  // Unified session for consent + PII mappings
  "consent_applied": {
    # Category filter stats
    "documents_filtered_by_category": 12,
    "categories_allowed": ["health"],

    # Document filter stats
    "documents_filtered_by_id": 1,
    "documents_blocked": [42],

    # Time filter stats
    "documents_filtered_by_time": 8,
    "time_range_applied": {
      "from": "2024-07-25",
      "to": "2025-01-25"
    },

    # Entity filter stats
    "entities_protected": ["Sarah Smith"],
    "entities_exposed": ["John Smith"],
    "entity_anonymizations": 3,

    # PII type stats
    "pii_types_exposed": ["DATE_TIME"],
    "pii_types_anonymized": ["PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER"],
    "total_pii_anonymized": 7,
    "total_pii_exposed": 2
  },
  "pii_stats": {
    "tokens_created": 7,       // New tokens created in this search
    "tokens_total": 15,        // Total tokens in session
    "perturbed_mappings": 3    // LPRAG perturbed value mappings
  }
}
```

### De-anonymization with Unified Session

The same `session_id` is used for both consent and de-anonymization:

```http
# De-anonymize LLM response using the unified session
POST /api/pii/deanonymize
{
  "text": "Based on Michael Chen's email, the appointment is on Jan 15",
  "session_id": "sess_abc123..."  // Same session used for search
}

Response:
{
  "deanonymized_text": "Based on John Smith's email, the appointment is on Jan 15",
  "session_id": "sess_abc123...",
  "tokens_replaced": 1,
  "perturbed_replaced": 1,  // LPRAG: "Michael Chen" → "John Smith"
  "session_info": {
    "ttl_remaining_seconds": 3540,
    "total_tokens": 15,
    "total_perturbed_mappings": 3
  }
}

# Get session info (consent rules + PII mappings)
GET /api/session/{session_id}

Response:
{
  "session_id": "sess_abc123...",
  "created_at": "2025-01-25T10:00:00Z",
  "last_accessed": "2025-01-25T10:30:00Z",
  "expires_at": "2025-01-25T11:30:00Z",
  "ttl_remaining_seconds": 3540,
  "consent": {
    "allowed_categories": ["health"],
    "exposed_pii_types": ["DATE_TIME"],
    "document_rules": {...},
    "time_rules": {...},
    "entity_rules": {...}
  },
  "pii_mappings": {
    "token_count": 15,
    "perturbed_count": 3,
    "types_seen": ["PERSON", "EMAIL_ADDRESS", "DATE_TIME"]
  }
}

# Refresh session TTL
POST /api/session/{session_id}/refresh

# Clear session (consent + all PII mappings)
DELETE /api/session/{session_id}
```

### Natural Language Consent (Enhanced)

```http
# Parse natural language consent expression (all 5 dimensions)
POST /api/consent/parse
{
  "expression": "Show me my health records from the last 3 months, but hide my wife Sarah's information. You can use my name and dates."
}

Response:
{
  "parsed": {
    "allowed_categories": ["health"],
    "exposed_pii_types": ["PERSON", "DATE_TIME"],
    "time_rules": {
      "relative": "-3m"
    },
    "entity_rules": {
      "protect_entities": [
        {"name": "Sarah", "inferred_relationship": "spouse"}
      ],
      "expose_entities": [
        {"name": "self", "inferred_relationship": "self"}
      ]
    }
  },
  "confidence": 0.88,
  "interpretation": "Allow health category, last 3 months only, protect 'Sarah' (spouse), expose self, expose PERSON and DATE_TIME types",
  "clarification_needed": [
    {
      "field": "entity_rules.protect_entities[0].name",
      "question": "Is 'Sarah' your wife Sarah Smith?",
      "suggestions": ["Sarah Smith", "Sarah Jones", "Other Sarah"]
    }
  ]
}
```

## Topic-to-Category Mapping

Documents have topics (from TinyLlama extraction). Categories are higher-level groupings.

```python
TOPIC_TO_CATEGORY_MAP = {
    # Health
    "health": "health",
    "medical": "health",
    "doctor": "health",
    "prescription": "health",
    "hospital": "health",
    "wellness": "health",
    "fitness": "health",

    # Finance
    "finance": "finance",
    "banking": "finance",
    "investment": "finance",
    "tax": "finance",
    "budget": "finance",
    "insurance": "finance",
    "crypto": "finance",

    # Work
    "work": "work",
    "business": "work",
    "meeting": "work",
    "project": "work",
    "email": "work",
    "corporate": "work",

    # Personal
    "personal": "personal",
    "diary": "personal",
    "journal": "personal",
    "family": "personal",
    "relationship": "personal",

    # Social
    "social": "social",
    "message": "social",
    "chat": "social",
    "friend": "social",

    # Legal
    "legal": "legal",
    "contract": "legal",
    "agreement": "legal",
    "court": "legal",

    # Travel
    "travel": "travel",
    "flight": "travel",
    "hotel": "travel",
    "vacation": "travel",

    # Education
    "education": "education",
    "school": "education",
    "course": "education",
    "learning": "education",
}

def get_document_categories(topics: List[str]) -> Set[str]:
    """Map document topics to consent categories."""
    categories = set()
    for topic in topics:
        topic_lower = topic.lower()
        for keyword, category in TOPIC_TO_CATEGORY_MAP.items():
            if keyword in topic_lower:
                categories.add(category)

    # Default to "general" if no category matched
    if not categories:
        categories.add("general")

    return categories
```

## Implementation Plan

### Phase 1: Core Consent Engine (Categories + PII Types)

**Files to create:**
- `vector-store/mcp_vector_store/consent_manager.py` - Core consent logic
- `vector-store/mcp_vector_store/consent_config.py` - Presets and configuration
- `vector-store/mcp_vector_store/consent_session.py` - Session management

**Key classes:**
- `ConsentSession` - Session-scoped consent state
- `ConsentPreferences` - Persistent defaults
- `ConsentManager` - Orchestrates consent logic
- `CategoryMatcher` - Maps topics to consent categories

**Deliverables:**
- Category-based document filtering
- PII type selective exposure
- Basic presets (strict, balanced, open)

### Phase 2: Per-Document Consent

**Files to modify:**
- `vector-store/mcp_vector_store/consent_manager.py` - Add DocumentRules
- `vector-store/mcp_vector_store/vector_store.py` - Filter by document IDs

**Key changes:**
- `DocumentRules` dataclass with blocked/allowed/priority IDs
- Document blocklist checked post-search
- Priority document score boosting
- Source-based filtering (e.g., block all from "old-backup")

### Phase 3: Time-Based Consent

**Files to modify:**
- `vector-store/mcp_vector_store/consent_manager.py` - Add TimeRules
- `vector-store/mcp_vector_store/vector_store.py` - Time-based filtering

**Key changes:**
- `TimeRules` dataclass with relative/absolute time support
- Parse relative time expressions (`-6m`, `-30d`, `-1y`)
- Time range inclusion/exclusion
- Preview endpoint for time filter impact

### Phase 4: Entity-Specific Consent

**Files to create:**
- `vector-store/mcp_vector_store/entity_registry.py` - Entity definitions
- `vector-store/mcp_vector_store/entity_matcher.py` - Entity matching logic

**Files to modify:**
- `vector-store/mcp_vector_store/pii_protection.py` - Entity-aware anonymization
- `vector-store/mcp_vector_store/consent_manager.py` - Add EntityRules

**Key changes:**
- `EntityRegistry` for persistent entity definitions
- Entity matching (name, aliases, relationships)
- Per-entity protection/exposure rules
- Relationship-based rules (protect "family", expose "self")
- Integration with LPRAG for entity-aware perturbation

### Phase 5: Search Integration

**Files to modify:**
- `vector-store/mcp_vector_store/vector_store.py` - Add consent filtering
- `vector-store/mcp_vector_store/pii_protection.py` - Add selective PII exposure
- `vector-store/mcp_vector_store/mcp_server_http.py` - Add consent endpoints

**Key changes:**
- `search_with_consent()` method applies all 5 filters in order
- `anonymize_with_consent()` respects entity rules and PII type settings
- Consent statistics in search responses
- REST endpoints for all consent operations

### Phase 6: Natural Language Consent

**Files to create:**
- `vector-store/mcp_vector_store/consent_parser.py`

**Approach:**
- Use TinyLlama (on-device) to parse consent expressions
- Extract: categories, time ranges, entity names, PII types
- Keyword matching as fallback
- Confidence scoring and clarification prompts
- Entity resolution against registry

**Example parsing:**
```
Input: "Show health data from last 6 months, hide my wife's info"

Extracted:
- categories: ["health"]
- time_rules: {"relative": "-6m"}
- entity_rules: {"protect_entities": [{"name": "wife", "relationship": "spouse"}]}
```

### Phase 7: TypeScript Integration

**Files to modify:**
- `server/vector-store-client.ts` - Add consent types and methods
- `server/chat-service.ts` - Integrate consent into chat flow

**New types:**
- `ConsentSession`, `ConsentPreferences`
- `DocumentRules`, `TimeRules`, `EntityRules`
- `EntityDefinition`, `EntityRegistry`

**New methods:**
- `createConsentSession()`, `updateConsentSession()`
- `blockDocument()`, `setTimeRules()`, `protectEntity()`
- `searchWithConsent()`

### Phase 8: Persistence Layer

**Files to create:**
- `vector-store/mcp_vector_store/consent_storage.py`

**Storage:**
- ConsentPreferences stored in JSON file (per-user)
- EntityRegistry stored in JSON file (per-user)
- Consent audit log (append-only JSON)

### Phase 9: UI (Future)

- Consent settings panel with 5 dimension tabs
- Per-session consent toggle
- Preset quick-select
- Natural language input field
- Entity registry management
- Time filter date picker
- Document blocklist management

## Security Considerations

### Critical PII Protection

Certain PII types are **ALWAYS anonymized** regardless of user consent:

```python
CRITICAL_PII_TYPES = {
    "US_SSN",
    "CREDIT_CARD",
    "US_BANK_NUMBER",
    "IBAN_CODE",
    "IN_AADHAAR",
    "AU_TFN",
    # Other highly sensitive identifiers
}

def validate_pii_exposure(exposed_types: Set[str]) -> Set[str]:
    """Remove critical PII types from exposure list."""
    return exposed_types - CRITICAL_PII_TYPES
```

### Consent Audit Trail

Log consent changes for accountability:

```python
@dataclass
class ConsentAuditEntry:
    timestamp: datetime
    session_id: str
    action: str  # "create", "update", "apply_preset", "delete"
    old_config: Optional[Dict]
    new_config: Dict
    source: str  # "ui", "api", "natural_language"
```

### Session Isolation

Sessions are isolated:
- Cannot access other sessions' consent rules or PII mappings
- Cannot modify persistent preferences without explicit API call
- Automatically expire with 1-hour sliding TTL (refreshed on each access)
- Single unified session contains both consent rules and PII mappings

## User Experience

### Scenario 1: First-Time User

1. User starts chat
2. System applies default "balanced" preset
3. User asks about health: "What did my doctor say?"
4. System returns empty results (health blocked by default)
5. System prompts: "Health data is currently blocked. Would you like to enable it for this session?"
6. User clicks "Enable health access"
7. Results now include health documents

### Scenario 2: Natural Language Consent

1. User says: "I'm working on my taxes. You can see my financial documents but please keep my SSN hidden."
2. System parses:
   - Allow categories: `["finance"]`
   - Expose PII: `[]` (SSN mention reinforces default protection)
3. System confirms: "I've enabled access to your financial documents. SSNs and account numbers will remain protected."
4. Search results now include finance documents with SSN/account numbers anonymized

### Scenario 3: Preset Selection

1. User opens consent settings
2. Sees presets: Strict | Balanced | Open | Custom
3. Selects "Work Only"
4. System applies:
   - Categories: work, education only
   - PII exposure: PERSON, DATE_TIME, URL
5. User can customize further or save as default

### Scenario 4: Per-Document Blocking

1. User asks: "What did I write about the Henderson project?"
2. Results include an embarrassing email the user regrets
3. User clicks "Block this document" on result #2
4. Document ID added to session blocklist
5. Subsequent searches never include that document
6. User can also block permanently in settings

### Scenario 5: Time-Based Filtering

1. User says: "I only want to discuss things from the past 3 months"
2. System parses and applies time filter: `{"relative": "-3m"}`
3. System confirms: "I'll only search documents from the last 3 months (Oct 25, 2024 - Jan 25, 2025)"
4. User can see preview: "This excludes 342 older documents"
5. All searches now filtered to this time range

### Scenario 6: Entity Protection (Family)

1. User sets up entity registry:
   - Wife: "Sarah Smith" (aliases: "wife", "Sarah")
   - Daughter: "Emma Smith" (aliases: "daughter", "Emma")
2. User enables "family_protected" preset
3. User asks: "What did Sarah email me about?"
4. Results show emails FROM Sarah, but her name is LPRAG-perturbed:
   - "Email from Emily Johnson about school pickup"
5. User sees original when de-anonymized locally
6. LLM never sees "Sarah Smith" - only "Emily Johnson"

### Scenario 7: Mixed Consent Expression

1. User says: "Show me my health records from last year, but don't include anything about my wife Sarah, and you can use my name but hide my doctor's name."
2. System parses:
   - Categories: `["health"]`
   - Time: `{"relative": "-1y"}`
   - Protect entities: `["Sarah", "doctor"]`
   - Expose entities: `["self"]`
   - Expose PII: `["PERSON"]` (but overridden for protected entities)
3. System asks for clarification: "Is 'Sarah' your wife Sarah Smith from your contacts?"
4. User confirms
5. Search results:
   - Only health documents from last year
   - User's name shown as-is
   - Wife's name anonymized (even though PERSON is exposed)
   - Doctor's name anonymized (due to explicit protection)

### Scenario 8: Document Source Filtering

1. User says: "Don't include anything from my old Gmail backup"
2. System adds source filter: `blocked_sources: ["gmail-backup-2020"]`
3. Documents from that connector are excluded from all searches
4. User can still see them in document browser, just not in chat context

## Metrics and Monitoring

Track consent usage:

```python
consent_metrics = {
    "sessions_created": Counter(),
    "preset_usage": Counter(labels=["preset_name"]),
    "category_exposure": Counter(labels=["category"]),
    "pii_exposure": Counter(labels=["pii_type"]),
    "natural_language_parses": Counter(),
    "documents_filtered_by_consent": Histogram(),
}
```

## Future Enhancements

1. **Consent Delegation**: Share consent config with trusted apps/users
2. **Consent Templates**: Save and share custom presets
3. **Consent Prompts**: LLM proactively asks for consent when needed data is blocked
4. **Smart Entity Detection**: Auto-detect and classify entities from documents
5. **Consent Analytics**: Dashboard showing what data was shared/blocked over time
6. **Consent Inheritance**: Child categories inherit parent consent (e.g., "medical" under "health")
7. **Consent Expiration**: Time-limited consent that auto-reverts
8. **Multi-User Consent**: Different consent profiles for different household members
9. **Consent Export/Import**: Backup and restore consent configurations
10. **Consent API Tokens**: Allow external apps to request specific consent scopes

## Summary

The consent system provides **five dimensions of granular control**:

| Dimension | What It Controls | Example |
|-----------|-----------------|---------|
| **Categories** | Which document topics to include | "health: yes, finance: no" |
| **PII Types** | Which PII is anonymized vs exposed | "show names, hide SSNs" |
| **Documents** | Block/allow specific documents | "block doc #42" |
| **Time-Based** | Temporal filters | "last 6 months only" |
| **Entity-Specific** | Per-person protection | "hide wife's info, show mine" |

### Key Features

1. **Five-dimensional control** for maximum flexibility

2. **Unified Session**:
   - Single `session_id` for both consent rules and PII mappings
   - Consent determines WHAT gets anonymized
   - PII mappings track HOW to de-anonymize
   - Same 1-hour sliding TTL for both
   - Simpler API: one ID to track per conversation

3. **Multiple interfaces**:
   - REST API for programmatic control
   - Presets for quick configuration
   - Natural language for intuitive expression

4. **Privacy-first**:
   - Critical PII (SSN, credit cards) always protected
   - Protected entities always anonymized regardless of PII type settings
   - Default to maximum protection

5. **Transparent**:
   - Audit logging for all consent changes
   - Statistics in search responses showing what was filtered
   - Preview endpoints to see impact before applying

6. **Entity-aware**:
   - Persistent entity registry for family/contacts
   - Relationship-based rules (protect "family", expose "self")
   - Entity matching across documents

### Consent Filter Order

Filters are applied in this order during search:

```
1. Vector Search (semantic similarity)
      ↓
2. Category Filter (by document topics)
      ↓
3. Document Filter (by ID/source blocklist)
      ↓
4. Time Filter (by document timestamp)
      ↓
5. Entity Filter + PII Anonymization
      (respects entity rules and PII type settings)
      ↓
6. Return Results with consent statistics
```

### Security Guarantees

- **Critical PII always protected**: SSN, credit cards, bank accounts cannot be exposed
- **Protected entities always anonymized**: Even if PERSON type is exposed
- **Session isolation**: Consent changes don't affect other sessions
- **Audit trail**: All consent changes logged with timestamps
- **No data deletion**: Consent filters search results, doesn't delete documents
