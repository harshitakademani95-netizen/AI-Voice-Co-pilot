import React from 'react';
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
} from 'lucide-react';
import { TimelineEvent } from '../../api/types';
import { HumanApprovalCard } from './HumanApprovalCard';

interface TimelineEventItemProps {
  event: TimelineEvent;
  sessionId: string;
  onApprovalDecision?: (approvalId: string, decision: 'approved' | 'rejected') => void;
}

export const TimelineEventItem: React.FC<TimelineEventItemProps> = ({
  event,
  sessionId,
  onApprovalDecision,
}) => {
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

  return (
    <article
      className={`timeline-item timeline-item-${event.type}`}
      aria-labelledby={`evt-title-${event.id}`}
    >
      <div className="timeline-item-icon-wrap" aria-hidden="true">
        {getEventIcon()}
      </div>

      <div className="timeline-item-body">
        <header className="timeline-item-header">
          <div className="timeline-header-left">
            {getActorBadge()}
            <h3 id={`evt-title-${event.id}`} className="timeline-item-title">
              {event.title}
            </h3>
          </div>
          <time className="timeline-item-time" dateTime={event.timestamp}>
            {event.timestamp}
          </time>
        </header>

        <div className="timeline-item-content">
          <p>{event.content}</p>

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

          {/* Metadata badges for confidence and active app */}
          {event.metadata && (
            <div className="timeline-meta-chips">
              {event.metadata.confidence !== undefined && (
                <span className="meta-chip">
                  Confidence: {Math.round(event.metadata.confidence * 100)}%
                </span>
              )}
              {event.metadata.application && (
                <span className="meta-chip">App: {event.metadata.application}</span>
              )}
              {event.metadata.audio_duration_seconds && (
                <span className="meta-chip">
                  Audio: {event.metadata.audio_duration_seconds}s
                </span>
              )}
            </div>
          )}
        </div>
      </div>
    </article>
  );
};
