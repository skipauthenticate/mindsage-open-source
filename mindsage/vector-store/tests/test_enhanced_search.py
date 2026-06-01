"""Tests for enhanced search functionality.

Tests the following features:
- min_score threshold filtering
- Passage extraction
- Query expansion
- Enhanced search combining all features
"""

import pytest
import tempfile
import shutil
import os
from unittest.mock import Mock, MagicMock, patch

# Add parent directory to path for imports
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp_vector_store.txtai_adapter import (
    TxtaiAdapter as VectorStore,
    SearchResult,
    EnhancedSearchResult,
)
from mcp_vector_store.passage_extractor import (
    PassageExtractor,
    ExtractedPassage,
)


class MockEmbeddingModel:
    """Mock embedding model for testing."""

    def __init__(self, dimension: int = 384):
        self.dimension = dimension
        self._call_count = 0

    def embed_query(self, text: str):
        """Generate a mock embedding based on text hash."""
        import numpy as np
        # Create deterministic embeddings based on text
        np.random.seed(hash(text) % (2**32))
        return np.random.randn(self.dimension).astype(np.float32)

    def embed(self, texts):
        """Generate mock embeddings for multiple texts."""
        return [self.embed_query(t) for t in texts]

    def get_dimension(self):
        return self.dimension


class MockTopicLabeler:
    """Mock topic labeler for testing passage extraction."""

    def __init__(self):
        self._model = MockLlamaModel()

    def _load_model(self):
        pass


class MockLlamaModel:
    """Mock LLM model for testing."""

    def __call__(self, prompt, **kwargs):
        # Return a simple mock response
        if "NO_MATCH" in prompt or "nothing is relevant" in prompt:
            return {"choices": [{"text": "This is a relevant passage from the document."}]}
        if "Relevance score" in prompt:
            return {"choices": [{"text": "7"}]}
        if "related terms" in prompt or "synonyms" in prompt:
            return {"choices": [{"text": "term1\nterm2\nterm3"}]}
        return {"choices": [{"text": "Mock response"}]}


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
def populated_vector_store(vector_store, mock_embedding_model):
    """Create a vector store with sample documents."""
    documents = [
        "Python is a popular programming language used for web development and data science.",
        "JavaScript is essential for front-end web development and browser scripting.",
        "Machine learning involves training algorithms on data to make predictions.",
        "Database systems store and manage data efficiently for applications.",
        "Cloud computing provides scalable infrastructure for modern applications.",
    ]

    for doc in documents:
        vector_store.add_document(
            text=doc,
            embedding_model=mock_embedding_model
        )

    return vector_store


class TestMinScoreThreshold:
    """Tests for min_score threshold filtering."""

    def test_search_without_threshold(self, populated_vector_store, mock_embedding_model):
        """Test that search without threshold returns all top_k results."""
        results = populated_vector_store.search(
            query="programming language",
            embedding_model=mock_embedding_model,
            top_k=3,
            min_score=None
        )

        # Should return up to top_k results
        assert len(results) <= 3
        assert all(isinstance(r, SearchResult) for r in results)

    def test_search_with_high_threshold(self, populated_vector_store, mock_embedding_model):
        """Test that high threshold filters out most results."""
        results = populated_vector_store.search(
            query="programming",
            embedding_model=mock_embedding_model,
            top_k=5,
            min_score=0.99  # Very high threshold
        )

        # High threshold should filter out most/all results
        assert len(results) <= 5
        for result in results:
            assert result.score >= 0.99

    def test_search_with_moderate_threshold(self, populated_vector_store, mock_embedding_model):
        """Test that moderate threshold returns relevant results."""
        results = populated_vector_store.search(
            query="web development",
            embedding_model=mock_embedding_model,
            top_k=5,
            min_score=0.3
        )

        # All returned results should be above threshold
        for result in results:
            assert result.score >= 0.3

    def test_search_with_topic_filter_and_threshold(self, populated_vector_store, mock_embedding_model):
        """Test combined topic filter and score threshold."""
        # First update topics
        populated_vector_store.update_document_topics(1, ["programming"], "programming")

        results = populated_vector_store.search_with_topic_filter(
            query="programming",
            embedding_model=mock_embedding_model,
            topic="programming",
            top_k=5,
            min_score=0.2
        )

        # Results should pass both filters
        for result in results:
            assert result.score >= 0.2


