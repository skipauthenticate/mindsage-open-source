import {
  type LucideIcon,
  Heart,
  DollarSign,
  Briefcase,
  User,
  MessageCircle,
  Scale,
  Plane,
  GraduationCap,
  FileText,
  Code,
  Trophy,
  Laptop,
  ShoppingCart,
  Users,
} from 'lucide-react';
import { Switch } from '@/components/ui/switch';
import { Badge } from '@/components/ui/badge';
import type { DataCategory, ConsentSession } from './types';

interface CategoryFilterProps {
  session: ConsentSession | null | undefined;
  onUpdate: (categories: { allowed_categories: DataCategory[]; blocked_categories: DataCategory[] }) => void;
  isUpdating?: boolean;
}

interface CategoryInfo {
  label: string;
  description: string;
  icon: LucideIcon;
  risk: 'low' | 'medium' | 'high';
}

const CATEGORY_INFO: Record<DataCategory, CategoryInfo> = {
  health: {
    label: 'Health',
    description: 'Medical records, prescriptions, wellness data',
    icon: Heart,
    risk: 'high',
  },
  finance: {
    label: 'Finance',
    description: 'Banking, investments, tax information',
    icon: DollarSign,
    risk: 'high',
  },
  work: {
    label: 'Work',
    description: 'Professional emails, projects, documents',
    icon: Briefcase,
    risk: 'low',
  },
  personal: {
    label: 'Personal',
    description: 'Journals, diaries, private notes',
    icon: User,
    risk: 'high',
  },
  social: {
    label: 'Social',
    description: 'Messages, social media posts',
    icon: MessageCircle,
    risk: 'medium',
  },
  legal: {
    label: 'Legal',
    description: 'Contracts, agreements, legal docs',
    icon: Scale,
    risk: 'high',
  },
  travel: {
    label: 'Travel',
    description: 'Bookings, itineraries, reservations',
    icon: Plane,
    risk: 'medium',
  },
  education: {
    label: 'Education',
    description: 'Courses, transcripts, certificates',
    icon: GraduationCap,
    risk: 'low',
  },
  programming: {
    label: 'Programming',
    description: 'Code, software projects, technical docs',
    icon: Code,
    risk: 'low',
  },
  sports: {
    label: 'Sports',
    description: 'Games, athletics, fitness activities',
    icon: Trophy,
    risk: 'low',
  },
  technology: {
    label: 'Technology',
    description: 'Devices, gadgets, tech products',
    icon: Laptop,
    risk: 'low',
  },
  shopping: {
    label: 'Shopping',
    description: 'Purchases, orders, wishlists',
    icon: ShoppingCart,
    risk: 'medium',
  },
  family: {
    label: 'Family',
    description: 'Family events, relatives, home life',
    icon: Users,
    risk: 'medium',
  },
  general: {
    label: 'General',
    description: 'Uncategorized documents',
    icon: FileText,
    risk: 'low',
  },
};

const RISK_COLORS: Record<string, string> = {
  low: 'bg-green-500/10 text-green-600',
  medium: 'bg-amber-500/10 text-amber-600',
  high: 'bg-red-500/10 text-red-600',
};

const CATEGORIES_BY_RISK: { label: string; risk: string; categories: DataCategory[] }[] = [
  {
    label: 'High sensitivity',
    risk: 'high',
    categories: ['health', 'finance', 'personal', 'legal'],
  },
  {
    label: 'Medium sensitivity',
    risk: 'medium',
    categories: ['social', 'travel', 'shopping', 'family'],
  },
  {
    label: 'Low sensitivity',
    risk: 'low',
    categories: ['work', 'education', 'programming', 'sports', 'technology', 'general'],
  },
];

export function CategoryFilter({
  session,
  onUpdate,
  isUpdating,
}: CategoryFilterProps) {
  const allowedCategories = session?.consent?.allowed_categories ?? [];
  const blockedCategories = session?.consent?.blocked_categories ?? [];

  const isCategoryAllowed = (category: DataCategory): boolean => {
    if (blockedCategories.includes(category)) return false;
    if (allowedCategories.length === 0) return true; // Default allow if no explicit list
    return allowedCategories.includes(category);
  };

  const handleToggle = (category: DataCategory, allowed: boolean) => {
    let newAllowed = [...allowedCategories];
    let newBlocked = [...blockedCategories];

    if (allowed) {
      // Remove from blocked, add to allowed
      newBlocked = newBlocked.filter((c) => c !== category);
      if (!newAllowed.includes(category)) {
        newAllowed.push(category);
      }
    } else {
      // Remove from allowed, add to blocked
      newAllowed = newAllowed.filter((c) => c !== category);
      if (!newBlocked.includes(category)) {
        newBlocked.push(category);
      }
    }

    onUpdate({
      allowed_categories: newAllowed,
      blocked_categories: newBlocked,
    });
  };

  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">
        Select topics for sharing source documents with AI. Documents with disabled topics will be excluded.
      </p>
      <div className="space-y-4">
        {CATEGORIES_BY_RISK.map((group) => (
          <div key={group.risk} className="space-y-2">
            <div className="flex items-center gap-2">
              <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">{group.label}</span>
              <Badge variant="secondary" className={`text-[10px] ${RISK_COLORS[group.risk]}`}>
                {group.risk}
              </Badge>
            </div>
            {group.categories.map((category) => {
              const info = CATEGORY_INFO[category];
              const Icon = info.icon;
              const isAllowed = isCategoryAllowed(category);

              return (
                <div
                  key={category}
                  className="flex items-center justify-between p-3 rounded-lg border bg-card"
                >
                  <div className="flex items-center gap-3">
                    <div className="h-8 w-8 rounded-full bg-muted flex items-center justify-center">
                      <Icon className="h-4 w-4 text-muted-foreground" />
                    </div>
                    <div className="flex-1">
                      <span className="text-sm font-medium">{info.label}</span>
                      <p className="text-xs text-muted-foreground">{info.description}</p>
                    </div>
                  </div>
                  <Switch
                    checked={isAllowed}
                    onCheckedChange={(checked) => handleToggle(category, checked)}
                    disabled={isUpdating}
                  />
                </div>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}
