"""MCP Vector Store - Platform-agnostic vector search for edge devices.

Uses txtai for unified hybrid search (BM25 + semantic vectors),
semantic graphs, and ONNX runtime optimization for edge devices.
"""

from .txtai_adapter import (
    TxtaiAdapter as VectorStore,  # Alias for backwards compatibility
    TxtaiEmbeddingWrapper,
    SearchResult,
    EnhancedSearchResult,
    DocumentResult,
    PaginatedResult,
    AddDocumentResult,
)
from .txtai_endpoints import create_vector_store, create_txtai_routes
from .txtai_store import TxtaiStore, TxtaiDocument, TxtaiSearchResult
from .file_processor import FileProcessor, extract_text_from_file, is_file_supported
from .audio_processor import AudioProcessor, AUDIO_EXTENSIONS
from .image_processor import ImageProcessor, IMAGE_EXTENSIONS
from .mcp_client import MCPVectorStoreClient, MCPVectorStoreSyncClient, quick_search
from .topic_labeler import TopicLabeler, TopicResult, DEFAULT_TOPICS
from .passage_extractor import (
    PassageExtractor,
    ExtractedPassage,
)

__version__ = "0.3.0"  # Version bump for txtai migration
__all__ = [
    # Core (txtai-based)
    "TxtaiEmbeddingWrapper",
    "VectorStore",  # TxtaiAdapter aliased for backwards compatibility
    "TxtaiStore",
    "TxtaiDocument",
    "TxtaiSearchResult",
    "SearchResult",
    "EnhancedSearchResult",
    "DocumentResult",
    "PaginatedResult",
    "AddDocumentResult",
    "create_vector_store",
    "create_txtai_routes",
    # File processing
    "FileProcessor",
    "extract_text_from_file",
    "is_file_supported",
    # Media processing
    "AudioProcessor",
    "ImageProcessor",
    "AUDIO_EXTENSIONS",
    "IMAGE_EXTENSIONS",
    # MCP client
    "MCPVectorStoreClient",
    "MCPVectorStoreSyncClient",
    "quick_search",
    # Topic labeling
    "TopicLabeler",
    "TopicResult",
    "DEFAULT_TOPICS",
    # Passage extraction
    "PassageExtractor",
    "ExtractedPassage",
]
