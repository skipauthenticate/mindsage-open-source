/**
 * MindSage Capture Extension - ChatGPT Content Script
 * Uses ChatGPT's internal API to fetch and sync conversations
 * Inspired by https://github.com/pionxzh/chatgpt-exporter
 */

(function() {
  'use strict';

  const SITE = 'chatgpt';
  const API_BASE = 'https://chatgpt.com/backend-api';
  const SYNC_BATCH_SIZE = 100;
  const SYNC_DELAY = 500; // Delay between API calls to avoid rate limiting

  let isSyncingAll = false;
  let syncAborted = false;
  let accessToken = null;

  /**
   * Get conversation ID from URL
   */
  function getConversationId() {
    const match = window.location.pathname.match(/\/c\/([a-zA-Z0-9-]+)/);
    return match ? match[1] : null;
  }

  /**
   * Report authentication status to backend via background script
   */
  async function reportAuthStatus(authenticated) {
    try {
      await chrome.runtime.sendMessage({
        type: 'reportAuth',
        site: SITE,
        authenticated: authenticated,
      });
      console.log('[MindSage] Auth status reported:', authenticated);
    } catch (error) {
      console.error('[MindSage] Failed to report auth status:', error);
    }
  }

  /**
   * Get access token from the page
   */
  async function getAccessToken() {
    if (accessToken) return accessToken;

    try {
      const response = await fetch('https://chatgpt.com/api/auth/session', {
        credentials: 'include',
      });

      // 401/403 means not logged in
      if (response.status === 401 || response.status === 403) {
        console.log('[MindSage] Not logged in (got', response.status, ')');
        return null;
      }

      if (!response.ok) {
        console.log('[MindSage] Session API error:', response.status);
        return null;
      }

      const data = await response.json();
      accessToken = data.accessToken;

      if (accessToken) {
        console.log('[MindSage] ✓ Logged in, got access token');
        reportAuthStatus(true);
      }

      return accessToken;
    } catch (error) {
      console.error('[MindSage] Auth check failed:', error.message);
      return null;
    }
  }

  /**
   * Make authenticated API request
   */
  async function apiRequest(endpoint, options = {}) {
    const token = await getAccessToken();
    if (!token) {
      throw new Error('Not authenticated');
    }

    const url = endpoint.startsWith('http') ? endpoint : `${API_BASE}${endpoint}`;

    const response = await fetch(url, {
      ...options,
      credentials: 'include',
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json',
        ...options.headers,
      },
    });

    if (!response.ok) {
      throw new Error(`API request failed: ${response.status} ${response.statusText}`);
    }

    return response.json();
  }

  /**
   * Fetch all conversations with pagination
   */
  async function fetchAllConversations() {
    const conversations = [];
    let offset = 0;
    let hasMore = true;

    console.log('[MindSage] Fetching conversation list...');

    while (hasMore) {
      const data = await apiRequest(`/conversations?offset=${offset}&limit=${SYNC_BATCH_SIZE}`);

      if (data.items && data.items.length > 0) {
        conversations.push(...data.items);
        offset += data.items.length;
        console.log(`[MindSage] Fetched ${conversations.length} conversations...`);

        // Check if there are more
        hasMore = data.has_missing_conversations !== false && data.items.length === SYNC_BATCH_SIZE;
      } else {
        hasMore = false;
      }

      // Small delay to avoid rate limiting
      await new Promise(r => setTimeout(r, 200));
    }

    console.log(`[MindSage] Total conversations found: ${conversations.length}`);
    return conversations;
  }

  /**
   * Fetch a single conversation by ID
   */
  async function fetchConversation(conversationId) {
    return apiRequest(`/conversation/${conversationId}`);
  }

  /**
   * Convert API conversation to MindSage format
   */
  function convertConversation(apiConversation) {
    const messages = [];

    // API returns a mapping object with message nodes
    const mapping = apiConversation.mapping || {};

    // Find all message nodes and sort by create_time
    const messageNodes = Object.values(mapping)
      .filter(node => node.message && node.message.content)
      .sort((a, b) => {
        const timeA = a.message.create_time || 0;
        const timeB = b.message.create_time || 0;
        return timeA - timeB;
      });

    for (const node of messageNodes) {
      const msg = node.message;
      const role = msg.author?.role;

      // Only include user and assistant messages
      if (role !== 'user' && role !== 'assistant') {
        continue;
      }

      // Extract content
      let content = '';
      const contentParts = msg.content?.parts || [];

      for (const part of contentParts) {
        if (typeof part === 'string') {
          content += part;
        } else if (part?.text) {
          content += part.text;
        }
      }

      if (!content.trim()) {
        continue;
      }

      messages.push({
        id: msg.id,
        role: role,
        content: content.trim(),
        timestamp: msg.create_time ? new Date(msg.create_time * 1000).toISOString() : null,
        model: msg.metadata?.model_slug || null,
      });
    }

    return {
      site: SITE,
      conversationId: apiConversation.conversation_id,
      conversationUrl: `https://chatgpt.com/c/${apiConversation.conversation_id}`,
      title: apiConversation.title || 'Untitled',
      messages: messages,
      createTime: apiConversation.create_time ? new Date(apiConversation.create_time * 1000).toISOString() : null,
      updateTime: apiConversation.update_time ? new Date(apiConversation.update_time * 1000).toISOString() : null,
      fullConversation: true,
    };
  }

  /**
   * Send capture to background worker
   */
  async function sendCapture(payload) {
    try {
      const response = await chrome.runtime.sendMessage({
        type: 'capture',
        payload: payload,
      });

      if (response?.success) {
        console.log('[MindSage] Capture successful:', payload.conversationId);
        return true;
      } else {
        console.warn('[MindSage] Capture failed:', response?.error);
        return false;
      }
    } catch (error) {
      console.error('[MindSage] Failed to send capture:', error);
      return false;
    }
  }

  /**
   * Capture current conversation
   */
  async function captureCurrentConversation() {
    const conversationId = getConversationId();
    if (!conversationId) {
      console.log('[MindSage] No conversation ID in URL');
      return false;
    }

    try {
      console.log('[MindSage] Capturing conversation:', conversationId);
      const apiData = await fetchConversation(conversationId);
      const payload = convertConversation(apiData);

      if (payload.messages.length === 0) {
        console.log('[MindSage] No messages in conversation');
        return false;
      }

      return await sendCapture(payload);
    } catch (error) {
      console.error('[MindSage] Failed to capture conversation:', error);
      return false;
    }
  }

  /**
   * Sync all conversations
   */
  async function syncAllConversations() {
    if (isSyncingAll) {
      console.log('[MindSage] Sync already in progress');
      return { success: false, error: 'Sync already in progress' };
    }

    isSyncingAll = true;
    syncAborted = false;

    console.log('[MindSage] Starting sync of all conversations...');

    // Send progress update - starting
    chrome.runtime.sendMessage({
      type: 'syncProgress',
      payload: { total: 0, synced: 0, failed: 0, status: 'starting' }
    });

    try {
      // Fetch all conversation metadata
      const conversations = await fetchAllConversations();

      if (conversations.length === 0) {
        isSyncingAll = false;
        return { success: false, error: 'No conversations found. Make sure you are logged in.' };
      }

      let synced = 0;
      let failed = 0;

      // Send progress update with total
      chrome.runtime.sendMessage({
        type: 'syncProgress',
        payload: { total: conversations.length, synced: 0, failed: 0, status: 'syncing' }
      });

      // Fetch and sync each conversation
      for (const conv of conversations) {
        if (syncAborted) {
          console.log('[MindSage] Sync aborted by user');
          break;
        }

        try {
          console.log(`[MindSage] Syncing ${synced + failed + 1}/${conversations.length}: ${conv.title}`);

          const apiData = await fetchConversation(conv.id);
          const payload = convertConversation(apiData);

          if (payload.messages.length > 0) {
            const success = await sendCapture(payload);
            if (success) {
              synced++;
            } else {
              failed++;
            }
          } else {
            // Empty conversation, skip
            synced++;
          }

          // Send progress update
          chrome.runtime.sendMessage({
            type: 'syncProgress',
            payload: {
              total: conversations.length,
              synced,
              failed,
              status: 'syncing',
              current: conv.title
            }
          });

          // Delay between requests to avoid rate limiting
          await new Promise(r => setTimeout(r, SYNC_DELAY));

        } catch (error) {
          console.error(`[MindSage] Failed to sync conversation ${conv.id}:`, error);
          failed++;
        }
      }

      isSyncingAll = false;

      const result = {
        success: true,
        synced,
        failed,
        total: conversations.length
      };

      // Send completion message
      chrome.runtime.sendMessage({
        type: 'syncProgress',
        payload: { ...result, status: 'complete' }
      });

      // Store sync completion
      await chrome.storage.local.set({
        initialSyncComplete: true,
        lastSyncTime: new Date().toISOString(),
        lastSyncCount: synced
      });

      console.log(`[MindSage] Sync complete. Synced: ${synced}, Failed: ${failed}`);

      // Report sync completion to backend (for headless mode)
      try {
        await chrome.runtime.sendMessage({
          type: 'syncComplete',
          result: result,
        });
      } catch (error) {
        console.error('[MindSage] Failed to report sync completion:', error);
      }

      return result;

    } catch (error) {
      isSyncingAll = false;
      console.error('[MindSage] Sync failed:', error);
      return { success: false, error: error.message };
    }
  }

  /**
   * Abort ongoing sync
   */
  function abortSync() {
    syncAborted = true;
    console.log('[MindSage] Sync abort requested');
  }

  /**
   * Check if user is logged in
   */
  async function isLoggedIn() {
    try {
      const token = await getAccessToken();
      return !!token;
    } catch {
      return false;
    }
  }

  /**
   * Check if force sync is requested via URL parameter
   */
  function isForceSyncRequested() {
    const urlParams = new URLSearchParams(window.location.search);
    return urlParams.get('mindsage-sync') === 'true';
  }

  /**
   * Auto-sync if not done before or if force sync is requested
   */
  async function checkAndAutoSync() {
    const forceSync = isForceSyncRequested();

    // Check if we've already done initial sync
    const stored = await chrome.storage.local.get(['initialSyncComplete', 'lastSyncTime']);

    if (stored.initialSyncComplete && !forceSync) {
      console.log('[MindSage] Initial sync already completed on:', stored.lastSyncTime);
      return;
    }

    if (forceSync) {
      console.log('[MindSage] Force sync requested via URL parameter');
    }

    // Check if logged in
    console.log('[MindSage] Checking login status...');
    const loggedIn = await isLoggedIn();

    if (!loggedIn) {
      console.log('[MindSage] Not logged in, skipping auto-sync');
      // Report sync failure for headless mode
      if (forceSync) {
        try {
          await chrome.runtime.sendMessage({
            type: 'syncComplete',
            result: { success: false, error: 'Not logged in' },
          });
        } catch (e) {
          console.error('[MindSage] Failed to report sync failure:', e);
        }
      }
      return;
    }

    console.log('[MindSage] User is logged in, starting automatic sync...');

    // Small delay before starting
    await new Promise(r => setTimeout(r, 2000));

    await syncAllConversations();
  }

  /**
   * Listen for messages from background script
   */
  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    console.log('[MindSage] Received message:', message.type);

    if (message.type === 'syncAll') {
      syncAllConversations().then(sendResponse);
      return true;
    }

    if (message.type === 'abortSync') {
      abortSync();
      sendResponse({ success: true });
      return true;
    }

    if (message.type === 'captureNow') {
      captureCurrentConversation().then((success) => sendResponse({ success }));
      return true;
    }

    if (message.type === 'getConversationList') {
      fetchAllConversations().then((conversations) => {
        sendResponse({ conversations: conversations.map(c => ({ id: c.id, title: c.title })) });
      });
      return true;
    }

    return false;
  });

  /**
   * Handle URL changes (SPA navigation)
   */
  let lastUrl = window.location.href;
  function handleUrlChange() {
    if (window.location.href === lastUrl) return;
    lastUrl = window.location.href;

    const conversationId = getConversationId();
    if (conversationId) {
      console.log('[MindSage] URL changed, capturing conversation:', conversationId);
      // Delay to let the page load
      setTimeout(() => {
        captureCurrentConversation();
      }, 1500);
    }
  }

  /**
   * Check auth status
   */
  async function checkAndReportAuth() {
    const loggedIn = await isLoggedIn();
    console.log('[MindSage] Auth check result:', loggedIn ? 'logged in' : 'not logged in');
    return loggedIn;
  }

  /**
   * Initialize content script
   */
  async function initialize() {
    console.log('[MindSage] ChatGPT content script loaded');

    // Check auth on page load
    setTimeout(() => checkAndReportAuth(), 2000);

    // Capture current conversation if on one
    const conversationId = getConversationId();
    if (conversationId) {
      setTimeout(() => captureCurrentConversation(), 3000);
    }

    // Check for auto-sync
    setTimeout(() => checkAndAutoSync(), 4000);

    // Periodic auth check (every 15 seconds) if not yet authenticated
    setInterval(() => {
      if (!accessToken) {
        checkAndReportAuth();
      }
    }, 15000);

    // Listen for URL changes (SPA navigation)
    const urlObserver = new MutationObserver(handleUrlChange);
    urlObserver.observe(document.body, { childList: true, subtree: true });

    window.addEventListener('popstate', handleUrlChange);

    const originalPushState = history.pushState;
    const originalReplaceState = history.replaceState;

    history.pushState = function(...args) {
      originalPushState.apply(this, args);
      handleUrlChange();
    };

    history.replaceState = function(...args) {
      originalReplaceState.apply(this, args);
      handleUrlChange();
    };
  }

  // Start when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initialize);
  } else {
    initialize();
  }

})();
