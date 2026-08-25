import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import LoginPage from '@/app/(auth)/login/page';
import RegisterPage from '@/app/(auth)/register/page';
import { apiClient } from '@/app/api/client';
import { __resetAuthStoreForTests } from '@/lib/auth-session';
import type { LoginResponse, User } from '@/types';

const USER: User = { id: 'user-1', email: 'seller@example.com', plan: 'free' };

const navigation = vi.hoisted(() => ({
  push: vi.fn(),
}));

vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: navigation.push,
    replace: vi.fn(),
  }),
}));

describe('login and register pages', () => {
  beforeEach(() => {
    __resetAuthStoreForTests();
    localStorage.clear();
    navigation.push.mockReset();
    vi.spyOn(apiClient, 'get').mockRejectedValue(new Error('unauthorized'));
    vi.spyOn(apiClient, 'post');
  });

  afterEach(() => {
    cleanup();
    __resetAuthStoreForTests();
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it('signs in through the cookie login contract without persisting tokens', async () => {
    const loginResponse: LoginResponse = {
      token_type: 'cookie',
      user: USER,
    };
    vi.mocked(apiClient.post).mockResolvedValue(loginResponse);

    render(<LoginPage />);
    fireEvent.change(screen.getByPlaceholderText('you@example.com'), {
      target: { value: 'seller@example.com' },
    });
    fireEvent.change(screen.getByPlaceholderText('••••••••'), {
      target: { value: 'secret12' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Sign In' }));

    await waitFor(() => {
      expect(navigation.push).toHaveBeenCalledWith('/dashboard');
    });
    expect(apiClient.post).toHaveBeenCalledWith('/auth/login', {
      email: 'seller@example.com',
      password: 'secret12',
    });
    expect(document.body.innerHTML).not.toMatch(/access_token|Authorization:\s*Bearer/i);
    expect(localStorage.getItem('access_token')).toBeNull();
    expect(JSON.stringify(loginResponse)).not.toContain('access_token');
  });

  it('registers through the existing API and redirect without writing tokens', async () => {
    vi.mocked(apiClient.post).mockResolvedValue(undefined as never);
    render(<RegisterPage />);
    const email = screen.getByPlaceholderText('you@example.com');
    const [password, confirm] = screen.getAllByPlaceholderText('••••••••');
    fireEvent.change(email, { target: { value: 'seller@example.com' } });
    fireEvent.change(password, { target: { value: 'Secret12!abc' } });
    fireEvent.change(confirm, { target: { value: 'Secret12!abc' } });
    fireEvent.click(screen.getByRole('button', { name: 'Create Account' }));

    await waitFor(() => {
      expect(navigation.push).toHaveBeenCalledWith('/login');
    });
    expect(apiClient.post).toHaveBeenCalledWith('/auth/register', {
      email: 'seller@example.com',
      password: 'Secret12!abc',
    });
    expect(localStorage.getItem('access_token')).toBeNull();
    expect(document.body.innerHTML).not.toMatch(/access_token|Authorization:\s*Bearer/i);
  });
});
