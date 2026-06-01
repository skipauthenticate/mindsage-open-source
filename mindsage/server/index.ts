import express from 'express';
import { spawn, ChildProcess } from 'child_process';
import { randomUUID, randomBytes, timingSafeEqual } from 'crypto';
import * as fs from 'fs';
import * as http from 'http';
import * as path from 'path';
import * as os from 'os';
import { fileURLToPath } from 'url';
import cors from 'cors';
import multer from 'multer';
import { getLocalSendServer, LocalSendServer, OnFileReceivedCallback } from './localsend-server.js';
import {
  getVectorStoreClient,
  initVectorStoreClient,
  isVectorStoreAvailable,
  VectorStoreClient,
  EnhancedSearchResult,
  EnhancedSearchOptions,
  AddDocumentResult,
} from './vector-store-client.js';
import {
  getChatStatus,
  streamChat,
  chat,
  ChatRequest,
  StreamEvent,
  getLLMConfigResponse,
  updateLLMConfig,
  testApiKey,
  StoredLLMConfig,
} from './chat-service.js';
import { browserConnectorRouter, autoStartIfConfigured } from './browser-connector/index.js';
import { createIngestRouter } from './connectors/ingest.js';
import { syncNotion, testNotionConnection } from './connectors/notion.js';
import { syncReadwise, testReadwiseConnection } from './connectors/readwise.js';
import { createWebhookRouter } from './connectors/webhooks.js';
import { ConnectorScheduler } from './connectors/scheduler.js';
import {
  processFacebookExport as processFacebookExportExtracted,
  loadPendingMediaRegistry,
} from './connectors/facebook.js';

// LocalSend server instance
let localSendServerInstance: LocalSendServer | null = null;

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT_DIR = path.join(__dirname, '..');

const app = express();
// RT-07: Restrict CORS to localhost and private network origins only
// Pre-compiled at module level to avoid regex re-parsing on every request
const CORS_ORIGIN_PATTERN = /^https?:\/\/(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+)(:\d+)?$/;

app.use(cors({
  origin: function(origin: string | undefined, callback: (err: Error | null, allow?: boolean) => void) {
    // Allow requests with no origin (same-origin, server-to-server, curl, etc.)
    if (!origin) return callback(null, true);
    // Allow localhost and private network (RFC 1918) origins
    if (CORS_ORIGIN_PATTERN.test(origin)) return callback(null, true);
    callback(new Error('CORS: Origin not allowed'));
  },
  credentials: true
}));
app.use(express.json({ limit: '10mb' }));
app.use(express.text({ type: 'text/plain', limit: '10mb' }));

// API-only server - no static file serving
// Frontend is served separately from mindsage-frontend package

const DATA_DIR = path.join(ROOT_DIR, 'data');
const CONNECTORS_DIR = path.join(DATA_DIR, 'connectors');
const EXPORTS_DIR = path.join(DATA_DIR, 'exports');
const UPLOADS_DIR = path.join(DATA_DIR, 'uploads');
const IMPORTS_DIR = path.join(DATA_DIR, 'imports');
const INDEXED_FILES_PATH = path.join(DATA_DIR, '.indexed-files.json');
const GRAPH_VIEWS_DIR = path.join(DATA_DIR, 'graph-views');
const GRAPH_CONNECTIONS_FILE = path.join(DATA_DIR, 'graph-connections.json');
// Pre-resolved for RT-04 path traversal checks (avoids per-request path.resolve)
const RESOLVED_EXPORTS_DIR = path.resolve(EXPORTS_DIR) + path.sep;

// --- RT-01: API Authentication ---
// Bearer token auth to prevent unauthenticated remote access.
// Token is generated on first startup and stored in data/.api-token.
// Localhost requests are allowed without a token (on-device frontend).
// Remote requests must provide: Authorization: Bearer <token>
const API_TOKEN_PATH = path.join(DATA_DIR, '.api-token');

function loadOrGenerateApiToken(): string {
  try {
    if (fs.existsSync(API_TOKEN_PATH)) {
      const token = fs.readFileSync(API_TOKEN_PATH, 'utf-8').trim();
      if (token.length >= 32) return token;
    }
  } catch {}
  // Ensure data directory exists
  if (!fs.existsSync(DATA_DIR)) {
    fs.mkdirSync(DATA_DIR, { recursive: true });
  }
  const token = randomBytes(32).toString('hex');
  fs.writeFileSync(API_TOKEN_PATH, token, { mode: 0o600 });
  console.log(`[Security] Generated new API token at ${API_TOKEN_PATH}`);
  return token;
}

const API_TOKEN = loadOrGenerateApiToken();

// Paths exempt from authentication (health checks + webhook endpoints)
// Webhooks use their own verification (HMAC signatures / shared secrets)
const AUTH_EXEMPT_PATHS = new Set([
  '/health', '/api/health',
  '/api/webhooks/notion', '/api/webhooks/readwise',
]);

function getDirectClientIp(req: express.Request): string {
  // RT-01: Never trust X-Forwarded-For — use socket address only
  return req.socket.remoteAddress || '';
}

function isLocalhostIp(ip: string): boolean {
  return ip === '127.0.0.1' || ip === '::1' || ip === '::ffff:127.0.0.1';
}

// Auth middleware
app.use((req: express.Request, res: express.Response, next: express.NextFunction) => {
  // Health checks are always allowed
  if (AUTH_EXEMPT_PATHS.has(req.path)) return next();

  // Localhost requests pass through (on-device frontend/services)
  const clientIp = getDirectClientIp(req);
  if (isLocalhostIp(clientIp)) return next();

  // Remote requests require bearer token
  const authHeader = req.headers.authorization;
  const token = authHeader?.startsWith('Bearer ') ? authHeader.slice(7) :
                (typeof req.query.token === 'string' ? req.query.token : null);

  if (token && token.length === API_TOKEN.length) {
    try {
      if (timingSafeEqual(Buffer.from(token), Buffer.from(API_TOKEN))) {
        return next();
      }
    } catch { /* length mismatch or encoding error */ }
  }

  return res.status(401).json({
    error: 'Authentication required',
    message: 'Provide API token via Authorization: Bearer <token> header. Token is stored in data/.api-token on the device.'
  });
});

// Localhost-only endpoint to retrieve API token (for frontend bootstrapping)
app.get('/api/auth/token', (req: express.Request, res: express.Response) => {
  const clientIp = getDirectClientIp(req);
  if (!isLocalhostIp(clientIp)) {
    return res.status(403).json({ error: 'Token retrieval is only available from localhost' });
  }
  res.json({ token: API_TOKEN });
});

// Track which files have been indexed to avoid re-indexing
interface IndexedFileRecord {
  filename: string;
  filePath: string;
  indexedAt: string;
  documentId?: number;
  size: number;
  modified: string;
}

function loadIndexedFiles(): Map<string, IndexedFileRecord> {
  try {
    if (fs.existsSync(INDEXED_FILES_PATH)) {
      const data = JSON.parse(fs.readFileSync(INDEXED_FILES_PATH, 'utf-8'));
      return new Map(Object.entries(data));
    }
  } catch (error) {
    console.error('Error loading indexed files:', error);
  }
  return new Map();
}

function saveIndexedFiles(indexed: Map<string, IndexedFileRecord>): void {
  try {
    const data = Object.fromEntries(indexed);
    fs.writeFileSync(INDEXED_FILES_PATH, JSON.stringify(data, null, 2));
  } catch (error) {
    console.error('Error saving indexed files:', error);
  }
}

function isFileIndexed(filePath: string): boolean {
  const indexed = loadIndexedFiles();
  const record = indexed.get(filePath);
  if (!record) return false;

  // Check if file still exists and hasn't been modified
  try {
    const stat = fs.statSync(filePath);
    return record.modified === stat.mtime.toISOString();
  } catch {
    return false;
  }
}

function markFileIndexed(filePath: string, documentId?: number): void {
  const indexed = loadIndexedFiles();
  const stat = fs.statSync(filePath);
  indexed.set(filePath, {
    filename: path.basename(filePath),
    filePath,
    indexedAt: new Date().toISOString(),
    documentId,
    size: stat.size,
    modified: stat.mtime.toISOString(),
  });
  saveIndexedFiles(indexed);
}

// Graph views and connections storage helpers
function ensureGraphDirs(): void {
  if (!fs.existsSync(GRAPH_VIEWS_DIR)) {
    fs.mkdirSync(GRAPH_VIEWS_DIR, { recursive: true });
  }
}

function readGraphConnections(): any[] {
  try {
    if (fs.existsSync(GRAPH_CONNECTIONS_FILE)) {
      return JSON.parse(fs.readFileSync(GRAPH_CONNECTIONS_FILE, 'utf-8'));
    }
  } catch (error) {
    console.error('Error reading graph connections:', error);
  }
  return [];
}

function writeGraphConnections(connections: any[]): void {
  fs.writeFileSync(GRAPH_CONNECTIONS_FILE, JSON.stringify(connections, null, 2));
}

// Configure multer for file uploads
const storage = multer.diskStorage({
  destination: (_req, _file, cb) => {
    cb(null, UPLOADS_DIR);
  },
  filename: (_req, file, cb) => {
    // Preserve original filename, handle duplicates
    const originalName = file.originalname;
    const filePath = path.join(UPLOADS_DIR, originalName);

    if (fs.existsSync(filePath)) {
      const ext = path.extname(originalName);
      const base = path.basename(originalName, ext);
      const timestamp = Date.now();
      cb(null, `${base}-${timestamp}${ext}`);
    } else {
      cb(null, originalName);
    }
  },
});

const upload = multer({
  storage,
  limits: {
    fileSize: 10 * 1024 * 1024 * 1024, // 10GB max file size
  },
});

interface ConnectorConfig {
  id: string;
  name: string;
  type: 'api' | 'webhook' | 'file' | 'custom';
  config: Record<string, any>;
  status: 'connected' | 'syncing' | 'error' | 'paused';
  lastSync?: string;
  itemCount: number;
  syncCursor?: { lastSyncAt: string; cursor?: string; state?: Record<string, any> };
  autoSyncEnabled?: boolean;
  autoSyncIntervalHours?: number;
}

interface RunStatus {
  running: boolean;
  output: string[];
  lastRun?: string;
  exitCode?: number;
  connectorId?: string;
}

let runStatuses: Map<string, RunStatus> = new Map();
let currentProcesses: Map<string, ChildProcess> = new Map();

// Background indexing job system for async file processing
interface IndexingJob {
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

const indexingJobs: Map<string, IndexingJob> = new Map();
const indexingQueue: string[] = [];
let isProcessingQueue = false;

// Supported media extensions for indexing queue (images and audio that vector-store can process)
const INDEXABLE_MEDIA_EXTENSIONS = new Set([
  '.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp',  // Images
  '.mp3', '.m4a', '.wav', '.aac', '.ogg', '.flac',   // Audio
]);

// Upload a media file to the vector store (for images/audio processing)
async function uploadMediaToVectorStore(filePath: string, filename: string): Promise<AddDocumentResult> {
  const vsHost = process.env.VECTOR_STORE_HOST || 'localhost';
  const vsPort = process.env.VECTOR_STORE_PORT || '8085';
  const url = `http://${vsHost}:${vsPort}/api/media/upload`;

  // Read the file
  const fileContent = fs.readFileSync(filePath);
  const boundary = '----FormBoundary' + Math.random().toString(36).substring(2);

  // Build multipart form data
  const header = Buffer.from(
    `--${boundary}\r\n` +
    `Content-Disposition: form-data; name="file"; filename="${filename}"\r\n` +
    `Content-Type: application/octet-stream\r\n\r\n`
  );
  const footer = Buffer.from(`\r\n--${boundary}--\r\n`);
  const body = Buffer.concat([header, fileContent, footer]);

  return new Promise((resolve, reject) => {
    const req = http.request(url, {
      method: 'POST',
      headers: {
        'Content-Type': `multipart/form-data; boundary=${boundary}`,
        'Content-Length': body.length,
      },
      timeout: 300000, // 5 minutes for media processing
    }, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        try {
          const result = JSON.parse(data);
          if (res.statusCode === 200) {
            resolve({
              success: true,
              document_id: result.document_id,
              is_duplicate: result.is_duplicate || false,
              existing_document_id: result.existing_document_id,
              message: result.message,
            });
          } else {
            reject(new Error(result.error || `HTTP ${res.statusCode}`));
          }
        } catch (e) {
          reject(new Error(`Invalid response: ${data.substring(0, 200)}`));
        }
      });
    });

    req.on('error', reject);
    req.on('timeout', () => {
      req.destroy();
      reject(new Error('Media upload timed out'));
    });

    req.write(body);
    req.end();
  });
}

// Process the indexing queue in background
async function processIndexingQueue(): Promise<void> {
  if (isProcessingQueue || indexingQueue.length === 0) return;

  isProcessingQueue = true;

  try {
    while (indexingQueue.length > 0) {
      const jobId = indexingQueue.shift();
      if (!jobId) continue;

      const job = indexingJobs.get(jobId);
      if (!job || job.status !== 'queued') continue;

      job.status = 'processing';
      job.startedAt = new Date().toISOString();
      job.progress = 'Starting indexing...';

    try {
      const available = await isVectorStoreAvailable();
      if (!available) {
        job.status = 'failed';
        job.error = 'Vector store not available';
        job.completedAt = new Date().toISOString();
        continue;
      }

      const ext = path.extname(job.filePath).toLowerCase();
      const isMediaFile = INDEXABLE_MEDIA_EXTENSIONS.has(ext);
      const isTextFile = SUPPORTED_TEXT_EXTENSIONS.has(ext);

      if (!isMediaFile && !isTextFile) {
        job.status = 'completed';
        job.progress = 'Skipped - unsupported file type';
        job.result = { indexed: false, isDuplicate: false };
        job.completedAt = new Date().toISOString();
        continue;
      }

      let result: AddDocumentResult;

      if (isMediaFile) {
        // Media files (images, audio) - upload to vector store for processing
        job.progress = 'Processing media file...';
        console.log(`Indexing media file: ${job.filename} (${ext})`);
        result = await uploadMediaToVectorStore(job.filePath, job.filename);
      } else {
        // Text files - extract text and add as document
        job.progress = 'Extracting text...';
        const text = await extractTextFromFile(job.filePath);

        if (!text || text.trim().length === 0) {
          job.status = 'completed';
          job.progress = 'Skipped - empty or unreadable';
          job.result = { indexed: false, isDuplicate: false };
          job.completedAt = new Date().toISOString();
          continue;
        }

        job.progress = 'Generating embeddings and topics...';
        const stat = fs.statSync(job.filePath);
        const client = getVectorStoreClient();

        result = await client.addDocument(text, {
          source: 'import',
          filename: job.filename,
          extension: ext,
          filePath: job.filePath,
          size: stat.size,
          modified: stat.mtime.toISOString(),
          indexed_at: new Date().toISOString(),
        });
      }

      if (result.is_duplicate) {
        markFileIndexed(job.filePath, result.existing_document_id);
        job.status = 'completed';
        job.progress = 'Content already indexed';
        job.result = {
          indexed: false,
          isDuplicate: true,
          existingDocId: result.existing_document_id,
        };
      } else if (result.document_id) {
        markFileIndexed(job.filePath, result.document_id);
        job.status = 'completed';
        job.progress = 'Successfully indexed';
        job.result = {
          indexed: true,
          isDuplicate: false,
          documentId: result.document_id,
        };
      }

      job.completedAt = new Date().toISOString();
      } catch (err) {
        job.status = 'failed';
        job.error = String(err);
        job.completedAt = new Date().toISOString();
        console.error(`Indexing job ${jobId} failed:`, err);
      }
    }
  } finally {
    isProcessingQueue = false;
  }
}

