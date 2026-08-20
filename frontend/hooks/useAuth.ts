'use client';

import { useCallback, useSyncExternalStore } from 'react';
import { useRouter } from 'next/navigation';

import { apiClient } from '@/app/api/client';
import { ApiClientError } from '@/lib/api-client-error';
import {
  getClientSnapshot,
  getServerSnapshot,
  markAuthenticated,
  markLoggedOut,
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
      markAuthenticated(data.user);
      router.push('/dashboard');
    },
    [router],
  );

  const register = useCallback(async (email: string, password: string) => {
    await apiClient.post('/auth/register', { email, password });
    router.push('/login');
  }, [router]);

  const logout = useCallback(async (): Promise<string | null> => {
    try {
      await apiClient.post('/auth/logout');
      markLoggedOut();
      router.push('/');
      return null;
    } catch (err) {
      if (err instanceof ApiClientError) {
        return err.message;
      }
      return 'Sign out failed. Please try again.';
    }
  }, [router]);

  const requireAuth = useCallback(() => {
    if (snapshot.isLoading) {
      return false;
    }
    if (!snapshot.user) {
      router.push('/login');
      return false;
    }
    return true;
  }, [router, snapshot.isLoading, snapshot.user]);

  return {
    user: snapshot.user,
    isLoading: snapshot.isLoading,
    login,
    register,
    logout,
    requireAuth,
  };
}
