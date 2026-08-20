import {
  API_BASE_URL,
  CSRF_EXEMPT_API_PATHS,
  CSRF_HEADER_NAME,
} from '@/lib/constants';
import { notifySessionInvalid } from '@/lib/auth-invalidation';
import { readCsrfTokenFromCookie } from '@/lib/csrf-cookie';
import { ApiClientError } from '@/lib/api-client-error';
import { AUTH_SESSION_INVALID, formatApiErrorPayload } from '@/lib/api-errors';
import type { ApiError, ApiResponse } from '@/types';

type RequestOptions = {
  headers?: Record<string, string>;
  signal?: AbortSignal;
};

const UNSAFE_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

export class CsrfTokenMissingError extends Error {
  constructor() {
    super('Request rejected.');
    this.name = 'CsrfTokenMissingError';
  }
}

class ApiClient {
  private baseUrl: string;

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl;
  }

  private buildPath(path: string, params?: Record<string, string | number | undefined>) {
    if (!params) return path;
    const search = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined) {
        search.set(key, String(value));
      }
    });
    const query = search.toString();
    return query ? `${path}?${query}` : path;
  }

  private resolveCsrfHeader(method: string, path: string): Record<string, string> {
    const normalizedMethod = method.toUpperCase();
    if (!UNSAFE_METHODS.has(normalizedMethod)) {
      return {};
    }
    if (CSRF_EXEMPT_API_PATHS.some((exemptPath) => path === exemptPath || path.startsWith(`${exemptPath}?`))) {
      return {};
    }
    const csrfToken = readCsrfTokenFromCookie();
    if (!csrfToken) {
      throw new CsrfTokenMissingError();
    }
    return { [CSRF_HEADER_NAME]: csrfToken };
  }

  private async request<T>(
    path: string,
    options: RequestInit = {},
  ): Promise<T> {
    const method = (options.method ?? 'GET').toUpperCase();
    const csrfHeaders = this.resolveCsrfHeader(method, path);
    const headers: HeadersInit = {
      'Content-Type': 'application/json',
      ...(options.headers || {}),
      ...csrfHeaders,
    };

    const response = await fetch(`${this.baseUrl}${path}`, {
      ...options,
      method,
      credentials: 'include',
      headers,
    });

    const json = await response.json();

    if (!response.ok) {
      const err = json as ApiError;
      if (response.status === 401 && err.error_code === AUTH_SESSION_INVALID) {
        notifySessionInvalid();
      }
      throw new ApiClientError(
        formatApiErrorPayload(err, response.status),
        response.status,
        err.error_code,
        err.detail,
      );
    }

    const wrapped = json as ApiResponse<T>;
    if (wrapped && typeof wrapped === 'object' && 'code' in wrapped && 'data' in wrapped) {
      return wrapped.data;
    }
    return json as T;
  }

  get<T>(
    path: string,
    options?: {
      params?: Record<string, string | number | undefined>;
      signal?: AbortSignal;
    },
  ) {
    return this.request<T>(this.buildPath(path, options?.params), {
      signal: options?.signal,
    });
  }

  post<T>(
    path: string,
    body?: unknown,
    options?: RequestOptions | Record<string, string>,
    legacySignal?: AbortSignal,
  ) {
    const resolved = normalizeRequestOptions(options, legacySignal);
    return this.request<T>(path, {
      method: 'POST',
      body: body ? JSON.stringify(body) : undefined,
      headers: resolved.headers,
      signal: resolved.signal,
    });
  }

  put<T>(path: string, body?: unknown, options?: RequestOptions) {
    return this.request<T>(path, {
      method: 'PUT',
      body: body ? JSON.stringify(body) : undefined,
      headers: options?.headers,
      signal: options?.signal,
    });
  }

  patch<T>(path: string, body?: unknown, options?: RequestOptions) {
    return this.request<T>(path, {
      method: 'PATCH',
      body: body ? JSON.stringify(body) : undefined,
      headers: options?.headers,
      signal: options?.signal,
    });
  }

  delete<T>(path: string, options?: RequestOptions) {
    return this.request<T>(path, {
      method: 'DELETE',
      signal: options?.signal,
      headers: options?.headers,
    });
  }
}

function normalizeRequestOptions(
  options?: RequestOptions | Record<string, string>,
  legacySignal?: AbortSignal,
): RequestOptions {
  if (!options) {
    return { signal: legacySignal };
  }
  if ('signal' in options || 'headers' in options) {
    return options as RequestOptions;
  }
  return {
    headers: options as Record<string, string>,
    signal: legacySignal,
  };
}

export const apiClient = new ApiClient(API_BASE_URL);