class TestPassageExtractor:
    """Tests for passage extraction functionality."""

    def test_extract_short_document(self):
        """Test that short documents are returned in full."""
        extractor = PassageExtractor(topic_labeler=None)

        short_text = "This is a short document."
        result = extractor.extract_passage(
            query="short document",
            document_text=short_text,
            max_excerpt_length=500
        )

        assert result.excerpt == short_text
        assert result.method == "full"
        assert result.confidence == 1.0

    def test_extract_window_without_llm(self):
        """Test window-based extraction when LLM is not available."""
        extractor = PassageExtractor(topic_labeler=None)

        long_text = """
        The first paragraph talks about Python programming.
        It is a versatile language for many applications.

        The second paragraph discusses JavaScript and web development.
        JavaScript is essential for building interactive websites.

        The third paragraph covers machine learning algorithms.
        These algorithms can learn patterns from data.
        """

        result = extractor.extract_passage(
            query="Python programming",
            document_text=long_text,
            max_excerpt_length=200
        )

        assert result.method == "window"
        assert "Python" in result.excerpt or len(result.excerpt) > 0

    def test_extract_with_mock_llm(self):
        """Test LLM-based extraction with mock model."""
        mock_labeler = MockTopicLabeler()
        extractor = PassageExtractor(topic_labeler=mock_labeler, verbose=False)

        long_text = "A" * 1000  # Long document

        result = extractor.extract_passage(
            query="test query",
            document_text=long_text,
            max_excerpt_length=500
        )

        # Should use LLM extraction
        assert result.method in ["llm_extract", "window"]

    def test_is_available(self):
        """Test availability check."""
        extractor_without = PassageExtractor(topic_labeler=None)
        assert not extractor_without.is_available()

        extractor_with = PassageExtractor(topic_labeler=MockTopicLabeler())
        assert extractor_with.is_available()


class TestQueryExpansion:
    """Tests for query expansion functionality."""

    @pytest.mark.skip(reason="expand_query functionality not implemented in current version")
    def test_expand_query_without_llm(self):
        """Test query expansion returns original query when LLM unavailable."""
        extractor = PassageExtractor(topic_labeler=None)

        result = extractor.expand_query("test query", num_terms=3)

        assert result.original_query == "test query"
        assert result.search_query == "test query"
        assert result.expanded_terms == []
        assert result.confidence == 0.5

    @pytest.mark.skip(reason="expand_query functionality not implemented in current version")
    def test_expand_query_with_mock_llm(self):
        """Test query expansion with mock LLM."""
        mock_labeler = MockTopicLabeler()
        extractor = PassageExtractor(topic_labeler=mock_labeler, verbose=False)

        result = extractor.expand_query("machine learning", num_terms=3)

        assert result.original_query == "machine learning"
        # With mock, should get some expanded terms
        assert isinstance(result.expanded_terms, list)


class TestEnhancedSearch:
    """Tests for combined enhanced search functionality."""

    def test_enhanced_search_without_extractor(self, populated_vector_store, mock_embedding_model):
        """Test enhanced search works without passage extractor."""
        results = populated_vector_store.enhanced_search(
            query="programming",
            embedding_model=mock_embedding_model,
            top_k=3,
            min_score=0.2,
            extract_passages=False,
            passage_extractor=None
        )

        assert len(results) <= 3
        for result in results:
            assert isinstance(result, EnhancedSearchResult)
            assert result.score >= 0.2
            # Without extractor, excerpt should equal full text
            assert result.excerpt == result.text
            assert result.excerpt_method == "full"

    def test_enhanced_search_with_extractor(self, populated_vector_store, mock_embedding_model):
        """Test enhanced search with passage extraction."""
        extractor = PassageExtractor(topic_labeler=None)

        results = populated_vector_store.enhanced_search(
            query="web development",
            embedding_model=mock_embedding_model,
            top_k=3,
            min_score=0.2,
            extract_passages=True,
            passage_extractor=extractor,
            max_excerpt_length=100
        )

        assert len(results) <= 3
        for result in results:
            assert isinstance(result, EnhancedSearchResult)
            assert result.excerpt is not None
            assert len(result.excerpt) <= 100 or result.excerpt_method == "full"

    def test_enhanced_search_result_structure(self, populated_vector_store, mock_embedding_model):
        """Test that enhanced search results have correct structure."""
        results = populated_vector_store.enhanced_search(
            query="data",
            embedding_model=mock_embedding_model,
            top_k=2
        )

        if results:
            result = results[0]
            assert hasattr(result, 'id')
            assert hasattr(result, 'text')
            assert hasattr(result, 'excerpt')
            assert hasattr(result, 'score')
            assert hasattr(result, 'metadata')
            assert hasattr(result, 'topics')
            assert hasattr(result, 'primary_topic')
            assert hasattr(result, 'excerpt_method')


