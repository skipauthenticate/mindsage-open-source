// Consent type definitions based on backend consent_config.py and consent_session.py

export type ConsentPreset =
  | 'strict'
  | 'balanced'
  | 'open'
  | 'health_focus'
  | 'work_only'
  | 'recent_only'
  | 'family_protected';

export type DataCategory =
  | 'health'
  | 'finance'
  | 'work'
  | 'personal'
  | 'social'
  | 'legal'
  | 'travel'
  | 'education'
  | 'programming'
  | 'sports'
  | 'technology'
  | 'shopping'
  | 'family'
  | 'general';

export type PIIType =
  | 'PERSON'
  | 'EMAIL_ADDRESS'
  | 'PHONE_NUMBER'
  | 'LOCATION'
  | 'DATE_TIME'
  | 'URL'
  | 'IP_ADDRESS'
  | 'US_SSN'
  | 'CREDIT_CARD'
  | 'US_BANK_NUMBER'
  | 'IBAN_CODE'
  | 'US_PASSPORT'
  | 'US_DRIVER_LICENSE';

export type PIIRiskLevel = 'low' | 'medium' | 'high' | 'critical';

// Critical PII types that cannot be exposed
export const CRITICAL_PII_TYPES: PIIType[] = [
  'US_SSN',
  'CREDIT_CARD',
  'US_BANK_NUMBER',
  'IBAN_CODE',
  'US_PASSPORT',
  'US_DRIVER_LICENSE',
];

export const PII_RISK_LEVELS: Record<PIIType, PIIRiskLevel> = {
  'DATE_TIME': 'low',
  'URL': 'low',
  'LOCATION': 'medium',
  'PERSON': 'medium',
  'EMAIL_ADDRESS': 'medium',
  'PHONE_NUMBER': 'medium',
  'IP_ADDRESS': 'medium',
  'US_DRIVER_LICENSE': 'high',
  'US_PASSPORT': 'high',
  'US_SSN': 'critical',
  'CREDIT_CARD': 'critical',
  'US_BANK_NUMBER': 'critical',
  'IBAN_CODE': 'critical',
};

export interface PresetInfo {
  id: ConsentPreset;
  name: string;
  description: string;
  allowed_categories: DataCategory[];
  blocked_categories: DataCategory[];
  exposed_pii_types: PIIType[];
}

export interface ConsentSession {
  session_id: string;
  created_at: string;
  expires_at: string;
  ttl_remaining_seconds: number;
  is_expired: boolean;
  consent: {
    allowed_categories: DataCategory[];
    blocked_categories: DataCategory[];
    exposed_pii_types: PIIType[];
  };
  metadata: {
    consent_source: 'ui' | 'api' | 'natural_language';
    preset_applied?: ConsentPreset;
  };
}

export interface ConsentStatus {
  available: boolean;
  active_sessions: number;
  presets_available: ConsentPreset[];
  categories_available: DataCategory[];
}

export interface ConsentSessionUpdate {
  allowed_categories?: DataCategory[];
  blocked_categories?: DataCategory[];
  exposed_pii_types?: PIIType[];
}
