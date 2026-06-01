/**
 * MindSage Companion Extension - Background Service Worker
 * Relays captured conversation data to MindSage backend
 * Supports configurable server URL for companion mode
 */

const DEFAULT_BACKEND = 'http://localhost:3003';

// Cache site data from backend for cookie domains
let cachedSites = null;
let cacheExpiry = 0;

/**
 * Get the configured backend URL
 */
async function getBackendUrl() {
  try {
    const data = await chrome.storage.sync.get('serverUrl');
    return data.serverUrl || DEFAULT_BACKEND;
  } catch {
    return DEFAULT_BACKEND;
  }
}

/**
 * Fetch site data from backend (with caching)
 */
async function getSiteData() {
  if (cachedSites && Date.now() < cacheExpiry) return cachedSites;
  try {
    const backendUrl = await getBackendUrl();
    const res = await fetch(`${backendUrl}/api/browser-connector/sites`);
    if (res.ok) {
      const data = await res.json();
      cachedSites = data.sites;
      cacheExpiry = Date.now() + 300000; // Cache 5 min
      return cachedSites;
    }
  } catch { /* fall through */ }
  return null;
}

/**
 * Get cookie domains for a specific site from backend
 */
async function getCookieDomainsForSite(site) {
  const sites = await getSiteData();
  const siteInfo = sites?.find(s => s.id === site);
  return siteInfo?.cookieDomains || [];
}

/**
 * Send captured data to MindSage backend
 */
async function sendToBackend(data) {
  try {
    const backendUrl = await getBackendUrl();
    const response = await fetch(`${backendUrl}/api/browser-connector/capture`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(data),
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    const result = await response.json();

    if (result.success) {
      console.log('[MindSage] Capture sent:', data.conversationId);
    }

    return result;

  } catch (error) {
    console.error('[MindSage] Failed to send capture:', error);
    throw error;
  }
}

/**
 * Report authentication status to backend
 */
async function reportAuthToBackend(site, authenticated) {
  try {
    const backendUrl = await getBackendUrl();
    const response = await fetch(`${backendUrl}/api/browser-connector/report-auth`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ site, authenticated }),
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    const result = await response.json();
    console.log('[MindSage] Auth reported:', site, authenticated);
    return result;

  } catch (error) {
    console.error('[MindSage] Failed to report auth:', error);
    throw error;
  }
}

/**
 * Report sync completion to backend (for headless mode)
 */
async function reportSyncComplete(result) {
  try {
    const backendUrl = await getBackendUrl();
    const response = await fetch(`${backendUrl}/api/browser-connector/sync-complete`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(result),
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    const data = await response.json();
    console.log('[MindSage] Sync completion reported');
    return data;

  } catch (error) {
    console.error('[MindSage] Failed to report sync completion:', error);
    throw error;
  }
}

/**
 * Relay cookies for a site to MindSage backend
 */
async function relayCookies(site, serverUrl) {
  const domains = await getCookieDomainsForSite(site);
  if (!domains || domains.length === 0) {
    throw new Error(`Unknown site or no cookie domains: ${site}`);
  }

  // Collect cookies from all domains for this site
  const allCookies = [];
  for (const domain of domains) {
    try {
      const cookies = await chrome.cookies.getAll({ domain });
      allCookies.push(...cookies);
    } catch (error) {
      console.warn(`[MindSage] Failed to get cookies for domain ${domain}:`, error);
    }
  }

  if (allCookies.length === 0) {
    throw new Error(`No cookies found for ${site}. Make sure you are logged in.`);
  }

  console.log(`[MindSage] Found ${allCookies.length} cookies for ${site}`);

  // Map chrome.cookies format to our ImportedCookie format
  const mappedCookies = allCookies.map(c => ({
    name: c.name,
    value: c.value,
    domain: c.domain,
    path: c.path,
    secure: c.secure,
    httpOnly: c.httpOnly,
    sameSite: c.sameSite || 'unspecified',
    expirationDate: c.expirationDate,
  }));

  // Send to backend
  const targetUrl = serverUrl || await getBackendUrl();
  const response = await fetch(`${targetUrl}/api/browser-connector/import-cookies`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      site,
      cookies: mappedCookies,
    }),
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.error || `HTTP ${response.status}`);
  }

  const result = await response.json();
  console.log(`[MindSage] Cookie relay complete for ${site}: ${result.cookiesImported} imported`);
  return result;
}

/**
 * Handle messages from content scripts and popup
 */
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  // Debug messages from content scripts
  if (message.type === 'debug') {
    getBackendUrl().then(backendUrl => {
      fetch(`${backendUrl}/api/browser-connector/debug`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(message.data)
      }).catch(e => console.error('[MindSage] Debug fetch failed:', e));
    });
    sendResponse({ success: true });
    return false;
  }

  if (message.type === 'capture') {
    sendToBackend(message.payload)
      .then(result => sendResponse(result))
      .catch(error => sendResponse({ success: false, error: error.message }));
    return true;
  }

  if (message.type === 'syncProgress') {
    chrome.storage.local.set({ syncProgress: message.payload });
    console.log('[MindSage] Sync progress:', message.payload.status, message.payload.synced, '/', message.payload.total);
    return false;
  }

  if (message.type === 'reportAuth') {
    reportAuthToBackend(message.site, message.authenticated)
      .then(result => sendResponse(result))
      .catch(error => sendResponse({ success: false, error: error.message }));
    return true;
  }

  if (message.type === 'syncComplete') {
    reportSyncComplete(message.result)
      .then(result => sendResponse(result))
      .catch(error => sendResponse({ success: false, error: error.message }));
    return true;
  }

  // Companion mode: relay cookies for a site
  if (message.type === 'relayCookies') {
    relayCookies(message.site, message.serverUrl)
      .then(result => sendResponse(result))
      .catch(error => sendResponse({ success: false, error: error.message }));
    return true;
  }

  // Test connection to a server URL
  if (message.type === 'testConnection') {
    const url = message.url || DEFAULT_BACKEND;
    fetch(`${url}/api/browser-connector/status`)
      .then(response => {
        if (response.ok) {
          sendResponse({ success: true, connected: true });
        } else {
          sendResponse({ success: false, error: `HTTP ${response.status}` });
        }
      })
      .catch(error => sendResponse({ success: false, error: error.message }));
    return true;
  }

  // Set server URL
  if (message.type === 'setServerUrl') {
    chrome.storage.sync.set({ serverUrl: message.url }).then(() => {
      // Set companion mode flag
      const isCompanion = message.url && message.url !== DEFAULT_BACKEND;
      chrome.storage.sync.set({ companionMode: isCompanion }).then(() => {
        sendResponse({ success: true });
      });
    });
    return true;
  }

  // Get server URL
  if (message.type === 'getServerUrl') {
    chrome.storage.sync.get('serverUrl').then(data => {
      sendResponse({ serverUrl: data.serverUrl || '' });
    });
    return true;
  }

  return false;
});

console.log('[MindSage] Background service worker started');

// Test ping to verify extension can reach backend
(async function testBackendConnection() {
  try {
    const backendUrl = await getBackendUrl();
    const response = await fetch(`${backendUrl}/api/browser-connector/status`);
    if (response.ok) {
      console.log('[MindSage] Backend connection successful');
    } else {
      console.error('[MindSage] Backend returned status:', response.status);
    }
  } catch (error) {
    console.error('[MindSage] Failed to connect to backend:', error.message);
  }
})();
