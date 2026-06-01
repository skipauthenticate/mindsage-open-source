import * as fs from 'fs';
import * as path from 'path';

// Configuration from environment
const EXPORTS_DIR = process.env.EXPORTS_DIR || './data/exports';
const NOTION_TOKEN = process.env.NOTION_TOKEN;

interface NotionBlock {
  id: string;
  type: string;
  [key: string]: any;
}

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
    title?: {
      title: { plain_text: string }[];
    };
    Name?: {
      title: { plain_text: string }[];
    };
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

interface ExportedPage {
  type: 'page';
  id: string;
  title: string;
  content: string;
  url: string;
  parentType: string;
  createdAt: string;
  updatedAt: string;
  exportedAt: string;
}

interface ExportedDatabase {
  type: 'database';
  id: string;
  title: string;
  url: string;
  properties: string[];
  entries: {
    id: string;
    title: string;
    properties: Record<string, string>;
    url: string;
  }[];
  createdAt: string;
  updatedAt: string;
  exportedAt: string;
}

interface ExportedIds {
  pageIds: string[];
  databaseIds: string[];
  lastExport: string;
}

const API_BASE = 'https://api.notion.com/v1';
const NOTION_VERSION = '2022-06-28';

function ensureDirectories(): void {
  if (!fs.existsSync(EXPORTS_DIR)) {
    fs.mkdirSync(EXPORTS_DIR, { recursive: true });
  }
}

function loadExportedIds(): ExportedIds {
  const exportedIdsFile = path.join(EXPORTS_DIR, '.exported-ids.json');
  if (fs.existsSync(exportedIdsFile)) {
    return JSON.parse(fs.readFileSync(exportedIdsFile, 'utf-8'));
  }
  return { pageIds: [], databaseIds: [], lastExport: '' };
}

function saveExportedIds(data: ExportedIds): void {
  const exportedIdsFile = path.join(EXPORTS_DIR, '.exported-ids.json');
  fs.writeFileSync(exportedIdsFile, JSON.stringify(data, null, 2));
}

async function fetchWithRetry(
  url: string,
  options: RequestInit,
  retries = 3
): Promise<Response> {
  for (let i = 0; i < retries; i++) {
    try {
      const response = await fetch(url, options);
      if (response.status === 429) {
        // Notion recommends exponential backoff
        const retryAfter = response.headers.get('retry-after');
        const waitTime = retryAfter ? parseInt(retryAfter) * 1000 : Math.pow(2, i) * 1000;
        console.log(`[fetchWithRetry] Rate limited, waiting ${waitTime}ms...`);
        await new Promise(resolve => setTimeout(resolve, waitTime));
        continue;
      }
      return response;
    } catch (error) {
      if (i === retries - 1) throw error;
      await new Promise(resolve => setTimeout(resolve, 1000));
    }
  }
  throw new Error('Max retries exceeded');
}

function getDefaultHeaders(): Record<string, string> {
  return {
    Authorization: `Bearer ${NOTION_TOKEN}`,
    'Notion-Version': NOTION_VERSION,
    'Content-Type': 'application/json',
  };
}

async function searchAllContent(): Promise<{ pages: NotionPage[]; databases: NotionDatabase[] }> {
  console.log('[searchAllContent] Searching for all accessible pages and databases...');
  const pages: NotionPage[] = [];
  const databases: NotionDatabase[] = [];
  let startCursor: string | undefined;

  do {
    const response = await fetchWithRetry(`${API_BASE}/search`, {
      method: 'POST',
      headers: getDefaultHeaders(),
      body: JSON.stringify({
        page_size: 100,
        start_cursor: startCursor,
      }),
    });

    if (!response.ok) {
      const error = await response.text();
      throw new Error(`Search failed: ${response.status} - ${error}`);
    }

    const data = await response.json();

    for (const result of data.results) {
      if (result.object === 'page') {
        pages.push(result);
      } else if (result.object === 'database') {
        databases.push(result);
      }
    }

    startCursor = data.has_more ? data.next_cursor : undefined;
    console.log(`[searchAllContent] Found ${pages.length} pages, ${databases.length} databases so far...`);

    // Small delay to respect rate limits (3 req/sec)
    await new Promise(resolve => setTimeout(resolve, 350));
  } while (startCursor);

  return { pages, databases };
}