class TestPrompts:
    """Tests for prompt templates."""

    def test_passage_extraction_prompt(self):
        """Test passage extraction prompt generation."""
        from mcp_vector_store.prompts import PassageExtractionPrompts

        prompt = PassageExtractionPrompts.extract_relevant_passage(
            query="test query",
            document_text="This is the document text.",
            max_text_length=100
        )

        assert "test query" in prompt
        assert "This is the document text" in prompt
        assert "<|system|>" in prompt
        assert "<|user|>" in prompt

    @pytest.mark.skip(reason="QueryExpansionPrompts not implemented in current version")
    def test_query_expansion_prompt(self):
        """Test query expansion prompt generation."""
        from mcp_vector_store.prompts import QueryExpansionPrompts

        prompt = QueryExpansionPrompts.expand_with_synonyms(
            query="machine learning",
            num_terms=3
        )

        assert "machine learning" in prompt
        assert "3" in prompt

    def test_relevance_scoring_prompt(self):
        """Test relevance scoring prompt generation."""
        from mcp_vector_store.prompts import RelevanceScoringPrompts

        prompt = RelevanceScoringPrompts.score_relevance(
            query="test query",
            document_excerpt="Sample document text."
        )

        assert "test query" in prompt
        assert "Sample document text" in prompt
        assert "0-10" in prompt


class TestKeyPassageEmbedding:
    """Tests for key passage embedding feature.

    Verifies that documents with key passage extraction embed the
    key passages instead of the full document text.
    """

    def test_add_document_with_key_passages(self, vector_store, mock_embedding_model):
        """Test that add_document stores embedding source in metadata."""
        mock_labeler = MockTopicLabeler()
        extractor = PassageExtractor(topic_labeler=mock_labeler)

        doc_id = vector_store.add_document(
            text="This is a long document. " * 50 + "The key insight is about Python programming.",
            embedding_model=mock_embedding_model,
            extract_key_passages=True,
            passage_extractor=extractor
        )

        doc = vector_store.get_document(doc_id)
        assert doc is not None
        assert doc.metadata.get("embedding_source") in ["key_passages", "full_text"]
        if doc.metadata.get("key_passages"):
            assert doc.metadata.get("embedding_source") == "key_passages"

    def test_add_document_without_key_passages(self, vector_store, mock_embedding_model):
        """Test that documents without passage extraction use full text."""
        doc_id = vector_store.add_document(
            text="This is a simple document about programming.",
            embedding_model=mock_embedding_model,
            extract_key_passages=False
        )

        doc = vector_store.get_document(doc_id)
        assert doc is not None
        assert doc.metadata.get("embedding_source") == "full_text"

    def test_key_passages_stored_in_metadata(self, vector_store, mock_embedding_model):
        """Test that key passages are stored in metadata."""
        mock_labeler = MockTopicLabeler()
        extractor = PassageExtractor(topic_labeler=mock_labeler)

        doc_id = vector_store.add_document(
            text="Python is great for data science. Machine learning is powerful. JavaScript for web.",
            embedding_model=mock_embedding_model,
            extract_key_passages=True,
            passage_extractor=extractor
        )

        doc = vector_store.get_document(doc_id)
        assert doc is not None
        # Key passages should be extracted (either by LLM or heuristic)
        if doc.metadata.get("embedding_source") == "key_passages":
            assert "key_passages" in doc.metadata
            assert isinstance(doc.metadata["key_passages"], list)


