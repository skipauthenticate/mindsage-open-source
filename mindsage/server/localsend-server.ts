/**
 * LocalSend Protocol Server - Headless Implementation
 *
 * Implements the LocalSend protocol to receive files from LocalSend apps
 * without requiring a GUI. Works on headless servers like Jetson Orin Nano.
 *
 * Protocol docs: https://github.com/localsend/protocol
 */

import * as dgram from 'dgram';
import * as crypto from 'crypto';
import * as os from 'os';
import * as fs from 'fs';
import * as path from 'path';
import * as http from 'http';
import { spawn, ChildProcess } from 'child_process';
import express, { Express, Request, Response } from 'express';

const MULTICAST_GROUP = '224.0.0.167';
const LOCALSEND_PORT = 53317;
const PROTOCOL_VERSION = '2.0';
const HTTP_PORT = 53317; // LocalSend standard port for HTTP API

interface DeviceInfo {
  alias: string;
  version: string;
  deviceModel: string | null;
  deviceType: 'mobile' | 'desktop' | 'web' | 'headless';
  fingerprint: string;
  port: number;
  protocol: string;
  download: boolean;
  announce: boolean;
}

interface FileInfo {
  id: string;
  fileName: string;
  size: number;
  fileType: string;
  sha256?: string;
  preview?: string;
}

interface PrepareUploadRequest {
  info: {
    alias: string;
    version: string;
    deviceModel: string | null;
    deviceType: string;
    fingerprint: string;
  };
  files: Record<string, FileInfo>;
}

interface Session {
  id: string;
  senderInfo: PrepareUploadRequest['info'];
  files: Record<string, FileInfo>;
  fileTokens: Record<string, string>;
  receivedFiles: Set<string>;
  savedFilenames: string[]; // Track actual filenames saved (for auto-import)
  createdAt: number;
}

// Callback type for auto-import when files are received
export type OnFileReceivedCallback = (filename: string, filePath: string) => void;

export class LocalSendServer {
  private deviceInfo: DeviceInfo;
  private udpSocket: dgram.Socket | null = null;
  private sessions: Map<string, Session> = new Map();
  private uploadsDir: string;
  private announceInterval: NodeJS.Timeout | null = null;
  private isRunning = false;
  private avahiProcess: ChildProcess | null = null;
  private httpServer: http.Server | null = null;
  private localSendApp: Express | null = null;
  private discoveredDevices: Map<string, string> = new Map(); // fingerprint -> IP
  private onFileReceived: OnFileReceivedCallback | null = null;

  constructor(uploadsDir: string, deviceName: string = 'MindSage', onFileReceived?: OnFileReceivedCallback) {
    this.uploadsDir = uploadsDir;
    this.onFileReceived = onFileReceived || null;
    this.deviceInfo = {
      alias: deviceName,
      version: PROTOCOL_VERSION,
      deviceModel: 'Jetson Orin Nano',
      deviceType: 'desktop',
      fingerprint: this.generateFingerprint(),
      port: HTTP_PORT, // HTTP API runs on Express port, not UDP port
      protocol: 'http',
      download: false,
      announce: true,
    };

    // Ensure uploads directory exists
    if (!fs.existsSync(uploadsDir)) {
      fs.mkdirSync(uploadsDir, { recursive: true });
    }
  }

  private generateFingerprint(): string {
    // Generate a consistent fingerprint based on machine ID
    const machineId = os.hostname() + os.platform() + os.arch();
    return crypto.createHash('sha256').update(machineId).digest('hex').substring(0, 32);
  }

  private getLocalIpAddress(): string {
    const interfaces = os.networkInterfaces();
    for (const name of Object.keys(interfaces)) {
      const ifaces = interfaces[name];
      if (ifaces) {
        for (const iface of ifaces) {
          if (iface.family === 'IPv4' && !iface.internal) {
            return iface.address;
          }
        }
      }
    }
    return '127.0.0.1';
  }

  private createAnnouncementMessage(): Buffer {
    const message = {
      ...this.deviceInfo,
      announcement: true,
    };
    return Buffer.from(JSON.stringify(message));
  }

  /**
   * Get all non-internal IPv4 network interfaces
   */
  private getNetworkInterfaces(): { name: string; address: string }[] {
    const interfaces = os.networkInterfaces();
    const result: { name: string; address: string }[] = [];

    for (const [name, ifaces] of Object.entries(interfaces)) {
      if (ifaces) {
        for (const iface of ifaces) {
          if (iface.family === 'IPv4' && !iface.internal) {
            result.push({ name, address: iface.address });
          }
        }
      }
    }
    return result;
  }

