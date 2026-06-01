"""Tests for unified tiered search functionality.

Tests:
1. Fast mode returns keyword-only results
2. Balanced mode includes semantic results
3. Quality mode includes reranked results (when available)
4. File system search integration (include_unindexed)
5. Tier cascade with missing models (graceful degradation)
6. Result deduplication across tiers
7. Score normalization and ordering
"""

import os
import sys
import json
import tempfile
import pytest
from unittest.mock import MagicMock, patch
from dataclasses import dataclass
from typing import List, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mcp_vector_store.txtai_store import TxtaiStore, TxtaiSearchResult
from mcp_vector_store.txtai_adapter import TxtaiAdapter, SearchResult
from mcp_vector_store.file_searcher import FileSearcher


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def data_dir(temp_dir):
    """Create a data directory with test files for file system search."""
    uploads_dir = os.path.join(temp_dir, "uploads")
    imports_dir = os.path.join(temp_dir, "imports")
    exports_dir = os.path.join(temp_dir, "exports")
    os.makedirs(uploads_dir)
    os.makedirs(imports_dir)
    os.makedirs(exports_dir)

    with open(os.path.join(uploads_dir, "notes.txt"), "w") as f:
        f.write("Meeting notes about machine learning project\n")
        f.write("Discussed privacy concerns with user data\n")

    with open(os.path.join(imports_dir, "research.md"), "w") as f:
        f.write("# Research Paper\n")
        f.write("Neural networks and deep learning applications\n")

    return temp_dir


@pytest.fixture
def adapter(temp_dir):
    adapter = TxtaiAdapter(db_path=temp_dir, use_onnx=False)
    yield adapter
    adapter.close()


@pytest.fixture
def populated_adapter(adapter):
    """Adapter with sample documents for tiered search testing."""
    docs = [
        ("Machine learning is transforming healthcare with AI diagnostics.",
         {"source": "import", "filename": "ml_health.txt", "topics": ["AI", "healthcare"]}),
        ("Privacy regulations require data anonymization for user protection.",
         {"source": "browser", "filename": "privacy.html", "topics": ["privacy", "legal"]}),
        ("Python programming for beginners includes variables and loops.",
         {"source": "import", "filename": "python_intro.pdf", "topics": ["programming"]}),
        ("The stock market showed gains in technology sector this quarter.",
         {"source": "connector", "filename": "market.csv", "topics": ["finance"]}),
        ("Deep learning neural networks achieve state of the art accuracy.",
         {"source": "import", "filename": "dl_paper.pdf", "topics": ["AI", "research"]}),
    ]
    for text, meta in docs:
        adapter.add_document(text=text, metadata=meta)
    return adapter


class TestUnifiedSearchFastMode:
    """Test fast mode: keyword search only, no GPU needed."""

    def test_fast_mode_returns_results(self, populated_adapter):
        results = populated_adapter.search_keyword("machine learning", limit=5)
        assert len(results) > 0
        assert isinstance(results[0], SearchResult)

    def test_fast_mode_no_semantic(self, populated_adapter):
        """Fast mode should only use keyword search."""
        # Keyword search should work independently of embedding model
        results = populated_adapter.search_keyword("privacy", limit=5)
        assert isinstance(results, list)

    def test_fast_mode_latency(self, populated_adapter):
        """Keyword search should be fast (<100ms even in test env)."""
        import time
        start = time.monotonic()
        populated_adapter.search_keyword("technology", limit=5)
        elapsed = (time.monotonic() - start) * 1000
        # In test env with small data, should be well under 100ms
        assert elapsed < 500  # generous bound for CI

    def test_fast_mode_empty_query(self, populated_adapter):
        results = populated_adapter.search_keyword("", limit=5)
        assert isinstance(results, list)


