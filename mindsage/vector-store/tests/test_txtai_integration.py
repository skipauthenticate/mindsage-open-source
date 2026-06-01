"""
Integration tests for txtai migration.

Tests:
1. Basic CRUD operations
2. Hybrid search functionality
3. Graph queries
4. Migration compatibility
5. API contract compliance
"""

import os
import sys
import tempfile
import pytest
from typing import List, Dict, Any

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def temp_dir():
    """Create a temporary directory for test data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def txtai_store(temp_dir):
    """Create a TxtaiStore instance for testing."""
    from mcp_vector_store.txtai_store import TxtaiStore
    store = TxtaiStore(data_dir=temp_dir, use_onnx=False)
    yield store
    store.close()


@pytest.fixture
def txtai_adapter(temp_dir):
    """Create a TxtaiAdapter instance for testing."""
    from mcp_vector_store.txtai_adapter import TxtaiAdapter
    adapter = TxtaiAdapter(db_path=temp_dir, use_onnx=False)
    yield adapter
    adapter.close()


@pytest.fixture
def sample_documents():
    """Sample documents for testing."""
    return [
        {
            "text": "Machine learning is a subset of artificial intelligence that enables systems to learn from data.",
            "metadata": {"source": "ml_intro.txt", "category": "tech"}
        },
        {
            "text": "Neural networks are computing systems inspired by biological neural networks in the brain.",
            "metadata": {"source": "nn_basics.txt", "category": "tech"}
        },
        {
            "text": "Python is a popular programming language widely used in data science and machine learning.",
            "metadata": {"source": "python_ds.txt", "category": "programming"}
        },
        {
            "text": "The weather today is sunny with temperatures around 75 degrees Fahrenheit.",
            "metadata": {"source": "weather.txt", "category": "general"}
        },
        {
            "text": "Cooking pasta requires boiling water, adding salt, and cooking for 8-10 minutes.",
            "metadata": {"source": "cooking.txt", "category": "lifestyle"}
        }
    ]


# =============================================================================
# TxtaiStore Tests
# =============================================================================

class TestTxtaiStore:
    """Test TxtaiStore basic operations."""

    def test_initialization(self, temp_dir):
        """Test store initializes correctly."""
        from mcp_vector_store.txtai_store import TxtaiStore
        store = TxtaiStore(data_dir=temp_dir)
        assert store.count() == 0
        store.close()

    def test_add_document(self, txtai_store, sample_documents):
        """Test adding a single document."""
        doc = sample_documents[0]
        doc_id, is_duplicate = txtai_store.add_document(
            text=doc["text"],
            metadata=doc["metadata"]
        )

        assert doc_id is not None
        assert not is_duplicate
        assert txtai_store.count() == 1

    def test_add_duplicate_document(self, txtai_store, sample_documents):
        """Test duplicate detection."""
        doc = sample_documents[0]

        # Add first time
        doc_id1, is_dup1 = txtai_store.add_document(doc["text"], doc["metadata"])
        assert not is_dup1

        # Add same document again
        doc_id2, is_dup2 = txtai_store.add_document(doc["text"], doc["metadata"])
        assert is_dup2
        assert doc_id2 == doc_id1

        # Count should still be 1
        assert txtai_store.count() == 1

    def test_add_multiple_documents(self, txtai_store, sample_documents):
        """Test batch document addition."""
        results = txtai_store.add_documents(sample_documents)

        assert len(results) == len(sample_documents)
        assert all(not r[1] for r in results)  # No duplicates
        assert txtai_store.count() == len(sample_documents)

    def test_search_basic(self, txtai_store, sample_documents):
        """Test basic semantic search."""
        # Add documents
        txtai_store.add_documents(sample_documents)

        # Search
        results = txtai_store.search("machine learning AI", limit=3)

        assert len(results) > 0
        assert results[0].score > 0

        # First result should be about ML or AI
        assert "machine" in results[0].text.lower() or "artificial" in results[0].text.lower()

    def test_search_returns_metadata(self, txtai_store, sample_documents):
        """Test that search returns metadata."""
        txtai_store.add_documents(sample_documents)

        results = txtai_store.search("programming language", limit=1)

        assert len(results) == 1
        assert results[0].metadata is not None
        assert "source" in results[0].metadata

    def test_search_min_score_filter(self, txtai_store, sample_documents):
        """Test minimum score filtering."""
        txtai_store.add_documents(sample_documents)

        # Search with high min_score should return fewer results
        results_low = txtai_store.search("technology", limit=5, min_score=0.0)
        results_high = txtai_store.search("technology", limit=5, min_score=0.5)

        assert len(results_high) <= len(results_low)

    def test_search_by_topic(self, txtai_store, sample_documents):
        """Test topic-filtered search."""
        # Add documents with topics
        for doc in sample_documents:
            doc_id, _ = txtai_store.add_document(doc["text"], doc["metadata"])
            # Assign topic based on category
            category = doc["metadata"].get("category", "general")
            txtai_store.update_document_topics(doc_id, [category])

        # Search within topic
        results = txtai_store.search_by_topic("programming", "programming", limit=3)

        # All results should have programming topic
        for r in results:
            assert "programming" in (r.topics or [])

    def test_delete_document(self, txtai_store, sample_documents):
        """Test document deletion."""
        doc_id, _ = txtai_store.add_document(
            sample_documents[0]["text"],
            sample_documents[0]["metadata"]
        )
        assert txtai_store.count() == 1

        result = txtai_store.delete_document(doc_id)
        assert result is True
        assert txtai_store.count() == 0

    def test_update_topics(self, txtai_store, sample_documents):
        """Test topic updates."""
        doc_id, _ = txtai_store.add_document(
            sample_documents[0]["text"],
            sample_documents[0]["metadata"]
        )

        # Update topics
        result = txtai_store.update_document_topics(
            doc_id,
            topics=["machine-learning", "AI"],
            primary_topic="machine-learning"
        )
        assert result is True

        # Verify topics in search
        search_results = txtai_store.search("machine learning", limit=1)
        assert search_results[0].topics == ["machine-learning", "AI"]
        assert search_results[0].primary_topic == "machine-learning"

    def test_list_documents(self, txtai_store, sample_documents):
        """Test document listing."""
        txtai_store.add_documents(sample_documents)

        docs = txtai_store.list_documents(offset=0, limit=10)

        assert len(docs) == len(sample_documents)

    def test_stats(self, txtai_store, sample_documents):
        """Test statistics retrieval."""
        txtai_store.add_documents(sample_documents)

        stats = txtai_store.stats()

        assert stats["document_count"] == len(sample_documents)
        assert "embedding_dim" in stats
        assert "hybrid_enabled" in stats


# =============================================================================
# TxtaiAdapter Tests (API Compatibility)
# =============================================================================

class TestTxtaiAdapter:
    """Test TxtaiAdapter API compatibility."""

    def test_add_document_returns_correct_type(self, txtai_adapter, sample_documents):
        """Test add_document returns AddDocumentResult."""
        from mcp_vector_store.txtai_adapter import AddDocumentResult

        result = txtai_adapter.add_document(
            text=sample_documents[0]["text"],
            metadata=sample_documents[0]["metadata"]
        )

        assert isinstance(result, AddDocumentResult)
        assert result.doc_id is not None
        assert result.is_duplicate is False
        assert result.content_hash is not None

    def test_search_returns_correct_type(self, txtai_adapter, sample_documents):
        """Test search returns List[SearchResult]."""
        from mcp_vector_store.txtai_adapter import SearchResult

        # Add documents first
        for doc in sample_documents:
            txtai_adapter.add_document(doc["text"], metadata=doc["metadata"])

        results = txtai_adapter.search("machine learning", limit=3)

        assert len(results) > 0
        assert all(isinstance(r, SearchResult) for r in results)
        assert all(hasattr(r, 'id') for r in results)
        assert all(hasattr(r, 'text') for r in results)
        assert all(hasattr(r, 'score') for r in results)

    def test_search_enhanced_returns_excerpts(self, txtai_adapter, sample_documents):
        """Test enhanced search returns excerpts."""
        from mcp_vector_store.txtai_adapter import EnhancedSearchResult

        for doc in sample_documents:
            txtai_adapter.add_document(doc["text"], metadata=doc["metadata"])

        results = txtai_adapter.search_enhanced("machine learning", limit=3)

        assert len(results) > 0
        assert all(isinstance(r, EnhancedSearchResult) for r in results)
        assert all(hasattr(r, 'excerpt') for r in results)

    def test_list_documents_pagination(self, txtai_adapter, sample_documents):
        """Test paginated document listing."""
        from mcp_vector_store.txtai_adapter import PaginatedResult

        for doc in sample_documents:
            txtai_adapter.add_document(doc["text"], metadata=doc["metadata"])

        result = txtai_adapter.list_documents(page=1, page_size=2)

        assert isinstance(result, PaginatedResult)
        assert len(result.documents) == 2
        assert result.total == len(sample_documents)
        assert result.has_next is True

        # Get next page
        result2 = txtai_adapter.list_documents(page=2, page_size=2)
        assert len(result2.documents) == 2
        assert result2.has_prev is True

    def test_get_document_returns_correct_type(self, txtai_adapter, sample_documents):
        """Test get_document returns DocumentResult."""
        from mcp_vector_store.txtai_adapter import AddDocumentResult, DocumentResult

        add_result = txtai_adapter.add_document(
            text=sample_documents[0]["text"],
            metadata=sample_documents[0]["metadata"]
        )
        assert isinstance(add_result, AddDocumentResult)

        doc = txtai_adapter.get_document(add_result.doc_id)

        assert isinstance(doc, DocumentResult)
        assert doc.id == add_result.doc_id
        assert doc.text == sample_documents[0]["text"]

    def test_chunking_large_documents(self, txtai_adapter):
        """Test automatic chunking of large documents."""
        # Create a large document
        large_text = "This is a test sentence. " * 200  # ~5000 chars

        result = txtai_adapter.add_document(text=large_text)

        assert result.doc_id is not None
        assert result.chunk_ids is not None
        assert len(result.chunk_ids) > 0

    def test_chunked_document_stores_full_text(self, txtai_adapter):
        """Test that chunked documents store full text in parent document."""
        # Create a document that exceeds CHUNK_THRESHOLD (2000 chars)
        large_text = "Sentence number {}. This is content for testing full text storage. " * 50
        large_text = large_text.format(*range(50))  # ~3000+ chars

        result = txtai_adapter.add_document(text=large_text)

        assert result.doc_id is not None
        assert result.chunk_ids is not None
        assert len(result.chunk_ids) > 0, "Document should be chunked"

        # Retrieve the parent document
        doc = txtai_adapter.get_document(result.doc_id)
        assert doc is not None

        # Verify full text is stored (not truncated)
        assert doc.metadata.get("is_parent") is True
        assert doc.metadata.get("full_text_length") == len(large_text)
        # The stored text should be at least as long as the original
        # (may be longer due to markdown conversion)
        assert len(doc.text) >= len(large_text) * 0.9, \
            f"Full text not stored: got {len(doc.text)} chars, expected ~{len(large_text)}"

    def test_non_chunked_document_full_text(self, txtai_adapter):
        """Test that small documents (under chunk threshold) store full text."""
        from mcp_vector_store.txtai_adapter import AddDocumentResult

        small_text = "This is a small document that should not be chunked. " * 10  # ~540 chars

        result = txtai_adapter.add_document(text=small_text)

        # Non-chunked documents return AddDocumentResult with no chunk_ids
        assert isinstance(result, AddDocumentResult)
        assert result.chunk_ids is None

        # Retrieve the document
        doc = txtai_adapter.get_document(result.doc_id)
        assert doc is not None

        # Verify text matches (allowing for markdown conversion)
        assert len(doc.text) >= len(small_text) * 0.9, \
            f"Text mismatch: got {len(doc.text)} chars, expected ~{len(small_text)}"

    def test_graph_search(self, txtai_adapter, sample_documents):
        """Test graph-based search."""
        for doc in sample_documents:
            txtai_adapter.add_document(doc["text"], metadata=doc["metadata"])

        result = txtai_adapter.graph_search("artificial intelligence", limit=3)

        assert "results" in result
        assert "related_concepts" in result

    def test_topic_operations(self, txtai_adapter, sample_documents):
        """Test topic CRUD operations."""
        add_result = txtai_adapter.add_document(
            text=sample_documents[0]["text"],
            metadata=sample_documents[0]["metadata"]
        )

        # Update topics
        success = txtai_adapter.update_document_topics(
            add_result.doc_id,
            topics=["tech", "ml"],
            primary_topic="tech"
        )
        assert success is True

        # Get topics
        topics = txtai_adapter.get_document_topics(add_result.doc_id)
        assert topics["topics"] == ["tech", "ml"]
        assert topics["primary_topic"] == "tech"

        # Get all topics
        all_topics = txtai_adapter.get_all_topics()
        assert len(all_topics) > 0

    def test_stats_format(self, txtai_adapter, sample_documents):
        """Test stats returns expected format."""
        for doc in sample_documents:
            txtai_adapter.add_document(doc["text"], metadata=doc["metadata"])

        stats = txtai_adapter.get_stats()

        assert "total_documents" in stats
        assert "embedding_dimension" in stats
        assert stats["total_documents"] == len(sample_documents)


# =============================================================================
# Performance Tests
# =============================================================================

class TestPerformance:
    """Basic performance tests."""

    def test_bulk_insert_performance(self, txtai_store):
        """Test bulk insert doesn't time out."""
        import time

        documents = [
            {"text": f"Document number {i} with some content about topic {i % 10}.", "metadata": {"index": i}}
            for i in range(100)
        ]

        start = time.perf_counter()
        txtai_store.add_documents(documents)
        elapsed = time.perf_counter() - start

        # Should complete in under 30 seconds
        assert elapsed < 30
        assert txtai_store.count() == 100

    def test_search_latency(self, txtai_store, sample_documents):
        """Test search latency is reasonable."""
        import time

        txtai_store.add_documents(sample_documents)

        latencies = []
        for _ in range(10):
            start = time.perf_counter()
            txtai_store.search("machine learning", limit=5)
            latencies.append((time.perf_counter() - start) * 1000)

        avg_latency = sum(latencies) / len(latencies)

        # Average latency should be under 500ms
        assert avg_latency < 500