async function getPageBlocks(pageId: string): Promise<NotionBlock[]> {
  const blocks: NotionBlock[] = [];
  let startCursor: string | undefined;

  do {
    const url = new URL(`${API_BASE}/blocks/${pageId}/children`);
    if (startCursor) {
      url.searchParams.set('start_cursor', startCursor);
    }
    url.searchParams.set('page_size', '100');

    const response = await fetchWithRetry(url.toString(), {
      headers: getDefaultHeaders(),
    });

    if (!response.ok) {
      // Some pages might not allow block access
      return blocks;
    }

    const data = await response.json();
    blocks.push(...data.results);
    startCursor = data.has_more ? data.next_cursor : undefined;

    await new Promise(resolve => setTimeout(resolve, 350));
  } while (startCursor);

  return blocks;
}

function extractTextFromBlock(block: NotionBlock): string {
  const blockContent = block[block.type];
  if (!blockContent) return '';

  // Handle rich_text array (most text blocks)
  if (blockContent.rich_text && Array.isArray(blockContent.rich_text)) {
    return blockContent.rich_text.map((t: any) => t.plain_text || '').join('');
  }

  // Handle title (for child_page, child_database)
  if (blockContent.title) {
    return blockContent.title;
  }

  // Handle caption
  if (blockContent.caption && Array.isArray(blockContent.caption)) {
    return blockContent.caption.map((t: any) => t.plain_text || '').join('');
  }

  return '';
}

function blocksToText(blocks: NotionBlock[]): string {
  const lines: string[] = [];

  for (const block of blocks) {
    const text = extractTextFromBlock(block);
    const type = block.type;

    switch (type) {
      case 'heading_1':
        lines.push(`# ${text}`);
        break;
      case 'heading_2':
        lines.push(`## ${text}`);
        break;
      case 'heading_3':
        lines.push(`### ${text}`);
        break;
      case 'paragraph':
        if (text) lines.push(text);
        break;
      case 'bulleted_list_item':
        lines.push(`• ${text}`);
        break;
      case 'numbered_list_item':
        lines.push(`- ${text}`);
        break;
      case 'to_do':
        const checked = block.to_do?.checked ? '✓' : '○';
        lines.push(`${checked} ${text}`);
        break;
      case 'toggle':
        lines.push(`▸ ${text}`);
        break;
      case 'quote':
        lines.push(`> ${text}`);
        break;
      case 'callout':
        const emoji = block.callout?.icon?.emoji || '📌';
        lines.push(`${emoji} ${text}`);
        break;
      case 'code':
        const lang = block.code?.language || '';
        lines.push(`\`\`\`${lang}\n${text}\n\`\`\``);
        break;
      case 'divider':
        lines.push('---');
        break;
      case 'child_page':
        lines.push(`📄 [Subpage: ${text}]`);
        break;
      case 'child_database':
        lines.push(`📊 [Database: ${text}]`);
        break;
      default:
        if (text) lines.push(text);
    }
  }

  return lines.join('\n\n');
}

function getPageTitle(page: NotionPage): string {
  // Try different property names that might contain the title
  const props = page.properties;

  if (props.title?.title) {
    return props.title.title.map(t => t.plain_text).join('') || 'Untitled';
  }
  if (props.Name?.title) {
    return props.Name.title.map(t => t.plain_text).join('') || 'Untitled';
  }

  // Check all properties for a title type
  for (const key of Object.keys(props)) {
    if (props[key]?.title) {
      return props[key].title.map((t: any) => t.plain_text).join('') || 'Untitled';
    }
  }

  return 'Untitled';
}