  /**
   * Start the UDP multicast announcements
   */
  startDiscovery(): void {
    if (this.udpSocket) {
      return;
    }

    try {
      this.udpSocket = dgram.createSocket({ type: 'udp4', reuseAddr: true });

      this.udpSocket.on('error', (err) => {
        console.error('LocalSend UDP socket error:', err.message);
        this.stopDiscovery();
      });

      this.udpSocket.on('listening', () => {
        const address = this.udpSocket!.address();
        console.log(`LocalSend discovery listening on ${address.address}:${address.port}`);

        // Get all network interfaces, but prefer WiFi
        const networkInterfaces = this.getNetworkInterfaces();
        const preferredIp = this.getPreferredIpAddress();
        console.log(`LocalSend: Found ${networkInterfaces.length} network interfaces, preferred: ${preferredIp}`);

        // Join multicast group on ALL interfaces for receiving
        for (const iface of networkInterfaces) {
          try {
            this.udpSocket!.addMembership(MULTICAST_GROUP, iface.address);
            console.log(`LocalSend: Joined multicast on ${iface.name} (${iface.address})`);
          } catch (err) {
            console.error(`LocalSend: Failed to join multicast on ${iface.name}:`, err);
          }
        }

        // Update deviceInfo with the preferred IP
        (this.deviceInfo as any).address = preferredIp;

        try {
          this.udpSocket!.setMulticastTTL(128);
          this.udpSocket!.setBroadcast(true);
          this.udpSocket!.setMulticastLoopback(true);
        } catch (err) {
          console.error('Failed to set multicast options:', err);
        }

        // Start periodic announcements
        this.announce();
        this.announceInterval = setInterval(() => this.announce(), 2000);
      });

      // Listen for incoming announcements and track devices for unicast replies
      this.udpSocket.on('message', (msg, rinfo) => {
        try {
          const data = JSON.parse(msg.toString());
          if (data.fingerprint && data.fingerprint !== this.deviceInfo.fingerprint) {
            // Track discovered device for unicast announcements
            if (!this.discoveredDevices.has(data.fingerprint)) {
              console.log(`LocalSend: Discovered device "${data.alias}" at ${rinfo.address}`);
            }
            this.discoveredDevices.set(data.fingerprint, rinfo.address);

            // Send immediate unicast reply so they discover us
            this.sendUnicastAnnouncement(rinfo.address);
          }
        } catch {
          // Ignore invalid messages
        }
      });

      this.udpSocket.bind(LOCALSEND_PORT);
      this.isRunning = true;
    } catch (err) {
      console.error('Failed to start LocalSend discovery:', err);
    }

    // Also start mDNS/Bonjour advertisement (works better on some routers)
    this.startMdnsAdvertisement();

    // Start HTTP server on port 53317 for LocalSend API
    this.startHttpServer();
  }

  /**
   * Get the preferred IP address (WiFi over Ethernet)
   */
  private getPreferredIpAddress(): string {
    const interfaces = os.networkInterfaces();
    let wifiIp: string | null = null;
    let ethernetIp: string | null = null;
    let fallbackIp: string | null = null;

    for (const [name, ifaces] of Object.entries(interfaces)) {
      if (ifaces) {
        for (const iface of ifaces) {
          if (iface.family === 'IPv4' && !iface.internal) {
            // Prefer WiFi interfaces (common naming patterns)
            if (name.startsWith('wl') || name.includes('wifi') || name.includes('wlan')) {
              wifiIp = iface.address;
            } else if (name.startsWith('en') || name.startsWith('eth') || name === 'eno1') {
              ethernetIp = iface.address;
            } else if (!name.startsWith('docker') && !name.startsWith('br-') && !name.startsWith('veth')) {
              fallbackIp = iface.address;
            }
          }
        }
      }
    }

    // Prefer WiFi > Ethernet > Fallback
    return wifiIp || ethernetIp || fallbackIp || '127.0.0.1';
  }

