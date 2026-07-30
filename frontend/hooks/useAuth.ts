'use client';

import { useCallback, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';

import { apiClient } from '@/app/api/client';
import { TOKEN_KEY, USER_KEY } from '@/lib/constants';
import type { LoginResponse, User } from '@/types';

export function useAuth() {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem(TOKEN_KEY);
    const stored = localStorage.getItem(USER_KEY);
    if (token && stored) {
      setUser(JSON.parse(stored));
    }
    setIsLoading(false);
  }, []);

  const login = useCallback(
    async (email: string, password: string) => {
      const data = await apiClient.post<LoginResponse>('/auth/login', {
        email,
        password,
      });
      localStorage.setItem(TOKEN_KEY, data.access_token);
      localStorage.setItem(USER_KEY, JSON.stringify(data.user));
      setUser(data.user);
      router.push('/dashboard');
    },
    [router]
  );

  const register = useCallback(async (email: string, password: string) => {
    await apiClient.post('/auth/register', { email, password });
    router.push('/login');
  }, [router]);

  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    setUser(null);
    router.push('/');
  }, [router]);

  const requireAuth = useCallback(() => {
    const token = localStorage.getItem(TOKEN_KEY);
    if (!token) {
      router.push('/login');
      return false;
    }
    return true;
  }, [router]);

  return { user, isLoading, login, register, logout, requireAuth };
}
