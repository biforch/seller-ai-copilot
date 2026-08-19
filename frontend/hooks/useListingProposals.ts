'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import { listListingProposals } from '@/app/api/listing-proposals';
import { isApiClientError } from '@/lib/api-client-error';
import type { PaginationMeta, ProposalListStatus, ListingProposalListItem } from '@/types';

export interface UseListingProposalsOptions {
  productId: string;
  initialStatus?: ProposalListStatus;
  pageSize?: number;
}

export function useListingProposals({
  productId,
  initialStatus = 'reviewing',
  pageSize = 20,
}: UseListingProposalsOptions) {
  const [items, setItems] = useState<ListingProposalListItem[]>([]);
  const [pagination, setPagination] = useState<PaginationMeta | null>(null);
  const [statusFilter, setStatusFilter] = useState<ProposalListStatus>(initialStatus);
  const [page, setPage] = useState(1);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);

  const abortRef = useRef<AbortController | null>(null);
  const requestSeq = useRef(0);
  const [seenProductId, setSeenProductId] = useState(productId);
  const [seenPageSize, setSeenPageSize] = useState(pageSize);

  if (productId !== seenProductId || pageSize !== seenPageSize) {
    setSeenProductId(productId);
    setSeenPageSize(pageSize);
    setPage(1);
    setItems([]);
    setPagination(null);
    setError(null);
    setNotFound(false);
    setIsLoading(true);
  }

  const load = useCallback(
    async (nextPage: number, nextStatus: ProposalListStatus) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      const seq = ++requestSeq.current;

      setIsLoading(true);
      setError(null);
      setNotFound(false);

      try {
        const data = await listListingProposals(
          productId,
          { page: nextPage, page_size: pageSize, status: nextStatus },
          controller.signal,
        );

        if (seq !== requestSeq.current || controller.signal.aborted) {
          return null;
        }

        setItems(data.items);
        setPagination(data.pagination);
        setPage(data.pagination.page);
        return data;
      } catch (err) {
        if (controller.signal.aborted) {
          return null;
        }
        if (seq !== requestSeq.current) {
          return null;
        }
        if (isApiClientError(err) && err.httpStatus === 404) {
          setNotFound(true);
          setItems([]);
          setPagination(null);
          setError('Product not found or you do not have access.');
        } else {
          setError(err instanceof Error ? err.message : 'Failed to load proposals');
        }
        return null;
      } finally {
        if (seq === requestSeq.current) {
          setIsLoading(false);
        }
      }
    },
    [productId, pageSize],
  );

  useEffect(() => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const seq = ++requestSeq.current;
    const requestedProductId = productId;
    const requestedPage = page;
    const requestedStatus = statusFilter;
    const requestedPageSize = pageSize;

    void listListingProposals(
      requestedProductId,
      { page: requestedPage, page_size: requestedPageSize, status: requestedStatus },
      controller.signal,
    ).then((data) => {
      if (seq !== requestSeq.current || controller.signal.aborted) {
        return;
      }
      setItems(data.items);
      setPagination(data.pagination);
      setPage(data.pagination.page);
      setError(null);
      setNotFound(false);
    }).catch((err) => {
      if (controller.signal.aborted || seq !== requestSeq.current) {
        return;
      }
      if (isApiClientError(err) && err.httpStatus === 404) {
        setNotFound(true);
        setItems([]);
        setPagination(null);
        setError('Product not found or you do not have access.');
      } else {
        setError(err instanceof Error ? err.message : 'Failed to load proposals');
      }
    }).finally(() => {
      if (seq === requestSeq.current) {
        setIsLoading(false);
      }
    });

    return () => {
      abortRef.current?.abort();
    };
  }, [page, pageSize, productId, statusFilter]);

  const changeStatus = useCallback((nextStatus: ProposalListStatus) => {
    setStatusFilter(nextStatus);
    setPage(1);
    setIsLoading(true);
    setError(null);
    setNotFound(false);
  }, []);

  const goToPage = useCallback((nextPage: number) => {
    setPage(nextPage);
    setIsLoading(true);
    setError(null);
    setNotFound(false);
  }, []);

  const refresh = useCallback(() => {
    void load(page, statusFilter);
  }, [load, page, statusFilter]);

  return {
    items,
    pagination,
    statusFilter,
    page,
    isLoading,
    error,
    notFound,
    changeStatus,
    goToPage,
    refresh,
  };
}
