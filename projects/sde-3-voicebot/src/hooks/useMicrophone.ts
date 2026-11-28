import { useState, useCallback } from 'react';
import { MicrophonePermissionState, MicrophoneActivityState } from '../api/types';

export interface UseMicrophoneReturn {
  permission: MicrophonePermissionState;
  activity: MicrophoneActivityState;
  isMuted: boolean;
  requestPermission: (grantOrDeny?: boolean) => Promise<boolean>;
  setPermission: (perm: MicrophonePermissionState) => void;
  toggleMute: () => void;
  startListening: () => void;
  stopListening: () => void;
  setProcessing: () => void;
  setSpeaking: () => void;
  setIdle: () => void;
  interruptAi: () => void;
  simulateAudioInput: (spokenPhrase: string) => Promise<string>;
}

export const useMicrophone = (
  initialPermission: MicrophonePermissionState = 'granted'
): UseMicrophoneReturn => {
  const [permission, setPermission] = useState<MicrophonePermissionState>(initialPermission);
  const [activity, setActivity] = useState<MicrophoneActivityState>('idle');
  const [isMuted, setIsMuted] = useState(false);

  const requestPermission = useCallback(async (grantOrDeny = true): Promise<boolean> => {
    const outcome: MicrophonePermissionState = grantOrDeny ? 'granted' : 'denied';
    setPermission(outcome);
    return grantOrDeny;
  }, []);

  const toggleMute = useCallback(() => {
    setIsMuted((prev) => {
      const next = !prev;
      if (next) {
        setActivity((act) => (act === 'listening' ? 'idle' : act));
      }
      return next;
    });
  }, []);

  const startListening = useCallback(() => {
    if (permission !== 'granted') return;
    if (isMuted) return;
    setActivity('listening');
  }, [permission, isMuted]);

  const stopListening = useCallback(() => {
    setActivity((prev) => (prev === 'listening' ? 'idle' : prev));
  }, []);

  const setProcessing = useCallback(() => {
    setActivity('processing');
  }, []);

  const setSpeaking = useCallback(() => {
    setActivity('speaking');
  }, []);

  const setIdle = useCallback(() => {
    setActivity('idle');
  }, []);

  const interruptAi = useCallback(() => {
    // FR-VOICE-004: Mechanism for users to interrupt an AI response
    setActivity((prev) => (prev === 'speaking' ? 'idle' : prev));
  }, []);

  const simulateAudioInput = useCallback(
    async (spokenPhrase: string): Promise<string> => {
      if (permission !== 'granted') {
        throw new Error('Microphone permission is not granted');
      }
      if (isMuted) {
        throw new Error('Microphone is muted');
      }

      setActivity('listening');
      await new Promise((r) => setTimeout(r, 600));
      setActivity('processing');
      await new Promise((r) => setTimeout(r, 500));
      setActivity('idle');
      return spokenPhrase;
    },
    [permission, isMuted]
  );

  return {
    permission,
    activity,
    isMuted,
    requestPermission,
    setPermission,
    toggleMute,
    startListening,
    stopListening,
    setProcessing,
    setSpeaking,
    setIdle,
    interruptAi,
    simulateAudioInput,
  };
};