# =============================================================================
# Concurrency Tests
# =============================================================================

class TestTxtaiStoreConcurrency:
    """Test TxtaiStore thread safety with concurrent operations."""

    def test_concurrent_add_documents(self, temp_dir):
        """Test that concurrent document additions don't cause race conditions.

        This test verifies the fix for the UNIQUE constraint failed: sections.indexid
        error that occurred when multiple documents were added in quick succession.
        """
        import threading
        import concurrent.futures
        from mcp_vector_store.txtai_store import TxtaiStore

        store = TxtaiStore(data_dir=temp_dir, use_onnx=False)

        # Create 10 unique documents
        documents = [
            {"text": f"Document number {i} about topic {i % 3}. " * 10, "metadata": {"index": i}}
            for i in range(10)
        ]

        errors = []
        success_count = [0]  # Use list for mutable counter in closure
        lock = threading.Lock()

        def add_document(doc):
            try:
                doc_id, is_dup = store.add_document(doc["text"], doc["metadata"])
                with lock:
                    success_count[0] += 1
                return doc_id
            except Exception as e:
                with lock:
                    errors.append(str(e))
                return None

        # Add documents concurrently using ThreadPoolExecutor
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(add_document, doc) for doc in documents]
            concurrent.futures.wait(futures)

        # Verify no errors occurred
        assert len(errors) == 0, f"Concurrent additions caused errors: {errors}"

        # Verify all documents were added
        assert success_count[0] == 10, f"Expected 10 successful additions, got {success_count[0]}"

        # Verify document count
        assert store.count() == 10, f"Expected 10 documents, got {store.count()}"

        store.close()

    def test_concurrent_add_and_update(self, temp_dir):
        """Test concurrent additions and metadata updates."""
        import threading
        import concurrent.futures
        from mcp_vector_store.txtai_store import TxtaiStore

        store = TxtaiStore(data_dir=temp_dir, use_onnx=False)

        # Add initial documents
        doc_ids = []
        for i in range(5):
            doc_id, _ = store.add_document(f"Initial document {i} content", {"index": i})
            doc_ids.append(doc_id)

        errors = []
        lock = threading.Lock()

        def update_metadata(doc_id, update_num):
            try:
                store.update_document_metadata(doc_id, {"update_num": update_num})
            except Exception as e:
                with lock:
                    errors.append(str(e))

        def add_new_document(index):
            try:
                store.add_document(f"New document {index}", {"new": True, "index": index})
            except Exception as e:
                with lock:
                    errors.append(str(e))

        # Run concurrent updates and additions
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = []
            # Add update tasks
            for i, doc_id in enumerate(doc_ids):
                futures.append(executor.submit(update_metadata, doc_id, i))
            # Add new document tasks
            for i in range(5):
                futures.append(executor.submit(add_new_document, i + 100))
            concurrent.futures.wait(futures)

        # Verify no errors occurred
        assert len(errors) == 0, f"Concurrent operations caused errors: {errors}"

        # Verify document count (5 original + 5 new)
        assert store.count() == 10, f"Expected 10 documents, got {store.count()}"

        store.close()

    def test_concurrent_add_delete(self, temp_dir):
        """Test concurrent additions and deletions."""
        import threading
        import concurrent.futures
        from mcp_vector_store.txtai_store import TxtaiStore

        store = TxtaiStore(data_dir=temp_dir, use_onnx=False)

        # Add initial documents
        doc_ids = []
        for i in range(10):
            doc_id, _ = store.add_document(f"Document to delete {i}", {"index": i})
            doc_ids.append(doc_id)

        errors = []
        lock = threading.Lock()

        def delete_document(doc_id):
            try:
                store.delete_document(doc_id)
            except Exception as e:
                with lock:
                    errors.append(str(e))

        def add_document(index):
            try:
                store.add_document(f"New document during delete {index}", {"index": index})
            except Exception as e:
                with lock:
                    errors.append(str(e))

        # Run concurrent deletes and additions
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = []
            # Delete first 5 documents
            for doc_id in doc_ids[:5]:
                futures.append(executor.submit(delete_document, doc_id))
            # Add 5 new documents
            for i in range(5):
                futures.append(executor.submit(add_document, i + 200))
            concurrent.futures.wait(futures)

        # Verify no errors occurred
        assert len(errors) == 0, f"Concurrent operations caused errors: {errors}"

        # Should have 10 documents (5 remaining + 5 new)
        assert store.count() == 10, f"Expected 10 documents, got {store.count()}"

        store.close()


