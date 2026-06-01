const API_BASE = import.meta.env.VITE_API_URL || '';

/** Throw on non-OK HTTP responses with a descriptive message. */
async function assertOk(res: Response, fallbackMessage: string): Promise<void> {
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error((body as Record<string, string>).error || fallbackMessage);
  }
}

export interface Connector {
  id: string;
  name: string;
  type: 'api' | 'webhook' | 'file' | 'custom';
  config: Record<string, any>;
  status: 'connected' | 'syncing' | 'error' | 'paused';
  lastSync?: string;
  itemCount: number;
}

export interface Stats {
  usedGB: number;
  totalGB: number;
  itemCount: number;
  sourcesCount: number;
}

export interface SyncStatus {
  running: boolean;
  output: string[];
  lastRun?: string;
  exitCode?: number;
}

export interface ReceivedFile {
  name: string;
  size: number;
  modified: string;
  source: 'localsend' | 'browser' | 'unknown';
}

export interface ServerInfo {
  port: number;
  ipAddress: string;
  url: string;
}

export interface LocalSendStatus {
  installed: boolean;
  running: boolean;
  deviceName: string;
  port: number;
  savePath: string;
  platform: string;
  canAutoStart: boolean;
}

export interface LocalSendResult {
  success: boolean;
  message: string;
  error?: string;
}

export interface VectorStoreStatus {
  available: boolean;
  host: string;
  port: number;
  total_documents?: number;
  total_files?: number;
  embedding_dimension?: number;
  db_path?: string;
  message?: string;
  error?: string;
}

export interface VectorSearchResult {
  id: number;
  text: string;
  score: number;
  metadata: Record<string, any>;
  topics?: string[];
  primary_topic?: string;
}

export interface VectorSearchResponse {
  query: string;
  results: VectorSearchResult[];
}

export interface VectorDocument {
  id: number;
  text: string;
  metadata: Record<string, any>;
  created_at: string;
  topics?: string[];
  primary_topic?: string;
}

export interface PaginatedDocuments {
  documents: VectorDocument[];
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
  has_next: boolean;
  has_prev: boolean;
}

export interface IndexConnectorResult {
  success: boolean;
  totalIndexed: number;
  filesProcessed: number;
  errors?: string[];
}

export interface TopicInfo {
  name: string;
  document_count: number;
}

export interface AllTopicsResult {
  success: boolean;
  total_unique_topics: number;
  topics: TopicInfo[];
}

export interface DocumentTopics {
  doc_id: number;
  topics: string[];
  primary_topic?: string;
  topics_updated_at?: number;
}

export interface GenerateTopicsResult {
  success: boolean;
  doc_id: number;
  topics: string[];
  primary_topic: string;
  confidence: number;
  error?: string;
}

export interface PaginatedDocumentsByTopic extends PaginatedDocuments {
  topic: string;
}

export interface SearchWithTopicResponse {
  query: string;
  topic?: string;
  minScore?: number;
  results: VectorSearchResult[];
}

/**
 * Enhanced search result with excerpt extraction.
 * Returns relevant passages instead of full documents.
 */
export interface EnhancedSearchResult {
  id: number;
  excerpt: string;  // Relevant passage extracted from the document
  score: number;
  excerpt_method: 'full' | 'llm_extract' | 'window' | 'precomputed';
  topics?: string[];
  primary_topic?: string;
  full_text_length: number;
  metadata: Record<string, any>;
}

/**
 * Response from enhanced search endpoint
 */
export interface EnhancedSearchResponse {
  query: string;
  minScore: number;
  extractPassages: boolean;
  expandQuery: boolean;
  results: EnhancedSearchResult[];
}

/**
 * Options for enhanced search
 */
export interface EnhancedSearchOptions {
  topK?: number;
  minScore?: number;
  extractPassages?: boolean;
  expandQuery?: boolean;
  maxExcerptLength?: number;
}

/**
 * Background indexing job status
 */
export interface IndexingJob {
  id: string;
  filename: string;
  filePath: string;
  status: 'queued' | 'processing' | 'completed' | 'failed';
  progress?: string;
  startedAt?: string;
  completedAt?: string;
  error?: string;
  result?: {
    indexed: boolean;
    isDuplicate: boolean;
    documentId?: number;
    existingDocId?: number;
  };
}

/**
 * Indexing status summary
 */
export interface IndexingStatus {
  active: boolean;
  queued: number;
  processing: number;
  completed: number;
  failed: number;
  currentJob: {
    id: string;
    filename: string;
    progress: string;
  } | null;
}

/**
 * Import file result with job ID
 */
export interface ImportFileResult {
  success: boolean;
  path: string;
  indexing: 'queued';
  jobId: string;
  message: string;
}

/**
 * Knowledge Graph Types
 */
export interface GraphNode {
  id: string;
  type: 'document' | 'topic' | 'person' | 'organization' | 'location' | 'technology';
  label: string;
  metadata: {
    doc_id?: number;
    filename?: string;
    created_at?: number;
    topics?: string[];
    text_preview?: string;
    connection_count?: number;
  };
}

export interface GraphEdge {
  source: string;
  target: string;
  type: 'has_topic' | 'has_person' | 'has_organization' | 'has_location' | 'has_technology';
}

export interface GraphStats {
  document_count: number;
  topic_count: number;
  person_count: number;
  organization_count: number;
  location_count: number;
  technology_count: number;
  edge_count: number;
}