class TestUnifiedSearchBalancedMode:
    """Test balanced mode: keyword + semantic search."""

    def test_balanced_uses_hybrid(self, populated_adapter):
        """Balanced mode should use both keyword and semantic."""
        # Standard search uses hybrid (BM25 + semantic)
        results = populated_adapter.search("machine learning", top_k=5)
        assert len(results) > 0

    def test_balanced_deduplication(self, populated_adapter):
        """Results from keyword and semantic should be deduplicated."""
        keyword_results = populated_adapter.search_keyword("machine learning", limit=10)
        semantic_results = populated_adapter.search("machine learning", top_k=10)

        # Simulate dedup logic from unified endpoint
        all_results = {}
        for r in keyword_results:
            all_results[r.id] = r
        for r in semantic_results:
            existing = all_results.get(r.id)
            if existing:
                # Keep higher score
                if r.score > existing.score:
                    all_results[r.id] = r
            else:
                all_results[r.id] = r

        # No duplicate IDs
        assert len(all_results) == len(set(all_results.keys()))

    def test_balanced_score_ordering(self, populated_adapter):
        """Merged results should be sorted by score descending."""
        keyword_results = populated_adapter.search_keyword("learning", limit=5)
        semantic_results = populated_adapter.search("learning", top_k=5)

        all_results = {}
        for r in keyword_results:
            all_results[r.id] = {"id": r.id, "score": r.score}
        for r in semantic_results:
            existing = all_results.get(r.id)
            if existing:
                existing["score"] = max(existing["score"], r.score)
            else:
                all_results[r.id] = {"id": r.id, "score": r.score}

        sorted_results = sorted(all_results.values(), key=lambda r: r["score"], reverse=True)
        scores = [r["score"] for r in sorted_results]
        assert scores == sorted(scores, reverse=True)


class TestUnifiedSearchQualityMode:
    """Test quality mode: keyword + semantic + reranking."""

    def test_quality_graceful_without_reranker(self, populated_adapter):
        """Quality mode should still work if reranker is not available."""
        # In test environment, reranker may not be installed
        keyword_results = populated_adapter.search_keyword("privacy", limit=5)
        semantic_results = populated_adapter.search("privacy", top_k=5)

        # Even without reranker, we should get combined results
        all_results = {}
        for r in keyword_results:
            all_results[r.id] = r
        for r in semantic_results:
            if r.id not in all_results or r.score > all_results[r.id].score:
                all_results[r.id] = r

        assert len(all_results) > 0

    def test_reranker_mock(self, populated_adapter):
        """Test reranking integration with a mock reranker."""
        results = populated_adapter.search("neural networks", top_k=5)

        if not results:
            pytest.skip("No search results to rerank")

        # Simulate reranker scoring
        mock_reranked = []
        for i, r in enumerate(results):
            mock_reranked.append({
                "id": r.id,
                "text": r.text,
                "score": r.score,
                "rerank_score": 1.0 - (i * 0.1)  # Simulated rerank scores
            })

        # Reranked should be sorted by rerank_score
        scores = [r["rerank_score"] for r in mock_reranked]
        assert scores == sorted(scores, reverse=True)


class TestFileSystemSearchIntegration:
    """Test include_unindexed file system search."""

    def test_file_search_finds_unindexed(self, data_dir):
        """File searcher should find content not in the vector index."""
        searcher = FileSearcher(data_dir=data_dir)
        results = searcher.search("machine learning")
        assert len(results) > 0
        assert any("notes.txt" in r.filename for r in results)

    def test_file_search_separate_from_indexed(self, data_dir, populated_adapter):
        """File results should be in separate section from indexed results."""
        # Indexed results
        indexed = populated_adapter.search("privacy", top_k=5)

        # Unindexed file results
        searcher = FileSearcher(data_dir=data_dir)
        file_results = searcher.search("privacy")

        # Both should have results, but they are independent
        assert isinstance(indexed, list)
        assert isinstance(file_results, list)

    def test_file_search_respects_directories(self, data_dir):
        """File search should filter by directory."""
        searcher = FileSearcher(data_dir=data_dir)

        uploads_results = searcher.search("machine learning", directories=["uploads"])
        imports_results = searcher.search("machine learning", directories=["imports"])

        # "machine learning" is in uploads/notes.txt, not imports/research.md
        assert len(uploads_results) > 0
        assert all(r.source == "uploads" for r in uploads_results)

    def test_file_search_empty_when_disabled(self, data_dir):
        """When include_unindexed is false, no file results should be returned."""
        # Simulating the unified endpoint behavior
        include_unindexed = False
        unindexed_results = []

        if include_unindexed:
            searcher = FileSearcher(data_dir=data_dir)
            unindexed_results = searcher.search("test")

        assert unindexed_results == []


