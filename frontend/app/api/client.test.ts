import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { apiClient, CsrfTokenMissingError } from '@/app/api/client';
import { notifySessionInvalid } from '@/lib/auth-invalidation';
import { AUTH_SESSION_INVALID } from '@/lib/api-errors';
import { CSRF_COOKIE_NAME, CSRF_HEADER_NAME } from '@/lib/constants';

vi.mock('@/lib/auth-invalidation', () => ({
  notifySessionInvalid: vi.fn(),
}));

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function mockFetchSuccess() {
  vi.mocked(fetch).mockImplementation(() => Promise.resolve(jsonResponse({ code: 200, data: {} })));
}

describe('apiClient cookie session contract', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn());
    document.cookie = 'sellerai_csrf=; Max-Age=0; path=/';
    vi.mocked(notifySessionInvalid).mockReset();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    document.cookie = '';
  });

  it('sends credentials include on GET requests', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ code: 200, data: { ok: true } }));
    await apiClient.get('/auth/me');
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining('/auth/me'),
      expect.objectContaining({ credentials: 'include', method: 'GET' }),
    );
    const [, init] = vi.mocked(fetch).mock.calls[0];
    expect((init?.headers as Record<string, string>)?.[CSRF_HEADER_NAME]).toBeUndefined();
  });

  it('does not attach CSRF headers to GET requests', async () => {
    document.cookie = `${CSRF_COOKIE_NAME}=csrf-token; path=/`;
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ code: 200, data: {} }));

    await apiClient.get('/projects');
    const [, init] = vi.mocked(fetch).mock.calls.at(-1)!;
    expect((init?.headers as Record<string, string>)?.[CSRF_HEADER_NAME]).toBeUndefined();
  });

  it('attaches CSRF headers to POST, PUT, PATCH, and DELETE', async () => {
    document.cookie = `${CSRF_COOKIE_NAME}=csrf-token; path=/`;
    mockFetchSuccess();

    await apiClient.post('/projects', { name: 'Demo' });
    let [, init] = vi.mocked(fetch).mock.calls.at(-1)!;
    expect((init?.headers as Record<string, string>)?.[CSRF_HEADER_NAME]).toBe('csrf-token');

    await apiClient.put('/projects/1', { name: 'Updated' });
    [, init] = vi.mocked(fetch).mock.calls.at(-1)!;
    expect((init?.headers as Record<string, string>)?.[CSRF_HEADER_NAME]).toBe('csrf-token');

    await apiClient.patch('/projects/1', { name: 'Patched' });
    [, init] = vi.mocked(fetch).mock.calls.at(-1)!;
    expect((init?.headers as Record<string, string>)?.[CSRF_HEADER_NAME]).toBe('csrf-token');

    await apiClient.delete('/projects/1');
    [, init] = vi.mocked(fetch).mock.calls.at(-1)!;
    expect((init?.headers as Record<string, string>)?.[CSRF_HEADER_NAME]).toBe('csrf-token');
  });

  it('attaches CSRF to Amazon OAuth start mutations', async () => {
    document.cookie = `${CSRF_COOKIE_NAME}=csrf-token; path=/`;
    mockFetchSuccess();
    await apiClient.post('/amazon/oauth/start', { region: 'na' });
    const [, init] = vi.mocked(fetch).mock.calls.at(-1)!;
    expect((init?.headers as Record<string, string>)?.[CSRF_HEADER_NAME]).toBe('csrf-token');
  });

  it('exempts login and register from CSRF requirements', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ code: 200, data: {} }));
    await apiClient.post('/auth/login', { email: 'a@b.com', password: 'secret12' });
    const [, init] = vi.mocked(fetch).mock.calls[0];
    expect((init?.headers as Record<string, string>)?.[CSRF_HEADER_NAME]).toBeUndefined();
  });

  it('fails closed when CSRF cookie is missing for unsafe methods', async () => {
    document.cookie = `${CSRF_COOKIE_NAME}=; Max-Age=0; path=/`;
    await expect(apiClient.post('/auth/logout')).rejects.toBeInstanceOf(CsrfTokenMissingError);
    expect(fetch).not.toHaveBeenCalled();
  });

  it('fails closed when CSRF cookie is malformed', async () => {
    document.cookie = `${CSRF_COOKIE_NAME}=%E0%A4%A; path=/`;
    await expect(apiClient.post('/auth/logout')).rejects.toBeInstanceOf(CsrfTokenMissingError);
    expect(fetch).not.toHaveBeenCalled();
  });

  it('notifies session invalid only for AUTH_SESSION_INVALID 401 responses', async () => {
    document.cookie = `${CSRF_COOKIE_NAME}=csrf-token; path=/`;
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse(
        {
          code: 401,
          error_code: AUTH_SESSION_INVALID,
          message: 'Session expired',
          detail: null,
        },
        401,
      ),
    );

    await expect(apiClient.get('/auth/me')).rejects.toThrow('Session expired');
    expect(notifySessionInvalid).toHaveBeenCalledTimes(1);

    vi.mocked(fetch).mockResolvedValue(
      jsonResponse({ code: 403, error_code: 'QUOTA_EXCEEDED', message: 'Quota exceeded', detail: null }, 403),
    );
    await expect(apiClient.get('/generate/history')).rejects.toThrow('Quota exceeded');
    expect(notifySessionInvalid).toHaveBeenCalledTimes(1);

    vi.mocked(fetch).mockResolvedValue(
      jsonResponse({ code: 404, message: 'Not found', detail: null }, 404),
    );
    await expect(apiClient.get('/projects/missing')).rejects.toThrow();
    expect(notifySessionInvalid).toHaveBeenCalledTimes(1);
  });
});
