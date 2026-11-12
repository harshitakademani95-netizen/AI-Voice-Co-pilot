import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { App } from '../App';
import { ContextPanel } from '../components/ContextPanel/ContextPanel';
import { AppContextData } from '../api/types';
import { createMockMediaStream } from './setup';

describe('Week 2: Screen Context Permission & Error Handling', () => {
  const baseMockContext: AppContextData = {
    activeApp: 'VS Code',
    windowTitle: 'main.py - AI Voice Co-Pilot',
    sessionId: 'session-001',
    screenContextEnabled: false, // OFF by default
    screenContextStatus: 'disabled',
    lastUpdated: '10:04:23 AM',
    freshnessState: 'fresh',
    details: 'Active workspace info',
    sources: [
      { id: 'user_voice', label: 'User Voice Request', description: 'Voice input', active: true },
      { id: 'screen_context', label: 'Screen Context', description: 'Visual snapshot', active: false },
    ],
  };

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('keeps Screen Context strictly OFF by default', () => {
    render(<App />);

    const screenSwitch = screen.getByRole('switch', { name: /enable screen context capture/i });
    expect(screenSwitch).toHaveAttribute('aria-checked', 'false');
    expect(screen.getByText(/STATUS: DISABLED \(OFF by Default - Privacy Protected\)/i)).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('explicitly requests browser permission when enabling, and shows ENABLED upon grant', async () => {
    const user = userEvent.setup();
    const mockStream = createMockMediaStream();
    const getDisplayMediaSpy = vi
      .spyOn(navigator.mediaDevices, 'getDisplayMedia')
      .mockResolvedValue(mockStream);

    render(<App />);

    const screenSwitch = screen.getByRole('switch', { name: /enable screen context capture/i });
    expect(screenSwitch).toHaveAttribute('aria-checked', 'false');

    // Click to enable
    await user.click(screenSwitch);

    // Verify browser permission was explicitly requested
    expect(getDisplayMediaSpy).toHaveBeenCalledWith({ video: true });

    // Verify switch updates to enabled
    await waitFor(() => {
      expect(screenSwitch).toHaveAttribute('aria-checked', 'true');
    });
    expect(screen.getByText(/STATUS: ENABLED \(Window & Code Context Active\)/i)).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();

    const liveRegion = document.querySelector('[aria-live="polite"]');
    expect(liveRegion).toHaveTextContent('Screen Context enabled.');
  });

  it('handles permission denied by keeping switch OFF and displaying accessible error alert', async () => {
    const user = userEvent.setup();
    const deniedError = new DOMException('Permission denied by user', 'NotAllowedError');
    vi.spyOn(navigator.mediaDevices, 'getDisplayMedia').mockRejectedValue(deniedError);

    render(<App />);

    const screenSwitch = screen.getByRole('switch', { name: /enable screen context capture/i });
    await user.click(screenSwitch);

    // Must NOT show Enabled
    expect(screenSwitch).toHaveAttribute('aria-checked', 'false');
    expect(screen.queryByText(/STATUS: ENABLED/i)).not.toBeInTheDocument();
    expect(screen.getByText(/STATUS: UNAVAILABLE/i)).toBeInTheDocument();

    // Must show clear accessible error message with role="alert"
    const alertBox = await screen.findByRole('alert');
    expect(alertBox).toHaveTextContent(
      /Screen capture permission was denied or cancelled\. Please allow screen sharing in your browser settings/i
    );
  });

  it('handles permission cancelled (AbortError) by keeping switch OFF and displaying accessible error alert', async () => {
    const user = userEvent.setup();
    const abortError = new DOMException('User cancelled the screen share prompt', 'AbortError');
    vi.spyOn(navigator.mediaDevices, 'getDisplayMedia').mockRejectedValue(abortError);

    render(<App />);

    const screenSwitch = screen.getByRole('switch', { name: /enable screen context capture/i });
    await user.click(screenSwitch);

    expect(screenSwitch).toHaveAttribute('aria-checked', 'false');
    expect(screen.queryByText(/STATUS: ENABLED/i)).not.toBeInTheDocument();

    const alertBox = await screen.findByRole('alert');
    expect(alertBox).toHaveTextContent(
      /Screen capture permission was denied or cancelled\. Please allow screen sharing in your browser settings/i
    );
  });

  it('allows recovery from permission error when user retries and grants access', async () => {
    const user = userEvent.setup();
    const getDisplayMediaSpy = vi.spyOn(navigator.mediaDevices, 'getDisplayMedia');
    getDisplayMediaSpy.mockRejectedValueOnce(new DOMException('Denied', 'NotAllowedError'));

    render(<App />);

    const screenSwitch = screen.getByRole('switch', { name: /enable screen context capture/i });
    await user.click(screenSwitch);

    // Initial failure
    expect(await screen.findByRole('alert')).toBeInTheDocument();
    expect(screenSwitch).toHaveAttribute('aria-checked', 'false');

    // Recovery attempt: user allows access on retry
    const mockStream = createMockMediaStream();
    getDisplayMediaSpy.mockResolvedValueOnce(mockStream);

    await user.click(screenSwitch);

    await waitFor(() => {
      expect(screenSwitch).toHaveAttribute('aria-checked', 'true');
    });
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getByText(/STATUS: ENABLED/i)).toBeInTheDocument();
  });

  it('handles permission unavailable / not supported by displaying accessible error alert', async () => {
    const user = userEvent.setup();
    const unavailableError = new DOMException('getDisplayMedia not supported', 'NotSupportedError');
    vi.spyOn(navigator.mediaDevices, 'getDisplayMedia').mockRejectedValue(unavailableError);

    render(<App />);

    const screenSwitch = screen.getByRole('switch', { name: /enable screen context capture/i });
    await user.click(screenSwitch);

    // Must NOT show Enabled
    expect(screenSwitch).toHaveAttribute('aria-checked', 'false');
    expect(screen.queryByText(/STATUS: ENABLED/i)).not.toBeInTheDocument();

    // Must show clear accessible error message with role="alert"
    const alertBox = await screen.findByRole('alert');
    expect(alertBox).toHaveTextContent(/Screen capture is unavailable or not supported in this browser environment/i);
  });

  it('stops media stream tracks and updates UI state when user disables Screen Context', async () => {
    const user = userEvent.setup();
    const mockStream = createMockMediaStream();
    const stopSpy = vi.spyOn(mockStream.getTracks()[0], 'stop');

    vi.spyOn(navigator.mediaDevices, 'getDisplayMedia').mockResolvedValue(mockStream);

    render(<App />);

    const screenSwitch = screen.getByRole('switch', { name: /enable screen context capture/i });

    // Enable first
    await user.click(screenSwitch);
    await waitFor(() => {
      expect(screenSwitch).toHaveAttribute('aria-checked', 'true');
    });

    // Disable now
    await user.click(screenSwitch);

    // Verify track.stop() was called to release hardware capture
    expect(stopSpy).toHaveBeenCalled();

    // Verify switch is back to OFF
    await waitFor(() => {
      expect(screenSwitch).toHaveAttribute('aria-checked', 'false');
    });
    expect(screen.getByText(/STATUS: DISABLED \(OFF by Default - Privacy Protected\)/i)).toBeInTheDocument();

    const liveRegion = document.querySelector('[aria-live="polite"]');
    expect(liveRegion).toHaveTextContent('Screen Context disabled.');
  });

  it('allows dismissing the screen context error message', async () => {
    const user = userEvent.setup();
    const deniedError = new DOMException('Permission denied', 'NotAllowedError');
    vi.spyOn(navigator.mediaDevices, 'getDisplayMedia').mockRejectedValue(deniedError);

    render(<App />);

    const screenSwitch = screen.getByRole('switch', { name: /enable screen context capture/i });
    await user.click(screenSwitch);

    const alertBox = await screen.findByRole('alert');
    expect(alertBox).toBeInTheDocument();

    const dismissBtn = screen.getByRole('button', { name: /dismiss screen capture error/i });
    await user.click(dismissBtn);

    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('ContextPanel component handles onRequestPermission callback prop for granted and denied cases', async () => {
    const user = userEvent.setup();
    const handleToggle = vi.fn();
    const onRequestGranted = vi.fn().mockResolvedValue(true);

    const { rerender } = render(
      <ContextPanel
        contextData={baseMockContext}
        onToggleScreenContext={handleToggle}
        onRequestPermission={onRequestGranted}
      />
    );

    const toggle = screen.getByRole('switch');
    await user.click(toggle);

    expect(onRequestGranted).toHaveBeenCalledTimes(1);
    expect(handleToggle).toHaveBeenCalledWith(true);

    // Test with onRequestPermission denying access
    const onRequestDenied = vi.fn().mockRejectedValue(new DOMException('Denied', 'NotAllowedError'));
    rerender(
      <ContextPanel
        contextData={baseMockContext}
        onToggleScreenContext={handleToggle}
        onRequestPermission={onRequestDenied}
      />
    );

    await user.click(toggle);
    expect(onRequestDenied).toHaveBeenCalledTimes(1);
    expect(handleToggle).toHaveBeenCalledWith(false);

    const errorAlert = await screen.findByRole('alert');
    expect(errorAlert).toHaveTextContent(/Screen capture permission was denied/i);
  });
});

