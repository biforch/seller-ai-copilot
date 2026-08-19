import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { TOKEN_KEY, USER_KEY } from '@/lib/constants';
import {
  AUTH_CHANGED_EVENT,
  clearAuthSession,
  getClientSnapshot,
  getServerSnapshot,
  hasAuthToken,
  persistAuthSession,
  subscribeAuth,
} from '@/lib/auth-session';
import type { User } from '@/types';

const CANARY = 'canary-token-s3d3c2c2-DO-NOT-LEAK';
const USER: User = { id: 'user-1', email: 'seller@example.com', plan: 'free' };

function assertNoCanary(value: unknown) {
  const serialized = typeof value === 'string' ? value : JSON.stringify(value);
  expect(serialized).not.toContain(CANARY);
}

describe('auth-session snapshots', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it('returns a stable server snapshot without reading storage', () => {
    const getItem = vi.spyOn(Storage.prototype, 'getItem');
    const first = getServerSnapshot();
    const second = getServerSnapshot();
    expect(Object.is(first, second)).toBe(true);
    expect(first).toEqual({ user: null, isLoading: true });
    expect(first).not.toHaveProperty('token');
    expect(getItem).not.toHaveBeenCalled();
    assertNoCanary(first);
  });

  it('caches identical client snapshots by raw storage strings', () => {
    localStorage.setItem(TOKEN_KEY, CANARY);
    localStorage.setItem(USER_KEY, JSON.stringify(USER));
    const first = getClientSnapshot();
    const second = getClientSnapshot();
    expect(Object.is(first, second)).toBe(true);
    expect(first.user).toEqual(USER);
    expect(first.isLoading).toBe(false);
    expect(first).not.toHaveProperty('token');
    assertNoCanary(first);
  });

  it('returns a new snapshot reference after storage contents change', () => {
    localStorage.setItem(TOKEN_KEY, CANARY);
    localStorage.setItem(USER_KEY, JSON.stringify(USER));
    const before = getClientSnapshot();
    localStorage.setItem(USER_KEY, JSON.stringify({ ...USER, email: 'other@example.com' }));
    const after = getClientSnapshot();
    expect(Object.is(before, after)).toBe(false);
    expect(after.user?.email).toBe('other@example.com');
    assertNoCanary(after);
  });

  it('treats missing token or missing user as unauthenticated', () => {
    localStorage.setItem(TOKEN_KEY, CANARY);
    expect(getClientSnapshot()).toEqual({ user: null, isLoading: false });
    localStorage.clear();
    localStorage.setItem(USER_KEY, JSON.stringify(USER));
    expect(getClientSnapshot()).toEqual({ user: null, isLoading: false });
  });

  it('caches malformed user JSON as a stable unauthenticated snapshot', () => {
    localStorage.setItem(TOKEN_KEY, CANARY);
    localStorage.setItem(USER_KEY, '{not-json');
    const first = getClientSnapshot();
    const second = getClientSnapshot();
    expect(Object.is(first, second)).toBe(true);
    expect(first).toEqual({ user: null, isLoading: false });
    assertNoCanary(first);
  });

  it('fails closed when localStorage getItem throws', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new DOMException('blocked', 'SecurityError');
    });
    const first = getClientSnapshot();
    const second = getClientSnapshot();
    expect(Object.is(first, second)).toBe(true);
    expect(first).toEqual({ user: null, isLoading: false });
    assertNoCanary(first);
  });
});

describe('auth-session subscribe and persist', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it('notifies on token/user storage events and clear, but ignores unrelated keys', () => {
    const onChange = vi.fn();
    const unsubscribe = subscribeAuth(onChange);
    window.dispatchEvent(new StorageEvent('storage', { key: 'theme', newValue: 'dark' }));
    expect(onChange).not.toHaveBeenCalled();
    window.dispatchEvent(new StorageEvent('storage', { key: TOKEN_KEY, newValue: CANARY }));
    window.dispatchEvent(new StorageEvent('storage', { key: USER_KEY, newValue: '{}' }));
    window.dispatchEvent(new StorageEvent('storage', { key: null }));
    expect(onChange).toHaveBeenCalledTimes(3);
    unsubscribe();
  });

  it('removes both listeners on cleanup', () => {
    const add = vi.spyOn(window, 'addEventListener');
    const remove = vi.spyOn(window, 'removeEventListener');
    const unsubscribe = subscribeAuth(() => undefined);
    expect(add).toHaveBeenCalledWith('storage', expect.any(Function));
    expect(add).toHaveBeenCalledWith(AUTH_CHANGED_EVENT, expect.any(Function));
    unsubscribe();
    expect(remove).toHaveBeenCalledWith('storage', expect.any(Function));
    expect(remove).toHaveBeenCalledWith(AUTH_CHANGED_EVENT, expect.any(Function));
  });

  it('dispatches a same-tab event with no token payload after a full persist', () => {
    const seen: Event[] = [];
    const onAuth = (event: Event) => {
      seen.push(event);
    };
    window.addEventListener(AUTH_CHANGED_EVENT, onAuth);
    persistAuthSession(CANARY, USER);
    window.removeEventListener(AUTH_CHANGED_EVENT, onAuth);
    expect(seen).toHaveLength(1);
    expect(seen[0]).toBeInstanceOf(Event);
    expect(seen[0]).not.toBeInstanceOf(CustomEvent);
    assertNoCanary(seen[0]);
    expect(localStorage.getItem(TOKEN_KEY)).toBe(CANARY);
    expect(JSON.parse(localStorage.getItem(USER_KEY) ?? '')).toEqual(USER);
  });

  it('does not notify when user storage write fails after token write', () => {
    const original = localStorage.setItem.bind(localStorage);
    const onAuth = vi.fn();
    window.addEventListener(AUTH_CHANGED_EVENT, onAuth);
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation((key, value) => {
      if (key === USER_KEY) {
        throw new Error('quota');
      }
      original(String(key), String(value));
    });
    expect(() => persistAuthSession(CANARY, USER)).toThrow('quota');
    expect(onAuth).not.toHaveBeenCalled();
    window.removeEventListener(AUTH_CHANGED_EVENT, onAuth);
  });

  it('clears storage and notifies subscribers on logout', () => {
    localStorage.setItem(TOKEN_KEY, CANARY);
    localStorage.setItem(USER_KEY, JSON.stringify(USER));
    const onAuth = vi.fn();
    window.addEventListener(AUTH_CHANGED_EVENT, onAuth);
    clearAuthSession();
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull();
    expect(localStorage.getItem(USER_KEY)).toBeNull();
    expect(onAuth).toHaveBeenCalledTimes(1);
    window.removeEventListener(AUTH_CHANGED_EVENT, onAuth);
  });

  it('requireAuth token helper fails closed on storage exceptions', () => {
    localStorage.setItem(TOKEN_KEY, CANARY);
    expect(hasAuthToken()).toBe(true);
    localStorage.removeItem(TOKEN_KEY);
    expect(hasAuthToken()).toBe(false);
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new DOMException('blocked', 'SecurityError');
    });
    expect(hasAuthToken()).toBe(false);
  });
});
