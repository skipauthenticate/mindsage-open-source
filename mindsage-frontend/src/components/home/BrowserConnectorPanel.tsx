import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Globe,
  Play,
  Square,
  RefreshCw,
  ExternalLink,
  MessageSquare,
  Settings,
  Loader2,
  Circle,
  ChevronDown,
  Trash2,
  Monitor,
  Copy,
  Check,
} from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Switch } from '@/components/ui/switch';
import { Label } from '@/components/ui/label';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { ScrollArea } from '@/components/ui/scroll-area';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { useToast } from '@/hooks/use-toast';
import { copyToClipboard, formatRelativeTime } from '@/lib/utils';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  api,
  type BrowserConnectorStatus,
  type BrowserConnectorConfig,
  type CapturedConversationSummary,
  type SupportedSite,
  type VncCheckResult,
} from '@/lib/api';

interface Platform {
  id: SupportedSite;
  name: string;
  url: string;
  available: boolean;
  description: string;
}

const platforms: Platform[] = [
  {
    id: 'chatgpt',
    name: 'ChatGPT',
    url: 'https://chatgpt.com',
    available: true,
    description: 'OpenAI ChatGPT',
  },
  {
    id: 'claude',
    name: 'Claude',
    url: 'https://claude.ai',
    available: false,
    description: 'Anthropic Claude (coming soon)',
  },
  {
    id: 'gemini',
    name: 'Gemini',
    url: 'https://gemini.google.com',
    available: false,
    description: 'Google Gemini (coming soon)',
  },
];

const siteLabels: Record<SupportedSite, string> = {
  chatgpt: 'ChatGPT',
  claude: 'Claude',
  gemini: 'Gemini',
};

const siteUrls: Record<SupportedSite, string> = {
  chatgpt: 'https://chatgpt.com',
  claude: 'https://claude.ai',
  gemini: 'https://gemini.google.com',
};