// Queue a file for background indexing
function queueIndexingJob(filename: string, filePath: string): string {
  const jobId = `idx_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;

  const job: IndexingJob = {
    id: jobId,
    filename,
    filePath,
    status: 'queued',
    progress: 'Waiting in queue...',
  };

  indexingJobs.set(jobId, job);
  indexingQueue.push(jobId);

  // Clean up old completed jobs (keep last 100)
  const allJobs = Array.from(indexingJobs.entries());
  const completedJobs = allJobs.filter(([_, j]) => j.status === 'completed' || j.status === 'failed');
  if (completedJobs.length > 100) {
    completedJobs
      .sort((a, b) => (a[1].completedAt || '').localeCompare(b[1].completedAt || ''))
      .slice(0, completedJobs.length - 100)
      .forEach(([id]) => indexingJobs.delete(id));
  }

  // Start processing queue (non-blocking)
  setImmediate(() => processIndexingQueue());

  return jobId;
}

// Auto-import a file: move from uploads to imports and queue for indexing
function autoImportFile(filename: string, sourcePath: string): void {
  try {
    // Security check: ensure source is within UPLOADS_DIR
    const resolvedSource = path.resolve(sourcePath);
    const resolvedDir = path.resolve(UPLOADS_DIR);
    if (!resolvedSource.startsWith(resolvedDir + path.sep) && resolvedSource !== resolvedDir) {
      console.error(`Auto-import: Security check failed for "${filename}"`);
      return;
    }

    if (!fs.existsSync(sourcePath)) {
      console.error(`Auto-import: File not found "${filename}"`);
      return;
    }

    // Handle duplicate filenames in imports
    let destPath = path.join(IMPORTS_DIR, filename);
    if (fs.existsSync(destPath)) {
      const ext = path.extname(filename);
      const base = path.basename(filename, ext);
      const timestamp = Date.now();
      destPath = path.join(IMPORTS_DIR, `${base}-${timestamp}${ext}`);
    }

    // Move file to imports directory
    fs.renameSync(sourcePath, destPath);

    // Queue background indexing
    const jobId = queueIndexingJob(path.basename(destPath), destPath);
    console.log(`Auto-import: "${filename}" queued for indexing (job ${jobId})`);
  } catch (err) {
    console.error(`Auto-import failed for "${filename}":`, err);
  }
}

// Ensure directories exist
function ensureDirectories(): void {
  [DATA_DIR, CONNECTORS_DIR, EXPORTS_DIR, UPLOADS_DIR, IMPORTS_DIR].forEach(dir => {
    if (!fs.existsSync(dir)) {
      fs.mkdirSync(dir, { recursive: true });
      console.log(`Created directory: ${dir}`);
    }
  });
}

ensureDirectories();

// Unified scheduler for all connectors
const connectorScheduler = new ConnectorScheduler(
  DATA_DIR,
  (connectorId, config) => {
    runCustomScript(connectorId, config);
  },
  (connectorId) => runStatuses.get(connectorId)?.running === true
);

// Load connectors
function loadConnectors(): ConnectorConfig[] {
  const configPath = path.join(DATA_DIR, 'connectors.json');
  if (fs.existsSync(configPath)) {
    return JSON.parse(fs.readFileSync(configPath, 'utf-8'));
  }
  return [];
}

// Save connectors
function saveConnectors(connectors: ConnectorConfig[]): void {
  const configPath = path.join(DATA_DIR, 'connectors.json');
  fs.writeFileSync(configPath, JSON.stringify(connectors, null, 2));
}

// Run custom script (e.g., ChatGPT export)
function runCustomScript(connectorId: string, config: Record<string, any>): void {
  const status: RunStatus = { running: true, output: [], connectorId };
  runStatuses.set(connectorId, status);

  // Determine which script to run
  const scriptName = config.script || 'chatgpt-export';

  if (scriptName === 'chatgpt-export') {
    runChatGPTExport(connectorId, config);
  } else if (scriptName === 'notion') {
    runNotionSync(connectorId, config);
  } else if (scriptName === 'readwise') {
    runReadwiseSync(connectorId, config);
  } else if (scriptName === 'facebook-import') {
    // Facebook is handled via upload, not script run
    status.running = false;
    status.output.push('Facebook connector uses file upload. Please upload your Facebook data export ZIP.');
    status.exitCode = 0;
  } else {
    status.running = false;
    status.output.push(`Unknown script: ${scriptName}`);
    status.exitCode = 1;
  }
}

// ChatGPT export via Playwright is deprecated — redirect to browser connector
function runChatGPTExport(connectorId: string, _config: Record<string, any>): void {
  const status = runStatuses.get(connectorId);
  if (!status) return;

  status.running = false;
  status.exitCode = 1;
  status.output.push(
    '[DEPRECATED] The Playwright-based ChatGPT exporter has been deprecated.',
    'Please use the Browser Connector instead:',
    '  1. Go to the ChatGPT connector in the frontend',
    '  2. Use "Launch VNC Login" for first-time authentication',
    '  3. After logging in, use "Sync Now" or enable auto-sync',
    'The browser connector uses ChatGPT\'s internal API and is more reliable.',
    'See POST /api/browser-connector/launch for programmatic access.'
  );
}

// Generic script runner for token-based connectors
function runTokenBasedExport(
  connectorId: string,
  scriptName: string,
  envVars: Record<string, string>
): void {
  const status = runStatuses.get(connectorId);
  if (!status) return;

  const scriptPath = path.join(__dirname, 'scripts', `export-${scriptName}.ts`);
  const proc = spawn('npx', ['tsx', scriptPath], {
    cwd: ROOT_DIR,
    env: {
      ...process.env,
      ...envVars,
      EXPORTS_DIR: path.join(EXPORTS_DIR, connectorId),
    },
  });

  currentProcesses.set(connectorId, proc);

  proc.stdout?.on('data', (data) => {
    const lines = data.toString().split('\n').filter(Boolean);
    status.output.push(...lines);
    if (status.output.length > 500) {
      status.output = status.output.slice(-500);
    }
  });

  proc.stderr?.on('data', (data) => {
    const lines = data.toString().split('\n').filter(Boolean);
    status.output.push(...lines);
  });

  proc.on('close', async (code) => {
    status.running = false;
    status.exitCode = code ?? undefined;
    status.lastRun = new Date().toISOString();
    currentProcesses.delete(connectorId);

    // Update connector
    const connectors = loadConnectors();
    const connector = connectors.find(c => c.id === connectorId);
    if (connector) {
      connector.status = code === 0 ? 'connected' : 'error';
      connector.lastSync = status.lastRun;
      connector.itemCount = countExportedItems(connectorId);
      saveConnectors(connectors);
    }

    // Auto-index to vector store on successful sync
    if (code === 0) {
      await autoIndexConnectorExports(connectorId);
    }
  });
}

// Run Notion sync in-process (replaces child process approach)
/**
 * Generic in-process sync runner. Eliminates duplication between Notion/Readwise sync handlers.
 * Handles: abort controller, progress logging, connector state updates, error handling.
 */
function runInProcessSync(
  connectorId: string,
  config: Record<string, any>,
  label: string,
  syncFn: (
    connectorId: string,
    config: Record<string, any>,
    cursor: { lastSyncAt: string } | null,
    onProgress: (progress: any) => void,
    signal: AbortSignal
  ) => Promise<{ success: boolean; errors: string[]; cursor: { lastSyncAt: string }; [key: string]: any }>,
  formatProgress: (progress: any) => string,
  formatResult: (result: any) => { message: string; itemCount: number }
): void {
  const status = runStatuses.get(connectorId);
  if (!status) return;

  const connectors = loadConnectors();
  const connector = connectors.find(c => c.id === connectorId);
  const cursor = connector?.syncCursor ? { lastSyncAt: connector.syncCursor.lastSyncAt } : null;

  status.output.push(`[${label}] Starting ${cursor ? 'incremental' : 'full'} sync...`);

  const abortController = new AbortController();
  const fakeProc = { kill: () => abortController.abort() } as any;
  currentProcesses.set(connectorId, fakeProc);

  syncFn(
    connectorId,
    config,
    cursor,
    (progress) => {
      const msg = `[${label}] ${formatProgress(progress)}`;
      status.output.push(msg);
      if (status.output.length > 500) {
        status.output = status.output.slice(-500);
      }
    },
    abortController.signal
  ).then((result) => {
    status.running = false;
    status.exitCode = result.success ? 0 : 1;
    status.lastRun = new Date().toISOString();
    currentProcesses.delete(connectorId);

    const { message, itemCount } = formatResult(result);
    status.output.push(`[${label}] ${message}`);

    const connectors = loadConnectors();
    const connector = connectors.find(c => c.id === connectorId);
    if (connector) {
      connector.status = result.success ? 'connected' : 'error';
      connector.lastSync = status.lastRun;
      connector.itemCount = itemCount;
      connector.syncCursor = result.cursor;
      saveConnectors(connectors);
    }
  }).catch((error) => {
    status.running = false;
    status.exitCode = 1;
    status.lastRun = new Date().toISOString();
    currentProcesses.delete(connectorId);
    status.output.push(`[${label}] Sync failed: ${error.message}`);

    const connectors = loadConnectors();
    const connector = connectors.find(c => c.id === connectorId);
    if (connector) {
      connector.status = 'error';
      connector.lastSync = status.lastRun;
      saveConnectors(connectors);
    }
  });
}

function runNotionSync(connectorId: string, config: Record<string, any>): void {
  runInProcessSync(
    connectorId, config, 'notion',
    syncNotion,
    (p) => `${p.phase}: pages ${p.pagesProcessed}/${p.pagesFound}, databases ${p.databasesProcessed}/${p.databasesFound}`,
    (r) => ({
      message: `Sync complete: ${r.pagesIndexed + r.pagesUpdated + r.databaseEntriesIndexed} indexed, ${r.duplicatesSkipped} duplicates, ${r.errors.length} errors`,
      itemCount: r.pagesIndexed + r.pagesUpdated + r.databaseEntriesIndexed + r.duplicatesSkipped,
    })
  );
}

function runReadwiseSync(connectorId: string, config: Record<string, any>): void {
  runInProcessSync(
    connectorId, config, 'readwise',
    syncReadwise,
    (p) => `${p.phase}: documents ${p.documentsProcessed}/${p.documentsFetched}, highlights ${p.highlightsProcessed}`,
    (r) => ({
      message: `Sync complete: ${r.documentsIndexed} documents, ${r.highlightsIndexed} highlights, ${r.duplicatesSkipped} duplicates, ${r.errors.length} errors`,
      itemCount: r.documentsIndexed + r.duplicatesSkipped,
    })
  );
}

// Auto-index connector exports to vector store after sync
async function autoIndexConnectorExports(connectorId: string): Promise<void> {
  try {
    const available = await isVectorStoreAvailable();
    if (!available) {
      console.log(`[autoIndex] Vector store not available, skipping auto-index for ${connectorId}`);
      return;
    }

    const exportDir = path.join(EXPORTS_DIR, connectorId);
    if (!fs.existsSync(exportDir)) {
      return;
    }

    const files = fs.readdirSync(exportDir).filter(f => f.endsWith('.json') && !f.startsWith('.'));
    const client = getVectorStoreClient();
    let totalIndexed = 0;
    let duplicatesSkipped = 0;

    for (const file of files) {
      try {
        const filePath = path.join(exportDir, file);
        const content = JSON.parse(fs.readFileSync(filePath, 'utf-8'));

        // Handle ChatGPT format
        if (content.messages && Array.isArray(content.messages)) {
          const documents = content.messages
            .filter((msg: any) => msg.content && typeof msg.content === 'string')
            .map((msg: any) => ({
              text: msg.content,
              metadata: {
                source: 'chatgpt',
                connectorId,
                conversationId: content.id || file.replace('.json', ''),
                conversationTitle: content.title || 'Untitled',
                role: msg.role || 'unknown',
                timestamp: msg.create_time || msg.timestamp,
                exportFile: file,
              },
            }));

          if (documents.length > 0) {
            const result = await client.addDocuments(documents);
            totalIndexed += result.document_ids.length;
            duplicatesSkipped += result.duplicates_skipped;
          }
        }
        // Handle Notion page format
        else if (content.type === 'page' && content.content) {
          const text = `# ${content.title || 'Untitled'}\n\n${content.content}`;
          const result = await client.addDocument(text, {
            source: 'notion',
            connectorId,
            notionId: content.id,
            title: content.title,
            url: content.url,
            parentType: content.parentType,
            createdAt: content.createdAt,
            updatedAt: content.updatedAt,
            exportFile: file,
          });
          if (result.is_duplicate) duplicatesSkipped++;
          else totalIndexed++;
        }
        // Handle Notion database format
        else if (content.type === 'database' && content.entries) {
          for (const entry of content.entries) {
            const propsText = Object.entries(entry.properties || {})
              .map(([key, value]) => `${key}: ${value}`)
              .join('\n');
            const text = `# ${entry.title || 'Untitled'}\n\nDatabase: ${content.title}\n\n${propsText}`;
            const result = await client.addDocument(text, {
              source: 'notion',
              connectorId,
              notionId: entry.id,
              databaseId: content.id,
              databaseTitle: content.title,
              title: entry.title,
              url: entry.url,
              exportFile: file,
            });
            if (result.is_duplicate) duplicatesSkipped++;
            else totalIndexed++;
          }
        }
        // Handle Facebook post format
        else if (content.type === 'post' && content.content !== undefined) {
          const text = `${content.title ? `${content.title}\n\n` : ''}${content.content}${content.attachments?.length ? '\n\n' + content.attachments.join('\n') : ''}`.trim();
          if (text.length > 10) {
            const result = await client.addDocument(text, {
              source: 'facebook',
              connectorId,
              type: 'post',
              timestamp: content.timestamp,
              date: content.date,
              tags: content.tags?.join(', '),
              exportFile: file,
            });
            if (result.is_duplicate) duplicatesSkipped++;
            else totalIndexed++;
          }
        }
        // Handle Facebook comment format
        else if (content.type === 'comment' && content.content) {
          const text = `${content.title ? `Comment on: ${content.title}\n\n` : ''}${content.content}`.trim();
          if (text.length > 5) {
            const result = await client.addDocument(text, {
              source: 'facebook',
              connectorId,
              type: 'comment',
              timestamp: content.timestamp,
              date: content.date,
              exportFile: file,
            });
            if (result.is_duplicate) duplicatesSkipped++;
            else totalIndexed++;
          }
        }
        // Handle Facebook message thread format
        else if (content.type === 'message_thread' && content.messages) {
          // Index each message separately for better search granularity
          for (const msg of content.messages) {
            if (!msg.content || msg.content.length < 5) continue;
            const text = `[${msg.sender}]: ${msg.content}`;
            const result = await client.addDocument(text, {
              source: 'facebook',
              connectorId,
              type: 'message',
              threadTitle: content.title,
              participants: content.participants,
              sender: msg.sender,
              timestamp: msg.timestamp,
              date: msg.date,
              exportFile: file,
            });
            if (result.is_duplicate) duplicatesSkipped++;
            else totalIndexed++;
          }
        }
        // Handle Facebook generic data format
        else if (content.type === 'facebook_data' && content.data) {
          // Extract searchable text from Facebook data structures
          const textParts: string[] = [];
          const extractText = (obj: any, depth = 0): void => {
            if (depth > 5) return;
            if (typeof obj === 'string' && obj.length > 3) {
              textParts.push(obj);
            } else if (Array.isArray(obj)) {
              obj.forEach(item => extractText(item, depth + 1));
            } else if (obj && typeof obj === 'object') {
              // Look for common text fields
              for (const key of ['name', 'title', 'text', 'value', 'data', 'search_query', 'interest']) {
                if (obj[key]) extractText(obj[key], depth + 1);
              }
            }
          };
          extractText(content.data);

          if (textParts.length > 0) {
            const text = `Facebook ${content.category}:\n${textParts.slice(0, 100).join('\n')}`;
            const result = await client.addDocument(text, {
              source: 'facebook',
              connectorId,
              type: 'data',
              category: content.category,
              exportFile: file,
            });
            if (result.is_duplicate) duplicatesSkipped++;
            else totalIndexed++;
          }
        }
        // Handle generic object with text/content field
        else if (content.text || content.content) {
          const text = content.text || content.content;
          const result = await client.addDocument(text, {
            source: 'export',
            connectorId,
            title: content.title || content.name,
            exportFile: file,
          });
          if (result.is_duplicate) duplicatesSkipped++;
          else totalIndexed++;
        }
      } catch (fileError) {
        console.error(`[autoIndex] Error indexing ${file}:`, fileError);
      }
    }

    console.log(`[autoIndex] Connector ${connectorId}: indexed ${totalIndexed}, skipped ${duplicatesSkipped} duplicates`);
  } catch (error) {
    console.error(`[autoIndex] Error auto-indexing connector ${connectorId}:`, error);
  }
}

