/**
 * Browser Connector Manager
 * Launches system Chrome/Chromium with persistent profile and extension
 * Supports VNC mode for headless remote access via noVNC
 *
 * Uses direct Chrome launch instead of Playwright to avoid bot detection.
 */

import { spawn, ChildProcess, execSync } from 'child_process';
import * as fs from 'fs';
import * as path from 'path';
import { fileURLToPath } from 'url';
import {
  type BrowserConnectorConfig,
  type BrowserStatus,
  type LaunchOptions,
  type CaptureEventListener,
  type CaptureEvent,
  type AuthStatus,
  type SyncResult,
  type SupportedSite,
  type ImportedCookie,
  ALLOWED_COOKIE_DOMAINS,
  SITE_URLS,
  getSupportedSiteIds,
} from './types.js';
import WebSocket from 'ws';

// ES module compatibility
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Paths
const DATA_DIR = path.join(process.cwd(), 'data', 'browser-connector');
const PROFILE_DIR = path.join(DATA_DIR, 'chromium-profile');
const CONFIG_FILE = path.join(DATA_DIR, 'config.json');
// Extension is in source directory, not dist - use process.cwd() for reliable path
const EXTENSION_DIR = path.join(process.cwd(), 'server', 'browser-connector', 'extension');

// State
let browserProcess: ChildProcess | null = null;
let launchedAt: string | null = null;
let sessionCaptureCount = 0;

// VNC state
let xvfbProcess: ChildProcess | null = null;
let x11vncProcess: ChildProcess | null = null;
let websockifyProcess: ChildProcess | null = null;
let vncEnabled = false;
let vncDisplay = ':99';
let vncPort = 5901;  // Use 5901 to avoid conflict with vino-server on 5900
let wsPort = 6080;

// Event listeners for real-time updates
const eventListeners: Set<CaptureEventListener> = new Set();

// Sync completion handling for headless mode
let syncCompletionResolve: ((result: SyncResult) => void) | null = null;
let syncCompletionTimeout: NodeJS.Timeout | null = null;
let isHeadlessMode = false;
let lastCaptureTime = 0;
let capturesDuringSyncCount = 0;
let syncInactivityTimeout: NodeJS.Timeout | null = null;
const SYNC_INACTIVITY_THRESHOLD_MS = 30000; // 30 seconds of inactivity means sync is done

// Auto-sync scheduling
let autoSyncTimer: NodeJS.Timeout | null = null;
const DEFAULT_SYNC_INTERVAL_HOURS = 5;

// Pending cookies for companion extension auth relay
const pendingCookies: Map<SupportedSite, ImportedCookie[]> = new Map();
const CDP_PORT = 9222;

/**
 * Find the Chrome/Chromium binary on the system
 */
function findChromeBinary(): string | null {
  const possiblePaths = [
    // Linux
    '/usr/bin/chromium-browser',
    '/usr/bin/chromium',
    '/usr/bin/google-chrome',
    '/usr/bin/google-chrome-stable',
    '/snap/bin/chromium',
    // macOS
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Chromium.app/Contents/MacOS/Chromium',
    // Windows (common paths)
    'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
  ];

  for (const chromePath of possiblePaths) {
    if (fs.existsSync(chromePath)) {
      return chromePath;
    }
  }

  return null;
}

/**
 * Check if a command exists on the system
 */
function commandExists(cmd: string): boolean {
  // Validate command name to prevent shell injection
  if (!/^[a-zA-Z0-9_-]+$/.test(cmd)) {
    console.error(`[browser-connector] Invalid command name: ${cmd}`);
    return false;
  }
  try {
    execSync(`which ${cmd}`, { stdio: 'ignore' });
    return true;
  } catch {
    return false;
  }
}

/**
 * Check VNC dependencies
 */
function checkVncDependencies(): { available: boolean; missing: string[] } {
  const required = ['Xvfb', 'x11vnc', 'websockify'];
  const missing = required.filter(cmd => !commandExists(cmd));
  return { available: missing.length === 0, missing };
}

/**
 * Start Xvfb (virtual framebuffer)
 */
async function startXvfb(display: string): Promise<ChildProcess> {
  console.log(`[browser-connector] Starting Xvfb on display ${display}...`);

  // Kill any existing Xvfb on this display
  try {
    execSync(`pkill -f "Xvfb ${display}"`, { stdio: 'ignore' });
    await new Promise(r => setTimeout(r, 500));
  } catch {
    // Ignore if no process to kill
  }

  const proc = spawn('Xvfb', [
    display,
    '-screen', '0', '1920x1080x24',
    '-ac',  // Disable access control
    '-nolisten', 'tcp',
  ], {
    detached: false,
    stdio: ['ignore', 'pipe', 'pipe'],
  });

  proc.stderr?.on('data', (data) => {
    const msg = data.toString().trim();
    if (msg && !msg.includes('could not open default font')) {
      console.log(`[browser-connector] Xvfb: ${msg}`);
    }
  });

  // Wait for Xvfb to start
  await new Promise(r => setTimeout(r, 1000));

  if (proc.killed) {
    throw new Error('Xvfb failed to start');
  }

  console.log(`[browser-connector] Xvfb started on display ${display}`);
  return proc;
}

/**
 * Start x11vnc server
 */
