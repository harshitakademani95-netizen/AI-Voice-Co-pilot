import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { TranscriptTimeline } from '../components/TranscriptTimeline/TranscriptTimeline';
import { TimelineEvent } from '../api/types';

describe('Week 2: TranscriptTimeline - Interim, Final & Revisions', () => {
  const interimEvent: TimelineEvent = {
    id: 'evt-interim-1',
    segment_id: 'seg-101',
    timestamp: '10:06:01 AM',
    type: 'user_voice',
    actor: 'user',
    title: 'User Voice Input (Streaming)',
    content: 'Why is my Fast...',
    is_interim: true,
    metadata: {
      confidence: 0.85,
    },
  };

  const finalEvent: TimelineEvent = {
    id: 'evt-final-1',
    segment_id: 'seg-101',
    timestamp: '10:06:02 AM',
    type: 'user_voice',
    actor: 'user',
    title: 'User Voice Input',
    content: 'Why is my FastAPI backend failing with this error?',
    is_final: true,
    metadata: {
      confidence: 0.98,
    },
  };

  const revisedEvent: TimelineEvent = {
    id: 'evt-revised-1',
    segment_id: 'seg-101',
    timestamp: '10:06:05 AM',
    type: 'user_voice',
    actor: 'user',
    title: 'User Voice Input (Corrected)',
    content: 'Why is my FastAPI backend failing with ModuleNotFoundError?',
    is_final: true,
    is_revised: true,
    revision_history: [
      {
        revision_number: 1,
        timestamp: '10:06:02 AM',
        content: 'Why is my FastAPI backend failing with this error?',
        confidence: 0.98,
        reason: 'Initial transcription',
      },
    ],
    metadata: {
      confidence: 0.99,
    },
  };

  it('displays interim transcript with INTERIM label and visual distinction', () => {
    render(
      <TranscriptTimeline
        events={[interimEvent]}
        sessionId="session-001"
      />
    );

    expect(screen.getByText('INTERIM')).toBeInTheDocument();
    expect(screen.getByText('Why is my Fast...')).toBeInTheDocument();
  });

  it('replaces interim transcript with final transcript without duplicate entries', () => {
    // 1. Initially only interim event
    const { rerender } = render(
      <TranscriptTimeline
        events={[interimEvent]}
        sessionId="session-001"
      />
    );
    expect(screen.getByText('INTERIM')).toBeInTheDocument();
    expect(screen.getByText('Why is my Fast...')).toBeInTheDocument();

    // 2. When final transcript arrives for the same segment, it replaces the interim event
    rerender(
      <TranscriptTimeline
        events={[finalEvent]} // Final replaces interim
        sessionId="session-001"
      />
    );

    expect(screen.queryByText('INTERIM')).not.toBeInTheDocument();
    expect(screen.queryByText('Why is my Fast...')).not.toBeInTheDocument();
    expect(screen.getByText('FINAL')).toBeInTheDocument();
    expect(screen.getByText('Why is my FastAPI backend failing with this error?')).toBeInTheDocument();
    expect(screen.getByText('1 event')).toBeInTheDocument(); // Exactly 1 event, no duplicate
  });

  it('supports multiple transcript segments concurrently', () => {
    const segmentA: TimelineEvent = {
      id: 'evt-seg-a',
      segment_id: 'seg-A',
      timestamp: '10:06:10 AM',
      type: 'user_voice',
      actor: 'user',
      title: 'Segment A (Final)',
      content: 'First utterance completed.',
      is_final: true,
      metadata: { confidence: 0.95 },
    };

    const segmentBInterim: TimelineEvent = {
      id: 'evt-seg-b-int',
      segment_id: 'seg-B',
      timestamp: '10:06:12 AM',
      type: 'user_voice',
      actor: 'user',
      title: 'Segment B (Streaming)',
      content: 'Second utter...',
      is_interim: true,
      metadata: { confidence: 0.81 },
    };

    const segmentBFinal: TimelineEvent = {
      id: 'evt-seg-b-fin',
      segment_id: 'seg-B',
      timestamp: '10:06:14 AM',
      type: 'user_voice',
      actor: 'user',
      title: 'Segment B (Final)',
      content: 'Second utterance completed.',
      is_final: true,
      metadata: { confidence: 0.97 },
    };

    const { rerender } = render(
      <TranscriptTimeline
        events={[segmentA, segmentBInterim]}
        sessionId="session-001"
      />
    );

    expect(screen.getByText('First utterance completed.')).toBeInTheDocument();
    expect(screen.getByText('Second utter...')).toBeInTheDocument();
    expect(screen.getByText('INTERIM')).toBeInTheDocument();
    expect(screen.getByText('FINAL')).toBeInTheDocument();

    // Now segment B finishes and updates
    rerender(
      <TranscriptTimeline
        events={[segmentA, segmentBFinal]}
        sessionId="session-001"
      />
    );

    expect(screen.getByText('First utterance completed.')).toBeInTheDocument();
    expect(screen.getByText('Second utterance completed.')).toBeInTheDocument();
    expect(screen.queryByText('Second utter...')).not.toBeInTheDocument();
    expect(screen.getByText('2 events')).toBeInTheDocument();
  });

  it('displays transcript revisions and toggles previous revision history', async () => {
    const user = userEvent.setup();

    render(
      <TranscriptTimeline
        events={[revisedEvent]}
        sessionId="session-001"
      />
    );

    expect(screen.getByText('REVISED')).toBeInTheDocument();
    expect(screen.getByText('Why is my FastAPI backend failing with ModuleNotFoundError?')).toBeInTheDocument();

    // Find and click view revision history button
    const historyBtn = screen.getByRole('button', { name: /view revision history \(1 previous\)/i });
    expect(historyBtn).toBeInTheDocument();
    await user.click(historyBtn);

    // Prior revision content is now visible
    expect(screen.getByText(/version 1/i)).toBeInTheDocument();
    expect(screen.getByText(/"Why is my FastAPI backend failing with this error\?"/i)).toBeInTheDocument();
    expect(screen.getByText(/reason: initial transcription/i)).toBeInTheDocument();
  });

  it('displays speech recognition confidence percentage and meter', () => {
    render(
      <TranscriptTimeline
        events={[finalEvent]}
        sessionId="session-001"
      />
    );

    expect(screen.getByText('Confidence: 98%')).toBeInTheDocument();
    const meter = screen.getByRole('meter');
    expect(meter).toHaveAttribute('aria-valuenow', '98');
  });

  it('handles missing, zero, NaN, out-of-range, and low confidence values properly', () => {
    const eventWithoutConfidence: TimelineEvent = {
      id: 'evt-no-conf',
      timestamp: '10:07:00 AM',
      type: 'user_voice',
      actor: 'user',
      title: 'User Speech',
      content: 'Hello without confidence score',
    };

    const eventZeroConfidence: TimelineEvent = {
      id: 'evt-zero-conf',
      timestamp: '10:07:01 AM',
      type: 'user_voice',
      actor: 'user',
      title: 'Zero Confidence Speech',
      content: 'Whispered utterance',
      metadata: { confidence: 0 },
    };

    const eventLowConfidence: TimelineEvent = {
      id: 'evt-low-conf',
      timestamp: '10:07:02 AM',
      type: 'user_voice',
      actor: 'user',
      title: 'Low Confidence Speech',
      content: 'Noisy background input',
      metadata: { confidence: 0.52 },
    };

    const eventOverOneConfidence: TimelineEvent = {
      id: 'evt-over-conf',
      timestamp: '10:07:03 AM',
      type: 'user_voice',
      actor: 'user',
      title: 'Clamped Confidence Speech',
      content: 'Clear loud input',
      metadata: { confidence: 1.5 }, // > 1 should clamp to 100%
    };

    const eventNaNConfidence: TimelineEvent = {
      id: 'evt-nan-conf',
      timestamp: '10:07:04 AM',
      type: 'user_voice',
      actor: 'user',
      title: 'NaN Confidence Speech',
      content: 'Invalid float',
      metadata: { confidence: NaN },
    };

    render(
      <TranscriptTimeline
        events={[
          eventWithoutConfidence,
          eventZeroConfidence,
          eventLowConfidence,
          eventOverOneConfidence,
          eventNaNConfidence,
        ]}
        sessionId="session-001"
      />
    );

    // Missing: no meter
    expect(screen.getByText('Hello without confidence score')).toBeInTheDocument();

    // Zero: meters at 0%
    expect(screen.getByText('Confidence: 0% (Low)')).toBeInTheDocument();

    // Low: shows (Low) indicator
    expect(screen.getByText('Confidence: 52% (Low)')).toBeInTheDocument();

    // Over 1: clamped to 100%
    expect(screen.getByText('Confidence: 100%')).toBeInTheDocument();

    // NaN: gracefully omits meter
    expect(screen.getByText('Invalid float')).toBeInTheDocument();
  });
});
