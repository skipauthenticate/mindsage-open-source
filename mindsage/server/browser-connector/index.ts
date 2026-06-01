/**
 * Browser Connector Module
 * Persistent Chromium browser for capturing AI chat conversations
 */

export { browserConnectorRouter } from './api.js';
export {
  launchBrowser,
  closeBrowser,
  getStatus,
  isRunning,
  navigateTo,
  loadConfig,
  saveConfig,
  autoStartIfConfigured,
  addCaptureListener,
  removeCaptureListener,
  getAuthStatus,
  setAuthenticatedAt,
  clearAuthentication,
  launchHeadlessSync,
  resolveSyncCompletion,
  isInHeadlessMode,
  startAutoSync,
  stopAutoSync,
  isAutoSyncEnabled,
  getAutoSyncStatus,
  setAutoSyncInterval,
  getSessionHealth,
} from './manager.js';
export {
  processCapture,
  getConversations,
  getConversation,
  getCaptureStats,
  reindexAll,
  deleteConversation,
  initializeProcessor,
} from './processor.js';
export * from './types.js';