async function startX11vnc(display: string, port: number): Promise<ChildProcess> {
  console.log(`[browser-connector] Starting x11vnc on port ${port}...`);

  const proc = spawn('x11vnc', [
    '-display', display,
    '-rfbport', port.toString(),
    '-passwd', 'mindsage',  // Simple password for VNC access
    '-shared',         // Allow multiple connections
    '-forever',        // Don't exit after client disconnects
    '-noxdamage',      // Better compatibility
    '-xkb',            // Use XKEYBOARD extension
    '-noxrecord',      // Disable RECORD extension (can cause issues)
    '-noxfixes',       // Disable XFIXES extension
    '-noxinerama',     // Disable Xinerama extension
    '-quiet',
  ], {
    detached: false,
    stdio: ['ignore', 'pipe', 'pipe'],
  });

  proc.stderr?.on('data', (data) => {
    const msg = data.toString().trim();
    if (msg && !msg.includes('PORT=')) {
      console.log(`[browser-connector] x11vnc: ${msg}`);
    }
  });

  // Wait for x11vnc to start
  await new Promise(r => setTimeout(r, 1000));

  if (proc.killed) {
    throw new Error('x11vnc failed to start');
  }

  console.log(`[browser-connector] x11vnc started on port ${port}`);
  return proc;
}

/**
 * Start websockify for noVNC
 */
async function startWebsockify(wsPortNum: number, vncPortNum: number): Promise<ChildProcess> {
  console.log(`[browser-connector] Starting websockify on port ${wsPortNum}...`);

  const proc = spawn('websockify', [
    '--web', path.join(__dirname, '../../novnc-web'),  // Serve noVNC web files (latest version)
    wsPortNum.toString(),
    `localhost:${vncPortNum}`,
  ], {
    detached: false,
    stdio: ['ignore', 'pipe', 'pipe'],
  });

  proc.stdout?.on('data', (data) => {
    const msg = data.toString().trim();
    if (msg) {
      console.log(`[browser-connector] websockify: ${msg}`);
    }
  });

  proc.stderr?.on('data', (data) => {
    const msg = data.toString().trim();
    if (msg) {
      console.log(`[browser-connector] websockify: ${msg}`);
    }
  });

  // Wait for websockify to start
  await new Promise(r => setTimeout(r, 1000));

  if (proc.killed) {
    throw new Error('websockify failed to start');
  }

  console.log(`[browser-connector] websockify started - noVNC available at http://localhost:${wsPortNum}/vnc.html`);
  return proc;
}

/**
 * Start VNC session (Xvfb + x11vnc + websockify)
 */
async function startVncSession(options: { display?: string; vncPort?: number; wsPort?: number } = {}): Promise<void> {
  // Check dependencies
  const deps = checkVncDependencies();
  if (!deps.available) {
    throw new Error(`Missing VNC dependencies: ${deps.missing.join(', ')}. Install with: sudo apt install xvfb x11vnc novnc websockify`);
  }

  vncDisplay = options.display || ':99';
  vncPort = options.vncPort || 5901;  // Use 5901 to avoid conflict with vino-server on 5900
  wsPort = options.wsPort || 6080;

  try {
    // Start components in order
    xvfbProcess = await startXvfb(vncDisplay);
    x11vncProcess = await startX11vnc(vncDisplay, vncPort);
    websockifyProcess = await startWebsockify(wsPort, vncPort);

    vncEnabled = true;
    console.log('[browser-connector] VNC session started successfully');
  } catch (error) {
    // Clean up on failure
    await stopVncSession();
    throw error;
  }
}

/**
 * Stop VNC session and clean up all processes
 */
async function stopVncSession(): Promise<void> {
  console.log('[browser-connector] Stopping VNC session...');

  const killProcess = (proc: ChildProcess | null, name: string) => {
    if (proc && !proc.killed) {
      try {
        proc.kill('SIGTERM');
        console.log(`[browser-connector] Stopped ${name}`);
      } catch (error) {
        console.error(`[browser-connector] Error stopping ${name}:`, error);
      }
    }
  };

  killProcess(websockifyProcess, 'websockify');
  killProcess(x11vncProcess, 'x11vnc');
  killProcess(xvfbProcess, 'Xvfb');

  websockifyProcess = null;
  x11vncProcess = null;
  xvfbProcess = null;
  vncEnabled = false;

  // Give processes time to exit
  await new Promise(r => setTimeout(r, 500));

  console.log('[browser-connector] VNC session stopped');
}

/**
 * Stop virtual display (Xvfb only, used for background sync)
 */
async function stopVirtualDisplay(): Promise<void> {
  if (xvfbProcess && !xvfbProcess.killed) {
    try {
      xvfbProcess.kill('SIGTERM');
      console.log('[browser-connector] Stopped Xvfb');
    } catch (error) {
      console.error('[browser-connector] Error stopping Xvfb:', error);
    }
  }

  xvfbProcess = null;

  // Give process time to exit
  await new Promise(r => setTimeout(r, 300));
}

/**
 * Load configuration from disk
 */
export function loadConfig(): BrowserConnectorConfig {
  const defaultConfig: BrowserConnectorConfig = {
    autoStart: false,
    defaultUrl: 'https://chatgpt.com',
    headed: true,
    memoryLimit: 512,
  };

  try {
    if (fs.existsSync(CONFIG_FILE)) {
      const data = JSON.parse(fs.readFileSync(CONFIG_FILE, 'utf-8'));
      return { ...defaultConfig, ...data };
    }
  } catch (error) {
    console.error('[browser-connector] Error loading config:', error);
  }

  return defaultConfig;
}

/**
 * Save configuration to disk
 */
export function saveConfig(config: Partial<BrowserConnectorConfig>): BrowserConnectorConfig {
  const currentConfig = loadConfig();
  const newConfig = { ...currentConfig, ...config };

  fs.mkdirSync(DATA_DIR, { recursive: true });
  fs.writeFileSync(CONFIG_FILE, JSON.stringify(newConfig, null, 2));

  return newConfig;
}

