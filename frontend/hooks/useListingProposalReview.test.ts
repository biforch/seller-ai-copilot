import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { getListingProposal } from '@/app/api/listing-proposals';
import { useListingProposalReview } from '@/hooks/useListingProposalReview';
import { ApiClientError } from '@/lib/api-client-error';
import { createDeferred } from '@/test/deferred';
import type { ListingProposalDetail } from '@/types';

vi.mock('@/app/api/listing-proposals', () => ({
  getListingProposal: vi.fn(),
  approveListingProposal: vi.fn(),
  patchListingProposalDecisions: vi.fn(),
  rejectListingProposal: vi.fn(),
}));

const getMock = vi.mocked(getListingProposal);

function detail(productId: string, proposalId: string, title: string): ListingProposalDetail {
  return {
    proposal: {
      id: proposalId,
      product_id: productId,
      base_version_id: null,
      candidate_snapshot: {
        title,
        bullets: ['b'],
        description: 'd',
        backend_keywords: ['k'],
      },
      field_decisions: {
        title: 'pending',
        bullets: 'pending',
        description: 'pending',
        backend_keywords: 'pending',
      },
      status: 'reviewing',
      revision: 1,
      generation_request_id: null,
      approved_version_id: null,
      reviewed_by: null,
      reviewed_at: null,
      created_at: '2026-01-01T00:00:00.000Z',
      updated_at: '2026-01-01T00:00:00.000Z',
    },
    base_version: null,
    approved_version: null,
    diff: {
      title: { base: null, candidate: title, changed: true },
      bullets: { base: null, candidate: ['b'], changed: true },
      description: { base: null, candidate: 'd', changed: true },
      backend_keywords: { base: null, candidate: ['k'], changed: true },
    },
  };
}

describe('useListingProposalReview', () => {
  beforeEach(() => {
    getMock.mockReset();
  });

  it('loads on mount', async () => {
    getMock.mockResolvedValue(detail('prod-1', 'prop-1', 'Mounted'));
    const { result } = renderHook(() => useListingProposalReview('prod-1', 'prop-1'));
    expect(result.current.isLoading).toBe(true);
    await waitFor(() => {
      expect(result.current.detail?.proposal.candidate_snapshot.title).toBe('Mounted');
    });
  });

  it('reloads when productId changes', async () => {
    getMock.mockImplementation((productId) =>
      Promise.resolve(detail(productId, 'prop-1', productId)),
    );
    const { result, rerender } = renderHook(
      ({ productId }) => useListingProposalReview(productId, 'prop-1'),
      { initialProps: { productId: 'prod-a' } },
    );
    await waitFor(() => expect(result.current.detail?.proposal.product_id).toBe('prod-a'));
    rerender({ productId: 'prod-b' });
    await waitFor(() => expect(result.current.detail?.proposal.product_id).toBe('prod-b'));
  });

  it('reloads when proposalId changes', async () => {
    getMock.mockImplementation((_productId, proposalId) =>
      Promise.resolve(detail('prod-1', proposalId, proposalId)),
    );
    const { result, rerender } = renderHook(
      ({ proposalId }) => useListingProposalReview('prod-1', proposalId),
      { initialProps: { proposalId: 'prop-a' } },
    );
    await waitFor(() => expect(result.current.detail?.proposal.id).toBe('prop-a'));
    rerender({ proposalId: 'prop-b' });
    await waitFor(() => expect(result.current.detail?.proposal.id).toBe('prop-b'));
  });

  it('rejects stale success after a faster switch', async () => {
    const first = createDeferred<ListingProposalDetail>();
    const second = createDeferred<ListingProposalDetail>();
    getMock.mockImplementation((productId) => (productId === 'prod-a' ? first.promise : second.promise));

    const { result, rerender } = renderHook(
      ({ productId }) => useListingProposalReview(productId, 'prop-1'),
      { initialProps: { productId: 'prod-a' } },
    );
    rerender({ productId: 'prod-b' });
    first.resolve(detail('prod-a', 'prop-1', 'Stale'));
    second.resolve(detail('prod-b', 'prop-1', 'Fresh'));
    await waitFor(() => {
      expect(result.current.detail?.proposal.candidate_snapshot.title).toBe('Fresh');
    });
  });

  it('rejects a stale error after a newer success', async () => {
    const first = createDeferred<ListingProposalDetail>();
    const second = createDeferred<ListingProposalDetail>();
    getMock.mockImplementation((productId) => (productId === 'prod-a' ? first.promise : second.promise));

    const { result, rerender } = renderHook(
      ({ productId }) => useListingProposalReview(productId, 'prop-1'),
      { initialProps: { productId: 'prod-a' } },
    );
    rerender({ productId: 'prod-b' });
    second.resolve(detail('prod-b', 'prop-1', 'Fresh'));
    await waitFor(() => {
      expect(result.current.detail?.proposal.candidate_snapshot.title).toBe('Fresh');
    });
    first.reject(new Error('stale failure'));
    await waitFor(() => {
      expect(result.current.detail?.proposal.candidate_snapshot.title).toBe('Fresh');
    });
    expect(result.current.error).toBeNull();
  });

  it('reload via load() fetches again', async () => {
    getMock.mockResolvedValue(detail('prod-1', 'prop-1', 'Mounted'));
    const { result } = renderHook(() => useListingProposalReview('prod-1', 'prop-1'));
    await waitFor(() => expect(result.current.detail).not.toBeNull());
    const callsBefore = getMock.mock.calls.length;

    await act(async () => {
      await result.current.load();
    });
    expect(getMock.mock.calls.length).toBeGreaterThan(callsBefore);
  });

  it('aborts the in-flight request on unmount', async () => {
    const deferred = createDeferred<ListingProposalDetail>();
    let capturedSignal: AbortSignal | undefined;
    getMock.mockImplementation((_productId, _proposalId, signal) => {
      capturedSignal = signal;
      return deferred.promise;
    });
    const { unmount } = renderHook(() => useListingProposalReview('prod-1', 'prop-1'));
    await waitFor(() => expect(capturedSignal).toBeDefined());
    unmount();
    expect(capturedSignal?.aborted).toBe(true);
  });

  it('maps 404 to the notFound contract', async () => {
    getMock.mockRejectedValue(new ApiClientError('missing', 404));
    const { result } = renderHook(() => useListingProposalReview('prod-1', 'missing'));
    await waitFor(() => expect(result.current.notFound).toBe(true));
    expect(result.current.error).toBe('Proposal not found or you do not have access.');
  });
});
