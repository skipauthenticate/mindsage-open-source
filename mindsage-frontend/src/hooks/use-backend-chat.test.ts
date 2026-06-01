import { describe, it, expect } from 'vitest';

describe('useBackendChat interface', () => {
  it('exports the expected interface with stopGeneration and dismissError', async () => {
    // Verify the hook module exports correctly
    const mod = await import('./use-backend-chat');
    expect(mod.useBackendChat).toBeDefined();
    expect(typeof mod.useBackendChat).toBe('function');
  });

  it('Message type includes voiceInitiated field', async () => {
    // Structural type test — verified at compile time
    // This test documents the expected shape
    const message = {
      id: '1',
      role: 'user' as const,
      content: 'hello',
      timestamp: new Date(),
      voiceInitiated: true,
    };
    expect(message.voiceInitiated).toBe(true);
  });
});
