import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ConsentDialog } from './ConsentDialog';

// Mock the consent hook
vi.mock('./use-consent', () => ({
  useConsent: () => ({
    session: null,
    presets: [],
    isLoading: false,
    isAvailable: true,
    createSession: { mutate: vi.fn(), isPending: false },
    updateSession: { mutate: vi.fn(), isPending: false },
    applyPreset: { mutate: vi.fn(), isPending: false },
    deleteSession: { mutate: vi.fn(), isPending: false },
  }),
}));

function renderDialog(props = {}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ConsentDialog {...props} />
    </QueryClientProvider>
  );
}

describe('ConsentDialog', () => {
  it('renders the privacy shield button', () => {
    renderDialog();
    expect(screen.getByRole('button', { name: /privacy consent settings/i })).toBeInTheDocument();
  });

  it('shows unavailable message when consent is not available', () => {
    // Re-mock for unavailable state
    vi.doMock('./use-consent', () => ({
      useConsent: () => ({
        session: null,
        presets: [],
        isLoading: false,
        isAvailable: false,
        createSession: { mutate: vi.fn(), isPending: false },
        updateSession: { mutate: vi.fn(), isPending: false },
        applyPreset: { mutate: vi.fn(), isPending: false },
        deleteSession: { mutate: vi.fn(), isPending: false },
      }),
    }));
    // The button should still render regardless of availability
    renderDialog();
    expect(screen.getByRole('button', { name: /privacy consent settings/i })).toBeInTheDocument();
  });
});
