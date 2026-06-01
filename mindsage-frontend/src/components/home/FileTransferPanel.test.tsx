import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

// Mock the API module
vi.mock('@/lib/api', () => ({
  getLocalSendStatus: vi.fn().mockResolvedValue({ running: false, deviceName: 'Test' }),
  startLocalSend: vi.fn(),
  stopLocalSend: vi.fn(),
  uploadFiles: vi.fn(),
  getServerInfo: vi.fn().mockResolvedValue({ ip: '192.168.1.1', port: 3003 }),
  api: {
    getMediaStatus: vi.fn().mockResolvedValue({
      audio: { available: true },
      image: { available: true },
    }),
    getIndexingStatus: vi.fn().mockResolvedValue({ processing: 0, queued: 0 }),
  },
}));

// Mock qrcode.react
vi.mock('qrcode.react', () => ({
  QRCodeSVG: ({ value }: { value: string }) => <div data-testid="qr-code">{value}</div>,
}));

function renderWithQueryClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      {ui}
    </QueryClientProvider>
  );
}

// Dynamically import after mocks are set up
import { FileTransferPanel } from './FileTransferPanel';

describe('FileTransferPanel', () => {
  it('renders the file transfer card', () => {
    renderWithQueryClient(<FileTransferPanel />);
    expect(screen.getByText('File Transfer')).toBeInTheDocument();
  });

  it('shows supported file types in HTTP upload tab', async () => {
    renderWithQueryClient(<FileTransferPanel />);

    // HTTP Upload tab should show file type hints
    const httpTab = screen.getByText('HTTP Upload');
    httpTab.click();

    // Wait for the file type hints to appear (with media types after query resolves)
    const fileTypes = await screen.findByText(/MP3, WAV/);
    expect(fileTypes).toBeInTheDocument();
    expect(fileTypes.textContent).toContain('PDF');
    expect(fileTypes.textContent).toContain('JPG');
  });

  it('shows audio and image capability badges when available', async () => {
    renderWithQueryClient(<FileTransferPanel />);
    // Badges are rendered after mediaStatus query resolves
    expect(await screen.findByText('Audio')).toBeInTheDocument();
    expect(await screen.findByText('Image')).toBeInTheDocument();
  });
});
