/**
 * Browser Connector API Routes
 * Express routes for browser control and capture handling
 */

import { Router, type Request, type Response } from 'express';
import {
  launchBrowser,
  closeBrowser,
  getStatus,
  isRunning,
  navigateTo,
  navigateToSite,
  loadConfig,
  saveConfig,
  getVncStatus,
  checkVncAvailable,
  isVncEnabled,
  getAuthStatus,
  getAuthenticatedSites,
  setAuthenticatedAt,
  clearAuthentication,
  launchHeadlessSync,
  resolveSyncCompletion,
  isInHeadlessMode,
  startAutoSync,
  stopAutoSync,
  getAutoSyncStatus,
  setAutoSyncInterval,
  onCaptureReceived,
  getSupportedSites,
  getSiteUrl,
  storePendingCookies,
  getPendingCookiesCounts,
  getSessionHealth,
} from './manager.js';
import {
  processCapture,
  getConversations,
  getConversation,
  getCaptureStats,
  reindexAll,
  deleteConversation,
  initializeProcessor,
} from './processor.js';
import type { CapturePayload, LaunchOptions, SupportedSite, SyncResult, ImportedCookie } from './types.js';
import { ALLOWED_COOKIE_DOMAINS, SITE_REGISTRY } from './types.js';

export const browserConnectorRouter = Router();

// Initialize processor on module load
initializeProcessor();

/**
 * POST /api/browser-connector/debug
 * Debug endpoint for extension to report status
 */
browserConnectorRouter.post('/debug', (req: Request, res: Response) => {
  console.log('[browser-connector] DEBUG from extension:', JSON.stringify(req.body));
  res.json({ success: true });
});

/**
 * POST /api/browser-connector/launch
 * Launch the Chromium browser with persistent profile
 */
browserConnectorRouter.post('/launch', async (req: Request, res: Response) => {
  try {
    if (isRunning()) {
      res.json({
        success: true,
        message: 'Browser already running',
        status: getStatus(),
      });
      return;
    }

    const options: LaunchOptions = {
      headed: req.body.headed,
      startUrl: req.body.startUrl,
      vnc: req.body.vnc,
      vncPort: req.body.vncPort,
      wsPort: req.body.wsPort,
    };

    const status = await launchBrowser(options);

    res.json({
      success: true,
      message: 'Browser launched successfully',
      status,
    });
  } catch (error) {
    console.error('[browser-connector] Launch error:', error);
    res.status(500).json({
      success: false,
      error: String(error),
    });
  }
});

/**
 * POST /api/browser-connector/close
 * Close the browser gracefully
 */
browserConnectorRouter.post('/close', async (_req: Request, res: Response) => {
  try {
    await closeBrowser();

    res.json({
      success: true,
      message: 'Browser closed',
    });
  } catch (error) {
    console.error('[browser-connector] Close error:', error);
    res.status(500).json({
      success: false,
      error: String(error),
    });
  }
});

/**
 * GET /api/browser-connector/status
 * Get current browser status
 */
browserConnectorRouter.get('/status', (_req: Request, res: Response) => {
  try {

    const status = getStatus();
    const stats = getCaptureStats();

    res.json({
      ...status,
      captureStats: {
        ...status.captureStats,
        totalCaptured: stats.totalMessages,
        totalConversations: stats.totalConversations,
      },
    });
  } catch (error) {
    console.error('[browser-connector] Status error:', error);
    res.status(500).json({
      success: false,
      error: String(error),
    });
  }
});

/**
 * POST /api/browser-connector/navigate
 * Navigate to a URL
 */
browserConnectorRouter.post('/navigate', async (req: Request, res: Response) => {
  try {
    const { url } = req.body;

    if (!url) {
      res.status(400).json({
        success: false,
        error: 'URL is required',
      });
      return;
    }

    await navigateTo(url);

    res.json({
      success: true,
      message: `Navigated to ${url}`,
    });
  } catch (error) {
    console.error('[browser-connector] Navigate error:', error);
    res.status(500).json({
      success: false,
      error: String(error),
    });
  }
});