export function BrowserConnectorPanel() {
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [isConversationsOpen, setIsConversationsOpen] = useState(false);
  const [selectedPlatform, setSelectedPlatform] = useState<SupportedSite>('chatgpt');
  const [vncMode, setVncMode] = useState(false);
  const [copied, setCopied] = useState(false);
  const { toast } = useToast();
  const queryClient = useQueryClient();

  // Query browser status
  const { data: status, refetch: refetchStatus } = useQuery({
    queryKey: ['browserConnectorStatus'],
    queryFn: api.getBrowserConnectorStatus,
    refetchInterval: (query) => (query.state.data?.running ? 5000 : 10000),
  });

  // Query config
  const { data: config, refetch: refetchConfig } = useQuery({
    queryKey: ['browserConnectorConfig'],
    queryFn: api.getBrowserConnectorConfig,
  });

  // Query conversations
  const { data: conversationsData, refetch: refetchConversations } = useQuery({
    queryKey: ['capturedConversations'],
    queryFn: () => api.getCapturedConversations({ limit: 10 }),
    refetchInterval: (query) => {
      // Poll faster when browser is running
      const browserStatus = queryClient.getQueryData<BrowserConnectorStatus>(['browserConnectorStatus']);
      return browserStatus?.running ? 10000 : 30000;
    },
  });

  // Query VNC availability
  const { data: vncCheck } = useQuery({
    queryKey: ['vncCheck'],
    queryFn: api.checkVncAvailable,
    staleTime: 60000, // Cache for 1 minute
  });

  // Query server info for IP address
  const { data: serverInfo } = useQuery({
    queryKey: ['serverInfo'],
    queryFn: api.getServerInfo,
    staleTime: 60000,
  });

  // Launch browser mutation
  const launchMutation = useMutation({
    mutationFn: ({ platform, useVnc }: { platform: SupportedSite; useVnc: boolean }) => {
      const platformConfig = platforms.find(p => p.id === platform);
      return api.launchBrowser({
        headed: config?.headed ?? true,
        startUrl: platformConfig?.url,
        vnc: useVnc,
      });
    },
    onSuccess: (data) => {
      refetchStatus();
      const platformName = platforms.find(p => p.id === selectedPlatform)?.name || selectedPlatform;
      const vncMessage = data.status.vnc?.enabled ? ' (VNC mode)' : '';
      toast({
        title: 'Browser launched',
        description: `Opening ${platformName}${vncMessage}...`,
      });
    },
    onError: (error) => {
      toast({
        variant: 'destructive',
        title: 'Failed to launch browser',
        description: String(error),
      });
    },
  });

  // Close browser mutation
  const closeMutation = useMutation({
    mutationFn: api.closeBrowser,
    onSuccess: () => {
      refetchStatus();
      toast({
        title: 'Browser closed',
        description: 'Browser session ended',
      });
    },
    onError: (error) => {
      toast({ variant: 'destructive', title: 'Failed to close browser', description: String(error) });
    },
  });

  // Navigate mutation
  const navigateMutation = useMutation({
    mutationFn: (url: string) => api.navigateBrowser(url),
    onSuccess: () => {
      refetchStatus();
    },
    onError: (error) => {
      toast({ variant: 'destructive', title: 'Navigation failed', description: String(error) });
    },
  });

  // Update config mutation
  const updateConfigMutation = useMutation({
    mutationFn: (updates: Partial<BrowserConnectorConfig>) => api.updateBrowserConnectorConfig(updates),
    onSuccess: () => {
      refetchConfig();
      toast({
        title: 'Settings saved',
        description: 'Browser connector settings updated',
      });
    },
    onError: (error) => {
      toast({ variant: 'destructive', title: 'Failed to save settings', description: String(error) });
    },
  });

  // Reindex mutation
  const reindexMutation = useMutation({
    mutationFn: api.reindexCapturedConversations,
    onSuccess: (result) => {
      refetchConversations();
      toast({
        title: 'Re-indexing complete',
        description: `${result.success_count} conversations indexed, ${result.failed} failed`,
      });
    },
    onError: (error) => {
      toast({ variant: 'destructive', title: 'Re-indexing failed', description: String(error) });
    },
  });

  // Delete conversation mutation
  const deleteMutation = useMutation({
    mutationFn: api.deleteCapturedConversation,
    onSuccess: () => {
      refetchConversations();
      toast({
        title: 'Conversation deleted',
      });
    },
    onError: (error) => {
      toast({ variant: 'destructive', title: 'Failed to delete conversation', description: String(error) });
    },
  });

  const isLoading = launchMutation.isPending || closeMutation.isPending;
  const conversations = conversationsData?.conversations || [];

  return (
    <Card className="h-full">
      <CardHeader className="pb-2">
        <CardTitle className="text-base font-medium flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Globe className="h-4 w-4" />
            Browser Connector
          </div>
          <div className="flex items-center gap-2">
            <Badge
              variant={status?.running ? 'default' : 'secondary'}
              className={status?.running ? 'bg-green-500' : ''}
            >
              <Circle className={`h-2 w-2 mr-1 ${status?.running ? 'fill-current' : ''}`} />
              {status?.running ? 'Running' : 'Stopped'}
            </Badge>
          </div>
        </CardTitle>
        <p className="text-xs text-muted-foreground mt-1">
          Capture AI conversations from ChatGPT, Claude, and Gemini
        </p>
      </CardHeader>

      <CardContent className="pt-0 space-y-4">
        {/* Control buttons */}
        <div className="flex gap-2">
          {status?.running ? (
            <>
              <Button
                variant="outline"
                size="sm"
                onClick={() => closeMutation.mutate()}
                disabled={isLoading}
                className="flex-1"
              >
                {closeMutation.isPending ? (
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                ) : (
                  <Square className="h-4 w-4 mr-2" />
                )}
                Stop Browser
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => refetchStatus()}
                aria-label="Refresh status"
              >
                <RefreshCw className="h-4 w-4" />
              </Button>
            </>
          ) : (
            <div className="flex flex-col gap-2 w-full">
              <div className="flex gap-2">
                <Select
                  value={selectedPlatform}
                  onValueChange={(value) => setSelectedPlatform(value as SupportedSite)}
                >
                  <SelectTrigger className="w-[140px]">
                    <SelectValue placeholder="Select platform" />
                  </SelectTrigger>
                  <SelectContent>
                    {platforms.map((platform) => (
                      <SelectItem
                        key={platform.id}
                        value={platform.id}
                        disabled={!platform.available}
                      >
                        <div className="flex items-center gap-2">
                          <span>{platform.name}</span>
                          {!platform.available && (
                            <span className="text-xs text-muted-foreground">(soon)</span>
                          )}
                        </div>
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Button
                  onClick={() => launchMutation.mutate({ platform: selectedPlatform, useVnc: vncMode })}
                  disabled={isLoading || !platforms.find(p => p.id === selectedPlatform)?.available || (vncMode && !vncCheck?.available)}
                  size="sm"
                  className="flex-1"
                >
                  {launchMutation.isPending ? (
                    <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  ) : vncMode ? (
                    <Monitor className="h-4 w-4 mr-2" />
                  ) : (
                    <Play className="h-4 w-4 mr-2" />
                  )}
                  {vncMode ? 'Launch VNC' : 'Launch'}
                </Button>
              </div>
              {/* VNC mode toggle */}
              <div className="flex items-center gap-2">
                <Switch
                  id="vncMode"
                  checked={vncMode}
                  onCheckedChange={setVncMode}
                  disabled={!vncCheck?.available}
                />
                <Label htmlFor="vncMode" className="text-xs text-muted-foreground cursor-pointer">
                  <Monitor className="h-3 w-3 inline mr-1" />
                  VNC mode (remote access)
                </Label>
                {vncCheck && !vncCheck.available && (
                  <span className="text-xs text-orange-500">
                    Missing: {vncCheck.missing.join(', ')}
                  </span>
                )}
              </div>
            </div>
          )}
          <Dialog open={isSettingsOpen} onOpenChange={setIsSettingsOpen}>
            <DialogTrigger asChild>
              <Button variant="outline" size="sm" aria-label="Browser connector settings">
                <Settings className="h-4 w-4" />
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Browser Connector Settings</DialogTitle>
                <DialogDescription>
                  Configure browser behavior and auto-start options
                </DialogDescription>
              </DialogHeader>
              <div className="space-y-4 py-4">
                <div className="flex items-center justify-between">
                  <Label htmlFor="autoStart">Auto-start with server</Label>
                  <Switch
                    id="autoStart"
                    checked={config?.autoStart ?? false}
                    onCheckedChange={(checked) => updateConfigMutation.mutate({ autoStart: checked })}
                  />
                </div>
                <div className="flex items-center justify-between">
                  <Label htmlFor="headed">Show browser window</Label>
                  <Switch
                    id="headed"
                    checked={config?.headed ?? true}
                    onCheckedChange={(checked) => updateConfigMutation.mutate({ headed: checked })}
                  />
                </div>
              </div>
              <DialogFooter>
                <Button variant="outline" onClick={() => setIsSettingsOpen(false)}>
                  Close
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </div>

        {/* Quick navigation buttons when running */}
        {status?.running && (
          <div className="flex flex-wrap gap-2">
            {(['chatgpt', 'claude', 'gemini'] as SupportedSite[]).map((site) => (
              <Button
                key={site}
                variant="outline"
                size="sm"
                onClick={() => navigateMutation.mutate(siteUrls[site])}
                disabled={navigateMutation.isPending}
                className="text-xs"
              >
                {siteLabels[site]}
                <ExternalLink className="h-3 w-3 ml-1" />
              </Button>
            ))}
          </div>
        )}

        {/* Status info */}
        {status?.running && (
          <div className="space-y-2 text-sm">
            {/* VNC URL when enabled */}
            {status.vnc?.enabled && (() => {
              const wsPort = status.vnc?.wsPort || 6080;
              const serverIp = serverInfo?.ipAddress;
              // Use frontend port for the custom VNC viewer page
              const frontendPort = window.location.port || '8080';
              const vncViewerUrl = serverIp ? `http://${serverIp}:${frontendPort}/vnc?host=${serverIp}&port=${wsPort}` : null;

              return (
                <div className="bg-gradient-to-r from-blue-50 to-indigo-50 dark:from-blue-950 dark:to-indigo-950 border border-blue-200 dark:border-blue-800 rounded-lg p-3">
                  <div className="flex items-center justify-between mb-3">
                    <div className="flex items-center gap-2 text-blue-700 dark:text-blue-300">
                      <Monitor className="h-4 w-4" />
                      <span className="font-medium text-sm">VNC Remote Access</span>
                    </div>
                    <Badge variant="secondary" className="text-xs bg-blue-100 dark:bg-blue-900 text-blue-700 dark:text-blue-300 font-mono">
                      pw: mindsage
                    </Badge>
                  </div>

                  <div className="bg-white dark:bg-gray-900 rounded-md p-2 border border-blue-100 dark:border-blue-900">
                    <div className="flex items-center justify-between gap-2">
                      <div className="min-w-0">
                        <p className="text-[10px] text-muted-foreground uppercase tracking-wide mb-0.5">Open on any device</p>
                        {serverIp ? (
                          <p className="text-sm font-mono font-medium text-foreground truncate">
                            {serverIp}:{frontendPort}/vnc
                          </p>
                        ) : (
                          <p className="text-sm font-mono text-muted-foreground flex items-center gap-1">
                            <Loader2 className="h-3 w-3 animate-spin" />
                            Loading IP...
                          </p>
                        )}
                      </div>
                      <div className="flex gap-1">
                        <Button
                          variant="outline"
                          size="sm"
                          className="h-8 px-2"
                          disabled={!vncViewerUrl}
                          aria-label="Copy VNC URL"
                          onClick={async () => {
                            if (vncViewerUrl) {
                              await copyToClipboard(vncViewerUrl);
                              setCopied(true);
                              setTimeout(() => setCopied(false), 2000);
                              toast({ title: 'URL copied to clipboard' });
                            }
                          }}
                        >
                          {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
                        </Button>
                        <Button
                          variant="default"
                          size="sm"
                          className="h-8 px-2"
                          disabled={!vncViewerUrl}
                          aria-label="Open VNC viewer"
                          onClick={() => vncViewerUrl && window.open(vncViewerUrl, '_blank')}
                        >
                          <ExternalLink className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                    </div>
                  </div>
                </div>
              );
            })()}
            {status.activeUrl && (
              <div className="flex items-center gap-2 text-muted-foreground">
                <span className="font-medium">Current:</span>
                <span className="truncate flex-1">{status.activeUrl}</span>
              </div>
            )}
            <div className="flex items-center justify-between text-muted-foreground">
              <span>Session captures:</span>
              <span className="font-medium">{status.captureStats.sessionCaptured}</span>
            </div>
          </div>
        )}

        {/* Capture statistics */}
        <div className="grid grid-cols-3 gap-2 text-center">
          <div className="bg-muted/50 rounded-lg p-2">
            <div className="text-lg font-semibold">{status?.captureStats.totalConversations ?? 0}</div>
            <div className="text-xs text-muted-foreground">Conversations</div>
          </div>
          <div className="bg-muted/50 rounded-lg p-2">
            <div className="text-lg font-semibold">{status?.captureStats.totalCaptured ?? 0}</div>
            <div className="text-xs text-muted-foreground">Messages</div>
          </div>
          <div className="bg-muted/50 rounded-lg p-2">
            <div className="text-xs font-medium">
              {formatRelativeTime(status?.captureStats.lastCaptureAt)}
            </div>
            <div className="text-xs text-muted-foreground">Last capture</div>
          </div>
        </div>

        {/* Recent conversations */}
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
              <ScrollArea className="h-[200px]">
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
                            <Badge variant="outline" className="text-xs">
                              {siteLabels[conv.site]}
                            </Badge>
                            {conv.indexed && (
                              <Badge variant="secondary" className="text-xs bg-green-100 text-green-700">
                                Indexed
                              </Badge>
                            )}
                          </div>
                          <p className="text-sm truncate mt-1">{conv.title || 'Untitled'}</p>
                          <p className="text-xs text-muted-foreground">
                            {conv.messageCount} messages • {formatRelativeTime(conv.updatedAt)}
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
                                This will permanently delete "{conv.title || 'Untitled'}" ({conv.messageCount} messages).
                              </AlertDialogDescription>
                            </AlertDialogHeader>
                            <AlertDialogFooter>
                              <AlertDialogCancel>Cancel</AlertDialogCancel>
                              <AlertDialogAction onClick={() => deleteMutation.mutate(conv.id)}>
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
      </CardContent>
    </Card>
  );
}
