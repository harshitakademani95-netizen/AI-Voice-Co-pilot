import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { CaptureStatus } from '../components/CaptureStatus/CaptureStatus';

describe('Week 2: CaptureStatus Component', () => {
  it('displays microphone capture indicators for listening, paused, denied, and unavailable', () => {
    // 1. Listening
    const { rerender } = render(
      <CaptureStatus
        micPermission="granted"
        micActivity="listening"
        screenContextStatus="disabled"
        appStatus="online"
      />
    );
    expect(screen.getByText('Microphone Listening')).toBeInTheDocument();

    // 2. Paused
    rerender(
      <CaptureStatus
        micPermission="granted"
        micActivity="paused"
        screenContextStatus="disabled"
        appStatus="online"
      />
    );
    expect(screen.getByText('Microphone Paused')).toBeInTheDocument();

    // 3. Denied
    rerender(
      <CaptureStatus
        micPermission="denied"
        micActivity="idle"
        screenContextStatus="disabled"
        appStatus="online"
      />
    );
    expect(screen.getByText('Microphone Permission Denied')).toBeInTheDocument();

    // 4. Unavailable
    rerender(
      <CaptureStatus
        micPermission="granted"
        micActivity="unavailable"
        screenContextStatus="disabled"
        appStatus="online"
      />
    );
    expect(screen.getByText('Microphone Unavailable')).toBeInTheDocument();

    // 5. Session Ended
    rerender(
      <CaptureStatus
        micPermission="granted"
        micActivity="idle"
        sessionStatus="ended"
        screenContextStatus="disabled"
        appStatus="online"
      />
    );
    expect(screen.getByText(/Session Ended/i)).toBeInTheDocument();

    // 6. Muted
    rerender(
      <CaptureStatus
        micPermission="granted"
        micActivity="muted"
        isMuted={true}
        screenContextStatus="disabled"
        appStatus="online"
      />
    );
    expect(screen.getByText('Microphone Muted')).toBeInTheDocument();

    // 7. Speaking
    rerender(
      <CaptureStatus
        micPermission="granted"
        micActivity="speaking"
        screenContextStatus="disabled"
        appStatus="online"
      />
    );
    expect(screen.getByText('Co-Pilot Speaking')).toBeInTheDocument();
  });

  it('displays screen context enabled and disabled capture states', () => {
    const { rerender } = render(
      <CaptureStatus
        micPermission="granted"
        micActivity="idle"
        screenContextStatus="disabled"
        appStatus="online"
      />
    );
    expect(screen.getByText('Screen Context Disabled')).toBeInTheDocument();

    rerender(
      <CaptureStatus
        micPermission="granted"
        micActivity="idle"
        screenContextStatus="active"
        appStatus="online"
      />
    );
    expect(screen.getByText('Screen Context Enabled')).toBeInTheDocument();
  });

  it('displays loading application state', () => {
    render(
      <CaptureStatus
        micPermission="granted"
        micActivity="idle"
        screenContextStatus="disabled"
        appStatus="loading"
      />
    );
    expect(screen.getByText('Loading')).toBeInTheDocument();
  });

  it('displays offline application state with retry button', async () => {
    const handleRetry = vi.fn();
    const user = userEvent.setup();

    render(
      <CaptureStatus
        micPermission="granted"
        micActivity="idle"
        screenContextStatus="disabled"
        appStatus="offline"
        onRetry={handleRetry}
      />
    );

    expect(screen.getByText('Offline')).toBeInTheDocument();
    expect(screen.getByText(/Application is currently in Offline state/i)).toBeInTheDocument();

    const retryBtn = screen.getByRole('button', { name: /retry application connection/i });
    await user.click(retryBtn);
    expect(handleRetry).toHaveBeenCalledTimes(1);
  });

  it('displays error state and executes retry callback', async () => {
    const handleRetry = vi.fn();
    const user = userEvent.setup();

    render(
      <CaptureStatus
        micPermission="granted"
        micActivity="idle"
        screenContextStatus="disabled"
        appStatus="error"
        onRetry={handleRetry}
      />
    );

    expect(screen.getByText('Error')).toBeInTheDocument();
    expect(screen.getByRole('alert')).toBeInTheDocument();

    const retryBtn = screen.getByRole('button', { name: /retry application connection/i });
    await user.click(retryBtn);
    expect(handleRetry).toHaveBeenCalledTimes(1);
  });
});
