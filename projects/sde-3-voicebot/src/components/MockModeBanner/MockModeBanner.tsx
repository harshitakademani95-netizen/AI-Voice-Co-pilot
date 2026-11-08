import React, { useState } from 'react';
import { Sliders, ShieldCheck, Zap, AlertTriangle } from 'lucide-react';
import { apiClient } from '../../api/apiClient';
import { ApiStandardError } from '../../api/types';
import './MockModeBanner.css';

interface MockModeBannerProps {
  onSimulateErrorChange?: (code: ApiStandardError['error']['code'] | null) => void;
}

export const MockModeBanner: React.FC<MockModeBannerProps> = ({ onSimulateErrorChange }) => {
  const [showSettings, setShowSettings] = useState(false);
  const [latency, setLatency] = useState(80);
  const [simulatedError, setSimulatedError] = useState<string>('none');

  const handleLatencyChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const val = Number(e.target.value);
    setLatency(val);
    apiClient.setMockLatency(val);
  };

  const handleErrorSimChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const val = e.target.value;
    setSimulatedError(val);
    const errorCode = val === 'none' ? null : (val as ApiStandardError['error']['code']);
    apiClient.setSimulatedError(errorCode);
    if (onSimulateErrorChange) {
      onSimulateErrorChange(errorCode);
    }
  };

  return (
    <aside
      className="mock-banner"
      role="region"
      aria-label="Mock Mode Information Banner"
    >
      <div className="mock-banner-container">
        <div className="mock-banner-left">
          <span className="mock-badge" aria-label="Mock Mode Active Badge">
            <Zap size={14} aria-hidden="true" />
            Mock Mode
          </span>
          <span className="mock-banner-text">
            Operating with fixture data & simulated API contracts. <span className="mock-banner-highlight">No paid API keys required.</span>
          </span>
        </div>

        <div className="mock-banner-right">
          <div className="mock-chip" title="Mock gateway operational">
            <span className="mock-chip-dot" aria-hidden="true"></span>
            <span>Gateway: Ready</span>
          </div>

          <div className="mock-chip" title="Simulated latency">
            <ShieldCheck size={14} color="#34d399" aria-hidden="true" />
            <span>Sandbox Safe</span>
          </div>

          <button
            type="button"
            className="mock-config-btn"
            onClick={() => setShowSettings(!showSettings)}
            aria-expanded={showSettings}
            aria-controls="mock-controls-panel"
          >
            <Sliders size={13} aria-hidden="true" />
            <span>{showSettings ? 'Hide Mock Controls' : 'Configure Mocks'}</span>
          </button>
        </div>

        {showSettings && (
          <div
            id="mock-controls-panel"
            className="mock-controls-panel"
            aria-label="Mock environment tuning options"
          >
            <div className="mock-control-item">
              <label htmlFor="mock-latency-select">Simulated Latency:</label>
              <select
                id="mock-latency-select"
                value={latency}
                onChange={handleLatencyChange}
                aria-label="Select simulated network latency"
              >
                <option value={0}>0ms (Instant)</option>
                <option value={80}>80ms (Fast)</option>
                <option value={300}>300ms (Realistic)</option>
                <option value={800}>800ms (High Latency)</option>
              </select>
            </div>

            <div className="mock-control-item">
              <label htmlFor="mock-error-select">Simulate Contract Error:</label>
              <select
                id="mock-error-select"
                value={simulatedError}
                onChange={handleErrorSimChange}
                aria-label="Simulate API contract error condition"
              >
                <option value="none">None (200 OK)</option>
                <option value="INVALID_REQUEST">400 INVALID_REQUEST</option>
                <option value="PERMISSION_DENIED">403 PERMISSION_DENIED</option>
                <option value="TOOL_EXECUTION_FAILED">422 TOOL_EXECUTION_FAILED</option>
                <option value="INTERNAL_ERROR">500 INTERNAL_ERROR</option>
              </select>
            </div>

            {simulatedError !== 'none' && (
              <div
                className="mock-control-item"
                style={{ color: 'var(--color-warning)' }}
                role="status"
              >
                <AlertTriangle size={14} aria-hidden="true" />
                <span>Error injection active: Next API calls will simulate error response.</span>
              </div>
            )}
          </div>
        )}
      </div>
    </aside>
  );
};
