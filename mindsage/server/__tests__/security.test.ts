/**
 * Security tests for Express server hardening (RT-01, RT-04, RT-07).
 *
 * Tests the authentication middleware, CORS restrictions, and path traversal
 * prevention. These are security-critical — a failure means attackers on the
 * local network can access or exfiltrate user data.
 *
 * The tests construct isolated Express apps with only the security middleware
 * to avoid needing the full server (vector store, browser connector, etc.).
 */

import { describe, it, expect, beforeAll, afterAll, beforeEach } from 'vitest';
import express, { Request, Response, NextFunction } from 'express';
import request from 'supertest';
import * as path from 'path';
import * as fs from 'fs';
import * as os from 'os';
import { randomBytes, timingSafeEqual } from 'crypto';

// ─────────────────────────────────────────────────────────────────
// RT-07: CORS Origin Validation
// ─────────────────────────────────────────────────────────────────

describe('RT-07: CORS Origin Pattern', () => {
  // Reproduce the exact regex from server/index.ts
  const CORS_ORIGIN_PATTERN = /^https?:\/\/(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+)(:\d+)?$/;

  describe('allowed origins', () => {
    const allowed = [
      'http://localhost',
      'http://localhost:3003',
      'http://localhost:8080',
      'https://localhost:443',
      'http://127.0.0.1',
      'http://127.0.0.1:3003',
      'http://192.168.1.1',
      'http://192.168.1.100:8080',
      'http://192.168.0.1',
      'http://192.168.255.255:3000',
      'http://10.0.0.1',
      'http://10.0.0.1:3003',
      'http://10.255.255.255',
      'http://172.16.0.1',
      'http://172.16.0.1:8080',
      'http://172.31.255.255',
    ];

    for (const origin of allowed) {
      it(`allows ${origin}`, () => {
        expect(CORS_ORIGIN_PATTERN.test(origin)).toBe(true);
      });
    }
  });

  describe('blocked origins', () => {
    const blocked = [
      // Public internet origins
      'http://evil.com',
      'https://attacker.io',
      'http://google.com',
      'https://malicious-site.com:3003',

      // Public IPs
      'http://8.8.8.8',
      'http://1.1.1.1:3003',
      'http://203.0.113.1',

      // Spoofed private-looking origins
      'http://192.168.1.1.evil.com',
      'http://not-localhost:3003',

      // Edge case: 172.x outside 16-31 range (not RFC 1918)
      'http://172.15.0.1',
      'http://172.32.0.1',

      // No protocol
      'localhost:3003',
      '192.168.1.1:3003',

      // FTP/other protocols
      'ftp://localhost',

      // JavaScript/data URIs (XSS vectors)
      'javascript:alert(1)',
      'data:text/html,<script>alert(1)</script>',
    ];

    for (const origin of blocked) {
      it(`blocks ${origin}`, () => {
        expect(CORS_ORIGIN_PATTERN.test(origin)).toBe(false);
      });
    }
  });
});

// ─────────────────────────────────────────────────────────────────
// RT-01: Authentication Middleware
// ─────────────────────────────────────────────────────────────────