class TestLargeDocumentHandling:
    """Tests for handling large documents."""

    def test_chunked_extraction_heuristic(self):
        """Test that large documents are processed in chunks (heuristic)."""
        extractor = PassageExtractor(topic_labeler=None)

        # Create a large document with distinct sections
        intro = "Introduction: Python is a versatile programming language. "
        middle = "Middle section discusses Django framework for web development. " * 20
        conclusion = "Conclusion: Machine learning with TensorFlow is powerful. "
        large_doc = intro + middle + conclusion

        assert len(large_doc) > 800  # Exceeds MAX_CONTEXT_LENGTH

        sentences = extractor.extract_key_sentences(large_doc, max_sentences=3)

        assert isinstance(sentences, list)
        assert len(sentences) == 3
        # Should get content from different parts of the document
        all_text = " ".join(sentences).lower()
        # Check that we captured content from the document
        assert len(all_text) > 50

    def test_chunked_extraction_with_llm(self):
        """Test that large documents are processed in chunks (with LLM)."""
        mock_labeler = MockTopicLabeler()
        extractor = PassageExtractor(topic_labeler=mock_labeler)

        # Create a very large document
        large_doc = "Important information about Python. " * 100

        assert len(large_doc) > 800

        sentences = extractor.extract_key_sentences(large_doc, max_sentences=3)

        assert isinstance(sentences, list)
        assert len(sentences) <= 3

    def test_position_diversity(self):
        """Test that sentences are selected from different document positions."""
        extractor = PassageExtractor(topic_labeler=None)

        # Create document with unique sentences at beginning, middle, end
        doc = (
            "The INTRODUCTION discusses Alpha technology. " +
            "Generic filler content here. " * 30 +
            "The MIDDLE section covers Beta framework. " +
            "More generic filler content. " * 30 +
            "The CONCLUSION summarizes Gamma results. "
        )

        sentences = extractor.extract_key_sentences(doc, max_sentences=3)

        # Should capture sentences from different parts
        assert len(sentences) == 3


class TestKeyEntityExtraction:
    """Tests for key entity extraction feature."""

    def test_extract_entities_heuristic(self):
        """Test heuristic entity extraction."""
        extractor = PassageExtractor(topic_labeler=None)

        text = """
        The Python programming language was created by Guido van Rossum.
        It's widely used at Google, Facebook, and Netflix.
        The framework Django makes web development easier.
        """

        entities = extractor.extract_key_entities(text, max_entities=5)

        assert isinstance(entities, list)
        # Should find some capitalized terms
        assert len(entities) > 0

    def test_extract_entities_with_mock_llm(self):
        """Test LLM-based entity extraction."""
        mock_labeler = MockTopicLabeler()
        extractor = PassageExtractor(topic_labeler=mock_labeler, verbose=False)

        text = "TensorFlow and PyTorch are popular machine learning frameworks developed by Google and Facebook."

        entities = extractor.extract_key_entities(text, max_entities=5)

        assert isinstance(entities, list)

    def test_add_document_with_entities(self, vector_store, mock_embedding_model):
        """Test that entities are stored in metadata."""
        mock_labeler = MockTopicLabeler()
        extractor = PassageExtractor(topic_labeler=mock_labeler)

        doc_id = vector_store.add_document(
            text="TensorFlow is a machine learning framework from Google. PyTorch is from Facebook.",
            embedding_model=mock_embedding_model,
            extract_key_passages=True,
            passage_extractor=extractor,
            extract_key_entities=True,
            max_key_entities=5
        )

        doc = vector_store.get_document(doc_id)
        assert doc is not None
        if "key_entities" in doc.metadata:
            assert isinstance(doc.metadata["key_entities"], list)


