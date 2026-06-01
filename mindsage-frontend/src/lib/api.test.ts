import { describe, it, expect, vi, beforeEach } from 'vitest';

// Mock fetch globally
const mockFetch = vi.fn();
vi.stubGlobal('fetch', mockFetch);

// Polyfill AbortSignal.timeout for jsdom
if (!AbortSignal.timeout) {
  AbortSignal.timeout = (ms: number) => {
    const controller = new AbortController();
    setTimeout(() => controller.abort(), ms);
    return controller.signal;
  };
}

// Must import after mocking
const { api } = await import('./api');

describe('api', () => {
  beforeEach(() => {
    mockFetch.mockReset();
  });

  describe('_isMediaFile', () => {
    it('detects audio files', () => {
      expect(api._isMediaFile('recording.mp3')).toBe(true);
      expect(api._isMediaFile('recording.wav')).toBe(true);
      expect(api._isMediaFile('recording.m4a')).toBe(true);
      expect(api._isMediaFile('recording.ogg')).toBe(true);
    });

    it('detects image files', () => {
      expect(api._isMediaFile('photo.jpg')).toBe(true);
      expect(api._isMediaFile('photo.jpeg')).toBe(true);
      expect(api._isMediaFile('photo.png')).toBe(true);
      expect(api._isMediaFile('photo.webp')).toBe(true);
    });

    it('rejects non-media files', () => {
      expect(api._isMediaFile('document.pdf')).toBe(false);
      expect(api._isMediaFile('notes.txt')).toBe(false);
      expect(api._isMediaFile('data.json')).toBe(false);
      expect(api._isMediaFile('style.css')).toBe(false);
    });

    it('is case-insensitive', () => {
      expect(api._isMediaFile('PHOTO.JPG')).toBe(true);
      expect(api._isMediaFile('Song.MP3')).toBe(true);
    });
  });

  describe('checkHealth', () => {
    it('returns true when API is healthy', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ status: 'ok' }),
      });
      const result = await api.checkHealth();
      expect(result).toBe(true);
      expect(mockFetch).toHaveBeenCalledWith('/api/stats', expect.objectContaining({ method: 'GET' }));
    });

    it('returns false when API is down', async () => {
      mockFetch.mockRejectedValueOnce(new Error('Network error'));
      const result = await api.checkHealth();
      expect(result).toBe(false);
    });
  });

  describe('getStats', () => {
    it('fetches and returns stats', async () => {
      const stats = { usedGB: 1.5, totalGB: 10, itemCount: 100, sourcesCount: 5 };
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve(stats),
      });
      const result = await api.getStats();
      expect(result).toEqual(stats);
      expect(mockFetch).toHaveBeenCalledWith('/api/stats');
    });

    it('throws on non-ok response', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        json: () => Promise.resolve({ error: 'Server error' }),
      });
      await expect(api.getStats()).rejects.toThrow('Server error');
    });
  });

  describe('searchVectorStore', () => {
    it('sends query and returns results', async () => {
      const response = { query: 'test', results: [] };
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve(response),
      });
      const result = await api.searchVectorStore('test', 5);
      expect(result).toEqual(response);
      expect(mockFetch).toHaveBeenCalledWith('/api/vector-store/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: expect.stringContaining('"query":"test"'),
      });
    });
  });

  describe('getLLMConfig', () => {
    it('fetches LLM configuration', async () => {
      const config = { provider: 'openai', model: 'gpt-4.1', apiKey: '' };
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve(config),
      });
      const result = await api.getLLMConfig();
      expect(result).toEqual(config);
    });
  });

  describe('deleteVectorDocument', () => {
    it('sends DELETE request with doc ID', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ success: true }),
      });
      const result = await api.deleteVectorDocument(42);
      expect(result).toEqual({ success: true });
      expect(mockFetch).toHaveBeenCalledWith('/api/vector-store/documents/42', {
        method: 'DELETE',
      });
    });
  });

  describe('deanonymize', () => {
    it('sends text and sessionId for de-anonymization', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ deanonymized_text: 'Hello John', tokens_replaced: 1 }),
      });
      const result = await api.deanonymize('Hello [PERSON_1]', 'session-123');
      expect(result).toEqual({ text: 'Hello John', tokens_replaced: 1 });
      expect(mockFetch).toHaveBeenCalledWith('/api/pii/deanonymize', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: 'Hello [PERSON_1]', session_id: 'session-123' }),
      });
    });
  });

  describe('disconnectVoice', () => {
    it('sends POST to disconnect endpoint', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({}) });
      await api.disconnectVoice();
      expect(mockFetch).toHaveBeenCalledWith('/api/voice/disconnect', {
        method: 'POST',
      });
    });
  });
});
