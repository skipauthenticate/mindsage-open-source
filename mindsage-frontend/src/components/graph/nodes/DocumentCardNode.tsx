import { memo } from 'react';
import { Handle, Position } from '@xyflow/react';
import { FileText } from 'lucide-react';
import type { GraphNode } from '@/types';

const TOPIC_COLORS = [
  'bg-blue-500/15 text-blue-700 dark:text-blue-300',
  'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300',
  'bg-amber-500/15 text-amber-700 dark:text-amber-300',
  'bg-purple-500/15 text-purple-700 dark:text-purple-300',
  'bg-rose-500/15 text-rose-700 dark:text-rose-300',
  'bg-cyan-500/15 text-cyan-700 dark:text-cyan-300',
];

function hashColor(str: string): string {
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    hash = str.charCodeAt(i) + ((hash << 5) - hash);
  }
  return TOPIC_COLORS[Math.abs(hash) % TOPIC_COLORS.length];
}

interface DocumentCardNodeData extends GraphNode {
  selected?: boolean;
  highlighted?: boolean;
  dimmed?: boolean;
  expanded?: boolean;
  pulseHighlight?: boolean;
}

function DocumentCardNode({ data }: { data: DocumentCardNodeData }) {
  const topics = data.topics || [];
  const displayTopics = topics.slice(0, 3);
  const overflow = topics.length - 3;

  return (
    <div
      className={`
        w-[280px] rounded-xl border bg-card shadow-md transition-all duration-200
        ${data.selected ? 'ring-2 ring-primary border-primary shadow-lg' : 'border-border'}
        ${data.highlighted ? 'shadow-lg scale-[1.02]' : ''}
        ${data.dimmed ? 'opacity-40' : ''}
        ${data.expanded ? 'ring-1 ring-primary/50' : ''}
        ${data.pulseHighlight ? 'ring-2 ring-primary animate-pulse' : ''}
      `}
    >
      <Handle type="target" position={Position.Top} className="!bg-border !w-2 !h-2 !-top-1" />

      {/* Left and Right handles for manual connections */}
      <Handle
        type="source"
        position={Position.Left}
        id="left"
        className="!w-3 !h-3 !bg-card !border-2 !border-foreground/30 hover:!border-primary hover:!scale-110 !transition-all !cursor-crosshair !-left-1.5"
      />
      <Handle
        type="source"
        position={Position.Right}
        id="right"
        className="!w-3 !h-3 !bg-card !border-2 !border-foreground/30 hover:!border-primary hover:!scale-110 !transition-all !cursor-crosshair !-right-1.5"
      />

      <div className="p-3.5">
        {/* Title row */}
        <div className="flex items-start gap-2 mb-2">
          <div className="mt-0.5 p-1 rounded bg-foreground/5 shrink-0">
            <FileText className="h-3.5 w-3.5 text-muted-foreground" />
          </div>
          <h3 className="text-sm font-medium leading-tight line-clamp-2 min-w-0">
            {data.label}
          </h3>
        </div>

        {/* Preview text */}
        {data.preview && (
          <p className="text-xs text-muted-foreground line-clamp-2 mb-2.5 leading-relaxed">
            {data.preview}
          </p>
        )}

        {/* Topic badges row with connection count */}
        <div className="flex items-center justify-between gap-2">
          {displayTopics.length > 0 && (
            <div className="flex flex-wrap gap-1 flex-1">
              {displayTopics.map((topic) => (
                <span
                  key={topic}
                  className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium ${hashColor(topic)}`}
                >
                  {topic}
                </span>
              ))}
              {overflow > 0 && (
                <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-muted text-muted-foreground">
                  +{overflow}
                </span>
              )}
            </div>
          )}
          {data.connectionCount > 0 && (
            <span className="text-[11px] text-muted-foreground ml-auto shrink-0">
              {data.connectionCount} connections
            </span>
          )}
        </div>
      </div>

      <Handle type="source" position={Position.Bottom} className="!bg-border !w-2 !h-2 !-bottom-1" />
    </div>
  );
}

export default memo(DocumentCardNode);
