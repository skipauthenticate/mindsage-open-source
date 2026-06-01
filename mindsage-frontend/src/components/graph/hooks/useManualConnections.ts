import { useCallback } from 'react';
import { useReactFlow, type Connection } from '@xyflow/react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { toast } from 'sonner';

export function useManualConnections() {
  const { setEdges } = useReactFlow();
  const queryClient = useQueryClient();

  const createConnection = useMutation({
    mutationFn: ({ source, target }: { source: string; target: string }) =>
      api.createManualConnection(source, target),
    onSuccess: (data) => {
      // Add the new edge to React Flow optimistically
      setEdges((edges) => [
        ...edges,
        {
          id: data.id,
          source: data.source,
          target: data.target,
          type: 'default',
          data: { isManual: true },
          style: {
            stroke: 'hsl(var(--primary))',
            strokeWidth: 2,
            strokeOpacity: 0.4,
          },
        },
      ]);
      // Invalidate graph cache to re-fetch
      queryClient.invalidateQueries({ queryKey: ['knowledgeGraph'] });
    },
    onError: (error: Error) => {
      toast.error(error.message || 'Failed to create connection');
    },
  });

  const onConnect = useCallback(
    (connection: Connection) => {
      if (!connection.source || !connection.target) return;
      if (connection.source === connection.target) {
        toast.error('Cannot connect a node to itself');
        return;
      }
      createConnection.mutate({
        source: connection.source,
        target: connection.target,
      });
    },
    [createConnection]
  );

  const isValidConnection = useCallback((connection: Connection) => {
    return connection.source !== connection.target;
  }, []);

  return {
    onConnect,
    isValidConnection,
    isCreating: createConnection.isPending,
  };
}
