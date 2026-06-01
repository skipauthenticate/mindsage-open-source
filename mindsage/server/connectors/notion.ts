/**
 * In-Process Notion Connector for MindSage
 *
 * Replaces the child-process-based export-notion.ts script.
 * Runs directly in the Express process (~5-10MB vs ~100-180MB for child process).
 * Supports incremental sync via last_edited_time filtering.
 * Indexes directly to vector store (no intermediate files on disk).
 */

import {
  getVectorStoreClient,
  isVectorStoreAvailable,
} from '../vector-store-client.js';
import { fetchWithRetry } from './utils.js';

// --- Notion API Types ---

interface NotionPage {
  id: string;
  object: 'page';
  created_time: string;
  last_edited_time: string;
  parent: {
    type: string;
    page_id?: string;
    database_id?: string;
    workspace?: boolean;
  };
  properties: {
    title?: { title: { plain_text: string }[] };
    Name?: { title: { plain_text: string }[] };
    [key: string]: any;
  };
  url: string;
}

interface NotionDatabase {
  id: string;
  object: 'database';
  created_time: string;
  last_edited_time: string;
  title: { plain_text: string }[];
  properties: Record<string, any>;
  url: string;
}

// --- Sync Types ---

export interface NotionSyncCursor {
  lastSyncAt: string;
}

export interface NotionSyncResult {
  success: boolean;
  pagesIndexed: number;
  pagesUpdated: number;
  databaseEntriesIndexed: number;
  duplicatesSkipped: number;
  errors: string[];
  syncedAt: string;
  cursor: NotionSyncCursor;
}

export interface NotionSyncProgress {
  phase: 'searching' | 'indexing-pages' | 'indexing-databases' | 'complete';
  pagesFound: number;
  databasesFound: number;
  pagesProcessed: number;
  databasesProcessed: number;
}

// --- Notion API Helpers ---

const API_BASE = 'https://api.notion.com/v1';
const NOTION_VERSION = '2025-09-03';

function getHeaders(token: string): Record<string, string> {
  return {
    Authorization: `Bearer ${token}`,
    'Notion-Version': NOTION_VERSION,
    'Content-Type': 'application/json',
  };
}

// --- Content Extraction ---

/**
 * Fetch page content as Markdown via Notion's Markdown API (2025-09-03+).
 * Single API call replaces block-by-block fetching (50-75% fewer API calls).
 * Falls back gracefully if the endpoint is unavailable.
 */
async function getPageMarkdown(
  token: string,
  pageId: string,
  signal?: AbortSignal
): Promise<string> {
  const headers = getHeaders(token);
  const url = `${API_BASE}/pages/${pageId}/markdown?include_transcript=true`;

  const response = await fetchWithRetry(url, { headers, signal });

  if (!response.ok) {
    // If markdown endpoint not available (older API), return empty
    if (response.status === 404) {
      console.warn(`[notion] Markdown API not available for page ${pageId}, skipping content`);
      return '';
    }
    const error = await response.text();
    throw new Error(`Failed to get markdown for page ${pageId}: ${response.status} - ${error}`);
  }

  const data = await response.json();

  if (data.truncated) {
    console.warn(`[notion] Page ${pageId} markdown was truncated (content too large)`);
  }

  return data.markdown || '';
}

function getPageTitle(page: NotionPage): string {
  const props = page.properties;

  if (props.title?.title) {
    return props.title.title.map(t => t.plain_text).join('') || 'Untitled';
  }
  if (props.Name?.title) {
    return props.Name.title.map(t => t.plain_text).join('') || 'Untitled';
  }

  for (const key of Object.keys(props)) {
    if (props[key]?.title) {
      return props[key].title.map((t: any) => t.plain_text).join('') || 'Untitled';
    }
  }

  return 'Untitled';
}

