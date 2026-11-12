import React from 'react';
import {
  Mic,
  MicOff,
  PauseCircle,
  AlertTriangle,
  Monitor,
  MonitorOff,
  Wifi,
  WifiOff,
  RotateCcw,
  Loader2,
  CheckCircle2,
  ShieldAlert,
  Square,
  Volume2,
} from 'lucide-react';
import {
  MicrophonePermissionState,
  MicrophoneActivityState,
  ApplicationStatusState,
  ScreenContextStatus,
  SessionStatus,
} from '../../api/types';
import './CaptureStatus.css';

interface CaptureStatusProps {
  micPermission: MicrophonePermissionState;
  micActivity: MicrophoneActivityState;
  isMuted?: boolean;
  sessionStatus?: SessionStatus;
  screenContextStatus: ScreenContextStatus;
  appStatus: ApplicationStatusState;
  onRetry?: () => void;
  onSetAppStatus?: (status: ApplicationStatusState) => void;
}

export const CaptureStatus: React.FC<CaptureStatusProps> = ({
  micPermission,
  micActivity,
  isMuted,
  sessionStatus,
  screenContextStatus,
  appStatus,
  onRetry,
  onSetAppStatus,
}) => {
  // Determine current microphone capture state
  const getMicCaptureState = () => {
    if (sessionStatus === 'ended') {
      return {
        label: 'Session Ended (Inactive)',
        icon: <Square size={13} aria-hidden="true" />,
        badgeClass: 'badge-offline',
      };
    }
    if (micActivity === 'muted' || isMuted) {
      return {
        label: 'Microphone Muted',
        icon: <MicOff size={14} aria-hidden="true" />,
        badgeClass: 'badge-paused',
      };
    }
    if (micActivity === 'paused') {
      return {
        label: 'Microphone Paused',
        icon: <PauseCircle size={14} aria-hidden="true" />,
        badgeClass: 'badge-paused',
      };
    }
    if (micActivity === 'unavailable' || micPermission === 'denied') {
      return {
        label: micPermission === 'denied' ? 'Microphone Permission Denied' : 'Microphone Unavailable',
        icon: <MicOff size={14} aria-hidden="true" />,
        badgeClass: 'badge-denied',
      };
    }
    if (micActivity === 'listening') {
      return {
        label: 'Microphone Listening',
        icon: <Mic size={14} className="pulse-icon" aria-hidden="true" />,
        badgeClass: 'badge-listening',
      };
    }
    if (micActivity === 'processing') {
      return {
        label: 'Processing Audio',
        icon: <Loader2 size={14} className="spin-icon" aria-hidden="true" />,
        badgeClass: 'badge-processing',
      };
    }
    if (micActivity === 'speaking') {
      return {
        label: 'Co-Pilot Speaking',
        icon: <Volume2 size={14} className="pulse-icon" aria-hidden="true" />,
        badgeClass: 'badge-listening',
      };
    }
    if (micPermission === 'granted') {
      return {
        label: 'Microphone Permission Granted',
        icon: <CheckCircle2 size={14} aria-hidden="true" />,
        badgeClass: 'badge-granted',
      };
    }
    return {
      label: 'Microphone Permission Required',
      icon: <ShieldAlert size={14} aria-hidden="true" />,
      badgeClass: 'badge-prompt',
    };
  };

  // Determine Screen Context State
  const getScreenContextState = () => {
    if (screenContextStatus === 'active') {
      return {
        label: 'Screen Context Enabled',
        icon: <Monitor size={14} aria-hidden="true" />,
        badgeClass: 'badge-active',
      };
    }
    if (screenContextStatus === 'loading') {
      return {
        label: 'Capturing Screen Context',
        icon: <Loader2 size={14} className="spin-icon" aria-hidden="true" />,
        badgeClass: 'badge-loading',
      };
    }
    if (screenContextStatus === 'denied') {
      return {
        label: 'Screen Context Permission Denied',
        icon: <ShieldAlert size={14} aria-hidden="true" />,
        badgeClass: 'badge-denied',
      };
    }
    if (screenContextStatus === 'unavailable') {
      return {
        label: 'Screen Context Unavailable',
        icon: <AlertTriangle size={14} aria-hidden="true" />,
        badgeClass: 'badge-unavailable',
      };
    }
    return {
      label: 'Screen Context Disabled',
      icon: <MonitorOff size={14} aria-hidden="true" />,
      badgeClass: 'badge-disabled',
    };
  };

  // Determine Application Status State
  const getAppStatusState = () => {
    switch (appStatus) {
      case 'online':
        return {
          label: 'Online',
          detail: 'Mock Service Connected',
          icon: <Wifi size={14} aria-hidden="true" />,
          badgeClass: 'badge-online',
        };
      case 'offline':
        return {
          label: 'Offline',
          detail: 'Service Disconnected',
          icon: <WifiOff size={14} aria-hidden="true" />,
          badgeClass: 'badge-offline',
        };
      case 'loading':
        return {
          label: 'Loading',
          detail: 'Synchronizing...',
          icon: <Loader2 size={14} className="spin-icon" aria-hidden="true" />,
          badgeClass: 'badge-loading',
        };
      case 'error':
        return {
          label: 'Error',
          detail: 'Connection Failure',
          icon: <AlertTriangle size={14} aria-hidden="true" />,
          badgeClass: 'badge-error',
        };
    }
  };

  const micState = getMicCaptureState();
  const screenState = getScreenContextState();
  const appState = getAppStatusState();

  return (
    <section
      className="capture-status-card"
      aria-labelledby="capture-status-heading"
      role="region"
    >
      <div className="capture-status-header">
        <h2 id="capture-status-heading" className="capture-status-title">
          System & Capture Status
        </h2>

        {/* Accessible live region announcing state changes */}
        <div
          role="status"
          aria-live="polite"
          aria-label={`Application status is ${appStatus}`}
          className="app-status-badge-wrap"
        >
          <span className={`status-badge ${appState.badgeClass}`}>
            {appState.icon}
            <span>{appState.label}</span>
          </span>
        </div>
      </div>

      <div className="capture-status-grid">
        {/* Microphone State */}
        <div className="capture-indicator-item" role="status" aria-label={`Microphone status: ${micState.label}`}>
          <div className="indicator-label">Microphone State</div>
          <div className={`indicator-badge ${micState.badgeClass}`}>
            {micState.icon}
            <span>{micState.label}</span>
          </div>
        </div>

        {/* Screen Context State */}
        <div className="capture-indicator-item" role="status" aria-label={`Screen context status: ${screenState.label}`}>
          <div className="indicator-label">Screen Context State</div>
          <div className={`indicator-badge ${screenState.badgeClass}`}>
            {screenState.icon}
            <span>{screenState.label}</span>
          </div>
        </div>
      </div>

      {/* When in Error or Offline state, show message & Retry action */}
      {(appStatus === 'error' || appStatus === 'offline') && (
        <div className="app-status-alert-box" role="alert">
          <div className="status-alert-content">
            <AlertTriangle size={16} aria-hidden="true" />
            <span>
              {appStatus === 'error'
                ? 'System encountered an error. Network service is degraded.'
                : 'Application is currently in Offline state. Live updates are paused.'}
            </span>
          </div>
          {onRetry && (
            <button
              type="button"
              className="btn-status-retry"
              onClick={onRetry}
              aria-label="Retry application connection"
            >
              <RotateCcw size={13} aria-hidden="true" />
              <span>Retry</span>
            </button>
          )}
        </div>
      )}

      {/* Reviewer / Demo Controls to simulate App States */}
      {onSetAppStatus && (
        <div className="status-simulation-bar" role="group" aria-label="Demo status switcher">
          <span className="sim-label">Demo Status:</span>
          <div className="sim-buttons">
            <button
              type="button"
              className={`btn-sim ${appStatus === 'online' ? 'active' : ''}`}
              onClick={() => onSetAppStatus('online')}
              aria-label="Simulate Online status"
              aria-pressed={appStatus === 'online'}
            >
              Online
            </button>
            <button
              type="button"
              className={`btn-sim ${appStatus === 'offline' ? 'active' : ''}`}
              onClick={() => onSetAppStatus('offline')}
              aria-label="Simulate Offline status"
              aria-pressed={appStatus === 'offline'}
            >
              Offline
            </button>
            <button
              type="button"
              className={`btn-sim ${appStatus === 'loading' ? 'active' : ''}`}
              onClick={() => onSetAppStatus('loading')}
              aria-label="Simulate Loading status"
              aria-pressed={appStatus === 'loading'}
            >
              Loading
            </button>
            <button
              type="button"
              className={`btn-sim ${appStatus === 'error' ? 'active' : ''}`}
              onClick={() => onSetAppStatus('error')}
              aria-label="Simulate Error status"
              aria-pressed={appStatus === 'error'}
            >
              Error
            </button>
          </div>
        </div>
      )}
    </section>
  );
};
