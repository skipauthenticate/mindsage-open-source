"""MCP server with HTTP transport for network accessibility.

This server runs over HTTP/SSE, allowing LLMs on other devices
to connect to the vector search system over local or public networks.

Supports two modes:
- Local: Accessible only on local network (default, no authentication)
- Public: Internet-accessible with API key authentication

Works on any edge device: Jetson Nano, Raspberry Pi, x86, ARM, etc.
"""

import asyncio
import json
import os
import secrets
from typing import Optional, Dict, Any, List
from contextlib import asynccontextmanager

from mcp.server import Server
from mcp.types import Tool, TextContent
from mcp.server.sse import SseServerTransport
from pydantic import BaseModel, Field
from starlette.applications import Starlette
from starlette.routing import Route, Mount
from starlette.responses import Response, JSONResponse
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
import uvicorn

from .txtai_adapter import EnhancedSearchResult, AddDocumentResult
from .txtai_endpoints import create_vector_store, create_txtai_routes
from .file_processor import FileProcessor
from .file_upload import FileUploadHandler
from .topic_labeler import TopicLabeler, TopicResult
from .passage_extractor import PassageExtractor
from .async_extractor import AsyncExtractor, ExtractionTask
from .async_image_redactor import AsyncImageRedactor, ImageRedactionTask
from .async_audio_redactor import AsyncAudioRedactor, AudioRedactionTask
from .pii_protection import get_pii_protector, PIIProtector
from .audio_processor import AudioProcessor, AUDIO_EXTENSIONS
from .image_processor import ImageProcessor, IMAGE_EXTENSIONS
from .think_tool import build_think_response
from .memory_tool import (
    MEMORY_STATES,
    build_actor_activity,
    build_memory_graph,
    build_memory_record,
    build_memory_timeline,
    build_workspace_info,
    filter_memory_records,
)
from .remote_auth import (
    REMOTE_API_KEY_ENV_KEYS,
    authorize_bearer_header,
    normalize_remote_api_key,
    resolve_remote_api_key,
)

# Image PII redaction - optional (graceful degradation if OCR not available)
try:
    from .image_pii_redactor import (
        ImagePIIRedactor,
        get_image_pii_redactor,
        get_image_pii_config,
    )
    IMAGE_PII_AVAILABLE = True
except ImportError:
    IMAGE_PII_AVAILABLE = False
    ImagePIIRedactor = None
    get_image_pii_redactor = None
    get_image_pii_config = None

# Image storage with PII redaction
from .image_storage import ImageStorageManager, get_image_storage

# Consent management - optional (graceful degradation if not available)
try:
    from .consent_config import CONSENT_PRESETS, get_preset_config, DATA_CATEGORIES
    from .consent_session import get_session_manager, Session
    from .consent_manager import get_consent_manager, ConsentManager
    CONSENT_AVAILABLE = True
except ImportError:
    CONSENT_AVAILABLE = False


# Authentication middleware for public mode
class APIKeyMiddleware:
    """Middleware to validate API keys for public access."""

    def __init__(self, app, api_key: str):
        self.app = app
        self.api_key = normalize_remote_api_key(api_key)
        self.public_endpoints = {"/health"}  # Minimal unauthenticated liveness probe only.

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            # Allow public endpoints without authentication
            path = scope["path"]
            if path in self.public_endpoints:
                await self.app(scope, receive, send)
                return

            # Check for API key
            headers = dict(scope["headers"])
            auth_header = headers.get(b"authorization", b"").decode()
            decision = authorize_bearer_header(auth_header, self.api_key)

            if not decision.authorized:
                response = JSONResponse(
                    {
                        "error": "Unauthorized remote MindSage request",
                        "reason_code": decision.reason_code,
                        "message": "Use Authorization: Bearer <api_key>",
                    },
                    status_code=decision.status_code,
                    headers={"WWW-Authenticate": "Bearer"},
                )
                await response(scope, receive, send)
                return

        await self.app(scope, receive, send)


def transform_metadata_for_context(metadata: Dict[str, Any], context: str = "user") -> Dict[str, Any]:
    """Transform metadata based on access context for LLM safety.

    Args:
        metadata: Document metadata dictionary
        context: Access context - "llm" for LLM API access, "user" for direct user access

    Returns:
        Transformed metadata with appropriate content:
        - context="llm": Returns redacted content if has_pii, hides original
        - context="user": Returns original metadata unchanged

    Safety transformations for LLM context when PII detected:
        - Images: Returns redacted_image_path, hides original_image_path
        - Audio: Returns redacted_transcript, hides original_transcript
        - Audio files: Returns redacted_audio_path, hides original_audio_path
    """
    if context != "llm":
        # User context: return original metadata unchanged
        return metadata

    # LLM context: protect PII
    if not metadata:
        return metadata

    has_pii = metadata.get("has_pii", False)
    if not has_pii:
        # No PII detected: return as-is
        return metadata

    # Create a copy to avoid modifying original
    safe_metadata = dict(metadata)

    # Protect image content
    if "redacted_image_path" in safe_metadata:
        # Replace original path with redacted for LLM safety
        safe_metadata["image_path"] = safe_metadata["redacted_image_path"]
        # Remove original path from LLM view to prevent accidental exposure
        safe_metadata.pop("original_image_path", None)

    # Protect audio transcript content
    if "original_transcript" in safe_metadata:
        # CRITICAL: Never expose original transcript to LLM when PII detected
        # Use redacted_transcript which has PII replaced with [TYPE] tags or LPRAG values
        safe_metadata.pop("original_transcript", None)
        # Note: redacted_transcript remains available for LLM context

    # Protect audio file content
    if "redacted_audio_path" in safe_metadata:
        # Replace original audio path with redacted version
        safe_metadata["audio_path"] = safe_metadata["redacted_audio_path"]
        # Remove original audio path from LLM view
        safe_metadata.pop("original_audio_path", None)

    return safe_metadata


# Pydantic models for tool inputs
class SearchDocumentsInput(BaseModel):
    """Input schema for search_documents tool."""
    query: str = Field(description="Search query text")
    top_k: int = Field(default=5, description="Number of results to return", ge=1, le=20)
    min_score: Optional[float] = Field(
        default=None,
        description="Minimum similarity score threshold (0.0-1.0). "
                    "Recommended: 0.7 for high precision, 0.5 for balanced, 0.3 for exploratory. "
                    "None returns all top_k results regardless of score.",
        ge=0.0,
        le=1.0
    )


class EnhancedSearchInput(BaseModel):
    """Input schema for enhanced_search tool with passage extraction."""
    query: str = Field(description="Search query text")
    top_k: int = Field(default=5, description="Number of results to return", ge=1, le=20)
    min_score: Optional[float] = Field(
        default=0.5,
        description="Minimum similarity score threshold (0.0-1.0). Default 0.5 for balanced results.",
        ge=0.0,
        le=1.0
    )
    extract_passages: bool = Field(
        default=True,
        description="If true, extract relevant passages instead of returning full documents"
    )
    max_excerpt_length: int = Field(
        default=500,
        description="Maximum length of extracted excerpts",
        ge=50,
        le=2000
    )


class ThinkInput(BaseModel):
    """Input schema for think tool with cited evidence, entity graph, freshness, and maintenance."""
    question: str = Field(description="Question to answer from the private memory index")
    top_k: int = Field(default=8, description="Number of evidence sources to inspect", ge=1, le=20)
    min_score: Optional[float] = Field(
        default=0.5,
        description="Minimum similarity score threshold (0.0-1.0). Default 0.5 for balanced evidence.",
        ge=0.0,
        le=1.0
    )
    freshness_days: int = Field(
        default=90,
        description="Warn when cited sources are older than this many days",
        ge=1,
        le=3650
    )
    include_gaps: bool = Field(
        default=True,
        description="Include explicit missing-evidence and weak-evidence gaps"
    )
    max_excerpt_length: int = Field(
        default=700,
        description="Maximum length of evidence excerpts",
        ge=100,
        le=2000
    )


class AddDocumentInput(BaseModel):
    """Input schema for add_document tool."""
    text: str = Field(description="Document text to add")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Optional metadata as JSON object")
    skip_duplicates: Optional[bool] = Field(
        default=None,
        description="If true, skip adding if identical content exists. Default: use server setting (enabled)"
    )
    extract_key_passages: bool = Field(
        default=True,
        description="If true, extract key passages at storage time for faster search. Recommended: True for optimal performance."
    )


class WriteMemoryInput(BaseModel):
    """Input schema for typed-memory writes."""
    kind: str = Field(
        description="Memory kind: claim, decision, task, artifact, entity, relation, thought_summary, note, policy, preference, or pattern"
    )
    content: str = Field(description="Memory content to store locally")
    workspace: str = Field(default="default", description="Workspace/scope isolation boundary")
    actor: str = Field(default="agent", description="Actor writing the memory")
    memory_key: Optional[str] = Field(default=None, description="Stable key for versioned memories")
    state: str = Field(default="accepted", description="Lifecycle state: scratch, candidate, accepted, or deprecated")
    source_document_id: Optional[int] = Field(default=None, description="Optional source document ID")
    relations: Optional[List[Dict[str, Any]]] = Field(default=None, description="Optional typed relations")
    ttl_days: Optional[int] = Field(default=None, description="Optional retention TTL in days", ge=1, le=36500)
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Optional extra metadata")
    reason: Optional[str] = Field(default=None, description="Reason for the memory write or revision")


class SearchMemoryInput(BaseModel):
    """Input schema for governed typed-memory search."""
    query: Optional[str] = Field(default=None, description="Optional semantic query over typed memory content")
    workspace: str = Field(default="default", description="Workspace/scope to search")
    kind: Optional[str] = Field(default=None, description="Optional memory kind filter")
    memory_key: Optional[str] = Field(default=None, description="Optional exact memory key filter")
    include_states: Optional[List[str]] = Field(
        default=None,
        description="Lifecycle states to include. Defaults to accepted only."
    )
    include_expired: bool = Field(default=False, description="If true, include expired memories")
    top_k: int = Field(default=10, description="Maximum typed-memory records to return", ge=1, le=50)
    min_score: Optional[float] = Field(
        default=0.3,
        description="Minimum semantic score when query is provided",
        ge=0.0,
        le=1.0
    )


class MemoryTimelineInput(BaseModel):
    """Input schema for typed-memory audit timelines."""
    workspace: str = Field(default="default", description="Workspace/scope isolation boundary")
    memory_key: str = Field(description="Stable memory key to audit")


class MemoryGraphInput(BaseModel):
    """Input schema for graph-assisted typed memory."""
    workspace: str = Field(default="default", description="Workspace/scope to graph")
    center_memory_key: Optional[str] = Field(default=None, description="Optional memory key to center the graph on")
    include_states: Optional[List[str]] = Field(
        default=None,
        description="Lifecycle states to include. Defaults to accepted only."
    )
    include_expired: bool = Field(default=False, description="If true, include expired memories")
    limit: int = Field(default=100, description="Maximum typed-memory records to inspect", ge=1, le=500)


class MemoryWorkspaceInfoInput(BaseModel):
    """Input schema for typed-memory workspace summaries."""
    workspace: str = Field(default="default", description="Workspace/scope isolation boundary")


class MemoryActorActivityInput(BaseModel):
    """Input schema for typed-memory actor audit activity."""
    workspace: Optional[str] = Field(default=None, description="Optional workspace/scope filter")
    actor: Optional[str] = Field(default=None, description="Optional actor filter")
    limit: int = Field(default=50, description="Maximum audit events to return", ge=1, le=500)


class GetStatsInput(BaseModel):
    """Input schema for get_stats tool (no parameters needed)."""
    pass


class ListDocumentsInput(BaseModel):
    """Input schema for list_documents tool."""
    page: int = Field(default=1, description="Page number (1-indexed)", ge=1)
    page_size: int = Field(default=10, description="Number of documents per page", ge=1, le=100)
    ascending: bool = Field(default=False, description="If true, oldest first; if false, newest first")


class GetDocumentInput(BaseModel):
    """Input schema for get_document tool."""
    doc_id: int = Field(description="Document ID to retrieve", ge=1)


class AddDocumentFromFileInput(BaseModel):
    """Input schema for add_document_from_file tool."""
    file_path: str = Field(description="Path to file to process and add")
    encoding: str = Field(default="utf-8", description="Text encoding (default: utf-8)")
    additional_metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Additional metadata to merge with file metadata"
    )
    skip_duplicates: Optional[bool] = Field(
        default=None,
        description="If true, skip adding if identical content exists. Default: use server setting (enabled)"
    )


class UploadAndAddDocumentInput(BaseModel):
    """Input schema for upload_and_add_document tool."""
    file_content: str = Field(description="Base64-encoded file content")
    filename: str = Field(description="Original filename")
    encoding: str = Field(default="utf-8", description="Text encoding for text files")
    additional_metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Additional metadata to include"
    )
    skip_duplicates: Optional[bool] = Field(
        default=None,
        description="If true, skip adding if identical content exists. Default: use server setting (enabled)"
    )


class GenerateTopicsInput(BaseModel):
    """Input schema for generate_topics tool."""
    doc_id: int = Field(description="Document ID to generate topics for", ge=1)
    num_topics: int = Field(default=3, description="Maximum number of topics to generate", ge=1, le=5)
    predefined_topics: Optional[List[str]] = Field(
        default=None,
        description="Optional list of allowed topics to choose from"
    )


class UpdateTopicsInput(BaseModel):
    """Input schema for update_topics tool."""
    doc_id: int = Field(description="Document ID to update topics for", ge=1)
    topics: List[str] = Field(description="List of topic labels")
    primary_topic: Optional[str] = Field(default=None, description="Main topic (defaults to first in list)")


class GetTopicsInput(BaseModel):
    """Input schema for get_topics tool."""
    doc_id: int = Field(description="Document ID to get topics for", ge=1)


class ListTopicsInput(BaseModel):
    """Input schema for list_all_topics tool."""
    pass


class SearchWithTopicInput(BaseModel):
    """Input schema for search_with_topic tool."""
    query: str = Field(description="Search query text")
    topic: Optional[str] = Field(default=None, description="Topic to filter by (optional)")
    top_k: int = Field(default=5, description="Number of results to return", ge=1, le=20)
    min_score: Optional[float] = Field(
        default=None,
        description="Minimum similarity score threshold (0.0-1.0).",
        ge=0.0,
        le=1.0
    )


class GetDocumentsByTopicInput(BaseModel):
    """Input schema for get_documents_by_topic tool."""
    topic: str = Field(description="Topic to filter by")
    page: int = Field(default=1, description="Page number (1-indexed)", ge=1)
    page_size: int = Field(default=10, description="Number of documents per page", ge=1, le=100)


class KnowledgeGraphInput(BaseModel):
    """Input schema for knowledge graph endpoint."""
    include_documents: bool = Field(default=True, description="Include document nodes")
    include_topics: bool = Field(default=True, description="Include topic nodes")
    include_entities: bool = Field(default=True, description="Include entity nodes (persons, orgs, etc.)")
    entity_types: Optional[List[str]] = Field(
        default=None,
        description="List of entity types to include: 'person', 'organization', 'location', 'technology'"
    )
    min_connections: int = Field(default=2, description="Minimum connections for entity/topic inclusion", ge=1)
    limit_documents: int = Field(default=200, description="Maximum document nodes", ge=1, le=500)
    limit_entities_per_type: int = Field(default=15, description="Maximum entities per type", ge=1, le=200)
    max_topic_edges_per_doc: int = Field(default=3, description="Maximum topic edges per document", ge=1, le=20)
    max_entity_edges_per_doc: int = Field(default=5, description="Maximum entity edges per document", ge=1, le=50)


class DeanonymizeTextInput(BaseModel):
    """Input schema for deanonymize_text MCP tool (localhost only)."""
    text: str = Field(description="Text containing PII tokens to de-anonymize")
    session_id: str = Field(description="PII session ID from the original search response")


