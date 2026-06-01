/**
 * MCP Vector Store Client for MindSage
 *
 * This module provides integration with the mcp-vector-store server
 * for semantic search capabilities across stored data.
 */

import * as http from 'http';
import * as https from 'https';

export interface VectorSearchResult {
  id: number;
  text: string;
  score: number;
  metadata: Record<string, any>;
  topics?: string[];
  primary_topic?: string;
}

export interface VectorDocument {
  id: number;
  text: string;
  metadata: Record<string, any>;
  created_at: string;
  topics?: string[];
  primary_topic?: string;
}

export interface VectorStoreStats {
  total_documents: number;
  total_files?: number;
  embedding_dimension: number;
  db_path: string;
  skip_duplicates?: boolean;
}

export interface AddDocumentResult {
  success: boolean;
  document_id?: number;
  is_duplicate?: boolean;
  existing_document_id?: number;
  content_hash?: string;
  message?: string;
}

export interface AddDocumentsBatchResult {
  success: boolean;
  document_ids: number[];
  count: number;
  duplicates_skipped: number;
  duplicates: Array<{
    existing_document_id: number;
    content_hash: string;
  }>;
  message?: string;
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

export interface VectorStoreConfig {
  host: string;
  port: number;
  apiKey?: string;
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
  min_score?: number;
  results: VectorSearchResult[];
  pii_session_id?: string;
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

export interface KnowledgeGraphResponse {
  nodes: GraphNode[];
  edges: GraphEdge[];
  stats: GraphStats;
}

export interface KnowledgeGraphOptions {
  include_documents?: boolean;
  include_topics?: boolean;
  include_entities?: boolean;
  entity_types?: ('person' | 'organization' | 'location' | 'technology')[];
  min_connections?: number;
  limit_documents?: number;
  limit_entities_per_type?: number;
}

export interface GraphNodeDetails {
  id: string;
  type: string;
  label: string;
  details: Record<string, any>;
}

/**
 * Media Processing Types (Audio & Image)
 */
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

/**
 * PII Protection Types
 */
export interface PIIStatus {
  enabled: boolean;
  reason?: string;
  presidio_available?: boolean;
  analyzer_initialized?: boolean;
  init_error?: string | null;
  active_sessions?: number;
  total_sessions?: number;
  total_tokens?: number;
  max_sessions?: number;
  session_ttl_seconds?: number;
  entities_detected?: string[];
  spacy_model?: string;
}

export interface PIISession {
  session_id: string;
  created_at: string;
  expires_at: string;
  is_expired: boolean;
  token_count: number;
}

export interface DeanonymizeResult {
  deanonymized_text: string;
  session_id: string;
  tokens_replaced: number;
  tokens_not_found: string[];
}

export interface PerturbedValue {
  pii_type: string;
  perturbed_value: string;
  is_lprag: boolean;
}

export interface AnonymizeResult {
  anonymized_text: string;
  session_id: string;
  token_count: number;
  pii_types_found: string[];
  processing_time_ms: number;
  perturbed_values?: PerturbedValue[];
}

/**
 * LPRAG (Locally Private RAG) Types
 * Local Differential Privacy for PII protection
 */
export interface LPRAGStatus {
  enabled: boolean;
  mode: 'token_only' | 'lprag_pure' | 'lprag_hybrid';
  lprag_available: boolean;
  initialized: boolean;
  error?: string | null;
  total_perturbed_values: number;
  engine?: LPRAGEngineStats;
}

export interface LPRAGEngineStats {
  supported_entities: string[];
  embeddings_available: boolean;
  embeddings_model?: string;
  vocabulary_size?: number;
  use_gpu: boolean;
}

export interface LPRAGConfig {
  mode: 'token_only' | 'lprag_pure' | 'lprag_hybrid';
  available: boolean;
  initialized: boolean;
  engine?: LPRAGEngineStats;
  note?: string;
}

/**
 * Consent Management Types
 * User-controlled data sharing preferences
 */
export type ConsentPresetName = 'strict' | 'balanced' | 'open' | 'health_focus' | 'work_only' | 'recent_only' | 'family_protected';
export type DataCategory = 'health' | 'finance' | 'work' | 'personal' | 'social' | 'legal' | 'travel' | 'education' | 'general';

export interface ConsentPreset {
  name: ConsentPresetName;
  description: string;
  allowed_categories: DataCategory[];
  blocked_categories: DataCategory[];
  exposed_pii_types: string[];
}

export interface ConsentPresetsResponse {
  presets: ConsentPreset[];
  categories: DataCategory[];
  default_preset: ConsentPresetName;
}

export interface EntityDefinition {
  name: string;
  aliases?: string[];
  relationship?: string;
}

export interface DocumentRules {
  blocked_ids: number[];
  allowed_ids: number[];
  blocked_sources: string[];
  allowed_sources: string[];
}

export interface TimeRules {
  after?: string;
  before?: string;
  relative?: string;
  date_field: string;
}

export interface EntityRules {
  protect_entities: EntityDefinition[];
  expose_entities: EntityDefinition[];
  protect_relationships: string[];
  expose_relationships: string[];
  default_protect: boolean;
}

export interface ConsentSettings {
  allowed_categories: DataCategory[];
  blocked_categories: DataCategory[];
  exposed_pii_types: string[];
  document_rules: DocumentRules;
  time_rules: TimeRules;
  entity_rules: EntityRules;
}

export interface ConsentSession {
  session_id: string;
  created_at: string;
  last_accessed: string;
  expires_at: string;
  is_expired: boolean;
  consent: ConsentSettings;
}

export interface ConsentSessionCreateRequest {
  session_id?: string;
  preset?: ConsentPresetName;
  allowed_categories?: DataCategory[];
  blocked_categories?: DataCategory[];
  exposed_pii_types?: string[];
  time_rules?: Partial<TimeRules>;
  protect_entities?: (string | EntityDefinition)[];
  expose_entities?: (string | EntityDefinition)[];
}

export interface ConsentSessionUpdateRequest {
  allowed_categories?: DataCategory[];
  blocked_categories?: DataCategory[];
  exposed_pii_types?: string[];
  time_rules?: Partial<TimeRules>;
  protect_entities?: (string | EntityDefinition)[];
  expose_entities?: (string | EntityDefinition)[];
  block_documents?: number[];
  allow_documents?: number[];
}

export interface ConsentStatus {
  available: boolean;
  reason?: string;
  active_sessions: number;
  total_sessions_created: number;
  max_sessions: number;
  session_ttl_seconds: number;
  presets_available: ConsentPresetName[];
  categories_available: DataCategory[];
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
 * Options for enhanced search
 */
export interface EnhancedSearchOptions {
  topK?: number;
  minScore?: number;
  extractPassages?: boolean;
  expandQuery?: boolean;
  maxExcerptLength?: number;
  consentSessionId?: string;
  /** Access context: "user" for direct user access, "llm" for LLM API access.
   *  When "llm", image paths are swapped to redacted versions for PII safety. */
  context?: 'user' | 'llm';
}

/**
 * Response from enhanced search endpoint
 */
export interface EnhancedSearchResponse {
  query: string;
  min_score_threshold: number | null;
  passage_extraction: boolean;
  query_expansion: boolean;
  results: EnhancedSearchResult[];
  pii_session_id?: string;
}

// === Fast Search Types ===

export interface QuickSearchResponse {
  query: string;
  search_mode: string;
  latency_ms: number;
  results: VectorSearchResult[];
}

export interface FileMatch {
  line: number;
  text: string;
  context_before?: string[];
  context_after?: string[];
}

export interface FileSearchResult {
  filename: string;
  path: string;
  source: string;
  file_size: number;
  matches: FileMatch[];
}

export interface FileSearchResponse {
  query: string;
  latency_ms: number;
  results: FileSearchResult[];
}

export interface MetadataSearchResponse {
  filters: Record<string, string | null>;
  latency_ms: number;
  results: VectorSearchResult[];
}

export interface UnifiedSearchOptions {
  topK?: number;
  mode?: 'fast' | 'balanced' | 'quality';
  includeUnindexed?: boolean;
}

export interface UnifiedSearchResponse {
  query: string;
  mode: string;
  tiers_used: string[];
  latency_ms: number;
  results: VectorSearchResult[];
  unindexed_results: FileSearchResult[];
}

/**
 * HTTP-based client for the MCP Vector Store server.
 * Uses the REST endpoints for simple operations.
 */
export class VectorStoreClient {
  private baseUrl: string;
  private headers: Record<string, string>;