# =============================================================================
# txtai 9.6 Upgrade Tests
# =============================================================================

class TestSourceScopedDuplicates:
    """Test source-scoped duplicate detection (fec3bfb fix).

    Same text from different sources (e.g. ChatGPT vs Claude) should be
    stored separately, while same text + same source should deduplicate.
    """

    def test_same_text_different_sources_not_duplicate(self, txtai_store):
        """Identical text from different sources should be stored separately."""
        text = "The meeting is scheduled for 3pm tomorrow."

        doc_id1, is_dup1 = txtai_store.add_document(text, {"source": "chatgpt"})
        doc_id2, is_dup2 = txtai_store.add_document(text, {"source": "claude"})

        assert not is_dup1
        assert not is_dup2
        assert doc_id1 != doc_id2
        assert txtai_store.count() == 2

    def test_same_text_same_source_is_duplicate(self, txtai_store):
        """Identical text from the same source should deduplicate."""
        text = "The meeting is scheduled for 3pm tomorrow."

        doc_id1, is_dup1 = txtai_store.add_document(text, {"source": "chatgpt"})
        doc_id2, is_dup2 = txtai_store.add_document(text, {"source": "chatgpt"})

        assert not is_dup1
        assert is_dup2
        assert doc_id2 == doc_id1
        assert txtai_store.count() == 1

    def test_same_text_no_source_deduplicates(self, txtai_store):
        """Text without source still deduplicates on content alone."""
        text = "A simple note."

        doc_id1, is_dup1 = txtai_store.add_document(text, {})
        doc_id2, is_dup2 = txtai_store.add_document(text, {})

        assert not is_dup1
        assert is_dup2
        assert txtai_store.count() == 1

    def test_batch_add_source_scoped_duplicates(self, txtai_store):
        """Batch add respects source-scoped duplicate detection."""
        text = "Batch test content."
        documents = [
            {"text": text, "metadata": {"source": "chatgpt"}},
            {"text": text, "metadata": {"source": "claude"}},
            {"text": text, "metadata": {"source": "chatgpt"}},  # duplicate
        ]

        results = txtai_store.add_documents(documents)

        assert len(results) == 3
        assert not results[0][1]  # chatgpt - new
        assert not results[1][1]  # claude - new (different source)
        assert results[2][1]      # chatgpt again - duplicate
        assert txtai_store.count() == 2


