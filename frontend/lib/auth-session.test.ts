import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { waitFor } from '@testing-library/react';

import { apiClient } from '@/app/api/client';
import {
  AUTH_CHANGED_EVENT,
  __resetAuthStoreForTests,
  bootstrapAuth,
  getClientSnapshot,
  getServerSnapshot,
  markAuthenticated,
  markLoggedOut,
  markSessionInvalid,
  subscribeAuth,
} from '@/lib/auth-session';
import type { User } from '@/types';

vi.mock('@/app/api/client', () => ({
  apiClient: {
    get: vi.fn(),
  },
}));

const USER: User = { id: 'user-1', email: 'seller@example.com', plan: 'free' };

describe('auth-session snapshots', () => {
  beforeEach(() => {
    __resetAuthStoreForTests();
    vi.mocked(apiClient.get).mockReset();
  });

  afterEach(() => {
    __resetAuthStoreForTests();
    vi.restoreAllMocks();
  });

  it('returns a stable server snapshot without token or user PII', () => {
    const first = getServerSnapshot();
    const second = getServerSnapshot();
    expect(Object.is(first, second)).toBe(true);
    expect(first).toEqual({ user: null, isLoading: true });
    expect(first).not.toHaveProperty('token');
    expect(JSON.stringify(first)).not.toContain(USER.email);
  });

  it('hydrates from /auth/me on first subscription', async () => {
    vi.mocked(apiClient.get).mockResolvedValue(USER);
    const onChange = vi.fn();
    subscribeAuth(onChange);
    await bootstrapAuth();
    expect(apiClient.get).toHaveBeenCalledWith('/auth/me');
    expect(getClientSnapshot()).toEqual({ user: USER, isLoading: false });
  });

  it('deduplicates concurrent bootstrap calls', async () => {
    const deferred = Promise.withResolvers<User>();
    vi.mocked(apiClient.get).mockImplementation(() => deferred.promise);
    const first = bootstrapAuth();
    const second = bootstrapAuth();
    deferred.resolve(USER);
    await Promise.all([first, second]);
    expect(apiClient.get).toHaveBeenCalledTimes(1);
  });

  it('ignores stale bootstrap success after logout invalidates the in-flight generation', async () => {
    const deferred = Promise.withResolvers<User>();
    vi.mocked(apiClient.get).mockImplementationOnce(() => deferred.promise);
    const pending = bootstrapAuth();
    markLoggedOut();
    deferred.resolve(USER);
    await pending;
    expect(getClientSnapshot()).toEqual({ user: null, isLoading: false });
  });

  it('marks authenticated and logged out without touching storage', () => {
    const storageGet = vi.spyOn(Storage.prototype, 'getItem');
    const storageSet = vi.spyOn(Storage.prototype, 'setItem');
    markAuthenticated(USER);
    expect(getClientSnapshot()).toEqual({ user: USER, isLoading: false });
    markLoggedOut();
    expect(getClientSnapshot()).toEqual({ user: null, isLoading: false });
    expect(storageGet).not.toHaveBeenCalled();
    expect(storageSet).not.toHaveBeenCalled();
  });

  it('notifies same-tab subscribers without payload events', () => {
    const onChange = vi.fn();
    subscribeAuth(onChange);
    const seen: Event[] = [];
    window.addEventListener(AUTH_CHANGED_EVENT, (event) => seen.push(event));
    markSessionInvalid();
    window.removeEventListener(AUTH_CHANGED_EVENT, () => undefined);
    expect(onChange).toHaveBeenCalled();
    expect(seen[0]).toBeInstanceOf(Event);
    expect(seen[0]).not.toBeInstanceOf(CustomEvent);
  });

  it('does not re-bootstrap after StrictMode-style resubscribe', async () => {
    vi.mocked(apiClient.get).mockResolvedValue(USER);
    const unsubscribe = subscribeAuth(() => undefined);
    await waitFor(() => {
      expect(apiClient.get).toHaveBeenCalledTimes(1);
    });
    unsubscribe();
    subscribeAuth(() => undefined);
    await Promise.resolve();
    expect(apiClient.get).toHaveBeenCalledTimes(1);
  });
});

describe('auth-session broadcast channel', () => {
  beforeEach(() => {
    __resetAuthStoreForTests();
    vi.mocked(apiClient.get).mockReset();
  });

  afterEach(() => {
    __resetAuthStoreForTests();
  });

  it('posts broadcast messages without sensitive payloads', () => {
    const posted: unknown[] = [];
    const original = BroadcastChannel.prototype.postMessage;
    vi.spyOn(BroadcastChannel.prototype, 'postMessage').mockImplementation(function (
      this: BroadcastChannel,
      data: unknown,
    ) {
      posted.push(data);
      return original.call(this, data);
    });

    markAuthenticated(USER);
    markLoggedOut();
    markSessionInvalid();

    expect(posted).toEqual([
      { type: 'authenticated' },
      { type: 'logged_out' },
      { type: 'session_invalid' },
    ]);
    expect(JSON.stringify(posted)).not.toMatch(/sellerai_session|access_token|seller@example.com/u);
  });
});
