"""Unit tests for reranker interface compatibility in TxtaiAdapter.enhanced_search."""

from types import SimpleNamespace

from mcp_vector_store.txtai_adapter import EnhancedSearchResult, TxtaiAdapter


def _make_adapter():
    """Create a lightweight adapter instance with a mocked search_enhanced path."""
    adapter = TxtaiAdapter.__new__(TxtaiAdapter)

    def mock_search_enhanced(**_kwargs):
        return [
            EnhancedSearchResult(id=1, text="doc one", excerpt="doc one", score=0.9, metadata={}),
            EnhancedSearchResult(id=2, text="doc two", excerpt="doc two", score=0.8, metadata={}),
            EnhancedSearchResult(id=3, text="doc three", excerpt="doc three", score=0.7, metadata={}),
        ]

    adapter.search_enhanced = mock_search_enhanced
    return adapter


def test_enhanced_search_uses_rerank_interface_when_available():
    adapter = _make_adapter()

    class MockWrapperReranker:
        def rerank(self, query, documents, top_k=None):
            assert query == "query"
            assert len(documents) == 3
            assert top_k == 3
            score_map = {1: 0.1, 2: 0.95, 3: 0.5}
            return [
                SimpleNamespace(id=doc_id, rerank_score=score_map[doc_id])
                for doc_id, _, _, _ in documents
            ]

    results = adapter.enhanced_search(
        query="query",
        limit=3,
        reranker=MockWrapperReranker(),
        rerank_top_k=3,
    )

    assert [r.id for r in results] == [2, 3, 1]


def test_enhanced_search_supports_predict_backcompat():
    adapter = _make_adapter()

    class MockPredictReranker:
        def predict(self, pairs):
            assert len(pairs) == 3
            return [0.2, 0.9, 0.1]

    results = adapter.enhanced_search(
        query="query",
        limit=3,
        reranker=MockPredictReranker(),
        rerank_top_k=3,
    )

    assert [r.id for r in results] == [2, 1, 3]


def test_enhanced_search_falls_back_when_reranker_interface_missing():
    adapter = _make_adapter()

    class InvalidReranker:
        pass

    results = adapter.enhanced_search(
        query="query",
        limit=3,
        reranker=InvalidReranker(),
        rerank_top_k=3,
    )

    # Should keep original order from search_enhanced
    assert [r.id for r in results] == [1, 2, 3]