/**
 * POST /api/browser-connector/capture
 * Receive captured data from extension
 */
browserConnectorRouter.post('/capture', async (req: Request, res: Response) => {
  try {
    const payload = req.body as CapturePayload;

    // Validate payload
    if (!payload.site || !payload.conversationId || !payload.messages) {
      res.status(400).json({
        success: false,
        error: 'Invalid capture payload: site, conversationId, and messages are required',
      });
      return;
    }

    // Validate site
    const validSites = getSupportedSites();
    if (!validSites.includes(payload.site as SupportedSite)) {
      res.status(400).json({
        success: false,
        error: `Invalid site: ${payload.site}. Must be one of: ${validSites.join(', ')}`,
      });
      return;
    }

    const result = await processCapture(payload);

    // Track capture for headless sync completion detection
    onCaptureReceived();

    // When we receive a capture, the user is authenticated for that site
    // This is more reliable than waiting for the extension's report-auth POST
    setAuthenticatedAt(payload.site);

    res.json({
      success: true,
      ...result,
    });
  } catch (error) {
    console.error('[browser-connector] Capture error:', error);
    res.status(500).json({
      success: false,
      error: String(error),
    });
  }
});

/**
 * GET /api/browser-connector/conversations
 * List captured conversations
 */
browserConnectorRouter.get('/conversations', (req: Request, res: Response) => {
  try {
    const site = req.query.site as SupportedSite | undefined;
    const limit = req.query.limit ? parseInt(req.query.limit as string) : undefined;
    const offset = req.query.offset ? parseInt(req.query.offset as string) : undefined;

    const conversations = getConversations({ site, limit, offset });

    // Return summary without full messages
    const summaries = conversations.map(c => ({
      id: c.id,
      site: c.site,
      title: c.title,
      url: c.url,
      messageCount: c.messageCount,
      indexed: c.indexed,
      createdAt: c.createdAt,
      updatedAt: c.updatedAt,
    }));

    // Get total count - if site filter is applied, get site-specific total
    let total: number;
    if (site) {
      const stats = getCaptureStats();
      total = stats.bySite?.[site]?.conversations ?? summaries.length;
    } else {
      total = getCaptureStats().totalConversations;
    }

    res.json({
      conversations: summaries,
      total,
    });
  } catch (error) {
    console.error('[browser-connector] List conversations error:', error);
    res.status(500).json({
      success: false,
      error: String(error),
    });
  }
});

/**
 * GET /api/browser-connector/conversations/:id
 * Get a specific conversation with full messages
 */
browserConnectorRouter.get('/conversations/:id', (req: Request, res: Response) => {
  try {
    const conversation = getConversation(req.params.id);

    if (!conversation) {
      res.status(404).json({
        success: false,
        error: 'Conversation not found',
      });
      return;
    }

    res.json(conversation);
  } catch (error) {
    console.error('[browser-connector] Get conversation error:', error);
    res.status(500).json({
      success: false,
      error: String(error),
    });
  }
});

/**
 * DELETE /api/browser-connector/conversations/:id
 * Delete a conversation
 */
browserConnectorRouter.delete('/conversations/:id', (req: Request, res: Response) => {
  try {
    const deleted = deleteConversation(req.params.id);

    if (!deleted) {
      res.status(404).json({
        success: false,
        error: 'Conversation not found',
      });
      return;
    }

    res.json({
      success: true,
      message: 'Conversation deleted',
    });
  } catch (error) {
    console.error('[browser-connector] Delete conversation error:', error);
    res.status(500).json({
      success: false,
      error: String(error),
    });
  }
});

/**
 * POST /api/browser-connector/reindex
 * Re-index all conversations to vector store
 */
browserConnectorRouter.post('/reindex', async (_req: Request, res: Response) => {
  try {
    const result = await reindexAll();

    res.json({
      success: true,
      ...result,
      message: `Re-indexed ${result.success} conversations, ${result.failed} failed`,
    });
  } catch (error) {
    console.error('[browser-connector] Reindex error:', error);
    res.status(500).json({
      success: false,
      error: String(error),
    });
  }
});

