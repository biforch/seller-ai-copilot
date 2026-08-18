import { describe, expect, it } from 'vitest';

import { isAbortError } from '@/lib/abort-error';

describe('isAbortError', () => {
  it('detects DOMException AbortError', () => {
    const error = new DOMException('The operation was aborted.', 'AbortError');
    expect(isAbortError(error)).toBe(true);
  });

  it('detects Error AbortError', () => {
    const error = new Error('Aborted');
    error.name = 'AbortError';
    expect(isAbortError(error)).toBe(true);
  });

  it('returns false for other errors', () => {
    expect(isAbortError(new Error('Network failed'))).toBe(false);
    expect(isAbortError(new TypeError('Cannot read property'))).toBe(false);
    expect(isAbortError('AbortError')).toBe(false);
    expect(isAbortError(null)).toBe(false);
    expect(isAbortError(undefined)).toBe(false);
  });
});