export interface AvailableNodeType {
  type: 'document' | 'topic' | 'person' | 'organization' | 'location' | 'technology';
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

export interface KnowledgeGraphResponse {
  nodes: GraphNode[];
  edges: GraphEdge[];
  stats: GraphStats;
  available_filters?: AvailableFilters;
}

export interface KnowledgeGraphOptions {
  includeDocuments?: boolean;
  includeTopics?: boolean;
  includeEntities?: boolean;
  entityTypes?: ('person' | 'organization' | 'location' | 'technology')[];
  minConnections?: number;
  limitDocuments?: number;
  limitEntitiesPerType?: number;
  maxTopicEdgesPerDoc?: number;
  maxEntityEdgesPerDoc?: number;
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

export interface DebugInfo {
  system_memory: {
    total_mb: number;
    available_mb: number;
    used_mb: number;
    percent_used: number;
  };
  swap: {
    total_mb: number;
    used_mb: number;
    percent_used: number;
  };
  process_memory: {
    rss_mb: number;
    vms_mb: number;
  };
  gpu: {
    cuda_available?: boolean;
    device_name?: string;
    memory_allocated_mb?: number;
    memory_reserved_mb?: number;
    max_memory_allocated_mb?: number;
    error?: string;
  };
  models: {
    status: Record<string, { is_loaded: boolean; on_gpu: boolean }>;
    current_gpu_model: string | null;
  };
  extraction_queue: {
    pending: number;
    running?: boolean;
    total_retries?: number;
    failed_count?: number;
    waiting_for_memory: boolean;
    memory_constrained: boolean;
    min_required_mb?: number;
  };
  vector_store: {
    total_documents: number;
    total_files: number;
  };
  pii_protection: {
    available: boolean;
  };
}

/**
 * Chat Types
 */
export interface ChatMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
}

export interface PerturbedValue {
  pii_type: string;
  perturbed_value: string;
  is_lprag: boolean;
}

export interface ChatContext {
  id: number;
  excerpt: string;
  score: number;
  source?: string;
  filename?: string;
  perturbed_values?: PerturbedValue[];
}

export interface ChatStatus {
  llmAvailable: boolean;
  llmProvider: LLMProvider | null;
  vectorStoreAvailable: boolean;
  defaultModel: string | null;
  availableModels: string[];
  gpuAvailable: boolean;
  gpuStatus: string;
  // Legacy compatibility
  ollamaAvailable: boolean;
}

export interface ChatRequest {
  message: string;
  conversationHistory?: ChatMessage[];
  model?: string;
  useRAG?: boolean;
  topK?: number;
  minScore?: number;
  temperature?: number;
  maxTokens?: number;
  consentSessionId?: string;
  voiceInitiated?: boolean;
}

export interface VoiceStatus {
  webrtc: {
    available: boolean;
  };
  stt: {
    available: boolean;
    backend: string;
  };
  tts: {
    available: boolean;
    backend: string;
  };
}

export interface VoiceConfig {
  voice: string;
}

export interface WebRTCOffer {
  sdp: string;
  type: string;
  webrtc_id: string;
}

export interface WebRTCAnswer {
  sdp: string;
  type: string;
}

export interface ChatResponse {
  message: string;
  model: string;
  context?: ChatContext[];
  tokensUsed?: number;
  duration?: number;
}

export interface StreamEvent {
  type: 'context' | 'token' | 'deanonymized' | 'done' | 'error';
  content?: string;
  context?: ChatContext[];
  model?: string;
  tokensUsed?: number;
  duration?: number;
  error?: string;
}

export interface PIIStatus {
  enabled: boolean;
  active_sessions: number;
  total_tokens_active: number;
}

export type LLMProvider = 'openai' | 'anthropic' | 'groq';

export interface LLMConfig {
  preferredProvider: 'auto' | LLMProvider;
  openaiConfigured: boolean;
  anthropicConfigured: boolean;
  groqConfigured: boolean;
  openaiModel: string;
  anthropicModel: string;
  groqModel: string;
  activeProvider: LLMProvider | null;
}

export interface LLMConfigUpdate {
  preferredProvider?: 'auto' | LLMProvider;
  openaiApiKey?: string;
  anthropicApiKey?: string;
  groqApiKey?: string;
  openaiModel?: string;
  anthropicModel?: string;
  groqModel?: string;
}

export interface TestKeyResult {
  success: boolean;
  error?: string;
}

// Browser Connector Types
export type SupportedSite = string;

export interface ImportedCookie {
  name: string;
  value: string;
  domain: string;
  path: string;
  secure: boolean;
  httpOnly: boolean;
  sameSite?: 'Strict' | 'Lax' | 'None' | 'no_restriction' | 'unspecified';
  expirationDate?: number;
}

export interface CookieImportResult {
  success: boolean;
  cookiesImported: number;
  site: SupportedSite;
  error?: string;
}

export interface BrowserConnectorConfig {
  autoStart: boolean;
  defaultUrl: string;
  headed: boolean;
  memoryLimit?: number;
  authenticatedAt?: string;
  autoSyncEnabled?: boolean;
  autoSyncIntervalHours?: number;
  lastSyncAt?: string;
  lastSyncResult?: SyncResult;
}

export interface AuthStatus {
  authenticated: boolean;
  authenticatedAt?: string;
  site?: SupportedSite;
}

export interface SiteInfo {
  id: string;
  name: string;
  url: string;
  cookieDomains?: string[];
  authenticated: boolean;
  authStatus: AuthStatus;
}

export interface SitesResponse {
  sites: SiteInfo[];
  authenticatedSites: string[];
}

export interface SyncResult {
  success: boolean;
  synced?: number;
  failed?: number;
  total?: number;
  error?: string;
}

export interface AutoSyncStatus {
  enabled: boolean;
  intervalHours: number;
  lastSyncAt?: string;
  lastSyncResult?: SyncResult;
  nextSyncAt?: string;
}

export interface VncInfo {
  enabled: boolean;
  wsPort: number;
  vncPort: number;
  display: string;
}

export interface BrowserConnectorStatus {
  running: boolean;
  pid?: number;
  activeUrl?: string;
  connectedSites: string[];
  launchedAt?: string;
  memoryUsageMB?: number;
  captureStats: {
    totalCaptured: number;
    lastCaptureAt?: string;
    sessionCaptured: number;
    totalConversations?: number;
  };
  vnc?: VncInfo;
}

export interface VncStatus {
  enabled: boolean;
  wsPort?: number;
  vncPort?: number;
  display?: string;
  url?: string;
}

export interface VncCheckResult {
  available: boolean;
  missing: string[];
  installCommand: string | null;
}

export interface CapturedConversationSummary {
  id: string;
  site: SupportedSite;
  title?: string;
  url: string;
  messageCount: number;
  indexed: boolean;
  createdAt: string;
  updatedAt: string;
}

export interface CapturedMessage {
  id: string;
  conversationId: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: string;
  site: SupportedSite;
}

export interface CapturedConversation extends CapturedConversationSummary {
  messages: CapturedMessage[];
}

export interface BrowserCaptureStats {
  totalConversations: number;
  totalMessages: number;
  bySite: Record<SupportedSite, { conversations: number; messages: number }>;
}

export interface MediaUploadResult {
  success: boolean;
  document_id?: number;
  media_type?: string;
  filename?: string;
  text_length?: number;
  metadata?: Record<string, any>;
  message?: string;
  // Duplicate case
  is_duplicate?: boolean;
  existing_document_id?: number;
  error?: string;
}

export interface MediaProcessorInfo {
  available: boolean;
  model: string | null;
  loaded: boolean;
  supported_formats: string[];
}

export interface MediaStatus {
  audio: MediaProcessorInfo;
  image: MediaProcessorInfo;
}

export const api = {
  // Health check
  async checkHealth(): Promise<boolean> {
    try {
      const res = await fetch(`${API_BASE}/api/stats`, {
        method: 'GET',
        signal: AbortSignal.timeout(3000)
      });
      return res.ok;
    } catch {
      return false;
    }
  },

  // Connectors
  async getConnectors(): Promise<Connector[]> {
    const res = await fetch(`${API_BASE}/api/connectors`);
    await assertOk(res, 'Failed to get connectors');
    return res.json();
  },

  async addConnector(data: { name: string; type: string; config: string }): Promise<Connector> {
    let parsedConfig: Record<string, unknown> = {};
    if (data.config) {
      try { parsedConfig = JSON.parse(data.config); }
      catch { throw new Error('Invalid connector config JSON'); }
    }
    const res = await fetch(`${API_BASE}/api/connectors`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: data.name,
        type: data.type.toLowerCase().replace(' ', ''),
        config: parsedConfig,
      }),
    });
    await assertOk(res, 'Failed to add connector');
    return res.json();
  },

  async updateConnector(id: string, data: Partial<Connector>): Promise<Connector> {
    const res = await fetch(`${API_BASE}/api/connectors/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    await assertOk(res, 'Failed to update connector');
    return res.json();
  },

  // Create or update a connector - handles the case where connector doesn't exist yet
  async connectConnector(connectorType: string, name: string, config: Record<string, any>): Promise<Connector> {
    // Map connector types to backend scripts
    const scriptMap: Record<string, string> = {
      chatgpt: 'chatgpt-import',
      facebook: 'facebook-import',
      notion: 'notion',
    };
    const script = scriptMap[connectorType] || connectorType;

    // First, check if connector exists by listing all
    const connectors = await this.getConnectors();
    const existing = connectors.find(c =>
      c.name.toLowerCase() === name.toLowerCase() ||
      c.config?.connectorType === connectorType
    );

    if (existing) {
      // Update existing connector
      const res = await fetch(`${API_BASE}/api/connectors/${existing.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          config: { ...existing.config, ...config, connectorType, script },
          status: 'connected',
        }),
      });
      await assertOk(res, 'Failed to update connector');
      return res.json();
    } else {
      // Create new connector
      const res = await fetch(`${API_BASE}/api/connectors`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name,
          type: 'custom',
          config: { ...config, connectorType, script },
        }),
      });
      await assertOk(res, 'Failed to create connector');
      return res.json();
    }
  },

  async deleteConnector(id: string): Promise<void> {
    const res = await fetch(`${API_BASE}/api/connectors/${id}`, {
      method: 'DELETE',
    });
    await assertOk(res, 'Failed to delete connector');
  },

  async syncConnector(id: string): Promise<void> {
    const res = await fetch(`${API_BASE}/api/connectors/${id}/sync`, {
      method: 'POST',
    });
    await assertOk(res, 'Failed to sync connector');
  },

  async getSyncStatus(id: string): Promise<SyncStatus> {
    const res = await fetch(`${API_BASE}/api/connectors/${id}/status`);
    await assertOk(res, 'Failed to get sync status');
    return res.json();
  },

  async stopSync(id: string): Promise<void> {
    const res = await fetch(`${API_BASE}/api/connectors/${id}/stop`, {
      method: 'POST',
    });
    await assertOk(res, 'Failed to stop sync');
  },

  async uploadConnectorFile(connectorId: string, file: File): Promise<{ success: boolean; itemCount: number; message: string; pendingMedia?: number }> {
    const formData = new FormData();
    formData.append('file', file);

    const res = await fetch(`${API_BASE}/api/connectors/${connectorId}/upload`, {
      method: 'POST',
      body: formData,
    });

    if (!res.ok) {
      const error = await res.json();
      throw new Error(error.error || 'Upload failed');
    }

    return res.json();
  },

  // Stats
  async getStats(): Promise<Stats> {
    const res = await fetch(`${API_BASE}/api/stats`);
    await assertOk(res, 'Failed to get stats');
    return res.json();
  },

  // Server info
  async getServerInfo(): Promise<ServerInfo> {
    const res = await fetch(`${API_BASE}/api/server-info`);
    await assertOk(res, 'Failed to get server info');
    return res.json();
  },

  // File Transfer
  async getReceivedFiles(): Promise<ReceivedFile[]> {
    const res = await fetch(`${API_BASE}/api/files`);
    await assertOk(res, 'Failed to get received files');
    return res.json();
  },

  async deleteReceivedFile(filename: string): Promise<void> {
    const res = await fetch(`${API_BASE}/api/files/${encodeURIComponent(filename)}`, {
      method: 'DELETE',
    });
    await assertOk(res, 'Failed to delete file');
  },

  async importReceivedFile(filename: string): Promise<ImportFileResult> {
    const res = await fetch(`${API_BASE}/api/files/${encodeURIComponent(filename)}/import`, {
      method: 'POST',
    });
    await assertOk(res, 'Failed to import file');
    return res.json();
  },

  // Indexing status
  async getIndexingStatus(): Promise<IndexingStatus> {
    const res = await fetch(`${API_BASE}/api/indexing/status`);
    await assertOk(res, 'Failed to get indexing status');
    return res.json();
  },

  async getIndexingJobs(): Promise<{ jobs: IndexingJob[]; queueLength: number; processing: number; isProcessing: boolean }> {
    const res = await fetch(`${API_BASE}/api/indexing/jobs`);
    await assertOk(res, 'Failed to get indexing jobs');
    return res.json();
  },

  async getIndexingJob(jobId: string): Promise<IndexingJob> {
    const res = await fetch(`${API_BASE}/api/indexing/jobs/${jobId}`);
    await assertOk(res, 'Failed to get indexing job');
    return res.json();
  },

  // LocalSend
  async getLocalSendStatus(): Promise<LocalSendStatus> {
    const res = await fetch(`${API_BASE}/api/localsend/status`);
    await assertOk(res, 'Failed to get LocalSend status');
    return res.json();
  },

  async startLocalSend(): Promise<LocalSendResult> {
    const res = await fetch(`${API_BASE}/api/localsend/start`, {
      method: 'POST',
    });
    await assertOk(res, 'Failed to start LocalSend');
    return res.json();
  },

  async stopLocalSend(): Promise<LocalSendResult> {
    const res = await fetch(`${API_BASE}/api/localsend/stop`, {
      method: 'POST',
    });
    await assertOk(res, 'Failed to stop LocalSend');
    return res.json();
  },

  async setupLocalSend(): Promise<LocalSendResult> {
    const res = await fetch(`${API_BASE}/api/localsend/setup`, {
      method: 'POST',
    });
    await assertOk(res, 'Failed to setup LocalSend');
    return res.json();
  },

  async configureLocalSend(deviceName: string): Promise<LocalSendResult> {
    const res = await fetch(`${API_BASE}/api/localsend/configure`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ deviceName }),
    });
    await assertOk(res, 'Failed to configure LocalSend');
    return res.json();
  },

  // Vector Store API
  async getVectorStoreStatus(): Promise<VectorStoreStatus> {
    const res = await fetch(`${API_BASE}/api/vector-store/status`);
    await assertOk(res, 'Failed to get vector store status');
    return res.json();
  },

  async searchVectorStore(query: string, topK: number = 5, minScore?: number): Promise<VectorSearchResponse> {
    const res = await fetch(`${API_BASE}/api/vector-store/search`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, topK, minScore }),
    });
    if (!res.ok) {
      const error = await res.json();
      throw new Error(error.error || 'Search failed');
    }
    return res.json();
  },

  async enhancedSearch(query: string, options: EnhancedSearchOptions = {}): Promise<EnhancedSearchResponse> {
    const {
      topK = 5,
      minScore = 0.5,  // Balanced threshold for quality results
      extractPassages = true,
      expandQuery = false,
      maxExcerptLength = 500,
    } = options;

    const res = await fetch(`${API_BASE}/api/vector-store/search/enhanced`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        query,
        topK,
        minScore,
        extractPassages,
        expandQuery,
        maxExcerptLength,
      }),
    });
    if (!res.ok) {
      const error = await res.json();
      throw new Error(error.error || 'Enhanced search failed');
    }
    return res.json();
  },

  async addVectorDocument(text: string, metadata?: Record<string, any>): Promise<{ success: boolean; documentId: number }> {
    const res = await fetch(`${API_BASE}/api/vector-store/documents`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, metadata }),
    });
    if (!res.ok) {
      const error = await res.json();
      throw new Error(error.error || 'Failed to add document');
    }
    return res.json();
  },

  async listVectorDocuments(page: number = 1, pageSize: number = 10): Promise<PaginatedDocuments> {
    const res = await fetch(`${API_BASE}/api/vector-store/documents?page=${page}&pageSize=${pageSize}`);
    if (!res.ok) {
      const error = await res.json();
      throw new Error(error.error || 'Failed to list documents');
    }
    return res.json();
  },

  async getVectorDocument(docId: number): Promise<VectorDocument> {
    const res = await fetch(`${API_BASE}/api/vector-store/documents/${docId}`);
    if (!res.ok) {
      const error = await res.json();
      throw new Error(error.error || 'Failed to get document');
    }
    const data = await res.json();
    return data.document;
  },

  async deleteVectorDocument(docId: number): Promise<{ success: boolean }> {
    const res = await fetch(`${API_BASE}/api/vector-store/documents/${docId}`, {
      method: 'DELETE',
    });
    if (!res.ok) {
      const error = await res.json();
      throw new Error(error.error || 'Failed to delete document');
    }
    return res.json();
  },

  async indexConnectorToVectorStore(connectorId: string): Promise<IndexConnectorResult> {
    const res = await fetch(`${API_BASE}/api/vector-store/index-connector/${connectorId}`, {
      method: 'POST',
    });
    if (!res.ok) {
      const error = await res.json();
      throw new Error(error.error || 'Failed to index connector');
    }
    return res.json();
  },

  async indexUploadsToVectorStore(): Promise<IndexConnectorResult & { indexed?: string[]; skipped?: string[] }> {
    const res = await fetch(`${API_BASE}/api/vector-store/index-uploads`, {
      method: 'POST',
    });
    if (!res.ok) {
      const error = await res.json();
      throw new Error(error.error || 'Failed to index uploads');
    }
    return res.json();
  },

  async indexFileToVectorStore(filename: string): Promise<{ success: boolean; documentId: number; filename: string; textLength: number }> {
    const res = await fetch(`${API_BASE}/api/vector-store/index-file/${encodeURIComponent(filename)}`, {
      method: 'POST',
    });
    if (!res.ok) {
      const error = await res.json();
      throw new Error(error.error || 'Failed to index file');
    }
    return res.json();
  },

  // Topic-related API methods

  async getAllTopics(): Promise<AllTopicsResult> {
    const res = await fetch(`${API_BASE}/api/vector-store/topics`);
    if (!res.ok) {
      const error = await res.json();
      throw new Error(error.error || 'Failed to get topics');
    }
    return res.json();
  },

  async getDocumentsByTopic(topic: string, page: number = 1, pageSize: number = 10): Promise<PaginatedDocumentsByTopic> {
    const res = await fetch(`${API_BASE}/api/vector-store/topics/${encodeURIComponent(topic)}/documents?page=${page}&pageSize=${pageSize}`);
    if (!res.ok) {
      const error = await res.json();
      throw new Error(error.error || 'Failed to get documents by topic');
    }
    return res.json();
  },

  async getDocumentTopics(docId: number): Promise<DocumentTopics> {
    const res = await fetch(`${API_BASE}/api/documents/${docId}/topics`);
    if (!res.ok) {
      const error = await res.json();
      throw new Error(error.error || 'Failed to get document topics');
    }
    return res.json();
  },

  async updateDocumentTopics(docId: number, topics: string[], primaryTopic?: string): Promise<{ success: boolean }> {
    const res = await fetch(`${API_BASE}/api/documents/${docId}/topics`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ topics, primaryTopic }),
    });
    if (!res.ok) {
      const error = await res.json();
      throw new Error(error.error || 'Failed to update document topics');
    }
    return res.json();
  },

  async generateTopics(docId: number, numTopics: number = 3, predefinedTopics?: string[]): Promise<GenerateTopicsResult> {
    const res = await fetch(`${API_BASE}/api/documents/${docId}/topics/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ numTopics, predefinedTopics }),
    });
    if (!res.ok) {
      const error = await res.json();
      throw new Error(error.error || 'Failed to generate topics');
    }
    return res.json();
  },

  async searchWithTopic(query: string, topic?: string, topK: number = 5, minScore?: number): Promise<SearchWithTopicResponse> {
    const res = await fetch(`${API_BASE}/api/vector-store/search/with-topic`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, topic, topK, minScore }),
    });
    if (!res.ok) {
      const error = await res.json();
      throw new Error(error.error || 'Search with topic failed');
    }
    return res.json();
  },

  // Knowledge Graph API methods

  async getKnowledgeGraph(options: KnowledgeGraphOptions = {}): Promise<KnowledgeGraphResponse> {
    const {
      includeDocuments = true,
      includeTopics = true,
      includeEntities = true,
      entityTypes,
      minConnections = 2,
      limitDocuments = 200,
      limitEntitiesPerType = 15,
      maxTopicEdgesPerDoc = 3,
      maxEntityEdgesPerDoc = 5,
    } = options;

    const res = await fetch(`${API_BASE}/api/vector-store/graph`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        include_documents: includeDocuments,
        include_topics: includeTopics,
        include_entities: includeEntities,
        entity_types: entityTypes,
        min_connections: minConnections,
        limit_documents: limitDocuments,
        limit_entities_per_type: limitEntitiesPerType,
        max_topic_edges_per_doc: maxTopicEdgesPerDoc,
        max_entity_edges_per_doc: maxEntityEdgesPerDoc,
      }),
    });
    if (!res.ok) {
      const error = await res.json();
      throw new Error(error.error || 'Failed to get knowledge graph');
    }
    return res.json();
  },

  async getGraphNodeDetails(nodeId: string): Promise<GraphNodeDetails> {
    const res = await fetch(`${API_BASE}/api/vector-store/graph/node/${encodeURIComponent(nodeId)}`);
    if (!res.ok) {
      const error = await res.json();
      throw new Error(error.error || 'Failed to get node details');
    }
    return res.json();
  },

  async getDebugInfo(): Promise<DebugInfo> {
    const res = await fetch(`${API_BASE}/api/vector-store/debug`);
    if (!res.ok) {
      throw new Error('Failed to get debug info');
    }
    return res.json();
  },

  async clearAllData(): Promise<{ success: boolean; vectorStore?: { deleted: number }; filesDeleted: number; importsDeleted: number }> {
    const res = await fetch(`${API_BASE}/api/data/clear-all`, { method: 'POST' });
    if (!res.ok) {
      const error = await res.json();
      throw new Error(error.error || 'Failed to clear data');
    }
    return res.json();
  },

  // Media file extensions that should be routed to the media processor
  _mediaExtensions: new Set([
    '.wav', '.mp3', '.flac', '.ogg', '.m4a', '.wma', '.aac', '.webm',
    '.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.tiff', '.tif',
  ]),

  _isMediaFile(filename: string): boolean {
    const ext = filename.slice(filename.lastIndexOf('.')).toLowerCase();
    return this._mediaExtensions.has(ext);
  },

  // Upload files with progress callback
  // Automatically routes media files (audio/image) to the media processor
  async uploadFiles(
    files: FileList | File[],
    onProgress?: (progress: number) => void
  ): Promise<{ success: boolean; files: { name: string; size: number }[]; count: number }> {
    const fileArray = Array.from(files);
    const textFiles = fileArray.filter(f => !this._isMediaFile(f.name));
    const mediaFiles = fileArray.filter(f => this._isMediaFile(f.name));

    const totalSize = fileArray.reduce((s, f) => s + f.size, 0);
    let uploadedBytes = 0;

    const results: { name: string; size: number }[] = [];

    // Upload text files via standard endpoint
    if (textFiles.length > 0) {
      await new Promise<void>((resolve, reject) => {
        const formData = new FormData();
        textFiles.forEach(file => formData.append('files', file));

        const xhr = new XMLHttpRequest();
        xhr.upload.addEventListener('progress', (e) => {
          if (e.lengthComputable && onProgress) {
            const progress = Math.round(((uploadedBytes + e.loaded) / totalSize) * 100);
            onProgress(Math.min(progress, 99));
          }
        });
        xhr.addEventListener('load', () => {
          if (xhr.status >= 200 && xhr.status < 300) {
            const res = JSON.parse(xhr.responseText);
            uploadedBytes += textFiles.reduce((s, f) => s + f.size, 0);
            if (res.files) results.push(...res.files);
            resolve();
          } else {
            reject(new Error(`Upload failed: ${xhr.statusText}`));
          }
        });
        xhr.addEventListener('error', () => reject(new Error('Upload failed')));
        xhr.open('POST', `${API_BASE}/api/files/upload`);
        xhr.send(formData);
      });
    }

    // Upload media files one at a time via media processor
    for (const file of mediaFiles) {
      const mediaResult = await this.uploadMedia(file, (p) => {
        if (onProgress) {
          const progress = Math.round(((uploadedBytes + (file.size * p / 100)) / totalSize) * 100);
          onProgress(Math.min(progress, 99));
        }
      });
      uploadedBytes += file.size;
      results.push({ name: file.name, size: file.size });
      if (!mediaResult.success && !mediaResult.is_duplicate) {
        throw new Error(mediaResult.error || `Failed to process ${file.name}`);
      }
    }

    if (onProgress) onProgress(100);
    return { success: true, files: results, count: results.length };
  },

  // Upload media file with progress callback
  uploadMedia(
    file: File,
    onProgress?: (progress: number) => void
  ): Promise<MediaUploadResult> {
    return new Promise((resolve, reject) => {
      const formData = new FormData();
      formData.append('file', file);

      const xhr = new XMLHttpRequest();

      xhr.upload.addEventListener('progress', (e) => {
        if (e.lengthComputable && onProgress) {
          const progress = Math.round((e.loaded / e.total) * 100);
          onProgress(progress);
        }
      });

      xhr.addEventListener('load', () => {
        try {
          const result = JSON.parse(xhr.responseText);
          if (xhr.status >= 200 && xhr.status < 300) {
            resolve(result);
          } else {
            reject(new Error(result.error || `Upload failed: ${xhr.statusText}`));
          }
        } catch {
          reject(new Error(`Upload failed: ${xhr.statusText}`));
        }
      });

      xhr.addEventListener('error', () => {
        reject(new Error('Media upload failed - network error'));
      });

      xhr.open('POST', `${API_BASE}/api/vector-store/media/upload`);
      xhr.send(formData);
    });
  },

  async getMediaStatus(): Promise<MediaStatus> {
    const res = await fetch(`${API_BASE}/api/vector-store/media/status`);
    if (!res.ok) {
      throw new Error('Failed to get media status');
    }
    return res.json();
  },

  // Chat API
  async getChatStatus(): Promise<ChatStatus> {
    const res = await fetch(`${API_BASE}/api/chat/status`);
    if (!res.ok) {
      throw new Error('Failed to get chat status');
    }
    return res.json();
  },

  async sendChatMessage(request: ChatRequest): Promise<ChatResponse> {
    const res = await fetch(`${API_BASE}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    });
    if (!res.ok) {
      const error = await res.json();
      throw new Error(error.error || 'Chat request failed');
    }
    return res.json();
  },

  async *streamChatMessage(request: ChatRequest, signal?: AbortSignal): AsyncGenerator<StreamEvent> {
    const res = await fetch(`${API_BASE}/api/chat/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
      signal,
    });

    if (!res.ok) {
      const error = await res.json();
      throw new Error(error.error || 'Stream request failed');
    }

    const reader = res.body?.getReader();
    if (!reader) {
      throw new Error('No response body');
    }

    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const data = line.slice(6);
          if (data === '[DONE]') {
            return;
          }
          try {
            const event: StreamEvent = JSON.parse(data);
            yield event;
          } catch {
            // Skip invalid JSON
          }
        }
      }
    }
  },

  // LLM Config API
  async getLLMConfig(): Promise<LLMConfig> {
    const res = await fetch(`${API_BASE}/api/chat/config`);
    if (!res.ok) {
      throw new Error('Failed to get LLM config');
    }
    return res.json();
  },

  async updateLLMConfig(update: LLMConfigUpdate): Promise<LLMConfig> {
    const res = await fetch(`${API_BASE}/api/chat/config`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(update),
    });
    if (!res.ok) {
      const error = await res.json();
      throw new Error(error.error || 'Failed to update LLM config');
    }
    return res.json();
  },

  async testApiKey(provider: LLMProvider, apiKey: string): Promise<TestKeyResult> {
    const res = await fetch(`${API_BASE}/api/chat/config/test`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider, apiKey }),
    });
    if (!res.ok) {
      const error = await res.json();
      throw new Error(error.error || 'Failed to test API key');
    }
    return res.json();
  },

  // PII API
  async getPIIStatus(): Promise<PIIStatus> {
    const res = await fetch(`${API_BASE}/api/pii/status`);
    if (!res.ok) {
      throw new Error('Failed to get PII status');
    }
    return res.json();
  },

  async deanonymize(text: string, sessionId: string): Promise<{ text: string; tokens_replaced: number }> {
    const res = await fetch(`${API_BASE}/api/pii/deanonymize`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, session_id: sessionId }),
    });
    if (!res.ok) {
      const error = await res.json();
      throw new Error(error.error || 'Deanonymization failed');
    }
    const data = await res.json();
    // Map backend field name to frontend expected name
    return {
      text: data.deanonymized_text,
      tokens_replaced: data.tokens_replaced,
    };
  },

  // Voice Chat v2 API (WebRTC)
  async getVoiceStatus(): Promise<VoiceStatus> {
    const res = await fetch(`${API_BASE}/api/voice/status`);
    if (!res.ok) throw new Error('Failed to get voice status');
    return res.json();
  },

  async getVoiceConfig(): Promise<VoiceConfig> {
    const res = await fetch(`${API_BASE}/api/voice/config`);
    if (!res.ok) throw new Error('Failed to get voice config');
    return res.json();
  },

  async updateVoiceConfig(config: Partial<VoiceConfig>): Promise<VoiceConfig> {
    const res = await fetch(`${API_BASE}/api/voice/config`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(config),
    });
    if (!res.ok) throw new Error('Failed to update voice config');
    return res.json();
  },

  async sendWebRTCOffer(offer: WebRTCOffer): Promise<WebRTCAnswer> {
    const res = await fetch(`${API_BASE}/api/voice/webrtc/offer`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(offer),
    });
    if (!res.ok) {
      const error = await res.json().catch(() => ({ error: 'WebRTC offer failed' }));
      throw new Error(error.error || 'WebRTC offer failed');
    }
    return res.json();
  },

  connectVoiceOutputs(webrtcId: string): EventSource {
    return new EventSource(`${API_BASE}/api/voice/outputs?webrtc_id=${webrtcId}`);
  },

  async disconnectVoice(): Promise<void> {
    await fetch(`${API_BASE}/api/voice/disconnect`, { method: 'POST' }).catch(() => {});
  },

  // Extraction queue status (may not be available on all backends)
  async getExtractionQueueStatus(): Promise<{
    pending: number;
    processing: number;
    completed_today: number;
    failed_today: number;
    current_task?: {
      doc_id: number;
      stage: string;
      started_at: number;
    };
  } | null> {
    try {
      const res = await fetch(`${API_BASE}/api/vector-store/extraction/status`);
      if (!res.ok) return null;
      return res.json();
    } catch {
      return null;
    }
  },

  // Browser Connector
  async getBrowserConnectorStatus(): Promise<BrowserConnectorStatus> {
    const res = await fetch(`${API_BASE}/api/browser-connector/status`);
    await assertOk(res, 'Failed to get browser connector status');
    return res.json();
  },

  async launchBrowser(options?: { headed?: boolean; startUrl?: string; vnc?: boolean; vncPort?: number; wsPort?: number }): Promise<{ success: boolean; status: BrowserConnectorStatus }> {
    const res = await fetch(`${API_BASE}/api/browser-connector/launch`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(options || {}),
    });
    await assertOk(res, 'Failed to launch browser');
    return res.json();
  },

  async closeBrowser(): Promise<{ success: boolean }> {
    const res = await fetch(`${API_BASE}/api/browser-connector/close`, {
      method: 'POST',
    });
    await assertOk(res, 'Failed to close browser');
    return res.json();
  },

  async navigateBrowser(url: string): Promise<{ success: boolean }> {
    const res = await fetch(`${API_BASE}/api/browser-connector/navigate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }),
    });
    await assertOk(res, 'Failed to navigate browser');
    return res.json();
  },

  async getBrowserConnectorConfig(): Promise<BrowserConnectorConfig> {
    const res = await fetch(`${API_BASE}/api/browser-connector/config`);
    await assertOk(res, 'Failed to get browser connector config');
    return res.json();
  },

  async updateBrowserConnectorConfig(config: Partial<BrowserConnectorConfig>): Promise<{ success: boolean; config: BrowserConnectorConfig }> {
    const res = await fetch(`${API_BASE}/api/browser-connector/config`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(config),
    });
    await assertOk(res, 'Failed to update browser connector config');
    return res.json();
  },

  async getBrowserCaptureStats(): Promise<BrowserCaptureStats> {
    const res = await fetch(`${API_BASE}/api/browser-connector/stats`);
    await assertOk(res, 'Failed to get capture stats');
    return res.json();
  },

  async getCapturedConversations(options?: { site?: SupportedSite; limit?: number; offset?: number }): Promise<{ conversations: CapturedConversationSummary[]; total: number }> {
    const params = new URLSearchParams();
    if (options?.site) params.append('site', options.site);
    if (options?.limit) params.append('limit', options.limit.toString());
    if (options?.offset) params.append('offset', options.offset.toString());
    const res = await fetch(`${API_BASE}/api/browser-connector/conversations?${params}`);
    await assertOk(res, 'Failed to get captured conversations');
    return res.json();
  },

  async getCapturedConversation(id: string): Promise<CapturedConversation> {
    const res = await fetch(`${API_BASE}/api/browser-connector/conversations/${id}`);
    await assertOk(res, 'Failed to get conversation');
    return res.json();
  },

  async deleteCapturedConversation(id: string): Promise<{ success: boolean }> {
    const res = await fetch(`${API_BASE}/api/browser-connector/conversations/${id}`, {
      method: 'DELETE',
    });
    await assertOk(res, 'Failed to delete conversation');
    return res.json();
  },

  async reindexCapturedConversations(): Promise<{ success: boolean; success_count: number; failed: number }> {
    const res = await fetch(`${API_BASE}/api/browser-connector/reindex`, {
      method: 'POST',
    });
    await assertOk(res, 'Failed to reindex conversations');
    return res.json();
  },

  // VNC
  async getVncStatus(): Promise<VncStatus> {
    const res = await fetch(`${API_BASE}/api/browser-connector/vnc/status`);
    await assertOk(res, 'Failed to get VNC status');
    return res.json();
  },

  async checkVncAvailable(): Promise<VncCheckResult> {
    const res = await fetch(`${API_BASE}/api/browser-connector/vnc/check`);
    await assertOk(res, 'Failed to check VNC availability');
    return res.json();
  },

  // Auth status
  async getAuthStatus(site?: SupportedSite): Promise<AuthStatus> {
    const params = site ? `?site=${site}` : '';
    const res = await fetch(`${API_BASE}/api/browser-connector/auth-status${params}`);
    await assertOk(res, 'Failed to get auth status');
    return res.json();
  },

  async clearAuth(site?: SupportedSite): Promise<{ success: boolean }> {
    const params = site ? `?site=${site}` : '';
    const res = await fetch(`${API_BASE}/api/browser-connector/auth${params}`, {
      method: 'DELETE',
    });
    await assertOk(res, 'Failed to clear auth');
    return res.json();
  },

  // Get all sites with auth status
  async getSites(): Promise<SitesResponse> {
    const res = await fetch(`${API_BASE}/api/browser-connector/sites`);
    await assertOk(res, 'Failed to get sites');
    return res.json();
  },

  // Navigate to a site in existing VNC session
  async navigateToSite(site: SupportedSite, forSync?: boolean): Promise<{ success: boolean; url: string }> {
    const res = await fetch(`${API_BASE}/api/browser-connector/navigate-to-site`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ site, forSync }),
    });
    await assertOk(res, 'Failed to navigate to site');
    return res.json();
  },

  // Headless sync
  async triggerSync(site?: SupportedSite): Promise<SyncResult & { site?: SupportedSite }> {
    const res = await fetch(`${API_BASE}/api/browser-connector/sync`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ site }),
    });
    await assertOk(res, 'Failed to trigger sync');
    return res.json();
  },

  // Auto-sync
  async getAutoSyncStatus(): Promise<AutoSyncStatus> {
    const res = await fetch(`${API_BASE}/api/browser-connector/auto-sync`);
    await assertOk(res, 'Failed to get auto-sync status');
    return res.json();
  },

  async startAutoSync(intervalHours?: number): Promise<{ success: boolean; status: AutoSyncStatus }> {
    const res = await fetch(`${API_BASE}/api/browser-connector/auto-sync/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ intervalHours }),
    });
    await assertOk(res, 'Failed to start auto-sync');
    return res.json();
  },

  async stopAutoSync(): Promise<{ success: boolean }> {
    const res = await fetch(`${API_BASE}/api/browser-connector/auto-sync/stop`, {
      method: 'POST',
    });
    await assertOk(res, 'Failed to stop auto-sync');
    return res.json();
  },

  async setAutoSyncInterval(hours: number): Promise<{ success: boolean; status: AutoSyncStatus }> {
    const res = await fetch(`${API_BASE}/api/browser-connector/auto-sync/interval`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ hours }),
    });
    await assertOk(res, 'Failed to set auto-sync interval');
    return res.json();
  },

  // Manual connections
  async createManualConnection(source: string, target: string): Promise<ManualConnection> {
    const res = await fetch(`${API_BASE}/api/vector-store/graph/connections`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source, target }),
    });
    if (!res.ok) throw new Error('Failed to create connection');
    return res.json();
  },

  async deleteManualConnection(connectionId: string): Promise<void> {
    const res = await fetch(`${API_BASE}/api/vector-store/graph/connections/${encodeURIComponent(connectionId)}`, {
      method: 'DELETE',
    });
    if (!res.ok) throw new Error('Failed to delete connection');
  },

  // Saved views
  async getSavedViews(): Promise<SavedViewSummary[]> {
    const res = await fetch(`${API_BASE}/api/vector-store/graph/views`);
    if (!res.ok) throw new Error('Failed to get saved views');
    const data = await res.json();
    return data.views;
  },

  async getSavedView(viewId: string): Promise<SavedView> {
    const res = await fetch(`${API_BASE}/api/vector-store/graph/views/${encodeURIComponent(viewId)}`);
    if (!res.ok) throw new Error('Failed to get saved view');
    return res.json();
  },

  async saveView(view: Omit<SavedView, 'id' | 'createdAt'>): Promise<{ id: string }> {
    const res = await fetch(`${API_BASE}/api/vector-store/graph/views`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(view),
    });
    if (!res.ok) throw new Error('Failed to save view');
    return res.json();
  },

  async deleteSavedView(viewId: string): Promise<void> {
    const res = await fetch(`${API_BASE}/api/vector-store/graph/views/${encodeURIComponent(viewId)}`, {
      method: 'DELETE',
    });
    if (!res.ok) throw new Error('Failed to delete view');
  },
};

// =============================================================================
// Hub-compatible API exports
// These functions wrap the api object methods to match the mindsage-hub interface
// =============================================================================

import type {
  VectorDocument as HubVectorDocument,
  VectorSearchResult as HubVectorSearchResult,
  GraphData,
  NodeType,
  Connector as HubConnector,
  LocalSendStatus as HubLocalSendStatus,
  MCPStatus,
  ManualConnection,
  SavedView,
  SavedViewSummary,
} from '@/types';

// Helper to generate a display name for documents/chunks
export function getDisplayName(id: number, metadata?: Record<string, any>): string {
  // First, try to get filename from various possible metadata fields
  const filename = metadata?.filename || metadata?.original_filename || metadata?.title;
  if (filename) {
    return filename;
  }
  // For chunks without a filename, show chunk info with parent filename if available
  if (metadata?.is_chunk && metadata?.chunk_index !== undefined) {
    const chunkNum = metadata.chunk_index + 1;
    const total = metadata.total_chunks || '?';
    const parentName = metadata.parent_filename || metadata.source_filename;
    if (parentName) {
      return `${parentName} (Excerpt ${chunkNum} of ${total})`;
    }
    // Use parent_id if available, otherwise use the chunk's own id
    const docId = metadata.parent_id || id;
    return `Document ${docId} (Excerpt ${chunkNum} of ${total})`;
  }
  // Last resort: try to extract something useful from source
  if (metadata?.source && metadata.source !== 'unknown') {
    return metadata.source;
  }
  return `Document ${id}`;
}

/**
 * Normalize hybrid search scores to a 0-100% scale for display.
 *
 * txtai hybrid search produces scores typically in 0.15-0.65 range due to
 * BM25 + semantic score combination and normalization. This function maps
 * those scores to a more intuitive percentage scale.
 *
 * Approach: Use relative ranking where top result anchors at ~95% and
 * others scale proportionally, with a floor of 40% for any returned result.
 */
function normalizeScoreForDisplay(score: number, maxScore: number): number {
  if (maxScore <= 0) return 50;

  // Calculate relative score (0-1 based on max in result set)
  const relativeScore = score / maxScore;

  // Map to display range: 40-98%
  // Top result (relativeScore=1) → 98%
  // Lowest relevant result → ~40-60% depending on actual score
  const displayMin = 40;
  const displayMax = 98;

  // Use sqrt to compress the scale slightly (makes mid-range scores look better)
  const normalized = Math.sqrt(relativeScore);

  const displayScore = displayMin + (normalized * (displayMax - displayMin));

  return Math.round(displayScore);
}

// Search functions
export async function search(query: string, topK: number = 10): Promise<HubVectorSearchResult[]> {
  // Use minScore of 0.0 to let txtai hybrid search return all relevant results
  // The hybrid search scoring (BM25 + semantic) produces scores typically in 0.2-0.6 range
  const response = await api.enhancedSearch(query, { topK, minScore: 0.0, extractPassages: true });

  // Find max score for relative normalization
  const maxScore = response.results.length > 0
    ? Math.max(...response.results.map(r => r.score))
    : 1;

  // Map results, resolving chunk IDs to parent document IDs
  const mapped = response.results.map(r => ({
    id: r.id,
    parentDocId: r.metadata?.parent_id ?? r.id,
    filename: getDisplayName(r.id, r.metadata),
    excerpt: r.excerpt,
    score: r.score,
    displayScore: normalizeScoreForDisplay(r.score, maxScore), // 0-100% for UI
    topics: r.topics || [],
    source: r.metadata?.source || 'unknown',
    excerptMethod: r.excerpt_method === 'llm_extract' ? 'ai' : r.excerpt_method === 'precomputed' ? 'indexed' : 'context',
  }));

  // Deduplicate by parent document, keeping the highest-scoring chunk per document
  const seen = new Set<number>();
  return mapped.filter(r => {
    if (seen.has(r.parentDocId)) return false;
    seen.add(r.parentDocId);
    return true;
  });
}

export async function searchWithTopic(
  query: string,
  topic: string,
  topK: number = 10
): Promise<HubVectorSearchResult[]> {
  const response = await api.searchWithTopic(query, topic, topK);

  // Find max score for relative normalization
  const maxScore = response.results.length > 0
    ? Math.max(...response.results.map(r => r.score))
    : 1;

  // Map results, resolving chunk IDs to parent document IDs
  const mapped = response.results.map(r => ({
    id: r.id,
    parentDocId: r.metadata?.parent_id ?? r.id,
    filename: getDisplayName(r.id, r.metadata),
    excerpt: r.text.slice(0, 500),
    score: r.score,
    displayScore: normalizeScoreForDisplay(r.score, maxScore),
    topics: r.topics || [],
    source: r.metadata?.source || 'unknown',
    excerptMethod: 'indexed' as const,
  }));

  // Deduplicate by parent document, keeping the highest-scoring chunk per document
  const seen = new Set<number>();
  return mapped.filter(r => {
    if (seen.has(r.parentDocId)) return false;
    seen.add(r.parentDocId);
    return true;
  });
}

export async function getAllTopics(): Promise<string[]> {
  const response = await api.getAllTopics();
  return response.topics.map(t => t.name);
}

// Document functions
export async function listVectorDocuments(
  page: number,
  pageSize: number
): Promise<{ documents: HubVectorDocument[]; total: number }> {
  const response = await api.listVectorDocuments(page, pageSize);
  return {
    documents: response.documents.map(d => {
      const fileType = getFileType(d.metadata?.filename || '', d.metadata);
      return {
        id: d.id,
        filename: getDisplayName(d.id, d.metadata),
        content: d.text,
        topics: d.topics || [],
        primaryTopic: d.primary_topic,
        source: d.metadata?.source || 'unknown',
        createdAt: d.created_at,
        wordCount: d.text.split(/\s+/).length,
        fileType,
        extension: getExtension(d.metadata?.filename || ''),
        // Image metadata
        mediaType: d.metadata?.media_type,
        imageId: d.metadata?.image_id,
        caption: d.metadata?.caption,
        width: d.metadata?.width,
        height: d.metadata?.height,
        hasPii: d.metadata?.has_pii,
        piiTypesFound: d.metadata?.pii_types_found,
        // Audio metadata
        audioMetadata: extractAudioMetadata(d.metadata),
      };
    }),
    total: response.total,
  };
}

export async function getVectorDocument(id: number): Promise<HubVectorDocument | null> {
  try {
    const doc = await api.getVectorDocument(id);
    const fileType = getFileType(doc.metadata?.filename || '', doc.metadata);
    return {
      id: doc.id,
      filename: getDisplayName(doc.id, doc.metadata),
      content: doc.text,
      topics: doc.topics || [],
      primaryTopic: doc.primary_topic,
      source: doc.metadata?.source || 'unknown',
      createdAt: doc.created_at,
      wordCount: doc.text.split(/\s+/).length,
      fileType,
      extension: getExtension(doc.metadata?.filename || ''),
      // Image metadata
      mediaType: doc.metadata?.media_type,
      imageId: doc.metadata?.image_id,
      caption: doc.metadata?.caption,
      width: doc.metadata?.width,
      height: doc.metadata?.height,
      hasPii: doc.metadata?.has_pii,
      piiTypesFound: doc.metadata?.pii_types_found,
      redactionPending: doc.metadata?.redaction_pending,
      redactionComplete: doc.metadata?.redaction_complete,
      // Audio metadata
      audioMetadata: extractAudioMetadata(doc.metadata),
    };
  } catch {
    return null;
  }
}

export async function deleteVectorDocument(id: number): Promise<void> {
  await api.deleteVectorDocument(id);
}

// Knowledge Graph
export async function getKnowledgeGraph(): Promise<GraphData> {
  const response = await api.getKnowledgeGraph();

  // Build topic label lookup from topic nodes
  const topicLabelMap = new Map<string, string>();
  for (const n of response.nodes) {
    if (n.type === 'topic') {
      topicLabelMap.set(n.id, n.label);
    }
  }

  // Build document-to-topics mapping from has_topic edges.
  // Backend edge direction: source=topic_node_id, target=doc_node_id
  const docTopicsMap = new Map<string, string[]>();
  const topicDocCount = new Map<string, number>();
  for (const e of response.edges) {
    if (e.type === 'has_topic') {
      // e.source = topic_id, e.target = doc_id
      const docId = e.target;
      const topicId = e.source;
      const topicLabel = topicLabelMap.get(topicId);
      if (topicLabel) {
        const topics = docTopicsMap.get(docId) || [];
        topics.push(topicLabel);
        docTopicsMap.set(docId, topics);
      }
      topicDocCount.set(topicId, (topicDocCount.get(topicId) || 0) + 1);
    }
  }

  const nodes = response.nodes.map(n => ({
    id: n.id,
    label: n.label,
    type: n.type,
    connectionCount: n.metadata?.connection_count || 0,
    preview: n.metadata?.text_preview,
    topics: n.type === 'document' ? (docTopicsMap.get(n.id) || []) : undefined,
    docCount: n.type === 'topic' ? (topicDocCount.get(n.id) || 0) : undefined,
  }));

  // Build node_types from actual nodes
  const typeCounts: Record<string, number> = {};
  for (const n of nodes) {
    typeCounts[n.type] = (typeCounts[n.type] || 0) + 1;
  }
  const typeLabels: Record<string, string> = {
    document: 'Documents', topic: 'Topics', person: 'Persons',
    organization: 'Organizations', location: 'Locations', technology: 'Technologies',
  };
  const node_types = Object.entries(typeCounts).map(([type, count]) => ({
    type: type as NodeType,
    label: typeLabels[type] || type,
    count,
  }));

  // Build content_types and domains from backend filters (now returns count objects)
  // Backend may return strings (legacy) or {type, label, count} objects
  type BackendFilterItem = string | { type: string; label?: string; count?: number };
  const backendFilters = (response.available_filters || {}) as { content_types?: BackendFilterItem[]; domains?: BackendFilterItem[] };
  const content_types = (backendFilters.content_types || []).map((ct) => {
    // Handle both new format {type, label, count} and legacy string format
    if (typeof ct === 'string') return { type: ct, label: ct, count: 0 };
    return { type: ct.type, label: ct.label || ct.type, count: ct.count || 0 };
  });
  const domains = (backendFilters.domains || []).map((d) => {
    if (typeof d === 'string') return { type: d, label: d, count: 0 };
    return { type: d.type, label: d.label || d.type, count: d.count || 0 };
  });

  return {
    nodes,
    edges: response.edges.map(e => ({
      id: `${e.source}-${e.target}`,
      source: e.source,
      target: e.target,
      edgeType: e.type,
    })),
    availableFilters: {
      node_types,
      sources: [],
      content_types,
      domains,
    },
  };
}

// Default connector definitions - always shown on dashboard
const DEFAULT_CONNECTORS: { type: HubConnector['type']; name: string }[] = [
  { type: 'chatgpt', name: 'ChatGPT' },
  { type: 'claude', name: 'Claude' },
  { type: 'notion', name: 'Notion' },
];

// Connectors
export async function getConnectors(): Promise<HubConnector[]> {
  const backendConnectors = await api.getConnectors();

  // Create a map of backend connectors by their normalized name
  const backendMap = new Map<string, Connector>();
  for (const c of backendConnectors) {
    // Try to match by name (case-insensitive) or by config.type
    const normalizedName = c.name.toLowerCase().replace(/[^a-z]/g, '');
    backendMap.set(normalizedName, c);
    // Also map by config.connectorType if present
    if (c.config?.connectorType) {
      backendMap.set(c.config.connectorType.toLowerCase(), c);
    }
  }

  // Build the connector list with default connectors
  return DEFAULT_CONNECTORS.map(def => {
    const normalizedType = def.type.toLowerCase();
    const backendConnector = backendMap.get(normalizedType) || backendMap.get(def.name.toLowerCase().replace(/[^a-z]/g, ''));

    if (backendConnector) {
      return {
        id: backendConnector.id,
        type: def.type,
        name: def.name,
        connected: backendConnector.status === 'connected' || backendConnector.status === 'syncing',
        itemCount: backendConnector.itemCount,
        lastSync: backendConnector.lastSync,
        config: backendConnector.config,
      };
    }

    // Return disconnected default connector
    return {
      id: def.type, // Use type as placeholder ID until connected
      type: def.type,
      name: def.name,
      connected: false,
      itemCount: 0,
    };
  });
}

export async function syncConnector(id: string): Promise<void> {
  await api.syncConnector(id);
}

export async function disconnectConnector(id: string): Promise<void> {
  await api.deleteConnector(id);
}

// File upload
export async function uploadFiles(
  files: FileList,
  onProgress?: (percent: number) => void
): Promise<void> {
  await api.uploadFiles(files, onProgress);
}

// LocalSend
export async function getLocalSendStatus(): Promise<HubLocalSendStatus> {
  const status = await api.getLocalSendStatus();
  return {
    running: status.running,
    deviceName: status.deviceName,
    port: status.port,
  };
}

export async function startLocalSend(): Promise<void> {
  await api.startLocalSend();
}

export async function stopLocalSend(): Promise<void> {
  await api.stopLocalSend();
}

// MCP Status
export async function getMCPStatus(): Promise<MCPStatus> {
  const status = await api.getVectorStoreStatus();
  return {
    ready: status.available,
    url: `http://${status.host}:${status.port}`,
    documentCount: status.total_files || 0,
  };
}