/**
 * Set authentication timestamp for a specific site
 */
export function setAuthenticatedAt(site: string): void {
  const config = loadConfig();
  const now = new Date().toISOString();

  // Initialize sites object if needed
  if (!config.sites) {
    config.sites = {};
  }

  // Set per-site auth
  const siteKey = site as SupportedSite;
  if (!config.sites[siteKey]) {
    config.sites[siteKey] = {};
  }

  if (!config.sites[siteKey]!.authenticatedAt) {
    config.sites[siteKey]!.authenticatedAt = now;
    // Also set legacy field for backwards compatibility
    if (!config.authenticatedAt) {
      config.authenticatedAt = now;
    }
    saveConfig(config);
    console.log(`[browser-connector] Authentication recorded for ${site} at ${now}`);
  }
}

/**
 * Get authentication status for a specific site (or any site if not specified)
 */
export function getAuthStatus(site?: string): AuthStatus {
  const config = loadConfig();

  if (site) {
    const siteKey = site as SupportedSite;
    const siteConfig = config.sites?.[siteKey];

    // Check site-specific auth first, then fall back to legacy for chatgpt
    const siteAuthAt = siteConfig?.authenticatedAt;
    const legacyAuthAt = (siteKey === 'chatgpt') ? config.authenticatedAt : undefined;
    const authenticatedAt = siteAuthAt || legacyAuthAt;

    return {
      authenticated: !!authenticatedAt,
      authenticatedAt: authenticatedAt,
      site: site,
    };
  }

  // Return status for any authenticated site (legacy behavior)
  return {
    authenticated: !!config.authenticatedAt,
    authenticatedAt: config.authenticatedAt,
  };
}

/**
 * Get all authenticated sites
 */
export function getAuthenticatedSites(): string[] {
  const config = loadConfig();
  const sites: string[] = [];

  for (const siteId of getSupportedSiteIds()) {
    if (config.sites?.[siteId]?.authenticatedAt) {
      sites.push(siteId);
    }
  }

  // Fallback to legacy single-site auth
  if (sites.length === 0 && config.authenticatedAt) {
    sites.push('chatgpt'); // Assume ChatGPT for legacy configs
  }

  return sites;
}

/**
 * Clear authentication for a specific site (or all if not specified)
 */
export function clearAuthentication(site?: string): void {
  const config = loadConfig();

  if (site) {
    const siteKey = site as SupportedSite;
    if (config.sites?.[siteKey]) {
      delete config.sites[siteKey]!.authenticatedAt;
      console.log(`[browser-connector] Authentication cleared for ${site}`);
    }
  } else {
    // Clear all
    delete config.authenticatedAt;
    if (config.sites) {
      for (const siteId of getSupportedSiteIds()) {
        if (config.sites[siteId]) {
          delete config.sites[siteId]!.authenticatedAt;
        }
      }
    }
    console.log('[browser-connector] All authentication cleared');
  }

  saveConfig(config);
}

/**
 * Check if display is available
 */
function hasDisplay(): boolean {
  return !!process.env.DISPLAY || process.platform === 'darwin' || process.platform === 'win32';
}

/**
 * Get Chrome launch arguments
 */
function getLaunchArgs(options: LaunchOptions, config: BrowserConnectorConfig, displayEnv?: string): string[] {
  const args = [
    // Use our persistent profile directory
    `--user-data-dir=${PROFILE_DIR}`,
    // Load our capture extension
    `--load-extension=${EXTENSION_DIR}`,
    // Basic flags
    '--no-first-run',
    '--no-default-browser-check',
    '--disable-default-apps',
    '--disable-sync',
    '--disable-background-networking',
    // GPU flags for Jetson compatibility
    '--disable-gpu',
    '--disable-software-rasterizer',
    // Allow extensions to run properly (needed for snap Chromium)
    '--no-sandbox',
    '--disable-setuid-sandbox',
  ];

  // Headless mode for background sync
  if (options.headless) {
    args.push('--headless=new');
    args.push('--disable-extensions-except=' + EXTENSION_DIR);
    args.push('--remote-debugging-port=9222');
  } else {
    // Window settings (only for headed mode)
    // Use full HD resolution for VNC mode
    args.push('--window-size=1920,1080');
    args.push('--window-position=0,0');
    // Don't use --start-maximized as it can conflict with window-size

    // Enable CDP for cookie injection in virtualDisplay mode
    if (options.virtualDisplay) {
      args.push(`--remote-debugging-port=${CDP_PORT}`);
    }
  }

  // Start URL
  const startUrl = options.startUrl || config.defaultUrl;
  if (startUrl) {
    args.push(startUrl);
  }

  return args;
}

/**
 * Launch the browser with persistent profile
 * Supports VNC mode for headless remote access
 * Supports virtualDisplay mode for background sync (Xvfb only, no VNC)
 */
