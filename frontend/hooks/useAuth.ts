'use client';

import { useCallback, useSyncExternalStore } from 'react';
import { useRouter } from 'next/navigation';

import { apiClient } from '@/app/api/client';
import {
  clearAuthSession,
  getClientSnapshot,
  getServerSnapshot,
  hasAuthToken,
  persistAuthSession,
  subscribeAuth,
} from '@/lib/auth-session';
import type { LoginResponse } from '@/types';

export function useAuth() {
  const router = useRouter();
  const snapshot = useSyncExternalStore(subscribeAuth, getClientSnapshot, getServerSnapshot);

  const login = useCallback(
    async (email: string, password: string) => {
      const data = await apiClient.post<LoginResponse>('/auth/login', {
        email,
        password,
      });
      persistAuthSession(data.access_token, data.user);
      router.push('/dashboard');
    },
    [router],
  );

  const register = useCallback(async (email: string, password: string) => {
    await apiClient.post('/auth/register', { email, password });
    router.push('/login');
  }, [router]);

  const logout = useCallback(() => {
    clearAuthSession();
    router.push('/');
  }, [router]);

  const requireAuth = useCallback(() => {
    if (!hasAuthToken()) {
      router.push('/login');
      return false;
    }
    return true;
  }, [router]);

  return {
    user: snapshot.user,
    isLoading: snapshot.isLoading,
    login,
    register,
    logout,
    requireAuth,
  };
}
