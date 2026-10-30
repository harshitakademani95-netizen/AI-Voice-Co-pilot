import React, { useState, useRef, useEffect } from 'react';
import { History, ArrowDownCircle, Trash2, Filter } from 'lucide-react';
import { TimelineEvent } from '../../api/types';
import { TimelineEventItem } from './TimelineEventItem';
import './TranscriptTimeline.css';

interface TranscriptTimelineProps {
  events: TimelineEvent[];
  sessionId: string;
  onClearEvents?: () => void;
  onApprovalDecision?: (approvalId: string, decision: 'approved' | 'rejected') => void;
}

export const TranscriptTimeline: React.FC<TranscriptTimelineProps> = ({
  events,
  sessionId,
  onClearEvents,
  onApprovalDecision,
}) => {
  const [filter, setFilter] = useState<string>('all');
  const [autoScroll, setAutoScroll] = useState<boolean>(true);
  const bottomAnchorRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (autoScroll && bottomAnchorRef.current) {
      bottomAnchorRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [events, autoScroll]);

  const filteredEvents = events.filter((evt) => {
    if (filter === 'all') return true;
    if (filter === 'user_voice') return evt.type === 'user_voice';
    if (filter === 'ai') return evt.type === 'ai_response' || evt.type === 'ai_thought' || evt.type === 'voice_output';
    if (filter === 'context') return evt.type === 'system_context';
    if (filter === 'agent') return evt.type === 'agent_plan' || evt.type === 'tool_execution';
    if (filter === 'approvals') return evt.type === 'approval_request';
    return true;
  });

  return (
    <section
      className="timeline-container"
      aria-labelledby="timeline-heading"
      role="region"
    >
      <header className="timeline-header">
        <div className="timeline-title-wrap">
          <History size={18} color="var(--color-primary)" aria-hidden="true" />
          <h2 id="timeline-heading" className="timeline-title">
            Transcript & Execution Timeline
          </h2>
          <span className="timeline-count-badge" aria-label={`${filteredEvents.length} events displayed`}>
            {filteredEvents.length} {filteredEvents.length === 1 ? 'event' : 'events'}
          </span>
        </div>

        <div className="timeline-controls-bar">
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <Filter size={14} color="var(--text-dim)" aria-hidden="true" />
            <select
              className="timeline-filter-select"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              aria-label="Filter timeline events by category"
            >
              <option value="all">All Events</option>
              <option value="user_voice">Voice Inputs</option>
              <option value="ai">AI Responses & Voice</option>
              <option value="context">Context Engine</option>
              <option value="agent">Agent Plans & Tools</option>
              <option value="approvals">Safety Approvals</option>
            </select>
          </div>

          <button
            type="button"
            className={`btn-timeline-action ${autoScroll ? 'active' : ''}`}
            onClick={() => setAutoScroll(!autoScroll)}
            aria-pressed={autoScroll}
            aria-label="Toggle auto scroll"
          >
            <ArrowDownCircle size={14} aria-hidden="true" />
            <span>Auto-Scroll</span>
          </button>

          {onClearEvents && (
            <button
              type="button"
              className="btn-timeline-action"
              onClick={onClearEvents}
              aria-label="Clear all timeline events"
            >
              <Trash2 size={13} aria-hidden="true" />
              <span>Clear</span>
            </button>
          )}
        </div>
      </header>

      <div
        className="timeline-feed"
        role="log"
        aria-live="polite"
        aria-atomic="false"
      >
        {filteredEvents.length === 0 ? (
          <div
            style={{
              padding: 40,
              textAlign: 'center',
              color: 'var(--text-dim)',
              fontSize: '0.875rem',
            }}
          >
            No events match the selected filter.
          </div>
        ) : (
          filteredEvents.map((evt) => (
            <TimelineEventItem
              key={evt.id}
              event={evt}
              sessionId={sessionId}
              onApprovalDecision={onApprovalDecision}
            />
          ))
        )}
        <div ref={bottomAnchorRef} aria-hidden="true" />
      </div>
    </section>
  );
};
