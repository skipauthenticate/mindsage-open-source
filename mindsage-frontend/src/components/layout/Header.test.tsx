import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { Header } from './Header';

// Mock ExtractionStatus to avoid query provider requirement
vi.mock('@/components/ExtractionStatus', () => ({
  ExtractionStatus: () => <div data-testid="extraction-status" />,
}));

// Mock ThemeProvider
vi.mock('@/components/ThemeProvider', () => ({
  useTheme: () => ({ theme: 'dark', setTheme: vi.fn(), resolvedTheme: 'dark' }),
}));

function renderHeader() {
  return render(
    <MemoryRouter initialEntries={['/dashboard']}>
      <Header />
    </MemoryRouter>
  );
}

describe('Header', () => {
  it('renders navigation links', () => {
    renderHeader();
    expect(screen.getByText('Dashboard')).toBeInTheDocument();
    expect(screen.getByText('Explore')).toBeInTheDocument();
  });

  it('renders logo', () => {
    renderHeader();
    expect(screen.getByText('MindSage')).toBeInTheDocument();
  });

  it('does not render a non-functional settings button', () => {
    renderHeader();
    // There should be no settings button that does nothing
    const buttons = screen.getAllByRole('button');
    // Only the theme toggle button should exist as an icon-only button in nav
    const settingsButtons = buttons.filter((btn) =>
      btn.querySelector('svg.lucide-settings')
    );
    expect(settingsButtons).toHaveLength(0);
  });
});
