import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { CSRF_COOKIE_NAME } from '@/lib/constants';
import { readCsrfTokenFromCookie } from '@/lib/csrf-cookie';

describe('readCsrfTokenFromCookie', () => {
  beforeEach(() => {
    document.cookie = 'sellerai_csrf=; Max-Age=0; path=/';
    document.cookie = 'sellerai_csrf_extra=; Max-Age=0; path=/';
  });

  afterEach(() => {
    document.cookie = 'sellerai_csrf=; Max-Age=0; path=/';
    document.cookie = 'sellerai_csrf_extra=; Max-Age=0; path=/';
  });

  it('returns null when the CSRF cookie is missing', () => {
    expect(readCsrfTokenFromCookie()).toBeNull();
  });

  it('reads an exact cookie name match and decodes the value', () => {
    document.cookie = `${CSRF_COOKIE_NAME}=abc%2B123; path=/`;
    expect(readCsrfTokenFromCookie()).toBe('abc+123');
  });

  it('ignores similarly named cookies', () => {
    document.cookie = `${CSRF_COOKIE_NAME}=safe; path=/`;
    document.cookie = 'sellerai_csrf_extra=evil; path=/';
    expect(readCsrfTokenFromCookie()).toBe('safe');
  });

  it('returns null for malformed percent-encoding', () => {
    document.cookie = `${CSRF_COOKIE_NAME}=%E0%A4%A; path=/`;
    expect(readCsrfTokenFromCookie()).toBeNull();
  });

  it('returns null for empty cookie values', () => {
    document.cookie = `${CSRF_COOKIE_NAME}=; path=/`;
    expect(readCsrfTokenFromCookie()).toBeNull();
  });
});
