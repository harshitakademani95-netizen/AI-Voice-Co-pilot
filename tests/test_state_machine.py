"""
Tests for Workflow State Machine and Transition Guardrails using Pytest.

Covers:
- All legal state transitions across draft, awaiting_approval, running, paused, succeeded, failed, cancelled.
- Rejection of illegal state transitions.
- Protection of terminal states (succeeded, failed, cancelled).
- Transition history and audit logging.
"""

import pytest

from agentic_workflow.schemas import WorkflowState
from agentic_workflow.state_machine import (
    InvalidStateTransitionError,
    WorkflowStateMachine,
)


class TestWorkflowStateMachine:
    """Test suite validating state machine transitions."""

    @pytest.fixture
    def sm(self) -> WorkflowStateMachine:
        return WorkflowStateMachine(initial_state=WorkflowState.DRAFT)

    def test_initial_state_is_draft(self, sm: WorkflowStateMachine):
        assert sm.current_state == WorkflowState.DRAFT
        assert not sm.is_terminal()
        assert len(sm.history) == 0

    def test_legal_draft_to_running(self, sm: WorkflowStateMachine):
        sm.transition_to(WorkflowState.RUNNING, reason="Starting plan")
        assert sm.current_state == WorkflowState.RUNNING
        assert len(sm.history) == 1
        assert sm.history[0].from_state == WorkflowState.DRAFT
        assert sm.history[0].to_state == WorkflowState.RUNNING

    def test_legal_draft_to_awaiting_approval(self, sm: WorkflowStateMachine):
        sm.transition_to(WorkflowState.AWAITING_APPROVAL, reason="Consequential initial step")
        assert sm.current_state == WorkflowState.AWAITING_APPROVAL

    def test_legal_draft_to_cancelled(self, sm: WorkflowStateMachine):
        sm.transition_to(WorkflowState.CANCELLED, reason="User cancelled early")
        assert sm.current_state == WorkflowState.CANCELLED
        assert sm.is_terminal()

    def test_legal_draft_to_failed(self, sm: WorkflowStateMachine):
        sm.transition_to(WorkflowState.FAILED, reason="Pre-check failed")
        assert sm.current_state == WorkflowState.FAILED
        assert sm.is_terminal()

    def test_legal_awaiting_approval_to_running(self, sm: WorkflowStateMachine):
        sm.transition_to(WorkflowState.AWAITING_APPROVAL)
        sm.transition_to(WorkflowState.RUNNING, reason="Approval granted")
        assert sm.current_state == WorkflowState.RUNNING

    def test_legal_awaiting_approval_to_cancelled(self, sm: WorkflowStateMachine):
        sm.transition_to(WorkflowState.AWAITING_APPROVAL)
        sm.transition_to(WorkflowState.CANCELLED, reason="Approval denied")
        assert sm.current_state == WorkflowState.CANCELLED
        assert sm.is_terminal()

    def test_legal_awaiting_approval_to_failed(self, sm: WorkflowStateMachine):
        sm.transition_to(WorkflowState.AWAITING_APPROVAL)
        sm.transition_to(WorkflowState.FAILED, reason="Approval timeout")
        assert sm.current_state == WorkflowState.FAILED

    def test_legal_running_to_paused_and_resume(self, sm: WorkflowStateMachine):
        sm.transition_to(WorkflowState.RUNNING)
        sm.transition_to(WorkflowState.PAUSED, reason="Workflow paused")
        assert sm.current_state == WorkflowState.PAUSED
        sm.transition_to(WorkflowState.RUNNING, reason="Workflow resumed")
        assert sm.current_state == WorkflowState.RUNNING

    def test_legal_running_to_succeeded(self, sm: WorkflowStateMachine):
        sm.transition_to(WorkflowState.RUNNING)
        sm.transition_to(WorkflowState.SUCCEEDED, reason="All steps done")
        assert sm.current_state == WorkflowState.SUCCEEDED
        assert sm.is_terminal()

    def test_legal_running_to_failed(self, sm: WorkflowStateMachine):
        sm.transition_to(WorkflowState.RUNNING)
        sm.transition_to(WorkflowState.FAILED, reason="Step execution failed")
        assert sm.current_state == WorkflowState.FAILED
        assert sm.is_terminal()

    def test_legal_running_to_cancelled(self, sm: WorkflowStateMachine):
        sm.transition_to(WorkflowState.RUNNING)
        sm.transition_to(WorkflowState.CANCELLED, reason="Aborted by user")
        assert sm.current_state == WorkflowState.CANCELLED

    def test_legal_paused_to_cancelled_or_failed(self, sm: WorkflowStateMachine):
        sm.transition_to(WorkflowState.RUNNING)
        sm.transition_to(WorkflowState.PAUSED)
        sm.transition_to(WorkflowState.CANCELLED, reason="Cancelled while paused")
        assert sm.current_state == WorkflowState.CANCELLED

    # Illegal transitions
    def test_reject_illegal_draft_to_succeeded(self, sm: WorkflowStateMachine):
        with pytest.raises(InvalidStateTransitionError) as exc:
            sm.transition_to(WorkflowState.SUCCEEDED)
        assert "Illegal state transition from 'draft' to 'succeeded'" in str(exc.value)

    def test_reject_illegal_draft_to_paused(self, sm: WorkflowStateMachine):
        with pytest.raises(InvalidStateTransitionError):
            sm.transition_to(WorkflowState.PAUSED)

    def test_reject_illegal_awaiting_approval_to_succeeded(self, sm: WorkflowStateMachine):
        sm.transition_to(WorkflowState.AWAITING_APPROVAL)
        with pytest.raises(InvalidStateTransitionError):
            sm.transition_to(WorkflowState.SUCCEEDED)

    def test_reject_illegal_awaiting_approval_to_paused(self, sm: WorkflowStateMachine):
        sm.transition_to(WorkflowState.AWAITING_APPROVAL)
        with pytest.raises(InvalidStateTransitionError):
            sm.transition_to(WorkflowState.PAUSED)

    def test_reject_illegal_paused_to_succeeded(self, sm: WorkflowStateMachine):
        sm.transition_to(WorkflowState.RUNNING)
        sm.transition_to(WorkflowState.PAUSED)
        with pytest.raises(InvalidStateTransitionError):
            sm.transition_to(WorkflowState.SUCCEEDED)

    def test_terminal_state_succeeded_blocks_all_transitions(self, sm: WorkflowStateMachine):
        sm.transition_to(WorkflowState.RUNNING)
        sm.transition_to(WorkflowState.SUCCEEDED)
        for target in [
            WorkflowState.DRAFT,
            WorkflowState.AWAITING_APPROVAL,
            WorkflowState.RUNNING,
            WorkflowState.PAUSED,
            WorkflowState.FAILED,
            WorkflowState.CANCELLED,
        ]:
            with pytest.raises(InvalidStateTransitionError):
                sm.transition_to(target)

    def test_terminal_state_failed_blocks_all_transitions(self, sm: WorkflowStateMachine):
        sm.transition_to(WorkflowState.FAILED)
        with pytest.raises(InvalidStateTransitionError):
            sm.transition_to(WorkflowState.RUNNING)

    def test_terminal_state_cancelled_blocks_all_transitions(self, sm: WorkflowStateMachine):
        sm.transition_to(WorkflowState.CANCELLED)
        with pytest.raises(InvalidStateTransitionError):
            sm.transition_to(WorkflowState.RUNNING)

    def test_redundant_self_transition_is_noop(self, sm: WorkflowStateMachine):
        sm.transition_to(WorkflowState.RUNNING)
        hist_len = len(sm.history)
        sm.transition_to(WorkflowState.RUNNING)
        assert len(sm.history) == hist_len

    def test_terminal_self_transition_raises_error(self):
        """Fix 5: transition to the same state from a terminal state raises InvalidStateTransitionError."""
        for term_state in [WorkflowState.SUCCEEDED, WorkflowState.FAILED, WorkflowState.CANCELLED]:
            sm = WorkflowStateMachine(initial_state=term_state)
            with pytest.raises(InvalidStateTransitionError) as exc:
                sm.transition_to(term_state)
            assert "Cannot transition from terminal state" in str(exc.value)

    def test_full_state_transition_matrix_all_42_pairs(self):
        """
        Requirement 6: Complete matrix test of all 42 ordered non-identical state pairs
        against ALLOWED_TRANSITIONS, including running->awaiting_approval and paused->failed.
        """
        states = list(WorkflowState)
        evaluated_pairs = 0

        for from_state in states:
            for to_state in states:
                if from_state == to_state:
                    continue  # The 42 non-identical pairs

                evaluated_pairs += 1
                sm = WorkflowStateMachine(initial_state=from_state)
                is_allowed = to_state in WorkflowStateMachine.ALLOWED_TRANSITIONS.get(from_state, set())

                if is_allowed:
                    sm.transition_to(to_state, reason=f"Testing legal {from_state.value} -> {to_state.value}")
                    assert sm.current_state == to_state
                else:
                    with pytest.raises(InvalidStateTransitionError):
                        sm.transition_to(to_state, reason=f"Testing illegal {from_state.value} -> {to_state.value}")

        assert evaluated_pairs == 42
