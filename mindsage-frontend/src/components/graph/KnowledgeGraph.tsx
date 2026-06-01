import { useCallback, useState, useMemo, useEffect, useRef, lazy, Suspense } from 'react';
import { ReactFlow, ReactFlowProvider, Background, Controls, useNodesState, useEdgesState, useReactFlow, type Node, SelectionMode } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { motion, AnimatePresence } from 'framer-motion';
import { FileText, Tag, User, Building, MapPin, Cpu, X, Loader2, Minimize2, Search, LayoutGrid, Lock, LockOpen, Save, Eye, Trash2, SlidersHorizontal, Shield, ShieldAlert } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog';
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger, DropdownMenuSeparator, DropdownMenuCheckboxItem, DropdownMenuLabel, DropdownMenuRadioGroup, DropdownMenuRadioItem } from '@/components/ui/dropdown-menu';
import { useQuery } from '@tanstack/react-query';
import { api, getKnowledgeGraph, getVectorDocument, search as semanticSearch } from '@/lib/api';
import type { NodeType, GraphNode, GraphNodeDetails, VectorDocument } from '@/types';

// Lazy-load document viewers — only needed when a document is selected
const DocumentContentViewer = lazy(() =>
  import('./MarkdownViewer').then(m => ({ default: m.DocumentContentViewer }))
);
const AudioDocumentViewer = lazy(() =>
  import('@/components/explore/AudioDocumentViewer').then(m => ({ default: m.AudioDocumentViewer }))
);

// Vector store URL for image serving
const VECTOR_STORE_URL = import.meta.env.VITE_VECTOR_STORE_URL || 'http://localhost:8085';
import DocumentCardNode from './nodes/DocumentCardNode';
import TopicBadgeNode from './nodes/TopicBadgeNode';
import EntityPillNode from './nodes/EntityPillNode';
import { useGraphLayout } from './useGraphLayout';
import { useExpandedNodes } from './useExpandedNodes';
import { useManualConnections } from './hooks/useManualConnections';
import { useSavedViews } from './hooks/useSavedViews';
import { useCanvasStore } from './store/canvasStore';
import { CanvasEmptyState, CanvasSearchingState, CanvasNoResultsState } from './CanvasEmptyState';
import { FileExplorer } from './FileExplorer';

const nodeTypeConfig: Record<NodeType, { icon: typeof FileText; color: string; label: string }> = {
  document: { icon: FileText, color: 'bg-foreground/10 border-foreground/20', label: 'Documents' },
  topic: { icon: Tag, color: 'bg-foreground/10 border-foreground/30', label: 'Topics' },
  person: { icon: User, color: 'bg-foreground/10 border-foreground/25', label: 'Persons' },
  organization: { icon: Building, color: 'bg-foreground/10 border-foreground/20', label: 'Organizations' },
  location: { icon: MapPin, color: 'bg-foreground/10 border-foreground/15', label: 'Locations' },
  technology: { icon: Cpu, color: 'bg-foreground/10 border-foreground/35', label: 'Technologies' },
};

const nodeTypes = {
  documentCard: DocumentCardNode,
  topicBadge: TopicBadgeNode,
  entityPill: EntityPillNode,
};