export async function launchBrowser(options: LaunchOptions = {}): Promise<BrowserStatus> {
  if (browserProcess && !browserProcess.killed) {
    console.log('[browser-connector] Browser already running');
    return getStatus();
  }

  const config = loadConfig();
  const useVnc = options.vnc || false;
  const useVirtualDisplay = options.virtualDisplay || false;
  const headed = (useVnc || useVirtualDisplay) ? true : (options.headed ?? config.headed ?? hasDisplay());

  // Find Chrome binary
  const chromeBinary = findChromeBinary();
  if (!chromeBinary) {
    throw new Error('Chrome/Chromium not found. Please install Chromium: sudo apt install chromium-browser');
  }

  console.log('[browser-connector] Launching browser...');
  let modeStr = 'Headed';
  if (options.headless) modeStr = 'Headless (background sync)';
  else if (useVnc) modeStr = 'VNC';
  else if (useVirtualDisplay) modeStr = 'Virtual Display (background sync)';
  else if (!headed) modeStr = 'Headless';
  console.log(`[browser-connector] Mode: ${modeStr}`);
  console.log(`[browser-connector] Chrome binary: ${chromeBinary}`);
  console.log(`[browser-connector] Profile directory: ${PROFILE_DIR}`);

  // Ensure directories exist
  fs.mkdirSync(PROFILE_DIR, { recursive: true });

  // Clear service worker cache to ensure extension updates are loaded
  // Chrome aggressively caches Manifest V3 service workers, which can cause issues
  const swCacheDir = path.join(PROFILE_DIR, 'Default', 'Service Worker');
  if (fs.existsSync(swCacheDir)) {
    console.log('[browser-connector] Clearing service worker cache for extension updates...');
    fs.rmSync(swCacheDir, { recursive: true, force: true });
  }

  // Check if extension exists
  const manifestPath = path.join(EXTENSION_DIR, 'manifest.json');
  if (!fs.existsSync(manifestPath)) {
    throw new Error(`Extension not found at ${EXTENSION_DIR}. Please ensure the extension is built.`);
  }

  // Start display session based on mode
  let displayEnv = process.env.DISPLAY || ':0';

  if (useVnc) {
    // Full VNC mode: Xvfb + x11vnc + websockify
    await startVncSession({
      display: ':99',
      vncPort: options.vncPort,
      wsPort: options.wsPort,
    });
    displayEnv = vncDisplay;
  } else if (useVirtualDisplay) {
    // Virtual display mode: only Xvfb (for background sync with extensions)
    const virtualDisplayNum = ':98';

    // Check Xvfb dependency
    if (!commandExists('Xvfb')) {
      throw new Error('Xvfb not found. Install with: sudo apt install xvfb');
    }

    xvfbProcess = await startXvfb(virtualDisplayNum);
    displayEnv = virtualDisplayNum;
    console.log(`[browser-connector] Virtual display started on ${virtualDisplayNum}`);
  }

  const launchArgs = getLaunchArgs(options, config, displayEnv);
  console.log(`[browser-connector] DISPLAY=${displayEnv}`);

  try {
    // Launch Chrome as a child process
    browserProcess = spawn(chromeBinary, launchArgs, {
      detached: false,
      stdio: ['ignore', 'pipe', 'pipe'],
      env: {
        ...process.env,
        DISPLAY: displayEnv,
      },
    });

    launchedAt = new Date().toISOString();
    sessionCaptureCount = 0;

    // Handle process output
    browserProcess.stdout?.on('data', (data) => {
      const output = data.toString().trim();
      if (output) {
        console.log(`[browser-connector] Chrome: ${output}`);
      }
    });

    browserProcess.stderr?.on('data', (data) => {
      const output = data.toString().trim();
      // Filter out common non-error messages
      if (output && !output.includes('DevTools listening') && !output.includes('GL implementation')) {
        console.log(`[browser-connector] Chrome stderr: ${output}`);
      }
    });

    browserProcess.on('close', (code) => {
      console.log(`[browser-connector] Chrome exited with code ${code}`);
      browserProcess = null;
      launchedAt = null;
    });

    browserProcess.on('error', (err) => {
      console.error('[browser-connector] Chrome process error:', err);
      browserProcess = null;
      launchedAt = null;
    });

    // Wait a moment for Chrome to start
    await new Promise(resolve => setTimeout(resolve, 2000));

    console.log('[browser-connector] Browser launched successfully');

    if (useVnc) {
      console.log(`[browser-connector] Access browser via noVNC at: http://localhost:${wsPort}/vnc.html`);
    }

    return getStatus();

  } catch (error) {
    console.error('[browser-connector] Failed to launch browser:', error);
    browserProcess = null;
    // Clean up display processes on failure
    if (useVnc) {
      await stopVncSession();
    } else if (useVirtualDisplay && xvfbProcess) {
      await stopVirtualDisplay();
    }
    throw error;
  }
}

/**
 * Close the browser gracefully
 */
export async function closeBrowser(): Promise<void> {
  console.log('[browser-connector] Closing browser...');

  // Close browser first
  if (browserProcess && !browserProcess.killed) {
    try {
      browserProcess.kill('SIGTERM');

      // Wait for process to exit
      await new Promise<void>((resolve) => {
        const timeout = setTimeout(() => {
          if (browserProcess && !browserProcess.killed) {
            browserProcess.kill('SIGKILL');
          }
          resolve();
        }, 5000);

        browserProcess?.on('close', () => {
          clearTimeout(timeout);
          resolve();
        });
      });
    } catch (error) {
      console.error('[browser-connector] Error closing browser:', error);
    }
  }

  browserProcess = null;
  launchedAt = null;
  isHeadlessMode = false;

  // Stop VNC session if running
  if (vncEnabled) {
    await stopVncSession();
  } else if (xvfbProcess) {
    // Stop virtual display if running (without VNC)
    await stopVirtualDisplay();
  }

  console.log('[browser-connector] Browser closed');
}

/**
 * Store pending cookies from companion extension
 */
