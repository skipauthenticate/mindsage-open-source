import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ConsentPresetSelector } from './ConsentPresetSelector';

describe('ConsentPresetSelector', () => {
  const mockOnSelect = vi.fn();

  it('renders the 3 main presets (strict, balanced, open)', () => {
    render(
      <ConsentPresetSelector
        presets={[]}
        onSelect={mockOnSelect}
      />
    );
    expect(screen.getByText('Strict')).toBeInTheDocument();
    expect(screen.getByText('Balanced')).toBeInTheDocument();
    expect(screen.getByText('Open')).toBeInTheDocument();
  });

  it('shows specialized presets toggle', () => {
    render(
      <ConsentPresetSelector
        presets={[]}
        onSelect={mockOnSelect}
      />
    );
    expect(screen.getByText('Specialized presets')).toBeInTheDocument();
  });

  it('reveals specialized presets when toggle is clicked', () => {
    render(
      <ConsentPresetSelector
        presets={[]}
        onSelect={mockOnSelect}
      />
    );

    // Specialized presets should not be visible initially
    expect(screen.queryByText('Health Focus')).not.toBeInTheDocument();

    // Click the toggle
    fireEvent.click(screen.getByText('Specialized presets'));

    // Now they should be visible
    expect(screen.getByText('Health Focus')).toBeInTheDocument();
    expect(screen.getByText('Work Only')).toBeInTheDocument();
    expect(screen.getByText('Recent Only')).toBeInTheDocument();
    expect(screen.getByText('Family Protected')).toBeInTheDocument();
  });

  it('auto-expands specialized presets when one is active', () => {
    render(
      <ConsentPresetSelector
        presets={[]}
        currentPreset="health_focus"
        onSelect={mockOnSelect}
      />
    );
    // Should be visible without clicking
    expect(screen.getByText('Health Focus')).toBeInTheDocument();
  });

  it('calls onSelect when a preset is clicked', () => {
    render(
      <ConsentPresetSelector
        presets={[]}
        onSelect={mockOnSelect}
      />
    );
    fireEvent.click(screen.getByText('Strict'));
    expect(mockOnSelect).toHaveBeenCalledWith('strict');
  });
});