  /**
   * Start mDNS advertisement using system avahi-publish
   * This works with the system's avahi-daemon instead of conflicting with it
   */
  private startMdnsAdvertisement(): void {
    try {
      const preferredIp = this.getPreferredIpAddress();
      console.log(`LocalSend: Using preferred IP ${preferredIp} for mDNS`);

      // Build TXT record strings for avahi-publish
      const txtRecords = [
        `alias=${this.deviceInfo.alias}`,
        `version=${this.deviceInfo.version}`,
        `deviceModel=${this.deviceInfo.deviceModel || ''}`,
        `deviceType=${this.deviceInfo.deviceType}`,
        `fingerprint=${this.deviceInfo.fingerprint}`,
        `download=false`,
        `protocol=http`,
      ];

      // Use avahi-publish-service to advertise via system avahi-daemon
      const args = [
        '-s',                           // Publish a service
        this.deviceInfo.alias,          // Service name
        '_localsend._tcp',              // Service type
        String(HTTP_PORT),              // Port
        ...txtRecords,                  // TXT records
      ];

      this.avahiProcess = spawn('avahi-publish', args, {
        stdio: ['ignore', 'pipe', 'pipe'],
      });

      this.avahiProcess.on('error', (err) => {
        console.error('LocalSend: Failed to start avahi-publish:', err.message);
        this.avahiProcess = null;
      });

      this.avahiProcess.stderr?.on('data', (data) => {
        const msg = data.toString().trim();
        if (msg && !msg.includes('Established')) {
          console.error('LocalSend avahi-publish:', msg);
        }
      });

      this.avahiProcess.on('exit', (code) => {
        if (code !== null && code !== 0) {
          console.error(`LocalSend: avahi-publish exited with code ${code}`);
        }
        this.avahiProcess = null;
      });

      console.log(`LocalSend: mDNS service advertised as "${this.deviceInfo.alias}" via avahi on port ${HTTP_PORT}`);
    } catch (err) {
      console.error('Failed to start mDNS advertisement:', err);
    }
  }

  /**
   * Stop mDNS advertisement
   */
  private stopMdnsAdvertisement(): void {
    if (this.avahiProcess) {
      try {
        this.avahiProcess.kill('SIGTERM');
      } catch {
        // Ignore
      }
      this.avahiProcess = null;
    }
  }

  /**
   * Start a standalone HTTP server on the LocalSend port (53317)
   * This is separate from the main Express app and handles LocalSend protocol
   */
  private startHttpServer(): void {
    if (this.httpServer) {
      return;
    }

    // Create a separate Express app for LocalSend
    this.localSendApp = express();
    this.localSendApp.use(express.json());

    // Add CORS headers for all responses
    this.localSendApp.use((_req, res, next) => {
      res.header('Access-Control-Allow-Origin', '*');
      res.header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
      res.header('Access-Control-Allow-Headers', 'Content-Type');
      next();
    });

    // Register LocalSend routes on this app
    this.registerLocalSendRoutes(this.localSendApp);

    this.httpServer = http.createServer(this.localSendApp);

    const preferredIp = this.getPreferredIpAddress();

    this.httpServer.listen(HTTP_PORT, '0.0.0.0', () => {
      console.log(`LocalSend HTTP server listening on port ${HTTP_PORT}`);
      console.log(`LocalSend: Accessible at http://${preferredIp}:${HTTP_PORT}`);
    });

    this.httpServer.on('error', (err: NodeJS.ErrnoException) => {
      if (err.code === 'EADDRINUSE') {
        console.error(`LocalSend: Port ${HTTP_PORT} is already in use`);
      } else {
        console.error('LocalSend HTTP server error:', err);
      }
    });
  }

  /**
   * Stop the HTTP server
   */
  private stopHttpServer(): void {
    if (this.httpServer) {
      this.httpServer.close();
      this.httpServer = null;
      this.localSendApp = null;
      console.log('LocalSend HTTP server stopped');
    }
  }

