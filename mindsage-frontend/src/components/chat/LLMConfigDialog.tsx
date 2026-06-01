import { useState, useEffect } from 'react';
import { Settings, Eye, EyeOff, Check, Loader2, AlertCircle, CheckCircle } from 'lucide-react';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogDescription } from '@/components/ui/dialog';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api, type LLMConfig, type LLMProvider } from '@/lib/api';
import { useToast } from '@/hooks/use-toast';

const PROVIDER_MODELS: Record<LLMProvider, string[]> = {
  openai: ['gpt-4.1', 'gpt-4.1-mini', 'gpt-4.1-nano', 'gpt-4o', 'gpt-4o-mini'],
  anthropic: ['claude-sonnet-4-6', 'claude-haiku-4-5-20251001', 'claude-opus-4-6'],
  groq: ['llama-3.3-70b-versatile', 'llama-3.1-70b-versatile', 'llama-3.1-8b-instant', 'mixtral-8x7b-32768'],
};

const PROVIDER_LABELS: Record<LLMProvider, string> = {
  openai: 'OpenAI',
  anthropic: 'Anthropic',
  groq: 'Groq',
};

const LEGACY_STORAGE_KEY = 'mindsage-llm-providers';

interface LegacyProvider {
  id: string;
  name: string;
  apiKey: string;
  baseUrl: string;
  model: string;
  isActive: boolean;
}

