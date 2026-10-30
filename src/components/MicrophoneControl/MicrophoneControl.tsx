import React from 'react';
import { Mic, MicOff, Volume2, Square, AlertOctagon, CheckCircle2, ShieldAlert } from 'lucide-react';
import { MicrophonePermissionState, MicrophoneActivityState } from '../../api/types';
import './MicrophoneControl.css';

interface MicrophoneControlProps {
  permission: MicrophonePermissionState;
  activity: MicrophoneActivityState;
  isMuted: boolean;
  onRequestPermission: (grantOrDeny?: boolean) => void;
  onToggleMute: () => void;
  onStartListening: () => void;
  onStopListening: () => void;
  onInterruptAi: () => void;
  onTestVoiceInput: () => void;
}

export const MicrophoneControl: React.FC<MicrophoneControlProps> = ({
  permission,
  activity,
  isMuted,
  onRequestPermission,
  onToggleMute,
  onStartListening,
  onStopListening,
  onInterruptAi,
  onTestVoiceInput,
}) => {
  const getStatusText = (): string => {
    if (permission === 'denied') return 'Microphone Access Blocked';
    if (permission === 'prompt') return 'Permission Required';
    if (isMuted) return 'Muted';
    if (activity === 'listening') return 'Listening... Speak clearly';
    if (activity === 'processing') return 'Processing speech...';
    if (activity === 'speaking') return 'Co-Pilot is speaking (Click Interrupt to stop)';
    return 'Ready to listen (Click Mic or Test Speech)';
  };

  return (
    <section className="mic-card" aria-labelledby="mic-controls-heading">
      <div className="mic-header">
        <div className="mic-title-wrap">
          <Mic size={18} color="var(--color-primary)" aria-hidden="true" />
          <h2 id="mic-controls-heading" className="mic-title">
            Microphone & Voice Input
          </h2>
        </div>

        <span
          className={`mic-permission-badge perm-${permission}`}
          role="status"
          aria-label={`Microphone permission is ${permission}`}
        >
          {permission === 'granted' ? (
            <CheckCircle2 size={13} aria-hidden="true" />
          ) : permission === 'denied' ? (
            <AlertOctagon size={13} aria-hidden="true" />
          ) : (
            <ShieldAlert size={13} aria-hidden="true" />
          )}
          <span>{permission}</span>
        </span>
      </div>

      {permission === 'denied' ? (
        <div className="mic-denied-box" role="alert">
          <div>
            <strong>Microphone permission denied.</strong> Audio capture is blocked. Voice input cannot be received until access is granted.
          </div>
          <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
            <button
              type="button"
              className="btn-mic-action"
              onClick={() => onRequestPermission(true)}
              style={{ background: 'var(--color-primary)', color: 'white', borderColor: 'transparent' }}
            >
              Grant Microphone Permission
            </button>
          </div>
        </div>
      ) : permission === 'prompt' ? (
        <div className="mic-denied-box" style={{ background: 'rgba(245, 158, 11, 0.1)', borderColor: 'rgba(245, 158, 11, 0.3)', color: '#fde68a' }} role="alert">
          <div>
            <strong>Microphone permission prompt:</strong> AI Voice Co-Pilot needs access to your microphone to capture spoken requests.
          </div>
          <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
            <button
              type="button"
              className="btn-mic-action"
              onClick={() => onRequestPermission(true)}
              style={{ background: 'var(--color-primary)', color: 'white' }}
            >
              Allow Microphone
            </button>
            <button
              type="button"
              className="btn-mic-action"
              onClick={() => onRequestPermission(false)}
            >
              Deny
            </button>
          </div>
        </div>
      ) : (
        <div className="mic-visualizer-box" aria-live="polite">
          <button
            type="button"
            className={`mic-pulse-button ${
              activity === 'listening'
                ? 'mic-listening'
                : activity === 'speaking'
                ? 'mic-speaking'
                : activity === 'processing'
                ? 'mic-processing'
                : ''
            }`}
            onClick={activity === 'listening' ? onStopListening : onStartListening}
            disabled={isMuted}
            aria-label={
              activity === 'listening'
                ? 'Stop listening'
                : 'Start listening to voice input'
            }
          >
            {isMuted ? (
              <MicOff size={24} aria-hidden="true" />
            ) : activity === 'speaking' ? (
              <Volume2 size={24} aria-hidden="true" />
            ) : (
              <Mic size={24} aria-hidden="true" />
            )}
          </button>

          {activity === 'listening' && (
            <div className="waveform-container" aria-hidden="true">
              <span className="waveform-bar" style={{ height: 10 }}></span>
              <span className="waveform-bar" style={{ height: 18 }}></span>
              <span className="waveform-bar" style={{ height: 26 }}></span>
              <span className="waveform-bar" style={{ height: 16 }}></span>
              <span className="waveform-bar" style={{ height: 20 }}></span>
            </div>
          )}

          <div className="mic-status-label">{getStatusText()}</div>
        </div>
      )}

      <div className="mic-toolbar" role="toolbar" aria-label="Microphone Actions">
        <button
          type="button"
          className="btn-mic-action"
          onClick={onToggleMute}
          disabled={permission !== 'granted'}
          aria-label={isMuted ? 'Unmute microphone' : 'Mute microphone'}
        >
          {isMuted ? <Mic size={14} aria-hidden="true" /> : <MicOff size={14} aria-hidden="true" />}
          <span>{isMuted ? 'Unmute' : 'Mute'}</span>
        </button>

        <button
          type="button"
          className="btn-mic-action"
          onClick={onTestVoiceInput}
          disabled={permission !== 'granted' || isMuted}
          aria-label="Simulate voice input question"
        >
          <Volume2 size={14} aria-hidden="true" />
          <span>Simulate Voice Query</span>
        </button>

        {activity === 'speaking' && (
          <button
            type="button"
            className="btn-mic-action btn-mic-interrupt"
            onClick={onInterruptAi}
            aria-label="Interrupt AI response (FR-VOICE-004)"
          >
            <Square size={13} aria-hidden="true" />
            <span>Interrupt AI</span>
          </button>
        )}

        <button
          type="button"
          className="btn-mic-action"
          onClick={() => onRequestPermission(permission === 'granted' ? false : true)}
          aria-label="Toggle permission between granted and denied"
        >
          <span>Toggle Perm ({permission === 'granted' ? 'Deny' : 'Grant'})</span>
        </button>
      </div>
    </section>
  );
};
