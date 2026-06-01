import { describe, it, expect, vi } from 'vitest';
import { render } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { LLMConfigDialog } from './LLMConfigDialog';

vi.mock('@/hooks/use-toast', () => ({
  useToast: () => ({ toast: vi.fn() }),
}));

function renderDialog() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <LLMConfigDialog />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe('LLMConfigDialog', () => {
  it('renders the settings trigger button', () => {
    renderDialog();
    const settingsButton = document.querySelector('button');
    expect(settingsButton).toBeInTheDocument();
  });
});
