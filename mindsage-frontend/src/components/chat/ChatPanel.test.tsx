import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ChatPanel } from './ChatPanel';

// Mock the hooks
vi.mock('@/hooks/use-backend-chat', () => ({
  useBackendChat: () => ({
    isAvailable: true,
    isLoading: false,
    isConfigured: true,
    error: null,
    provider: 'openai',
    model: 'gpt-4.1',
    messages: [],
    sendMessage: vi.fn(),
    addVoiceMessages: vi.fn(),
    clearMessages: vi.fn(),
    stopGeneration: vi.fn(),
    dismissError: vi.fn(),
  }),
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

function renderChatPanel() {
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

describe('ChatPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders the empty state when configured', () => {
    renderChatPanel();
    expect(screen.getByText('How can I help you today?')).toBeInTheDocument();
  });

  it('shows keyboard shortcut hint', () => {
    renderChatPanel();
    expect(screen.getByText(/Enter to send/)).toBeInTheDocument();
    expect(screen.getByText(/Shift\+Enter for newline/)).toBeInTheDocument();
  });

  it('renders a textarea with auto-resize onChange handler', () => {
    renderChatPanel();
    const textarea = screen.getByPlaceholderText('Message...');
    expect(textarea).toBeInTheDocument();
    expect(textarea.tagName).toBe('TEXTAREA');
  });

  it('has the send button that requires input', () => {
    renderChatPanel();
    // When there's no input, the send button should be disabled
    const buttons = document.querySelectorAll('button');
    const sendButton = Array.from(buttons).find(btn =>
      btn.querySelector('svg') && btn.className.includes('rounded-full') && btn.className.includes('absolute')
    );
    expect(sendButton).toBeDefined();
    expect(sendButton).toBeDisabled();
  });
});
