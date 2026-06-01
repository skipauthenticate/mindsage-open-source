"""
Adapter layer that maintains existing API contract while using txtai backend.

Ensures backward compatibility with:
- mcp_server_http.py endpoints
- vector-store-client.ts
- Frontend API calls

This adapter provides a consistent VectorStore API over the txtai-based
implementation with hybrid search (BM25 + semantic vectors).
"""

import os
import math
import time
import hashlib
from collections import OrderedDict
from typing import List, Optional, Dict, Any, Tuple, TYPE_CHECKING
from dataclasses import dataclass
from datetime import datetime

import numpy as np

from .txtai_store import TxtaiStore, TxtaiDocument, TxtaiSearchResult, compute_content_hash

if TYPE_CHECKING:
    from .async_extractor import AsyncExtractor
    from .pii_protection import PIIProtector


# =============================================================================
# Result Classes (matching existing API)
# =============================================================================

@dataclass
class AddDocumentResult:
    """Result from adding a document, includes duplicate detection info."""
    doc_id: Optional[int]
    is_duplicate: bool
    existing_doc_id: Optional[int] = None
    content_hash: Optional[str] = None
    chunk_ids: Optional[List[int]] = None


@dataclass
class ChunkInfo:
    """Information about a document chunk."""
    chunk_id: int
    parent_id: int
    chunk_index: int
    char_start: int
    char_end: int
    text: str
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class SearchResult:
    """Result from a vector search."""
    id: int
    text: str
    score: float
    metadata: Optional[Dict[str, Any]] = None
    topics: Optional[List[str]] = None
    primary_topic: Optional[str] = None


@dataclass
class EnhancedSearchResult:
    """Enhanced result from vector search with excerpt extraction."""
    id: int
    text: str
    excerpt: str
    score: float
    metadata: Optional[Dict[str, Any]] = None
    topics: Optional[List[str]] = None
    primary_topic: Optional[str] = None
    excerpt_method: str = "full"


@dataclass
class DocumentResult:
    """Document with metadata for retrieval."""
    id: int
    text: str
    metadata: Optional[Dict[str, Any]] = None
    created_at: int = 0
    topics: Optional[List[str]] = None
    primary_topic: Optional[str] = None

    @property
    def created_datetime(self) -> datetime:
        """Get creation time as datetime object."""
        return datetime.fromtimestamp(self.created_at / 1000.0)


@dataclass
class PaginatedResult:
    """Paginated document results."""
    documents: List[DocumentResult]
    total: int
    page: int
    page_size: int
    total_pages: int
    has_next: bool
    has_prev: bool


# =============================================================================
# Embedding Wrapper (uses txtai's internal model)
# =============================================================================

class TxtaiEmbeddingWrapper:
    """Thin wrapper around txtai's internal embedding model.

    Provides the same embed()/embed_query()/get_dimension() interface as
    EmbeddingModel, but delegates to txtai's Embeddings.batchtransform().
    This avoids loading a duplicate model on GPU.
    """

    def __init__(self, txtai_embeddings, embedding_dim: int = 384, db_lock=None):
        self._embeddings = txtai_embeddings
        self._db_lock = db_lock
        self.embedding_dim = embedding_dim
        self.device = "cuda" if txtai_embeddings.config.get("gpu") else "cpu"
        self.model_name = txtai_embeddings.config.get("path", "unknown")
        self._is_loaded = True

        # Query cache (same as EmbeddingModel)
        self._cache: OrderedDict[str, Tuple[np.ndarray, float]] = OrderedDict()
        self._cache_max_size = 1000
        self._cache_ttl = 3600
        self._cache_hits = 0
        self._cache_misses = 0

    def embed(self, texts) -> np.ndarray:
        """Generate embeddings for text(s). Returns (n, dim) ndarray."""
        if isinstance(texts, str):
            texts = [texts]
        if self._db_lock:
            with self._db_lock:
                return np.array(self._embeddings.batchtransform(texts))
        return np.array(self._embeddings.batchtransform(texts))

    def embed_query(self, query: str, use_cache: bool = True) -> np.ndarray:
        """Generate embedding for a search query with caching. Returns (dim,) ndarray."""
        if use_cache:
            key = hashlib.md5(query.encode('utf-8')).hexdigest()
            if key in self._cache:
                emb, ts = self._cache[key]
                if time.time() - ts < self._cache_ttl:
                    self._cache.move_to_end(key)
                    self._cache_hits += 1
                    return emb
                del self._cache[key]
            self._cache_misses += 1

        embedding = self.embed(query)[0]

        if use_cache:
            while len(self._cache) >= self._cache_max_size:
                self._cache.popitem(last=False)
            self._cache[key] = (embedding.copy(), time.time())

        return embedding

    def get_dimension(self) -> int:
        return self.embedding_dim

    def get_cache_stats(self) -> dict:
        total = self._cache_hits + self._cache_misses
        return {
            "hits": self._cache_hits,
            "misses": self._cache_misses,
            "size": len(self._cache),
            "max_size": self._cache_max_size,
            "hit_rate": self._cache_hits / total if total > 0 else 0.0,
            "ttl_seconds": self._cache_ttl
        }

    def clear_cache(self) -> None:
        self._cache.clear()
        self._cache_hits = 0
        self._cache_misses = 0

    def is_loaded(self) -> bool:
        return self._is_loaded

    def unload(self) -> None:
        pass  # txtai manages its own model lifecycle

    def reload(self) -> None:
        pass  # txtai manages its own model lifecycle


# =============================================================================
# Adapter Implementation
# =============================================================================

