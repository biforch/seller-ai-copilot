import { act, cleanup, render, renderHook, waitFor } from '@testing-library/react';
import { StrictMode } from 'react';
import { hydrateRoot, type Root } from 'react-dom/client';
import { renderToString } from 'react-dom/server';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { apiClient } from '@/app/api/client';
import { useAuth } from '@/hooks/useAuth';
import { AUTH_CHANGED_EVENT, getClientSnapshot, getServerSnapshot } from '@/lib/auth-session';
import { TOKEN_KEY, USER_KEY } from '@/lib/constants';
import type { LoginResponse, User } from '@/types';

const CANARY = 'canary-token-s3d3c2c2-DO-NOT-LEAK';
const USER: User = { id: 'user-1', email: 'seller@example.com', plan: 'free' };
const LOGIN_RESPONSE: LoginResponse = {
  access_token: CANARY,
  token_type: 'bearer',
  user: USER,
};

const navigation = vi.hoisted(() => ({
  push: vi.fn(),
}));

vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: navigation.push,
    replace: vi.fn(),
  }),
}));

function AuthProbe() {
  const { user, isLoading } = useAuth();
  return (
    <div>
      <span data-testid="loading">{String(isLoading)}</span>
      <span data-testid="email">{user?.email ?? ''}</span>
    </div>
  );
}

function assertNoCanary(...values: unknown[]) {
  for (const value of values) {
    const serialized = typeof value === 'string' ? value : JSON.stringify(value);
    expect(serialized).not.toContain(CANARY);
  }
}