// Count exported items for a connector
function countExportedItems(connectorId: string): number {
  const exportDir = path.join(EXPORTS_DIR, connectorId);
  if (!fs.existsSync(exportDir)) return 0;

  const files = fs.readdirSync(exportDir).filter(f => f.endsWith('.json') && !f.startsWith('.'));
  let totalItems = 0;

  files.forEach(file => {
    try {
      const content = JSON.parse(fs.readFileSync(path.join(exportDir, file), 'utf-8'));
      // ChatGPT: count messages
      if (content.messages && Array.isArray(content.messages)) {
        totalItems += content.messages.length;
      }
      // Notion database: count entries
      else if (content.type === 'database' && content.entries) {
        totalItems += content.entries.length;
      }
      // Facebook message thread: count individual messages
      else if (content.type === 'message_thread' && content.messages) {
        totalItems += content.messages.length;
      }
      // Facebook post/comment: count as 1
      else if (content.type === 'post' || content.type === 'comment') {
        totalItems += 1;
      }
      // Facebook data: count as 1
      else if (content.type === 'facebook_data') {
        totalItems += 1;
      }
      // Generic: count as 1 item per file
      else {
        totalItems += 1;
      }
    } catch (e) {
      // Skip invalid files
    }
  });

  return totalItems;
}

// API Routes

// Get all connectors
app.get('/api/connectors', (_req, res) => {
  const connectors = loadConnectors();
  res.json(connectors);
});

// Add connector
app.post('/api/connectors', (req, res) => {
  const { name, type, config } = req.body;

  // Validate required fields
  if (!name || typeof name !== 'string' || name.trim().length === 0) {
    return res.status(400).json({ error: 'Missing or invalid "name" field' });
  }
  const validTypes = ['api', 'webhook', 'file', 'custom'];
  if (!type || !validTypes.includes(type)) {
    return res.status(400).json({ error: `Invalid "type". Must be one of: ${validTypes.join(', ')}` });
  }
  if (config !== undefined && (typeof config !== 'object' || Array.isArray(config))) {
    return res.status(400).json({ error: '"config" must be an object' });
  }

  const connectors = loadConnectors();
  const newConnector: ConnectorConfig = {
    id: randomUUID(),
    name: name.trim(),
    type,
    config: config || {},
    status: 'connected',
    itemCount: 0,
  };
  connectors.push(newConnector);
  saveConnectors(connectors);
  res.json(newConnector);
});

// Update connector (allowlisted fields only to prevent mass assignment)
app.put('/api/connectors/:id', (req, res) => {
  const connectors = loadConnectors();
  const index = connectors.findIndex(c => c.id === req.params.id);
  if (index === -1) {
    return res.status(404).json({ error: 'Connector not found' });
  }
  const allowedFields = ['name', 'config', 'autoSyncEnabled', 'autoSyncIntervalHours'];
  for (const field of allowedFields) {
    if (req.body[field] !== undefined) {
      (connectors[index] as any)[field] = req.body[field];
    }
  }
  saveConnectors(connectors);
  res.json(connectors[index]);
});

// Delete connector (with cleanup)
app.delete('/api/connectors/:id', (req, res) => {
  const connectorId = req.params.id;

  // Stop running sync if any
  const proc = currentProcesses.get(connectorId);
  if (proc) {
    proc.kill();
    currentProcesses.delete(connectorId);
  }
  runStatuses.delete(connectorId);

  // Unschedule auto-sync
  connectorScheduler.unschedule(connectorId);

  const connectors = loadConnectors();
  const filtered = connectors.filter(c => c.id !== connectorId);
  saveConnectors(filtered);
  res.json({ success: true });
});

// Sync connector
app.post('/api/connectors/:id/sync', (req, res) => {
  const connectors = loadConnectors();
  const connector = connectors.find(c => c.id === req.params.id);
  
  if (!connector) {
    return res.status(404).json({ error: 'Connector not found' });
  }

  if (connector.type === 'custom') {
    if (runStatuses.get(connector.id)?.running) {
      return res.status(400).json({ error: 'Script already running' });
    }
    // Set status before starting async sync to avoid race
    connector.status = 'syncing';
    saveConnectors(connectors);
    runCustomScript(connector.id, connector.config);
  } else {
    // Other connector types would be handled here
    return res.status(400).json({ error: 'Sync not supported for this connector type' });
  }

  res.json({ success: true });
});

// Get sync status
app.get('/api/connectors/:id/status', (req, res) => {
  const status = runStatuses.get(req.params.id);
  res.json(status || { running: false, output: [] });
});

// Stop sync
app.post('/api/connectors/:id/stop', (req, res) => {
  const connectorId = req.params.id;
  const proc = currentProcesses.get(connectorId);
  if (proc) {
    proc.kill();
    currentProcesses.delete(connectorId);
    const status = runStatuses.get(connectorId);
    if (status) {
      status.running = false;
      status.output.push('[Stopped by user]');
    }
    // Update connector status so it doesn't stay stuck on 'syncing'
    const connectors = loadConnectors();
    const connector = connectors.find(c => c.id === connectorId);
    if (connector && connector.status === 'syncing') {
      connector.status = 'connected';
      saveConnectors(connectors);
    }
    return res.json({ success: true, stopped: true });
  }
  res.json({ success: true, stopped: false });
});

// Test connector connectivity
app.post('/api/connectors/:id/test', async (req, res) => {
  try {
    const connectors = loadConnectors();
    const connector = connectors.find(c => c.id === req.params.id);

    if (!connector) {
      return res.status(404).json({ error: 'Connector not found' });
    }

    const config = connector.config as Record<string, any>;
    const script = config?.script || '';

    if (script === 'notion') {
      const result = await testNotionConnection(config.token || '');
      return res.json(result);
    }

    if (script === 'readwise') {
      const result = await testReadwiseConnection(config.token || '');
      return res.json(result);
    }

    return res.status(400).json({ error: 'Test not supported for this connector type' });
  } catch (error: any) {
    console.error('[test] Connection test failed:', error.message);
    return res.status(500).json({ ok: false, error: `Test failed: ${error.message}` });
  }
});

// Force full re-sync (clears cursor)
app.post('/api/connectors/:id/full-sync', (req, res) => {
  const connectors = loadConnectors();
  const connector = connectors.find(c => c.id === req.params.id);

  if (!connector) {
    return res.status(404).json({ error: 'Connector not found' });
  }

  if (runStatuses.get(connector.id)?.running) {
    return res.status(400).json({ error: 'Sync already running' });
  }

  // Clear cursor and set syncing status in one save
  connector.syncCursor = undefined;
  connector.status = 'syncing';
  saveConnectors(connectors);

  if (connector.type === 'custom') {
    runCustomScript(connector.id, connector.config);
    return res.json({ success: true, message: 'Full re-sync started (cursor cleared)' });
  }

  return res.status(400).json({ error: 'Sync not supported for this connector type' });
});

// Enable/disable auto-sync schedule for a connector
app.put('/api/connectors/:id/schedule', (req, res) => {
  const { enabled, intervalHours } = req.body;

  if (typeof enabled !== 'boolean') {
    return res.status(400).json({ error: 'Missing "enabled" boolean field' });
  }

  if (enabled) {
    const hours = intervalHours && Number.isFinite(intervalHours) && intervalHours >= 1 && intervalHours <= 168
      ? intervalHours
      : undefined;
    const result = connectorScheduler.enable(req.params.id, hours);
    return res.json(result);
  } else {
    const result = connectorScheduler.disable(req.params.id);
    return res.json(result);
  }
});

// Get unified scheduler status
app.get('/api/scheduler/status', (_req, res) => {
  res.json(connectorScheduler.getStatus());
});

// Connector-scoped search — search only within a specific connector's data
app.get('/api/connectors/:id/search', async (req, res) => {
  const connectors = loadConnectors();
  const connector = connectors.find(c => c.id === req.params.id);

  if (!connector) {
    return res.status(404).json({ error: 'Connector not found' });
  }

  const query = req.query.q as string;
  if (!query || typeof query !== 'string') {
    return res.status(400).json({ error: 'Query parameter "q" is required' });
  }

  try {
    const available = await isVectorStoreAvailable();
    if (!available) {
      return res.status(503).json({ error: 'Vector store not available' });
    }

    const client = getVectorStoreClient();
    const rawTopK = parseInt(req.query.top_k as string || '', 10);
    const topK = Math.min(Math.max(isNaN(rawTopK) ? 10 : rawTopK, 1), 100);

    // Determine the source name for this connector
    const config = connector.config as Record<string, any>;
    const script = config?.script || connector.type;
    const sourceMap: Record<string, string> = {
      notion: 'notion',
      readwise: 'readwise',
      'facebook-import': 'facebook',
      'chatgpt-export': 'browser-connector',
    };
    const source = sourceMap[script] || script;

    // Semantic search, then filter to this specific connector (AND, not OR)
    const semanticResults = await client.search(query, topK * 3);
    const filtered = semanticResults.filter(r =>
      r.metadata?.connectorId === connector.id ||
      (r.metadata?.source === source && !r.metadata?.connectorId)
    ).slice(0, topK);

    res.json({
      connectorId: connector.id,
      connectorName: connector.name,
      source,
      query,
      results: filtered,
    });
  } catch (error: any) {
    console.error(`[search] Connector search failed:`, error.message);
    res.status(500).json({ error: 'Search failed' });
  }
});

// Upload file for manual connector (e.g., ChatGPT export ZIP)
app.post('/api/connectors/:id/upload', upload.single('file'), async (req, res) => {
  try {
    const connectorId = req.params.id;
    const connectors = loadConnectors();
    const connector = connectors.find(c => c.id === connectorId);

    if (!connector) {
      return res.status(404).json({ error: 'Connector not found' });
    }

    if (!req.file) {
      return res.status(400).json({ error: 'No file uploaded' });
    }

    const config = connector.config as Record<string, any>;
    const script = config?.script || '';

    // Process based on connector type
    if (script === 'chatgpt-import') {
      const result = await processChatGPTExport(connectorId, req.file.path);

      // Update connector
      connector.status = 'connected';
      connector.lastSync = new Date().toISOString();
      connector.itemCount = result.itemCount;
      saveConnectors(connectors);

      // Auto-index to vector store
      await autoIndexConnectorExports(connectorId);

      // Clean up uploaded file
      fs.unlinkSync(req.file.path);

      res.json({
        success: true,
        itemCount: result.itemCount,
        message: `Imported ${result.conversationCount} conversations with ${result.itemCount} messages`,
      });
    } else if (script === 'facebook-import') {
      const result = await processFacebookExportExtracted(connectorId, req.file.path, EXPORTS_DIR);

      // Update connector
      connector.status = 'connected';
      connector.lastSync = new Date().toISOString();
      connector.itemCount = result.postCount + result.commentCount + result.messageCount;
      saveConnectors(connectors);

      // Auto-index to vector store
      await autoIndexConnectorExports(connectorId);

      // Clean up uploaded file
      fs.unlinkSync(req.file.path);

      res.json({
        success: true,
        itemCount: connector.itemCount,
        pendingMedia: result.mediaCount,
        message: `Imported ${result.postCount} posts, ${result.commentCount} comments, ${result.messageCount} messages. ${result.mediaCount} media files stored for future indexing.`,
      });
    } else {
      // Generic file handling for other connectors
      const exportDir = path.join(EXPORTS_DIR, connectorId);
      if (!fs.existsSync(exportDir)) {
        fs.mkdirSync(exportDir, { recursive: true });
      }

      // Sanitize filename to prevent path traversal
      const safeFilename = path.basename(req.file.originalname || `upload-${Date.now()}`);
      const destPath = path.join(exportDir, safeFilename);
      fs.renameSync(req.file.path, destPath);

      connector.status = 'connected';
      connector.lastSync = new Date().toISOString();
      connector.itemCount = countExportedItems(connectorId);
      saveConnectors(connectors);

      res.json({
        success: true,
        itemCount: connector.itemCount,
        message: 'File imported successfully',
      });
    }
  } catch (error) {
    console.error('Upload error:', error);
    res.status(500).json({ error: 'Upload processing failed' });
  }
});

// Process ChatGPT export ZIP file
async function processChatGPTExport(connectorId: string, zipPath: string): Promise<{ conversationCount: number; itemCount: number }> {
  const AdmZip = (await import('adm-zip')).default;
  const zip = new AdmZip(zipPath);
  const zipEntries = zip.getEntries();

  const exportDir = path.join(EXPORTS_DIR, connectorId);
  if (!fs.existsSync(exportDir)) {
    fs.mkdirSync(exportDir, { recursive: true });
  }

  let conversationCount = 0;
  let itemCount = 0;

  // Find conversations.json in the ZIP
  const conversationsEntry = zipEntries.find(e => e.entryName === 'conversations.json' || e.entryName.endsWith('/conversations.json'));

  if (conversationsEntry) {
    const content = conversationsEntry.getData().toString('utf-8');
    const conversations = JSON.parse(content);

    if (Array.isArray(conversations)) {
      for (const conv of conversations) {
        conversationCount++;

        // Extract messages from the conversation mapping
        const messages: any[] = [];
        if (conv.mapping) {
          for (const nodeId of Object.keys(conv.mapping)) {
            const node = conv.mapping[nodeId];
            if (node.message && node.message.content && node.message.content.parts) {
              const role = node.message.author?.role || 'unknown';
              const content = node.message.content.parts.join('\n');
              const createTime = node.message.create_time;

              if (content && content.trim()) {
                messages.push({
                  role,
                  content: content.trim(),
                  create_time: createTime,
                });
                itemCount++;
              }
            }
          }
        }

        // Sort messages by create_time
        messages.sort((a, b) => (a.create_time || 0) - (b.create_time || 0));

        // Save each conversation as a separate file
        const convData = {
          id: conv.id,
          title: conv.title || 'Untitled',
          create_time: conv.create_time,
          update_time: conv.update_time,
          messages,
        };

        const safeTitle = (conv.title || 'untitled').replace(/[^a-z0-9]/gi, '_').substring(0, 40);
        const filename = `chatgpt_${conv.id?.substring(0, 8) || conversationCount}_${safeTitle}.json`;
        fs.writeFileSync(path.join(exportDir, filename), JSON.stringify(convData, null, 2));
      }
    }
  }

  // Also extract any other useful files
  for (const entry of zipEntries) {
    if (entry.entryName === 'user.json' || entry.entryName.endsWith('/user.json')) {
      const content = entry.getData().toString('utf-8');
      fs.writeFileSync(path.join(exportDir, 'user_profile.json'), content);
    }
    if (entry.entryName === 'model_comparisons.json' || entry.entryName.endsWith('/model_comparisons.json')) {
      const content = entry.getData().toString('utf-8');
      fs.writeFileSync(path.join(exportDir, 'model_comparisons.json'), content);
    }
  }

  return { conversationCount, itemCount };
}