class TxtaiAdapter:
    """
    Vector store adapter providing unified API over txtai backend.

    Provides hybrid search (BM25 + semantic vectors) with:
    - Same method signatures as VectorStore API
    - Same return types (dataclasses)
    - Same metadata format
    - Integer IDs (mapped from txtai string IDs)
    """

    # Chunking thresholds
    # - CHUNK_THRESHOLD: Documents larger than this are split into chunks
    # - CHUNK_SIZE: Target size for each chunk (~250 tokens, safe for all embedding models)
    # - CHUNK_OVERLAP: Overlap between chunks for context continuity
    CHUNK_THRESHOLD = 2000
    CHUNK_SIZE = 1000
    CHUNK_OVERLAP = 150

    def __init__(
        self,
        db_path: str = "./data/txtai",
        embedding_dim: int = None,
        skip_duplicates: bool = True,
        auto_chunk_large_docs: bool = True,
        use_onnx: bool = True
    ):
        """
        Initialize the txtai adapter.

        Args:
            db_path: Path to txtai data directory
            embedding_dim: Expected embedding dimension (for validation)
            skip_duplicates: Skip adding documents with identical content
            auto_chunk_large_docs: Automatically chunk large documents
            use_onnx: Use ONNX backend for inference
        """
        self.db_path = db_path
        self.skip_duplicates = skip_duplicates
        self.auto_chunk_large_docs = auto_chunk_large_docs

        # Initialize txtai store
        self._store = TxtaiStore(
            data_dir=db_path,
            use_onnx=use_onnx,
            skip_duplicates=skip_duplicates
        )

        # Validate embedding dimension if specified
        if embedding_dim is not None and embedding_dim != self._store.embedding_dim:
            print(f"Warning: Requested dim {embedding_dim}, txtai using {self._store.embedding_dim}")

        self.embedding_dim = self._store.embedding_dim

        # Optional components (lazily loaded)
        self._extractor: Optional['AsyncExtractor'] = None
        self._pii_protector: Optional['PIIProtector'] = None

    def get_embedding_wrapper(self) -> TxtaiEmbeddingWrapper:
        """Get an embedding wrapper that delegates to txtai's internal model.

        Returns a TxtaiEmbeddingWrapper with the same embed()/embed_query()
        API as EmbeddingModel, so TopicLabeler and PassageExtractor can use it
        without loading a separate model.
        """
        return TxtaiEmbeddingWrapper(
            self._store._embeddings,
            embedding_dim=self.embedding_dim,
            db_lock=self._store._write_lock
        )

    def _str_to_int_id(self, str_id: str) -> int:
        """Convert string ID to integer."""
        try:
            return int(str_id)
        except (ValueError, TypeError):
            # Hash-based fallback for non-numeric IDs
            return abs(hash(str_id)) % (10 ** 9)

    def _int_to_str_id(self, int_id: int) -> str:
        """Convert integer ID to string."""
        return str(int_id)

    def _resolve_doc_id(self, doc_id) -> int:
        """Resolve a doc_id from either an int or AddDocumentResult.

        This allows callers to pass the return value of add_document() directly
        to methods like get_document(), delete_document(), etc.
        """
        if isinstance(doc_id, AddDocumentResult):
            return doc_id.doc_id
        return int(doc_id)

    # =========================================================================
    # Document Management (matching VectorStore API)
    # =========================================================================

    def add_document(
        self,
        text: str,
        embedding: Any = None,  # Ignored - txtai generates embeddings
        metadata: Optional[Dict[str, Any]] = None,
        skip_extraction: bool = False,
        # Compatibility params (ignored - txtai handles these internally)
        embedding_model: Any = None,
        skip_duplicates: bool = None,
        topic_labeler: Any = None,
        extract_key_passages: bool = False,
        passage_extractor: Any = None,
        **kwargs  # Accept any additional kwargs for compatibility
    ) -> AddDocumentResult:
        """
        Add a document to the store.

        Args:
            text: Document text content
            embedding: Ignored (txtai handles embedding generation)
            metadata: Optional metadata dictionary
            skip_extraction: If True, skip async extraction queuing
            embedding_model: Ignored (for API compatibility)
            skip_duplicates: Ignored (txtai always checks duplicates)
            topic_labeler: Ignored (for API compatibility)
            extract_key_passages: Ignored (for API compatibility)
            passage_extractor: Ignored (for API compatibility)

        Returns:
            AddDocumentResult with document ID and duplicate info.
            For chunked documents, includes chunk_ids.
        """
        source = (metadata or {}).get("source", "")
        content_hash = compute_content_hash(text, source=source)

        # Handle chunking for large documents
        if self.auto_chunk_large_docs and len(text) > self.CHUNK_THRESHOLD:
            return self._add_chunked_document(
                text, metadata, content_hash, skip_extraction,
                extract_key_passages=extract_key_passages,
                passage_extractor=passage_extractor,
                **kwargs
            )

        # Prepare metadata with embedding source tracking
        doc_metadata = dict(metadata) if metadata else {}

        # Extract key passages if requested
        if extract_key_passages and passage_extractor is not None:
            try:
                passages = passage_extractor.extract_key_sentences(text, max_sentences=3)
                if passages:
                    doc_metadata["key_passages"] = passages
                    doc_metadata["embedding_source"] = "key_passages"
            except Exception:
                pass

        # Set default embedding source if not already set
        if "embedding_source" not in doc_metadata:
            doc_metadata["embedding_source"] = "full_text"

        # Extract key entities if requested
        if kwargs.get("extract_key_entities") and passage_extractor is not None:
            try:
                max_entities = kwargs.get("max_key_entities", 10)
                entities = passage_extractor.extract_key_entities(text, max_entities=max_entities)
                if entities:
                    doc_metadata["entities"] = entities
            except Exception:
                pass

        # Add single document
        doc_id, is_duplicate = self._store.add_document(
            text=text,
            metadata=doc_metadata
        )

        int_id = self._str_to_int_id(doc_id)

        if is_duplicate:
            return AddDocumentResult(
                doc_id=None,
                is_duplicate=True,
                existing_doc_id=int_id,
                content_hash=content_hash
            )

        # Queue for async extraction if not skipped
        if not skip_extraction and self._extractor:
            self._extractor.queue_extraction(int_id, text)

        return AddDocumentResult(
            doc_id=int_id,
            is_duplicate=False,
            content_hash=content_hash
        )

    def _add_chunked_document(
        self,
        text: str,
        metadata: Optional[Dict[str, Any]],
        content_hash: str,
        skip_extraction: bool,
        extract_key_passages: bool = False,
        passage_extractor: Any = None,
        **kwargs
    ) -> AddDocumentResult:
        """Add a large document as multiple chunks."""
        chunks = self._create_chunks(text)
        chunk_ids = []

        # Add parent document with full text (chunks handle semantic search)
        parent_metadata = {
            **(metadata or {}),
            "is_parent": True,
            "chunk_count": len(chunks),
            "full_text_length": len(text),
            "embedding_source": "full_text"
        }
        parent_id, is_dup = self._store.add_document(
            text=text,  # Store full text - txtai handles embedding truncation internally
            metadata=parent_metadata
        )

        if is_dup:
            return AddDocumentResult(
                doc_id=None,
                is_duplicate=True,
                existing_doc_id=self._str_to_int_id(parent_id),
                content_hash=content_hash
            )

        parent_int_id = self._str_to_int_id(parent_id)

        # Add chunks — skip dedup since chunks are positional fragments
        # of the parent and may have identical text (e.g., repeated content)
        for i, chunk in enumerate(chunks):
            chunk_metadata = {
                **(metadata or {}),
                "parent_id": parent_int_id,
                "chunk_index": i,
                "char_start": chunk["start"],
                "char_end": chunk["end"],
                "is_chunk": True,
                "embedding_source": "full_text"
            }

            # Extract key passages per chunk if requested
            if extract_key_passages and passage_extractor is not None:
                try:
                    passages = passage_extractor.extract_key_sentences(
                        chunk["text"], max_sentences=2
                    )
                    if passages:
                        chunk_metadata["key_passages"] = passages
                        chunk_metadata["embedding_source"] = "key_passages"
                except Exception:
                    pass

            chunk_id, _ = self._store.add_document(
                text=chunk["text"],
                metadata=chunk_metadata,
                skip_dedup=True
            )
            chunk_ids.append(self._str_to_int_id(chunk_id))

        # Update parent metadata with chunk_ids for reference
        self._store.update_document_metadata(
            self._int_to_str_id(parent_int_id),
            {"chunk_ids": chunk_ids}
        )

        # Queue parent for extraction
        if not skip_extraction and self._extractor:
            self._extractor.queue_extraction(parent_int_id, text)

        return AddDocumentResult(
            doc_id=parent_int_id,
            is_duplicate=False,
            content_hash=content_hash,
            chunk_ids=chunk_ids
        )

    def _create_chunks(self, text: str) -> List[Dict[str, Any]]:
        """Create overlapping chunks from text."""
        chunks = []
        start = 0

        while start < len(text):
            end = min(start + self.CHUNK_SIZE, len(text))

            # Try to break at sentence boundary
            if end < len(text):
                # Look for sentence end within last 20% of chunk
                search_start = start + int(self.CHUNK_SIZE * 0.8)
                for i in range(end, search_start, -1):
                    if text[i] in '.!?\n':
                        end = i + 1
                        break

            chunks.append({
                "text": text[start:end],
                "start": start,
                "end": end
            })

            # Move start with overlap
            start = end - self.CHUNK_OVERLAP
            if start >= len(text) - self.CHUNK_OVERLAP:
                break

        return chunks

    def add_documents(
        self,
        documents: List[Tuple[str, Any, Optional[Dict[str, Any]]]],
        skip_extraction: bool = False
    ) -> List[AddDocumentResult]:
        """
        Add multiple documents in batch.

        Args:
            documents: List of (text, embedding, metadata) tuples
            skip_extraction: If True, skip async extraction

        Returns:
            List of AddDocumentResult objects
        """
        results = []
        for text, _, metadata in documents:
            result = self.add_document(
                text=text,
                metadata=metadata,
                skip_extraction=skip_extraction
            )
            results.append(result)
        return results

    # =========================================================================
    # Search (matching VectorStore API)
    # =========================================================================

    def search(
        self,
        query: str,
        query_embedding: Any = None,  # Ignored
        limit: int = 10,
        min_score: float = 0.0,
        exclude_chunks: bool = False,
        deduplicate_chunks: bool = False,
        entity_boost: float = 0.0,
        weights: float = None,
        # Compatibility params (ignored - txtai handles these internally)
        embedding_model: Any = None,
        top_k: int = None,  # Alias for limit
        **kwargs
    ) -> List[SearchResult]:
        """
        Search for similar documents.

        Args:
            query: Search query text
            query_embedding: Ignored (txtai handles embedding)
            limit: Maximum results
            min_score: Minimum similarity threshold
            exclude_chunks: If True, only return parent documents
            deduplicate_chunks: If True, deduplicate chunks by parent_id
            entity_boost: Score boost for matching entities (0.0 = disabled)
            weights: Hybrid fusion weights (0.0=keyword, 0.5=balanced, 1.0=semantic).
                     None uses txtai default. Passed to txtai's native hybrid fusion.
            embedding_model: Ignored (for API compatibility)
            top_k: Alias for limit (for API compatibility)

        Returns:
            List of SearchResult objects
        """
        # Handle top_k alias
        if top_k is not None:
            limit = top_k
        # Handle None min_score
        if min_score is None:
            min_score = 0.0
        results = self._store.search(
            query=query,
            limit=limit * 2 if (exclude_chunks or deduplicate_chunks) else limit,
            min_score=min_score,
            weights=weights
        )

        # Extract query terms for entity matching
        query_terms = set(query.lower().split()) if entity_boost > 0 else set()

        search_results = []
        seen_ids = set()  # Track final result IDs for deduplication
        for r in results:
            # Skip chunks if requested
            if exclude_chunks and r.metadata.get("is_chunk"):
                continue

            result_id = self._str_to_int_id(r.id)
            result_metadata = dict(r.metadata) if r.metadata else {}
            result_score = r.score

            # Apply entity boost if enabled
            if entity_boost > 0 and query_terms:
                matched_entities = []
                boost = 0.0

                # Check key_entities
                key_entities = result_metadata.get("entities", [])
                if isinstance(key_entities, list):
                    for entity in key_entities:
                        entity_lower = entity.lower() if isinstance(entity, str) else ""
                        if any(term in entity_lower for term in query_terms):
                            matched_entities.append(entity)

                # Check key_passages for query term matches
                key_passages = result_metadata.get("key_passages", [])
                if isinstance(key_passages, list):
                    for passage in key_passages:
                        passage_lower = passage.lower() if isinstance(passage, str) else ""
                        passage_terms = set(passage_lower.split())
                        overlap = query_terms & passage_terms
                        if overlap:
                            boost += entity_boost * 0.5 * len(overlap)

                if matched_entities:
                    boost += entity_boost * len(matched_entities)

                result_metadata["vector_score"] = result_score
                result_metadata["entity_boost"] = round(boost, 4)
                result_metadata["matched_entities"] = matched_entities
                result_score = result_score + boost

            # Map chunk results to parent ID for consistent document reference
            if result_metadata.get("is_chunk") and result_metadata.get("parent_id"):
                result_id = result_metadata["parent_id"]

            # Deduplicate by final result ID (handles both chunk→parent mapping
            # and parent+chunk both appearing for the same document)
            if deduplicate_chunks:
                if result_id in seen_ids:
                    continue
                seen_ids.add(result_id)

            search_results.append(SearchResult(
                id=result_id,
                text=r.text,
                score=result_score,
                metadata=result_metadata,
                topics=r.topics,
                primary_topic=r.primary_topic
            ))

        # Re-sort after boost
        if entity_boost > 0:
            search_results.sort(key=lambda x: x.score, reverse=True)

        return search_results[:limit]

    def search_enhanced(
        self,
        query: str,
        limit: int = 10,
        min_score: float = 0.0,
        extract_method: str = "precomputed"
    ) -> List[EnhancedSearchResult]:
        """
        Enhanced search with excerpt extraction.

        Args:
            query: Search query text
            limit: Maximum results
            min_score: Minimum similarity threshold
            extract_method: How to extract excerpts

        Returns:
            List of EnhancedSearchResult objects
        """
        results = self.search(query, limit=limit, min_score=min_score)

        enhanced_results = []
        for r in results:
            # Use pre-extracted key passages if available
            key_passages = r.metadata.get("key_passages", []) if r.metadata else []

            if key_passages:
                excerpt = key_passages[0]
                method = "precomputed"
            elif len(r.text) <= 500:
                excerpt = r.text
                method = "full"
            else:
                excerpt = r.text[:500]
                method = "truncate"

            enhanced_results.append(EnhancedSearchResult(
                id=r.id,
                text=r.text,
                excerpt=excerpt,
                score=r.score,
                metadata=r.metadata,
                topics=r.topics,
                primary_topic=r.primary_topic,
                excerpt_method=method
            ))

        return enhanced_results

    # Alias for API compatibility
    def enhanced_search(
        self,
        query: str,
        limit: int = 10,
        min_score: float = 0.0,
        extract_method: str = "precomputed",
        embedding_model: Any = None,
        top_k: int = None,
        extract_passages: bool = False,
        reranker: Any = None,
        rerank_top_k: int = None,
        **kwargs
    ) -> List[EnhancedSearchResult]:
        """Alias for search_enhanced for API compatibility.

        When a reranker is provided, over-fetches results and re-sorts
        by cross-encoder score so the final top-K are properly ranked.
        """
        if top_k is not None:
            limit = top_k
        if min_score is None:
            min_score = 0.0

        # Over-fetch when reranking so the reranker sees enough candidates
        fetch_limit = rerank_top_k if (reranker and rerank_top_k) else limit

        results = self.search_enhanced(
            query=query,
            limit=fetch_limit,
            min_score=min_score,
            extract_method=extract_method
        )

        # Apply cross-encoder reranking if available
        if reranker and results:
            try:
                if hasattr(reranker, "rerank"):
                    # Preferred path: Reranker wrapper interface used in production.
                    documents = [(r.id, r.text, r.score, r.metadata) for r in results]
                    reranked = reranker.rerank(
                        query=query,
                        documents=documents,
                        top_k=len(results),
                    )
                    score_by_id = {str(item.id): float(item.rerank_score) for item in reranked}
                    for r in results:
                        if str(r.id) in score_by_id:
                            r.score = score_by_id[str(r.id)]
                elif hasattr(reranker, "predict"):
                    # Backward compatibility for direct CrossEncoder-style mocks.
                    pairs = [(query, r.text) for r in results]
                    scores = reranker.predict(pairs)
                    for r, score in zip(results, scores):
                        r.score = float(score)
                else:
                    raise AttributeError("Reranker must provide rerank(...) or predict(...)")
                results.sort(key=lambda r: r.score, reverse=True)
            except Exception as e:
                print(f"Reranker failed, falling back to original scores: {e}")

        return results[:limit]

    def search_with_topic_filter(
        self,
        query: str,
        topic: str,
        limit: int = 10,
        min_score: float = 0.0,
        # Compatibility params
        embedding_model: Any = None,
        top_k: int = None,
        **kwargs
    ) -> List[SearchResult]:
        """
        Search with topic filter.

        Args:
            query: Search query
            topic: Topic to filter by
            limit: Maximum results
            min_score: Minimum similarity

        Returns:
            Search results filtered by topic
        """
        if top_k is not None:
            limit = top_k
        if min_score is None:
            min_score = 0.0
        results = self._store.search_by_topic(
            query=query,
            topic=topic,
            limit=limit,
            min_score=min_score
        )

        return [
            SearchResult(
                id=self._str_to_int_id(r.id),
                text=r.text,
                score=r.score,
                metadata=r.metadata,
                topics=r.topics,
                primary_topic=r.primary_topic
            )
            for r in results
        ]

    def search_hybrid(
        self,
        query: str,
        limit: int = 10,
        keyword_weight: float = 0.3,
        semantic_weight: float = 0.7
    ) -> List[SearchResult]:
        """
        NEW: Explicit hybrid search with weight control.

        Args:
            query: Search query
            limit: Maximum results
            keyword_weight: Weight for BM25 keyword matching
            semantic_weight: Weight for semantic similarity

        Returns:
            Combined search results
        """
        # txtai handles hybrid internally, weights configurable in config
        return self.search(query, limit=limit)

    def search_keyword(
        self,
        query: str,
        limit: int = 10,
        min_score: float = 0.0
    ) -> List[SearchResult]:
        """
        Keyword-only search using FTS5/BM25 — no vector similarity.

        Fast search mode: zero GPU, <5ms latency.

        Args:
            query: Search query text
            limit: Maximum results
            min_score: Minimum BM25 score threshold

        Returns:
            List of SearchResult objects
        """
        results = self._store.keyword_search(
            query=query,
            limit=limit,
            min_score=min_score
        )

        return [
            SearchResult(
                id=self._str_to_int_id(r.id),
                text=r.text,
                score=r.score,
                metadata=r.metadata,
                topics=r.topics,
                primary_topic=r.primary_topic
            )
            for r in results
        ]

    def search_metadata(
        self,
        limit: int = 50,
        filename: str = None,
        source: str = None,
        date_from: str = None,
        date_to: str = None,
        topic: str = None
    ) -> List[SearchResult]:
        """
        Search documents by metadata fields — no vector similarity.

        Args:
            limit: Maximum results
            filename: Glob pattern for filename (e.g., "*.pdf")
            source: Source filter
            date_from: ISO date string
            date_to: ISO date string
            topic: Topic filter

        Returns:
            List of SearchResult objects
        """
        results = self._store.metadata_search(
            limit=limit,
            filename=filename,
            source=source,
            date_from=date_from,
            date_to=date_to,
            topic=topic
        )

        return [
            SearchResult(
                id=self._str_to_int_id(r.id),
                text=r.text,
                score=r.score,
                metadata=r.metadata,
                topics=r.topics,
                primary_topic=r.primary_topic
            )
            for r in results
        ]

    def search_reranked(
        self,
        query: str,
        limit: int = 10,
        min_score: float = 0.0,
        overfetch_factor: int = 3,
        reranker=None,
        deduplicate_chunks: bool = True
    ) -> List[SearchResult]:
        """
        Two-phase coarse-to-fine search: broad hybrid retrieval + cross-encoder reranking.

        Phase 1: Over-fetch candidates with hybrid search (BM25 + semantic).
        Phase 2: Rerank with cross-encoder for higher precision top-K.

        Args:
            query: Search query text
            limit: Final number of results to return
            min_score: Minimum similarity threshold for phase 1
            overfetch_factor: Multiply limit by this for phase 1 candidates (default 3)
            reranker: Reranker instance. If None, falls back to plain search.
            deduplicate_chunks: If True, deduplicate chunks by parent_id

        Returns:
            List of SearchResult objects, reranked by cross-encoder score
        """
        # Phase 1: Broad retrieval
        candidates = self.search(
            query=query,
            limit=limit * overfetch_factor,
            min_score=min_score,
            deduplicate_chunks=deduplicate_chunks
        )

        if not reranker or not candidates:
            return candidates[:limit]

        # Phase 2: Cross-encoder reranking
        docs_for_rerank = [
            (r.id, r.text, r.score, r.metadata)
            for r in candidates
        ]

        reranked = reranker.rerank(query, docs_for_rerank, top_k=limit)

        # Build lookup for topic info by (id, text) since reranker reorders results
        topic_lookup = {(r.id, r.text[:100]): (r.topics, r.primary_topic) for r in candidates}

        return [
            SearchResult(
                id=rr.id,
                text=rr.text,
                score=rr.rerank_score,
                metadata=rr.metadata,
                topics=topic_lookup.get((rr.id, rr.text[:100]), (None, None))[0],
                primary_topic=topic_lookup.get((rr.id, rr.text[:100]), (None, None))[1]
            )
            for rr in reranked
        ]

    def graph_search(
        self,
        query: str,
        limit: int = 10,
        depth: int = 1
    ) -> Dict[str, Any]:
        """
        NEW: Graph-based search with concept traversal.

        Args:
            query: Search query
            limit: Maximum results
            depth: Graph traversal depth

        Returns:
            Dict with 'results' and 'related_concepts'
        """
        result = self._store.graph_search(query, limit=limit, graph_depth=depth)

        # Convert results to SearchResult format
        search_results = [
            SearchResult(
                id=self._str_to_int_id(r["id"]),
                text=r["text"],
                score=r["score"],
                metadata=r.get("metadata"),
                topics=r.get("topics"),
                primary_topic=r.get("primary_topic")
            )
            for r in result["results"]
        ]

        return {
            "results": search_results,
            "related_concepts": result.get("related_concepts", [])
        }

    # =========================================================================
    # Document Retrieval (matching VectorStore API)
    # =========================================================================

    def get_document(self, doc_id) -> Optional[DocumentResult]:
        """Get a document by ID (accepts int or AddDocumentResult)."""
        doc_id = self._resolve_doc_id(doc_id)
        doc = self._store.get_document(self._int_to_str_id(doc_id))
        if not doc:
            return None

        return DocumentResult(
            id=self._str_to_int_id(doc.id),
            text=doc.text,
            metadata=doc.metadata,
            created_at=doc.created_at,
            topics=doc.metadata.get("topics", []),
            primary_topic=doc.metadata.get("primary_topic")
        )

    def get_document_chunks(self, parent_id) -> List[ChunkInfo]:
        """Get chunks for a parent document (accepts int or AddDocumentResult)."""
        parent_id = self._resolve_doc_id(parent_id)
        # Search for chunks with this parent
        all_docs = self._store.list_documents(limit=10000)
        chunks = []

        for doc in all_docs:
            if doc.metadata.get("parent_id") == parent_id:
                chunks.append(ChunkInfo(
                    chunk_id=self._str_to_int_id(doc.id),
                    parent_id=parent_id,
                    chunk_index=doc.metadata.get("chunk_index", 0),
                    char_start=doc.metadata.get("char_start", 0),
                    char_end=doc.metadata.get("char_end", 0),
                    text=doc.text,
                    metadata=doc.metadata
                ))

        chunks.sort(key=lambda c: c.chunk_index)
        return chunks

    def delete_document(self, doc_id) -> bool:
        """Delete a document and its chunks (accepts int or AddDocumentResult)."""
        doc_id = self._resolve_doc_id(doc_id)
        # Delete chunks first
        chunks = self.get_document_chunks(doc_id)
        for chunk in chunks:
            self._store.delete_document(self._int_to_str_id(chunk.chunk_id))

        # Delete parent
        return self._store.delete_document(self._int_to_str_id(doc_id))

    def extract_passages_for_document(
        self,
        doc_id=None,
        passage_extractor: Any = None,
        embedding_model: Any = None
    ) -> bool:
        """Extract key passages for an existing document and update its metadata.

        Args:
            doc_id: Document ID (accepts int or AddDocumentResult)
            passage_extractor: PassageExtractor instance
            embedding_model: Ignored (for API compatibility)

        Returns:
            True if passages were extracted and metadata updated
        """
        doc_id = self._resolve_doc_id(doc_id)
        doc = self.get_document(doc_id)
        if not doc:
            return False

        if passage_extractor is None:
            return False

        # Extract key sentences as passages
        passages = passage_extractor.extract_key_sentences(doc.text, max_sentences=3)
        if not passages:
            return False

        # Update document metadata with extracted passages
        self._store.update_document_metadata(
            self._int_to_str_id(doc_id),
            {
                "key_passages": passages,
                "embedding_source": "key_passages"
            }
        )

        return True

    def clear_all_documents(self) -> dict:
        """Delete all documents from the store.

        Returns:
            dict with 'deleted_count' and 'success' status
        """
        # Collect all doc IDs first (closes cursor), then batch delete
        all_docs = self._store.list_documents(limit=100000)
        all_ids = [doc.id for doc in all_docs]
        deleted_count = len(all_ids)

        if all_ids:
            # Batch delete via txtai - single operation, no cursor conflict
            with self._store._write_lock:
                self._store._embeddings.delete(all_ids)
                # Clear content hash tracking
                self._store._content_hashes.clear()
                self._store._save_state()

        return {
            "success": True,
            "deleted_count": deleted_count
        }

    def list_documents(
        self,
        page: int = 1,
        page_size: int = 20,
        sort_by: str = "created_at",
        sort_order: str = "desc",
        exclude_chunks: bool = True
    ) -> PaginatedResult:
        """
        List documents with pagination.

        Args:
            page: Page number (1-indexed)
            page_size: Documents per page
            sort_by: Field to sort by
            sort_order: 'asc' or 'desc'
            exclude_chunks: If True, only return parent documents

        Returns:
            PaginatedResult with documents and pagination info
        """
        # Get all documents
        all_docs = self._store.list_documents(
            offset=0,
            limit=100000,
            sort_by=sort_by,
            sort_order=sort_order
        )

        # Filter chunks if requested
        if exclude_chunks:
            all_docs = [d for d in all_docs if not d.metadata.get("is_chunk")]

        total = len(all_docs)
        total_pages = math.ceil(total / page_size) if total > 0 else 1

        # Apply pagination
        offset = (page - 1) * page_size
        page_docs = all_docs[offset:offset + page_size]

        documents = [
            DocumentResult(
                id=self._str_to_int_id(d.id),
                text=d.text,
                metadata=d.metadata,
                created_at=d.created_at,
                topics=d.metadata.get("topics", []),
                primary_topic=d.metadata.get("primary_topic")
            )
            for d in page_docs
        ]

        return PaginatedResult(
            documents=documents,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
            has_next=page < total_pages,
            has_prev=page > 1
        )

    def get_all_documents(
        self,
        ascending: bool = False,
        exclude_chunks: bool = True
    ) -> List[DocumentResult]:
        """
        Get all documents (for extraction recovery and batch operations).

        Args:
            ascending: If True, sort by created_at ascending (oldest first)
            exclude_chunks: If True, only return parent documents

        Returns:
            List of DocumentResult objects
        """
        sort_order = "asc" if ascending else "desc"
        all_docs = self._store.list_documents(
            offset=0,
            limit=100000,
            sort_by="created_at",
            sort_order=sort_order
        )

        # Filter chunks if requested
        if exclude_chunks:
            all_docs = [d for d in all_docs if not d.metadata.get("is_chunk")]

        return [
            DocumentResult(
                id=self._str_to_int_id(d.id),
                text=d.text,
                metadata=d.metadata,
                created_at=d.created_at,
                topics=d.metadata.get("topics", []),
                primary_topic=d.metadata.get("primary_topic")
            )
            for d in all_docs
        ]

    def get_documents_chronological(
        self,
        page: int = 1,
        page_size: int = 20,
        ascending: bool = False,
        exclude_chunks: bool = True
    ) -> PaginatedResult:
        """
        Get documents in chronological order with pagination.

        Args:
            page: Page number (1-indexed)
            page_size: Documents per page
            ascending: If True, oldest first; False = newest first
            exclude_chunks: If True, only return parent documents

        Returns:
            PaginatedResult with documents and pagination info
        """
        sort_order = "asc" if ascending else "desc"
        return self.list_documents(
            page=page,
            page_size=page_size,
            sort_by="created_at",
            sort_order=sort_order,
            exclude_chunks=exclude_chunks
        )

    # =========================================================================
    # Document Updates (matching VectorStore API)
    # =========================================================================

    def update_document_metadata(
        self,
        doc_id: int,
        metadata_updates: Dict[str, Any],
        text: Optional[str] = None
    ) -> bool:
        """
        Update metadata for a document, optionally updating text as well.

        Args:
            doc_id: Document ID (integer)
            metadata_updates: Fields to update in metadata
            text: If provided, also replace the document text

        Returns:
            True if updated successfully
        """
        return self._store.update_document_metadata(
            self._int_to_str_id(doc_id),
            metadata_updates,
            text=text
        )

    # =========================================================================
    # Topics (matching VectorStore API)
    # =========================================================================

    def update_document_topics(
        self,
        doc_id,
        topics: List[str],
        primary_topic: Optional[str] = None
    ) -> bool:
        """Update topics for a document (accepts int or AddDocumentResult)."""
        doc_id = self._resolve_doc_id(doc_id)
        return self._store.update_document_topics(
            self._int_to_str_id(doc_id),
            topics,
            primary_topic
        )

    def get_document_topics(self, doc_id) -> Optional[Dict[str, Any]]:
        """Get topics for a document (accepts int or AddDocumentResult)."""
        doc_id = self._resolve_doc_id(doc_id)
        doc = self.get_document(doc_id)
        if not doc:
            return None
        return {
            "topics": doc.topics or [],
            "primary_topic": doc.primary_topic
        }

    def get_all_topics(self) -> Dict[str, int]:
        """Get all topics with document counts as dict."""
        topic_list = self._store.get_all_topics()
        # Convert list of {"topic": t, "count": c} to dict {t: c}
        return {item["topic"]: item["count"] for item in topic_list}

    def get_documents_by_topic(
        self,
        topic: str,
        page: int = 1,
        page_size: int = 20
    ) -> PaginatedResult:
        """Get documents with a specific topic."""
        all_docs = self._store.list_documents(limit=100000)

        # Filter by topic
        matching = [
            d for d in all_docs
            if topic.lower() in [t.lower() for t in d.metadata.get("topics", [])]
        ]

        total = len(matching)
        total_pages = math.ceil(total / page_size) if total > 0 else 1

        offset = (page - 1) * page_size
        page_docs = matching[offset:offset + page_size]

        documents = [
            DocumentResult(
                id=self._str_to_int_id(d.id),
                text=d.text,
                metadata=d.metadata,
                created_at=d.created_at,
                topics=d.metadata.get("topics", []),
                primary_topic=d.metadata.get("primary_topic")
            )
            for d in page_docs
        ]

        return PaginatedResult(
            documents=documents,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
            has_next=page < total_pages,
            has_prev=page > 1
        )

    # =========================================================================
    # Statistics (matching VectorStore API)
    # =========================================================================

    def get_stats(self) -> Dict[str, Any]:
        """Get store statistics."""
        stats = self._store.stats()
        return {
            "total_documents": stats["document_count"],
            "embedding_dimension": stats["embedding_dim"],
            "hybrid_search_enabled": stats["hybrid_enabled"],
            "onnx_backend": stats["onnx_backend"],
            "db_path": stats["data_dir"]
        }

    def count(self) -> int:
        """Get total document count."""
        return self._store.count()

    # =========================================================================
    # Knowledge Graph
    # =========================================================================

    def _find_docs_by_entity(
        self,
        entity_field: str,
        entity_name: str
    ) -> List[DocumentResult]:
        """Find documents containing a specific entity in structured_metadata.

        Args:
            entity_field: Field name in structured_metadata (e.g. 'persons')
            entity_name: Entity value to search for (case-insensitive)

        Returns:
            List of matching DocumentResult objects
        """
        all_docs = self._store.list_documents(limit=100000)
        results = []
        name_lower = entity_name.lower()

        for doc in all_docs:
            if doc.metadata.get("is_chunk"):
                continue
            struct_meta = doc.metadata.get("structured_metadata", {})
            entities = struct_meta.get(entity_field, [])
            if any(e.lower() == name_lower for e in entities):
                results.append(DocumentResult(
                    id=self._str_to_int_id(doc.id),
                    text=doc.text,
                    metadata=doc.metadata,
                    created_at=doc.created_at,
                    topics=doc.metadata.get("topics", []),
                    primary_topic=doc.metadata.get("primary_topic")
                ))

        return results

    def find_by_person(self, name: str) -> List[DocumentResult]:
        """Find documents mentioning a specific person."""
        return self._find_docs_by_entity("persons", name)

    def find_by_organization(self, name: str) -> List[DocumentResult]:
        """Find documents mentioning a specific organization."""
        return self._find_docs_by_entity("organizations", name)

    def find_by_location(self, name: str) -> List[DocumentResult]:
        """Find documents mentioning a specific location."""
        return self._find_docs_by_entity("locations", name)

    def find_by_technology(self, name: str) -> List[DocumentResult]:
        """Find documents mentioning a specific technology."""
        return self._find_docs_by_entity("technologies", name)

    def get_knowledge_graph(
        self,
        include_documents: bool = True,
        include_topics: bool = True,
        include_entities: bool = True,
        entity_types: Optional[List[str]] = None,
        min_connections: int = 2,
        limit_documents: int = 200,
        limit_entities_per_type: int = 15,
        max_topic_edges_per_doc: int = 3,
        max_entity_edges_per_doc: int = 5
    ) -> Dict[str, Any]:
        """Build knowledge graph data from documents, topics, and entities.

        Returns a dict with nodes, edges, stats, and available_filters suitable
        for the frontend KnowledgeGraph component.
        """
        nodes = []
        edges = []
        node_ids = set()

        # Collect all parent documents
        all_docs = self._store.list_documents(limit=100000)
        parent_docs = [d for d in all_docs if not d.metadata.get("is_chunk")]
        parent_docs = parent_docs[:limit_documents]

        # Track entity occurrences for connection counting
        entity_counts: Dict[str, Dict[str, set]] = {
            "persons": {},
            "organizations": {},
            "locations": {},
            "technologies": {},
        }

        # Allowed entity types
        allowed_entity_types = set(entity_types) if entity_types else {
            "person", "organization", "location", "technology"
        }
        entity_field_map = {
            "person": "persons",
            "organization": "organizations",
            "location": "locations",
            "technology": "technologies",
        }

        # Collect available content_types and domains for filters
        content_types = set()
        domains = set()

        # === Pass 1: Build document nodes and collect entity references ===
        for doc in parent_docs:
            meta = doc.metadata or {}
            doc_int_id = self._str_to_int_id(doc.id)
            doc_node_id = f"doc_{doc_int_id}"

            # Collect filters
            doc_filters = meta.get("document_filters", {})
            if doc_filters.get("content_type"):
                content_types.add(doc_filters["content_type"])
            if doc_filters.get("domain"):
                domains.add(doc_filters["domain"])

            if include_documents:
                nodes.append({
                    "id": doc_node_id,
                    "label": meta.get("title") or meta.get("filename") or meta.get("original_filename") or f"Doc {doc_int_id}",
                    "type": "document",
                    "metadata": {
                        "text_preview": (doc.text or "")[:150],
                        "content_type": doc_filters.get("content_type"),
                        "domain": doc_filters.get("domain"),
                    }
                })
                node_ids.add(doc_node_id)

            # Collect entity references from structured_metadata
            struct_meta = meta.get("structured_metadata", {})
            for entity_type, field in entity_field_map.items():
                if entity_type not in allowed_entity_types:
                    continue
                for entity_name in struct_meta.get(field, []):
                    if not entity_name or not entity_name.strip():
                        continue
                    name_key = entity_name.strip().lower()
                    if name_key not in entity_counts[field]:
                        entity_counts[field][name_key] = set()
                    entity_counts[field][name_key].add(doc_node_id)

            # Collect topic references
            topics = meta.get("topics", [])
            if isinstance(topics, str):
                topics = [topics]
            for topic in topics:
                if not topic or not topic.strip():
                    continue
                topic_node_id = f"topic_{topic.lower()}"
                # Track topic → doc edges (added later)
                field_key = f"_topics"
                if field_key not in entity_counts:
                    entity_counts[field_key] = {}
                if topic.lower() not in entity_counts[field_key]:
                    entity_counts[field_key][topic.lower()] = set()
                entity_counts[field_key][topic.lower()].add(doc_node_id)

        # === Pass 2: Build topic nodes and edges ===
        # Limit edges per document to top N most-connected topics to avoid edge explosion.
        # A topic's "weight" for a doc = how many total docs that topic connects to (popularity).
        if include_topics and "_topics" in entity_counts:
            # Sort topics by popularity (most connected docs first)
            sorted_topics = sorted(
                entity_counts["_topics"].items(),
                key=lambda x: len(x[1]),
                reverse=True
            )

            # Track how many topic edges each doc already has
            doc_topic_edge_count: Dict[str, int] = {}

            for topic_name, connected_docs in sorted_topics:
                if len(connected_docs) < min_connections:
                    continue
                topic_node_id = f"topic_{topic_name}"
                if topic_node_id not in node_ids:
                    nodes.append({
                        "id": topic_node_id,
                        "label": topic_name.title(),
                        "type": "topic",
                        "metadata": {
                            "connection_count": len(connected_docs),
                        }
                    })
                    node_ids.add(topic_node_id)

                # Add edges from topic to documents, respecting per-doc limit
                if include_documents:
                    for doc_node_id in connected_docs:
                        if doc_node_id not in node_ids:
                            continue
                        current_count = doc_topic_edge_count.get(doc_node_id, 0)
                        if current_count >= max_topic_edges_per_doc:
                            continue
                        edges.append({
                            "source": topic_node_id,
                            "target": doc_node_id,
                            "type": "has_topic",
                        })
                        doc_topic_edge_count[doc_node_id] = current_count + 1

        # === Pass 3: Build entity nodes and edges ===
        if include_entities:
            type_prefix_map = {
                "persons": "person",
                "organizations": "organization",
                "locations": "location",
                "technologies": "technology",
            }
            # Track how many entity edges each doc already has
            doc_entity_edge_count: Dict[str, int] = {}

            for field, prefix in type_prefix_map.items():
                if prefix not in allowed_entity_types:
                    continue
                # Sort by connection count, take top N
                sorted_entities = sorted(
                    entity_counts.get(field, {}).items(),
                    key=lambda x: len(x[1]),
                    reverse=True
                )[:limit_entities_per_type]

                for entity_name, connected_docs in sorted_entities:
                    if len(connected_docs) < min_connections:
                        continue
                    entity_node_id = f"{prefix}_{entity_name}"
                    if entity_node_id not in node_ids:
                        nodes.append({
                            "id": entity_node_id,
                            "label": entity_name.title(),
                            "type": prefix,
                            "metadata": {
                                "connection_count": len(connected_docs),
                            }
                        })
                        node_ids.add(entity_node_id)

                    # Add edges from entity to documents, respecting per-doc limit
                    if include_documents:
                        for doc_node_id in connected_docs:
                            if doc_node_id not in node_ids:
                                continue
                            current_count = doc_entity_edge_count.get(doc_node_id, 0)
                            if current_count >= max_entity_edges_per_doc:
                                continue
                            edges.append({
                                "source": entity_node_id,
                                "target": doc_node_id,
                                "type": f"has_{prefix}",
                            })
                            doc_entity_edge_count[doc_node_id] = current_count + 1

        # Update connection counts on document nodes
        doc_connection_counts: Dict[str, int] = {}
        for edge in edges:
            doc_connection_counts[edge["target"]] = doc_connection_counts.get(edge["target"], 0) + 1
            doc_connection_counts[edge["source"]] = doc_connection_counts.get(edge["source"], 0) + 1
        for node in nodes:
            if node["id"] in doc_connection_counts:
                node["metadata"]["connection_count"] = doc_connection_counts[node["id"]]

        # Build content_type and domain counts from document nodes
        content_type_counts: Dict[str, int] = {}
        domain_counts: Dict[str, int] = {}
        for node in nodes:
            if node["type"] == "document":
                ct = node["metadata"].get("content_type")
                if ct:
                    content_type_counts[ct] = content_type_counts.get(ct, 0) + 1
                dm = node["metadata"].get("domain")
                if dm:
                    domain_counts[dm] = domain_counts.get(dm, 0) + 1

        return {
            "nodes": nodes,
            "edges": edges,
            "stats": {
                "total_nodes": len(nodes),
                "total_edges": len(edges),
                "document_count": len([n for n in nodes if n["type"] == "document"]),
                "topic_count": len([n for n in nodes if n["type"] == "topic"]),
                "entity_count": len([n for n in nodes if n["type"] not in ("document", "topic")]),
            },
            "available_filters": {
                "content_types": [
                    {"type": ct, "label": ct, "count": count}
                    for ct, count in sorted(content_type_counts.items(), key=lambda x: x[1], reverse=True)
                ],
                "domains": [
                    {"type": d, "label": d, "count": count}
                    for d, count in sorted(domain_counts.items(), key=lambda x: x[1], reverse=True)
                ],
                "entity_types": sorted(allowed_entity_types),
            }
        }

    # =========================================================================
    # Cleanup
    # =========================================================================

    def close(self):
        """Close the store and release resources."""
        if self._store:
            self._store.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