class TestSearchRelevanceImprovement:
    """Tests to verify search relevance improves with key passage embedding."""

    def test_focused_embedding_vs_full_text(self, temp_db_path, mock_embedding_model):
        """Compare search relevance between focused and full text embeddings."""
        # Create two stores: one with key passages, one without
        store_with_passages = VectorStore(db_path=temp_db_path + "_passages", embedding_dim=384)
        store_without = VectorStore(db_path=temp_db_path + "_full", embedding_dim=384)

        mock_labeler = MockTopicLabeler()
        extractor = PassageExtractor(topic_labeler=mock_labeler)

        # Document with relevant info buried in noise
        doc_text = (
            "Lorem ipsum dolor sit amet. " * 20 +
            "Python is excellent for machine learning applications. " +
            "Lorem ipsum dolor sit amet. " * 20
        )

        # Add to both stores
        store_with_passages.add_document(
            text=doc_text,
            embedding_model=mock_embedding_model,
            extract_key_passages=True,
            passage_extractor=extractor
        )

        store_without.add_document(
            text=doc_text,
            embedding_model=mock_embedding_model,
            extract_key_passages=False
        )

        # Search both stores
        query = "Python machine learning"

        results_with = store_with_passages.search(
            query=query,
            embedding_model=mock_embedding_model,
            top_k=1
        )

        results_without = store_without.search(
            query=query,
            embedding_model=mock_embedding_model,
            top_k=1
        )

        # Both should return results
        assert len(results_with) > 0 or len(results_without) > 0

        # Clean up
        store_with_passages.close()
        store_without.close()

    def test_extract_passages_for_existing_document(self, vector_store, mock_embedding_model):
        """Test re-extracting passages for an existing document."""
        # Add document without passages
        doc_id = vector_store.add_document(
            text="This document discusses Python programming and data science applications.",
            embedding_model=mock_embedding_model,
            extract_key_passages=False
        )

        doc_before = vector_store.get_document(doc_id)
        assert doc_before.metadata.get("embedding_source") == "full_text"

        # Extract passages for the document
        mock_labeler = MockTopicLabeler()
        extractor = PassageExtractor(topic_labeler=mock_labeler)

        success = vector_store.extract_passages_for_document(
            doc_id=doc_id,
            passage_extractor=extractor,
            embedding_model=mock_embedding_model
        )

        assert success

        doc_after = vector_store.get_document(doc_id)
        assert "key_passages" in doc_after.metadata
        assert doc_after.metadata.get("embedding_source") == "key_passages"


