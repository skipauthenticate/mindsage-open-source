import { useState, useEffect, type ComponentType, type SVGProps } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Monitor,
  RefreshCw,
  Square,
  Loader2,
  Circle,
  ChevronDown,
  Trash2,
  MessageSquare,
  Clock,
  Check,
  Copy,
  ExternalLink,
  LogIn,
  Zap,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Switch } from '@/components/ui/switch';
import { Label } from '@/components/ui/label';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Slider } from '@/components/ui/slider';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
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
import { useToast } from '@/hooks/use-toast';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  api,
  type SupportedSite,
} from '@/lib/api';
import { copyToClipboard, formatRelativeTime } from '@/lib/utils';

export interface AIConnectorDialogProps {
  isOpen: boolean;
  onClose: () => void;
  onConnect: () => void;
  site: SupportedSite;
  Icon: ComponentType<SVGProps<SVGSVGElement> & { className?: string }>;
}

export function AIConnectorDialog({ isOpen, onClose, onConnect, site, Icon }: AIConnectorDialogProps) {
  const [isConversationsOpen, setIsConversationsOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const [showVncPassword, setShowVncPassword] = useState(false);
  const [syncInterval, setSyncInterval] = useState<number | null>(null);
  const { toast } = useToast();
  const queryClient = useQueryClient();

  // Fetch site data from API
  const { data: sitesData } = useQuery({
    queryKey: ['browserSites'],
    queryFn: api.getSites,
    enabled: isOpen,
    staleTime: 60000,
  });

  const siteInfo = sitesData?.sites.find(s => s.id === site);
  const siteName = siteInfo?.name || site;
  const siteUrl = siteInfo?.url || '';

  // Query auth status for this site
  const { data: authStatus, refetch: refetchAuth } = useQuery({
    queryKey: ['browserAuthStatus', site],
    queryFn: () => api.getAuthStatus(site),
    enabled: isOpen,
    staleTime: 5000,
  });

  // Query auto-sync status
  const { data: autoSyncStatus, refetch: refetchAutoSync } = useQuery({
    queryKey: ['autoSyncStatus'],
    queryFn: api.getAutoSyncStatus,
    enabled: isOpen,
    refetchInterval: 30000,
    staleTime: 5000,
  });

  // Sync local slider state with API data
  useEffect(() => {
    if (autoSyncStatus?.intervalHours && syncInterval === null) {
      setSyncInterval(autoSyncStatus.intervalHours);
    }
  }, [autoSyncStatus?.intervalHours, syncInterval]);

  // Refetch all data when dialog opens
  useEffect(() => {
    if (isOpen) {
      refetchAuth();
      refetchAutoSync();
      refetchBrowser();
      refetchConversations();
      // Reset slider to sync with fresh data
      setSyncInterval(null);
    }
  }, [isOpen, refetchAuth, refetchAutoSync, refetchBrowser, refetchConversations]);

  // Query browser status
  const { data: browserStatus, refetch: refetchBrowser } = useQuery({
    queryKey: ['browserConnectorStatus'],
    queryFn: api.getBrowserConnectorStatus,
    enabled: isOpen,
    refetchInterval: (query) => (query.state.data?.running ? 5000 : 30000),
  });

  // Query conversations for this site
  const { data: conversationsData, refetch: refetchConversations } = useQuery({
    queryKey: ['capturedConversations', site],
    queryFn: () => api.getCapturedConversations({ site, limit: 10 }),
    enabled: isOpen,
  });

  // Query VNC availability
  const { data: vncCheck } = useQuery({
    queryKey: ['vncCheck'],
    queryFn: api.checkVncAvailable,
    enabled: isOpen,
    staleTime: 60000,
  });

  // Query server info for IP
  const { data: serverInfo } = useQuery({
    queryKey: ['serverInfo'],
    queryFn: api.getServerInfo,
    enabled: isOpen,
    staleTime: 60000,
  });

  // Launch VNC browser for this site
  const launchVncMutation = useMutation({
    mutationFn: () => api.launchBrowser({ vnc: true, startUrl: siteUrl }),
    onSuccess: () => {
      refetchBrowser();
      toast({ title: 'Browser launched', description: `Connect via VNC to log in to ${siteName}` });
    },
    onError: (error) => {
      toast({ variant: 'destructive', title: 'Failed to launch', description: String(error) });
    },
  });

  // Navigate to this site in existing VNC session
  const navigateToSiteMutation = useMutation({
    mutationFn: () => api.navigateToSite(site, false),
    onSuccess: () => {
      toast({ title: 'Navigating', description: `Opening ${siteName} in browser` });
    },
    onError: (error) => {
      toast({ variant: 'destructive', title: 'Failed to navigate', description: String(error) });
    },
  });

  // Close browser
  const closeBrowserMutation = useMutation({
    mutationFn: api.closeBrowser,
    onSuccess: () => {
      refetchBrowser();
      refetchAuth();
      toast({ title: 'Browser closed' });
    },
    onError: (error) => {
      toast({ variant: 'destructive', title: 'Failed to close browser', description: String(error) });
    },
  });

  // Manual sync for this site
  const syncMutation = useMutation({
    mutationFn: () => api.triggerSync(site),
    onSuccess: (result) => {
      refetchAutoSync();
      refetchConversations();
      queryClient.invalidateQueries({ queryKey: ['connectors'] });
      if (result.success) {
        toast({
          title: 'Sync complete',
          description: `Synced ${result.synced} conversations from ${siteName}`,
        });
        onConnect();
      } else {
        toast({
          variant: 'destructive',
          title: 'Sync failed',
          description: result.error,
        });
      }
    },
    onError: (error) => {
      toast({ variant: 'destructive', title: 'Sync failed', description: String(error) });
    },
  });

  // Start auto-sync
  const startAutoSyncMutation = useMutation({
    mutationFn: (hours: number) => api.startAutoSync(hours),
    onSuccess: (_, hours) => {
      refetchAutoSync();
      toast({ title: 'Auto-sync enabled', description: `Will sync every ${hours} hours` });
    },
  });

  // Stop auto-sync
  const stopAutoSyncMutation = useMutation({
    mutationFn: api.stopAutoSync,
    onSuccess: () => {
      refetchAutoSync();
      toast({ title: 'Auto-sync disabled' });
    },
  });

  // Delete conversation
  const deleteMutation = useMutation({
    mutationFn: api.deleteCapturedConversation,
    onSuccess: () => {
      refetchConversations();
      toast({ title: 'Conversation deleted' });
    },
  });

  // Reindex
  const reindexMutation = useMutation({
    mutationFn: api.reindexCapturedConversations,
    onSuccess: (result) => {
      refetchConversations();
      toast({
        title: 'Re-indexing complete',
        description: `${result.success_count} conversations indexed`,
      });
    },
  });

  const conversations = conversationsData?.conversations || [];
  const isAuthenticated = authStatus?.authenticated;
  const isBrowserRunning = browserStatus?.running;
  const isVncEnabled = browserStatus?.vnc?.enabled;

  // VNC URL for remote access
  const wsPort = browserStatus?.vnc?.wsPort || 6080;
  const serverIp = serverInfo?.ipAddress;
  const frontendPort = typeof window !== 'undefined' ? (window.location.port || '8080') : '8080';
  const vncViewerUrl = serverIp ? `http://${serverIp}:${frontendPort}/vnc?host=${serverIp}&port=${wsPort}` : null;

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-muted">
              <Icon className="h-4 w-4" />
            </div>
            {siteName} Connector
          </DialogTitle>
          <DialogDescription>
            Automatically sync your {siteName} conversations
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          {/* Auth Status */}
          <div className="flex items-center justify-between p-3 rounded-lg bg-muted/50">
            <div className="flex items-center gap-2">
              <LogIn className="h-4 w-4" />
              <span className="text-sm font-medium">Login Status</span>
            </div>
            <Badge variant={isAuthenticated ? 'default' : 'secondary'} className={isAuthenticated ? 'bg-green-500' : ''}>
              <Circle className={`h-2 w-2 mr-1 ${isAuthenticated ? 'fill-current' : ''}`} />
              {isAuthenticated ? 'Logged In' : 'Not Logged In'}
            </Badge>
          </div>

          {/* First-time login flow */}
          {!isAuthenticated && !isBrowserRunning && (
            <div className="space-y-3">
              {/* Primary: Companion Extension */}
              <div className="p-4 rounded-lg border border-blue-200 bg-blue-50 dark:border-blue-800 dark:bg-blue-950">
                <h4 className="font-medium text-sm mb-2">Setup with Companion Extension</h4>
                <p className="text-xs text-muted-foreground mb-3">
                  Install the MindSage Companion extension on your browser, then connect your {siteName} session:
                </p>
                <ol className="text-xs text-muted-foreground space-y-1 mb-3 list-decimal list-inside">
                  <li>Open the MindSage Companion extension popup</li>
                  <li>Enter this server URL:</li>
                </ol>
                {serverIp && (
                  <div className="bg-white dark:bg-gray-900 rounded-md p-2 mb-3">
                    <div className="flex items-center justify-between gap-2">
                      <code className="text-sm font-mono text-blue-700 dark:text-blue-300">http://{serverIp}:3003</code>
                      <Button
                        variant="outline"
                        size="sm"
                        className="h-7 px-2"
                        onClick={() => {
                          if (serverIp) {
                            copyToClipboard(`http://${serverIp}:3003`).then((ok) => {
                              if (ok) {
                                setCopied(true);
                                setTimeout(() => setCopied(false), 2000);
                              }
                            });
                          }
                        }}
                      >
                        {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
                      </Button>
                    </div>
                  </div>
                )}
                <ol className="text-xs text-muted-foreground space-y-1 list-decimal list-inside" start={3}>
                  <li>Click "Connect" next to {siteName}</li>
                </ol>
              </div>

              {/* Secondary: VNC Login (collapsible fallback) */}
              <Collapsible>
                <CollapsibleTrigger asChild>
                  <Button variant="ghost" className="w-full justify-between text-xs text-muted-foreground">
                    <span className="flex items-center gap-2">
                      <Monitor className="h-3 w-3" />
                      Advanced: Manual VNC Login
                    </span>
                    <ChevronDown className="h-3 w-3" />
                  </Button>
                </CollapsibleTrigger>
                <CollapsibleContent>
                  <div className="p-4 rounded-lg border border-orange-200 bg-orange-50 dark:border-orange-800 dark:bg-orange-950 mt-2">
                    <p className="text-xs text-muted-foreground mb-3">
                      Launch the browser in VNC mode to log into {siteName} directly on the device. This requires VNC dependencies and uses more RAM.
                    </p>
                    <Button
                      onClick={() => launchVncMutation.mutate()}
                      disabled={launchVncMutation.isPending || !vncCheck?.available}
                      size="sm"
                      className="w-full"
                    >
                      {launchVncMutation.isPending ? (
                        <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                      ) : (
                        <Monitor className="h-4 w-4 mr-2" />
                      )}
                      Launch VNC Login
                    </Button>
                    {vncCheck && !vncCheck.available && (
                      <p className="text-xs text-orange-600 mt-2">
                        Missing dependencies: {vncCheck.missing.join(', ')}
                      </p>
                    )}
                  </div>
                </CollapsibleContent>
              </Collapsible>
            </div>
          )}

          {/* VNC Browser Running - show option to navigate to this site */}
          {isBrowserRunning && isVncEnabled && (
            <div className="p-4 rounded-lg border border-blue-200 bg-blue-50 dark:border-blue-800 dark:bg-blue-950">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <Monitor className="h-4 w-4 text-blue-600" />
                  <span className="font-medium text-sm">VNC Browser Running</span>
                </div>
                <Badge
                  variant="secondary"
                  className="text-xs font-mono cursor-pointer select-none"
                  onClick={() => setShowVncPassword(!showVncPassword)}
                >
                  {showVncPassword ? 'pw: mindsage' : 'pw: ••••••'}
                </Badge>
              </div>

              {serverIp && (
                <div className="bg-white dark:bg-gray-900 rounded-md p-2 mb-3">
                  <p className="text-xs text-muted-foreground mb-1">Open on any device:</p>
                  <div className="flex items-center justify-between gap-2">
                    <code className="text-sm font-mono">{serverIp}:{frontendPort}/vnc</code>
                    <div className="flex gap-1">
                      <Button
                        variant="outline"
                        size="sm"
                        className="h-7 px-2"
                        onClick={() => {
                          if (vncViewerUrl) {
                            copyToClipboard(vncViewerUrl).then((ok) => {
                              if (ok) {
                                setCopied(true);
                                setTimeout(() => setCopied(false), 2000);
                              }
                            });
                          }
                        }}
                      >
                        {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        className="h-7 px-2"
                        onClick={() => vncViewerUrl && window.open(vncViewerUrl, '_blank')}
                      >
                        <ExternalLink className="h-3 w-3" />
                      </Button>
                    </div>
                  </div>
                </div>
              )}

              {/* Option to navigate to this site if not authenticated */}
              {!isAuthenticated && (
                <Button
                  variant="outline"
                  size="sm"
                  className="w-full mb-2"
                  onClick={() => navigateToSiteMutation.mutate()}
                  disabled={navigateToSiteMutation.isPending}
                >
                  {navigateToSiteMutation.isPending ? (
                    <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  ) : (
                    <Icon className="h-4 w-4 mr-2" />
                  )}
                  Navigate to {siteName}
                </Button>
              )}

              <Button
                variant="outline"
                size="sm"
                className="w-full"
                onClick={() => closeBrowserMutation.mutate()}
                disabled={closeBrowserMutation.isPending}
              >
                {closeBrowserMutation.isPending ? (
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                ) : (
                  <Square className="h-4 w-4 mr-2" />
                )}
                Close Browser
              </Button>
            </div>
          )}

          {/* Sync Controls (only when authenticated) */}
          {isAuthenticated && !isBrowserRunning && (
            <>
              {/* Manual Sync Button */}
              <div className="flex gap-2">
                <Button
                  onClick={() => syncMutation.mutate()}
                  disabled={syncMutation.isPending}
                  className="flex-1"
                >
                  {syncMutation.isPending ? (
                    <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  ) : (
                    <RefreshCw className="h-4 w-4 mr-2" />
                  )}
                  Sync Now
                </Button>
                <Button
                  variant="outline"
                  onClick={() => launchVncMutation.mutate()}
                  disabled={launchVncMutation.isPending}
                >
                  <Monitor className="h-4 w-4" />
                </Button>
              </div>

              {/* Auto-Sync Settings */}
              <div className="p-4 rounded-lg border">
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-2">
                    <Zap className="h-4 w-4" />
                    <Label htmlFor="autoSync" className="font-medium">Auto-Sync</Label>
                  </div>
                  <Switch
                    id="autoSync"
                    checked={autoSyncStatus?.enabled || false}
                    onCheckedChange={(checked) => {
                      if (checked) {
                        const interval = syncInterval ?? autoSyncStatus?.intervalHours ?? 5;
                        startAutoSyncMutation.mutate(interval);
                      } else {
                        stopAutoSyncMutation.mutate();
                      }
                    }}
                  />
                </div>

                {autoSyncStatus?.enabled && (
                  <div className="space-y-3">
                    <div className="flex items-center justify-between text-sm">
                      <span className="text-muted-foreground">Interval</span>
                      <span className="font-medium">{syncInterval ?? autoSyncStatus.intervalHours} hours</span>
                    </div>
                    <Slider
                      value={[syncInterval ?? autoSyncStatus.intervalHours]}
                      onValueChange={([value]) => setSyncInterval(value)}
                      onValueCommit={([value]) => {
                        api.setAutoSyncInterval(value).then(() => {
                          refetchAutoSync();
                          toast({ title: 'Interval updated', description: `Will sync every ${value} hours` });
                        }).catch(() => {
                          toast({ variant: 'destructive', title: 'Failed to update interval' });
                        });
                      }}
                      min={1}
                      max={24}
                      step={1}
                      className="w-full"
                    />
                    <div className="flex justify-between text-xs text-muted-foreground">
                      <span>1h</span>
                      <span>24h</span>
                    </div>
                  </div>
                )}

                {autoSyncStatus?.lastSyncAt && (
                  <div className="flex items-center justify-between text-sm mt-3 pt-3 border-t">
                    <span className="text-muted-foreground flex items-center gap-1">
                      <Clock className="h-3 w-3" />
                      Last sync
                    </span>
                    <span>{formatRelativeTime(autoSyncStatus.lastSyncAt)}</span>
                  </div>
                )}
              </div>
            </>
          )}

          {/* Capture Statistics */}
          <div className="grid grid-cols-3 gap-2 text-center">
            <div className="bg-muted/50 rounded-lg p-2">
              <div className="text-lg font-semibold">{conversationsData?.total ?? 0}</div>
              <div className="text-xs text-muted-foreground">Conversations</div>
            </div>
            <div className="bg-muted/50 rounded-lg p-2">
              <div className="text-lg font-semibold">
                {conversations.reduce((sum, c) => sum + c.messageCount, 0)}
              </div>
              <div className="text-xs text-muted-foreground">Messages</div>
            </div>
            <div className="bg-muted/50 rounded-lg p-2">
              <div className="text-xs font-medium">
                {formatRelativeTime(conversations[0]?.updatedAt)}
              </div>
              <div className="text-xs text-muted-foreground">Last capture</div>
            </div>
          </div>

          {/* Recent Conversations */}
          <Collapsible open={isConversationsOpen} onOpenChange={setIsConversationsOpen}>
            <CollapsibleTrigger asChild>
              <Button variant="ghost" className="w-full justify-between text-sm">
                <span className="flex items-center gap-2">
                  <MessageSquare className="h-4 w-4" />
                  Recent Conversations ({conversations.length})
                </span>
                <motion.div
                  animate={{ rotate: isConversationsOpen ? 180 : 0 }}
                  transition={{ duration: 0.2 }}
                >
                  <ChevronDown className="h-4 w-4" />
                </motion.div>
              </Button>
            </CollapsibleTrigger>
            <CollapsibleContent>
              <div className="mt-2 space-y-2">
                <div className="flex justify-end">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => reindexMutation.mutate()}
                    disabled={reindexMutation.isPending}
                  >
                    {reindexMutation.isPending ? (
                      <Loader2 className="h-3 w-3 mr-1 animate-spin" />
                    ) : (
                      <RefreshCw className="h-3 w-3 mr-1" />
                    )}
                    Re-index All
                  </Button>
                </div>
                <ScrollArea className="h-[180px]">
                  <AnimatePresence mode="popLayout">
                    {conversations.length === 0 ? (
                      <div className="text-center text-muted-foreground text-sm py-4">
                        No conversations captured yet
                      </div>
                    ) : (
                      conversations.map((conv) => (
                        <motion.div
                          key={conv.id}
                          initial={{ opacity: 0, y: -10 }}
                          animate={{ opacity: 1, y: 0 }}
                          exit={{ opacity: 0, y: -10 }}
                          className="flex items-center justify-between p-2 rounded-lg hover:bg-muted/50 group"
                        >
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2">
                              {conv.indexed && (
                                <Badge variant="secondary" className="text-xs bg-green-100 text-green-700">
                                  Indexed
                                </Badge>
                              )}
                            </div>
                            <p className="text-sm truncate mt-1">{conv.title || 'Untitled'}</p>
                            <p className="text-xs text-muted-foreground">
                              {conv.messageCount} messages
                            </p>
                          </div>
                          <AlertDialog>
                            <AlertDialogTrigger asChild>
                              <Button
                                variant="ghost"
                                size="sm"
                                className="opacity-0 group-hover:opacity-100 focus:opacity-100 transition-opacity"
                                aria-label="Delete conversation"
                              >
                                <Trash2 className="h-4 w-4 text-destructive" />
                              </Button>
                            </AlertDialogTrigger>
                            <AlertDialogContent>
                              <AlertDialogHeader>
                                <AlertDialogTitle>Delete conversation?</AlertDialogTitle>
                                <AlertDialogDescription>
                                  This will permanently remove "{conv.title || 'Untitled'}" and its indexed data.
                                </AlertDialogDescription>
                              </AlertDialogHeader>
                              <AlertDialogFooter>
                                <AlertDialogCancel>Cancel</AlertDialogCancel>
                                <AlertDialogAction
                                  onClick={() => deleteMutation.mutate(conv.id)}
                                  className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                                >
                                  Delete
                                </AlertDialogAction>
                              </AlertDialogFooter>
                            </AlertDialogContent>
                          </AlertDialog>
                        </motion.div>
                      ))
                    )}
                  </AnimatePresence>
                </ScrollArea>
              </div>
            </CollapsibleContent>
          </Collapsible>
        </div>
      </DialogContent>
    </Dialog>
  );
}
