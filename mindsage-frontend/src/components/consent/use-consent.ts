import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import type {
  ConsentPreset,
  ConsentSession,
  ConsentSessionUpdate,
  PresetInfo,
  ConsentStatus,
} from './types';

const API_BASE = import.meta.env.VITE_API_URL || '';

// Helper to map nested API response to flat ConsentSession
function mapSessionResponse(data: any): ConsentSession {
  // Handle nested structure from API
  const inner = data.consent || data;
  return {
    session_id: data.session_id || inner.session_id,
    created_at: data.created_at || inner.created_at,
    expires_at: data.expires_at || inner.expires_at,
    ttl_remaining_seconds: inner.ttl_remaining_seconds ?? 3600,
    is_expired: data.is_expired ?? inner.is_expired ?? false,
    consent: {
      allowed_categories: inner.consent?.allowed_categories ?? [],
      blocked_categories: inner.consent?.blocked_categories ?? [],
      exposed_pii_types: inner.consent?.exposed_pii_types ?? [],
    },
    metadata: {
      consent_source: inner.metadata?.consent_source ?? 'api',
      preset_applied: inner.metadata?.preset_applied,
    },
  };
}

// Consent API functions
const consentApi = {
  async getStatus(): Promise<ConsentStatus> {
    const res = await fetch(`${API_BASE}/api/consent/status`);
    if (!res.ok) {
      throw new Error('Failed to get consent status');
    }
    return res.json();
  },

  async getPresets(): Promise<PresetInfo[]> {
    const res = await fetch(`${API_BASE}/api/consent/presets`);
    if (!res.ok) {
      throw new Error('Failed to get presets');
    }
    const data = await res.json();
    // Map 'name' from API to 'id' expected by frontend
    return data.presets.map((p: any) => ({
      id: p.name,
      name: p.name,
      description: p.description,
      allowed_categories: p.allowed_categories,
      blocked_categories: p.blocked_categories,
      exposed_pii_types: p.exposed_pii_types,
    }));
  },

  async createSession(preset?: ConsentPreset): Promise<ConsentSession> {
    const res = await fetch(`${API_BASE}/api/consent/session`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ preset }),
    });
    if (!res.ok) {
      throw new Error('Failed to create consent session');
    }
    const data = await res.json();
    return mapSessionResponse(data);
  },

  async getSession(sessionId: string): Promise<ConsentSession> {
    const res = await fetch(`${API_BASE}/api/consent/session/${sessionId}`);
    if (!res.ok) {
      throw new Error('Session not found');
    }
    const data = await res.json();
    return mapSessionResponse(data);
  },

  async updateSession(
    sessionId: string,
    updates: ConsentSessionUpdate
  ): Promise<ConsentSession> {
    const res = await fetch(`${API_BASE}/api/consent/session/${sessionId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(updates),
    });
    if (!res.ok) {
      throw new Error('Failed to update session');
    }
    const data = await res.json();
    return mapSessionResponse(data);
  },

  async applyPreset(
    sessionId: string,
    preset: ConsentPreset
  ): Promise<ConsentSession> {
    const res = await fetch(
      `${API_BASE}/api/consent/session/${sessionId}/apply-preset`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ preset }),
      }
    );
    if (!res.ok) {
      throw new Error('Failed to apply preset');
    }
    const data = await res.json();
    return mapSessionResponse(data);
  },

  async deleteSession(sessionId: string): Promise<void> {
    await fetch(`${API_BASE}/api/consent/session/${sessionId}`, {
      method: 'DELETE',
    });
  },
};

export function useConsent(sessionId?: string | null) {
  const queryClient = useQueryClient();

  // Query consent status
  const {
    data: status,
    isLoading: isStatusLoading,
  } = useQuery({
    queryKey: ['consentStatus'],
    queryFn: consentApi.getStatus,
    staleTime: 30000,
    retry: 1,
  });

  // Query presets
  const { data: presets } = useQuery({
    queryKey: ['consentPresets'],
    queryFn: consentApi.getPresets,
    staleTime: 60000,
    retry: 1,
  });

  // Query current session
  const {
    data: session,
    isLoading: isSessionLoading,
  } = useQuery({
    queryKey: ['consentSession', sessionId],
    queryFn: () => (sessionId ? consentApi.getSession(sessionId) : null),
    enabled: !!sessionId,
    staleTime: 30000,
    refetchInterval: 60000, // Refresh to check TTL
  });

  // Create session mutation
  const createSession = useMutation({
    mutationFn: (preset?: ConsentPreset) => consentApi.createSession(preset),
    onSuccess: (data) => {
      queryClient.setQueryData(['consentSession', data.session_id], data);
    },
  });

  // Update session mutation
  const updateSession = useMutation({
    mutationFn: (updates: ConsentSessionUpdate) =>
      sessionId ? consentApi.updateSession(sessionId, updates) : Promise.reject('No session'),
    onSuccess: (data) => {
      queryClient.setQueryData(['consentSession', sessionId], data);
    },
  });

  // Apply preset mutation
  const applyPreset = useMutation({
    mutationFn: (preset: ConsentPreset) =>
      sessionId ? consentApi.applyPreset(sessionId, preset) : Promise.reject('No session'),
    onSuccess: (data) => {
      queryClient.setQueryData(['consentSession', sessionId], data);
    },
  });

  // Delete session mutation
  const deleteSession = useMutation({
    mutationFn: () =>
      sessionId ? consentApi.deleteSession(sessionId) : Promise.resolve(),
    onSuccess: () => {
      queryClient.removeQueries({ queryKey: ['consentSession', sessionId] });
    },
  });

  return {
    // Data
    status,
    presets: presets ?? [],
    session,

    // Loading states
    isLoading: isStatusLoading || isSessionLoading,
    isAvailable: status?.available ?? false,

    // Mutations
    createSession,
    updateSession,
    applyPreset,
    deleteSession,
  };
}
