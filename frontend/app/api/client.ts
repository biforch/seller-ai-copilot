import { API_BASE_URL, TOKEN_KEY } from '@/lib/constants';
import { ApiClientError } from '@/lib/api-client-error';
import { formatApiErrorPayload } from '@/lib/api-errors';
import type { ApiError, ApiResponse } from '@/types';

type RequestOptions = {
  headers?: Record<string, string>;
  signal?: AbortSignal;
};

class ApiClient {
  private baseUrl: string;

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl;
  }

  private getToken(): string | null {
    if (typeof window === 'undefined') return null;
    return localStorage.getItem(TOKEN_KEY);
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

  private async request<T>(
    path: string,
    options: RequestInit = {}
  ): Promise<T> {
    const token = this.getToken();
    const headers: HeadersInit = {
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    };
    if (token) {
      (headers as Record<string, string>)['Authorization'] = `Bearer ${token}`;
    }

    const response = await fetch(`${this.baseUrl}${path}`, {
      ...options,
      headers,
    });

    const json = await response.json();

    if (!response.ok) {
      const err = json as ApiError;
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
    }
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
