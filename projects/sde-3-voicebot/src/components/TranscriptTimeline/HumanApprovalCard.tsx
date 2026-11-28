import React, { useState } from 'react';
import { ShieldCheck, ShieldAlert, Check, X, AlertTriangle } from 'lucide-react';
import { RiskLevel } from '../../api/types';
import { apiClient, ApiClientError } from '../../api/apiClient';

interface HumanApprovalCardProps {
  approvalId: string;
  sessionId: string;
  toolName: string;
  riskLevel: RiskLevel;
  changeSummary: string;
  target?: string;
  initialStatus?: 'pending' | 'approved' | 'rejected';
  onDecision: (decision: 'approved' | 'rejected') => void;
}

export const HumanApprovalCard: React.FC<HumanApprovalCardProps> = ({
  approvalId,
  sessionId,
  toolName,
  riskLevel,
  changeSummary,
  target,
  initialStatus = 'pending',
  onDecision,
}) => {
  const [status, setStatus] = useState<'pending' | 'approved' | 'rejected'>(initialStatus);
  const [loading, setLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const handleDecision = async (decision: 'approved' | 'rejected') => {
    setLoading(true);
    setErrorMessage(null);
    try {
      await apiClient.submitApproval({
        session_id: sessionId,
        approval_id: approvalId,
        decision,
      });
      setStatus(decision);
      onDecision(decision);
    } catch (err: unknown) {
      if (err instanceof ApiClientError) {
        setErrorMessage(`Approval submission failed [${err.code}]: ${err.message}`);
      } else if (err instanceof Error) {
        setErrorMessage(`Approval submission failed: ${err.message}`);
      } else {
        setErrorMessage('Approval submission failed. Please retry.');
      }
    } finally {
      setLoading(false);
    }
  };

  const getRiskColor = (level: RiskLevel) => {
    switch (level) {
      case 'D': return { bg: 'rgba(239, 68, 68, 0.15)', border: '#ef4444', text: '#fca5a5', label: 'Level D: High-Risk / Destructive' };
      case 'C': return { bg: 'rgba(245, 158, 11, 0.15)', border: '#f59e0b', text: '#fde68a', label: 'Level C: Sensitive Action' };
      case 'B': return { bg: 'rgba(59, 130, 246, 0.15)', border: '#3b82f6', text: '#93c5fd', label: 'Level B: Low-Risk Interaction' };
      default: return { bg: 'rgba(16, 185, 129, 0.15)', border: '#10b981', text: '#a7f3d0', label: 'Level A: Informational' };
    }
  };

  const riskBadge = getRiskColor(riskLevel);

  return (
    <div
      className="approval-card"
      style={{
        backgroundColor: 'var(--bg-surface-elevated)',
        border: `1px solid ${status === 'pending' ? riskBadge.border : 'var(--border-subtle)'}`,
        borderRadius: 'var(--radius-md)',
        padding: '14px',
        marginTop: '8px',
      }}
      role="region"
      aria-label={`Human approval request for ${toolName}`}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <span
          style={{
            backgroundColor: riskBadge.bg,
            color: riskBadge.text,
            border: `1px solid ${riskBadge.border}`,
            padding: '2px 8px',
            borderRadius: 'var(--radius-sm)',
            fontSize: '0.75rem',
            fontWeight: 600,
            display: 'inline-flex',
            alignItems: 'center',
            gap: 4,
          }}
        >
          <AlertTriangle size={12} aria-hidden="true" />
          {riskBadge.label}
        </span>

        <span style={{ fontSize: '0.75rem', color: 'var(--text-dim)', fontFamily: 'monospace' }}>
          ID: {approvalId}
        </span>
      </div>

      <div style={{ fontSize: '0.875rem', color: 'var(--text-main)', marginBottom: 6 }}>
        <strong>Tool Requested:</strong> <code style={{ background: '#0f172a', padding: '2px 6px', borderRadius: 4 }}>{toolName}</code>
      </div>

      {target && (
        <div style={{ fontSize: '0.8125rem', color: 'var(--text-muted)', marginBottom: 6 }}>
          <strong>Target:</strong> <code style={{ background: '#0f172a', padding: '2px 6px', borderRadius: 4 }}>{target}</code>
        </div>
      )}

      <div style={{ fontSize: '0.8125rem', color: 'var(--text-muted)', marginBottom: 12 }}>
        {changeSummary}
      </div>

      {errorMessage && (
        <div
          role="alert"
          style={{
            backgroundColor: 'var(--color-danger-bg)',
            border: '1px solid rgba(239, 68, 68, 0.4)',
            color: '#fca5a5',
            padding: '8px 12px',
            borderRadius: 'var(--radius-md)',
            fontSize: '0.8125rem',
            marginBottom: '12px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: '8px',
          }}
        >
          <span>{errorMessage}</span>
          <button
            type="button"
            onClick={() => handleDecision('approved')}
            disabled={loading}
            style={{
              background: 'transparent',
              border: 'none',
              color: '#fca5a5',
              textDecoration: 'underline',
              cursor: 'pointer',
              fontWeight: 600,
              fontSize: '0.75rem',
              padding: '2px 6px',
            }}
            aria-label="Retry approval submission"
          >
            Retry
          </button>
        </div>
      )}

      {status === 'pending' ? (
        <div style={{ display: 'flex', gap: 10 }}>
          <button
            type="button"
            onClick={() => handleDecision('approved')}
            disabled={loading}
            style={{
              backgroundColor: 'var(--color-success)',
              color: 'white',
              padding: '6px 14px',
              borderRadius: 'var(--radius-md)',
              fontWeight: 600,
              fontSize: '0.8125rem',
              display: 'inline-flex',
              alignItems: 'center',
              gap: 6,
            }}
            aria-label="Authorize and approve tool execution"
          >
            <Check size={14} aria-hidden="true" />
            <span>Approve Action</span>
          </button>

          <button
            type="button"
            onClick={() => handleDecision('rejected')}
            disabled={loading}
            style={{
              backgroundColor: 'var(--color-danger-bg)',
              color: 'var(--color-danger)',
              border: '1px solid rgba(239, 68, 68, 0.4)',
              padding: '6px 14px',
              borderRadius: 'var(--radius-md)',
              fontWeight: 600,
              fontSize: '0.8125rem',
              display: 'inline-flex',
              alignItems: 'center',
              gap: 6,
            }}
            aria-label="Reject tool execution"
          >
            <X size={14} aria-hidden="true" />
            <span>Reject</span>
          </button>
        </div>
      ) : status === 'approved' ? (
        <div
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 6,
            color: 'var(--color-success)',
            fontSize: '0.8125rem',
            fontWeight: 600,
          }}
          role="status"
        >
          <ShieldCheck size={16} aria-hidden="true" />
          <span>Action Approved by User — Dispatched for safe execution</span>
        </div>
      ) : (
        <div
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 6,
            color: 'var(--color-danger)',
            fontSize: '0.8125rem',
            fontWeight: 600,
          }}
          role="status"
        >
          <ShieldAlert size={16} aria-hidden="true" />
          <span>Action Rejected by User — Operation aborted</span>
        </div>
      )}
    </div>
  );
};
