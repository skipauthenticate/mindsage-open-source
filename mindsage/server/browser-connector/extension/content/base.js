/**
 * MindSage Capture Extension - Base Module
 * Shared functionality for all AI chat site content scripts
 */

const MindSageBase = {
  /**
   * Report authentication status to backend
   */
  async reportAuthStatus(site, authenticated) {
    try {
      await chrome.runtime.sendMessage({
        type: 'reportAuth',
        site: site,
        authenticated: authenticated,
      });
      console.log(`[MindSage:${site}] Auth status reported:`, authenticated);
    } catch (error) {
      console.error(`[MindSage:${site}] Failed to report auth status:`, error);
    }
  },

  /**
   * Send capture to background worker
   */
  async sendCapture(site, payload) {
    try {
      const response = await chrome.runtime.sendMessage({
        type: 'capture',
        payload: payload,
      });

      if (response?.success) {
        console.log(`[MindSage:${site}] Capture successful:`, payload.conversationId);
        return true;
      } else {
        console.warn(`[MindSage:${site}] Capture failed:`, response?.error);
        return false;
      }
    } catch (error) {
      console.error(`[MindSage:${site}] Failed to send capture:`, error);
      return false;
    }
  },

  /**
   * Report sync completion to backend (for headless mode)
   */
  async reportSyncComplete(site, result) {
    try {
      await chrome.runtime.sendMessage({
        type: 'syncComplete',
        result: result,
      });
      console.log(`[MindSage:${site}] Sync completion reported`);
    } catch (error) {
      console.error(`[MindSage:${site}] Failed to report sync completion:`, error);
    }
  },

  /**
   * Send sync progress update
   */
  sendSyncProgress(payload) {
    chrome.runtime.sendMessage({
      type: 'syncProgress',
      payload: payload,
    });
  },

  /**
   * Check if force sync is requested via URL parameter
   */
  isForceSyncRequested() {
    const urlParams = new URLSearchParams(window.location.search);
    return urlParams.get('mindsage-sync') === 'true';
  },

  /**
   * Get site-specific storage key
   */
  getStorageKey(site, key) {
    return `${site}_${key}`;
  },

  /**
   * Check and run auto-sync for a site
   */
  async checkAndAutoSync(site, isLoggedInFn, syncAllFn) {
    const forceSync = this.isForceSyncRequested();

    // Check if we've already done initial sync for this site
    const storageKey = this.getStorageKey(site, 'initialSyncComplete');
    const stored = await chrome.storage.local.get([storageKey, this.getStorageKey(site, 'lastSyncTime')]);

    if (stored[storageKey] && !forceSync) {
      console.log(`[MindSage:${site}] Initial sync already completed`);
      return;
    }

    if (forceSync) {
      console.log(`[MindSage:${site}] Force sync requested via URL parameter`);
    }

    // Check if logged in
    console.log(`[MindSage:${site}] Checking login status...`);
    const loggedIn = await isLoggedInFn();

    if (!loggedIn) {
      console.log(`[MindSage:${site}] Not logged in, skipping auto-sync`);
      if (forceSync) {
        await this.reportSyncComplete(site, { success: false, error: 'Not logged in' });
      }
      return;
    }

    console.log(`[MindSage:${site}] User is logged in, starting automatic sync...`);

    // Small delay before starting
    await new Promise(r => setTimeout(r, 2000));

    await syncAllFn();
  },

  /**
   * Store sync completion for a site
   */
  async storeSyncCompletion(site, synced) {
    const storageKey = this.getStorageKey(site, 'initialSyncComplete');
    await chrome.storage.local.set({
      [storageKey]: true,
      [this.getStorageKey(site, 'lastSyncTime')]: new Date().toISOString(),
      [this.getStorageKey(site, 'lastSyncCount')]: synced,
    });
  },

  /**
   * Setup URL change detection for SPA navigation
   */
  setupUrlChangeDetection(callback) {
    let lastUrl = window.location.href;

    const handleUrlChange = () => {
      if (window.location.href === lastUrl) return;
      lastUrl = window.location.href;
      callback();
    };

    // Mutation observer
    const urlObserver = new MutationObserver(handleUrlChange);
    urlObserver.observe(document.body, { childList: true, subtree: true });

    // History API events
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

    return urlObserver;
  },
};

// Export for use in content scripts
if (typeof window !== 'undefined') {
  window.MindSageBase = MindSageBase;
}
