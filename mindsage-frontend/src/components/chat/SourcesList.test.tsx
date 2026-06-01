import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { SourcesList } from './SourcesList';
import type { ChatContext } from '@/lib/api';

describe('SourcesList', () => {
  it('renders nothing when sources is empty', () => {
    const { container } = render(<SourcesList sources={[]} />);
    expect(container.innerHTML).toBe('');
  });

  it('renders source count button', () => {
    const sources: ChatContext[] = [
      { id: 1, excerpt: 'Test excerpt', score: 0.85, filename: 'test.txt', perturbed_values: [] },
      { id: 2, excerpt: 'Another excerpt', score: 0.72, filename: 'other.txt', perturbed_values: [] },
    ];
    render(<SourcesList sources={sources} />);
    expect(screen.getByText('2 sources')).toBeInTheDocument();
  });

  it('renders singular "source" for single source', () => {
    const sources: ChatContext[] = [
      { id: 1, excerpt: 'Test excerpt', score: 0.85, filename: 'test.txt', perturbed_values: [] },
    ];
    render(<SourcesList sources={sources} />);
    expect(screen.getByText('1 source')).toBeInTheDocument();
  });

  it('expands to show source details on click', () => {
    const sources: ChatContext[] = [
      { id: 1, excerpt: 'Test excerpt content', score: 0.85, filename: 'document.pdf', perturbed_values: [] },
    ];
    render(<SourcesList sources={sources} />);

    // Click to expand
    fireEvent.click(screen.getByText('1 source'));

    // Should show filename
    expect(screen.getByText('document.pdf')).toBeInTheDocument();
    // Should show score percentage
    expect(screen.getByText('85%')).toBeInTheDocument();
  });

  it('handles undefined score gracefully (no NaN)', () => {
    const sources: ChatContext[] = [
      { id: 1, excerpt: 'Test excerpt', score: undefined as unknown as number, filename: 'test.txt', perturbed_values: [] },
    ];
    render(<SourcesList sources={sources} />);

    fireEvent.click(screen.getByText('1 source'));

    // Should NOT show NaN%
    expect(screen.queryByText('NaN%')).not.toBeInTheDocument();
    // Filename should still render
    expect(screen.getByText('test.txt')).toBeInTheDocument();
  });

  it('shows "Document N" fallback when filename is missing', () => {
    const sources: ChatContext[] = [
      { id: 42, excerpt: 'Test excerpt', score: 0.9, filename: '', perturbed_values: [] },
    ];
    render(<SourcesList sources={sources} />);
    fireEvent.click(screen.getByText('1 source'));
    expect(screen.getByText('Document 42')).toBeInTheDocument();
  });
});
