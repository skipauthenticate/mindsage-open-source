import {
  type LucideIcon,
  User,
  Mail,
  Phone,
  MapPin,
  Calendar,
  Link,
  Wifi,
  CreditCard,
  Lock,
  FileText,
  Car,
} from 'lucide-react';
import { Switch } from '@/components/ui/switch';
import { Badge } from '@/components/ui/badge';
import {
  CRITICAL_PII_TYPES,
  PII_RISK_LEVELS,
  type PIIType,
  type ConsentSession,
  type PIIRiskLevel,
} from './types';

interface PIITypeFilterProps {
  session: ConsentSession | null | undefined;
  onUpdate: (update: { exposed_pii_types: PIIType[] }) => void;
  isUpdating?: boolean;
}

interface PIIInfo {
  label: string;
  description: string;
  icon: LucideIcon;
  example: string;
}

const PII_INFO: Record<PIIType, PIIInfo> = {
  PERSON: {
    label: 'Names',
    description: 'Personal names',
    icon: User,
    example: 'John Smith → Michael Chen',
  },
  EMAIL_ADDRESS: {
    label: 'Email',
    description: 'Email addresses',
    icon: Mail,
    example: 'john@example.com → user123@mail.com',
  },
  PHONE_NUMBER: {
    label: 'Phone',
    description: 'Phone numbers',
    icon: Phone,
    example: '555-1234 → 555-5678',
  },
  LOCATION: {
    label: 'Locations',
    description: 'Addresses and places',
    icon: MapPin,
    example: '123 Main St → 456 Oak Ave',
  },
  DATE_TIME: {
    label: 'Dates',
    description: 'Dates and times',
    icon: Calendar,
    example: 'Jan 15, 2024 → Mar 22, 2024',
  },
  URL: {
    label: 'URLs',
    description: 'Web addresses',
    icon: Link,
    example: 'example.com/user → example.com/anon',
  },
  IP_ADDRESS: {
    label: 'IP Address',
    description: 'Network addresses',
    icon: Wifi,
    example: '192.168.1.1 → 10.0.0.1',
  },
  US_SSN: {
    label: 'SSN',
    description: 'Social Security Numbers',
    icon: Lock,
    example: 'Always anonymized',
  },
  CREDIT_CARD: {
    label: 'Credit Card',
    description: 'Payment card numbers',
    icon: CreditCard,
    example: 'Always anonymized',
  },
  US_BANK_NUMBER: {
    label: 'Bank Account',
    description: 'Bank account numbers',
    icon: CreditCard,
    example: 'Always anonymized',
  },
  IBAN_CODE: {
    label: 'IBAN',
    description: 'International bank codes',
    icon: CreditCard,
    example: 'Always anonymized',
  },
  US_PASSPORT: {
    label: 'Passport',
    description: 'Passport numbers',
    icon: FileText,
    example: 'Always anonymized',
  },
  US_DRIVER_LICENSE: {
    label: 'Driver License',
    description: 'License numbers',
    icon: Car,
    example: 'Always anonymized',
  },
};

const RISK_COLORS: Record<PIIRiskLevel, string> = {
  low: 'bg-green-500/10 text-green-600',
  medium: 'bg-amber-500/10 text-amber-600',
  high: 'bg-red-500/10 text-red-600',
  critical: 'bg-red-600/20 text-red-700',
};

// Order PII types by risk level
const ORDERED_PII_TYPES: PIIType[] = [
  'DATE_TIME',
  'URL',
  'LOCATION',
  'PERSON',
  'EMAIL_ADDRESS',
  'PHONE_NUMBER',
  'IP_ADDRESS',
  'US_DRIVER_LICENSE',
  'US_PASSPORT',
  'US_SSN',
  'CREDIT_CARD',
  'US_BANK_NUMBER',
  'IBAN_CODE',
];

export function PIITypeFilter({
  session,
  onUpdate,
  isUpdating,
}: PIITypeFilterProps) {
  const exposedTypes = session?.consent?.exposed_pii_types ?? [];

  const isExposed = (piiType: PIIType): boolean => {
    return exposedTypes.includes(piiType);
  };

  const isCritical = (piiType: PIIType): boolean => {
    return CRITICAL_PII_TYPES.includes(piiType);
  };

  const handleToggle = (piiType: PIIType, exposed: boolean) => {
    if (isCritical(piiType)) return; // Cannot expose critical types

    let newExposed = [...exposedTypes];
    if (exposed) {
      if (!newExposed.includes(piiType)) {
        newExposed.push(piiType);
      }
    } else {
      newExposed = newExposed.filter((t) => t !== piiType);
    }

    onUpdate({ exposed_pii_types: newExposed });
  };

  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">
        Control which personal information types are anonymized. Critical data is always protected.
      </p>
      <div className="space-y-2">
        {ORDERED_PII_TYPES.map((piiType) => {
          const info = PII_INFO[piiType];
          const Icon = info.icon;
          const risk = PII_RISK_LEVELS[piiType];
          const critical = isCritical(piiType);
          const exposed = isExposed(piiType);

          return (
            <div
              key={piiType}
              className={`flex items-center justify-between p-3 rounded-lg border bg-card ${
                critical ? 'opacity-60' : ''
              }`}
            >
              <div className="flex items-center gap-3">
                <div className="h-8 w-8 rounded-full bg-muted flex items-center justify-center">
                  <Icon className="h-4 w-4 text-muted-foreground" />
                </div>
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium">{info.label}</span>
                    <Badge variant="secondary" className={`text-xs ${RISK_COLORS[risk]}`}>
                      {risk}
                    </Badge>
                    {critical && (
                      <Badge variant="secondary" className="text-xs bg-muted">
                        <Lock className="h-3 w-3 mr-1" />
                        Protected
                      </Badge>
                    )}
                  </div>
                  <p className="text-xs text-muted-foreground">{info.example}</p>
                </div>
              </div>
              {critical ? (
                <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <Lock className="h-3 w-3" />
                  <span>Always protected</span>
                </div>
              ) : (
                <div className="flex items-center gap-2">
                  <span className="text-xs text-muted-foreground">
                    {exposed ? 'Show original' : 'Anonymize'}
                  </span>
                  <Switch
                    checked={exposed}
                    onCheckedChange={(checked) => handleToggle(piiType, checked)}
                    disabled={isUpdating}
                  />
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
