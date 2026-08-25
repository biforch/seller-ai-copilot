import { act, cleanup, render, renderHook, waitFor } from '@testing-library/react';
import { StrictMode } from 'react';
import { hydrateRoot, type Root } from 'react-dom/client';
import { renderToString } from 'react-dom/server';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { apiClient } from '@/app/api/client';
import { ApiClientError } from '@/lib/api-client-error';
import { useAuth } from '@/hooks/useAuth';
import {
  AUTH_CHANGED_EVENT,
  __resetAuthStoreForTests,
  bootstrapAuth,
  getClientSnapshot,
  getServerSnapshot,
  markAuthenticated,
  markLoggedOut,
  subscribeAuth,
} from '@/lib/auth-session';
import type { LoginResponse, User } from '@/types';

const USER: User = { id: 'user-1', email: 'seller@example.com', plan: 'free' };
const LOGIN_RESPONSE: LoginResponse = {
  token_type: 'cookie',
  user: USER,
  mfa_required: false,
  mfa_enrollment_required: false,
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

function assertNoTokenArtifacts(...values: unknown[]) {
  for (const value of values) {
    const serialized = typeof value === 'string' ? value : JSON.stringify(value);
    expect(serialized).not.toMatch(/access_token/i);
    expect(serialized).not.toMatch(/Authorization:\s*Bearer/i);
  }
}

describe('useAuth', () => {
  beforeEach(() => {
    __resetAuthStoreForTests();
    localStorage.clear();
    sessionStorage.clear();
    navigation.push.mockReset();
    vi.spyOn(apiClient, 'get').mockResolvedValue(USER);
    vi.spyOn(apiClient, 'post');
  });

  afterEach(() => {
    cleanup();
    __resetAuthStoreForTests();
    localStorage.clear();
    sessionStorage.clear();
    vi.restoreAllMocks();
  });

  it('exposes the public contract without a token field', () => {
    const { result } = renderHook(() => useAuth());
    expect(Object.keys(result.current).sort()).toEqual(
      ['isLoading', 'login', 'logout', 'register', 'requireAuth', 'user'].sort(),
    );
    expect(result.current).not.toHaveProperty('token');
    assertNoTokenArtifacts(result.current);
  });

  it('bootstraps from /auth/me instead of localStorage', async () => {
    localStorage.setItem('access_token', 'legacy-token');
    const { result } = renderHook(() => useAuth());
    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });
    expect(apiClient.get).toHaveBeenCalledWith('/auth/me');
    expect(result.current.user).toEqual(USER);
    assertNoTokenArtifacts(localStorage.getItem('access_token'));
  });

  it('logs in without access_token and navigates to dashboard', async () => {
    vi.mocked(apiClient.post).mockResolvedValue(LOGIN_RESPONSE);
    const { result } = renderHook(() => useAuth());
    await act(async () => {
      await result.current.login('seller@example.com', 'secret12');
    });
    expect(apiClient.post).toHaveBeenCalledWith('/auth/login', {
      email: 'seller@example.com',
      password: 'secret12',
    });
    expect(result.current.user).toEqual(USER);
    expect(localStorage.getItem('access_token')).toBeNull();
    expect(navigation.push).toHaveBeenCalledWith('/dashboard');
    assertNoTokenArtifacts(result.current);
  });

  it('returns an MFA challenge without authenticating or navigating', async () => {
    vi.mocked(apiClient.get).mockRejectedValue(new Error('pending MFA'));
    vi.mocked(apiClient.post).mockResolvedValue({
      token_type: 'cookie',
      user: null,
      mfa_required: true,
      mfa_enrollment_required: false,
    });
    const { result } = renderHook(() => useAuth());
    let response;
    await act(async () => {
      response = await result.current.login('seller@example.com', 'Secret12!abc');
    });
    expect(response).toMatchObject({ mfa_required: true, user: null });
    expect(result.current.user).toBeNull();
    expect(navigation.push).not.toHaveBeenCalledWith('/dashboard');
  });

  it('does not clear other tabs when login fails', async () => {
    markAuthenticated(USER);
    vi.mocked(apiClient.post).mockRejectedValue(new Error('invalid credentials'));
    const { result } = renderHook(() => useAuth());
    await expect(
      act(async () => {
        await result.current.login('seller@example.com', 'bad');
      }),
    ).rejects.toThrow('invalid credentials');
    expect(result.current.user).toEqual(USER);
    expect(navigation.push).not.toHaveBeenCalled();
  });

  it('logs out through /auth/logout and syncs hook instances', async () => {
    markAuthenticated(USER);
    vi.mocked(apiClient.post).mockResolvedValue(undefined as never);
    document.cookie = 'sellerai_csrf=csrf-token; path=/';
    const first = renderHook(() => useAuth());
    const second = renderHook(() => useAuth());
    await waitFor(() => {
      expect(first.result.current.user).toEqual(USER);
    });
    await act(async () => {
      await first.result.current.logout();
    });
    expect(apiClient.post).toHaveBeenCalledWith('/auth/logout');
    expect(first.result.current.user).toBeNull();
    expect(second.result.current.user).toBeNull();
    expect(navigation.push).toHaveBeenCalledWith('/');
  });

  it('returns a sanitized logout error without clearing a valid session', async () => {
    markAuthenticated(USER);
    vi.mocked(apiClient.post).mockRejectedValue(new ApiClientError('network down', 503));
    document.cookie = 'sellerai_csrf=csrf-token; path=/';
    const { result } = renderHook(() => useAuth());
    await waitFor(() => {
      expect(result.current.user).toEqual(USER);
    });
    let error: string | null = null;
    await act(async () => {
      error = await result.current.logout();
    });
    expect(error).toBe('network down');
    expect(result.current.user).toEqual(USER);
    expect(navigation.push).not.toHaveBeenCalled();
  });

  it('requireAuth waits for bootstrap and redirects when unauthenticated', async () => {
    vi.mocked(apiClient.get).mockRejectedValue(new Error('unauthorized'));
    const { result } = renderHook(() => useAuth());
    expect(result.current.requireAuth()).toBe(false);
    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });
    expect(result.current.requireAuth()).toBe(false);
    expect(navigation.push).toHaveBeenCalledWith('/login');
  });

  it('updates from same-tab auth events', async () => {
    const { result } = renderHook(() => useAuth());
    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });
    markAuthenticated(USER);
    act(() => {
      window.dispatchEvent(new Event(AUTH_CHANGED_EVENT));
    });
    expect(result.current.user).toEqual(USER);

    markLoggedOut();
    act(() => {
      window.dispatchEvent(new Event(AUTH_CHANGED_EVENT));
    });
    expect(result.current.user).toBeNull();
  });

  it('clears hook state when an independent BroadcastChannel posts logged_out', async () => {
    const { result } = renderHook(() => useAuth());
    await waitFor(() => {
      expect(result.current.user).toEqual(USER);
    });

    const sender = new BroadcastChannel('sellerai-auth');
    try {
      act(() => {
        sender.postMessage({ type: 'logged_out' });
      });
      await waitFor(() => {
        expect(result.current.user).toBeNull();
      });
    } finally {
      sender.close();
    }
  });

  it('does not duplicate bootstrap under StrictMode', async () => {
    render(
      <StrictMode>
        <AuthProbe />
      </StrictMode>,
    );
    await waitFor(() => {
      expect(apiClient.get).toHaveBeenCalledTimes(1);
    });
  });
});

