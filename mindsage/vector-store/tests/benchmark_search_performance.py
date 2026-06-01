#!/usr/bin/env python3
"""
Performance benchmark for MindSage search — before vs after optimization.

Measures:
1. Indexing throughput (docs/sec)
2. Search latency across all modes (keyword, semantic, enhanced, hybrid)
3. Search relevance (score quality for known-good queries)
4. New features (keyword-only, metadata, entity boost) — feature branch only

Usage:
    cd /home/user/mindsage/vector-store
    python -m pytest tests/benchmark_search_performance.py -v -s 2>&1 | tee /tmp/benchmark_results.txt

    # Or run directly:
    python tests/benchmark_search_performance.py 2>&1 | tee /tmp/benchmark_results.txt
"""

import json
import os
import sys
import time
import tempfile
import statistics
from typing import Dict, List, Any, Optional

# Add parent to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mcp_vector_store.txtai_store import TxtaiStore
from mcp_vector_store.txtai_adapter import TxtaiAdapter

# Try importing feature-branch-only components
try:
    from mcp_vector_store.file_searcher import FileSearcher
    HAS_FILE_SEARCHER = True
except ImportError:
    HAS_FILE_SEARCHER = False

# Check if adapter has new methods
HAS_KEYWORD_SEARCH = hasattr(TxtaiAdapter, "search_keyword")
HAS_METADATA_SEARCH = hasattr(TxtaiAdapter, "search_metadata")
HAS_RERANKED_SEARCH = hasattr(TxtaiAdapter, "search_reranked")

# Try importing reranker
try:
    from mcp_vector_store.reranker import create_reranker
    HAS_RERANKER = True
except ImportError:
    HAS_RERANKER = False

# =============================================================================
# Test Documents — varied sizes and topics
# =============================================================================

DOCUMENTS = [
    {
        "text": (
            "Python is a high-level, general-purpose programming language. "
            "Its design philosophy emphasizes code readability with the use of significant indentation. "
            "Python is dynamically typed and garbage-collected. It supports multiple programming paradigms, "
            "including structured, object-oriented and functional programming. Python was conceived in the "
            "late 1980s by Guido van Rossum at Centrum Wiskunde & Informatica in the Netherlands as a "
            "successor to the ABC programming language, which was inspired by SETL, capable of exception "
            "handling and interfacing with the Amoeba operating system. Its implementation began in "
            "December 1989. Van Rossum shouldered sole responsibility for the project, as the lead "
            "developer, until 12 July 2018, when he announced his permanent vacation from the role."
        ),
        "metadata": {"source": "wikipedia", "filename": "python_language.txt", "topic": "programming"},
    },
    {
        "text": (
            "Machine learning is a subset of artificial intelligence that focuses on the development "
            "of algorithms and statistical models that enable computers to perform tasks without explicit "
            "programming. Machine learning algorithms build mathematical models based on sample data, "
            "known as training data, in order to make predictions or decisions. Machine learning is "
            "closely related to computational statistics, which focuses on making predictions using "
            "computers. The study of mathematical optimization delivers methods, theory and application "
            "domains to the field of machine learning. Data mining is a related field of study, "
            "focusing on exploratory data analysis through unsupervised learning. Some implementations "
            "of machine learning use data and neural networks in a way that mimics the working of a "
            "biological brain. In its application across business problems, machine learning is also "
            "referred to as predictive analytics."
        ),
        "metadata": {"source": "textbook", "filename": "ml_overview.txt", "topic": "ai"},
    },
    {
        "text": (
            "SQLite is a relational database management system contained in a C library. In contrast to "
            "many other database management systems, SQLite is not a client-server database engine. "
            "Rather, it is embedded into the end program. SQLite generally follows PostgreSQL syntax. "
            "SQLite uses a dynamically and weakly typed SQL syntax that does not guarantee domain "
            "integrity. This means that one can, for example, insert a string into a column defined as "
            "an integer. SQLite is a popular choice as embedded database software for local or client "
            "storage in application software such as web browsers. It is arguably the most widely "
            "deployed database engine, as it is used by several widespread browsers, operating systems, "
            "and embedded systems, among others. SQLite has bindings to many programming languages "
            "including Python, Java, C#, and JavaScript."
        ),
        "metadata": {"source": "documentation", "filename": "sqlite_guide.pdf", "topic": "databases"},
    },
    {
        "text": (
            "The NVIDIA Jetson Orin Nano is a compact edge AI computer designed for running modern AI "
            "workloads. It features an NVIDIA Ampere architecture GPU with up to 1024 CUDA cores and "
            "8GB of shared LPDDR5 memory. The Jetson Orin Nano delivers up to 40 TOPS of AI performance, "
            "making it suitable for robotics, smart cameras, and IoT applications. The module supports "
            "CUDA, cuDNN, TensorRT, and the complete NVIDIA JetPack SDK. Power consumption ranges from "
            "7W to 15W depending on the performance mode. The shared memory architecture means CPU and "
            "GPU compete for the same 8GB RAM pool, requiring careful memory management for applications "
            "that run multiple ML models simultaneously."
        ),
        "metadata": {"source": "nvidia", "filename": "jetson_orin_specs.txt", "topic": "hardware"},
    },
    {
        "text": (
            "Privacy in the digital age has become a significant concern for individuals and organizations "
            "alike. Data protection regulations such as GDPR in Europe and CCPA in California have "
            "established frameworks for how personal information should be collected, stored, and "
            "processed. Techniques like differential privacy, homomorphic encryption, and federated "
            "learning allow organizations to derive insights from data while preserving individual "
            "privacy. On-device processing, where data never leaves the user's hardware, represents "
            "the strongest form of privacy protection. Personal data hubs that store information locally "
            "and use edge AI for analysis are emerging as alternatives to cloud-based services that "
            "require uploading sensitive data to remote servers."
        ),
        "metadata": {"source": "research", "filename": "privacy_whitepaper.pdf", "topic": "privacy"},
    },
    # Longer document that triggers chunking (>2000 chars)
    {
        "text": (
            "Deep learning has revolutionized artificial intelligence over the past decade. "
            "Neural networks with many layers, hence the term deep, can learn hierarchical "
            "representations of data through backpropagation. Convolutional neural networks "
            "excel at image recognition, achieving superhuman performance on tasks like object "
            "detection and image classification. Recurrent neural networks and their variants "
            "like LSTM and GRU are designed for sequential data processing, making them useful "
            "for natural language processing and time series prediction. "
            "\n\n"
            "The transformer architecture, introduced in the 2017 paper Attention Is All You Need, "
            "has become the dominant paradigm for natural language processing. Models like BERT, "
            "GPT, and T5 are all based on transformers. The key innovation is the self-attention "
            "mechanism, which allows the model to weigh the importance of different parts of the "
            "input when producing each part of the output. This parallelizable architecture "
            "replaced sequential processing, enabling training on much larger datasets. "
            "\n\n"
            "Transfer learning has dramatically reduced the cost of training neural networks for "
            "specific tasks. Pre-trained models like BERT and GPT can be fine-tuned on small "
            "datasets to achieve state-of-the-art performance on downstream tasks. This approach "
            "has democratized access to advanced AI capabilities, as organizations no longer need "
            "massive datasets or computational resources to build effective models. Foundation "
            "models trained on broad data can be adapted to specific domains through techniques "
            "like LoRA, QLoRA, and prefix tuning. "
            "\n\n"
            "Edge AI represents the deployment of AI models directly on edge devices rather than "
            "in the cloud. This approach offers several advantages including reduced latency, "
            "improved privacy by keeping data on-device, lower bandwidth requirements, and the "
            "ability to operate without internet connectivity. Techniques like model quantization, "
            "pruning, and knowledge distillation enable running complex models on resource-constrained "
            "hardware. NVIDIA's TensorRT and Apple's CoreML are examples of frameworks optimized "
            "for edge inference. The ONNX Runtime provides cross-platform edge deployment capability. "
            "Model compression techniques like 4-bit quantization can reduce model size by 8x while "
            "maintaining 95% of original accuracy, making previously cloud-only models viable on "
            "devices with as little as 4GB of RAM."
        ),
        "metadata": {"source": "course", "filename": "deep_learning_guide.txt", "topic": "ai"},
    },
    {
        "text": (
            "Vector databases are specialized database systems designed to store and efficiently query "
            "high-dimensional vector embeddings. Unlike traditional databases that search by exact match "
            "or keyword, vector databases use approximate nearest neighbor algorithms like HNSW, IVF, "
            "and product quantization to find similar items based on their vector representations. "
            "Popular vector databases include Pinecone, Weaviate, Milvus, Chroma, and Qdrant. The "
            "choice between these depends on factors like scale, latency requirements, and whether "
            "a managed service or self-hosted solution is preferred. For edge deployments, FAISS and "
            "LanceDB offer embedded options that don't require a separate server process."
        ),
        "metadata": {"source": "blog", "filename": "vector_databases.txt", "topic": "databases"},
    },
    {
        "text": (
            "Natural language processing has evolved significantly with the advent of large language "
            "models. Traditional NLP relied on rule-based systems and statistical methods like TF-IDF, "
            "bag of words, and n-gram models. Modern approaches use contextual embeddings from "
            "transformer models to capture semantic meaning. Tasks like named entity recognition, "
            "sentiment analysis, text classification, and question answering have seen dramatic "
            "improvements. SpaCy, NLTK, and Hugging Face Transformers are popular libraries for "
            "building NLP applications. Retrieval-augmented generation combines vector search with "
            "language model generation to produce grounded, factual responses."
        ),
        "metadata": {"source": "tutorial", "filename": "nlp_intro.txt", "topic": "ai"},
    },
]

