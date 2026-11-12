import React from 'react';
import { Bot, Radio } from 'lucide-react';
import { SkipLink } from './SkipLink';
import { MockModeBanner } from '../MockModeBanner/MockModeBanner';
import { ApiStandardError } from '../../api/types';
import './AppShell.css';

interface AppShellProps {
  children: React.ReactNode;
  sidebarControls: React.ReactNode;
  onSimulateErrorChange?: (code: ApiStandardError['error']['code'] | null) => void;
}

export const AppShell: React.FC<AppShellProps> = ({
  children,
  sidebarControls,
  onSimulateErrorChange,
}) => {
  return (
    <div className="app-layout">
      <SkipLink />

      {/* Prominent Mock-Mode Banner */}
      <MockModeBanner onSimulateErrorChange={onSimulateErrorChange} />

      {/* Accessible Header Landmark */}
      <header className="app-header" role="banner">
        <div className="header-inner">
          <div className="brand-section">
            <div className="brand-icon" aria-hidden="true">
              <Bot size={22} />
            </div>
            <div>
              <h1 className="brand-title">AI Voice Co-Pilot</h1>
              <div className="brand-subtitle">
                Context-Aware Multimodal Desktop Companion
              </div>
            </div>
          </div>

          <div className="header-meta">
            <span className="team-badge" aria-label="Workstream Assignment">
              W6: Frontend & UX
            </span>
            <div
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 6,
                fontSize: '0.8125rem',
                color: 'var(--text-muted)',
              }}
              role="status"
            >
              <Radio size={14} color="var(--color-success)" aria-hidden="true" />
              <span>Mock Workspace</span>
            </div>
          </div>
        </div>
      </header>

      {/* Accessible Main Layout Landmark */}
      <div className="app-main-layout">
        {/* Sidebar Controls Landmark */}
        <aside
          className="app-sidebar"
          role="complementary"
          aria-label="Session & Input Controls"
        >
          {sidebarControls}
        </aside>

        {/* Primary Content Landmark */}
        <main id="main-content" className="app-content-region" tabIndex={-1}>
          {children}
        </main>
      </div>

      {/* Accessible Footer Landmark */}
      <footer className="app-footer" role="contentinfo">
        <div className="footer-inner">
          <div>
            AI Voice Co-Pilot • Week 1 Vertical Slice • SDE 3 | Varsha B S | W6 Frontend & UX
          </div>
          <div>
            Mock Mode Active • Compliant with 04. API Specs & PRD V1.0 • No External Keys Required
          </div>
        </div>
      </footer>
    </div>
  );
};
