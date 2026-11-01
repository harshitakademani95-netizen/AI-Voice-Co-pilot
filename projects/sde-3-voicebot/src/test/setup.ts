import '@testing-library/jest-dom/vitest';
import { afterEach } from 'vitest';
import { cleanup } from '@testing-library/react';

// Automatically clean up React DOM after each test
afterEach(() => {
  cleanup();
});

// Mock window.HTMLElement.prototype.scrollIntoView if needed in tests
if (typeof window !== 'undefined') {
  window.HTMLElement.prototype.scrollIntoView = function () {};
}