  constructor(config: VectorStoreConfig) {
    this.baseUrl = `http://${config.host}:${config.port}`;
    this.headers = {
      'Content-Type': 'application/json',
    };
    if (config.apiKey) {
      this.headers['Authorization'] = `Bearer ${config.apiKey}`;
    }
  }

  /**
   * Make an HTTP request to the vector store server
   */
  private async request<T>(
    method: string,
    path: string,
    body?: any
  ): Promise<T> {
    return new Promise((resolve, reject) => {
      const url = new URL(path, this.baseUrl);
      const isHttps = url.protocol === 'https:';
      const lib = isHttps ? https : http;

      const options: http.RequestOptions = {
        hostname: url.hostname,
        port: url.port || (isHttps ? 443 : 80),
        path: url.pathname + url.search,
        method,
        headers: this.headers,
        timeout: 300000, // 5 minutes - extended for Jetson Orin Nano processing
      };

      const req = lib.request(options, (res) => {
        let data = '';
        res.on('data', (chunk) => {
          data += chunk;
        });
        res.on('end', () => {
          try {
            if (res.statusCode && res.statusCode >= 400) {
              reject(new Error(`HTTP ${res.statusCode}: ${data}`));
              return;
            }
            const parsed = JSON.parse(data);
            resolve(parsed as T);
          } catch (e) {
            reject(new Error(`Failed to parse response: ${data}`));
          }
        });
      });

      req.on('error', (e) => {
        reject(new Error(`Request failed: ${e.message}`));
      });

      req.on('timeout', () => {
        req.destroy();
        reject(new Error('Request timeout'));
      });

      if (body) {
        req.write(JSON.stringify(body));
      }
      req.end();
    });
  }