class MCPVectorSearchHTTPServer:
    """MCP server with HTTP transport for network accessibility."""

    def __init__(
        self,
        db_path: str = "./vectordb",
        model_name: Optional[str] = None,
        host: str = "0.0.0.0",
        port: int = 8085,
        public: bool = False,
        api_key: Optional[str] = None
    ):
        """Initialize the HTTP MCP server.

        Args:
            db_path: Path to vector database directory
            model_name: Embedding model name (None for auto-selection)
            host: Host to bind to (0.0.0.0 for all interfaces)
            port: Port to listen on
            public: If True, enable public internet access with authentication
            api_key: API key for authentication (auto-generated if public=True and not provided)
        """
        self.db_path = db_path
        # Compute data_dir as parent of db_path (for uploads, redacted files, etc.)
        # e.g., if db_path is "/app/data/vectordb", data_dir is "/app/data"
        self.data_dir = os.path.dirname(os.path.abspath(db_path))
        self.model_name = model_name
        self.host = host
        self.port = port
        self.public = public

        # Handle API key for public mode
        if self.public:
            resolved_api_key = resolve_remote_api_key(api_key)
            if resolved_api_key:
                self.api_key = resolved_api_key
            else:
                # Generate secure API key
                self.api_key = secrets.token_urlsafe(32)
                print(f"\n🔐 Generated API Key: {self.api_key}")
                print("⚠️  Save this key! It won't be shown again.\n")
        else:
            self.api_key = None

        # Will be initialized in async context
        self.embedding_model = None  # TxtaiEmbeddingWrapper (set during initialize)
        self.vector_store = None  # VectorStore or TxtaiAdapter (determined at runtime)
        self.topic_labeler: Optional[TopicLabeler] = None
        self.passage_extractor: Optional[PassageExtractor] = None
        self.reranker = None  # Cross-encoder reranker for improved search quality
        self.async_extractor: Optional[AsyncExtractor] = None  # Background extraction
        self.upload_handler = FileUploadHandler()
        self.auto_label_on_upload = False  # Disabled - extraction runs in background

        # PII protection - initialized lazily, always on for search results
        self.pii_protector: Optional[PIIProtector] = None

        # Media processors (audio/image) - initialized in initialize()
        self.audio_processor: Optional[AudioProcessor] = None
        self.image_processor: Optional[ImageProcessor] = None

        # Track current client IP for conditional tool visibility
        # This is set per-request in handle_sse/handle_messages
        self._current_client_ip: Optional[str] = None

        # Create MCP server
        self.server = Server("mcp-vector-store")

        # Create SSE transport for MCP protocol
        self.sse_transport = SseServerTransport("/messages")

        # Register tool handlers
        self._register_handlers()

    def _register_handlers(self):
        """Register MCP tool handlers."""

        @self.server.list_tools()
        async def list_tools() -> List[Tool]:
            """List available tools. Conditionally includes deanonymize_text for localhost clients."""
            tools = [
                Tool(
                    name="search_documents",
                    description="Search the vector database for documents similar to a query. "
                               "Returns relevant documents with similarity scores. "
                               "Supports optional min_score threshold to filter low-quality matches.",
                    inputSchema=SearchDocumentsInput.model_json_schema()
                ),
                Tool(
                    name="enhanced_search",
                    description="Advanced search with intelligent passage extraction. "
                               "Returns relevant excerpts instead of full documents, "
                               "with configurable score threshold and optional query expansion. "
                               "Best for getting focused, relevant content from large documents.",
                    inputSchema=EnhancedSearchInput.model_json_schema()
                ),
                Tool(
                    name="think",
                    description="Answer a question with PII-safe cited evidence, cited-answer graph links, "
                               "safe entity graph links, source coverage, freshness warnings, contradictions, explicit gaps, "
                               "and citation-maintenance actions. "
                               "Returns structured reasoning context for AI coding tools.",
                    inputSchema=ThinkInput.model_json_schema()
                ),
                Tool(
                    name="write_memory",
                    description="Write a typed, versioned memory record with append-only audit metadata. "
                               "Use for decisions, claims, tasks, artifacts, entities, relations, and summaries.",
                    inputSchema=WriteMemoryInput.model_json_schema()
                ),
                Tool(
                    name="search_memory",
                    description="Search typed memory with governed defaults. "
                               "Returns accepted, non-expired records by default with redacted content previews.",
                    inputSchema=SearchMemoryInput.model_json_schema()
                ),
                Tool(
                    name="memory_timeline",
                    description="Return an audit timeline for one typed-memory key, including versions and events.",
                    inputSchema=MemoryTimelineInput.model_json_schema()
                ),
                Tool(
                    name="memory_graph",
                    description="Return a graph of typed-memory records, declared relations, and source-document links. "
                               "Defaults to accepted, non-expired memories with redacted labels/previews.",
                    inputSchema=MemoryGraphInput.model_json_schema()
                ),
                Tool(
                    name="memory_workspace_info",
                    description="Return governed workspace-level typed-memory counts by kind, state, actor, "
                               "retention status, and audit window without raw memory content.",
                    inputSchema=MemoryWorkspaceInfoInput.model_json_schema()
                ),
                Tool(
                    name="memory_actor_activity",
                    description="Return bounded append-only typed-memory audit activity for an actor or workspace "
                               "without raw memory content.",
                    inputSchema=MemoryActorActivityInput.model_json_schema()
                ),
                Tool(
                    name="add_document",
                    description="Add a new document to the vector database. "
                               "The document will be embedded and stored for future retrieval.",
                    inputSchema=AddDocumentInput.model_json_schema()
                ),
                Tool(
                    name="get_stats",
                    description="Get statistics about the vector database, including "
                               "total document count and embedding dimensions.",
                    inputSchema=GetStatsInput.model_json_schema()
                ),
                Tool(
                    name="list_documents",
                    description="Retrieve documents in chronological order with pagination. "
                               "Returns full document text and metadata. Useful for browsing all documents.",
                    inputSchema=ListDocumentsInput.model_json_schema()
                ),
                Tool(
                    name="get_document",
                    description="Retrieve a specific document by its ID. "
                               "Returns the full document text and metadata.",
                    inputSchema=GetDocumentInput.model_json_schema()
                ),
                Tool(
                    name="add_document_from_file",
                    description="Add a document by reading and processing a file. "
                               "Supports text files (.txt, .md, .py, etc.), JSON, CSV, PDF, "
                               "audio files (.wav, .mp3, .flac, .ogg, .m4a), and "
                               "image files (.jpg, .png, .gif, .webp, .bmp). "
                               "Audio files are transcribed and images are captioned automatically.",
                    inputSchema=AddDocumentFromFileInput.model_json_schema()
                ),
                Tool(
                    name="upload_and_add_document",
                    description="Upload a file from a remote device and add it to the vector store. "
                               "File content should be base64-encoded. "
                               "Perfect for adding files from devices that don't share the server's filesystem.",
                    inputSchema=UploadAndAddDocumentInput.model_json_schema()
                ),
                Tool(
                    name="generate_topics",
                    description="Generate topic labels for a document using keyword matching and embedding similarity. "
                               "Topics are stored with the document for filtering and organization.",
                    inputSchema=GenerateTopicsInput.model_json_schema()
                ),
                Tool(
                    name="update_topics",
                    description="Manually update topic labels for a document. "
                               "Use this to override auto-generated topics.",
                    inputSchema=UpdateTopicsInput.model_json_schema()
                ),
                Tool(
                    name="get_topics",
                    description="Get the topic labels for a specific document.",
                    inputSchema=GetTopicsInput.model_json_schema()
                ),
                Tool(
                    name="list_all_topics",
                    description="List all unique topics in the vector store with document counts.",
                    inputSchema=ListTopicsInput.model_json_schema()
                ),
                Tool(
                    name="search_with_topic",
                    description="Search documents with optional topic filtering. "
                               "Combines semantic search with topic-based filtering.",
                    inputSchema=SearchWithTopicInput.model_json_schema()
                ),
                Tool(
                    name="get_documents_by_topic",
                    description="Get all documents that belong to a specific topic.",
                    inputSchema=GetDocumentsByTopicInput.model_json_schema()
                )
            ]

            # Only expose deanonymize_text to localhost clients (on-device apps)
            if self._is_localhost(self._current_client_ip):
                tools.append(Tool(
                    name="deanonymize_text",
                    description="De-anonymize text containing PII tokens. Restores original PII values "
                               "from a previous search response. Only available to on-device clients.",
                    inputSchema=DeanonymizeTextInput.model_json_schema()
                ))

            return tools

        @self.server.call_tool()
        async def call_tool(name: str, arguments: Any) -> List[TextContent]:
            """Handle tool calls."""
            try:
                if name == "search_documents":
                    return await self._search_documents(arguments)
                elif name == "enhanced_search":
                    return await self._enhanced_search(arguments)
                elif name == "think":
                    return await self._think(arguments)
                elif name == "write_memory":
                    return await self._write_memory(arguments)
                elif name == "search_memory":
                    return await self._search_memory(arguments)
                elif name == "memory_timeline":
                    return await self._memory_timeline(arguments)
                elif name == "memory_graph":
                    return await self._memory_graph(arguments)
                elif name == "memory_workspace_info":
                    return await self._memory_workspace_info(arguments)
                elif name == "memory_actor_activity":
                    return await self._memory_actor_activity(arguments)
                elif name == "add_document":
                    return await self._add_document(arguments)
                elif name == "get_stats":
                    return await self._get_stats(arguments)
                elif name == "list_documents":
                    return await self._list_documents(arguments)
                elif name == "get_document":
                    return await self._get_document(arguments)
                elif name == "add_document_from_file":
                    return await self._add_document_from_file(arguments)
                elif name == "upload_and_add_document":
                    return await self._upload_and_add_document(arguments)
                elif name == "generate_topics":
                    return await self._generate_topics(arguments)
                elif name == "update_topics":
                    return await self._update_topics(arguments)
                elif name == "get_topics":
                    return await self._get_topics(arguments)
                elif name == "list_all_topics":
                    return await self._list_all_topics(arguments)
                elif name == "search_with_topic":
                    return await self._search_with_topic(arguments)
                elif name == "get_documents_by_topic":
                    return await self._get_documents_by_topic(arguments)
                elif name == "deanonymize_text":
                    return await self._deanonymize_text(arguments)
                else:
                    return [TextContent(
                        type="text",
                        text=f"Error: Unknown tool '{name}'"
                    )]
            except Exception as e:
                return [TextContent(
                    type="text",
                    text=f"Error executing tool '{name}': {str(e)}"
                )]

    async def _search_documents(self, arguments: Dict[str, Any]) -> List[TextContent]:
        """Handle search_documents tool call."""
        # Validate input
        input_data = SearchDocumentsInput(**arguments)

        # Perform search with optional min_score threshold
        results = self.vector_store.search(
            query=input_data.query,
            embedding_model=self.embedding_model,
            top_k=input_data.top_k,
            min_score=input_data.min_score
        )

        # Format results
        if not results:
            response = {
                "query": input_data.query,
                "min_score_threshold": input_data.min_score,
                "results": [],
                "message": "No documents found matching criteria"
            }
        else:
            # MCP tools are used by external LLMs - apply LLM context for image PII safety
            formatted_results = [
                {
                    "id": result.id,
                    "text": result.text,
                    "score": result.score,
                    "metadata": transform_metadata_for_context(result.metadata, context="llm")
                }
                for result in results
            ]

            # Apply text PII protection (always on)
            pii_session_id = None
            if self.pii_protector:
                formatted_results, pii_session_id, _ = self.pii_protector.anonymize_search_results(
                    formatted_results,
                    text_fields=["text"]
                )

            response = {
                "query": input_data.query,
                "min_score_threshold": input_data.min_score,
                "results": formatted_results
            }

            # SECURITY: Do NOT include pii_session_id in MCP tool responses.
            # MCP results go to external LLMs — exposing session IDs would allow
            # the LLM (or an attacker via prompt injection) to call de-anonymize.
            # Session IDs are instead returned via the REST search API for on-device
            # clients that need to de-anonymize for display purposes.
            # The session_id is stored server-side and accessible via REST /api/pii/session/*.

        return [TextContent(
            type="text",
            text=json.dumps(response, indent=2)
        )]

    async def _enhanced_search(self, arguments: Dict[str, Any]) -> List[TextContent]:
        """Handle enhanced_search tool call with passage extraction and reranking."""
        from .model_manager import ModelType

        # Validate input
        input_data = EnhancedSearchInput(**arguments)

        # Lazy-load reranker if available
        reranker = self._ensure_reranker()
        if reranker:
            self.model_manager.ensure_loaded(ModelType.RERANKER)

        # Perform enhanced search with reranking if available
        reranker_available = reranker and reranker.is_available()
        results = self.vector_store.enhanced_search(
            query=input_data.query,
            embedding_model=self.embedding_model,
            top_k=input_data.top_k,
            min_score=input_data.min_score,
            extract_passages=input_data.extract_passages,
            passage_extractor=self.passage_extractor,
            max_excerpt_length=input_data.max_excerpt_length,
            reranker=reranker if reranker_available else None,
            rerank_top_k=input_data.top_k * 3 if reranker_available else None
        )

        # Format results
        if not results:
            response = {
                "query": input_data.query,
                "min_score_threshold": input_data.min_score,
                "passage_extraction": input_data.extract_passages,
                "results": [],
                "message": "No documents found matching criteria"
            }
        else:
            # MCP tools are used by external LLMs - apply LLM context for image PII safety
            formatted_results = [
                {
                    "id": result.id,
                    "excerpt": result.excerpt,
                    "score": result.score,
                    "excerpt_method": result.excerpt_method,
                    "topics": result.topics,
                    "primary_topic": result.primary_topic,
                    "full_text_length": len(result.text),
                    "metadata": transform_metadata_for_context(result.metadata, context="llm")
                }
                for result in results
            ]

            # Apply text PII protection (always on)
            pii_session_id = None
            if self.pii_protector:
                formatted_results, pii_session_id, _ = self.pii_protector.anonymize_search_results(
                    formatted_results,
                    text_fields=["excerpt"]  # Only anonymize excerpts, not full text
                )

            response = {
                "query": input_data.query,
                "min_score_threshold": input_data.min_score,
                "passage_extraction": input_data.extract_passages,
                "results": formatted_results
            }

            # SECURITY: Do NOT include pii_session_id in MCP tool responses.
            # See _search_documents() for rationale.

        return [TextContent(
            type="text",
            text=json.dumps(response, indent=2)
        )]

    async def _think(self, arguments: Dict[str, Any]) -> List[TextContent]:
        """Handle think tool call with PII-safe cited evidence shaping."""
        input_data = ThinkInput(**arguments)
        response = self._build_think_response(input_data)
        return [TextContent(
            type="text",
            text=json.dumps(response, indent=2)
        )]

    def _build_think_response(self, input_data: ThinkInput) -> Dict[str, Any]:
        """Retrieve redacted evidence and convert it into a think response."""
        formatted_results = self._get_think_evidence(input_data)
        return build_think_response(
            question=input_data.question,
            results=formatted_results,
            top_k=input_data.top_k,
            freshness_days=input_data.freshness_days,
            include_gaps=input_data.include_gaps,
        )

    def _get_think_evidence(self, input_data: ThinkInput) -> List[Dict[str, Any]]:
        """Run existing retrieval with LLM-safe metadata and text redaction."""
        if not input_data.question.strip():
            return []

        from .model_manager import ModelType

        reranker = self._ensure_reranker()
        if reranker:
            self.model_manager.ensure_loaded(ModelType.RERANKER)
        reranker_available = reranker and reranker.is_available()

        if hasattr(self.vector_store, "enhanced_search"):
            results = self.vector_store.enhanced_search(
                query=input_data.question,
                embedding_model=self.embedding_model,
                top_k=input_data.top_k,
                min_score=input_data.min_score,
                extract_passages=True,
                passage_extractor=self.passage_extractor,
                max_excerpt_length=input_data.max_excerpt_length,
                reranker=reranker if reranker_available else None,
                rerank_top_k=input_data.top_k * 3 if reranker_available else None
            )
            formatted_results = [
                {
                    "id": result.id,
                    "excerpt": result.excerpt,
                    "score": result.score,
                    "excerpt_method": result.excerpt_method,
                    "topics": result.topics,
                    "primary_topic": result.primary_topic,
                    "metadata": transform_metadata_for_context(result.metadata, context="llm")
                }
                for result in results
            ]
            text_fields = ["excerpt"]
        else:
            results = self.vector_store.search(
                query=input_data.question,
                embedding_model=self.embedding_model,
                top_k=input_data.top_k,
                min_score=input_data.min_score
            )
            formatted_results = [
                {
                    "id": result.id,
                    "text": result.text,
                    "score": result.score,
                    "topics": result.topics,
                    "primary_topic": result.primary_topic,
                    "metadata": transform_metadata_for_context(result.metadata, context="llm")
                }
                for result in results
            ]
            text_fields = ["text"]

        if self.pii_protector and formatted_results:
            formatted_results, _, _ = self.pii_protector.anonymize_search_results(
                formatted_results,
                text_fields=text_fields
            )

        return formatted_results

    async def _write_memory(self, arguments: Dict[str, Any]) -> List[TextContent]:
        """Handle typed-memory writes from MCP clients."""
        input_data = WriteMemoryInput(**arguments)
        response = self._write_memory_payload(input_data)
        return [TextContent(
            type="text",
            text=json.dumps(response, indent=2)
        )]

    async def _search_memory(self, arguments: Dict[str, Any]) -> List[TextContent]:
        """Handle governed typed-memory search from MCP clients."""
        input_data = SearchMemoryInput(**arguments)
        response = self._search_memory_payload(input_data)
        return [TextContent(
            type="text",
            text=json.dumps(response, indent=2)
        )]

    async def _memory_timeline(self, arguments: Dict[str, Any]) -> List[TextContent]:
        """Handle typed-memory audit timeline lookup from MCP clients."""
        input_data = MemoryTimelineInput(**arguments)
        response = self._memory_timeline_payload(input_data)
        return [TextContent(
            type="text",
            text=json.dumps(response, indent=2)
        )]

    async def _memory_graph(self, arguments: Dict[str, Any]) -> List[TextContent]:
        """Handle graph-assisted typed-memory lookup from MCP clients."""
        input_data = MemoryGraphInput(**arguments)
        response = self._memory_graph_payload(input_data)
        return [TextContent(
            type="text",
            text=json.dumps(response, indent=2)
        )]

    async def _memory_workspace_info(self, arguments: Dict[str, Any]) -> List[TextContent]:
        """Handle typed-memory workspace summaries from MCP clients."""
        input_data = MemoryWorkspaceInfoInput(**arguments)
        response = self._memory_workspace_info_payload(input_data)
        return [TextContent(
            type="text",
            text=json.dumps(response, indent=2)
        )]

    async def _memory_actor_activity(self, arguments: Dict[str, Any]) -> List[TextContent]:
        """Handle typed-memory actor activity from MCP clients."""
        input_data = MemoryActorActivityInput(**arguments)
        response = self._memory_actor_activity_payload(input_data)
        return [TextContent(
            type="text",
            text=json.dumps(response, indent=2)
        )]

    def _write_memory_payload(self, input_data: WriteMemoryInput) -> Dict[str, Any]:
        """Build and store a typed-memory record in the existing local vector store."""
        existing_records = self._get_memory_candidate_documents(ascending=True)
        record = build_memory_record(
            kind=input_data.kind,
            content=input_data.content,
            workspace=input_data.workspace,
            actor=input_data.actor,
            memory_key=input_data.memory_key,
            state=input_data.state,
            source_document_id=input_data.source_document_id,
            relations=input_data.relations,
            ttl_days=input_data.ttl_days,
            metadata=input_data.metadata,
            reason=input_data.reason,
            existing_records=existing_records,
        )

        result = self.vector_store.add_document(
            text=record["text"],
            embedding_model=self.embedding_model,
            metadata=record["metadata"],
            skip_duplicates=True,
            topic_labeler=None,
            extract_key_passages=False,
            passage_extractor=None,
            extract_key_entities=False,
            verbose=False
        )

        memory = self._public_memory_summary(record["metadata"]["memory"])
        event = self._public_audit_event(record["metadata"]["memory_events"][0])
        if isinstance(result, AddDocumentResult) and result.is_duplicate:
            return self._redact_memory_write_response({
                "success": False,
                "is_duplicate": True,
                "existing_document_id": result.existing_doc_id,
                "content_hash": result.content_hash,
                "memory": memory,
                "audit_event": event,
                "message": "Typed memory already exists"
            })

        doc_id = result.doc_id if isinstance(result, AddDocumentResult) else result
        return self._redact_memory_write_response({
            "success": True,
            "document_id": doc_id,
            "memory": memory,
            "audit_event": event,
            "message": f"Typed memory stored with key {memory['memory_key']} version {memory['version']}"
        })

    def _search_memory_payload(self, input_data: SearchMemoryInput) -> Dict[str, Any]:
        """Search typed memory with accepted/non-expired defaults."""
        if input_data.query and input_data.query.strip():
            overfetch = min(max(input_data.top_k * 5, input_data.top_k), 100)
            documents = self.vector_store.search(
                query=input_data.query,
                embedding_model=self.embedding_model,
                top_k=overfetch,
                min_score=input_data.min_score
            )
        else:
            documents = self._get_memory_candidate_documents(ascending=False)

        records = filter_memory_records(
            documents,
            workspace=input_data.workspace,
            kind=input_data.kind,
            memory_key=input_data.memory_key,
            include_states=input_data.include_states,
            include_expired=input_data.include_expired,
            limit=input_data.top_k,
        )
        public_records = self._public_memory_records(records)

        public_records = self._redact_public_dicts(
            public_records,
            ["workspace", "memory_key", "content_preview"]
        )

        return {
            "query": input_data.query,
            "workspace": input_data.workspace,
            "kind": input_data.kind,
            "memory_key": input_data.memory_key,
            "governance": {
                "include_states": input_data.include_states or ["accepted"],
                "include_expired": input_data.include_expired,
                "default_policy": "accepted_non_expired_only",
            },
            "results": public_records,
        }

    def _memory_timeline_payload(self, input_data: MemoryTimelineInput) -> Dict[str, Any]:
        """Return an audit timeline for a typed-memory key."""
        documents = self._get_memory_candidate_documents(ascending=True)
        timeline = build_memory_timeline(
            documents,
            workspace=input_data.workspace,
            memory_key=input_data.memory_key,
        )

        timeline["versions"] = self._redact_public_dicts(
            timeline.get("versions", []),
            ["workspace", "memory_key", "content_preview"]
        )
        timeline["events"] = self._redact_public_dicts(
            timeline.get("events", []),
            ["actor", "workspace", "memory_key", "reason"]
        )

        timeline["governance"] = {
            "include_states": sorted(MEMORY_STATES),
            "include_expired": True,
            "content_included": False,
        }
        return timeline

    def _memory_graph_payload(self, input_data: MemoryGraphInput) -> Dict[str, Any]:
        """Return graph-assisted typed memory with redacted labels/previews."""
        documents = self._get_memory_candidate_documents(ascending=True)
        graph = build_memory_graph(
            documents,
            workspace=input_data.workspace,
            center_memory_key=input_data.center_memory_key,
            include_states=input_data.include_states,
            include_expired=input_data.include_expired,
            limit=input_data.limit,
        )

        graph["nodes"] = self._redact_public_dicts(
            graph.get("nodes", []),
            ["workspace", "memory_key", "content_preview", "label"]
        )
        graph["edges"] = self._redact_graph_edges(graph.get("edges", []))
        return graph

    def _memory_workspace_info_payload(self, input_data: MemoryWorkspaceInfoInput) -> Dict[str, Any]:
        """Return workspace governance summary with no raw memory content."""
        documents = self._get_memory_candidate_documents(ascending=True)
        info = build_workspace_info(
            documents,
            workspace=input_data.workspace,
        )
        info = dict(info)
        if info.get("workspace"):
            info["workspace"] = self._redact_public_dicts(
                [{"workspace": info["workspace"]}],
                ["workspace"]
            )[0]["workspace"]
        info["actor_counts"] = self._redact_count_keys(info.get("actor_counts", {}))
        return info

    def _memory_actor_activity_payload(self, input_data: MemoryActorActivityInput) -> Dict[str, Any]:
        """Return bounded audit activity with redacted identifiers/reasons."""
        documents = self._get_memory_candidate_documents(ascending=True)
        activity = build_actor_activity(
            documents,
            workspace=input_data.workspace,
            actor=input_data.actor,
            limit=input_data.limit,
        )
        activity["events"] = self._redact_public_dicts(
            activity.get("events", []),
            ["actor", "workspace", "memory_key", "reason"]
        )
        header_fields = []
        if activity.get("workspace") is not None:
            header_fields.append("workspace")
        if activity.get("actor") is not None:
            header_fields.append("actor")
        if header_fields:
            header = self._redact_public_dicts(
                [{field: activity.get(field) for field in header_fields}],
                header_fields
            )[0]
            activity.update(header)
        return activity

    def _get_memory_candidate_documents(self, ascending: bool = False) -> List[Any]:
        """Load candidate documents for typed-memory filtering without new storage."""
        if hasattr(self.vector_store, "get_all_documents"):
            try:
                return self.vector_store.get_all_documents(
                    ascending=ascending,
                    exclude_chunks=True
                )
            except TypeError:
                return self.vector_store.get_all_documents(ascending=ascending)

        result = self.vector_store.get_documents_chronological(
            page=1,
            page_size=1000,
            ascending=ascending
        )
        return result.documents

    def _public_memory_records(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Trim internal metadata from memory search output for LLM-facing tools."""
        public_records = []
        for record in records:
            public_records.append({
                "doc_id": record.get("doc_id"),
                "kind": record.get("kind"),
                "workspace": record.get("workspace"),
                "memory_key": record.get("memory_key"),
                "state": record.get("state"),
                "version": record.get("version"),
                "value_hash": record.get("value_hash"),
                "created_at": record.get("created_at"),
                "expires_at": record.get("expires_at"),
                "expired": record.get("expired"),
                "score": record.get("score"),
                "content_preview": record.get("content_preview"),
            })
        return public_records

    def _public_memory_summary(self, memory: Dict[str, Any]) -> Dict[str, Any]:
        """Return memory metadata without raw content or relation payloads."""
        return {
            "kind": memory.get("kind"),
            "workspace": memory.get("workspace"),
            "memory_key": memory.get("memory_key"),
            "state": memory.get("state"),
            "version": memory.get("version"),
            "value_hash": memory.get("value_hash"),
            "created_at": memory.get("created_at"),
            "expires_at": memory.get("expires_at"),
            "source_document_id": memory.get("source_document_id"),
            "relation_count": len(memory.get("relations") or []),
        }

    def _public_audit_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Return audit event fields that are useful without exposing content."""
        return {
            "event_id": event.get("event_id"),
            "event_type": event.get("event_type"),
            "timestamp": event.get("timestamp"),
            "actor": event.get("actor"),
            "workspace": event.get("workspace"),
            "memory_key": event.get("memory_key"),
            "version": event.get("version"),
            "state": event.get("state"),
            "value_hash": event.get("value_hash"),
            "reason": event.get("reason"),
        }

    def _redact_memory_write_response(self, response: Dict[str, Any]) -> Dict[str, Any]:
        """Apply text PII protection to LLM-facing memory write metadata."""
        response = dict(response)
        if response.get("memory"):
            response["memory"] = self._redact_public_dicts(
                [response["memory"]],
                ["workspace", "memory_key"]
            )[0]
        if response.get("audit_event"):
            response["audit_event"] = self._redact_public_dicts(
                [response["audit_event"]],
                ["actor", "workspace", "memory_key", "reason"]
            )[0]
        if response.get("message"):
            response["message"] = self._redact_public_dicts(
                [{"message": response["message"]}],
                ["message"]
            )[0]["message"]
        return response

    def _redact_public_dicts(self, rows: List[Dict[str, Any]], text_fields: List[str]) -> List[Dict[str, Any]]:
        """Redact selected text fields without exposing PII session IDs."""
        if not self.pii_protector or not rows:
            return rows
        redacted_rows, _, _ = self.pii_protector.anonymize_search_results(
            rows,
            text_fields=text_fields
        )
        return redacted_rows

    def _redact_count_keys(self, counts: Dict[str, int]) -> Dict[str, int]:
        """Redact PII in dictionary keys while preserving aggregate counts."""
        if not self.pii_protector or not counts:
            return counts
        rows = [{"key": key, "count": count} for key, count in counts.items()]
        redacted_rows = self._redact_public_dicts(rows, ["key"])
        redacted_counts: Dict[str, int] = {}
        for row in redacted_rows:
            key = row.get("key")
            count = int(row.get("count") or 0)
            redacted_counts[key] = redacted_counts.get(key, 0) + count
        return dict(sorted(redacted_counts.items()))

    def _redact_graph_edges(self, edges: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Redact edge labels and shallow metadata text fields."""
        redacted_edges = self._redact_public_dicts(edges, ["label"])
        if not self.pii_protector:
            return redacted_edges

        sanitized_edges = []
        for edge in redacted_edges:
            edge = dict(edge)
            metadata = edge.get("metadata")
            if isinstance(metadata, dict):
                redacted_metadata = self._redact_public_dicts(
                    [metadata],
                    ["label", "description", "target_key", "target_memory_key", "memory_key", "target_label"]
                )[0]
                edge["metadata"] = redacted_metadata
            sanitized_edges.append(edge)
        return sanitized_edges

    async def _deanonymize_text(self, arguments: Dict[str, Any]) -> List[TextContent]:
        """Handle deanonymize_text tool call with authorization check.

        SECURITY: This tool is restricted to localhost/on-device clients only.
        Note: _current_client_ip may be stale due to concurrent connections (V-03),
        but the tool is also gated at the list_tools level. The REST endpoint
        (/api/pii/deanonymize) uses per-request _get_client_ip_secure() for
        a more reliable check.
        """
        # Validate input
        input_data = DeanonymizeTextInput(**arguments)

        # Check if client is localhost (tool should only be visible to localhost,
        # but double-check here for security)
        if not self._is_localhost(self._current_client_ip):
            return [TextContent(
                type="text",
                text=json.dumps({
                    "success": False,
                    "error": "Access denied: deanonymize_text is only available to on-device clients"
                }, indent=2)
            )]

        # Check if PII protector is available
        if not self.pii_protector:
            return [TextContent(
                type="text",
                text=json.dumps({
                    "success": False,
                    "error": "PII protection not available on this server"
                }, indent=2)
            )]

        # De-anonymize (no auth required - access controlled by localhost check)
        result = self.pii_protector.deanonymize(
            text=input_data.text,
            session_id=input_data.session_id,
            require_auth=False  # Access controlled by localhost check instead
        )

        # Check for session errors
        if "SESSION_NOT_FOUND" in result.tokens_not_found:
            return [TextContent(
                type="text",
                text=json.dumps({
                    "success": False,
                    "error": "Session not found: The PII session has expired or does not exist"
                }, indent=2)
            )]

        if "SESSION_EXPIRED" in result.tokens_not_found:
            return [TextContent(
                type="text",
                text=json.dumps({
                    "success": False,
                    "error": "Session expired: The PII session has timed out"
                }, indent=2)
            )]

        response = {
            "success": True,
            "deanonymized_text": result.deanonymized_text,
            "session_id": result.session_id,
            "tokens_replaced": result.tokens_replaced,
            "tokens_not_found": result.tokens_not_found
        }

        return [TextContent(
            type="text",
            text=json.dumps(response, indent=2)
        )]

    async def _add_document(self, arguments: Dict[str, Any]) -> List[TextContent]:
        """Handle add_document tool call."""
        # Validate input
        input_data = AddDocumentInput(**arguments)

        # Add document WITHOUT synchronous extraction (fast) - extraction happens async in background
        print(f"\n📄 Adding document ({len(input_data.text)} chars)...")
        result = self.vector_store.add_document(
            text=input_data.text,
            embedding_model=self.embedding_model,
            metadata=input_data.metadata,
            skip_duplicates=input_data.skip_duplicates,
            topic_labeler=None,  # Skip sync extraction
            extract_key_passages=False,  # Skip sync extraction
            passage_extractor=None,
            extract_key_entities=False,  # Skip sync extraction
            verbose=True
        )

        # Handle duplicate detection result
        if isinstance(result, AddDocumentResult):
            if result.is_duplicate:
                response = {
                    "success": False,
                    "is_duplicate": True,
                    "existing_document_id": result.existing_doc_id,
                    "content_hash": result.content_hash,
                    "message": f"Document already exists with ID {result.existing_doc_id}"
                }
            else:
                # Queue async extraction for background processing
                if self.async_extractor and self.passage_extractor and self.passage_extractor.is_available():
                    metadata = input_data.metadata or {}
                    self.async_extractor.queue_extraction(ExtractionTask(
                        doc_id=result.doc_id,
                        text=input_data.text,
                        extract_key_passages=True,
                        extract_key_entities=True,
                        extract_structured_metadata=True,
                        extract_filters=True,
                        source=metadata.get('source'),
                        filename=metadata.get('filename')
                    ))
                response = {
                    "success": True,
                    "document_id": result.doc_id,
                    "content_hash": result.content_hash,
                    "message": f"Document added successfully with ID {result.doc_id}"
                }
        else:
            # Backward compatibility: result is just the doc_id
            # Queue async extraction for background processing
            if self.async_extractor and self.passage_extractor and self.passage_extractor.is_available():
                metadata = input_data.metadata or {}
                self.async_extractor.queue_extraction(ExtractionTask(
                    doc_id=result,
                    text=input_data.text,
                    extract_key_passages=True,
                    extract_key_entities=True,
                    extract_structured_metadata=True,
                    extract_filters=True,
                    source=metadata.get('source'),
                    filename=metadata.get('filename')
                ))
            response = {
                "success": True,
                "document_id": result,
                "message": f"Document added successfully with ID {result}"
            }

        return [TextContent(
            type="text",
            text=json.dumps(response, indent=2)
        )]

    async def _get_stats(self, arguments: Dict[str, Any]) -> List[TextContent]:
        """Handle get_stats tool call."""
        stats = self.vector_store.get_stats()

        return [TextContent(
            type="text",
            text=json.dumps(stats, indent=2)
        )]

    async def _list_documents(self, arguments: Dict[str, Any]) -> List[TextContent]:
        """Handle list_documents tool call."""
        # Validate input
        input_data = ListDocumentsInput(**arguments)

        # Get paginated documents
        result = self.vector_store.get_documents_chronological(
            page=input_data.page,
            page_size=input_data.page_size,
            ascending=input_data.ascending
        )

        # Format response
        from datetime import datetime
        # RT-02: Build formatted list first, then anonymize before returning to LLM
        formatted_docs = [
            {
                "id": doc.id,
                "text": doc.text[:500] + "..." if len(doc.text) > 500 else doc.text,
                "metadata": transform_metadata_for_context(doc.metadata, context="llm"),
                "created_at": doc.created_datetime.isoformat()
            }
            for doc in result.documents
        ]

        # Apply PII anonymization (same pattern as search_documents)
        if self.pii_protector:
            formatted_docs, _, _ = self.pii_protector.anonymize_search_results(
                formatted_docs,
                text_fields=["text"]
            )

        response = {
            "page": result.page,
            "page_size": result.page_size,
            "total": result.total,
            "total_pages": result.total_pages,
            "has_next": result.has_next,
            "has_prev": result.has_prev,
            "documents": formatted_docs
        }

        return [TextContent(
            type="text",
            text=json.dumps(response, indent=2)
        )]

    async def _get_document(self, arguments: Dict[str, Any]) -> List[TextContent]:
        """Handle get_document tool call."""
        from datetime import datetime

        # Validate input
        input_data = GetDocumentInput(**arguments)

        # Get document
        doc = self.vector_store.get_document(input_data.doc_id)

        if doc is None:
            response = {
                "success": False,
                "message": f"Document with ID {input_data.doc_id} not found"
            }
        else:
            # RT-02: Anonymize document text before returning to LLM
            doc_text = doc.text
            if self.pii_protector:
                anon_result = self.pii_protector.anonymize(doc_text)
                doc_text = anon_result.anonymized_text

            response = {
                "success": True,
                "document": {
                    "id": doc.id,
                    "text": doc_text,
                    "metadata": transform_metadata_for_context(doc.metadata, context="llm"),
                    "created_at": datetime.fromtimestamp(doc.created_at / 1000.0).isoformat()
                }
            }

        return [TextContent(
            type="text",
            text=json.dumps(response, indent=2)
        )]

    async def _add_document_from_file(self, arguments: Dict[str, Any]) -> List[TextContent]:
        """Handle add_document_from_file tool call."""
        # AddDocumentResult imported at top level from txtai_adapter

        # Validate input
        input_data = AddDocumentFromFileInput(**arguments)

        # SECURITY: Validate file path to prevent path traversal attacks.
        # Only allow files within the data directory to prevent reading sensitive
        # files like llm-config.json, /etc/passwd, etc.
        allowed_dirs = [
            os.path.abspath(self.data_dir),  # data/ directory
            os.path.abspath(os.path.join(self.data_dir, "..")),  # project root (for imports)
        ]
        real_path = os.path.realpath(input_data.file_path)  # Resolve symlinks
        path_allowed = any(
            real_path.startswith(allowed_dir + os.sep) or real_path == allowed_dir
            for allowed_dir in allowed_dirs
        )
        # Also block access to sensitive files even within allowed directories
        sensitive_patterns = ["llm-config.json", "connectors.json", ".env", "chromium-profile"]
        path_is_sensitive = any(pattern in real_path for pattern in sensitive_patterns)

        if not path_allowed or path_is_sensitive:
            return [TextContent(
                type="text",
                text=json.dumps({
                    "success": False,
                    "error": f"Access denied: file path is outside allowed directories or targets a sensitive file"
                }, indent=2)
            )]

        try:
            # Check for async audio processing BEFORE calling FileProcessor
            ext = os.path.splitext(input_data.file_path)[1].lower()
            audio_storage_path = None
            audio_id = None
            use_async_audio = ext in AUDIO_EXTENSIONS and self.async_audio_redactor

            # For audio files with async processing: skip FileProcessor, create placeholder
            if use_async_audio:
                try:
                    import uuid
                    import shutil
                    filename = os.path.basename(input_data.file_path)
                    audio_id = str(uuid.uuid4())[:12]
                    audio_dir = os.path.join(self.data_dir, "uploads", "audio")
                    os.makedirs(audio_dir, exist_ok=True)
                    audio_storage_path = os.path.join(audio_dir, f"{audio_id}{ext}")

                    # Copy audio to persistent storage
                    shutil.copy2(input_data.file_path, audio_storage_path)

                    # Create placeholder result (no transcription yet)
                    result = {
                        'text': f"[Audio file: {filename}]\n\n[Transcription in progress...]",
                        'metadata': {
                            'filename': filename,
                            'extension': ext,
                            'media_type': 'audio',
                            'format': ext.lstrip('.'),
                            'audio_id': audio_id,
                            'audio_path': audio_storage_path,
                            'transcription_pending': True,
                            'redaction_pending': True,
                        }
                    }
                    print(f"   🎵 Audio stored: {audio_id} (transcription queued)")
                except Exception as e:
                    print(f"   ⚠️ Audio storage failed: {e} (using sync processing)")
                    audio_storage_path = None
                    audio_id = None
                    use_async_audio = False

            # Process file with markdown conversion (media files routed to ML processors)
            # Skip for async audio files (already handled above)
            if not use_async_audio or audio_storage_path is None:
                result = FileProcessor.process_file(
                    input_data.file_path,
                    encoding=input_data.encoding,
                    include_metadata=True,
                    generate_markdown=True,
                    audio_processor=self.audio_processor,
                    image_processor=self.image_processor,
                )

            # Merge additional metadata if provided
            metadata = result['metadata']
            if input_data.additional_metadata:
                metadata.update(input_data.additional_metadata)

            # Store markdown content in metadata for viewing
            if 'markdown_content' in result:
                metadata['markdown_content'] = result['markdown_content']

            # For audio files processed via sync path: persist to disk
            # so the audio can be served back to the frontend
            if ext in AUDIO_EXTENSIONS and not audio_id:
                try:
                    import uuid
                    import shutil
                    audio_id = str(uuid.uuid4())[:12]
                    audio_dir = os.path.join(self.data_dir, "uploads", "audio")
                    os.makedirs(audio_dir, exist_ok=True)
                    audio_storage_path = os.path.join(audio_dir, f"{audio_id}{ext}")
                    shutil.copy2(input_data.file_path, audio_storage_path)
                    metadata['audio_id'] = audio_id
                    metadata['audio_path'] = audio_storage_path
                    print(f"   🎵 Audio stored: {audio_id}")
                except Exception as e:
                    print(f"   ⚠️ Audio storage failed: {e} (audio playback unavailable)")

            # Determine media type for extraction task
            media_type = metadata.get('media_type')  # 'audio', 'image', or None

            # Add document WITHOUT synchronous extraction (fast) - extraction happens async in background
            kind = media_type or "document"
            print(f"\n📄 Adding {kind} from file: {input_data.file_path} ({len(result['text'])} chars)...")
            add_result = self.vector_store.add_document(
                text=result['text'],
                embedding_model=self.embedding_model,
                metadata=metadata,
                skip_duplicates=input_data.skip_duplicates,
                topic_labeler=None,  # Skip sync extraction
                extract_key_passages=False,  # Skip sync extraction
                passage_extractor=None,
                extract_key_entities=False,  # Skip sync extraction
                verbose=True
            )

            # Handle duplicate detection result
            if isinstance(add_result, AddDocumentResult):
                if add_result.is_duplicate:
                    response = {
                        "success": False,
                        "is_duplicate": True,
                        "existing_document_id": add_result.existing_doc_id,
                        "content_hash": add_result.content_hash,
                        "file_path": input_data.file_path,
                        "message": f"File content already exists with document ID {add_result.existing_doc_id}"
                    }
                else:
                    doc_id = add_result.doc_id
                    # Queue async extraction for background processing
                    if self.async_extractor and self.passage_extractor and self.passage_extractor.is_available():
                        self.async_extractor.queue_extraction(ExtractionTask(
                            doc_id=doc_id,
                            text=result['text'],
                            extract_key_passages=True,
                            extract_key_entities=True,
                            extract_structured_metadata=True,
                            extract_filters=True,
                            source=metadata.get('source'),
                            filename=metadata.get('filename'),
                            media_type=media_type,
                        ))
                    # Queue async audio transcription and PII redaction
                    if audio_storage_path and audio_id and self.async_audio_redactor:
                        self.async_audio_redactor.queue_task(AudioRedactionTask(
                            doc_id=doc_id,
                            audio_id=audio_id,
                            audio_path=audio_storage_path,
                            mute_audio=True,
                            mute_style="beep",
                        ))
                    response = {
                        "success": True,
                        "document_id": doc_id,
                        "content_hash": add_result.content_hash,
                        "file_path": input_data.file_path,
                        "text_length": len(result['text']),
                        "metadata": metadata,
                        "message": f"Document added successfully from file '{metadata['filename']}' with ID {doc_id}"
                    }
            else:
                doc_id = add_result
                # Queue async extraction for background processing
                if self.async_extractor and self.passage_extractor and self.passage_extractor.is_available():
                    self.async_extractor.queue_extraction(ExtractionTask(
                        doc_id=doc_id,
                        text=result['text'],
                        extract_key_passages=True,
                        extract_key_entities=True,
                        extract_structured_metadata=True,
                        extract_filters=True,
                        source=metadata.get('source'),
                        filename=metadata.get('filename'),
                        media_type=media_type,
                    ))
                # Queue async audio transcription and PII redaction
                if audio_storage_path and audio_id and self.async_audio_redactor:
                    self.async_audio_redactor.queue_task(AudioRedactionTask(
                        doc_id=doc_id,
                        audio_id=audio_id,
                        audio_path=audio_storage_path,
                        mute_audio=True,
                        mute_style="beep",
                    ))
                response = {
                    "success": True,
                    "document_id": doc_id,
                    "file_path": input_data.file_path,
                    "text_length": len(result['text']),
                    "metadata": metadata,
                    "message": f"Document added successfully from file '{metadata['filename']}' with ID {doc_id}"
                }

        except FileNotFoundError as e:
            response = {
                "success": False,
                "error": "file_not_found",
                "message": str(e)
            }
        except ValueError as e:
            # Unsupported file format
            response = {
                "success": False,
                "error": "unsupported_format",
                "message": str(e),
                "supported_formats": list(FileProcessor.SUPPORTED_EXTENSIONS)
            }
        except UnicodeDecodeError as e:
            response = {
                "success": False,
                "error": "encoding_error",
                "message": f"Could not decode file with encoding '{input_data.encoding}'. Try a different encoding.",
                "details": str(e)
            }
        except Exception as e:
            response = {
                "success": False,
                "error": "processing_error",
                "message": f"Error processing file: {str(e)}"
            }

        return [TextContent(
            type="text",
            text=json.dumps(response, indent=2)
        )]

    async def _upload_and_add_document(self, arguments: Dict[str, Any]) -> List[TextContent]:
        """Handle upload_and_add_document tool call."""
        # AddDocumentResult imported at top level from txtai_adapter

        # Validate input
        input_data = UploadAndAddDocumentInput(**arguments)

        temp_file_path = None
        try:
            # Save uploaded file to temp location
            temp_file_path = self.upload_handler.save_base64_file(
                input_data.file_content,
                input_data.filename,
                keep_temp=False  # Will be auto-cleaned
            )

            # Process the uploaded file with markdown conversion (media files routed to ML processors)
            result = FileProcessor.process_file(
                temp_file_path,
                encoding=input_data.encoding,
                include_metadata=True,
                generate_markdown=True,
                audio_processor=self.audio_processor,
                image_processor=self.image_processor,
            )

            # Merge additional metadata
            metadata = result['metadata']
            # Add upload info
            metadata['uploaded'] = True
            metadata['original_filename'] = input_data.filename
            if input_data.additional_metadata:
                metadata.update(input_data.additional_metadata)

            # Store markdown content in metadata for viewing
            if 'markdown_content' in result:
                metadata['markdown_content'] = result['markdown_content']

            # Determine media type for extraction task
            media_type = metadata.get('media_type')

            # Add document WITHOUT synchronous extraction (fast) - extraction happens async in background
            kind = media_type or "document"
            print(f"\n📄 Adding uploaded {kind}: {input_data.filename} ({len(result['text'])} chars)...")
            add_result = self.vector_store.add_document(
                text=result['text'],
                embedding_model=self.embedding_model,
                metadata=metadata,
                skip_duplicates=input_data.skip_duplicates,
                topic_labeler=None,  # Skip sync extraction
                extract_key_passages=False,  # Skip sync extraction
                passage_extractor=None,
                extract_key_entities=False,  # Skip sync extraction
                verbose=True
            )

            # Handle duplicate detection result
            if isinstance(add_result, AddDocumentResult):
                if add_result.is_duplicate:
                    response = {
                        "success": False,
                        "is_duplicate": True,
                        "existing_document_id": add_result.existing_doc_id,
                        "content_hash": add_result.content_hash,
                        "filename": input_data.filename,
                        "message": f"File content already exists with document ID {add_result.existing_doc_id}"
                    }
                else:
                    # Queue async extraction for background processing
                    if self.async_extractor and self.passage_extractor and self.passage_extractor.is_available():
                        self.async_extractor.queue_extraction(ExtractionTask(
                            doc_id=add_result.doc_id,
                            text=result['text'],
                            extract_key_passages=True,
                            extract_key_entities=True,
                            extract_structured_metadata=True,
                            extract_filters=True,
                            source=metadata.get('source'),
                            filename=metadata.get('filename'),
                            media_type=media_type,
                        ))
                    response = {
                        "success": True,
                        "document_id": add_result.doc_id,
                        "content_hash": add_result.content_hash,
                        "filename": input_data.filename,
                        "text_length": len(result['text']),
                        "metadata": metadata,
                        "message": f"File '{input_data.filename}' uploaded and added successfully with ID {add_result.doc_id}"
                    }
            else:
                # Queue async extraction for background processing
                if self.async_extractor and self.passage_extractor and self.passage_extractor.is_available():
                    self.async_extractor.queue_extraction(ExtractionTask(
                        doc_id=add_result,
                        text=result['text'],
                        extract_key_passages=True,
                        extract_key_entities=True,
                        extract_structured_metadata=True,
                        extract_filters=True,
                        source=metadata.get('source'),
                        filename=metadata.get('filename'),
                        media_type=media_type,
                    ))
                response = {
                    "success": True,
                    "document_id": add_result,
                    "filename": input_data.filename,
                    "text_length": len(result['text']),
                    "metadata": metadata,
                    "message": f"File '{input_data.filename}' uploaded and added successfully with ID {add_result}"
                }

        except ValueError as e:
            # Base64 decode error or unsupported format
            response = {
                "success": False,
                "error": "invalid_input",
                "message": str(e),
                "supported_formats": list(FileProcessor.SUPPORTED_EXTENSIONS)
            }
        except UnicodeDecodeError as e:
            response = {
                "success": False,
                "error": "encoding_error",
                "message": f"Could not decode file with encoding '{input_data.encoding}'. Try a different encoding.",
                "details": str(e)
            }
        except Exception as e:
            response = {
                "success": False,
                "error": "processing_error",
                "message": f"Error processing uploaded file: {str(e)}"
            }
        finally:
            # Cleanup temp file
            if temp_file_path:
                self.upload_handler.cleanup_file(temp_file_path)

        return [TextContent(
            type="text",
            text=json.dumps(response, indent=2)
        )]

    async def _generate_topics(self, arguments: Dict[str, Any]) -> List[TextContent]:
        """Handle generate_topics tool call."""
        input_data = GenerateTopicsInput(**arguments)

        if not self.topic_labeler:
            return [TextContent(
                type="text",
                text=json.dumps({
                    "success": False,
                    "error": "Topic labeler not available",
                    "message": "Topic labeler not initialized."
                }, indent=2)
            )]

        # Get the document
        doc = self.vector_store.get_document(input_data.doc_id)
        if not doc:
            return [TextContent(
                type="text",
                text=json.dumps({
                    "success": False,
                    "error": "Document not found",
                    "message": f"Document with ID {input_data.doc_id} not found"
                }, indent=2)
            )]

        # Generate topics
        try:
            result = self.topic_labeler.generate_topics(
                text=doc.text,
                num_topics=input_data.num_topics,
                predefined_topics=input_data.predefined_topics
            )

            # Update document with topics
            self.vector_store.update_document_topics(
                doc_id=input_data.doc_id,
                topics=result.topics,
                primary_topic=result.primary_topic
            )

            response = {
                "success": True,
                "doc_id": input_data.doc_id,
                "topics": result.topics,
                "primary_topic": result.primary_topic,
                "confidence": result.confidence,
                "method": result.method,
                "message": f"Generated {len(result.topics)} topics for document {input_data.doc_id}"
            }
        except Exception as e:
            response = {
                "success": False,
                "error": "topic_generation_failed",
                "message": str(e)
            }

        return [TextContent(
            type="text",
            text=json.dumps(response, indent=2)
        )]

    async def _update_topics(self, arguments: Dict[str, Any]) -> List[TextContent]:
        """Handle update_topics tool call."""
        input_data = UpdateTopicsInput(**arguments)

        success = self.vector_store.update_document_topics(
            doc_id=input_data.doc_id,
            topics=input_data.topics,
            primary_topic=input_data.primary_topic
        )

        if success:
            response = {
                "success": True,
                "doc_id": input_data.doc_id,
                "topics": input_data.topics,
                "primary_topic": input_data.primary_topic or input_data.topics[0],
                "message": f"Topics updated for document {input_data.doc_id}"
            }
        else:
            response = {
                "success": False,
                "error": "Document not found",
                "message": f"Document with ID {input_data.doc_id} not found"
            }

        return [TextContent(
            type="text",
            text=json.dumps(response, indent=2)
        )]

    async def _get_topics(self, arguments: Dict[str, Any]) -> List[TextContent]:
        """Handle get_topics tool call."""
        input_data = GetTopicsInput(**arguments)

        result = self.vector_store.get_document_topics(input_data.doc_id)

        if result:
            response = {
                "success": True,
                **result
            }
        else:
            response = {
                "success": False,
                "error": "Document not found",
                "message": f"Document with ID {input_data.doc_id} not found"
            }

        return [TextContent(
            type="text",
            text=json.dumps(response, indent=2)
        )]

    async def _list_all_topics(self, arguments: Dict[str, Any]) -> List[TextContent]:
        """Handle list_all_topics tool call."""
        topic_counts = self.vector_store.get_all_topics()

        # Sort by count descending
        sorted_topics = sorted(topic_counts.items(), key=lambda x: x[1], reverse=True)

        response = {
            "success": True,
            "total_unique_topics": len(topic_counts),
            "topics": [
                {"name": name, "document_count": count}
                for name, count in sorted_topics
            ]
        }

        return [TextContent(
            type="text",
            text=json.dumps(response, indent=2)
        )]

    async def _search_with_topic(self, arguments: Dict[str, Any]) -> List[TextContent]:
        """Handle search_with_topic tool call."""
        input_data = SearchWithTopicInput(**arguments)

        results = self.vector_store.search_with_topic_filter(
            query=input_data.query,
            topic=input_data.topic,
            limit=input_data.top_k,
            min_score=input_data.min_score
        )

        # RT-02: Build formatted list first, then anonymize before returning to LLM
        formatted_results = [
            {
                "id": r.id,
                "text": r.text[:500] + "..." if len(r.text) > 500 else r.text,
                "score": r.score,
                "topics": r.topics,
                "primary_topic": r.primary_topic,
                "metadata": transform_metadata_for_context(r.metadata, context="llm")
            }
            for r in results
        ]

        # Apply PII anonymization (same pattern as search_documents)
        if self.pii_protector:
            formatted_results, _, _ = self.pii_protector.anonymize_search_results(
                formatted_results,
                text_fields=["text"]
            )

        response = {
            "query": input_data.query,
            "topic_filter": input_data.topic,
            "min_score_threshold": input_data.min_score,
            "results": formatted_results
        }

        return [TextContent(
            type="text",
            text=json.dumps(response, indent=2)
        )]

    async def _get_documents_by_topic(self, arguments: Dict[str, Any]) -> List[TextContent]:
        """Handle get_documents_by_topic tool call."""
        input_data = GetDocumentsByTopicInput(**arguments)

        result = self.vector_store.get_documents_by_topic(
            topic=input_data.topic,
            page=input_data.page,
            page_size=input_data.page_size
        )

        # RT-02: Build formatted list first, then anonymize before returning to LLM
        formatted_docs = [
            {
                "id": doc.id,
                "text": doc.text[:200] + "..." if len(doc.text) > 200 else doc.text,
                "topics": doc.topics,
                "primary_topic": doc.primary_topic,
                "created_at": doc.created_datetime.isoformat()
            }
            for doc in result.documents
        ]

        # Apply PII anonymization (same pattern as search_documents)
        if self.pii_protector:
            formatted_docs, _, _ = self.pii_protector.anonymize_search_results(
                formatted_docs,
                text_fields=["text"]
            )

        response = {
            "topic": input_data.topic,
            "page": result.page,
            "page_size": result.page_size,
            "total": result.total,
            "total_pages": result.total_pages,
            "has_next": result.has_next,
            "has_prev": result.has_prev,
            "documents": formatted_docs
        }

        return [TextContent(
            type="text",
            text=json.dumps(response, indent=2)
        )]

    async def _auto_generate_topics_for_document(self, doc_id: int, text: str) -> Optional[TopicResult]:
        """Auto-generate topics for a newly added document."""
        if not self.topic_labeler or not self.auto_label_on_upload:
            return None

        try:
            result = self.topic_labeler.generate_topics(text=text, num_topics=3)
            self.vector_store.update_document_topics(
                doc_id=doc_id,
                topics=result.topics,
                primary_topic=result.primary_topic
            )
            return result
        except Exception as e:
            print(f"Auto topic generation failed for doc {doc_id}: {e}")
            return None

    async def initialize(self):
        """Initialize models and vector store.

        txtai manages the embedding model internally - we use a thin wrapper
        around its model for TopicLabeler and PassageExtractor, avoiding
        duplicate GPU model loading on memory-constrained devices (Jetson).
        """
        from .model_manager import get_model_manager

        # Get the global model manager
        self.model_manager = get_model_manager(verbose=True)

        # Create shared MemoryMonitor for backpressure across all async workers
        from .gpu_scheduler import create_memory_monitor
        self._memory_monitor = create_memory_monitor()
        print(f"GPU scheduler: memory monitor (high={self._memory_monitor.high_watermark_pct}%, "
              f"low={self._memory_monitor.low_watermark_pct}%), "
              f"circuit breaker (threshold={self.model_manager._circuit_breaker._failure_threshold}, "
              f"cooldown={self.model_manager._circuit_breaker._cooldown_seconds}s)")

        # Initialize txtai first - it loads the embedding model onto GPU
        print("Initializing vector store (txtai backend)...")
        self.vector_store = create_vector_store(
            db_path=self.db_path,
            embedding_dim=384  # all-MiniLM-L6-v2 dimension
        )

        # Get a wrapper around txtai's internal embedding model
        # This provides the same embed()/embed_query() API without loading a second model
        print("Using txtai's embedding model for topic labeling and passage extraction...")
        self.embedding_model = self.vector_store.get_embedding_wrapper()
        print(f"Embedding wrapper ready: model={self.embedding_model.model_name}, dim={self.embedding_model.embedding_dim}")

        print("Initializing topic labeler (embedding-based)...")
        try:
            # Topic labeler uses embedding model for semantic similarity
            self.topic_labeler = TopicLabeler(
                embedding_model=self.embedding_model,
                verbose=True
            )
            print("Topic labeler initialized (keyword + embedding-based classification)")

            # Initialize passage extractor with embedding model
            self.passage_extractor = PassageExtractor(
                embedding_model=self.embedding_model,
                verbose=True
            )
            print("Passage extractor initialized (embedding-based extraction)")
        except Exception as e:
            print(f"Warning: Topic labeler initialization failed: {e}")
            print("Topic labeling and passage extraction will use heuristics only")
            self.topic_labeler = TopicLabeler(verbose=True)  # Keywords only
            self.passage_extractor = PassageExtractor(verbose=True)  # Heuristics only

        # Reranker is lazy-loaded on first search to keep GPU free for Ollama
        # See _ensure_reranker() method
        self.reranker = None
        self._reranker_init_attempted = False
        print("Reranker will be lazy-loaded on first search (keeps GPU free for chat)")

        # Initialize async extractor for background extraction
        print("Initializing async extractor...")
        self.async_extractor = AsyncExtractor(
            vector_store=self.vector_store,
            passage_extractor=self.passage_extractor,
            topic_labeler=self.topic_labeler,
            verbose=True,
            memory_monitor=self._memory_monitor,
        )
        self.async_extractor.start()
        print("Async extractor started (background extraction enabled)")

        # Queue documents missing extraction (recover from restart)
        self._queue_pending_extractions()

        # Initialize media processors (audio/image)
        print("Initializing media processors...")
        try:
            self.audio_processor = AudioProcessor(verbose=True)
            print("Audio processor initialized (Whisper transcription)")
        except Exception as e:
            print(f"Warning: Audio processor not available: {e}")
            self.audio_processor = None

        try:
            self.image_processor = ImageProcessor(verbose=True)
            print("Image processor initialized (BLIP captioning)")
        except Exception as e:
            print(f"Warning: Image processor not available: {e}")
            self.image_processor = None

        # Initialize PII protection (Microsoft Presidio)
        print("Initializing PII protection...")
        try:
            self.pii_protector = get_pii_protector(
                verbose=True,
                spacy_model="en_core_web_sm",
                session_ttl_seconds=3600
            )
            if self.pii_protector.is_available:
                print("PII protection initialized (Microsoft Presidio)")
            else:
                print("PII protection: Presidio not installed, search results will not be anonymized")
                print("  Install with: pip install presidio-analyzer presidio-anonymizer")
                print("  Then run: python -m spacy download en_core_web_sm")
        except Exception as e:
            print(f"Warning: PII protection initialization failed: {e}")
            self.pii_protector = None

        # Initialize Image PII Redactor (OCR + Presidio for images)
        self.image_pii_redactor = None
        if IMAGE_PII_AVAILABLE:
            config = get_image_pii_config()
            if config.get("enabled", True):
                print("Initializing image PII redactor...")
                try:
                    self.image_pii_redactor = get_image_pii_redactor(
                        pii_protector=self.pii_protector,
                        verbose=True,
                    )
                    if self.image_pii_redactor.is_available():
                        engine = self.image_pii_redactor._ocr_engine.value
                        gpu = "GPU" if self.image_pii_redactor._use_gpu else "CPU"
                        print(f"Image PII redactor initialized ({engine} on {gpu})")
                        # Register with model manager for GPU swapping
                        if self.image_pii_redactor._use_gpu:
                            from .model_manager import get_model_manager
                            manager = get_model_manager()
                            manager.register_ocr(self.image_pii_redactor)
                    else:
                        print("Image PII redactor: OCR engine not available")
                        print("  Install with: pip install easyocr pytesseract")
                except Exception as e:
                    print(f"Warning: Image PII redactor initialization failed: {e}")
                    self.image_pii_redactor = None

        # Initialize Image Storage Manager (for persistent image storage with redaction)
        self.image_storage = None
        try:
            # Derive storage paths from db_path (sibling dirs to vectordb)
            # e.g. db_path="../data/vectordb" → data_root="../data"
            data_root = os.path.dirname(os.path.abspath(self.db_path))
            default_uploads = os.path.join(data_root, "uploads", "images")
            default_redacted = os.path.join(data_root, "redacted", "images")
            uploads_dir = os.environ.get("IMAGE_UPLOAD_PATH", default_uploads)
            redacted_dir = os.environ.get("IMAGE_REDACTED_PATH", default_redacted)

            self.image_storage = ImageStorageManager(
                uploads_dir=uploads_dir,
                redacted_dir=redacted_dir,
                pii_redactor=self.image_pii_redactor,
                verbose=True,
            )
            print(f"Image storage initialized:")
            print(f"  Uploads: {uploads_dir}")
            print(f"  Redacted: {redacted_dir}")
            print(f"  PII redaction: {'enabled' if self.image_pii_redactor else 'disabled'}")
        except Exception as e:
            print(f"Warning: Image storage initialization failed: {e}")
            self.image_storage = None

        # Initialize async image redactor for background PII redaction
        self.async_image_redactor = None
        if self.image_storage and self.image_pii_redactor:
            print("Initializing async image redactor...")
            self.async_image_redactor = AsyncImageRedactor(
                vector_store=self.vector_store,
                pii_redactor=self.image_pii_redactor,
                verbose=True,
                memory_monitor=self._memory_monitor,
            )
            self.async_image_redactor.start()
            print("Async image redactor started (background PII redaction enabled)")

        # Initialize async audio redactor for background transcription and PII redaction
        self.async_audio_redactor = None
        if self.audio_processor:
            from .audio_pii_redactor import get_audio_pii_redactor
            audio_pii_redactor = get_audio_pii_redactor(pii_protector=self.pii_protector, verbose=True)
            if audio_pii_redactor.is_available():
                print("Initializing async audio redactor...")
                self.async_audio_redactor = AsyncAudioRedactor(
                    vector_store=self.vector_store,
                    audio_pii_redactor=audio_pii_redactor,
                    verbose=True,
                    memory_monitor=self._memory_monitor,
                )
                self.async_audio_redactor.start()
                print("Async audio redactor started (background transcription enabled)")

        # Initialize voice chat services (all-Groq cloud pipeline)
        self.groq_stt_service = None
        self.groq_tts_service = None
        self.voice_stream = None
        self._voice_text_events = []  # SSE event buffer per connection
        self._voice_text_lock = __import__('threading').Lock()

        # Voice config: voice is TTS voice name for Groq Orpheus
        self._voice_config = {"voice": "troy"}

        try:
            from .groq_stt_service import GroqSTT
            self.groq_stt_service = GroqSTT()
            print("Groq STT initialized (cloud Whisper API, on demand)")
        except ImportError as e:
            print(f"Groq STT not available: {e}")
        except Exception as e:
            print(f"Warning: Groq STT initialization failed: {e}")

        try:
            from .groq_tts_service import GroqTTS
            self.groq_tts_service = GroqTTS()
            print("Groq TTS initialized (cloud PlayAI API, on demand)")
        except ImportError as e:
            print(f"Groq TTS not available: {e}")
        except Exception as e:
            print(f"Warning: Groq TTS initialization failed: {e}")

        # Initialize FastRTC voice stream
        self._init_voice_stream()

        print("MCP HTTP server initialized and ready!")

    def _init_voice_stream(self):
        """Initialize FastRTC voice stream for WebRTC voice chat."""
        if not self.groq_stt_service or not self.groq_tts_service:
            print("Voice stream not initialized: missing Groq STT or TTS service")
            return

        try:
            from fastrtc import Stream, ReplyOnPause
            from .voice_rtc_handler import VoiceRTCHandler

            def text_callback(event_type: str, data: dict) -> None:
                """Buffer text events for SSE delivery."""
                with self._voice_text_lock:
                    self._voice_text_events.append({
                        "type": event_type,
                        "data": data,
                        "timestamp": __import__('time').time(),
                    })

            handler = VoiceRTCHandler(
                vector_store=self.vector_store,
                embedding_model=self.embedding_model,
                model_manager=self.model_manager,
                pii_protector=self.pii_protector,
                groq_stt_service=self.groq_stt_service,
                groq_tts_service=self.groq_tts_service,
                text_callback=text_callback,
                verbose=True,
            )
            self._voice_handler = handler

            self.voice_stream = Stream(
                handler=ReplyOnPause(handler),
                modality="audio",
                mode="send-receive",
                concurrency_limit=1,  # One voice session at a time on Jetson
                time_limit=300,       # 5 min max
            )
            print("FastRTC voice stream initialized (WebRTC ready, all-Groq cloud pipeline)")

        except ImportError as e:
            print(f"FastRTC not available: {e}")
            self.voice_stream = None
        except Exception as e:
            print(f"Warning: FastRTC voice stream initialization failed: {e}")
            self.voice_stream = None

    async def cleanup(self):
        """Cleanup resources and unload models."""
        # Stop async extractor
        if hasattr(self, 'async_extractor') and self.async_extractor:
            self.async_extractor.stop()

        # Stop async image redactor
        if hasattr(self, 'async_image_redactor') and self.async_image_redactor:
            self.async_image_redactor.stop()

        # Stop async audio redactor
        if hasattr(self, 'async_audio_redactor') and self.async_audio_redactor:
            self.async_audio_redactor.stop()

        # Unload all models via model manager
        if hasattr(self, 'model_manager') and self.model_manager:
            self.model_manager.unload_all()

        # Close vector store
        if self.vector_store:
            self.vector_store.close()

    def _ensure_reranker(self):
        """Lazy-load the reranker on first use."""
        if self.reranker is not None:
            return self.reranker

        if self._reranker_init_attempted:
            return None

        self._reranker_init_attempted = True

        try:
            from .reranker import create_reranker
            print("Lazy-loading reranker for search...")
            self.reranker = create_reranker(preset="fast")
            if self.reranker:
                print("Reranker loaded (cross-encoder for improved precision)")
                # Register with model manager
                self.model_manager.register_reranker(self.reranker)
            else:
                print("Reranker not available (sentence-transformers not installed)")
        except Exception as e:
            print(f"Warning: Reranker initialization failed: {e}")
            self.reranker = None

        return self.reranker

    def _get_data_dir(self) -> str:
        """Get the data directory path for file system operations."""
        return self.data_dir

    def _queue_pending_extractions(self):
        """Queue documents missing extraction metadata for background processing.

        Called on startup to recover from restart - documents that were indexed
        but not yet extracted will be re-queued.
        """
        if not self.async_extractor or not self.passage_extractor:
            return

        if not self.passage_extractor.is_available():
            print("Skipping extraction recovery: passage extractor not available")
            return

        try:
            # Get all parent documents (exclude chunks)
            all_docs = self.vector_store.get_all_documents(ascending=True)

            # Filter to only parent documents (not chunks)
            parent_docs = [d for d in all_docs if not d.metadata.get('is_chunk', False)]

            # Find documents missing extraction metadata
            pending = []
            for doc in parent_docs:
                metadata = doc.metadata or {}
                # Check if extraction was done (has key_passages or key_entities)
                has_extraction = (
                    metadata.get('key_passages') or
                    metadata.get('key_entities') or
                    metadata.get('structured_metadata')
                )
                if not has_extraction:
                    pending.append(doc)

            if not pending:
                print("No documents pending extraction")
                return

            print(f"Found {len(pending)} documents pending extraction, queueing...")

            for doc in pending:
                metadata = doc.metadata or {}
                self.async_extractor.queue_extraction(ExtractionTask(
                    doc_id=doc.id,
                    text=doc.text,
                    extract_key_passages=True,
                    extract_key_entities=True,
                    extract_structured_metadata=True,
                    extract_filters=True,
                    extract_topics=True,
                    source=metadata.get('source'),
                    filename=metadata.get('filename')
                ))

            print(f"Queued {len(pending)} documents for extraction")

        except Exception as e:
            print(f"Warning: Failed to queue pending extractions: {e}")

    def get_gpu_status(self) -> dict:
        """Get current GPU usage status for coordination with external services."""
        extraction_pending = 0
        if self.async_extractor:
            extraction_pending = self.async_extractor.get_pending_count()

        current_model = None
        models_status = {}
        if self.model_manager:
            current_model = self.model_manager.get_current_gpu_model()
            models_status = self.model_manager.get_status()

        # GPU is busy if extraction is running or a model is loaded
        is_busy = extraction_pending > 0 or current_model is not None

        return {
            "gpu_busy": is_busy,
            "current_model": current_model,
            "extraction_pending": extraction_pending,
            "models": models_status,
            "can_release": extraction_pending == 0  # Can only release if no extraction running
        }

    def release_gpu(self) -> dict:
        """Release GPU by unloading all models. For external service coordination."""
        extraction_pending = 0
        if self.async_extractor:
            extraction_pending = self.async_extractor.get_pending_count()

        if extraction_pending > 0:
            return {
                "success": False,
                "error": f"Cannot release GPU: {extraction_pending} extraction tasks pending",
                "extraction_pending": extraction_pending
            }

        # Unload all models
        if self.model_manager:
            self.model_manager.unload_all()
            print("GPU released: All models unloaded for external use")

        return {
            "success": True,
            "message": "GPU released - all models unloaded"
        }

    def _is_localhost(self, client_ip: Optional[str]) -> bool:
        """Check if the client IP is localhost."""
        if not client_ip:
            return False
        localhost_ips = {"127.0.0.1", "::1", "localhost"}
        return client_ip in localhost_ips

    def _get_client_ip(self, request) -> Optional[str]:
        """Extract client IP from request.

        WARNING: This method trusts X-Forwarded-For headers. Use _get_client_ip_secure()
        for security-sensitive checks (e.g., PII de-anonymization access control).
        """
        # Check X-Forwarded-For header (for reverse proxy)
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        # Fall back to direct client
        client = request.scope.get("client")
        if client:
            return client[0]
        return None

    def _get_client_ip_secure(self, request) -> Optional[str]:
        """Extract client IP from request WITHOUT trusting proxy headers.

        SECURITY: This method ignores X-Forwarded-For to prevent IP spoofing.
        Use this for all security-critical access control decisions (e.g., localhost checks
        for PII de-anonymization). X-Forwarded-For can be trivially spoofed by any client.

        If you deploy behind a trusted reverse proxy, configure TRUSTED_PROXY_IPS
        environment variable with comma-separated IPs of your proxies.
        """
        # Get the actual TCP connection IP (cannot be spoofed)
        client = request.scope.get("client")
        direct_ip = client[0] if client else None

        # Only trust X-Forwarded-For if the direct connection is from a trusted proxy
        trusted_proxies_env = os.environ.get("TRUSTED_PROXY_IPS", "").strip()
        if trusted_proxies_env and direct_ip:
            trusted_proxies = {ip.strip() for ip in trusted_proxies_env.split(",") if ip.strip()}
            if direct_ip in trusted_proxies:
                forwarded_for = request.headers.get("x-forwarded-for")
                if forwarded_for:
                    return forwarded_for.split(",")[0].strip()

        return direct_ip

    async def handle_sse(self, request):
        """Handle SSE connection for MCP.

        SECURITY NOTE: _current_client_ip is stored per-connection but as an instance
        variable, which creates a race condition with concurrent SSE connections.
        The secure IP check (_get_client_ip_secure) should be used for all security-
        critical decisions. The _current_client_ip is only used for MCP tool listing
        (non-security-critical), while the actual deanonymize_text tool handler
        performs its own independent localhost check.
        """
        # Track client IP for conditional tool visibility (non-security-critical)
        # SECURITY: Use _get_client_ip_secure for the tool listing as well
        self._current_client_ip = self._get_client_ip_secure(request)

        async with self.sse_transport.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await self.server.run(
                streams[0],
                streams[1],
                self.server.create_initialization_options()
            )

        # Clear after connection ends
        self._current_client_ip = None

    async def handle_messages(self, request):
        """Handle MCP messages endpoint."""
        await self.sse_transport.handle_post_message(
            request.scope, request.receive, request._send
        )

    def create_app(self) -> Starlette:
        """Create Starlette application."""

        async def health_check(request):
            """Health check endpoint with PII subsystem status."""
            # Get PII protection status
            pii_status = {
                "available": False,
                "initialized": False,
            }
            if self.pii_protector:
                pii_status["available"] = self.pii_protector.is_available
                stats = self.pii_protector.get_stats()
                pii_status["initialized"] = stats.get("analyzer_initialized", False)
                if stats.get("init_error"):
                    pii_status["error"] = stats["init_error"]

            return Response(
                json.dumps({
                    "status": "healthy",
                    "service": "mcp-vector-store",
                    "version": "0.6.0",
                    "mode": "public" if self.public else "local",
                    "pii_protection": pii_status
                }),
                media_type="application/json"
            )

        async def health_pii(request):
            """Detailed PII subsystem health check endpoint."""
            if not self.pii_protector:
                return JSONResponse({
                    "status": "unavailable",
                    "reason": "PII protector not initialized",
                    "healthy": False
                }, status_code=503)

            stats = self.pii_protector.get_stats()

            # Determine health status
            is_healthy = (
                stats.get("presidio_available", False) and
                stats.get("analyzer_initialized", False) and
                stats.get("init_error") is None
            )

            response_data = {
                "status": "healthy" if is_healthy else "degraded",
                "healthy": is_healthy,
                "presidio_available": stats.get("presidio_available", False),
                "analyzer_initialized": stats.get("analyzer_initialized", False),
                "spacy_model": stats.get("spacy_model", "unknown"),
                "active_sessions": stats.get("active_sessions", 0),
                "total_sessions": stats.get("total_sessions", 0),
                "total_tokens": stats.get("total_tokens", 0),
                "max_sessions": stats.get("max_sessions", 100),
                "session_ttl_seconds": stats.get("session_ttl_seconds", 3600),
                "entities_configured": len(stats.get("entities_detected", [])),
            }

            if stats.get("init_error"):
                response_data["error"] = stats["init_error"]
                response_data["status"] = "error"

            status_code = 200 if is_healthy else 503
            return JSONResponse(response_data, status_code=status_code)

        async def health_lprag(request):
            """Detailed LPRAG subsystem health check endpoint."""
            if not self.pii_protector:
                return JSONResponse({
                    "status": "unavailable",
                    "reason": "PII protector not initialized",
                    "healthy": False
                }, status_code=503)

            stats = self.pii_protector.get_stats()
            lprag_stats = stats.get("lprag", {})

            # Check LPRAG availability and status
            lprag_available = lprag_stats.get("available", False)
            lprag_mode = lprag_stats.get("mode", "token_only")
            lprag_initialized = lprag_stats.get("initialized", False)
            lprag_error = lprag_stats.get("init_error")

            # LPRAG is healthy if:
            # - Mode is token_only (LPRAG disabled, which is fine), OR
            # - LPRAG is available and initialized without errors
            is_healthy = (
                lprag_mode == "token_only" or
                (lprag_available and lprag_initialized and lprag_error is None)
            )

            response_data = {
                "status": "healthy" if is_healthy else "degraded",
                "healthy": is_healthy,
                "lprag_available": lprag_available,
                "mode": lprag_mode,
                "initialized": lprag_initialized,
                "total_perturbed_values": stats.get("total_perturbed_values", 0),
            }

            # Add engine stats if available
            if lprag_stats.get("engine"):
                response_data["engine"] = lprag_stats["engine"]

            if lprag_error:
                response_data["error"] = lprag_error
                response_data["status"] = "error"

            status_code = 200 if is_healthy else 503
            return JSONResponse(response_data, status_code=status_code)

        async def health_consent(request):
            """Detailed consent subsystem health check endpoint."""
            if not CONSENT_AVAILABLE:
                return JSONResponse({
                    "status": "unavailable",
                    "reason": "consent modules not installed",
                    "healthy": False
                }, status_code=503)

            try:
                session_manager = get_session_manager()
                stats = session_manager.get_stats()

                response_data = {
                    "status": "healthy",
                    "healthy": True,
                    "consent_available": True,
                    "active_sessions": stats["active_sessions"],
                    "total_sessions_created": stats["total_sessions_created"],
                    "max_sessions": stats["max_sessions"],
                    "presets_available": list(CONSENT_PRESETS.keys()),
                    "categories_available": list(DATA_CATEGORIES)
                }

                return JSONResponse(response_data)
            except Exception as e:
                return JSONResponse({
                    "status": "error",
                    "healthy": False,
                    "error": str(e)
                }, status_code=503)

        async def info(request):
            """Info endpoint."""
            stats = self.vector_store.get_stats() if self.vector_store else {}
            return Response(
                json.dumps({
                    "service": "MCP Vector Store",
                    "transport": "HTTP/SSE",
                    "mode": "public (authenticated)" if self.public else "local (no auth)",
                    "host": self.host,
                    "port": self.port,
                    "endpoints": {
                        "health": "/health",
                        "info": "/info",
                        "sse": "/sse",
                        "messages": "/messages",
                        "api/search": "/api/search (POST)",
                        "api/documents": "/api/documents (GET, POST)",
                        "api/documents/{id}": "/api/documents/{id} (GET, DELETE)",
                        "api/documents/batch": "/api/documents/batch (POST)",
                        "api/memory": "/api/memory (POST) - Write typed memory",
                        "api/memory/search": "/api/memory/search (POST) - Search typed memory",
                        "api/memory/timeline": "/api/memory/timeline (POST) - Audit typed memory",
                        "api/memory/graph": "/api/memory/graph (POST) - Graph typed memory",
                        "api/graph": "/api/graph (POST) - Get knowledge graph",
                        "api/graph/node/{id}": "/api/graph/node/{id} (GET) - Get node details"
                    },
                    "authentication": "API key required (Bearer token)" if self.public else "None",
                    "stats": stats
                }, indent=2),
                media_type="application/json"
            )

        # REST API endpoint: Search documents
        async def api_search(request):
            """REST API endpoint for semantic search.

            Args (JSON body):
                query: Search query text
                top_k: Number of results (default 5, max 20)
                min_score: Optional minimum similarity threshold
                context: Access context - "user" (default) or "llm"
                         When "llm", image paths are swapped to redacted versions
                         to protect PII from being sent to external LLM APIs.
            """
            try:
                body = await request.json()
                query = body.get("query", "")
                top_k = body.get("top_k", 5)
                min_score = body.get("min_score")  # Optional threshold
                context = body.get("context", "user")  # "user" or "llm"

                if not query:
                    return JSONResponse(
                        {"error": "Query is required"},
                        status_code=400
                    )

                results = self.vector_store.search(
                    query=query,
                    embedding_model=self.embedding_model,
                    top_k=min(top_k, 20),
                    min_score=min_score
                )

                # Transform metadata based on context for LLM safety
                # context="llm": Returns redacted image paths to protect PII
                # context="user": Returns original metadata for direct user access
                return JSONResponse({
                    "query": query,
                    "min_score_threshold": min_score,
                    "context": context,
                    "results": [
                        {
                            "id": r.id,
                            "text": r.text,
                            "score": r.score,
                            "topics": r.topics,
                            "primary_topic": r.primary_topic,
                            "metadata": transform_metadata_for_context(r.metadata, context)
                        }
                        for r in results
                    ]
                })
            except Exception as e:
                return JSONResponse(
                    {"error": str(e)},
                    status_code=500
                )

        # REST API endpoint: Enhanced search with passage extraction
        async def api_enhanced_search(request):
            """REST API endpoint for enhanced search with passage extraction.

            Args (JSON body):
                query: Search query text
                top_k: Number of results (default 5, max 20)
                min_score: Minimum similarity threshold (default 0.5)
                extract_passages: Extract relevant passages (default True)
                max_excerpt_length: Max excerpt length (default 500)
                consent_session_id: Optional consent session for filtering
                context: Access context - "user" (default) or "llm"
                         When "llm", image paths are swapped to redacted versions.
            """
            from .model_manager import ModelType
            from .consent_manager import get_consent_manager

            try:
                body = await request.json()
                query = body.get("query", "")
                top_k = body.get("top_k", 5)
                min_score = body.get("min_score", 0.5)  # Balanced threshold for quality results
                extract_passages = body.get("extract_passages", True)
                max_excerpt_length = body.get("max_excerpt_length", 500)
                consent_session_id = body.get("consent_session_id")  # Optional consent filtering
                context = body.get("context", "user")  # "user" or "llm"

                if not query:
                    return JSONResponse(
                        {"error": "Query is required"},
                        status_code=400
                    )

                # Lazy-load reranker if available
                reranker = self._ensure_reranker()
                if reranker:
                    self.model_manager.ensure_loaded(ModelType.RERANKER)

                # Use reranking by default if available
                effective_top_k = min(top_k, 20)
                reranker_available = reranker and reranker.is_available()

                # Fetch more results if consent filtering is active (some may be filtered out)
                fetch_top_k = effective_top_k * 3 if consent_session_id else effective_top_k

                results = self.vector_store.enhanced_search(
                    query=query,
                    embedding_model=self.embedding_model,
                    top_k=fetch_top_k,
                    min_score=min_score,
                    extract_passages=extract_passages,
                    passage_extractor=self.passage_extractor,
                    max_excerpt_length=max_excerpt_length,
                    reranker=reranker if reranker_available else None,
                    rerank_top_k=fetch_top_k * 3 if reranker_available else None
                )

                # Apply consent filtering if session provided
                if consent_session_id:
                    consent_manager = get_consent_manager()
                    session = consent_manager.get_session(consent_session_id)
                    if session:
                        # Convert results to dict format for filtering
                        result_dicts = [
                            {
                                "id": r.id,
                                "excerpt": r.excerpt,
                                "score": r.score,
                                "excerpt_method": r.excerpt_method,
                                "topics": r.topics,
                                "primary_topic": r.primary_topic,
                                "full_text_length": len(r.text),
                                "metadata": r.metadata
                            }
                            for r in results
                        ]
                        filtered_results, stats = consent_manager.filter_documents(result_dicts, session)
                        # Limit to requested top_k after filtering
                        filtered_results = filtered_results[:effective_top_k]
                        # Apply context-aware metadata transformation for LLM safety
                        for r in filtered_results:
                            if "metadata" in r:
                                r["metadata"] = transform_metadata_for_context(r["metadata"], context)
                        return JSONResponse({
                            "query": query,
                            "min_score_threshold": min_score,
                            "passage_extraction": extract_passages,
                            "consent_applied": True,
                            "context": context,
                            "consent_stats": {
                                "documents_input": stats.documents_input,
                                "documents_filtered_by_category": stats.documents_filtered_by_category,
                                "documents_output": len(filtered_results),
                            },
                            "results": filtered_results
                        })

                # Apply context-aware metadata transformation for LLM safety
                return JSONResponse({
                    "query": query,
                    "min_score_threshold": min_score,
                    "passage_extraction": extract_passages,
                    "context": context,
                    "results": [
                        {
                            "id": r.id,
                            "excerpt": r.excerpt,
                            "score": r.score,
                            "excerpt_method": r.excerpt_method,
                            "topics": r.topics,
                            "primary_topic": r.primary_topic,
                            "full_text_length": len(r.text),
                            "metadata": transform_metadata_for_context(r.metadata, context)
                        }
                        for r in results
                    ][:effective_top_k]
                })
            except Exception as e:
                return JSONResponse(
                    {"error": str(e)},
                    status_code=500
                )

        # REST API endpoint: Think with cited evidence, entity graph, gaps, freshness, and maintenance actions
        async def api_think(request):
            """REST API endpoint for PII-safe agent reasoning context."""
            try:
                body = await request.json()
                input_data = ThinkInput(**body)
                if not input_data.question.strip():
                    return JSONResponse(
                        {"error": "Question is required"},
                        status_code=400
                    )
                return JSONResponse(self._build_think_response(input_data))
            except Exception as e:
                return JSONResponse(
                    {"error": str(e)},
                    status_code=500
                )

        # REST API endpoint: Write typed memory
        async def api_write_memory(request):
            """REST API endpoint for typed, versioned memory writes."""
            try:
                body = await request.json()
                input_data = WriteMemoryInput(**body)
                response = self._write_memory_payload(input_data)
                return JSONResponse(response, status_code=201 if response.get("success") else 200)
            except ValueError as e:
                return JSONResponse({"error": str(e)}, status_code=400)
            except Exception as e:
                return JSONResponse(
                    {"error": str(e)},
                    status_code=500
                )

        # REST API endpoint: Search typed memory
        async def api_search_memory(request):
            """REST API endpoint for governed typed-memory search."""
            try:
                body = await request.json()
                input_data = SearchMemoryInput(**body)
                return JSONResponse(self._search_memory_payload(input_data))
            except ValueError as e:
                return JSONResponse({"error": str(e)}, status_code=400)
            except Exception as e:
                return JSONResponse(
                    {"error": str(e)},
                    status_code=500
                )

        # REST API endpoint: Typed memory audit timeline
        async def api_memory_timeline(request):
            """REST API endpoint for typed-memory audit timelines."""
            try:
                body = await request.json()
                input_data = MemoryTimelineInput(**body)
                return JSONResponse(self._memory_timeline_payload(input_data))
            except ValueError as e:
                return JSONResponse({"error": str(e)}, status_code=400)
            except Exception as e:
                return JSONResponse(
                    {"error": str(e)},
                    status_code=500
                )

        # REST API endpoint: Typed memory graph
        async def api_memory_graph(request):
            """REST API endpoint for graph-assisted typed memory."""
            try:
                body = await request.json()
                input_data = MemoryGraphInput(**body)
                return JSONResponse(self._memory_graph_payload(input_data))
            except ValueError as e:
                return JSONResponse({"error": str(e)}, status_code=400)
            except Exception as e:
                return JSONResponse(
                    {"error": str(e)},
                    status_code=500
                )

        # REST API endpoint: Typed memory workspace summary
        async def api_memory_workspace_info(request):
            """REST API endpoint for typed-memory workspace governance summaries."""
            try:
                body = await request.json()
                input_data = MemoryWorkspaceInfoInput(**body)
                return JSONResponse(self._memory_workspace_info_payload(input_data))
            except ValueError as e:
                return JSONResponse({"error": str(e)}, status_code=400)
            except Exception as e:
                return JSONResponse(
                    {"error": str(e)},
                    status_code=500
                )

        # REST API endpoint: Typed memory actor activity
        async def api_memory_actor_activity(request):
            """REST API endpoint for typed-memory actor audit activity."""
            try:
                body = await request.json()
                input_data = MemoryActorActivityInput(**body)
                return JSONResponse(self._memory_actor_activity_payload(input_data))
            except ValueError as e:
                return JSONResponse({"error": str(e)}, status_code=400)
            except Exception as e:
                return JSONResponse(
                    {"error": str(e)},
                    status_code=500
                )

        # REST API endpoint: Add single document
        async def api_add_document(request):
            """REST API endpoint to add a document."""
            # AddDocumentResult imported at top level from txtai_adapter
            from .markdown_converter import MarkdownConverter

            try:
                body = await request.json()
                text = body.get("text", "")
                metadata = body.get("metadata") or {}
                skip_duplicates = body.get("skip_duplicates")  # None means use server default

                if not text:
                    return JSONResponse(
                        {"error": "Text is required"},
                        status_code=400
                    )

                # Generate markdown content for viewing if not already present
                if 'markdown_content' not in metadata:
                    filename = metadata.get('filename', 'document.txt')
                    extension = metadata.get('extension', '.txt')
                    metadata['markdown_content'] = MarkdownConverter.convert(
                        text=text,
                        filename=filename,
                        extension=extension
                    )

                # Add document WITHOUT extraction (fast) - extraction happens async
                print(f"\n📄 [REST API] Adding document ({len(text)} chars)...")
                result = self.vector_store.add_document(
                    text=text,
                    embedding_model=self.embedding_model,
                    metadata=metadata,
                    skip_duplicates=skip_duplicates,
                    topic_labeler=None,  # Skip sync extraction
                    extract_key_passages=False,  # Skip sync extraction
                    passage_extractor=None,
                    extract_key_entities=False,  # Skip sync extraction
                    verbose=True
                )

                # Handle duplicate detection result
                if isinstance(result, AddDocumentResult):
                    if result.is_duplicate:
                        return JSONResponse({
                            "success": False,
                            "is_duplicate": True,
                            "existing_document_id": result.existing_doc_id,
                            "content_hash": result.content_hash,
                            "message": f"Document already exists with ID {result.existing_doc_id}"
                        })
                    else:
                        doc_id = result.doc_id
                else:
                    doc_id = result

                # Queue async extraction (runs on GPU in background)
                extraction_queued = False
                if self.async_extractor and self.passage_extractor and self.passage_extractor.is_available():
                    self.async_extractor.queue_extraction(ExtractionTask(
                        doc_id=doc_id,
                        text=text,
                        extract_key_passages=True,
                        extract_key_entities=True,
                        extract_structured_metadata=True,
                        extract_filters=True,
                        source=metadata.get('source'),
                        filename=metadata.get('filename')
                    ))
                    extraction_queued = True

                return JSONResponse({
                    "success": True,
                    "document_id": doc_id,
                    "content_hash": result.content_hash if isinstance(result, AddDocumentResult) else None,
                    "message": f"Document added with ID {doc_id}",
                    "extraction_queued": extraction_queued
                })
            except Exception as e:
                return JSONResponse(
                    {"error": str(e)},
                    status_code=500
                )

        # REST API endpoint: Add multiple documents
        async def api_add_documents_batch(request):
            """REST API endpoint to add multiple documents."""
            # AddDocumentResult imported at top level from txtai_adapter
            from .markdown_converter import MarkdownConverter

            try:
                body = await request.json()
                documents = body.get("documents", [])
                skip_duplicates = body.get("skip_duplicates")  # None means use server default
                # Option to extract key passages at storage time (default: True for optimal search)
                extract_key_passages = body.get("extract_key_passages", True)

                if not documents:
                    return JSONResponse(
                        {"error": "Documents array is required"},
                        status_code=400
                    )

                doc_ids = []
                duplicates = []
                texts_to_extract = []  # For async extraction
                total_docs = len(documents)

                print(f"\n📄 [REST API] Adding batch of {total_docs} documents (fast mode)...")
                for i, doc in enumerate(documents):
                    text = doc.get("text", "")
                    metadata = doc.get("metadata") or {}

                    # Generate markdown content for viewing if not already present
                    if text and 'markdown_content' not in metadata:
                        filename = metadata.get('filename', f'document_{i+1}.txt')
                        extension = metadata.get('extension', '.txt')
                        metadata['markdown_content'] = MarkdownConverter.convert(
                            text=text,
                            filename=filename,
                            extension=extension
                        )

                    if text:
                        # Add document WITHOUT extraction (fast)
                        result = self.vector_store.add_document(
                            text=text,
                            embedding_model=self.embedding_model,
                            metadata=metadata,
                            skip_duplicates=skip_duplicates,
                            topic_labeler=None,
                            extract_key_passages=False,
                            passage_extractor=None,
                            extract_key_entities=False,
                            verbose=False
                        )
                        if isinstance(result, AddDocumentResult):
                            if result.is_duplicate:
                                duplicates.append({
                                    "existing_document_id": result.existing_doc_id,
                                    "content_hash": result.content_hash
                                })
                            else:
                                doc_ids.append(result.doc_id)
                                texts_to_extract.append((result.doc_id, text, metadata))
                        else:
                            doc_ids.append(result)
                            texts_to_extract.append((result, text, metadata))

                # Queue async extractions
                if self.async_extractor and self.passage_extractor and self.passage_extractor.is_available():
                    for doc_id, text, doc_metadata in texts_to_extract:
                        self.async_extractor.queue_extraction(ExtractionTask(
                            doc_id=doc_id,
                            text=text,
                            extract_key_passages=True,
                            extract_key_entities=True,
                            extract_structured_metadata=True,
                            extract_filters=True,
                            source=doc_metadata.get('source'),
                            filename=doc_metadata.get('filename')
                        ))

                return JSONResponse({
                    "success": True,
                    "document_ids": doc_ids,
                    "count": len(doc_ids),
                    "duplicates_skipped": len(duplicates),
                    "duplicates": duplicates,
                    "extraction_queued": len(texts_to_extract),
                    "message": f"Added {len(doc_ids)} documents, skipped {len(duplicates)} duplicates, {len(texts_to_extract)} queued for extraction"
                })
            except Exception as e:
                return JSONResponse(
                    {"error": str(e)},
                    status_code=500
                )

        # REST API endpoint: List documents
        def _get_full_text(doc):
            """Get full text from document, preferring metadata sources over truncated text."""
            full_text = doc.text
            if doc.metadata:
                if doc.metadata.get("markdown_content") and len(doc.metadata["markdown_content"]) > len(full_text):
                    full_text = doc.metadata["markdown_content"]
                elif doc.metadata.get("full_text") and len(doc.metadata["full_text"]) > len(full_text):
                    full_text = doc.metadata["full_text"]
            return full_text

        async def api_list_documents(request):
            """REST API endpoint to list documents with pagination."""
            try:
                page = int(request.query_params.get("page", 1))
                page_size = int(request.query_params.get("page_size", 10))
                ascending = request.query_params.get("ascending", "false").lower() == "true"
                # By default, exclude chunks to show only whole documents
                exclude_chunks = request.query_params.get("exclude_chunks", "true").lower() != "false"

                result = self.vector_store.get_documents_chronological(
                    page=page,
                    page_size=min(page_size, 100),
                    ascending=ascending,
                    exclude_chunks=exclude_chunks
                )

                return JSONResponse({
                    "documents": [
                        {
                            "id": doc.id,
                            "text": _get_full_text(doc),
                            "topics": doc.topics,
                            "primary_topic": doc.primary_topic,
                            "metadata": doc.metadata,
                            "created_at": doc.created_datetime.isoformat()
                        }
                        for doc in result.documents
                    ],
                    "page": result.page,
                    "page_size": result.page_size,
                    "total": result.total,
                    "total_pages": result.total_pages,
                    "has_next": result.has_next,
                    "has_prev": result.has_prev
                })
            except Exception as e:
                return JSONResponse(
                    {"error": str(e)},
                    status_code=500
                )

        # REST API endpoint: Get single document
        async def api_get_document(request):
            """REST API endpoint to get a document by ID."""
            try:
                doc_id = int(request.path_params["doc_id"])
                doc = self.vector_store.get_document(doc_id)

                if doc is None:
                    return JSONResponse(
                        {"success": False, "error": f"Document {doc_id} not found"},
                        status_code=404
                    )

                from datetime import datetime
                return JSONResponse({
                    "success": True,
                    "document": {
                        "id": doc.id,
                        "text": _get_full_text(doc),
                        "metadata": doc.metadata,
                        "created_at": datetime.fromtimestamp(doc.created_at / 1000.0).isoformat(),
                        "topics": doc.topics or [],
                        "primary_topic": doc.primary_topic
                    }
                })
            except ValueError:
                return JSONResponse(
                    {"error": "Invalid document ID"},
                    status_code=400
                )
            except Exception as e:
                return JSONResponse(
                    {"error": str(e)},
                    status_code=500
                )

        # REST API endpoint: Delete document
        async def api_delete_document(request):
            """REST API endpoint to delete a document by ID."""
            try:
                doc_id = int(request.path_params["doc_id"])
                success = self.vector_store.delete_document(doc_id)

                if not success:
                    return JSONResponse(
                        {"success": False, "error": f"Document {doc_id} not found"},
                        status_code=404
                    )

                return JSONResponse({
                    "success": True,
                    "message": f"Document {doc_id} deleted"
                })
            except ValueError:
                return JSONResponse(
                    {"error": "Invalid document ID"},
                    status_code=400
                )
            except Exception as e:
                return JSONResponse(
                    {"error": str(e)},
                    status_code=500
                )

        async def api_clear_all_documents(request):
            """REST API endpoint to delete all documents from the store."""
            try:
                result = self.vector_store.clear_all_documents()
                return JSONResponse({
                    "success": result["success"],
                    "deleted_count": result["deleted_count"],
                    "message": f"Deleted {result['deleted_count']} documents"
                })
            except Exception as e:
                return JSONResponse(
                    {"error": str(e)},
                    status_code=500
                )

        # REST API endpoint: Get stats
        async def api_get_stats(request):
            """REST API endpoint to get vector store statistics."""
            try:
                stats = self.vector_store.get_stats()
                # Add embedding cache stats if available
                cache_stats = self.embedding_model.get_cache_stats()
                if cache_stats is not None:
                    stats["embedding_cache"] = cache_stats
                # Add extraction queue status
                if self.async_extractor:
                    stats["extraction_queue"] = {
                        "pending": self.async_extractor.get_pending_count()
                    }
                return JSONResponse(stats)
            except Exception as e:
                return JSONResponse(
                    {"error": str(e)},
                    status_code=500
                )

        # REST API endpoint: Get model status
        async def api_get_models(request):
            """REST API endpoint to get GPU model loading status."""
            try:
                return JSONResponse({
                    "models": self.model_manager.get_status(),
                    "current_gpu_model": self.model_manager.get_current_gpu_model(),
                    "info": "GPU models are managed dynamically based on current operation."
                })
            except Exception as e:
                return JSONResponse(
                    {"error": str(e)},
                    status_code=500
                )

        # REST API endpoint: Get GPU status (for external service coordination)
        async def api_gpu_status(request):
            """REST API endpoint to get GPU status for coordination with Ollama."""
            try:
                return JSONResponse(self.get_gpu_status())
            except Exception as e:
                return JSONResponse(
                    {"error": str(e)},
                    status_code=500
                )

        # REST API endpoint: Release GPU (for external service coordination)
        async def api_gpu_release(request):
            """REST API endpoint to release GPU for Ollama chat."""
            try:
                result = self.release_gpu()
                status_code = 200 if result.get("success") else 409
                return JSONResponse(result, status_code=status_code)
            except Exception as e:
                return JSONResponse(
                    {"error": str(e)},
                    status_code=500
                )

        # REST API endpoint: Get debug info (system stats, memory, models)
        async def api_debug_info(request):
            """REST API endpoint to get detailed debug information."""
            import psutil
            import os

            try:
                # System memory
                mem = psutil.virtual_memory()
                swap = psutil.swap_memory()

                # Process memory
                process = psutil.Process(os.getpid())
                proc_mem = process.memory_info()

                # GPU memory (Jetson uses unified memory)
                gpu_info = {}
                try:
                    import torch
                    if torch.cuda.is_available():
                        gpu_info = {
                            "cuda_available": True,
                            "device_name": torch.cuda.get_device_name(0),
                            "memory_allocated_mb": round(torch.cuda.memory_allocated(0) / 1024 / 1024, 2),
                            "memory_reserved_mb": round(torch.cuda.memory_reserved(0) / 1024 / 1024, 2),
                            "max_memory_allocated_mb": round(torch.cuda.max_memory_allocated(0) / 1024 / 1024, 2),
                        }
                except Exception as e:
                    gpu_info = {"cuda_available": False, "error": str(e)}

                # Model status
                models = self.model_manager.get_status() if self.model_manager else {}

                # Extraction queue (includes memory-constrained status and current stage)
                if self.async_extractor:
                    extraction = self.async_extractor.get_status()
                else:
                    extraction = {"pending": 0, "running": False, "total_retries": 0, "failed_count": 0, "waiting_for_memory": False, "memory_constrained": False}

                # Add passage extractor availability
                extraction["passage_extractor_available"] = (
                    self.passage_extractor is not None and
                    self.passage_extractor.is_available()
                )

                # Stage device info so frontend can show GPU/CPU badge per stage
                extraction["stage_devices"] = {
                    "passages": "GPU",
                    "entities": "CPU",
                    "metadata": "CPU",
                    "filters": "CPU",
                    "topics": "GPU",
                    "saving": "CPU",
                }

                # Vector store stats
                vs_stats = self.vector_store.get_stats()

                # GPU scheduler status (circuit breaker + memory monitor + refcounts)
                gpu_scheduler = (
                    self.model_manager.get_scheduler_status()
                    if self.model_manager else {}
                )

                return JSONResponse({
                    "system_memory": {
                        "total_mb": round(mem.total / 1024 / 1024, 2),
                        "available_mb": round(mem.available / 1024 / 1024, 2),
                        "used_mb": round(mem.used / 1024 / 1024, 2),
                        "percent_used": mem.percent,
                    },
                    "swap": {
                        "total_mb": round(swap.total / 1024 / 1024, 2),
                        "used_mb": round(swap.used / 1024 / 1024, 2),
                        "percent_used": swap.percent,
                    },
                    "process_memory": {
                        "rss_mb": round(proc_mem.rss / 1024 / 1024, 2),
                        "vms_mb": round(proc_mem.vms / 1024 / 1024, 2),
                    },
                    "gpu": gpu_info,
                    "gpu_scheduler": gpu_scheduler,
                    "models": {
                        "status": models,
                        "current_gpu_model": self.model_manager.get_current_gpu_model() if self.model_manager else None,
                    },
                    "extraction_queue": extraction,
                    "vector_store": {
                        "total_documents": vs_stats.get("total_documents", 0),
                        "total_files": vs_stats.get("total_files", 0),
                    },
                    "pii_protection": {
                        "available": self.pii_protector is not None,
                    }
                })
            except Exception as e:
                import traceback
                return JSONResponse(
                    {"error": str(e), "traceback": traceback.format_exc()},
                    status_code=500
                )

        # REST API endpoint: Get all topics
        async def api_get_all_topics(request):
            """REST API endpoint to get all topics with counts."""
            try:
                topic_counts = self.vector_store.get_all_topics()
                sorted_topics = sorted(topic_counts.items(), key=lambda x: x[1], reverse=True)
                return JSONResponse({
                    "success": True,
                    "total_unique_topics": len(topic_counts),
                    "topics": [
                        {"name": name, "document_count": count}
                        for name, count in sorted_topics
                    ]
                })
            except Exception as e:
                return JSONResponse(
                    {"error": str(e)},
                    status_code=500
                )

        # REST API endpoint: Get documents by topic
        async def api_get_documents_by_topic(request):
            """REST API endpoint to get documents filtered by topic."""
            try:
                topic = request.path_params["topic"]
                page = int(request.query_params.get("page", 1))
                page_size = int(request.query_params.get("page_size", 10))

                result = self.vector_store.get_documents_by_topic(
                    topic=topic,
                    page=page,
                    page_size=min(page_size, 100)
                )

                return JSONResponse({
                    "topic": topic,
                    "documents": [
                        {
                            "id": doc.id,
                            "text": doc.text[:200] + "..." if len(doc.text) > 200 else doc.text,
                            "topics": doc.topics,
                            "primary_topic": doc.primary_topic,
                            "metadata": doc.metadata,
                            "created_at": doc.created_datetime.isoformat()
                        }
                        for doc in result.documents
                    ],
                    "page": result.page,
                    "page_size": result.page_size,
                    "total": result.total,
                    "total_pages": result.total_pages,
                    "has_next": result.has_next,
                    "has_prev": result.has_prev
                })
            except Exception as e:
                return JSONResponse(
                    {"error": str(e)},
                    status_code=500
                )

        # REST API endpoint: Generate topics for a document
        async def api_generate_topics(request):
            """REST API endpoint to generate topics for a document."""
            try:
                doc_id = int(request.path_params["doc_id"])
                body = await request.json()
                num_topics = body.get("num_topics", 3)
                predefined_topics = body.get("predefined_topics")

                if not self.topic_labeler:
                    return JSONResponse({
                        "success": False,
                        "error": "Topic labeler not available"
                    }, status_code=503)

                doc = self.vector_store.get_document(doc_id)
                if not doc:
                    return JSONResponse({
                        "success": False,
                        "error": f"Document {doc_id} not found"
                    }, status_code=404)

                result = self.topic_labeler.generate_topics(
                    text=doc.text,
                    num_topics=num_topics,
                    predefined_topics=predefined_topics
                )

                self.vector_store.update_document_topics(
                    doc_id=doc_id,
                    topics=result.topics,
                    primary_topic=result.primary_topic
                )

                return JSONResponse({
                    "success": True,
                    "doc_id": doc_id,
                    "topics": result.topics,
                    "primary_topic": result.primary_topic,
                    "confidence": result.confidence
                })
            except Exception as e:
                return JSONResponse(
                    {"error": str(e)},
                    status_code=500
                )

        # REST API endpoint: Get topics for a document
        async def api_get_document_topics(request):
            """REST API endpoint to get topics for a document."""
            try:
                doc_id = int(request.path_params["doc_id"])
                result = self.vector_store.get_document_topics(doc_id)

                if not result:
                    return JSONResponse({
                        "success": False,
                        "error": f"Document {doc_id} not found"
                    }, status_code=404)

                return JSONResponse({
                    "success": True,
                    **result
                })
            except Exception as e:
                return JSONResponse(
                    {"error": str(e)},
                    status_code=500
                )

        # REST API endpoint: Update topics for a document
        async def api_update_document_topics(request):
            """REST API endpoint to update topics for a document."""
            try:
                doc_id = int(request.path_params["doc_id"])
                body = await request.json()
                topics = body.get("topics", [])
                primary_topic = body.get("primary_topic")

                if not topics:
                    return JSONResponse({
                        "error": "Topics array is required"
                    }, status_code=400)

                success = self.vector_store.update_document_topics(
                    doc_id=doc_id,
                    topics=topics,
                    primary_topic=primary_topic
                )

                if not success:
                    return JSONResponse({
                        "success": False,
                        "error": f"Document {doc_id} not found"
                    }, status_code=404)

                return JSONResponse({
                    "success": True,
                    "doc_id": doc_id,
                    "topics": topics,
                    "primary_topic": primary_topic or topics[0]
                })
            except Exception as e:
                return JSONResponse(
                    {"error": str(e)},
                    status_code=500
                )

        # REST API endpoint: Search with topic filter
        async def api_search_with_topic(request):
            """REST API endpoint for semantic search with optional topic filtering."""
            try:
                body = await request.json()
                query = body.get("query", "")
                topic = body.get("topic")  # Optional topic filter
                top_k = body.get("top_k", 5)

                if not query:
                    return JSONResponse({
                        "error": "Query is required"
                    }, status_code=400)

                results = self.vector_store.search_with_topic_filter(
                    query=query,
                    topic=topic,
                    limit=min(top_k, 20)
                )

                return JSONResponse({
                    "query": query,
                    "topic_filter": topic,
                    "results": [
                        {
                            "id": r.id,
                            "text": r.text,
                            "score": r.score,
                            "topics": r.topics,
                            "primary_topic": r.primary_topic,
                            "metadata": r.metadata
                        }
                        for r in results
                    ]
                })
            except Exception as e:
                return JSONResponse(
                    {"error": str(e)},
                    status_code=500
                )

        # REST API endpoint: Quick keyword search (FTS5/BM25 only, no GPU)
        async def api_search_quick(request):
            """Fast keyword-only search using FTS5/BM25.

            Zero GPU memory, <5ms latency. Works even when embedding model is not loaded.

            Args (JSON body):
                query: Search query text
                top_k: Number of results (default 10, max 50)
            """
            try:
                body = await request.json()
                query = body.get("query", "")
                top_k = body.get("top_k", 10)

                if not query:
                    return JSONResponse({"error": "Query is required"}, status_code=400)

                import time as _time
                start = _time.monotonic()

                results = self.vector_store.search_keyword(
                    query=query,
                    limit=min(top_k, 50)
                )

                latency_ms = round((_time.monotonic() - start) * 1000, 1)

                return JSONResponse({
                    "query": query,
                    "search_mode": "keyword",
                    "latency_ms": latency_ms,
                    "results": [
                        {
                            "id": r.id,
                            "text": r.text,
                            "score": r.score,
                            "topics": r.topics,
                            "primary_topic": r.primary_topic,
                            "metadata": r.metadata
                        }
                        for r in results
                    ]
                })
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        # REST API endpoint: File system search (unindexed content)
        async def api_search_files(request):
            """Search raw files that may not be indexed yet.

            Grep-style search through uploads, imports, exports, and conversations.
            Zero GPU memory, CPU-only.

            Args (JSON body):
                query: Search text
                directories: List of dirs to search (default: all)
                max_results: Max file results (default 20)
                case_sensitive: Case-sensitive search (default false)
            """
            from .file_searcher import FileSearcher
            try:
                body = await request.json()
                query = body.get("query", "")
                directories = body.get("directories")
                max_results = body.get("max_results", 20)
                case_sensitive = body.get("case_sensitive", False)

                if not query:
                    return JSONResponse({"error": "Query is required"}, status_code=400)

                import time as _time
                start = _time.monotonic()

                searcher = FileSearcher(data_dir=self._get_data_dir())
                results = searcher.search(
                    query=query,
                    directories=directories,
                    max_results=min(max_results, 100),
                    case_sensitive=case_sensitive
                )

                latency_ms = round((_time.monotonic() - start) * 1000, 1)

                return JSONResponse({
                    "query": query,
                    "latency_ms": latency_ms,
                    "results": [
                        {
                            "filename": r.filename,
                            "path": r.path,
                            "source": r.source,
                            "file_size": r.file_size,
                            "matches": [
                                {
                                    "line": m.line_number,
                                    "text": m.text,
                                    "context_before": m.context_before,
                                    "context_after": m.context_after
                                }
                                for m in r.matches
                            ]
                        }
                        for r in results
                    ]
                })
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        # REST API endpoint: Metadata search
        async def api_search_metadata(request):
            """Search documents by metadata fields — no vector similarity.

            Pure SQLite query on metadata, zero GPU.

            Args (JSON body):
                filename: Glob pattern (e.g., "*.pdf")
                source: Source filter ("import", "connector", "browser")
                date_from: ISO date minimum
                date_to: ISO date maximum
                topic: Topic filter
                top_k: Max results (default 50)
            """
            try:
                body = await request.json()
                filename = body.get("filename")
                source = body.get("source")
                date_from = body.get("date_from")
                date_to = body.get("date_to")
                topic = body.get("topic")
                top_k = body.get("top_k", 50)

                import time as _time
                start = _time.monotonic()

                results = self.vector_store.search_metadata(
                    limit=min(top_k, 200),
                    filename=filename,
                    source=source,
                    date_from=date_from,
                    date_to=date_to,
                    topic=topic
                )

                latency_ms = round((_time.monotonic() - start) * 1000, 1)

                return JSONResponse({
                    "filters": {
                        "filename": filename,
                        "source": source,
                        "date_from": date_from,
                        "date_to": date_to,
                        "topic": topic
                    },
                    "latency_ms": latency_ms,
                    "results": [
                        {
                            "id": r.id,
                            "text": r.text,
                            "score": r.score,
                            "topics": r.topics,
                            "primary_topic": r.primary_topic,
                            "metadata": r.metadata
                        }
                        for r in results
                    ]
                })
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        # REST API endpoint: Unified tiered search
        async def api_search_unified(request):
            """Smart tiered search that cascades through available search modes.

            Automatically uses the best search tier available:
            - fast: keyword only (<5ms, no GPU)
            - balanced: keyword + semantic (~15ms)
            - quality: keyword + semantic + reranking (~100ms)

            Args (JSON body):
                query: Search query text
                top_k: Number of results (default 10, max 20)
                mode: "fast" | "balanced" | "quality" (default "balanced")
                weights: Hybrid fusion balance (0.0=keyword, 0.5=balanced, 1.0=semantic).
                         None uses txtai default. Only applies to balanced/quality modes.
                include_unindexed: Search raw files too (default false)
            """
            from .model_manager import ModelType
            try:
                body = await request.json()
                query = body.get("query", "")
                top_k = body.get("top_k", 10)
                mode = body.get("mode", "balanced")
                weights = body.get("weights", None)
                include_unindexed = body.get("include_unindexed", False)

                if not query:
                    return JSONResponse({"error": "Query is required"}, status_code=400)

                effective_top_k = min(top_k, 20)

                import time as _time
                import asyncio
                start = _time.monotonic()

                tiers_used = []
                all_results = {}  # id -> result dict (dedup by id)
                unindexed_results = []

                # Tier 1: Keyword search (always runs)
                try:
                    keyword_results = self.vector_store.search_keyword(
                        query=query,
                        limit=effective_top_k * 2
                    )
                    tiers_used.append("keyword")
                    for r in keyword_results:
                        all_results[r.id] = {
                            "id": r.id,
                            "text": r.text,
                            "score": r.score,
                            "topics": r.topics,
                            "primary_topic": r.primary_topic,
                            "metadata": r.metadata
                        }
                except Exception:
                    pass

                # Tier 2: Semantic search (balanced + quality modes)
                if mode in ("balanced", "quality"):
                    try:
                        semantic_results = self.vector_store.search(
                            query=query,
                            top_k=effective_top_k * 2,
                            weights=weights
                        )
                        tiers_used.append("semantic")
                        for r in semantic_results:
                            existing = all_results.get(r.id)
                            if existing:
                                # Keep higher score
                                existing["score"] = max(existing["score"], r.score)
                            else:
                                all_results[r.id] = {
                                    "id": r.id,
                                    "text": r.text,
                                    "score": r.score,
                                    "topics": r.topics,
                                    "primary_topic": r.primary_topic,
                                    "metadata": r.metadata
                                }
                    except Exception:
                        pass

                # Tier 3: Reranking (quality mode only)
                if mode == "quality" and all_results:
                    try:
                        reranker = self._ensure_reranker()
                        if reranker and reranker.is_available():
                            self.model_manager.ensure_loaded(ModelType.RERANKER)
                            # Build tuples: (id, text, score, metadata)
                            result_list = list(all_results.values())
                            docs_for_rerank = [
                                (r["id"], r["text"], r["score"], r.get("metadata"))
                                for r in result_list
                            ]
                            reranked = reranker.rerank(query, docs_for_rerank, top_k=effective_top_k)
                            tiers_used.append("reranked")
                            # Build lookup for topic info from original results
                            topic_lookup = {r["id"]: (r.get("topics"), r.get("primary_topic"))
                                            for r in result_list}
                            # Replace all_results with reranked order and scores
                            all_results = {}
                            for rr in reranked:
                                topics, primary_topic = topic_lookup.get(rr.id, (None, None))
                                all_results[rr.id] = {
                                    "id": rr.id,
                                    "text": rr.text,
                                    "score": rr.rerank_score,
                                    "metadata": rr.metadata,
                                    "topics": topics,
                                    "primary_topic": primary_topic
                                }
                    except Exception:
                        pass

                # Tier 4: File system search (if requested)
                if include_unindexed:
                    try:
                        from .file_searcher import FileSearcher
                        searcher = FileSearcher(data_dir=self._get_data_dir())
                        file_results = searcher.search(
                            query=query,
                            max_results=10
                        )
                        if file_results:
                            tiers_used.append("files")
                            unindexed_results = [
                                {
                                    "filename": r.filename,
                                    "path": r.path,
                                    "source": r.source,
                                    "file_size": r.file_size,
                                    "matches": [
                                        {
                                            "line": m.line_number,
                                            "text": m.text,
                                        }
                                        for m in r.matches[:3]  # Limit matches per file
                                    ]
                                }
                                for r in file_results
                            ]
                    except Exception:
                        pass

                # Sort by score descending and return top_k
                sorted_results = sorted(
                    all_results.values(),
                    key=lambda r: r["score"],
                    reverse=True
                )[:effective_top_k]

                latency_ms = round((_time.monotonic() - start) * 1000, 1)

                return JSONResponse({
                    "query": query,
                    "mode": mode,
                    "tiers_used": tiers_used,
                    "latency_ms": latency_ms,
                    "results": sorted_results,
                    "unindexed_results": unindexed_results
                })
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        # REST API endpoint: Reranked search (two-phase coarse-to-fine)
        async def api_search_reranked(request):
            """Two-phase search: broad hybrid retrieval + cross-encoder reranking.

            Args (JSON body):
                query: Search query text
                top_k: Number of results (default 10, max 20)
                min_score: Minimum similarity threshold (default 0.0)
                overfetch_factor: Candidates = top_k * factor (default 3)
            """
            from .model_manager import ModelType
            try:
                body = await request.json()
                query = body.get("query", "")
                top_k = body.get("top_k", 10)
                min_score = body.get("min_score", 0.0)
                overfetch_factor = body.get("overfetch_factor", 3)

                if not query:
                    return JSONResponse({"error": "Query is required"}, status_code=400)

                effective_top_k = min(top_k, 20)

                import time as _time
                start = _time.monotonic()

                reranker = self._ensure_reranker()
                if reranker and reranker.is_available():
                    self.model_manager.ensure_loaded(ModelType.RERANKER)
                else:
                    reranker = None

                results = self.vector_store.search_reranked(
                    query=query,
                    limit=effective_top_k,
                    min_score=min_score,
                    overfetch_factor=overfetch_factor,
                    reranker=reranker,
                    deduplicate_chunks=True
                )

                latency_ms = round((_time.monotonic() - start) * 1000, 1)

                return JSONResponse({
                    "query": query,
                    "reranker_used": reranker is not None,
                    "latency_ms": latency_ms,
                    "results": [
                        {
                            "id": r.id,
                            "text": r.text,
                            "score": r.score,
                            "topics": r.topics,
                            "primary_topic": r.primary_topic,
                            "metadata": r.metadata
                        }
                        for r in results
                    ]
                })
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        # REST API endpoint: Get knowledge graph
        async def api_get_knowledge_graph(request):
            """REST API endpoint to get knowledge graph data for visualization."""
            try:
                body = await request.json()
                input_data = KnowledgeGraphInput(**body)

                graph_data = self.vector_store.get_knowledge_graph(
                    include_documents=input_data.include_documents,
                    include_topics=input_data.include_topics,
                    include_entities=input_data.include_entities,
                    entity_types=input_data.entity_types,
                    min_connections=input_data.min_connections,
                    limit_documents=input_data.limit_documents,
                    limit_entities_per_type=input_data.limit_entities_per_type,
                    max_topic_edges_per_doc=input_data.max_topic_edges_per_doc,
                    max_entity_edges_per_doc=input_data.max_entity_edges_per_doc
                )

                return JSONResponse(graph_data)
            except Exception as e:
                return JSONResponse(
                    {"error": str(e)},
                    status_code=500
                )

        # REST API endpoint: Get node details
        async def api_get_graph_node(request):
            """REST API endpoint to get details for a specific graph node."""
            try:
                node_id = request.path_params["node_id"]

                # Parse node_id to determine type and lookup
                if node_id.startswith("doc_"):
                    doc_identifier = node_id[4:]

                    # Parse as integer (format: doc_123 where 123 is the parent doc ID)
                    try:
                        parent_id = int(doc_identifier)
                    except ValueError:
                        return JSONResponse(
                            {"error": f"Invalid document ID format: {doc_identifier}"},
                            status_code=400
                        )

                    # Get the parent document
                    parent_doc = self.vector_store.get_document(parent_id)
                    if not parent_doc:
                        return JSONResponse(
                            {"error": f"Document {parent_id} not found"},
                            status_code=404
                        )

                    # Find all chunks that belong to this parent
                    chunks = self.vector_store.get_document_chunks(parent_id)

                    # Aggregate data from parent and all chunks
                    # Convert ChunkInfo to objects with metadata for uniform processing
                    chunk_docs = []
                    for chunk in chunks:
                        chunk_doc = self.vector_store.get_document(chunk.chunk_id)
                        if chunk_doc:
                            chunk_docs.append(chunk_doc)
                    all_related = [parent_doc] + chunk_docs
                    all_topics = set()
                    all_persons = set()
                    all_orgs = set()
                    all_locations = set()
                    all_technologies = set()
                    total_text_length = 0

                    for d in all_related:
                        meta = d.metadata or {}
                        struct_meta = meta.get('structured_metadata', {})

                        topics = meta.get('topics', [])
                        if isinstance(topics, str):
                            topics = [topics]
                        all_topics.update(t for t in topics if t)

                        all_persons.update(p for p in struct_meta.get('persons', []) if p)
                        all_orgs.update(o for o in struct_meta.get('organizations', []) if o)
                        all_locations.update(l for l in struct_meta.get('locations', []) if l)
                        all_technologies.update(t for t in struct_meta.get('technologies', []) if t)

                        if d.text:
                            total_text_length += len(d.text)

                    from datetime import datetime
                    metadata = parent_doc.metadata or {}
                    filename = metadata.get('filename')

                    return JSONResponse({
                        "id": node_id,
                        "type": "document",
                        "label": metadata.get('title') or filename or f"Document {parent_id}",
                        "details": {
                            "doc_id": parent_id,
                            "filename": filename,
                            "text": parent_doc.text[:500] if parent_doc.text else None,
                            "text_length": total_text_length,
                            "chunk_count": len(chunks),
                            "topics": list(all_topics),
                            "persons": list(all_persons),
                            "organizations": list(all_orgs),
                            "locations": list(all_locations),
                            "technologies": list(all_technologies),
                            "created_at": datetime.fromtimestamp(parent_doc.created_at / 1000.0).isoformat() if parent_doc.created_at else None
                        }
                    })
                elif node_id.startswith("topic_"):
                    topic = node_id[6:]
                    # Get documents with this topic
                    result = self.vector_store.get_documents_by_topic(topic=topic, page=1, page_size=10)
                    return JSONResponse({
                        "id": node_id,
                        "type": "topic",
                        "label": topic.title(),
                        "details": {
                            "topic": topic,
                            "document_count": result.total,
                            "sample_documents": [
                                {
                                    "id": d.id,
                                    "title": d.metadata.get('title') or d.metadata.get('filename') if d.metadata else None,
                                    "text_preview": d.text[:200] if d.text else None
                                }
                                for d in result.documents[:5]
                            ]
                        }
                    })
                else:
                    # Entity node (person_, organization_, location_, technology_)
                    entity_type = None
                    entity_name = None
                    for prefix in ['person_', 'organization_', 'location_', 'technology_']:
                        if node_id.startswith(prefix):
                            entity_type = prefix[:-1]
                            entity_name = node_id[len(prefix):]
                            break

                    if not entity_type:
                        return JSONResponse(
                            {"error": f"Unknown node type: {node_id}"},
                            status_code=400
                        )

                    # Find documents with this entity
                    entity_docs = []
                    if entity_type == 'person':
                        entity_docs = self.vector_store.find_by_person(entity_name)
                    elif entity_type == 'organization':
                        entity_docs = self.vector_store.find_by_organization(entity_name)
                    elif entity_type == 'location':
                        entity_docs = self.vector_store.find_by_location(entity_name)
                    elif entity_type == 'technology':
                        entity_docs = self.vector_store.find_by_technology(entity_name)

                    return JSONResponse({
                        "id": node_id,
                        "type": entity_type,
                        "label": entity_name.title(),
                        "details": {
                            "entity_name": entity_name,
                            "entity_type": entity_type,
                            "document_count": len(entity_docs),
                            "sample_documents": [
                                {
                                    "id": d.id,
                                    "title": d.metadata.get('title') or d.metadata.get('filename') if d.metadata else None,
                                    "text_preview": d.text[:200] if d.text else None
                                }
                                for d in entity_docs[:5]
                            ]
                        }
                    })
            except Exception as e:
                return JSONResponse(
                    {"error": str(e)},
                    status_code=500
                )

        # PII Protection REST API endpoints
        async def api_pii_anonymize(request):
            """REST API endpoint to anonymize text by detecting and replacing PII.

            SECURITY: Restricted to localhost/on-device clients only.
            This endpoint creates PII sessions that can map back to original PII,
            so it must not be accessible to remote clients.
            """
            from .consent_manager import get_consent_manager

            try:
                # SECURITY: Enforce localhost-only access
                client_ip = self._get_client_ip_secure(request)
                if not self._is_localhost(client_ip):
                    return JSONResponse(
                        {"error": "Access denied: PII anonymization API is only available to on-device clients"},
                        status_code=403
                    )

                body = await request.json()
                text = body.get("text", "")
                session_id = body.get("session_id")  # Optional PII session - creates new if not provided
                consent_session_id = body.get("consent_session_id")  # Optional consent session for PII type rules

                if not text:
                    return JSONResponse(
                        {"error": "'text' is required"},
                        status_code=400
                    )

                if not self.pii_protector:
                    return JSONResponse(
                        {"error": "PII protection not available"},
                        status_code=503
                    )

                # Get exposed PII types from consent session if provided
                exposed_pii_types = None
                if consent_session_id:
                    consent_manager = get_consent_manager()
                    consent_session = consent_manager.get_session(consent_session_id)
                    if consent_session:
                        exposed_pii_types = consent_session.exposed_pii_types
                        print(f"Anonymize: consent session {consent_session_id} found, exposed_pii_types={list(exposed_pii_types)}")
                    else:
                        print(f"Anonymize: consent session {consent_session_id} not found (may have expired)")

                result = self.pii_protector.anonymize(
                    text=text,
                    session_id=session_id,
                    exposed_pii_types=exposed_pii_types
                )

                return JSONResponse({
                    "anonymized_text": result.anonymized_text,
                    "session_id": result.session_id,
                    "token_count": result.token_count,
                    "pii_types_found": result.pii_types_found,
                    "processing_time_ms": result.processing_time_ms,
                    "consent_applied": consent_session_id is not None,
                    "exposed_pii_types": list(exposed_pii_types) if exposed_pii_types else [],
                    "perturbed_values": [
                        {
                            "pii_type": pv.pii_type,
                            "perturbed_value": pv.perturbed_value,
                            "is_lprag": pv.is_lprag
                        }
                        for pv in result.perturbed_values
                    ] if result.perturbed_values else []
                })
            except Exception as e:
                return JSONResponse(
                    {"error": str(e)},
                    status_code=500
                )

        async def api_pii_deanonymize(request):
            """REST API endpoint to de-anonymize text containing PII tokens.

            SECURITY: Restricted to localhost/on-device clients only.
            This prevents remote clients from reversing PII anonymization.
            """
            try:
                # SECURITY: Enforce localhost-only access (matches MCP tool restriction)
                client_ip = self._get_client_ip_secure(request)
                if not self._is_localhost(client_ip):
                    return JSONResponse(
                        {"error": "Access denied: de-anonymization is only available to on-device clients"},
                        status_code=403
                    )

                body = await request.json()
                text = body.get("text", "")
                session_id = body.get("session_id", "")

                if not text or not session_id:
                    return JSONResponse(
                        {"error": "Both 'text' and 'session_id' are required"},
                        status_code=400
                    )

                if not self.pii_protector:
                    return JSONResponse(
                        {"error": "PII protection not available"},
                        status_code=503
                    )

                # REST API does not require auth token (access controlled by localhost check)
                result = self.pii_protector.deanonymize(
                    text=text,
                    session_id=session_id,
                    require_auth=False
                )

                # Check for session errors
                if "SESSION_NOT_FOUND" in result.tokens_not_found:
                    return JSONResponse(
                        {"error": "Session not found"},
                        status_code=404
                    )

                if "SESSION_EXPIRED" in result.tokens_not_found:
                    return JSONResponse(
                        {"error": "Session expired"},
                        status_code=410
                    )

                return JSONResponse({
                    "deanonymized_text": result.deanonymized_text,
                    "session_id": result.session_id,
                    "tokens_replaced": result.tokens_replaced,
                    "tokens_not_found": result.tokens_not_found
                })
            except Exception as e:
                return JSONResponse(
                    {"error": str(e)},
                    status_code=500
                )

        async def api_pii_status(request):
            """REST API endpoint to get PII protection status and statistics."""
            if not self.pii_protector:
                return JSONResponse({
                    "enabled": False,
                    "reason": "Presidio not installed or initialization failed"
                })

            stats = self.pii_protector.get_stats()
            return JSONResponse({
                "enabled": True,
                **stats
            })

        async def api_pii_session_info(request):
            """REST API endpoint to get information about a PII session.

            SECURITY: Restricted to localhost/on-device clients only.
            """
            # SECURITY: Enforce localhost-only access
            client_ip = self._get_client_ip_secure(request)
            if not self._is_localhost(client_ip):
                return JSONResponse(
                    {"error": "Access denied: PII session info is only available to on-device clients"},
                    status_code=403
                )

            session_id = request.path_params.get("session_id")

            if not self.pii_protector:
                return JSONResponse(
                    {"error": "PII protection not available"},
                    status_code=503
                )

            info = self.pii_protector.get_session_info(session_id)
            if not info:
                return JSONResponse(
                    {"error": "Session not found"},
                    status_code=404
                )

            return JSONResponse(info)

        async def api_pii_clear_session(request):
            """REST API endpoint to clear a PII session.

            SECURITY: Restricted to localhost/on-device clients only.
            """
            # SECURITY: Enforce localhost-only access
            client_ip = self._get_client_ip_secure(request)
            if not self._is_localhost(client_ip):
                return JSONResponse(
                    {"error": "Access denied: PII session management is only available to on-device clients"},
                    status_code=403
                )

            session_id = request.path_params.get("session_id")

            if not self.pii_protector:
                return JSONResponse(
                    {"error": "PII protection not available"},
                    status_code=503
                )

            cleared = self.pii_protector.clear_session(session_id)
            return JSONResponse({
                "cleared": cleared,
                "session_id": session_id
            })

        async def api_pii_refresh_session(request):
            """REST API endpoint to refresh a PII session's TTL (sliding expiration).

            Useful for clients that want to keep a session alive while the user
            is actively using the application, without performing a deanonymize.

            SECURITY: Restricted to localhost/on-device clients only.
            """
            # SECURITY: Enforce localhost-only access
            client_ip = self._get_client_ip_secure(request)
            if not self._is_localhost(client_ip):
                return JSONResponse(
                    {"error": "Access denied: PII session management is only available to on-device clients"},
                    status_code=403
                )

            session_id = request.path_params.get("session_id")

            if not self.pii_protector:
                return JSONResponse(
                    {"error": "PII protection not available"},
                    status_code=503
                )

            info = self.pii_protector.refresh_session(session_id)
            if not info:
                return JSONResponse(
                    {"error": "Session not found or expired"},
                    status_code=404
                )

            return JSONResponse({
                "refreshed": True,
                **info
            })

        # LPRAG API endpoints
        async def api_lprag_status(request):
            """REST API endpoint to get LPRAG status and configuration."""
            if not self.pii_protector:
                return JSONResponse({
                    "enabled": False,
                    "reason": "PII protector not initialized"
                })

            stats = self.pii_protector.get_stats()
            lprag_stats = stats.get("lprag", {})

            return JSONResponse({
                "enabled": lprag_stats.get("mode", "token_only") != "token_only",
                "mode": lprag_stats.get("mode", "token_only"),
                "lprag_available": lprag_stats.get("available", False),
                "initialized": lprag_stats.get("initialized", False),
                "error": lprag_stats.get("init_error"),
                "total_perturbed_values": stats.get("total_perturbed_values", 0),
                "engine": lprag_stats.get("engine", {})
            })

        async def api_lprag_config(request):
            """REST API endpoint to get or update LPRAG configuration."""
            if request.method == "GET":
                # Return current configuration
                if not self.pii_protector:
                    return JSONResponse({
                        "error": "PII protector not initialized"
                    }, status_code=503)

                stats = self.pii_protector.get_stats()
                lprag_stats = stats.get("lprag", {})

                # Return configuration info
                return JSONResponse({
                    "mode": lprag_stats.get("mode", "token_only"),
                    "available": lprag_stats.get("available", False),
                    "initialized": lprag_stats.get("initialized", False),
                    "engine": lprag_stats.get("engine", {}),
                    "note": "Configuration is set via environment variables: LPRAG_MODE, LPRAG_PRESET, LPRAG_EPSILON"
                })
            else:
                # PUT - configuration changes require server restart
                return JSONResponse({
                    "error": "Runtime configuration updates not yet supported",
                    "note": "Set LPRAG_MODE, LPRAG_PRESET, or LPRAG_EPSILON environment variables and restart the server"
                }, status_code=501)

        # Image PII Detection and Redaction REST API endpoints
        async def api_image_pii_status(request):
            """REST API endpoint to get image PII redaction status."""
            if not self.image_pii_redactor:
                return JSONResponse({
                    "available": False,
                    "reason": "Image PII redactor not initialized. Install easyocr or pytesseract."
                })

            return JSONResponse({
                "available": self.image_pii_redactor.is_available(),
                "ocr_engine": self.image_pii_redactor._ocr_engine.value,
                "use_gpu": self.image_pii_redactor._use_gpu,
                "is_loaded": self.image_pii_redactor.is_loaded(),
                "redaction_color": list(self.image_pii_redactor.redaction_color),
                "use_blur": self.image_pii_redactor.use_blur,
                "blur_radius": self.image_pii_redactor.blur_radius,
                "padding": self.image_pii_redactor.padding,
                "languages": self.image_pii_redactor.languages,
                "supported_formats": list(IMAGE_EXTENSIONS),
            })

        async def api_image_pii_detect(request):
            """REST API endpoint to detect PII regions in an image (without redaction).

            Accepts multipart/form-data with a 'file' field.
            Returns detected PII regions with bounding boxes.
            """
            import tempfile

            if not self.image_pii_redactor:
                return JSONResponse({
                    "error": "Image PII redactor not available"
                }, status_code=503)

            try:
                form = await request.form()
                upload = form.get("file")
                if upload is None or not hasattr(upload, 'filename'):
                    return JSONResponse({
                        "error": "No file uploaded. Send multipart/form-data with a 'file' field."
                    }, status_code=400)

                filename = upload.filename or "unknown"
                session_id = form.get("session_id")

                # Check if it's a supported image format
                ext = os.path.splitext(filename)[1].lower()
                if ext not in IMAGE_EXTENSIONS:
                    return JSONResponse({
                        "error": f"Unsupported image format: {ext}. Supported: {', '.join(sorted(IMAGE_EXTENSIONS))}"
                    }, status_code=400)

                # Read and save to temp file
                content = await upload.read()
                if len(content) == 0:
                    return JSONResponse({"error": "Uploaded file is empty."}, status_code=400)

                fd, temp_path = tempfile.mkstemp(suffix=ext)
                try:
                    with os.fdopen(fd, 'wb') as f:
                        f.write(content)

                    # Detect PII regions
                    regions, ocr_result = self.image_pii_redactor.detect_pii_regions(
                        temp_path,
                        session_id=session_id,
                    )

                    return JSONResponse({
                        "success": True,
                        "filename": filename,
                        "regions": [
                            {
                                "pii_type": r.pii_type,
                                "text": r.original_text,
                                "bounding_box": {
                                    "x": r.x,
                                    "y": r.y,
                                    "width": r.width,
                                    "height": r.height,
                                },
                                "confidence": r.confidence,
                            }
                            for r in regions
                        ],
                        "ocr_text": ocr_result.text,
                        "ocr_engine": ocr_result.engine,
                        "processing_time_ms": ocr_result.processing_time_ms,
                    })
                finally:
                    os.unlink(temp_path)

            except Exception as e:
                return JSONResponse({
                    "error": f"Image PII detection failed: {str(e)}"
                }, status_code=500)

        async def api_image_pii_redact(request):
            """REST API endpoint to detect and redact PII in an image.

            Accepts multipart/form-data with:
            - file: Image file
            - redaction_color (optional): "black", "white", or hex color
            - use_blur (optional): "true" or "false"
            - store_original (optional): "true" or "false"
            - session_id (optional): PII session ID for tracking

            Returns redacted image metadata and URL.
            """
            import tempfile
            from pathlib import Path

            if not self.image_pii_redactor:
                return JSONResponse({
                    "error": "Image PII redactor not available"
                }, status_code=503)

            try:
                form = await request.form()
                upload = form.get("file")
                if upload is None or not hasattr(upload, 'filename'):
                    return JSONResponse({
                        "error": "No file uploaded. Send multipart/form-data with a 'file' field."
                    }, status_code=400)

                filename = upload.filename or "unknown"
                session_id = form.get("session_id")
                store_original = form.get("store_original", "true").lower() == "true"

                # Parse optional redaction options
                redaction_color_str = form.get("redaction_color")
                use_blur_str = form.get("use_blur")

                # Check if it's a supported image format
                ext = os.path.splitext(filename)[1].lower()
                if ext not in IMAGE_EXTENSIONS:
                    return JSONResponse({
                        "error": f"Unsupported image format: {ext}. Supported: {', '.join(sorted(IMAGE_EXTENSIONS))}"
                    }, status_code=400)

                # Read and save to temp file
                content = await upload.read()
                if len(content) == 0:
                    return JSONResponse({"error": "Uploaded file is empty."}, status_code=400)

                fd, temp_path = tempfile.mkstemp(suffix=ext)
                try:
                    with os.fdopen(fd, 'wb') as f:
                        f.write(content)

                    # Temporarily override redaction settings if provided
                    original_color = self.image_pii_redactor.redaction_color
                    original_blur = self.image_pii_redactor.use_blur

                    if redaction_color_str:
                        from .image_pii_redactor import parse_color
                        self.image_pii_redactor.redaction_color = parse_color(redaction_color_str)
                    if use_blur_str:
                        self.image_pii_redactor.use_blur = use_blur_str.lower() == "true"

                    try:
                        # Redact image
                        result = self.image_pii_redactor.redact_image(
                            temp_path,
                            session_id=session_id,
                            store_original=store_original,
                        )
                    finally:
                        # Restore original settings
                        self.image_pii_redactor.redaction_color = original_color
                        self.image_pii_redactor.use_blur = original_blur

                    # Build response
                    response_data = {
                        "success": True,
                        "filename": filename,
                        "redacted_image_path": result.redacted_image_path,
                        "original_stored": result.original_image_path is not None,
                        "regions_redacted": len(result.regions_redacted),
                        "pii_types_found": list(set(r.pii_type for r in result.regions_redacted)),
                        "session_id": result.session_id,
                        "processing_time_ms": result.processing_time_ms,
                        "ocr_engine": result.ocr_engine,
                    }

                    # Include detailed regions info
                    response_data["regions"] = [
                        {
                            "pii_type": r.pii_type,
                            "bounding_box": {
                                "x": r.x,
                                "y": r.y,
                                "width": r.width,
                                "height": r.height,
                            },
                            "confidence": r.confidence,
                        }
                        for r in result.regions_redacted
                    ]

                    return JSONResponse(response_data)

                finally:
                    os.unlink(temp_path)

            except Exception as e:
                return JSONResponse({
                    "error": f"Image PII redaction failed: {str(e)}"
                }, status_code=500)

        async def api_image_serve(request):
            """REST API endpoint to serve stored images.

            Serves images from either the uploads directory (original) or
            redacted directory based on the context parameter.

            Path parameter:
                image_id: The unique image ID (e.g., 'abc123def456')

            Query parameters:
                context: 'user' (default) returns original, 'llm' returns redacted
                type: 'original' or 'redacted' (overrides context)
            """
            from starlette.responses import FileResponse

            image_id = request.path_params.get("image_id", "")
            context = request.query_params.get("context", "user")
            type_param = request.query_params.get("type")

            if not image_id:
                return JSONResponse({
                    "error": "Missing image_id parameter"
                }, status_code=400)

            # Get image storage manager
            if not self.image_storage:
                return JSONResponse({
                    "error": "Image storage not available"
                }, status_code=503)

            # Determine which image to serve
            if type_param:
                # Explicit type parameter overrides context
                serve_context = "llm" if type_param == "redacted" else "user"
            else:
                # Use context parameter
                serve_context = context

            image_path = self.image_storage.get_image_path(image_id, context=serve_context)

            if not image_path or not os.path.exists(image_path):
                return JSONResponse({
                    "error": f"Image not found: {image_id}"
                }, status_code=404)

            # Determine media type from extension
            ext = os.path.splitext(image_path)[1].lower()
            media_types = {
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".png": "image/png",
                ".gif": "image/gif",
                ".webp": "image/webp",
                ".bmp": "image/bmp",
            }
            media_type = media_types.get(ext, "application/octet-stream")

            return FileResponse(
                image_path,
                media_type=media_type,
                headers={
                    "Cache-Control": "public, max-age=3600",  # Cache for 1 hour
                }
            )

        async def api_image_base64(request):
            """REST API endpoint to get base64-encoded image data for LLM multimodal input.

            Returns the image as base64 data suitable for sending to multimodal LLMs
            like Claude, GPT-4V, or Gemini.

            Path parameter:
                image_id: The unique image ID (e.g., 'abc123def456')

            Query parameters:
                context: 'llm' (default) returns redacted, 'user' returns original
                max_size: Maximum dimension (width or height) to resize to (optional)
            """
            import base64

            image_id = request.path_params.get("image_id", "")
            context = request.query_params.get("context", "llm")  # Default to redacted for LLM
            max_size = request.query_params.get("max_size")

            if not image_id:
                return JSONResponse({
                    "error": "Missing image_id parameter"
                }, status_code=400)

            # Get image storage manager
            if not self.image_storage:
                return JSONResponse({
                    "error": "Image storage not available"
                }, status_code=503)

            # Get the image path (default to LLM context = redacted)
            image_path = self.image_storage.get_image_path(image_id, context=context)

            if not image_path or not os.path.exists(image_path):
                return JSONResponse({
                    "error": f"Image not found: {image_id}"
                }, status_code=404)

            try:
                # Determine media type from extension
                ext = os.path.splitext(image_path)[1].lower()
                media_types = {
                    ".jpg": "image/jpeg",
                    ".jpeg": "image/jpeg",
                    ".png": "image/png",
                    ".gif": "image/gif",
                    ".webp": "image/webp",
                    ".bmp": "image/bmp",
                }
                media_type = media_types.get(ext, "image/jpeg")

                # Read and optionally resize image
                if max_size:
                    try:
                        from PIL import Image
                        import io

                        max_dim = int(max_size)
                        with Image.open(image_path) as img:
                            # Resize if larger than max_size
                            if img.width > max_dim or img.height > max_dim:
                                img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)

                            # Convert to bytes
                            buffer = io.BytesIO()
                            img_format = "JPEG" if ext in [".jpg", ".jpeg"] else ext[1:].upper()
                            if img_format == "JPG":
                                img_format = "JPEG"
                            img.save(buffer, format=img_format)
                            image_data = buffer.getvalue()
                    except Exception as resize_err:
                        print(f"Warning: Failed to resize image, using original: {resize_err}")
                        with open(image_path, "rb") as f:
                            image_data = f.read()
                else:
                    with open(image_path, "rb") as f:
                        image_data = f.read()

                # Encode to base64
                base64_data = base64.b64encode(image_data).decode("utf-8")

                return JSONResponse({
                    "success": True,
                    "image_id": image_id,
                    "media_type": media_type,
                    "base64_data": base64_data,
                    "context": context,
                    "size_bytes": len(image_data),
                })

            except Exception as e:
                return JSONResponse({
                    "error": f"Failed to encode image: {str(e)}"
                }, status_code=500)

        async def api_audio_serve(request):
            """REST API endpoint to serve stored audio files.

            Serves audio files from the uploads/audio directory.

            Path parameter:
                audio_id: The unique audio ID (e.g., 'abc123def456')

            Query parameters:
                type: 'original' (default) or 'redacted'
            """
            from starlette.responses import FileResponse

            audio_id = request.path_params.get("audio_id", "")
            type_param = request.query_params.get("type", "original")

            if not audio_id:
                return JSONResponse({
                    "error": "Missing audio_id parameter"
                }, status_code=400)

            # Find audio file in uploads directory
            audio_dir = os.path.join(self.data_dir, "uploads", "audio")
            redacted_dir = os.path.join(self.data_dir, "redacted", "audio")

            # Search for audio file with any extension
            audio_path = None
            search_dir = redacted_dir if type_param == "redacted" else audio_dir

            if os.path.exists(search_dir):
                for filename in os.listdir(search_dir):
                    # Match audio_id with or without _redacted suffix
                    base_name = os.path.splitext(filename)[0]
                    if type_param == "redacted":
                        # For redacted, look for files ending with _redacted or matching audio_id
                        if base_name == f"{audio_id}_redacted" or base_name == audio_id:
                            audio_path = os.path.join(search_dir, filename)
                            break
                    else:
                        if base_name == audio_id or filename.startswith(audio_id):
                            audio_path = os.path.join(search_dir, filename)
                            break

            # Fallback: try original directory if redacted not found
            if not audio_path and type_param == "redacted" and os.path.exists(audio_dir):
                for filename in os.listdir(audio_dir):
                    base_name = os.path.splitext(filename)[0]
                    if base_name == audio_id or filename.startswith(audio_id):
                        audio_path = os.path.join(audio_dir, filename)
                        break

            if not audio_path or not os.path.exists(audio_path):
                return JSONResponse({
                    "error": f"Audio not found: {audio_id}"
                }, status_code=404)

            # Determine media type from extension
            ext = os.path.splitext(audio_path)[1].lower()
            media_types = {
                ".wav": "audio/wav",
                ".mp3": "audio/mpeg",
                ".flac": "audio/flac",
                ".ogg": "audio/ogg",
                ".m4a": "audio/mp4",
                ".webm": "audio/webm",
                ".aac": "audio/aac",
            }
            media_type = media_types.get(ext, "application/octet-stream")

            return FileResponse(
                audio_path,
                media_type=media_type,
                headers={
                    "Cache-Control": "public, max-age=3600",  # Cache for 1 hour
                    "Accept-Ranges": "bytes",  # Enable seeking
                }
            )

        # Consent Management REST API endpoints
        async def api_consent_list_presets(request):
            """REST API endpoint to list available consent presets."""
            if not CONSENT_AVAILABLE:
                return JSONResponse({
                    "error": "Consent management not available",
                    "reason": "consent modules not installed"
                }, status_code=503)

            presets = []
            for name, config in CONSENT_PRESETS.items():
                presets.append({
                    "name": name,
                    "description": config.description,
                    "allowed_categories": list(config.allowed_categories),
                    "blocked_categories": list(config.blocked_categories),
                    "exposed_pii_types": list(config.exposed_pii_types),
                })

            return JSONResponse({
                "presets": presets,
                "categories": list(DATA_CATEGORIES),
                "default_preset": "balanced"
            })

        async def api_consent_create_session(request):
            """REST API endpoint to create a consent session with rules."""
            if not CONSENT_AVAILABLE:
                return JSONResponse({
                    "error": "Consent management not available"
                }, status_code=503)

            try:
                body = await request.json()
                preset = body.get("preset", "balanced")
                session_id = body.get("session_id")  # Optional - auto-generated if not provided

                # Create session via consent manager
                consent_manager = get_consent_manager()
                session = consent_manager.get_or_create_session(
                    session_id=session_id,
                    preset=preset if preset else None
                )
                print(f"Consent session created: {session.session_id}, preset={preset}, exposed_pii_types={list(session.exposed_pii_types)}")

                # Apply additional rules if provided
                if "allowed_categories" in body:
                    session.update_categories(
                        allowed=set(body["allowed_categories"]),
                        blocked=set(body.get("blocked_categories", []))
                    )

                if "exposed_pii_types" in body:
                    session.update_pii_types(exposed=set(body["exposed_pii_types"]))

                if "time_rules" in body:
                    time_rules = body["time_rules"]
                    session.set_time_rules(
                        after=time_rules.get("after"),
                        before=time_rules.get("before"),
                        relative=time_rules.get("relative")
                    )

                if "protect_entities" in body:
                    for entity in body["protect_entities"]:
                        if isinstance(entity, str):
                            session.protect_entity(entity)
                        else:
                            session.protect_entity(
                                name=entity.get("name"),
                                aliases=entity.get("aliases", []),
                                relationship=entity.get("relationship")
                            )

                if "expose_entities" in body:
                    for entity in body["expose_entities"]:
                        if isinstance(entity, str):
                            session.expose_entity(entity)
                        else:
                            session.expose_entity(
                                name=entity.get("name"),
                                aliases=entity.get("aliases", []),
                                relationship=entity.get("relationship")
                            )

                return JSONResponse({
                    "success": True,
                    "session_id": session.session_id,
                    "created_at": session.created_at.isoformat(),
                    "expires_at": session.expires_at.isoformat(),
                    "consent": session.to_dict()
                })
            except Exception as e:
                return JSONResponse(
                    {"error": str(e)},
                    status_code=500
                )

        async def api_consent_get_session(request):
            """REST API endpoint to get consent session settings."""
            if not CONSENT_AVAILABLE:
                return JSONResponse({
                    "error": "Consent management not available"
                }, status_code=503)

            session_id = request.path_params.get("session_id")
            consent_manager = get_consent_manager()
            session = consent_manager.get_session(session_id)

            if not session:
                return JSONResponse(
                    {"error": "Session not found"},
                    status_code=404
                )

            return JSONResponse({
                "session_id": session.session_id,
                "created_at": session.created_at.isoformat(),
                "last_accessed": session.last_accessed.isoformat(),
                "expires_at": session.expires_at.isoformat(),
                "is_expired": session.is_expired,
                "consent": session.to_dict()
            })

        async def api_consent_update_session(request):
            """REST API endpoint to update consent rules for a session."""
            if not CONSENT_AVAILABLE:
                return JSONResponse({
                    "error": "Consent management not available"
                }, status_code=503)

            session_id = request.path_params.get("session_id")
            consent_manager = get_consent_manager()
            session = consent_manager.get_session(session_id)

            if not session:
                return JSONResponse(
                    {"error": "Session not found"},
                    status_code=404
                )

            try:
                body = await request.json()

                # Update category rules
                if "allowed_categories" in body or "blocked_categories" in body:
                    session.update_categories(
                        allowed=set(body.get("allowed_categories", [])) if "allowed_categories" in body else None,
                        blocked=set(body.get("blocked_categories", [])) if "blocked_categories" in body else None
                    )

                # Update PII type exposure
                if "exposed_pii_types" in body:
                    session.update_pii_types(exposed=set(body["exposed_pii_types"]))

                # Update time rules
                if "time_rules" in body:
                    time_rules = body["time_rules"]
                    session.set_time_rules(
                        after=time_rules.get("after"),
                        before=time_rules.get("before"),
                        relative=time_rules.get("relative")
                    )

                # Update entity protections
                if "protect_entities" in body:
                    for entity in body["protect_entities"]:
                        if isinstance(entity, str):
                            session.protect_entity(entity)
                        else:
                            session.protect_entity(
                                name=entity.get("name"),
                                aliases=entity.get("aliases", []),
                                relationship=entity.get("relationship")
                            )

                if "expose_entities" in body:
                    for entity in body["expose_entities"]:
                        if isinstance(entity, str):
                            session.expose_entity(entity)
                        else:
                            session.expose_entity(
                                name=entity.get("name"),
                                aliases=entity.get("aliases", []),
                                relationship=entity.get("relationship")
                            )

                # Update document rules
                if "block_documents" in body:
                    for doc_id in body["block_documents"]:
                        session.block_document(doc_id)

                if "allow_documents" in body:
                    for doc_id in body["allow_documents"]:
                        session.allow_document(doc_id)

                return JSONResponse({
                    "success": True,
                    "session_id": session.session_id,
                    "consent": session.to_dict()
                })
            except Exception as e:
                return JSONResponse(
                    {"error": str(e)},
                    status_code=500
                )

        async def api_consent_delete_session(request):
            """REST API endpoint to delete a consent session."""
            if not CONSENT_AVAILABLE:
                return JSONResponse({
                    "error": "Consent management not available"
                }, status_code=503)

            session_id = request.path_params.get("session_id")
            session_manager = get_session_manager()
            deleted = session_manager.delete_session(session_id)

            return JSONResponse({
                "deleted": deleted,
                "session_id": session_id
            })

        async def api_consent_apply_preset(request):
            """REST API endpoint to apply a preset to an existing session."""
            if not CONSENT_AVAILABLE:
                return JSONResponse({
                    "error": "Consent management not available"
                }, status_code=503)

            session_id = request.path_params.get("session_id")
            consent_manager = get_consent_manager()
            session = consent_manager.get_session(session_id)

            if not session:
                return JSONResponse(
                    {"error": "Session not found"},
                    status_code=404
                )

            try:
                body = await request.json()
                preset_name = body.get("preset", "balanced")

                preset_config = get_preset_config(preset_name)
                if not preset_config:
                    return JSONResponse(
                        {"error": f"Unknown preset: {preset_name}"},
                        status_code=400
                    )

                session.apply_preset(preset_name)

                return JSONResponse({
                    "success": True,
                    "session_id": session.session_id,
                    "preset_applied": preset_name,
                    "consent": session.to_dict()
                })
            except Exception as e:
                return JSONResponse(
                    {"error": str(e)},
                    status_code=500
                )

        async def api_consent_status(request):
            """REST API endpoint to get consent system status."""
            if not CONSENT_AVAILABLE:
                return JSONResponse({
                    "available": False,
                    "reason": "consent modules not installed"
                })

            session_manager = get_session_manager()
            stats = session_manager.get_stats()

            return JSONResponse({
                "available": True,
                "active_sessions": stats["active_sessions"],
                "total_sessions_created": stats["total_sessions_created"],
                "max_sessions": stats["max_sessions"],
                "session_ttl_seconds": stats["session_ttl_seconds"],
                "presets_available": list(CONSENT_PRESETS.keys()),
                "categories_available": list(DATA_CATEGORIES)
            })

        async def api_upload_media(request):
            """REST API endpoint to upload and index an audio or image file.

            Accepts multipart/form-data with a 'file' field.
            Transcribes audio or captions images, then indexes the text.
            """
            import tempfile
            from starlette.datastructures import UploadFile as StarletteUploadFile

            try:
                form = await request.form()
                upload = form.get("file")
                if upload is None or not hasattr(upload, 'filename'):
                    return JSONResponse(
                        {"error": "No file uploaded. Send multipart/form-data with a 'file' field."},
                        status_code=400
                    )

                filename = upload.filename or "unknown"
                skip_duplicates = form.get("skip_duplicates", "true").lower() == "true"
                source = form.get("source")

                # Check if it's a supported media file
                if not FileProcessor.is_media_file(filename):
                    # Fall back to text processing if it's a supported text file
                    if FileProcessor.is_supported(filename):
                        pass  # Will be handled by process_file below
                    else:
                        supported = sorted(FileProcessor.SUPPORTED_EXTENSIONS | FileProcessor.MEDIA_EXTENSIONS)
                        return JSONResponse(
                            {"error": f"Unsupported file format. Supported: {', '.join(supported)}"},
                            status_code=400
                        )

                # Read file with size limit (500MB max to protect Jetson memory)
                MAX_UPLOAD_SIZE = 500 * 1024 * 1024  # 500MB
                content = await upload.read()
                if len(content) > MAX_UPLOAD_SIZE:
                    return JSONResponse(
                        {"error": f"File too large ({len(content) / (1024*1024):.1f}MB). Maximum upload size is 500MB."},
                        status_code=413
                    )
                if len(content) == 0:
                    return JSONResponse(
                        {"error": "Uploaded file is empty."},
                        status_code=400
                    )

                suffix = os.path.splitext(filename)[1] or '.tmp'
                fd, temp_path = tempfile.mkstemp(suffix=suffix)
                try:
                    with os.fdopen(fd, 'wb') as f:
                        f.write(content)

                    # Check for async audio processing BEFORE calling FileProcessor
                    ext = os.path.splitext(filename)[1].lower()
                    storage_result = None
                    audio_storage_path = None
                    audio_id = None
                    use_async_audio = ext in AUDIO_EXTENSIONS and self.async_audio_redactor

                    # For audio files with async processing: skip FileProcessor, create placeholder
                    if use_async_audio:
                        try:
                            import uuid
                            import shutil
                            audio_id = str(uuid.uuid4())[:12]
                            audio_dir = os.path.join(self.data_dir, "uploads", "audio")
                            os.makedirs(audio_dir, exist_ok=True)
                            audio_storage_path = os.path.join(audio_dir, f"{audio_id}{ext}")

                            # Copy audio to persistent storage
                            shutil.copy2(temp_path, audio_storage_path)

                            # Create placeholder result (no transcription yet)
                            result = {
                                'text': f"[Audio file: {filename}]\n\n[Transcription in progress...]",
                                'metadata': {
                                    'filename': filename,
                                    'extension': ext,
                                    'media_type': 'audio',
                                    'format': ext.lstrip('.'),
                                    'audio_id': audio_id,
                                    'audio_path': audio_storage_path,
                                    'transcription_pending': True,
                                    'redaction_pending': True,
                                }
                            }
                            print(f"   🎵 Audio stored: {audio_id} (transcription queued)")
                        except Exception as e:
                            # Log but don't fail - fall back to sync processing
                            print(f"   ⚠️ Audio storage failed: {e} (using sync processing)")
                            audio_storage_path = None
                            audio_id = None
                            use_async_audio = False

                    # Process the file (routes to audio/image processor automatically)
                    # Skip for async audio files (already handled above)
                    if not use_async_audio or audio_storage_path is None:
                        result = FileProcessor.process_file(
                            temp_path,
                            include_metadata=True,
                            generate_markdown=True,
                            audio_processor=self.audio_processor,
                            image_processor=self.image_processor,
                        )

                    metadata = result['metadata']
                    metadata['uploaded'] = True
                    metadata['original_filename'] = filename
                    if 'filename' not in metadata:
                        metadata['filename'] = filename
                    if source:
                        metadata['source'] = source
                    if 'markdown_content' in result:
                        metadata['markdown_content'] = result['markdown_content']

                    # For image files: persist to disk (PII redaction runs async)
                    if ext in IMAGE_EXTENSIONS and self.image_storage:
                        try:
                            # Use deferred redaction for fast uploads
                            # Async worker will run PII detection/redaction in background
                            storage_result = self.image_storage.store_image_deferred_redaction(
                                source_path=temp_path,
                                original_filename=filename,
                            )
                            # Add image storage metadata
                            metadata['original_image_path'] = storage_result.original_image_path
                            metadata['redacted_image_path'] = storage_result.redacted_image_path
                            metadata['image_id'] = storage_result.image_id
                            metadata['redaction_pending'] = True  # Indicates async redaction queued
                            print(f"   📸 Image stored: {storage_result.image_id} (redaction queued)")
                        except Exception as e:
                            # Log but don't fail the upload - image processing is optional
                            print(f"   ⚠️ Image storage failed: {e} (continuing without PII redaction)")

                    # For audio files processed via sync path: persist to disk
                    # so the audio can be served back to the frontend
                    if ext in AUDIO_EXTENSIONS and not audio_id:
                        try:
                            import uuid
                            import shutil
                            audio_id = str(uuid.uuid4())[:12]
                            audio_dir = os.path.join(self.data_dir, "uploads", "audio")
                            os.makedirs(audio_dir, exist_ok=True)
                            audio_storage_path = os.path.join(audio_dir, f"{audio_id}{ext}")
                            shutil.copy2(temp_path, audio_storage_path)
                            metadata['audio_id'] = audio_id
                            metadata['audio_path'] = audio_storage_path
                            print(f"   🎵 Audio stored: {audio_id}")
                        except Exception as e:
                            print(f"   ⚠️ Audio storage failed: {e} (audio playback unavailable)")

                    media_type = metadata.get('media_type')
                    kind = media_type or "document"

                    print(f"\n📄 [REST API] Adding uploaded {kind}: {filename} ({len(result['text'])} chars)...")
                    add_result = self.vector_store.add_document(
                        text=result['text'],
                        embedding_model=self.embedding_model,
                        metadata=metadata,
                        skip_duplicates=skip_duplicates,
                        topic_labeler=None,
                        extract_key_passages=False,
                        passage_extractor=None,
                        extract_key_entities=False,
                        verbose=True
                    )

                    if isinstance(add_result, AddDocumentResult):
                        if add_result.is_duplicate:
                            return JSONResponse({
                                "success": False,
                                "is_duplicate": True,
                                "existing_document_id": add_result.existing_doc_id,
                                "filename": filename,
                                "message": f"Content already exists with document ID {add_result.existing_doc_id}"
                            })
                        doc_id = add_result.doc_id
                    else:
                        doc_id = add_result

                    # Queue async image PII redaction (if image was stored)
                    if storage_result and self.async_image_redactor:
                        self.async_image_redactor.queue_redaction(ImageRedactionTask(
                            doc_id=doc_id,
                            image_id=storage_result.image_id,
                            original_image_path=storage_result.original_image_path,
                            redacted_image_path=storage_result.redacted_image_path,
                        ))

                    # Queue async audio transcription and PII redaction (if audio was stored)
                    if audio_storage_path and audio_id and self.async_audio_redactor:
                        self.async_audio_redactor.queue_task(AudioRedactionTask(
                            doc_id=doc_id,
                            audio_id=audio_id,
                            audio_path=audio_storage_path,
                            mute_audio=True,
                            mute_style="beep",
                        ))

                    # Queue async extraction
                    if self.async_extractor and self.passage_extractor and self.passage_extractor.is_available():
                        self.async_extractor.queue_extraction(ExtractionTask(
                            doc_id=doc_id,
                            text=result['text'],
                            extract_key_passages=True,
                            extract_key_entities=True,
                            extract_structured_metadata=True,
                            extract_filters=True,
                            source=source,
                            filename=filename,
                            media_type=media_type,
                        ))

                    return JSONResponse({
                        "success": True,
                        "document_id": doc_id,
                        "media_type": media_type,
                        "filename": filename,
                        "text_length": len(result['text']),
                        "metadata": {k: v for k, v in metadata.items()
                                     if k not in ('markdown_content',)},
                        "message": f"{kind.title()} '{filename}' processed and indexed with ID {doc_id}"
                    })
                finally:
                    # Clean up temp file
                    try:
                        os.unlink(temp_path)
                    except OSError:
                        pass
            except (FileNotFoundError, ValueError) as e:
                return JSONResponse(
                    {"error": str(e)},
                    status_code=400
                )
            except Exception as e:
                import traceback
                traceback.print_exc()
                return JSONResponse(
                    {"error": f"Media processing failed: {type(e).__name__}: {e}"},
                    status_code=500
                )

        async def api_media_status(request):
            """REST API endpoint to check media processing capabilities."""
            return JSONResponse({
                "audio": {
                    "available": self.audio_processor is not None,
                    "model": self.audio_processor.model_name if self.audio_processor else None,
                    "loaded": self.audio_processor.is_loaded() if self.audio_processor else False,
                    "supported_formats": sorted(AUDIO_EXTENSIONS),
                },
                "image": {
                    "available": self.image_processor is not None,
                    "model": self.image_processor.model_name if self.image_processor else None,
                    "loaded": self.image_processor.is_loaded() if self.image_processor else False,
                    "supported_formats": sorted(IMAGE_EXTENSIONS),
                },
            })

        # =====================================================================
        # Voice Chat v2 Endpoints (WebRTC via FastRTC)
        # =====================================================================

        async def api_voice_webrtc_offer(request):
            """Handle WebRTC SDP offer — FastRTC signaling endpoint."""
            if not self.voice_stream:
                return JSONResponse(
                    {"error": "Voice WebRTC not available"},
                    status_code=503,
                )

            # Clear previous text events
            with self._voice_text_lock:
                self._voice_text_events.clear()

            # Forward SDP offer to FastRTC stream
            try:
                body = await request.json()
                sdp_offer = body.get("sdp")
                sdp_type = body.get("type", "offer")
                webrtc_id = body.get("webrtc_id", "")

                if not sdp_offer:
                    return JSONResponse(
                        {"error": "Missing 'sdp' field"},
                        status_code=400,
                    )

                # Use FastRTC's offer handling — expects a Pydantic Body model
                from fastrtc.stream import Body as RTCBody
                offer_body = RTCBody(
                    sdp=sdp_offer,
                    type=sdp_type,
                    webrtc_id=webrtc_id,
                )
                answer = await self.voice_stream.offer(offer_body)

                # FastRTC.offer() returns a Starlette Response directly
                if isinstance(answer, Response):
                    return answer
                return JSONResponse(answer)
            except Exception as e:
                import traceback
                traceback.print_exc()
                return JSONResponse(
                    {"error": f"WebRTC offer failed: {e}"},
                    status_code=500,
                )

        async def api_voice_outputs(request):
            """SSE endpoint for voice text events (transcript, response, sources)."""
            from sse_starlette.sse import EventSourceResponse

            webrtc_id = request.query_params.get("webrtc_id", "")

            async def event_generator():
                """Yield text events as SSE."""
                last_idx = 0
                while True:
                    with self._voice_text_lock:
                        events = self._voice_text_events[last_idx:]
                        last_idx = len(self._voice_text_events)

                    for event in events:
                        yield {
                            "event": event["type"],
                            "data": json.dumps(event["data"]),
                        }

                    await asyncio.sleep(0.1)

            return EventSourceResponse(event_generator())

        async def api_voice_disconnect(request):
            """Explicitly disconnect voice session, closing stale WebRTC peers."""
            closed = 0
            if self.voice_stream:
                # Close all peer connections so concurrency slot is freed
                for wid in list(self.voice_stream.pcs.keys()):
                    try:
                        pc = self.voice_stream.pcs[wid]
                        await pc.close()
                        self.voice_stream.clean_up(wid)
                        closed += 1
                    except Exception:
                        pass
            return JSONResponse({"status": "disconnected", "closed": closed})

        async def api_voice_status(request):
            """Get voice chat availability and session status."""
            return JSONResponse({
                "webrtc": {
                    "available": self.voice_stream is not None,
                },
                "stt": {
                    "available": self.groq_stt_service is not None,
                    "backend": "groq",
                },
                "tts": {
                    "available": self.groq_tts_service is not None,
                    "backend": "groq",
                },
            })

        async def api_voice_config(request):
            """Get or update voice configuration."""
            if request.method == "GET":
                return JSONResponse(self._voice_config)

            # PUT: update config
            try:
                body = await request.json()
                if "voice" in body:
                    self._voice_config["voice"] = body["voice"]
                return JSONResponse(self._voice_config)
            except Exception as e:
                return JSONResponse(
                    {"error": f"Invalid config: {e}"},
                    status_code=400,
                )

        routes = [
            Route("/health", health_check),
            Route("/health/pii", health_pii),
            Route("/health/lprag", health_lprag),
            Route("/health/consent", health_consent),
            Route("/info", info),
            Route("/sse", self.handle_sse),
            Route("/messages", self.handle_messages, methods=["POST"]),
            # REST API routes
            Route("/api/search", api_search, methods=["POST"]),
            Route("/api/search/enhanced", api_enhanced_search, methods=["POST"]),
            Route("/api/think", api_think, methods=["POST"]),
            Route("/api/memory", api_write_memory, methods=["POST"]),
            Route("/api/memory/search", api_search_memory, methods=["POST"]),
            Route("/api/memory/timeline", api_memory_timeline, methods=["POST"]),
            Route("/api/memory/graph", api_memory_graph, methods=["POST"]),
            Route("/api/memory/workspace", api_memory_workspace_info, methods=["POST"]),
            Route("/api/memory/activity", api_memory_actor_activity, methods=["POST"]),
            Route("/api/search/reranked", api_search_reranked, methods=["POST"]),
            Route("/api/documents", api_list_documents, methods=["GET"]),
            Route("/api/documents", api_add_document, methods=["POST"]),
            Route("/api/documents/batch", api_add_documents_batch, methods=["POST"]),
            Route("/api/documents/{doc_id:int}", api_get_document, methods=["GET"]),
            Route("/api/documents/{doc_id:int}", api_delete_document, methods=["DELETE"]),
            Route("/api/documents/clear", api_clear_all_documents, methods=["DELETE"]),
            # Media upload (audio/image)
            Route("/api/media/upload", api_upload_media, methods=["POST"]),
            Route("/api/media/status", api_media_status, methods=["GET"]),
            Route("/api/stats", api_get_stats, methods=["GET"]),
            Route("/api/models", api_get_models, methods=["GET"]),
            Route("/api/debug", api_debug_info, methods=["GET"]),
            # GPU coordination routes (for Ollama)
            Route("/api/gpu/status", api_gpu_status, methods=["GET"]),
            Route("/api/gpu/release", api_gpu_release, methods=["POST"]),
            # Topic-related routes
            Route("/api/topics", api_get_all_topics, methods=["GET"]),
            Route("/api/topics/{topic:str}/documents", api_get_documents_by_topic, methods=["GET"]),
            Route("/api/documents/{doc_id:int}/topics", api_get_document_topics, methods=["GET"]),
            Route("/api/documents/{doc_id:int}/topics", api_update_document_topics, methods=["PUT"]),
            Route("/api/documents/{doc_id:int}/topics/generate", api_generate_topics, methods=["POST"]),
            Route("/api/search/with-topic", api_search_with_topic, methods=["POST"]),
            # Fast search routes (no GPU required)
            Route("/api/search/quick", api_search_quick, methods=["POST"]),
            Route("/api/search/files", api_search_files, methods=["POST"]),
            Route("/api/search/metadata", api_search_metadata, methods=["POST"]),
            Route("/api/search/unified", api_search_unified, methods=["POST"]),
            # Knowledge graph routes
            Route("/api/graph", api_get_knowledge_graph, methods=["POST"]),
            Route("/api/graph/node/{node_id:str}", api_get_graph_node, methods=["GET"]),
            # PII protection routes (REST API - no auth needed, for on-device apps)
            Route("/api/pii/anonymize", api_pii_anonymize, methods=["POST"]),
            Route("/api/pii/deanonymize", api_pii_deanonymize, methods=["POST"]),
            Route("/api/pii/status", api_pii_status, methods=["GET"]),
            Route("/api/pii/session/{session_id:str}", api_pii_session_info, methods=["GET"]),
            Route("/api/pii/session/{session_id:str}", api_pii_clear_session, methods=["DELETE"]),
            Route("/api/pii/session/{session_id:str}/refresh", api_pii_refresh_session, methods=["POST"]),
            # Image PII routes (OCR + Presidio for images)
            Route("/api/image/pii/status", api_image_pii_status, methods=["GET"]),
            Route("/api/image/pii/detect", api_image_pii_detect, methods=["POST"]),
            Route("/api/image/pii/redact", api_image_pii_redact, methods=["POST"]),
            Route("/api/image/serve/{image_id:str}", api_image_serve, methods=["GET"]),
            Route("/api/image/base64/{image_id:str}", api_image_base64, methods=["GET"]),
            # Audio serving route
            Route("/api/audio/serve/{audio_id:str}", api_audio_serve, methods=["GET"]),
            # LPRAG routes (Local Differential Privacy for RAG)
            Route("/api/lprag/status", api_lprag_status, methods=["GET"]),
            Route("/api/lprag/config", api_lprag_config, methods=["GET", "PUT"]),
            # Consent management routes
            Route("/api/consent/presets", api_consent_list_presets, methods=["GET"]),
            Route("/api/consent/status", api_consent_status, methods=["GET"]),
            Route("/api/consent/session", api_consent_create_session, methods=["POST"]),
            Route("/api/consent/session/{session_id:str}", api_consent_get_session, methods=["GET"]),
            Route("/api/consent/session/{session_id:str}", api_consent_update_session, methods=["PATCH"]),
            Route("/api/consent/session/{session_id:str}", api_consent_delete_session, methods=["DELETE"]),
            Route("/api/consent/session/{session_id:str}/apply-preset", api_consent_apply_preset, methods=["POST"]),
            # Voice chat v2 routes (WebRTC via FastRTC)
            Route("/api/voice/webrtc/offer", api_voice_webrtc_offer, methods=["POST"]),
            Route("/api/voice/outputs", api_voice_outputs, methods=["GET"]),
            Route("/api/voice/disconnect", api_voice_disconnect, methods=["POST"]),
            Route("/api/voice/status", api_voice_status, methods=["GET"]),
            Route("/api/voice/config", api_voice_config, methods=["GET", "PUT"]),
        ]

        # Add txtai-specific routes (hybrid search, graph search, topic network)
        txtai_routes = create_txtai_routes(self)
        routes.extend(txtai_routes)

        # Setup middleware
        middleware = []

        # Add CORS middleware
        # SECURITY: Restrict origins to localhost variants and local network.
        # Configure CORS_ALLOWED_ORIGINS env var for custom origins in production.
        cors_origins_env = os.environ.get("CORS_ALLOWED_ORIGINS", "").strip()
        if cors_origins_env:
            cors_origins = [origin.strip() for origin in cors_origins_env.split(",") if origin.strip()]
        else:
            # Default: localhost on common development ports + local network patterns
            cors_origins = [
                "http://localhost:3000",
                "http://localhost:3003",
                "http://localhost:8080",
                "http://localhost:8085",
                "http://127.0.0.1:3000",
                "http://127.0.0.1:3003",
                "http://127.0.0.1:8080",
                "http://127.0.0.1:8085",
            ]
        middleware.append(
            Middleware(
                CORSMiddleware,
                allow_origins=cors_origins,
                allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+)(:\d+)?$",
                allow_credentials=True,
                allow_methods=["*"],
                allow_headers=["*"],
            )
        )

        app = Starlette(routes=routes, middleware=middleware)

        # Add authentication middleware for public mode
        if self.public and self.api_key:
            app = APIKeyMiddleware(app, self.api_key)

        return app

    async def run(self):
        """Run the HTTP MCP server."""
        await self.initialize()

        mode_str = "PUBLIC (Internet-Accessible)" if self.public else "LOCAL (Network Only)"
        print(f"\n{'='*70}")
        print(f"MCP Vector Store Server - {mode_str}")
        print(f"{'='*70}")
        print(f"Server running on: http://{self.host}:{self.port}")
        print(f"Health check: http://{self.host}:{self.port}/health")
        print(f"Info: http://{self.host}:{self.port}/info")
        print(f"SSE endpoint: http://{self.host}:{self.port}/sse")

        if self.public:
            print(f"\n🌍 PUBLIC MODE - Internet accessible")
            print(f"🔐 Authentication: API Key required")
            print(f"📝 API Key: {self.api_key}")
            print(f"📌 Usage: Add header 'Authorization: Bearer {self.api_key}'")
            print(f"\n⚠️  SECURITY:")
            print(f"  • Keep the API key secure")
            print(f"  • Use HTTPS in production (consider reverse proxy)")
            print(f"  • Configure firewall rules appropriately")
        else:
            print(f"\n🏠 LOCAL MODE - Network only")
            print(f"🔓 No authentication required")
            print(f"📍 Accessible from devices on same network")
            print(f"\n💡 To enable public access:")
            print(f"  python src/mcp_vector_store/mcp_server_http.py --public")

        print(f"{'='*70}\n")

        # Create app
        app = self.create_app()

        # Configure uvicorn
        config = uvicorn.Config(
            app,
            host=self.host,
            port=self.port,
            log_level="info",
            access_log=True
        )

        server = uvicorn.Server(config)

        try:
            await server.serve()
        finally:
            await self.cleanup()


async def main():
    """Main entry point."""
    import argparse

    public_default = any(
        os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}
        for name in ("MCP_VECTOR_STORE_PUBLIC", "VECTOR_STORE_PUBLIC")
    )

    parser = argparse.ArgumentParser(
        description="MCP Vector Store Server with HTTP/SSE transport"
    )
    parser.add_argument(
        "--db-path",
        default="./vectordb",
        help="Path to vector database directory"
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host to bind to (default: 0.0.0.0 for all interfaces)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8085,
        help="Port to listen on (default: 8085)"
    )
    parser.add_argument(
        "--public",
        action="store_true",
        default=public_default,
        help="Enable public internet access with API key authentication"
    )
    parser.add_argument(
        "--api-key",
        help="Custom API key (auto-generated if not provided in public mode)"
    )
    parser.add_argument(
        "--model",
        help="Embedding model name (auto-selects if not provided)"
    )

    args = parser.parse_args()

    # Validate public mode
    has_env_api_key = any(os.environ.get(name) for name in REMOTE_API_KEY_ENV_KEYS)
    if not args.public and (args.api_key or has_env_api_key):
        print("⚠️  Warning: remote API keys are only used in public mode. Use --public or MCP_VECTOR_STORE_PUBLIC=true to enable.")

    # Create and run server
    server = MCPVectorSearchHTTPServer(
        db_path=args.db_path,
        model_name=args.model,
        host=args.host,
        port=args.port,
        public=args.public,
        api_key=args.api_key
    )

    await server.run()


if __name__ == "__main__":
    asyncio.run(main())
