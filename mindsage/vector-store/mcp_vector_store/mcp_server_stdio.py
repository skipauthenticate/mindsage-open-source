"""MCP server with stdio transport for Claude Code integration.

This server wraps the HTTP Vector Store API for use with Claude Code's
stdio-based MCP protocol.
"""

import asyncio
import json
import sys
from typing import Any, List, Optional

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent
from pydantic import BaseModel, Field

try:
    from .remote_auth import build_auth_headers, resolve_remote_api_key
except ImportError:  # Allows direct script execution from the mcp_vector_store directory.
    from remote_auth import build_auth_headers, resolve_remote_api_key


class SearchDocumentsInput(BaseModel):
    query: str = Field(description="Search query text")
    top_k: int = Field(default=5, description="Number of results to return", ge=1, le=20)


class ThinkInput(BaseModel):
    question: str = Field(description="Question to answer from the private memory index")
    top_k: int = Field(default=8, description="Number of evidence sources to inspect", ge=1, le=20)
    min_score: Optional[float] = Field(
        default=0.5,
        description="Minimum similarity score threshold (0.0-1.0)",
        ge=0.0,
        le=1.0,
    )
    freshness_days: int = Field(default=90, description="Warn when cited sources are older than this many days", ge=1, le=3650)
    include_gaps: bool = Field(default=True, description="Include explicit missing-evidence and weak-evidence gaps")


class AddDocumentInput(BaseModel):
    text: str = Field(description="Document text to add")
    metadata: Optional[dict] = Field(default=None, description="Optional metadata")


class WriteMemoryInput(BaseModel):
    kind: str = Field(description="Memory kind: claim, decision, task, artifact, entity, relation, thought_summary, note, policy, preference, or pattern")
    content: str = Field(description="Memory content to store locally")
    workspace: str = Field(default="default", description="Workspace/scope isolation boundary")
    actor: str = Field(default="agent", description="Actor writing the memory")
    memory_key: Optional[str] = Field(default=None, description="Stable key for versioned memories")
    state: str = Field(default="accepted", description="Lifecycle state: scratch, candidate, accepted, or deprecated")
    source_document_id: Optional[int] = Field(default=None, description="Optional source document ID")
    relations: Optional[List[dict]] = Field(default=None, description="Optional typed relations")
    ttl_days: Optional[int] = Field(default=None, description="Optional retention TTL in days", ge=1, le=36500)
    metadata: Optional[dict] = Field(default=None, description="Optional extra metadata")
    reason: Optional[str] = Field(default=None, description="Reason for the memory write or revision")


class SearchMemoryInput(BaseModel):
    query: Optional[str] = Field(default=None, description="Optional semantic query over typed memory content")
    workspace: str = Field(default="default", description="Workspace/scope to search")
    kind: Optional[str] = Field(default=None, description="Optional memory kind filter")
    memory_key: Optional[str] = Field(default=None, description="Optional exact memory key filter")
    include_states: Optional[List[str]] = Field(default=None, description="Lifecycle states to include. Defaults to accepted only.")
    include_expired: bool = Field(default=False, description="If true, include expired memories")
    top_k: int = Field(default=10, description="Maximum typed-memory records to return", ge=1, le=50)
    min_score: Optional[float] = Field(default=0.3, description="Minimum semantic score when query is provided", ge=0.0, le=1.0)


class MemoryTimelineInput(BaseModel):
    workspace: str = Field(default="default", description="Workspace/scope isolation boundary")
    memory_key: str = Field(description="Stable memory key to audit")


class MemoryGraphInput(BaseModel):
    workspace: str = Field(default="default", description="Workspace/scope to graph")
    center_memory_key: Optional[str] = Field(default=None, description="Optional memory key to center the graph on")
    include_states: Optional[List[str]] = Field(default=None, description="Lifecycle states to include. Defaults to accepted only.")
    include_expired: bool = Field(default=False, description="If true, include expired memories")
    limit: int = Field(default=100, description="Maximum typed-memory records to inspect", ge=1, le=500)


class MemoryWorkspaceInfoInput(BaseModel):
    workspace: str = Field(default="default", description="Workspace/scope isolation boundary")


class MemoryActorActivityInput(BaseModel):
    workspace: Optional[str] = Field(default=None, description="Optional workspace/scope filter")
    actor: Optional[str] = Field(default=None, description="Optional actor filter")
    limit: int = Field(default=50, description="Maximum audit events to return", ge=1, le=500)


class GetStatsInput(BaseModel):
    pass


class ListDocumentsInput(BaseModel):
    page: int = Field(default=1, description="Page number", ge=1)
    page_size: int = Field(default=10, description="Documents per page", ge=1, le=100)