/**
 * GET /api/browser-connector/stats
 * Get capture statistics
 */
browserConnectorRouter.get('/stats', (_req: Request, res: Response) => {
  try {
    const stats = getCaptureStats();
    res.json(stats);
  } catch (error) {
    console.error('[browser-connector] Stats error:', error);
    res.status(500).json({
      success: false,
      error: String(error),
    });
  }
});

/**
 * GET /api/browser-connector/config
 * Get browser connector configuration
 */
browserConnectorRouter.get('/config', (_req: Request, res: Response) => {
  try {
    const config = loadConfig();
    res.json(config);
  } catch (error) {
    console.error('[browser-connector] Config error:', error);
    res.status(500).json({
      success: false,
      error: String(error),
    });
  }
});

/**
 * PUT /api/browser-connector/config
 * Update browser connector configuration
 */
browserConnectorRouter.put('/config', (req: Request, res: Response) => {
  try {
    const config = saveConfig(req.body);

    res.json({
      success: true,
      config,
    });
  } catch (error) {
    console.error('[browser-connector] Config update error:', error);
    res.status(500).json({
      success: false,
      error: String(error),
    });
  }
});

/**
 * GET /api/browser-connector/vnc/status
 * Get VNC status and connection URL
 */
browserConnectorRouter.get('/vnc/status', (_req: Request, res: Response) => {
  try {
    const vncStatus = getVncStatus();
    res.json(vncStatus);
  } catch (error) {
    console.error('[browser-connector] VNC status error:', error);
    res.status(500).json({
      success: false,
      error: String(error),
    });
  }
});

/**
 * GET /api/browser-connector/vnc/check
 * Check if VNC dependencies are installed
 */
browserConnectorRouter.get('/vnc/check', (_req: Request, res: Response) => {
  try {
    const result = checkVncAvailable();
    res.json({
      available: result.available,
      missing: result.missing,
      installCommand: result.missing.length > 0
        ? 'sudo apt install xvfb x11vnc novnc websockify'
        : null,
    });
  } catch (error) {
    console.error('[browser-connector] VNC check error:', error);
    res.status(500).json({
      success: false,
      error: String(error),
    });
  }
});

/**
 * GET /api/browser-connector/session-health
 * Get session health for all sites, including expiry estimates and cumulative stats
 */
browserConnectorRouter.get('/session-health', (_req: Request, res: Response) => {
  try {
    res.json(getSessionHealth());
  } catch (error) {
    console.error('[browser-connector] Session health error:', error);
    res.status(500).json({ error: String(error) });
  }
});

/**
 * GET /api/browser-connector/auth-status
 * Get authentication status (whether user has logged in before)
 * @query site - Optional site to check (chatgpt, claude, gemini)
 */
browserConnectorRouter.get('/auth-status', (req: Request, res: Response) => {
  try {
    const site = req.query.site as SupportedSite | undefined;
    const status = getAuthStatus(site);
    res.json(status);
  } catch (error) {
    console.error('[browser-connector] Auth status error:', error);
    res.status(500).json({
      success: false,
      error: String(error),
    });
  }
});

/**
 * GET /api/browser-connector/sites
 * Get list of all supported sites with auth status
 */
browserConnectorRouter.get('/sites', (_req: Request, res: Response) => {
  try {
    const supportedSites = getSupportedSites();
    const authenticatedSites = getAuthenticatedSites();

    const sites = supportedSites.map(site => ({
      id: site,
      name: SITE_REGISTRY[site].name,
      url: getSiteUrl(site),
      cookieDomains: SITE_REGISTRY[site].cookieDomains,
      authenticated: authenticatedSites.includes(site),
      authStatus: getAuthStatus(site),
    }));

    res.json({
      sites,
      authenticatedSites,
    });
  } catch (error) {
    console.error('[browser-connector] Sites error:', error);
    res.status(500).json({
      success: false,
      error: String(error),
    });
  }
});