# =============================================================================
# Search Queries with Expected Top Results
# =============================================================================

BENCHMARK_QUERIES = [
    {
        "query": "Python programming language",
        "expected_topic": "programming",
        "description": "exact keyword match",
    },
    {
        "query": "how do neural networks learn from data",
        "expected_topic": "ai",
        "description": "semantic/conceptual query",
    },
    {
        "query": "database embedded application",
        "expected_topic": "databases",
        "description": "multi-keyword sparse match",
    },
    {
        "query": "protecting personal information on device",
        "expected_topic": "privacy",
        "description": "paraphrase/semantic similarity",
    },
    {
        "query": "edge computing AI hardware specifications",
        "expected_topic": "hardware",
        "description": "cross-domain semantic",
    },
    {
        "query": "BERT GPT transformer attention mechanism",
        "expected_topic": "ai",
        "description": "technical terminology dense",
    },
    {
        "query": "FAISS vector similarity search",
        "expected_topic": "databases",
        "description": "specific technology query",
    },
    {
        "query": "Guido van Rossum programming",
        "expected_topic": "programming",
        "description": "entity + topic query",
    },
    {
        "query": "GDPR data protection regulation",
        "expected_topic": "privacy",
        "description": "acronym + concept",
    },
    {
        "query": "CUDA GPU memory management models",
        "expected_topic": "hardware",
        "description": "hardware + software cross-concept",
    },
]


# =============================================================================
# Benchmark Helpers
# =============================================================================

def _results_to_dicts(results):
    """Convert search results (dataclass or dict) to dicts for scoring."""
    dicts = []
    for r in results:
        if isinstance(r, dict):
            dicts.append(r)
        else:
            dicts.append({
                "text": getattr(r, "text", ""),
                "metadata": getattr(r, "metadata", {}) or {},
                "score": getattr(r, "score", 0),
            })
    return dicts