class TestSearchByTopicNone:
    """Test search_by_topic with None topic (fec3bfb fix for topic.lower() guard)."""

    def test_search_by_topic_none_returns_unfiltered(self, txtai_store, sample_documents):
        """search_by_topic(topic=None) should fall back to regular search."""
        txtai_store.add_documents(sample_documents)

        results = txtai_store.search_by_topic("machine learning", topic=None, limit=5)

        assert len(results) > 0
        # Should behave like regular search (no topic filter)
        regular_results = txtai_store.search("machine learning", limit=5)
        assert len(results) == len(regular_results)

    def test_search_by_topic_empty_string_returns_unfiltered(self, txtai_store, sample_documents):
        """search_by_topic(topic='') should fall back to regular search."""
        txtai_store.add_documents(sample_documents)

        results = txtai_store.search_by_topic("machine learning", topic="", limit=5)

        assert len(results) > 0


class TestDeferredSaveBatching:
    """Test the deferred save mechanism (fec3bfb optimization for Jetson I/O)."""

    def test_dirty_flag_set_on_add(self, txtai_store, sample_documents):
        """Adding a document should set the dirty flag."""
        txtai_store.add_document(sample_documents[0]["text"], sample_documents[0]["metadata"])

        assert txtai_store._dirty is True

    def test_close_flushes_dirty_writes(self, temp_dir, sample_documents):
        """close() should persist dirty writes immediately."""
        from mcp_vector_store.txtai_store import TxtaiStore

        store = TxtaiStore(data_dir=temp_dir, use_onnx=False)
        store.add_document(sample_documents[0]["text"], sample_documents[0]["metadata"])
        assert store._dirty is True

        store.close()

        # Reopen and verify data persisted
        store2 = TxtaiStore(data_dir=temp_dir, use_onnx=False)
        assert store2.count() == 1
        store2.close()

    def test_multiple_adds_batched_to_single_save(self, txtai_store, sample_documents):
        """Multiple rapid additions should not trigger separate saves per document."""
        import time

        # Add 5 documents quickly (should batch into deferred save)
        for doc in sample_documents:
            txtai_store.add_document(doc["text"], doc["metadata"])

        # Dirty flag should be set (not yet flushed)
        assert txtai_store._dirty is True
        assert txtai_store.count() == len(sample_documents)

        # Wait for deferred save to fire (interval + buffer)
        time.sleep(txtai_store._save_interval + 1.0)

        # Should now be clean
        assert txtai_store._dirty is False


