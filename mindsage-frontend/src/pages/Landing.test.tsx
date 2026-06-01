import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import Landing from './Landing';

function renderLanding() {
  return render(
    <MemoryRouter>
      <Landing />
    </MemoryRouter>
  );
}

describe('Landing Page', () => {
  it('renders the hero headline', () => {
    renderLanding();
    expect(screen.getByText('Index everything.')).toBeInTheDocument();
    expect(screen.getByText('Expose nothing.')).toBeInTheDocument();
  });

  it('has a working GitHub link (not a dead button)', () => {
    renderLanding();
    const githubLink = screen.getByText('View on GitHub').closest('a');
    expect(githubLink).toHaveAttribute('href', expect.stringContaining('github.com'));
    expect(githubLink).toHaveAttribute('target', '_blank');
    expect(githubLink).toHaveAttribute('rel', expect.stringContaining('noopener'));
  });

  it('shows honest capability stats, not fake metrics', () => {
    renderLanding();
    // Should describe capabilities, not claim user-specific stats
    expect(screen.getByText('Documents Supported')).toBeInTheDocument();
    expect(screen.getByText('Cloud Dependencies')).toBeInTheDocument();
    expect(screen.getByText('Local Processing')).toBeInTheDocument();
    // Should NOT show misleading labels
    expect(screen.queryByText('Documents Indexed')).not.toBeInTheDocument();
    expect(screen.queryByText('Data Sent to Cloud')).not.toBeInTheDocument();
  });

  it('nav has distinct destinations (Dashboard, Explore, Get Started)', () => {
    renderLanding();
    const dashboardLinks = screen.getAllByText('Dashboard');
    // Desktop nav should link to /dashboard
    const dashLink = dashboardLinks[0].closest('a');
    expect(dashLink).toHaveAttribute('href', '/dashboard');

    // Explore link should exist and go to /explore
    const exploreLinks = screen.getAllByText('Explore');
    const exploreLink = exploreLinks[0].closest('a');
    expect(exploreLink).toHaveAttribute('href', '/explore');

    // Get Started should scroll (anchor link), not duplicate /dashboard
    const getStartedButtons = screen.getAllByText('Get Started');
    const getStartedLink = getStartedButtons[0].closest('a');
    expect(getStartedLink).toHaveAttribute('href', '#get-started');
  });

  it('CTA section has the anchor target for Get Started', () => {
    renderLanding();
    const ctaSection = document.getElementById('get-started');
    expect(ctaSection).toBeInTheDocument();
  });

  it('bottom CTA says "Open Dashboard" (not redundant "Get Started")', () => {
    renderLanding();
    expect(screen.getByText('Open Dashboard')).toBeInTheDocument();
  });

  it('footer has navigation links', () => {
    renderLanding();
    const footer = document.querySelector('footer');
    expect(footer).toBeInTheDocument();

    // Footer should contain useful links
    const footerLinks = footer!.querySelectorAll('a');
    const hrefs = Array.from(footerLinks).map(a => a.getAttribute('href'));
    expect(hrefs).toContain('/dashboard');
    expect(hrefs).toContain('/explore');
    expect(hrefs.some(h => h?.includes('github.com'))).toBe(true);
  });

  it('mobile nav toggle button exists', () => {
    renderLanding();
    // The mobile nav should have a toggle button (Menu icon)
    // It's inside a div with className "sm:hidden"
    const mobileNavContainer = document.querySelector('.sm\\:hidden');
    expect(mobileNavContainer).toBeInTheDocument();
    const toggleButton = mobileNavContainer!.querySelector('button');
    expect(toggleButton).toBeInTheDocument();
  });

  it('renders all 6 feature cards', () => {
    renderLanding();
    expect(screen.getByText('Semantic Search')).toBeInTheDocument();
    expect(screen.getByText('Knowledge Graph')).toBeInTheDocument();
    expect(screen.getByText('Multi-Source Indexing')).toBeInTheDocument();
    expect(screen.getByText('Privacy First')).toBeInTheDocument();
    expect(screen.getByText('Lightning Fast')).toBeInTheDocument();
    expect(screen.getByText('Rich Previews')).toBeInTheDocument();
  });

  it('renders the 3-step how-it-works section', () => {
    renderLanding();
    expect(screen.getByText('Connect Your Sources')).toBeInTheDocument();
    expect(screen.getByText('Index Everything')).toBeInTheDocument();
    expect(screen.getByText('Search & Explore')).toBeInTheDocument();
  });
});