export function storePendingCookies(site: SupportedSite, cookies: ImportedCookie[]): void {
  // Filter to whitelisted domains only
  const allowedDomains = ALLOWED_COOKIE_DOMAINS[site] || [];
  const filtered = cookies.filter(c => {
    const cookieDomain = c.domain.startsWith('.') ? c.domain : `.${c.domain}`;
    return allowedDomains.some(d => {
      const allowed = d.startsWith('.') ? d : `.${d}`;
      return cookieDomain === allowed || cookieDomain.endsWith(allowed);
    });
  });

  pendingCookies.set(site, filtered);
  console.log(`[browser-connector] Stored ${filtered.length} pending cookies for ${site} (${cookies.length - filtered.length} filtered out)`);
}

/**
 * Get and clear pending cookies for a site
 */
export function getPendingCookies(site: SupportedSite): ImportedCookie[] | undefined {
  const cookies = pendingCookies.get(site);
  if (cookies) {
    pendingCookies.delete(site);
  }
  return cookies;
}

/**
 * Get count of pending cookies per site (for debugging, no values exposed)
 */
export function getPendingCookiesCounts(): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const [site, cookies] of pendingCookies.entries()) {
    counts[site] = cookies.length;
  }
  return counts;
}

/**
 * Inject cookies into Chrome via CDP (Chrome DevTools Protocol)
 * Connects to Chrome's remote debugging port and uses Network.setCookie
 */
async function importCookiesViaCDP(port: number, cookies: ImportedCookie[], targetUrl: string): Promise<void> {
  // Get the WebSocket debugger URL from CDP
  const response = await fetch(`http://localhost:${port}/json/version`);
  const versionInfo = await response.json();
  const wsUrl = versionInfo.webSocketDebuggerUrl;

  if (!wsUrl) {
    throw new Error('Could not get WebSocket debugger URL from CDP');
  }

  console.log(`[browser-connector] Connecting to CDP at ${wsUrl}`);

  return new Promise((resolve, reject) => {
    const ws = new WebSocket(wsUrl);
    let messageId = 1;
    const pendingMessages = new Map<number, { resolve: (v: any) => void; reject: (e: Error) => void }>();

    ws.on('error', (err) => {
      reject(new Error(`CDP WebSocket error: ${err.message}`));
    });

    ws.on('open', async () => {
      console.log(`[browser-connector] CDP connected, injecting ${cookies.length} cookies...`);

      try {
        // Enable Network domain
        await sendCdpCommand('Network.enable', {});

        // Inject each cookie
        let injected = 0;
        for (const cookie of cookies) {
          const cdpCookie: Record<string, unknown> = {
            name: cookie.name,
            value: cookie.value,
            domain: cookie.domain,
            path: cookie.path || '/',
            secure: cookie.secure ?? false,
            httpOnly: cookie.httpOnly ?? false,
          };

          // Map sameSite values
          if (cookie.sameSite) {
            const sameSiteMap: Record<string, string> = {
              'no_restriction': 'None',
              'unspecified': 'Lax',
              'Strict': 'Strict',
              'Lax': 'Lax',
              'None': 'None',
            };
            cdpCookie.sameSite = sameSiteMap[cookie.sameSite] || 'Lax';
          }

          if (cookie.expirationDate) {
            cdpCookie.expires = cookie.expirationDate;
          }

          try {
            await sendCdpCommand('Network.setCookie', cdpCookie);
            injected++;
          } catch (err) {
            console.warn(`[browser-connector] Failed to set cookie "${cookie.name}": ${err}`);
          }
        }

        console.log(`[browser-connector] Injected ${injected}/${cookies.length} cookies via CDP`);

        // Navigate to the target URL
        console.log(`[browser-connector] Navigating to ${targetUrl}`);
        await sendCdpCommand('Page.navigate', { url: targetUrl });

        // Wait for navigation to start
        await new Promise(r => setTimeout(r, 2000));

        ws.close();
        resolve();
      } catch (err) {
        ws.close();
        reject(err);
      }
    });

    ws.on('message', (data) => {
      try {
        const msg = JSON.parse(data.toString());
        if (msg.id && pendingMessages.has(msg.id)) {
          const handler = pendingMessages.get(msg.id)!;
          pendingMessages.delete(msg.id);
          if (msg.error) {
            handler.reject(new Error(msg.error.message));
          } else {
            handler.resolve(msg.result);
          }
        }
      } catch {
        // Ignore parse errors
      }
    });

    function sendCdpCommand(method: string, params: Record<string, unknown>): Promise<any> {
      return new Promise((res, rej) => {
        const id = messageId++;
        pendingMessages.set(id, { resolve: res, reject: rej });
        ws.send(JSON.stringify({ id, method, params }));
      });
    }
  });
}

/**
 * Launch browser in headless mode for background sync
 * Returns a promise that resolves when sync completes
 * @param site - Optional site to sync (defaults to chatgpt)
 * @param timeoutMs - Timeout in milliseconds (default: 5 minutes)
 */
