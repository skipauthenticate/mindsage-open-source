import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { Folder } from '@/types';

interface CanvasState {
  // Search
  searchQuery: string;
  searchMode: 'semantic' | 'hybrid';
  searchResultDocIds: number[];
  isSearching: boolean;
  hasSearched: boolean;

  // Selection (React Flow handles the actual selection, we track IDs)
  selectedNodeIds: string[];

  // Layout
  snapToGrid: boolean;
  lockView: boolean;

  // Expanded nodes (progressive disclosure)
  expandedNodeIds: string[]; // Array for serialization

  // Hover state
  hoveredNodeId: string | null;

  // UI panels
  detailPanelNodeId: string | null;
  saveViewDialogOpen: boolean;

  // File explorer
  fileExplorerOpen: boolean;
  fileExplorerSelectedDocId: number | null;
  folders: Folder[];

  // Canvas ↔ Explorer sync
  highlightedCanvasNodeId: string | null;

  // Actions
  setSearchQuery: (query: string) => void;
  setSearchMode: (mode: 'semantic' | 'hybrid') => void;
  setSearchResultDocIds: (ids: number[]) => void;
  setIsSearching: (val: boolean) => void;
  setHasSearched: (val: boolean) => void;
  setSelectedNodeIds: (ids: string[]) => void;
  toggleSnapToGrid: () => void;
  toggleLockView: () => void;
  toggleExpandNode: (nodeId: string) => void;
  collapseAll: () => void;
  setHoveredNodeId: (id: string | null) => void;
  setDetailPanelNodeId: (id: string | null) => void;
  setSaveViewDialogOpen: (open: boolean) => void;
  setFileExplorerOpen: (open: boolean) => void;
  setFileExplorerSelectedDocId: (id: number | null) => void;
  setHighlightedCanvasNodeId: (id: string | null) => void;
  createFolder: (name: string) => void;
  renameFolder: (id: string, name: string) => void;
  deleteFolder: (id: string) => void;
  addDocumentToFolder: (folderId: string, docId: number) => void;
  removeDocumentFromFolder: (folderId: string, docId: number) => void;
  resetCanvas: () => void;
}

const initialState = {
  searchQuery: '',
  searchMode: 'hybrid' as const,
  searchResultDocIds: [] as number[],
  isSearching: false,
  hasSearched: false,
  selectedNodeIds: [] as string[],
  snapToGrid: false,
  lockView: false,
  expandedNodeIds: [] as string[],
  hoveredNodeId: null as string | null,
  detailPanelNodeId: null as string | null,
  saveViewDialogOpen: false,
  fileExplorerOpen: true,
  fileExplorerSelectedDocId: null as number | null,
  folders: [] as Folder[],
  highlightedCanvasNodeId: null as string | null,
};

export const useCanvasStore = create<CanvasState>()(
  persist(
    (set) => ({
      ...initialState,

      setSearchQuery: (query) => set({ searchQuery: query }),
      setSearchMode: (mode) => set({ searchMode: mode }),
      setSearchResultDocIds: (ids) => set({ searchResultDocIds: ids }),
      setIsSearching: (val) => set({ isSearching: val }),
      setHasSearched: (val) => set({ hasSearched: val }),
      setSelectedNodeIds: (ids) => set({ selectedNodeIds: ids }),
      toggleSnapToGrid: () => set((state) => ({ snapToGrid: !state.snapToGrid })),
      toggleLockView: () => set((state) => ({ lockView: !state.lockView })),

      toggleExpandNode: (nodeId) =>
        set((state) => {
          const expandedNodeIds = [...state.expandedNodeIds];
          const index = expandedNodeIds.indexOf(nodeId);
          if (index >= 0) {
            expandedNodeIds.splice(index, 1);
          } else {
            expandedNodeIds.push(nodeId);
          }
          return { expandedNodeIds };
        }),

      collapseAll: () => set({ expandedNodeIds: [] }),

      setHoveredNodeId: (id) => set({ hoveredNodeId: id }),
      setDetailPanelNodeId: (id) => set({ detailPanelNodeId: id }),
      setSaveViewDialogOpen: (open) => set({ saveViewDialogOpen: open }),
      setFileExplorerOpen: (open) => set({ fileExplorerOpen: open }),
      setFileExplorerSelectedDocId: (id) => set({ fileExplorerSelectedDocId: id }),
      setHighlightedCanvasNodeId: (id) => set({ highlightedCanvasNodeId: id }),

      createFolder: (name) =>
        set((state) => ({
          folders: [
            ...state.folders,
            {
              id: crypto.randomUUID(),
              name,
              documentIds: [],
              createdAt: new Date().toISOString(),
            },
          ],
        })),

      renameFolder: (id, name) =>
        set((state) => ({
          folders: state.folders.map((f) => (f.id === id ? { ...f, name } : f)),
        })),

      deleteFolder: (id) =>
        set((state) => ({
          folders: state.folders.filter((f) => f.id !== id),
        })),

      addDocumentToFolder: (folderId, docId) =>
        set((state) => ({
          folders: state.folders.map((f) =>
            f.id === folderId && !f.documentIds.includes(docId)
              ? { ...f, documentIds: [...f.documentIds, docId] }
              : f
          ),
        })),

      removeDocumentFromFolder: (folderId, docId) =>
        set((state) => ({
          folders: state.folders.map((f) =>
            f.id === folderId
              ? { ...f, documentIds: f.documentIds.filter((d) => d !== docId) }
              : f
          ),
        })),

      resetCanvas: () =>
        set({
          searchQuery: '',
          searchResultDocIds: [],
          isSearching: false,
          hasSearched: false,
          selectedNodeIds: [],
          expandedNodeIds: [],
          hoveredNodeId: null,
          detailPanelNodeId: null,
          saveViewDialogOpen: false,
          highlightedCanvasNodeId: null,
        }),
    }),
    {
      name: 'canvas-store',
      partialize: (state) => ({
        snapToGrid: state.snapToGrid,
        fileExplorerOpen: state.fileExplorerOpen,
        searchMode: state.searchMode,
        folders: state.folders,
      }),
    }
  )
);

// Selectors
export const useSearchQuery = () => useCanvasStore((s) => s.searchQuery);
export const useSearchMode = () => useCanvasStore((s) => s.searchMode);
export const useSearchResultDocIds = () => useCanvasStore((s) => s.searchResultDocIds);
export const useIsSearching = () => useCanvasStore((s) => s.isSearching);
export const useHasSearched = () => useCanvasStore((s) => s.hasSearched);
export const useSelectedNodeIds = () => useCanvasStore((s) => s.selectedNodeIds);
export const useSnapToGrid = () => useCanvasStore((s) => s.snapToGrid);
export const useLockView = () => useCanvasStore((s) => s.lockView);
export const useExpandedNodeIds = () => useCanvasStore((s) => new Set(s.expandedNodeIds));
export const useHoveredNodeId = () => useCanvasStore((s) => s.hoveredNodeId);
export const useDetailPanelNodeId = () => useCanvasStore((s) => s.detailPanelNodeId);
export const useSaveViewDialogOpen = () => useCanvasStore((s) => s.saveViewDialogOpen);
export const useFileExplorerOpen = () => useCanvasStore((s) => s.fileExplorerOpen);
export const useFileExplorerSelectedDocId = () => useCanvasStore((s) => s.fileExplorerSelectedDocId);
export const useFolders = () => useCanvasStore((s) => s.folders);
export const useHighlightedCanvasNodeId = () => useCanvasStore((s) => s.highlightedCanvasNodeId);
