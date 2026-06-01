// Document types
export interface VectorDocument {
  id: number;
  filename: string;
  content: string;
  topics: string[];
  primaryTopic?: string;
  source: string;
  createdAt: string;
  wordCount: number;
  fileType: 'code' | 'document' | 'data' | 'text' | 'audio' | 'image';
  extension: string;
  // Media type indicator
  mediaType?: 'image' | 'audio';
  // Image-specific metadata (present when fileType === 'image')
  imageId?: string;
  caption?: string;
  width?: number;
  height?: number;
  hasPii?: boolean;
  piiTypesFound?: string[];
  redactionPending?: boolean;
  redactionComplete?: boolean;
  // Audio-specific metadata (present when fileType === 'audio')
  audioMetadata?: AudioMetadata;
}

// Audio PII region with timestamp for click-to-seek
export interface AudioPIIRegion {
  startTime: number;   // Start time in seconds
  endTime: number;     // End time in seconds
  piiType: string;     // PERSON, EMAIL_ADDRESS, PHONE_NUMBER, etc.
  originalText: string;
  replacementText: string;  // [PERSON], [PHONE_NUMBER], etc.
  confidence: number;
}

// Audio-specific metadata from vector store
export interface AudioMetadata {
  mediaType: 'audio';
  audioId?: string;                  // Unique audio ID for serving
  format: string;                    // wav, mp3, flac, etc.
  durationSeconds?: number;
  sampleRate?: number;
  channels?: number;
  originalTranscript?: string;       // Full text for Explore tab viewing
  redactedTranscript?: string;       // PII replaced for LLM/embeddings
  hasPii?: boolean;
  piiTypesFound?: string[];
  piiRegions?: AudioPIIRegion[];
  wordCount?: number;
  piiProcessingTimeMs?: number;
  // Redacted audio file (Phase 2)
  redactedAudioPath?: string;
}

export interface VectorSearchResult {
  id: number;
  parentDocId: number; // Parent document ID (same as id for non-chunks)
  filename: string;
  excerpt: string;
  score: number;
  displayScore?: number; // Normalized 0-100% score for UI display
  topics: string[];
  source: string;
  excerptMethod: 'ai' | 'indexed' | 'context';
}

export interface EnhancedSearchResult extends VectorSearchResult {
  metadata: {
    createdAt: string;
    wordCount: number;
  };
}

// Graph types
export type NodeType = 'document' | 'topic' | 'person' | 'organization' | 'location' | 'technology';

export interface GraphNode {
  id: string;
  label: string;
  type: NodeType;
  connectionCount: number;
  preview?: string;
  topics?: string[];
  docCount?: number;
}

export type EdgeType = 'has_topic' | 'has_person' | 'has_organization' | 'has_location' | 'has_technology';

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  edgeType?: EdgeType;
}

export interface AvailableNodeType {
  type: NodeType;
  label: string;
  count: number;
}

export interface DynamicFilter {
  type: string;
  label: string;
  count: number;
}

export interface AvailableFilters {
  node_types: AvailableNodeType[];
  sources: string[];
  content_types?: DynamicFilter[];
  domains?: DynamicFilter[];
}

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
  availableFilters?: AvailableFilters;
}

export interface GraphNodeDetails {
  id: string;
  type: string;
  label: string;
  details: {
    doc_id?: number;
    filename?: string;
    text?: string;
    text_length?: number;
    topics?: string[];
    persons?: string[];
    organizations?: string[];
    locations?: string[];
    technologies?: string[];
    created_at?: string;
    topic?: string;
    document_count?: number;
    entity_name?: string;
    entity_type?: string;
    sample_documents?: {
      id: number;
      title?: string;
      text_preview?: string;
    }[];
  };
}

// Connector types
export type ConnectorType = 'chatgpt' | 'claude' | 'gemini' | 'notion' | 'facebook' | (string & {});

export interface Connector {
  id: string;
  type: ConnectorType;
  name: string;
  connected: boolean;
  itemCount?: number;
  lastSync?: string;
  config?: Record<string, string>;
}

// LocalSend types
export interface LocalSendStatus {
  running: boolean;
  deviceName: string;
  port: number;
}

// Server types
export interface ServerInfo {
  ip: string;
  port: number;
  url: string;
}

export interface VectorStoreStatus {
  status: 'ready' | 'offline' | 'indexing';
  documentCount: number;
}

// MCP types
export interface MCPStatus {
  ready: boolean;
  url: string;
  documentCount: number;
}

// Folder (file explorer)
export interface Folder {
  id: string;
  name: string;
  documentIds: number[];
  createdAt: string;
}

// Manual connection (user-created edge)
export interface ManualConnection {
  id: string;
  source: string;
  target: string;
  createdAt: string;
}

// Saved view
export interface SavedView {
  id: string;
  name: string;
  description?: string;
  createdAt: string;
  nodePositions: { id: string; position: { x: number; y: number } }[];
  viewport: { x: number; y: number; zoom: number };
  searchQuery: string;
  searchMode: 'semantic' | 'hybrid';
  visibleTypes: string[];
  expandedNodeIds: string[];
  nodeCount: number;
  edgeCount: number;
}

export interface SavedViewSummary {
  id: string;
  name: string;
  description?: string;
  createdAt: string;
  nodeCount: number;
  edgeCount: number;
}