async function getDatabaseEntries(databaseId: string): Promise<NotionPage[]> {
  const entries: NotionPage[] = [];
  let startCursor: string | undefined;

  do {
    const response = await fetchWithRetry(`${API_BASE}/databases/${databaseId}/query`, {
      method: 'POST',
      headers: getDefaultHeaders(),
      body: JSON.stringify({
        page_size: 100,
        start_cursor: startCursor,
      }),
    });

    if (!response.ok) {
      return entries;
    }

    const data = await response.json();
    entries.push(...data.results);
    startCursor = data.has_more ? data.next_cursor : undefined;

    await new Promise(resolve => setTimeout(resolve, 350));
  } while (startCursor);

  return entries;
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

function saveExport(filename: string, data: ExportedPage | ExportedDatabase): void {
  const filepath = path.join(EXPORTS_DIR, filename);
  fs.writeFileSync(filepath, JSON.stringify(data, null, 2));
}

async function main(): Promise<void> {
  if (!NOTION_TOKEN) {
    console.error('Missing NOTION_TOKEN environment variable');
    console.error('');
    console.error('To get your Notion integration token:');
    console.error('1. Go to https://www.notion.so/my-integrations');
    console.error('2. Create a new internal integration');
    console.error('3. Copy the "Internal Integration Token"');
    console.error('4. Share pages/databases with your integration in Notion');
    process.exit(1);
  }

  ensureDirectories();

  console.log('='.repeat(60));
  console.log('Starting Notion Exporter');
  console.log('='.repeat(60));
  console.log('Note: Only pages/databases shared with your integration will be exported.');
  console.log('='.repeat(60));

  try {
    const { pages, databases } = await searchAllContent();
    const exportedData = loadExportedIds();
    const exportedPageSet = new Set(exportedData.pageIds);
    const exportedDbSet = new Set(exportedData.databaseIds);

    let newPages = 0;
    let newDatabases = 0;

    // Export pages
    console.log(`\n[main] Exporting ${pages.length} pages...`);
    for (const page of pages) {
      const title = getPageTitle(page);
      console.log(`[main] Processing page: "${title}"`);

      // Get page content
      const blocks = await getPageBlocks(page.id);
      const content = blocksToText(blocks);

      const exported: ExportedPage = {
        type: 'page',
        id: page.id,
        title,
        content,
        url: page.url,
        parentType: page.parent.type,
        createdAt: page.created_time,
        updatedAt: page.last_edited_time,
        exportedAt: new Date().toISOString(),
      };

      const sanitizedTitle = title.replace(/[^a-z0-9]/gi, '_').substring(0, 40);
      const shortId = page.id.replace(/-/g, '').substring(0, 8);
      saveExport(`notion_page_${shortId}_${sanitizedTitle}.json`, exported);

      if (!exportedPageSet.has(page.id)) {
        exportedData.pageIds.push(page.id);
        exportedPageSet.add(page.id);
        newPages++;
        console.log(`[main] ✓ New page: "${title}"`);
      } else {
        console.log(`[main] ↻ Updated page: "${title}"`);
      }
    }

    // Export databases
    console.log(`\n[main] Exporting ${databases.length} databases...`);
    for (const database of databases) {
      const title = database.title.map(t => t.plain_text).join('') || 'Untitled Database';
      console.log(`[main] Processing database: "${title}"`);

      // Get database entries
      const entries = await getDatabaseEntries(database.id);
      const propertyNames = Object.keys(database.properties);

      const exportedEntries = entries.map(entry => {
        const entryTitle = getPageTitle(entry);
        const properties: Record<string, string> = {};

        for (const propName of propertyNames) {
          const prop = entry.properties[propName];
          if (prop) {
            properties[propName] = extractPropertyValue(prop);
          }
        }

        return {
          id: entry.id,
          title: entryTitle,
          properties,
          url: entry.url,
        };
      });

      const exported: ExportedDatabase = {
        type: 'database',
        id: database.id,
        title,
        url: database.url,
        properties: propertyNames,
        entries: exportedEntries,
        createdAt: database.created_time,
        updatedAt: database.last_edited_time,
        exportedAt: new Date().toISOString(),
      };

      const sanitizedTitle = title.replace(/[^a-z0-9]/gi, '_').substring(0, 40);
      const shortId = database.id.replace(/-/g, '').substring(0, 8);
      saveExport(`notion_db_${shortId}_${sanitizedTitle}.json`, exported);

      if (!exportedDbSet.has(database.id)) {
        exportedData.databaseIds.push(database.id);
        exportedDbSet.add(database.id);
        newDatabases++;
        console.log(`[main] ✓ New database: "${title}" (${entries.length} entries)`);
      } else {
        console.log(`[main] ↻ Updated database: "${title}" (${entries.length} entries)`);
      }
    }

    exportedData.lastExport = new Date().toISOString();
    saveExportedIds(exportedData);

    console.log('='.repeat(60));
    console.log(`Export complete!`);
    console.log(`  - Pages: ${pages.length} (${newPages} new)`);
    console.log(`  - Databases: ${databases.length} (${newDatabases} new)`);
    console.log('='.repeat(60));
  } catch (error) {
    console.error('[main] Export failed:', error);
    throw error;
  }
}

main().catch((error) => {
  console.error('Fatal error:', error);
  process.exit(1);
});
