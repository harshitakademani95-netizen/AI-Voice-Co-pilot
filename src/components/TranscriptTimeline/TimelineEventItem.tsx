import React, { useState } from 'react';
import {
  Mic,
  Monitor,
  Brain,
  MessageSquare,
  ListTree,
  ShieldAlert,
  Wrench,
  Volume2,
  Info,
  History,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Sparkles,
} from 'lucide-react';
import { TimelineEvent } from '../../api/types';
import { HumanApprovalCard } from './HumanApprovalCard';

interface TimelineEventItemProps {
  event: TimelineEvent;
  sessionId: string;
  onApprovalDecision?: (approvalId: string, decision: 'approved' | 'rejected') => void;
}

export const formatConfidencePct = (val: number | undefined | null): number | null => {
  if (val === undefined || val === null || Number.isNaN(val)) {
    return null;
  }
  let pct: number;
  if (val <= 2) {
    pct = val * 100;
  } else {
    pct = val;
  }
  if (Number.isNaN(pct)) return null;
  return Math.max(0, Math.min(100, Math.round(pct)));
};

export const TimelineEventItem: React.FC<TimelineEventItemProps> = ({
  event,
  sessionId,
  onApprovalDecision,
}) => {
  const [showRevisions, setShowRevisions] = useState(false);

  const getEventIcon = () => {
    switch (event.type) {
      case 'user_voice':
        return <Mic size={16} color="#38bdf8" />;
      case 'system_context':
        return <Monitor size={16} color="#a78bfa" />;
      case 'ai_thought':
        return <Brain size={16} color="#f472b6" />;
      case 'ai_response':
        return <MessageSquare size={16} color="#34d399" />;
      case 'agent_plan':
        return <ListTree size={16} color="#fbbf24" />;
      case 'approval_request':
        return <ShieldAlert size={16} color="#f87171" />;
      case 'tool_execution':
        return <Wrench size={16} color="#38bdf8" />;
      case 'voice_output':
        return <Volume2 size={16} color="#60a5fa" />;
      default:
        return <Info size={16} color="#94a3b8" />;
    }
  };

  const getActorBadge = () => {
    switch (event.actor) {
      case 'user':
        return <span className="timeline-actor actor-user">User (Voice)</span>;
      case 'context_engine':
        return <span className="timeline-actor actor-system">Context Engine</span>;
      case 'safety_gate':
        return <span className="timeline-actor actor-safety">Safety Gate</span>;
      case 'tool':
        return <span className="timeline-actor actor-tool">Tool Execution</span>;
      default:
        return <span className="timeline-actor actor-ai">Co-Pilot AI</span>;
    }
  };

  const confidencePct = formatConfidencePct(event.metadata?.confidence);

  return (
    <article
      className={`timeline-item timeline-item-${event.type} ${event.is_interim ? 'timeline-item-interim' : ''}`}
      aria-labelledby={`evt-title-${event.id}`}
    >
      <div className="timeline-item-icon-wrap" aria-hidden="true">
        {getEventIcon()}
      </div>

      <div className="timeline-item-body">
        <header className="timeline-item-header">
          <div className="timeline-header-left">
            {getActorBadge()}

            {/* Interim / Final Transcript Badges */}
            {event.is_interim && (
              <span className="transcript-state-badge badge-interim" aria-label="Interim speech transcript">
                <span className="interim-pulse-dot" aria-hidden="true" />
                INTERIM
              </span>
            )}
            {event.is_final && (
              <span className="transcript-state-badge badge-final" aria-label="Final speech transcript">
                <CheckCircle2 size={11} aria-hidden="true" />
                FINAL
              </span>
            )}

            {/* Revised Badge */}
            {event.is_revised && (
              <span className="transcript-state-badge badge-revised" aria-label="Revised transcript">
                <Sparkles size={11} aria-hidden="true" />
                REVISED
              </span>
            )}

            <h3 id={`evt-title-${event.id}`} className="timeline-item-title">
              {event.title}
            </h3>
          </div>
          <time className="timeline-item-time" dateTime={event.timestamp}>
            {event.timestamp}
          </time>
        </header>

        <div className="timeline-item-content">
          <p className={event.is_interim ? 'interim-text' : ''}>{event.content}</p>

          {/* If the event contains an agent plan */}
          {event.type === 'agent_plan' && event.metadata?.plan_steps && (
            <div className="plan-steps-list" role="list" aria-label="Generated execution steps">
              {event.metadata.plan_steps.map((step) => (
                <div key={step.step_number} className="plan-step-row" role="listitem">
                  <span className="step-num">Step {step.step_number}</span>
                  <span className="step-desc">{step.description}</span>
                  <span className={`step-risk-chip risk-${step.risk_level}`}>
                    Level {step.risk_level}
                  </span>
                </div>
              ))}
            </div>
          )}

          {/* If the event is a human approval request */}
          {event.type === 'approval_request' && event.metadata?.approval_id && (
            <HumanApprovalCard
              approvalId={event.metadata.approval_id}
              sessionId={sessionId}
              toolName={event.metadata.tool_name ?? 'tool'}
              riskLevel={event.metadata.risk_level ?? 'C'}
              changeSummary={event.content}
              target={String(event.metadata.tool_params?.target ?? '')}
              initialStatus={event.metadata.approval_status ?? 'pending'}
              onDecision={(decision) =>
                onApprovalDecision &&
                onApprovalDecision(event.metadata!.approval_id!, decision)
              }
            />
          )}

          {/* Revision History Viewer */}
          {event.is_revised && event.revision_history && event.revision_history.length > 0 && (
            <div className="revision-history-container">
              <button
                type="button"
                className="btn-toggle-revisions"
                onClick={() => setShowRevisions(!showRevisions)}
                aria-expanded={showRevisions}
                aria-label={`View revision history (${event.revision_history.length} previous)`}
              >
                <History size={13} aria-hidden="true" />
                <span>
                  {showRevisions ? 'Hide' : 'View'} Revision History ({event.revision_history.length})
                </span>
                {showRevisions ? (
                  <ChevronUp size={13} aria-hidden="true" />
                ) : (
                  <ChevronDown size={13} aria-hidden="true" />
                )}
              </button>

              {showRevisions && (
                <div
                  className="revisions-list"
                  role="region"
                  aria-label="Previous transcript revisions"
                >
                  {event.revision_history.map((rev) => (
                    <div key={rev.revision_number} className="revision-item">
                      <div className="revision-item-header">
                        <span className="rev-num">Version {rev.revision_number}</span>
                        <span className="rev-time">{rev.timestamp}</span>
                        {formatConfidencePct(rev.confidence) !== null && (
                          <span className="rev-conf">
                            Confidence: {formatConfidencePct(rev.confidence)}%
                          </span>
                        )}
                      </div>
                      <div className="revision-content-prev">"{rev.content}"</div>
                      {rev.reason && <div className="revision-reason">Reason: {rev.reason}</div>}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Metadata badges for confidence and active app */}
          <div className="timeline-meta-chips">
            {/* Visual Confidence Progress Indicator */}
            {confidencePct !== null && (
              <div
                className="confidence-meter"
                role="meter"
                aria-valuenow={confidencePct}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-label={`Speech recognition confidence: ${confidencePct}%`}
              >
                <span className={`meta-chip confidence-chip ${confidencePct < 75 ? 'confidence-low' : ''}`}>
                  Confidence: {confidencePct}%{confidencePct < 75 ? ' (Low)' : ''}
                </span>
                <div className="confidence-track" aria-hidden="true">
                  <div
                    className="confidence-fill"
                    style={{
                      width: `${confidencePct}%`,
                      backgroundColor:
                        confidencePct >= 90
                          ? 'var(--color-success)'
                          : confidencePct >= 75
                          ? 'var(--color-warning)'
                          : 'var(--color-danger)',
                    }}
                  />
                </div>
              </div>
            )}

            {event.metadata?.application && (
              <span className="meta-chip">App: {event.metadata.application}</span>
            )}
            {event.metadata?.audio_duration_seconds && (
              <span className="meta-chip">
                Audio: {event.metadata.audio_duration_seconds}s
              </span>
            )}
          </div>
        </div>
      </div>
    </article>
  );
};
