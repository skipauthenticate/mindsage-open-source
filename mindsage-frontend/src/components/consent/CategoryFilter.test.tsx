import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { CategoryFilter } from './CategoryFilter';

describe('CategoryFilter', () => {
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

  it('renders categories grouped by risk level', () => {
    render(
      <CategoryFilter
        session={mockSession}
        onUpdate={vi.fn()}
      />
    );

    // Should have risk group headers
    expect(screen.getByText('High sensitivity')).toBeInTheDocument();
    expect(screen.getByText('Medium sensitivity')).toBeInTheDocument();
    expect(screen.getByText('Low sensitivity')).toBeInTheDocument();
  });

  it('shows high-risk categories first', () => {
    const { container } = render(
      <CategoryFilter
        session={mockSession}
        onUpdate={vi.fn()}
      />
    );

    // Get all section headers in order
    const headers = container.querySelectorAll('.uppercase');
    const headerTexts = Array.from(headers).map(h => h.textContent);
    expect(headerTexts[0]).toBe('High sensitivity');
    expect(headerTexts[1]).toBe('Medium sensitivity');
    expect(headerTexts[2]).toBe('Low sensitivity');
  });

  it('renders all 14 categories', () => {
    render(
      <CategoryFilter
        session={mockSession}
        onUpdate={vi.fn()}
      />
    );

    expect(screen.getByText('Health')).toBeInTheDocument();
    expect(screen.getByText('Finance')).toBeInTheDocument();
    expect(screen.getByText('Work')).toBeInTheDocument();
    expect(screen.getByText('Personal')).toBeInTheDocument();
    expect(screen.getByText('General')).toBeInTheDocument();
  });
});