  /**
   * Check if the vector store server is healthy
   */
  async checkHealth(): Promise<{ status: string; service: string; version: string; mode: string }> {
    return this.request('GET', '/health');
  }

  /**
   * Get server info and statistics
   */
  async getInfo(): Promise<Record<string, any>> {
    return this.request('GET', '/info');
  }

  /**
   * Search for documents similar to the query
   * @param query Search query text
   * @param topK Number of results to return (default: 5)
   * @param minScore Minimum similarity score threshold (0.0-1.0). Results below this are filtered out.
   */
  async search(query: string, topK: number = 5, minScore?: number): Promise<VectorSearchResult[]> {
    try {
      const response = await this.request<{ results: VectorSearchResult[] }>(
        'POST',
        '/api/search',
        { query, top_k: topK, min_score: minScore }
      );
      return response.results || [];
    } catch (error) {
      console.warn('Vector store search endpoint not available:', error);
      return [];
    }
  }

  /**
   * Enhanced search with passage extraction and query expansion.
   * Returns relevant excerpts instead of full documents.
   *
   * @param query Search query text
   * @param options Enhanced search options
   * @returns Enhanced search response with results and PII session info
   */
  async enhancedSearch(
    query: string,
    options: EnhancedSearchOptions = {}
  ): Promise<EnhancedSearchResponse> {
    const {
      topK = 5,
      minScore = 0.5,  // Balanced threshold for quality results
      extractPassages = true,
      expandQuery = false,
      maxExcerptLength = 500,
      consentSessionId,
      context,  // "user" for direct access, "llm" for LLM API access
    } = options;

    try {
      const requestBody: Record<string, any> = {
        query,
        top_k: topK,
        min_score: minScore,
        extract_passages: extractPassages,
        expand_query: expandQuery,
        max_excerpt_length: maxExcerptLength,
      };

      // Add consent session ID if provided (for category/document filtering)
      if (consentSessionId) {
        requestBody.consent_session_id = consentSessionId;
      }

      // Add context for image PII safety (llm context returns redacted image paths)
      if (context) {
        requestBody.context = context;
      }

      const response = await this.request<EnhancedSearchResponse>(
        'POST',
        '/api/search/enhanced',
        requestBody
      );
      return response;
    } catch (error) {
      console.warn('Vector store enhanced search endpoint not available:', error);
      return {
        query,
        min_score_threshold: minScore,
        passage_extraction: extractPassages,
        query_expansion: expandQuery,
        results: [],
      };
    }
  }

  /**
   * Add a document to the vector store
   * @param text Document text
   * @param metadata Optional metadata
   * @param skipDuplicates If true, skip if identical content exists. Default: use server setting (enabled)
   * @returns AddDocumentResult with success status and duplicate detection info
   */
  async addDocument(
    text: string,
    metadata?: Record<string, any>,
    skipDuplicates?: boolean
  ): Promise<AddDocumentResult> {
    try {
      const response = await this.request<AddDocumentResult>(
        'POST',
        '/api/documents',
        { text, metadata, skip_duplicates: skipDuplicates }
      );
      return response;
    } catch (error) {
      console.warn('Vector store add document endpoint not available:', error);
      throw error;
    }
  }