describe('useAuth SSR and hydration', () => {
  beforeEach(() => {
    __resetAuthStoreForTests();
    navigation.push.mockReset();
    vi.spyOn(apiClient, 'get').mockResolvedValue(USER);
  });

  afterEach(() => {
    __resetAuthStoreForTests();
    vi.restoreAllMocks();
  });

  it('renders the server snapshot without token, cookie, or user PII', () => {
    localStorage.setItem('access_token', 'legacy-token');
    const getItem = vi.spyOn(Storage.prototype, 'getItem');
    const html = renderToString(<AuthProbe />);
    expect(getItem).not.toHaveBeenCalled();
    expect(html).toContain('true');
    expect(html).not.toContain(USER.email);
    expect(html).not.toMatch(/access_token|sellerai_session|sellerai_csrf/i);
    expect(Object.is(getServerSnapshot(), getServerSnapshot())).toBe(true);
  });

  it('hydrates from the server snapshot then settles from /auth/me', async () => {
    const html = renderToString(<AuthProbe />);
    expect(html).not.toContain(USER.email);

    const errors: string[] = [];
    vi.spyOn(console, 'error').mockImplementation((...args) => {
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
    expect(errors.join('\n')).not.toMatch(/hydrat/i);
    await act(async () => {
      root?.unmount();
    });
    container.remove();
  });
});

describe('useAuth snapshot helpers used by the hook', () => {
  beforeEach(() => {
    __resetAuthStoreForTests();
  });

  it('keeps Object.is identity for repeated client reads', async () => {
    vi.spyOn(apiClient, 'get').mockResolvedValue(USER);
    subscribeAuth(() => undefined);
    await bootstrapAuth();
    await waitFor(() => {
      expect(getClientSnapshot().isLoading).toBe(false);
    });
    expect(Object.is(getClientSnapshot(), getClientSnapshot())).toBe(true);
  });
});