// Server Info
export async function getServerInfo(): Promise<{ ip: string; port: number; url: string }> {
  const info = await api.getServerInfo();
  return {
    ip: info.ipAddress,
    port: info.port,
    url: info.url,
  };
}

// Helper functions
function getFileType(filename: string, metadata?: Record<string, any>): 'code' | 'document' | 'data' | 'text' | 'audio' | 'image' {
  // Check metadata for media type first
  if (metadata?.media_type === 'audio') return 'audio';
  if (metadata?.media_type === 'image') return 'image';

  const ext = getExtension(filename).toLowerCase();
  const codeExts = ['ts', 'tsx', 'js', 'jsx', 'py', 'java', 'cpp', 'c', 'h', 'rs', 'go', 'rb', 'php'];
  const docExts = ['md', 'txt', 'doc', 'docx', 'pdf'];
  const dataExts = ['json', 'csv', 'xml', 'yaml', 'yml'];
  const audioExts = ['wav', 'mp3', 'flac', 'ogg', 'm4a', 'wma', 'aac', 'webm'];
  const imageExts = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'tiff', 'heic', 'svg'];

  if (codeExts.includes(ext)) return 'code';
  if (docExts.includes(ext)) return 'document';
  if (dataExts.includes(ext)) return 'data';
  if (audioExts.includes(ext)) return 'audio';
  if (imageExts.includes(ext)) return 'image';
  return 'text';
}

// Extract audio metadata from vector store metadata
function extractAudioMetadata(metadata: Record<string, any>): import('@/types').AudioMetadata | undefined {
  if (metadata?.media_type !== 'audio') return undefined;

  return {
    mediaType: 'audio',
    audioId: metadata.audio_id,
    format: metadata.format || '',
    durationSeconds: metadata.duration_seconds,
    sampleRate: metadata.sample_rate,
    channels: metadata.channels,
    originalTranscript: metadata.original_transcript,
    redactedTranscript: metadata.redacted_transcript,
    hasPii: metadata.has_pii,
    piiTypesFound: metadata.pii_types_found,
    piiRegions: metadata.pii_regions?.map((r: any) => ({
      startTime: r.start_time,
      endTime: r.end_time,
      piiType: r.pii_type,
      originalText: r.original_text,
      replacementText: r.replacement_text,
      confidence: r.confidence,
    })),
    wordCount: metadata.word_count,
    piiProcessingTimeMs: metadata.pii_processing_time_ms,
    redactedAudioPath: metadata.redacted_audio_path,
  };
}

function getExtension(filename: string): string {
  const parts = filename.split('.');
  return parts.length > 1 ? parts[parts.length - 1] : '';
}