function extractPropertyValue(property: any): string {
  if (!property) return '';

  switch (property.type) {
    case 'title':
      return property.title?.map((t: any) => t.plain_text).join('') || '';
    case 'rich_text':
      return property.rich_text?.map((t: any) => t.plain_text).join('') || '';
    case 'number':
      return property.number?.toString() || '';
    case 'select':
      return property.select?.name || '';
    case 'multi_select':
      return property.multi_select?.map((s: any) => s.name).join(', ') || '';
    case 'date':
      return property.date?.start || '';
    case 'checkbox':
      return property.checkbox ? 'Yes' : 'No';
    case 'url':
      return property.url || '';
    case 'email':
      return property.email || '';
    case 'phone_number':
      return property.phone_number || '';
    case 'status':
      return property.status?.name || '';
    default:
      return '';
  }
}

// --- Notion API Fetchers ---

async function searchContent(
  token: string,
  lastSyncAt: string | null,
  signal?: AbortSignal
): Promise<{ pages: NotionPage[]; databases: NotionDatabase[] }> {
  const pages: NotionPage[] = [];
  const databases: NotionDatabase[] = [];
  let startCursor: string | undefined;
  const headers = getHeaders(token);

  do {
    if (signal?.aborted) throw new Error('Sync cancelled');

    const body: Record<string, any> = {
      page_size: 100,
      start_cursor: startCursor,
    };

    // Incremental: filter by last_edited_time if we have a cursor
    if (lastSyncAt) {
      body.filter = {
        property: 'object',
        value: 'page',
      };
      body.sort = {
        direction: 'descending',
        timestamp: 'last_edited_time',
      };
    }

    const response = await fetchWithRetry(`${API_BASE}/search`, {
      method: 'POST',
      headers,
      body: JSON.stringify(body),
      signal,
    });

    if (!response.ok) {
      const error = await response.text();
      throw new Error(`Notion search failed: ${response.status} - ${error}`);
    }

    const data = await response.json();

    for (const result of data.results) {
      // For incremental sync, skip items not edited since last sync
      if (lastSyncAt && result.last_edited_time <= lastSyncAt) {
        // Since results are sorted by last_edited_time desc, we can stop early
        if (body.sort) {
          return { pages, databases };
        }
        continue;
      }

      if (result.object === 'page') {
        pages.push(result);
      } else if (result.object === 'database') {
        databases.push(result);
      }
    }

    startCursor = data.has_more ? data.next_cursor : undefined;

    // Respect rate limits (3 req/sec)
    await new Promise(resolve => setTimeout(resolve, 350));
  } while (startCursor);

  // If incremental with page filter, also search for databases
  if (lastSyncAt) {
    startCursor = undefined;
    do {
      if (signal?.aborted) throw new Error('Sync cancelled');

      const response = await fetchWithRetry(`${API_BASE}/search`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          page_size: 100,
          start_cursor: startCursor,
          filter: { property: 'object', value: 'database' },
          sort: { direction: 'descending', timestamp: 'last_edited_time' },
        }),
        signal,
      });

      if (!response.ok) break;

      const data = await response.json();
      for (const result of data.results) {
        if (result.last_edited_time <= lastSyncAt) {
          return { pages, databases };
        }
        databases.push(result);
      }

      startCursor = data.has_more ? data.next_cursor : undefined;
      await new Promise(resolve => setTimeout(resolve, 350));
    } while (startCursor);
  }

  return { pages, databases };
}

async function getDatabaseEntries(
  token: string,
  databaseId: string,
  signal?: AbortSignal
): Promise<NotionPage[]> {
  const entries: NotionPage[] = [];
  let startCursor: string | undefined;
  const headers = getHeaders(token);

  do {
    if (signal?.aborted) throw new Error('Sync cancelled');

    const response = await fetchWithRetry(`${API_BASE}/databases/${databaseId}/query`, {
      method: 'POST',
      headers,
      body: JSON.stringify({
        page_size: 100,
        start_cursor: startCursor,
      }),
      signal,
    });

    if (!response.ok) return entries;

    const data = await response.json();
    entries.push(...data.results);
    startCursor = data.has_more ? data.next_cursor : undefined;

    await new Promise(resolve => setTimeout(resolve, 350));
  } while (startCursor);

  return entries;
}

