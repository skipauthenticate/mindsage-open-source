import { describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

// Mock API before importing component
vi.mock('@/lib/api', () => ({
  getConnectors: vi.fn().mockResolvedValue([]),
  syncConnector: vi.fn(),
  disconnectConnector: vi.fn(),
  api: {
    getSites: vi.fn().mockResolvedValue({
      sites: [
        { id: 'chatgpt', name: 'ChatGPT', url: 'https://chatgpt.com', authenticated: false },
      ],
    }),
    getCapturedConversations: vi.fn().mockResolvedValue({ conversations: [], total: 0 }),
  },
}));

import { ConnectorGrid } from './ConnectorGrid';

function renderWithProviders(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>
  );
}

describe('ConnectorGrid', () => {
  it('renders the data connectors heading', () => {
    renderWithProviders(<ConnectorGrid />);
    expect(screen.getByText('Data Connectors')).toBeInTheDocument();
  });

  it('shows empty state when no connectors are configured', async () => {
    renderWithProviders(<ConnectorGrid />);
    await waitFor(() => {
      expect(screen.getByText('No connectors configured yet')).toBeInTheDocument();
    });
  });

  it('renders the Add Connector button', () => {
    renderWithProviders(<ConnectorGrid />);
    expect(screen.getByText('Add Connector')).toBeInTheDocument();
  });
});