class GetDocumentInput(BaseModel):
    doc_id: int = Field(description="Document ID to retrieve", ge=1)


class DeleteDocumentInput(BaseModel):
    doc_id: int = Field(description="Document ID to delete", ge=1)


class MCPVectorStoreStdioServer:
    """MCP stdio server that wraps the HTTP Vector Store API."""

    def __init__(self, base_url: str = "http://localhost:8085", api_key: Optional[str] = None):
        self.base_url = base_url
        self.api_key = resolve_remote_api_key(api_key)
        self.headers = build_auth_headers(self.api_key)
        self.server = Server("mcp-vector-store")
        self._register_handlers()

    def _register_handlers(self):
        @self.server.list_tools()
        async def list_tools() -> List[Tool]:
            return [
                Tool(
                    name="search_documents",
                    description="Search the vector database for documents similar to a query. Returns relevant documents with similarity scores.",
                    inputSchema=SearchDocumentsInput.model_json_schema()
                ),
                Tool(
                    name="think",
                    description="Answer a question with PII-safe cited evidence, cited-answer graph links, safe entity graph links, source coverage, freshness warnings, contradictions, explicit gaps, and citation-maintenance actions.",
                    inputSchema=ThinkInput.model_json_schema()
                ),
                Tool(
                    name="add_document",
                    description="Add a new document to the vector database.",
                    inputSchema=AddDocumentInput.model_json_schema()
                ),
                Tool(
                    name="write_memory",
                    description="Write a typed, versioned memory record with append-only audit metadata.",
                    inputSchema=WriteMemoryInput.model_json_schema()
                ),
                Tool(
                    name="search_memory",
                    description="Search typed memory with accepted, non-expired defaults and redacted previews.",
                    inputSchema=SearchMemoryInput.model_json_schema()
                ),
                Tool(
                    name="memory_timeline",
                    description="Return an audit timeline for one typed-memory key.",
                    inputSchema=MemoryTimelineInput.model_json_schema()
                ),
                Tool(
                    name="memory_graph",
                    description="Return a graph of typed-memory records, declared relations, and source-document links.",
                    inputSchema=MemoryGraphInput.model_json_schema()
                ),
                Tool(
                    name="memory_workspace_info",
                    description="Return workspace-level typed-memory counts by kind, state, actor, retention status, and audit window.",
                    inputSchema=MemoryWorkspaceInfoInput.model_json_schema()
                ),
                Tool(
                    name="memory_actor_activity",
                    description="Return bounded append-only typed-memory audit activity for an actor or workspace.",
                    inputSchema=MemoryActorActivityInput.model_json_schema()
                ),
                Tool(
                    name="get_stats",
                    description="Get statistics about the vector database.",
                    inputSchema=GetStatsInput.model_json_schema()
                ),
                Tool(
                    name="list_documents",
                    description="List documents with pagination.",
                    inputSchema=ListDocumentsInput.model_json_schema()
                ),
                Tool(
                    name="get_document",
                    description="Get a specific document by ID.",
                    inputSchema=GetDocumentInput.model_json_schema()
                ),
                Tool(
                    name="delete_document",
                    description="Delete a document by ID.",
                    inputSchema=DeleteDocumentInput.model_json_schema()
                ),
            ]

        @self.server.call_tool()
        async def call_tool(name: str, arguments: Any) -> List[TextContent]:
            try:
                async with httpx.AsyncClient(timeout=30.0, headers=self.headers) as client:
                    if name == "search_documents":
                        resp = await client.post(
                            f"{self.base_url}/api/search",
                            json={
                                "query": arguments.get("query", ""),
                                "top_k": arguments.get("top_k", 5),
                                "context": "llm"  # LLM context: return redacted images for PII safety
                            }
                        )
                        return [TextContent(type="text", text=resp.text)]

                    elif name == "think":
                        resp = await client.post(
                            f"{self.base_url}/api/think",
                            json={
                                "question": arguments.get("question", ""),
                                "top_k": arguments.get("top_k", 8),
                                "min_score": arguments.get("min_score", 0.5),
                                "freshness_days": arguments.get("freshness_days", 90),
                                "include_gaps": arguments.get("include_gaps", True),
                            }
                        )
                        return [TextContent(type="text", text=resp.text)]

                    elif name == "add_document":
                        resp = await client.post(
                            f"{self.base_url}/api/documents",
                            json={"text": arguments.get("text", ""), "metadata": arguments.get("metadata")}
                        )
                        return [TextContent(type="text", text=resp.text)]

                    elif name == "write_memory":
                        resp = await client.post(
                            f"{self.base_url}/api/memory",
                            json={
                                "kind": arguments.get("kind", ""),
                                "content": arguments.get("content", ""),
                                "workspace": arguments.get("workspace", "default"),
                                "actor": arguments.get("actor", "agent"),
                                "memory_key": arguments.get("memory_key"),
                                "state": arguments.get("state", "accepted"),
                                "source_document_id": arguments.get("source_document_id"),
                                "relations": arguments.get("relations"),
                                "ttl_days": arguments.get("ttl_days"),
                                "metadata": arguments.get("metadata"),
                                "reason": arguments.get("reason"),
                            }
                        )
                        return [TextContent(type="text", text=resp.text)]

                    elif name == "search_memory":
                        resp = await client.post(
                            f"{self.base_url}/api/memory/search",
                            json={
                                "query": arguments.get("query"),
                                "workspace": arguments.get("workspace", "default"),
                                "kind": arguments.get("kind"),
                                "memory_key": arguments.get("memory_key"),
                                "include_states": arguments.get("include_states"),
                                "include_expired": arguments.get("include_expired", False),
                                "top_k": arguments.get("top_k", 10),
                                "min_score": arguments.get("min_score", 0.3),
                            }
                        )
                        return [TextContent(type="text", text=resp.text)]

                    elif name == "memory_timeline":
                        resp = await client.post(
                            f"{self.base_url}/api/memory/timeline",
                            json={
                                "workspace": arguments.get("workspace", "default"),
                                "memory_key": arguments.get("memory_key", ""),
                            }
                        )
                        return [TextContent(type="text", text=resp.text)]

                    elif name == "memory_graph":
                        resp = await client.post(
                            f"{self.base_url}/api/memory/graph",
                            json={
                                "workspace": arguments.get("workspace", "default"),
                                "center_memory_key": arguments.get("center_memory_key"),
                                "include_states": arguments.get("include_states"),
                                "include_expired": arguments.get("include_expired", False),
                                "limit": arguments.get("limit", 100),
                            }
                        )
                        return [TextContent(type="text", text=resp.text)]

                    elif name == "memory_workspace_info":
                        resp = await client.post(
                            f"{self.base_url}/api/memory/workspace",
                            json={
                                "workspace": arguments.get("workspace", "default"),
                            }
                        )
                        return [TextContent(type="text", text=resp.text)]

                    elif name == "memory_actor_activity":
                        resp = await client.post(
                            f"{self.base_url}/api/memory/activity",
                            json={
                                "workspace": arguments.get("workspace"),
                                "actor": arguments.get("actor"),
                                "limit": arguments.get("limit", 50),
                            }
                        )
                        return [TextContent(type="text", text=resp.text)]

                    elif name == "get_stats":
                        resp = await client.get(f"{self.base_url}/api/stats")
                        return [TextContent(type="text", text=resp.text)]

                    elif name == "list_documents":
                        page = arguments.get("page", 1)
                        page_size = arguments.get("page_size", 10)
                        resp = await client.get(
                            f"{self.base_url}/api/documents",
                            params={"page": page, "page_size": page_size}
                        )
                        return [TextContent(type="text", text=resp.text)]

                    elif name == "get_document":
                        doc_id = arguments.get("doc_id")
                        resp = await client.get(f"{self.base_url}/api/documents/{doc_id}")
                        return [TextContent(type="text", text=resp.text)]

                    elif name == "delete_document":
                        doc_id = arguments.get("doc_id")
                        resp = await client.delete(f"{self.base_url}/api/documents/{doc_id}")
                        return [TextContent(type="text", text=resp.text)]

                    else:
                        return [TextContent(type="text", text=f"Unknown tool: {name}")]

            except httpx.ConnectError:
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "error": "connection_failed",
                        "message": f"Could not connect to Vector Store at {self.base_url}. Is the server running?"
                    })
                )]
            except Exception as e:
                return [TextContent(
                    type="text",
                    text=json.dumps({"error": "request_failed", "message": str(e)})
                )]

    async def run(self):
        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream,
                write_stream,
                self.server.create_initialization_options()
            )


async def main():
    import argparse
    parser = argparse.ArgumentParser(description="MCP Vector Store stdio server")
    parser.add_argument("--url", default="http://localhost:8085", help="Vector Store HTTP URL")
    parser.add_argument(
        "--api-key",
        default=None,
        help="Bearer token for authenticated remote vector-store servers. Also reads VECTOR_STORE_API_KEY or MCP_VECTOR_STORE_API_KEY.",
    )
    args = parser.parse_args()

    server = MCPVectorStoreStdioServer(base_url=args.url, api_key=args.api_key)
    await server.run()


if __name__ == "__main__":
    asyncio.run(main())
