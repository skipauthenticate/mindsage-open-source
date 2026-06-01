/**
 * Unified Connector Scheduler for MindSage
 *
 * Manages periodic auto-sync for all connectors (Notion, browser connector, etc.)
 * from a single place. Ensures only one sync runs at a time.
 *
 * For the browser connector, delegates to its existing auto-sync infrastructure
 * rather than reimplementing it.
 */

import * as fs from 'fs';
import * as path from 'path';

interface ConnectorConfig {
  id: string;
  name: string;
  type: string;
  config: Record<string, any>;
  status: string;
  lastSync?: string;
  itemCount: number;
  syncCursor?: { lastSyncAt: string };
  autoSyncEnabled?: boolean;
  autoSyncIntervalHours?: number;
}

interface ScheduledConnector {
  connectorId: string;
  name: string;
  intervalHours: number;
  lastSyncAt: string | null;
  nextSyncAt: string | null;
  enabled: boolean;
}

type SyncFunction = (connectorId: string, config: Record<string, any>) => void;

const MIN_INTERVAL_HOURS = 0.5;
const MAX_INTERVAL_HOURS = 168; // 1 week

export class ConnectorScheduler {
  private timers: Map<string, NodeJS.Timeout> = new Map();
  private overdueTimeouts: Map<string, NodeJS.Timeout> = new Map();
  private dataDir: string;
  private syncFunction: SyncFunction;
  private isSyncRunning: (connectorId: string) => boolean;

  constructor(
    dataDir: string,
    syncFunction: SyncFunction,
    isSyncRunning: (connectorId: string) => boolean
  ) {
    this.dataDir = dataDir;
    this.syncFunction = syncFunction;
    this.isSyncRunning = isSyncRunning;
  }

  /**
   * Initialize scheduler — read all connectors and schedule enabled ones.
   * Call once at server startup.
   */
  initialize(): void {
    const connectors = this.loadConnectors();
    let scheduled = 0;

    for (const connector of connectors) {
      if (connector.autoSyncEnabled && connector.type === 'custom') {
        const script = (connector.config as Record<string, any>)?.script || '';
        // Skip browser-connector (chatgpt-export) — it has its own auto-sync
        if (script === 'chatgpt-export') continue;
        // Skip facebook-import — it's upload-based, not sync-based
        if (script === 'facebook-import') continue;

        this.schedule(connector);
        scheduled++;
      }
    }

    if (scheduled > 0) {
      console.log(`[scheduler] Initialized with ${scheduled} scheduled connector(s)`);
    }
  }

  /**
   * Schedule auto-sync for a connector.
   */
  schedule(connector: ConnectorConfig): void {
    // Clear existing timers (both interval and overdue)
    this.unschedule(connector.id);

    const intervalHours = Math.max(
      MIN_INTERVAL_HOURS,
      Math.min(connector.autoSyncIntervalHours || 6, MAX_INTERVAL_HOURS)
    );
    const intervalMs = intervalHours * 60 * 60 * 1000;

    console.log(`[scheduler] Scheduling "${connector.name}" (${connector.id}) every ${intervalHours}h`);

    const timer = setInterval(() => {
      this.runSync(connector.id);
    }, intervalMs);

    this.timers.set(connector.id, timer);

    // Check if overdue — run after 30s delay if last sync was too long ago
    const lastSync = connector.lastSync ? new Date(connector.lastSync).getTime() : 0;
    const timeSinceLastSync = Date.now() - lastSync;

    if (timeSinceLastSync > intervalMs) {
      console.log(`[scheduler] "${connector.name}" is overdue, scheduling sync in 30s`);
      const overdueTimer = setTimeout(() => {
        this.overdueTimeouts.delete(connector.id);
        this.runSync(connector.id);
      }, 30000);
      this.overdueTimeouts.set(connector.id, overdueTimer);
    }
  }

  /**
   * Unschedule auto-sync for a connector.
   */
  unschedule(connectorId: string): void {
    const timer = this.timers.get(connectorId);
    if (timer) {
      clearInterval(timer);
      this.timers.delete(connectorId);
    }
    const overdueTimer = this.overdueTimeouts.get(connectorId);
    if (overdueTimer) {
      clearTimeout(overdueTimer);
      this.overdueTimeouts.delete(connectorId);
    }
  }