  /**
   * Add a document and return the document ID (for backward compatibility)
   * @throws Error if document is a duplicate and skip_duplicates is enabled
   */
  async addDocumentGetId(
    text: string,
    metadata?: Record<string, any>,
    skipDuplicates?: boolean
  ): Promise<number> {
    const result = await this.addDocument(text, metadata, skipDuplicates);
    if (result.is_duplicate) {
      throw new Error(`Document already exists with ID ${result.existing_document_id}`);
    }
    if (!result.document_id) {
      throw new Error('Failed to add document: no document ID returned');
    }
    return result.document_id;
  }

  /**
   * Add multiple documents in batch
   * @param documents Array of documents to add
   * @param skipDuplicates If true, skip duplicates. Default: use server setting (enabled)
   * @returns AddDocumentsBatchResult with success status and duplicate info
   */
  async addDocuments(
    documents: Array<{ text: string; metadata?: Record<string, any> }>,
    skipDuplicates?: boolean
  ): Promise<AddDocumentsBatchResult> {
    try {
      const response = await this.request<AddDocumentsBatchResult>(
        'POST',
        '/api/documents/batch',
        { documents, skip_duplicates: skipDuplicates }
      );
      return response;
    } catch (error) {
      console.warn('Vector store batch add endpoint not available:', error);
      throw error;
    }
  }

  /**
   * Add multiple documents and return IDs (for backward compatibility)
   * Note: This ignores duplicates silently and only returns IDs of successfully added documents
   */
  async addDocumentsGetIds(
    documents: Array<{ text: string; metadata?: Record<string, any> }>,
    skipDuplicates?: boolean
  ): Promise<number[]> {
    const result = await this.addDocuments(documents, skipDuplicates);
    return result.document_ids || [];
  }

  /**
   * Get statistics about the vector store
   */
  async getStats(): Promise<VectorStoreStats> {
    try {
      const info = await this.getInfo();
      return info.stats as VectorStoreStats || {
        total_documents: 0,
        total_files: 0,
        embedding_dimension: 384,
        db_path: './objectbox_data',
      };
    } catch (error) {
      return {
        total_documents: 0,
        total_files: 0,
        embedding_dimension: 384,
        db_path: './objectbox_data',
      };
    }
  }

  /**
   * Get detailed debug information (memory, GPU, models)
   */
  async getDebugInfo(): Promise<any> {
    try {
      return await this.request<any>('GET', '/api/debug');
    } catch (error) {
      console.warn('Vector store debug endpoint not available:', error);
      return { error: 'Debug endpoint not available' };
    }
  }

  /**
   * List documents with pagination
   */
  async listDocuments(
    page: number = 1,
    pageSize: number = 10,
    ascending: boolean = false
  ): Promise<PaginatedDocuments> {
    try {
      return await this.request<PaginatedDocuments>(
        'GET',
        `/api/documents?page=${page}&page_size=${pageSize}&ascending=${ascending}`
      );
    } catch (error) {
      console.warn('Vector store list documents endpoint not available:', error);
      return {
        documents: [],
        page,
        page_size: pageSize,
        total: 0,
        total_pages: 0,
        has_next: false,
        has_prev: false,
      };
    }
  }

  /**
   * Get a specific document by ID
   */
  async getDocument(docId: number): Promise<VectorDocument | null> {
    try {
      const response = await this.request<{ document: VectorDocument; success: boolean }>(
        'GET',
        `/api/documents/${docId}`
      );
      return response.success ? response.document : null;
    } catch (error) {
      console.warn('Vector store get document endpoint not available:', error);
      return null;
    }
  }

  /**
   * Delete a document by ID
   */
  async deleteDocument(docId: number): Promise<boolean> {
    try {
      const response = await this.request<{ success: boolean }>(
        'DELETE',
        `/api/documents/${docId}`
      );
      return response.success;
    } catch (error) {
      console.warn('Vector store delete document endpoint not available:', error);
      return false;
    }
  }

  async clearAllDocuments(): Promise<{ success: boolean; deleted_count: number }> {
    try {
      const response = await this.request<{ success: boolean; deleted_count: number }>(
        'DELETE',
        '/api/documents/clear'
      );
      return response;
    } catch (error) {
      console.warn('Vector store clear all documents endpoint not available:', error);
      return { success: false, deleted_count: 0 };
    }
  }

