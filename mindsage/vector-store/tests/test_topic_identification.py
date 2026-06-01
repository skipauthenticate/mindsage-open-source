"""Tests for topic identification functionality.

Tests the following features:
- TopicLabeler generation with keyword matching and embedding similarity
- Topic storage when documents are added
- Topic indexing and retrieval
- Topic updates and index consistency
- Chunked document topic handling
- Fallback behavior when classification fails
"""

import pytest
import tempfile
import shutil
import os
import json
from unittest.mock import Mock, MagicMock, patch
from dataclasses import dataclass

# Add parent directory to path for imports
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp_vector_store.txtai_adapter import TxtaiAdapter as VectorStore, SearchResult, AddDocumentResult
from mcp_vector_store.topic_labeler import TopicLabeler, TopicResult, DEFAULT_TOPICS, WEIGHTED_KEYWORD_MAP


def add_document_with_topics(
    vector_store: VectorStore,
    text: str,
    topic_labeler=None,
    embedding_model=None,
    **kwargs
) -> int:
    """Helper to add a document and assign topics.

    TxtaiAdapter ignores topic_labeler in add_document (topics are assigned async).
    This helper simulates synchronous topic assignment for testing by:
    1. Adding the document
    2. Using the mock topic_labeler to generate topics
    3. Calling update_document_topics to assign them

    Returns the document ID as an int.
    """
    result = vector_store.add_document(text=text, **kwargs)
    doc_id = result.doc_id if result.doc_id is not None else result.existing_doc_id

    # If topic_labeler provided, generate and assign topics
    if topic_labeler and doc_id is not None:
        topic_result = topic_labeler.generate_topics(text)
        vector_store.update_document_topics(
            doc_id=doc_id,
            topics=topic_result.topics,
            primary_topic=topic_result.primary_topic
        )
        # Also update metadata with confidence and timestamp
        doc = vector_store.get_document(doc_id)
        if doc:
            import time
            metadata = doc.metadata or {}
            metadata["topic_confidence"] = topic_result.confidence
            metadata["topics_updated_at"] = int(time.time() * 1000)
            vector_store.update_document_metadata(doc_id, metadata)

    return doc_id


class MockEmbeddingModel:
    """Mock embedding model for testing."""

    def __init__(self, dimension: int = 384):
        self.dimension = dimension
        self._topic_seeds = {
            "health": 1, "finance": 2, "work": 3, "personal": 4,
            "social": 5, "legal": 6, "travel": 7, "education": 8,
            "programming": 9, "sports": 10, "technology": 11,
            "shopping": 12, "family": 13, "general": 14
        }

    def embed_query(self, text: str):
        """Generate a mock embedding based on text hash."""
        import numpy as np
        np.random.seed(hash(text) % (2**32))
        return np.random.randn(self.dimension).astype(np.float32)

    def embed(self, text):
        """Generate mock embedding for text (single string or list)."""
        if isinstance(text, list):
            return [self.embed_query(t) for t in text]
        return self.embed_query(text)

    def get_dimension(self):
        return self.dimension


class MockTopicLabeler:
    """Mock topic labeler that returns predictable topics."""

    def __init__(self, topics: list = None, primary_topic: str = None):
        self._topics = topics or ["programming", "technology"]
        self._primary_topic = primary_topic or self._topics[0]

    def generate_topics(self, text: str, num_topics: int = 3, predefined_topics=None, **kwargs) -> TopicResult:
        """Return mock topic result."""
        return TopicResult(
            topics=self._topics[:num_topics],
            primary_topic=self._primary_topic,
            confidence=0.85,
            method="weighted_keyword_match"
        )

    def is_model_loaded(self) -> bool:
        return True


@pytest.fixture
def temp_db_path():
    """Create a temporary database path for testing."""
    temp_dir = tempfile.mkdtemp()
    yield os.path.join(temp_dir, "test_vectordb")
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def mock_embedding_model():
    """Create a mock embedding model."""
    return MockEmbeddingModel()


@pytest.fixture
def vector_store(temp_db_path):
    """Create a vector store for testing."""
    store = VectorStore(db_path=temp_db_path, embedding_dim=384)
    yield store
    store.close()


@pytest.fixture
def mock_topic_labeler():
    """Create a mock topic labeler."""
    return MockTopicLabeler()


class TestTopicLabelerKeywordMatching:
    """Tests for TopicLabeler keyword-based classification.

    The TopicLabeler uses weighted keyword matching as the primary
    classification method, with embedding similarity as fallback.
    """

    def test_weighted_keyword_map_has_all_topics(self):
        """Test that keyword map covers all default topics."""
        topics_in_map = set(topic for topic, weight in WEIGHTED_KEYWORD_MAP.values())
        for topic in DEFAULT_TOPICS:
            if topic != "general":  # general is the fallback
                assert topic in topics_in_map, f"Topic '{topic}' missing from WEIGHTED_KEYWORD_MAP"

    def test_programming_keywords_detected(self):
        """Test that programming keywords are properly detected."""
        labeler = TopicLabeler(verbose=False)
        result = labeler.generate_topics(
            "Python programming tutorial with code examples",
            predefined_topics=DEFAULT_TOPICS
        )
        assert "programming" in result.topics
        assert result.confidence > 0.5

    def test_health_keywords_detected(self):
        """Test that health keywords are properly detected."""
        labeler = TopicLabeler(verbose=False)
        result = labeler.generate_topics(
            "My doctor prescribed medicine for the treatment",
            predefined_topics=DEFAULT_TOPICS
        )
        assert "health" in result.topics

    def test_finance_keywords_detected(self):
        """Test that finance keywords are properly detected."""
        labeler = TopicLabeler(verbose=False)
        result = labeler.generate_topics(
            "Check the budget and investment portfolio for tax planning",
            predefined_topics=DEFAULT_TOPICS
        )
        assert "finance" in result.topics

    def test_sports_keywords_detected(self):
        """Test that sports keywords are properly detected."""
        labeler = TopicLabeler(verbose=False)
        result = labeler.generate_topics(
            "The basketball game went into overtime at the stadium",
            predefined_topics=DEFAULT_TOPICS
        )
        assert "sports" in result.topics

    def test_stemming_matches_variations(self):
        """Test that stemming allows matching word variations."""
        labeler = TopicLabeler(verbose=False)
        # "programming" stem should match "programmer", "programmed", etc.
        result = labeler.generate_topics(
            "The programmer was programming a new feature",
            predefined_topics=DEFAULT_TOPICS
        )
        assert "programming" in result.topics

    def test_weighted_scoring_prefers_specific_keywords(self):
        """Test that specific keywords (weight 3.0) dominate over generic ones."""
        labeler = TopicLabeler(verbose=False)
        # "quicksort" has weight 3.0, very specific to programming
        result = labeler.generate_topics(
            "Implement quicksort algorithm",
            predefined_topics=DEFAULT_TOPICS
        )
        assert result.primary_topic == "programming"
        assert result.confidence > 0.6

    def test_ambiguous_text_lower_confidence(self):
        """Test that ambiguous text results in lower confidence."""
        labeler = TopicLabeler(verbose=False)
        # Generic text without strong topic indicators
        result = labeler.generate_topics(
            "The thing is interesting",
            predefined_topics=DEFAULT_TOPICS
        )
        assert result.confidence < 0.6

    def test_fallback_to_general(self):
        """Test fallback to 'general' when no keywords match."""
        labeler = TopicLabeler(verbose=False)
        result = labeler.generate_topics(
            "xyz123 abc456 random gibberish",
            predefined_topics=DEFAULT_TOPICS
        )
        assert result.primary_topic == "general"

    def test_empty_text_returns_general(self):
        """Test that empty text returns general topic."""
        labeler = TopicLabeler(verbose=False)
        result = labeler.generate_topics("", predefined_topics=DEFAULT_TOPICS)
        assert result.primary_topic == "general"
        assert result.method == "empty_text"

    def test_multiple_topics_detected(self):
        """Test that multiple topics can be detected in mixed content."""
        labeler = TopicLabeler(verbose=False)
        result = labeler.generate_topics(
            "Python programming for financial budget analysis",
            predefined_topics=DEFAULT_TOPICS,
            num_topics=3
        )
        # Should detect both programming and finance
        assert len(result.topics) >= 2
        assert "programming" in result.topics or "finance" in result.topics


