import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Progress } from '@/components/ui/progress';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog';
import {
  AlertTriangle,
  Bug,
  ChevronDown,
  ChevronUp,
  Cpu,
  HardDrive,
  Layers,
  RefreshCw,
  Server,
  Trash2,
  Zap,
} from 'lucide-react';

export function DebugPanel() {
  const [isOpen, setIsOpen] = useState(false);
  const queryClient = useQueryClient();

  const clearAllMutation = useMutation({
    mutationFn: api.clearAllData,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['debugInfo'] });
      queryClient.invalidateQueries({ queryKey: ['documents'] });
      queryClient.invalidateQueries({ queryKey: ['files'] });
      queryClient.invalidateQueries({ queryKey: ['stats'] });
      refetch();
    },
  });

  const { data: debugInfo, refetch, isLoading, isError } = useQuery({
    queryKey: ['debugInfo'],
    queryFn: api.getDebugInfo,
    refetchInterval: (query) => {
      if (!isOpen) return false;
      return query.state.data?.extraction_queue?.current ? 1000 : 5000;
    },
    enabled: isOpen,
  });

  if (!isOpen) {
    return (
      <Button
        variant="outline"
        size="sm"
        onClick={() => setIsOpen(true)}
        className="fixed bottom-4 right-4 z-50 gap-2 bg-background/95 backdrop-blur-sm shadow-lg"
      >
        <Bug className="h-4 w-4" />
        Debug
      </Button>
    );
  }

  return (
    <div className="fixed bottom-4 right-4 z-50 w-80 bg-card/95 backdrop-blur-sm border border-border rounded-lg shadow-xl">
      <div className="flex items-center justify-between p-3 border-b border-border">
        <div className="flex items-center gap-2">
          <Bug className="h-4 w-4 text-muted-foreground" />
          <span className="font-medium text-sm">Debug Panel</span>
        </div>
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="icon"
            className="h-6 w-6"
            onClick={() => refetch()}
            disabled={isLoading}
            aria-label="Refresh debug info"
          >
            <RefreshCw className={`h-3 w-3 ${isLoading ? 'animate-spin' : ''}`} />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-6 w-6"
            onClick={() => setIsOpen(false)}
            aria-label="Collapse debug panel"
          >
            <ChevronDown className="h-4 w-4" />
          </Button>
        </div>
      </div>

      <div className="max-h-[60vh] overflow-y-auto">
        <div className="p-3 space-y-4">
          {isError ? (
            <div className="text-sm text-destructive">Failed to load debug info</div>
          ) : !debugInfo ? (
            <div className="text-sm text-muted-foreground">Loading...</div>
          ) : (
            <>
              {/* System Memory */}
              {debugInfo.system_memory && (
              <div className="space-y-2">
                <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
                  <HardDrive className="h-3 w-3" />
                  System Memory
                </div>
                <div className="space-y-1">
                  <div className="flex justify-between text-xs">
                    <span>Used</span>
                    <span>{debugInfo.system_memory.used_mb?.toFixed(0) ?? '?'} / {debugInfo.system_memory.total_mb?.toFixed(0) ?? '?'} MB</span>
                  </div>
                  <Progress value={debugInfo.system_memory.percent_used ?? 0} className="h-1.5" />
                  <div className="flex justify-between text-[10px] text-muted-foreground">
                    <span>Available: {debugInfo.system_memory.available_mb?.toFixed(0) ?? '?'} MB</span>
                    <span>{debugInfo.system_memory.percent_used?.toFixed(1) ?? '?'}%</span>
                  </div>
                </div>
              </div>
              )}

              {/* Swap */}
              {debugInfo.swap && debugInfo.swap.total_mb > 0 && (
                <div className="space-y-2">
                  <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
                    <Layers className="h-3 w-3" />
                    Swap
                  </div>
                  <div className="space-y-1">
                    <div className="flex justify-between text-xs">
                      <span>Used</span>
                      <span>{debugInfo.swap.used_mb?.toFixed(0) ?? '?'} / {debugInfo.swap.total_mb?.toFixed(0) ?? '?'} MB</span>
                    </div>
                    <Progress value={debugInfo.swap.percent_used ?? 0} className="h-1.5" />
                  </div>
                </div>
              )}

              {/* GPU */}
              {debugInfo.gpu && (
              <div className="space-y-2">
                <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
                  <Cpu className="h-3 w-3" />
                  GPU (CUDA)
                </div>
                {debugInfo.gpu.cuda_available ? (
                  <div className="space-y-1 text-xs">
                    <div className="text-muted-foreground">{debugInfo.gpu.device_name}</div>
                    <div className="flex justify-between">
                      <span>Allocated</span>
                      <span>{debugInfo.gpu.memory_allocated_mb?.toFixed(1) ?? '?'} MB</span>
                    </div>
                    <div className="flex justify-between">
                      <span>Reserved</span>
                      <span>{debugInfo.gpu.memory_reserved_mb?.toFixed(1) ?? '?'} MB</span>
                    </div>
                    <div className="flex justify-between text-muted-foreground">
                      <span>Peak</span>
                      <span>{debugInfo.gpu.max_memory_allocated_mb?.toFixed(1) ?? '?'} MB</span>
                    </div>
                  </div>
                ) : (
                  <div className="text-xs text-muted-foreground">
                    {debugInfo.gpu.error || 'CUDA not available'}
                  </div>
                )}
              </div>
              )}

              {/* OOM Error Banner */}
              {debugInfo.models?.status && Object.values(debugInfo.models.status).some((s: any) => s?.error?.startsWith('OOM:')) && (
                <div className="p-2 rounded-md bg-destructive/10 border border-destructive/20">
                  <div className="flex items-center gap-2 text-xs font-medium text-destructive">
                    <AlertTriangle className="h-3 w-3 shrink-0" />
                    GPU Out of Memory
                  </div>
                  <div className="text-[10px] text-destructive/80 mt-1">
                    {Object.entries(debugInfo.models.status)
                      .filter(([, s]: [string, any]) => s?.error?.startsWith('OOM:'))
                      .map(([name]: [string, any]) => name)
                      .join(', ')} failed to load. Close other apps to free memory, then restart the vector store.
                  </div>
                </div>
              )}

              {/* Models */}
              {debugInfo.models && (
              <div className="space-y-2">
                <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
                  <Zap className="h-3 w-3" />
                  Models
                </div>
                <div className="space-y-1">
                  {debugInfo.models.status && Object.entries(debugInfo.models.status).map(([name, status]: [string, any]) => (
                    <div key={name}>
                      <div className="flex items-center justify-between">
                        <span className="text-xs capitalize">{name}</span>
                        <div className="flex items-center gap-1">
                          {status?.error ? (
                            <Badge
                              variant="destructive"
                              className="text-[10px] h-4 px-1"
                            >
                              {status.error.startsWith('OOM:') ? 'OOM' : 'Error'}
                            </Badge>
                          ) : (
                            <Badge
                              variant={status?.is_loaded ? 'default' : 'secondary'}
                              className="text-[10px] h-4 px-1"
                            >
                              {status?.is_loaded ? 'Loaded' : 'Unloaded'}
                            </Badge>
                          )}
                          {status?.on_gpu && !status?.error && (
                            <Badge variant="outline" className="text-[10px] h-4 px-1">
                              GPU
                            </Badge>
                          )}
                        </div>
                      </div>
                      {status?.error && (
                        <div className="text-[10px] text-destructive/80 mt-0.5 break-words leading-tight">
                          {status.error.startsWith('OOM:') ? status.error.slice(5) : status.error}
                        </div>
                      )}
                    </div>
                  ))}
                  {debugInfo.models.current_gpu_model && (
                    <div className="text-[10px] text-muted-foreground mt-1">
                      Active GPU model: {debugInfo.models.current_gpu_model}
                    </div>
                  )}
                </div>
              </div>
              )}

              {/* Process & Vector Store */}
              <div className="space-y-2">
                <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
                  <Server className="h-3 w-3" />
                  Vector Store Process
                </div>
                <div className="grid grid-cols-2 gap-2 text-xs">
                  <div className="bg-muted/50 rounded px-2 py-1">
                    <div className="text-[10px] text-muted-foreground">Process Memory</div>
                    <div>{debugInfo.process_memory?.rss_mb?.toFixed(0) ?? '?'} MB</div>
                  </div>
                  <div className="bg-muted/50 rounded px-2 py-1">
                    <div className="text-[10px] text-muted-foreground">Documents</div>
                    <div>{debugInfo.vector_store?.total_documents ?? '?'}</div>
                  </div>
                  <div className="bg-muted/50 rounded px-2 py-1">
                    <div className="text-[10px] text-muted-foreground">PII Protection</div>
                    <div>{debugInfo.pii_protection?.available ? 'Active' : 'Off'}</div>
                  </div>
                  <div className="bg-muted/50 rounded px-2 py-1">
                    <div className="text-[10px] text-muted-foreground">Extraction Queue</div>
                    <div>{debugInfo.extraction_queue?.pending ?? '?'}</div>
                  </div>
                </div>
              </div>

              {/* Extraction Activity */}
              {debugInfo.extraction_queue?.current && (
                <div className="p-2 rounded-md bg-blue-500/10 border border-blue-500/20">
                  <div className="flex items-center gap-2 text-xs font-medium text-blue-600 dark:text-blue-400">
                    <Zap className="h-3 w-3 animate-pulse" />
                    Extracting Doc #{debugInfo.extraction_queue.current.doc_id}
                  </div>
                  <div className="mt-1.5 space-y-1">
                    {['passages', 'entities', 'metadata', 'filters', 'topics', 'saving'].map((stage) => {
                      const currentStage = debugInfo.extraction_queue?.current?.stage;
                      const stageDevices = debugInfo.extraction_queue?.stage_devices ?? {};
                      const device = stageDevices[stage] ?? 'CPU';
                      const isActive = currentStage === stage;
                      const stageOrder = ['passages', 'entities', 'metadata', 'filters', 'topics', 'saving'];
                      const isDone = currentStage ? stageOrder.indexOf(stage) < stageOrder.indexOf(currentStage) : false;

                      return (
                        <div key={stage} className="flex items-center justify-between text-[10px]">
                          <div className="flex items-center gap-1.5">
                            <span className={`inline-block w-1.5 h-1.5 rounded-full ${
                              isActive ? 'bg-blue-500 animate-pulse' :
                              isDone ? 'bg-green-500' :
                              'bg-muted-foreground/30'
                            }`} />
                            <span className={isActive ? 'text-blue-600 dark:text-blue-400 font-medium' : isDone ? 'text-muted-foreground' : 'text-muted-foreground/70'}>
                              {stage}
                            </span>
                          </div>
                          <Badge
                            variant="outline"
                            className={`text-[9px] h-3.5 px-1 ${
                              isActive
                                ? device === 'GPU'
                                  ? 'border-green-500/50 text-green-600 dark:text-green-400'
                                  : 'border-muted-foreground/30 text-muted-foreground'
                                : 'border-transparent text-muted-foreground/70'
                            }`}
                          >
                            {device}
                          </Badge>
                        </div>
                      );
                    })}
                  </div>
                  {debugInfo.extraction_queue.current.filename && (
                    <div className="text-[10px] text-muted-foreground mt-1.5 truncate">
                      {debugInfo.extraction_queue.current.filename}
                    </div>
                  )}
                  {(debugInfo.extraction_queue?.pending ?? 0) > 0 && (
                    <div className="text-[10px] text-muted-foreground mt-0.5">
                      +{debugInfo.extraction_queue.pending} queued
                    </div>
                  )}
                </div>
              )}

              {/* Memory-Constrained Extraction Status */}
              {debugInfo.extraction_queue?.memory_constrained && (
                <div className="p-2 rounded-md bg-yellow-500/10 border border-yellow-500/20">
                  <div className="flex items-center gap-2 text-xs font-medium text-yellow-600 dark:text-yellow-400">
                    <Cpu className="h-3 w-3" />
                    Waiting for GPU Memory
                  </div>
                  <div className="text-[10px] text-yellow-600/80 dark:text-yellow-400/80 mt-1">
                    {`${debugInfo.extraction_queue?.pending ?? 0} files pending extraction`}
                    {debugInfo.extraction_queue?.min_required_mb && (
                      <span className="block mt-0.5">
                        Need {debugInfo.extraction_queue.min_required_mb} MB free
                      </span>
                    )}
                  </div>
                </div>
              )}

              {/* Clear All Data */}
              <div className="pt-2 border-t border-border">
                <AlertDialog>
                  <AlertDialogTrigger asChild>
                    <Button
                      variant="destructive"
                      size="sm"
                      className="w-full gap-2"
                      disabled={clearAllMutation.isPending}
                    >
                      <Trash2 className="h-3 w-3" />
                      {clearAllMutation.isPending ? 'Clearing...' : 'Clear All Data'}
                    </Button>
                  </AlertDialogTrigger>
                  <AlertDialogContent>
                    <AlertDialogHeader>
                      <AlertDialogTitle>Clear all data?</AlertDialogTitle>
                      <AlertDialogDescription>
                        This will permanently delete all vector store documents, uploaded files, and imports. This action cannot be undone.
                      </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                      <AlertDialogCancel>Cancel</AlertDialogCancel>
                      <AlertDialogAction
                        onClick={() => clearAllMutation.mutate()}
                        className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                      >
                        Delete Everything
                      </AlertDialogAction>
                    </AlertDialogFooter>
                  </AlertDialogContent>
                </AlertDialog>
                {clearAllMutation.isSuccess && (
                  <div className="text-[10px] text-muted-foreground mt-1 text-center">
                    Cleared {clearAllMutation.data?.vectorStore?.deleted ?? 0} docs, {clearAllMutation.data?.filesDeleted ?? 0} files
                  </div>
                )}
                {clearAllMutation.isError && (
                  <div className="text-[10px] text-destructive mt-1 text-center">
                    {String(clearAllMutation.error)}
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