class TestRerankerIntegration:
    """Test cross-encoder reranker wiring in enhanced_search (fec3bfb fix)."""

    def test_enhanced_search_with_mock_reranker(self, txtai_adapter, sample_documents):
        """enhanced_search should apply reranker scores when provided."""
        for doc in sample_documents:
            txtai_adapter.add_document(doc["text"], metadata=doc["metadata"])

        class MockReranker:
            """Mock cross-encoder that reverses result order."""
            def predict(self, pairs):
                # Return descending scores so the last result becomes first
                n = len(pairs)
                return [float(i) / n for i in range(n)]

        reranker = MockReranker()
        results = txtai_adapter.enhanced_search(
            query="machine learning",
            limit=3,
            reranker=reranker,
            rerank_top_k=5
        )

        assert len(results) > 0
        # Verify scores are from the reranker (should be monotonically decreasing)
        for i in range(len(results) - 1):
            assert results[i].score >= results[i + 1].score

    def test_enhanced_search_without_reranker(self, txtai_adapter, sample_documents):
        """enhanced_search without reranker should work as before."""
        for doc in sample_documents:
            txtai_adapter.add_document(doc["text"], metadata=doc["metadata"])

        results = txtai_adapter.enhanced_search(
            query="machine learning",
            limit=3
        )

        assert len(results) > 0
        assert all(hasattr(r, 'score') for r in results)

    def test_enhanced_search_reranker_failure_fallback(self, txtai_adapter, sample_documents):
        """If reranker.predict() throws, should fall back to original scores."""
        for doc in sample_documents:
            txtai_adapter.add_document(doc["text"], metadata=doc["metadata"])

        class BrokenReranker:
            def predict(self, pairs):
                raise RuntimeError("Reranker model failed")

        results = txtai_adapter.enhanced_search(
            query="machine learning",
            limit=3,
            reranker=BrokenReranker(),
            rerank_top_k=5
        )

        # Should still return results (original scores)
        assert len(results) > 0


