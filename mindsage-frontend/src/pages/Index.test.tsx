import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import Index from './Index';

function renderDashboard() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <Index />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe('Dashboard Page', () => {
  it('renders without crashing', () => {
    const { container } = renderDashboard();
    expect(container).toBeInTheDocument();
  });

  it('chat panel uses responsive height instead of fixed 600px', () => {
    const { container } = renderDashboard();
    // The chat container should NOT have a fixed h-[600px]
    const fixedHeightEl = container.querySelector('.h-\\[600px\\]');
    expect(fixedHeightEl).toBeNull();

    // Should have a calc-based responsive height
    const allEls = container.querySelectorAll('div');
    const hasCalcHeight = Array.from(allEls).some(el =>
      el.className.includes('h-[calc(')
    );
    expect(hasCalcHeight).toBe(true);
  });

  it('chat panel appears first in DOM order on mobile (order-first)', () => {
    const { container } = renderDashboard();
    const chatContainer = container.querySelector('.order-first');
    expect(chatContainer).toBeInTheDocument();
    // The left column should have order-last on mobile
    const leftCol = container.querySelector('.order-last.lg\\:order-first');
    expect(leftCol).toBeInTheDocument();
  });
});
