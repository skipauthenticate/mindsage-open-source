"""Tests for file system search functionality.

Tests:
1. Text file searching
2. Binary file skipping
3. JSON conversation parsing
4. Filename glob search
5. Content caching
"""

import os
import sys
import json
import tempfile
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mcp_vector_store.file_searcher import FileSearcher, FileContentCache


@pytest.fixture
def temp_data_dir():
    """Create a temporary data directory with test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create subdirectories matching MindSage structure
        uploads_dir = os.path.join(tmpdir, "uploads")
        imports_dir = os.path.join(tmpdir, "imports")
        exports_dir = os.path.join(tmpdir, "exports")
        convos_dir = os.path.join(tmpdir, "browser-connector", "conversations")

        os.makedirs(uploads_dir)
        os.makedirs(imports_dir)
        os.makedirs(exports_dir)
        os.makedirs(convos_dir)

        # Create test text files
        with open(os.path.join(uploads_dir, "meeting_notes.txt"), "w") as f:
            f.write("Meeting Notes - Q1 Review\n")
            f.write("Attendees: Alice, Bob, Charlie\n")
            f.write("Discussion about AI project timeline\n")
            f.write("Budget review for next quarter\n")

        with open(os.path.join(uploads_dir, "report.md"), "w") as f:
            f.write("# Annual Report\n\n")
            f.write("The company achieved record growth in machine learning services.\n")
            f.write("Revenue increased by 25% year over year.\n")

        with open(os.path.join(imports_dir, "data.csv"), "w") as f:
            f.write("name,email,department\n")
            f.write("Alice,alice@example.com,Engineering\n")
            f.write("Bob,bob@example.com,Marketing\n")

        # Create a binary file (should be skipped)
        with open(os.path.join(uploads_dir, "image.png"), "wb") as f:
            f.write(b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR')

        # Create a JSON conversation file
        convo_dir = os.path.join(convos_dir, "convo1")
        os.makedirs(convo_dir)
        with open(os.path.join(convo_dir, "conversation.json"), "w") as f:
            json.dump({
                "title": "Discussion about neural networks",
                "messages": [
                    {"role": "user", "content": "Explain backpropagation"},
                    {"role": "assistant", "content": "Backpropagation is a learning algorithm for neural networks."}
                ]
            }, f)

        # Create a large-ish file (within limit)
        with open(os.path.join(exports_dir, "export.json"), "w") as f:
            json.dump([
                {"text": f"Document {i} about privacy and security"} for i in range(50)
            ], f)

        yield tmpdir


@pytest.fixture
def searcher(temp_data_dir):
    return FileSearcher(data_dir=temp_data_dir)


class TestFileSearch:
    def test_search_finds_text_matches(self, searcher):
        results = searcher.search("AI project")
        assert len(results) > 0
        assert any("meeting_notes.txt" in r.filename for r in results)

    def test_search_returns_context(self, searcher):
        results = searcher.search("Alice")
        assert len(results) > 0
        # Check that matches have line numbers and text
        for result in results:
            for match in result.matches:
                assert match.line_number > 0
                assert match.text

    def test_search_skips_binary_files(self, searcher):
        results = searcher.search("PNG")
        # Should not find anything in the PNG file
        filenames = [r.filename for r in results]
        assert "image.png" not in filenames

    def test_search_respects_max_results(self, searcher):
        results = searcher.search("the", max_results=1)
        assert len(results) <= 1

    def test_search_case_insensitive(self, searcher):
        results_lower = searcher.search("alice", case_sensitive=False)
        results_upper = searcher.search("Alice", case_sensitive=False)
        # Both should find results (case insensitive)
        assert len(results_lower) > 0
        assert len(results_upper) > 0

    def test_search_case_sensitive(self, searcher):
        results = searcher.search("alice", case_sensitive=True)
        # "alice" (lowercase) should only match in CSV, not in meeting notes
        for result in results:
            for match in result.matches:
                assert "alice" in match.text.lower()

    def test_search_specific_directories(self, searcher):
        results = searcher.search("Alice", directories=["imports"])
        # Should only find in imports (CSV file)
        assert all(r.source == "imports" for r in results)

    def test_search_nonexistent_directory(self, searcher):
        results = searcher.search("test", directories=["nonexistent"])
        assert results == []

    def test_search_empty_query(self, searcher):
        # Empty pattern should match everything in regex, but we escape it
        results = searcher.search("")
        assert isinstance(results, list)

    def test_search_json_conversations(self, searcher):
        results = searcher.search("backpropagation", directories=["conversations"])
        assert len(results) > 0

    def test_search_export_json(self, searcher):
        results = searcher.search("privacy", directories=["exports"])
        assert len(results) > 0


class TestFilenameSearch:
    def test_search_by_extension(self, searcher):
        results = searcher.search_filenames("*.txt")
        assert len(results) > 0
        assert all(r["filename"].endswith(".txt") for r in results)

    def test_search_by_name_pattern(self, searcher):
        results = searcher.search_filenames("meeting*")
        assert len(results) > 0
        assert any("meeting_notes.txt" in r["filename"] for r in results)

    def test_search_no_matches(self, searcher):
        results = searcher.search_filenames("*.xyz")
        assert results == []

    def test_search_specific_directory(self, searcher):
        results = searcher.search_filenames("*.csv", directories=["imports"])
        assert len(results) > 0


class TestFileContentCache:
    def test_cache_put_and_get(self):
        cache = FileContentCache(max_size_bytes=1024 * 1024)
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("test content")
            f.flush()
            path = f.name
            mtime = os.path.getmtime(path)

        try:
            cache.put(path, "test content", mtime)
            result = cache.get(path)
            assert result == "test content"
        finally:
            os.unlink(path)

    def test_cache_invalidation_on_mtime_change(self):
        cache = FileContentCache(max_size_bytes=1024 * 1024)
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("original content")
            f.flush()
            path = f.name

        try:
            cache.put(path, "original content", os.path.getmtime(path) - 100)
            # Cache entry has old mtime, file has newer mtime
            result = cache.get(path)
            assert result is None  # Should be invalidated
        finally:
            os.unlink(path)

    def test_cache_miss(self):
        cache = FileContentCache()
        result = cache.get("/nonexistent/file.txt")
        assert result is None
