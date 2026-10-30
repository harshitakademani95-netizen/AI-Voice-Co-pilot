import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MicrophoneControl } from '../components/MicrophoneControl/MicrophoneControl';

describe('MicrophoneControl Component', () => {
  const defaultProps = {
    permission: 'granted' as const,
    activity: 'idle' as const,
    isMuted: false,
    onRequestPermission: vi.fn(),
    onToggleMute: vi.fn(),
    onStartListening: vi.fn(),
    onStopListening: vi.fn(),
    onInterruptAi: vi.fn(),
    onTestVoiceInput: vi.fn(),
  };

  it('renders granted state with microphone action button', () => {
    render(<MicrophoneControl {...defaultProps} />);

    expect(screen.getByText('Microphone & Voice Input')).toBeInTheDocument();
    expect(screen.getByRole('status', { name: /microphone permission is granted/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /start listening to voice input/i })).toBeInTheDocument();
  });

  it('renders prompt state and triggers allow/deny callbacks', async () => {
    const user = userEvent.setup();
    render(<MicrophoneControl {...defaultProps} permission="prompt" />);

    expect(screen.getByText(/microphone permission prompt/i)).toBeInTheDocument();

    const allowBtn = screen.getByRole('button', { name: /allow microphone/i });
    await user.click(allowBtn);
    expect(defaultProps.onRequestPermission).toHaveBeenCalledWith(true);

    const denyBtn = screen.getByRole('button', { name: /deny/i });
    await user.click(denyBtn);
    expect(defaultProps.onRequestPermission).toHaveBeenCalledWith(false);
  });

  it('renders denied state and provides a grant recovery button', async () => {
    const user = userEvent.setup();
    render(<MicrophoneControl {...defaultProps} permission="denied" />);

    expect(screen.getByText(/microphone permission denied/i)).toBeInTheDocument();

    const grantBtn = screen.getByRole('button', { name: /grant microphone permission/i });
    await user.click(grantBtn);
    expect(defaultProps.onRequestPermission).toHaveBeenCalledWith(true);
  });

  it('toggles mute/unmute state when mute button is clicked', async () => {
    const user = userEvent.setup();
    render(<MicrophoneControl {...defaultProps} isMuted={false} />);

    const muteBtn = screen.getByRole('button', { name: /mute microphone/i });
    await user.click(muteBtn);
    expect(defaultProps.onToggleMute).toHaveBeenCalledTimes(1);
  });

  it('allows user to interrupt AI speech when AI is speaking (FR-VOICE-004)', async () => {
    const user = userEvent.setup();
    render(<MicrophoneControl {...defaultProps} activity="speaking" />);

    const interruptBtn = screen.getByRole('button', { name: /interrupt ai response/i });
    expect(interruptBtn).toBeInTheDocument();

    await user.click(interruptBtn);
    expect(defaultProps.onInterruptAi).toHaveBeenCalledTimes(1);
  });
});