def _get_score(result):
    """Extract score from a search result (dict or dataclass)."""
    if isinstance(result, dict):
        return result.get("score", 0)
    return getattr(result, "score", 0)


def time_operation(func, *args, iterations=10, **kwargs):
    """Run func N times and return (mean_ms, median_ms, p95_ms, min_ms, max_ms)."""
    times = []
    result = None
    for _ in range(iterations):
        start = time.perf_counter()
        result = func(*args, **kwargs)
        elapsed = (time.perf_counter() - start) * 1000  # ms
        times.append(elapsed)
    return {
        "mean_ms": round(statistics.mean(times), 2),
        "median_ms": round(statistics.median(times), 2),
        "p95_ms": round(sorted(times)[int(len(times) * 0.95)], 2),
        "min_ms": round(min(times), 2),
        "max_ms": round(max(times), 2),
        "iterations": iterations,
        "result": result,
    }


# Keywords to identify topic from document text content
TOPIC_KEYWORDS = {
    "programming": ["python", "guido", "programming language", "van rossum", "abc programming"],
    "ai": ["machine learning", "neural network", "deep learning", "transformer", "NLP",
            "natural language", "BERT", "GPT", "backpropagation", "attention mechanism"],
    "databases": ["sqlite", "database", "vector database", "FAISS", "SQL", "relational"],
    "hardware": ["jetson", "orin", "cuda", "gpu memory", "edge ai", "nvidia", "TOPS"],
    "privacy": ["privacy", "GDPR", "CCPA", "differential privacy", "data protection",
                "personal data", "on-device"],
}


def _detect_topic_from_text(text: str) -> str:
    """Detect topic from document text using keyword matching."""
    text_lower = text.lower()
    best_topic = ""
    best_count = 0
    for topic, keywords in TOPIC_KEYWORDS.items():
        count = sum(1 for kw in keywords if kw.lower() in text_lower)
        if count > best_count:
            best_count = count
            best_topic = topic
    return best_topic


def compute_relevance_score(results, expected_topic):
    """Score how well results match expected topic using text content analysis.
    Uses nDCG-style weighting: higher rank = more weight."""
    if not results:
        return 0.0
    score = 0.0
    for i, r in enumerate(results[:5]):
        weight = 1.0 / (i + 1)  # DCG-style weight
        text = r.get("text", "") if isinstance(r, dict) else getattr(r, "text", "")
        detected = _detect_topic_from_text(text)
        if detected == expected_topic:
            score += weight
    max_score = sum(1.0 / (i + 1) for i in range(min(5, len(results))))
    return round(score / max_score if max_score > 0 else 0, 3)


def get_branch_name():
    """Get current git branch."""
    try:
        import subprocess
        # Use the directory of this script's parent to find the git repo
        script_dir = os.path.dirname(os.path.abspath(__file__))
        repo_dir = os.path.dirname(script_dir)  # vector-store/
        result = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                                capture_output=True, text=True, cwd=repo_dir)
        return result.stdout.strip()
    except Exception:
        return "unknown"


def get_commit_hash():
    """Get current commit hash."""
    try:
        import subprocess
        script_dir = os.path.dirname(os.path.abspath(__file__))
        repo_dir = os.path.dirname(script_dir)
        result = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                                capture_output=True, text=True, cwd=repo_dir)
        return result.stdout.strip()
    except Exception:
        return "unknown"


# =============================================================================
# Main Benchmark
# =============================================================================