function KnowledgeGraphInner() {
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [selectedNodeDetails, setSelectedNodeDetails] = useState<GraphNodeDetails | null>(null);
  const [selectedFullDoc, setSelectedFullDoc] = useState<VectorDocument | null>(null);
  const [viewingDocId, setViewingDocId] = useState<number | null>(null);
  const [loadingDetails, setLoadingDetails] = useState(false);
  const [canvasSearchQuery, setCanvasSearchQuery] = useState('');
  const [saveViewName, setSaveViewName] = useState('');
  const [saveViewDescription, setSaveViewDescription] = useState('');
  const prevNodeKeyRef = useRef('');

  // Use Zustand store with individual selectors
  const snapToGrid = useCanvasStore(s => s.snapToGrid);
  const lockView = useCanvasStore(s => s.lockView);
  const saveViewDialogOpen = useCanvasStore(s => s.saveViewDialogOpen);
  const selectedNodeIds = useCanvasStore(s => s.selectedNodeIds);
  const searchResultDocIds = useCanvasStore(s => s.searchResultDocIds);
  const isSearching = useCanvasStore(s => s.isSearching);
  const hasSearched = useCanvasStore(s => s.hasSearched);
  const highlightedCanvasNodeId = useCanvasStore(s => s.highlightedCanvasNodeId);

  // Stable action references
  const storeActions = useMemo(() => ({
    toggleSnapToGrid: useCanvasStore.getState().toggleSnapToGrid,
    toggleLockView: useCanvasStore.getState().toggleLockView,
    setSaveViewDialogOpen: useCanvasStore.getState().setSaveViewDialogOpen,
    setSelectedNodeIds: useCanvasStore.getState().setSelectedNodeIds,
    setSearchResultDocIds: useCanvasStore.getState().setSearchResultDocIds,
    setIsSearching: useCanvasStore.getState().setIsSearching,
    setHasSearched: useCanvasStore.getState().setHasSearched,
    setFileExplorerSelectedDocId: useCanvasStore.getState().setFileExplorerSelectedDocId,
    setHighlightedCanvasNodeId: useCanvasStore.getState().setHighlightedCanvasNodeId,
  }), []);

  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null);
  const [connectionDensity, setConnectionDensity] = useState<'sparse' | 'normal' | 'dense'>('normal');
  const maxEdgesPerNode = connectionDensity === 'sparse' ? 3 : connectionDensity === 'normal' ? 8 : 20;

  const { fitView } = useReactFlow();
  const manualConnections = useManualConnections();
  const savedViews = useSavedViews();

  const { data: graphData } = useQuery({
    queryKey: ['knowledgeGraph'],
    queryFn: getKnowledgeGraph,
  });

  // Fetch full document when viewingDocId changes (from graph click or file explorer)
  useEffect(() => {
    if (viewingDocId === null || viewingDocId === undefined) {
      setSelectedFullDoc(null);
      return;
    }

    let cancelled = false;
    const fetchDoc = async () => {
      setLoadingDetails(true);
      try {
        const fullDoc = await getVectorDocument(viewingDocId);
        if (!cancelled) setSelectedFullDoc(fullDoc);
      } catch (err) {
        console.error('Failed to fetch document:', err);
        if (!cancelled) setSelectedFullDoc(null);
      } finally {
        if (!cancelled) setLoadingDetails(false);
      }
    };

    fetchDoc();
    return () => { cancelled = true; };
  }, [viewingDocId]);

  // Fetch graph node details for non-document nodes (topics, entities)
  useEffect(() => {
    if (!selectedNode || selectedNode.type === 'document') {
      setSelectedNodeDetails(null);
      return;
    }

    let cancelled = false;
    const fetchDetails = async () => {
      setLoadingDetails(true);
      try {
        const details = await api.getGraphNodeDetails(selectedNode.id);
        if (!cancelled) setSelectedNodeDetails(details);
      } catch (err) {
        console.error('Failed to fetch node details:', err);
        if (!cancelled) setSelectedNodeDetails(null);
      } finally {
        if (!cancelled) setLoadingDetails(false);
      }
    };

    fetchDetails();
    return () => { cancelled = true; };
  }, [selectedNode]);


  // ---- SEARCH ----
  const handleSearch = useCallback(async () => {
    const query = canvasSearchQuery.trim();
    if (!query) return;

    storeActions.setIsSearching(true);
    storeActions.setHasSearched(true);
    try {
      const results = await semanticSearch(query, 20);
      storeActions.setSearchResultDocIds(results.map(r => r.parentDocId));
    } catch (err) {
      console.error('Search failed:', err);
      storeActions.setSearchResultDocIds([]);
    } finally {
      storeActions.setIsSearching(false);
    }
  }, [canvasSearchQuery, storeActions]);

  const handleSearchKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      handleSearch();
    }
    if (e.key === 'Escape') {
      handleClearSearch();
    }
  };

  const handleClearSearch = () => {
    setCanvasSearchQuery('');
    storeActions.setSearchResultDocIds([]);
    storeActions.setHasSearched(false);
  };

  // ---- AUTO-CLEAR HIGHLIGHT ----
  useEffect(() => {
    if (!highlightedCanvasNodeId) return;
    const timer = setTimeout(() => {
      storeActions.setHighlightedCanvasNodeId(null);
    }, 2000);
    return () => clearTimeout(timer);
  }, [highlightedCanvasNodeId, storeActions]);

  // ---- DATA PIPELINE ----
  const allNodes = graphData?.nodes ?? [];
  const allEdges = graphData?.edges ?? [];

  // Progressive disclosure
  const {
    expandedIds,
    expandedEntityIds,
    expandedTopicIds,
    focusOn,
    collapseAll,
    hasExpanded,
  } = useExpandedNodes(allNodes, allEdges);

  // "Active" node IDs: in focus mode only the expanded doc, otherwise search results
  const activeNodeIds = useMemo(() => {
    const ids = new Set<string>();
    if (expandedIds.size > 0) {
      // Focus mode: only the expanded doc(s)
      for (const id of expandedIds) ids.add(id);
    } else {
      // Browse mode: all search result docs
      for (const docId of searchResultDocIds) ids.add(`doc_${docId}`);
    }
    return ids;
  }, [searchResultDocIds, expandedIds]);

  // Edges: clean cards in browse mode, connections in focus mode
  const visibleEdges = useMemo(() => {
    if (!graphData) return [];
    if (activeNodeIds.size === 0) return [];
    if (expandedIds.size === 0) return []; // Browse mode: no edges, just clean cards

    // Focus mode: edges from/to the expanded doc, with density cap
    const candidates = allEdges.filter(e =>
      activeNodeIds.has(e.source) || activeNodeIds.has(e.target)
    );

    const nodeEdgeCounts = new Map<string, number>();
    const result: typeof candidates = [];

    for (const edge of candidates) {
      const sourceCount = nodeEdgeCounts.get(edge.source) ?? 0;
      const targetCount = nodeEdgeCounts.get(edge.target) ?? 0;

      if (sourceCount < maxEdgesPerNode && targetCount < maxEdgesPerNode) {
        result.push(edge);
        nodeEdgeCounts.set(edge.source, sourceCount + 1);
        nodeEdgeCounts.set(edge.target, targetCount + 1);
      }
    }

    return result;
  }, [graphData, allEdges, activeNodeIds, maxEdgesPerNode, expandedIds]);

  // Visible nodes — focus mode vs browse mode
  const visibleNodes = useMemo(() => {
    if (!graphData) return [];
    if (!hasSearched) return [];

    const searchDocNodeIds = new Set(searchResultDocIds.map(id => `doc_${id}`));
    const result = new Map<string, typeof allNodes[0]>();

    if (expandedIds.size > 0) {
      // Focus mode: only the expanded doc + its direct connections
      for (const n of allNodes) {
        if (expandedIds.has(n.id)) {
          result.set(n.id, n);
        }
        if (n.type === 'topic' && expandedTopicIds.has(n.id)) {
          result.set(n.id, n);
        }
        if (expandedEntityIds.has(n.id)) {
          result.set(n.id, n);
        }
      }
    } else {
      // Browse mode: only search result document cards, no entities/topics
      for (const n of allNodes) {
        if (n.type === 'document' && searchDocNodeIds.has(n.id)) {
          result.set(n.id, n);
        }
      }
    }

    return Array.from(result.values());
  }, [graphData, allNodes, hasSearched, searchResultDocIds, expandedIds, expandedTopicIds, expandedEntityIds]);

  // Dagre layout
  const { nodes: layoutNodes, edges: layoutEdges } = useGraphLayout({
    nodes: visibleNodes,
    edges: visibleEdges,
    selectedNodeId: selectedNode?.id,
    hoveredNodeId,
    expandedNodeIds: expandedIds,
    lockView,
    highlightedCanvasNodeId,
    focusMode: expandedIds.size > 0,
  });

  const [nodes, setNodes, onNodesChange] = useNodesState(layoutNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(layoutEdges);

  // Sync layout output to React Flow state
  useEffect(() => {
    setNodes(prev => {
      const prevMap = new Map(prev.map(n => [n.id, n]));
      return layoutNodes.map(layoutNode => {
        const existing = prevMap.get(layoutNode.id);
        if (existing) {
          return {
            ...existing,
            position: layoutNode.position,
            data: layoutNode.data,
            type: layoutNode.type,
          };
        }
        return layoutNode;
      });
    });
  }, [layoutNodes, setNodes]);

  useEffect(() => {
    setEdges(prev => {
      const prevMap = new Map(prev.map(e => [e.id, e]));
      return layoutEdges.map(layoutEdge => {
        const existing = prevMap.get(layoutEdge.id);
        if (existing) {
          return {
            ...existing,
            source: layoutEdge.source,
            target: layoutEdge.target,
            data: layoutEdge.data,
            style: layoutEdge.style,
            type: layoutEdge.type,
          };
        }
        return layoutEdge;
      });
    });
  }, [layoutEdges, setEdges]);

  // Stable identity of visible node set
  const visibleNodeKey = useMemo(
    () => visibleNodes.map(n => n.id).sort().join(','),
    [visibleNodes]
  );

  // Fit view when node set changes
  useEffect(() => {
    if (lockView) return;
    if (visibleNodes.length === 0) return;
    if (visibleNodeKey === prevNodeKeyRef.current) return;
    prevNodeKeyRef.current = visibleNodeKey;

    const timer = setTimeout(() => {
      fitView({ padding: 0.3, duration: 500 });
    }, 250);
    return () => clearTimeout(timer);
  }, [visibleNodeKey, fitView, lockView, visibleNodes.length]);

  const onNodeClick = useCallback((_: any, node: Node) => {
    const graphNode = graphData?.nodes.find(n => n.id === node.id);
    if (!graphNode) return;

    // Toggle: clicking the already-selected node deselects it
    if (selectedNode?.id === graphNode.id) {
      setSelectedNode(null);
      setViewingDocId(null);
      collapseAll();
      return;
    }

    setSelectedNode(graphNode);

    // Focus on this document (show its connections, hide other docs)
    if (graphNode.type === 'document') {
      focusOn(graphNode.id);
      const match = graphNode.id.match(/^doc_(\d+)$/);
      if (match) {
        const docId = parseInt(match[1], 10);
        setViewingDocId(docId);
        storeActions.setFileExplorerSelectedDocId(docId);
      }
    } else {
      setViewingDocId(null);
    }
  }, [graphData, focusOn, collapseAll, storeActions, selectedNode?.id]);

  const onNodeMouseEnter = useCallback((_: any, node: Node) => {
    setHoveredNodeId(node.id);
  }, []);

  const onNodeMouseLeave = useCallback(() => {
    setHoveredNodeId(null);
  }, []);

  const handleSelectionChange = useCallback(({ nodes }: { nodes: Node[] }) => {
    const newIds = nodes.map(n => n.id);
    const currentIds = useCanvasStore.getState().selectedNodeIds;
    if (newIds.length !== currentIds.length || newIds.some((id, i) => id !== currentIds[i])) {
      storeActions.setSelectedNodeIds(newIds);
    }
  }, [storeActions]);

  // File explorer → canvas sync + open document viewer
  const handleFileExplorerSelectDoc = useCallback((docId: number) => {
    const nodeId = `doc_${docId}`;
    storeActions.setHighlightedCanvasNodeId(nodeId);

    // Open the document in the detail panel
    setViewingDocId(docId);
    // Clear non-doc selection if any
    if (selectedNode && selectedNode.type !== 'document') {
      setSelectedNode(null);
    }

    // If node is on canvas, fit view to it
    const nodeExists = nodes.find(n => n.id === nodeId);
    if (nodeExists) {
      fitView({ nodes: [{ id: nodeId }], padding: 0.5, duration: 500 });
    }
  }, [storeActions, nodes, fitView, selectedNode]);

  const handleSaveView = () => {
    if (!saveViewName.trim()) return;
    savedViews.saveView({
      name: saveViewName.trim(),
      description: saveViewDescription.trim() || undefined,
    });
    setSaveViewName('');
    setSaveViewDescription('');
  };

  // Determine canvas overlay state
  const showEmptyState = !hasSearched && !isSearching;
  const showSearchingState = isSearching;
  const showNoResultsState = hasSearched && !isSearching && searchResultDocIds.length === 0;

  return (
    <div className="h-full w-full relative">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={onNodeClick}
        onNodeMouseEnter={onNodeMouseEnter}
        onNodeMouseLeave={onNodeMouseLeave}
        onPaneClick={() => { setSelectedNode(null); setViewingDocId(null); collapseAll(); }}
        onConnect={manualConnections.onConnect}
        isValidConnection={manualConnections.isValidConnection}
        nodeTypes={nodeTypes}
        nodesDraggable={!lockView}
        nodesConnectable={!lockView}
        snapToGrid={snapToGrid}
        snapGrid={[24, 24]}
        fitView
        selectionMode={SelectionMode.Partial}
        multiSelectionKeyCode="Shift"
        selectionOnDrag
        onSelectionChange={handleSelectionChange}
        className="bg-background"
        minZoom={0.1}
        maxZoom={2.5}
      >
        <Background
          gap={24}
          size={snapToGrid ? 1.5 : 1}
          color="hsl(var(--border))"
        />
        <Controls className="bg-card border-border" />
      </ReactFlow>

      {/* Canvas overlays */}
      {showEmptyState && <CanvasEmptyState />}
      {showSearchingState && <CanvasSearchingState />}
      {showNoResultsState && <CanvasNoResultsState query={canvasSearchQuery} />}

      {/* Canvas Top Bar - Search + View Management + Lock */}
      <div className="absolute top-4 left-1/2 -translate-x-1/2 z-20 flex items-center gap-2">
        {/* Search Bar */}
        <div className="relative w-full max-w-[480px]">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground pointer-events-none" />
          <Input
            placeholder="Search your knowledge base..."
            value={canvasSearchQuery}
            onChange={(e) => setCanvasSearchQuery(e.target.value)}
            onKeyDown={handleSearchKeyDown}
            className="h-11 pl-10 pr-10 bg-card/95 backdrop-blur-sm border shadow-md"
          />
          {canvasSearchQuery && (
            <Button
              variant="ghost"
              size="icon"
              className="absolute right-2 top-1/2 -translate-y-1/2 h-7 w-7"
              onClick={handleClearSearch}
            >
              <X className="h-3.5 w-3.5" />
            </Button>
          )}
        </div>

        {/* Result count badge */}
        {hasSearched && !isSearching && searchResultDocIds.length > 0 && (
          <Badge variant="secondary" className="h-7 px-2.5 text-xs whitespace-nowrap">
            {searchResultDocIds.length} documents
          </Badge>
        )}

        {/* View Management Dropdown */}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline" size="icon" className="h-11 w-11 bg-card/95 backdrop-blur-sm shadow-md" aria-label="View management">
              <LayoutGrid className="h-4 w-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-56">
            <DropdownMenuItem onClick={() => storeActions.setSaveViewDialogOpen(true)}>
              <Save className="h-4 w-4 mr-2" />
              Save Current View...
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            {savedViews.views.length > 0 && (
              <>
                <DropdownMenuLabel className="text-xs">Load View</DropdownMenuLabel>
                {savedViews.views.map((view) => (
                  <DropdownMenuItem
                    key={view.id}
                    onClick={() => savedViews.loadView(view.id)}
                    className="flex items-center justify-between"
                  >
                    <span className="flex items-center">
                      <Eye className="h-3.5 w-3.5 mr-2" />
                      {view.name}
                    </span>
                    <AlertDialog>
                      <AlertDialogTrigger asChild>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-5 w-5 ml-2"
                          onClick={(e) => e.stopPropagation()}
                        >
                          <Trash2 className="h-3 w-3" />
                        </Button>
                      </AlertDialogTrigger>
                      <AlertDialogContent>
                        <AlertDialogHeader>
                          <AlertDialogTitle>Delete saved view "{view.name}"?</AlertDialogTitle>
                          <AlertDialogDescription>
                            This saved view will be permanently removed.
                          </AlertDialogDescription>
                        </AlertDialogHeader>
                        <AlertDialogFooter>
                          <AlertDialogCancel>Cancel</AlertDialogCancel>
                          <AlertDialogAction onClick={() => savedViews.deleteView(view.id)}>
                            Delete
                          </AlertDialogAction>
                        </AlertDialogFooter>
                      </AlertDialogContent>
                    </AlertDialog>
                  </DropdownMenuItem>
                ))}
                <DropdownMenuSeparator />
              </>
            )}
            <DropdownMenuItem onClick={() => fitView({ padding: 0.3, duration: 500 })}>
              <Minimize2 className="h-4 w-4 mr-2" />
              Auto-Arrange
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuCheckboxItem
              checked={snapToGrid}
              onCheckedChange={() => storeActions.toggleSnapToGrid()}
            >
              Snap to Grid
            </DropdownMenuCheckboxItem>
          </DropdownMenuContent>
        </DropdownMenu>

        {/* Connection Density */}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline" size="icon" className="h-11 w-11 bg-card/95 backdrop-blur-sm shadow-md" title="Connection density" aria-label="Connection density">
              <SlidersHorizontal className="h-4 w-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuLabel className="text-xs">Connection Density</DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuRadioGroup value={connectionDensity} onValueChange={(v) => setConnectionDensity(v as 'sparse' | 'normal' | 'dense')}>
              <DropdownMenuRadioItem value="sparse">
                Sparse (max 3/node)
              </DropdownMenuRadioItem>
              <DropdownMenuRadioItem value="normal">
                Normal (max 8/node)
              </DropdownMenuRadioItem>
              <DropdownMenuRadioItem value="dense">
                Dense (max 20/node)
              </DropdownMenuRadioItem>
            </DropdownMenuRadioGroup>
          </DropdownMenuContent>
        </DropdownMenu>

        {/* Lock Toggle */}
        <Button
          variant={lockView ? 'default' : 'outline'}
          size="icon"
          className="h-11 w-11 bg-card/95 backdrop-blur-sm shadow-md"
          onClick={() => storeActions.toggleLockView()}
        >
          {lockView ? <Lock className="h-4 w-4" /> : <LockOpen className="h-4 w-4" />}
        </Button>
      </div>

      {/* Save View Dialog */}
      <Dialog open={saveViewDialogOpen} onOpenChange={storeActions.setSaveViewDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Save Current View</DialogTitle>
            <DialogDescription>
              Save the current canvas layout and search state for later.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="view-name">View Name *</Label>
              <Input
                id="view-name"
                placeholder="My Important View"
                value={saveViewName}
                onChange={(e) => setSaveViewName(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="view-description">Description (optional)</Label>
              <Textarea
                id="view-description"
                placeholder="What makes this view useful?"
                value={saveViewDescription}
                onChange={(e) => setSaveViewDescription(e.target.value)}
                rows={3}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => storeActions.setSaveViewDialogOpen(false)}>
              Cancel
            </Button>
            <Button onClick={handleSaveView} disabled={!saveViewName.trim() || savedViews.isSaving}>
              {savedViews.isSaving ? (
                <>
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  Saving...
                </>
              ) : (
                <>
                  <Save className="h-4 w-4 mr-2" />
                  Save View
                </>
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Multi-Select Toolbar */}
      {selectedNodeIds.length > 1 && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: 10 }}
          className="absolute bottom-4 left-1/2 -translate-x-1/2 z-20 bg-card/95 backdrop-blur-sm border border-border rounded-lg px-4 py-2.5 shadow-lg flex items-center gap-3"
        >
          <Badge variant="secondary" className="text-sm">
            {selectedNodeIds.length} nodes selected
          </Badge>
          <Button
            variant="outline"
            size="sm"
            onClick={() => storeActions.setSelectedNodeIds([])}
          >
            Deselect All
          </Button>
        </motion.div>
      )}

      {/* Stats overlay */}
      {hasSearched && visibleNodes.length > 0 && (
        <div className="absolute top-4 left-4 bg-card/95 backdrop-blur-sm border border-border rounded-lg px-3 py-2 pointer-events-auto z-10 shadow-sm flex items-center gap-3">
          <p className="text-xs text-muted-foreground">
            {visibleNodes.length} nodes &middot; {visibleEdges.length} edges
          </p>
          {hasExpanded && (
            <Button
              variant="ghost"
              size="sm"
              className="h-6 px-2 text-xs text-muted-foreground hover:text-foreground"
              onClick={collapseAll}
            >
              <Minimize2 className="h-3 w-3 mr-1" />
              Collapse all
            </Button>
          )}
        </div>
      )}

      {/* File Explorer (replaces filters sidebar) */}
      <FileExplorer onSelectDocument={handleFileExplorerSelectDoc} />

      {/* Document detail panel — opens from file explorer click or graph doc node click */}
      <AnimatePresence>
        {((viewingDocId !== null && viewingDocId !== undefined) || (selectedNode && selectedNode.type !== 'document')) && (
          <motion.div
            initial={{ x: 80, opacity: 0 }}
            animate={{ x: 0, opacity: 1 }}
            exit={{ x: 80, opacity: 0 }}
            transition={{ type: 'tween', duration: 0.25, ease: [0.25, 0.1, 0.25, 1] }}
            className={`absolute top-4 right-4 bottom-4 bg-card/95 backdrop-blur-sm border border-border rounded-lg flex flex-col z-20 shadow-lg ${
              viewingDocId !== null && viewingDocId !== undefined ? 'w-[480px]' : 'w-80'
            }`}
          >
            {/* Header */}
            <div className="p-3 border-b border-border flex items-center justify-between">
              <div className="flex items-center gap-2 min-w-0">
                {selectedFullDoc ? (
                  <>
                    <Badge variant="outline" className="shrink-0 capitalize">{selectedFullDoc.fileType}</Badge>
                    <h3 className="font-medium text-sm truncate">{selectedFullDoc.filename}</h3>
                  </>
                ) : selectedNode ? (
                  <>
                    <Badge variant="outline" className="shrink-0">{nodeTypeConfig[selectedNode.type].label}</Badge>
                    <h3 className="font-medium text-sm truncate">{selectedNode.label}</h3>
                  </>
                ) : null}
              </div>
              <Button variant="ghost" size="icon" className="h-6 w-6 shrink-0" aria-label="Close details" onClick={() => {
                setViewingDocId(null);
                setSelectedNode(null);
              }}>
                <X className="h-4 w-4" />
              </Button>
            </div>

            {/* Metadata bar for documents */}
            {selectedFullDoc && (
              <div className="px-3 py-2 border-b border-border flex items-center gap-2 flex-wrap">
                <span className="text-xs text-muted-foreground shrink-0">
                  {selectedFullDoc.wordCount} words
                </span>
                {selectedFullDoc.topics.map((topic) => (
                  <Badge key={topic} variant="secondary" className="text-[10px]">{topic}</Badge>
                ))}
              </div>
            )}

            {loadingDetails ? (
              <div className="flex-1 flex items-center justify-center">
                <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
              </div>
            ) : selectedFullDoc ? (
              /* Full document viewer — audio / image / text */
              selectedFullDoc.fileType === 'audio' ? (
                <Suspense fallback={<div className="flex-1 flex items-center justify-center"><Loader2 className="h-6 w-6 animate-spin text-muted-foreground" /></div>}>
                  <AudioDocumentViewer document={selectedFullDoc} />
                </Suspense>
              ) : selectedFullDoc.fileType === 'image' && selectedFullDoc.imageId ? (
                <ScrollArea className="flex-1">
                  <div className="p-4 space-y-4">
                    {/* Image tabs: Original / Redacted */}
                    <Tabs defaultValue="original" className="w-full">
                      <TabsList className="grid w-full grid-cols-2 max-w-[300px]">
                        <TabsTrigger value="original">Original</TabsTrigger>
                        <TabsTrigger value="redacted" disabled={selectedFullDoc.redactionPending}>
                          {selectedFullDoc.redactionPending ? (
                            <span className="flex items-center gap-1">
                              <Loader2 className="h-3 w-3 animate-spin" />
                              Processing...
                            </span>
                          ) : (
                            'Redacted'
                          )}
                        </TabsTrigger>
                      </TabsList>
                      <TabsContent value="original" className="mt-3">
                        <div className="relative rounded-lg overflow-hidden border border-border bg-muted/30">
                          <img
                            src={`${VECTOR_STORE_URL}/api/image/serve/${selectedFullDoc.imageId}?context=user`}
                            alt={selectedFullDoc.caption || selectedFullDoc.filename}
                            className="max-w-full h-auto mx-auto"
                            style={{ maxHeight: '50vh' }}
                          />
                        </div>
                      </TabsContent>
                      <TabsContent value="redacted" className="mt-3">
                        <div className="relative rounded-lg overflow-hidden border border-border bg-muted/30">
                          <img
                            src={`${VECTOR_STORE_URL}/api/image/serve/${selectedFullDoc.imageId}?context=llm`}
                            alt={`Redacted: ${selectedFullDoc.caption || selectedFullDoc.filename}`}
                            className="max-w-full h-auto mx-auto"
                            style={{ maxHeight: '50vh' }}
                          />
                          {selectedFullDoc.hasPii && (
                            <div className="absolute top-2 right-2">
                              <Badge variant="outline" className="bg-background/80 text-warning gap-1">
                                <ShieldAlert className="h-3 w-3" />
                                PII Redacted
                              </Badge>
                            </div>
                          )}
                        </div>
                      </TabsContent>
                    </Tabs>

                    {/* Image metadata */}
                    <div className="space-y-3">
                      {selectedFullDoc.caption && (
                        <div className="p-3 rounded-lg bg-muted/50 border border-border">
                          <p className="text-xs text-muted-foreground mb-1 font-medium">AI Caption</p>
                          <p className="text-sm">{selectedFullDoc.caption}</p>
                        </div>
                      )}
                      <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
                        {selectedFullDoc.width && selectedFullDoc.height && (
                          <Badge variant="outline">{selectedFullDoc.width} x {selectedFullDoc.height}</Badge>
                        )}
                        <Badge variant="outline" className="uppercase">{selectedFullDoc.extension}</Badge>
                        {selectedFullDoc.redactionPending ? (
                          <Badge variant="outline" className="text-muted-foreground gap-1">
                            <Loader2 className="h-3 w-3 animate-spin" />
                            Scanning for PII...
                          </Badge>
                        ) : selectedFullDoc.hasPii ? (
                          <Badge variant="outline" className="text-warning gap-1">
                            <ShieldAlert className="h-3 w-3" />
                            PII Detected
                          </Badge>
                        ) : selectedFullDoc.redactionComplete ? (
                          <Badge variant="outline" className="text-success gap-1">
                            <Shield className="h-3 w-3" />
                            No PII
                          </Badge>
                        ) : null}
                      </div>
                      {selectedFullDoc.hasPii && selectedFullDoc.piiTypesFound && selectedFullDoc.piiTypesFound.length > 0 && (
                        <div className="flex flex-wrap gap-1">
                          <span className="text-xs text-muted-foreground">Redacted:</span>
                          {selectedFullDoc.piiTypesFound.map(type => (
                            <Badge key={type} variant="secondary" className="text-xs">{type}</Badge>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                </ScrollArea>
              ) : (
                /* Text / code / markdown documents */
                <ScrollArea className="flex-1">
                  <div className="p-4">
                    <Suspense fallback={<Loader2 className="h-6 w-6 animate-spin text-muted-foreground mx-auto" />}>
                      <DocumentContentViewer doc={selectedFullDoc} />
                    </Suspense>
                  </div>
                </ScrollArea>
              )
            ) : selectedNodeDetails ? (
              /* Non-document node details (topics, entities) */
              <ScrollArea className="flex-1">
                <div className="p-3 space-y-3">
                  {selectedNode && <p className="text-xs text-muted-foreground">{selectedNode.connectionCount} connections</p>}

                  {selectedNodeDetails.details.persons && selectedNodeDetails.details.persons.length > 0 && (
                    <div>
                      <h4 className="text-xs font-medium text-muted-foreground mb-1">People</h4>
                      <div className="flex flex-wrap gap-1">
                        {selectedNodeDetails.details.persons.map((person, i) => (
                          <Badge key={`${person}-${i}`} variant="outline" className="text-[10px]">{person}</Badge>
                        ))}
                      </div>
                    </div>
                  )}

                  {selectedNodeDetails.details.organizations && selectedNodeDetails.details.organizations.length > 0 && (
                    <div>
                      <h4 className="text-xs font-medium text-muted-foreground mb-1">Organizations</h4>
                      <div className="flex flex-wrap gap-1">
                        {selectedNodeDetails.details.organizations.map((org, i) => (
                          <Badge key={`${org}-${i}`} variant="outline" className="text-[10px]">{org}</Badge>
                        ))}
                      </div>
                    </div>
                  )}

                  {selectedNodeDetails.details.locations && selectedNodeDetails.details.locations.length > 0 && (
                    <div>
                      <h4 className="text-xs font-medium text-muted-foreground mb-1">Locations</h4>
                      <div className="flex flex-wrap gap-1">
                        {selectedNodeDetails.details.locations.map((loc, i) => (
                          <Badge key={`${loc}-${i}`} variant="outline" className="text-[10px]">{loc}</Badge>
                        ))}
                      </div>
                    </div>
                  )}

                  {selectedNodeDetails.details.technologies && selectedNodeDetails.details.technologies.length > 0 && (
                    <div>
                      <h4 className="text-xs font-medium text-muted-foreground mb-1">Technologies</h4>
                      <div className="flex flex-wrap gap-1">
                        {selectedNodeDetails.details.technologies.map((tech, i) => (
                          <Badge key={`${tech}-${i}`} variant="outline" className="text-[10px]">{tech}</Badge>
                        ))}
                      </div>
                    </div>
                  )}

                  {selectedNodeDetails.details.text && (
                    <div>
                      <h4 className="text-xs font-medium text-muted-foreground mb-1">Content</h4>
                      <div className="text-xs text-muted-foreground whitespace-pre-wrap bg-muted/50 rounded p-2">
                        {selectedNodeDetails.details.text}
                      </div>
                    </div>
                  )}

                  {selectedNodeDetails.details.sample_documents && selectedNodeDetails.details.sample_documents.length > 0 && (
                    <div>
                      <h4 className="text-xs font-medium text-muted-foreground mb-1">
                        Related Documents {selectedNodeDetails.details.document_count && `(${selectedNodeDetails.details.document_count} total)`}
                      </h4>
                      <div className="space-y-1">
                        {selectedNodeDetails.details.sample_documents.map((doc) => (
                          <div
                            key={doc.id}
                            className="text-xs text-muted-foreground bg-muted/50 rounded px-2 py-1 cursor-pointer hover:bg-muted/80 transition-colors"
                            onClick={() => {
                              setViewingDocId(doc.id);
                              storeActions.setFileExplorerSelectedDocId(doc.id);
                              setSelectedNode(null);
                            }}
                          >
                            <div className="font-medium">{doc.title || `Document ${doc.id}`}</div>
                            {doc.text_preview && <div className="mt-0.5 line-clamp-2">{doc.text_preview}</div>}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </ScrollArea>
            ) : selectedNode?.preview ? (
              <ScrollArea className="flex-1 p-3">
                <p className="text-xs text-muted-foreground">{selectedNode.preview}</p>
              </ScrollArea>
            ) : null}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export function KnowledgeGraph() {
  return (
    <ReactFlowProvider>
      <KnowledgeGraphInner />
    </ReactFlowProvider>
  );
}