  /**
   * Register LocalSend protocol routes on an Express app
   */
  private registerLocalSendRoutes(app: Express): void {
    // Log ALL incoming requests for debugging
    app.use((req: Request, _res: Response, next) => {
      console.log(`LocalSend [53317]: ${req.method} ${req.path} from ${req.ip}`);
      next();
    });

    // Handle OPTIONS for CORS preflight
    app.options('*', (_req: Request, res: Response) => {
      res.setHeader('Content-Type', 'application/json');
      res.status(200).json({});
    });

    // Root path - return device info (some clients hit this first)
    app.get('/', (_req: Request, res: Response) => {
      res.setHeader('Content-Type', 'application/json');
      res.json(this.deviceInfo);
    });

    // Device info / registration - this is the first endpoint the iOS app calls
    app.post('/api/localsend/v2/register', (req: Request, res: Response) => {
      console.log('LocalSend [53317]: Register request from', req.ip);
      res.setHeader('Content-Type', 'application/json');
      res.json(this.deviceInfo);
    });

    // Also respond to GET for info
    app.get('/api/localsend/v2/info', (_req: Request, res: Response) => {
      console.log('LocalSend [53317]: Info request');
      res.setHeader('Content-Type', 'application/json');
      res.json(this.deviceInfo);
    });

    // Prepare upload - sender tells us what files they want to send
    app.post('/api/localsend/v2/prepare-upload', (req: Request, res: Response) => {
      try {
        const body: PrepareUploadRequest = req.body;
        console.log(`LocalSend [53317]: Prepare upload from "${body.info?.alias}" with ${Object.keys(body.files || {}).length} files`);

        const sessionId = crypto.randomUUID();
        const fileTokens: Record<string, string> = {};

        // Generate tokens for each file
        for (const fileId of Object.keys(body.files || {})) {
          fileTokens[fileId] = crypto.randomUUID();
        }

        // Store session
        const session: Session = {
          id: sessionId,
          senderInfo: body.info,
          files: body.files || {},
          fileTokens,
          receivedFiles: new Set(),
          savedFilenames: [],
          createdAt: Date.now(),
        };
        this.sessions.set(sessionId, session);

        // Clean up old sessions (older than 1 hour)
        const oneHourAgo = Date.now() - 60 * 60 * 1000;
        for (const [id, sess] of this.sessions) {
          if (sess.createdAt < oneHourAgo) {
            this.sessions.delete(id);
          }
        }

        res.json({
          sessionId,
          files: fileTokens,
        });
      } catch (error) {
        console.error('LocalSend [53317] prepare-upload error:', error);
        res.status(400).json({ error: 'Invalid request' });
      }
    });

    // Upload file - handle raw body
    app.post('/api/localsend/v2/upload', express.raw({ type: '*/*', limit: '10gb' }), (req: Request, res: Response) => {
      try {
        const sessionId = req.query.sessionId as string;
        const fileId = req.query.fileId as string;
        const token = req.query.token as string;

        console.log(`LocalSend [53317]: Upload request - sessionId=${sessionId}, fileId=${fileId}, bodyLength=${req.body?.length || 0}`);

        const session = this.sessions.get(sessionId);
        if (!session) {
          console.log('LocalSend [53317]: Session not found');
          return res.status(404).json({ error: 'Session not found' });
        }

        if (session.fileTokens[fileId] !== token) {
          console.log('LocalSend [53317]: Invalid token');
          return res.status(403).json({ error: 'Invalid token' });
        }

        const fileInfo = session.files[fileId];
        if (!fileInfo) {
          console.log('LocalSend [53317]: File info not found');
          return res.status(404).json({ error: 'File not found in session' });
        }

        // Get the raw body buffer
        const bodyBuffer = req.body as Buffer;
        if (!bodyBuffer || bodyBuffer.length === 0) {
          console.log('LocalSend [53317]: No file data received');
          return res.status(400).json({ error: 'No file data received' });
        }

        // Determine filename
        let filename = fileInfo.fileName;
        const filePath = path.join(this.uploadsDir, filename);
        if (fs.existsSync(filePath)) {
          const ext = path.extname(filename);
          const base = path.basename(filename, ext);
          filename = `${base}-${Date.now()}${ext}`;
        }

        const fullPath = path.join(this.uploadsDir, filename);

        // Write the file
        fs.writeFileSync(fullPath, bodyBuffer);

        session.receivedFiles.add(fileId);
        session.savedFilenames.push(filename);
        console.log(`LocalSend [53317]: Received file "${filename}" (${bodyBuffer.length} bytes)`);
        res.json({ success: true });
      } catch (error) {
        console.error('LocalSend [53317] upload error:', error);
        res.status(500).json({ error: 'Upload failed' });
      }
    });

    // Cancel session
    app.post('/api/localsend/v2/cancel', (req: Request, res: Response) => {
      const sessionId = req.query.sessionId as string;
      if (sessionId) {
        this.sessions.delete(sessionId);
      }
      res.json({ success: true });
    });

    // Finish session
    app.post('/api/localsend/v2/finish', (req: Request, res: Response) => {
      const sessionId = req.query.sessionId as string;
      const session = this.sessions.get(sessionId);

      if (session) {
        console.log(`LocalSend [53317]: Transfer complete from "${session.senderInfo?.alias}"`);

        // Auto-import received files
        if (this.onFileReceived && session.savedFilenames.length > 0) {
          console.log(`LocalSend [53317]: Auto-importing ${session.savedFilenames.length} file(s)...`);
          for (const filename of session.savedFilenames) {
            const filePath = path.join(this.uploadsDir, filename);
            try {
              this.onFileReceived(filename, filePath);
            } catch (err) {
              console.error(`LocalSend [53317]: Auto-import failed for "${filename}":`, err);
            }
          }
        }

        this.sessions.delete(sessionId);
      }

      res.json({ success: true });
    });

    // Catch-all: return JSON 404 instead of HTML (fixes "invalid content type" errors)
    app.use((_req: Request, res: Response) => {
      res.setHeader('Content-Type', 'application/json');
      res.status(404).json({ error: 'Not found' });
    });

    console.log('LocalSend protocol routes registered on port 53317');
  }

