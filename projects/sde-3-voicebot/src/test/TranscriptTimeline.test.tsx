import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { TranscriptTimeline } from '../components/TranscriptTimeline/TranscriptTimeline';
import { INITIAL_FIXTURE_EVENTS } from '../fixtures/mockTimelineEvents';
import { apiClient } from '../api/apiClient';

describe('TranscriptTimeline Component', () => {
  beforeEach(() => {
    apiClient.setMockLatency(0);
    apiClient.setSimulatedError(null);
  });

  it('renders fixture events in chronological order', () => {
    render(
      <TranscriptTimeline
        events={INITIAL_FIXTURE_EVENTS}
        sessionId="session-001"
      />
    );

    expect(screen.getByRole('heading', { name: /transcript & execution timeline/i })).toBeInTheDocument();
    expect(screen.getByText('Session Initialized')).toBeInTheDocument();
    expect(screen.getByText('Why is my FastAPI backend failing with this error?')).toBeInTheDocument();
    expect(screen.getByText(/context captured: vs code/i)).toBeInTheDocument();
    expect(screen.getByText('Agentic Task Plan Generated')).toBeInTheDocument();
    expect(screen.getByText('Human-in-the-Loop Approval Required')).toBeInTheDocument();
  });

  it('filters events when a category is selected in the dropdown', async () => {
    const user = userEvent.setup();
    render(
      <TranscriptTimeline
        events={INITIAL_FIXTURE_EVENTS}
        sessionId="session-001"
      />
    );

    const select = screen.getByLabelText(/filter timeline events by category/i);
    await user.selectOptions(select, 'approvals');

    // Only approval event should remain visible
    expect(screen.getByText('Human-in-the-Loop Approval Required')).toBeInTheDocument();
    expect(screen.queryByText('Session Initialized')).not.toBeInTheDocument();
  });

  it('calls onClearEvents when Clear button is clicked', async () => {
    const user = userEvent.setup();
    const handleClear = vi.fn();

    render(
      <TranscriptTimeline
        events={INITIAL_FIXTURE_EVENTS}
        sessionId="session-001"
        onClearEvents={handleClear}
      />
    );

    const clearBtn = screen.getByRole('button', { name: /clear all timeline events/i });
    expect(clearBtn).toBeInTheDocument();

    await user.click(clearBtn);
    expect(handleClear).toHaveBeenCalledTimes(1);
  });

  it('renders empty state message when no events are provided or match the filter', () => {
    render(
      <TranscriptTimeline
        events={[]}
        sessionId="session-001"
      />
    );

    expect(screen.getByText(/no events match the selected filter/i)).toBeInTheDocument();
    expect(screen.getByText(/0 events/i)).toBeInTheDocument();
  });

  it('handles human approval decision in the approval card', async () => {
    const user = userEvent.setup();
    const handleApproval = vi.fn();

    render(
      <TranscriptTimeline
        events={INITIAL_FIXTURE_EVENTS}
        sessionId="session-001"
        onApprovalDecision={handleApproval}
      />
    );

    const approveBtn = screen.getByRole('button', { name: /authorize and approve tool execution/i });
    expect(approveBtn).toBeInTheDocument();

    await user.click(approveBtn);

    await waitFor(() => {
      expect(handleApproval).toHaveBeenCalledWith('appr-901', 'approved');
    });
  });

  it('handles approval failure gracefully with error alert and keeps buttons available', async () => {
    const user = userEvent.setup();
    const handleApproval = vi.fn();

    apiClient.setSimulatedError('INTERNAL_ERROR');

    try {
      render(
        <TranscriptTimeline
          events={INITIAL_FIXTURE_EVENTS}
          sessionId="session-001"
          onApprovalDecision={handleApproval}
        />
      );

      const approveBtn = screen.getByRole('button', { name: /authorize and approve tool execution/i });
      await user.click(approveBtn);

      await waitFor(() => {
        expect(screen.getByRole('alert')).toBeInTheDocument();
      });

      expect(screen.getByText(/INTERNAL_ERROR/i)).toBeInTheDocument();
      expect(handleApproval).not.toHaveBeenCalled();
      expect(screen.getByRole('button', { name: /authorize and approve tool execution/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /reject tool execution/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /retry approval submission/i })).toBeInTheDocument();
    } finally {
      apiClient.setSimulatedError(null);
    }
  });
});
