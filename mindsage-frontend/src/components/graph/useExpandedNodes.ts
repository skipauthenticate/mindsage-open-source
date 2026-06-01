import { useState, useCallback, useMemo } from 'react';
import type { GraphNode, GraphEdge } from '@/types';

const ENTITY_TYPES = new Set(['person', 'organization', 'location', 'technology']);

/**
 * Manages progressive disclosure of topic and entity nodes.
 * Takes the FULL graph data (all nodes + edges) and computes which topic/entity IDs
 * should be visible based on which documents the user has expanded.
 */
export function useExpandedNodes(allNodes: GraphNode[], allEdges: GraphEdge[]) {
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());

  // Build doc -> entity mapping from full graph data
  const docEntityMap = useMemo(() => {
    const map = new Map<string, Set<string>>();
    const entityIds = new Set(allNodes.filter(n => ENTITY_TYPES.has(n.type)).map(n => n.id));
    const docIds = new Set(allNodes.filter(n => n.type === 'document').map(n => n.id));

    for (const edge of allEdges) {
      // doc -> entity
      if (docIds.has(edge.source) && entityIds.has(edge.target)) {
        const set = map.get(edge.source) || new Set();
        set.add(edge.target);
        map.set(edge.source, set);
      }
      // entity -> doc (reverse direction)
      if (entityIds.has(edge.source) && docIds.has(edge.target)) {
        const set = map.get(edge.target) || new Set();
        set.add(edge.source);
        map.set(edge.target, set);
      }
    }
    return map;
  }, [allNodes, allEdges]);

  // Build doc -> topic mapping from full graph data
  const docTopicMap = useMemo(() => {
    const map = new Map<string, Set<string>>();
    const topicIds = new Set(allNodes.filter(n => n.type === 'topic').map(n => n.id));
    const docIds = new Set(allNodes.filter(n => n.type === 'document').map(n => n.id));

    for (const edge of allEdges) {
      // topic -> doc (has_topic edges typically: source=topic, target=doc)
      if (topicIds.has(edge.source) && docIds.has(edge.target)) {
        const set = map.get(edge.target) || new Set();
        set.add(edge.source);
        map.set(edge.target, set);
      }
      // doc -> topic (reverse direction)
      if (docIds.has(edge.source) && topicIds.has(edge.target)) {
        const set = map.get(edge.source) || new Set();
        set.add(edge.target);
        map.set(edge.source, set);
      }
    }
    return map;
  }, [allNodes, allEdges]);

  // Focus on a doc, or unfocus if clicking the same one
  const focusOn = useCallback((nodeId: string) => {
    setExpandedIds(prev => prev.has(nodeId) ? new Set() : new Set([nodeId]));
  }, []);

  const collapseAll = useCallback(() => {
    setExpandedIds(new Set());
  }, []);

  // Compute the set of entity IDs that should be visible due to expansion
  const expandedEntityIds = useMemo(() => {
    const ids = new Set<string>();
    for (const docId of expandedIds) {
      const entities = docEntityMap.get(docId);
      if (entities) {
        for (const eid of entities) ids.add(eid);
      }
    }
    return ids;
  }, [expandedIds, docEntityMap]);

  // Compute the set of topic IDs that should be visible due to expansion
  const expandedTopicIds = useMemo(() => {
    const ids = new Set<string>();
    for (const docId of expandedIds) {
      const topics = docTopicMap.get(docId);
      if (topics) {
        for (const tid of topics) ids.add(tid);
      }
    }
    return ids;
  }, [expandedIds, docTopicMap]);

  return {
    expandedIds,
    expandedEntityIds,
    expandedTopicIds,
    focusOn,
    collapseAll,
    hasExpanded: expandedIds.size > 0,
  };
}
