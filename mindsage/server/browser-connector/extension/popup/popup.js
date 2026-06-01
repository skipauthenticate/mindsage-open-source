/**
 * MindSage Companion Extension - Popup Script
 * Handles setup flow and per-site cookie relay
 */

document.addEventListener('DOMContentLoaded', async () => {
  // Views
  const setupView = document.getElementById('setup-view');
  const connectedView = document.getElementById('connected-view');

  // Setup elements
  const serverUrlInput = document.getElementById('server-url');
  const testBtn = document.getElementById('test-btn');
  const saveBtn = document.getElementById('save-btn');
  const setupStatus = document.getElementById('setup-status');

  // Connected elements
  const connectionBar = document.getElementById('connection-bar');
  const connectionDot = document.getElementById('connection-dot');
  const connectionUrl = document.getElementById('connection-url');
  const changeServer = document.getElementById('change-server');
  const conversationCount = document.getElementById('conversation-count');
  const messageCount = document.getElementById('message-count');
  const openLink = document.getElementById('open-link');

  // Local sync elements (for Jetson mode)
  const localSyncSection = document.getElementById('local-sync-section');
  const syncBtn = document.getElementById('sync-btn');
  const syncStatus = document.getElementById('sync-status');
  const syncStatusText = document.getElementById('sync-status-text');
  const progressBarFill = document.getElementById('progress-bar-fill');

  let serverUrl = '';
  let isCompanionMode = false;
  let isSyncing = false;
  const connectingStates = {}; // per-site connecting state
  let knownSites = []; // cached sites from API

  /**
   * Show a status message in the setup view
   */
  function showSetupStatus(message, type) {
    setupStatus.textContent = message;
    setupStatus.className = `status-message ${type}`;
    setupStatus.classList.remove('hidden');
  }

  function hideSetupStatus() {
    setupStatus.classList.add('hidden');
  }

  /**
   * Switch between setup and connected views
   */
  function showSetupView() {
    setupView.classList.remove('hidden');
    connectedView.classList.add('hidden');
    serverUrlInput.value = serverUrl;
  }

  function showConnectedView() {
    setupView.classList.add('hidden');
    connectedView.classList.remove('hidden');

    // Update connection URL display
    const displayUrl = serverUrl.replace(/^https?:\/\//, '');
    connectionUrl.textContent = displayUrl;

    // Update Open MindSage link
    const frontendUrl = serverUrl.replace(':3003', ':8080');
    openLink.href = frontendUrl;

    // Show/hide local sync section (only for Jetson mode)
    if (!isCompanionMode) {
      localSyncSection.classList.remove('hidden');
    } else {
      localSyncSection.classList.add('hidden');
    }
  }

  /**
   * Update site badge status
   */
  function updateSiteBadge(site, status) {
    const badge = document.querySelector(`[data-badge="${site}"]`);
    if (!badge) return;

    badge.className = 'site-badge';
    switch (status) {
      case 'connected':
        badge.classList.add('connected');
        badge.textContent = 'Connected';
        break;
      case 'syncing':
        badge.classList.add('syncing');
        badge.textContent = 'Syncing...';
        break;
      default:
        badge.classList.add('not-connected');
        badge.textContent = 'Not Connected';
    }
  }

  /**
   * Load server URL and determine initial view
   */
  async function initialize() {
    const data = await chrome.storage.sync.get(['serverUrl', 'companionMode']);
    serverUrl = data.serverUrl || '';
    isCompanionMode = data.companionMode || false;

    if (serverUrl) {
      showConnectedView();
      await refreshStatus();
    } else {
      showSetupView();
    }
  }

  /**
   * Render site rows dynamically from API data
   */
  function renderSiteRows(sites) {
    const container = document.getElementById('sites-list');
    container.innerHTML = '';
    for (const site of sites) {
      const row = document.createElement('div');
      row.className = 'site-row';
      row.dataset.site = site.id;
      row.innerHTML = `
        <span class="site-name">${site.name}</span>
        <div class="site-actions">
          <span class="site-badge not-connected" data-badge="${site.id}">Not Connected</span>
          <button class="connect-btn" data-connect="${site.id}">Connect</button>
        </div>
      `;
      container.appendChild(row);
    }
    attachConnectHandlers();
  }

  /**
   * Attach click handlers to dynamically rendered connect buttons
   */
  function attachConnectHandlers() {
    document.querySelectorAll('[data-connect]').forEach(btn => {
      btn.addEventListener('click', async () => {
        const site = btn.dataset.connect;

        btn.disabled = true;
        btn.textContent = 'Connecting...';
        connectingStates[site] = true;
        updateSiteBadge(site, 'syncing');

        try {
          const result = await chrome.runtime.sendMessage({
            type: 'relayCookies',
            site: site,
            serverUrl: serverUrl,
          });

          if (result.success) {
            updateSiteBadge(site, 'syncing');
            btn.textContent = 'Syncing...';
            pollSiteStatus(site, btn);
          } else {
            updateSiteBadge(site, 'not-connected');
            btn.textContent = 'Connect';
            btn.disabled = false;
            connectingStates[site] = false;
            alert(`Failed to connect ${site}: ${result.error}`);
          }
        } catch (error) {
          updateSiteBadge(site, 'not-connected');
          btn.textContent = 'Connect';
          btn.disabled = false;
          connectingStates[site] = false;
          alert(`Error connecting ${site}: ${error.message}`);
        }
      });
    });
  }

  /**
   * Refresh connection and site status
   */
  async function refreshStatus() {
    if (!serverUrl) return;

    // Check backend connection
    try {
      const response = await chrome.runtime.sendMessage({
        type: 'testConnection',
        url: serverUrl,
      });

      if (response.success && response.connected) {
        connectionDot.className = 'status-dot connected';
        connectionBar.classList.remove('disconnected');
      } else {
        connectionDot.className = 'status-dot disconnected';
        connectionBar.classList.add('disconnected');
      }
    } catch {
      connectionDot.className = 'status-dot disconnected';
      connectionBar.classList.add('disconnected');
    }

    // Fetch stats and site auth status
    try {
      const statsResponse = await fetch(`${serverUrl}/api/browser-connector/stats`);
      if (statsResponse.ok) {
        const stats = await statsResponse.json();
        conversationCount.textContent = stats.totalConversations || 0;
        messageCount.textContent = stats.totalMessages || 0;
      }
    } catch {
      conversationCount.textContent = '-';
      messageCount.textContent = '-';
    }

    // Fetch per-site auth status and render site rows dynamically
    try {
      const sitesResponse = await fetch(`${serverUrl}/api/browser-connector/sites`);
      if (sitesResponse.ok) {
        const sitesData = await sitesResponse.json();

        // Render site rows if sites changed
        if (JSON.stringify(sitesData.sites.map(s => s.id)) !== JSON.stringify(knownSites.map(s => s.id))) {
          knownSites = sitesData.sites;
          renderSiteRows(sitesData.sites);
        }

        // Update badges
        for (const site of sitesData.sites) {
          if (connectingStates[site.id]) {
            updateSiteBadge(site.id, 'syncing');
          } else if (site.authenticated) {
            updateSiteBadge(site.id, 'connected');
          } else {
            updateSiteBadge(site.id, 'not-connected');
          }
        }
      }
    } catch {
      // Ignore - will retry
    }
  }

  /**
   * Test connection to a URL
   */
  testBtn.addEventListener('click', async () => {
    const url = serverUrlInput.value.trim().replace(/\/$/, '');
    if (!url) {
      showSetupStatus('Please enter a server URL', 'error');
      return;
    }

    testBtn.textContent = 'Testing...';
    testBtn.disabled = true;

    try {
      const response = await chrome.runtime.sendMessage({
        type: 'testConnection',
        url: url,
      });

      if (response.success && response.connected) {
        showSetupStatus('Connection successful!', 'success');
      } else {
        showSetupStatus(`Connection failed: ${response.error || 'Unknown error'}`, 'error');
      }
    } catch (error) {
      showSetupStatus(`Connection failed: ${error.message}`, 'error');
    }

    testBtn.textContent = 'Test';
    testBtn.disabled = false;
  });

  /**
   * Save server URL and switch to connected view
   */
  saveBtn.addEventListener('click', async () => {
    const url = serverUrlInput.value.trim().replace(/\/$/, '');
    if (!url) {
      showSetupStatus('Please enter a server URL', 'error');
      return;
    }

    saveBtn.textContent = 'Connecting...';
    saveBtn.disabled = true;

    try {
      // Test first
      const testResult = await chrome.runtime.sendMessage({
        type: 'testConnection',
        url: url,
      });

      if (!testResult.success || !testResult.connected) {
        showSetupStatus(`Cannot connect to ${url}. Is MindSage running?`, 'error');
        saveBtn.textContent = 'Save & Connect';
        saveBtn.disabled = false;
        return;
      }

      // Save URL
      serverUrl = url;
      await chrome.runtime.sendMessage({
        type: 'setServerUrl',
        url: url,
      });

      isCompanionMode = url !== 'http://localhost:3003';
      hideSetupStatus();
      showConnectedView();
      await refreshStatus();
    } catch (error) {
      showSetupStatus(`Error: ${error.message}`, 'error');
    }

    saveBtn.textContent = 'Save & Connect';
    saveBtn.disabled = false;
  });

  /**
   * Change server button
   */
  changeServer.addEventListener('click', () => {
    showSetupView();
  });

  // Connect button handlers are attached dynamically by attachConnectHandlers()
  // when site rows are rendered from the API response in refreshStatus().

  /**
   * Poll site status after cookie relay to detect sync completion
   */
  function pollSiteStatus(site, btn) {
    let polls = 0;
    const maxPolls = 60; // ~5 minutes at 5s intervals

    const interval = setInterval(async () => {
      polls++;
      if (polls > maxPolls) {
        clearInterval(interval);
        btn.textContent = 'Connect';
        btn.disabled = false;
        connectingStates[site] = false;
        updateSiteBadge(site, 'connected'); // Assume success if it took long
        return;
      }

      try {
        const response = await fetch(`${serverUrl}/api/browser-connector/auth-status?site=${site}`);
        if (response.ok) {
          const data = await response.json();
          if (data.authenticated) {
            clearInterval(interval);
            btn.textContent = 'Connect';
            btn.disabled = false;
            connectingStates[site] = false;
            updateSiteBadge(site, 'connected');
            await refreshStatus();
          }
        }
      } catch {
        // Ignore polling errors
      }
    }, 5000);
  }

  /**
   * Local sync button (Jetson mode only)
   */
  if (syncBtn) {
    syncBtn.addEventListener('click', async () => {
      if (isSyncing) {
        // Abort sync
        try {
          const tabs = await chrome.tabs.query({ url: ['*://chatgpt.com/*', '*://chat.openai.com/*'] });
          if (tabs.length > 0) {
            await chrome.tabs.sendMessage(tabs[0].id, { type: 'abortSync' });
          }
          updateSyncButton(false);
          syncStatus.style.display = 'none';
          chrome.storage.local.remove('syncProgress');
        } catch (error) {
          console.error('Failed to abort sync:', error);
        }
        return;
      }

      // Start sync
      try {
        const tabs = await chrome.tabs.query({ url: ['*://chatgpt.com/*', '*://chat.openai.com/*'] });
        if (tabs.length === 0) {
          alert('Please open ChatGPT in a tab first.');
          return;
        }

        await chrome.storage.local.remove(['initialSyncComplete']);
        updateSyncButton(true);
        syncStatus.style.display = 'block';
        syncStatus.className = 'sync-status progress';
        syncStatusText.textContent = 'Starting sync...';
        progressBarFill.style.width = '0%';

        chrome.tabs.sendMessage(tabs[0].id, { type: 'syncAll' }, (response) => {
          if (chrome.runtime.lastError) {
            console.error('Sync error:', chrome.runtime.lastError);
            alert('Failed to start sync. Make sure you are logged in to ChatGPT.');
            updateSyncButton(false);
            syncStatus.style.display = 'none';
            return;
          }
          if (response?.success === false) {
            alert(response.error || 'Sync failed');
            updateSyncButton(false);
            syncStatus.style.display = 'none';
          }
        });
      } catch (error) {
        console.error('Failed to start sync:', error);
        alert('Failed to start sync: ' + error.message);
        updateSyncButton(false);
        syncStatus.style.display = 'none';
      }
    });
  }

  function updateSyncButton(syncing) {
    isSyncing = syncing;
    if (!syncBtn) return;

    if (syncing) {
      syncBtn.innerHTML = '<div class="spinner"></div> Stop Sync';
      syncBtn.classList.add('syncing', 'abort');
    } else {
      syncBtn.innerHTML = `
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M21 12a9 9 0 11-6.219-8.56"/>
          <polyline points="21 3 21 9 15 9"/>
        </svg>
        Sync All Conversations
      `;
      syncBtn.classList.remove('syncing', 'abort');
    }
  }

  /**
   * Listen for sync progress updates
   */
  chrome.storage.onChanged.addListener((changes, areaName) => {
    if (areaName === 'local' && changes.syncProgress) {
      const progress = changes.syncProgress.newValue;
      if (!progress || progress.status === 'complete') {
        if (progress?.status === 'complete') {
          syncStatus.style.display = 'block';
          syncStatus.className = 'sync-status complete';
          syncStatusText.textContent = `Synced ${progress.synced} conversations`;
          progressBarFill.style.width = '100%';
          updateSyncButton(false);
        } else {
          syncStatus.style.display = 'none';
          updateSyncButton(false);
        }
        return;
      }

      syncStatus.style.display = 'block';
      syncStatus.className = 'sync-status progress';
      updateSyncButton(true);

      const { total, synced, current, status } = progress;
      const percent = total > 0 ? Math.round((synced / total) * 100) : 0;
      progressBarFill.style.width = `${percent}%`;

      if (status === 'starting') {
        syncStatusText.textContent = 'Loading conversation list...';
      } else if (status === 'syncing') {
        syncStatusText.textContent = `Syncing ${synced}/${total}: ${current || '...'}`;
      }
    }
  });

  // Initialize
  await initialize();

  // Refresh every 5 seconds while popup is open
  setInterval(refreshStatus, 5000);
});
