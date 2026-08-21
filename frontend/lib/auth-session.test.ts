import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { waitFor } from '@testing-library/react';

import { apiClient } from '@/app/api/client';
import {
  AUTH_BROADCAST_CHANNEL,
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
  const senders: BroadcastChannel[] = [];

  function independentSender(): BroadcastChannel {
    const sender = new BroadcastChannel(AUTH_BROADCAST_CHANNEL);
    senders.push(sender);
    return sender;
  }

  beforeEach(() => {
    __resetAuthStoreForTests();
    vi.mocked(apiClient.get).mockReset();
  });

  afterEach(() => {
    for (const sender of senders) {
      sender.close();
    }
    senders.length = 0;
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

  it('receiver-only subscribe accepts logged_out from an independent sender channel', async () => {
    vi.mocked(apiClient.get).mockResolvedValue(USER);
    const onChange = vi.fn();
    subscribeAuth(onChange);
    await waitFor(() => {
      expect(getClientSnapshot()).toEqual({ user: USER, isLoading: false });
    });

    independentSender().postMessage({ type: 'logged_out' });

    await waitFor(() => {
      expect(getClientSnapshot()).toEqual({ user: null, isLoading: false });
    });
    expect(JSON.stringify(getClientSnapshot())).not.toMatch(/access_token|sellerai_session|sellerai_csrf/u);
  });

  it('authenticated broadcast from an independent sender triggers one bootstrap', async () => {
    vi.mocked(apiClient.get).mockResolvedValue(USER);
    subscribeAuth(() => undefined);
    await waitFor(() => {
      expect(apiClient.get).toHaveBeenCalledTimes(1);
    });
    vi.mocked(apiClient.get).mockClear();

    independentSender().postMessage({ type: 'authenticated' });

    await waitFor(() => {
      expect(apiClient.get).toHaveBeenCalledTimes(1);
    });
    expect(apiClient.get).toHaveBeenCalledWith('/auth/me');
  });

  it('session_invalid broadcast from an independent sender clears state', async () => {
    vi.mocked(apiClient.get).mockResolvedValue(USER);
    subscribeAuth(() => undefined);
    await waitFor(() => {
      expect(getClientSnapshot().user).toEqual(USER);
    });

    independentSender().postMessage({ type: 'session_invalid' });

    await waitFor(() => {
      expect(getClientSnapshot()).toEqual({ user: null, isLoading: false });
    });
  });

  it('still receives after StrictMode-style unsubscribe and resubscribe', async () => {
    vi.mocked(apiClient.get).mockResolvedValue(USER);
    const first = subscribeAuth(() => undefined);
    await waitFor(() => {
      expect(getClientSnapshot().user).toEqual(USER);
    });
    first();
    subscribeAuth(() => undefined);

    independentSender().postMessage({ type: 'logged_out' });

    await waitFor(() => {
      expect(getClientSnapshot()).toEqual({ user: null, isLoading: false });
    });
  });

  it('does not recreate the channel when additional subscribers attach', () => {
    const Original = globalThis.BroadcastChannel;
    let created = 0;
    const TrackingBroadcastChannel = class extends Original {
      constructor(name: string) {
        super(name);
        created += 1;
      }
    };
    Object.defineProperty(window, 'BroadcastChannel', {
      configurable: true,
      writable: true,
      value: TrackingBroadcastChannel,
    });
    Object.defineProperty(globalThis, 'BroadcastChannel', {
      configurable: true,
      writable: true,
      value: TrackingBroadcastChannel,
    });

    try {
      subscribeAuth(() => undefined);
      subscribeAuth(() => undefined);
      subscribeAuth(() => undefined);
      expect(created).toBe(1);
    } finally {
      Object.defineProperty(window, 'BroadcastChannel', {
        configurable: true,
        writable: true,
        value: Original,
      });
      Object.defineProperty(globalThis, 'BroadcastChannel', {
        configurable: true,
        writable: true,
        value: Original,
      });
    }
  });

  it('ignores messages on a closed channel after test reset', async () => {
    vi.mocked(apiClient.get).mockResolvedValue(USER);
    subscribeAuth(() => undefined);
    await waitFor(() => {
      expect(getClientSnapshot().user).toEqual(USER);
    });

    const staleSender = independentSender();
    __resetAuthStoreForTests();
    expect(getClientSnapshot()).toEqual({ user: null, isLoading: true });

    staleSender.postMessage({ type: 'logged_out' });
    staleSender.postMessage({ type: 'authenticated' });
    staleSender.postMessage({ type: 'session_invalid' });
    await Promise.resolve();
    await Promise.resolve();

    expect(getClientSnapshot()).toEqual({ user: null, isLoading: true });
    expect(apiClient.get).toHaveBeenCalledTimes(1);
  });

  it('degrades when BroadcastChannel is unavailable', () => {
    const Original = globalThis.BroadcastChannel;
    __resetAuthStoreForTests();
    Object.defineProperty(window, 'BroadcastChannel', {
      configurable: true,
      writable: true,
      value: undefined,
    });
    Object.defineProperty(globalThis, 'BroadcastChannel', {
      configurable: true,
      writable: true,
      value: undefined,
    });

    try {
      expect(() => subscribeAuth(() => undefined)).not.toThrow();
      expect(() => markLoggedOut()).not.toThrow();
      expect(getClientSnapshot()).toEqual({ user: null, isLoading: false });
    } finally {
      Object.defineProperty(window, 'BroadcastChannel', {
        configurable: true,
        writable: true,
        value: Original,
      });
      Object.defineProperty(globalThis, 'BroadcastChannel', {
        configurable: true,
        writable: true,
        value: Original,
      });
    }
  });
});