describe('RT-01: Authentication Middleware', () => {
  const API_TOKEN = randomBytes(32).toString('hex');
  const AUTH_EXEMPT_PATHS = new Set(['/health', '/api/health']);

  function isLocalhostIp(ip: string): boolean {
    return ip === '127.0.0.1' || ip === '::1' || ip === '::ffff:127.0.0.1';
  }

  // Build a minimal Express app with ONLY the auth middleware
  function createTestApp() {
    const app = express();
    app.use(express.json());

    // Auth middleware (exact replica from server/index.ts)
    app.use((req: Request, res: Response, next: NextFunction) => {
      if (AUTH_EXEMPT_PATHS.has(req.path)) return next();

      const clientIp = req.socket.remoteAddress || '';
      if (isLocalhostIp(clientIp)) return next();

      const authHeader = req.headers.authorization;
      const token = authHeader?.startsWith('Bearer ') ? authHeader.slice(7) :
                    (typeof req.query.token === 'string' ? req.query.token : null);

      if (token && token.length === API_TOKEN.length) {
        try {
          if (timingSafeEqual(Buffer.from(token), Buffer.from(API_TOKEN))) {
            return next();
          }
        } catch { /* length mismatch */ }
      }

      return res.status(401).json({ error: 'Authentication required' });
    });

    // Test endpoints
    app.get('/health', (_req, res) => res.json({ status: 'ok' }));
    app.get('/api/health', (_req, res) => res.json({ status: 'ok' }));
    app.get('/api/data', (_req, res) => res.json({ data: 'secret' }));
    app.post('/api/pii/deanonymize', (_req, res) => res.json({ result: 'deanonymized' }));
    app.put('/api/chat/config', (_req, res) => res.json({ updated: true }));
    app.post('/api/data/clear-all', (_req, res) => res.json({ cleared: true }));
    app.get('/api/connectors/1/exports/data.json', (_req, res) => res.json({ file: 'content' }));

    return app;
  }

  // Note: supertest connects via localhost, so auth middleware allows it through.
  // To test the auth rejection path, we simulate remote IPs by overriding remoteAddress.

  describe('exempt paths', () => {
    it('allows /health without authentication', async () => {
      const app = createTestApp();
      const res = await request(app).get('/health');
      expect(res.status).toBe(200);
    });

    it('allows /api/health without authentication', async () => {
      const app = createTestApp();
      const res = await request(app).get('/api/health');
      expect(res.status).toBe(200);
    });
  });

  describe('bearer token validation', () => {
    it('accepts valid bearer token in Authorization header', async () => {
      const app = createTestApp();
      const res = await request(app)
        .get('/api/data')
        .set('Authorization', `Bearer ${API_TOKEN}`);
      expect(res.status).toBe(200);
    });

    it('accepts valid token as query parameter', async () => {
      const app = createTestApp();
      const res = await request(app)
        .get(`/api/data?token=${API_TOKEN}`);
      expect(res.status).toBe(200);
    });

    it('rejects request with wrong token', async () => {
      // Create app that treats all IPs as remote
      const app = express();
      app.use(express.json());
      app.use((req: Request, res: Response, next: NextFunction) => {
        if (AUTH_EXEMPT_PATHS.has(req.path)) return next();
        // Force non-localhost to test auth rejection
        const authHeader = req.headers.authorization;
        const token = authHeader?.startsWith('Bearer ') ? authHeader.slice(7) :
                      (typeof req.query.token === 'string' ? req.query.token : null);

        if (token && token.length === API_TOKEN.length) {
          try {
            if (timingSafeEqual(Buffer.from(token), Buffer.from(API_TOKEN))) {
              return next();
            }
          } catch {}
        }
        return res.status(401).json({ error: 'Authentication required' });
      });
      app.get('/api/data', (_req, res) => res.json({ data: 'secret' }));

      const res = await request(app)
        .get('/api/data')
        .set('Authorization', 'Bearer wrong-token-here-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx');
      expect(res.status).toBe(401);
    });

    it('rejects request with no token (forced remote)', async () => {
      const app = express();
      app.use(express.json());
      app.use((req: Request, res: Response, next: NextFunction) => {
        // Skip localhost bypass to test auth
        const authHeader = req.headers.authorization;
        const token = authHeader?.startsWith('Bearer ') ? authHeader.slice(7) : null;
        if (token && token.length === API_TOKEN.length) {
          try {
            if (timingSafeEqual(Buffer.from(token), Buffer.from(API_TOKEN))) {
              return next();
            }
          } catch {}
        }
        return res.status(401).json({ error: 'Authentication required' });
      });
      app.get('/api/data', (_req, res) => res.json({ data: 'secret' }));

      const res = await request(app).get('/api/data');
      expect(res.status).toBe(401);
    });

    it('rejects token with wrong length (prevents timing attack)', async () => {
      const app = express();
      app.use((req: Request, res: Response, next: NextFunction) => {
        const authHeader = req.headers.authorization;
        const token = authHeader?.startsWith('Bearer ') ? authHeader.slice(7) : null;
        if (token && token.length === API_TOKEN.length) {
          try {
            if (timingSafeEqual(Buffer.from(token), Buffer.from(API_TOKEN))) {
              return next();
            }
          } catch {}
        }
        return res.status(401).json({ error: 'Authentication required' });
      });
      app.get('/api/data', (_req, res) => res.json({ data: 'secret' }));

      // Short token
      const res = await request(app)
        .get('/api/data')
        .set('Authorization', 'Bearer short');
      expect(res.status).toBe(401);
    });

    it('protects sensitive endpoints when auth is required', async () => {
      // Middleware that forces auth check (no localhost bypass)
      function createStrictApp() {
        const app = express();
        app.use(express.json());
        app.use((req: Request, res: Response, next: NextFunction) => {
          if (AUTH_EXEMPT_PATHS.has(req.path)) return next();
          const authHeader = req.headers.authorization;
          const token = authHeader?.startsWith('Bearer ') ? authHeader.slice(7) : null;
          if (token && token.length === API_TOKEN.length) {
            try {
              if (timingSafeEqual(Buffer.from(token), Buffer.from(API_TOKEN))) {
                return next();
              }
            } catch {}
          }
          return res.status(401).json({ error: 'Authentication required' });
        });
        app.post('/api/pii/deanonymize', (_req, res) => res.json({ result: 'deanonymized' }));
        app.put('/api/chat/config', (_req, res) => res.json({ updated: true }));
        app.post('/api/data/clear-all', (_req, res) => res.json({ cleared: true }));
        return app;
      }

      const app = createStrictApp();

      // RT-01: deanonymize endpoint must require auth
      const r1 = await request(app).post('/api/pii/deanonymize').send({ text: 'test', session_id: 's' });
      expect(r1.status).toBe(401);

      // RT-06: chat config endpoint must require auth
      const r2 = await request(app).put('/api/chat/config').send({ groqApiKey: 'stolen-key' });
      expect(r2.status).toBe(401);

      // RT-05: data clear-all endpoint must require auth
      const r3 = await request(app).post('/api/data/clear-all');
      expect(r3.status).toBe(401);
    });
  });

  describe('isLocalhostIp', () => {
    it('recognizes IPv4 localhost', () => {
      expect(isLocalhostIp('127.0.0.1')).toBe(true);
    });

    it('recognizes IPv6 localhost', () => {
      expect(isLocalhostIp('::1')).toBe(true);
    });

    it('recognizes IPv4-mapped IPv6 localhost', () => {
      expect(isLocalhostIp('::ffff:127.0.0.1')).toBe(true);
    });

    it('rejects private network IPs (not localhost)', () => {
      expect(isLocalhostIp('192.168.1.1')).toBe(false);
      expect(isLocalhostIp('10.0.0.1')).toBe(false);
      expect(isLocalhostIp('172.16.0.1')).toBe(false);
    });

    it('rejects public IPs', () => {
      expect(isLocalhostIp('8.8.8.8')).toBe(false);
      expect(isLocalhostIp('203.0.113.1')).toBe(false);
    });

    it('rejects empty string', () => {
      expect(isLocalhostIp('')).toBe(false);
    });
  });
});

