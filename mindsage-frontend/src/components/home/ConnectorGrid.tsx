import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  MoreHorizontal,
  RefreshCw,
  Unlink,
  Upload,
  Loader2,
  ExternalLink,
  Eye,
  EyeOff,
  Key,
  CheckCircle,
  Plus,
  Link,
  Settings,
} from 'lucide-react';
import { getConnectorLogo } from '@/components/icons/ConnectorLogos';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog';
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { useQuery, useQueries, useMutation, useQueryClient } from '@tanstack/react-query';
import { getConnectors, syncConnector, disconnectConnector, api, type SupportedSite } from '@/lib/api';
import { useToast } from '@/hooks/use-toast';
import type { Connector, ConnectorType } from '@/types';
import { AIConnectorDialog } from './AIConnectorDialog';


// Non-AI connector descriptions (static, not derived from registry)
const staticConnectorDescriptions: Record<string, { connected: string; setup: string; tokenHelp?: string }> = {
  notion: {
    connected: 'Notion pages',
    setup: 'Connect your Notion workspace to sync pages.',
    tokenHelp: 'Create an integration at notion.so/my-integrations',
  },
  facebook: {
    connected: 'Facebook data',
    setup: 'Upload your Facebook data export ZIP file to import your posts, messages, and activity.',
    tokenHelp: 'Download from Meta Account Center → Your Information → Download Your Information (JSON format)',
  },
};

// Non-AI connector types (static)
const NON_AI_CONNECTOR_TYPES: { type: ConnectorType; name: string }[] = [
  { type: 'notion', name: 'Notion' },
  { type: 'facebook', name: 'Facebook' },
];

/**
 * Get connector description - uses site registry for AI connectors, static for others
 */
function getConnectorDescription(type: ConnectorType, sitesData?: { sites: { id: string; name: string }[] } | null): { connected: string; setup: string; tokenHelp?: string; useBrowserConnector?: boolean } {
  if (staticConnectorDescriptions[type]) {
    return staticConnectorDescriptions[type];
  }

  // AI connectors — generic description using site name from registry
  const siteName = sitesData?.sites.find(s => s.id === type)?.name || type;
  return {
    connected: `${siteName} conversations`,
    setup: `Sync your ${siteName} conversations automatically.`,
    useBrowserConnector: true,
  };
}

function ConnectedConnectorCard({
  connector,
  onSync,
  onDisconnect,
  onOpenSettings,
  isSyncing,
  description,
}: {
  connector: Connector;
  onSync: () => void;
  onDisconnect: () => void;
  onOpenSettings?: () => void;
  isSyncing: boolean;
  description: { connected: string; setup: string; tokenHelp?: string; useBrowserConnector?: boolean };
}) {
  const Icon = getConnectorLogo(connector.type);
  const useBrowserConnector = description.useBrowserConnector;

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={{ opacity: 0, scale: 0.95 }}
      className={`flex items-center gap-3 p-3 rounded-lg border border-border hover:bg-muted/50 transition-colors ${useBrowserConnector ? 'cursor-pointer' : ''}`}
      onClick={useBrowserConnector ? onOpenSettings : undefined}
    >
      <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-muted shrink-0">
        <Icon className="h-4 w-4" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="font-medium text-sm truncate">{connector.name}</span>
          {connector.itemCount !== undefined && connector.itemCount > 0 && (
            <Badge variant="secondary" className="text-xs">
              {connector.itemCount} items
            </Badge>
          )}
        </div>
        <p className="text-xs text-muted-foreground truncate">
          {description.connected}
        </p>
      </div>
      {useBrowserConnector ? (
        <Button variant="ghost" size="icon" className="h-8 w-8 shrink-0" aria-label="Connector settings" onClick={(e) => { e.stopPropagation(); onOpenSettings?.(); }}>
          <Settings className="h-4 w-4" />
        </Button>
      ) : (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon" className="h-8 w-8 shrink-0" aria-label="Connector options">
              <MoreHorizontal className="h-4 w-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onClick={onSync} disabled={isSyncing}>
              <RefreshCw className={`h-4 w-4 mr-2 ${isSyncing ? 'animate-spin' : ''}`} />
              Sync now
            </DropdownMenuItem>
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <DropdownMenuItem className="text-destructive" onSelect={(e) => e.preventDefault()}>
                  <Unlink className="h-4 w-4 mr-2" />
                  Disconnect
                </DropdownMenuItem>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Disconnect {connector.name}?</AlertDialogTitle>
                  <AlertDialogDescription>
                    This will remove the connection to {connector.name}. You can reconnect later.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Cancel</AlertDialogCancel>
                  <AlertDialogAction onClick={onDisconnect}>
                    Disconnect
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          </DropdownMenuContent>
        </DropdownMenu>
      )}
    </motion.div>
  );
}