  /**
   * Get all topics with document counts
   */
  async getAllTopics(): Promise<AllTopicsResult> {
    try {
      return await this.request<AllTopicsResult>('GET', '/api/topics');
    } catch (error) {
      console.warn('Vector store get topics endpoint not available:', error);
      return {
        success: false,
        total_unique_topics: 0,
        topics: [],
      };
    }
  }

  /**
   * Get documents filtered by topic
   */
  async getDocumentsByTopic(
    topic: string,
    page: number = 1,
    pageSize: number = 10
  ): Promise<PaginatedDocumentsByTopic> {
    try {
      return await this.request<PaginatedDocumentsByTopic>(
        'GET',
        `/api/topics/${encodeURIComponent(topic)}/documents?page=${page}&page_size=${pageSize}`
      );
    } catch (error) {
      console.warn('Vector store get documents by topic endpoint not available:', error);
      return {
        topic,
        documents: [],
        page,
        page_size: pageSize,
        total: 0,
        total_pages: 0,
        has_next: false,
        has_prev: false,
      };
    }
  }

  /**
   * Get topics for a specific document
   */
  async getDocumentTopics(docId: number): Promise<DocumentTopics | null> {
    try {
      const response = await this.request<{ success: boolean } & DocumentTopics>(
        'GET',
        `/api/documents/${docId}/topics`
      );
      return response.success ? response : null;
    } catch (error) {
      console.warn('Vector store get document topics endpoint not available:', error);
      return null;
    }
  }

  /**
   * Update topics for a document
   */
  async updateDocumentTopics(
    docId: number,
    topics: string[],
    primaryTopic?: string
  ): Promise<boolean> {
    try {
      const response = await this.request<{ success: boolean }>(
        'PUT',
        `/api/documents/${docId}/topics`,
        { topics, primary_topic: primaryTopic }
      );
      return response.success;
    } catch (error) {
      console.warn('Vector store update document topics endpoint not available:', error);
      return false;
    }
  }

  /**
   * Generate topics for a document using TinyLlama
   */
  async generateTopics(
    docId: number,
    numTopics: number = 3,
    predefinedTopics?: string[]
  ): Promise<GenerateTopicsResult> {
    try {
      return await this.request<GenerateTopicsResult>(
        'POST',
        `/api/documents/${docId}/topics/generate`,
        { num_topics: numTopics, predefined_topics: predefinedTopics }
      );
    } catch (error) {
      console.warn('Vector store generate topics endpoint not available:', error);
      return {
        success: false,
        doc_id: docId,
        topics: [],
        primary_topic: '',
        confidence: 0,
        error: String(error),
      };
    }
  }

  /**
   * Search documents with optional topic filtering
   * @param query Search query text
   * @param topic Optional topic to filter by
   * @param topK Number of results to return (default: 5)
   * @param minScore Minimum similarity score threshold (0.0-1.0)
   */
  async searchWithTopic(
    query: string,
    topic?: string,
    topK: number = 5,
    minScore?: number
  ): Promise<SearchWithTopicResponse> {
    try {
      const response = await this.request<SearchWithTopicResponse>(
        'POST',
        '/api/search/with-topic',
        { query, topic, top_k: topK, min_score: minScore }
      );
      return response;
    } catch (error) {
      console.warn('Vector store search with topic endpoint not available:', error);
      return {
        query,
        topic,
        min_score: minScore,
        results: [],
      };
    }
  }

  // === Fast Search Methods ===

  /**
   * Quick keyword-only search (FTS5/BM25). Zero GPU, <5ms latency.
   */
  async quickSearch(query: string, topK: number = 10): Promise<QuickSearchResponse> {
    try {
      return await this.request<QuickSearchResponse>(
        'POST',
        '/api/search/quick',
        { query, top_k: topK }
      );
    } catch (error) {
      console.warn('Quick search endpoint not available:', error);
      return { query, search_mode: 'keyword', latency_ms: 0, results: [] };
    }
  }

  /**
   * Search raw files that may not be indexed yet.
   */
  async searchFiles(
    query: string,
    directories?: string[],
    maxResults: number = 20,
    caseSensitive: boolean = false
  ): Promise<FileSearchResponse> {
    try {
      return await this.request<FileSearchResponse>(
        'POST',
        '/api/search/files',
        { query, directories, max_results: maxResults, case_sensitive: caseSensitive }
      );
    } catch (error) {
      console.warn('File search endpoint not available:', error);
      return { query, latency_ms: 0, results: [] };
    }
  }

