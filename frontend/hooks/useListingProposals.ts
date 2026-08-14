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
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);

  const abortRef = useRef<AbortController | null>(null);
  const requestSeq = useRef(0);

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
    void load(page, statusFilter);
    return () => {
      abortRef.current?.abort();
    };
  }, [load, page, statusFilter]);

  const changeStatus = useCallback((nextStatus: ProposalListStatus) => {
    setStatusFilter(nextStatus);
    setPage(1);
  }, []);

  const goToPage = useCallback((nextPage: number) => {
    setPage(nextPage);
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