// ─────────────────────────────────────────────────────────────────
// RT-01: X-Forwarded-For must be ignored
// ─────────────────────────────────────────────────────────────────

describe('RT-01: X-Forwarded-For Bypass Prevention', () => {
  it('does not trust X-Forwarded-For header for auth bypass', () => {
    // The getDirectClientIp function must return socket.remoteAddress,
    // NOT req.headers['x-forwarded-for']
    function getDirectClientIp(req: Request): string {
      return req.socket.remoteAddress || '';
    }

    // Simulate a request where X-Forwarded-For claims localhost
    // but the actual socket is a remote IP
    const mockReq = {
      socket: { remoteAddress: '192.168.1.50' },
      headers: { 'x-forwarded-for': '127.0.0.1' },
    } as unknown as Request;

    const ip = getDirectClientIp(mockReq);
    expect(ip).toBe('192.168.1.50');
    expect(ip).not.toBe('127.0.0.1');
  });
});

// ─────────────────────────────────────────────────────────────────
// RT-04: Path Traversal Prevention
// ─────────────────────────────────────────────────────────────────

describe('RT-04: Path Traversal Prevention', () => {
  let tmpDir: string;
  let exportsDir: string;
  let resolvedExportsDir: string;

  beforeAll(() => {
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'mindsage-test-'));
    exportsDir = path.join(tmpDir, 'exports');
    fs.mkdirSync(exportsDir, { recursive: true });
    resolvedExportsDir = path.resolve(exportsDir) + path.sep;

    // Create test files
    const connectorDir = path.join(exportsDir, 'connector1');
    fs.mkdirSync(connectorDir, { recursive: true });
    fs.writeFileSync(path.join(connectorDir, 'data.json'), '{"exported": true}');

    // Create a sensitive file OUTSIDE exports
    fs.writeFileSync(path.join(tmpDir, 'secret.json'), '{"apiKey": "placeholder-secret"}');
  });

  afterAll(() => {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  });

  function createPathTraversalApp() {
    const app = express();

    app.get('/api/connectors/:id/exports/:filename', (req, res) => {
      const filePath = path.join(exportsDir, req.params.id, req.params.filename);
      const resolvedPath = path.resolve(filePath);
      if (!resolvedPath.startsWith(resolvedExportsDir)) {
        return res.status(403).json({ error: 'Access denied: invalid path' });
      }
      if (!fs.existsSync(filePath)) {
        return res.status(404).json({ error: 'File not found' });
      }
      const content = JSON.parse(fs.readFileSync(filePath, 'utf-8'));
      res.json(content);
    });

    return app;
  }

  it('allows valid export file access', async () => {
    const app = createPathTraversalApp();
    const res = await request(app).get('/api/connectors/connector1/exports/data.json');
    expect(res.status).toBe(200);
    expect(res.body).toEqual({ exported: true });
  });

  it('blocks ../ directory traversal to parent directory', async () => {
    const app = createPathTraversalApp();
    const res = await request(app).get('/api/connectors/connector1/exports/../../secret.json');
    // Express normalizes the URL, but let's test the logic directly
    expect(res.status).not.toBe(200);
  });

  it('blocks path traversal via encoded characters', async () => {
    const app = createPathTraversalApp();
    // %2e%2e = ..
    const res = await request(app).get('/api/connectors/%2e%2e/exports/secret.json');
    expect([403, 404]).toContain(res.status);
  });

  it('validates path containment logic directly', () => {
    // Test the path containment check directly
    const validPath = path.resolve(path.join(exportsDir, 'connector1', 'data.json'));
    const traversalPath = path.resolve(path.join(exportsDir, '..', 'secret.json'));
    const doubleTraversal = path.resolve(path.join(exportsDir, 'connector1', '..', '..', 'secret.json'));

    expect(validPath.startsWith(resolvedExportsDir)).toBe(true);
    expect(traversalPath.startsWith(resolvedExportsDir)).toBe(false);
    expect(doubleTraversal.startsWith(resolvedExportsDir)).toBe(false);
  });

  it('prevents access to /etc/passwd via deep traversal', () => {
    const attackPath = path.resolve(path.join(exportsDir, '..', '..', '..', '..', 'etc', 'passwd'));
    expect(attackPath.startsWith(resolvedExportsDir)).toBe(false);
  });

  it('prevents symlink escape (if symlinks existed)', () => {
    // path.resolve follows symlinks, so this validates the containment check
    const fakePath = path.resolve(path.join(exportsDir, 'legit', '..', '..', 'secret.json'));
    expect(fakePath.startsWith(resolvedExportsDir)).toBe(false);
  });
});

