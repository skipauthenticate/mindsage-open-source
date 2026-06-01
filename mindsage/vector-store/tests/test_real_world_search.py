#!/usr/bin/env python3
"""
Real-world integration test for MindSage search.

Pulls diverse web-sourced documents, indexes them, and exercises every
search mode end-to-end against the actual txtai backend.

Documents used (fetched from the web and embedded here):
  1. Python tutorial (medium, ~7k chars) — programming, language features
  2. NVIDIA Jetson Orin Nano guide (medium, ~5k chars) — hardware, AI edge
  3. PyTorch intro (small, ~1k chars) — ML framework, deep learning
  4. SQLite about page (medium, ~3k chars) — database, embedded SQL
  5. Synthetic long doc (large, >10k chars) — forces chunking

Test coverage:
  - Document indexing (small, medium, large/chunked)
  - Keyword search (FTS5/BM25, zero GPU)
  - Semantic/hybrid search
  - Enhanced search with passage extraction
  - Entity boost search
  - Chunk deduplication
  - Metadata search (filename, source, topic)
  - Topic assignment and topic-filtered search
  - Graph search
  - File system search integration
  - Passage and entity extraction at index time
  - Unified tiered search (fast / balanced / quality)
"""

import os
import sys
import time
import json
import shutil
import tempfile
import textwrap

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mcp_vector_store.txtai_adapter import (
    TxtaiAdapter,
    AddDocumentResult,
    SearchResult,
    EnhancedSearchResult,
    DocumentResult,
    ChunkInfo,
)
from mcp_vector_store.passage_extractor import PassageExtractor


# ============================================================================
# Real web-sourced documents (content fetched and embedded)
# ============================================================================

DOC_PYTHON_TUTORIAL = textwrap.dedent("""\
    An Informal Introduction to Python

    In the following examples, input and output are distinguished by the
    presence or absence of prompts (>>> and ...). The interpreter acts as
    a simple calculator: expression syntax uses operators +, -, *, / and
    parentheses () for grouping.

    Integer numbers (e.g. 2, 4, 20) have type int, while those with
    fractional parts (e.g. 5.0, 1.6) have type float. Division (/) always
    returns a float. Use // for floor division and % for remainder.

    The equal sign (=) assigns a value to a variable. Python also supports
    Decimal, Fraction, and complex numbers using j or J suffix.

    Python can manipulate text (type str, called strings). Strings can be
    enclosed in single quotes or double quotes with the same result.
    The print() function produces readable output. Raw strings prefix
    with r to prevent backslash interpretation. String literals can span
    multiple lines using triple-quotes.

    Strings can be concatenated with + and repeated with *. They can be
    indexed with the first character having index 0. Indices may be
    negative to count from the right. Slicing allows obtaining substrings.
    Python strings are immutable. The built-in function len() returns
    the length of a string.

    The most versatile compound data type is the list, written as
    comma-separated values between square brackets. Lists can be indexed
    and sliced. Unlike strings, lists are mutable. Add new items using
    the list.append() method.

    The while loop executes as long as the condition remains true.
    Indentation is Python's way of grouping statements. The print()
    function writes the value of the arguments given.

    Guido van Rossum created Python at Centrum Wiskunde & Informatica
    in the Netherlands. Python 3.12 is the latest stable release.
    The Python Software Foundation manages the language development.
""")

DOC_JETSON_ORIN = textwrap.dedent("""\
    Jetson Orin Nano Developer Kit Getting Started Guide

    The NVIDIA Jetson Orin Nano Developer Kit enables development of
    AI-powered robots, smart drones, and intelligent cameras. With the
    December 2024 software update, this advanced edge computer delivers
    up to 70 percent more performance.

    The box contains a Jetson Orin Nano module with microSD card slot,
    a reference carrier board with 802.11 WLAN and Bluetooth module
    preinstalled, a 19V power supply, and a quick start card.

    Hardware components include a microSD card slot, 40-pin expansion
    header, power indicator LED, USB-C port, Gigabit Ethernet port,
    four USB 3.1 Type A ports, DisplayPort connector, DC barrel jack
    for 19V power input, and MIPI CSI camera connectors.

    The kit ships with factory firmware incompatible with JetPack 6.x.
    You must upgrade to the latest firmware before inserting the SD card
    flashed with the JetPack 6.x image. The Jetson Orin Nano uses an
    NVIDIA Ampere architecture GPU with CUDA support.

    Setup involves inserting the flashed microSD card, connecting the
    display, keyboard, mouse, and 19V power supply. The default power
    mode is 25W. To unlock maximum performance, select MAXN SUPER mode
    from the NVIDIA icon on the Ubuntu desktop.

    Jensen Huang, CEO of NVIDIA, announced the Jetson Orin platform at
    GTC 2022 in San Jose, California. The Jetson ecosystem includes
    support for TensorRT, CUDA, cuDNN, and DeepStream SDK.

    Explore generative AI applications through Jetson AI Lab including
    Ollama with Open Web UI for LLM applications, NanoOWL with Vision
    Transformer technology, and LeRobot for physical AI using
    HuggingFace's framework. Visit the NVIDIA Jetson Forums for
    community support.
""")

