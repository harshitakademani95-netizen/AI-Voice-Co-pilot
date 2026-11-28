import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { AppShell } from '../components/AppShell/AppShell';

describe('AppShell Component', () => {
  it('renders skip link for keyboard accessibility', () => {
    render(
      <AppShell sidebarControls={<div>Sidebar</div>}>
        <div>Main content</div>
      </AppShell>
    );

    const skipLink = screen.getByRole('link', { name: /skip to main content/i });
    expect(skipLink).toBeInTheDocument();
    expect(skipLink).toHaveAttribute('href', '#main-content');
  });

  it('renders accessible semantic landmarks', () => {
    render(
      <AppShell sidebarControls={<div>Sidebar content</div>}>
        <div>Primary workspace area</div>
      </AppShell>
    );

    expect(screen.getByRole('banner')).toBeInTheDocument();
    expect(screen.getByRole('main')).toHaveAttribute('id', 'main-content');
    expect(screen.getByRole('complementary', { name: /session & input controls/i })).toBeInTheDocument();
    expect(screen.getByRole('contentinfo')).toBeInTheDocument();
  });

  it('displays workstream badge and app branding', () => {
    render(
      <AppShell sidebarControls={<div>Sidebar</div>}>
        <div>Main</div>
      </AppShell>
    );

    expect(screen.getByText('AI Voice Co-Pilot')).toBeInTheDocument();
    expect(screen.getByText('W6: Frontend & UX')).toBeInTheDocument();
  });
});