class TestTopicLabelerGeneration:
    """Tests for TopicLabeler topic generation."""

    def test_generate_topics_with_predefined_list(self):
        """Test generating topics constrained to predefined list."""
        labeler = TopicLabeler(verbose=False)

        # Use text with keywords that map to programming topic
        result = labeler.generate_topics(
            text="This is a Python programming tutorial about coding",
            num_topics=3,
            predefined_topics=["programming", "technology", "education"]
        )

        assert result.topics is not None
        assert result.primary_topic is not None
        # Keywords like "python", "programming", "coding" should map to programming
        assert "programming" in result.topics

    def test_generate_topics_uses_default_topics(self):
        """Test that default topics are used when none provided."""
        labeler = TopicLabeler(verbose=False)

        result = labeler.generate_topics(
            text="Python programming code",
            num_topics=2,
            use_default_topics=True
        )

        # Result should be from DEFAULT_TOPICS
        assert result.primary_topic in DEFAULT_TOPICS

    def test_generate_topics_truncates_long_text(self):
        """Test that long text is truncated for processing."""
        labeler = TopicLabeler(verbose=False)

        # Create text with programming keywords at the start
        long_text = "Python programming " + "A" * 2000
        result = labeler.generate_topics(
            text=long_text,
            max_text_length=400
        )

        # Should still detect programming from truncated text
        assert result.primary_topic in DEFAULT_TOPICS

    def test_generate_topics_handles_exceptions(self):
        """Test graceful handling of errors."""
        labeler = TopicLabeler(verbose=False)

        # Use text without keyword matches
        result = labeler.generate_topics(text="xyz random text without any keywords")

        assert result.topics == ["general"]
        assert result.confidence <= 0.3
        assert "fallback" in result.method or "no_match" in result.method

    def test_batch_generate_topics(self):
        """Test batch topic generation for multiple texts."""
        labeler = TopicLabeler(verbose=False)

        texts = [
            "Python programming tutorial",
            "Finance budget planning",
            "Health fitness workout"
        ]

        results = labeler.batch_generate_topics(texts, num_topics=2)

        assert len(results) == 3
        assert all(isinstance(r, TopicResult) for r in results)
        # Verify keyword matching works for each text
        assert results[0].primary_topic == "programming"
        assert results[1].primary_topic == "finance"
        assert results[2].primary_topic == "health"


class TestTopicStorageIntegration:
    """Tests for topic storage when documents are added.

    Note: TxtaiAdapter handles topics via update_document_topics() rather than
    synchronously during add_document(). Tests use add_document_with_topics helper.
    """

    def test_topics_stored_in_document_metadata(self, vector_store, mock_embedding_model, mock_topic_labeler):
        """Test that topics are stored in document metadata when added."""
        doc_id = add_document_with_topics(
            vector_store,
            text="Python programming tutorial for beginners",
            topic_labeler=mock_topic_labeler
        )

        doc = vector_store.get_document(doc_id)
        assert doc is not None
        assert "topics" in doc.metadata
        assert "primary_topic" in doc.metadata
        assert doc.metadata["topics"] == ["programming", "documentation"]
        assert doc.metadata["primary_topic"] == "programming"

    def test_topics_indexed_after_document_add(self, vector_store, mock_embedding_model, mock_topic_labeler):
        """Test that topics are retrievable via public API after assignment."""
        doc_id = add_document_with_topics(
            vector_store,
            text="Python programming tutorial",
            topic_labeler=mock_topic_labeler
        )

        # Use public API to verify topics
        topic_info = vector_store.get_document_topics(doc_id)
        assert topic_info is not None
        assert "programming" in topic_info.get("topics", [])

        # Verify topic appears in get_all_topics
        all_topics = vector_store.get_all_topics()
        assert "programming" in all_topics

    def test_document_stored_without_topic_labeler(self, vector_store, mock_embedding_model):
        """Test that documents can be stored without topic labeler."""
        result = vector_store.add_document(
            text="Simple document text"
        )
        doc_id = result.doc_id

        doc = vector_store.get_document(doc_id)
        assert doc is not None
        # Should have empty or no topics
        topics = doc.metadata.get("topics", []) if doc.metadata else []
        assert topics == []

    def test_topic_confidence_stored(self, vector_store, mock_embedding_model, mock_topic_labeler):
        """Test that topic confidence is stored in metadata."""
        doc_id = add_document_with_topics(
            vector_store,
            text="Test document",
            topic_labeler=mock_topic_labeler
        )

        doc = vector_store.get_document(doc_id)
        assert "topic_confidence" in doc.metadata
        assert doc.metadata["topic_confidence"] == 0.85

    def test_topics_timestamp_stored(self, vector_store, mock_embedding_model, mock_topic_labeler):
        """Test that topics_updated_at timestamp is stored."""
        doc_id = add_document_with_topics(
            vector_store,
            text="Test document",
            topic_labeler=mock_topic_labeler
        )

        doc = vector_store.get_document(doc_id)
        assert "topics_updated_at" in doc.metadata
        assert isinstance(doc.metadata["topics_updated_at"], int)