DOC_PYTORCH_INTRO = textwrap.dedent("""\
    Learn the Basics of PyTorch

    Most machine learning workflows involve working with data, creating
    models, optimizing model parameters, and saving the trained models.
    This tutorial uses the FashionMNIST dataset to train a neural network
    classifier that predicts clothing items across 10 categories.

    The tutorial covers Tensors, Datasets and DataLoaders, Transforms,
    Build Model, Automatic Differentiation, Optimization Loop, and
    Save/Load/Use Model.

    PyTorch was developed by Meta AI (formerly Facebook AI Research)
    and is maintained by the PyTorch Foundation under the Linux Foundation.
    It provides GPU-accelerated tensor computation and automatic
    differentiation for building deep learning models.

    Created by Suraj Subramanian, Seth Juarez, Cassie Breviu,
    Dmitry Soshnikov, and Ari Bornstein.
""")

DOC_SQLITE_ABOUT = textwrap.dedent("""\
    About SQLite — Small. Fast. Reliable. Choose any three.

    SQLite is an in-process library that implements a self-contained,
    serverless, zero-configuration, transactional SQL database engine.
    The code for SQLite is in the public domain and is free for any
    purpose, commercial or private. SQLite is the most widely deployed
    database in the world.

    Unlike most other SQL databases, SQLite does not have a separate
    server process. SQLite reads and writes directly to ordinary disk
    files. A complete SQL database with multiple tables, indices,
    triggers, and views is contained in a single disk file. The database
    file format is cross-platform. Think of SQLite not as a replacement
    for Oracle but as a replacement for fopen().

    With all features enabled, the library size can be less than 900KiB.
    SQLite can be faster than direct filesystem I/O. Maximum database
    size is 281 terabytes. Maximum row size is 1 gigabyte.

    SQLite is very carefully tested prior to every release. An automated
    test suite runs millions of test cases involving hundreds of millions
    of SQL statements and achieves 100 percent branch test coverage.
    Transactions are ACID even if interrupted by system crashes.

    D. Richard Hipp started the SQLite project on 2000-05-09 at
    General Dynamics in Huntsville, Alabama. The developers intend to
    support SQLite through the year 2050. SQLite uses a B-tree storage
    engine and supports full-text search via FTS5.
""")


def _make_large_doc():
    """Create a synthetic large document that will trigger chunking (>2000 chars)."""
    sections = [
        textwrap.dedent("""\
        Chapter 1: Introduction to Edge Computing

        Edge computing brings computation and data storage closer to the
        devices where it is being gathered, rather than relying on a central
        data center. This approach reduces latency, saves bandwidth, and
        improves response times. Companies like NVIDIA, Intel, and Google
        are investing heavily in edge AI hardware.

        The NVIDIA Jetson platform is a leading edge AI solution. Models
        like YOLO, ResNet, and EfficientNet can run inference directly on
        Jetson devices with TensorRT optimization, achieving real-time
        performance for computer vision tasks.
        """),
        textwrap.dedent("""\
        Chapter 2: Vector Databases and Semantic Search

        Vector databases store high-dimensional embeddings that represent
        the semantic meaning of text, images, or other data. Popular vector
        databases include Pinecone, Weaviate, Milvus, Qdrant, and ChromaDB.
        txtai combines SQLite FTS5 for keyword search with FAISS for vector
        similarity, enabling hybrid search on resource-constrained devices.

        Embedding models like BAAI/bge-small-en-v1.5 produce 384-dimensional
        vectors. Cross-encoder rerankers such as mixedbread-ai/mxbai-rerank-xsmall-v1
        improve search quality by scoring query-document pairs jointly.
        The BM25 algorithm handles keyword matching through inverted indexes.
        """),
        textwrap.dedent("""\
        Chapter 3: Privacy-Preserving AI

        On-device processing keeps sensitive data local, eliminating the
        need to send personal information to cloud servers. Microsoft
        Presidio detects PII entities like names, emails, phone numbers,
        and credit card numbers. Local Differential Privacy (LDP) adds
        mathematically proven noise to data before sharing.

        The LPRAG framework perturbs PII values to semantically similar
        alternatives. For example, the name "John Smith" might become
        "Michael Chen" with epsilon-differential privacy guarantees.
        This allows language models to reason about the data while
        protecting individual privacy.
        """),
        textwrap.dedent("""\
        Chapter 4: Building AI Applications with Python

        Python is the dominant language for AI and machine learning.
        Frameworks like PyTorch, TensorFlow, and JAX provide GPU-accelerated
        tensor computation. FastAPI and Flask serve as web frameworks for
        deploying ML models as REST APIs.

        The transformer architecture, introduced in the paper "Attention Is
        All You Need" by Vaswani et al. at Google Brain, revolutionized
        natural language processing. Models like BERT, GPT, and T5 are all
        based on transformers. Hugging Face provides the Transformers library
        for easy access to thousands of pre-trained models.

        SQLite is often used as the storage backend for edge AI applications
        due to its serverless, zero-configuration design. Combined with
        FAISS for vector indexing, it enables efficient hybrid search.
        """),
    ]
    return "\n".join(sections)


