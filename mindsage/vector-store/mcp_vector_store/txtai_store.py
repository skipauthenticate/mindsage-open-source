"""
txtai-based vector store for MindSage.

Provides hybrid search (BM25 + semantic), graph queries, and optimized inference.
Designed for edge deployment on NVIDIA Jetson Orin Nano with limited memory.
"""

import os
import atexit
import uuid
import hashlib
import threading
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
import numpy as np

from txtai.embeddings import Embeddings


def compute_content_hash(text: str, source: str = "") -> str:
    """Compute SHA-256 hash of text content for duplicate detection.

    When source is provided, the hash includes the source so that identical
    text from different origins (e.g. ChatGPT vs Claude) is stored separately,
    preserving cross-source correlation.
    """
    key = f"{source}:{text}" if source else text
    return hashlib.sha256(key.encode('utf-8')).hexdigest()


@dataclass
class TxtaiDocument:
    """Document representation for txtai storage."""
    id: str
    text: str
    embedding: Optional[np.ndarray] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    content_hash: str = ""
    created_at: int = 0  # Unix timestamp in milliseconds

    def __post_init__(self):
        if not self.content_hash and self.text:
            self.content_hash = compute_content_hash(self.text)
        if not self.created_at:
            self.created_at = int(datetime.now().timestamp() * 1000)


@dataclass
class TxtaiSearchResult:
    """Search result from txtai."""
    id: str
    text: str
    score: float
    metadata: Dict[str, Any] = field(default_factory=dict)
    topics: Optional[List[str]] = None
    primary_topic: Optional[str] = None


