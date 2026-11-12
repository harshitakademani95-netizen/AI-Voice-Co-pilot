import React, { useState } from 'react';
import {
  Layers,
  Monitor,
  MonitorOff,
  Code,
  Mic,
  FileText,
  MessageSquare,
  Clock,
  RotateCw,
  CheckCircle2,
  AlertCircle,
  ShieldCheck,
  ShieldOff,
  ShieldAlert,
  Lock,
  X,
} from 'lucide-react';
import { AppContextData, ContextSourceType } from '../../api/types';
import './ContextPanel.css';

export interface ContextPanelProps {
  contextData: AppContextData;
  onToggleScreenContext: (enabled: boolean) => void | Promise<void | boolean>;
  onRefreshContext?: () => void;
  onClearContext?: () => void;
  errorMessage?: string | null;
  onClearError?: () => void;
  onRequestPermission?: () => Promise<boolean | MediaStream>;
}

export const ContextPanel: React.FC<ContextPanelProps> = ({
  contextData,
  onToggleScreenContext,
  onRefreshContext,
  onClearContext,
  errorMessage,
  onClearError,
  onRequestPermission,
}) => {
  const [internalError, setInternalError] = useState<string | null>(null);

  const displayError = errorMessage ?? contextData.errorMessage ?? internalError;

  const handleDismissError = () => {
    setInternalError(null);
    onClearError?.();
  };

  const handleToggleClick = async () => {
    if (contextData.screenContextEnabled) {
      setInternalError(null);
      handleDismissError();
      await onToggleScreenContext(false);
      return;
    }

    if (onRequestPermission) {
      setInternalError(null);
      try {
        const result = await onRequestPermission();
        if (result) {
          setInternalError(null);
          await onToggleScreenContext(true);
        } else {
          setInternalError('Screen capture permission was denied. Please allow screen sharing in your browser settings to enable screen context.');
          await onToggleScreenContext(false);
        }
      } catch (err: unknown) {
        const errObj = err as { name?: string; message?: string };
        let msg = 'Screen capture permission was denied. Please allow screen sharing in your browser settings to enable screen context.';
        if (
          errObj?.name === 'NotAllowedError' ||
          errObj?.name === 'PermissionDeniedError' ||
          errObj?.name === 'AbortError' ||
          errObj?.message?.toLowerCase().includes('denied') ||
          errObj?.message?.toLowerCase().includes('cancel') ||
          errObj?.message?.toLowerCase().includes('dismiss')
        ) {
          msg = 'Screen capture permission was denied or cancelled. Please allow screen sharing in your browser settings to enable screen context.';
        } else if (
          errObj?.name === 'NotFoundError' ||
          errObj?.name === 'NotSupportedError' ||
          errObj?.message?.toLowerCase().includes('unavailable') ||
          errObj?.message?.toLowerCase().includes('not supported')
        ) {
          msg = 'Screen capture is unavailable or not supported in this browser environment.';
        } else if (errObj?.message) {
          msg = errObj.message;
        }
        setInternalError(msg);
        await onToggleScreenContext(false);
      }
      return;
    }

    await onToggleScreenContext(true);
  };

  const getSourceIcon = (type: ContextSourceType) => {
    switch (type) {
      case 'user_voice':
        return <Mic size={14} aria-hidden="true" />;
      case 'active_app':
        return <Code size={14} aria-hidden="true" />;
      case 'screen_context':
        return <Monitor size={14} aria-hidden="true" />;
      case 'document_context':
        return <FileText size={14} aria-hidden="true" />;
      case 'conversation_history':
        return <MessageSquare size={14} aria-hidden="true" />;
    }
  };

  const hasContextContent =
    Boolean(contextData.details || contextData.terminalOutput || contextData.activeApp);

  return (
    <section
      className="context-card"
      aria-labelledby="context-panel-heading"
      role="region"
    >
      <div className="context-header">
        <div className="context-title-wrap">
          <Layers size={18} color="var(--color-primary)" aria-hidden="true" />
          <h2 id="context-panel-heading" className="context-title">
            Context & Sources
          </h2>
        </div>

        {/* Freshness Badge */}
        <span
          className={`context-freshness-badge freshness-${contextData.freshnessState}`}
          role="status"
          aria-label={`Context freshness is ${contextData.freshnessState}`}
        >
          {contextData.freshnessState === 'fresh' ? (
            <CheckCircle2 size={12} aria-hidden="true" />
          ) : (
            <Clock size={12} aria-hidden="true" />
          )}
          <span>{contextData.freshnessState}</span>
        </span>
      </div>

      {/* Screen Context ON/OFF Privacy Control - OFF by default (Strict Privacy Requirement) */}
      <div className="screen-context-control-box">
        <div className="screen-toggle-left">
          <div className="screen-toggle-icon">
            {contextData.screenContextEnabled ? (
              <ShieldCheck size={18} color="var(--color-success)" aria-hidden="true" />
            ) : Boolean(displayError) ? (
              <ShieldAlert size={18} color="#f87171" aria-hidden="true" />
            ) : (
              <ShieldOff size={18} color="var(--text-dim)" aria-hidden="true" />
            )}
          </div>
          <div>
            <div className="screen-toggle-title">
              Screen Context Capture
            </div>
            <div className="screen-toggle-status">
              {contextData.screenContextEnabled
                ? 'Status: ENABLED (Window & Code Context Active)'
                : (contextData.screenContextStatus === 'unavailable' || contextData.screenContextStatus === 'denied' || Boolean(displayError))
                ? 'Status: UNAVAILABLE (Screen capture permission denied or unsupported)'
                : 'Status: DISABLED (OFF by Default - Privacy Protected)'}
            </div>
          </div>
        </div>

        <button
          type="button"
          role="switch"
          id="screen-context-toggle"
          aria-checked={contextData.screenContextEnabled}
          aria-label={
            contextData.screenContextEnabled
              ? 'Disable screen context capture'
              : 'Enable screen context capture'
          }
          className={`switch-button ${contextData.screenContextEnabled ? 'switch-on' : 'switch-off'}`}
          onClick={handleToggleClick}
        >
          <span className="switch-slider" />
          <span className="sr-only">
            {contextData.screenContextEnabled ? 'Screen context enabled' : 'Screen context disabled'}
          </span>
        </button>
      </div>

      {/* Accessible Error Banner if permission is denied or unavailable */}
      {displayError && (
        <div
          className="screen-context-error-banner"
          role="alert"
          aria-live="assertive"
        >
          <div className="screen-context-error-content">
            <AlertCircle size={15} color="#f87171" aria-hidden="true" />
            <span className="screen-context-error-text">{displayError}</span>
          </div>
          <button
            type="button"
            className="screen-context-error-dismiss"
            onClick={handleDismissError}
            aria-label="Dismiss screen capture error"
          >
            <X size={13} aria-hidden="true" />
          </button>
        </div>
      )}

      {/* Explicit Privacy Notice */}
      <div className="privacy-guarantee-note" role="note">
        <Lock size={12} color="var(--color-primary)" aria-hidden="true" />
        <span>
          <strong>Privacy Guarantee:</strong> Screen context is strictly OFF by default. Only enabled upon explicit user consent. Disables immediately with one click.
        </span>
      </div>

      {/* Context Freshness Metadata */}
      <div className="context-meta-row" role="region" aria-label="Context update metadata">
        <div className="context-meta-item">
          <Clock size={13} aria-hidden="true" />
          <span>Last Updated: {contextData.lastUpdated || 'Never'}</span>
        </div>
        {onRefreshContext && (
          <button
            type="button"
            className="btn-context-refresh"
            onClick={onRefreshContext}
            aria-label="Refresh application context"
          >
            <RotateCw size={12} aria-hidden="true" />
            <span>Refresh</span>
          </button>
        )}
      </div>

      {/* Application Context Summary */}
      <div className="context-summary-box">
        <div className="context-section-label">Active Workspace</div>
        <div className="context-app-meta">
          <div className="context-kv">
            <span className="kv-key">Application:</span>
            <span className="kv-val">{contextData.activeApp || 'None detected'}</span>
          </div>
          <div className="kv-divider" />
          <div className="context-kv">
            <span className="kv-key">Window:</span>
            <span className="kv-val" title={contextData.windowTitle}>
              {contextData.windowTitle || 'No active window'}
            </span>
          </div>
        </div>

        {/* Captured Content or Meaningful Empty State */}
        {!hasContextContent ? (
          <div className="context-empty-state" role="status">
            <AlertCircle size={16} aria-hidden="true" />
            <span>No workspace context captured yet. Enable screen context or trigger an action.</span>
          </div>
        ) : (
          <div className="context-content-preview">
            {contextData.details && (
              <div className="context-snippet-text">{contextData.details}</div>
            )}
            {contextData.screenContextEnabled && contextData.terminalOutput && (
              <pre className="context-terminal-box" aria-label="Terminal context output">
                <code>{contextData.terminalOutput}</code>
              </pre>
            )}
            {!contextData.screenContextEnabled && (
              <div className="context-disabled-note" role="note">
                <MonitorOff size={14} aria-hidden="true" />
                <span>Screen capture is disabled. Visual code & terminal snapshots are paused.</span>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Context Sources List */}
      <div className="context-sources-section">
        <div className="context-section-label">Active Context Sources</div>
        <div className="sources-list" role="list" aria-label="Context information sources">
          {contextData.sources.map((src) => {
            const isCurrentlyActive =
              src.id === 'screen_context' ? contextData.screenContextEnabled : src.active;

            return (
              <div
                key={src.id}
                className={`source-row ${isCurrentlyActive ? 'source-active' : 'source-inactive'}`}
                role="listitem"
              >
                <div className="source-info-left">
                  <span className="source-icon" aria-hidden="true">
                    {getSourceIcon(src.id)}
                  </span>
                  <div className="source-text-wrap">
                    <span className="source-name">{src.label}</span>
                    <span className="source-desc">{src.description}</span>
                  </div>
                </div>

                <span
                  className={`source-status-chip ${isCurrentlyActive ? 'chip-active' : 'chip-inactive'}`}
                  aria-label={`${src.label} is ${isCurrentlyActive ? 'active' : 'inactive'}`}
                >
                  {isCurrentlyActive ? 'Active' : 'Inactive'}
                </span>
              </div>
            );
          })}
        </div>
      </div>

      {onClearContext && (
        <div className="context-footer-actions">
          <button
            type="button"
            className="btn-context-clear"
            onClick={onClearContext}
            aria-label="Clear active context data"
          >
            Clear Context
          </button>
        </div>
      )}
    </section>
  );
};