def run_benchmark():
    """Run the complete benchmark suite and return structured results."""
    branch = get_branch_name()
    commit = get_commit_hash()

    print(f"\n{'='*70}")
    print(f" MindSage Search Performance Benchmark")
    print(f" Branch: {branch} ({commit})")
    print(f" Features: keyword_search={HAS_KEYWORD_SEARCH}, "
          f"metadata_search={HAS_METADATA_SEARCH}, "
          f"file_searcher={HAS_FILE_SEARCHER}")
    print(f"{'='*70}\n")

    results = {
        "branch": branch,
        "commit": commit,
        "features": {
            "keyword_search": HAS_KEYWORD_SEARCH,
            "metadata_search": HAS_METADATA_SEARCH,
            "file_searcher": HAS_FILE_SEARCHER,
        },
        "indexing": {},
        "search_latency": {},
        "relevance": {},
    }

    # Create temp directory for benchmark
    tmpdir = tempfile.mkdtemp(prefix="mindsage_bench_")
    print(f"Data directory: {tmpdir}\n")

    try:
        # =====================================================================
        # 1. INDEXING BENCHMARK
        # =====================================================================
        print("=" * 50)
        print(" 1. INDEXING PERFORMANCE")
        print("=" * 50)

        adapter = TxtaiAdapter(db_path=tmpdir, use_onnx=False)

        # Warm up the embedding model with a single document
        print("  Warming up embedding model...")
        warmup_start = time.perf_counter()
        adapter.add_document("Warmup document for model loading", {"source": "warmup"})
        warmup_time = (time.perf_counter() - warmup_start) * 1000
        print(f"  Model warmup: {warmup_time:.0f}ms")

        # Delete warmup doc
        adapter.delete_document(1)

        # Index all documents and measure per-doc time
        print(f"\n  Indexing {len(DOCUMENTS)} documents...")
        doc_ids = []
        indexing_times = []

        for i, doc in enumerate(DOCUMENTS):
            start = time.perf_counter()
            result = adapter.add_document(doc["text"], doc["metadata"])
            elapsed = (time.perf_counter() - start) * 1000
            indexing_times.append(elapsed)

            # Handle both old (int) and new (AddDocumentResult) return types
            if hasattr(result, 'doc_id'):
                doc_ids.append(result.doc_id)
            else:
                doc_ids.append(result)

            char_count = len(doc["text"])
            print(f"    Doc {i+1}: {elapsed:7.1f}ms ({char_count:5d} chars) "
                  f"- {doc['metadata'].get('filename', 'unknown')}")

        total_chars = sum(len(d["text"]) for d in DOCUMENTS)
        total_index_time = sum(indexing_times)

        results["indexing"] = {
            "total_docs": len(DOCUMENTS),
            "total_chars": total_chars,
            "total_time_ms": round(total_index_time, 1),
            "mean_per_doc_ms": round(statistics.mean(indexing_times), 1),
            "median_per_doc_ms": round(statistics.median(indexing_times), 1),
            "docs_per_second": round(len(DOCUMENTS) / (total_index_time / 1000), 1),
            "chars_per_second": round(total_chars / (total_index_time / 1000), 0),
            "model_warmup_ms": round(warmup_time, 1),
        }

        print(f"\n  Total: {total_index_time:.0f}ms for {len(DOCUMENTS)} docs ({total_chars} chars)")
        print(f"  Throughput: {results['indexing']['docs_per_second']:.1f} docs/sec, "
              f"{results['indexing']['chars_per_second']:.0f} chars/sec")

        doc_count = adapter.count()
        print(f"  Documents in index: {doc_count}")

        # =====================================================================
        # 2. SEARCH LATENCY BENCHMARKS
        # =====================================================================
        print(f"\n{'='*50}")
        print(" 2. SEARCH LATENCY")
        print("=" * 50)

        # 2a. Hybrid search (BM25 + semantic) — works on both branches
        print("\n  --- Hybrid Search (BM25 + semantic) ---")
        hybrid_latencies = []
        for q in BENCHMARK_QUERIES:
            timing = time_operation(adapter.search, q["query"], top_k=5, iterations=10)
            hybrid_latencies.append(timing)
            print(f"    [{timing['median_ms']:6.2f}ms med, {timing['p95_ms']:6.2f}ms p95] "
                  f"{q['description']}: \"{q['query'][:50]}\"")

        results["search_latency"]["hybrid"] = {
            "mean_ms": round(statistics.mean(t["median_ms"] for t in hybrid_latencies), 2),
            "median_ms": round(statistics.median(t["median_ms"] for t in hybrid_latencies), 2),
            "p95_ms": round(sorted(t["p95_ms"] for t in hybrid_latencies)[
                int(len(hybrid_latencies) * 0.95)], 2),
            "min_ms": round(min(t["min_ms"] for t in hybrid_latencies), 2),
            "max_ms": round(max(t["max_ms"] for t in hybrid_latencies), 2),
        }
        print(f"\n  Hybrid overall: median={results['search_latency']['hybrid']['median_ms']:.2f}ms, "
              f"p95={results['search_latency']['hybrid']['p95_ms']:.2f}ms")

        # 2b. Enhanced search (with passage extraction)
        print("\n  --- Enhanced Search (hybrid + passage extraction) ---")
        enhanced_latencies = []
        for q in BENCHMARK_QUERIES:
            timing = time_operation(
                adapter.search_enhanced, q["query"], limit=5, iterations=10
            )
            enhanced_latencies.append(timing)
            print(f"    [{timing['median_ms']:6.2f}ms med, {timing['p95_ms']:6.2f}ms p95] "
                  f"{q['description']}")

        results["search_latency"]["enhanced"] = {
            "mean_ms": round(statistics.mean(t["median_ms"] for t in enhanced_latencies), 2),
            "median_ms": round(statistics.median(t["median_ms"] for t in enhanced_latencies), 2),
            "p95_ms": round(sorted(t["p95_ms"] for t in enhanced_latencies)[
                int(len(enhanced_latencies) * 0.95)], 2),
            "min_ms": round(min(t["min_ms"] for t in enhanced_latencies), 2),
            "max_ms": round(max(t["max_ms"] for t in enhanced_latencies), 2),
        }
        print(f"\n  Enhanced overall: median={results['search_latency']['enhanced']['median_ms']:.2f}ms, "
              f"p95={results['search_latency']['enhanced']['p95_ms']:.2f}ms")

        # 2c. Search with topic filter
        print("\n  --- Topic-filtered Search ---")
        topic_latencies = []
        for q in BENCHMARK_QUERIES:
            timing = time_operation(
                adapter.search_with_topic_filter, q["query"],
                topic=q["expected_topic"], limit=5, iterations=10
            )
            topic_latencies.append(timing)
            print(f"    [{timing['median_ms']:6.2f}ms med] topic={q['expected_topic']}")

        results["search_latency"]["topic_filtered"] = {
            "mean_ms": round(statistics.mean(t["median_ms"] for t in topic_latencies), 2),
            "median_ms": round(statistics.median(t["median_ms"] for t in topic_latencies), 2),
            "p95_ms": round(sorted(t["p95_ms"] for t in topic_latencies)[
                int(len(topic_latencies) * 0.95)], 2),
        }
        print(f"\n  Topic-filtered overall: median={results['search_latency']['topic_filtered']['median_ms']:.2f}ms")

        # 2d. Keyword-only search (FEATURE BRANCH ONLY)
        if HAS_KEYWORD_SEARCH:
            print("\n  --- Keyword-Only Search (FTS5, no GPU) ---")
            keyword_latencies = []
            for q in BENCHMARK_QUERIES:
                timing = time_operation(
                    adapter.search_keyword, q["query"], limit=5, iterations=20
                )
                keyword_latencies.append(timing)
                print(f"    [{timing['median_ms']:6.2f}ms med, {timing['p95_ms']:6.2f}ms p95] "
                      f"\"{q['query'][:50]}\"")

            results["search_latency"]["keyword_only"] = {
                "mean_ms": round(statistics.mean(t["median_ms"] for t in keyword_latencies), 2),
                "median_ms": round(statistics.median(t["median_ms"] for t in keyword_latencies), 2),
                "p95_ms": round(sorted(t["p95_ms"] for t in keyword_latencies)[
                    int(len(keyword_latencies) * 0.95)], 2),
                "min_ms": round(min(t["min_ms"] for t in keyword_latencies), 2),
                "max_ms": round(max(t["max_ms"] for t in keyword_latencies), 2),
            }
            print(f"\n  Keyword-only overall: median={results['search_latency']['keyword_only']['median_ms']:.2f}ms, "
                  f"p95={results['search_latency']['keyword_only']['p95_ms']:.2f}ms")
        else:
            print("\n  --- Keyword-Only Search: NOT AVAILABLE (master branch) ---")

        # 2e. Metadata search (FEATURE BRANCH ONLY)
        if HAS_METADATA_SEARCH:
            print("\n  --- Metadata Search (SQLite, no GPU) ---")
            meta_queries = [
                {"filename": "*.pdf"},
                {"source": "research"},
                {"topic": "ai"},
                {"source": "wikipedia", "filename": "*.txt"},
            ]
            meta_latencies = []
            for mq in meta_queries:
                timing = time_operation(
                    adapter.search_metadata, limit=10, iterations=20, **mq
                )
                meta_latencies.append(timing)
                print(f"    [{timing['median_ms']:6.2f}ms med] filters={mq}")

            results["search_latency"]["metadata"] = {
                "mean_ms": round(statistics.mean(t["median_ms"] for t in meta_latencies), 2),
                "median_ms": round(statistics.median(t["median_ms"] for t in meta_latencies), 2),
                "p95_ms": round(sorted(t["p95_ms"] for t in meta_latencies)[
                    int(len(meta_latencies) * 0.95)], 2),
            }
            print(f"\n  Metadata overall: median={results['search_latency']['metadata']['median_ms']:.2f}ms")
        else:
            print("\n  --- Metadata Search: NOT AVAILABLE (master branch) ---")

        # 2f. Graph search
        print("\n  --- Graph Search ---")
        graph_latencies = []
        graph_queries = ["Python programming", "machine learning AI", "database SQLite"]
        for gq in graph_queries:
            timing = time_operation(
                adapter.graph_search, gq, limit=5, iterations=10
            )
            graph_latencies.append(timing)
            print(f"    [{timing['median_ms']:6.2f}ms med] \"{gq}\"")

        results["search_latency"]["graph"] = {
            "mean_ms": round(statistics.mean(t["median_ms"] for t in graph_latencies), 2),
            "median_ms": round(statistics.median(t["median_ms"] for t in graph_latencies), 2),
        }

        # 2g. Entity-boost search (FEATURE BRANCH — check if param exists)
        try:
            # Test if entity_boost parameter is accepted
            adapter.search("test", top_k=1, entity_boost=True)
            has_entity_boost = True
        except TypeError:
            has_entity_boost = False

        if has_entity_boost:
            print("\n  --- Entity-Boost Search ---")
            eb_latencies = []
            for q in BENCHMARK_QUERIES:
                timing = time_operation(
                    adapter.search, q["query"], top_k=5, entity_boost=True, iterations=10
                )
                eb_latencies.append(timing)
                print(f"    [{timing['median_ms']:6.2f}ms med] \"{q['query'][:50]}\"")

            results["search_latency"]["entity_boost"] = {
                "mean_ms": round(statistics.mean(t["median_ms"] for t in eb_latencies), 2),
                "median_ms": round(statistics.median(t["median_ms"] for t in eb_latencies), 2),
                "p95_ms": round(sorted(t["p95_ms"] for t in eb_latencies)[
                    int(len(eb_latencies) * 0.95)], 2),
            }
            print(f"\n  Entity-boost overall: median={results['search_latency']['entity_boost']['median_ms']:.2f}ms")
        else:
            print("\n  --- Entity-Boost Search: NOT AVAILABLE (master branch) ---")

        # 2g2. Reranked search (two-phase: hybrid + cross-encoder)
        if HAS_RERANKED_SEARCH and HAS_RERANKER:
            print("\n  --- Reranked Search (hybrid + cross-encoder) ---")
            try:
                reranker = create_reranker(preset="fast")
                if reranker:
                    rr_latencies = []
                    for q in BENCHMARK_QUERIES:
                        timing = time_operation(
                            adapter.search_reranked, q["query"],
                            limit=5, reranker=reranker, iterations=5
                        )
                        rr_latencies.append(timing)
                        print(f"    [{timing['median_ms']:6.2f}ms med, {timing['p95_ms']:6.2f}ms p95] "
                              f"\"{q['query'][:50]}\"")

                    results["search_latency"]["reranked"] = {
                        "mean_ms": round(statistics.mean(t["median_ms"] for t in rr_latencies), 2),
                        "median_ms": round(statistics.median(t["median_ms"] for t in rr_latencies), 2),
                        "p95_ms": round(sorted(t["p95_ms"] for t in rr_latencies)[
                            int(len(rr_latencies) * 0.95)], 2),
                        "min_ms": round(min(t["min_ms"] for t in rr_latencies), 2),
                        "max_ms": round(max(t["max_ms"] for t in rr_latencies), 2),
                    }
                    print(f"\n  Reranked overall: median={results['search_latency']['reranked']['median_ms']:.2f}ms, "
                          f"p95={results['search_latency']['reranked']['p95_ms']:.2f}ms")

                    # Also measure reranked relevance
                    print("\n  --- Reranked Search Relevance ---")
                    rr_relevance = []
                    for q in BENCHMARK_QUERIES:
                        search_results = adapter.search_reranked(
                            q["query"], limit=5, reranker=reranker
                        )
                        result_dicts = _results_to_dicts(search_results)
                        score = compute_relevance_score(result_dicts, q["expected_topic"])
                        rr_relevance.append(score)
                        top_match = "✓" if score >= 0.4 else "✗"
                        print(f"    {top_match} [{score:.3f}] \"{q['query'][:45]}\" (expect: {q['expected_topic']})")

                    results["relevance"]["reranked"] = {
                        "mean_ndcg": round(statistics.mean(rr_relevance), 3),
                        "median_ndcg": round(statistics.median(rr_relevance), 3),
                        "min_ndcg": round(min(rr_relevance), 3),
                        "queries_with_top1_match": sum(1 for s in rr_relevance if s >= 0.4),
                        "total_queries": len(rr_relevance),
                    }
                    print(f"\n  Reranked relevance: mean={results['relevance']['reranked']['mean_ndcg']:.3f}, "
                          f"top-1 accuracy={results['relevance']['reranked']['queries_with_top1_match']}/{len(rr_relevance)}")

                    # Clean up reranker
                    reranker.unload()
                else:
                    print("\n  --- Reranked Search: reranker failed to load ---")
            except Exception as e:
                print(f"\n  --- Reranked Search: ERROR: {e} ---")
        else:
            print("\n  --- Reranked Search: NOT AVAILABLE ---")

        # 2h. File system search (FEATURE BRANCH ONLY)
        if HAS_FILE_SEARCHER:
            print("\n  --- File System Search (no GPU, no index) ---")
            # Create test files in the expected directory structure
            search_data_dir = os.path.join(tmpdir, "file_search_data")
            uploads_dir = os.path.join(search_data_dir, "uploads")
            os.makedirs(uploads_dir, exist_ok=True)
            for i, doc in enumerate(DOCUMENTS):
                fname = doc["metadata"].get("filename", f"doc_{i}.txt")
                # Use .txt extension for all (FileSearcher skips binary)
                if not fname.endswith(".txt"):
                    fname = fname.rsplit(".", 1)[0] + ".txt"
                with open(os.path.join(uploads_dir, fname), "w") as f:
                    f.write(doc["text"])

            fs = FileSearcher(data_dir=search_data_dir)
            fs_latencies = []
            fs_queries = ["Python programming", "neural network", "privacy GDPR", "Jetson CUDA"]
            for fq in fs_queries:
                timing = time_operation(
                    fs.search, fq, max_results=5, iterations=20
                )
                fs_latencies.append(timing)
                num_results = len(timing["result"]) if timing["result"] else 0
                print(f"    [{timing['median_ms']:6.2f}ms med] \"{fq}\" → {num_results} results")

            results["search_latency"]["file_system"] = {
                "mean_ms": round(statistics.mean(t["median_ms"] for t in fs_latencies), 2),
                "median_ms": round(statistics.median(t["median_ms"] for t in fs_latencies), 2),
                "p95_ms": round(sorted(t["p95_ms"] for t in fs_latencies)[
                    int(len(fs_latencies) * 0.95)], 2),
            }
            print(f"\n  File system overall: median={results['search_latency']['file_system']['median_ms']:.2f}ms")
        else:
            print("\n  --- File System Search: NOT AVAILABLE (master branch) ---")

        # =====================================================================
        # 3. RELEVANCE BENCHMARKS
        # =====================================================================
        print(f"\n{'='*50}")
        print(" 3. SEARCH RELEVANCE (topic accuracy)")
        print("=" * 50)

        # 3a. Hybrid search relevance
        print("\n  --- Hybrid Search Relevance ---")
        hybrid_relevance = []
        for q in BENCHMARK_QUERIES:
            search_results = adapter.search(q["query"], top_k=5)
            # Convert to dict format for scoring
            result_dicts = _results_to_dicts(search_results)
            score = compute_relevance_score(result_dicts, q["expected_topic"])
            hybrid_relevance.append(score)

            # Check if top result matches expected topic
            top_match = "✓" if score >= 0.4 else "✗"
            top_score_val = _get_score(search_results[0]) if search_results else 0
            print(f"    {top_match} [{score:.3f}] \"{q['query'][:45]}\" "
                  f"(expect: {q['expected_topic']}, top_score: {top_score_val:.3f})")

        results["relevance"]["hybrid"] = {
            "mean_ndcg": round(statistics.mean(hybrid_relevance), 3),
            "median_ndcg": round(statistics.median(hybrid_relevance), 3),
            "min_ndcg": round(min(hybrid_relevance), 3),
            "queries_with_top1_match": sum(1 for s in hybrid_relevance if s >= 0.4),
            "total_queries": len(hybrid_relevance),
        }
        print(f"\n  Hybrid relevance: mean={results['relevance']['hybrid']['mean_ndcg']:.3f}, "
              f"top-1 accuracy={results['relevance']['hybrid']['queries_with_top1_match']}/{len(hybrid_relevance)}")

        # 3b. Enhanced search relevance
        print("\n  --- Enhanced Search Relevance ---")
        enhanced_relevance = []
        for q in BENCHMARK_QUERIES:
            search_results = adapter.search_enhanced(q["query"], limit=5)
            result_dicts = _results_to_dicts(search_results)
            score = compute_relevance_score(result_dicts, q["expected_topic"])
            enhanced_relevance.append(score)
            top_match = "✓" if score >= 0.4 else "✗"
            print(f"    {top_match} [{score:.3f}] \"{q['query'][:45]}\" (expect: {q['expected_topic']})")

        results["relevance"]["enhanced"] = {
            "mean_ndcg": round(statistics.mean(enhanced_relevance), 3),
            "median_ndcg": round(statistics.median(enhanced_relevance), 3),
            "min_ndcg": round(min(enhanced_relevance), 3),
            "queries_with_top1_match": sum(1 for s in enhanced_relevance if s >= 0.4),
            "total_queries": len(enhanced_relevance),
        }
        print(f"\n  Enhanced relevance: mean={results['relevance']['enhanced']['mean_ndcg']:.3f}, "
              f"top-1 accuracy={results['relevance']['enhanced']['queries_with_top1_match']}/{len(enhanced_relevance)}")

        # 3c. Keyword search relevance (FEATURE BRANCH)
        if HAS_KEYWORD_SEARCH:
            print("\n  --- Keyword-Only Search Relevance ---")
            kw_relevance = []
            for q in BENCHMARK_QUERIES:
                search_results = adapter.search_keyword(q["query"], limit=5)
                result_dicts = _results_to_dicts(search_results)
                score = compute_relevance_score(result_dicts, q["expected_topic"])
                kw_relevance.append(score)
                top_match = "✓" if score >= 0.4 else "✗"
                print(f"    {top_match} [{score:.3f}] \"{q['query'][:45]}\" (expect: {q['expected_topic']})")

            results["relevance"]["keyword"] = {
                "mean_ndcg": round(statistics.mean(kw_relevance), 3),
                "median_ndcg": round(statistics.median(kw_relevance), 3),
                "min_ndcg": round(min(kw_relevance), 3),
                "queries_with_top1_match": sum(1 for s in kw_relevance if s >= 0.4),
                "total_queries": len(kw_relevance),
            }
            print(f"\n  Keyword relevance: mean={results['relevance']['keyword']['mean_ndcg']:.3f}, "
                  f"top-1 accuracy={results['relevance']['keyword']['queries_with_top1_match']}/{len(kw_relevance)}")

        # 3d. Entity-boost relevance (FEATURE BRANCH)
        if has_entity_boost:
            print("\n  --- Entity-Boost Search Relevance ---")
            eb_relevance = []
            for q in BENCHMARK_QUERIES:
                search_results = adapter.search(q["query"], top_k=5, entity_boost=True)
                result_dicts = _results_to_dicts(search_results)
                score = compute_relevance_score(result_dicts, q["expected_topic"])
                eb_relevance.append(score)
                top_match = "✓" if score >= 0.4 else "✗"
                print(f"    {top_match} [{score:.3f}] \"{q['query'][:45]}\"")

            results["relevance"]["entity_boost"] = {
                "mean_ndcg": round(statistics.mean(eb_relevance), 3),
                "median_ndcg": round(statistics.median(eb_relevance), 3),
                "queries_with_top1_match": sum(1 for s in eb_relevance if s >= 0.4),
                "total_queries": len(eb_relevance),
            }
            print(f"\n  Entity-boost relevance: mean={results['relevance']['entity_boost']['mean_ndcg']:.3f}, "
                  f"top-1 accuracy={results['relevance']['entity_boost']['queries_with_top1_match']}/{len(eb_relevance)}")

        # =====================================================================
        # 4. DOCUMENT RETRIEVAL LATENCY
        # =====================================================================
        print(f"\n{'='*50}")
        print(" 4. DOCUMENT RETRIEVAL LATENCY")
        print("=" * 50)

        # get_document
        print("\n  --- get_document() ---")
        get_latencies = []
        for did in doc_ids[:5]:
            timing = time_operation(adapter.get_document, did, iterations=20)
            get_latencies.append(timing)

        results["search_latency"]["get_document"] = {
            "mean_ms": round(statistics.mean(t["median_ms"] for t in get_latencies), 2),
            "median_ms": round(statistics.median(t["median_ms"] for t in get_latencies), 2),
        }
        print(f"  get_document: median={results['search_latency']['get_document']['median_ms']:.2f}ms")

        # list_documents (different signatures on master vs feature)
        import inspect
        list_sig = inspect.signature(adapter.list_documents)
        if "limit" in list_sig.parameters:
            timing = time_operation(adapter.list_documents, limit=100, iterations=20)
        else:
            timing = time_operation(adapter.list_documents, page_size=100, iterations=20)
        results["search_latency"]["list_documents"] = {
            "median_ms": round(timing["median_ms"], 2),
        }
        print(f"  list_documents: median={timing['median_ms']:.2f}ms")

        # count
        timing = time_operation(adapter.count, iterations=20)
        results["search_latency"]["count"] = {
            "median_ms": round(timing["median_ms"], 2),
        }
        print(f"  count: median={timing['median_ms']:.2f}ms")

        # =====================================================================
        # 5. HYBRID WEIGHTS COMPARISON (txtai 9.x native)
        # =====================================================================
        print(f"\n{'='*50}")
        print(" 5. HYBRID WEIGHTS COMPARISON")
        print("=" * 50)

        weight_configs = [
            (0.3, "keyword-heavy (0.3)"),
            (0.5, "balanced (0.5)"),
            (0.7, "semantic-heavy (0.7)"),
        ]
        for w, label in weight_configs:
            print(f"\n  --- weights={w} ({label}) ---")
            w_relevance = []
            w_latencies = []
            for q in BENCHMARK_QUERIES:
                timing = time_operation(
                    adapter.search, q["query"], top_k=5, weights=w, iterations=5
                )
                w_latencies.append(timing)
                search_results = adapter.search(q["query"], top_k=5, weights=w)
                result_dicts = _results_to_dicts(search_results)
                score = compute_relevance_score(result_dicts, q["expected_topic"])
                w_relevance.append(score)
                top_match = "✓" if score >= 0.4 else "✗"
                print(f"    {top_match} [{score:.3f}] [{timing['median_ms']:6.2f}ms] "
                      f"\"{q['query'][:40]}\"")

            w_key = f"weights_{w}"
            results["search_latency"][w_key] = {
                "median_ms": round(statistics.median(t["median_ms"] for t in w_latencies), 2),
            }
            results["relevance"][w_key] = {
                "mean_ndcg": round(statistics.mean(w_relevance), 3),
                "queries_with_top1_match": sum(1 for s in w_relevance if s >= 0.4),
                "total_queries": len(w_relevance),
            }
            print(f"\n  {label}: relevance={results['relevance'][w_key]['mean_ndcg']:.3f}, "
                  f"latency={results['search_latency'][w_key]['median_ms']:.2f}ms")

        # =====================================================================
        # 6. SUMMARY
        # =====================================================================
        print(f"\n{'='*70}")
        print(" BENCHMARK SUMMARY")
        print(f"{'='*70}")
        print(f"  Branch: {branch} ({commit})")
        print(f"  Documents: {len(DOCUMENTS)} ({total_chars} chars)")
        print()
        print("  INDEXING:")
        print(f"    Throughput: {results['indexing']['docs_per_second']:.1f} docs/sec")
        print(f"    Mean per doc: {results['indexing']['mean_per_doc_ms']:.1f}ms")
        print()
        print("  SEARCH LATENCY (median):")
        for mode, data in results["search_latency"].items():
            if isinstance(data, dict) and "median_ms" in data:
                print(f"    {mode:20s}: {data['median_ms']:8.2f}ms")
        print()
        print("  RELEVANCE (mean nDCG):")
        for mode, data in results["relevance"].items():
            if isinstance(data, dict) and "mean_ndcg" in data:
                acc = f"{data['queries_with_top1_match']}/{data['total_queries']}"
                print(f"    {mode:20s}: {data['mean_ndcg']:.3f} (top-1 accuracy: {acc})")

        adapter._store.close()

    except Exception as e:
        print(f"\n  ERROR: {e}")
        import traceback
        traceback.print_exc()
        results["error"] = str(e)
    finally:
        # Cleanup
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

    return results