  /**
   * Search documents by metadata fields (filename, source, date, topic).
   */
  async searchMetadata(filters: {
    filename?: string;
    source?: string;
    date_from?: string;
    date_to?: string;
    topic?: string;
    top_k?: number;
  }): Promise<MetadataSearchResponse> {
    try {
      return await this.request<MetadataSearchResponse>(
        'POST',
        '/api/search/metadata',
        filters
      );
    } catch (error) {
      console.warn('Metadata search endpoint not available:', error);
      return { filters: {}, latency_ms: 0, results: [] };
    }
  }

  /**
   * Unified tiered search — automatically uses the best available search tier.
   *
   * Modes:
   * - fast: keyword only (<5ms, no GPU)
   * - balanced: keyword + semantic (~15ms)
   * - quality: keyword + semantic + reranking (~100ms)
   */
  async unifiedSearch(
    query: string,
    options: UnifiedSearchOptions = {}
  ): Promise<UnifiedSearchResponse> {
    try {
      return await this.request<UnifiedSearchResponse>(
        'POST',
        '/api/search/unified',
        {
          query,
          top_k: options.topK ?? 10,
          mode: options.mode ?? 'balanced',
          include_unindexed: options.includeUnindexed ?? false,
        }
      );
    } catch (error) {
      console.warn('Unified search endpoint not available:', error);
      return { query, mode: 'balanced', tiers_used: [], latency_ms: 0, results: [], unindexed_results: [] };
    }
  }

  /**
   * Get knowledge graph data for visualization
   */
  async getKnowledgeGraph(options: KnowledgeGraphOptions = {}): Promise<KnowledgeGraphResponse> {
    try {
      return await this.request<KnowledgeGraphResponse>(
        'POST',
        '/api/graph',
        options
      );
    } catch (error) {
      console.warn('Vector store knowledge graph endpoint not available:', error);
      return {
        nodes: [],
        edges: [],
        stats: {
          document_count: 0,
          topic_count: 0,
          person_count: 0,
          organization_count: 0,
          location_count: 0,
          technology_count: 0,
          edge_count: 0,
        },
      };
    }
  }

  /**
   * Get details for a specific graph node
   */
  async getGraphNodeDetails(nodeId: string): Promise<GraphNodeDetails | null> {
    try {
      return await this.request<GraphNodeDetails>(
        'GET',
        `/api/graph/node/${encodeURIComponent(nodeId)}`
      );
    } catch (error) {
      console.warn('Vector store graph node details endpoint not available:', error);
      return null;
    }
  }

  /**
   * Get media processing status (audio/image availability)
   */
  async getMediaStatus(): Promise<MediaStatus> {
    try {
      return await this.request<MediaStatus>('GET', '/api/media/status');
    } catch (error) {
      console.warn('Vector store media status endpoint not available:', error);
      return {
        audio: { available: false, model: null, loaded: false, supported_formats: [] },
        image: { available: false, model: null, loaded: false, supported_formats: [] },
      };
    }
  }

  /**
   * Get PII protection status
   */
  async getPIIStatus(): Promise<PIIStatus> {
    try {
      return await this.request<PIIStatus>('GET', '/api/pii/status');
    } catch (error) {
      console.warn('Vector store PII status endpoint not available:', error);
      return {
        enabled: false,
        reason: 'PII protection not available',
      };
    }
  }

  /**
   * Anonymize text by detecting and replacing PII with tokens
   * @param text Text to anonymize
   * @param sessionId Optional PII session ID for token mapping
   * @param consentSessionId Optional consent session ID for exposed_pii_types rules
   */
  async anonymize(text: string, sessionId?: string, consentSessionId?: string): Promise<AnonymizeResult> {
    try {
      const requestBody: Record<string, any> = {
        text,
        session_id: sessionId,
      };

      // Add consent session ID if provided (for PII type exposure rules)
      if (consentSessionId) {
        requestBody.consent_session_id = consentSessionId;
      }

      return await this.request<AnonymizeResult>(
        'POST',
        '/api/pii/anonymize',
        requestBody
      );
    } catch (error) {
      console.warn('Vector store anonymize endpoint not available:', error);
      return {
        anonymized_text: text,
        session_id: sessionId || '',
        token_count: 0,
        pii_types_found: [],
        processing_time_ms: 0,
      };
    }
  }

