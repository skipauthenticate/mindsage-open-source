/**
 * Universal Push Endpoint for MindSage
 *
 * Allows any external tool (Apple Shortcuts, curl, Tasker, cron scripts, etc.)
 * to push data directly into MindSage for indexing.
 *
 * Endpoints:
 *   POST /api/ingest       — Push single item (JSON, text, or file)
 *   POST /api/ingest/batch — Push multiple items at once
 */

import { Router, Request, Response, NextFunction } from 'express';
import multer from 'multer';
import * as fs from 'fs';
import * as path from 'path';
import {
  getVectorStoreClient,
  isVectorStoreAvailable,
} from '../vector-store-client.js';

interface IngestItem {
  text: string;
  title?: string;
  source?: string;
  metadata?: Record<string, any>;
  tags?: string[];
}

interface IngestResult {
  success: boolean;
  documentId?: number;
  isDuplicate?: boolean;
  existingDocumentId?: number;
  message?: string;
}

/**
 * Sanitize a filename to prevent path traversal and edge cases.
 * Strips directory components and replaces unsafe characters.
 * Returns a generated fallback name if the result is empty or unsafe.
 */
function sanitizeFilename(filename: string): string {
  // Strip directory components (handles both / and \)
  let base = path.basename(filename);
  // Remove null bytes and other control characters
  base = base.replace(/[\x00-\x1f]/g, '');
  // Reject empty, dot-only, or whitespace-only names
  if (!base || /^\.{1,2}$/.test(base) || !base.trim()) {
    return `ingest-${Date.now()}`;
  }
  return base;
}

/**
 * Build document metadata from user-supplied fields.
 * Ensures system fields (source, ingestedAt) cannot be overridden by user metadata.
 */
function buildMetadata(item: IngestItem): Record<string, any> {
  const docMetadata: Record<string, any> = {
    ...(item.metadata || {}),
    // System fields applied AFTER user metadata to prevent override
    source: item.source || 'ingest',
    ingestedAt: new Date().toISOString(),
  };
  if (item.title) docMetadata.title = item.title;
  if (item.tags && Array.isArray(item.tags) && item.tags.length > 0) {
    docMetadata.tags = item.tags.join(', ');
  }
  return docMetadata;
}

// Maximum text size for a single item (1MB)
const MAX_TEXT_SIZE = 1 * 1024 * 1024;

