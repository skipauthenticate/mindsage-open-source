import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

// Mock the API
vi.mock('@/lib/api', () => ({
  getMCPStatus: vi.fn().mockResolvedValue({ ready: true, documentCount: 42 }),
  getServerInfo: vi.fn().mockResolvedValue({ ip: '192.168.1.100' }),
}));

// Mock the shared clipboard utility
vi.mock('@/lib/utils', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/lib/utils')>();
  return {
    ...original,
    copyToClipboard: vi.fn().mockResolvedValue(true),
  };
});

function renderWithProviders(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>
  );
}

import { MCPSetupPanel } from './MCPSetupPanel';

describe('MCPSetupPanel', () => {
  it('renders the MCP Integration title', () => {
    renderWithProviders(<MCPSetupPanel />);
    expect(screen.getByText('MCP Integration')).toBeInTheDocument();
  });

  it('shows setup instructions for Claude Desktop', () => {
    renderWithProviders(<MCPSetupPanel />);
    const trigger = screen.getByText('Claude Desktop Setup');
    fireEvent.click(trigger);
    expect(screen.getByText(/Add this to your Claude Desktop config/)).toBeInTheDocument();
  });

  it('shows setup instructions for Claude CLI', () => {
    renderWithProviders(<MCPSetupPanel />);
    const trigger = screen.getByText('Claude CLI Setup');
    fireEvent.click(trigger);
    expect(screen.getByText(/Run this command to add MindSage/)).toBeInTheDocument();
  });
});
