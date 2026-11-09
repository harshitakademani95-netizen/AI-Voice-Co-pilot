import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ContextPanel } from '../components/ContextPanel/ContextPanel';
import { AppContextData } from '../api/types';

describe('Week 2: ContextPanel Component', () => {
  const mockContextData: AppContextData = {
    activeApp: 'VS Code',
    windowTitle: 'main.py - AI Voice Co-Pilot',
    sessionId: 'session-001',
    screenContextEnabled: false, // OFF by default
    screenContextStatus: 'disabled',
    lastUpdated: '10:04:23 AM',
    freshnessState: 'fresh',
    details: 'ModuleNotFoundError in main.py:12',
    sources: [
      { id: 'user_voice', label: 'User Voice Request', description: 'Voice input', active: true },
      { id: 'active_app', label: 'Active Application', description: 'Window tracking', active: true },
      { id: 'screen_context', label: 'Screen Context', description: 'Visual snapshot', active: false },
    ],
  };

  it('verifies Screen Context is OFF by default', () => {
    render(
      <ContextPanel
        contextData={mockContextData}
        onToggleScreenContext={vi.fn()}
      />
    );

    const toggle = screen.getByRole('switch');
    expect(toggle).toHaveAttribute('aria-checked', 'false');
    expect(screen.getByText(/STATUS: DISABLED \(OFF by Default - Privacy Protected\)/i)).toBeInTheDocument();
  });

  it('allows user to enable and disable Screen Context with accessible switch', async () => {
    const handleToggle = vi.fn();
    const user = userEvent.setup();

    const { rerender } = render(
      <ContextPanel
        contextData={mockContextData}
        onToggleScreenContext={handleToggle}
      />
    );

    const toggle = screen.getByRole('switch');
    await user.click(toggle);
    expect(handleToggle).toHaveBeenCalledWith(true);

    // Rerender as enabled
    rerender(
      <ContextPanel
        contextData={{
          ...mockContextData,
          screenContextEnabled: true,
          screenContextStatus: 'active',
        }}
        onToggleScreenContext={handleToggle}
      />
    );

    const enabledToggle = screen.getByRole('switch');
    expect(enabledToggle).toHaveAttribute('aria-checked', 'true');
    expect(screen.getByText(/STATUS: ENABLED/i)).toBeInTheDocument();

    // Disable it again
    await user.click(enabledToggle);
    expect(handleToggle).toHaveBeenCalledWith(false);
  });

  it('supports keyboard navigation for Screen Context switch', async () => {
    const handleToggle = vi.fn();
    const user = userEvent.setup();

    render(
      <ContextPanel
        contextData={mockContextData}
        onToggleScreenContext={handleToggle}
      />
    );

    const toggle = screen.getByRole('switch');
    toggle.focus();
    expect(toggle).toHaveFocus();

    await user.keyboard(' '); // Space triggers button switch
    expect(handleToggle).toHaveBeenCalledWith(true);
  });

  it('renders application context, window title, freshness, and sources correctly', () => {
    render(
      <ContextPanel
        contextData={mockContextData}
        onToggleScreenContext={vi.fn()}
      />
    );

    expect(screen.getByText('Context & Sources')).toBeInTheDocument();
    expect(screen.getByText('VS Code')).toBeInTheDocument();
    expect(screen.getByText('main.py - AI Voice Co-Pilot')).toBeInTheDocument();
    expect(screen.getByText(/Last Updated: 10:04:23 AM/i)).toBeInTheDocument();
    expect(screen.getByText('User Voice Request')).toBeInTheDocument();
    expect(screen.getByText('Active Application')).toBeInTheDocument();
  });

  it('renders meaningful empty state when context is empty or cleared', () => {
    render(
      <ContextPanel
        contextData={{
          ...mockContextData,
          activeApp: '',
          windowTitle: '',
          details: undefined,
          terminalOutput: undefined,
        }}
        onToggleScreenContext={vi.fn()}
      />
    );

    expect(screen.getByText(/No workspace context captured yet/i)).toBeInTheDocument();
  });
});