// Facebook encoding fix (they use Latin-1 for Unicode)
function fixFacebookEncoding(text: string): string {
  try {
    return text.replace(/\\u00([0-9a-fA-F]{2})/g, (_, hex) => {
      return String.fromCharCode(parseInt(hex, 16));
    });
  } catch {
    return text;
  }
}

function fixEncodingDeep(obj: any): any {
  if (typeof obj === 'string') {
    return fixFacebookEncoding(obj);
  }
  if (Array.isArray(obj)) {
    return obj.map(fixEncodingDeep);
  }
  if (obj && typeof obj === 'object') {
    const fixed: any = {};
    for (const key of Object.keys(obj)) {
      fixed[key] = fixEncodingDeep(obj[key]);
    }
    return fixed;
  }
  return obj;
}

// Supported media extensions for pending storage
const PENDING_MEDIA_EXTENSIONS = new Set([
  '.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.heic', '.heif',
  '.mp4', '.mov', '.avi', '.mkv', '.webm', '.m4v',
  '.mp3', '.m4a', '.wav', '.aac', '.ogg', '.flac',
]);

interface PendingMediaFile {
  originalPath: string;
  filename: string;
  type: 'photo' | 'video' | 'audio';
  extension: string;
  size: number;
  context?: {
    source: string;
    timestamp?: number;
    description?: string;
  };
  storedAt: string;
  storedPath: string;
}

interface PendingMediaRegistry {
  files: PendingMediaFile[];
  lastUpdated: string;
  totalSize: number;
  counts: { photos: number; videos: number; audio: number };
}

function getMediaType(ext: string): 'photo' | 'video' | 'audio' {
  const photos = ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.heic', '.heif'];
  const videos = ['.mp4', '.mov', '.avi', '.mkv', '.webm', '.m4v'];
  if (photos.includes(ext)) return 'photo';
  if (videos.includes(ext)) return 'video';
  return 'audio';
}

// Process Facebook export ZIP file
async function processFacebookExport(connectorId: string, zipPath: string): Promise<{
  postCount: number;
  commentCount: number;
  messageCount: number;
  mediaCount: number;
}> {
  const AdmZip = (await import('adm-zip')).default;
  const zip = new AdmZip(zipPath);
  const zipEntries = zip.getEntries();

  const exportDir = path.join(EXPORTS_DIR, connectorId);
  if (!fs.existsSync(exportDir)) {
    fs.mkdirSync(exportDir, { recursive: true });
  }

  const pendingMediaDir = path.join(exportDir, 'pending-media');
  if (!fs.existsSync(pendingMediaDir)) {
    fs.mkdirSync(pendingMediaDir, { recursive: true });
  }

  let postCount = 0;
  let commentCount = 0;
  let messageCount = 0;
  let mediaCount = 0;

  // Load pending media registry
  const registryPath = path.join(pendingMediaDir, '.registry.json');
  let pendingRegistry: PendingMediaRegistry = {
    files: [],
    lastUpdated: '',
    totalSize: 0,
    counts: { photos: 0, videos: 0, audio: 0 },
  };
  if (fs.existsSync(registryPath)) {
    pendingRegistry = JSON.parse(fs.readFileSync(registryPath, 'utf-8'));
  }

  console.log(`[processFacebookExport] Found ${zipEntries.length} entries in ZIP`);

  for (const entry of zipEntries) {
    if (entry.isDirectory) continue;

    const entryName = entry.entryName.toLowerCase();
    const ext = path.extname(entryName).toLowerCase();

    // Handle media files - store for future indexing
    if (PENDING_MEDIA_EXTENSIONS.has(ext)) {
      try {
        const mediaType = getMediaType(ext);
        const filename = `${Date.now()}_${path.basename(entry.entryName)}`;
        const storedPath = path.join(pendingMediaDir, filename);

        // Extract file
        fs.writeFileSync(storedPath, entry.getData());

        let source = 'unknown';
        if (entryName.includes('messages/')) source = 'messages';
        else if (entryName.includes('posts/')) source = 'posts';
        else if (entryName.includes('photos_and_videos/')) source = 'photos_and_videos';
        else if (entryName.includes('profile/')) source = 'profile';

        const size = entry.header.size;
        pendingRegistry.files.push({
          originalPath: entry.entryName,
          filename,
          type: mediaType,
          extension: ext,
          size,
          context: { source },
          storedAt: new Date().toISOString(),
          storedPath,
        });
        pendingRegistry.totalSize += size;
        pendingRegistry.counts[mediaType === 'photo' ? 'photos' : mediaType === 'video' ? 'videos' : 'audio']++;
        mediaCount++;
      } catch (error) {
        console.error(`[processFacebookExport] Error storing media ${entry.entryName}:`, error);
      }
      continue;
    }

    if (!entryName.endsWith('.json')) continue;

    try {
      const content = entry.getData().toString('utf-8');
      const data = fixEncodingDeep(JSON.parse(content));

      // Process posts (posts/your_posts_1.json, etc.)
      if (entryName.includes('posts/') && Array.isArray(data)) {
        for (const post of data) {
          if (!post.timestamp) continue;

          let postText = '';
          if (post.data && Array.isArray(post.data)) {
            postText = post.data.map((d: any) => d.post || '').filter(Boolean).join('\n');
          }

          const attachmentTexts: string[] = [];
          if (post.attachments) {
            for (const att of post.attachments) {
              if (att.data && Array.isArray(att.data)) {
                for (const d of att.data) {
                  if (d.text) attachmentTexts.push(d.text);
                  if (d.external_context?.name) attachmentTexts.push(d.external_context.name);
                  if (d.media?.description) attachmentTexts.push(d.media.description);
                }
              }
            }
          }

          if (postText || attachmentTexts.length > 0) {
            const exportedPost = {
              type: 'post',
              timestamp: post.timestamp,
              date: new Date(post.timestamp * 1000).toISOString(),
              title: post.title,
              content: postText,
              attachments: attachmentTexts.length > 0 ? attachmentTexts : undefined,
              tags: post.tags?.map((t: any) => t.name),
              exportedAt: new Date().toISOString(),
            };

            const filename = `facebook_post_${post.timestamp}.json`;
            fs.writeFileSync(path.join(exportDir, filename), JSON.stringify(exportedPost, null, 2));
            postCount++;
          }
        }
      }

      // Process comments
      else if (entryName.includes('comments/')) {
        const comments = data.comments || (Array.isArray(data) ? data : []);
        for (const comment of comments) {
          const timestamp = comment.timestamp || comment.data?.[0]?.comment?.timestamp;
          if (!timestamp) continue;

          let commentText = '';
          if (comment.data && Array.isArray(comment.data)) {
            commentText = comment.data
              .map((d: any) => d.comment?.comment || d.comment || '')
              .filter(Boolean)
              .join('\n');
          } else if (typeof comment.comment === 'string') {
            commentText = comment.comment;
          }

          if (commentText) {
            const exportedComment = {
              type: 'comment',
              timestamp,
              date: new Date(timestamp * 1000).toISOString(),
              title: comment.title,
              content: commentText,
              exportedAt: new Date().toISOString(),
            };

            const filename = `facebook_comment_${timestamp}.json`;
            fs.writeFileSync(path.join(exportDir, filename), JSON.stringify(exportedComment, null, 2));
            commentCount++;
          }
        }
      }

      // Process messages (messages/inbox/{person}/message_1.json)
      else if (entryName.includes('messages/') && (entryName.includes('message_') || entryName.endsWith('message_1.json'))) {
        if (!data.messages || !Array.isArray(data.messages)) continue;

        const participants = data.participants?.map((p: any) => p.name).join(', ') || 'Unknown';
        const threadMessages = data.messages
          .filter((msg: any) => msg.content || msg.share)
          .map((msg: any) => ({
            sender: msg.sender_name,
            timestamp: msg.timestamp_ms,
            date: new Date(msg.timestamp_ms).toISOString(),
            content: msg.content || msg.share?.share_text || msg.share?.link || '',
            type: msg.type,
            hasMedia: !!(msg.photos?.length || msg.videos?.length || msg.audio_files?.length),
          }));

        if (threadMessages.length > 0) {
          const exportedThread = {
            type: 'message_thread',
            title: data.title || `Chat with ${participants}`,
            participants,
            messageCount: threadMessages.length,
            messages: threadMessages,
            firstMessage: threadMessages[threadMessages.length - 1]?.date,
            lastMessage: threadMessages[0]?.date,
            exportedAt: new Date().toISOString(),
          };

          const safeThreadName = (data.title || participants)
            .replace(/[^a-z0-9]/gi, '_')
            .substring(0, 40);
          const filename = `facebook_messages_${safeThreadName}_${Date.now()}.json`;
          fs.writeFileSync(path.join(exportDir, filename), JSON.stringify(exportedThread, null, 2));
          messageCount += threadMessages.length;
        }
      }

      // Process other interesting data
      else {
        const baseName = path.basename(entry.entryName, '.json').toLowerCase();
        const interestingPatterns = [
          'search_history', 'ads_interests', 'profile_information',
          'pages_you', 'posts_you', 'saved_items', 'your_places',
        ];

        if (interestingPatterns.some(p => baseName.includes(p))) {
          const exported = {
            type: 'facebook_data',
            category: baseName,
            data,
            exportedAt: new Date().toISOString(),
          };

          const filename = `facebook_data_${baseName}.json`;
          fs.writeFileSync(path.join(exportDir, filename), JSON.stringify(exported, null, 2));
        }
      }
    } catch (error) {
      console.error(`[processFacebookExport] Error processing ${entry.entryName}:`, error);
    }
  }

  // Save pending media registry
  pendingRegistry.lastUpdated = new Date().toISOString();
  fs.writeFileSync(registryPath, JSON.stringify(pendingRegistry, null, 2));

  console.log(`[processFacebookExport] Complete: ${postCount} posts, ${commentCount} comments, ${messageCount} messages, ${mediaCount} media stored`);
  return { postCount, commentCount, messageCount, mediaCount };
}

// Get exports for a connector
app.get('/api/connectors/:id/exports', (req, res) => {
  const exportDir = path.join(EXPORTS_DIR, req.params.id);
  // Prevent path traversal via connector ID
  const resolvedExportDir = path.resolve(exportDir);
  if (!resolvedExportDir.startsWith(RESOLVED_EXPORTS_DIR)) {
    return res.status(403).json({ error: 'Access denied: invalid path' });
  }
  if (!fs.existsSync(exportDir)) {
    return res.json([]);
  }

  const files = fs.readdirSync(exportDir)
    .filter(f => f.endsWith('.json') && !f.startsWith('.'))
    .map(f => {
      const stat = fs.statSync(path.join(exportDir, f));
      return { name: f, size: stat.size, modified: stat.mtime };
    })
    .sort((a, b) => b.modified.getTime() - a.modified.getTime());

  res.json(files);
});

// Get export file content
app.get('/api/connectors/:id/exports/:filename', (req, res) => {
  const filePath = path.join(EXPORTS_DIR, req.params.id, req.params.filename);
  // RT-04: Prevent path traversal — ensure resolved path stays within EXPORTS_DIR
  const resolvedPath = path.resolve(filePath);
  if (!resolvedPath.startsWith(RESOLVED_EXPORTS_DIR)) {
    return res.status(403).json({ error: 'Access denied: invalid path' });
  }
  if (!fs.existsSync(filePath)) {
    return res.status(404).json({ error: 'File not found' });
  }
  const content = JSON.parse(fs.readFileSync(filePath, 'utf-8'));
  res.json(content);
});

// Get pending media files for a connector (stored but not yet indexable)
app.get('/api/connectors/:id/pending-media', (req, res) => {
  const pendingDir = path.join(EXPORTS_DIR, req.params.id, 'pending-media');
  // Prevent path traversal via connector ID
  const resolvedPendingDir = path.resolve(pendingDir);
  if (!resolvedPendingDir.startsWith(RESOLVED_EXPORTS_DIR)) {
    return res.status(403).json({ error: 'Access denied: invalid path' });
  }
  const registryPath = path.join(pendingDir, '.registry.json');

  if (!fs.existsSync(registryPath)) {
    return res.json({
      exists: false,
      files: [],
      totalSize: 0,
      counts: { photos: 0, videos: 0, audio: 0 },
      message: 'No pending media files for this connector',
    });
  }

  try {
    const registry = JSON.parse(fs.readFileSync(registryPath, 'utf-8')) as PendingMediaRegistry;
    res.json({
      exists: true,
      lastUpdated: registry.lastUpdated,
      fileCount: registry.files.length,
      totalSize: registry.totalSize,
      totalSizeGB: (registry.totalSize / (1024 * 1024 * 1024)).toFixed(2),
      counts: registry.counts,
      // Return summary, not full file list (can be large)
      recentFiles: registry.files.slice(-20).map(f => ({
        filename: f.filename,
        type: f.type,
        size: f.size,
        source: f.context?.source,
        storedAt: f.storedAt,
      })),
    });
  } catch (error) {
    res.status(500).json({ error: 'Failed to read pending media registry' });
  }
});

// Get all pending media across all connectors
app.get('/api/pending-media', (_req, res) => {
  try {
    const connectorDirs = fs.existsSync(EXPORTS_DIR)
      ? fs.readdirSync(EXPORTS_DIR).filter(d => {
          const stat = fs.statSync(path.join(EXPORTS_DIR, d));
          return stat.isDirectory() && !d.startsWith('.');
        })
      : [];

    const summary: {
      connectorId: string;
      fileCount: number;
      totalSize: number;
      counts: { photos: number; videos: number; audio: number };
    }[] = [];

    let grandTotal = 0;
    let grandCounts = { photos: 0, videos: 0, audio: 0 };

    for (const connectorId of connectorDirs) {
      const registryPath = path.join(EXPORTS_DIR, connectorId, 'pending-media', '.registry.json');
      if (fs.existsSync(registryPath)) {
        try {
          const registry = JSON.parse(fs.readFileSync(registryPath, 'utf-8')) as PendingMediaRegistry;
          summary.push({
            connectorId,
            fileCount: registry.files.length,
            totalSize: registry.totalSize,
            counts: registry.counts,
          });
          grandTotal += registry.totalSize;
          grandCounts.photos += registry.counts.photos;
          grandCounts.videos += registry.counts.videos;
          grandCounts.audio += registry.counts.audio;
        } catch {
          // Skip invalid registries
        }
      }
    }

    res.json({
      connectors: summary,
      totalFileCount: grandCounts.photos + grandCounts.videos + grandCounts.audio,
      totalSize: grandTotal,
      totalSizeGB: (grandTotal / (1024 * 1024 * 1024)).toFixed(2),
      counts: grandCounts,
      supportedWhenAvailable: ['photos (.jpg, .png, etc.)', 'videos (.mp4, .mov, etc.)', 'audio (.mp3, .m4a, etc.)'],
    });
  } catch (error) {
    res.status(500).json({ error: String(error) });
  }
});