/**
 * POST /api/browser-connector/report-auth
 * Called by extension when authentication is detected
 */
browserConnectorRouter.post('/report-auth', (req: Request, res: Response) => {
  try {
    const { site, authenticated } = req.body;

    console.log(`[browser-connector] Received auth report: site=${site}, authenticated=${authenticated}`);

    if (!site) {
      res.status(400).json({
        success: false,
        error: 'Site is required',
      });
      return;
    }

    if (authenticated) {
      setAuthenticatedAt(site);
      console.log(`[browser-connector] ✓ Auth recorded for ${site}`);
    } else {
      console.log(`[browser-connector] Auth report for ${site}: not authenticated`);
    }

    res.json({
      success: true,
      message: `Auth status reported for ${site}`,
    });
  } catch (error) {
    console.error('[browser-connector] Report auth error:', error);
    res.status(500).json({
      success: false,
      error: String(error),
    });
  }
});

/**
 * DELETE /api/browser-connector/auth
 * Clear authentication (for testing or re-login)
 * @query site - Optional site to clear (clears all if not specified)
 */
browserConnectorRouter.delete('/auth', (req: Request, res: Response) => {
  try {
    const site = req.query.site as SupportedSite | undefined;
    clearAuthentication(site);
    res.json({
      success: true,
      message: site ? `Authentication cleared for ${site}` : 'All authentication cleared',
    });
  } catch (error) {
    console.error('[browser-connector] Clear auth error:', error);
    res.status(500).json({
      success: false,
      error: String(error),
    });
  }
});

/**
 * POST /api/browser-connector/sync
 * Start a headless sync (requires prior authentication)
 * @body site - Optional site to sync (defaults to chatgpt)
 */
browserConnectorRouter.post('/sync', async (req: Request, res: Response) => {
  try {
    const site = req.body.site as SupportedSite | undefined;
    const targetSite = site || 'chatgpt';

    const authStatus = getAuthStatus(targetSite);

    if (!authStatus.authenticated) {
      res.status(401).json({
        success: false,
        error: `Login required for ${targetSite}. Please use VNC mode to log in first.`,
        requiresVnc: true,
        site: targetSite,
      });
      return;
    }

    console.log(`[browser-connector] Starting headless sync for ${targetSite}...`);
    const result = await launchHeadlessSync(targetSite);

    res.json({
      success: result.success,
      site: targetSite,
      ...result,
    });
  } catch (error) {
    console.error('[browser-connector] Sync error:', error);
    res.status(500).json({
      success: false,
      error: String(error),
    });
  }
});

/**
 * POST /api/browser-connector/navigate-to-site
 * Navigate an existing browser session to a specific site (for VNC reuse)
 */
browserConnectorRouter.post('/navigate-to-site', async (req: Request, res: Response) => {
  try {
    const { site, forSync } = req.body;

    if (!site) {
      res.status(400).json({
        success: false,
        error: 'Site is required (chatgpt, claude, gemini)',
      });
      return;
    }

    const validSites = getSupportedSites();
    if (!validSites.includes(site as SupportedSite)) {
      res.status(400).json({
        success: false,
        error: `Invalid site: ${site}. Must be one of: ${validSites.join(', ')}`,
      });
      return;
    }

    if (!isRunning()) {
      res.status(400).json({
        success: false,
        error: 'Browser not running. Launch browser first.',
      });
      return;
    }

    await navigateToSite(site, forSync);

    res.json({
      success: true,
      message: `Navigated to ${site}`,
      url: getSiteUrl(site),
    });
  } catch (error) {
    console.error('[browser-connector] Navigate to site error:', error);
    res.status(500).json({
      success: false,
      error: String(error),
    });
  }
});

/**
 * POST /api/browser-connector/sync-complete
 * Called by extension when sync completes (for headless mode)
 */
