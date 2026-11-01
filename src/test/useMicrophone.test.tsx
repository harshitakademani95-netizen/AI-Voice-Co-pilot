import { describe, it, expect } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useMicrophone } from '../hooks/useMicrophone';

describe('useMicrophone Hook', () => {
  it('startListening then stopListening returns activity to idle', () => {
    const { result } = renderHook(() => useMicrophone('granted'));

    expect(result.current.activity).toBe('idle');

    act(() => {
      result.current.startListening();
    });
    expect(result.current.activity).toBe('listening');

    act(() => {
      result.current.stopListening();
    });
    expect(result.current.activity).toBe('idle');
  });

  it('setSpeaking then interruptAi returns to idle', () => {
    const { result } = renderHook(() => useMicrophone('granted'));

    act(() => {
      result.current.setSpeaking();
    });
    expect(result.current.activity).toBe('speaking');

    act(() => {
      result.current.interruptAi();
    });
    expect(result.current.activity).toBe('idle');
  });

  it('setProcessing then setIdle returns to idle', () => {
    const { result } = renderHook(() => useMicrophone('granted'));

    act(() => {
      result.current.setProcessing();
    });
    expect(result.current.activity).toBe('processing');

    act(() => {
      result.current.setIdle();
    });
    expect(result.current.activity).toBe('idle');
  });

  it('startListening does nothing when permission is denied or when muted', () => {
    // Permission denied
    const { result: deniedResult } = renderHook(() => useMicrophone('denied'));
    expect(deniedResult.current.activity).toBe('idle');

    act(() => {
      deniedResult.current.startListening();
    });
    expect(deniedResult.current.activity).toBe('idle');

    // Muted
    const { result: mutedResult } = renderHook(() => useMicrophone('granted'));
    act(() => {
      mutedResult.current.toggleMute();
    });
    expect(mutedResult.current.isMuted).toBe(true);

    act(() => {
      mutedResult.current.startListening();
    });
    expect(mutedResult.current.activity).toBe('idle');
  });
});