// Get storage stats
app.get('/api/stats', (_req, res) => {
  const connectors = loadConnectors();
  const totalItems = connectors.reduce((sum, c) => sum + c.itemCount, 0);
  
  let totalSize = 0;
  if (fs.existsSync(EXPORTS_DIR)) {
    const calculateSize = (dir: string): number => {
      let size = 0;
      const files = fs.readdirSync(dir);
      files.forEach(file => {
        const filePath = path.join(dir, file);
        const stat = fs.statSync(filePath);
        if (stat.isDirectory()) {
          size += calculateSize(filePath);
        } else {
          size += stat.size;
        }
      });
      return size;
    };
    totalSize = calculateSize(EXPORTS_DIR);
  }

  res.json({
    usedGB: totalSize / (1024 * 1024 * 1024),
    totalGB: 64,
    itemCount: totalItems,
    sourcesCount: connectors.length,
  });
});

// Server info
app.get('/api/server-info', (_req, res) => {
  const interfaces = os.networkInterfaces();
  let ipAddress = 'localhost';

  for (const name of Object.keys(interfaces)) {
    const ifaces = interfaces[name];
    if (ifaces) {
      for (const iface of ifaces) {
        if (iface.family === 'IPv4' && !iface.internal) {
          ipAddress = iface.address;
          break;
        }
      }
    }
    if (ipAddress !== 'localhost') break;
  }

  res.json({
    port: PORT,
    ipAddress,
    url: `http://${ipAddress}:${PORT}`,
  });
});

// File Transfer API Routes

// Helper to determine file source
function getFileSource(filename: string): 'localsend' | 'browser' | 'unknown' {
  // LocalSend typically doesn't add metadata we can detect easily
  // For now, files uploaded via browser will have a marker or we check creation method
  // Default to 'unknown' unless we have a way to track
  return 'unknown';
}

// Get received files
app.get('/api/files', (_req, res) => {
  if (!fs.existsSync(UPLOADS_DIR)) {
    return res.json([]);
  }

  try {
    const files = fs.readdirSync(UPLOADS_DIR)
      .filter(f => !f.startsWith('.'))
      .map(f => {
        const filePath = path.join(UPLOADS_DIR, f);
        const stat = fs.statSync(filePath);
        return {
          name: f,
          size: stat.size,
          modified: stat.mtime.toISOString(),
          source: getFileSource(f),
          isDirectory: stat.isDirectory(),
        };
      })
      .filter(f => !f.isDirectory)
      .sort((a, b) => new Date(b.modified).getTime() - new Date(a.modified).getTime());

    res.json(files);
  } catch (error) {
    console.error('Error reading uploads directory:', error);
    res.status(500).json({ error: 'Failed to read uploads directory' });
  }
});

// Upload files via HTTP (auto-imports for indexing)
app.post('/api/files/upload', upload.array('files', 50), (req, res) => {
  try {
    const files = req.files as Express.Multer.File[];

    if (!files || files.length === 0) {
      return res.status(400).json({ error: 'No files uploaded' });
    }

    const uploadedFiles = files.map(file => ({
      name: file.filename,
      size: file.size,
      path: file.path,
    }));

    // Auto-import each file for indexing
    console.log(`HTTP upload: Auto-importing ${files.length} file(s)...`);
    for (const file of files) {
      autoImportFile(file.filename, file.path);
    }

    res.json({
      success: true,
      files: uploadedFiles,
      count: uploadedFiles.length,
      autoImported: true,
    });
  } catch (error) {
    console.error('Upload error:', error);
    res.status(500).json({ error: 'Failed to upload files' });
  }
});

// Delete received file
app.delete('/api/files/:filename', (req, res) => {
  const filePath = path.join(UPLOADS_DIR, req.params.filename);

  // Security check: ensure file is within UPLOADS_DIR
  const resolvedPath = path.resolve(filePath);
  const resolvedDir = path.resolve(UPLOADS_DIR);
  if (!resolvedPath.startsWith(resolvedDir + path.sep) && resolvedPath !== resolvedDir) {
    return res.status(403).json({ error: 'Access denied' });
  }

  if (!fs.existsSync(filePath)) {
    return res.status(404).json({ error: 'File not found' });
  }

  try {
    fs.unlinkSync(filePath);
    res.json({ success: true });
  } catch (error) {
    res.status(500).json({ error: 'Failed to delete file' });
  }
});

// Import file (move to imports directory and queue background indexing)
app.post('/api/files/:filename/import', async (req, res) => {
  const sourcePath = path.join(UPLOADS_DIR, req.params.filename);
  const destPath = path.join(IMPORTS_DIR, req.params.filename);

  // Security check
  const resolvedSource = path.resolve(sourcePath);
  const resolvedDir = path.resolve(UPLOADS_DIR);
  if (!resolvedSource.startsWith(resolvedDir + path.sep) && resolvedSource !== resolvedDir) {
    return res.status(403).json({ error: 'Access denied' });
  }

  if (!fs.existsSync(sourcePath)) {
    return res.status(404).json({ error: 'File not found' });
  }

  try {
    // Handle duplicate filenames in imports
    let finalDestPath = destPath;
    if (fs.existsSync(destPath)) {
      const ext = path.extname(req.params.filename);
      const base = path.basename(req.params.filename, ext);
      const timestamp = Date.now();
      finalDestPath = path.join(IMPORTS_DIR, `${base}-${timestamp}${ext}`);
    }

    fs.renameSync(sourcePath, finalDestPath);

    // Queue background indexing - returns immediately to UI
    const jobId = queueIndexingJob(path.basename(finalDestPath), finalDestPath);

    // Return immediately with job ID for status tracking
    res.json({
      success: true,
      path: finalDestPath,
      indexing: 'queued',
      jobId,
      message: 'File imported. Indexing in background.',
    });
  } catch (error) {
    res.status(500).json({ error: 'Failed to import file' });
  }
});

// Indexing Job Status API Routes

// Get all indexing jobs status
app.get('/api/indexing/jobs', (_req, res) => {
  const jobs = Array.from(indexingJobs.values())
    .sort((a, b) => {
      // Active jobs first, then by time
      if (a.status === 'processing' && b.status !== 'processing') return -1;
      if (b.status === 'processing' && a.status !== 'processing') return 1;
      if (a.status === 'queued' && b.status !== 'queued') return -1;
      if (b.status === 'queued' && a.status !== 'queued') return 1;
      return (b.startedAt || b.id).localeCompare(a.startedAt || a.id);
    })
    .slice(0, 50); // Return last 50 jobs

  const queueLength = indexingQueue.length;
  const processing = jobs.filter(j => j.status === 'processing').length;

  res.json({
    jobs,
    queueLength,
    processing,
    isProcessing: isProcessingQueue,
  });
});

// Get specific job status
app.get('/api/indexing/jobs/:jobId', (req, res) => {
  const job = indexingJobs.get(req.params.jobId);
  if (!job) {
    return res.status(404).json({ error: 'Job not found' });
  }
  res.json(job);
});

// Get indexing summary (for UI status indicator)
app.get('/api/indexing/status', (_req, res) => {
  const jobs = Array.from(indexingJobs.values());
  const queued = jobs.filter(j => j.status === 'queued').length;
  const processing = jobs.filter(j => j.status === 'processing').length;
  const completed = jobs.filter(j => j.status === 'completed').length;
  const failed = jobs.filter(j => j.status === 'failed').length;

  const currentJob = jobs.find(j => j.status === 'processing');

  res.json({
    active: queued + processing > 0,
    queued,
    processing,
    completed,
    failed,
    currentJob: currentJob ? {
      id: currentJob.id,
      filename: currentJob.filename,
      progress: currentJob.progress,
    } : null,
  });
});

// Vector Store API Routes

// Initialize vector store client with config from environment
const VECTOR_STORE_HOST = process.env.VECTOR_STORE_HOST || 'localhost';
const VECTOR_STORE_PORT = parseInt(process.env.VECTOR_STORE_PORT || '8085', 10);
const VECTOR_STORE_API_KEY = process.env.VECTOR_STORE_API_KEY;

initVectorStoreClient({
  host: VECTOR_STORE_HOST,
  port: VECTOR_STORE_PORT,
  apiKey: VECTOR_STORE_API_KEY,
});

// Get vector store status
app.get('/api/vector-store/status', async (_req, res) => {
  try {
    const available = await isVectorStoreAvailable();
    if (available) {
      const client = getVectorStoreClient();
      const stats = await client.getStats();
      res.json({
        available: true,
        host: VECTOR_STORE_HOST,
        port: VECTOR_STORE_PORT,
        ...stats,
      });
    } else {
      res.json({
        available: false,
        host: VECTOR_STORE_HOST,
        port: VECTOR_STORE_PORT,
        message: 'Vector store server not running. Start mcp-vector-store HTTP server.',
      });
    }
  } catch (error) {
    res.json({
      available: false,
      error: String(error),
    });
  }
});

// Debug info - detailed system stats
app.get('/api/vector-store/debug', async (_req, res) => {
  try {
    const available = await isVectorStoreAvailable();
    if (available) {
      const client = getVectorStoreClient();
      const debugInfo = await client.getDebugInfo();
      res.json(debugInfo);
    } else {
      res.json({
        error: 'Vector store not available',
        available: false,
      });
    }
  } catch (error) {
    res.status(500).json({ error: String(error) });
  }
});

// Search documents in vector store
app.post('/api/vector-store/search', async (req, res) => {
  try {
    const { query, topK = 5, minScore } = req.body;
    if (!query) {
      return res.status(400).json({ error: 'Query is required' });
    }

    const available = await isVectorStoreAvailable();
    if (!available) {
      return res.status(503).json({
        error: 'Vector store not available',
        message: 'Start the mcp-vector-store HTTP server',
      });
    }

    const client = getVectorStoreClient();
    const results = await client.search(query, topK, minScore);
    res.json({ query, minScore, results });
  } catch (error) {
    res.status(500).json({ error: String(error) });
  }
});

// Enhanced search with passage extraction
app.post('/api/vector-store/search/enhanced', async (req, res) => {
  try {
    const {
      query,
      topK = 5,
      minScore = 0.5,  // Balanced threshold for quality results
      extractPassages = true,
      expandQuery = false,
      maxExcerptLength = 500,
    } = req.body;

    if (!query) {
      return res.status(400).json({ error: 'Query is required' });
    }

    const available = await isVectorStoreAvailable();
    if (!available) {
      return res.status(503).json({
        error: 'Vector store not available',
        message: 'Start the mcp-vector-store HTTP server',
      });
    }

    const client = getVectorStoreClient();
    const response = await client.enhancedSearch(query, {
      topK,
      minScore,
      extractPassages,
      expandQuery,
      maxExcerptLength,
    });

    res.json({
      query,
      minScore,
      extractPassages,
      expandQuery,
      results: response.results,
      pii_session_id: response.pii_session_id,
    });
  } catch (error) {
    res.status(500).json({ error: String(error) });
  }
});

// Add document to vector store
app.post('/api/vector-store/documents', async (req, res) => {
  try {
    const { text, metadata } = req.body;
    if (!text) {
      return res.status(400).json({ error: 'Text is required' });
    }

    const available = await isVectorStoreAvailable();
    if (!available) {
      return res.status(503).json({
        error: 'Vector store not available',
        message: 'Start the mcp-vector-store HTTP server',
      });
    }

    const client = getVectorStoreClient();
    const result = await client.addDocument(text, metadata);
    res.json({
      success: true,
      documentId: result.document_id,
      isDuplicate: result.is_duplicate,
      existingDocumentId: result.existing_document_id,
      contentHash: result.content_hash
    });
  } catch (error) {
    res.status(500).json({ error: String(error) });
  }
});

// Add multiple documents to vector store
app.post('/api/vector-store/documents/batch', async (req, res) => {
  try {
    const { documents } = req.body;
    if (!documents || !Array.isArray(documents)) {
      return res.status(400).json({ error: 'Documents array is required' });
    }

    const available = await isVectorStoreAvailable();
    if (!available) {
      return res.status(503).json({
        error: 'Vector store not available',
        message: 'Start the mcp-vector-store HTTP server',
      });
    }

    const client = getVectorStoreClient();
    const result = await client.addDocuments(documents);
    res.json({
      success: true,
      documentIds: result.document_ids,
      count: result.count,
      duplicatesSkipped: result.duplicates_skipped,
      duplicates: result.duplicates
    });
  } catch (error) {
    res.status(500).json({ error: String(error) });
  }
});

// List documents in vector store
app.get('/api/vector-store/documents', async (req, res) => {
  try {
    const page = parseInt(req.query.page as string || '1', 10);
    const pageSize = parseInt(req.query.pageSize as string || '10', 10);
    const ascending = req.query.ascending === 'true';

    const available = await isVectorStoreAvailable();
    if (!available) {
      return res.status(503).json({
        error: 'Vector store not available',
        message: 'Start the mcp-vector-store HTTP server',
      });
    }

    const client = getVectorStoreClient();
    const result = await client.listDocuments(page, pageSize, ascending);
    res.json(result);
  } catch (error) {
    res.status(500).json({ error: String(error) });
  }
});

// Get single document from vector store
app.get('/api/vector-store/documents/:docId', async (req, res) => {
  try {
    const docId = parseInt(req.params.docId, 10);
    if (isNaN(docId)) {
      return res.status(400).json({ error: 'Invalid document ID' });
    }

    const available = await isVectorStoreAvailable();
    if (!available) {
      return res.status(503).json({
        error: 'Vector store not available',
        message: 'Start the mcp-vector-store HTTP server',
      });
    }

    const client = getVectorStoreClient();
    const doc = await client.getDocument(docId);
    if (!doc) {
      return res.status(404).json({ error: 'Document not found' });
    }
    res.json({ success: true, document: doc });
  } catch (error) {
    res.status(500).json({ error: String(error) });
  }
});

// Delete document from vector store
app.delete('/api/vector-store/documents/:docId', async (req, res) => {
  try {
    const docId = parseInt(req.params.docId, 10);
    if (isNaN(docId)) {
      return res.status(400).json({ error: 'Invalid document ID' });
    }

    const available = await isVectorStoreAvailable();
    if (!available) {
      return res.status(503).json({
        error: 'Vector store not available',
        message: 'Start the mcp-vector-store HTTP server',
      });
    }

    const client = getVectorStoreClient();
    const success = await client.deleteDocument(docId);
    res.json({ success });
  } catch (error) {
    res.status(500).json({ error: String(error) });
  }
});

// Clear all data (vector store documents, uploaded files, imports)
app.post('/api/data/clear-all', async (_req, res) => {
  try {
    const results: { vectorStore?: any; filesDeleted: number; importsDeleted: number } = {
      filesDeleted: 0,
      importsDeleted: 0,
    };

    // 1. Clear vector store
    const available = await isVectorStoreAvailable();
    if (available) {
      const client = getVectorStoreClient();
      results.vectorStore = await client.clearAllDocuments();
    }

    // 2. Delete all uploaded files
    if (fs.existsSync(UPLOADS_DIR)) {
      const files = fs.readdirSync(UPLOADS_DIR);
      for (const file of files) {
        try {
          fs.unlinkSync(path.join(UPLOADS_DIR, file));
          results.filesDeleted++;
        } catch { /* skip */ }
      }
    }

    // 3. Delete all import files
    if (fs.existsSync(IMPORTS_DIR)) {
      const files = fs.readdirSync(IMPORTS_DIR);
      for (const file of files) {
        try {
          fs.unlinkSync(path.join(IMPORTS_DIR, file));
          results.importsDeleted++;
        } catch { /* skip */ }
      }
    }

    // 4. Clear indexed-files tracking
    if (fs.existsSync(INDEXED_FILES_PATH)) {
      fs.writeFileSync(INDEXED_FILES_PATH, '{}');
    }

    res.json({ success: true, ...results });
  } catch (error) {
    res.status(500).json({ error: String(error) });
  }
});

