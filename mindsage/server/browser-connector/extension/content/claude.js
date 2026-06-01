/**
 * MindSage Capture Extension - Claude Content Script
 * Uses Claude.ai's internal API to fetch and sync conversations
 */

(function() {
  'use strict';

  const SITE = 'claude';
  const API_BASE = 'https://claude.ai/api';
  const SYNC_BATCH_SIZE = 50;
  const SYNC_DELAY = 500; // Delay between API calls to avoid rate limiting

  let isSyncingAll = false;
  let syncAborted = false;
  let organizationId = null;

  /**
   * Get conversation ID from URL
   * Claude URLs: /chat/[conversation-id] or /project/[project-id]/chat/[conversation-id]
   */
  function getConversationId() {
    const match = window.location.pathname.match(/\/chat\/([a-zA-Z0-9-]+)/);
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
      console.log('[MindSage:claude] Auth status reported:', authenticated);
    } catch (error) {
      console.error('[MindSage:claude] Failed to report auth status:', error);
    }
  }

  /**
   * Get organization ID from the page or API
   */
  async function getOrganizationId() {
    if (organizationId) return organizationId;

    console.log('[MindSage:claude] Checking auth via organizations API...');

    try {
      const response = await fetch(`${API_BASE}/organizations`, {
        credentials: 'include',
      });

      // 401/403 means not logged in
      if (response.status === 401 || response.status === 403) {
        console.log('[MindSage:claude] Not logged in (got', response.status, ')');
        return null;
      }

      if (!response.ok) {
        console.log('[MindSage:claude] API error:', response.status);
        return null;
      }

      const orgs = await response.json();

      if (orgs && orgs.length > 0) {
        organizationId = orgs[0].uuid;
        console.log('[MindSage:claude] ✓ Logged in, org:', organizationId);
        reportAuthStatus(true);
        return organizationId;
      }

      return null;
    } catch (error) {
      console.error('[MindSage:claude] Auth check failed:', error.message);
      return null;
    }
  }

  /**
   * Make authenticated API request
   */
  async function apiRequest(endpoint, options = {}) {
    const url = endpoint.startsWith('http') ? endpoint : `${API_BASE}${endpoint}`;

    const response = await fetch(url, {
      ...options,
      credentials: 'include',
      headers: {
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
    const orgId = await getOrganizationId();
    if (!orgId) {
      throw new Error('Not authenticated - no organization ID');
    }

    const conversations = [];
    let cursor = null;
    let hasMore = true;

    console.log('[MindSage:claude] Fetching conversation list...');

    while (hasMore) {
      const url = cursor
        ? `/organizations/${orgId}/chat_conversations?cursor=${cursor}&limit=${SYNC_BATCH_SIZE}`
        : `/organizations/${orgId}/chat_conversations?limit=${SYNC_BATCH_SIZE}`;

      const data = await apiRequest(url);

      if (data && data.length > 0) {
        conversations.push(...data);
        console.log(`[MindSage:claude] Fetched ${conversations.length} conversations...`);

        // Check if there are more (Claude uses cursor-based pagination)
        if (data.length === SYNC_BATCH_SIZE) {
          cursor = data[data.length - 1].uuid;
        } else {
          hasMore = false;
        }
      } else {
        hasMore = false;
      }

      // Small delay to avoid rate limiting
      await new Promise(r => setTimeout(r, 200));
    }

    console.log(`[MindSage:claude] Total conversations found: ${conversations.length}`);
    return conversations;
  }

  /**
   * Fetch a single conversation by ID
   */
  async function fetchConversation(conversationId) {
    const orgId = await getOrganizationId();
    if (!orgId) {
      throw new Error('Not authenticated');
    }

    return apiRequest(`/organizations/${orgId}/chat_conversations/${conversationId}`);
  }

  /**
   * Convert API conversation to MindSage format
   */
  function convertConversation(apiConversation) {
    const messages = [];

    // Claude returns chat_messages array
    const chatMessages = apiConversation.chat_messages || [];

    for (const msg of chatMessages) {
      const role = msg.sender === 'human' ? 'user' : 'assistant';

      // Extract text content
      let content = '';
      if (Array.isArray(msg.content)) {
        for (const part of msg.content) {
          if (part.type === 'text') {
            content += part.text || '';
          }
        }
      } else if (typeof msg.content === 'string') {
        content = msg.content;
      } else if (msg.text) {
        content = msg.text;
      }

      if (!content.trim()) {
        continue;
      }

      messages.push({
        id: msg.uuid,
        role: role,
        content: content.trim(),
        timestamp: msg.created_at || null,
        model: msg.model || apiConversation.model || null,
      });
    }

    return {
      site: SITE,
      conversationId: apiConversation.uuid,
      conversationUrl: `https://claude.ai/chat/${apiConversation.uuid}`,
      title: apiConversation.name || 'Untitled',
      messages: messages,
      createTime: apiConversation.created_at || null,
      updateTime: apiConversation.updated_at || null,
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
        console.log('[MindSage:claude] Capture successful:', payload.conversationId);
        return true;
      } else {
        console.warn('[MindSage:claude] Capture failed:', response?.error);
        return false;
      }
    } catch (error) {
      console.error('[MindSage:claude] Failed to send capture:', error);
      return false;
    }
  }

  /**
   * Capture current conversation
   */
  async function captureCurrentConversation() {
    const conversationId = getConversationId();
    if (!conversationId) {
      console.log('[MindSage:claude] No conversation ID in URL');
      return false;
    }

    try {
      console.log('[MindSage:claude] Capturing conversation:', conversationId);
      const apiData = await fetchConversation(conversationId);
      const payload = convertConversation(apiData);

      if (payload.messages.length === 0) {
        console.log('[MindSage:claude] No messages in conversation');
        return false;
      }

      return await sendCapture(payload);
    } catch (error) {
      console.error('[MindSage:claude] Failed to capture conversation:', error);
      return false;
    }
  }

  /**
   * Sync all conversations
   */
  async function syncAllConversations() {
    if (isSyncingAll) {
      console.log('[MindSage:claude] Sync already in progress');
      return { success: false, error: 'Sync already in progress' };
    }

    isSyncingAll = true;
    syncAborted = false;

    console.log('[MindSage:claude] Starting sync of all conversations...');

    // Send progress update - starting
    chrome.runtime.sendMessage({
      type: 'syncProgress',
      payload: { total: 0, synced: 0, failed: 0, status: 'starting', site: SITE }
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
        payload: { total: conversations.length, synced: 0, failed: 0, status: 'syncing', site: SITE }
      });

      // Fetch and sync each conversation
      for (const conv of conversations) {
        if (syncAborted) {
          console.log('[MindSage:claude] Sync aborted by user');
          break;
        }

        try {
          console.log(`[MindSage:claude] Syncing ${synced + failed + 1}/${conversations.length}: ${conv.name || 'Untitled'}`);

          const apiData = await fetchConversation(conv.uuid);
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
              current: conv.name || 'Untitled',
              site: SITE
            }
          });

          // Delay between requests to avoid rate limiting
          await new Promise(r => setTimeout(r, SYNC_DELAY));

        } catch (error) {
          console.error(`[MindSage:claude] Failed to sync conversation ${conv.uuid}:`, error);
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
        payload: { ...result, status: 'complete', site: SITE }
      });

      // Store sync completion
      await chrome.storage.local.set({
        claude_initialSyncComplete: true,
        claude_lastSyncTime: new Date().toISOString(),
        claude_lastSyncCount: synced
      });

      console.log(`[MindSage:claude] Sync complete. Synced: ${synced}, Failed: ${failed}`);

      // Report sync completion to backend (for headless mode)
      try {
        await chrome.runtime.sendMessage({
          type: 'syncComplete',
          result: result,
        });
      } catch (error) {
        console.error('[MindSage:claude] Failed to report sync completion:', error);
      }

      return result;

    } catch (error) {
      isSyncingAll = false;
      console.error('[MindSage:claude] Sync failed:', error);
      return { success: false, error: error.message };
    }
  }

  /**
   * Abort ongoing sync
   */
  function abortSync() {
    syncAborted = true;
    console.log('[MindSage:claude] Sync abort requested');
  }

  /**
   * Check if user is logged in
   */
  async function isLoggedIn() {
    try {
      const orgId = await getOrganizationId();
      return !!orgId;
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
    const stored = await chrome.storage.local.get(['claude_initialSyncComplete', 'claude_lastSyncTime']);

    if (stored.claude_initialSyncComplete && !forceSync) {
      console.log('[MindSage:claude] Initial sync already completed on:', stored.claude_lastSyncTime);
      return;
    }

    if (forceSync) {
      console.log('[MindSage:claude] Force sync requested via URL parameter');
    }

    // Check if logged in
    console.log('[MindSage:claude] Checking login status...');
    const loggedIn = await isLoggedIn();

    if (!loggedIn) {
      console.log('[MindSage:claude] Not logged in, skipping auto-sync');
      // Report sync failure for headless mode
      if (forceSync) {
        try {
          await chrome.runtime.sendMessage({
            type: 'syncComplete',
            result: { success: false, error: 'Not logged in' },
          });
        } catch (e) {
          console.error('[MindSage:claude] Failed to report sync failure:', e);
        }
      }
      return;
    }

    console.log('[MindSage:claude] User is logged in, starting automatic sync...');

    // Small delay before starting
    await new Promise(r => setTimeout(r, 2000));

    await syncAllConversations();
  }

  /**
   * Listen for messages from background script
   */
  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    console.log('[MindSage:claude] Received message:', message.type);

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
        sendResponse({ conversations: conversations.map(c => ({ id: c.uuid, title: c.name })) });
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
      console.log('[MindSage:claude] URL changed, capturing conversation:', conversationId);
      // Delay to let the page load
      setTimeout(() => {
        captureCurrentConversation();
      }, 1500);
    }
  }

  /**
   * Check if user appears to be logged in based on DOM indicators
   */
  function checkDomLoginIndicators() {
    // Check for common Claude UI elements that appear when logged in
    const hasConversationList = document.querySelector('[data-testid="conversation-list"]') ||
                                 document.querySelector('.conversation-list') ||
                                 document.querySelector('[class*="ConversationList"]') ||
                                 document.querySelector('nav [class*="conversation"]');

    const hasNewChatButton = document.querySelector('[data-testid="new-chat-button"]') ||
                              document.querySelector('button[aria-label*="New chat"]') ||
                              document.querySelector('button[aria-label*="new conversation"]') ||
                              document.querySelector('[class*="StartNewChat"]') ||
                              document.querySelector('button[class*="new-chat"]');

    const hasUserMenu = document.querySelector('[data-testid="user-menu"]') ||
                        document.querySelector('[class*="UserMenu"]') ||
                        document.querySelector('[aria-label*="Account"]') ||
                        document.querySelector('[class*="Avatar"]') ||
                        document.querySelector('[class*="ProfileMenu"]');

    const hasMainContent = document.querySelector('main') &&
                           !document.querySelector('[data-testid="login-button"]') &&
                           !document.querySelector('button[data-testid*="sign"]');

    // Check for sidebar with history
    const hasSidebar = document.querySelector('aside') ||
                       document.querySelector('[class*="Sidebar"]') ||
                       document.querySelector('nav[class*="navigation"]');

    // Check for message input area (only visible when logged in)
    const hasMessageInput = document.querySelector('textarea[placeholder*="message"]') ||
                             document.querySelector('[contenteditable="true"]') ||
                             document.querySelector('[class*="ProseMirror"]') ||
                             document.querySelector('[class*="composer"]');

    // Check URL - if we're on /chat/ path, we're likely logged in
    const isOnChatPath = window.location.pathname.includes('/chat');

    // Check for login/signup pages
    const isOnLoginPage = window.location.pathname.includes('/login') ||
                          window.location.pathname.includes('/signup') ||
                          document.querySelector('form[action*="login"]') ||
                          document.querySelector('input[type="password"]');

    if (isOnLoginPage) {
      return false;
    }

    return hasConversationList || hasNewChatButton || hasUserMenu ||
           (hasMainContent && hasSidebar) || hasMessageInput ||
           (isOnChatPath && !isOnLoginPage);
  }

  /**
   * Proactively check and report auth status
   */
  async function checkAndReportAuth() {
    const loggedIn = await isLoggedIn();
    console.log('[MindSage:claude] Auth check result:', loggedIn ? 'logged in' : 'not logged in');
    return loggedIn;
  }

  /**
   * Initialize content script
   */
  async function initialize() {
    console.log('[MindSage:claude] Claude content script loaded on', window.location.href);

    // Debug: notify backend via background script
    try {
      await chrome.runtime.sendMessage({
        type: 'debug',
        data: { event: 'content_script_loaded', site: 'claude', url: window.location.href }
      });
    } catch (e) {
      console.error('[MindSage:claude] Failed to send debug message:', e);
    }

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
      if (!organizationId) {
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