def save_results(results, filename):
    """Save benchmark results to JSON file."""
    with open(filename, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n  Results saved to: {filename}")


def compare_results(baseline_file, feature_file):
    """Compare two benchmark result files and print a table."""
    with open(baseline_file) as f:
        baseline = json.load(f)
    with open(feature_file) as f:
        feature = json.load(f)

    print(f"\n{'='*80}")
    print(f" PERFORMANCE COMPARISON: {baseline['branch']} vs {feature['branch']}")
    print(f"{'='*80}")

    # Indexing comparison
    print(f"\n  INDEXING")
    print(f"  {'Metric':<30s} {'Baseline':>12s} {'Feature':>12s} {'Delta':>12s}")
    print(f"  {'-'*66}")
    bi = baseline.get("indexing", {})
    fi = feature.get("indexing", {})
    for key in ["mean_per_doc_ms", "docs_per_second", "chars_per_second"]:
        bv = bi.get(key, 0)
        fv = fi.get(key, 0)
        if bv > 0:
            delta_pct = ((fv - bv) / bv) * 100
            sign = "+" if delta_pct >= 0 else ""
            print(f"  {key:<30s} {bv:>12.1f} {fv:>12.1f} {sign}{delta_pct:>10.1f}%")

    # Search latency comparison
    print(f"\n  SEARCH LATENCY (median ms)")
    print(f"  {'Mode':<30s} {'Baseline':>12s} {'Feature':>12s} {'Delta':>12s}")
    print(f"  {'-'*66}")
    all_modes = set(list(baseline.get("search_latency", {}).keys()) +
                    list(feature.get("search_latency", {}).keys()))
    for mode in sorted(all_modes):
        bv = baseline.get("search_latency", {}).get(mode, {}).get("median_ms", None)
        fv = feature.get("search_latency", {}).get(mode, {}).get("median_ms", None)
        bstr = f"{bv:.2f}" if bv is not None else "N/A"
        fstr = f"{fv:.2f}" if fv is not None else "N/A"
        if bv is not None and fv is not None and bv > 0:
            delta_pct = ((fv - bv) / bv) * 100
            sign = "+" if delta_pct >= 0 else ""
            dstr = f"{sign}{delta_pct:.1f}%"
        elif fv is not None and bv is None:
            dstr = "NEW"
        else:
            dstr = "---"
        print(f"  {mode:<30s} {bstr:>12s} {fstr:>12s} {dstr:>12s}")

    # Relevance comparison
    print(f"\n  RELEVANCE (mean nDCG)")
    print(f"  {'Mode':<30s} {'Baseline':>12s} {'Feature':>12s} {'Delta':>12s}")
    print(f"  {'-'*66}")
    all_modes = set(list(baseline.get("relevance", {}).keys()) +
                    list(feature.get("relevance", {}).keys()))
    for mode in sorted(all_modes):
        bv = baseline.get("relevance", {}).get(mode, {}).get("mean_ndcg", None)
        fv = feature.get("relevance", {}).get(mode, {}).get("mean_ndcg", None)
        bstr = f"{bv:.3f}" if bv is not None else "N/A"
        fstr = f"{fv:.3f}" if fv is not None else "N/A"
        if bv is not None and fv is not None and bv > 0:
            delta_pct = ((fv - bv) / bv) * 100
            sign = "+" if delta_pct >= 0 else ""
            dstr = f"{sign}{delta_pct:.1f}%"
        elif fv is not None and bv is None:
            dstr = "NEW"
        else:
            dstr = "---"
        print(f"  {mode:<30s} {bstr:>12s} {fstr:>12s} {dstr:>12s}")

    # New features summary
    new_features = []
    for mode in feature.get("search_latency", {}):
        if mode not in baseline.get("search_latency", {}):
            new_features.append(mode)
    if new_features:
        print(f"\n  NEW SEARCH MODES (feature branch only):")
        for nf in new_features:
            data = feature["search_latency"][nf]
            med = data.get("median_ms", "?")
            print(f"    {nf}: {med}ms median")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="MindSage Search Benchmark")
    parser.add_argument("--save", help="Save results to JSON file")
    parser.add_argument("--compare", nargs=2, metavar=("BASELINE", "FEATURE"),
                        help="Compare two result JSON files")
    args = parser.parse_args()

    if args.compare:
        compare_results(args.compare[0], args.compare[1])
    else:
        results = run_benchmark()
        if args.save:
            save_results(results, args.save)
