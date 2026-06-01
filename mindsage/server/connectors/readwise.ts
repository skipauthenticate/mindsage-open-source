/**
 * Readwise Connector for MindSage
 *
 * Syncs highlights and documents from Readwise using the v3 API.
 * Supports incremental sync via `updatedAfter` parameter.
 * Indexes directly to vector store (no intermediate files).
 *
 * API Docs: https://readwise.io/api_defs
 *
 * Supported data:
 *   - Books, articles, podcasts, tweets (Reader library)
 *   - Highlights with notes and tags
 *   - Incremental sync via updatedAfter timestamp
 */

import {
  getVectorStoreClient,
  isVectorStoreAvailable,
} from '../vector-store-client.js';
import { fetchWithRetry } from './utils.js';

// --- Types ---

export interface ReadwiseSyncCursor {
  lastSyncAt: string;
}

export interface ReadwiseSyncResult {
  success: boolean;
  documentsIndexed: number;
  highlightsIndexed: number;
  duplicatesSkipped: number;
  errors: string[];
  syncedAt: string;
  cursor: ReadwiseSyncCursor;
}

export interface ReadwiseSyncProgress {
  phase: 'fetching-documents' | 'indexing' | 'complete';
  documentsFetched: number;
  documentsProcessed: number;
  highlightsProcessed: number;
}

interface ReadwiseDocument {
  id: string;
  url: string;
  source_url: string | null;
  title: string;
  author: string | null;
  source: string;
  category: string;
  location: string;
  tags: Record<string, any>;
  site_name: string | null;
  word_count: number | null;
  created_at: string;
  updated_at: string;
  notes: string;
  published_date: string | null;
  summary: string | null;
  image_url: string | null;
  parent_id: string | null;
  reading_progress: number;
}

interface ReadwiseHighlight {
  id: string;
  text: string;
  note: string;
  location: number;
  location_type: string;
  url: string | null;
  color: string;
  updated: string;
  book_id: string;
  tags: { name: string }[];
}

// --- API Helpers ---

const API_BASE = 'https://readwise.io/api/v3';

function getHeaders(token: string): Record<string, string> {
  return {
    Authorization: `Token ${token}`,
    'Content-Type': 'application/json',
  };
}

// --- API Fetchers ---

/**
 * Fetch documents (books, articles, etc.) from Readwise Reader API.
 * Uses cursor-based pagination and supports incremental sync.
 */
async function fetchDocuments(
  token: string,
  updatedAfter: string | null,
  signal?: AbortSignal
): Promise<ReadwiseDocument[]> {
  const documents: ReadwiseDocument[] = [];
  let pageCursor: string | undefined;
  const headers = getHeaders(token);

  do {
    if (signal?.aborted) throw new Error('Sync cancelled');

    const url = new URL(`${API_BASE}/list/`);
    if (pageCursor) url.searchParams.set('pageCursor', pageCursor);
    if (updatedAfter) url.searchParams.set('updatedAfter', updatedAfter);

    const response = await fetchWithRetry(url.toString(), { headers, signal });

    if (!response.ok) {
      const error = await response.text();
      throw new Error(`Readwise list failed: ${response.status} - ${error}`);
    }

    const data = await response.json();
    if (data.results) {
      documents.push(...data.results);
    }

    pageCursor = data.nextPageCursor || undefined;

    // Respect rate limits
    await new Promise(resolve => setTimeout(resolve, 500));
  } while (pageCursor);

  return documents;
}

/**
 * Fetch highlights for a specific book/document from Readwise v2 API.
 */
async function fetchHighlights(
  token: string,
  bookId: string,
  updatedAfter: string | null,
  signal?: AbortSignal
): Promise<ReadwiseHighlight[]> {
  const highlights: ReadwiseHighlight[] = [];
  let page = 1;
  const maxPages = 100;
  const headers = getHeaders(token);

  do {
    if (signal?.aborted) throw new Error('Sync cancelled');

    const url = new URL('https://readwise.io/api/v2/highlights/');
    url.searchParams.set('book_id', bookId);
    url.searchParams.set('page', page.toString());
    url.searchParams.set('page_size', '100');
    if (updatedAfter) url.searchParams.set('updated__gt', updatedAfter);

    const response = await fetchWithRetry(url.toString(), { headers, signal });

    if (!response.ok) {
      if (response.status === 404) break;
      const error = await response.text();
      throw new Error(`Readwise highlights failed: ${response.status} - ${error}`);
    }

    const data = await response.json();
    if (data.results) {
      highlights.push(...data.results);
    }

    if (!data.next || page >= maxPages) break;
    page++;

    await new Promise(resolve => setTimeout(resolve, 500));
  } while (true);

  return highlights;
}

// --- Main Functions ---

/**
 * Validate a Readwise API token.
 */
export async function testReadwiseConnection(token: string): Promise<{ ok: boolean; error?: string }> {
  try {
    const response = await fetch('https://readwise.io/api/v2/auth/', {
      headers: getHeaders(token),
    });

    if (response.status === 204) {
      return { ok: true };
    }
    if (response.status === 401) {
      return { ok: false, error: 'Invalid token. Check your Readwise access token.' };
    }
    return { ok: false, error: `Readwise API error: ${response.status}` };
  } catch (error: any) {
    return { ok: false, error: `Connection failed: ${error.message}` };
  }
}

/**
 * Sync Readwise content directly to the vector store.
 *
 * Fetches documents and highlights from Readwise, indexes them directly.
 * Supports incremental sync via updatedAfter timestamp.
 */