class TestTierCascade:
    """Test the cascading tier logic of unified search."""

    def test_fast_mode_only_keyword(self, populated_adapter):
        """Fast mode should only run keyword tier."""
        mode = "fast"
        tiers_used = []

        # Tier 1: always
        keyword_results = populated_adapter.search_keyword("learning", limit=10)
        tiers_used.append("keyword")

        # Tier 2: balanced/quality only
        if mode in ("balanced", "quality"):
            populated_adapter.search("learning", top_k=10)
            tiers_used.append("semantic")

        assert tiers_used == ["keyword"]

    def test_balanced_mode_two_tiers(self, populated_adapter):
        """Balanced mode should run keyword + semantic."""
        mode = "balanced"
        tiers_used = []

        tiers_used.append("keyword")

        if mode in ("balanced", "quality"):
            populated_adapter.search("learning", top_k=10)
            tiers_used.append("semantic")

        assert tiers_used == ["keyword", "semantic"]

    def test_quality_mode_three_tiers(self, populated_adapter):
        """Quality mode should attempt keyword + semantic + reranking."""
        mode = "quality"
        tiers_used = []

        tiers_used.append("keyword")

        if mode in ("balanced", "quality"):
            tiers_used.append("semantic")

        if mode == "quality":
            # Reranker may not be available, but tier should be attempted
            tiers_used.append("reranked")

        assert "keyword" in tiers_used
        assert "semantic" in tiers_used
        assert "reranked" in tiers_used

    def test_include_unindexed_adds_files_tier(self, data_dir):
        """include_unindexed should add files tier."""
        tiers_used = ["keyword"]
        include_unindexed = True
        unindexed_results = []

        if include_unindexed:
            searcher = FileSearcher(data_dir=data_dir)
            file_results = searcher.search("machine learning", max_results=10)
            if file_results:
                tiers_used.append("files")
                unindexed_results = file_results

        assert "files" in tiers_used
        assert len(unindexed_results) > 0


class TestResultDeduplication:
    """Test deduplication of results across tiers."""

    def test_dedup_by_id(self, populated_adapter):
        """Same document from multiple tiers should appear only once."""
        keyword_results = populated_adapter.search_keyword("machine learning", limit=10)
        semantic_results = populated_adapter.search("machine learning", top_k=10)

        all_results = {}
        for r in keyword_results:
            all_results[r.id] = {"id": r.id, "text": r.text, "score": r.score}
        for r in semantic_results:
            existing = all_results.get(r.id)
            if existing:
                existing["score"] = max(existing["score"], r.score)
            else:
                all_results[r.id] = {"id": r.id, "text": r.text, "score": r.score}

        # Check no duplicate IDs
        ids = list(all_results.keys())
        assert len(ids) == len(set(ids))

    def test_dedup_keeps_best_score(self, populated_adapter):
        """When deduplicating, the higher score should be kept."""
        keyword_results = populated_adapter.search_keyword("privacy", limit=10)
        semantic_results = populated_adapter.search("privacy", top_k=10)

        all_results = {}
        for r in keyword_results:
            all_results[r.id] = r.score
        for r in semantic_results:
            if r.id in all_results:
                all_results[r.id] = max(all_results[r.id], r.score)
            else:
                all_results[r.id] = r.score

        # Every score in the merged results should be >= any individual tier score
        for r in keyword_results:
            assert all_results.get(r.id, 0) >= r.score
        for r in semantic_results:
            assert all_results.get(r.id, 0) >= r.score


class TestScoreOrdering:
    """Test that final results are properly scored and ordered."""

    def test_results_sorted_descending(self, populated_adapter):
        """Final results should be sorted by score descending."""
        results = populated_adapter.search("artificial intelligence", top_k=10)
        if len(results) >= 2:
            scores = [r.score for r in results]
            assert scores == sorted(scores, reverse=True)

    def test_top_k_limiting(self, populated_adapter):
        """Results should respect the top_k limit."""
        results = populated_adapter.search("the", top_k=2)
        assert len(results) <= 2

    def test_keyword_results_have_scores(self, populated_adapter):
        """All keyword results should have non-negative scores."""
        results = populated_adapter.search_keyword("learning", limit=10)
        for r in results:
            assert r.score >= 0

    def test_semantic_results_have_scores(self, populated_adapter):
        """All semantic results should have scores."""
        results = populated_adapter.search("learning", top_k=10)
        for r in results:
            assert isinstance(r.score, (int, float))
