import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import LoginPage from '@/app/(auth)/login/page';
import RegisterPage from '@/app/(auth)/register/page';
import { apiClient } from '@/app/api/client';
import { TOKEN_KEY, USER_KEY } from '@/lib/constants';
import type { LoginResponse, User } from '@/types';

const CANARY = 'canary-token-s3d3c2c2-DO-NOT-LEAK';
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
    localStorage.clear();
    navigation.push.mockReset();
    vi.spyOn(apiClient, 'post');
  });

  afterEach(() => {
    cleanup();
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it('signs in through the public login contract without rendering the token', async () => {
    vi.mocked(apiClient.post).mockResolvedValue({
      access_token: CANARY,
      token_type: 'bearer',
      user: USER,
    } satisfies LoginResponse);

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
    expect(document.body.innerHTML).not.toContain(CANARY);
    expect(localStorage.getItem(TOKEN_KEY)).toBe(CANARY);
    expect(JSON.parse(localStorage.getItem(USER_KEY) ?? '')).toEqual(USER);
  });

  it('registers through the existing API and redirect without writing tokens', async () => {
    vi.mocked(apiClient.post).mockResolvedValue(undefined as never);
    render(<RegisterPage />);
    const email = screen.getByPlaceholderText('you@example.com');
    const [password, confirm] = screen.getAllByPlaceholderText('••••••••');
    fireEvent.change(email, { target: { value: 'seller@example.com' } });
    fireEvent.change(password, { target: { value: 'secret12' } });
    fireEvent.change(confirm, { target: { value: 'secret12' } });
    fireEvent.click(screen.getByRole('button', { name: 'Create Account' }));

    await waitFor(() => {
      expect(navigation.push).toHaveBeenCalledWith('/login');
    });
    expect(apiClient.post).toHaveBeenCalledWith('/auth/register', {
      email: 'seller@example.com',
      password: 'secret12',
    });
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull();
    expect(document.body.innerHTML).not.toContain(CANARY);
  });
});
