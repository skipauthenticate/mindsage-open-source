import { useMemo } from 'react';
import dagre from '@dagrejs/dagre';
import type { Node, Edge } from '@xyflow/react';
import type { GraphNode, GraphEdge, ManualConnection } from '@/types';

const NODE_DIMENSIONS: Record<string, { width: number; height: number }> = {
  document: { width: 280, height: 140 },
  topic: { width: 160, height: 48 },
  person: { width: 120, height: 36 },
  organization: { width: 120, height: 36 },
  location: { width: 120, height: 36 },
  technology: { width: 120, height: 36 },
};

const NODE_TYPE_MAP: Record<string, string> = {
  document: 'documentCard',
  topic: 'topicBadge',
  person: 'entityPill',
  organization: 'entityPill',
  location: 'entityPill',
  technology: 'entityPill',
};

interface LayoutInput {
  nodes: GraphNode[];
  edges: GraphEdge[];
  manualEdges?: ManualConnection[];
  selectedNodeId?: string | null;
  hoveredNodeId?: string | null;
  expandedNodeIds?: Set<string>;
  lockView?: boolean;
  existingPositions?: Map<string, { x: number; y: number }>;
  highlightedCanvasNodeId?: string | null;
  focusMode?: boolean;
}

interface LayoutOutput {
  nodes: Node[];
  edges: Edge[];
}

export function useGraphLayout({
  nodes,
  edges,
  manualEdges = [],
  selectedNodeId,
  hoveredNodeId,
  expandedNodeIds,
  lockView = false,
  existingPositions,
  highlightedCanvasNodeId,
  focusMode = false,
}: LayoutInput): LayoutOutput {
  return useMemo(() => {
    if (nodes.length === 0) return { nodes: [], edges: [] };

    // Build set of connected node IDs for hover highlighting
    const hoveredConnections = new Set<string>();
    const hoveredEdgeIds = new Set<string>();
    if (hoveredNodeId) {
      hoveredConnections.add(hoveredNodeId);
      for (const e of edges) {
        if (e.source === hoveredNodeId || e.target === hoveredNodeId) {
          hoveredConnections.add(e.source);
          hoveredConnections.add(e.target);
          hoveredEdgeIds.add(e.id);
        }
      }
      // Also check manual edges
      for (const e of manualEdges) {
        if (e.source === hoveredNodeId || e.target === hoveredNodeId) {
          hoveredConnections.add(e.source);
          hoveredConnections.add(e.target);
          hoveredEdgeIds.add(e.id);
        }
      }
    }

    // Determine if we should use existing positions
    const useExistingPositions = lockView && existingPositions && existingPositions.size > 0;

    let nodePositions: Map<string, { x: number; y: number }>;

    if (useExistingPositions) {
      // Use existing positions when view is locked
      nodePositions = existingPositions!;
    } else {
      // Run Dagre layout
      const g = new dagre.graphlib.Graph();
      g.setGraph({
        rankdir: 'TB',
        nodesep: 60,
        ranksep: 120,
        marginx: 40,
        marginy: 40,
      });
      g.setDefaultEdgeLabel(() => ({}));

      // Add nodes with dimensions
      for (const node of nodes) {
        const dims = NODE_DIMENSIONS[node.type] || NODE_DIMENSIONS.technology;
        g.setNode(node.id, { width: dims.width, height: dims.height });
      }

      // Add edges (including manual edges for layout calculation)
      for (const edge of edges) {
        g.setEdge(edge.source, edge.target);
      }
      for (const edge of manualEdges) {
        g.setEdge(edge.source, edge.target);
      }

      // Run layout
      dagre.layout(g);

      // Extract positions
      nodePositions = new Map();
      for (const node of nodes) {
        const pos = g.node(node.id);
        const dims = NODE_DIMENSIONS[node.type] || NODE_DIMENSIONS.technology;
        nodePositions.set(node.id, {
          x: pos.x - dims.width / 2,
          y: pos.y - dims.height / 2,
        });
      }
    }

    // Map to React Flow nodes
    const nodeIdSet = new Set(nodes.map((n) => n.id));
    const flowNodes: Node[] = nodes.map((node) => {
      const pos = nodePositions.get(node.id) || { x: 0, y: 0 };
      const isHoverMode = hoveredNodeId !== null && hoveredNodeId !== undefined;
      const isConnected = hoveredConnections.has(node.id);

      return {
        id: node.id,
        type: NODE_TYPE_MAP[node.type] || 'entityPill',
        position: pos,
        data: {
          ...node,
          selected: selectedNodeId === node.id,
          highlighted: isHoverMode && isConnected,
          dimmed: isHoverMode && !isConnected,
          expanded: expandedNodeIds?.has(node.id) || false,
          pulseHighlight: highlightedCanvasNodeId === node.id,
        },
      };
    });

    // Map to React Flow edges (regular edges)
    const flowEdges: Edge[] = edges
      .filter((e) => nodeIdSet.has(e.source) && nodeIdSet.has(e.target))
      .map((edge) => {
        const isHoverMode = hoveredNodeId !== null && hoveredNodeId !== undefined;
        const isHighlighted = hoveredEdgeIds.has(edge.id);

        return {
          id: edge.id,
          source: edge.source,
          target: edge.target,
          type: 'default',
          style: {
            stroke: 'hsl(var(--foreground))',
            strokeWidth: isHighlighted ? 2.5 : focusMode ? 2 : 1.5,
            strokeOpacity: isHoverMode ? (isHighlighted ? 0.9 : 0.08) : focusMode ? 0.6 : 0.25,
          },
        };
      });

    // Add manual edges with distinct styling
    const manualFlowEdges: Edge[] = manualEdges
      .filter((e) => nodeIdSet.has(e.source) && nodeIdSet.has(e.target))
      .map((edge) => {
        const isHoverMode = hoveredNodeId !== null && hoveredNodeId !== undefined;
        const isHighlighted = hoveredEdgeIds.has(edge.id);

        return {
          id: edge.id,
          source: edge.source,
          target: edge.target,
          type: 'default',
          data: { isManual: true },
          style: {
            stroke: 'hsl(var(--primary))',
            strokeWidth: isHighlighted ? 2.5 : 2,
            strokeOpacity: isHoverMode ? (isHighlighted ? 0.6 : 0.15) : 0.4,
          },
        };
      });

    return { nodes: flowNodes, edges: [...flowEdges, ...manualFlowEdges] };
  }, [nodes, edges, manualEdges, selectedNodeId, hoveredNodeId, expandedNodeIds, lockView, existingPositions, highlightedCanvasNodeId, focusMode]);
}
