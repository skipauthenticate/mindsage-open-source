import { describe, it, expect, vi, beforeEach } from 'vitest';
import { copyToClipboard, formatRelativeTime } from './utils';

describe('formatRelativeTime', () => {
  it('returns "Never" for undefined input', () => {
    expect(formatRelativeTime()).toBe('Never');
    expect(formatRelativeTime(undefined)).toBe('Never');
  });

  it('returns "Just now" for times less than 60 seconds ago', () => {
    const now = new Date();
    expect(formatRelativeTime(now.toISOString())).toBe('Just now');
  });

  it('returns minutes ago format', () => {
    const fiveMinAgo = new Date(Date.now() - 5 * 60 * 1000);
    expect(formatRelativeTime(fiveMinAgo.toISOString())).toBe('5m ago');
  });

  it('returns hours ago format', () => {
    const threeHoursAgo = new Date(Date.now() - 3 * 60 * 60 * 1000);
    expect(formatRelativeTime(threeHoursAgo.toISOString())).toBe('3h ago');
  });

  it('returns localized date for times over 24 hours ago', () => {
    const twoDaysAgo = new Date(Date.now() - 2 * 24 * 60 * 60 * 1000);
    const result = formatRelativeTime(twoDaysAgo.toISOString());
    // Should be a date string, not a relative format
    expect(result).not.toContain('ago');
    expect(result).not.toBe('Never');
  });
});

describe('copyToClipboard', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('uses navigator.clipboard when available', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, {
      clipboard: { writeText },
    });

    const result = await copyToClipboard('test text');
    expect(result).toBe(true);
    expect(writeText).toHaveBeenCalledWith('test text');
  });

  it('falls back to execCommand when clipboard API fails', async () => {
    Object.assign(navigator, {
      clipboard: { writeText: vi.fn().mockRejectedValue(new Error('denied')) },
    });

    const execCommand = vi.fn().mockReturnValue(true);
    document.execCommand = execCommand;

    const result = await copyToClipboard('fallback text');
    expect(result).toBe(true);
    expect(execCommand).toHaveBeenCalledWith('copy');
  });
});