// Create router
export function createIngestRouter(
  uploadsDir: string,
  autoImportFile: (filename: string, sourcePath: string) => void
): Router {
  const router = Router();

  // Multer for file uploads to ingest endpoint
  const ingestStorage = multer.diskStorage({
    destination: (_req, _file, cb) => {
      if (!fs.existsSync(uploadsDir)) {
        fs.mkdirSync(uploadsDir, { recursive: true });
      }
      cb(null, uploadsDir);
    },
    filename: (_req, file, cb) => {
      const safeName = sanitizeFilename(file.originalname || `ingest-${Date.now()}`);
      const filePath = path.join(uploadsDir, safeName);
      if (fs.existsSync(filePath)) {
        const ext = path.extname(safeName);
        const base = path.basename(safeName, ext);
        cb(null, `${base}-${Date.now()}${ext}`);
      } else {
        cb(null, safeName);
      }
    },
  });

  const ingestUpload = multer({
    storage: ingestStorage,
    limits: { fileSize: 500 * 1024 * 1024 }, // 500MB for ingest
  });

  /**
   * Multer error handler middleware.
   * Returns proper JSON errors for file size limit and other multer errors
   * instead of leaking raw error objects.
   */
  function handleMulterError(err: any, _req: Request, res: Response, next: NextFunction): void {
    if (err instanceof multer.MulterError) {
      if (err.code === 'LIMIT_FILE_SIZE') {
        res.status(413).json({ error: 'File exceeds maximum size of 500MB' });
        return;
      }
      res.status(400).json({ error: `Upload error: ${err.code}` });
      return;
    }
    next(err);
  }

  /**
   * POST /api/ingest
   *
   * Push a single item into MindSage for indexing.
   *
   * Content types:
   *   application/json:       { text, title?, source?, metadata?, tags? }
   *   text/plain:             Raw text body
   *   multipart/form-data:    File upload (uses existing import pipeline)
   *
   * JSON/text body limits are handled by the app-level express.json({ limit: '10mb' })
   * and express.text({ limit: '10mb' }) middleware. Per-item text content is further
   * limited to 1MB by MAX_TEXT_SIZE validation below.
   */
  router.post(
    '/ingest',
    ingestUpload.single('file'),
    handleMulterError,
    async (req: Request, res: Response) => {
      try {
        // Handle file upload
        if (req.file) {
          const vsAvailable = await isVectorStoreAvailable();
          autoImportFile(req.file.filename, req.file.path);
          return res.json({
            success: true,
            message: `File "${req.file.filename}" queued for indexing`,
            filename: req.file.filename,
            ...(!vsAvailable && { warning: 'Vector store is currently unavailable. File saved but indexing will be retried later.' }),
          });
        }

        // Handle plain text (Content-Type: text/plain)
        if (typeof req.body === 'string') {
          const text = req.body.trim();
          if (!text) {
            return res.status(400).json({ error: 'Empty text body' });
          }
          if (text.length > MAX_TEXT_SIZE) {
            return res.status(413).json({ error: `Text exceeds maximum size of ${MAX_TEXT_SIZE / 1024 / 1024}MB` });
          }

          // Use buildMetadata for consistency with JSON path
          const metadata = buildMetadata({
            text,
            source: 'ingest',
            title: text.split('\n')[0].substring(0, 100),
          });
          const result = await indexText(text, metadata);
          return res.json(result);
        }

        // Handle JSON (Content-Type: application/json)
        if (req.body && typeof req.body === 'object') {
          const item = req.body as IngestItem;

          if (!item.text || typeof item.text !== 'string') {
            return res.status(400).json({ error: 'Missing or invalid "text" field' });
          }
          if (item.text.length > MAX_TEXT_SIZE) {
            return res.status(413).json({ error: `Text exceeds maximum size of ${MAX_TEXT_SIZE / 1024 / 1024}MB` });
          }

          const docMetadata = buildMetadata(item);
          const docText = item.title ? `${item.title}\n\n${item.text}` : item.text;
          const result = await indexText(docText, docMetadata);
          return res.json(result);
        }

        return res.status(400).json({
          error: 'Unsupported content type. Use application/json, text/plain, or multipart/form-data',
        });
      } catch (error: any) {
        console.error('[ingest] Error:', error);
        if (error.message === 'Vector store not available') {
          return res.status(503).json({ error: 'Vector store not available' });
        }
        return res.status(500).json({ error: 'Ingest failed' });
      }
    },
  );

  /**
   * POST /api/ingest/batch
   *
   * Push multiple items at once.
   * Body: { items: [{ text, title?, source?, metadata?, tags? }, ...] }
   *
   * Body limit is handled by the app-level express.json({ limit: '10mb' }) middleware.
   * This means total batch payload is limited to 10MB. Each individual item's text
   * is further limited to 1MB by MAX_TEXT_SIZE validation.
   */
  router.post('/ingest/batch', async (req: Request, res: Response) => {
    try {
      const { items } = req.body;

      if (!Array.isArray(items) || items.length === 0) {
        return res.status(400).json({ error: 'Missing or empty "items" array' });
      }

      if (items.length > 100) {
        return res.status(400).json({ error: 'Maximum 100 items per batch' });
      }

      // Validate all items have text before processing
      for (let i = 0; i < items.length; i++) {
        if (!items[i].text || typeof items[i].text !== 'string') {
          return res.status(400).json({ error: `Item ${i} is missing or has invalid "text" field` });
        }
        if (items[i].text.length > MAX_TEXT_SIZE) {
          return res.status(413).json({ error: `Item ${i} text exceeds maximum size of ${MAX_TEXT_SIZE / 1024 / 1024}MB` });
        }
      }

      const available = await isVectorStoreAvailable();
      if (!available) {
        return res.status(503).json({ error: 'Vector store not available' });
      }

      const client = getVectorStoreClient();
      const documents = items.map((item: IngestItem) => ({
        text: item.title ? `${item.title}\n\n${item.text}` : item.text,
        metadata: buildMetadata(item),
      }));

      const result = await client.addDocuments(documents);

      return res.json({
        success: true,
        indexed: result.document_ids.length,
        duplicatesSkipped: result.duplicates_skipped,
        documentIds: result.document_ids,
      });
    } catch (error: any) {
      console.error('[ingest/batch] Error:', error);
      return res.status(500).json({ error: 'Batch ingest failed' });
    }
  });

  return router;
}

/**
 * Index text directly to the vector store.
 */
async function indexText(
  text: string,
  metadata: Record<string, any>
): Promise<IngestResult> {
  const available = await isVectorStoreAvailable();
  if (!available) {
    throw new Error('Vector store not available');
  }

  const client = getVectorStoreClient();
  const result = await client.addDocument(text, metadata);

  if (result.is_duplicate) {
    return {
      success: true,
      isDuplicate: true,
      existingDocumentId: result.existing_document_id,
      message: 'Content already indexed (duplicate skipped)',
    };
  }

  return {
    success: true,
    documentId: result.document_id,
    isDuplicate: false,
  };
}