  /**
   * De-anonymize text containing PII tokens
   */
  async deanonymize(text: string, sessionId: string): Promise<DeanonymizeResult> {
    try {
      return await this.request<DeanonymizeResult>(
        'POST',
        '/api/pii/deanonymize',
        { text, session_id: sessionId }
      );
    } catch (error) {
      console.warn('Vector store deanonymize endpoint not available:', error);
      return {
        deanonymized_text: text,
        session_id: sessionId,
        tokens_replaced: 0,
        tokens_not_found: ['SERVICE_UNAVAILABLE'],
      };
    }
  }

  /**
   * Get PII session info
   */
  async getPIISession(sessionId: string): Promise<PIISession | null> {
    try {
      return await this.request<PIISession>(
        'GET',
        `/api/pii/session/${sessionId}`
      );
    } catch (error) {
      console.warn('Vector store PII session endpoint not available:', error);
      return null;
    }
  }

  /**
   * Clear a PII session
   */
  async clearPIISession(sessionId: string): Promise<boolean> {
    try {
      const response = await this.request<{ cleared: boolean }>(
        'DELETE',
        `/api/pii/session/${sessionId}`
      );
      return response.cleared;
    } catch (error) {
      console.warn('Vector store clear PII session endpoint not available:', error);
      return false;
    }
  }

  /**
   * Get LPRAG (Local Differential Privacy) status
   * Returns information about LPRAG mode and configuration
   */
  async getLPRAGStatus(): Promise<LPRAGStatus> {
    try {
      return await this.request<LPRAGStatus>('GET', '/api/lprag/status');
    } catch (error) {
      console.warn('Vector store LPRAG status endpoint not available:', error);
      return {
        enabled: false,
        mode: 'token_only',
        lprag_available: false,
        initialized: false,
        total_perturbed_values: 0,
      };
    }
  }

  /**
   * Get LPRAG configuration
   * Note: Configuration is set via environment variables at server startup
   */
  async getLPRAGConfig(): Promise<LPRAGConfig> {
    try {
      return await this.request<LPRAGConfig>('GET', '/api/lprag/config');
    } catch (error) {
      console.warn('Vector store LPRAG config endpoint not available:', error);
      return {
        mode: 'token_only',
        available: false,
        initialized: false,
        note: 'LPRAG not available',
      };
    }
  }

  // ==================== Consent Management ====================

  /**
   * Get consent system status
   */
  async getConsentStatus(): Promise<ConsentStatus> {
    try {
      return await this.request<ConsentStatus>('GET', '/api/consent/status');
    } catch (error) {
      console.warn('Vector store consent status endpoint not available:', error);
      return {
        available: false,
        reason: 'Consent system not available',
        active_sessions: 0,
        total_sessions_created: 0,
        max_sessions: 0,
        session_ttl_seconds: 0,
        presets_available: [],
        categories_available: [],
      };
    }
  }

  /**
   * Get available consent presets
   */
  async getConsentPresets(): Promise<ConsentPresetsResponse> {
    try {
      return await this.request<ConsentPresetsResponse>('GET', '/api/consent/presets');
    } catch (error) {
      console.warn('Vector store consent presets endpoint not available:', error);
      return {
        presets: [],
        categories: [],
        default_preset: 'balanced',
      };
    }
  }

  /**
   * Create a new consent session with optional preset and rules
   */
  async createConsentSession(options?: ConsentSessionCreateRequest): Promise<ConsentSession> {
    const response = await this.request<{ success: boolean; session_id: string; created_at: string; expires_at: string; consent: ConsentSettings }>(
      'POST',
      '/api/consent/session',
      options || {}
    );
    return {
      session_id: response.session_id,
      created_at: response.created_at,
      last_accessed: response.created_at,
      expires_at: response.expires_at,
      is_expired: false,
      consent: response.consent,
    };
  }

  /**
   * Get consent session by ID
   */
  async getConsentSession(sessionId: string): Promise<ConsentSession | null> {
    try {
      return await this.request<ConsentSession>('GET', `/api/consent/session/${sessionId}`);
    } catch (error: any) {
      if (error.message?.includes('404') || error.message?.includes('not found')) {
        return null;
      }
      throw error;
    }
  }

