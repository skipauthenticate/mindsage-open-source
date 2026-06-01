import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ChatPanel } from './ChatPanel';

// Mutable state that tests can change before rendering
const hookState = {
  isAvailable: true,
  isLoading: false,
  isConfigured: true,
  error: null as string | null,
  provider: 'openai',
  model: 'gpt-4.1',
  messages: [] as Array<{ id: string; role: string; content: string; timestamp: Date; context?: unknown[]; voiceInitiated?: boolean }>,
  sendMessage: vi.fn(),
  addVoiceMessages: vi.fn(),
  clearMessages: vi.fn(),
  stopGeneration: vi.fn(),
  dismissError: vi.fn(),
};

vi.mock('@/hooks/use-backend-chat', () => ({
  useBackendChat: () => hookState,
}));

vi.mock('@/hooks/use-voice-rtc', () => ({
  useVoiceRTC: () => ({
    state: 'disconnected',
    isAvailable: false,
    connect: vi.fn(),
    disconnect: vi.fn(),
    toggleConnection: vi.fn(),
  }),
}));

vi.mock('@/components/consent', () => ({
  ConsentDialog: () => null,
  useConsent: () => ({
    isAvailable: false,
    isLoading: false,
    createSession: { mutate: vi.fn(), isPending: false },
  }),
}));

function renderChat() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <ChatPanel />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe('ChatPanel with messages', () => {
  beforeEach(() => {
    cleanup();
    hookState.messages = [];
    hookState.isLoading = false;
    hookState.error = null;
  });

  it('shows "New chat" button when messages exist', () => {
    hookState.messages = [
      { id: '1', role: 'user', content: 'Hello', timestamp: new Date() },
      { id: '2', role: 'assistant', content: 'Hi there!', timestamp: new Date() },
    ];
    renderChat();
    expect(screen.getByText('New chat')).toBeInTheDocument();
  });

  it('does not show "New chat" button when no messages', () => {
    hookState.messages = [];
    renderChat();
    expect(screen.queryByText('New chat')).not.toBeInTheDocument();
  });

  it('shows stop button when loading', () => {
    hookState.isLoading = true;
    hookState.messages = [
      { id: '1', role: 'user', content: 'Hello', timestamp: new Date() },
      { id: '2', role: 'assistant', content: '', timestamp: new Date() },
    ];
    renderChat();
    const stopButton = screen.getByTitle('Stop generating');
    expect(stopButton).toBeInTheDocument();
  });

  it('shows error banner with dismiss button', () => {
    hookState.error = 'Something went wrong';
    renderChat();
    expect(screen.getByText('Something went wrong')).toBeInTheDocument();
    // Should have a dismiss button (X icon)
    const errorBanner = screen.getByText('Something went wrong').closest('div');
    const dismissButton = errorBanner?.querySelector('button');
    expect(dismissButton).toBeInTheDocument();
  });
});
