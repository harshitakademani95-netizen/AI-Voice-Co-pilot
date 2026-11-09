import { describe, it, expect } from 'vitest';
import { render, screen, waitFor, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from '../App';

describe('Week 2: Session Pause/Resume & Integration in App', () => {
  it('pauses session when Pause button is clicked and stops active capture', async () => {
    const user = userEvent.setup();
    render(<App />);

    expect(screen.getByText('Session Controls')).toBeInTheDocument();
    expect(screen.getByRole('status', { name: /session status is active/i })).toBeInTheDocument();

    // Click Pause
    const pauseBtn = screen.getByRole('button', { name: /pause current session/i });
    await user.click(pauseBtn);

    // Session status changes to paused
    expect(screen.getByRole('status', { name: /session status is paused/i })).toBeInTheDocument();

    // Microphone capture status indicator reflects paused state
    expect(screen.getByRole('status', { name: /microphone status: microphone paused/i })).toBeInTheDocument();

    // Resume button becomes available
    const resumeBtn = screen.getByRole('button', { name: /resume current session/i });
    expect(resumeBtn).toBeInTheDocument();

    // Attempting to simulate voice query while paused is prevented with alert
    const simBtn = screen.getByRole('button', { name: /simulate voice input question/i });
    await user.click(simBtn);

    expect(screen.getByRole('alert')).toHaveTextContent(/session is currently paused/i);
  });

  it('resumes session when Resume button is clicked and restores capture', async () => {
    const user = userEvent.setup();
    render(<App />);

    // Pause first
    const pauseBtn = screen.getByRole('button', { name: /pause current session/i });
    await user.click(pauseBtn);
    expect(screen.getByRole('status', { name: /session status is paused/i })).toBeInTheDocument();

    // Now Resume
    const resumeBtn = screen.getByRole('button', { name: /resume current session/i });
    await user.click(resumeBtn);

    // Session is active again
    expect(screen.getByRole('status', { name: /session status is active/i })).toBeInTheDocument();
    // Microphone is ready/granted again
    expect(screen.getByRole('status', { name: /microphone status: microphone permission granted/i })).toBeInTheDocument();
  });

  it('prevents audio capture when session is ended and shows appropriate alert', async () => {
    const user = userEvent.setup();
    render(<App />);

    // End the active session
    const endBtn = screen.getByRole('button', { name: /end active session/i });
    await user.click(endBtn);

    expect(screen.getByRole('status', { name: /session status is ended/i })).toBeInTheDocument();

    // Attempting to capture audio should be stopped with alert
    const simBtn = screen.getByRole('button', { name: /simulate voice input question/i });
    await user.click(simBtn);

    expect(screen.getByRole('alert')).toHaveTextContent(/session has ended/i);
  });

  it('verifies ARIA live announcements for session, capture, service, and context updates', async () => {
    const user = userEvent.setup();
    render(<App />);

    const liveRegion = document.querySelector('[aria-live="polite"]');
    expect(liveRegion).toBeInTheDocument();
    expect(liveRegion).toHaveAttribute('aria-atomic', 'true');

    // 1. Session paused announcement
    const pauseBtn = screen.getByRole('button', { name: /pause current session/i });
    await user.click(pauseBtn);
    expect(liveRegion).toHaveTextContent('Session paused.');

    // 2. Session resumed announcement
    const resumeBtn = screen.getByRole('button', { name: /resume current session/i });
    await user.click(resumeBtn);
    expect(liveRegion).toHaveTextContent('Session resumed.');

    // 3. Screen Context enabled & disabled announcements
    const screenSwitch = screen.getByRole('switch');
    await user.click(screenSwitch);
    expect(liveRegion).toHaveTextContent('Screen Context enabled.');

    await user.click(screenSwitch);
    expect(liveRegion).toHaveTextContent('Screen Context disabled.');

    // 4. Application state announcements (Loading, Offline, Online, Error)
    const simOfflineBtn = screen.getByRole('button', { name: /simulate offline status/i });
    await user.click(simOfflineBtn);
    expect(liveRegion).toHaveTextContent('Application offline.');

    const simOnlineBtn = screen.getByRole('button', { name: /simulate online status/i });
    await user.click(simOnlineBtn);
    expect(liveRegion).toHaveTextContent('Application online.');

    const simLoadingBtn = screen.getByRole('button', { name: /simulate loading status/i });
    await user.click(simLoadingBtn);
    expect(liveRegion).toHaveTextContent('Loading started.');

    const simErrorBtn = screen.getByRole('button', { name: /simulate error status/i });
    await user.click(simErrorBtn);
    expect(liveRegion).toHaveTextContent('Error occurred.');

    // 5. Microphone unavailable announcement
    const permSelect = screen.getByLabelText(/demo: set microphone permission/i);
    await user.selectOptions(permSelect, 'denied');
    expect(liveRegion).toHaveTextContent('Microphone unavailable.');
  });

  it('runs Week 2 speech interim to final simulation and transcript revision with live announcements', async () => {
    const user = userEvent.setup();
    render(<App />);

    const liveRegion = document.querySelector('[aria-live="polite"]');

    // 1. Simulate interim -> final
    const simSpeechBtn = screen.getByRole('button', { name: /simulate interim to final speech recognition/i });
    await user.click(simSpeechBtn);

    // Shows interim text first
    expect(screen.getByText('INTERIM')).toBeInTheDocument();
    expect(liveRegion).toHaveTextContent(/transcript interim update/i);

    // After simulated recognition, it is replaced with FINAL
    await waitFor(
      () => {
        expect(screen.getByText('FINAL')).toBeInTheDocument();
      },
      { timeout: 2500 }
    );
    expect(liveRegion).toHaveTextContent(/final transcript received/i);

    // 2. Simulate transcript revision
    const reviseBtn = screen.getByRole('button', { name: /simulate transcript revision with history/i });
    await user.click(reviseBtn);

    expect(screen.getByText('REVISED')).toBeInTheDocument();
    expect(liveRegion).toHaveTextContent(/transcript revised/i);
  });

  it('supports full keyboard navigation for interactive controls without mouse', async () => {
    const user = userEvent.setup();
    render(<App />);

    // Tab to Screen Context Switch and toggle with Space
    const screenSwitch = screen.getByRole('switch');
    screenSwitch.focus();
    expect(screenSwitch).toHaveFocus();
    await user.keyboard(' ');
    expect(screenSwitch).toHaveAttribute('aria-checked', 'true');

    await user.keyboard(' ');
    expect(screenSwitch).toHaveAttribute('aria-checked', 'false');

    // Tab to Pause button and press Enter
    const pauseBtn = screen.getByRole('button', { name: /pause current session/i });
    pauseBtn.focus();
    expect(pauseBtn).toHaveFocus();
    await user.keyboard('{Enter}');
    expect(screen.getByRole('status', { name: /session status is paused/i })).toBeInTheDocument();

    // Tab to Resume button and press Enter
    const resumeBtn = screen.getByRole('button', { name: /resume current session/i });
    resumeBtn.focus();
    expect(resumeBtn).toHaveFocus();
    await user.keyboard('{Enter}');
    expect(screen.getByRole('status', { name: /session status is active/i })).toBeInTheDocument();
  });

  it('updates application status dynamically upon real window offline and online network events', async () => {
    render(<App />);
    const liveRegion = document.querySelector('[aria-live="polite"]');

    // Simulate browser going offline
    await act(async () => {
      window.dispatchEvent(new Event('offline'));
    });
    expect(screen.getByRole('status', { name: /application status is offline/i })).toBeInTheDocument();
    expect(liveRegion).toHaveTextContent('Application offline.');

    // Simulate browser returning online
    await act(async () => {
      window.dispatchEvent(new Event('online'));
    });
    expect(screen.getByRole('status', { name: /application status is online/i })).toBeInTheDocument();
    expect(liveRegion).toHaveTextContent('Application online.');
  });
});
