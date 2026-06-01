/**
 * Webhook Receiver for MindSage
 *
 * Handles incoming webhooks from external services (Notion, Readwise, etc.)
 * to trigger real-time sync when content changes.
 *
 * Requirements:
 *   - Notion webhooks require a publicly accessible HTTPS endpoint.
 *     On a local Jetson device, use a tunnel (e.g., ngrok, Cloudflare Tunnel)
 *     or set up auto-sync via the scheduler as an alternative.
 *   - Readwise webhooks are configured at readwise.io/webhooks
 *
 * Security:
 *   - Notion: HMAC-SHA256 signature verification via X-Notion-Signature header
 *   - Readwise: Shared secret verification via X-Readwise-Secret header
 *   - Both endpoints reject requests when no verification token is configured
 */

import { Router, Request, Response } from 'express';
import { createHmac, timingSafeEqual } from 'crypto';

// --- Types ---

export interface WebhookConfig {
  notionVerificationToken?: string;
  readwiseVerificationToken?: string;
}

type SyncTrigger = (connectorId: string, config: Record<string, any>) => void;
type ConnectorLookup = (source: string) => { id: string; config: Record<string, any> } | null;
type WebhookConfigSetter = (config: Partial<WebhookConfig>) => void;

// --- Constants ---

const NOTION_SYNC_TRIGGER_EVENTS = [
  'page.content_updated',
  'page.created',
  'page.property_item_updated',
  'database.schema_updated',
  'data_source.schema_updated',
];

// --- Signature Verification ---

function verifyHmacSignature(
  body: string,
  signature: string | undefined,
  secret: string
): boolean {
  if (!signature || !secret) return false;

  const calculated = `sha256=${createHmac('sha256', secret)
    .update(body)
    .digest('hex')}`;

  try {
    return timingSafeEqual(
      Buffer.from(calculated),
      Buffer.from(signature)
    );
  } catch {
    return false;
  }
}

// --- Router Factory ---

export function createWebhookRouter(
  triggerSync: SyncTrigger,
  findConnector: ConnectorLookup,
  getWebhookConfig: () => WebhookConfig,
  setWebhookConfig: WebhookConfigSetter
): Router {
  const router = Router();

  /**
   * POST /api/webhooks/notion
   *
   * Receives Notion webhook events. Handles the initial verification handshake,
   * then triggers sync on content change events.
   *
   * Security: Rejects all non-verification requests unless a verification token
   * is configured. Verifies HMAC-SHA256 signature on every event.
   */
  router.post('/webhooks/notion', (req: Request, res: Response) => {
    const config = getWebhookConfig();

    // Handle Notion verification handshake
    // Notion sends { verification_token: "secret_..." } during subscription setup
    if (req.body.verification_token && typeof req.body.verification_token === 'string') {
      // Only accept if we don't already have a token, or if it matches the existing one
      if (config.notionVerificationToken && config.notionVerificationToken !== req.body.verification_token) {
        console.warn('[webhook] Notion verification rejected: token mismatch with existing config');
        res.status(403).json({ error: 'Verification token mismatch' });
        return;
      }

      // Store the token for future HMAC verification
      setWebhookConfig({ notionVerificationToken: req.body.verification_token });
      console.log('[webhook] Notion verification token stored');
      res.status(200).json({ ok: true });
      return;
    }

    // All non-verification requests require a configured token
    if (!config.notionVerificationToken) {
      console.warn('[webhook] Notion webhook rejected: no verification token configured');
      res.status(403).json({ error: 'Webhook not configured. Complete Notion verification first.' });
      return;
    }

    // Verify HMAC-SHA256 signature
    const signature = req.headers['x-notion-signature'] as string | undefined;
    if (!verifyHmacSignature(JSON.stringify(req.body), signature, config.notionVerificationToken)) {
      console.warn('[webhook] Notion signature verification failed');
      res.status(401).json({ error: 'Invalid signature' });
      return;
    }

    // Process the event
    const eventType = req.body.type;
    console.log(`[webhook] Notion event: ${eventType}`);

    if (NOTION_SYNC_TRIGGER_EVENTS.includes(eventType)) {
      const connector = findConnector('notion');
      if (connector) {
        console.log(`[webhook] Triggering Notion sync for connector ${connector.id}`);
        try {
          triggerSync(connector.id, connector.config);
        } catch (error) {
          console.error('[webhook] Error triggering Notion sync:', error);
        }
      } else {
        console.warn('[webhook] Notion event received but no Notion connector configured');
      }
    }

    res.status(200).json({ ok: true });
  });

  /**
   * POST /api/webhooks/readwise
   *
   * Receives Readwise webhook events for new highlights/documents.
   * Requires a shared secret in X-Readwise-Secret header.
   */
  router.post('/webhooks/readwise', (req: Request, res: Response) => {
    const config = getWebhookConfig();

    // Require a configured verification token
    if (!config.readwiseVerificationToken) {
      console.warn('[webhook] Readwise webhook rejected: no verification token configured');
      res.status(403).json({ error: 'Webhook not configured. Set readwiseVerificationToken first.' });
      return;
    }

    // Verify shared secret header
    const providedSecret = req.headers['x-readwise-secret'] as string | undefined;
    if (!providedSecret || providedSecret !== config.readwiseVerificationToken) {
      console.warn('[webhook] Readwise secret verification failed');
      res.status(401).json({ error: 'Invalid or missing secret' });
      return;
    }

    const eventType = req.body.action || req.body.type || 'unknown';
    console.log(`[webhook] Readwise event: ${eventType}`);

    const connector = findConnector('readwise');
    if (connector) {
      console.log(`[webhook] Triggering Readwise sync for connector ${connector.id}`);
      try {
        triggerSync(connector.id, connector.config);
      } catch (error) {
        console.error('[webhook] Error triggering Readwise sync:', error);
      }
    } else {
      console.warn('[webhook] Readwise event received but no Readwise connector configured');
    }

    res.status(200).json({ ok: true });
  });

  /**
   * GET /api/webhooks/status
   */
  router.get('/webhooks/status', (_req: Request, res: Response) => {
    const config = getWebhookConfig();
    res.json({
      notion: {
        configured: !!config.notionVerificationToken,
        endpoint: '/api/webhooks/notion',
      },
      readwise: {
        configured: !!config.readwiseVerificationToken,
        endpoint: '/api/webhooks/readwise',
      },
      note: 'Notion webhooks require a publicly accessible HTTPS endpoint. Use a tunnel (ngrok, Cloudflare Tunnel) on local deployments.',
    });
  });

  return router;
}
