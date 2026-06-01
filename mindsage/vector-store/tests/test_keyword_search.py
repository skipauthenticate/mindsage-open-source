"""Tests for keyword search and metadata search functionality.

Tests:
1. FTS5 keyword-only search
2. Keyword search scoring
3. Metadata search by various filters
"""

import os
import sys
import tempfile
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def txtai_store(temp_dir):
    from mcp_vector_store.txtai_store import TxtaiStore
    store = TxtaiStore(data_dir=temp_dir, use_onnx=False)
    yield store
    store.close()


@pytest.fixture
def txtai_adapter(temp_dir):
    from mcp_vector_store.txtai_adapter import TxtaiAdapter
    adapter = TxtaiAdapter(db_path=temp_dir, use_onnx=False)
    yield adapter
    adapter.close()


@pytest.fixture
def populated_store(txtai_store):
    """Store with sample documents for testing."""
    import json
    docs = [
        ("Machine learning is a subset of artificial intelligence.",
         {"source": "import", "filename": "ml_intro.txt", "topics": ["technology", "AI"]}),
        ("Python is widely used for data science and machine learning.",
         {"source": "connector", "filename": "python_ds.pdf", "topics": ["programming"]}),
        ("The weather today is sunny with temperatures around 75 degrees.",
         {"source": "import", "filename": "weather.txt", "topics": ["weather"]}),
        ("Privacy policy: we collect minimal data for analytics purposes.",
         {"source": "browser", "filename": "privacy.html", "topics": ["legal", "privacy"]}),
        ("Cooking pasta requires boiling water and adding salt.",
         {"source": "import", "filename": "recipe.md", "topics": ["cooking"]}),
    ]
    for text, meta in docs:
        txtai_store.add_document(text, metadata=meta)
    return txtai_store


class TestKeywordSearch:
    def test_keyword_search_returns_results(self, populated_store):
        results = populated_store.keyword_search("machine learning", limit=5)
        assert len(results) > 0
        # Should find documents containing "machine learning"
        texts = [r.text.lower() for r in results]
        assert any("machine learning" in t for t in texts)

    def test_keyword_search_no_matches(self, populated_store):
        results = populated_store.keyword_search("quantum computing blockchain", limit=5)
        # May return some results via hybrid, but with low scores
        # The key test is that it doesn't crash
        assert isinstance(results, list)

    def test_keyword_search_empty_query(self, populated_store):
        # Empty index should return empty
        results = populated_store.keyword_search("", limit=5)
        assert isinstance(results, list)

    def test_keyword_search_special_characters(self, populated_store):
        # Should not crash with special characters
        results = populated_store.keyword_search("it's a test (with) 'quotes'", limit=5)
        assert isinstance(results, list)

    def test_keyword_search_respects_limit(self, populated_store):
        results = populated_store.keyword_search("the", limit=2)
        assert len(results) <= 2

    def test_keyword_search_empty_store(self, txtai_store):
        results = txtai_store.keyword_search("test", limit=5)
        assert results == []

    def test_keyword_search_score_ordering(self, populated_store):
        results = populated_store.keyword_search("machine learning", limit=10)
        if len(results) >= 2:
            # Results should be sorted by score descending
            scores = [r.score for r in results]
            assert scores == sorted(scores, reverse=True)


class TestMetadataSearch:
    def test_metadata_search_by_filename(self, populated_store):
        results = populated_store.metadata_search(filename="*.txt")
        assert len(results) > 0
        for r in results:
            fname = r.metadata.get("filename", "")
            assert fname.endswith(".txt")

    def test_metadata_search_by_source(self, populated_store):
        results = populated_store.metadata_search(source="import")
        assert len(results) > 0
        for r in results:
            assert "import" in r.metadata.get("source", "").lower()

    def test_metadata_search_by_topic(self, populated_store):
        results = populated_store.metadata_search(topic="privacy")
        assert len(results) > 0
        for r in results:
            topics = r.metadata.get("topics", [])
            assert any("privacy" in t.lower() for t in topics)

    def test_metadata_search_no_filters(self, populated_store):
        # Should return all documents when no filters
        results = populated_store.metadata_search()
        assert len(results) >= 5

    def test_metadata_search_no_matches(self, populated_store):
        results = populated_store.metadata_search(filename="nonexistent_*.xyz")
        assert len(results) == 0

    def test_metadata_search_combined_filters(self, populated_store):
        results = populated_store.metadata_search(source="import", filename="*.txt")
        for r in results:
            assert "import" in r.metadata.get("source", "").lower()
            assert r.metadata.get("filename", "").endswith(".txt")

    def test_metadata_search_respects_limit(self, populated_store):
        results = populated_store.metadata_search(limit=2)
        assert len(results) <= 2


class TestAdapterKeywordSearch:
    def test_adapter_search_keyword(self, txtai_adapter):
        """Test keyword search through the adapter layer."""
        # Add a document
        txtai_adapter.add_document(
            text="Deep learning neural networks",
            metadata={"source": "test"}
        )
        results = txtai_adapter.search_keyword("neural", limit=5)
        assert isinstance(results, list)

    def test_adapter_search_metadata(self, txtai_adapter):
        """Test metadata search through the adapter layer."""
        txtai_adapter.add_document(
            text="Test document",
            metadata={"source": "import", "filename": "test.pdf"}
        )
        results = txtai_adapter.search_metadata(filename="*.pdf")
        assert isinstance(results, list)
