import { memo } from 'react';
import { Handle, Position } from '@xyflow/react';
import { Tag } from 'lucide-react';
import type { GraphNode } from '@/types';

interface TopicBadgeNodeData extends GraphNode {
  selected?: boolean;
  highlighted?: boolean;
  dimmed?: boolean;
}

function TopicBadgeNode({ data }: { data: TopicBadgeNodeData }) {
  return (
    <div
      className={`
        inline-flex items-center gap-2 px-4 py-2.5 rounded-full border bg-card shadow-sm transition-all duration-200
        ${data.selected ? 'ring-2 ring-primary border-primary' : 'border-foreground/20'}
        ${data.highlighted ? 'shadow-md scale-105' : ''}
        ${data.dimmed ? 'opacity-40' : ''}
      `}
    >
      <Handle type="target" position={Position.Top} className="!bg-border !w-1.5 !h-1.5 !-top-0.5" />

      {/* Left and Right handles for manual connections */}
      <Handle
        type="source"
        position={Position.Left}
        id="left"
        className="!w-2.5 !h-2.5 !bg-card !border-2 !border-foreground/30 hover:!border-primary hover:!scale-110 !transition-all !cursor-crosshair !-left-1"
      />
      <Handle
        type="source"
        position={Position.Right}
        id="right"
        className="!w-2.5 !h-2.5 !bg-card !border-2 !border-foreground/30 hover:!border-primary hover:!scale-110 !transition-all !cursor-crosshair !-right-1"
      />

      <Tag className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
      <span className="text-xs font-semibold whitespace-nowrap max-w-[120px] truncate">
        {data.label}
      </span>
      {data.docCount !== null && data.docCount !== undefined && data.docCount > 0 && (
        <span className="text-[10px] text-muted-foreground bg-muted rounded-full px-1.5 py-0.5 font-medium">
          {data.docCount}
        </span>
      )}

      <Handle type="source" position={Position.Bottom} className="!bg-border !w-1.5 !h-1.5 !-bottom-0.5" />
    </div>
  );
}

export default memo(TopicBadgeNode);
