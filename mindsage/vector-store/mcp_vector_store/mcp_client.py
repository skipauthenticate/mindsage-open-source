"""Universal MCP client library for MCP Vector Store.

This module provides a simple interface for any LLM application to connect
to the MCP Vector Store server over HTTP/SSE.
"""

import asyncio
import json
from typing import List, Dict, Any, Optional
import httpx
from mcp import ClientSession
from mcp.client.sse import sse_client


class MCPVectorStoreClient:
    """Universal client for MCP Vector Store server.

    Works with any LLM framework (LangChain, OpenAI, Claude, custom apps).

    Example:
        # Connect to local server
        client = MCPVectorStoreClient("http://localhost:8085")

        # Connect to remote server with auth
        client = MCPVectorStoreClient(
            "http://192.168.1.100:8085",
            api_key="your-api-key"
        )

        # Use with async context manager
        async with client:
            results = await client.search("machine learning", top_k=5)
            for result in results:
                print(f"[{result['score']:.4f}] {result['text']}")
    """

    def __init__(self, base_url: str, api_key: Optional[str] = None):
        """Initialize the client.

        Args:
            base_url: MCP server URL (e.g., "http://192.168.1.100:8085")
            api_key: Optional API key for authentication
        """
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.headers = {}

        if self.api_key:
            self.headers["Authorization"] = f"Bearer {self.api_key}"

        self._session: Optional[ClientSession] = None
        self._sse_context = None
        self._read = None
        self._write = None

    async def __aenter__(self):
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.disconnect()

    async def check_health(self) -> Dict[str, Any]:
        """Check if server is healthy.

        Returns:
            Health status dictionary

        Raises:
            ConnectionError: If server is not accessible
        """
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    f"{self.base_url}/health",
                    timeout=5.0
                )
                response.raise_for_status()
                return response.json()
            except Exception as e:
                raise ConnectionError(f"Cannot connect to {self.base_url}: {e}")

    async def get_info(self) -> Dict[str, Any]:
        """Get server information and statistics.

        Returns:
            Server info and stats dictionary
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/info",
                headers=self.headers,
                timeout=5.0
            )
            response.raise_for_status()
            return response.json()

    async def connect(self):
        """Establish connection to MCP server."""
        sse_url = f"{self.base_url}/sse"

        # Create SSE connection
        self._sse_context = sse_client(sse_url, headers=self.headers)
        self._read, self._write = await self._sse_context.__aenter__()

        # Create MCP session
        session_context = ClientSession(self._read, self._write)
        self._session = await session_context.__aenter__()

        # Initialize session
        await self._session.initialize()

    async def disconnect(self):
        """Close connection to MCP server."""
        if self._session:
            await self._session.__aexit__(None, None, None)
            self._session = None

        if self._sse_context:
            await self._sse_context.__aexit__(None, None, None)
            self._sse_context = None

    def _ensure_connected(self):
        """Ensure client is connected."""
        if not self._session:
            raise RuntimeError(
                "Client not connected. Use 'async with client:' or call await client.connect()"
            )

    async def search(
        self,
        query: str,
        top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """Search for documents similar to query.

        Args:
            query: Search query text
            top_k: Number of results to return (1-20)

        Returns:
            List of matching documents with scores and metadata

        Example:
            results = await client.search("machine learning", top_k=3)
            # [
            #   {"id": 1, "text": "...", "score": 0.95, "metadata": {...}},
            #   {"id": 2, "text": "...", "score": 0.87, "metadata": {...}},
            # ]
        """
        self._ensure_connected()

        result = await self._session.call_tool("search_documents", {
            "query": query,
            "top_k": top_k
        })

        data = json.loads(result.content[0].text)
        return data.get("results", [])

    async def think(
        self,
        question: str,
        top_k: int = 8,
        freshness_days: int = 90,
        include_gaps: bool = True,
    ) -> Dict[str, Any]:
        """Build PII-safe cited reasoning context for a question.

        Args:
            question: Question to answer from private memory
            top_k: Number of evidence sources to inspect (1-20)
            freshness_days: Warn when sources are older than this many days
            include_gaps: Include explicit missing-evidence gaps

        Returns:
            Dictionary with answer_brief, citations, citation_graph,
            coverage, gaps, contradictions, freshness, safe entity graph,
            maintenance actions, and privacy metadata.
        """
        self._ensure_connected()

        result = await self._session.call_tool("think", {
            "question": question,
            "top_k": top_k,
            "freshness_days": freshness_days,
            "include_gaps": include_gaps,
        })

        return json.loads(result.content[0].text)

    async def write_memory(
        self,
        kind: str,
        content: str,
        workspace: str = "default",
        actor: str = "agent",
        memory_key: Optional[str] = None,
        state: str = "accepted",
        source_document_id: Optional[int] = None,
        relations: Optional[List[Dict[str, Any]]] = None,
        ttl_days: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
        reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Write a typed, versioned memory record with audit metadata."""
        self._ensure_connected()

        result = await self._session.call_tool("write_memory", {
            "kind": kind,
            "content": content,
            "workspace": workspace,
            "actor": actor,
            "memory_key": memory_key,
            "state": state,
            "source_document_id": source_document_id,
            "relations": relations,
            "ttl_days": ttl_days,
            "metadata": metadata,
            "reason": reason,
        })

        return json.loads(result.content[0].text)

    async def search_memory(
        self,
        query: Optional[str] = None,
        workspace: str = "default",
        kind: Optional[str] = None,
        memory_key: Optional[str] = None,
        include_states: Optional[List[str]] = None,
        include_expired: bool = False,
        top_k: int = 10,
        min_score: Optional[float] = 0.3,
    ) -> Dict[str, Any]:
        """Search typed memory with accepted/non-expired defaults."""
        self._ensure_connected()

        result = await self._session.call_tool("search_memory", {
            "query": query,
            "workspace": workspace,
            "kind": kind,
            "memory_key": memory_key,
            "include_states": include_states,
            "include_expired": include_expired,
            "top_k": top_k,
            "min_score": min_score,
        })

        return json.loads(result.content[0].text)

    async def memory_timeline(
        self,
        memory_key: str,
        workspace: str = "default",
    ) -> Dict[str, Any]:
        """Return the audit timeline for one typed-memory key."""
        self._ensure_connected()

        result = await self._session.call_tool("memory_timeline", {
            "workspace": workspace,
            "memory_key": memory_key,
        })

        return json.loads(result.content[0].text)

    async def memory_graph(
        self,
        workspace: str = "default",
        center_memory_key: Optional[str] = None,
        include_states: Optional[List[str]] = None,
        include_expired: bool = False,
        limit: int = 100,
    ) -> Dict[str, Any]:
        """Return a graph of typed-memory relations and source-document links."""
        self._ensure_connected()

        result = await self._session.call_tool("memory_graph", {
            "workspace": workspace,
            "center_memory_key": center_memory_key,
            "include_states": include_states,
            "include_expired": include_expired,
            "limit": limit,
        })

        return json.loads(result.content[0].text)

    async def memory_workspace_info(self, workspace: str = "default") -> Dict[str, Any]:
        """Return workspace-level typed-memory governance counts."""
        self._ensure_connected()

        result = await self._session.call_tool("memory_workspace_info", {
            "workspace": workspace,
        })

        return json.loads(result.content[0].text)

    async def memory_actor_activity(
        self,
        workspace: Optional[str] = None,
        actor: Optional[str] = None,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """Return bounded typed-memory audit activity for an actor or workspace."""
        self._ensure_connected()

        result = await self._session.call_tool("memory_actor_activity", {
            "workspace": workspace,
            "actor": actor,
            "limit": limit,
        })

        return json.loads(result.content[0].text)

    async def add_document(
        self,
        text: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> int:
        """Add a new document to the database.

        Args:
            text: Document text
            metadata: Optional metadata dictionary

        Returns:
            Document ID

        Example:
            doc_id = await client.add_document(
                "Machine learning is awesome",
                metadata={"source": "blog", "author": "John"}
            )
        """
        self._ensure_connected()

        result = await self._session.call_tool("add_document", {
            "text": text,
            "metadata": metadata
        })

        data = json.loads(result.content[0].text)
        return data["document_id"]

    async def add_document_from_file(
        self,
        file_path: str,
        encoding: str = "utf-8",
        additional_metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Add a document by processing a file.

        Args:
            file_path: Path to file to process
            encoding: Text encoding (default: utf-8)
            additional_metadata: Additional metadata to include

        Returns:
            Response dictionary with success, document_id, and metadata

        Example:
            result = await client.add_document_from_file(
                "document.txt",
                additional_metadata={"category": "research"}
            )
            # {"success": True, "document_id": 123, "filename": "document.txt", ...}
        """
        self._ensure_connected()

        result = await self._session.call_tool("add_document_from_file", {
            "file_path": file_path,
            "encoding": encoding,
            "additional_metadata": additional_metadata
        })

        return json.loads(result.content[0].text)

    async def upload_and_add_document(
        self,
        file_path: str,
        encoding: str = "utf-8",
        additional_metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Upload a file from local device and add to vector store.

        This method uploads a file over the network to the MCP server,
        which processes it and adds it to the vector store.

        Args:
            file_path: Path to local file to upload
            encoding: Text encoding (default: utf-8)
            additional_metadata: Additional metadata to include

        Returns:
            Response dictionary with success, document_id, and metadata

        Example:
            # Upload from laptop to Jetson over network
            result = await client.upload_and_add_document(
                "/home/user/document.pdf",
                additional_metadata={"source": "laptop", "category": "research"}
            )
            # {"success": True, "document_id": 123, "filename": "document.pdf", ...}
        """
        import base64
        from pathlib import Path

        self._ensure_connected()

        # Read and encode file
        with open(file_path, 'rb') as f:
            file_content = base64.b64encode(f.read()).decode('utf-8')

        filename = Path(file_path).name

        result = await self._session.call_tool("upload_and_add_document", {
            "file_content": file_content,
            "filename": filename,
            "encoding": encoding,
            "additional_metadata": additional_metadata
        })

        return json.loads(result.content[0].text)

    async def list_documents(
        self,
        page: int = 1,
        page_size: int = 10,
        ascending: bool = False
    ) -> Dict[str, Any]:
        """List documents with pagination.

        Args:
            page: Page number (1-indexed)
            page_size: Documents per page (1-100)
            ascending: If True, oldest first; if False, newest first

        Returns:
            Paginated results dictionary

        Example:
            result = await client.list_documents(page=1, page_size=10)
            # {
            #   "documents": [...],
            #   "page": 1,
            #   "total": 100,
            #   "total_pages": 10,
            #   "has_next": True,
            #   "has_prev": False
            # }
        """
        self._ensure_connected()

        result = await self._session.call_tool("list_documents", {
            "page": page,
            "page_size": page_size,
            "ascending": ascending
        })

        return json.loads(result.content[0].text)

    async def get_document(self, doc_id: int) -> Optional[Dict[str, Any]]:
        """Get a specific document by ID.

        Args:
            doc_id: Document ID

        Returns:
            Document dictionary or None if not found

        Example:
            doc = await client.get_document(123)
            if doc:
                print(doc["text"])
        """
        self._ensure_connected()

        result = await self._session.call_tool("get_document", {
            "doc_id": doc_id
        })

        data = json.loads(result.content[0].text)
        if data.get("success"):
            return data["document"]
        return None

    async def get_stats(self) -> Dict[str, Any]:
        """Get database statistics.

        Returns:
            Statistics dictionary

        Example:
            stats = await client.get_stats()
            print(f"Total documents: {stats['count']}")
            print(f"Embedding dimensions: {stats['dimension']}")
        """
        self._ensure_connected()

        result = await self._session.call_tool("get_stats", {})
        return json.loads(result.content[0].text)


# Convenience function for one-off operations
async def quick_search(
    query: str,
    base_url: str = "http://localhost:8085",
    api_key: Optional[str] = None,
    top_k: int = 5
) -> List[Dict[str, Any]]:
    """Quick search without managing connection manually.

    Args:
        query: Search query
        base_url: MCP server URL
        api_key: Optional API key
        top_k: Number of results

    Returns:
        List of matching documents

    Example:
        from mcp_vector_store.mcp_client import quick_search

        results = await quick_search("AI research", top_k=3)
        for result in results:
            print(result["text"])
    """
    async with MCPVectorStoreClient(base_url, api_key) as client:
        return await client.search(query, top_k)


# Synchronous wrapper for non-async code
class MCPVectorStoreSyncClient:
    """Synchronous wrapper for MCPVectorStoreClient.

    For use in non-async code or frameworks that don't support async.

    Example:
        client = MCPVectorStoreSyncClient("http://localhost:8085")
        results = client.search("machine learning")
    """

    def __init__(self, base_url: str, api_key: Optional[str] = None):
        """Initialize sync client.

        Args:
            base_url: MCP server URL
            api_key: Optional API key
        """
        self._async_client = MCPVectorStoreClient(base_url, api_key)
        self._loop = None

    def _run_async(self, coro):
        """Run async coroutine synchronously."""
        if self._loop is None:
            self._loop = asyncio.new_event_loop()
        return self._loop.run_until_complete(coro)

    def __enter__(self):
        """Context manager entry."""
        self._run_async(self._async_client.connect())
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self._run_async(self._async_client.disconnect())

    def check_health(self) -> Dict[str, Any]:
        """Check server health (synchronous)."""
        return self._run_async(self._async_client.check_health())

    def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """Search for documents (synchronous)."""
        return self._run_async(self._async_client.search(query, top_k))

    def think(
        self,
        question: str,
        top_k: int = 8,
        freshness_days: int = 90,
        include_gaps: bool = True,
    ) -> Dict[str, Any]:
        """Build PII-safe cited reasoning context with citation, entity, and maintenance graphs."""
        return self._run_async(
            self._async_client.think(question, top_k, freshness_days, include_gaps)
        )

    def write_memory(
        self,
        kind: str,
        content: str,
        workspace: str = "default",
        actor: str = "agent",
        memory_key: Optional[str] = None,
        state: str = "accepted",
        source_document_id: Optional[int] = None,
        relations: Optional[List[Dict[str, Any]]] = None,
        ttl_days: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
        reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Write typed memory (synchronous)."""
        return self._run_async(
            self._async_client.write_memory(
                kind,
                content,
                workspace,
                actor,
                memory_key,
                state,
                source_document_id,
                relations,
                ttl_days,
                metadata,
                reason,
            )
        )

    def search_memory(
        self,
        query: Optional[str] = None,
        workspace: str = "default",
        kind: Optional[str] = None,
        memory_key: Optional[str] = None,
        include_states: Optional[List[str]] = None,
        include_expired: bool = False,
        top_k: int = 10,
        min_score: Optional[float] = 0.3,
    ) -> Dict[str, Any]:
        """Search typed memory (synchronous)."""
        return self._run_async(
            self._async_client.search_memory(
                query,
                workspace,
                kind,
                memory_key,
                include_states,
                include_expired,
                top_k,
                min_score,
            )
        )

    def memory_timeline(
        self,
        memory_key: str,
        workspace: str = "default",
    ) -> Dict[str, Any]:
        """Return typed-memory audit timeline (synchronous)."""
        return self._run_async(
            self._async_client.memory_timeline(memory_key, workspace)
        )

    def memory_graph(
        self,
        workspace: str = "default",
        center_memory_key: Optional[str] = None,
        include_states: Optional[List[str]] = None,
        include_expired: bool = False,
        limit: int = 100,
    ) -> Dict[str, Any]:
        """Return typed-memory graph (synchronous)."""
        return self._run_async(
            self._async_client.memory_graph(
                workspace,
                center_memory_key,
                include_states,
                include_expired,
                limit,
            )
        )

    def memory_workspace_info(self, workspace: str = "default") -> Dict[str, Any]:
        """Return workspace-level typed-memory governance counts (synchronous)."""
        return self._run_async(self._async_client.memory_workspace_info(workspace))

    def memory_actor_activity(
        self,
        workspace: Optional[str] = None,
        actor: Optional[str] = None,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """Return bounded typed-memory audit activity (synchronous)."""
        return self._run_async(
            self._async_client.memory_actor_activity(workspace, actor, limit)
        )

    def add_document(
        self,
        text: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> int:
        """Add document (synchronous)."""
        return self._run_async(self._async_client.add_document(text, metadata))

    def add_document_from_file(
        self,
        file_path: str,
        encoding: str = "utf-8",
        additional_metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Add document from file (synchronous)."""
        return self._run_async(
            self._async_client.add_document_from_file(file_path, encoding, additional_metadata)
        )

    def upload_and_add_document(
        self,
        file_path: str,
        encoding: str = "utf-8",
        additional_metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Upload file and add to vector store (synchronous)."""
        return self._run_async(
            self._async_client.upload_and_add_document(file_path, encoding, additional_metadata)
        )

    def list_documents(
        self,
        page: int = 1,
        page_size: int = 10,
        ascending: bool = False
    ) -> Dict[str, Any]:
        """List documents (synchronous)."""
        return self._run_async(
            self._async_client.list_documents(page, page_size, ascending)
        )

    def get_document(self, doc_id: int) -> Optional[Dict[str, Any]]:
        """Get document by ID (synchronous)."""
        return self._run_async(self._async_client.get_document(doc_id))

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics (synchronous)."""
        return self._run_async(self._async_client.get_stats())