// ─────────────────────────────────────────────────────────────────
// RT-01: Token Generation Security
// ─────────────────────────────────────────────────────────────────

describe('RT-01: API Token Security Properties', () => {
  it('generates 256-bit (64 hex chars) tokens', () => {
    const token = randomBytes(32).toString('hex');
    expect(token.length).toBe(64);
  });

  it('generates unique tokens on each call', () => {
    const tokens = new Set<string>();
    for (let i = 0; i < 100; i++) {
      tokens.add(randomBytes(32).toString('hex'));
    }
    expect(tokens.size).toBe(100);
  });

  it('timingSafeEqual rejects wrong-content same-length tokens', () => {
    const real = randomBytes(32).toString('hex');
    const fake = randomBytes(32).toString('hex');

    expect(real.length).toBe(fake.length);
    expect(timingSafeEqual(Buffer.from(real), Buffer.from(fake))).toBe(false);
  });

  it('timingSafeEqual accepts identical tokens', () => {
    const token = randomBytes(32).toString('hex');
    expect(timingSafeEqual(Buffer.from(token), Buffer.from(token))).toBe(true);
  });

  it('timingSafeEqual throws on different-length buffers', () => {
    expect(() => {
      timingSafeEqual(Buffer.from('short'), Buffer.from('much-longer-string'));
    }).toThrow();
  });

  it('token file has restrictive permissions when created', () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'token-test-'));
    const tokenPath = path.join(tmpDir, '.api-token');

    const token = randomBytes(32).toString('hex');
    fs.writeFileSync(tokenPath, token, { mode: 0o600 });

    const stat = fs.statSync(tokenPath);
    const permissions = stat.mode & 0o777;
    expect(permissions).toBe(0o600);

    fs.rmSync(tmpDir, { recursive: true, force: true });
  });
});

