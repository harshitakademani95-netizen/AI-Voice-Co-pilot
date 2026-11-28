import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { DemoRunner } from '../components/DemoRunner/DemoRunner';

describe('DemoRunner Component (Day 7 Demonstration)', () => {
  const defaultProps = {
    onLoadEvents: vi.fn(),
    onAddEvent: vi.fn(),
    onClearEvents: vi.fn(),
    onSimulateVoiceSpeaking: vi.fn(),
  };

  it('renders demo controls and progress indicator', () => {
    render(<DemoRunner {...defaultProps} />);

    expect(screen.getByRole('heading', { name: /day 7 interactive demo/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /advance next demo step/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /autoplay full demonstration/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /load complete fixture scenario/i })).toBeInTheDocument();
  });

  it('allows user to reset steps to start from beginning', async () => {
    const user = userEvent.setup();
    render(<DemoRunner {...defaultProps} />);

    const resetBtn = screen.getByRole('button', { name: /reset demo steps/i });
    await user.click(resetBtn);

    expect(defaultProps.onClearEvents).toHaveBeenCalledTimes(1);
    expect(screen.getByText(/step 0 of/i)).toBeInTheDocument();
  });

  it('advances next step when next step button is clicked', async () => {
    const user = userEvent.setup();
    render(<DemoRunner {...defaultProps} />);

    // Reset first
    await user.click(screen.getByRole('button', { name: /reset demo steps/i }));

    const nextBtn = screen.getByRole('button', { name: /advance next demo step/i });
    await user.click(nextBtn);

    expect(defaultProps.onAddEvent).toHaveBeenCalledTimes(1);
    expect(screen.getByText(/step 1 of/i)).toBeInTheDocument();
  });
});