browserConnectorRouter.post('/sync-complete', (req: Request, res: Response) => {
  try {
    const result = req.body as SyncResult;

    console.log('[browser-connector] Sync complete received:', result);

    // Only process if we're in headless mode
    if (isInHeadlessMode()) {
      resolveSyncCompletion(result);
    }

    res.json({
      success: true,
      message: 'Sync completion acknowledged',
    });
  } catch (error) {
    console.error('[browser-connector] Sync complete error:', error);
    res.status(500).json({
      success: false,
      error: String(error),
    });
  }
});

/**
 * GET /api/browser-connector/auto-sync
 * Get auto-sync status
 */
browserConnectorRouter.get('/auto-sync', (_req: Request, res: Response) => {
  try {
    const status = getAutoSyncStatus();
    res.json(status);
  } catch (error) {
    console.error('[browser-connector] Auto-sync status error:', error);
    res.status(500).json({
      success: false,
      error: String(error),
    });
  }
});

/**
 * POST /api/browser-connector/auto-sync/start
 * Start automatic sync scheduling
 */
browserConnectorRouter.post('/auto-sync/start', (req: Request, res: Response) => {
  try {
    const authStatus = getAuthStatus();

    if (!authStatus.authenticated) {
      res.status(401).json({
        success: false,
        error: 'Login required. Please use VNC mode to log in first.',
        requiresVnc: true,
      });
      return;
    }

    // Optionally set interval from request body
    if (req.body.intervalHours && typeof req.body.intervalHours === 'number') {
      setAutoSyncInterval(req.body.intervalHours);
    }

    startAutoSync();

    res.json({
      success: true,
      message: 'Auto-sync started',
      status: getAutoSyncStatus(),
    });
  } catch (error) {
    console.error('[browser-connector] Auto-sync start error:', error);
    res.status(500).json({
      success: false,
      error: String(error),
    });
  }
});

/**
 * POST /api/browser-connector/auto-sync/stop
 * Stop automatic sync scheduling
 */
browserConnectorRouter.post('/auto-sync/stop', (_req: Request, res: Response) => {
  try {
    stopAutoSync();

    res.json({
      success: true,
      message: 'Auto-sync stopped',
    });
  } catch (error) {
    console.error('[browser-connector] Auto-sync stop error:', error);
    res.status(500).json({
      success: false,
      error: String(error),
    });
  }
});

/**
 * PUT /api/browser-connector/auto-sync/interval
 * Update auto-sync interval
 */
browserConnectorRouter.put('/auto-sync/interval', (req: Request, res: Response) => {
  try {
    const { hours } = req.body;

    if (typeof hours !== 'number' || hours < 0.5 || hours > 24) {
      res.status(400).json({
        success: false,
        error: 'Invalid interval. Must be between 0.5 and 24 hours.',
      });
      return;
    }

    setAutoSyncInterval(hours);

    res.json({
      success: true,
      message: `Auto-sync interval set to ${hours} hours`,
      status: getAutoSyncStatus(),
    });
  } catch (error) {
    console.error('[browser-connector] Auto-sync interval error:', error);
    res.status(500).json({
      success: false,
      error: String(error),
    });
  }
});

/**
 * Validate that the request comes from a private/local network
 */
function isLocalNetwork(req: Request): boolean {
  const ip = req.ip || req.socket?.remoteAddress || '';
  // Normalize IPv6-mapped IPv4
  const normalizedIp = ip.replace(/^::ffff:/, '');

  return (
    normalizedIp === '127.0.0.1' ||
    normalizedIp === '::1' ||
    normalizedIp === 'localhost' ||
    normalizedIp.startsWith('192.168.') ||
    normalizedIp.startsWith('10.') ||
    /^172\.(1[6-9]|2\d|3[01])\./.test(normalizedIp)
  );
}

/**
 * Sanitize a cookie object — keep only expected fields
 */
