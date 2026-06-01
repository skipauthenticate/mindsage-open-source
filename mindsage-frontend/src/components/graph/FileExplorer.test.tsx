import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

// Mock the API
vi.mock('@/lib/api', () => ({
  listVectorDocuments: vi.fn().mockResolvedValue({ documents: [], total: 0 }),
}));

// Mock canvas store with folders
const mockDeleteFolder = vi.fn();
const mockStore = {
  fileExplorerOpen: true,
  fileExplorerSelectedDocId: null,
  folders: [
    { id: 'folder-1', name: 'My Documents', documentIds: [1, 2] },
  ],
  createFolder: vi.fn(),
  deleteFolder: mockDeleteFolder,
  renameFolder: vi.fn(),
  moveDocumentToFolder: vi.fn(),
  removeDocumentFromFolder: vi.fn(),
  toggleFileExplorer: vi.fn(),
  setFileExplorerSelectedDocId: vi.fn(),
  toggleSnapToGrid: vi.fn(),
  toggleLockView: vi.fn(),
  snapToGrid: false,
  lockView: false,
};

vi.mock('./store/canvasStore', () => ({
  useCanvasStore: Object.assign(
    (selector: (s: typeof mockStore) => unknown) => selector(mockStore),
    { getState: () => mockStore }
  ),
}));

function renderWithProviders(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>
  );
}

import { FileExplorer } from './FileExplorer';

describe('FileExplorer', () => {
  beforeEach(() => {
    mockDeleteFolder.mockClear();
  });

  it('renders folder names', () => {
    renderWithProviders(<FileExplorer onSelectDocument={vi.fn()} />);
    expect(screen.getByText('My Documents')).toBeInTheDocument();
  });

  it('shows doc count next to folder', () => {
    renderWithProviders(<FileExplorer onSelectDocument={vi.fn()} />);
    // folderDocs is filtered through docMap, and since we have no documents
    // in the mock response, the count shown is 0
    expect(screen.getByText('0')).toBeInTheDocument();
  });

  it('folder delete triggers confirmation via AlertDialog (integration)', async () => {
    const user = userEvent.setup();
    renderWithProviders(<FileExplorer onSelectDocument={vi.fn()} />);

    // Find the dropdown trigger button (h-5 w-5 icon button)
    const allButtons = screen.getAllByRole('button');
    const dropdownTrigger = allButtons.find(
      (btn) => btn.className.includes('h-5') && btn.className.includes('w-5')
    );
    expect(dropdownTrigger).toBeDefined();
    await user.click(dropdownTrigger!);

    // The dropdown menu should now be open with Delete option
    const deleteItem = await screen.findByRole('menuitem', { name: /delete/i });
    await user.click(deleteItem);

    // AlertDialog confirmation should appear
    expect(await screen.findByText(/Delete folder "My Documents"/)).toBeInTheDocument();

    // Should NOT have deleted yet
    expect(mockDeleteFolder).not.toHaveBeenCalled();

    // Confirm deletion
    await user.click(screen.getByRole('button', { name: /delete folder/i }));
    expect(mockDeleteFolder).toHaveBeenCalledWith('folder-1');
  });
});