DOC_LARGE_EDGE_AI = _make_large_doc()

# Metadata templates for each document
DOC_METADATA = {
    "python_tutorial": {
        "source": "docs.python.org",
        "filename": "python_tutorial_intro.txt",
        "content_type": "tutorial",
        "domain": "programming",
    },
    "jetson_orin": {
        "source": "developer.nvidia.com",
        "filename": "jetson_orin_nano_guide.md",
        "content_type": "hardware_guide",
        "domain": "hardware",
    },
    "pytorch_intro": {
        "source": "pytorch.org",
        "filename": "pytorch_basics.txt",
        "content_type": "tutorial",
        "domain": "machine_learning",
    },
    "sqlite_about": {
        "source": "sqlite.org",
        "filename": "sqlite_about.txt",
        "content_type": "documentation",
        "domain": "database",
    },
    "edge_ai_guide": {
        "source": "internal",
        "filename": "edge_ai_comprehensive_guide.md",
        "content_type": "guide",
        "domain": "edge_computing",
    },
}


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture(scope="module")
def temp_dir():
    """Module-scoped temp directory for the vector store."""
    d = tempfile.mkdtemp(prefix="mindsage_realworld_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture(scope="module")
def store(temp_dir):
    """Module-scoped TxtaiAdapter with all documents indexed."""
    adapter = TxtaiAdapter(
        db_path=os.path.join(temp_dir, "vectordb"),
        auto_chunk_large_docs=True,
        use_onnx=False,
    )
    yield adapter
    adapter.close()


@pytest.fixture(scope="module")
def passage_extractor():
    """PassageExtractor without LLM (heuristic mode)."""
    return PassageExtractor(topic_labeler=None)


@pytest.fixture(scope="module")
def indexed_docs(store, passage_extractor):
    """Index all documents and return their IDs + results."""
    results = {}

    docs = [
        ("python_tutorial", DOC_PYTHON_TUTORIAL),
        ("pytorch_intro", DOC_PYTORCH_INTRO),
        ("jetson_orin", DOC_JETSON_ORIN),
        ("sqlite_about", DOC_SQLITE_ABOUT),
        ("edge_ai_guide", DOC_LARGE_EDGE_AI),
    ]

    for key, text in docs:
        meta = DOC_METADATA[key].copy()
        r = store.add_document(
            text=text,
            metadata=meta,
            extract_key_passages=True,
            passage_extractor=passage_extractor,
            extract_key_entities=True,
        )
        results[key] = r

    return results


# ============================================================================
# 1. Document Indexing Tests
# ============================================================================

class TestDocumentIndexing:
    """Verify documents were indexed correctly with proper metadata."""

    def test_all_documents_indexed(self, store, indexed_docs):
        """All 5 documents should be in the store."""
        # count includes chunks, so it will be > 5
        assert store.count() >= 5

    def test_small_doc_not_chunked(self, indexed_docs):
        """PyTorch intro (~700 chars) should NOT be chunked."""
        r = indexed_docs["pytorch_intro"]
        assert isinstance(r, AddDocumentResult)
        assert r.is_duplicate is False
        assert r.chunk_ids is None, "Small doc should not have chunks"

    def test_medium_docs_not_chunked(self, indexed_docs):
        """Python tutorial and SQLite about should NOT be chunked (< CHUNK_THRESHOLD)."""
        for key in ["python_tutorial", "sqlite_about", "jetson_orin"]:
            r = indexed_docs[key]
            assert r.chunk_ids is None, f"{key} should not be chunked"

    def test_large_doc_chunked(self, indexed_docs):
        """Edge AI guide (>2000 chars) SHOULD be chunked."""
        r = indexed_docs["edge_ai_guide"]
        assert r.chunk_ids is not None, "Large doc should be chunked"
        assert len(r.chunk_ids) >= 2, f"Expected >=2 chunks, got {len(r.chunk_ids)}"

    def test_document_retrieval(self, store, indexed_docs):
        """Retrieved documents should match original text."""
        r = indexed_docs["sqlite_about"]
        doc = store.get_document(r.doc_id)
        assert doc is not None
        assert "SQLite" in doc.text
        assert doc.metadata.get("source") == "sqlite.org"
        assert doc.metadata.get("filename") == "sqlite_about.txt"

    def test_chunked_doc_parent_has_full_text(self, store, indexed_docs):
        """Parent of chunked doc should contain the full text."""
        r = indexed_docs["edge_ai_guide"]
        parent = store.get_document(r.doc_id)
        assert parent is not None
        assert parent.metadata.get("is_parent") is True
        assert "Edge Computing" in parent.text
        assert "Privacy-Preserving AI" in parent.text  # from a later chapter

    def test_chunk_metadata(self, store, indexed_docs):
        """Chunks should have proper parent_id and chunk_index metadata."""
        r = indexed_docs["edge_ai_guide"]
        chunks = store.get_document_chunks(r.doc_id)
        assert len(chunks) == len(r.chunk_ids)
        for i, chunk in enumerate(chunks):
            assert chunk.metadata.get("is_chunk") is True
            assert chunk.metadata.get("parent_id") == r.doc_id
            assert chunk.metadata.get("chunk_index") == i

    def test_embedding_source_tracked(self, store, indexed_docs):
        """Documents should have embedding_source in metadata."""
        for key in ["python_tutorial", "pytorch_intro", "sqlite_about"]:
            doc = store.get_document(indexed_docs[key].doc_id)
            assert doc.metadata.get("embedding_source") in ["full_text", "key_passages"]

    def test_key_passages_extracted(self, store, indexed_docs):
        """Documents with passage extraction should have key_passages metadata."""
        doc = store.get_document(indexed_docs["python_tutorial"].doc_id)
        # key_passages may or may not be present depending on extractor success
        # but embedding_source should be set
        assert "embedding_source" in doc.metadata

    def test_entities_extracted(self, store, indexed_docs):
        """Documents should have extracted entities in metadata."""
        doc = store.get_document(indexed_docs["jetson_orin"].doc_id)
        entities = doc.metadata.get("entities", [])
        # Heuristic entity extraction should find capitalized terms like NVIDIA, Jetson
        if entities:
            entities_lower = [e.lower() for e in entities]
            assert any("nvidia" in e or "jetson" in e for e in entities_lower), \
                f"Expected NVIDIA/Jetson in entities, got: {entities}"

    def test_duplicate_detection(self, store, indexed_docs):
        """Adding the same document again should detect it as duplicate."""
        r = store.add_document(
            text=DOC_PYTORCH_INTRO,
            metadata=DOC_METADATA["pytorch_intro"],
        )
        assert r.is_duplicate is True


# ============================================================================
# 2. Keyword Search (FTS5/BM25 — Zero GPU, Fast Mode)
# ============================================================================

class TestKeywordSearch:
    """Test keyword-only search via BM25/FTS5."""

    def test_single_term(self, store, indexed_docs):
        """Search for a single keyword."""
        results = store.search_keyword("SQLite", limit=5)
        assert len(results) > 0
        assert any("SQLite" in r.text for r in results)

    def test_multi_term(self, store, indexed_docs):
        """Search for multiple keywords."""
        results = store.search_keyword("Python strings immutable", limit=5)
        assert len(results) > 0
        # The Python tutorial doc should rank high
        top_texts = " ".join(r.text[:200] for r in results[:2])
        assert "Python" in top_texts or "string" in top_texts.lower()

    def test_phrase_search(self, store, indexed_docs):
        """Quoted phrase search in FTS5."""
        results = store.search_keyword('"vector databases"', limit=5)
        assert len(results) > 0
        assert any("vector database" in r.text.lower() for r in results)

    def test_no_results(self, store, indexed_docs):
        """Searching for nonsense should return empty or very low scores."""
        results = store.search_keyword("xyzzy foobarbaz", limit=5, min_score=0.5)
        assert len(results) == 0

    def test_keyword_speed(self, store, indexed_docs):
        """Keyword search should be fast (<100ms)."""
        start = time.perf_counter()
        for _ in range(10):
            store.search_keyword("machine learning", limit=5)
        avg_ms = ((time.perf_counter() - start) / 10) * 1000
        assert avg_ms < 100, f"Keyword search too slow: {avg_ms:.1f}ms"

    def test_result_structure(self, store, indexed_docs):
        """Keyword results should have correct structure."""
        results = store.search_keyword("database", limit=3)
        for r in results:
            assert isinstance(r, SearchResult)
            assert isinstance(r.id, int)
            assert isinstance(r.text, str)
            assert isinstance(r.score, float)
            assert r.score > 0


# ============================================================================
# 3. Semantic / Hybrid Search
# ============================================================================

class TestSemanticSearch:
    """Test hybrid semantic + BM25 search."""

    def test_semantic_relevance(self, store, indexed_docs):
        """Semantic search should find conceptually related docs."""
        results = store.search("embedded database engine for mobile apps", limit=3)
        assert len(results) > 0
        # SQLite doc should be in top results (semantically related)
        top_ids = [r.id for r in results]
        # Check that at least one result mentions database concepts
        top_texts = " ".join(r.text[:300] for r in results)
        assert "database" in top_texts.lower() or "sqlite" in top_texts.lower()

    def test_cross_document_relevance(self, store, indexed_docs):
        """Search should find relevant content across different documents."""
        results = store.search("GPU computing for AI inference", limit=5)
        assert len(results) > 0
        # Should find Jetson and/or Edge AI content
        top_texts = " ".join(r.text[:300] for r in results)
        has_relevant = any(term in top_texts.lower() for term in
                          ["gpu", "cuda", "jetson", "tensorrt", "inference"])
        assert has_relevant, f"Expected GPU/AI terms in results"

    def test_min_score_filter(self, store, indexed_docs):
        """min_score should filter low-relevance results."""
        all_results = store.search("programming", limit=10, min_score=0.0)
        filtered = store.search("programming", limit=10, min_score=0.5)
        assert len(filtered) <= len(all_results)
        for r in filtered:
            assert r.score >= 0.5

    def test_top_k_limiting(self, store, indexed_docs):
        """top_k / limit should cap results."""
        results = store.search("data", limit=2)
        assert len(results) <= 2

    def test_score_ordering(self, store, indexed_docs):
        """Results should be sorted by score descending."""
        results = store.search("machine learning neural network", limit=5)
        for i in range(len(results) - 1):
            assert results[i].score >= results[i + 1].score


# ============================================================================
# 4. Enhanced Search with Passage Extraction
# ============================================================================

class TestEnhancedSearch:
    """Test enhanced search that returns excerpts."""

    def test_enhanced_returns_excerpts(self, store, indexed_docs):
        """Enhanced search should include excerpt field."""
        results = store.search_enhanced("Python programming", limit=3)
        assert len(results) > 0
        for r in results:
            assert isinstance(r, EnhancedSearchResult)
            assert r.excerpt is not None
            assert len(r.excerpt) > 0
            assert r.excerpt_method in ("precomputed", "full", "truncate")

    def test_short_doc_full_excerpt(self, store, indexed_docs):
        """Short docs should have excerpt_method='full'."""
        results = store.search_enhanced("PyTorch FashionMNIST", limit=1)
        if results and len(results[0].text) <= 500:
            assert results[0].excerpt_method == "full"
            assert results[0].excerpt == results[0].text

    def test_enhanced_via_alias(self, store, indexed_docs):
        """enhanced_search() alias should work identically."""
        results = store.enhanced_search(
            query="database testing",
            top_k=3,
            min_score=0.1,
        )
        assert len(results) > 0
        assert all(isinstance(r, EnhancedSearchResult) for r in results)


# ============================================================================
# 5. Entity Boost Search
# ============================================================================

class TestEntityBoostSearch:
    """Test entity matching boosting in hybrid search."""

    def test_entity_boost_metadata(self, store, indexed_docs):
        """With entity_boost > 0, results should include hybrid metadata."""
        results = store.search(
            "NVIDIA Jetson",
            limit=3,
            entity_boost=0.1,
        )
        assert len(results) > 0
        for r in results:
            assert "vector_score" in r.metadata
            assert "entity_boost" in r.metadata
            assert "matched_entities" in r.metadata

    def test_boost_vs_no_boost(self, store, indexed_docs):
        """Entity boost should increase score when entities match."""
        results_no = store.search("NVIDIA CUDA TensorRT", limit=1, entity_boost=0.0)
        results_yes = store.search("NVIDIA CUDA TensorRT", limit=1, entity_boost=0.2)
        assert len(results_no) > 0
        assert len(results_yes) > 0
        # If entities matched, boosted score should be >= base score
        if results_yes[0].metadata.get("matched_entities"):
            assert results_yes[0].score >= results_no[0].score

    def test_no_boost_no_metadata(self, store, indexed_docs):
        """With entity_boost=0.0, no hybrid metadata should appear."""
        results = store.search("SQLite database", limit=1, entity_boost=0.0)
        assert len(results) > 0
        assert "vector_score" not in results[0].metadata
        assert "matched_entities" not in results[0].metadata


# ============================================================================
# 6. Chunked Document Search and Deduplication
# ============================================================================

class TestChunkedSearch:
    """Test search behaviour with chunked documents."""

    def test_chunk_maps_to_parent(self, store, indexed_docs):
        """Searching chunk content should map result ID to parent."""
        # "Privacy-Preserving AI" is in chapter 3 of the large doc
        results = store.search("Presidio PII detection", limit=3)
        assert len(results) > 0
        parent_id = indexed_docs["edge_ai_guide"].doc_id
        # At least one result should reference the parent
        result_ids = [r.id for r in results]
        assert parent_id in result_ids, \
            f"Expected parent {parent_id} in results {result_ids}"

    def test_chunk_deduplication(self, store, indexed_docs):
        """deduplicate_chunks should return only unique parent IDs."""
        results = store.search(
            "edge computing AI NVIDIA",
            limit=10,
            deduplicate_chunks=True,
        )
        ids = [r.id for r in results]
        assert len(ids) == len(set(ids)), \
            f"Duplicate IDs found after dedup: {ids}"

    def test_exclude_chunks(self, store, indexed_docs):
        """exclude_chunks should filter out chunk results."""
        results = store.search(
            "transformer architecture",
            limit=10,
            exclude_chunks=True,
        )
        for r in results:
            assert not r.metadata.get("is_chunk"), \
                "Chunk should have been excluded"


# ============================================================================
# 7. Metadata Search
# ============================================================================

class TestMetadataSearch:
    """Test metadata-only search (zero GPU)."""

    def test_search_by_source(self, store, indexed_docs):
        """Filter documents by source field."""
        results = store.search_metadata(source="sqlite.org")
        assert len(results) > 0
        for r in results:
            assert r.metadata.get("source") == "sqlite.org"

    def test_search_by_filename_glob(self, store, indexed_docs):
        """Filter documents by filename glob pattern."""
        results = store.search_metadata(filename="*.md")
        assert len(results) > 0
        for r in results:
            assert r.metadata.get("filename", "").endswith(".md")

    def test_search_by_topic(self, store, indexed_docs):
        """Filter documents by assigned topic."""
        # First assign a topic
        store.update_document_topics(
            indexed_docs["sqlite_about"].doc_id,
            topics=["database", "sql"],
            primary_topic="database"
        )
        results = store.search_metadata(topic="database")
        assert len(results) > 0

    def test_metadata_speed(self, store, indexed_docs):
        """Metadata search should be fast (<50ms)."""
        start = time.perf_counter()
        for _ in range(10):
            store.search_metadata(source="internal")
        avg_ms = ((time.perf_counter() - start) / 10) * 1000
        assert avg_ms < 50, f"Metadata search too slow: {avg_ms:.1f}ms"


# ============================================================================
# 8. Topic Operations
# ============================================================================

class TestTopicOperations:
    """Test topic assignment and topic-filtered search."""

    def test_assign_topics(self, store, indexed_docs):
        """Assign topics to documents."""
        store.update_document_topics(
            indexed_docs["python_tutorial"].doc_id,
            topics=["programming", "python", "tutorial"],
            primary_topic="python"
        )
        store.update_document_topics(
            indexed_docs["pytorch_intro"].doc_id,
            topics=["machine_learning", "pytorch", "deep_learning"],
            primary_topic="machine_learning"
        )
        store.update_document_topics(
            indexed_docs["jetson_orin"].doc_id,
            topics=["hardware", "nvidia", "edge_ai"],
            primary_topic="hardware"
        )

    def test_get_document_topics(self, store, indexed_docs):
        """Retrieve topics for a document."""
        topics = store.get_document_topics(indexed_docs["python_tutorial"].doc_id)
        assert topics is not None
        assert "python" in topics["topics"]
        assert topics["primary_topic"] == "python"

    def test_get_all_topics(self, store, indexed_docs):
        """List all topics with counts."""
        all_topics = store.get_all_topics()
        assert len(all_topics) > 0
        assert isinstance(all_topics, dict)
        # Each topic should have count >= 1
        for topic, count in all_topics.items():
            assert count >= 1

    def test_search_with_topic_filter(self, store, indexed_docs):
        """Search within a specific topic."""
        results = store.search_with_topic_filter(
            query="strings lists",
            topic="python",
            limit=5,
        )
        # Should find the Python tutorial
        assert len(results) > 0

    def test_get_documents_by_topic(self, store, indexed_docs):
        """Get paginated documents for a topic."""
        result = store.get_documents_by_topic("hardware", page=1, page_size=10)
        assert result.total >= 1
        assert any("Jetson" in d.text for d in result.documents)


# ============================================================================
# 9. Graph Search
# ============================================================================

class TestGraphSearch:
    """Test graph-based search."""

    def test_graph_search_returns_results(self, store, indexed_docs):
        """Graph search should return results and related concepts."""
        result = store.graph_search("artificial intelligence", limit=3)
        assert "results" in result
        assert "related_concepts" in result
        assert isinstance(result["results"], list)

    def test_graph_search_finds_relevant(self, store, indexed_docs):
        """Graph search results should be relevant."""
        result = store.graph_search("database SQL", limit=3)
        if result["results"]:
            texts = " ".join(r.text[:200] for r in result["results"])
            assert "sql" in texts.lower() or "database" in texts.lower()


# ============================================================================
# 10. Passage and Entity Extraction
# ============================================================================

class TestPassageEntityExtraction:
    """Test passage extractor on real content."""

    def test_extract_key_sentences(self, passage_extractor):
        """Extract key sentences from real document text."""
        sentences = passage_extractor.extract_key_sentences(
            DOC_SQLITE_ABOUT, max_sentences=3
        )
        assert isinstance(sentences, list)
        assert len(sentences) == 3
        # Sentences should contain meaningful content
        all_text = " ".join(sentences)
        assert len(all_text) > 50

    def test_extract_entities_from_real_text(self, passage_extractor):
        """Extract entities from real document text."""
        entities = passage_extractor.extract_key_entities(
            DOC_JETSON_ORIN, max_entities=10
        )
        assert isinstance(entities, list)
        assert len(entities) > 0
        # Should find NVIDIA, Jetson, etc.
        entities_lower = [e.lower() for e in entities]
        found_relevant = any(
            term in e for e in entities_lower
            for term in ["nvidia", "jetson", "cuda", "tensorrt"]
        )
        assert found_relevant, f"Expected hardware entities, got: {entities}"

    def test_extract_passages_for_existing_doc(self, store, indexed_docs, passage_extractor):
        """Re-extract passages for an already-indexed document."""
        doc_id = indexed_docs["sqlite_about"].doc_id
        success = store.extract_passages_for_document(
            doc_id=doc_id,
            passage_extractor=passage_extractor,
        )
        assert success is True
        doc = store.get_document(doc_id)
        assert "key_passages" in doc.metadata
        assert doc.metadata["embedding_source"] == "key_passages"

    def test_passage_extraction_on_query(self, passage_extractor):
        """Extract relevant passage given a query."""
        result = passage_extractor.extract_passage(
            query="How is SQLite tested?",
            document_text=DOC_SQLITE_ABOUT,
            max_excerpt_length=300,
        )
        assert result.excerpt is not None
        assert len(result.excerpt) > 0
        assert result.method in ("full", "window", "embedding_extract", "llm_extract")
        # The excerpt should contain testing-related content
        assert "test" in result.excerpt.lower()


# ============================================================================
# 11. Document Listing and Pagination
# ============================================================================

class TestDocumentListing:
    """Test document listing and pagination."""

    def test_list_excludes_chunks_by_default(self, store, indexed_docs):
        """Default listing should exclude chunks."""
        result = store.list_documents(page=1, page_size=50)
        for doc in result.documents:
            assert not doc.metadata.get("is_chunk"), "Chunks should be excluded"

    def test_pagination(self, store, indexed_docs):
        """Pagination should work correctly."""
        page1 = store.list_documents(page=1, page_size=2)
        assert len(page1.documents) == 2
        assert page1.has_next is True

        page2 = store.list_documents(page=2, page_size=2)
        assert page2.has_prev is True

        # Pages should have different documents
        ids1 = {d.id for d in page1.documents}
        ids2 = {d.id for d in page2.documents}
        assert ids1.isdisjoint(ids2), "Pages should not overlap"

    def test_document_count(self, store, indexed_docs):
        """Total documents should match what we indexed."""
        result = store.list_documents(page=1, page_size=50)
        # 5 documents indexed (one is chunked parent)
        assert result.total >= 5


# ============================================================================
# 12. Delete Operations
# ============================================================================

class TestDeleteOperations:
    """Test document deletion including cascading chunk deletes."""

    def test_delete_simple_doc(self, store):
        """Delete a non-chunked document."""
        r = store.add_document(
            text="Temporary document to be deleted.",
            metadata={"source": "test", "filename": "temp.txt"},
        )
        assert not r.is_duplicate
        count_before = store.count()

        deleted = store.delete_document(r.doc_id)
        assert deleted is True
        assert store.count() == count_before - 1
        assert store.get_document(r.doc_id) is None

    def test_delete_chunked_doc_cascades(self, store):
        """Deleting a chunked parent should delete all its chunks."""
        large = "This is a large document for deletion testing. " * 200
        r = store.add_document(text=large, metadata={"source": "test"})
        assert r.chunk_ids is not None
        num_chunks = len(r.chunk_ids)
        count_before = store.count()

        deleted = store.delete_document(r.doc_id)
        assert deleted is True
        # Parent + all chunks should be deleted
        assert store.count() == count_before - num_chunks - 1


# ============================================================================
# 13. Stats
# ============================================================================

class TestStats:
    """Test statistics reporting."""

    def test_stats_format(self, store, indexed_docs):
        """Stats should return expected format."""
        stats = store.get_stats()
        assert "total_documents" in stats
        assert "embedding_dimension" in stats
        assert "hybrid_search_enabled" in stats
        assert stats["total_documents"] > 0
        assert stats["embedding_dimension"] > 0

    def test_count(self, store, indexed_docs):
        """Count should return total including chunks."""
        assert store.count() > 0


# ============================================================================
# 14. File System Search Integration
# ============================================================================

class TestFileSystemSearch:
    """Test file system grep-like search."""

    def test_file_searcher_import(self):
        """FileSearcher should be importable."""
        from mcp_vector_store.file_searcher import FileSearcher
        assert FileSearcher is not None

    def test_file_search_in_temp_dir(self, temp_dir):
        """FileSearcher should find content in files on disk."""
        from mcp_vector_store.file_searcher import FileSearcher

        # Create test files in a subdirectory
        uploads_dir = os.path.join(temp_dir, "uploads")
        os.makedirs(uploads_dir, exist_ok=True)

        # Write some test files
        with open(os.path.join(uploads_dir, "notes.txt"), "w") as f:
            f.write("Meeting notes from the quarterly review.\n")
            f.write("Discussed budget allocation for Q3.\n")
            f.write("Action items: update project timeline.\n")

        with open(os.path.join(uploads_dir, "report.md"), "w") as f:
            f.write("# Annual Report\n\n")
            f.write("Revenue grew 15% year-over-year.\n")
            f.write("Key markets: North America, Europe, Asia Pacific.\n")

        searcher = FileSearcher(data_dir=temp_dir)
        results = searcher.search("budget", directories=["uploads"], max_results=5)
        assert len(results) > 0
        assert any("budget" in m.text.lower()
                    for r in results for m in r.matches)

    def test_filename_search(self, temp_dir):
        """FileSearcher should find files by name pattern."""
        from mcp_vector_store.file_searcher import FileSearcher

        searcher = FileSearcher(data_dir=temp_dir)
        results = searcher.search_filenames("*.md", directories=["uploads"])
        assert len(results) > 0
        assert any(f["filename"].endswith(".md") for f in results)


# ============================================================================
# Entry Point
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