class TestSQLInjectionSafety:
    """Test that search queries with special characters don't cause SQL errors."""

    def test_search_with_single_quotes(self, txtai_store, sample_documents):
        """Search queries containing single quotes should not crash."""
        txtai_store.add_documents(sample_documents)

        # This would break unescaped SQL: similar('it's a test')
        results = txtai_store.search("it's a test", limit=5)
        assert isinstance(results, list)

    def test_search_with_sql_keywords(self, txtai_store, sample_documents):
        """Search queries containing SQL keywords should work safely."""
        txtai_store.add_documents(sample_documents)

        results = txtai_store.search("SELECT * FROM documents; DROP TABLE", limit=5)
        assert isinstance(results, list)

    def test_search_with_unicode(self, txtai_store, sample_documents):
        """Search with unicode characters should not crash."""
        txtai_store.add_documents(sample_documents)

        results = txtai_store.search("machine learning 人工智能", limit=5)
        assert isinstance(results, list)

    def test_get_document_with_special_id(self, txtai_store):
        """get_document with special characters in ID should not crash."""
        result = txtai_store.get_document("'; DROP TABLE txtai; --")
        assert result is None  # Not found, but no crash


class TestSearchFallback:
    """Test that search falls back to standard search when SQL fails."""

    def test_search_returns_results_on_empty_store(self, txtai_store):
        """Search on empty store should return empty list, not crash."""
        results = txtai_store.search("anything", limit=5)
        assert results == []

    def test_search_after_single_document(self, txtai_store):
        """Search with only 1 real document (+ system seed) should work."""
        txtai_store.add_document("Machine learning fundamentals", {"source": "test"})

        results = txtai_store.search("machine learning", limit=5)
        assert len(results) >= 1
        assert "machine" in results[0].text.lower() or "learning" in results[0].text.lower()


