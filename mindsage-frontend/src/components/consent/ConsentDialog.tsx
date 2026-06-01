import { useState } from 'react';
import { Shield, Loader2 } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
  DialogDescription,
} from '@/components/ui/dialog';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { Button } from '@/components/ui/button';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useToast } from '@/hooks/use-toast';
import { useConsent } from './use-consent';
import { ConsentPresetSelector } from './ConsentPresetSelector';
import { CategoryFilter } from './CategoryFilter';
import { PIITypeFilter } from './PIITypeFilter';
import type { ConsentPreset, DataCategory, PIIType } from './types';
import { cn } from '@/lib/utils';

// Shield icon colors based on preset (only 3 main presets are shown in UI)
const PRESET_SHIELD_COLORS: Partial<Record<ConsentPreset, string>> = {
  strict: 'text-red-500',
  balanced: 'text-blue-500',
  open: 'text-green-500',
};

interface ConsentDialogProps {
  sessionId?: string | null;
  onSessionCreated?: (sessionId: string) => void;
}

export function ConsentDialog({ sessionId, onSessionCreated }: ConsentDialogProps) {
  const [open, setOpen] = useState(false);
  const { toast } = useToast();

  const {
    session,
    presets,
    isLoading,
    isAvailable,
    createSession,
    updateSession,
    applyPreset,
  } = useConsent(sessionId);

  // Session is now auto-created in ChatPanel when LLM is configured

  const handlePresetSelect = async (preset: ConsentPreset) => {
    if (!sessionId) {
      // Create new session with preset
      createSession.mutate(preset, {
        onSuccess: (data) => {
          onSessionCreated?.(data.session_id);
          toast({
            title: 'Preset applied',
            description: `Privacy settings set to "${preset}".`,
          });
        },
        onError: () => {
          toast({
            variant: 'destructive',
            title: 'Failed to apply preset',
          });
        },
      });
    } else {
      // Apply preset to existing session
      applyPreset.mutate(preset, {
        onSuccess: () => {
          toast({
            title: 'Preset applied',
            description: `Privacy settings set to "${preset}".`,
          });
        },
        onError: () => {
          toast({
            variant: 'destructive',
            title: 'Failed to apply preset',
          });
        },
      });
    }
  };

  const handleCategoryUpdate = (categories: {
    allowed_categories: DataCategory[];
    blocked_categories: DataCategory[];
  }) => {
    if (!sessionId) return;
    updateSession.mutate(categories, {
      onError: () => {
        toast({
          variant: 'destructive',
          title: 'Failed to update categories',
        });
      },
    });
  };

  const handlePIIUpdate = (update: { exposed_pii_types: PIIType[] }) => {
    if (!sessionId) return;
    updateSession.mutate(update, {
      onError: () => {
        toast({
          variant: 'destructive',
          title: 'Failed to update PII settings',
        });
      },
    });
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <TooltipProvider delayDuration={300}>
        <Tooltip>
          <TooltipTrigger asChild>
            <DialogTrigger asChild>
              <Button variant="ghost" size="icon" className="h-8 w-8" aria-label="Privacy consent settings">
                <Shield
                  className={cn(
                    'h-4 w-4',
                    session?.metadata.preset_applied
                      ? PRESET_SHIELD_COLORS[session.metadata.preset_applied]
                      : 'text-muted-foreground'
                  )}
                />
              </Button>
            </DialogTrigger>
          </TooltipTrigger>
          <TooltipContent side="top" className="text-xs">
            {session?.metadata.preset_applied
              ? `Privacy: ${session.metadata.preset_applied}`
              : 'Privacy settings'}
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
      <DialogContent className="max-w-lg max-h-[85vh] overflow-hidden flex flex-col">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Shield className="h-5 w-5" />
            Privacy & Consent
          </DialogTitle>
          <DialogDescription>
            Control what data is shared with the AI. Changes apply to this conversation.
          </DialogDescription>
        </DialogHeader>

        {!isAvailable && !isLoading ? (
          <div className="py-8 text-center text-muted-foreground">
            <Shield className="h-12 w-12 mx-auto mb-4 opacity-20" />
            <p>Consent management is not available.</p>
            <p className="text-sm mt-1">The backend service may not be running.</p>
          </div>
        ) : isLoading || createSession.isPending ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        ) : (
          <div className="flex-1 overflow-hidden flex flex-col space-y-4">
            {/* Quick Presets */}
            <ConsentPresetSelector
              presets={presets}
              currentPreset={session?.metadata.preset_applied}
              onSelect={handlePresetSelect}
              isLoading={applyPreset.isPending || createSession.isPending}
            />

            {/* Fine-grained Controls - only enabled after session is created */}
            {session ? (
              <Tabs defaultValue="pii" className="flex-1 flex flex-col overflow-hidden">
                <TabsList className="grid w-full grid-cols-2">
                  <TabsTrigger value="pii">PII Types</TabsTrigger>
                  <TabsTrigger value="categories">Topics</TabsTrigger>
                </TabsList>

                <div className="flex-1 overflow-y-auto mt-4 pr-1">
                  <TabsContent value="pii" className="mt-0">
                    <PIITypeFilter
                      session={session}
                      onUpdate={handlePIIUpdate}
                      isUpdating={updateSession.isPending}
                    />
                  </TabsContent>
                  <TabsContent value="categories" className="mt-0">
                    <CategoryFilter
                      session={session}
                      onUpdate={handleCategoryUpdate}
                      isUpdating={updateSession.isPending}
                    />
                  </TabsContent>
                </div>
              </Tabs>
            ) : (
              <div className="text-center py-6 text-sm text-muted-foreground border rounded-lg bg-muted/30">
                <p>Select a preset above to enable fine-grained controls</p>
              </div>
            )}

          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