describe('useAuth', () => {
  beforeEach(() => {
    localStorage.clear();
    navigation.push.mockReset();
    vi.spyOn(apiClient, 'post');
  });

  afterEach(() => {
    cleanup();
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it('exposes the public contract without a token field', () => {
    const { result } = renderHook(() => useAuth());
    expect(Object.keys(result.current).sort()).toEqual(
      ['isLoading', 'login', 'logout', 'register', 'requireAuth', 'user'].sort(),
    );
    expect(result.current).not.toHaveProperty('token');
    assertNoCanary(result.current);
  });

  it('treats empty storage as unauthenticated on the client', () => {
    const { result } = renderHook(() => useAuth());
    expect(result.current.user).toBeNull();
    expect(result.current.isLoading).toBe(false);
  });

  it('hydrates a valid stored user on the client', () => {
    localStorage.setItem(TOKEN_KEY, CANARY);
    localStorage.setItem(USER_KEY, JSON.stringify(USER));
    const { result } = renderHook(() => useAuth());
    expect(result.current.user).toEqual(USER);
    expect(result.current.isLoading).toBe(false);
    assertNoCanary(result.current);
  });

  it('stays unauthenticated for malformed stored JSON', () => {
    localStorage.setItem(TOKEN_KEY, CANARY);
    localStorage.setItem(USER_KEY, '{broken');
    const { result } = renderHook(() => useAuth());
    expect(result.current.user).toBeNull();
    expect(result.current.isLoading).toBe(false);
  });

  it('does not loop on malformed storage', async () => {
    localStorage.setItem(TOKEN_KEY, CANARY);
    localStorage.setItem(USER_KEY, '{broken');
    const { result, rerender } = renderHook(() => useAuth());
    expect(result.current.user).toBeNull();
    rerender();
    rerender();
    expect(result.current.user).toBeNull();
    expect(result.current.isLoading).toBe(false);
    assertNoCanary(result.current);
  });

  it('logs in, writes storage, notifies, and navigates without exposing the token', async () => {
    vi.mocked(apiClient.post).mockResolvedValue(LOGIN_RESPONSE);
    const { result } = renderHook(() => useAuth());
    await act(async () => {
      await result.current.login('seller@example.com', 'secret12');
    });
    expect(apiClient.post).toHaveBeenCalledWith('/auth/login', {
      email: 'seller@example.com',
      password: 'secret12',
    });
    expect(localStorage.getItem(TOKEN_KEY)).toBe(CANARY);
    expect(JSON.parse(localStorage.getItem(USER_KEY) ?? '')).toEqual(USER);
    expect(result.current.user).toEqual(USER);
    expect(navigation.push).toHaveBeenCalledWith('/dashboard');
    expect(result.current).not.toHaveProperty('token');
    assertNoCanary(result.current);
  });

  it('registers without writing storage and keeps the existing redirect', async () => {
    vi.mocked(apiClient.post).mockResolvedValue(undefined as never);
    const { result } = renderHook(() => useAuth());
    await act(async () => {
      await result.current.register('seller@example.com', 'secret12');
    });
    expect(apiClient.post).toHaveBeenCalledWith('/auth/register', {
      email: 'seller@example.com',
      password: 'secret12',
    });
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull();
    expect(navigation.push).toHaveBeenCalledWith('/login');
  });

  it('propagates login errors and does not navigate', async () => {
    vi.mocked(apiClient.post).mockRejectedValue(new Error('invalid credentials'));
    const { result } = renderHook(() => useAuth());
    await expect(
      act(async () => {
        await result.current.login('seller@example.com', 'bad');
      }),
    ).rejects.toThrow('invalid credentials');
    expect(navigation.push).not.toHaveBeenCalled();
    expect(result.current.user).toBeNull();
  });

  it('does not emit a success event when login storage writes fail', async () => {
    vi.mocked(apiClient.post).mockResolvedValue(LOGIN_RESPONSE);
    const original = localStorage.setItem.bind(localStorage);
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation((key, value) => {
      if (key === USER_KEY) {
        throw new Error('quota');
      }
      original(String(key), String(value));
    });
    const onAuth = vi.fn();
    window.addEventListener(AUTH_CHANGED_EVENT, onAuth);
    const { result } = renderHook(() => useAuth());
    await expect(
      act(async () => {
        await result.current.login('seller@example.com', 'secret12');
      }),
    ).rejects.toThrow('quota');
    expect(onAuth).not.toHaveBeenCalled();
    expect(navigation.push).not.toHaveBeenCalled();
    window.removeEventListener(AUTH_CHANGED_EVENT, onAuth);
  });

  it('logs out, clears storage, and updates every mounted hook', async () => {
    localStorage.setItem(TOKEN_KEY, CANARY);
    localStorage.setItem(USER_KEY, JSON.stringify(USER));
    const first = renderHook(() => useAuth());
    const second = renderHook(() => useAuth());
    expect(first.result.current.user).toEqual(USER);
    act(() => {
      first.result.current.logout();
    });
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull();
    expect(first.result.current.user).toBeNull();
    expect(second.result.current.user).toBeNull();
    expect(first.result.current.isLoading).toBe(false);
    expect(navigation.push).toHaveBeenCalledWith('/');
  });

  it('updates from a same-tab auth event', async () => {
    const { result } = renderHook(() => useAuth());
    localStorage.setItem(TOKEN_KEY, CANARY);
    localStorage.setItem(USER_KEY, JSON.stringify(USER));
    act(() => {
      window.dispatchEvent(new Event(AUTH_CHANGED_EVENT));
    });
    expect(result.current.user).toEqual(USER);
    assertNoCanary(result.current);
  });

  it('updates from a cross-tab token change and ignores unrelated keys', async () => {
    localStorage.setItem(TOKEN_KEY, CANARY);
    localStorage.setItem(USER_KEY, JSON.stringify(USER));
    const { result } = renderHook(() => useAuth());
    expect(result.current.user).toEqual(USER);

    act(() => {
      window.dispatchEvent(new StorageEvent('storage', { key: 'theme', newValue: 'dark' }));
    });
    expect(result.current.user).toEqual(USER);

    localStorage.removeItem(TOKEN_KEY);
    act(() => {
      window.dispatchEvent(new StorageEvent('storage', { key: TOKEN_KEY, newValue: null }));
    });
    expect(result.current.user).toBeNull();
  });

  it('updates from a cross-tab user change and from storage clear', async () => {
    localStorage.setItem(TOKEN_KEY, CANARY);
    localStorage.setItem(USER_KEY, JSON.stringify(USER));
    const { result } = renderHook(() => useAuth());

    localStorage.setItem(USER_KEY, JSON.stringify({ ...USER, email: 'other@example.com' }));
    act(() => {
      window.dispatchEvent(new StorageEvent('storage', { key: USER_KEY }));
    });
    expect(result.current.user?.email).toBe('other@example.com');

    localStorage.clear();
    act(() => {
      window.dispatchEvent(new StorageEvent('storage', { key: null }));
    });
    expect(result.current.user).toBeNull();
  });

  it('requireAuth redirects when the token is missing or storage throws', () => {
    const { result } = renderHook(() => useAuth());
    expect(result.current.requireAuth()).toBe(false);
    expect(navigation.push).toHaveBeenCalledWith('/login');

    navigation.push.mockReset();
    localStorage.setItem(TOKEN_KEY, CANARY);
    expect(result.current.requireAuth()).toBe(true);
    expect(navigation.push).not.toHaveBeenCalled();

    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new DOMException('blocked', 'SecurityError');
    });
    expect(result.current.requireAuth()).toBe(false);
    expect(navigation.push).toHaveBeenCalledWith('/login');
  });

  it('pairs subscribe and cleanup under StrictMode', () => {
    const add = vi.spyOn(window, 'addEventListener');
    const remove = vi.spyOn(window, 'removeEventListener');
    const { unmount } = render(
      <StrictMode>
        <AuthProbe />
      </StrictMode>,
    );
    const addedStorage = add.mock.calls.filter(([type]) => type === 'storage').length;
    const addedAuth = add.mock.calls.filter(([type]) => type === AUTH_CHANGED_EVENT).length;
    expect(addedStorage).toBeGreaterThan(0);
    expect(addedAuth).toBeGreaterThan(0);
    unmount();
    const removedStorage = remove.mock.calls.filter(([type]) => type === 'storage').length;
    const removedAuth = remove.mock.calls.filter(([type]) => type === AUTH_CHANGED_EVENT).length;
    expect(removedStorage).toBe(addedStorage);
    expect(removedAuth).toBe(addedAuth);
  });

  it('does not warn about uncached snapshots under StrictMode', () => {
    const errors: string[] = [];
    vi.spyOn(console, 'error').mockImplementation((...args) => {
      errors.push(args.map(String).join(' '));
    });
    render(
      <StrictMode>
        <AuthProbe />
      </StrictMode>,
    );
    expect(errors.join('\n')).not.toMatch(/should be cached/i);
    expect(errors.join('\n')).not.toContain(CANARY);
  });
});

