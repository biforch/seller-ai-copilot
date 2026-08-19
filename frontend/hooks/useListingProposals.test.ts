import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { listListingProposals } from '@/app/api/listing-proposals';
import { useListingProposals } from '@/hooks/useListingProposals';
import { ApiClientError } from '@/lib/api-client-error';
import { createDeferred } from '@/test/deferred';
import type { ListingProposalListItem, PaginatedResponse } from '@/types';

vi.mock('@/app/api/listing-proposals', () => ({
  listListingProposals: vi.fn(),
}));

const listMock = vi.mocked(listListingProposals);

function item(id: string, title: string): ListingProposalListItem {
  return {
    id,
    product_id: 'prod-1',
    base_version_id: null,
    approved_version_id: null,
    status: 'reviewing',
    revision: 1,
    candidate_title: title,
    generation_request_id: null,
    reviewed_at: null,
    created_at: '2026-01-01T00:00:00.000Z',
    updated_at: '2026-01-01T00:00:00.000Z',
  };
}

function pageOf(
  title: string,
  page: number,
  status: string,
): PaginatedResponse<ListingProposalListItem> {
  return {
    items: [item(`${status}-${page}`, title)],
    pagination: {
      page,
      page_size: 20,
      total: 40,
      total_pages: 2,
      has_next: page < 2,
      has_previous: page > 1,
    },
  };
}

describe('useListingProposals', () => {
  beforeEach(() => {
    listMock.mockReset();
  });

  it('loads on mount', async () => {
    listMock.mockResolvedValue(pageOf('First', 1, 'reviewing'));
    const { result } = renderHook(() => useListingProposals({ productId: 'prod-1' }));
    expect(result.current.isLoading).toBe(true);
    await waitFor(() => {
      expect(result.current.items[0]?.candidate_title).toBe('First');
    });
    expect(listMock).toHaveBeenCalledWith(
      'prod-1',
      { page: 1, page_size: 20, status: 'reviewing' },
      expect.any(AbortSignal),
    );
  });

  it('reloads when the page changes', async () => {
    listMock.mockImplementation((_productId, params) => {
      const page = Number(params?.page ?? 1);
      return Promise.resolve(pageOf(`Page ${page}`, page, 'reviewing'));
    });
    const { result } = renderHook(() => useListingProposals({ productId: 'prod-1' }));
    await waitFor(() => expect(result.current.items).toHaveLength(1));

    act(() => {
      result.current.goToPage(2);
    });
    expect(result.current.isLoading).toBe(true);
    await waitFor(() => {
      expect(result.current.items[0]?.candidate_title).toBe('Page 2');
    });
  });

  it('reloads when the status filter changes', async () => {
    listMock.mockImplementation((_productId, params) => {
      const status = String(params?.status ?? 'reviewing');
      return Promise.resolve(pageOf(status, 1, status));
    });
    const { result } = renderHook(() => useListingProposals({ productId: 'prod-1' }));
    await waitFor(() => expect(result.current.items[0]?.candidate_title).toBe('reviewing'));

    act(() => {
      result.current.changeStatus('approved');
    });
    await waitFor(() => {
      expect(result.current.items[0]?.candidate_title).toBe('approved');
    });
    expect(result.current.page).toBe(1);
  });

  it('keeps the latest page when overlapping page requests finish out of order', async () => {
    const pageOne = createDeferred<PaginatedResponse<ListingProposalListItem>>();
    const pageTwo = createDeferred<PaginatedResponse<ListingProposalListItem>>();
    listMock.mockImplementation((_productId, params) =>
      Number(params?.page) === 1 ? pageOne.promise : pageTwo.promise,
    );

    const { result } = renderHook(() => useListingProposals({ productId: 'prod-1' }));
    act(() => {
      result.current.goToPage(2);
    });

    pageTwo.resolve(pageOf('Page 2', 2, 'reviewing'));
    await waitFor(() => {
      expect(result.current.items[0]?.candidate_title).toBe('Page 2');
    });
    pageOne.resolve(pageOf('Page 1', 1, 'reviewing'));
    await waitFor(() => {
      expect(result.current.items[0]?.candidate_title).toBe('Page 2');
    });
  });

  it('rejects stale success after a faster parameter switch', async () => {
    const first = createDeferred<PaginatedResponse<ListingProposalListItem>>();
    const second = createDeferred<PaginatedResponse<ListingProposalListItem>>();
    listMock.mockImplementation((productId) => (productId === 'prod-a' ? first.promise : second.promise));

    const { result, rerender } = renderHook(
      ({ productId }) => useListingProposals({ productId }),
      { initialProps: { productId: 'prod-a' } },
    );

    rerender({ productId: 'prod-b' });
    first.resolve(pageOf('Stale', 1, 'reviewing'));
    second.resolve(pageOf('Fresh', 1, 'reviewing'));

    await waitFor(() => {
      expect(result.current.items[0]?.candidate_title).toBe('Fresh');
    });
  });

  it('rejects a stale error after a newer success', async () => {
    const first = createDeferred<PaginatedResponse<ListingProposalListItem>>();
    const second = createDeferred<PaginatedResponse<ListingProposalListItem>>();
    listMock.mockImplementation((productId) => (productId === 'prod-a' ? first.promise : second.promise));

    const { result, rerender } = renderHook(
      ({ productId }) => useListingProposals({ productId }),
      { initialProps: { productId: 'prod-a' } },
    );
    rerender({ productId: 'prod-b' });
    second.resolve(pageOf('Fresh', 1, 'reviewing'));
    await waitFor(() => expect(result.current.items[0]?.candidate_title).toBe('Fresh'));

    first.reject(new Error('stale failure'));
    await waitFor(() => expect(result.current.items[0]?.candidate_title).toBe('Fresh'));
    expect(result.current.error).toBeNull();
  });

  it('refresh reloads the current page and may set loading', async () => {
    listMock.mockResolvedValue(pageOf('First', 1, 'reviewing'));
    const { result } = renderHook(() => useListingProposals({ productId: 'prod-1' }));
    await waitFor(() => expect(result.current.items).toHaveLength(1));
    const callsBefore = listMock.mock.calls.length;

    act(() => {
      result.current.refresh();
    });
    expect(result.current.isLoading).toBe(true);
    await waitFor(() => expect(listMock.mock.calls.length).toBeGreaterThan(callsBefore));
  });

  it('aborts the in-flight request on unmount', async () => {
    const deferred = createDeferred<PaginatedResponse<ListingProposalListItem>>();
    let capturedSignal: AbortSignal | undefined;
    listMock.mockImplementation((_productId, _params, signal) => {
      capturedSignal = signal;
      return deferred.promise;
    });
    const { unmount } = renderHook(() => useListingProposals({ productId: 'prod-1' }));
    await waitFor(() => expect(capturedSignal).toBeDefined());
    unmount();
    expect(capturedSignal?.aborted).toBe(true);
  });

  it('maps 404 to the notFound contract', async () => {
    listMock.mockRejectedValue(new ApiClientError('missing', 404));
    const { result } = renderHook(() => useListingProposals({ productId: 'missing' }));
    await waitFor(() => expect(result.current.notFound).toBe(true));
    expect(result.current.error).toBe('Product not found or you do not have access.');
    expect(result.current.items).toEqual([]);
  });
});