// --- Main Sync Function ---

/**
 * Validate a Notion integration token by making a test API call.
 */
export async function testNotionConnection(token: string): Promise<{ ok: boolean; error?: string }> {
  try {
    const response = await fetch(`${API_BASE}/users/me`, {
      headers: getHeaders(token),
    });

    if (response.ok) {
      return { ok: true };
    }

    const error = await response.text();
    if (response.status === 401) {
      return { ok: false, error: 'Invalid token. Check your Notion integration token.' };
    }
    return { ok: false, error: `Notion API error: ${response.status} - ${error}` };
  } catch (error: any) {
    return { ok: false, error: `Connection failed: ${error.message}` };
  }
}

/**
 * Sync Notion content directly to the vector store.
 *
 * Runs in-process (no child process). Supports incremental sync via cursor.
 * Each page/database entry is indexed directly to the vector store.
 *
 * @param connectorId  The connector ID for metadata tracking
 * @param config       Connector config containing `token`
 * @param cursor       Previous sync cursor (null for full sync)
 * @param onProgress   Optional callback for progress updates
 * @param signal       Optional AbortSignal for cancellation
 */
export async function syncNotion(
  connectorId: string,
  config: Record<string, any>,
  cursor: NotionSyncCursor | null,
  onProgress?: (progress: NotionSyncProgress) => void,
  signal?: AbortSignal
): Promise<NotionSyncResult> {
  const token = config.token;
  if (!token || typeof token !== 'string') {
    return {
      success: false,
      pagesIndexed: 0,
      pagesUpdated: 0,
      databaseEntriesIndexed: 0,
      duplicatesSkipped: 0,
      errors: ['Missing or invalid Notion token in connector config'],
      syncedAt: new Date().toISOString(),
      cursor: cursor || { lastSyncAt: '' },
    };
  }

  const available = await isVectorStoreAvailable();
  if (!available) {
    return {
      success: false,
      pagesIndexed: 0,
      pagesUpdated: 0,
      databaseEntriesIndexed: 0,
      duplicatesSkipped: 0,
      errors: ['Vector store not available'],
      syncedAt: new Date().toISOString(),
      cursor: cursor || { lastSyncAt: '' },
    };
  }

  const syncStartedAt = new Date().toISOString();
  const client = getVectorStoreClient();
  const result: NotionSyncResult = {
    success: true,
    pagesIndexed: 0,
    pagesUpdated: 0,
    databaseEntriesIndexed: 0,
    duplicatesSkipped: 0,
    errors: [],
    syncedAt: '',
    cursor: cursor || { lastSyncAt: '' },
  };

  const lastSyncAt = cursor?.lastSyncAt || null;
  const syncType = lastSyncAt ? 'incremental' : 'full';
  console.log(`[notion] Starting ${syncType} sync for connector ${connectorId}${lastSyncAt ? ` (since ${lastSyncAt})` : ''}`);

  try {
    // Phase 1: Search for content
    onProgress?.({
      phase: 'searching',
      pagesFound: 0,
      databasesFound: 0,
      pagesProcessed: 0,
      databasesProcessed: 0,
    });

    const { pages, databases } = await searchContent(token, lastSyncAt, signal);
    console.log(`[notion] Found ${pages.length} pages, ${databases.length} databases${lastSyncAt ? ' (changed since last sync)' : ''}`);

    // Phase 2: Index pages
    onProgress?.({
      phase: 'indexing-pages',
      pagesFound: pages.length,
      databasesFound: databases.length,
      pagesProcessed: 0,
      databasesProcessed: 0,
    });

    for (let i = 0; i < pages.length; i++) {
      if (signal?.aborted) throw new Error('Sync cancelled');

      const page = pages[i];
      const title = getPageTitle(page);

      try {
        const content = await getPageMarkdown(token, page.id, signal);
        const text = content ? `# ${title}\n\n${content}` : `# ${title}`;

        const addResult = await client.addDocument(text, {
          source: 'notion',
          connectorId,
          notionId: page.id,
          title,
          url: page.url,
          parentType: page.parent.type,
          createdAt: page.created_time,
          updatedAt: page.last_edited_time,
        });

        if (addResult.is_duplicate) {
          result.duplicatesSkipped++;
        } else if (lastSyncAt) {
          result.pagesUpdated++;
        } else {
          result.pagesIndexed++;
        }
      } catch (pageError: any) {
        result.errors.push(`Page "${title}" (${page.id}): ${pageError.message}`);
        console.error(`[notion] Error indexing page "${title}":`, pageError.message);
      }

      onProgress?.({
        phase: 'indexing-pages',
        pagesFound: pages.length,
        databasesFound: databases.length,
        pagesProcessed: i + 1,
        databasesProcessed: 0,
      });
    }

    // Phase 3: Index databases
    onProgress?.({
      phase: 'indexing-databases',
      pagesFound: pages.length,
      databasesFound: databases.length,
      pagesProcessed: pages.length,
      databasesProcessed: 0,
    });

    for (let i = 0; i < databases.length; i++) {
      if (signal?.aborted) throw new Error('Sync cancelled');

      const database = databases[i];
      const dbTitle = database.title.map(t => t.plain_text).join('') || 'Untitled Database';

      try {
        const entries = await getDatabaseEntries(token, database.id, signal);
        const propertyNames = Object.keys(database.properties);

        for (const entry of entries) {
          if (signal?.aborted) throw new Error('Sync cancelled');

          const entryTitle = getPageTitle(entry);
          const propsText = propertyNames
            .map(propName => {
              const prop = entry.properties[propName];
              if (!prop) return null;
              const value = extractPropertyValue(prop);
              return value ? `${propName}: ${value}` : null;
            })
            .filter(Boolean)
            .join('\n');

          const text = `# ${entryTitle}\n\nDatabase: ${dbTitle}\n\n${propsText}`;

          const addResult = await client.addDocument(text, {
            source: 'notion',
            connectorId,
            notionId: entry.id,
            databaseId: database.id,
            databaseTitle: dbTitle,
            title: entryTitle,
            url: entry.url,
          });

          if (addResult.is_duplicate) {
            result.duplicatesSkipped++;
          } else {
            result.databaseEntriesIndexed++;
          }
        }
      } catch (dbError: any) {
        result.errors.push(`Database "${dbTitle}" (${database.id}): ${dbError.message}`);
        console.error(`[notion] Error indexing database "${dbTitle}":`, dbError.message);
      }

      onProgress?.({
        phase: 'indexing-databases',
        pagesFound: pages.length,
        databasesFound: databases.length,
        pagesProcessed: pages.length,
        databasesProcessed: i + 1,
      });
    }

    onProgress?.({
      phase: 'complete',
      pagesFound: pages.length,
      databasesFound: databases.length,
      pagesProcessed: pages.length,
      databasesProcessed: databases.length,
    });

    const totalIndexed = result.pagesIndexed + result.pagesUpdated + result.databaseEntriesIndexed;
    // Set cursor and timestamp only after successful sync
    result.syncedAt = new Date().toISOString();
    result.cursor = { lastSyncAt: syncStartedAt };

    console.log(`[notion] Sync complete: ${totalIndexed} indexed, ${result.duplicatesSkipped} duplicates, ${result.errors.length} errors`);

    if (result.errors.length > 0) {
      result.success = result.errors.length < (pages.length + databases.length);
    }

    return result;
  } catch (error: any) {
    console.error(`[notion] Sync failed:`, error.message);
    result.success = false;
    result.errors.push(error.message);
    // On failure, don't advance the cursor
    result.cursor = cursor || { lastSyncAt: '' };
    return result;
  }
}