// Index connector exports to vector store
app.post('/api/vector-store/index-connector/:connectorId', async (req, res) => {
  try {
    const { connectorId } = req.params;
    const exportDir = path.join(EXPORTS_DIR, connectorId);

    if (!fs.existsSync(exportDir)) {
      return res.status(404).json({ error: 'Connector exports not found' });
    }

    const available = await isVectorStoreAvailable();
    if (!available) {
      return res.status(503).json({
        error: 'Vector store not available',
        message: 'Start the mcp-vector-store HTTP server',
      });
    }

    // Read all export files
    const files = fs.readdirSync(exportDir).filter(f => f.endsWith('.json') && !f.startsWith('.'));
    const client = getVectorStoreClient();
    let totalIndexed = 0;
    let duplicatesSkipped = 0;
    const errors: string[] = [];

    for (const file of files) {
      try {
        const filePath = path.join(exportDir, file);
        const content = JSON.parse(fs.readFileSync(filePath, 'utf-8'));

        // Handle ChatGPT export format (messages array)
        if (content.messages && Array.isArray(content.messages)) {
          const documents = content.messages
            .filter((msg: any) => msg.content && typeof msg.content === 'string')
            .map((msg: any) => ({
              text: msg.content,
              metadata: {
                source: 'chatgpt',
                connectorId,
                conversationId: content.id || file.replace('.json', ''),
                conversationTitle: content.title || 'Untitled',
                role: msg.role || 'unknown',
                timestamp: msg.create_time || msg.timestamp,
                exportFile: file,
              },
            }));

          if (documents.length > 0) {
            const result = await client.addDocuments(documents);
            totalIndexed += result.document_ids.length;
            duplicatesSkipped += result.duplicates_skipped;
          }
        }
        // Handle Notion page format
        else if (content.type === 'page' && content.content) {
          const text = `# ${content.title || 'Untitled'}\n\n${content.content}`;
          const result = await client.addDocument(text, {
            source: 'notion',
            connectorId,
            notionId: content.id,
            title: content.title,
            url: content.url,
            parentType: content.parentType,
            createdAt: content.createdAt,
            updatedAt: content.updatedAt,
            exportFile: file,
          });
          if (result.is_duplicate) {
            duplicatesSkipped++;
          } else {
            totalIndexed++;
          }
        }
        // Handle Notion database format
        else if (content.type === 'database' && content.entries) {
          for (const entry of content.entries) {
            const propsText = Object.entries(entry.properties || {})
              .map(([key, value]) => `${key}: ${value}`)
              .join('\n');
            const text = `# ${entry.title || 'Untitled'}\n\nDatabase: ${content.title}\n\n${propsText}`;
            const result = await client.addDocument(text, {
              source: 'notion',
              connectorId,
              notionId: entry.id,
              databaseId: content.id,
              databaseTitle: content.title,
              title: entry.title,
              url: entry.url,
              exportFile: file,
            });
            if (result.is_duplicate) {
              duplicatesSkipped++;
            } else {
              totalIndexed++;
            }
          }
        }
        // Handle plain text content
        else if (typeof content === 'string') {
          const result = await client.addDocument(content, {
            source: 'export',
            connectorId,
            exportFile: file,
          });
          if (result.is_duplicate) {
            duplicatesSkipped++;
          } else {
            totalIndexed++;
          }
        }
        // Handle generic object with text/content field
        else if (content.text || content.content) {
          const text = content.text || content.content;
          const result = await client.addDocument(text, {
            source: 'export',
            connectorId,
            title: content.title || content.name,
            exportFile: file,
          });
          if (result.is_duplicate) {
            duplicatesSkipped++;
          } else {
            totalIndexed++;
          }
        }
      } catch (fileError) {
        errors.push(`${file}: ${String(fileError)}`);
      }
    }

    res.json({
      success: true,
      totalIndexed,
      duplicatesSkipped,
      filesProcessed: files.length,
      errors: errors.length > 0 ? errors : undefined,
    });
  } catch (error) {
    res.status(500).json({ error: String(error) });
  }
});

// Supported file extensions for text extraction
const SUPPORTED_TEXT_EXTENSIONS = new Set([
  '.txt', '.md', '.py', '.js', '.ts', '.java', '.c', '.cpp', '.h',
  '.json', '.xml', '.html', '.css', '.yml', '.yaml', '.sh',
  '.rst', '.log', '.csv', '.tsv', '.jsx', '.tsx', '.go', '.rs',
  '.rb', '.php', '.swift', '.kt', '.scala', '.r', '.sql', '.pdf'
]);

// Extract text from file based on extension (async for PDF support)
async function extractTextFromFile(filePath: string): Promise<string | null> {
  const ext = path.extname(filePath).toLowerCase();

  if (!SUPPORTED_TEXT_EXTENSIONS.has(ext)) {
    return null;
  }

  try {
    // Handle PDF files
    if (ext === '.pdf') {
      const { PDFParse } = await import('pdf-parse');
      const dataBuffer = fs.readFileSync(filePath);
      const uint8Array = new Uint8Array(dataBuffer);
      const pdfParser = new PDFParse(uint8Array) as any;
      await pdfParser.load();
      const result = await pdfParser.getText();
      return result.text || '';
    }

    const content = fs.readFileSync(filePath, 'utf-8');

    // For JSON files, try to extract meaningful text
    if (ext === '.json') {
      try {
        const data = JSON.parse(content);
        // Handle ChatGPT export format
        if (data.messages && Array.isArray(data.messages)) {
          return data.messages
            .filter((m: any) => m.content && typeof m.content === 'string')
            .map((m: any) => `${m.role || 'unknown'}: ${m.content}`)
            .join('\n\n');
        }
        // Handle array of text items
        if (Array.isArray(data)) {
          return data.map((item: any) =>
            typeof item === 'string' ? item : JSON.stringify(item, null, 2)
          ).join('\n\n');
        }
        // Return formatted JSON for other structures
        return JSON.stringify(data, null, 2);
      } catch {
        return content;
      }
    }

    return content;
  } catch (error) {
    console.error(`Error reading file ${filePath}:`, error);
    return null;
  }
}

// Index uploaded files to vector store
app.post('/api/vector-store/index-uploads', async (_req, res) => {
  try {
    const available = await isVectorStoreAvailable();
    if (!available) {
      return res.status(503).json({
        error: 'Vector store not available',
        message: 'Start the mcp-vector-store HTTP server',
      });
    }

    if (!fs.existsSync(IMPORTS_DIR)) {
      return res.json({
        success: true,
        totalIndexed: 0,
        filesProcessed: 0,
        message: 'No imports directory found',
      });
    }

    // Read all files from imports directory (where LocalSend and uploaded files are stored)
    const files = fs.readdirSync(IMPORTS_DIR).filter(f => {
      const filePath = path.join(IMPORTS_DIR, f);
      return fs.statSync(filePath).isFile() && !f.startsWith('.');
    });

    const client = getVectorStoreClient();
    let totalIndexed = 0;
    let duplicatesSkipped = 0;
    const errors: string[] = [];
    const indexed: string[] = [];
    const skipped: string[] = [];
    const duplicates: string[] = [];

    for (const file of files) {
      const filePath = path.join(IMPORTS_DIR, file);
      const ext = path.extname(file).toLowerCase();

      // Skip already indexed files
      if (isFileIndexed(filePath)) {
        skipped.push(`${file} (already indexed)`);
        continue;
      }

      if (!SUPPORTED_TEXT_EXTENSIONS.has(ext)) {
        skipped.push(`${file} (unsupported format)`);
        continue;
      }

      try {
        const text = await extractTextFromFile(filePath);
        if (!text || text.trim().length === 0) {
          skipped.push(`${file} (empty or unreadable)`);
          continue;
        }

        const stat = fs.statSync(filePath);

        // Add document to vector store (duplicate detection enabled by default)
        const result = await client.addDocument(text, {
          source: 'import',
          filename: file,
          extension: ext,
          filePath: filePath,
          size: stat.size,
          modified: stat.mtime.toISOString(),
          indexed_at: new Date().toISOString(),
        });

        if (result.is_duplicate) {
          // Content already exists - mark file as indexed with existing doc ID
          duplicatesSkipped++;
          duplicates.push(`${file} (content exists as doc ${result.existing_document_id})`);
          markFileIndexed(filePath, result.existing_document_id);
        } else if (result.document_id) {
          // Mark file as indexed to avoid re-indexing
          markFileIndexed(filePath, result.document_id);
          totalIndexed++;
          indexed.push(file);
        }
      } catch (fileError) {
        errors.push(`${file}: ${String(fileError)}`);
      }
    }

    res.json({
      success: true,
      totalIndexed,
      duplicatesSkipped,
      filesProcessed: files.length,
      indexed,
      duplicates: duplicates.length > 0 ? duplicates : undefined,
      skipped: skipped.length > 0 ? skipped : undefined,
      errors: errors.length > 0 ? errors : undefined,
    });
  } catch (error) {
    res.status(500).json({ error: String(error) });
  }
});

// Index a specific file to vector store
app.post('/api/vector-store/index-file/:filename', async (req, res) => {
  try {
    const { filename } = req.params;
    const filePath = path.join(IMPORTS_DIR, filename);

    if (!fs.existsSync(filePath)) {
      return res.status(404).json({ error: 'File not found in imports directory' });
    }

    const available = await isVectorStoreAvailable();
    if (!available) {
      return res.status(503).json({
        error: 'Vector store not available',
        message: 'Start the mcp-vector-store HTTP server',
      });
    }

    const ext = path.extname(filename).toLowerCase();
    if (!SUPPORTED_TEXT_EXTENSIONS.has(ext)) {
      return res.status(400).json({
        error: 'Unsupported file format',
        supported: Array.from(SUPPORTED_TEXT_EXTENSIONS),
      });
    }

    const text = await extractTextFromFile(filePath);
    if (!text || text.trim().length === 0) {
      return res.status(400).json({ error: 'File is empty or unreadable' });
    }

    const stat = fs.statSync(filePath);
    const client = getVectorStoreClient();

    const result = await client.addDocument(text, {
      source: 'import',
      filename,
      extension: ext,
      filePath,
      size: stat.size,
      modified: stat.mtime.toISOString(),
      indexed_at: new Date().toISOString(),
    });

    if (result.is_duplicate) {
      res.json({
        success: false,
        isDuplicate: true,
        existingDocumentId: result.existing_document_id,
        contentHash: result.content_hash,
        filename,
        message: `Content already exists with document ID ${result.existing_document_id}`,
      });
    } else {
      res.json({
        success: true,
        documentId: result.document_id,
        filename,
        textLength: text.length,
      });
    }
  } catch (error) {
    res.status(500).json({ error: String(error) });
  }
});

// Media Processing Routes (Audio & Image)

// Get media processing status (available models, supported formats)
app.get('/api/vector-store/media/status', async (_req, res) => {
  try {
    const available = await isVectorStoreAvailable();
    if (!available) {
      return res.status(503).json({
        error: 'Vector store not available',
        message: 'Start the mcp-vector-store HTTP server',
      });
    }

    const client = getVectorStoreClient();
    const result = await client.getMediaStatus();
    res.json(result);
  } catch (error) {
    res.status(500).json({ error: String(error) });
  }
});

// Upload and process a media file (audio/image)
// Proxies multipart upload to Python vector store
app.post('/api/vector-store/media/upload', async (req, res) => {
  try {
    const available = await isVectorStoreAvailable();
    if (!available) {
      return res.status(503).json({
        error: 'Vector store not available',
        message: 'Start the mcp-vector-store HTTP server',
      });
    }

    // Forward the raw request to the Python vector store
    const vsHost = process.env.VECTOR_STORE_HOST || 'localhost';
    const vsPort = process.env.VECTOR_STORE_PORT || '8085';
    const url = `http://${vsHost}:${vsPort}/api/media/upload`;

    // Only forward safe headers for the proxy request
    const proxyHeaders: Record<string, string | string[] | undefined> = {
      'content-type': req.headers['content-type'],
      'content-length': req.headers['content-length'],
      host: `${vsHost}:${vsPort}`,
    };

    const proxyReq = http.request(url, {
      method: 'POST',
      headers: proxyHeaders,
      timeout: 600000, // 10 minutes - media processing can be slow on Jetson
    }, (proxyRes) => {
      res.status(proxyRes.statusCode || 500);
      // Forward content-type header
      if (proxyRes.headers['content-type']) {
        res.setHeader('content-type', proxyRes.headers['content-type']);
      }
      proxyRes.pipe(res);
    });

    proxyReq.on('error', (error) => {
      if (!res.headersSent) {
        res.status(502).json({ error: `Proxy error: ${error.message}` });
      }
    });

    proxyReq.on('timeout', () => {
      proxyReq.destroy();
      if (!res.headersSent) {
        res.status(504).json({ error: 'Media processing timed out' });
      }
    });

    req.on('error', () => {
      proxyReq.destroy();
    });

    // Pipe the incoming request body to the proxy request
    req.pipe(proxyReq);
  } catch (error) {
    res.status(500).json({ error: String(error) });
  }
});

// Serve audio files (proxy to vector store)
// Allows browser to fetch audio via Express instead of direct vector store access
app.get('/api/audio/serve/:audioId', async (req, res) => {
  try {
    const available = await isVectorStoreAvailable();
    if (!available) {
      return res.status(503).json({ error: 'Vector store not available' });
    }

    const { audioId } = req.params;
    const type = req.query.type || 'original';
    const vsHost = process.env.VECTOR_STORE_HOST || 'localhost';
    const vsPort = process.env.VECTOR_STORE_PORT || '8085';
    const url = `http://${vsHost}:${vsPort}/api/audio/serve/${encodeURIComponent(audioId)}?type=${encodeURIComponent(String(type))}`;

    const proxyReq = http.request(url, { method: 'GET' }, (proxyRes) => {
      res.status(proxyRes.statusCode || 500);
      // Forward audio headers
      for (const header of ['content-type', 'content-length', 'accept-ranges', 'cache-control']) {
        if (proxyRes.headers[header]) {
          res.setHeader(header, proxyRes.headers[header]!);
        }
      }
      proxyRes.pipe(res);
    });

    proxyReq.on('error', (error) => {
      if (!res.headersSent) {
        res.status(502).json({ error: `Audio proxy error: ${error.message}` });
      }
    });

    proxyReq.end();
  } catch (error) {
    if (!res.headersSent) {
      res.status(500).json({ error: String(error) });
    }
  }
});

// =====================================================================
// Voice Chat v2 Routes (WebRTC signaling + SSE proxy)
// =====================================================================

// WebRTC SDP offer — proxy to Python FastRTC
app.post('/api/voice/webrtc/offer', async (req, res) => {
  try {
    const available = await isVectorStoreAvailable();
    if (!available) {
      return res.status(503).json({ error: 'Vector store not available' });
    }
    const vsHost = process.env.VECTOR_STORE_HOST || 'localhost';
    const vsPort = process.env.VECTOR_STORE_PORT || '8085';
    const url = `http://${vsHost}:${vsPort}/api/voice/webrtc/offer`;

    const bodyStr = JSON.stringify(req.body);

    const proxyReq = http.request(url, {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        'content-length': Buffer.byteLength(bodyStr).toString(),
        host: `${vsHost}:${vsPort}`,
      },
      timeout: 15000,
    }, (proxyRes) => {
      res.status(proxyRes.statusCode || 500);
      if (proxyRes.headers['content-type']) {
        res.setHeader('content-type', proxyRes.headers['content-type']);
      }
      proxyRes.pipe(res);
    });

    proxyReq.on('error', (error) => {
      if (!res.headersSent) {
        res.status(502).json({ error: `WebRTC offer proxy error: ${error.message}` });
      }
    });

    proxyReq.on('timeout', () => {
      proxyReq.destroy();
      if (!res.headersSent) {
        res.status(504).json({ error: 'WebRTC offer timed out' });
      }
    });

    proxyReq.write(bodyStr);
    proxyReq.end();
  } catch (error) {
    if (!res.headersSent) {
      res.status(500).json({ error: String(error) });
    }
  }
});

