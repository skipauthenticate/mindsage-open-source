import { memo } from 'react';
import { Handle, Position } from '@xyflow/react';
import { User, Building, MapPin, Cpu } from 'lucide-react';
import type { GraphNode, NodeType } from '@/types';

const entityIcons: Partial<Record<NodeType, typeof User>> = {
  person: User,
  organization: Building,
  location: MapPin,
  technology: Cpu,
};

interface EntityPillNodeData extends GraphNode {
  selected?: boolean;
  highlighted?: boolean;
  dimmed?: boolean;
}

function EntityPillNode({ data }: { data: EntityPillNodeData }) {
  const Icon = entityIcons[data.type] || Cpu;

  return (
    <div
      className={`
        inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-full border bg-card/80 shadow-sm transition-all duration-200 max-w-[140px]
        ${data.selected ? 'ring-2 ring-primary border-primary' : 'border-border'}
        ${data.highlighted ? 'shadow-md scale-105' : ''}
        ${data.dimmed ? 'opacity-40' : ''}
      `}
    >
      <Handle type="target" position={Position.Top} className="!bg-border !w-1 !h-1 !-top-0.5" />

      {/* Left and Right handles for manual connections */}
      <Handle
        type="source"
        position={Position.Left}
        id="left"
        className="!w-2 !h-2 !bg-card !border-2 !border-foreground/30 hover:!border-primary hover:!scale-110 !transition-all !cursor-crosshair !-left-1"
      />
      <Handle
        type="source"
        position={Position.Right}
        id="right"
        className="!w-2 !h-2 !bg-card !border-2 !border-foreground/30 hover:!border-primary hover:!scale-110 !transition-all !cursor-crosshair !-right-1"
      />

      <Icon className="h-3 w-3 text-muted-foreground shrink-0" />
      <span className="text-[11px] font-medium truncate">{data.label}</span>

      <Handle type="source" position={Position.Bottom} className="!bg-border !w-1 !h-1 !-bottom-0.5" />
    </div>
  );
}

export default memo(EntityPillNode);
