import React, { useState } from 'react';
import { AppShell } from './components/AppShell/AppShell';
import { SessionControls } from './components/SessionControls/SessionControls';
import { MicrophoneControl } from './components/MicrophoneControl/MicrophoneControl';
import { TranscriptTimeline } from './components/TranscriptTimeline/TranscriptTimeline';
import { DemoRunner } from './components/DemoRunner/DemoRunner';
import { useSession } from './hooks/useSession';
import { useMicrophone } from './hooks/useMicrophone';
import { TimelineEvent, ApiStandardError, MicrophonePermissionState } from './api/types';
import { INITIAL_FIXTURE_EVENTS } from './fixtures/mockTimelineEvents';
import { apiClient } from './api/apiClient';
import { AlertCircle } from 'lucide-react';
import './App.css';

export const App: React.FC = () => {
  const session = useSession('session-001');
  const mic = useMicrophone('granted');
  const [events, setEvents] = useState<TimelineEvent[]>(INITIAL_FIXTURE_EVENTS);
  const [apiError, setApiError] = useState<string | null>(null);

  // Handle Voice Simulation Flow
  const handleSimulateVoiceInput = async () => {
    setApiError(null);
    try {
      // 1. Microphone state feedback
      mic.startListening();
      await new Promise((r) => setTimeout(r, 600));

      mic.setProcessing();
      const transcribed = await apiClient.transcribeAudio({
        session_id: session.sessionId,
        format: 'pcm',
      });

      const now = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
      const userEvt: TimelineEvent = {
        id: `evt-${Date.now()}-user`,
        timestamp: now,
        type: 'user_voice',
        actor: 'user',
        title: 'User Voice Input',
        content: transcribed.transcript,
        metadata: {
          confidence: transcribed.confidence,
          audio_duration_seconds: 2.8,
        },
      };

      // 2. Fetch context
      const contextRes = await apiClient.submitContext({
        session_id: session.sessionId,
        application: session.activeApp,
        user_query: transcribed.transcript,
      });

      const contextEvt: TimelineEvent = {
        id: `evt-${Date.now()}-ctx`,
        timestamp: now,
        type: 'system_context',
        actor: 'context_engine',
        title: `Context Captured: ${contextRes.application}`,
        content: contextRes.relevant_context,
        metadata: {
          application: contextRes.application,
        },
      };

      // 3. AI chat reasoning
      const chatRes = await apiClient.sendChatMessage({
        session_id: session.sessionId,
        message: transcribed.transcript,
        context_id: contextRes.context_id,
      });

      const aiEvt: TimelineEvent = {
        id: `evt-${Date.now()}-ai`,
        timestamp: now,
        type: 'ai_response',
        actor: 'assistant',
        title: 'Co-Pilot Answer',
        content: chatRes.response,
      };

      const ttsEvt: TimelineEvent = {
        id: `evt-${Date.now()}-tts`,
        timestamp: now,
        type: 'voice_output',
        actor: 'assistant',
        title: 'Text-to-Speech Output',
        content: chatRes.response,
        metadata: { audio_duration_seconds: 3.5 },
      };

      setEvents((prev) => [...prev, userEvt, contextEvt, aiEvt, ttsEvt]);
      session.incrementTurn();

      // 4. Voice response state
      mic.setSpeaking();
      setTimeout(() => {
        mic.setIdle();
      }, 3500);
    } catch (err: any) {
      mic.setIdle();
      setApiError(err?.message || 'Error occurred during voice simulation.');
    }
  };

  const handleApprovalDecision = (approvalId: string, decision: 'approved' | 'rejected') => {
    setEvents((prev) =>
      prev.map((evt) => {
        if (evt.metadata?.approval_id === approvalId) {
          return {
            ...evt,
            metadata: {
              ...evt.metadata,
              approval_status: decision,
            },
          };
        }
        return evt;
      })
    );

    // Follow up execution event
    const now = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    if (decision === 'approved') {
      const followUp: TimelineEvent = {
        id: `evt-${Date.now()}-exec`,
        timestamp: now,
        type: 'tool_execution',
        actor: 'tool',
        title: 'Tool Executed Post-Approval',
        content: 'Controlled action write_file executed successfully on ./requirements.txt after explicit user authorization.',
        metadata: {
          risk_level: 'C',
          tool_name: 'write_file',
        },
      };
      setEvents((prev) => [...prev, followUp]);
    } else {
      const cancelEvt: TimelineEvent = {
        id: `evt-${Date.now()}-reject`,
        timestamp: now,
        type: 'system_notification',
        actor: 'safety_gate',
        title: 'Action Aborted by User',
        content: 'Modification was rejected by user. Safety policy enforced; tool execution cancelled.',
      };
      setEvents((prev) => [...prev, cancelEvt]);
    }
  };

  const handleSimulateVoiceSpeaking = () => {
    mic.setSpeaking();
    setTimeout(() => {
      mic.setIdle();
    }, 3000);
  };

  return (
    <AppShell
      onSimulateErrorChange={(code: ApiStandardError['error']['code'] | null) => {
        if (code) {
          setApiError(`Simulating API Contract Error: ${code}`);
        } else {
          setApiError(null);
        }
      }}
      sidebarControls={
        <>
          {apiError && (
            <div className="api-error-alert" role="alert">
              <AlertCircle size={16} aria-hidden="true" />
              <span>{apiError}</span>
            </div>
          )}

          <SessionControls
            sessionId={session.sessionId}
            status={session.status}
            durationFormatted={session.formatDuration(session.durationSeconds)}
            turnCount={session.turnCount}
            activeApp={session.activeApp}
            onStart={session.startSession}
            onPause={session.pauseSession}
            onResume={session.resumeSession}
            onEnd={session.endSession}
            onReset={session.resetSession}
          />

          <div
            className="demo-mic-perm-container"
            style={{
              background: 'var(--bg-surface)',
              border: '1px solid var(--border-subtle)',
              borderRadius: 'var(--radius-lg)',
              padding: '12px 16px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: '10px',
            }}
          >
            <label
              htmlFor="demo-mic-perm-select"
              style={{
                fontSize: '0.8125rem',
                fontWeight: 600,
                color: 'var(--text-main)',
              }}
            >
              Demo: set microphone permission
            </label>
            <select
              id="demo-mic-perm-select"
              value={mic.permission}
              onChange={(e) => mic.setPermission(e.target.value as MicrophonePermissionState)}
              style={{
                background: 'var(--bg-surface-elevated)',
                border: '1px solid var(--border-subtle)',
                color: 'var(--text-main)',
                padding: '4px 10px',
                borderRadius: 'var(--radius-md)',
                fontSize: '0.8125rem',
              }}
              aria-label="Demo: set microphone permission"
            >
              <option value="prompt">prompt</option>
              <option value="granted">granted</option>
              <option value="denied">denied</option>
            </select>
          </div>

          <MicrophoneControl
            permission={mic.permission}
            activity={mic.activity}
            isMuted={mic.isMuted}
            onRequestPermission={(grant) => mic.requestPermission(grant)}
            onToggleMute={mic.toggleMute}
            onStartListening={mic.startListening}
            onStopListening={mic.stopListening}
            onInterruptAi={mic.interruptAi}
            onTestVoiceInput={handleSimulateVoiceInput}
          />

          <DemoRunner
            onLoadEvents={(newEvents) => setEvents(newEvents)}
            onAddEvent={(newEvt) => setEvents((prev) => [...prev, newEvt])}
            onClearEvents={() => setEvents([])}
            onSimulateVoiceSpeaking={handleSimulateVoiceSpeaking}
          />
        </>
      }
    >
      <TranscriptTimeline
        events={events}
        sessionId={session.sessionId}
        onClearEvents={() => setEvents([])}
        onApprovalDecision={handleApprovalDecision}
      />
    </AppShell>
  );
};

export default App;
