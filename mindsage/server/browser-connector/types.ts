/**
 * Browser Connector Types
 * Types for the persistent Chromium browser profile system
 */

export interface SiteAuthConfig {
  authenticatedAt?: string; // ISO timestamp when user first authenticated
  lastSyncAt?: string; // ISO timestamp of last successful sync
  lastSyncResult?: SyncResult; // Result of last sync
}

// --- Site Registry: Single source of truth for all AI connector sites ---

export interface SiteDefinition {
  name: string;            // Display name (e.g., 'ChatGPT')
  url: string;             // Base URL (e.g., 'https://chatgpt.com')
  cookieDomains: string[]; // Domains for cookie filtering
}

export const SITE_REGISTRY = {
  chatgpt: {
    name: 'ChatGPT',
    url: 'https://chatgpt.com',
    cookieDomains: ['.chatgpt.com', '.openai.com', 'chatgpt.com', 'openai.com'],
  },
  claude: {
    name: 'Claude',
    url: 'https://claude.ai',
    cookieDomains: ['.claude.ai', 'claude.ai', '.anthropic.com', 'anthropic.com'],
  },
  gemini: {
    name: 'Gemini',
    url: 'https://gemini.google.com',
    cookieDomains: ['.google.com', 'google.com', '.gemini.google.com'],
  },
} as const satisfies Record<string, SiteDefinition>;

// Type is automatically 'chatgpt' | 'claude' | 'gemini' — expands when registry grows
export type SupportedSite = keyof typeof SITE_REGISTRY;

// Helper to get all site IDs
export function getSupportedSiteIds(): SupportedSite[] {
  return Object.keys(SITE_REGISTRY) as SupportedSite[];
}

// Derived from registry (replaces standalone constants)
export const SITE_URLS = Object.fromEntries(
  Object.entries(SITE_REGISTRY).map(([k, v]) => [k, v.url])
) as { [K in SupportedSite]: string };

export const ALLOWED_COOKIE_DOMAINS = Object.fromEntries(
  Object.entries(SITE_REGISTRY).map(([k, v]) => [k, [...v.cookieDomains]])
) as { [K in SupportedSite]: string[] };

export interface BrowserConnectorConfig {
  autoStart: boolean;
  defaultUrl: string;
  headed: boolean;
  vncPort?: number;
  memoryLimit?: number; // MB - Chromium renderer limit
  // Legacy single-site auth (for backwards compatibility)
  authenticatedAt?: string;
  // Per-site authentication tracking
  sites?: Partial<Record<SupportedSite, SiteAuthConfig>>;
  autoSyncEnabled?: boolean; // Enable automatic sync
  autoSyncIntervalHours?: number; // Sync interval in hours (default: 5)
  lastSyncAt?: string; // ISO timestamp of last successful sync
  lastSyncResult?: SyncResult; // Result of last sync
  syncStats?: { // Cumulative sync statistics
    totalSynced: number;
    totalFailed: number;
    syncCount: number;
  };
}

export interface BrowserStatus {
  running: boolean;
  pid?: number;
  activeUrl?: string;
  connectedSites: string[];
  launchedAt?: string;
  memoryUsageMB?: number;
  captureStats: {
    totalCaptured: number;
    lastCaptureAt?: string;
    sessionCaptured: number;
  };
  vnc?: {
    enabled: boolean;
    wsPort: number;       // WebSocket port for noVNC
    vncPort: number;      // Raw VNC port
    display: string;      // X display (e.g., ":99")
  };
}

export interface CapturedMessage {
  id: string;
  conversationId: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: string;
  site: SupportedSite;
  metadata?: Record<string, unknown>;
}

export interface CapturedConversation {
  id: string;
  site: SupportedSite;
  title?: string;
  url: string;
  messages: CapturedMessage[];
  createdAt: string;
  updatedAt: string;
  indexed: boolean;
  messageCount: number;
}

export interface CapturePayload {
  site: SupportedSite;
  conversationId: string;
  conversationUrl: string;
  title?: string;
  messages: Array<{
    id?: string;
    role: 'user' | 'assistant' | 'system';
    content: string;
    timestamp?: string;
  }>;
  fullConversation?: boolean; // true = replace all messages, false = append new
}

export interface CaptureState {
  processedConversationIds: Set<string>;
  lastProcessedMessageIds: Map<string, string>; // conversationId -> lastMessageId
  conversations: Map<string, CapturedConversation>;
}

export interface LaunchOptions {
  headed?: boolean;
  headless?: boolean;     // Enable headless mode (no display, for background sync)
  virtualDisplay?: boolean; // Use Xvfb virtual display (extensions work, no VNC needed)
  startUrl?: string;
  vnc?: boolean;          // Enable VNC mode (virtual display + noVNC)
  vncPort?: number;       // Raw VNC port (default: 5901, avoids vino-server conflict)
  wsPort?: number;        // WebSocket port for noVNC (default: 6080)
}

export interface ExtensionMessage {
  type: 'capture' | 'status' | 'ping';
  payload: unknown;
}

// Event types for real-time updates
export interface CaptureEvent {
  type: 'new_message' | 'conversation_updated' | 'indexed';
  conversationId: string;
  site: SupportedSite;
  messageCount?: number;
  timestamp: string;
}

export type CaptureEventListener = (event: CaptureEvent) => void;

// Auth status for tracking first-time login
export interface AuthStatus {
  authenticated: boolean;
  authenticatedAt?: string;
  site?: string;
}

// Sync result for headless sync operations
export interface SyncResult {
  success: boolean;
  synced?: number;
  failed?: number;
  total?: number;
  error?: string;
}

// Cookie import types for Companion Extension auth relay
export interface ImportedCookie {
  name: string;
  value: string;
  domain: string;
  path: string;
  secure: boolean;
  httpOnly: boolean;
  sameSite?: 'Strict' | 'Lax' | 'None' | 'no_restriction' | 'unspecified';
  expirationDate?: number;
}

export interface CookieImportPayload {
  site: SupportedSite;
  cookies: ImportedCookie[];
}

export interface CookieImportResult {
  success: boolean;
  cookiesImported: number;
  site: SupportedSite;
  error?: string;
}

