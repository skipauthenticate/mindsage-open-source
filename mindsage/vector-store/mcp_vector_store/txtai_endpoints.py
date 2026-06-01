"""
txtai-specific REST API endpoints for MindSage.

This module provides additional endpoints for txtai features:
- Hybrid search with configurable BM25/semantic weights
- Graph-based search with concept traversal
- Topic network visualization

Integration:
    1. Import this module in mcp_server_http.py
    2. Call create_txtai_routes(server_instance) to get routes
    3. Add routes to the Starlette application

Example:
    from .txtai_endpoints import create_txtai_routes

    # In MCPServer.run():
    txtai_routes = create_txtai_routes(self)
    routes.extend(txtai_routes)
"""

from typing import TYPE_CHECKING, List, Dict, Any
from starlette.routing import Route
from starlette.responses import JSONResponse
from starlette.requests import Request

if TYPE_CHECKING:
    from .mcp_server_http import MCPServer


def create_txtai_routes(server: 'MCPServer') -> List[Route]:
    """
    Create txtai-specific REST API routes.

    Args:
        server: MCPServer instance with vector_store and embedding_model

    Returns:
        List of Starlette Route objects
    """

    async def api_hybrid_search(request: Request) -> JSONResponse:
        """
        Hybrid search with configurable BM25/semantic weights.

        Request body:
            query: str - Search query
            top_k: int - Number of results (default: 5)
            keyword_weight: float - BM25 weight (default: 0.3)
            semantic_weight: float - Vector weight (default: 0.7)
            min_score: float - Minimum score threshold (default: 0.0)

        Returns:
            results: List of search results with scores
        """
        try:
            body = await request.json()
            query = body.get("query", "")
            top_k = body.get("top_k", 5)
            keyword_weight = body.get("keyword_weight", 0.3)
            semantic_weight = body.get("semantic_weight", 0.7)
            min_score = body.get("min_score", 0.0)

            if not query:
                return JSONResponse(
                    {"error": "Query is required"},
                    status_code=400
                )

            # Check if using txtai adapter
            if hasattr(server.vector_store, 'search_hybrid'):
                results = server.vector_store.search_hybrid(
                    query=query,
                    limit=min(top_k, 20),
                    keyword_weight=keyword_weight,
                    semantic_weight=semantic_weight
                )
            else:
                # Fallback to standard search
                results = server.vector_store.search(
                    query=query,
                    embedding_model=server.embedding_model,
                    top_k=min(top_k, 20),
                    min_score=min_score
                )

            return JSONResponse({
                "results": [
                    {
                        "id": r.id if hasattr(r, 'id') else r.get("id"),
                        "text": r.text if hasattr(r, 'text') else r.get("text"),
                        "score": r.score if hasattr(r, 'score') else r.get("score"),
                        "metadata": r.metadata if hasattr(r, 'metadata') else r.get("metadata"),
                        "topics": r.topics if hasattr(r, 'topics') else r.get("topics")
                    }
                    for r in results
                ],
                "query": query,
                "weights": {
                    "keyword": keyword_weight,
                    "semantic": semantic_weight
                }
            })

        except Exception as e:
            return JSONResponse(
                {"error": f"Hybrid search failed: {str(e)}"},
                status_code=500
            )

    async def api_graph_search(request: Request) -> JSONResponse:
        """
        Graph-based search with concept traversal.

        Request body:
            query: str - Search query
            top_k: int - Number of results (default: 5)
            depth: int - Graph traversal depth (default: 1)

        Returns:
            results: List of search results
            related_concepts: List of related concepts from graph
        """
        try:
            body = await request.json()
            query = body.get("query", "")
            top_k = body.get("top_k", 5)
            depth = body.get("depth", 1)

            if not query:
                return JSONResponse(
                    {"error": "Query is required"},
                    status_code=400
                )

            # Check if using txtai adapter with graph support
            if hasattr(server.vector_store, 'graph_search'):
                result = server.vector_store.graph_search(
                    query=query,
                    limit=min(top_k, 20),
                    depth=depth
                )
                return JSONResponse(result)
            else:
                # Fallback: standard search, no graph
                results = server.vector_store.search(
                    query=query,
                    embedding_model=server.embedding_model,
                    top_k=min(top_k, 20)
                )
                return JSONResponse({
                    "results": [
                        {
                            "id": r.id,
                            "text": r.text,
                            "score": r.score,
                            "metadata": r.metadata,
                            "topics": r.topics
                        }
                        for r in results
                    ],
                    "related_concepts": [],
                    "note": "Graph search requires txtai backend"
                })

        except Exception as e:
            return JSONResponse(
                {"error": f"Graph search failed: {str(e)}"},
                status_code=500
            )

    async def api_topic_network(request: Request) -> JSONResponse:
        """
        Get topic network for visualization.

        Returns:
            topics: List of topics with their connections
        """
        try:
            # Check if using txtai with graph support
            if hasattr(server.vector_store, '_store') and hasattr(server.vector_store._store, '_embeddings'):
                embeddings = server.vector_store._store._embeddings
                if hasattr(embeddings, 'graph') and embeddings.graph is not None:
                    try:
                        with server.vector_store._store._write_lock:
                            topics = embeddings.graph.topics() if hasattr(embeddings.graph, 'topics') else []
                        return JSONResponse({
                            "topics": topics,
                            "source": "txtai_graph"
                        })
                    except Exception:
                        pass

            # Fallback: get topics from documents
            if hasattr(server.vector_store, 'get_all_topics'):
                all_topics = server.vector_store.get_all_topics()
            else:
                all_topics = server.vector_store.get_all_topics_with_counts()

            return JSONResponse({
                "topics": [
                    {"name": t.get("topic", t.get("name", "")), "count": t.get("count", 0)}
                    for t in all_topics
                ],
                "source": "document_aggregation"
            })

        except Exception as e:
            return JSONResponse(
                {"error": f"Failed to get topic network: {str(e)}"},
                status_code=500
            )

    async def api_multilevel_search(request: Request) -> JSONResponse:
        """
        Multi-level hierarchical search.

        Request body:
            query: str - Search query
            top_k: int - Number of results (default: 5)
            levels: List[str] - Levels to search ["document", "section", "passage"]
            include_context: bool - Include parent context (default: true)

        Returns:
            results: List of results with context
        """
        try:
            body = await request.json()
            query = body.get("query", "")
            top_k = body.get("top_k", 5)
            levels = body.get("levels", ["passage", "section"])
            include_context = body.get("include_context", True)

            if not query:
                return JSONResponse(
                    {"error": "Query is required"},
                    status_code=400
                )

            # Standard search (hierarchical features depend on chunking strategy)
            if hasattr(server.vector_store, 'search'):
                results = server.vector_store.search(
                    query=query,
                    embedding_model=server.embedding_model if hasattr(server, 'embedding_model') else None,
                    top_k=min(top_k, 20)
                )

                formatted_results = []
                for r in results:
                    result_dict = {
                        "id": r.id if hasattr(r, 'id') else r.get("id"),
                        "text": r.text if hasattr(r, 'text') else r.get("text"),
                        "score": r.score if hasattr(r, 'score') else r.get("score"),
                        "metadata": r.metadata if hasattr(r, 'metadata') else r.get("metadata"),
                    }

                    # Check for hierarchical metadata
                    metadata = result_dict.get("metadata", {})
                    if metadata:
                        result_dict["level"] = metadata.get("chunk_type", "document")
                        result_dict["parent_id"] = metadata.get("parent_id")

                    formatted_results.append(result_dict)

                return JSONResponse({
                    "results": formatted_results,
                    "query": query,
                    "levels_searched": levels
                })
            else:
                return JSONResponse(
                    {"error": "Search not available"},
                    status_code=500
                )

        except Exception as e:
            return JSONResponse(
                {"error": f"Multi-level search failed: {str(e)}"},
                status_code=500
            )

    async def api_txtai_status(request: Request) -> JSONResponse:
        """
        Get txtai backend status and capabilities.

        Returns:
            backend: str - Current backend type
            capabilities: Dict - Available features
            stats: Dict - Store statistics
        """
        try:
            # Determine backend type (txtai is the only supported backend)
            backend = "txtai"
            capabilities = {
                "hybrid_search": False,
                "graph_search": False,
                "onnx_inference": False,
                "hierarchical_chunking": False
            }

            # Get txtai capabilities
            if hasattr(server.vector_store, '_store'):
                store = server.vector_store._store

                if hasattr(store, '_config'):
                    config = store._config
                    capabilities["hybrid_search"] = config.get("hybrid", False)
                    capabilities["onnx_inference"] = config.get("backend") == "onnx"

                if hasattr(store, '_embeddings'):
                    embeddings = store._embeddings
                    capabilities["graph_search"] = (
                        hasattr(embeddings, 'graph') and embeddings.graph is not None
                    )

            # Get stats
            stats = {}
            if hasattr(server.vector_store, 'get_stats'):
                stats = server.vector_store.get_stats()
            elif hasattr(server.vector_store, 'count'):
                stats = {"document_count": server.vector_store.count()}

            return JSONResponse({
                "backend": backend,
                "capabilities": capabilities,
                "stats": stats
            })

        except Exception as e:
            return JSONResponse(
                {"error": f"Failed to get status: {str(e)}"},
                status_code=500
            )

    # Return routes
    return [
        Route("/api/search/hybrid", api_hybrid_search, methods=["POST"]),
        Route("/api/search/graph", api_graph_search, methods=["POST"]),
        Route("/api/search/multilevel", api_multilevel_search, methods=["POST"]),
        Route("/api/graph/topics", api_topic_network, methods=["GET"]),
        Route("/api/txtai/status", api_txtai_status, methods=["GET"]),
    ]


# =============================================================================
# Vector Store Factory
# =============================================================================

def create_vector_store(
    db_path: str,
    embedding_dim: int = None,
    use_txtai: bool = True,  # Kept for backwards compatibility, always uses txtai
    txtai_config: Dict[str, Any] = None
):
    """
    Factory function to create the txtai vector store backend.

    Args:
        db_path: Path to database directory
        embedding_dim: Embedding dimension (for validation, optional)
        use_txtai: Deprecated, always uses txtai
        txtai_config: Optional txtai configuration overrides

    Returns:
        TxtaiAdapter instance

    Usage:
        from .txtai_endpoints import create_vector_store

        self.vector_store = create_vector_store(
            db_path=self.db_path,
            embedding_dim=self.embedding_model.get_dimension()
        )
    """
    from .txtai_adapter import TxtaiAdapter
    return TxtaiAdapter(
        db_path=db_path,
        embedding_dim=embedding_dim,
        **(txtai_config or {})
    )
