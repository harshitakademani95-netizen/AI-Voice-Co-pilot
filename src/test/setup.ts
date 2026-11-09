import '@testing-library/jest-dom/vitest';
import { afterEach, vi } from 'vitest';
import { cleanup } from '@testing-library/react';

// Default mock for navigator.mediaDevices.getDisplayMedia
export const createMockMediaStream = () => {
  const mockTrack = {
    kind: 'video',
    id: 'mock-track-id',
    label: 'Screen 1',
    enabled: true,
    muted: false,
    readyState: 'live' as MediaStreamTrackState,
    stop: vi.fn(function (this: { readyState: string; onended: ((ev: Event) => void) | null }) {
      this.readyState = 'ended';
      if (typeof this.onended === 'function') {
        this.onended(new Event('ended'));
      }
    }),
    onended: null as ((ev: Event) => void) | null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(() => true),
  };

  return {
    id: 'mock-stream-id',
    active: true,
    getTracks: () => [mockTrack],
    getVideoTracks: () => [mockTrack],
    getAudioTracks: () => [],
    addTrack: vi.fn(),
    removeTrack: vi.fn(),
    clone: () => createMockMediaStream(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(() => true),
  } as unknown as MediaStream;
};

if (typeof navigator !== 'undefined') {
  if (!navigator.mediaDevices) {
    Object.defineProperty(navigator, 'mediaDevices', {
      writable: true,
      configurable: true,
      value: {
        getDisplayMedia: vi.fn(async () => createMockMediaStream()),
        getUserMedia: vi.fn(async () => createMockMediaStream()),
      },
    });
  } else {
    if (!navigator.mediaDevices.getDisplayMedia) {
      navigator.mediaDevices.getDisplayMedia = vi.fn(async () => createMockMediaStream());
    }
  }
}

// Automatically clean up React DOM after each test
afterEach(() => {
  cleanup();
});

// Mock window.HTMLElement.prototype.scrollIntoView if needed in tests
if (typeof window !== 'undefined') {
  window.HTMLElement.prototype.scrollIntoView = function () {};
}