function AddConnectorButton({
  availableConnectors,
  onSelect,
}: {
  availableConnectors: { type: ConnectorType; name: string }[];
  onSelect: (type: ConnectorType, name: string) => void;
}) {
  const [isOpen, setIsOpen] = useState(false);

  if (availableConnectors.length === 0) {
    return null;
  }

  return (
    <Popover open={isOpen} onOpenChange={setIsOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          className="w-full border-dashed"
        >
          <Plus className="h-4 w-4 mr-2" />
          Add Connector
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-64 p-2" align="start">
        <div className="grid gap-1">
          {availableConnectors.map(({ type, name }) => {
            const Icon = getConnectorLogo(type);
            return (
              <button
                key={type}
                onClick={() => {
                  onSelect(type, name);
                  setIsOpen(false);
                }}
                className="flex items-center gap-3 w-full p-2 rounded-md hover:bg-muted text-left transition-colors"
              >
                <div className="flex h-8 w-8 items-center justify-center rounded-md bg-muted">
                  <Icon className="h-4 w-4" />
                </div>
                <div>
                  <span className="text-sm font-medium">{name}</span>
                </div>
              </button>
            );
          })}
        </div>
      </PopoverContent>
    </Popover>
  );
}

function ConnectorConfigModal({
  connector,
  isOpen,
  onClose,
  onConnect,
}: {
  connector: { type: ConnectorType; name: string } | null;
  isOpen: boolean;
  onClose: () => void;
  onConnect: () => void;
}) {
  const [token, setToken] = useState('');
  const [showToken, setShowToken] = useState(false);
  const [isConnecting, setIsConnecting] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { toast } = useToast();

  if (!connector) return null;

  const description = getConnectorDescription(connector.type);
  const Icon = getConnectorLogo(connector.type);
  const isFileUpload = connector.type === 'chatgpt' || connector.type === 'facebook';

  const handleFileDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    const file = e.dataTransfer.files[0];
    if (file?.name.endsWith('.zip')) {
      setSelectedFile(file);
      setError(null);
    } else {
      setError('Please upload a ZIP file');
    }
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file?.name.endsWith('.zip')) {
      setSelectedFile(file);
      setError(null);
    } else if (file) {
      setError('Please upload a ZIP file');
    }
  };

  const handleConnect = async () => {
    setIsConnecting(true);
    setError(null);
    try {
      if (isFileUpload && selectedFile) {
        const created = await api.connectConnector(connector.type, connector.name, {});
        const result = await api.uploadConnectorFile(created.id, selectedFile);
        const itemLabel = connector.type === 'facebook' ? 'items' : 'conversations';
        const pendingNote = result.pendingMedia ? ` (${result.pendingMedia} media files stored for future indexing)` : '';
        toast({
          title: 'Import successful',
          description: `Imported ${result.itemCount} ${itemLabel}${pendingNote}`,
        });
      } else if (token) {
        await api.connectConnector(connector.type, connector.name, { token });
        toast({
          title: 'Connected',
          description: `${connector.name} has been connected successfully`,
        });
      }
      setToken('');
      setSelectedFile(null);
      onConnect();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Connection failed');
    } finally {
      setIsConnecting(false);
    }
  };

  const handleClose = () => {
    setToken('');
    setSelectedFile(null);
    setError(null);
    setShowToken(false);
    onClose();
  };

  const canConnect = isFileUpload ? !!selectedFile : !!token;

  return (
    <Dialog open={isOpen} onOpenChange={handleClose}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-muted">
              <Icon className="h-4 w-4" />
            </div>
            Connect {connector.name}
          </DialogTitle>
          <DialogDescription>
            {description.setup}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-4">
          {isFileUpload ? (
            <div
              onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
              onDragLeave={() => setIsDragging(false)}
              onDrop={handleFileDrop}
              className={`relative flex flex-col items-center justify-center h-32 rounded-lg border-2 border-dashed transition-colors cursor-pointer ${
                isDragging ? 'border-foreground bg-accent' : 'border-border hover:border-muted-foreground'
              }`}
            >
              <input
                type="file"
                accept=".zip"
                onChange={handleFileSelect}
                className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
              />
              {selectedFile ? (
                <>
                  <CheckCircle className="h-8 w-8 text-success mb-2" />
                  <span className="text-sm text-foreground font-medium">
                    {selectedFile.name}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {(selectedFile.size / 1024 / 1024).toFixed(2)} MB
                  </span>
                </>
              ) : (
                <>
                  <Upload className="h-8 w-8 text-muted-foreground mb-2" />
                  <span className="text-sm text-muted-foreground">
                    Drop ZIP file here or click to browse
                  </span>
                </>
              )}
            </div>
          ) : (
            <div className="space-y-2">
              <Label htmlFor="token" className="flex items-center gap-2">
                <Key className="h-4 w-4" />
                API Token
              </Label>
              <div className="relative">
                <Input
                  id="token"
                  type={showToken ? 'text' : 'password'}
                  value={token}
                  onChange={(e) => setToken(e.target.value)}
                  placeholder="Enter your API token"
                  className="pr-10"
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="absolute right-1 top-1/2 -translate-y-1/2 h-7 w-7"
                  onClick={() => setShowToken(!showToken)}
                >
                  {showToken ? (
                    <EyeOff className="h-4 w-4" />
                  ) : (
                    <Eye className="h-4 w-4" />
                  )}
                </Button>
              </div>
            </div>
          )}

          {description.tokenHelp && (
            <p className="text-xs text-muted-foreground flex items-start gap-1">
              <ExternalLink className="h-3 w-3 mt-0.5 shrink-0" />
              <span>{description.tokenHelp}</span>
            </p>
          )}

          {error && (
            <p className="text-sm text-destructive">{error}</p>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={handleClose}>
            Cancel
          </Button>
          <Button
            onClick={handleConnect}
            disabled={!canConnect || isConnecting}
          >
            {isConnecting ? (
              <>
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                {isFileUpload ? 'Importing...' : 'Connecting...'}
              </>
            ) : (
              <>
                <Link className="h-4 w-4 mr-2" />
                {isFileUpload ? 'Import' : 'Connect'}
              </>
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function ConnectorGrid() {
  const [configConnector, setConfigConnector] = useState<{ type: ConnectorType; name: string } | null>(null);
  const [syncingId, setSyncingId] = useState<string | null>(null);
  const [openAIDialog, setOpenAIDialog] = useState<SupportedSite | null>(null);
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const { data: connectors } = useQuery({
    queryKey: ['connectors'],
    queryFn: getConnectors,
  });

  // Query all sites with auth status
  const { data: sitesData } = useQuery({
    queryKey: ['browserSites'],
    queryFn: api.getSites,
  });

  // Derive AI connector site IDs from the sites API
  const aiConnectorSites = (sitesData?.sites || []).map(s => s.id);

  // Build all connector types dynamically
  const allConnectorTypes: { type: ConnectorType; name: string }[] = [
    ...(sitesData?.sites || []).map(s => ({ type: s.id as ConnectorType, name: s.name })),
    ...NON_AI_CONNECTOR_TYPES,
  ];

  // Query captured conversations for each AI site dynamically
  const conversationQueries = useQueries({
    queries: aiConnectorSites.map(siteId => ({
      queryKey: ['capturedConversations', siteId],
      queryFn: () => api.getCapturedConversations({ site: siteId }),
    })),
  });

  // Build auth status map
  const siteAuthMap = new Map<string, boolean>();
  sitesData?.sites.forEach(site => {
    siteAuthMap.set(site.id, site.authenticated);
  });

  // Build conversation count map dynamically
  const siteConversationCount: Record<string, number> = {};
  aiConnectorSites.forEach((siteId, i) => {
    siteConversationCount[siteId] = conversationQueries[i]?.data?.total || 0;
  });

  const syncMutation = useMutation({
    mutationFn: syncConnector,
    onMutate: (id) => setSyncingId(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['connectors'] });
      toast({
        title: 'Sync complete',
        description: 'Your data has been synchronized.',
      });
    },
    onSettled: () => setSyncingId(null),
  });

  const disconnectMutation = useMutation({
    mutationFn: disconnectConnector,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['connectors'] });
      toast({
        title: 'Disconnected',
        description: 'The connector has been disconnected.',
      });
    },
  });

  // Build connected connectors list with AI connector overrides
  const connectedConnectors = (connectors || [])
    .map(c => {
      // Override AI connectors with browser connector data
      if (aiConnectorSites.includes(c.type)) {
        return {
          ...c,
          connected: siteAuthMap.get(c.type) || false,
          itemCount: siteConversationCount[c.type] || 0,
        };
      }
      return c;
    })
    .filter(c => c.connected);

  // Get available (not connected) connector types
  const connectedTypes = new Set(connectedConnectors.map(c => c.type));
  // For AI connectors, consider them "available" if not authenticated
  for (const site of aiConnectorSites) {
    if (!siteAuthMap.get(site)) {
      connectedTypes.delete(site);
    }
  }
  const availableConnectors = allConnectorTypes.filter(c => !connectedTypes.has(c.type));

  return (
    <Card className="h-full">
      <CardHeader className="pb-2">
        <CardTitle className="text-base font-medium flex items-center gap-2">
          <RefreshCw className="h-4 w-4" />
          Data Connectors
        </CardTitle>
        <p className="text-xs text-muted-foreground mt-1">
          Import data from your apps and services
        </p>
      </CardHeader>
      <CardContent className="pt-0">
        <div className="space-y-2">
          <AnimatePresence mode="popLayout">
            {connectedConnectors.map((connector) => (
              <ConnectedConnectorCard
                key={connector.id}
                connector={connector}
                onSync={() => syncMutation.mutate(connector.id)}
                onDisconnect={() => disconnectMutation.mutate(connector.id)}
                onOpenSettings={aiConnectorSites.includes(connector.type) ? () => setOpenAIDialog(connector.type as SupportedSite) : undefined}
                isSyncing={syncingId === connector.id}
                description={getConnectorDescription(connector.type, sitesData)}
              />
            ))}
          </AnimatePresence>

          {connectedConnectors.length === 0 && (
            <p className="text-sm text-muted-foreground text-center py-4">
              No connectors configured yet
            </p>
          )}

          <AddConnectorButton
            availableConnectors={availableConnectors}
            onSelect={(type, name) => {
              if (aiConnectorSites.includes(type)) {
                setOpenAIDialog(type as SupportedSite);
              } else {
                setConfigConnector({ type, name });
              }
            }}
          />
        </div>

        <ConnectorConfigModal
          connector={configConnector}
          isOpen={!!configConnector}
          onClose={() => setConfigConnector(null)}
          onConnect={() => queryClient.invalidateQueries({ queryKey: ['connectors'] })}
        />

        {/* AI Connector Dialog - shared for ChatGPT, Claude, Gemini */}
        {openAIDialog && (
          <AIConnectorDialog
            isOpen={!!openAIDialog}
            onClose={() => setOpenAIDialog(null)}
            onConnect={() => {
              queryClient.invalidateQueries({ queryKey: ['connectors'] });
              queryClient.invalidateQueries({ queryKey: ['browserSites'] });
              queryClient.invalidateQueries({ queryKey: ['browserConnectorStatus'] });
              queryClient.invalidateQueries({ queryKey: ['capturedConversations'] });
            }}
            site={openAIDialog}
            Icon={getConnectorLogo(openAIDialog)}
          />
        )}
      </CardContent>
    </Card>
  );
}