function sanitizeCookie(cookie: any): ImportedCookie | null {
  if (!cookie || typeof cookie.name !== 'string' || typeof cookie.value !== 'string') {
    return null;
  }

  return {
    name: cookie.name,
    value: cookie.value,
    domain: String(cookie.domain || ''),
    path: String(cookie.path || '/'),
    secure: Boolean(cookie.secure),
    httpOnly: Boolean(cookie.httpOnly),
    sameSite: ['Strict', 'Lax', 'None', 'no_restriction', 'unspecified'].includes(cookie.sameSite)
      ? cookie.sameSite
      : undefined,
    expirationDate: typeof cookie.expirationDate === 'number' ? cookie.expirationDate : undefined,
  };
}

/**
 * POST /api/browser-connector/import-cookies
 * Accept cookies from companion extension for CDP injection
 */
browserConnectorRouter.post('/import-cookies', async (req: Request, res: Response) => {
  try {
    // Validate local network origin
    if (!isLocalNetwork(req)) {
      console.warn(`[browser-connector] Rejected cookie import from non-local IP: ${req.ip}`);
      res.status(403).json({
        success: false,
        error: 'Cookie import only allowed from local network',
      });
      return;
    }

    const { site, cookies } = req.body;

    // Validate site
    const validSites = getSupportedSites();
    if (!site || !validSites.includes(site as SupportedSite)) {
      res.status(400).json({
        success: false,
        error: `Invalid site. Must be one of: ${validSites.join(', ')}`,
      });
      return;
    }

    // Validate cookies array
    if (!Array.isArray(cookies) || cookies.length === 0) {
      res.status(400).json({
        success: false,
        error: 'Cookies array is required and must not be empty',
      });
      return;
    }

    // Sanitize cookies
    const sanitized: ImportedCookie[] = [];
    for (const raw of cookies) {
      const clean = sanitizeCookie(raw);
      if (clean) {
        sanitized.push(clean);
      }
    }

    if (sanitized.length === 0) {
      res.status(400).json({
        success: false,
        error: 'No valid cookies found after sanitization',
      });
      return;
    }

    // Filter to allowed domains for this site
    const allowedDomains = ALLOWED_COOKIE_DOMAINS[site as SupportedSite] || [];
    const domainFiltered = sanitized.filter(c => {
      const cookieDomain = c.domain.startsWith('.') ? c.domain : `.${c.domain}`;
      return allowedDomains.some(d => {
        const allowed = d.startsWith('.') ? d : `.${d}`;
        return cookieDomain === allowed || cookieDomain.endsWith(allowed);
      });
    });

    // Log cookie names only (never values)
    console.log(`[browser-connector] Cookie import for ${site}: ${domainFiltered.length} cookies accepted (names: ${domainFiltered.map(c => c.name).join(', ')})`);

    // Store pending cookies
    storePendingCookies(site as SupportedSite, domainFiltered);

    // Return success immediately
    res.json({
      success: true,
      cookiesImported: domainFiltered.length,
      site,
    });

    // Trigger headless sync in the background
    console.log(`[browser-connector] Triggering headless sync for ${site} after cookie import...`);
    launchHeadlessSync(site as SupportedSite).then(result => {
      if (result.success) {
        console.log(`[browser-connector] Post-import sync complete: ${result.synced} synced`);
      } else {
        console.error(`[browser-connector] Post-import sync failed: ${result.error}`);
      }
    }).catch(err => {
      console.error(`[browser-connector] Post-import sync error:`, err);
    });

  } catch (error) {
    console.error('[browser-connector] Import cookies error:', error);
    res.status(500).json({
      success: false,
      error: String(error),
    });
  }
});

/**
 * GET /api/browser-connector/pending-cookies
 * Get count of pending cookies per site (for debugging, no values)
 */
browserConnectorRouter.get('/pending-cookies', (_req: Request, res: Response) => {
  try {
    const counts = getPendingCookiesCounts();
    res.json({ pendingCookies: counts });
  } catch (error) {
    console.error('[browser-connector] Pending cookies error:', error);
    res.status(500).json({
      success: false,
      error: String(error),
    });
  }
});