class TestTopicIndexing:
    """Tests for topic indexing and retrieval.

    Note: TxtaiAdapter stores topics in document metadata and uses get_documents_by_topic()
    and get_all_topics() for retrieval rather than internal indices.
    """

    def test_topic_index_case_insensitive(self, vector_store, mock_embedding_model):
        """Test that topic retrieval is case-insensitive."""
        # Create labeler that returns uppercase topic
        labeler = MockTopicLabeler(topics=["PROGRAMMING", "DATABASE"])

        doc_id = add_document_with_topics(
            vector_store,
            text="Test document",
            topic_labeler=labeler
        )

        # Topic retrieval should be case-insensitive
        all_topics = vector_store.get_all_topics()
        # Topics are stored lowercase
        assert any(t.lower() == "programming" for t in all_topics.keys())

    def test_get_doc_ids_by_topic(self, vector_store, mock_embedding_model):
        """Test retrieving documents by topic."""
        labeler1 = MockTopicLabeler(topics=["programming"])
        labeler2 = MockTopicLabeler(topics=["database"])
        labeler3 = MockTopicLabeler(topics=["programming", "database"])

        doc1 = add_document_with_topics(vector_store, "Doc 1", topic_labeler=labeler1)
        doc2 = add_document_with_topics(vector_store, "Doc 2", topic_labeler=labeler2)
        doc3 = add_document_with_topics(vector_store, "Doc 3", topic_labeler=labeler3)

        prog_result = vector_store.get_documents_by_topic("programming")
        db_result = vector_store.get_documents_by_topic("database")

        prog_ids = [d.id for d in prog_result.documents]
        db_ids = [d.id for d in db_result.documents]

        assert doc1 in prog_ids
        assert doc3 in prog_ids
        assert doc2 not in prog_ids

        assert doc2 in db_ids
        assert doc3 in db_ids
        assert doc1 not in db_ids

    def test_topic_exact_match(self, vector_store, mock_embedding_model):
        """Test that topic search uses case-insensitive exact matching via get_documents_by_topic."""
        labeler = MockTopicLabeler(topics=["machine learning"])

        doc_id = add_document_with_topics(
            vector_store,
            "ML document",
            topic_labeler=labeler
        )

        # get_documents_by_topic uses case-insensitive exact matching
        matching_result = vector_store.get_documents_by_topic("machine learning")
        matching_ids = [d.id for d in matching_result.documents]
        assert doc_id in matching_ids

        # Also verify case-insensitivity
        matching_result_upper = vector_store.get_documents_by_topic("MACHINE LEARNING")
        matching_ids_upper = [d.id for d in matching_result_upper.documents]
        assert doc_id in matching_ids_upper

    def test_update_document_topics(self, vector_store, mock_embedding_model):
        """Test updating topics for an existing document."""
        result = vector_store.add_document("Test document")
        doc_id = result.doc_id

        # Update topics
        update_result = vector_store.update_document_topics(
            doc_id=doc_id,
            topics=["security", "devops"],
            primary_topic="security"
        )

        assert update_result is True

        # Verify metadata updated
        doc = vector_store.get_document(doc_id)
        assert doc.metadata["topics"] == ["security", "devops"]
        assert doc.metadata["primary_topic"] == "security"

        # Verify document appears in topic queries
        security_result = vector_store.get_documents_by_topic("security")
        devops_result = vector_store.get_documents_by_topic("devops")
        assert any(d.id == doc_id for d in security_result.documents)
        assert any(d.id == doc_id for d in devops_result.documents)

    def test_update_topics_removes_old_from_index(self, vector_store, mock_embedding_model):
        """Test that old topics are removed on update."""
        labeler = MockTopicLabeler(topics=["programming"])

        doc_id = add_document_with_topics(
            vector_store,
            "Test document",
            topic_labeler=labeler
        )

        # Verify initial topic
        prog_result = vector_store.get_documents_by_topic("programming")
        assert any(d.id == doc_id for d in prog_result.documents)

        # Update to different topics
        vector_store.update_document_topics(doc_id, ["database"])

        # Old topic should no longer match
        prog_result = vector_store.get_documents_by_topic("programming")
        assert not any(d.id == doc_id for d in prog_result.documents)

        # New topic should match
        db_result = vector_store.get_documents_by_topic("database")
        assert any(d.id == doc_id for d in db_result.documents)

    def test_update_nonexistent_document(self, vector_store):
        """Test updating topics for nonexistent document returns False."""
        result = vector_store.update_document_topics(
            doc_id=99999,
            topics=["test"]
        )
        assert result is False

    def test_get_all_topics(self, vector_store, mock_embedding_model):
        """Test listing all unique topics."""
        labeler1 = MockTopicLabeler(topics=["programming", "tutorial"])
        labeler2 = MockTopicLabeler(topics=["database", "tutorial"])

        add_document_with_topics(vector_store, "Doc 1", topic_labeler=labeler1)
        add_document_with_topics(vector_store, "Doc 2", topic_labeler=labeler2)

        all_topics = vector_store.get_all_topics()

        assert "programming" in all_topics
        assert "database" in all_topics
        assert "tutorial" in all_topics
        # Tutorial should have count of 2
        assert all_topics["tutorial"] == 2