  /**
   * Enable auto-sync for a connector.
   */
  enable(connectorId: string, intervalHours?: number): { success: boolean; error?: string } {
    const connectors = this.loadConnectors();
    const connector = connectors.find(c => c.id === connectorId);

    if (!connector) {
      return { success: false, error: 'Connector not found' };
    }

    if (intervalHours !== undefined) {
      if (intervalHours < MIN_INTERVAL_HOURS || intervalHours > MAX_INTERVAL_HOURS) {
        return { success: false, error: `Interval must be between ${MIN_INTERVAL_HOURS} and ${MAX_INTERVAL_HOURS} hours` };
      }
      connector.autoSyncIntervalHours = intervalHours;
    }

    connector.autoSyncEnabled = true;
    this.saveConnectors(connectors);

    this.schedule(connector);
    return { success: true };
  }

  /**
   * Disable auto-sync for a connector.
   */
  disable(connectorId: string): { success: boolean; error?: string } {
    const connectors = this.loadConnectors();
    const connector = connectors.find(c => c.id === connectorId);

    if (!connector) {
      return { success: false, error: 'Connector not found' };
    }

    connector.autoSyncEnabled = false;
    this.saveConnectors(connectors);

    this.unschedule(connectorId);
    return { success: true };
  }

  /**
   * Get status of all scheduled connectors.
   */
  getStatus(): { connectors: ScheduledConnector[] } {
    const connectors = this.loadConnectors();
    const scheduled: ScheduledConnector[] = [];

    for (const connector of connectors) {
      if (connector.autoSyncEnabled) {
        const intervalHours = connector.autoSyncIntervalHours || 6;
        const lastSyncAt = connector.lastSync || null;

        let nextSyncAt: string | null = null;
        if (lastSyncAt) {
          const next = new Date(lastSyncAt);
          next.setHours(next.getHours() + intervalHours);
          nextSyncAt = next.toISOString();
        }

        scheduled.push({
          connectorId: connector.id,
          name: connector.name,
          intervalHours,
          lastSyncAt,
          nextSyncAt,
          enabled: true,
        });
      }
    }

    return { connectors: scheduled };
  }

  /**
   * Stop all scheduled syncs. Call on server shutdown.
   */
  stopAll(): void {
    for (const [, timer] of this.timers) {
      clearInterval(timer);
    }
    this.timers.clear();
    for (const [, timer] of this.overdueTimeouts) {
      clearTimeout(timer);
    }
    this.overdueTimeouts.clear();
    console.log('[scheduler] All scheduled syncs stopped');
  }

  // --- Private ---

  private runSync(connectorId: string): void {
    if (this.isSyncRunning(connectorId)) {
      console.log(`[scheduler] Skipping "${connectorId}": sync already running`);
      return;
    }

    const connectors = this.loadConnectors();
    const connector = connectors.find(c => c.id === connectorId);

    if (!connector) {
      console.log(`[scheduler] Connector ${connectorId} no longer exists, unscheduling`);
      this.unschedule(connectorId);
      return;
    }

    if (!connector.autoSyncEnabled) {
      console.log(`[scheduler] Connector ${connectorId} auto-sync disabled, unscheduling`);
      this.unschedule(connectorId);
      return;
    }

    console.log(`[scheduler] Running scheduled sync for "${connector.name}"`);
    this.syncFunction(connectorId, connector.config);
  }

  private loadConnectors(): ConnectorConfig[] {
    const configPath = path.join(this.dataDir, 'connectors.json');
    try {
      if (fs.existsSync(configPath)) {
        return JSON.parse(fs.readFileSync(configPath, 'utf-8'));
      }
    } catch (error) {
      console.error('[scheduler] Error reading connectors.json:', error);
    }
    return [];
  }

  private saveConnectors(connectors: ConnectorConfig[]): void {
    const configPath = path.join(this.dataDir, 'connectors.json');
    try {
      fs.writeFileSync(configPath, JSON.stringify(connectors, null, 2));
    } catch (error) {
      console.error('[scheduler] Error writing connectors.json:', error);
    }
  }
}