export async function launchHeadlessSync(site?: SupportedSite, timeoutMs: number = 300000): Promise<SyncResult> {
  const targetSite = site || 'chatgpt';
  const cookies = pendingCookies.get(targetSite);
  const hasPendingCookies = cookies && cookies.length > 0;

  // Check authentication for the specific site (skip if we have pending cookies to inject)
  if (!hasPendingCookies) {
    const authStatus = getAuthStatus(targetSite);
    if (!authStatus.authenticated) {
      return {
        success: false,
        error: `Login required for ${targetSite}. Please use VNC mode or the Companion Extension to log in first.`,
      };
    }
  }

  if (browserProcess && !browserProcess.killed) {
    return {
      success: false,
      error: 'Browser already running. Close it first.',
    };
  }

  console.log(`[browser-connector] Starting headless sync for ${targetSite}...`);
  if (hasPendingCookies) {
    console.log(`[browser-connector] Will inject ${cookies!.length} cookies via CDP`);
  }
  isHeadlessMode = true;
  lastCaptureTime = 0;
  capturesDuringSyncCount = 0;

  // Create a promise that will be resolved by sync completion
  const syncPromise = new Promise<SyncResult>((resolve) => {
    syncCompletionResolve = resolve;

    // Set overall timeout (catches case where no captures come in at all)
    syncCompletionTimeout = setTimeout(() => {
      if (capturesDuringSyncCount > 0) {
        // If we got some captures, consider it a partial success
        console.log(`[browser-connector] Headless sync timeout with ${capturesDuringSyncCount} captures`);
        cleanupSyncTimers();
        resolve({
          success: true,
          synced: capturesDuringSyncCount,
          failed: 0,
          total: capturesDuringSyncCount,
        });
      } else {
        console.log('[browser-connector] Headless sync timed out (no captures)');
        cleanupSyncTimers();
        resolve({
          success: false,
          error: 'Sync timed out',
        });
      }
      closeBrowser().catch(console.error);
    }, timeoutMs);
  });

  try {
    const siteUrl = SITE_URLS[targetSite];
    const syncUrl = `${siteUrl}/?mindsage-sync=true`;

    if (hasPendingCookies) {
      // Cookie injection flow: launch to about:blank, inject cookies via CDP, then navigate
      const cookiesToInject = getPendingCookies(targetSite)!;

      await launchBrowser({
        virtualDisplay: true,
        startUrl: 'about:blank',
      });

      // Wait for Chrome's CDP to be ready
      await new Promise(r => setTimeout(r, 3000));

      // Inject cookies and navigate to sync URL
      await importCookiesViaCDP(CDP_PORT, cookiesToInject, syncUrl);

      // Mark as authenticated since we just injected cookies
      setAuthenticatedAt(targetSite);
    } else {
      // Standard flow: launch directly to sync URL
      await launchBrowser({
        virtualDisplay: true,
        startUrl: syncUrl,
      });
    }

    // Wait for sync completion or timeout
    const result = await syncPromise;

    // Clean up timers
    cleanupSyncTimers();

    // Close browser after sync
    await closeBrowser();

    // Save sync result for the site
    saveSyncResultForSite(targetSite, result);

    return result;

  } catch (error) {
    isHeadlessMode = false;
    if (syncCompletionTimeout) {
      clearTimeout(syncCompletionTimeout);
      syncCompletionTimeout = null;
    }
    syncCompletionResolve = null;

    return {
      success: false,
      error: String(error),
    };
  }
}

/**
 * Save sync result for a specific site
 */
function saveSyncResultForSite(site: SupportedSite, result: SyncResult): void {
  const config = loadConfig();

  if (!config.sites) {
    config.sites = {};
  }

  if (!config.sites[site]) {
    config.sites[site] = {};
  }

  config.sites[site]!.lastSyncAt = new Date().toISOString();
  config.sites[site]!.lastSyncResult = result;

  // Also update global lastSync for backwards compatibility
  config.lastSyncAt = new Date().toISOString();
  config.lastSyncResult = result;

  saveConfig(config);
}

/**
 * Called by extension (via API) to signal sync completion
 */
export function resolveSyncCompletion(result: SyncResult): void {
  if (syncCompletionResolve) {
    console.log('[browser-connector] Sync completion received:', result);
    cleanupSyncTimers();
    syncCompletionResolve(result);
    syncCompletionResolve = null;
  }
}

/**
 * Clean up all sync-related timers
 */
function cleanupSyncTimers(): void {
  if (syncCompletionTimeout) {
    clearTimeout(syncCompletionTimeout);
    syncCompletionTimeout = null;
  }
  if (syncInactivityTimeout) {
    clearTimeout(syncInactivityTimeout);
    syncInactivityTimeout = null;
  }
}

/**
 * Called when a capture is received during headless sync
 * Uses inactivity detection to complete sync if extension doesn't signal completion
 */
export function onCaptureReceived(): void {
  if (!isHeadlessMode || !syncCompletionResolve) {
    return;
  }

  lastCaptureTime = Date.now();
  capturesDuringSyncCount++;

  // Reset inactivity timer
  if (syncInactivityTimeout) {
    clearTimeout(syncInactivityTimeout);
  }

  // Set new inactivity timer - if no captures for 30 seconds, consider sync complete
  syncInactivityTimeout = setTimeout(() => {
    if (syncCompletionResolve) {
      console.log(`[browser-connector] Sync completed via inactivity detection (${capturesDuringSyncCount} captures)`);
      const result: SyncResult = {
        success: true,
        synced: capturesDuringSyncCount,
        failed: 0,
        total: capturesDuringSyncCount,
      };
      cleanupSyncTimers();
      syncCompletionResolve(result);
      syncCompletionResolve = null;
    }
  }, SYNC_INACTIVITY_THRESHOLD_MS);
}

/**
 * Check if currently in headless mode
 */
export function isInHeadlessMode(): boolean {
  return isHeadlessMode;
}

/**
 * Navigate to a URL (opens in new tab since we don't have direct control)
 */
