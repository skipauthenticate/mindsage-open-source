/**
 * MindSage Capture Extension - Gemini Content Script
 * Captures conversations from Gemini (gemini.google.com)
 *
 * Note: Gemini's API is not as easily accessible as ChatGPT/Claude.
 * This script monitors DOM changes and extracts conversation content.
 */

(function() {
  'use strict';

  const SITE = 'gemini';
  const SYNC_DELAY = 1000; // Delay between syncs to avoid overwhelming

  let isSyncingAll = false;
  let syncAborted = false;
  let lastCapturedContent = '';

  /**
   * Get conversation ID from URL or generate one
   * Gemini URLs: /app/[conversation-id] or /app
   */
  function getConversationId() {
    // Try to extract from URL
    const match = window.location.pathname.match(/\/app\/([a-zA-Z0-9-_]+)/);
    if (match) return match[1];

    // Generate from page content hash
    const content = document.body.innerText || '';
    if (content.length > 100) {
      return 'gemini-' + hashCode(content.substring(0, 500));
    }

    return null;
  }

  /**
   * Simple hash function for generating IDs
   */
  function hashCode(str) {
    let hash = 0;
    for (let i = 0; i < str.length; i++) {
      const char = str.charCodeAt(i);
      hash = ((hash << 5) - hash) + char;
      hash = hash & hash;
    }
    return Math.abs(hash).toString(36);
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
      console.log('[MindSage:gemini] Auth status reported:', authenticated);
    } catch (error) {
      console.error('[MindSage:gemini] Failed to report auth status:', error);
    }
  }

  /**
   * Check if user is logged in
   */
  function isLoggedIn() {
    // Check for common Gemini UI elements that appear when logged in
    // These selectors may need to be updated as Gemini's UI changes
    const hasConversationUI = document.querySelector('[data-test-id="conversation"]') ||
                              document.querySelector('.conversation-container') ||
                              document.querySelector('model-response') ||
                              document.querySelector('user-query');

    // Check if login button is NOT present
    const hasLoginButton = document.querySelector('[data-test-id="sign-in"]') ||
                           document.querySelector('a[href*="accounts.google.com"]');

    return hasConversationUI || !hasLoginButton;
  }

  /**
   * Extract messages from the DOM
   */
  function extractMessages() {
    const messages = [];

    // Try multiple selectors for Gemini's UI
    // Gemini uses web components, so selectors may vary
    const messageContainers = document.querySelectorAll(
      'user-query, model-response, .conversation-turn, [data-message-id]'
    );

    messageContainers.forEach((container, index) => {
      let role = 'user';
      let content = '';

      // Determine role based on element type or class
      if (container.tagName === 'MODEL-RESPONSE' ||
          container.classList.contains('model-response') ||
          container.getAttribute('data-is-model') === 'true') {
        role = 'assistant';
      }

      // Extract text content, handling nested markdown
      const textContent = container.querySelector('.message-content, .response-text, .markdown-content');
      if (textContent) {
        content = textContent.innerText.trim();
      } else {
        content = container.innerText.trim();
      }

      if (content && content.length > 0) {
        messages.push({
          id: `gemini-msg-${index}-${hashCode(content.substring(0, 50))}`,
          role: role,
          content: content,
          timestamp: new Date().toISOString(),
        });
      }
    });

    return messages;
  }

  /**
   * Get conversation title from page
   */
  function getConversationTitle() {
    // Try various selectors for title
    const titleElement = document.querySelector(
      'h1.conversation-title, .chat-title, [data-test-id="conversation-title"], title'
    );

    if (titleElement) {
      const text = titleElement.innerText || titleElement.textContent;
      if (text && text !== 'Gemini' && text.length < 200) {
        return text.trim();
      }
    }

    // Fall back to first user message
    const firstUserMessage = document.querySelector('user-query, .user-message');
    if (firstUserMessage) {
      const text = firstUserMessage.innerText.trim();
      return text.substring(0, 50) + (text.length > 50 ? '...' : '');
    }

    return 'Gemini Conversation';
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
        console.log('[MindSage:gemini] Capture successful:', payload.conversationId);
        return true;
      } else {
        console.warn('[MindSage:gemini] Capture failed:', response?.error);
        return false;
      }
    } catch (error) {
      console.error('[MindSage:gemini] Failed to send capture:', error);
      return false;
    }
  }

  /**
   * Capture current conversation
   */
  async function captureCurrentConversation() {
    const conversationId = getConversationId();
    if (!conversationId) {
      console.log('[MindSage:gemini] No conversation ID found');
      return false;
    }

    const messages = extractMessages();
    if (messages.length === 0) {
      console.log('[MindSage:gemini] No messages found');
      return false;
    }

    // Check if content has changed since last capture
    const contentHash = messages.map(m => m.content).join('|||');
    if (contentHash === lastCapturedContent) {
      console.log('[MindSage:gemini] Content unchanged, skipping capture');
      return true;
    }
    lastCapturedContent = contentHash;

    const payload = {
      site: SITE,
      conversationId: conversationId,
      conversationUrl: window.location.href,
      title: getConversationTitle(),
      messages: messages,
      fullConversation: true,
    };

    console.log('[MindSage:gemini] Capturing conversation:', conversationId, messages.length, 'messages');
    return await sendCapture(payload);
  }

  /**
   * Sync all conversations (Gemini doesn't have easy API access)
   * This captures the current visible conversation
   */
  async function syncAllConversations() {
    if (isSyncingAll) {
      console.log('[MindSage:gemini] Sync already in progress');
      return { success: false, error: 'Sync already in progress' };
    }

    isSyncingAll = true;
    syncAborted = false;

    console.log('[MindSage:gemini] Starting sync...');

    // Send progress update - starting
    chrome.runtime.sendMessage({
      type: 'syncProgress',
      payload: { total: 1, synced: 0, failed: 0, status: 'starting', site: SITE }
    });

    try {
      // Check if logged in
      if (!isLoggedIn()) {
        isSyncingAll = false;
        return { success: false, error: 'Not logged in. Please log in to Gemini.' };
      }

      // Report auth status
      reportAuthStatus(true);

      // Capture current conversation
      const success = await captureCurrentConversation();

      isSyncingAll = false;

      const result = {
        success: true,
        synced: success ? 1 : 0,
        failed: success ? 0 : 1,
        total: 1
      };

      // Send completion message
      chrome.runtime.sendMessage({
        type: 'syncProgress',
        payload: { ...result, status: 'complete', site: SITE }
      });

      // Store sync completion
      await chrome.storage.local.set({
        gemini_initialSyncComplete: true,
        gemini_lastSyncTime: new Date().toISOString(),
        gemini_lastSyncCount: result.synced
      });

      console.log('[MindSage:gemini] Sync complete.');

      // Report sync completion to backend (for headless mode)
      try {
        await chrome.runtime.sendMessage({
          type: 'syncComplete',
          result: result,
        });
      } catch (error) {
        console.error('[MindSage:gemini] Failed to report sync completion:', error);
      }

      return result;

    } catch (error) {
      isSyncingAll = false;
      console.error('[MindSage:gemini] Sync failed:', error);
      return { success: false, error: error.message };
    }
  }

  /**
   * Abort ongoing sync
   */
  function abortSync() {
    syncAborted = true;
    console.log('[MindSage:gemini] Sync abort requested');
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
    const stored = await chrome.storage.local.get(['gemini_initialSyncComplete', 'gemini_lastSyncTime']);

    if (stored.gemini_initialSyncComplete && !forceSync) {
      console.log('[MindSage:gemini] Initial sync already completed on:', stored.gemini_lastSyncTime);
      return;
    }

    if (forceSync) {
      console.log('[MindSage:gemini] Force sync requested via URL parameter');
    }

    // Check if logged in
    console.log('[MindSage:gemini] Checking login status...');

    if (!isLoggedIn()) {
      console.log('[MindSage:gemini] Not logged in, skipping auto-sync');
      // Report sync failure for headless mode
      if (forceSync) {
        try {
          await chrome.runtime.sendMessage({
            type: 'syncComplete',
            result: { success: false, error: 'Not logged in' },
          });
        } catch (e) {
          console.error('[MindSage:gemini] Failed to report sync failure:', e);
        }
      }
      return;
    }

    console.log('[MindSage:gemini] User is logged in, starting automatic sync...');
    reportAuthStatus(true);

    // Small delay before starting
    await new Promise(r => setTimeout(r, 2000));

    await syncAllConversations();
  }

  /**
   * Listen for messages from background script
   */
  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    console.log('[MindSage:gemini] Received message:', message.type);

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

    return false;
  });

  /**
   * Handle URL changes (SPA navigation)
   */
  let lastUrl = window.location.href;
  function handleUrlChange() {
    if (window.location.href === lastUrl) return;
    lastUrl = window.location.href;
    lastCapturedContent = ''; // Reset content tracking

    console.log('[MindSage:gemini] URL changed, capturing conversation...');
    // Delay to let the page load
    setTimeout(() => {
      captureCurrentConversation();
    }, 2000);
  }

  /**
   * Initialize content script
   */
  async function initialize() {
    console.log('[MindSage:gemini] Gemini content script loaded');

    // Wait for page to fully load
    await new Promise(r => setTimeout(r, 3000));

    // Check login and report auth
    if (isLoggedIn()) {
      reportAuthStatus(true);
    }

    // Capture current conversation if present
    const messages = extractMessages();
    if (messages.length > 0) {
      setTimeout(() => {
        captureCurrentConversation();
      }, 2000);
    }

    // Check for auto-sync
    setTimeout(() => {
      checkAndAutoSync();
    }, 4000);

    // Listen for URL changes (SPA navigation)
    const urlObserver = new MutationObserver(handleUrlChange);
    urlObserver.observe(document.body, { childList: true, subtree: true });

    // Also use History API events
    window.addEventListener('popstate', handleUrlChange);

    // Intercept pushState/replaceState
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

    // Also observe for new content (Gemini dynamically loads responses)
    const contentObserver = new MutationObserver(() => {
      // Debounce captures when content changes
      clearTimeout(window.geminiCaptureTimeout);
      window.geminiCaptureTimeout = setTimeout(() => {
        captureCurrentConversation();
      }, 3000);
    });

    // Watch for conversation changes
    const conversationContainer = document.querySelector('.conversation-container, [data-test-id="conversation"], main');
    if (conversationContainer) {
      contentObserver.observe(conversationContainer, { childList: true, subtree: true });
    }
  }

  // Start when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initialize);
  } else {
    initialize();
  }

})();