export async function syncReadwise(
  connectorId: string,
  config: Record<string, any>,
  cursor: ReadwiseSyncCursor | null,
  onProgress?: (progress: ReadwiseSyncProgress) => void,
  signal?: AbortSignal
): Promise<ReadwiseSyncResult> {
  const token = config.token;
  if (!token || typeof token !== 'string') {
    return {
      success: false,
      documentsIndexed: 0,
      highlightsIndexed: 0,
      duplicatesSkipped: 0,
      errors: ['Missing or invalid Readwise token in connector config'],
      syncedAt: new Date().toISOString(),
      cursor: cursor || { lastSyncAt: '' },
    };
  }

  const available = await isVectorStoreAvailable();
  if (!available) {
    return {
      success: false,
      documentsIndexed: 0,
      highlightsIndexed: 0,
      duplicatesSkipped: 0,
      errors: ['Vector store not available'],
      syncedAt: new Date().toISOString(),
      cursor: cursor || { lastSyncAt: '' },
    };
  }

  const syncStartedAt = new Date().toISOString();
  const client = getVectorStoreClient();
  const result: ReadwiseSyncResult = {
    success: true,
    documentsIndexed: 0,
    highlightsIndexed: 0,
    duplicatesSkipped: 0,
    errors: [],
    syncedAt: '',
    cursor: cursor || { lastSyncAt: '' },
  };

  const updatedAfter = cursor?.lastSyncAt || null;
  const syncType = updatedAfter ? 'incremental' : 'full';
  console.log(`[readwise] Starting ${syncType} sync for connector ${connectorId}${updatedAfter ? ` (since ${updatedAfter})` : ''}`);

  try {
    // Phase 1: Fetch documents
    onProgress?.({
      phase: 'fetching-documents',
      documentsFetched: 0,
      documentsProcessed: 0,
      highlightsProcessed: 0,
    });

    const documents = await fetchDocuments(token, updatedAfter, signal);
    console.log(`[readwise] Found ${documents.length} documents${updatedAfter ? ' (changed since last sync)' : ''}`);

    onProgress?.({
      phase: 'indexing',
      documentsFetched: documents.length,
      documentsProcessed: 0,
      highlightsProcessed: 0,
    });

    // Phase 2: Index each document with its highlights
    for (let i = 0; i < documents.length; i++) {
      if (signal?.aborted) throw new Error('Sync cancelled');

      const doc = documents[i];

      try {
        // Build document text
        const parts: string[] = [`# ${doc.title}`];

        if (doc.author) parts.push(`Author: ${doc.author}`);
        if (doc.source) parts.push(`Source: ${doc.source}`);
        if (doc.category) parts.push(`Category: ${doc.category}`);
        if (doc.published_date) parts.push(`Published: ${doc.published_date}`);
        if (doc.summary) parts.push(`\n## Summary\n${doc.summary}`);
        if (doc.notes) parts.push(`\n## Notes\n${doc.notes}`);

        const tags = Object.keys(doc.tags || {});
        if (tags.length > 0) parts.push(`Tags: ${tags.join(', ')}`);

        // Fetch and include highlights
        let highlightCount = 0;
        try {
          const highlights = await fetchHighlights(token, doc.id, updatedAfter, signal);
          if (highlights.length > 0) {
            parts.push('\n## Highlights');
            for (const hl of highlights) {
              let hlText = `> ${hl.text}`;
              if (hl.note) hlText += `\n\nNote: ${hl.note}`;
              if (hl.tags?.length) hlText += `\nTags: ${hl.tags.map(t => t.name).join(', ')}`;
              parts.push(hlText);
              highlightCount++;
            }
          }
        } catch (hlError: any) {
          // Non-fatal: index document without highlights
          console.warn(`[readwise] Could not fetch highlights for "${doc.title}": ${hlError.message}`);
        }

        const text = parts.join('\n\n');

        const addResult = await client.addDocument(text, {
          source: 'readwise',
          connectorId,
          readwiseId: doc.id,
          title: doc.title,
          author: doc.author,
          category: doc.category,
          sourceType: doc.source,
          url: doc.source_url || doc.url,
          publishedDate: doc.published_date,
          readingProgress: doc.reading_progress,
          wordCount: doc.word_count,
          createdAt: doc.created_at,
          updatedAt: doc.updated_at,
        });

        if (addResult.is_duplicate) {
          result.duplicatesSkipped++;
        } else {
          result.documentsIndexed++;
          result.highlightsIndexed += highlightCount;
        }
      } catch (docError: any) {
        result.errors.push(`Document "${doc.title}" (${doc.id}): ${docError.message}`);
        console.error(`[readwise] Error indexing "${doc.title}":`, docError.message);
      }

      onProgress?.({
        phase: 'indexing',
        documentsFetched: documents.length,
        documentsProcessed: i + 1,
        highlightsProcessed: result.highlightsIndexed,
      });
    }

    onProgress?.({
      phase: 'complete',
      documentsFetched: documents.length,
      documentsProcessed: documents.length,
      highlightsProcessed: result.highlightsIndexed,
    });

    // Set cursor and timestamp only after successful sync
    result.syncedAt = new Date().toISOString();
    result.cursor = { lastSyncAt: syncStartedAt };

    console.log(`[readwise] Sync complete: ${result.documentsIndexed} documents, ${result.highlightsIndexed} highlights, ${result.duplicatesSkipped} duplicates, ${result.errors.length} errors`);

    if (result.errors.length > 0) {
      result.success = result.errors.length < documents.length;
    }

    return result;
  } catch (error: any) {
    console.error(`[readwise] Sync failed:`, error.message);
    result.success = false;
    result.errors.push(error.message);
    result.cursor = cursor || { lastSyncAt: '' };
    return result;
  }
}
