import { useState } from 'react';
import {
  type LucideIcon,
  Lock,
  Scale,
  Unlock,
  Heart,
  Briefcase,
  Clock,
  Users,
  Loader2,
  Check,
  ChevronDown,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import type { ConsentPreset, PresetInfo } from './types';

interface ConsentPresetSelectorProps {
  presets: PresetInfo[];
  currentPreset?: ConsentPreset;
  onSelect: (preset: ConsentPreset) => void;
  isLoading?: boolean;
}

const PRESET_ICONS: Record<ConsentPreset, LucideIcon> = {
  strict: Lock,
  balanced: Scale,
  open: Unlock,
  health_focus: Heart,
  work_only: Briefcase,
  recent_only: Clock,
  family_protected: Users,
};

const PRESET_COLORS: Record<ConsentPreset, string> = {
  strict: 'text-red-500 hover:bg-red-500/10',
  balanced: 'text-blue-500 hover:bg-blue-500/10',
  open: 'text-green-500 hover:bg-green-500/10',
  health_focus: 'text-pink-500 hover:bg-pink-500/10',
  work_only: 'text-amber-500 hover:bg-amber-500/10',
  recent_only: 'text-purple-500 hover:bg-purple-500/10',
  family_protected: 'text-cyan-500 hover:bg-cyan-500/10',
};

const PRESET_DISPLAY_NAMES: Record<ConsentPreset, string> = {
  strict: 'Strict',
  balanced: 'Balanced',
  open: 'Open',
  health_focus: 'Health Focus',
  work_only: 'Work Only',
  recent_only: 'Recent Only',
  family_protected: 'Family Protected',
};

const PRESET_DESCRIPTIONS: Record<ConsentPreset, string> = {
  strict: 'Maximum anonymization',
  balanced: 'Smart defaults',
  open: 'Minimal filtering',
  health_focus: 'Extra health data protection',
  work_only: 'Only work-related data',
  recent_only: 'Only recent documents',
  family_protected: 'Hide family information',
};

function PresetButton({
  presetId,
  isSelected,
  isLoading,
  onSelect,
  showDescription,
}: {
  presetId: ConsentPreset;
  isSelected: boolean;
  isLoading?: boolean;
  onSelect: (preset: ConsentPreset) => void;
  showDescription?: boolean;
}) {
  const Icon = PRESET_ICONS[presetId];
  const colorClass = PRESET_COLORS[presetId];

  return (
    <Button
      variant="outline"
      size="sm"
      disabled={isLoading}
      onClick={() => onSelect(presetId)}
      className={`relative flex ${showDescription ? 'flex-row justify-start gap-2' : 'flex-col gap-1'} items-center h-auto py-3 ${colorClass} ${
        isSelected ? 'ring-2 ring-primary' : ''
      }`}
    >
      {isLoading ? (
        <Loader2 className="h-4 w-4 animate-spin" />
      ) : (
        <Icon className="h-4 w-4 shrink-0" />
      )}
      <div className={showDescription ? 'text-left' : ''}>
        <span className="text-xs font-medium">{PRESET_DISPLAY_NAMES[presetId]}</span>
        {showDescription && (
          <p className="text-[10px] text-muted-foreground font-normal">{PRESET_DESCRIPTIONS[presetId]}</p>
        )}
      </div>
      {isSelected && (
        <Check className="absolute top-1 right-1 h-3 w-3 text-primary" />
      )}
    </Button>
  );
}

export function ConsentPresetSelector({
  currentPreset,
  onSelect,
  isLoading,
}: ConsentPresetSelectorProps) {
  const [showSpecialized, setShowSpecialized] = useState(false);
  const mainPresets: ConsentPreset[] = ['strict', 'balanced', 'open'];
  const specializedPresets: ConsentPreset[] = ['health_focus', 'work_only', 'recent_only', 'family_protected'];

  // Auto-expand if a specialized preset is currently active
  const hasSpecializedActive = currentPreset && specializedPresets.includes(currentPreset);

  return (
    <div className="space-y-2">
      <label className="text-sm font-medium text-muted-foreground">
        Quick Presets
      </label>
      <div className="grid grid-cols-3 gap-2">
        {mainPresets.map((presetId) => (
          <PresetButton
            key={presetId}
            presetId={presetId}
            isSelected={currentPreset === presetId}
            isLoading={isLoading}
            onSelect={onSelect}
          />
        ))}
      </div>

      {/* Specialized presets */}
      <button
        onClick={() => setShowSpecialized(!showSpecialized)}
        className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors w-full justify-center py-1"
      >
        <span>Specialized presets</span>
        <ChevronDown className={`h-3 w-3 transition-transform ${showSpecialized || hasSpecializedActive ? 'rotate-180' : ''}`} />
      </button>
      {(showSpecialized || hasSpecializedActive) && (
        <div className="grid grid-cols-2 gap-2">
          {specializedPresets.map((presetId) => (
            <PresetButton
              key={presetId}
              presetId={presetId}
              isSelected={currentPreset === presetId}
              isLoading={isLoading}
              onSelect={onSelect}
              showDescription
            />
          ))}
        </div>
      )}
    </div>
  );
}