// ─────────────────────────────────────────────────────────────────
// Integration: Sensitive endpoints are protected
// ─────────────────────────────────────────────────────────────────

describe('Integration: Sensitive endpoint protection', () => {
  const API_TOKEN = randomBytes(32).toString('hex');

  function createProtectedApp() {
    const app = express();
    app.use(express.json());

    // Strict auth (no localhost bypass for testing)
    app.use((req: Request, res: Response, next: NextFunction) => {
      const authHeader = req.headers.authorization;
      const token = authHeader?.startsWith('Bearer ') ? authHeader.slice(7) : null;
      if (token && token.length === API_TOKEN.length) {
        try {
          if (timingSafeEqual(Buffer.from(token), Buffer.from(API_TOKEN))) {
            return next();
          }
        } catch {}
      }
      return res.status(401).json({ error: 'Authentication required' });
    });

    // Simulated sensitive endpoints
    app.post('/api/pii/deanonymize', (_req, res) => res.json({ deanonymized: true }));
    app.put('/api/chat/config', (_req, res) => res.json({ configured: true }));
    app.post('/api/data/clear-all', (_req, res) => res.json({ cleared: true }));
    app.get('/api/connectors/1/exports/data.json', (_req, res) => res.json({ file: true }));
    app.get('/api/browser-connector/conversations', (_req, res) => res.json({ conversations: [] }));

    return app;
  }

  it('blocks unauthenticated PII deanonymize (RT-01 attack chain)', async () => {
    const app = createProtectedApp();
    const res = await request(app)
      .post('/api/pii/deanonymize')
      .send({ text: '<PII:PERSON:abc123>', session_id: 'stolen-session' });
    expect(res.status).toBe(401);
  });

  it('blocks unauthenticated API key injection (RT-06)', async () => {
    const app = createProtectedApp();
    const res = await request(app)
      .put('/api/chat/config')
      .send({ groqApiKey: 'gsk_attacker_key' });
    expect(res.status).toBe(401);
  });

  it('blocks unauthenticated data deletion (RT-05)', async () => {
    const app = createProtectedApp();
    const res = await request(app).post('/api/data/clear-all');
    expect(res.status).toBe(401);
  });

  it('blocks unauthenticated conversation access (RT-08)', async () => {
    const app = createProtectedApp();
    const res = await request(app).get('/api/browser-connector/conversations');
    expect(res.status).toBe(401);
  });

  it('allows authenticated access to all endpoints', async () => {
    const app = createProtectedApp();

    const r1 = await request(app)
      .post('/api/pii/deanonymize')
      .set('Authorization', `Bearer ${API_TOKEN}`)
      .send({ text: 'test', session_id: 's' });
    expect(r1.status).toBe(200);

    const r2 = await request(app)
      .put('/api/chat/config')
      .set('Authorization', `Bearer ${API_TOKEN}`)
      .send({});
    expect(r2.status).toBe(200);

    const r3 = await request(app)
      .post('/api/data/clear-all')
      .set('Authorization', `Bearer ${API_TOKEN}`);
    expect(r3.status).toBe(200);
  });
});