export async function navigateTo(url: string): Promise<void> {
  if (!browserProcess || browserProcess.killed) {
    throw new Error('Browser not running');
  }

  const chromeBinary = findChromeBinary();
  if (chromeBinary) {
    // Open URL in the existing profile
    spawn(chromeBinary, [
      `--user-data-dir=${PROFILE_DIR}`,
      url
    ], {
      detached: true,
      stdio: 'ignore',
      env: {
        ...process.env,
        DISPLAY: vncEnabled ? vncDisplay : (xvfbProcess ? ':98' : (process.env.DISPLAY || ':0')),
      },
    }).unref();
  }
}

/**
 * Navigate to a site's sync URL (for use with existing VNC session)
 * This allows reusing the VNC session to log into multiple sites
 */
export async function navigateToSite(site: SupportedSite, forSync: boolean = false): Promise<void> {
  if (!browserProcess || browserProcess.killed) {
    throw new Error('Browser not running');
  }

  const baseUrl = SITE_URLS[site];
  const url = forSync ? `${baseUrl}/?mindsage-sync=true` : baseUrl;

  console.log(`[browser-connector] Navigating to ${site}: ${url}`);
  await navigateTo(url);
}

/**
 * Get the list of all supported sites
 */
export function getSupportedSites(): SupportedSite[] {
  return getSupportedSiteIds();
}

/**
 * Get site URL
 */
export function getSiteUrl(site: SupportedSite): string {
  return SITE_URLS[site];
}

/**
 * Get current browser status
 */
export function getStatus(): BrowserStatus {
  const running = browserProcess !== null && !browserProcess.killed;

  const status: BrowserStatus = {
    running,
    pid: browserProcess?.pid,
    connectedSites: [],
    launchedAt: launchedAt || undefined,
    captureStats: {
      totalCaptured: 0,
      sessionCaptured: sessionCaptureCount,
    },
  };

  // Add VNC info if enabled
  if (vncEnabled) {
    status.vnc = {
      enabled: true,
      wsPort,
      vncPort,
      display: vncDisplay,
    };
  }

  return status;
}

/**
 * Get session health information for all authenticated sites.
 * Includes time since authentication and whether re-auth is recommended.
 */
export function getSessionHealth(): {
  sites: Array<{
    site: string;
    authenticated: boolean;
    authenticatedAt?: string;
    daysSinceAuth?: number;
    reAuthRecommended: boolean;
    lastSyncAt?: string;
    lastSyncSuccess?: boolean;
  }>;
  syncStats?: { totalSynced: number; totalFailed: number; syncCount: number };
} {
  const config = loadConfig();
  const sites = [];

  for (const siteId of getSupportedSiteIds()) {
    const siteConfig = config.sites?.[siteId];
    const authAt = siteConfig?.authenticatedAt || (siteId === 'chatgpt' ? config.authenticatedAt : undefined);
    const daysSinceAuth = authAt
      ? Math.floor((Date.now() - new Date(authAt).getTime()) / (1000 * 60 * 60 * 24))
      : undefined;

    sites.push({
      site: siteId,
      authenticated: !!authAt,
      authenticatedAt: authAt,
      daysSinceAuth,
      // Sessions typically expire after 30-90 days
      reAuthRecommended: daysSinceAuth !== undefined && daysSinceAuth > 30,
      lastSyncAt: siteConfig?.lastSyncAt || config.lastSyncAt,
      lastSyncSuccess: siteConfig?.lastSyncResult?.success ?? config.lastSyncResult?.success,
    });
  }

  return {
    sites,
    syncStats: config.syncStats,
  };
}

/**
 * Get VNC status and connection info
 */
export function getVncStatus(): { enabled: boolean; wsPort?: number; vncPort?: number; display?: string; url?: string } {
  if (!vncEnabled) {
    return { enabled: false };
  }

  return {
    enabled: true,
    wsPort,
    vncPort,
    display: vncDisplay,
    url: `http://localhost:${wsPort}/vnc.html`,
  };
}

/**
 * Check if VNC dependencies are installed
 */
export function checkVncAvailable(): { available: boolean; missing: string[] } {
  return checkVncDependencies();
}

/**
 * Check if browser is running
 */
export function isRunning(): boolean {
  return browserProcess !== null && !browserProcess.killed;
}

/**
 * Check if VNC is enabled
 */
export function isVncEnabled(): boolean {
  return vncEnabled;
}

/**
 * Increment session capture count
 */
export function incrementCaptureCount(): void {
  sessionCaptureCount++;
}

/**
 * Add event listener for capture events
 */
export function addCaptureListener(listener: CaptureEventListener): void {
  eventListeners.add(listener);
}

/**
 * Remove event listener
 */
export function removeCaptureListener(listener: CaptureEventListener): void {
  eventListeners.delete(listener);
}

/**
 * Emit capture event to all listeners
 */
export function emitCaptureEvent(event: CaptureEvent): void {
  for (const listener of eventListeners) {
    try {
      listener(event);
    } catch (error) {
      console.error('[browser-connector] Error in capture listener:', error);
    }
  }
}

/**
 * Auto-start browser if configured
 */
export async function autoStartIfConfigured(): Promise<void> {
  const config = loadConfig();

  if (config.autoStart) {
    console.log('[browser-connector] Auto-starting browser...');
    try {
      await launchBrowser();
    } catch (error) {
      console.error('[browser-connector] Auto-start failed:', error);
    }
  }

  // Start auto-sync if enabled and authenticated
  if (config.autoSyncEnabled && config.authenticatedAt) {
    startAutoSync();
  }
}

/**
 * Perform a headless sync and save results.
 * Includes retry logic for transient failures and session expiry detection.
 */