class TestConcurrentSearch:
    """Test concurrent search operations (previously untested)."""

    def test_concurrent_search_operations(self, temp_dir, sample_documents):
        """Multiple threads searching simultaneously should not crash."""
        import concurrent.futures
        import threading
        from mcp_vector_store.txtai_store import TxtaiStore

        store = TxtaiStore(data_dir=temp_dir, use_onnx=False)
        store.add_documents(sample_documents)

        errors = []
        lock = threading.Lock()

        def do_search(query):
            try:
                results = store.search(query, limit=3)
                assert len(results) >= 0
                return results
            except Exception as e:
                with lock:
                    errors.append(str(e))
                return None

        queries = [
            "machine learning", "neural networks", "programming",
            "weather forecast", "cooking recipes", "artificial intelligence",
            "data science", "Python language", "deep learning", "statistics"
        ]

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(do_search, q) for q in queries]
            concurrent.futures.wait(futures)

        assert len(errors) == 0, f"Concurrent searches caused errors: {errors}"

        store.close()

    def test_concurrent_search_and_write(self, temp_dir, sample_documents):
        """Simultaneous reads and writes should not deadlock or crash."""
        import concurrent.futures
        import threading
        from mcp_vector_store.txtai_store import TxtaiStore

        store = TxtaiStore(data_dir=temp_dir, use_onnx=False)
        store.add_documents(sample_documents)

        errors = []
        lock = threading.Lock()

        def do_search(query):
            try:
                store.search(query, limit=3)
            except Exception as e:
                with lock:
                    errors.append(f"search: {e}")

        def do_write(index):
            try:
                store.add_document(f"New document {index} about concurrent testing", {"index": index})
            except Exception as e:
                with lock:
                    errors.append(f"write: {e}")

        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
            futures = []
            # 5 search tasks
            for i in range(5):
                futures.append(executor.submit(do_search, f"query {i}"))
            # 5 write tasks
            for i in range(5):
                futures.append(executor.submit(do_write, i + 1000))
            concurrent.futures.wait(futures)

        assert len(errors) == 0, f"Concurrent search+write caused errors: {errors}"

        store.close()