class TxtaiStore:
    """
    Unified vector store using txtai.

    Features:
    - Hybrid search (BM25 keyword + semantic vectors)
    - Semantic graph for concept traversal
    - ONNX runtime for Jetson optimization
    - SQLite for metadata storage
    - Compatible with existing MindSage API
    """

    # System document ID used to seed empty indexes
    SYSTEM_DOC_ID = "__system_seed__"

    # Default configuration for Jetson Orin Nano
    DEFAULT_CONFIG = {
        # Embedding model — bge-small-en-v1.5: 384-dim, 512 token context, +6 MTEB points vs MiniLM
        "path": "BAAI/bge-small-en-v1.5",

        # GPU acceleration - use CUDA when available
        "gpu": True,

        # Hybrid search: BM25 + vectors
        "keyword": True,
        "hybrid": True,

        # Scoring configuration (txtai 9.x)
        # normalize: True (default convex fusion), "bb25" (Bayesian BB25 + log-odds fusion)
        # Note: BB25 ("bayes") produces negative scores that break min_score filtering
        # k1/b: BM25 parameters (defaults: k1=1.2, b=0.75)
        "scoring": {
            "method": "bm25",
            "normalize": True,
            "terms": True
        },

        # Storage - store document content for retrieval
        "content": True,

        # SQLite configuration for metadata
        "sqlite": {
            "wal": True  # Write-ahead logging for concurrent access
        },

        # Expression indexing for fast topic/source lookups
        "expressions": [
            {"name": "primary_topic", "index": True},
            {"name": "source", "index": True},
        ],

        # Graph support for concept traversal
        "graph": {
            "approximate": True,
            "minscore": 0.7
        }
    }

    # Jetson-optimized configuration
    JETSON_CONFIG = {
        **DEFAULT_CONFIG,
        # Note: 'backend: onnx' removed - txtai auto-selects best ANN backend
        # ONNX for embeddings is handled separately via sentence-transformers

        # Smaller batches for limited VRAM
        "batch": 32,

        # Graph limits for memory
        "graph": {
            "approximate": True,
            "minscore": 0.7,
            "limit": 500
        }
    }

    def __init__(
        self,
        data_dir: str = "data/txtai",
        config: Optional[Dict[str, Any]] = None,
        use_onnx: bool = True,
        skip_duplicates: bool = True
    ):
        """
        Initialize txtai vector store.

        Args:
            data_dir: Directory for storing index and SQLite database
            config: Custom txtai configuration (overrides defaults)
            use_onnx: Use ONNX backend for inference (recommended for Jetson)
            skip_duplicates: Skip adding documents with identical content hash
        """
        self.data_dir = data_dir
        self.skip_duplicates = skip_duplicates
        self._embeddings: Optional[Embeddings] = None
        self._id_counter = 0
        self._content_hashes: Dict[str, str] = {}  # hash -> doc_id mapping
        self._write_lock = threading.RLock()  # Serialize ALL SQLite access (reads + writes) across threads
        self._dirty = False  # Track whether index needs saving
        self._save_timer: Optional[threading.Timer] = None
        self._dirty_write_count = 0
        try:
            # Keep write-loss window short on constrained devices (Jetson/OOM risk).
            self._save_interval = max(0.25, float(os.getenv("MINDSAGE_SAVE_INTERVAL_SECONDS", "1.0")))
        except ValueError:
            self._save_interval = 1.0
        try:
            # Force periodic checkpoints under sustained ingest even before timer fires.
            self._max_dirty_writes = max(1, int(os.getenv("MINDSAGE_MAX_DIRTY_WRITES", "25")))
        except ValueError:
            self._max_dirty_writes = 25

        # Build configuration
        base_config = self.JETSON_CONFIG if use_onnx else self.DEFAULT_CONFIG
        self._config = {**base_config, **(config or {})}

        # Initialize
        self._initialize()

    def _initialize(self):
        """Initialize txtai embeddings with configuration."""
        os.makedirs(self.data_dir, exist_ok=True)

        print(f"Initializing txtai at: {self.data_dir}")
        print(f"  Hybrid search: {self._config.get('hybrid', False)}")
        print(f"  ONNX backend: {self._config.get('backend') == 'onnx'}")

        self._embeddings = Embeddings(self._config)

        # Load existing index if present
        index_path = os.path.join(self.data_dir, "index")
        if os.path.exists(index_path):
            print(f"  Loading existing index from: {index_path}")
            self._embeddings.load(index_path)
            self._load_state()
        else:
            print("  Starting with empty index")
            self._seed_index_if_empty()

        # Get embedding dimension
        self._embedding_dim = self._embeddings.config.get("dimensions", 384)
        print(f"  Embedding dimension: {self._embedding_dim}")

        # Register atexit handler to flush dirty writes on process exit
        # Critical for Jetson where abrupt exits can interrupt deferred saves
        atexit.register(self._atexit_flush)

    def _atexit_flush(self):
        """Flush dirty writes on process exit (atexit handler)."""
        if self._dirty and self._embeddings:
            try:
                if self._save_timer and self._save_timer.is_alive():
                    self._save_timer.cancel()
                self._save_index()
                self._save_state()
            except Exception:
                pass  # Best-effort on exit

    def _load_state(self):
        """Load persisted state (ID counter, content hashes)."""
        state_file = os.path.join(self.data_dir, ".state.json")
        if os.path.exists(state_file):
            import json
            with open(state_file, 'r') as f:
                state = json.load(f)
                self._id_counter = state.get("id_counter", 0)
                self._content_hashes = state.get("content_hashes", {})

    def _save_state(self):
        """Persist state to disk."""
        import json
        state_file = os.path.join(self.data_dir, ".state.json")
        with open(state_file, 'w') as f:
            json.dump({
                "id_counter": self._id_counter,
                "content_hashes": self._content_hashes
            }, f)

    def _seed_index_if_empty(self):
        """Seed the index with a system document for initial FAISS index creation."""
        print("  Seeding empty index...")

        seed_doc = {
            "text": "MindSage vector store initialized. This is a system document.",
            "metadata": {
                "type": "system",
                "hidden": True,
                "description": "Seed document for FAISS index initialization"
            }
        }

        self._embeddings.index([(self.SYSTEM_DOC_ID, seed_doc, None)])

        index_path = os.path.join(self.data_dir, "index")
        self._embeddings.save(index_path)
        print(f"  Seeded and saved index")

    def _next_id(self) -> int:
        """Generate next document ID."""
        self._id_counter += 1
        return self._id_counter

    @property
    def embedding_dim(self) -> int:
        """Get embedding dimension."""
        return self._embedding_dim

    def add_document(
        self,
        text: str,
        metadata: Optional[Dict[str, Any]] = None,
        doc_id: Optional[str] = None,
        skip_dedup: bool = False
    ) -> Tuple[str, bool]:
        """
        Add a single document to the store.

        Args:
            text: Document text content
            metadata: Optional metadata dictionary
            doc_id: Optional document ID (auto-generated if not provided)
            skip_dedup: If True, skip duplicate detection (used for chunks)

        Returns:
            Tuple of (document_id, is_duplicate)
        """
        source = (metadata or {}).get("source", "")
        content_hash = compute_content_hash(text, source=source)

        # Check for duplicates (unless skip_dedup is set, e.g. for chunks)
        if not skip_dedup and self.skip_duplicates and content_hash in self._content_hashes:
            existing_id = self._content_hashes[content_hash]
            print(f"  Duplicate detected, existing doc: {existing_id}")
            return existing_id, True

        # Generate ID if not provided
        if doc_id is None:
            doc_id = str(self._next_id())

        # Prepare metadata - serialize to JSON for txtai storage
        import json
        now = int(datetime.now().timestamp() * 1000)
        full_metadata = {
            "content_hash": content_hash,
            "created_at": now,
            "updated_at": now,
            "topics": [],
            "key_passages": [],
            "entities": [],
            **(metadata or {})
        }

        # Upsert document - txtai format with content storage:
        # [(id, {"text": text, "metadata": json_string}, tags)]
        # Using upsert() to add to existing index (index() replaces entire index)
        doc_data = {
            "text": text,
            "metadata_json": json.dumps(full_metadata)
        }

        # Serialize write operations to prevent SQLite race conditions
        with self._write_lock:
            self._embeddings.upsert([(doc_id, doc_data, None)])

            # Track content hash
            self._content_hashes[content_hash] = doc_id

            # Schedule deferred persist (batches multiple writes)
            self._schedule_save()

        return doc_id, False

    def add_documents(
        self,
        documents: List[Dict[str, Any]]
    ) -> List[Tuple[str, bool]]:
        """
        Add multiple documents in batch.

        Args:
            documents: List of dicts with 'text' and optional 'metadata', 'id' keys

        Returns:
            List of (document_id, is_duplicate) tuples
        """
        results = []
        to_index = []

        for doc in documents:
            text = doc.get("text", "")
            metadata = doc.get("metadata", {})
            doc_id = doc.get("id")

            source = metadata.get("source", "")
            content_hash = compute_content_hash(text, source=source)

            # Check for duplicates
            if self.skip_duplicates and content_hash in self._content_hashes:
                existing_id = self._content_hashes[content_hash]
                results.append((existing_id, True))
                continue

            # Generate ID if not provided
            if doc_id is None:
                doc_id = str(self._next_id())

            # Prepare metadata - serialize to JSON for txtai storage
            import json
            now = int(datetime.now().timestamp() * 1000)
            full_metadata = {
                "content_hash": content_hash,
                "created_at": now,
                "updated_at": now,
                "topics": [],
                "key_passages": [],
                "entities": [],
                **metadata
            }

            # Use dict format for txtai content storage
            doc_data = {
                "text": text,
                "metadata_json": json.dumps(full_metadata)
            }
            to_index.append((doc_id, doc_data, None))
            self._content_hashes[content_hash] = doc_id
            results.append((doc_id, False))

        # Batch upsert non-duplicates (using upsert to add to existing index)
        # Serialize write operations to prevent SQLite race conditions
        if to_index:
            with self._write_lock:
                self._embeddings.upsert(to_index)
                self._schedule_save()

        return results

    def search(
        self,
        query: str,
        limit: int = 10,
        min_score: float = 0.0,
        hybrid: bool = True,
        weights: float = None
    ) -> List[TxtaiSearchResult]:
        """
        Search with hybrid BM25 + semantic.

        Args:
            query: Search query text
            limit: Maximum results to return
            min_score: Minimum similarity threshold (0.0 to 1.0)
            hybrid: Use hybrid search (BM25 + vectors)
            weights: Dense/sparse balance (0.0=keyword only, 1.0=semantic only,
                     0.5=balanced). None uses txtai default (0.5). Passed directly
                     to txtai's native hybrid fusion.

        Returns:
            List of TxtaiSearchResult objects sorted by score descending
        """
        import json
        search_results = []

        with self._write_lock:
            if self._embeddings.count() == 0:
                return []

            # When weights are specified, use txtai's native search with weights param
            # (SQL path doesn't support the weights parameter)
            if weights is not None:
                results = self._embeddings.search(query, limit=limit * 2, weights=weights)
            else:
                # Use SQL query to retrieve all stored fields including metadata_json
                # Escape single quotes in query to prevent SQL injection
                safe_query = query.replace("'", "''")
                sql = f"SELECT id, text, metadata_json, score FROM txtai WHERE similar('{safe_query}') LIMIT {limit * 2}"

                try:
                    results = self._embeddings.search(sql)
                except Exception:
                    # Fallback to standard search if SQL fails
                    results = self._embeddings.search(query, limit=limit * 2)

        for result in results:
            # txtai returns dict with 'id', 'score', 'text' (if content=True)
            doc_id = str(result.get("id", ""))

            # Skip system seed document
            if doc_id == self.SYSTEM_DOC_ID:
                continue

            score = result.get("score", 0.0)

            if score < min_score:
                continue

            # Get text - may be in 'text' field directly or nested
            text = result.get("text", "")

            # Parse metadata from metadata_json field if present
            metadata = {}
            metadata_json = result.get("metadata_json", "")
            if metadata_json:
                try:
                    metadata = json.loads(metadata_json)
                except (json.JSONDecodeError, TypeError):
                    pass

            topics = metadata.get("topics", [])
            primary_topic = topics[0] if topics else None

            search_results.append(TxtaiSearchResult(
                id=str(result.get("id", "")),
                text=text,
                score=score,
                metadata=metadata,
                topics=topics,
                primary_topic=primary_topic
            ))

        return search_results[:limit]

    def keyword_search(
        self,
        query: str,
        limit: int = 10,
        min_score: float = 0.0
    ) -> List[TxtaiSearchResult]:
        """
        Keyword-only search using BM25 scoring — no vector similarity, no GPU.

        Uses txtai's BM25 scoring module directly, bypassing the embedding model
        entirely. Typical latency: <1ms.

        Args:
            query: Search query text
            limit: Maximum results to return
            min_score: Minimum BM25 score threshold

        Returns:
            List of TxtaiSearchResult objects sorted by BM25 relevance
        """
        if not self._embeddings or self._embeddings.count() == 0:
            return []

        import json

        # Use txtai's BM25 scoring module directly (no embedding model needed)
        scoring = getattr(self._embeddings, 'scoring', None)
        if not scoring:
            # Fallback to hybrid search if scoring not available
            return self._hybrid_keyword_fallback(query, limit, min_score)

        try:
            bm25_results = scoring.search(query, limit * 2)
        except Exception:
            return self._hybrid_keyword_fallback(query, limit, min_score)

        if not bm25_results:
            return []

        # Map indexid → document data via txtai's database connection
        search_results = []
        db = getattr(self._embeddings, 'database', None)
        conn = getattr(db, 'connection', None) if db else None

        if not conn:
            return self._hybrid_keyword_fallback(query, limit, min_score)

        for indexid, bm25_score in bm25_results:
            if bm25_score < min_score:
                continue

            try:
                # Resolve indexid → document id via sections table, then get full data
                row = conn.execute(
                    "SELECT s.id, d.data FROM sections s "
                    "JOIN documents d ON s.id = d.id "
                    "WHERE s.indexid = ?",
                    (indexid,)
                ).fetchone()
            except Exception:
                continue

            if not row:
                continue

            doc_id = str(row[0])
            if doc_id == self.SYSTEM_DOC_ID:
                continue

            text = ""
            metadata = {}
            try:
                data = json.loads(row[1])
                text = data.get("text", "")
                metadata_json = data.get("metadata_json", "")
                if metadata_json:
                    metadata = json.loads(metadata_json)
            except (json.JSONDecodeError, TypeError):
                pass

            search_results.append(TxtaiSearchResult(
                id=doc_id,
                text=text,
                score=bm25_score,
                metadata=metadata,
                topics=metadata.get("topics", []),
                primary_topic=(metadata.get("topics", []) or [None])[0]
            ))

        search_results.sort(key=lambda r: r.score, reverse=True)
        return search_results[:limit]

    def _hybrid_keyword_fallback(
        self,
        query: str,
        limit: int,
        min_score: float
    ) -> List[TxtaiSearchResult]:
        """Fallback keyword search using hybrid search when BM25 scoring is unavailable."""
        import json
        results = self._embeddings.search(query, limit=limit * 2)
        search_results = []
        for result in results:
            doc_id = str(result.get("id", ""))
            if doc_id == self.SYSTEM_DOC_ID:
                continue
            score = result.get("score", 0.0)
            if score < min_score:
                continue
            text = result.get("text", "")
            metadata = {}
            metadata_json = result.get("metadata_json", "")
            if metadata_json:
                try:
                    metadata = json.loads(metadata_json)
                except (json.JSONDecodeError, TypeError):
                    pass
            search_results.append(TxtaiSearchResult(
                id=doc_id, text=text, score=score, metadata=metadata,
                topics=metadata.get("topics", []),
                primary_topic=(metadata.get("topics", []) or [None])[0]
            ))
        search_results.sort(key=lambda r: r.score, reverse=True)
        return search_results[:limit]

    def metadata_search(
        self,
        limit: int = 50,
        filename: Optional[str] = None,
        source: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        topic: Optional[str] = None
    ) -> List[TxtaiSearchResult]:
        """
        Search documents by metadata fields — no vector similarity needed.

        Pure SQLite query on metadata_json, zero GPU.

        Args:
            limit: Maximum results
            filename: Glob pattern for filename (e.g., "*.pdf")
            source: Source filter (e.g., "import", "connector", "browser")
            date_from: ISO date string for minimum created_at
            date_to: ISO date string for maximum created_at
            topic: Topic to filter by

        Returns:
            List of TxtaiSearchResult objects
        """
        if not self._embeddings or self._embeddings.count() == 0:
            return []

        import json
        import fnmatch

        # Fetch all documents with metadata
        try:
            results = self._embeddings.search(
                f"SELECT id, text, metadata_json FROM txtai LIMIT {limit * 5}",
                limit=limit * 5
            )
        except Exception:
            return []

        # Parse date bounds
        date_from_ts = None
        date_to_ts = None
        if date_from:
            try:
                from datetime import datetime as dt
                date_from_ts = int(dt.fromisoformat(date_from.replace('Z', '+00:00')).timestamp() * 1000)
            except (ValueError, TypeError):
                pass
        if date_to:
            try:
                from datetime import datetime as dt
                date_to_ts = int(dt.fromisoformat(date_to.replace('Z', '+00:00')).timestamp() * 1000)
            except (ValueError, TypeError):
                pass

        search_results = []
        for result in results:
            doc_id = str(result.get("id", ""))
            if doc_id == self.SYSTEM_DOC_ID:
                continue

            text = result.get("text", "")
            metadata = {}
            metadata_json = result.get("metadata_json", "")
            if metadata_json:
                try:
                    metadata = json.loads(metadata_json)
                except (json.JSONDecodeError, TypeError):
                    pass

            # Apply filters
            if filename:
                doc_filename = metadata.get("filename", metadata.get("source_file", ""))
                if not fnmatch.fnmatch(doc_filename, filename):
                    continue

            if source:
                doc_source = metadata.get("source", metadata.get("connector_type", ""))
                if source.lower() not in doc_source.lower():
                    continue

            if date_from_ts:
                created_at = metadata.get("created_at", 0)
                if created_at < date_from_ts:
                    continue

            if date_to_ts:
                created_at = metadata.get("created_at", 0)
                if created_at > date_to_ts:
                    continue

            if topic:
                doc_topics = metadata.get("topics", [])
                if not any(topic.lower() in t.lower() for t in doc_topics):
                    continue

            topics = metadata.get("topics", [])
            search_results.append(TxtaiSearchResult(
                id=doc_id,
                text=text,
                score=1.0,  # Metadata search doesn't have relevance scores
                metadata=metadata,
                topics=topics,
                primary_topic=topics[0] if topics else None
            ))

        return search_results[:limit]

    def search_by_topic(
        self,
        query: str,
        topic: Optional[str],
        limit: int = 10,
        min_score: float = 0.0
    ) -> List[TxtaiSearchResult]:
        """
        Search with topic filter.

        Args:
            query: Search query text
            topic: Topic to filter by (if None, returns unfiltered results)
            limit: Maximum results
            min_score: Minimum similarity threshold

        Returns:
            Search results filtered by topic
        """
        # If no topic specified, fall back to regular search
        if not topic:
            return self.search(query, limit=limit, min_score=min_score)

        # Over-fetch to account for filtering
        results = self.search(query, limit=limit * 3, min_score=min_score)

        # Filter by topic
        topic_lower = topic.lower()
        filtered = [
            r for r in results
            if topic_lower in [t.lower() for t in (r.topics or [])]
        ]

        return filtered[:limit]

    def graph_search(
        self,
        query: str,
        limit: int = 10,
        graph_depth: int = 1
    ) -> Dict[str, Any]:
        """
        Graph-based search with concept traversal.

        Returns documents plus related concepts from the semantic graph.

        Args:
            query: Search query
            limit: Max results
            graph_depth: How deep to traverse the graph

        Returns:
            Dict with 'results' and 'related_concepts' keys
        """
        # Get direct search results
        results = self.search(query, limit=limit)

        # Get related concepts from graph if available
        related_concepts = []
        if hasattr(self._embeddings, 'graph') and self._embeddings.graph is not None:
            try:
                with self._write_lock:
                    # txtai graph search returns related nodes
                    graph_results = self._embeddings.graph.search(query, limit=limit)
                related_concepts = [
                    {"concept": r.get("id", ""), "score": r.get("score", 0.0)}
                    for r in graph_results
                ]
            except Exception as e:
                print(f"Graph search error: {e}")

        return {
            "results": [self._result_to_dict(r) for r in results],
            "related_concepts": related_concepts
        }

    def get_document(self, doc_id: str) -> Optional[TxtaiDocument]:
        """
        Get a document by ID.

        Args:
            doc_id: Document ID

        Returns:
            TxtaiDocument or None if not found
        """
        # Don't return system seed document
        if doc_id == self.SYSTEM_DOC_ID:
            return None

        import json
        try:
            with self._write_lock:
                # Search for exact ID match - include metadata_json in select
                safe_doc_id = str(doc_id).replace("'", "''")
                results = self._embeddings.search(f"select id, text, metadata_json from txtai where id = '{safe_doc_id}'", limit=1)
            if results:
                result = results[0]
                # Parse metadata from metadata_json field
                metadata = {}
                metadata_json = result.get("metadata_json", "")
                if metadata_json:
                    try:
                        metadata = json.loads(metadata_json)
                    except (json.JSONDecodeError, TypeError):
                        pass
                return TxtaiDocument(
                    id=str(result.get("id", "")),
                    text=result.get("text", ""),
                    metadata=metadata,
                    content_hash=metadata.get("content_hash", ""),
                    created_at=metadata.get("created_at", 0)
                )
        except Exception:
            # Fallback: iterate through index
            pass

        return None

    def delete_document(self, doc_id: str) -> bool:
        """
        Delete a document by ID.

        Args:
            doc_id: Document ID to delete

        Returns:
            True if deleted, False if not found
        """
        try:
            # Serialize write operations to prevent SQLite race conditions
            with self._write_lock:
                self._embeddings.delete([doc_id])

                # Remove from content hash tracking
                hash_to_remove = None
                for h, did in self._content_hashes.items():
                    if did == doc_id:
                        hash_to_remove = h
                        break
                if hash_to_remove:
                    del self._content_hashes[hash_to_remove]

                self._schedule_save()
            return True
        except Exception as e:
            print(f"Delete error: {e}")
            return False

    def update_document_metadata(
        self,
        doc_id: str,
        metadata_updates: Dict[str, Any],
        text: Optional[str] = None
    ) -> bool:
        """
        Update metadata for a document, optionally updating text as well.

        Args:
            doc_id: Document ID
            metadata_updates: Fields to update in metadata
            text: If provided, also replace the document text

        Returns:
            True if updated successfully
        """
        import json

        # Serialize read + write to prevent "Recursive use of cursors" SQLite error
        # when multiple documents are being extracted concurrently
        with self._write_lock:
            doc = self.get_document(doc_id)
            if not doc:
                return False

            # Merge metadata
            updated_metadata = {**doc.metadata, **metadata_updates}
            updated_metadata["updated_at"] = int(datetime.now().timestamp() * 1000)

            # Upsert with updated metadata - use same format as add_document
            doc_data = {
                "text": text if text is not None else doc.text,
                "metadata_json": json.dumps(updated_metadata)
            }

            self._embeddings.upsert([(doc_id, doc_data, None)])
            self._schedule_save()

        return True

    def update_document_topics(
        self,
        doc_id: str,
        topics: List[str],
        primary_topic: Optional[str] = None
    ) -> bool:
        """
        Update topics for a document.

        Args:
            doc_id: Document ID
            topics: List of topic strings
            primary_topic: Optional primary topic (defaults to first topic)

        Returns:
            True if updated successfully
        """
        return self.update_document_metadata(doc_id, {
            "topics": topics,
            "primary_topic": primary_topic or (topics[0] if topics else None)
        })

    def get_all_topics(self) -> List[Dict[str, Any]]:
        """
        Get all topics with document counts.

        Returns:
            List of dicts with 'topic' and 'count' keys
        """
        topic_counts: Dict[str, int] = {}

        import json
        with self._write_lock:
            # Iterate through all documents
            count = self._embeddings.count()
            if count == 0:
                return []

            # Use SQL query with metadata_json
            try:
                results = self._embeddings.search("select id, text, metadata_json from txtai", limit=count)
            except Exception:
                return []

        for result in results:
            # Parse metadata from metadata_json field
            metadata = {}
            metadata_json = result.get("metadata_json", "")
            if metadata_json:
                try:
                    metadata = json.loads(metadata_json)
                except (json.JSONDecodeError, TypeError):
                    pass
            topics = metadata.get("topics", [])
            for topic in topics:
                topic_counts[topic] = topic_counts.get(topic, 0) + 1

        return [
            {"topic": t, "count": c}
            for t, c in sorted(topic_counts.items(), key=lambda x: -x[1])
        ]

    def list_documents(
        self,
        offset: int = 0,
        limit: int = 20,
        sort_by: str = "created_at",
        sort_order: str = "desc"
    ) -> List[TxtaiDocument]:
        """
        List documents with pagination.

        Args:
            offset: Number of documents to skip
            limit: Maximum documents to return
            sort_by: Field to sort by ('created_at' or 'id')
            sort_order: 'asc' or 'desc'

        Returns:
            List of TxtaiDocument objects
        """
        import json
        with self._write_lock:
            count = self._embeddings.count()
            if count == 0:
                return []

            # Get all documents with metadata (txtai doesn't have native pagination)
            try:
                results = self._embeddings.search("select id, text, metadata_json from txtai", limit=count)
            except Exception:
                return []

        # Convert to documents (parsing happens outside lock)
        documents = []
        for result in results:
            doc_id = str(result.get("id", ""))

            # Skip system seed document
            if doc_id == self.SYSTEM_DOC_ID:
                continue

            # Parse metadata from metadata_json field
            metadata = {}
            metadata_json = result.get("metadata_json", "")
            if metadata_json:
                try:
                    metadata = json.loads(metadata_json)
                except (json.JSONDecodeError, TypeError):
                    pass
            documents.append(TxtaiDocument(
                id=doc_id,
                text=result.get("text", ""),
                metadata=metadata,
                content_hash=metadata.get("content_hash", ""),
                created_at=metadata.get("created_at", 0)
            ))

        # Sort
        reverse = sort_order.lower() == "desc"
        if sort_by == "created_at":
            documents.sort(key=lambda d: d.created_at, reverse=reverse)
        else:
            documents.sort(key=lambda d: d.id, reverse=reverse)

        # Apply pagination
        return documents[offset:offset + limit]

    def count(self) -> int:
        """Get total document count (excludes system seed document)."""
        if not self._embeddings:
            return 0
        with self._write_lock:
            raw_count = self._embeddings.count()
        # Subtract 1 for system seed document if present
        return max(0, raw_count - 1) if raw_count > 0 else 0

    def stats(self) -> Dict[str, Any]:
        """
        Get store statistics.

        Returns:
            Dict with document count, index info, etc.
        """
        return {
            "document_count": self.count(),
            "embedding_dim": self._embedding_dim,
            "hybrid_enabled": self._config.get("hybrid", False),
            "onnx_backend": self._config.get("backend") == "onnx",
            "data_dir": self.data_dir,
            "unique_content_hashes": len(self._content_hashes)
        }

    def _save_index(self):
        """Persist index to disk immediately."""
        index_path = os.path.join(self.data_dir, "index")
        self._embeddings.save(index_path)
        self._dirty = False
        self._dirty_write_count = 0

    def _schedule_save(self):
        """Schedule a deferred save to batch multiple writes.

        On Jetson Orin Nano, saving the FAISS index on every write throttles
        ingestion. Instead we mark the index dirty and flush after a short
        interval. Explicit close() always flushes immediately.
        """
        self._dirty = True
        self._dirty_write_count += 1

        # Bound durability risk during heavy ingest even if timer hasn't fired yet.
        if self._dirty_write_count >= self._max_dirty_writes:
            if self._save_timer and self._save_timer.is_alive():
                self._save_timer.cancel()
            self._flush_save()
            return

        if self._save_timer is None or not self._save_timer.is_alive():
            self._save_timer = threading.Timer(self._save_interval, self._flush_save)
            self._save_timer.daemon = True
            self._save_timer.start()

    def _flush_save(self):
        """Flush pending saves to disk."""
        if self._dirty:
            with self._write_lock:
                if self._dirty:
                    self._save_index()
                    self._save_state()

    def _result_to_dict(self, result: TxtaiSearchResult) -> Dict[str, Any]:
        """Convert TxtaiSearchResult to dict."""
        return {
            "id": result.id,
            "text": result.text,
            "score": result.score,
            "metadata": result.metadata,
            "topics": result.topics,
            "primary_topic": result.primary_topic
        }

    def close(self):
        """Close the store and release resources."""
        # Cancel any pending deferred save
        if self._save_timer and self._save_timer.is_alive():
            self._save_timer.cancel()
        if self._embeddings:
            try:
                with self._write_lock:
                    # Flush any pending writes immediately
                    if self._embeddings.count() > 0:
                        self._save_index()
                    self._save_state()
            except Exception as e:
                print(f"Warning: Error during close: {e}")
            finally:
                self._embeddings = None
