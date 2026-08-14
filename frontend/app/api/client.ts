import { API_BASE_URL, TOKEN_KEY } from '@/lib/constants';
import { formatApiErrorPayload } from '@/lib/api-errors';
import type { ApiError, ApiResponse } from '@/types';

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
      throw new Error(formatApiErrorPayload(err, response.status));
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

  post<T>(path: string, body?: unknown, extraHeaders?: Record<string, string>) {
    return this.request<T>(path, {
      method: 'POST',
      body: body ? JSON.stringify(body) : undefined,
      headers: extraHeaders,
    });
  }

  delete<T>(path: string) {
    return this.request<T>(path, { method: 'DELETE' });
  }
}

export const apiClient = new ApiClient(API_BASE_URL);