// Voice text outputs — SSE proxy from Python
app.get('/api/voice/outputs', async (req, res) => {
  try {
    const available = await isVectorStoreAvailable();
    if (!available) {
      return res.status(503).json({ error: 'Vector store not available' });
    }
    const vsHost = process.env.VECTOR_STORE_HOST || 'localhost';
    const vsPort = process.env.VECTOR_STORE_PORT || '8085';
    const webrtcId = req.query.webrtc_id || '';
    const url = `http://${vsHost}:${vsPort}/api/voice/outputs?webrtc_id=${webrtcId}`;

    // SSE proxy: set headers and pipe
    res.setHeader('Content-Type', 'text/event-stream');
    res.setHeader('Cache-Control', 'no-cache');
    res.setHeader('Connection', 'keep-alive');
    res.flushHeaders();

    const proxyReq = http.request(url, { method: 'GET' }, (proxyRes) => {
      proxyRes.pipe(res);
    });

    proxyReq.on('error', (error) => {
      if (!res.headersSent) {
        res.status(502).json({ error: `Voice outputs proxy error: ${error.message}` });
      }
    });

    req.on('close', () => {
      proxyReq.destroy();
    });

    proxyReq.end();
  } catch (error) {
    if (!res.headersSent) {
      res.status(500).json({ error: String(error) });
    }
  }
});

// Disconnect voice session
app.post('/api/voice/disconnect', async (_req, res) => {
  try {
    const available = await isVectorStoreAvailable();
    if (!available) {
      return res.status(503).json({ error: 'Vector store not available' });
    }
    const vsHost = process.env.VECTOR_STORE_HOST || 'localhost';
    const vsPort = process.env.VECTOR_STORE_PORT || '8085';
    const url = `http://${vsHost}:${vsPort}/api/voice/disconnect`;

    const proxyReq = http.request(url, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      timeout: 5000,
    }, (proxyRes) => {
      res.status(proxyRes.statusCode || 500);
      if (proxyRes.headers['content-type']) {
        res.setHeader('content-type', proxyRes.headers['content-type']);
      }
      proxyRes.pipe(res);
    });

    proxyReq.on('error', (error) => {
      if (!res.headersSent) {
        res.status(502).json({ error: `Voice disconnect proxy error: ${error.message}` });
      }
    });

    proxyReq.end();
  } catch (error) {
    if (!res.headersSent) {
      res.status(500).json({ error: String(error) });
    }
  }
});

// Voice chat status
app.get('/api/voice/status', async (_req, res) => {
  try {
    const available = await isVectorStoreAvailable();
    if (!available) {
      return res.status(503).json({ error: 'Vector store not available' });
    }
    const vsHost = process.env.VECTOR_STORE_HOST || 'localhost';
    const vsPort = process.env.VECTOR_STORE_PORT || '8085';
    const url = `http://${vsHost}:${vsPort}/api/voice/status`;

    const proxyReq = http.request(url, { method: 'GET' }, (proxyRes) => {
      res.status(proxyRes.statusCode || 500);
      if (proxyRes.headers['content-type']) {
        res.setHeader('content-type', proxyRes.headers['content-type']);
      }
      proxyRes.pipe(res);
    });

    proxyReq.on('error', (error) => {
      if (!res.headersSent) {
        res.status(502).json({ error: `Voice status proxy error: ${error.message}` });
      }
    });

    proxyReq.end();
  } catch (error) {
    if (!res.headersSent) {
      res.status(500).json({ error: String(error) });
    }
  }
});

// Voice configuration
app.get('/api/voice/config', async (_req, res) => {
  try {
    const available = await isVectorStoreAvailable();
    if (!available) {
      return res.status(503).json({ error: 'Vector store not available' });
    }
    const vsHost = process.env.VECTOR_STORE_HOST || 'localhost';
    const vsPort = process.env.VECTOR_STORE_PORT || '8085';
    const url = `http://${vsHost}:${vsPort}/api/voice/config`;

    const proxyReq = http.request(url, { method: 'GET' }, (proxyRes) => {
      res.status(proxyRes.statusCode || 500);
      if (proxyRes.headers['content-type']) {
        res.setHeader('content-type', proxyRes.headers['content-type']);
      }
      proxyRes.pipe(res);
    });

    proxyReq.on('error', (error) => {
      if (!res.headersSent) {
        res.status(502).json({ error: `Voice config proxy error: ${error.message}` });
      }
    });

    proxyReq.end();
  } catch (error) {
    if (!res.headersSent) {
      res.status(500).json({ error: String(error) });
    }
  }
});

app.put('/api/voice/config', async (req, res) => {
  try {
    const available = await isVectorStoreAvailable();
    if (!available) {
      return res.status(503).json({ error: 'Vector store not available' });
    }
    const vsHost = process.env.VECTOR_STORE_HOST || 'localhost';
    const vsPort = process.env.VECTOR_STORE_PORT || '8085';
    const url = `http://${vsHost}:${vsPort}/api/voice/config`;

    const bodyStr = JSON.stringify(req.body);

    const proxyReq = http.request(url, {
      method: 'PUT',
      headers: {
        'content-type': 'application/json',
        'content-length': Buffer.byteLength(bodyStr).toString(),
        host: `${vsHost}:${vsPort}`,
      },
    }, (proxyRes) => {
      res.status(proxyRes.statusCode || 500);
      if (proxyRes.headers['content-type']) {
        res.setHeader('content-type', proxyRes.headers['content-type']);
      }
      proxyRes.pipe(res);
    });

    proxyReq.on('error', (error) => {
      if (!res.headersSent) {
        res.status(502).json({ error: `Voice config proxy error: ${error.message}` });
      }
    });

    proxyReq.write(bodyStr);
    proxyReq.end();
  } catch (error) {
    if (!res.headersSent) {
      res.status(500).json({ error: String(error) });
    }
  }
});

// Topic-related Vector Store Routes

// Get all topics with document counts
app.get('/api/vector-store/topics', async (_req, res) => {
  try {
    const available = await isVectorStoreAvailable();
    if (!available) {
      return res.status(503).json({
        error: 'Vector store not available',
        message: 'Start the mcp-vector-store HTTP server',
      });
    }

    const client = getVectorStoreClient();
    const result = await client.getAllTopics();
    res.json(result);
  } catch (error) {
    res.status(500).json({ error: String(error) });
  }
});

// Get documents by topic
app.get('/api/vector-store/topics/:topic/documents', async (req, res) => {
  try {
    const { topic } = req.params;
    const page = parseInt(req.query.page as string || '1', 10);
    const pageSize = parseInt(req.query.pageSize as string || '10', 10);

    const available = await isVectorStoreAvailable();
    if (!available) {
      return res.status(503).json({
        error: 'Vector store not available',
        message: 'Start the mcp-vector-store HTTP server',
      });
    }

    const client = getVectorStoreClient();
    const result = await client.getDocumentsByTopic(topic, page, pageSize);
    res.json(result);
  } catch (error) {
    res.status(500).json({ error: String(error) });
  }
});

// Get topics for a document
app.get('/api/vector-store/documents/:docId/topics', async (req, res) => {
  try {
    const docId = parseInt(req.params.docId, 10);
    if (isNaN(docId)) {
      return res.status(400).json({ error: 'Invalid document ID' });
    }

    const available = await isVectorStoreAvailable();
    if (!available) {
      return res.status(503).json({
        error: 'Vector store not available',
        message: 'Start the mcp-vector-store HTTP server',
      });
    }

    const client = getVectorStoreClient();
    const result = await client.getDocumentTopics(docId);
    if (!result) {
      return res.status(404).json({ error: 'Document not found' });
    }
    res.json({ success: true, ...result });
  } catch (error) {
    res.status(500).json({ error: String(error) });
  }
});

// Update topics for a document
app.put('/api/vector-store/documents/:docId/topics', async (req, res) => {
  try {
    const docId = parseInt(req.params.docId, 10);
    if (isNaN(docId)) {
      return res.status(400).json({ error: 'Invalid document ID' });
    }

    const { topics, primaryTopic } = req.body;
    if (!topics || !Array.isArray(topics)) {
      return res.status(400).json({ error: 'Topics array is required' });
    }

    const available = await isVectorStoreAvailable();
    if (!available) {
      return res.status(503).json({
        error: 'Vector store not available',
        message: 'Start the mcp-vector-store HTTP server',
      });
    }

    const client = getVectorStoreClient();
    const success = await client.updateDocumentTopics(docId, topics, primaryTopic);
    res.json({ success, docId, topics, primaryTopic: primaryTopic || topics[0] });
  } catch (error) {
    res.status(500).json({ error: String(error) });
  }
});

// Generate topics for a document
app.post('/api/vector-store/documents/:docId/topics/generate', async (req, res) => {
  try {
    const docId = parseInt(req.params.docId, 10);
    if (isNaN(docId)) {
      return res.status(400).json({ error: 'Invalid document ID' });
    }

    const { numTopics = 3, predefinedTopics } = req.body;

    const available = await isVectorStoreAvailable();
    if (!available) {
      return res.status(503).json({
        error: 'Vector store not available',
        message: 'Start the mcp-vector-store HTTP server',
      });
    }

    const client = getVectorStoreClient();
    const result = await client.generateTopics(docId, numTopics, predefinedTopics);
    res.json(result);
  } catch (error) {
    res.status(500).json({ error: String(error) });
  }
});

// Search with topic filter
app.post('/api/vector-store/search/with-topic', async (req, res) => {
  try {
    const { query, topic, topK = 5, minScore } = req.body;
    if (!query) {
      return res.status(400).json({ error: 'Query is required' });
    }

    const available = await isVectorStoreAvailable();
    if (!available) {
      return res.status(503).json({
        error: 'Vector store not available',
        message: 'Start the mcp-vector-store HTTP server',
      });
    }

    const client = getVectorStoreClient();
    const response = await client.searchWithTopic(query, topic, topK, minScore);
    res.json({
      query,
      topic,
      minScore,
      results: response.results,
      pii_session_id: response.pii_session_id,
    });
  } catch (error) {
    res.status(500).json({ error: String(error) });
  }
});

// Fast Search Routes (no GPU required)

// Quick keyword search (FTS5/BM25 only)
app.post('/api/vector-store/search/quick', async (req, res) => {
  try {
    const available = await isVectorStoreAvailable();
    if (!available) {
      return res.status(503).json({ error: 'Vector store not available' });
    }
    const client = getVectorStoreClient();
    const response = await client.quickSearch(req.body.query, req.body.top_k);
    res.json(response);
  } catch (error) {
    res.status(500).json({ error: String(error) });
  }
});

// File system search (unindexed content)
app.post('/api/vector-store/search/files', async (req, res) => {
  try {
    const available = await isVectorStoreAvailable();
    if (!available) {
      return res.status(503).json({ error: 'Vector store not available' });
    }
    const client = getVectorStoreClient();
    const response = await client.searchFiles(req.body.query, req.body.directories, req.body.max_results, req.body.case_sensitive);
    res.json(response);
  } catch (error) {
    res.status(500).json({ error: String(error) });
  }
});

// Metadata search
app.post('/api/vector-store/search/metadata', async (req, res) => {
  try {
    const available = await isVectorStoreAvailable();
    if (!available) {
      return res.status(503).json({ error: 'Vector store not available' });
    }
    const client = getVectorStoreClient();
    const response = await client.searchMetadata(req.body);
    res.json(response);
  } catch (error) {
    res.status(500).json({ error: String(error) });
  }
});

// Unified tiered search
app.post('/api/vector-store/search/unified', async (req, res) => {
  try {
    const available = await isVectorStoreAvailable();
    if (!available) {
      return res.status(503).json({ error: 'Vector store not available' });
    }
    const client = getVectorStoreClient();
    const response = await client.unifiedSearch(req.body.query, {
      topK: req.body.top_k,
      mode: req.body.mode,
      includeUnindexed: req.body.include_unindexed,
    });
    res.json(response);
  } catch (error) {
    res.status(500).json({ error: String(error) });
  }
});

// Knowledge Graph API Routes

// Get knowledge graph data
app.post('/api/vector-store/graph', async (req, res) => {
  try {
    const available = await isVectorStoreAvailable();
    if (!available) {
      return res.status(503).json({
        error: 'Vector store not available',
        message: 'Start the mcp-vector-store HTTP server',
      });
    }

    const client = getVectorStoreClient();
    const result = await client.getKnowledgeGraph(req.body);
    res.json(result);
  } catch (error) {
    res.status(500).json({ error: String(error) });
  }
});

// Get graph node details
app.get('/api/vector-store/graph/node/:nodeId', async (req, res) => {
  try {
    const { nodeId } = req.params;

    const available = await isVectorStoreAvailable();
    if (!available) {
      return res.status(503).json({
        error: 'Vector store not available',
        message: 'Start the mcp-vector-store HTTP server',
      });
    }

    const client = getVectorStoreClient();
    const result = await client.getGraphNodeDetails(nodeId);
    if (!result) {
      return res.status(404).json({ error: 'Node not found' });
    }
    res.json(result);
  } catch (error) {
    res.status(500).json({ error: String(error) });
  }
});

// === Graph Views API Routes ===

// List all saved views
app.get('/api/vector-store/graph/views', (_req, res) => {
  try {
    ensureGraphDirs();
    const files = fs.readdirSync(GRAPH_VIEWS_DIR).filter(f => f.endsWith('.json'));
    const views = files.map(f => {
      try {
        const data = JSON.parse(fs.readFileSync(path.join(GRAPH_VIEWS_DIR, f), 'utf-8'));
        return {
          id: data.id,
          name: data.name,
          description: data.description,
          createdAt: data.createdAt,
          nodeCount: data.nodeCount || 0,
          edgeCount: data.edgeCount || 0,
        };
      } catch {
        return null;
      }
    }).filter(Boolean);

    // Sort by creation date, newest first
    views.sort((a: any, b: any) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime());
    res.json({ views });
  } catch (error) {
    res.status(500).json({ error: String(error) });
  }
});

// Get a saved view by ID
app.get('/api/vector-store/graph/views/:viewId', (req, res) => {
  try {
    // Sanitize viewId to prevent directory traversal
    const safeId = path.basename(req.params.viewId).replace(/[^a-zA-Z0-9-]/g, '');
    if (!safeId || safeId !== req.params.viewId) {
      return res.status(400).json({ error: 'Invalid view ID' });
    }

    const filePath = path.join(GRAPH_VIEWS_DIR, `${safeId}.json`);
    if (!fs.existsSync(filePath)) {
      return res.status(404).json({ error: 'View not found' });
    }
    const data = JSON.parse(fs.readFileSync(filePath, 'utf-8'));
    res.json(data);
  } catch (error) {
    res.status(500).json({ error: String(error) });
  }
});

// Save a new view
app.post('/api/vector-store/graph/views', (req, res) => {
  try {
    ensureGraphDirs();
    const id = randomUUID();
    const view = {
      id,
      ...req.body,
      createdAt: new Date().toISOString(),
    };
    fs.writeFileSync(
      path.join(GRAPH_VIEWS_DIR, `${id}.json`),
      JSON.stringify(view, null, 2)
    );
    res.json({ id, createdAt: view.createdAt });
  } catch (error) {
    res.status(500).json({ error: String(error) });
  }
});