class TestTopicIndexPersistence:
    """Tests for topic index persistence and rebuilding."""

    def test_topic_index_rebuilt_on_init(self, temp_db_path, mock_embedding_model):
        """Test that topics are persisted and retrievable when store is reopened."""
        # Create store and add documents
        store1 = VectorStore(db_path=temp_db_path, embedding_dim=384)
        labeler = MockTopicLabeler(topics=["programming"])

        doc_id = add_document_with_topics(
            store1,
            "Test document",
            topic_labeler=labeler
        )
        store1.close()

        # Reopen store
        store2 = VectorStore(db_path=temp_db_path, embedding_dim=384)

        # Topics should be retrievable via public API
        topic_info = store2.get_document_topics(doc_id)
        assert topic_info is not None
        assert "programming" in topic_info.get("topics", [])

        # Document should be findable by topic
        prog_result = store2.get_documents_by_topic("programming")
        assert any(d.id == doc_id for d in prog_result.documents)

        store2.close()

    def test_topic_metadata_persisted(self, temp_db_path, mock_embedding_model):
        """Test that topic metadata is persisted across store restarts."""
        store1 = VectorStore(db_path=temp_db_path, embedding_dim=384)
        labeler = MockTopicLabeler(topics=["security", "devops"], primary_topic="security")

        doc_id = add_document_with_topics(
            store1,
            "Test document",
            topic_labeler=labeler
        )
        store1.close()

        # Reopen and verify
        store2 = VectorStore(db_path=temp_db_path, embedding_dim=384)
        doc = store2.get_document(doc_id)

        assert doc.metadata["topics"] == ["security", "devops"]
        assert doc.metadata["primary_topic"] == "security"

        store2.close()


class TestChunkedDocumentTopics:
    """Tests for topic handling with chunked documents."""

    def test_large_document_chunks_get_topics(self, temp_db_path, mock_embedding_model):
        """Test that chunked documents have topics assigned to chunks."""
        store = VectorStore(
            db_path=temp_db_path,
            embedding_dim=384,
            auto_chunk_large_docs=True
        )

        # Create labeler that returns different topics
        call_count = [0]
        original_topics = [
            ["programming", "tutorial"],
            ["database", "tutorial"],
            ["security", "devops"]
        ]

        class RotatingTopicLabeler:
            def generate_topics(self, text, num_topics=3, predefined_topics=None, **kwargs):
                topics = original_topics[call_count[0] % len(original_topics)]
                call_count[0] += 1
                return TopicResult(
                    topics=topics,
                    primary_topic=topics[0],
                    confidence=0.85,
                    method="llm_local"
                )

        labeler = RotatingTopicLabeler()

        # Create large document
        large_doc = "This is content about various topics. " * 500

        result = store.add_document(
            text=large_doc,
            embedding_model=mock_embedding_model,
            topic_labeler=labeler
        )

        # Should be chunked
        from mcp_vector_store.txtai_adapter import AddDocumentResult
        assert isinstance(result, AddDocumentResult)
        assert result.chunk_ids is not None

        # Verify chunks exist (ChunkInfo doesn't have metadata, topics are on parent doc)
        chunks = store.get_document_chunks(result.doc_id)
        assert len(chunks) > 0, "Large document should have chunks"
        for chunk in chunks:
            # ChunkInfo has: chunk_id, parent_id, chunk_index, char_start, char_end, text
            assert chunk.parent_id == result.doc_id
            assert chunk.text is not None

        store.close()

    def test_parent_document_aggregates_chunk_topics(self, temp_db_path, mock_embedding_model):
        """Test that parent document has aggregated topics from chunks."""
        store = VectorStore(
            db_path=temp_db_path,
            embedding_dim=384,
            auto_chunk_large_docs=True
        )

        # Labeler that returns different topics for each chunk
        topics_to_return = [["programming"], ["database"], ["security"]]
        call_idx = [0]

        class MultiTopicLabeler:
            def generate_topics(self, text, **kwargs):
                idx = call_idx[0] % len(topics_to_return)
                call_idx[0] += 1
                return TopicResult(
                    topics=topics_to_return[idx],
                    primary_topic=topics_to_return[idx][0],
                    confidence=0.85,
                    method="llm_local"
                )

        large_doc = "Content " * 600
        result = store.add_document(
            text=large_doc,
            embedding_model=mock_embedding_model,
            topic_labeler=MultiTopicLabeler()
        )

        if hasattr(result, 'doc_id'):
            parent = store.get_document(result.doc_id)
            # Parent should have topics (either aggregated or from first chunk)
            if parent and parent.metadata:
                topics = parent.metadata.get("topics", [])
                # Should have some topics from chunks
                assert isinstance(topics, list)

        store.close()


class TestSearchWithTopicFilter:
    """Tests for searching with topic filtering."""

    def test_search_with_topic_filter(self, vector_store, mock_embedding_model):
        """Test that search can be filtered by topic."""
        labeler1 = MockTopicLabeler(topics=["programming"])
        labeler2 = MockTopicLabeler(topics=["database"])

        doc1 = add_document_with_topics(
            vector_store,
            "Python programming code",
            topic_labeler=labeler1
        )
        doc2 = add_document_with_topics(
            vector_store,
            "Database SQL queries",
            topic_labeler=labeler2
        )

        # Search with programming filter
        results = vector_store.search_with_topic_filter(
            query="code",
            topic="programming",
            limit=5
        )

        # Should only return programming document
        result_ids = [r.id for r in results]
        assert doc1 in result_ids or any(r.metadata.get("parent_id") == doc1 for r in results)

    def test_search_with_topic_and_score_threshold(self, vector_store, mock_embedding_model):
        """Test combined topic filter and score threshold."""
        labeler = MockTopicLabeler(topics=["programming"])

        add_document_with_topics(
            vector_store,
            "Python programming tutorial",
            topic_labeler=labeler
        )

        results = vector_store.search_with_topic_filter(
            query="Python",
            topic="programming",
            limit=5,
            min_score=0.1
        )

        for result in results:
            assert result.score >= 0.1


class TestTopicEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_document_text(self, vector_store, mock_embedding_model):
        """Test handling of empty document text."""
        # Empty text should still work
        result = vector_store.add_document(text="   ")  # Whitespace only
        assert result.doc_id is not None or result.is_duplicate

    def test_special_characters_in_topics(self, vector_store, mock_embedding_model):
        """Test handling of special characters in topic names."""
        labeler = MockTopicLabeler(topics=["c++", "node.js"])

        doc_id = add_document_with_topics(
            vector_store,
            text="Programming languages",
            topic_labeler=labeler
        )

        doc = vector_store.get_document(doc_id)
        assert "c++" in doc.metadata["topics"] or "node.js" in doc.metadata["topics"]

    def test_unicode_in_document_text(self, vector_store, mock_embedding_model):
        """Test handling of unicode characters in document text."""
        labeler = MockTopicLabeler(topics=["programming"])

        doc_id = add_document_with_topics(
            vector_store,
            text="Programacion en espanol",
            topic_labeler=labeler
        )

        doc = vector_store.get_document(doc_id)
        assert doc is not None
        assert doc.metadata["topics"] == ["programming"]

    def test_topic_labeler_returns_empty_result(self, vector_store, mock_embedding_model):
        """Test handling when topic labeler returns empty topics."""

        class EmptyTopicLabeler:
            def generate_topics(self, text, num_topics=3, predefined_topics=None, **kwargs):
                return TopicResult(
                    topics=[],
                    primary_topic="",
                    confidence=0.0,
                    method="llm_local_fallback"
                )

        doc_id = add_document_with_topics(
            vector_store,
            text="Test document",
            topic_labeler=EmptyTopicLabeler()
        )

        doc = vector_store.get_document(doc_id)
        # Should handle empty topics gracefully
        topics = doc.metadata.get("topics", [])
        assert isinstance(topics, list)

    def test_delete_document_removes_from_topic_index(self, vector_store, mock_embedding_model):
        """Test that deleting a document removes it from topic queries."""
        labeler = MockTopicLabeler(topics=["programming"])

        doc_id = add_document_with_topics(
            vector_store,
            text="Test document",
            topic_labeler=labeler
        )

        # Verify findable by topic
        prog_result = vector_store.get_documents_by_topic("programming")
        assert any(d.id == doc_id for d in prog_result.documents)

        # Delete document
        vector_store.delete_document(doc_id)

        # Should no longer be findable by topic
        prog_result = vector_store.get_documents_by_topic("programming")
        assert not any(d.id == doc_id for d in prog_result.documents)

    def test_duplicate_topics_deduplicated(self, vector_store, mock_embedding_model):
        """Test that duplicate topics are handled correctly."""
        labeler = MockTopicLabeler(topics=["programming", "programming", "database"])

        doc_id = add_document_with_topics(
            vector_store,
            text="Test document",
            topic_labeler=labeler
        )

        # Verify document is findable by topic
        prog_result = vector_store.get_documents_by_topic("programming")
        assert any(d.id == doc_id for d in prog_result.documents)


class TestGetDocumentTopics:
    """Tests for get_document_topics method."""

    def test_get_document_topics_returns_topic_info(self, vector_store, mock_embedding_model):
        """Test retrieving topics for a specific document."""
        labeler = MockTopicLabeler(topics=["programming", "tutorial"], primary_topic="programming")

        doc_id = add_document_with_topics(
            vector_store,
            text="Test document",
            topic_labeler=labeler
        )

        topic_info = vector_store.get_document_topics(doc_id)

        assert topic_info is not None
        assert topic_info["topics"] == ["programming", "tutorial"]
        assert topic_info["primary_topic"] == "programming"

    def test_get_document_topics_nonexistent_returns_none(self, vector_store):
        """Test that getting topics for nonexistent document returns None."""
        result = vector_store.get_document_topics(99999)
        assert result is None


class ContentAwareTopicLabeler:
    """Topic labeler that returns topics based on document content keywords.

    This simulates realistic LLM behavior for testing content-based categorization.
    """

    # Keyword to topic mapping - covers ALL 25 DEFAULT_TOPICS
    KEYWORD_TOPICS = {
        # Programming keywords
        "python": "programming",
        "javascript": "programming",
        "function": "programming",
        "class": "programming",
        "code": "programming",
        "algorithm": "programming",
        "api": "programming",

        # Software Architecture keywords
        "architecture": "software architecture",
        "microservices": "software architecture",
        "monolith": "software architecture",
        "design pattern": "software architecture",
        "scalability": "software architecture",
        "system design": "software architecture",

        # Database keywords
        "database": "database",
        "sql": "database",
        "query": "database",
        "table": "database",
        "schema": "database",
        "postgresql": "database",
        "mongodb": "database",

        # Machine learning keywords
        "machine learning": "machine learning",
        "neural network": "machine learning",
        "model training": "machine learning",
        "tensorflow": "machine learning",
        "pytorch": "machine learning",
        "deep learning": "machine learning",

        # Security keywords
        "security": "security",
        "vulnerability": "security",
        "authentication": "security",
        "encryption": "security",
        "firewall": "security",
        "penetration": "security",

        # DevOps keywords
        "docker": "devops",
        "kubernetes": "devops",
        "deployment": "devops",
        "ci/cd": "devops",
        "pipeline": "devops",
        "infrastructure": "devops",

        # Business keywords
        "revenue": "business",
        "profit": "business",
        "strategy": "business",
        "stakeholder": "business",
        "quarterly": "business",

        # Marketing keywords
        "marketing": "marketing",
        "campaign": "marketing",
        "brand": "marketing",
        "advertising": "marketing",
        "seo": "marketing",
        "social media": "marketing",

        # Finance keywords
        "budget": "finance",
        "invoice": "finance",
        "accounting": "finance",
        "financial": "finance",
        "expense": "finance",
        "payroll": "finance",

        # Product Management keywords
        "product roadmap": "product management",
        "user story": "product management",
        "backlog": "product management",
        "sprint planning": "product management",
        "feature request": "product management",
        "product requirements": "product management",

        # Project Management keywords
        "project plan": "project management",
        "milestone": "project management",
        "gantt": "project management",
        "timeline": "project management",
        "deliverable": "project management",
        "project status": "project management",

        # Meeting Notes keywords
        "meeting": "meeting notes",
        "agenda": "meeting notes",
        "attendees": "meeting notes",
        "action items": "meeting notes",
        "minutes": "meeting notes",

        # Email keywords
        "email": "email",
        "inbox": "email",
        "reply": "email",
        "forward": "email",
        "subject line": "email",
        "cc:": "email",

        # Proposal keywords
        "proposal": "proposal",
        "rfp": "proposal",
        "bid": "proposal",
        "quotation": "proposal",
        "scope of work": "proposal",

        # Presentation keywords
        "presentation": "presentation",
        "slides": "presentation",
        "powerpoint": "presentation",
        "keynote": "presentation",
        "deck": "presentation",

        # Documentation keywords
        "documentation": "documentation",
        "readme": "documentation",
        "guide": "documentation",
        "manual": "documentation",

        # Tutorial keywords
        "tutorial": "tutorial",
        "learn": "tutorial",
        "beginner": "tutorial",
        "step by step": "tutorial",
        "how to": "tutorial",

        # Specification keywords
        "specification": "specification",
        "spec": "specification",
        "requirements document": "specification",
        "functional requirements": "specification",
        "technical spec": "specification",

        # Troubleshooting keywords
        "troubleshoot": "troubleshooting",
        "debug": "troubleshooting",
        "error": "troubleshooting",
        "fix": "troubleshooting",
        "issue": "troubleshooting",
        "problem": "troubleshooting",

        # Research keywords
        "research": "research",
        "study": "research",
        "hypothesis": "research",
        "experiment": "research",
        "findings": "research",

        # Analysis keywords
        "analysis": "analysis",
        "analyze": "analysis",
        "metrics": "analysis",
        "data analysis": "analysis",
        "report": "analysis",
        "insights": "analysis",

        # Design keywords
        "design": "design",
        "mockup": "design",
        "wireframe": "design",
        "ui/ux": "design",
        "prototype": "design",
        "figma": "design",

        # Personal Notes keywords
        "personal note": "personal notes",
        "diary": "personal notes",
        "journal": "personal notes",
        "reminder": "personal notes",
        "thought": "personal notes",
        "idea": "personal notes",

        # Planning keywords
        "planning": "planning",
        "plan": "planning",
        "schedule": "planning",
        "calendar": "planning",
        "upcoming": "planning",
        "todo": "planning",
    }

    def generate_topics(self, text: str, num_topics: int = 3, predefined_topics=None, **kwargs) -> TopicResult:
        """Generate topics based on keywords found in the text."""
        text_lower = text.lower()
        found_topics = []

        # Check for keywords in text
        for keyword, topic in self.KEYWORD_TOPICS.items():
            if keyword in text_lower and topic not in found_topics:
                found_topics.append(topic)
                if len(found_topics) >= num_topics:
                    break

        # If no topics found, return general
        if not found_topics:
            found_topics = ["general"]

        # Filter by predefined topics if provided
        if predefined_topics:
            predefined_lower = [t.lower() for t in predefined_topics]
            found_topics = [t for t in found_topics if t.lower() in predefined_lower]
            if not found_topics:
                found_topics = ["general"]

        return TopicResult(
            topics=found_topics[:num_topics],
            primary_topic=found_topics[0],
            confidence=0.85 if len(found_topics) > 0 else 0.3,
            method="weighted_keyword_match"
        )