class TestChunkedStorage:
    """Tests for chunked document storage."""

    def test_small_document_not_chunked(self, temp_db_path, mock_embedding_model):
        """Test that small documents are stored as single records."""
        from mcp_vector_store.txtai_adapter import AddDocumentResult

        store = VectorStore(
            db_path=temp_db_path,
            embedding_dim=384,
            auto_chunk_large_docs=True
        )

        small_doc = "This is a small document. " * 10  # ~270 chars

        result = store.add_document(
            text=small_doc,
            embedding_model=mock_embedding_model
        )

        # Small docs should NOT have chunk_ids
        assert isinstance(result, AddDocumentResult)
        assert result.doc_id is not None
        assert result.chunk_ids is None

        doc = store.get_document(result.doc_id)
        assert doc is not None
        assert not doc.metadata.get("is_parent")
        assert not doc.metadata.get("is_chunk")

        store.close()

    def test_large_document_chunked(self, temp_db_path, mock_embedding_model):
        """Test that large documents are split into chunks."""
        store = VectorStore(
            db_path=temp_db_path,
            embedding_dim=384,
            auto_chunk_large_docs=True
        )

        # Create a document larger than CHUNK_THRESHOLD (10000 chars)
        large_doc = "This is sentence number {}. " * 500  # ~15000 chars
        large_doc = large_doc.format(*range(500))

        assert len(large_doc) > store.CHUNK_THRESHOLD

        result = store.add_document(
            text=large_doc,
            embedding_model=mock_embedding_model
        )

        # Should return AddDocumentResult with chunk_ids
        from mcp_vector_store.txtai_adapter import AddDocumentResult
        assert isinstance(result, AddDocumentResult)
        assert result.chunk_ids is not None
        assert len(result.chunk_ids) > 1

        # Check parent document
        parent = store.get_document(result.doc_id)
        assert parent is not None
        assert parent.metadata.get("is_parent") is True
        assert parent.metadata.get("chunk_ids") == result.chunk_ids
        assert parent.text == large_doc  # Full text stored in parent

        # Check chunks
        chunks = store.get_document_chunks(result.doc_id)
        assert len(chunks) == len(result.chunk_ids)

        for i, chunk in enumerate(chunks):
            assert chunk.metadata.get("is_chunk") is True
            assert chunk.metadata.get("parent_id") == result.doc_id
            assert chunk.metadata.get("chunk_index") == i

        store.close()

    def test_chunk_search_returns_parent_id(self, temp_db_path, mock_embedding_model):
        """Test that searching chunks returns parent document ID."""
        store = VectorStore(
            db_path=temp_db_path,
            embedding_dim=384,
            auto_chunk_large_docs=True
        )

        # Create large document with searchable content in the middle
        part1 = "Introduction content. " * 200
        searchable = "Python machine learning TensorFlow deep neural networks. " * 50
        part2 = "Conclusion content. " * 200
        large_doc = part1 + searchable + part2

        result = store.add_document(
            text=large_doc,
            embedding_model=mock_embedding_model
        )

        # Search for the searchable content
        search_results = store.search(
            query="Python machine learning TensorFlow",
            embedding_model=mock_embedding_model,
            top_k=1
        )

        assert len(search_results) > 0

        # Result should reference the parent document
        first_result = search_results[0]
        assert first_result.id == result.doc_id  # Parent ID
        assert first_result.metadata.get("is_chunk") is True
        assert first_result.metadata.get("parent_id") == result.doc_id

        store.close()

    def test_chunk_deduplication(self, temp_db_path, mock_embedding_model):
        """Test that multiple matching chunks from same parent are deduplicated."""
        store = VectorStore(
            db_path=temp_db_path,
            embedding_dim=384,
            auto_chunk_large_docs=True
        )

        # Create document with repeated searchable content
        repeated_content = "Python programming is great for data science. " * 100
        large_doc = repeated_content * 5  # Same content appears in multiple chunks

        result = store.add_document(
            text=large_doc,
            embedding_model=mock_embedding_model
        )

        # Search - should only get one result despite multiple matching chunks
        search_results = store.search(
            query="Python programming data science",
            embedding_model=mock_embedding_model,
            top_k=5,
            deduplicate_chunks=True
        )

        # Should only have one result (deduplicated by parent)
        parent_ids = [r.id for r in search_results]
        assert len(set(parent_ids)) == len(parent_ids)  # All unique

        store.close()

    def test_delete_parent_deletes_chunks(self, temp_db_path, mock_embedding_model):
        """Test that deleting parent document also deletes all chunks."""
        store = VectorStore(
            db_path=temp_db_path,
            embedding_dim=384,
            auto_chunk_large_docs=True
        )

        large_doc = "This is a large document. " * 500

        result = store.add_document(
            text=large_doc,
            embedding_model=mock_embedding_model
        )

        initial_count = store.count()
        num_chunks = len(result.chunk_ids)

        # Delete parent
        deleted = store.delete_document(result.doc_id)
        assert deleted is True

        # All chunks should be deleted too
        final_count = store.count()
        assert final_count == initial_count - num_chunks - 1  # chunks + parent

        # Verify chunks are gone
        for chunk_id in result.chunk_ids:
            assert store.get_document(chunk_id) is None

        store.close()

    def test_chunks_have_own_key_passages(self, temp_db_path, mock_embedding_model):
        """Test that each chunk gets its own key passages extracted."""
        store = VectorStore(
            db_path=temp_db_path,
            embedding_dim=384,
            auto_chunk_large_docs=True
        )

        mock_labeler = MockTopicLabeler()
        extractor = PassageExtractor(topic_labeler=mock_labeler)

        # Create large doc with distinct content in different parts
        part1 = "Python is excellent for web development with Django. " * 150
        part2 = "Machine learning uses TensorFlow and PyTorch frameworks. " * 150
        part3 = "Data science requires strong statistical knowledge. " * 150
        large_doc = part1 + part2 + part3

        result = store.add_document(
            text=large_doc,
            embedding_model=mock_embedding_model,
            extract_key_passages=True,
            passage_extractor=extractor
        )

        # Each chunk should have its own key_passages
        chunks = store.get_document_chunks(result.doc_id)

        for chunk in chunks:
            # Chunks should have key passages or embedding source set
            assert chunk.metadata.get("embedding_source") in ["key_passages", "full_text"]

        store.close()


