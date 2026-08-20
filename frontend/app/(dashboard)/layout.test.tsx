import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import DashboardLayout from '@/app/(dashboard)/layout';
import { apiClient } from '@/app/api/client';
import { __resetAuthStoreForTests } from '@/lib/auth-session';
import type { User } from '@/types';

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

describe('dashboard auth layout', () => {
  beforeEach(() => {
    __resetAuthStoreForTests();
    navigation.push.mockReset();
    vi.spyOn(apiClient, 'get').mockRejectedValue(new Error('unauthorized'));
  });

  afterEach(() => {
    cleanup();
    __resetAuthStoreForTests();
    vi.restoreAllMocks();
  });

  it('shows loading before /auth/me completes', async () => {
    const deferred = Promise.withResolvers<User>();
    vi.mocked(apiClient.get).mockImplementation(() => deferred.promise);
    render(
      <DashboardLayout>
        <div>secret</div>
      </DashboardLayout>,
    );
    expect(screen.getByLabelText('Loading')).toBeInTheDocument();
    deferred.resolve(USER);
    await waitFor(() => {
      expect(document.body.textContent).toContain(USER.email);
    });
  });

  it('redirects unauthenticated visits to login', async () => {
    render(
      <DashboardLayout>
        <div>secret</div>
      </DashboardLayout>,
    );
    await waitFor(() => {
      expect(navigation.push).toHaveBeenCalledWith('/login');
    });
    expect(document.body.textContent).not.toContain('secret');
  });

  it('keeps an authenticated session and shows the user email', async () => {
    vi.mocked(apiClient.get).mockResolvedValue(USER);
    render(
      <DashboardLayout>
        <div>secret</div>
      </DashboardLayout>,
    );
    await waitFor(() => {
      expect(document.body.textContent).toContain(USER.email);
    });
    expect(navigation.push).not.toHaveBeenCalledWith('/login');
    expect(document.body.innerHTML).not.toMatch(/access_token|Authorization:\s*Bearer/i);
  });
});
