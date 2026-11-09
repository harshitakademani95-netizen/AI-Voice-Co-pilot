import React, { useState, useCallback, useRef, useEffect } from 'react';
import { AppShell } from './components/AppShell/AppShell';
import { SessionControls } from './components/SessionControls/SessionControls';
import { MicrophoneControl } from './components/MicrophoneControl/MicrophoneControl';
import { TranscriptTimeline } from './components/TranscriptTimeline/TranscriptTimeline';
import { ContextPanel } from './components/ContextPanel/ContextPanel';
import { CaptureStatus } from './components/CaptureStatus/CaptureStatus';
import { DemoRunner } from './components/DemoRunner/DemoRunner';
import { useSession } from './hooks/useSession';
import { useMicrophone } from './hooks/useMicrophone';
import {
  TimelineEvent,
  ApiStandardError,
  MicrophonePermissionState,
  ApplicationStatusState,
  AppContextData,
} from './api/types';
import { INITIAL_FIXTURE_EVENTS } from './fixtures/mockTimelineEvents';
import { apiClient } from './api/apiClient';
import { AlertCircle, Radio, Sparkles } from 'lucide-react';
import './App.css';

export const App: React.FC = () => {
  const session = useSession('session-001');
  const mic = useMicrophone('granted');
  const [events, setEvents] = useState<TimelineEvent[]>(INITIAL_FIXTURE_EVENTS);
  const [apiError, setApiError] = useState<string | null>(null);
  const [appStatus, setAppStatus] = useState<ApplicationStatusState>(
    typeof navigator !== 'undefined' && !navigator.onLine ? 'offline' : 'online'
  );
  const [ariaAnnouncement, setAriaAnnouncement] = useState<string>('System ready in Mock Mode');

  // Listen for real browser connectivity transitions
  useEffect(() => {
    const handleOnline = () => {
      setAppStatus('online');
      setAriaAnnouncement('Application online.');
    };
    const handleOffline = () => {
      setAppStatus('offline');
      setAriaAnnouncement('Application offline.');
    };

    if (typeof window !== 'undefined') {
      window.addEventListener('online', handleOnline);
      window.addEventListener('offline', handleOffline);
    }
    return () => {
      if (typeof window !== 'undefined') {
        window.removeEventListener('online', handleOnline);
        window.removeEventListener('offline', handleOffline);
      }
    };
  }, []);

  // Days 12-13: Screen Context OFF by default as required
  const [contextData, setContextData] = useState<AppContextData>({
    activeApp: 'VS Code',
    windowTitle: 'main.py - AI Voice Co-Pilot - Visual Studio Code',
    sessionId: session.sessionId,
    screenContextEnabled: false, // OFF by default (Strict Privacy Requirement)
    screenContextStatus: 'disabled',
    lastUpdated: '10:04:23 AM',
    freshnessState: 'fresh',
    details: 'Terminal error: ModuleNotFoundError: No module named \'fastapi\'. Active file: main.py:12.',
    terminalOutput: undefined, // empty while disabled
    sources: [
      {
        id: 'user_voice',
        label: 'User Voice Request',
        description: 'Microphone speech recognition input',
        active: true,
      },
      {
        id: 'active_app',
        label: 'Active Application',
        description: 'Foreground workspace window tracking',
        active: true,
      },
      {
        id: 'screen_context',
        label: 'Screen Context',
        description: 'Visual window snapshot & code recognition',
        active: false, // OFF by default
      },
      {
        id: 'document_context',
        label: 'Document Context',
        description: 'Workspace files, requirements.txt, project tree',
        active: true,
      },
      {
        id: 'conversation_history',
        label: 'Conversation History',
        description: 'Prior session turns and execution memory',
        active: true,
      },
    ],
  });

  // Handle Pause Session
  const handlePauseSession = useCallback(() => {
    session.pauseSession();
    mic.setPaused();
    setAriaAnnouncement('Session paused.');
  }, [session, mic]);

  // Handle Resume Session
  const handleResumeSession = useCallback(() => {
    session.resumeSession();
    mic.setIdle();
    setAriaAnnouncement('Session resumed.');
  }, [session, mic]);

  // Handle End Session
  const handleEndSession = useCallback(() => {
    session.endSession();
    mic.setIdle();
    setAriaAnnouncement('Session ended.');
  }, [session, mic]);

  // Reference to active screen capture MediaStream to safely release hardware tracks
  const activeScreenStreamRef = useRef<MediaStream | null>(null);

  const stopScreenStream = useCallback(() => {
    if (activeScreenStreamRef.current) {
      try {
        const tracks = activeScreenStreamRef.current.getTracks();
        tracks.forEach((track) => {
          if (track.readyState === 'live') {
            track.stop();
          }
        });
      } catch {
        // Safe fallback
      }
      activeScreenStreamRef.current = null;
    }
  }, []);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      stopScreenStream();
    };
  }, [stopScreenStream]);

  const handleClearScreenError = useCallback(() => {
    setContextData((prev) => ({
      ...prev,
      errorMessage: undefined,
      screenContextStatus: prev.screenContextEnabled ? 'active' : 'disabled',
    }));
  }, []);

  // Handle Screen Context Toggle (Privacy Controlled + Browser Permission Explicitly Requested)
  const handleToggleScreenContext = useCallback(
    async (enabled: boolean) => {
      if (!enabled) {
        stopScreenStream();
        setContextData((prev) => {
          const now = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
          return {
            ...prev,
            screenContextEnabled: false,
            screenContextStatus: 'disabled',
            errorMessage: undefined,
            lastUpdated: now,
            terminalOutput: undefined,
          };
        });
        setAriaAnnouncement('Screen Context disabled.');
        return;
      }

      // Enabling: Keep Screen Context OFF until permission is explicitly granted
      setContextData((prev) => ({
        ...prev,
        screenContextStatus: 'loading',
        errorMessage: undefined,
      }));

      try {
        if (
          typeof navigator === 'undefined' ||
          !navigator.mediaDevices ||
          typeof navigator.mediaDevices.getDisplayMedia !== 'function'
        ) {
          throw new Error('Screen capture is unavailable or not supported in this browser environment.');
        }

        // Explicitly request browser screen capture permission
        const stream = await navigator.mediaDevices.getDisplayMedia({ video: true });

        if (!stream) {
          throw new Error('Screen capture permission was denied.');
        }

        activeScreenStreamRef.current = stream;

        // Auto-disable if user stops sharing via native browser UI
        const tracks = stream.getVideoTracks ? stream.getVideoTracks() : stream.getTracks ? stream.getTracks() : [];
        if (tracks.length > 0 && tracks[0]) {
          tracks[0].onended = () => {
            stopScreenStream();
            setContextData((prev) => ({
              ...prev,
              screenContextEnabled: false,
              screenContextStatus: 'disabled',
              terminalOutput: undefined,
            }));
            setAriaAnnouncement('Screen Context disabled.');
          };
        }

        const now = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        setContextData((prev) => ({
          ...prev,
          screenContextEnabled: true,
          screenContextStatus: 'active',
          errorMessage: undefined,
          lastUpdated: now,
          terminalOutput:
            "Terminal output: ModuleNotFoundError: No module named 'fastapi'.\nActive window: VS Code.\nVisible lines: 1-28 in main.py.",
        }));
        setAriaAnnouncement('Screen Context enabled.');
      } catch (err: unknown) {
        stopScreenStream();
        const errObj = err as { name?: string; message?: string };
        let message =
          'Screen capture permission was denied. Please allow screen sharing in your browser settings to enable screen context.';

        if (
          errObj?.name === 'NotAllowedError' ||
          errObj?.name === 'PermissionDeniedError' ||
          errObj?.name === 'AbortError' ||
          errObj?.message?.toLowerCase().includes('denied') ||
          errObj?.message?.toLowerCase().includes('cancel') ||
          errObj?.message?.toLowerCase().includes('dismiss')
        ) {
          message =
            'Screen capture permission was denied or cancelled. Please allow screen sharing in your browser settings to enable screen context.';
        } else if (
          errObj?.name === 'NotFoundError' ||
          errObj?.name === 'NotSupportedError' ||
          errObj?.message?.toLowerCase().includes('unavailable') ||
          errObj?.message?.toLowerCase().includes('not supported')
        ) {
          message = 'Screen capture is unavailable or not supported in this browser environment.';
        } else if (errObj?.message) {
          message = errObj.message;
        }

        setContextData((prev) => ({
          ...prev,
          screenContextEnabled: false,
          screenContextStatus: 'unavailable',
          errorMessage: message,
          terminalOutput: undefined,
        }));
        setAriaAnnouncement(`Screen capture error: ${message}`);
      }
    },
    [stopScreenStream]
  );

  // Handle Refresh Context
  const handleRefreshContext = useCallback(() => {
    const now = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    setContextData((prev) => ({
      ...prev,
      lastUpdated: now,
      freshnessState: 'fresh',
    }));
    setAriaAnnouncement('Workspace context refreshed successfully.');
  }, []);

  // Handle Clear Context
  const handleClearContext = useCallback(() => {
    setContextData((prev) => ({
      ...prev,
      details: undefined,
      terminalOutput: undefined,
      freshnessState: 'unavailable',
    }));
    setAriaAnnouncement('Active context cleared.');
  }, []);

  // Days 10-11: Demonstrate Interim Transcript -> Final Transcript Replacement (Supports Multiple Segments)
  const handleSimulateInterimAndFinalSpeech = async (customSegmentId?: string, customText?: string) => {
    if (session.status === 'paused') {
      const msg = 'Session is currently paused. Please resume the session to capture audio.';
      setApiError(msg);
      setAriaAnnouncement(`Error occurred: ${msg}`);
      return;
    }
    if (session.status === 'ended') {
      const msg = 'Session has ended. Please start a new session to capture audio.';
      setApiError(msg);
      setAriaAnnouncement(`Error occurred: ${msg}`);
      return;
    }
    setApiError(null);

    const segmentId = customSegmentId || `seg-${Date.now()}-${Math.floor(Math.random() * 1000)}`;
    const now = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });

    // Step 1: Emit Interim Transcript Event
    mic.startListening();
    setAriaAnnouncement('Microphone listening.');

    const interimEvt: TimelineEvent = {
      id: `evt-${Date.now()}-interim`,
      segment_id: segmentId,
      timestamp: now,
      type: 'user_voice',
      actor: 'user',
      title: 'User Voice Input (Streaming)',
      content: customText ? `${customText.slice(0, 15)}...` : 'Why is my Fast...',
      is_interim: true,
      metadata: {
        confidence: 0.82,
        audio_duration_seconds: 1.2,
      },
    };

    setEvents((prev) => [...prev, interimEvt]);
    setAriaAnnouncement(`Transcript interim update: ${interimEvt.content}`);

    // Wait simulated recognition latency
    await new Promise((r) => setTimeout(r, 700));

    // Step 2: Replace Interim with Final Transcript Event (No duplicate entry!)
    mic.setProcessing();
    const finalNow = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    const finalEvt: TimelineEvent = {
      id: `evt-${Date.now()}-final`,
      segment_id: segmentId,
      timestamp: finalNow,
      type: 'user_voice',
      actor: 'user',
      title: 'User Voice Input',
      content: customText || 'Why is my FastAPI backend failing with this error?',
      is_final: true,
      metadata: {
        confidence: 0.98,
        audio_duration_seconds: 3.2,
      },
    };

    setEvents((prev) =>
      prev.map((evt) => (evt.segment_id === segmentId ? finalEvt : evt))
    );
    session.incrementTurn();
    mic.setIdle();
    setAriaAnnouncement(`Final transcript received: ${finalEvt.content}`);
  };

  // Days 10-11: Demonstrate Transcript Revision with Preserved History
  const handleSimulateTranscriptRevision = () => {
    setEvents((prev) => {
      // Find the most recent final user voice event to revise
      const targetIndex = [...prev].reverse().findIndex((e) => e.type === 'user_voice' && e.is_final);
      if (targetIndex === -1) return prev;

      const actualIndex = prev.length - 1 - targetIndex;
      const target = prev[actualIndex];

      const now = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
      const revisedEvent: TimelineEvent = {
        ...target,
        title: 'User Voice Input (Corrected)',
        content: 'Why is my FastAPI backend failing with ModuleNotFoundError: No module named \'fastapi\'?',
        is_revised: true,
        revision_history: [
          ...(target.revision_history || []),
          {
            revision_number: (target.revision_history?.length || 0) + 1,
            timestamp: target.timestamp,
            content: target.content,
            confidence: target.metadata?.confidence,
            reason: 'Acoustic refinement from domain dictionary',
          },
        ],
        timestamp: now,
      };

      const nextEvents = [...prev];
      nextEvents[actualIndex] = revisedEvent;
      return nextEvents;
    });

    setAriaAnnouncement('Transcript revised: Why is my FastAPI backend failing with ModuleNotFoundError: No module named \'fastapi\'?');
  };

  // Handle Standard Voice Simulation Flow
  const handleSimulateVoiceInput = async () => {
    if (session.status === 'paused') {
      const msg = 'Session is currently paused. Please resume the session to capture audio.';
      setApiError(msg);
      setAriaAnnouncement(`Error occurred: ${msg}`);
      return;
    }
    if (session.status === 'ended') {
      const msg = 'Session has ended. Please start a new session to capture audio.';
      setApiError(msg);
      setAriaAnnouncement(`Error occurred: ${msg}`);
      return;
    }
    if (mic.activity === 'unavailable' || mic.permission === 'denied') {
      const msg = 'Microphone is unavailable or permission is denied.';
      setApiError(msg);
      setAriaAnnouncement('Microphone unavailable.');
      return;
    }

    setApiError(null);
    try {
      mic.startListening();
      setAriaAnnouncement('Microphone listening.');
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
        is_final: true,
        metadata: {
          confidence: transcribed.confidence,
          audio_duration_seconds: 2.8,
        },
      };

      // 2. Fetch context (adhering to screenContextEnabled flag)
      const contextRes = await apiClient.submitContext({
        session_id: session.sessionId,
        application: session.activeApp,
        user_query: transcribed.transcript,
        screen_summary: contextData.screenContextEnabled ? 'VS Code Window Captured' : undefined,
      });

      const contextEvt: TimelineEvent = {
        id: `evt-${Date.now()}-ctx`,
        timestamp: now,
        type: 'system_context',
        actor: 'context_engine',
        title: `Context Captured: ${contextRes.application}`,
        content: contextData.screenContextEnabled
          ? contextRes.relevant_context
          : `Application: ${session.activeApp}. Screen capture disabled by user setting.`,
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
      setAriaAnnouncement(`Final transcript received: ${transcribed.transcript}`);

      // 4. Voice response state
      mic.setSpeaking();
      setTimeout(() => {
        mic.setIdle();
      }, 3500);
    } catch (err: unknown) {
      mic.setIdle();
      const message = err instanceof Error ? err.message : 'Error occurred during voice simulation.';
      setApiError(message);
      setAriaAnnouncement(`Error occurred: ${message}`);
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

  // Handle Application State Retry via typed ApiClient
  const handleAppStatusRetry = async () => {
    setAppStatus('loading');
    setAriaAnnouncement('Retrying service connection...');
    try {
      const health = await apiClient.checkHealth();
      setAppStatus(health.status === 'ok' ? 'online' : 'offline');
      setApiError(null);
      setAriaAnnouncement('Application reconnected successfully. Service online.');
    } catch (err: unknown) {
      setAppStatus('error');
      const msg = err instanceof Error ? err.message : 'Retry failed';
      setApiError(msg);
      setAriaAnnouncement(`Service retry failed: ${msg}`);
    }
  };

  return (
    <AppShell
      onSimulateErrorChange={(code: ApiStandardError['error']['code'] | null) => {
        if (code) {
          setApiError(`Simulating API Contract Error: ${code}`);
          setAppStatus('error');
          setAriaAnnouncement('Error occurred.');
        } else {
          setApiError(null);
          setAppStatus('online');
          setAriaAnnouncement('Application online.');
        }
      }}
      sidebarControls={
        <>
          {/* Accessible Live Region for Announcements */}
          <div className="sr-only" role="status" aria-live="polite" aria-atomic="true">
            {ariaAnnouncement}
          </div>

          {apiError && (
            <div className="api-error-alert" role="alert">
              <AlertCircle size={16} aria-hidden="true" />
              <span>{apiError}</span>
            </div>
          )}

          {/* Days 8-9: System & Capture Status */}
          <CaptureStatus
            micPermission={mic.permission}
            micActivity={mic.activity}
            isMuted={mic.isMuted}
            sessionStatus={session.status}
            screenContextStatus={contextData.screenContextStatus}
            appStatus={appStatus}
            onRetry={handleAppStatusRetry}
            onSetAppStatus={(status) => {
              setAppStatus(status);
              if (status === 'loading') setAriaAnnouncement('Loading started.');
              else if (status === 'offline') setAriaAnnouncement('Application offline.');
              else if (status === 'online') setAriaAnnouncement('Application online.');
              else if (status === 'error') setAriaAnnouncement('Error occurred.');
            }}
          />

          {/* Days 8-9: Session Controls with Functional Pause and Resume */}
          <SessionControls
            sessionId={session.sessionId}
            status={session.status}
            durationFormatted={session.formatDuration(session.durationSeconds)}
            turnCount={session.turnCount}
            activeApp={session.activeApp}
            onStart={session.startSession}
            onPause={handlePauseSession}
            onResume={handleResumeSession}
            onEnd={handleEndSession}
            onReset={session.resetSession}
          />

          {/* Microphone Permission Demo Select */}
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
              onChange={(e) => {
                const val = e.target.value as MicrophonePermissionState;
                mic.setPermission(val);
                if (val === 'denied') {
                  mic.setUnavailable();
                  setAriaAnnouncement('Microphone unavailable.');
                } else if (val === 'granted') {
                  mic.setIdle();
                  setAriaAnnouncement('Microphone permission granted.');
                }
              }}
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

          {/* Microphone & Voice Input Control */}
          <MicrophoneControl
            permission={mic.permission}
            activity={mic.activity}
            isMuted={mic.isMuted}
            onRequestPermission={(grant) => {
              mic.requestPermission(grant);
              if (grant) {
                setAriaAnnouncement('Microphone permission granted.');
              } else {
                setAriaAnnouncement('Microphone unavailable.');
              }
            }}
            onToggleMute={mic.toggleMute}
            onStartListening={() => {
              if (mic.permission !== 'granted') {
                setAriaAnnouncement('Microphone unavailable.');
                return;
              }
              mic.startListening();
              setAriaAnnouncement('Microphone listening.');
            }}
            onStopListening={mic.stopListening}
            onInterruptAi={mic.interruptAi}
            onTestVoiceInput={handleSimulateVoiceInput}
          />

          {/* Days 12-13: Professional Context & Sources Panel */}
          <ContextPanel
            contextData={contextData}
            onToggleScreenContext={handleToggleScreenContext}
            onRefreshContext={handleRefreshContext}
            onClearContext={handleClearContext}
            onClearError={handleClearScreenError}
          />

          {/* Days 10-11: Interactive Demo Actions for Interim & Revisions */}
          <div
            className="week2-actions-card"
            style={{
              background: 'var(--bg-surface)',
              border: '1px solid var(--border-subtle)',
              borderRadius: 'var(--radius-lg)',
              padding: '14px 16px',
              display: 'flex',
              flexDirection: 'column',
              gap: '10px',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <Radio size={14} color="var(--color-primary)" aria-hidden="true" />
              <h3 style={{ fontSize: '0.875rem', fontWeight: 600, color: 'var(--text-main)', margin: 0 }}>
                Week 2 Speech & Revision Demos
              </h3>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <button
                type="button"
                className="btn-mic-action"
                onClick={() => handleSimulateInterimAndFinalSpeech()}
                aria-label="Simulate Interim to Final Speech Recognition"
              >
                <span>Simulate Interim → Final Transcript</span>
              </button>
              <button
                type="button"
                className="btn-mic-action"
                onClick={handleSimulateTranscriptRevision}
                aria-label="Simulate Transcript Revision with History"
              >
                <Sparkles size={14} aria-hidden="true" />
                <span>Simulate Transcript Revision</span>
              </button>
            </div>
          </div>

          {/* Day 7 Demo Runner (Props kept exactly as required) */}
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