  /**
   * Send a multicast announcement on all interfaces
   */
  private announce(): void {
    if (!this.udpSocket) return;

    const message = this.createAnnouncementMessage();
    const interfaces = this.getNetworkInterfaces();

    // Send on ALL interfaces to maximize discovery chances
    for (const iface of interfaces) {
      // Skip docker interfaces
      if (iface.name.startsWith('docker') || iface.name.startsWith('br-') || iface.name.startsWith('veth')) {
        continue;
      }

      try {
        this.udpSocket.setMulticastInterface(iface.address);
        this.udpSocket.send(message, 0, message.length, LOCALSEND_PORT, MULTICAST_GROUP, (err) => {
          if (err) {
            console.error(`LocalSend announcement error on ${iface.name}:`, err.message);
          }
        });
      } catch (err) {
        // Ignore interface errors
      }
    }

    // Also send unicast to all discovered devices (bypasses multicast routing issues)
    for (const [_, ip] of this.discoveredDevices) {
      this.sendUnicastAnnouncement(ip);
    }
  }

  /**
   * Send a unicast announcement directly to a specific IP
   * This bypasses multicast routing issues on some networks
   */
  private sendUnicastAnnouncement(targetIp: string): void {
    if (!this.udpSocket) return;

    const message = this.createAnnouncementMessage();
    this.udpSocket.send(message, 0, message.length, LOCALSEND_PORT, targetIp, (err) => {
      if (err) {
        // Remove device if we can't reach it
        for (const [fp, ip] of this.discoveredDevices) {
          if (ip === targetIp) {
            this.discoveredDevices.delete(fp);
            break;
          }
        }
      }
    });
  }

  /**
   * Stop the UDP multicast announcements and mDNS
   */
  stopDiscovery(): void {
    if (this.announceInterval) {
      clearInterval(this.announceInterval);
      this.announceInterval = null;
    }

    if (this.udpSocket) {
      // Leave multicast on all interfaces
      const interfaces = this.getNetworkInterfaces();
      for (const iface of interfaces) {
        try {
          this.udpSocket.dropMembership(MULTICAST_GROUP, iface.address);
        } catch {
          // Ignore
        }
      }
      this.udpSocket.close();
      this.udpSocket = null;
    }

    // Stop mDNS advertisement
    this.stopMdnsAdvertisement();

    // Stop HTTP server
    this.stopHttpServer();

    this.isRunning = false;
    console.log('LocalSend discovery stopped');
  }

  /**
   * Get server status
   */
  getStatus(): { running: boolean; deviceInfo: DeviceInfo; ipAddress: string } {
    return {
      running: this.isRunning,
      deviceInfo: this.deviceInfo,
      ipAddress: this.getLocalIpAddress(),
    };
  }