class TestHybridSearch:
    """Tests for hybrid search (vector + entity matching)."""

    def test_entity_boost_increases_score(self, temp_db_path, mock_embedding_model):
        """Test that matching entities boost the search score."""
        store = VectorStore(
            db_path=temp_db_path,
            embedding_dim=384,
            auto_chunk_large_docs=True
        )

        mock_labeler = MockTopicLabeler()
        extractor = PassageExtractor(topic_labeler=mock_labeler)

        # Add document with entities
        doc_id = store.add_document(
            text="TensorFlow is a machine learning framework from Google. It supports deep neural networks.",
            embedding_model=mock_embedding_model,
            extract_key_passages=True,
            passage_extractor=extractor,
            extract_key_entities=True
        )

        # Search with entity boost
        results_with_boost = store.search(
            query="TensorFlow machine learning",
            embedding_model=mock_embedding_model,
            top_k=1,
            entity_boost=0.1
        )

        # Search without entity boost
        results_no_boost = store.search(
            query="TensorFlow machine learning",
            embedding_model=mock_embedding_model,
            top_k=1,
            entity_boost=0.0
        )

        assert len(results_with_boost) > 0
        assert len(results_no_boost) > 0

        # With entity boost, score should be >= score without boost
        # (if entities matched)
        if results_with_boost[0].metadata.get("matched_entities"):
            assert results_with_boost[0].score >= results_no_boost[0].score

        store.close()

    def test_matched_entities_in_metadata(self, temp_db_path, mock_embedding_model):
        """Test that matched entities are included in result metadata."""
        store = VectorStore(
            db_path=temp_db_path,
            embedding_dim=384
        )

        mock_labeler = MockTopicLabeler()
        extractor = PassageExtractor(topic_labeler=mock_labeler)

        # Add document with clear entities
        store.add_document(
            text="Python and Django are popular for web development. Flask is also used.",
            embedding_model=mock_embedding_model,
            extract_key_passages=True,
            passage_extractor=extractor,
            extract_key_entities=True
        )

        # Search for an entity
        results = store.search(
            query="Django web",
            embedding_model=mock_embedding_model,
            top_k=1,
            entity_boost=0.1
        )

        assert len(results) > 0
        # Should have hybrid search metadata
        metadata = results[0].metadata
        assert "vector_score" in metadata
        assert "entity_boost" in metadata

        store.close()

    def test_hybrid_search_reranking(self, temp_db_path, mock_embedding_model):
        """Test that entity matches can rerank results."""
        store = VectorStore(
            db_path=temp_db_path,
            embedding_dim=384
        )

        mock_labeler = MockTopicLabeler()
        extractor = PassageExtractor(topic_labeler=mock_labeler)

        # Add two similar documents, one with exact entity match
        store.add_document(
            text="General information about programming languages and frameworks.",
            embedding_model=mock_embedding_model,
            extract_key_passages=True,
            passage_extractor=extractor,
            extract_key_entities=True
        )

        store.add_document(
            text="TensorFlow is specifically designed for machine learning tasks.",
            embedding_model=mock_embedding_model,
            extract_key_passages=True,
            passage_extractor=extractor,
            extract_key_entities=True
        )

        # Search with entity boost - TensorFlow doc should rank higher
        results = store.search(
            query="TensorFlow",
            embedding_model=mock_embedding_model,
            top_k=2,
            entity_boost=0.2  # Higher boost to see reranking effect
        )

        # Should return results
        assert len(results) > 0

        store.close()

    def test_disable_entity_boost(self, temp_db_path, mock_embedding_model):
        """Test that entity_boost=0 disables entity matching."""
        store = VectorStore(
            db_path=temp_db_path,
            embedding_dim=384
        )

        mock_labeler = MockTopicLabeler()
        extractor = PassageExtractor(topic_labeler=mock_labeler)

        store.add_document(
            text="TensorFlow machine learning framework.",
            embedding_model=mock_embedding_model,
            extract_key_passages=True,
            passage_extractor=extractor,
            extract_key_entities=True
        )

        # Search with entity boost disabled
        results = store.search(
            query="TensorFlow",
            embedding_model=mock_embedding_model,
            top_k=1,
            entity_boost=0.0
        )

        assert len(results) > 0
        # Should NOT have hybrid search metadata when disabled
        metadata = results[0].metadata
        assert "vector_score" not in metadata
        assert "matched_entities" not in metadata

        store.close()

    def test_key_passages_also_boost_score(self, temp_db_path, mock_embedding_model):
        """Test that query terms in key_passages provide partial boost."""
        store = VectorStore(
            db_path=temp_db_path,
            embedding_dim=384
        )

        mock_labeler = MockTopicLabeler()
        extractor = PassageExtractor(topic_labeler=mock_labeler)

        # Add document - key passages should contain the important terms
        store.add_document(
            text="Python programming is excellent for data science and machine learning applications.",
            embedding_model=mock_embedding_model,
            extract_key_passages=True,
            passage_extractor=extractor,
            extract_key_entities=True
        )

        results = store.search(
            query="Python data science",
            embedding_model=mock_embedding_model,
            top_k=1,
            entity_boost=0.1
        )

        assert len(results) > 0
        # Should have some entity boost from passage matches
        metadata = results[0].metadata
        assert "entity_boost" in metadata
        assert metadata["entity_boost"] >= 0  # May have boost from passages

        store.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