// Delete a saved view
app.delete('/api/vector-store/graph/views/:viewId', (req, res) => {
  try {
    // Sanitize viewId to prevent directory traversal
    const safeId = path.basename(req.params.viewId).replace(/[^a-zA-Z0-9-]/g, '');
    if (!safeId || safeId !== req.params.viewId) {
      return res.status(400).json({ error: 'Invalid view ID' });
    }

    const filePath = path.join(GRAPH_VIEWS_DIR, `${safeId}.json`);
    if (!fs.existsSync(filePath)) {
      return res.status(404).json({ error: 'View not found' });
    }
    fs.unlinkSync(filePath);
    res.json({ success: true });
  } catch (error) {
    res.status(500).json({ error: String(error) });
  }
});

// === Graph Manual Connections API Routes ===

// Create a manual connection
app.post('/api/vector-store/graph/connections', (req, res) => {
  try {
    const { source, target } = req.body;
    if (!source || !target) {
      return res.status(400).json({ error: 'source and target are required' });
    }
    if (source === target) {
      return res.status(400).json({ error: 'Cannot connect a node to itself' });
    }

    const connections = readGraphConnections();

    // Check for duplicates (bidirectional)
    const exists = connections.some(
      (c: any) => (c.source === source && c.target === target) || (c.source === target && c.target === source)
    );
    if (exists) {
      return res.status(409).json({ error: 'Connection already exists' });
    }

    const connection = {
      id: randomUUID(),
      source,
      target,
      createdAt: new Date().toISOString(),
    };
    connections.push(connection);
    writeGraphConnections(connections);

    res.json(connection);
  } catch (error) {
    res.status(500).json({ error: String(error) });
  }
});

// List all manual connections
app.get('/api/vector-store/graph/connections', (_req, res) => {
  try {
    const connections = readGraphConnections();
    res.json({ connections });
  } catch (error) {
    res.status(500).json({ error: String(error) });
  }
});

// Delete a manual connection
app.delete('/api/vector-store/graph/connections/:connectionId', (req, res) => {
  try {
    const connections = readGraphConnections();
    const filtered = connections.filter((c: any) => c.id !== req.params.connectionId);
    if (filtered.length === connections.length) {
      return res.status(404).json({ error: 'Connection not found' });
    }
    writeGraphConnections(filtered);
    res.json({ success: true });
  } catch (error) {
    res.status(500).json({ error: String(error) });
  }
});

// PII Protection API Routes

// Get PII protection status
app.get('/api/pii/status', async (_req, res) => {
  try {
    const available = await isVectorStoreAvailable();
    if (!available) {
      return res.json({
        enabled: false,
        reason: 'Vector store not available',
      });
    }

    const client = getVectorStoreClient();
    const status = await client.getPIIStatus();
    res.json(status);
  } catch (error) {
    res.status(500).json({ error: String(error) });
  }
});

// De-anonymize text containing PII tokens
app.post('/api/pii/deanonymize', async (req, res) => {
  try {
    const { text, session_id } = req.body;
    if (!text || !session_id) {
      return res.status(400).json({
        error: "Both 'text' and 'session_id' are required",
      });
    }

    const available = await isVectorStoreAvailable();
    if (!available) {
      return res.status(503).json({
        error: 'Vector store not available',
      });
    }

    const client = getVectorStoreClient();
    const result = await client.deanonymize(text, session_id);
    res.json(result);
  } catch (error) {
    res.status(500).json({ error: String(error) });
  }
});

// Get PII session info
app.get('/api/pii/session/:sessionId', async (req, res) => {
  try {
    const { sessionId } = req.params;

    const available = await isVectorStoreAvailable();
    if (!available) {
      return res.status(503).json({
        error: 'Vector store not available',
      });
    }

    const client = getVectorStoreClient();
    const session = await client.getPIISession(sessionId);
    if (!session) {
      return res.status(404).json({ error: 'Session not found' });
    }
    res.json(session);
  } catch (error) {
    res.status(500).json({ error: String(error) });
  }
});

// Clear a PII session
app.delete('/api/pii/session/:sessionId', async (req, res) => {
  try {
    const { sessionId } = req.params;

    const available = await isVectorStoreAvailable();
    if (!available) {
      return res.status(503).json({
        error: 'Vector store not available',
      });
    }

    const client = getVectorStoreClient();
    const cleared = await client.clearPIISession(sessionId);
    res.json({ cleared, session_id: sessionId });
  } catch (error) {
    res.status(500).json({ error: String(error) });
  }
});

// Consent Management API Routes

// Get consent system status
app.get('/api/consent/status', async (_req, res) => {
  try {
    const available = await isVectorStoreAvailable();
    if (!available) {
      return res.json({
        available: false,
        reason: 'Vector store not available',
        active_sessions: 0,
        total_sessions_created: 0,
        max_sessions: 0,
        session_ttl_seconds: 0,
        presets_available: [],
        categories_available: [],
      });
    }

    const client = getVectorStoreClient();
    const status = await client.getConsentStatus();
    res.json(status);
  } catch (error) {
    res.status(500).json({ error: String(error) });
  }
});

// Get available consent presets
app.get('/api/consent/presets', async (_req, res) => {
  try {
    const available = await isVectorStoreAvailable();
    if (!available) {
      return res.status(503).json({
        error: 'Vector store not available',
      });
    }

    const client = getVectorStoreClient();
    const presets = await client.getConsentPresets();
    res.json(presets);
  } catch (error) {
    res.status(500).json({ error: String(error) });
  }
});

// Create a new consent session
app.post('/api/consent/session', async (req, res) => {
  try {
    const available = await isVectorStoreAvailable();
    if (!available) {
      return res.status(503).json({
        error: 'Vector store not available',
      });
    }

    const client = getVectorStoreClient();
    const session = await client.createConsentSession(req.body);
    res.json(session);
  } catch (error) {
    res.status(500).json({ error: String(error) });
  }
});

// Get consent session by ID
app.get('/api/consent/session/:sessionId', async (req, res) => {
  try {
    const { sessionId } = req.params;

    const available = await isVectorStoreAvailable();
    if (!available) {
      return res.status(503).json({
        error: 'Vector store not available',
      });
    }

    const client = getVectorStoreClient();
    const session = await client.getConsentSession(sessionId);
    if (!session) {
      return res.status(404).json({ error: 'Session not found' });
    }
    res.json(session);
  } catch (error) {
    res.status(500).json({ error: String(error) });
  }
});

// Update consent session
app.patch('/api/consent/session/:sessionId', async (req, res) => {
  try {
    const { sessionId } = req.params;

    const available = await isVectorStoreAvailable();
    if (!available) {
      return res.status(503).json({
        error: 'Vector store not available',
      });
    }

    const client = getVectorStoreClient();
    const session = await client.updateConsentSession(sessionId, req.body);
    res.json(session);
  } catch (error) {
    res.status(500).json({ error: String(error) });
  }
});

// Delete consent session
app.delete('/api/consent/session/:sessionId', async (req, res) => {
  try {
    const { sessionId } = req.params;

    const available = await isVectorStoreAvailable();
    if (!available) {
      return res.status(503).json({
        error: 'Vector store not available',
      });
    }

    const client = getVectorStoreClient();
    const deleted = await client.deleteConsentSession(sessionId);
    res.json({ deleted, session_id: sessionId });
  } catch (error) {
    res.status(500).json({ error: String(error) });
  }
});

// Apply preset to consent session
app.post('/api/consent/session/:sessionId/apply-preset', async (req, res) => {
  try {
    const { sessionId } = req.params;
    const { preset } = req.body;

    if (!preset) {
      return res.status(400).json({ error: 'Preset is required' });
    }

    const available = await isVectorStoreAvailable();
    if (!available) {
      return res.status(503).json({
        error: 'Vector store not available',
      });
    }

    const client = getVectorStoreClient();
    const session = await client.applyConsentPreset(sessionId, preset);
    res.json(session);
  } catch (error) {
    res.status(500).json({ error: String(error) });
  }
});

// Chat API Routes

// Get chat status (LLM availability, model info)
app.get('/api/chat/status', async (_req, res) => {
  try {
    const status = await getChatStatus();
    res.json(status);
  } catch (error) {
    res.status(500).json({ error: String(error) });
  }
});

// Non-streaming chat endpoint
app.post('/api/chat', async (req, res) => {
  try {
    const request: ChatRequest = req.body;
    if (!request.message) {
      return res.status(400).json({ error: 'Message is required' });
    }

    const response = await chat(request);
    res.json(response);
  } catch (error) {
    res.status(500).json({ error: String(error) });
  }
});

// Streaming chat endpoint (SSE)
app.post('/api/chat/stream', async (req, res) => {
  try {
    const request: ChatRequest = req.body;
    if (!request.message) {
      return res.status(400).json({ error: 'Message is required' });
    }

    // Set up SSE headers
    res.setHeader('Content-Type', 'text/event-stream');
    res.setHeader('Cache-Control', 'no-cache');
    res.setHeader('Connection', 'keep-alive');
    res.setHeader('X-Accel-Buffering', 'no');

    // Stream events
    for await (const event of streamChat(request)) {
      res.write(`data: ${JSON.stringify(event)}\n\n`);

      // Flush the response
      if (typeof (res as any).flush === 'function') {
        (res as any).flush();
      }
    }

    // Signal end of stream
    res.write('data: [DONE]\n\n');
    res.end();
  } catch (error) {
    // If headers haven't been sent, send error as JSON
    if (!res.headersSent) {
      res.status(500).json({ error: String(error) });
    } else {
      // Otherwise send as SSE error event
      res.write(`data: ${JSON.stringify({ type: 'error', error: String(error) })}\n\n`);
      res.end();
    }
  }
});

// Get LLM configuration (masked keys)
app.get('/api/chat/config', (_req, res) => {
  try {
    const config = getLLMConfigResponse();
    res.json(config);
  } catch (error) {
    res.status(500).json({ error: String(error) });
  }
});

// Update LLM configuration
app.put('/api/chat/config', (req, res) => {
  try {
    const update: Partial<StoredLLMConfig> = req.body;

    // Validate provider preference
    if (update.preferredProvider && !['auto', 'openai', 'anthropic', 'groq'].includes(update.preferredProvider)) {
      return res.status(400).json({ error: 'Invalid provider preference' });
    }

    const config = updateLLMConfig(update);
    res.json(config);
  } catch (error) {
    res.status(500).json({ error: String(error) });
  }
});

// Test an API key
app.post('/api/chat/config/test', async (req, res) => {
  try {
    const { provider, apiKey } = req.body;

    if (!provider || !apiKey) {
      return res.status(400).json({ error: 'Provider and apiKey are required' });
    }

    if (!['openai', 'anthropic', 'groq'].includes(provider)) {
      return res.status(400).json({ error: 'Invalid provider' });
    }

    const result = await testApiKey(provider, apiKey);
    res.json(result);
  } catch (error) {
    res.status(500).json({ error: String(error) });
  }
});

// LocalSend API Routes (status and control)

// Get LocalSend status
app.get('/api/localsend/status', (_req, res) => {
  if (!localSendServerInstance) {
    return res.json({
      installed: true,
      running: false,
      deviceName: 'MindSage',
      port: 53317,  // LocalSend standard port
      savePath: UPLOADS_DIR,
      platform: `${os.platform()}/${os.arch()}`,
      canAutoStart: true,
    });
  }

  const status = localSendServerInstance.getStatus();
  res.json({
    installed: true,
    running: status.running,
    deviceName: status.deviceInfo.alias,
    port: 53317,  // LocalSend standard port
    savePath: UPLOADS_DIR,
    platform: `${os.platform()}/${os.arch()}`,
    canAutoStart: true,
    ipAddress: status.ipAddress,
  });
});

// Start LocalSend
app.post('/api/localsend/start', async (_req, res) => {
  try {
    if (!localSendServerInstance) {
      localSendServerInstance = getLocalSendServer(UPLOADS_DIR, 'MindSage', autoImportFile);
      localSendServerInstance.registerRoutes(app);
    }
    localSendServerInstance.startDiscovery();
    res.json({ success: true, message: 'LocalSend server started' });
  } catch (error) {
    res.json({ success: false, message: 'Failed to start LocalSend', error: String(error) });
  }
});

// Stop LocalSend
app.post('/api/localsend/stop', async (_req, res) => {
  if (localSendServerInstance) {
    localSendServerInstance.stopDiscovery();
  }
  res.json({ success: true, message: 'LocalSend server stopped' });
});

// Setup LocalSend (no longer needed - built-in)
app.post('/api/localsend/setup', async (_req, res) => {
  res.json({ success: true, message: 'LocalSend is built-in, no setup required' });
});

// Configure LocalSend
app.post('/api/localsend/configure', (req, res) => {
  // Configuration is handled at startup, but we could extend this later
  res.json({ success: true, message: 'Configuration updated' });
});

// API-only server - frontend served separately

// Browser Connector routes
app.use('/api/browser-connector', browserConnectorRouter);

// Universal push/ingest endpoint
const ingestRouter = createIngestRouter(UPLOADS_DIR, autoImportFile);
app.use('/api', ingestRouter);

// Webhook receivers for real-time sync triggers
const webhookConfigPath = path.join(DATA_DIR, 'webhook-config.json');
const webhookRouter = createWebhookRouter(
  (connectorId, config) => {
    if (!runStatuses.get(connectorId)?.running) {
      runCustomScript(connectorId, config);
    }
  },
  (source) => {
    const connectors = loadConnectors();
    const connector = connectors.find(
      c => c.type === 'custom' && (c.config as Record<string, any>)?.script === source
    );
    return connector ? { id: connector.id, config: connector.config as Record<string, any> } : null;
  },
  () => {
    try {
      if (fs.existsSync(webhookConfigPath)) {
        return JSON.parse(fs.readFileSync(webhookConfigPath, 'utf-8'));
      }
    } catch (error) {
      console.error('[webhook] Error reading webhook config:', error);
    }
    return {};
  },
  (updates) => {
    try {
      let existing = {};
      if (fs.existsSync(webhookConfigPath)) {
        existing = JSON.parse(fs.readFileSync(webhookConfigPath, 'utf-8'));
      }
      fs.writeFileSync(webhookConfigPath, JSON.stringify({ ...existing, ...updates }, null, 2));
    } catch (error) {
      console.error('[webhook] Error saving webhook config:', error);
    }
  }
);
app.use('/api', webhookRouter);

const PORT = parseInt(process.env.PORT || '3003', 10);
app.listen(PORT, '0.0.0.0', () => {
  console.log(`MindSage server running at http://0.0.0.0:${PORT}`);
  console.log(`Access from other devices: http://<your-ip>:${PORT}`);
  console.log(`[Security] API authentication enabled. Token stored at: ${API_TOKEN_PATH}`);
  console.log(`[Security] Localhost requests are allowed without authentication.`);
  console.log(`[Security] Remote requests require: Authorization: Bearer <token>`);

  // Auto-start built-in LocalSend server
  console.log('Starting LocalSend protocol server...');
  localSendServerInstance = getLocalSendServer(UPLOADS_DIR, 'MindSage', autoImportFile);
  localSendServerInstance.registerRoutes(app);
  localSendServerInstance.startDiscovery();

  const status = localSendServerInstance.getStatus();
  console.log(`LocalSend server started - device name: "${status.deviceInfo.alias}"`);
  console.log(`LocalSend HTTP API: port 53317 (standard LocalSend port)`);
  console.log(`LocalSend also available on: port 3000 (Express server)`);
  console.log(`Files will be saved to: ${UPLOADS_DIR}`);

  // Auto-start browser connector if configured
  autoStartIfConfigured().catch((error) => {
    console.error('Browser connector auto-start failed:', error);
  });

  // Initialize unified connector scheduler
  connectorScheduler.initialize();
});