async function performAutoSync(): Promise<SyncResult> {
  console.log('[browser-connector] Starting scheduled auto-sync...');

  let result = await launchHeadlessSync();

  // Retry once with 30s delay for transient failures (not auth failures)
  if (!result.success && result.error && !isAuthError(result.error)) {
    console.log('[browser-connector] Auto-sync failed, retrying in 30s...');
    await new Promise(resolve => setTimeout(resolve, 30000));
    if (!isRunning()) {
      result = await launchHeadlessSync();
    }
  }

  // Save sync results to config
  const config = loadConfig();
  config.lastSyncAt = new Date().toISOString();
  config.lastSyncResult = result;

  // Update cumulative sync stats
  if (!config.syncStats) {
    config.syncStats = { totalSynced: 0, totalFailed: 0, syncCount: 0 };
  }
  config.syncStats.syncCount++;
  if (result.success) {
    config.syncStats.totalSynced += result.synced || 0;
    config.syncStats.totalFailed += result.failed || 0;
    console.log(`[browser-connector] Auto-sync complete: ${result.synced} synced, ${result.failed} failed`);
  } else {
    console.error('[browser-connector] Auto-sync failed:', result.error);

    // Detect session expiry — if the error suggests auth issues, clear authenticatedAt
    if (result.error && isAuthError(result.error)) {
      console.warn('[browser-connector] Session appears expired. Clearing authentication — re-login required.');
      // Clear auth for all sites that might be affected
      for (const siteId of getSupportedSiteIds()) {
        if (config.sites?.[siteId]?.authenticatedAt) {
          config.sites[siteId]!.authenticatedAt = undefined;
        }
      }
      config.authenticatedAt = undefined;
    }
  }

  saveConfig(config);
  return result;
}

/**
 * Check if a sync error indicates session/auth expiry
 */
function isAuthError(error: string): boolean {
  const authPatterns = [
    'login required',
    'not authenticated',
    'session expired',
    'unauthorized',
    '401',
    '403',
    'access denied',
    'please log in',
    'sign in',
  ];
  const lowerError = error.toLowerCase();
  return authPatterns.some(pattern => lowerError.includes(pattern));
}

/**
 * Start automatic sync scheduling
 */
export function startAutoSync(): void {
  const config = loadConfig();

  // Must be authenticated to start auto-sync
  if (!config.authenticatedAt) {
    console.log('[browser-connector] Cannot start auto-sync: not authenticated');
    return;
  }

  // Stop existing timer if any
  if (autoSyncTimer) {
    clearInterval(autoSyncTimer);
  }

  const intervalHours = config.autoSyncIntervalHours || DEFAULT_SYNC_INTERVAL_HOURS;
  const intervalMs = intervalHours * 60 * 60 * 1000;

  console.log(`[browser-connector] Starting auto-sync every ${intervalHours} hours`);

  // Save config with auto-sync enabled
  config.autoSyncEnabled = true;
  saveConfig(config);

  // Set up interval
  autoSyncTimer = setInterval(async () => {
    // Skip if browser is already running (user might be using VNC)
    if (isRunning()) {
      console.log('[browser-connector] Skipping auto-sync: browser already running');
      return;
    }

    await performAutoSync();
  }, intervalMs);

  // Also run an initial sync if we haven't synced recently
  const lastSync = config.lastSyncAt ? new Date(config.lastSyncAt).getTime() : 0;
  const timeSinceLastSync = Date.now() - lastSync;

  if (timeSinceLastSync > intervalMs) {
    console.log('[browser-connector] Running initial sync (last sync was over interval ago)');
    // Delay initial sync slightly to not block startup
    setTimeout(async () => {
      if (!isRunning()) {
        await performAutoSync();
      }
    }, 10000);
  }
}

/**
 * Stop automatic sync scheduling
 */
export function stopAutoSync(): void {
  if (autoSyncTimer) {
    clearInterval(autoSyncTimer);
    autoSyncTimer = null;
    console.log('[browser-connector] Auto-sync stopped');
  }

  // Save config with auto-sync disabled
  const config = loadConfig();
  config.autoSyncEnabled = false;
  saveConfig(config);
}

/**
 * Check if auto-sync is running
 */
export function isAutoSyncEnabled(): boolean {
  return autoSyncTimer !== null;
}

/**
 * Get auto-sync status
 */
export function getAutoSyncStatus(): {
  enabled: boolean;
  intervalHours: number;
  lastSyncAt?: string;
  lastSyncResult?: SyncResult;
  nextSyncAt?: string;
} {
  const config = loadConfig();
  const intervalHours = config.autoSyncIntervalHours || DEFAULT_SYNC_INTERVAL_HOURS;

  let nextSyncAt: string | undefined;
  if (config.autoSyncEnabled && config.lastSyncAt) {
    const lastSync = new Date(config.lastSyncAt);
    const nextSync = new Date(lastSync.getTime() + intervalHours * 60 * 60 * 1000);
    nextSyncAt = nextSync.toISOString();
  }

  return {
    enabled: config.autoSyncEnabled || false,
    intervalHours,
    lastSyncAt: config.lastSyncAt,
    lastSyncResult: config.lastSyncResult,
    nextSyncAt,
  };
}

/**
 * Update auto-sync interval
 */
export function setAutoSyncInterval(hours: number): void {
  const config = loadConfig();
  config.autoSyncIntervalHours = hours;
  saveConfig(config);

  // Restart auto-sync with new interval if enabled
  if (autoSyncTimer) {
    stopAutoSync();
    startAutoSync();
  }

  console.log(`[browser-connector] Auto-sync interval set to ${hours} hours`);
}