describe('useAuth SSR and hydration', () => {
  beforeEach(() => {
    localStorage.clear();
    navigation.push.mockReset();
  });

  afterEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it('renders the server snapshot without reading localStorage or leaking the token', () => {
    localStorage.setItem(TOKEN_KEY, CANARY);
    localStorage.setItem(USER_KEY, JSON.stringify(USER));
    const getItem = vi.spyOn(Storage.prototype, 'getItem');
    const html = renderToString(<AuthProbe />);
    expect(getItem).not.toHaveBeenCalled();
    expect(html).toContain('true');
    expect(html).not.toContain(USER.email);
    expect(html).not.toContain(CANARY);
    expect(Object.is(getServerSnapshot(), getServerSnapshot())).toBe(true);
  });

  it('hydrates from the server snapshot then shows the stored user', async () => {
    localStorage.setItem(TOKEN_KEY, CANARY);
    localStorage.setItem(USER_KEY, JSON.stringify(USER));
    const html = renderToString(<AuthProbe />);
    expect(html).not.toContain(CANARY);
    expect(html).not.toContain(USER.email);

    const errors: string[] = [];
    vi.spyOn(console, 'error').mockImplementation((...args) => {
      errors.push(args.map(String).join(' '));
    });
    vi.spyOn(console, 'warn').mockImplementation((...args) => {
      errors.push(args.map(String).join(' '));
    });

    const container = document.createElement('div');
    container.innerHTML = html;
    document.body.appendChild(container);
    let root: Root | undefined;
    await act(async () => {
      root = hydrateRoot(container, <AuthProbe />);
    });
    await waitFor(() => {
      expect(container.querySelector('[data-testid="email"]')?.textContent).toBe(USER.email);
    });
    expect(container.querySelector('[data-testid="loading"]')?.textContent).toBe('false');
    expect(container.innerHTML).not.toContain(CANARY);
    expect(errors.join('\n')).not.toMatch(/hydrat/i);
    expect(errors.join('\n')).not.toContain(CANARY);
    await act(async () => {
      root?.unmount();
    });
    container.remove();
  });

  it('hydrates missing storage to a settled unauthenticated client snapshot', async () => {
    const html = renderToString(<AuthProbe />);
    const container = document.createElement('div');
    container.innerHTML = html;
    document.body.appendChild(container);
    let root: Root | undefined;
    await act(async () => {
      root = hydrateRoot(container, <AuthProbe />);
    });
    await waitFor(() => {
      expect(container.querySelector('[data-testid="loading"]')?.textContent).toBe('false');
    });
    expect(container.querySelector('[data-testid="email"]')?.textContent).toBe('');
    await act(async () => {
      root?.unmount();
    });
    container.remove();
  });
});

describe('useAuth snapshot helpers used by the hook', () => {
  it('keeps Object.is identity for repeated client reads', () => {
    localStorage.setItem(TOKEN_KEY, CANARY);
    localStorage.setItem(USER_KEY, JSON.stringify(USER));
    expect(Object.is(getClientSnapshot(), getClientSnapshot())).toBe(true);
  });
});
