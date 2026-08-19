import { cleanup, render, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import DashboardLayout from '@/app/(dashboard)/layout';
import { TOKEN_KEY, USER_KEY } from '@/lib/constants';
import type { User } from '@/types';

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

describe('dashboard auth layout', () => {
  beforeEach(() => {
    localStorage.clear();
    navigation.push.mockReset();
  });

  afterEach(() => {
    cleanup();
    localStorage.clear();
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
    expect(document.body.innerHTML).not.toContain(CANARY);
  });

  it('keeps an authenticated session and shows the stored email', async () => {
    localStorage.setItem(TOKEN_KEY, CANARY);
    localStorage.setItem(USER_KEY, JSON.stringify(USER));
    render(
      <DashboardLayout>
        <div>secret</div>
      </DashboardLayout>,
    );
    await waitFor(() => {
      expect(document.body.textContent).toContain(USER.email);
    });
    expect(navigation.push).not.toHaveBeenCalledWith('/login');
    expect(document.body.innerHTML).not.toContain(CANARY);
  });
});