export function LLMConfigDialog() {
  const [open, setOpen] = useState(false);
  const [showMigrationDialog, setShowMigrationDialog] = useState(false);
  const [legacyProviders, setLegacyProviders] = useState<LegacyProvider[]>([]);
  const { toast } = useToast();
  const queryClient = useQueryClient();

  // Check for legacy localStorage data on mount
  useEffect(() => {
    const stored = localStorage.getItem(LEGACY_STORAGE_KEY);
    if (stored) {
      try {
        const providers = JSON.parse(stored) as LegacyProvider[];
        if (providers.length > 0) {
          setLegacyProviders(providers);
          setShowMigrationDialog(true);
        }
      } catch {
        // Invalid data, remove it
        localStorage.removeItem(LEGACY_STORAGE_KEY);
      }
    }
  }, []);

  // Query current config from backend
  const { data: config, isLoading: configLoading } = useQuery({
    queryKey: ['llmConfig'],
    queryFn: api.getLLMConfig,
  });

  // Mutation to update config
  const updateConfigMutation = useMutation({
    mutationFn: api.updateLLMConfig,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['llmConfig'] });
      queryClient.invalidateQueries({ queryKey: ['chatStatus'] });
      toast({
        title: 'Configuration saved',
        description: 'Your LLM settings have been updated.',
      });
    },
    onError: (error) => {
      toast({
        variant: 'destructive',
        title: 'Failed to save',
        description: error instanceof Error ? error.message : 'Unknown error',
      });
    },
  });

  // Mutation to test API key
  const testKeyMutation = useMutation({
    mutationFn: ({ provider, apiKey }: { provider: LLMProvider; apiKey: string }) =>
      api.testApiKey(provider, apiKey),
  });

  const handleMigrate = async () => {
    // Migrate legacy providers to backend
    for (const provider of legacyProviders) {
      const providerType = provider.name.toLowerCase() as LLMProvider;
      if (providerType === 'openai' || providerType === 'anthropic' || providerType === 'groq') {
        try {
          await api.updateLLMConfig({
            [`${providerType}ApiKey`]: provider.apiKey,
            [`${providerType}Model`]: provider.model,
          });
        } catch {
          // Continue with other providers
        }
      }
    }

    // Clear localStorage
    localStorage.removeItem(LEGACY_STORAGE_KEY);
    setShowMigrationDialog(false);
    setLegacyProviders([]);

    queryClient.invalidateQueries({ queryKey: ['llmConfig'] });
    queryClient.invalidateQueries({ queryKey: ['chatStatus'] });

    toast({
      title: 'Migration complete',
      description: 'Your API keys have been migrated to server-side storage.',
    });
  };

  const handleSkipMigration = () => {
    localStorage.removeItem(LEGACY_STORAGE_KEY);
    setShowMigrationDialog(false);
    setLegacyProviders([]);
  };

  // Migration dialog
  if (showMigrationDialog) {
    return (
      <Dialog open={showMigrationDialog} onOpenChange={setShowMigrationDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Migrate API Keys</DialogTitle>
            <DialogDescription>
              We found API keys stored in your browser. For better security and to enable RAG features,
              we recommend migrating them to server-side storage.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3 py-4">
            {legacyProviders.map(p => (
              <div key={p.id} className="flex items-center gap-2 p-2 rounded bg-muted">
                <Check className="h-4 w-4 text-success" />
                <span className="text-sm">{p.name}</span>
                <Badge variant="outline" className="text-xs">{p.model}</Badge>
              </div>
            ))}
          </div>
          <div className="flex gap-2 justify-end">
            <Button variant="outline" onClick={handleSkipMigration}>
              Skip
            </Button>
            <Button onClick={handleMigrate}>
              Migrate to Server
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    );
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <TooltipProvider delayDuration={300}>
        <Tooltip>
          <TooltipTrigger asChild>
            <DialogTrigger asChild>
              <Button variant="ghost" size="icon" className="h-8 w-8" aria-label="LLM settings">
                <Settings className="h-4 w-4" />
              </Button>
            </DialogTrigger>
          </TooltipTrigger>
          <TooltipContent side="top" className="text-xs">
            LLM settings
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>LLM Configuration</DialogTitle>
          <DialogDescription>
            Configure API keys for different providers. Keys are stored securely on the server.
          </DialogDescription>
        </DialogHeader>

        {configLoading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-6 w-6 animate-spin" />
          </div>
        ) : (
          <div className="space-y-4">
            {/* Preferred Provider */}
            <div className="space-y-2">
              <Label className="text-xs text-muted-foreground">Preferred Provider</Label>
              <Select
                value={config?.preferredProvider || 'auto'}
                onValueChange={(value) => {
                  updateConfigMutation.mutate({ preferredProvider: value as 'auto' | LLMProvider });
                }}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="auto">Auto (use first available)</SelectItem>
                  <SelectItem value="openai">OpenAI</SelectItem>
                  <SelectItem value="anthropic">Anthropic</SelectItem>
                  <SelectItem value="groq">Groq</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {/* Provider Tabs */}
            <Tabs defaultValue="openai" className="w-full">
              <TabsList className="grid w-full grid-cols-3">
                <TabsTrigger value="openai" className="relative">
                  OpenAI
                  {config?.openaiConfigured && (
                    <CheckCircle className="h-3 w-3 text-success absolute -top-1 -right-1" />
                  )}
                </TabsTrigger>
                <TabsTrigger value="anthropic" className="relative">
                  Anthropic
                  {config?.anthropicConfigured && (
                    <CheckCircle className="h-3 w-3 text-success absolute -top-1 -right-1" />
                  )}
                </TabsTrigger>
                <TabsTrigger value="groq" className="relative">
                  Groq
                  {config?.groqConfigured && (
                    <CheckCircle className="h-3 w-3 text-success absolute -top-1 -right-1" />
                  )}
                </TabsTrigger>
              </TabsList>

              {(['openai', 'anthropic', 'groq'] as LLMProvider[]).map((provider) => (
                <TabsContent key={provider} value={provider}>
                  <ProviderConfig
                    provider={provider}
                    config={config}
                    onUpdate={updateConfigMutation.mutate}
                    onTest={(apiKey) => testKeyMutation.mutateAsync({ provider, apiKey })}
                    isUpdating={updateConfigMutation.isPending}
                    isTesting={testKeyMutation.isPending}
                    testResult={testKeyMutation.data}
                  />
                </TabsContent>
              ))}
            </Tabs>

            {/* Active Provider Status */}
            {config?.activeProvider && (
              <div className="p-3 rounded-lg bg-muted">
                <div className="flex items-center gap-2">
                  <CheckCircle className="h-4 w-4 text-success" />
                  <span className="text-sm font-medium">
                    Active: {PROVIDER_LABELS[config.activeProvider]}
                  </span>
                </div>
              </div>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

interface ProviderConfigProps {
  provider: LLMProvider;
  config: LLMConfig | undefined;
  onUpdate: (update: Partial<LLMConfig>) => void;
  onTest: (apiKey: string) => Promise<{ success: boolean; error?: string }>;
  isUpdating: boolean;
  isTesting: boolean;
  testResult?: { success: boolean; error?: string };
}

function ProviderConfig({
  provider,
  config,
  onUpdate,
  onTest,
  isUpdating,
  isTesting,
  testResult,
}: ProviderConfigProps) {
  const [apiKey, setApiKey] = useState('');
  const [showKey, setShowKey] = useState(false);
  const [testStatus, setTestStatus] = useState<'idle' | 'success' | 'error'>('idle');
  const [testError, setTestError] = useState<string | null>(null);

  // Reset state when switching between provider tabs
  useEffect(() => {
    setApiKey('');
    setShowKey(false);
    setTestStatus('idle');
    setTestError(null);
    setIsSaving(false);
  }, [provider]);

  const isConfigured = config?.[`${provider}Configured` as keyof LLMConfig] as boolean;
  const currentModel = config?.[`${provider}Model` as keyof LLMConfig] as string;
  const models = PROVIDER_MODELS[provider];

  const [isSaving, setIsSaving] = useState(false);

  const handleTestAndSave = async () => {
    if (!apiKey) return;
    setTestStatus('idle');
    setTestError(null);
    setIsSaving(true);
    try {
      const result = await onTest(apiKey);
      if (result.success) {
        setTestStatus('success');
        // Auto-save on successful test
        onUpdate({ [`${provider}ApiKey`]: apiKey });
        setApiKey('');
      } else {
        setTestStatus('error');
        setTestError(result.error || 'Test failed');
      }
    } catch (err) {
      setTestStatus('error');
      setTestError(err instanceof Error ? err.message : 'Test failed');
    } finally {
      setIsSaving(false);
    }
  };

  const handleSaveWithoutTest = () => {
    if (!apiKey) return;
    onUpdate({
      [`${provider}ApiKey`]: apiKey,
    });
    setApiKey('');
    setTestStatus('idle');
  };

  return (
    <div className="space-y-4 pt-4">
      {/* API Key */}
      <div className="space-y-2">
        <Label className="text-xs">API Key</Label>
        <div className="relative">
          <Input
            type={showKey ? 'text' : 'password'}
            placeholder={isConfigured ? '••••••••••••••••' : 'Enter API key'}
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            className="pr-10"
          />
          <Button
            variant="ghost"
            size="icon"
            className="absolute right-1 top-1/2 -translate-y-1/2 h-6 w-6"
            onClick={() => setShowKey(!showKey)}
          >
            {showKey ? <EyeOff className="h-3 w-3" /> : <Eye className="h-3 w-3" />}
          </Button>
        </div>
        {isConfigured && (
          <p className="text-xs text-muted-foreground">
            Key is configured. Enter a new key to replace it.
          </p>
        )}
      </div>

      {/* Test Result */}
      {testStatus === 'success' && (
        <div className="flex items-center gap-2 p-2 rounded bg-success/10 text-success text-sm">
          <CheckCircle className="h-4 w-4" />
          Key is valid
        </div>
      )}
      {testStatus === 'error' && (
        <div className="flex items-center gap-2 p-2 rounded bg-destructive/10 text-destructive text-sm">
          <AlertCircle className="h-4 w-4" />
          {testError || 'Invalid key'}
        </div>
      )}

      {/* Model Selection */}
      <div className="space-y-2">
        <Label className="text-xs">Model</Label>
        <Select
          value={currentModel || models[0]}
          onValueChange={(value) => {
            onUpdate({ [`${provider}Model`]: value });
          }}
        >
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {models.map((model) => (
              <SelectItem key={model} value={model}>
                {model}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* Actions */}
      <div className="flex gap-2">
        <Button
          size="sm"
          onClick={handleTestAndSave}
          disabled={!apiKey || isTesting || isSaving}
          className="flex-1"
        >
          {isTesting || isSaving ? (
            <Loader2 className="h-4 w-4 animate-spin mr-2" />
          ) : null}
          {isTesting ? 'Testing...' : isSaving ? 'Saving...' : 'Test & Save'}
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={handleSaveWithoutTest}
          disabled={!apiKey || isUpdating}
          title="Save without testing"
        >
          {isUpdating ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            'Save Only'
          )}
        </Button>
      </div>
    </div>
  );
}

