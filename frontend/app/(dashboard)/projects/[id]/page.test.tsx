import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import ProjectDetailPage from '@/app/(dashboard)/projects/[id]/page';
import { apiClient } from '@/app/api/client';
import { createDeferred } from '@/test/deferred';
import type { ProjectDetail, ProjectProductSummary } from '@/types';

const route = vi.hoisted(() => ({
  id: 'proj-1',
  push: vi.fn(),
}));

vi.mock('next/navigation', () => ({
  useParams: () => ({ id: route.id }),
  useRouter: () => ({ push: route.push }),
}));

function product(id: string, name: string): ProjectProductSummary {
  return {
    id,
    name,
    category: 'Gadgets',
    platform: 'Amazon',
    market: 'USA',
    generations_count: 1,
    created_at: '2026-01-01T00:00:00.000Z',
  };
}

function projectPage(page: number, name: string, productName: string): ProjectDetail {
  const totalPages = 3;
  return {
    id: route.id,
    name,
    description: 'A project',
    platform: 'Amazon',
    market: 'USA',
    status: 'active',
    product_count: 3,
    created_at: '2026-01-01T00:00:00.000Z',
    products: {
      items: [product(`prod-${page}`, productName)],
      pagination: {
        page,
        page_size: 10,
        total: 3,
        total_pages: totalPages,
        has_next: page < totalPages,
        has_previous: page > 1,
      },
    },
  };
}

describe('ProjectDetailPage async loading', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    route.id = 'proj-1';
    route.push.mockReset();
    vi.spyOn(apiClient, 'get');
  });

  afterEach(() => {
    cleanup();
  });

  it('loads the initial project page', async () => {
    vi.mocked(apiClient.get).mockResolvedValue(projectPage(1, 'Alpha', 'Product One'));
    render(<ProjectDetailPage />);
    expect(screen.getByText('Loading...')).toBeInTheDocument();
    expect(await screen.findByRole('heading', { name: 'Alpha' })).toBeInTheDocument();
    expect(screen.getByText('Product One')).toBeInTheDocument();
  });

  it('keeps previous products visible while paging', async () => {
    const pageTwo = createDeferred<ProjectDetail>();
    vi.mocked(apiClient.get).mockImplementation((_path, options) => {
      const page = Number(options?.params?.page ?? 1);
      if (page === 1) {
        return Promise.resolve(projectPage(1, 'Alpha', 'Product One'));
      }
      return pageTwo.promise;
    });

    const user = userEvent.setup();
    render(<ProjectDetailPage />);
    expect(await screen.findByText('Product One')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /Next/i }));
    expect(screen.getByText('Product One')).toBeInTheDocument();
    expect(screen.queryByText('Loading...')).not.toBeInTheDocument();

    pageTwo.resolve(projectPage(2, 'Alpha', 'Product Two'));
    expect(await screen.findByText('Product Two')).toBeInTheDocument();
  });

  it('keeps the later project when the first id resolves after a switch', async () => {
    const first = createDeferred<ProjectDetail>();
    const second = createDeferred<ProjectDetail>();
    vi.mocked(apiClient.get).mockImplementation((path) => {
      if (String(path).includes('proj-1')) return first.promise;
      return second.promise;
    });

    const { rerender } = render(<ProjectDetailPage />);
    await waitFor(() => expect(apiClient.get).toHaveBeenCalled());

    route.id = 'proj-2';
    rerender(<ProjectDetailPage />);

    second.resolve({ ...projectPage(1, 'Beta', 'Product Beta'), id: 'proj-2' });
    expect(await screen.findByText('Beta')).toBeInTheDocument();

    first.resolve(projectPage(1, 'Alpha', 'Product One'));
    await waitFor(() => {
      expect(screen.getByText('Beta')).toBeInTheDocument();
    });
    expect(screen.queryByText('Alpha')).not.toBeInTheDocument();
  });

  it('ignores a stale error from the previous project id', async () => {
    const first = createDeferred<ProjectDetail>();
    const second = createDeferred<ProjectDetail>();
    vi.mocked(apiClient.get).mockImplementation((path) => {
      if (String(path).includes('proj-1')) return first.promise;
      return second.promise;
    });

    const { rerender } = render(<ProjectDetailPage />);
    route.id = 'proj-2';
    rerender(<ProjectDetailPage />);

    second.resolve({ ...projectPage(1, 'Beta', 'Product Beta'), id: 'proj-2' });
    expect(await screen.findByText('Beta')).toBeInTheDocument();

    first.reject(new Error('stale project failed'));
    await waitFor(() => {
      expect(screen.getByText('Beta')).toBeInTheDocument();
    });
    expect(screen.queryByText('stale project failed')).not.toBeInTheDocument();
  });

  it('clears the previous project when id changes', async () => {
    vi.mocked(apiClient.get).mockImplementation((path) => {
      if (String(path).includes('proj-1')) {
        return Promise.resolve(projectPage(1, 'Alpha', 'Product One'));
      }
      return Promise.resolve({
        ...projectPage(1, 'Beta', 'Product Beta'),
        id: 'proj-2',
      });
    });

    const { rerender } = render(<ProjectDetailPage />);
    expect(await screen.findByText('Alpha')).toBeInTheDocument();

    route.id = 'proj-2';
    rerender(<ProjectDetailPage />);
    expect(screen.getByText('Loading...')).toBeInTheDocument();
    expect(screen.queryByText('Alpha')).not.toBeInTheDocument();
    expect(await screen.findByText('Beta')).toBeInTheDocument();
  });

  it('shows a failure message when the request fails', async () => {
    vi.mocked(apiClient.get).mockRejectedValue(new Error('Failed to load project'));
    render(<ProjectDetailPage />);
    expect(await screen.findByText('Failed to load project')).toBeInTheDocument();
  });

  it('aborts the in-flight request on unmount', async () => {
    const deferred = createDeferred<ProjectDetail>();
    let capturedSignal: AbortSignal | undefined;
    vi.mocked(apiClient.get).mockImplementation((_path, options) => {
      capturedSignal = options?.signal;
      return deferred.promise;
    });

    const { unmount } = render(<ProjectDetailPage />);
    await waitFor(() => expect(capturedSignal).toBeDefined());
    unmount();
    expect(capturedSignal?.aborted).toBe(true);
  });
});
