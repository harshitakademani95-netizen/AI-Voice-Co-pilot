import { useState, useEffect, useCallback } from 'react';
import { SessionStatus } from '../api/types';
import { apiClient } from '../api/apiClient';

export interface UseSessionReturn {
  sessionId: string;
  status: SessionStatus;
  durationSeconds: number;
  turnCount: number;
  activeApp: string;
  startSession: () => Promise<void>;
  pauseSession: () => void;
  resumeSession: () => void;
  endSession: () => void;
  resetSession: () => void;
  incrementTurn: () => void;
  formatDuration: (seconds: number) => string;
}

export const useSession = (initialSessionId = 'session-001'): UseSessionReturn => {
  const [sessionId, setSessionId] = useState(initialSessionId);
  const [status, setStatus] = useState<SessionStatus>('active');
  const [durationSeconds, setDurationSeconds] = useState(185); // 3m 5s elapsed in mock
  const [turnCount, setTurnCount] = useState(3);
  const [activeApp, setActiveApp] = useState('VS Code');

  // Duration timer when active
  useEffect(() => {
    let timer: any = null;
    if (status === 'active') {
      timer = setInterval(() => {
        setDurationSeconds((prev) => prev + 1);
      }, 1000);
    }
    return () => {
      if (timer) clearInterval(timer);
    };
  }, [status]);

  const startSession = useCallback(async () => {
    const newId = `session-${Math.floor(100 + Math.random() * 900)}`;
    setSessionId(newId);
    setStatus('active');
    setDurationSeconds(0);
    setTurnCount(0);
    setActiveApp('VS Code');
    try {
      await apiClient.getSession(newId);
    } catch {
      // Fallback in case of mock error
    }
  }, []);

  const pauseSession = useCallback(() => {
    setStatus('paused');
  }, []);

  const resumeSession = useCallback(() => {
    setStatus('active');
  }, []);

  const endSession = useCallback(() => {
    setStatus('ended');
  }, []);

  const resetSession = useCallback(() => {
    setSessionId(`session-001`);
    setStatus('idle');
    setDurationSeconds(0);
    setTurnCount(0);
    setActiveApp('VS Code');
  }, []);

  const incrementTurn = useCallback(() => {
    setTurnCount((prev) => prev + 1);
  }, []);

  const formatDuration = useCallback((seconds: number): string => {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
  }, []);

  return {
    sessionId,
    status,
    durationSeconds,
    turnCount,
    activeApp,
    startSession,
    pauseSession,
    resumeSession,
    endSession,
    resetSession,
    incrementTurn,
    formatDuration,
  };
};
