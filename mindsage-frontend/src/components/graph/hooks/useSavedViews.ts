import { useCallback } from 'react';
import { useReactFlow } from '@xyflow/react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { useCanvasStore } from '../store/canvasStore';
import { toast } from 'sonner';
import type { SavedView } from '@/types';

export function useSavedViews() {
  const reactFlow = useReactFlow();
  const queryClient = useQueryClient();
  const store = useCanvasStore();

  const { data: views = [], isLoading } = useQuery({
    queryKey: ['graphViews'],
    queryFn: () => api.getSavedViews(),
  });

  const saveMutation = useMutation({
    mutationFn: (params: { name: string; description?: string }) => {
      const rfInstance = reactFlow.toObject();
      const view: Omit<SavedView, 'id' | 'createdAt'> = {
        name: params.name,
        description: params.description,
        nodePositions: rfInstance.nodes.map((n) => ({
          id: n.id,
          position: n.position,
        })),
        viewport: rfInstance.viewport,
        searchQuery: store.searchQuery,
        searchMode: store.searchMode,
        visibleTypes: [],
        expandedNodeIds: Array.from(store.expandedNodeIds),
        nodeCount: rfInstance.nodes.length,
        edgeCount: rfInstance.edges.length,
      };
      return api.saveView(view);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['graphViews'] });
      store.setSaveViewDialogOpen(false);
      toast.success('View saved');
    },
    onError: () => {
      toast.error('Failed to save view');
    },
  });

  const loadView = useCallback(
    async (viewId: string) => {
      try {
        const view = await api.getSavedView(viewId);

        // Restore node positions
        reactFlow.setNodes((nodes) =>
          nodes.map((node) => {
            const savedPos = view.nodePositions.find((p) => p.id === node.id);
            return savedPos ? { ...node, position: savedPos.position } : node;
          })
        );

        // Restore viewport
        reactFlow.setViewport(view.viewport, { duration: 500 });

        // Restore store state
        store.setSearchQuery(view.searchQuery);
        store.setSearchMode(view.searchMode);
        // Restore expanded nodes
        store.collapseAll();
        for (const id of view.expandedNodeIds) {
          store.toggleExpandNode(id);
        }

        toast.success(`Loaded view: ${view.name}`);
      } catch {
        toast.error('Failed to load view');
      }
    },
    [reactFlow, store]
  );

  const deleteMutation = useMutation({
    mutationFn: (viewId: string) => api.deleteSavedView(viewId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['graphViews'] });
      toast.success('View deleted');
    },
    onError: () => {
      toast.error('Failed to delete view');
    },
  });

  return {
    views,
    isLoading,
    saveView: saveMutation.mutate,
    isSaving: saveMutation.isPending,
    loadView,
    deleteView: deleteMutation.mutate,
    isDeleting: deleteMutation.isPending,
  };
}