  /**
   * Register LocalSend API routes with Express app (for port 3000)
   * Note: The main LocalSend API is served on port 53317, but we also
   * register routes on port 3000 for backward compatibility
   */
  registerRoutes(app: Express): void {
    // Add logging prefix for port 3000 routes
    app.post('/api/localsend/v2/register', (req: Request, res: Response) => {
      console.log('LocalSend [3000]: Register request from', req.ip);
      res.setHeader('Content-Type', 'application/json');
      res.json(this.deviceInfo);
    });

    app.get('/api/localsend/v2/info', (_req: Request, res: Response) => {
      console.log('LocalSend [3000]: Info request');
      res.setHeader('Content-Type', 'application/json');
      res.json(this.deviceInfo);
    });

    app.post('/api/localsend/v2/prepare-upload', (req: Request, res: Response) => {
      try {
        const body: PrepareUploadRequest = req.body;
        console.log(`LocalSend [3000]: Prepare upload from "${body.info?.alias}" with ${Object.keys(body.files || {}).length} files`);

        const sessionId = crypto.randomUUID();
        const fileTokens: Record<string, string> = {};

        for (const fileId of Object.keys(body.files || {})) {
          fileTokens[fileId] = crypto.randomUUID();
        }

        const session: Session = {
          id: sessionId,
          senderInfo: body.info,
          files: body.files || {},
          fileTokens,
          receivedFiles: new Set(),
          savedFilenames: [],
          createdAt: Date.now(),
        };
        this.sessions.set(sessionId, session);

        const oneHourAgo = Date.now() - 60 * 60 * 1000;
        for (const [id, sess] of this.sessions) {
          if (sess.createdAt < oneHourAgo) {
            this.sessions.delete(id);
          }
        }

        res.json({ sessionId, files: fileTokens });
      } catch (error) {
        console.error('LocalSend [3000] prepare-upload error:', error);
        res.status(400).json({ error: 'Invalid request' });
      }
    });

    app.post('/api/localsend/v2/upload', express.raw({ type: '*/*', limit: '10gb' }), (req: Request, res: Response) => {
      try {
        const sessionId = req.query.sessionId as string;
        const fileId = req.query.fileId as string;
        const token = req.query.token as string;

        console.log(`LocalSend [3000]: Upload request - sessionId=${sessionId}, fileId=${fileId}`);

        const session = this.sessions.get(sessionId);
        if (!session) return res.status(404).json({ error: 'Session not found' });
        if (session.fileTokens[fileId] !== token) return res.status(403).json({ error: 'Invalid token' });

        const fileInfo = session.files[fileId];
        if (!fileInfo) return res.status(404).json({ error: 'File not found in session' });

        const bodyBuffer = req.body as Buffer;
        if (!bodyBuffer || bodyBuffer.length === 0) {
          return res.status(400).json({ error: 'No file data received' });
        }

        let filename = fileInfo.fileName;
        const filePath = path.join(this.uploadsDir, filename);
        if (fs.existsSync(filePath)) {
          const ext = path.extname(filename);
          const base = path.basename(filename, ext);
          filename = `${base}-${Date.now()}${ext}`;
        }

        fs.writeFileSync(path.join(this.uploadsDir, filename), bodyBuffer);
        session.receivedFiles.add(fileId);
        session.savedFilenames.push(filename);
        console.log(`LocalSend [3000]: Received file "${filename}" (${bodyBuffer.length} bytes)`);
        res.json({ success: true });
      } catch (error) {
        console.error('LocalSend [3000] upload error:', error);
        res.status(500).json({ error: 'Upload failed' });
      }
    });

    app.post('/api/localsend/v2/cancel', (req: Request, res: Response) => {
      const sessionId = req.query.sessionId as string;
      if (sessionId) this.sessions.delete(sessionId);
      res.json({ success: true });
    });

    app.post('/api/localsend/v2/finish', (req: Request, res: Response) => {
      const sessionId = req.query.sessionId as string;
      const session = this.sessions.get(sessionId);
      if (session) {
        console.log(`LocalSend [3000]: Transfer complete from "${session.senderInfo?.alias}"`);

        // Auto-import received files
        if (this.onFileReceived && session.savedFilenames.length > 0) {
          console.log(`LocalSend [3000]: Auto-importing ${session.savedFilenames.length} file(s)...`);
          for (const filename of session.savedFilenames) {
            const filePath = path.join(this.uploadsDir, filename);
            try {
              this.onFileReceived(filename, filePath);
            } catch (err) {
              console.error(`LocalSend [3000]: Auto-import failed for "${filename}":`, err);
            }
          }
        }

        this.sessions.delete(sessionId);
      }
      res.json({ success: true });
    });

    console.log('LocalSend API routes registered on port 3000');
  }
}

// Singleton instance
let localSendServer: LocalSendServer | null = null;

export function getLocalSendServer(uploadsDir: string, deviceName?: string, onFileReceived?: OnFileReceivedCallback): LocalSendServer {
  if (!localSendServer) {
    localSendServer = new LocalSendServer(uploadsDir, deviceName, onFileReceived);
  }
  return localSendServer;
}
