import React from 'react';
import { Play, Pause, Square, RotateCcw, Activity } from 'lucide-react';
import { SessionStatus } from '../../api/types';
import './SessionControls.css';

interface SessionControlsProps {
  sessionId: string;
  status: SessionStatus;
  durationFormatted: string;
  turnCount: number;
  activeApp: string;
  onStart: () => void;
  onPause: () => void;
  onResume: () => void;
  onEnd: () => void;
  onReset: () => void;
}

export const SessionControls: React.FC<SessionControlsProps> = ({
  sessionId,
  status,
  durationFormatted,
  turnCount,
  activeApp,
  onStart,
  onPause,
  onResume,
  onEnd,
  onReset,
}) => {
  return (
    <section
      className="session-card"
      aria-labelledby="session-controls-heading"
    >
      <div className="session-header">
        <div className="session-title-wrap">
          <Activity size={18} color="var(--color-primary)" aria-hidden="true" />
          <h2 id="session-controls-heading" className="session-title">
            Session Controls
          </h2>
        </div>

        <span
          className={`session-badge session-badge-${status}`}
          role="status"
          aria-label={`Session status is ${status}`}
        >
          <span
            style={{
              width: 6,
              height: 6,
              borderRadius: '50%',
              backgroundColor: 'currentColor',
            }}
            aria-hidden="true"
          />
          {status}
        </span>
      </div>

      <div className="session-meta-grid" role="region" aria-label="Session Metadata">
        <div className="session-meta-item">
          <div className="session-meta-label">Session ID</div>
          <div className="session-meta-value" title={sessionId}>
            {sessionId}
          </div>
        </div>

        <div className="session-meta-item">
          <div className="session-meta-label">Active App</div>
          <div className="session-meta-value" title={activeApp}>
            {activeApp}
          </div>
        </div>

        <div className="session-meta-item">
          <div className="session-meta-label">Duration</div>
          <div className="session-meta-value">{durationFormatted}</div>
        </div>

        <div className="session-meta-item">
          <div className="session-meta-label">Turns</div>
          <div className="session-meta-value">{turnCount}</div>
        </div>
      </div>

      <div className="session-actions" role="toolbar" aria-label="Session management actions">
        {status === 'idle' || status === 'ended' ? (
          <button
            type="button"
            className="btn-session btn-session-primary"
            onClick={onStart}
            aria-label="Start new session"
          >
            <Play size={14} aria-hidden="true" />
            <span>Start Session</span>
          </button>
        ) : status === 'active' ? (
          <button
            type="button"
            className="btn-session btn-session-secondary"
            onClick={onPause}
            aria-label="Pause current session"
          >
            <Pause size={14} aria-hidden="true" />
            <span>Pause</span>
          </button>
        ) : (
          <button
            type="button"
            className="btn-session btn-session-primary"
            onClick={onResume}
            aria-label="Resume current session"
          >
            <Play size={14} aria-hidden="true" />
            <span>Resume</span>
          </button>
        )}

        {status !== 'idle' && status !== 'ended' && (
          <button
            type="button"
            className="btn-session btn-session-danger"
            onClick={onEnd}
            aria-label="End active session"
          >
            <Square size={13} aria-hidden="true" />
            <span>End Session</span>
          </button>
        )}

        <button
          type="button"
          className="btn-session btn-session-secondary"
          onClick={onReset}
          aria-label="Reset session state"
        >
          <RotateCcw size={13} aria-hidden="true" />
          <span>Reset</span>
        </button>
      </div>
    </section>
  );
};