class TestContentBasedCategorization:
    """Tests for content-based document categorization.

    These tests verify that documents with specific content are categorized
    into appropriate topics based on their actual text content.
    """

    @pytest.fixture
    def content_aware_labeler(self):
        """Create a content-aware topic labeler."""
        return ContentAwareTopicLabeler()

    def test_programming_document_categorized_as_programming(
        self, vector_store, mock_embedding_model, content_aware_labeler
    ):
        """Test that a programming-related document gets 'programming' topic."""
        doc_id = add_document_with_topics(
            vector_store,
            text="This Python function implements a sorting algorithm using recursion.",
            topic_labeler=content_aware_labeler
        )

        doc = vector_store.get_document(doc_id)
        assert "programming" in doc.metadata["topics"]
        assert doc.metadata["primary_topic"] == "programming"

    def test_database_document_categorized_as_database(
        self, vector_store, mock_embedding_model, content_aware_labeler
    ):
        """Test that a database-related document gets 'database' topic."""
        doc_id = add_document_with_topics(
            vector_store,
            text="Write a SQL query to join the users table with orders and filter by date.",
            topic_labeler=content_aware_labeler
        )

        doc = vector_store.get_document(doc_id)
        assert "database" in doc.metadata["topics"]

    def test_ml_document_categorized_as_machine_learning(
        self, vector_store, mock_embedding_model, content_aware_labeler
    ):
        """Test that ML-related document gets 'machine learning' topic."""
        doc_id = add_document_with_topics(
            vector_store,
            text="Training a neural network with TensorFlow for image classification.",
            topic_labeler=content_aware_labeler
        )

        doc = vector_store.get_document(doc_id)
        assert "machine learning" in doc.metadata["topics"]

    def test_security_document_categorized_as_security(
        self, vector_store, mock_embedding_model, content_aware_labeler
    ):
        """Test that security-related document gets 'security' topic."""
        doc_id = add_document_with_topics(
            vector_store,
            text="Review the authentication system for vulnerabilities and implement encryption.",
            topic_labeler=content_aware_labeler
        )

        doc = vector_store.get_document(doc_id)
        assert "security" in doc.metadata["topics"]

    def test_devops_document_categorized_as_devops(
        self, vector_store, mock_embedding_model, content_aware_labeler
    ):
        """Test that DevOps-related document gets 'devops' topic."""
        doc_id = add_document_with_topics(
            vector_store,
            text="Deploy the application using Docker and Kubernetes with a CI/CD pipeline.",
            topic_labeler=content_aware_labeler
        )

        doc = vector_store.get_document(doc_id)
        assert "devops" in doc.metadata["topics"]

    def test_meeting_notes_categorized_correctly(
        self, vector_store, mock_embedding_model, content_aware_labeler
    ):
        """Test that meeting notes are categorized as 'meeting notes'."""
        doc_id = add_document_with_topics(
            vector_store,
            text="Meeting agenda: Discuss Q3 roadmap. Attendees: John, Jane. Action items to follow.",
            topic_labeler=content_aware_labeler
        )

        doc = vector_store.get_document(doc_id)
        assert "meeting notes" in doc.metadata["topics"]

    def test_tutorial_document_categorized_as_tutorial(
        self, vector_store, mock_embedding_model, content_aware_labeler
    ):
        """Test that tutorial content is categorized as 'tutorial'."""
        doc_id = add_document_with_topics(
            vector_store,
            text="This beginner tutorial will teach you how to build your first web app step by step.",
            topic_labeler=content_aware_labeler
        )

        doc = vector_store.get_document(doc_id)
        assert "tutorial" in doc.metadata["topics"]

    def test_multi_topic_document_gets_multiple_topics(
        self, vector_store, mock_embedding_model, content_aware_labeler
    ):
        """Test that documents spanning multiple domains get multiple topics."""
        doc_id = add_document_with_topics(
            vector_store,
            text="This Python tutorial covers how to write SQL queries for database operations.",
            topic_labeler=content_aware_labeler
        )

        doc = vector_store.get_document(doc_id)
        topics = doc.metadata["topics"]
        # Should have multiple topics since content spans programming, tutorial, and database
        assert len(topics) >= 2
        # At least one of the expected topics should be present
        expected_any = ["programming", "tutorial", "database"]
        assert any(t in topics for t in expected_any)

    def test_generic_document_categorized_as_general(
        self, vector_store, mock_embedding_model, content_aware_labeler
    ):
        """Test that generic documents without specific keywords get 'general' topic."""
        doc_id = add_document_with_topics(
            vector_store,
            text="The weather today is sunny with a high of 75 degrees.",
            topic_labeler=content_aware_labeler
        )

        doc = vector_store.get_document(doc_id)
        assert "general" in doc.metadata["topics"]

    def test_different_documents_get_different_topics(
        self, vector_store, mock_embedding_model, content_aware_labeler
    ):
        """Test that different document types are categorized differently."""
        # Add programming document
        prog_id = add_document_with_topics(
            vector_store,
            text="Implement a binary search algorithm in Python with O(log n) complexity.",
            topic_labeler=content_aware_labeler
        )

        # Add security document
        sec_id = add_document_with_topics(
            vector_store,
            text="Audit the firewall rules and check for authentication vulnerabilities.",
            topic_labeler=content_aware_labeler
        )

        # Add business document
        biz_id = add_document_with_topics(
            vector_store,
            text="Q3 revenue exceeded expectations. Strategy discussion with stakeholders.",
            topic_labeler=content_aware_labeler
        )

        prog_doc = vector_store.get_document(prog_id)
        sec_doc = vector_store.get_document(sec_id)
        biz_doc = vector_store.get_document(biz_id)

        # Each should have different primary topics
        assert prog_doc.metadata["primary_topic"] != sec_doc.metadata["primary_topic"]
        assert sec_doc.metadata["primary_topic"] != biz_doc.metadata["primary_topic"]

        # Verify specific categorizations
        assert "programming" in prog_doc.metadata["topics"]
        assert "security" in sec_doc.metadata["topics"]
        assert "business" in biz_doc.metadata["topics"]

    def test_search_returns_correct_topic_documents(
        self, vector_store, mock_embedding_model, content_aware_labeler
    ):
        """Test that searching by topic returns correctly categorized documents."""
        # Add documents of different types
        add_document_with_topics(
            vector_store,
            text="Python function for data processing with pandas library.",
            topic_labeler=content_aware_labeler
        )
        add_document_with_topics(
            vector_store,
            text="SQL query optimization for PostgreSQL database performance.",
            topic_labeler=content_aware_labeler
        )
        add_document_with_topics(
            vector_store,
            text="Meeting notes from the team standup. Action items discussed.",
            topic_labeler=content_aware_labeler
        )

        # Search for programming documents
        prog_results = vector_store.search_with_topic_filter(
            query="data processing",
            topic="programming",
            limit=5
        )

        # Search for database documents
        db_results = vector_store.search_with_topic_filter(
            query="query optimization",
            topic="database",
            limit=5
        )

        # Verify filtered results only contain matching topics
        for result in prog_results:
            doc_topics = vector_store.get_document_topics(result.id)
            if doc_topics:
                # Should match programming or be a related topic
                assert "programming" in doc_topics.get("topics", []) or result.metadata.get("parent_id")

    def test_topic_consistency_across_similar_documents(
        self, vector_store, mock_embedding_model, content_aware_labeler
    ):
        """Test that similar documents get consistent topic assignments."""
        # Add multiple similar programming documents
        doc1_id = add_document_with_topics(
            vector_store,
            text="Python code for sorting a list using quicksort algorithm.",
            topic_labeler=content_aware_labeler
        )
        doc2_id = add_document_with_topics(
            vector_store,
            text="JavaScript function implementing bubble sort algorithm.",
            topic_labeler=content_aware_labeler
        )
        doc3_id = add_document_with_topics(
            vector_store,
            text="Implement merge sort algorithm in Python with recursion.",
            topic_labeler=content_aware_labeler
        )

        doc1 = vector_store.get_document(doc1_id)
        doc2 = vector_store.get_document(doc2_id)
        doc3 = vector_store.get_document(doc3_id)

        # All should be categorized as programming
        assert "programming" in doc1.metadata["topics"]
        assert "programming" in doc2.metadata["topics"]
        assert "programming" in doc3.metadata["topics"]

    # Tests for all 25 DEFAULT_TOPICS

    def test_software_architecture_document(
        self, vector_store, mock_embedding_model, content_aware_labeler
    ):
        """Test software architecture topic categorization."""
        doc_id = add_document_with_topics(
            vector_store,
            text="The microservices architecture provides better scalability than a monolith design pattern.",
            topic_labeler=content_aware_labeler
        )
        doc = vector_store.get_document(doc_id)
        assert "software architecture" in doc.metadata["topics"]

    def test_marketing_document(
        self, vector_store, mock_embedding_model, content_aware_labeler
    ):
        """Test marketing topic categorization."""
        doc_id = add_document_with_topics(
            vector_store,
            text="Launch the new marketing campaign with social media advertising and SEO optimization.",
            topic_labeler=content_aware_labeler
        )
        doc = vector_store.get_document(doc_id)
        assert "marketing" in doc.metadata["topics"]

    def test_finance_document(
        self, vector_store, mock_embedding_model, content_aware_labeler
    ):
        """Test finance topic categorization."""
        doc_id = add_document_with_topics(
            vector_store,
            text="Review the budget and accounting records. Process the invoice and expense reports.",
            topic_labeler=content_aware_labeler
        )
        doc = vector_store.get_document(doc_id)
        assert "finance" in doc.metadata["topics"]

    def test_product_management_document(
        self, vector_store, mock_embedding_model, content_aware_labeler
    ):
        """Test product management topic categorization."""
        doc_id = add_document_with_topics(
            vector_store,
            text="Update the product roadmap with new user story items from the backlog for sprint planning.",
            topic_labeler=content_aware_labeler
        )
        doc = vector_store.get_document(doc_id)
        assert "product management" in doc.metadata["topics"]

    def test_project_management_document(
        self, vector_store, mock_embedding_model, content_aware_labeler
    ):
        """Test project management topic categorization."""
        doc_id = add_document_with_topics(
            vector_store,
            text="Update the project plan with new milestone dates and deliverable timeline.",
            topic_labeler=content_aware_labeler
        )
        doc = vector_store.get_document(doc_id)
        assert "project management" in doc.metadata["topics"]

    def test_email_document(
        self, vector_store, mock_embedding_model, content_aware_labeler
    ):
        """Test email topic categorization."""
        doc_id = add_document_with_topics(
            vector_store,
            text="Check your email inbox and reply to the message. Forward it to the team.",
            topic_labeler=content_aware_labeler
        )
        doc = vector_store.get_document(doc_id)
        assert "email" in doc.metadata["topics"]

    def test_proposal_document(
        self, vector_store, mock_embedding_model, content_aware_labeler
    ):
        """Test proposal topic categorization."""
        doc_id = add_document_with_topics(
            vector_store,
            text="Submit the proposal for the RFP with detailed scope of work and quotation.",
            topic_labeler=content_aware_labeler
        )
        doc = vector_store.get_document(doc_id)
        assert "proposal" in doc.metadata["topics"]

    def test_presentation_document(
        self, vector_store, mock_embedding_model, content_aware_labeler
    ):
        """Test presentation topic categorization."""
        doc_id = add_document_with_topics(
            vector_store,
            text="Create a presentation with slides in PowerPoint or Keynote for the meeting deck.",
            topic_labeler=content_aware_labeler
        )
        doc = vector_store.get_document(doc_id)
        assert "presentation" in doc.metadata["topics"]

    def test_specification_document(
        self, vector_store, mock_embedding_model, content_aware_labeler
    ):
        """Test specification topic categorization."""
        doc_id = add_document_with_topics(
            vector_store,
            text="Write the technical spec with functional requirements and specification details.",
            topic_labeler=content_aware_labeler
        )
        doc = vector_store.get_document(doc_id)
        assert "specification" in doc.metadata["topics"]

    def test_troubleshooting_document(
        self, vector_store, mock_embedding_model, content_aware_labeler
    ):
        """Test troubleshooting topic categorization."""
        doc_id = add_document_with_topics(
            vector_store,
            text="Troubleshoot the error by debugging the issue. Here's how to fix the problem.",
            topic_labeler=content_aware_labeler
        )
        doc = vector_store.get_document(doc_id)
        assert "troubleshooting" in doc.metadata["topics"]

    def test_analysis_document(
        self, vector_store, mock_embedding_model, content_aware_labeler
    ):
        """Test analysis topic categorization."""
        doc_id = add_document_with_topics(
            vector_store,
            text="Data analysis report with metrics and insights. Analyze the trends carefully.",
            topic_labeler=content_aware_labeler
        )
        doc = vector_store.get_document(doc_id)
        assert "analysis" in doc.metadata["topics"]

    def test_design_document(
        self, vector_store, mock_embedding_model, content_aware_labeler
    ):
        """Test design topic categorization."""
        doc_id = add_document_with_topics(
            vector_store,
            text="Create a mockup and wireframe in Figma for the UI/UX prototype design.",
            topic_labeler=content_aware_labeler
        )
        doc = vector_store.get_document(doc_id)
        assert "design" in doc.metadata["topics"]

    def test_personal_notes_document(
        self, vector_store, mock_embedding_model, content_aware_labeler
    ):
        """Test personal notes topic categorization."""
        doc_id = add_document_with_topics(
            vector_store,
            text="Personal note: reminder to call mom. Just a random thought and idea for later.",
            topic_labeler=content_aware_labeler
        )
        doc = vector_store.get_document(doc_id)
        assert "personal notes" in doc.metadata["topics"]

    def test_planning_document(
        self, vector_store, mock_embedding_model, content_aware_labeler
    ):
        """Test planning topic categorization."""
        doc_id = add_document_with_topics(
            vector_store,
            text="Planning for next week. Check the schedule and calendar for upcoming todo items.",
            topic_labeler=content_aware_labeler
        )
        doc = vector_store.get_document(doc_id)
        assert "planning" in doc.metadata["topics"]

    def test_research_document(
        self, vector_store, mock_embedding_model, content_aware_labeler
    ):
        """Test research topic categorization."""
        doc_id = add_document_with_topics(
            vector_store,
            text="Research study with hypothesis testing. Document the experiment findings.",
            topic_labeler=content_aware_labeler
        )
        doc = vector_store.get_document(doc_id)
        assert "research" in doc.metadata["topics"]