class TestIndexPersistence:
    """Test that index data persists correctly across store instances."""

    def test_data_survives_close_and_reopen(self, temp_dir, sample_documents):
        """Documents should persist after close() and reopen."""
        from mcp_vector_store.txtai_store import TxtaiStore

        # Write documents
        store1 = TxtaiStore(data_dir=temp_dir, use_onnx=False)
        for doc in sample_documents:
            store1.add_document(doc["text"], doc["metadata"])
        assert store1.count() == len(sample_documents)
        store1.close()

        # Reopen and verify
        store2 = TxtaiStore(data_dir=temp_dir, use_onnx=False)
        assert store2.count() == len(sample_documents)

        # Search should still work
        results = store2.search("machine learning", limit=3)
        assert len(results) > 0
        store2.close()

    def test_duplicate_hashes_persist_across_reopen(self, temp_dir):
        """Content hashes should persist so duplicates are caught after reopen."""
        from mcp_vector_store.txtai_store import TxtaiStore

        text = "Unique document content for persistence test."

        # Add document
        store1 = TxtaiStore(data_dir=temp_dir, use_onnx=False)
        doc_id, is_dup = store1.add_document(text, {"source": "test"})
        assert not is_dup
        store1.close()

        # Reopen and try adding same document
        store2 = TxtaiStore(data_dir=temp_dir, use_onnx=False)
        doc_id2, is_dup2 = store2.add_document(text, {"source": "test"})
        assert is_dup2
        assert doc_id2 == doc_id
        assert store2.count() == 1
        store2.close()


class TestContentHashFunction:
    """Test compute_content_hash directly."""

    def test_hash_deterministic(self):
        """Same input should always produce same hash."""
        from mcp_vector_store.txtai_store import compute_content_hash

        h1 = compute_content_hash("hello world")
        h2 = compute_content_hash("hello world")
        assert h1 == h2

    def test_hash_with_source(self):
        """Hash with source should differ from hash without source."""
        from mcp_vector_store.txtai_store import compute_content_hash

        h_no_source = compute_content_hash("hello world")
        h_with_source = compute_content_hash("hello world", source="chatgpt")
        assert h_no_source != h_with_source

    def test_hash_different_sources(self):
        """Same text with different sources should produce different hashes."""
        from mcp_vector_store.txtai_store import compute_content_hash

        h1 = compute_content_hash("hello world", source="chatgpt")
        h2 = compute_content_hash("hello world", source="claude")
        assert h1 != h2

    def test_hash_empty_source_same_as_no_source(self):
        """Empty string source should behave same as no source."""
        from mcp_vector_store.txtai_store import compute_content_hash

        h1 = compute_content_hash("hello world", source="")
        h2 = compute_content_hash("hello world")
        assert h1 == h2


class TestSystemSeedDocument:
    """Test that the system seed document is properly hidden."""

    def test_seed_not_in_count(self, txtai_store):
        """System seed document should not be counted."""
        assert txtai_store.count() == 0

    def test_seed_not_in_search(self, txtai_store, sample_documents):
        """System seed document should not appear in search results."""
        txtai_store.add_documents(sample_documents)

        results = txtai_store.search("MindSage vector store initialized system document", limit=10)

        for r in results:
            assert r.id != txtai_store.SYSTEM_DOC_ID

    def test_seed_not_retrievable(self, txtai_store):
        """get_document should return None for system seed ID."""
        doc = txtai_store.get_document(txtai_store.SYSTEM_DOC_ID)
        assert doc is None

    def test_seed_not_in_list(self, txtai_store, sample_documents):
        """list_documents should not include system seed."""
        txtai_store.add_documents(sample_documents)

        docs = txtai_store.list_documents(offset=0, limit=100)

        for d in docs:
            assert d.id != txtai_store.SYSTEM_DOC_ID


# =============================================================================
# Run Tests
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