  /**
   * Update consent rules for a session
   */
  async updateConsentSession(sessionId: string, updates: ConsentSessionUpdateRequest): Promise<ConsentSession> {
    const response = await this.request<{ success: boolean; session_id: string; consent: ConsentSettings }>(
      'PATCH',
      `/api/consent/session/${sessionId}`,
      updates
    );
    // Fetch full session to get timestamps
    const session = await this.getConsentSession(sessionId);
    if (!session) {
      throw new Error('Session not found after update');
    }
    return session;
  }

  /**
   * Delete a consent session
   */
  async deleteConsentSession(sessionId: string): Promise<boolean> {
    try {
      const response = await this.request<{ deleted: boolean }>('DELETE', `/api/consent/session/${sessionId}`);
      return response.deleted;
    } catch (error) {
      console.warn('Failed to delete consent session:', error);
      return false;
    }
  }

  /**
   * Apply a preset to an existing session
   */
  async applyConsentPreset(sessionId: string, preset: ConsentPresetName): Promise<ConsentSession> {
    const response = await this.request<{ success: boolean; session_id: string; preset_applied: string; consent: ConsentSettings }>(
      'POST',
      `/api/consent/session/${sessionId}/apply-preset`,
      { preset }
    );
    // Fetch full session to get timestamps
    const session = await this.getConsentSession(sessionId);
    if (!session) {
      throw new Error('Session not found after applying preset');
    }
    return session;
  }

  /**
   * Quick helper to create a session with a specific preset
   */
  async createSessionWithPreset(preset: ConsentPresetName): Promise<ConsentSession> {
    return this.createConsentSession({ preset });
  }

  /**
   * Quick helper to protect specific entities in a session
   */
  async protectEntities(sessionId: string, entities: (string | EntityDefinition)[]): Promise<ConsentSession> {
    return this.updateConsentSession(sessionId, { protect_entities: entities });
  }

  /**
   * Quick helper to block specific documents in a session
   */
  async blockDocuments(sessionId: string, documentIds: number[]): Promise<ConsentSession> {
    return this.updateConsentSession(sessionId, { block_documents: documentIds });
  }

  /**
   * Quick helper to update allowed categories
   */
  async updateAllowedCategories(sessionId: string, categories: DataCategory[]): Promise<ConsentSession> {
    return this.updateConsentSession(sessionId, { allowed_categories: categories });
  }

  /**
   * Quick helper to update exposed PII types
   */
  async updateExposedPiiTypes(sessionId: string, piiTypes: string[]): Promise<ConsentSession> {
    return this.updateConsentSession(sessionId, { exposed_pii_types: piiTypes });
  }

  // ==================== Image RAG Support ====================

  /**
   * Get base64-encoded image data for multimodal LLM input.
   * Returns the redacted version by default for PII safety.
   *
   * @param imageId The unique image ID
   * @param context 'llm' for redacted (default), 'user' for original
   * @param maxSize Optional max dimension to resize (useful for LLM token limits)
   */
  async getImageBase64(
    imageId: string,
    context: 'llm' | 'user' = 'llm',
    maxSize?: number
  ): Promise<{
    success: boolean;
    image_id: string;
    media_type: string;
    base64_data: string;
    context: string;
    size_bytes: number;
  } | null> {
    try {
      const params = new URLSearchParams({ context });
      if (maxSize) {
        params.append('max_size', maxSize.toString());
      }
      return await this.request(
        'GET',
        `/api/image/base64/${encodeURIComponent(imageId)}?${params.toString()}`
      );
    } catch (error) {
      console.warn(`Failed to get base64 image ${imageId}:`, error);
      return null;
    }
  }
}

// Singleton instance management
let vectorStoreClient: VectorStoreClient | null = null;
let vectorStoreConfig: VectorStoreConfig = {
  host: 'localhost',
  port: 8085,
};

/**
 * Initialize the vector store client with configuration
 */
export function initVectorStoreClient(config: Partial<VectorStoreConfig>): void {
  vectorStoreConfig = { ...vectorStoreConfig, ...config };
  vectorStoreClient = new VectorStoreClient(vectorStoreConfig);
}

/**
 * Get the vector store client instance
 */
export function getVectorStoreClient(): VectorStoreClient {
  if (!vectorStoreClient) {
    vectorStoreClient = new VectorStoreClient(vectorStoreConfig);
  }
  return vectorStoreClient;
}

/**
 * Check if vector store is available
 */
export async function isVectorStoreAvailable(): Promise<boolean> {
  try {
    const client = getVectorStoreClient();
    await client.checkHealth();
    return true;
  } catch {
    return false;
  }
}