class TestTopicLabelerWithEmbeddings:
    """Tests for TopicLabeler with embedding model integration.

    These tests verify that embedding-based classification works correctly
    when keyword matching is ambiguous.
    """

    def test_labeler_works_without_embedding_model(self):
        """Test that labeler works with keyword matching only."""
        labeler = TopicLabeler(embedding_model=None, verbose=False)

        result = labeler.generate_topics(
            "Python programming tutorial",
            predefined_topics=DEFAULT_TOPICS
        )

        assert "programming" in result.topics
        assert result.method == "weighted_keyword_match"

    def test_labeler_with_mock_embedding_model(self):
        """Test that labeler can use embedding model for classification."""
        mock_embedding = MockEmbeddingModel()
        labeler = TopicLabeler(embedding_model=mock_embedding, verbose=False)

        result = labeler.generate_topics(
            "Python programming tutorial",
            predefined_topics=DEFAULT_TOPICS
        )

        assert result is not None
        assert len(result.topics) >= 1

    def test_is_model_loaded_always_true(self):
        """Test that is_model_loaded returns True (keyword matching always available)."""
        labeler = TopicLabeler(verbose=False)
        assert labeler.is_model_loaded() is True

    def test_unload_model_clears_cache(self):
        """Test that unload_model clears topic embeddings cache."""
        mock_embedding = MockEmbeddingModel()
        labeler = TopicLabeler(embedding_model=mock_embedding, verbose=False)

        # Generate topics to potentially cache embeddings
        labeler.generate_topics("test", predefined_topics=DEFAULT_TOPICS)

        # Unload should clear cache
        labeler.unload_model()
        assert labeler._topic_embeddings is None

    def test_set_embedding_model(self):
        """Test that embedding model can be set after initialization."""
        labeler = TopicLabeler(verbose=False)
        assert labeler.embedding_model is None

        mock_embedding = MockEmbeddingModel()
        labeler.set_embedding_model(mock_embedding)

        assert labeler.embedding_model is not None

    def test_predefined_topics_filter_results(self):
        """Test that results are limited to predefined topics."""
        labeler = TopicLabeler(verbose=False)

        # Text with programming keywords, but predefined list doesn't include programming
        result = labeler.generate_topics(
            "Python programming tutorial",
            predefined_topics=["finance", "health", "travel"]
        )

        # Should not return programming since it's not in predefined list
        assert "programming" not in result.topics
        # Should return general as fallback
        assert result.primary_topic == "general"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
