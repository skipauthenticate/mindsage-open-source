import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { PIITypeFilter } from './PIITypeFilter';

describe('PIITypeFilter', () => {
  const mockSession = {
    session_id: 'test-session',
    consent: {
      allowed_categories: [],
      blocked_categories: [],
      exposed_pii_types: [],
    },
    metadata: {
      preset_applied: 'balanced' as const,
      created_at: new Date().toISOString(),
    },
  };

  it('renders all PII types', () => {
    render(
      <PIITypeFilter
        session={mockSession}
        onUpdate={vi.fn()}
      />
    );

    expect(screen.getByText('Names')).toBeInTheDocument();
    expect(screen.getByText('Email')).toBeInTheDocument();
    expect(screen.getByText('SSN')).toBeInTheDocument();
    expect(screen.getByText('Credit Card')).toBeInTheDocument();
  });

  it('shows "Always protected" text for critical PII types instead of a switch', () => {
    render(
      <PIITypeFilter
        session={mockSession}
        onUpdate={vi.fn()}
      />
    );

    // Critical types should show "Always protected" instead of a switch
    const protectedLabels = screen.getAllByText('Always protected');
    expect(protectedLabels.length).toBeGreaterThan(0);
  });

  it('shows toggle switches for non-critical PII types', () => {
    const { container } = render(
      <PIITypeFilter
        session={mockSession}
        onUpdate={vi.fn()}
      />
    );

    // Non-critical types should have switches
    const switches = container.querySelectorAll('[role="switch"]');
    expect(switches.length).toBeGreaterThan(0);

    // All visible switches should be enabled (not disabled)
    switches.forEach(s => {
      expect(s).not.toBeDisabled();
    });
  });
});
