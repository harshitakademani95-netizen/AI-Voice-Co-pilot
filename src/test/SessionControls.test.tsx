import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SessionControls } from '../components/SessionControls/SessionControls';

describe('SessionControls Component', () => {
  const defaultProps = {
    sessionId: 'session-001',
    status: 'active' as const,
    durationFormatted: '03:05',
    turnCount: 4,
    activeApp: 'VS Code',
    onStart: vi.fn(),
    onPause: vi.fn(),
    onResume: vi.fn(),
    onEnd: vi.fn(),
    onReset: vi.fn(),
  };

  it('renders session information and status badge', () => {
    render(<SessionControls {...defaultProps} />);

    expect(screen.getByText('Session Controls')).toBeInTheDocument();
    expect(screen.getByText('session-001')).toBeInTheDocument();
    expect(screen.getByText('VS Code')).toBeInTheDocument();
    expect(screen.getByText('03:05')).toBeInTheDocument();
    expect(screen.getByText('4')).toBeInTheDocument();
    expect(screen.getByRole('status', { name: /session status is active/i })).toBeInTheDocument();
  });

  it('calls onPause when pause button is clicked during active session', async () => {
    const user = userEvent.setup();
    render(<SessionControls {...defaultProps} status="active" />);

    const pauseBtn = screen.getByRole('button', { name: /pause current session/i });
    await user.click(pauseBtn);

    expect(defaultProps.onPause).toHaveBeenCalledTimes(1);
  });

  it('calls onResume when resume button is clicked during paused session', async () => {
    const user = userEvent.setup();
    render(<SessionControls {...defaultProps} status="paused" />);

    const resumeBtn = screen.getByRole('button', { name: /resume current session/i });
    await user.click(resumeBtn);

    expect(defaultProps.onResume).toHaveBeenCalledTimes(1);
  });

  it('calls onStart when start session button is clicked during idle state', async () => {
    const user = userEvent.setup();
    render(<SessionControls {...defaultProps} status="idle" />);

    const startBtn = screen.getByRole('button', { name: /start new session/i });
    await user.click(startBtn);

    expect(defaultProps.onStart).toHaveBeenCalledTimes(1);
  });

  it('calls onEnd and onReset actions properly', async () => {
    const user = userEvent.setup();
    render(<SessionControls {...defaultProps} status="active" />);

    const endBtn = screen.getByRole('button', { name: /end active session/i });
    await user.click(endBtn);
    expect(defaultProps.onEnd).toHaveBeenCalledTimes(1);

    const resetBtn = screen.getByRole('button', { name: /reset session state/i });
    await user.click(resetBtn);
    expect(defaultProps.onReset).toHaveBeenCalledTimes(1);
  });
});
