import type { ConsentPreset } from './types';

interface ConsentBadgeProps {
  preset?: ConsentPreset;
}

const PRESET_COLORS: Record<ConsentPreset, string> = {
  strict: 'bg-red-500',
  balanced: 'bg-blue-500',
  open: 'bg-green-500',
  health_focus: 'bg-pink-500',
  work_only: 'bg-amber-500',
  recent_only: 'bg-purple-500',
  family_protected: 'bg-cyan-500',
};

export function ConsentBadge({ preset }: ConsentBadgeProps) {
  if (!preset) {
    return (
      <span className="absolute -top-0.5 -right-0.5 h-2 w-2 rounded-full bg-muted-foreground/50" />
    );
  }

  const color = PRESET_COLORS[preset] || 'bg-primary';

  return (
    <span
      className={`absolute -top-0.5 -right-0.5 h-2 w-2 rounded-full ${color}`}
      title={`Preset: ${preset}`}
    />
  );
}
