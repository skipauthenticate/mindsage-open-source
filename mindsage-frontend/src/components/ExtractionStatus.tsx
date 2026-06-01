import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { Loader2, AlertTriangle, Check, FileText } from 'lucide-react';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { cn } from '@/lib/utils';

export function ExtractionStatus() {
  const { data: debugInfo } = useQuery({
    queryKey: ['extractionStatus'],
    queryFn: api.getDebugInfo,
    // Only poll while there's pending work; do a slow check otherwise to detect new work
    refetchInterval: (query) => {
      const pending = query.state.data?.extraction_queue?.pending ?? 0;
      const constrained = query.state.data?.extraction_queue?.memory_constrained ?? false;
      return (pending > 0 || constrained) ? 3000 : 30000;
    },
    staleTime: 2000,
  });

  const extractionQueue = debugInfo?.extraction_queue;

  // Don't show anything if no pending tasks and not memory constrained
  if (!extractionQueue || (extractionQueue.pending === 0 && !extractionQueue.memory_constrained)) {
    return null;
  }

  const isMemoryConstrained = extractionQueue.memory_constrained;
  const pendingCount = extractionQueue.pending;

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <div
          className={cn(
            "flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium transition-colors cursor-default",
            isMemoryConstrained
              ? "bg-yellow-500/15 text-yellow-600 dark:text-yellow-400 border border-yellow-500/30"
              : "bg-primary/10 text-primary border border-primary/20"
          )}
        >
          {isMemoryConstrained ? (
            <>
              <AlertTriangle className="h-3 w-3" />
              <span>{pendingCount} waiting</span>
            </>
          ) : (
            <>
              <Loader2 className="h-3 w-3 animate-spin" />
              <span>Processing {pendingCount}</span>
            </>
          )}
        </div>
      </TooltipTrigger>
      <TooltipContent side="bottom" className="max-w-xs">
        {isMemoryConstrained ? (
          <div className="space-y-1">
            <p className="font-medium text-yellow-600 dark:text-yellow-400">
              Waiting for GPU Memory
            </p>
            <p className="text-muted-foreground">
              {pendingCount} file{pendingCount !== 1 ? 's' : ''} queued for metadata extraction.
              Processing will resume when memory becomes available.
            </p>
            <p className="text-[10px] text-muted-foreground/70">
              Need {extractionQueue.min_required_mb}MB free to load TinyLlama
            </p>
          </div>
        ) : (
          <div className="space-y-1">
            <p className="font-medium">Extracting Metadata</p>
            <p className="text-muted-foreground">
              Processing {pendingCount} file{pendingCount !== 1 ? 's' : ''} in background.
              Documents are searchable immediately.
            </p>
          </div>
        )}
      </TooltipContent>
    </Tooltip>
  );
}
