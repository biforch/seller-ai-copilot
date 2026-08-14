'use client';

import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { ArrowLeft, ChevronLeft, ChevronRight } from 'lucide-react';

import { ProposalStatusBadge } from '@/components/features/ProposalStatusBadge';
import { useListingProposals } from '@/hooks/useListingProposals';
import { buildReviewPath, PROPOSAL_LIST_STATUSES } from '@/lib/listing-proposals';
import type { ProposalListStatus } from '@/types';

interface ProposalInboxClientProps {
  productId: string;
  productName?: string;
  initialStatus?: ProposalListStatus;
}

function PaginationBar({
  pagination,
  disabled,
  onPageChange,
}: {
  pagination: {
    page: number;
    total_pages: number;
    has_next: boolean;
    has_previous: boolean;
  };
  disabled?: boolean;
  onPageChange: (page: number) => void;
}) {
  if (pagination.total_pages <= 1) {
    return null;
  }

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-t px-4 py-3">
      <p className="text-sm text-gray-500">
        Page {pagination.page} of {pagination.total_pages}
      </p>
      <div className="flex items-center gap-2">
        <button
          type="button"
          disabled={disabled || !pagination.has_previous}
          onClick={() => onPageChange(pagination.page - 1)}
          className="inline-flex items-center gap-1 rounded-lg border px-3 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-50 hover:bg-gray-50"
        >
          <ChevronLeft className="h-4 w-4" />
          Previous
        </button>
        <button
          type="button"
          disabled={disabled || !pagination.has_next}
          onClick={() => onPageChange(pagination.page + 1)}
          className="inline-flex items-center gap-1 rounded-lg border px-3 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-50 hover:bg-gray-50"
        >
          Next
          <ChevronRight className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}

export function ProposalInboxClient({
  productId,
  productName,
  initialStatus = 'reviewing',
}: ProposalInboxClientProps) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const {
    items,
    pagination,
    statusFilter,
    isLoading,
    error,
    notFound,
    changeStatus,
    goToPage,
  } = useListingProposals({ productId, initialStatus });

  const handleStatusChange = (nextStatus: ProposalListStatus) => {
    changeStatus(nextStatus);
    const params = new URLSearchParams(searchParams.toString());
    if (nextStatus === 'reviewing') {
      params.delete('status');
    } else {
      params.set('status', nextStatus);
    }
    const query = params.toString();
    router.replace(
      query
        ? `/products/${productId}/listing/reviews?${query}`
        : `/products/${productId}/listing/reviews`,
    );
  };

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      <button
        type="button"
        onClick={() => router.push(`/products/${productId}`)}
        className="flex items-center gap-2 text-gray-600 hover:text-gray-900 mb-6"
      >
        <ArrowLeft className="w-4 h-4" />
        Back to Product
      </button>

      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900">AI Listing Reviews</h1>
        <p className="text-gray-600 mt-1">
          {productName
            ? `Review AI suggestions for ${productName} before creating a new listing version.`
            : 'Review AI suggestions before creating a new listing version.'}
        </p>
      </div>

      <div className="mb-4">
        <label htmlFor="proposal-status-filter" className="block text-sm text-gray-600 mb-1">
          Status
        </label>
        <select
          id="proposal-status-filter"
          value={statusFilter}
          onChange={(event) => handleStatusChange(event.target.value as ProposalListStatus)}
          className="w-full max-w-xs rounded-lg border bg-white px-3 py-2"
        >
          {PROPOSAL_LIST_STATUSES.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </div>

      {error && (
        <div className="mb-4 rounded-lg bg-red-50 p-3 text-sm text-red-600" role="alert">
          {error}
        </div>
      )}

      <div className="rounded-xl border bg-white overflow-hidden">
        {isLoading ? (
          <p className="p-6 text-gray-500">Loading proposals...</p>
        ) : notFound ? (
          <p className="p-6 text-gray-600">Product not found or you do not have access.</p>
        ) : items.length === 0 ? (
          <div className="p-6">
            <p className="text-gray-600">
              {statusFilter === 'reviewing'
                ? 'No proposals are waiting for review. Generate a listing to create a new AI suggestion.'
                : 'No proposals match this filter.'}
            </p>
          </div>
        ) : (
          <div className="divide-y">
            {items.map((item) => (
              <Link
                key={item.id}
                href={buildReviewPath(productId, item.id)}
                className="block p-4 hover:bg-gray-50 transition-colors"
              >
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div className="min-w-0">
                    <p className="font-medium text-gray-900 break-words">{item.candidate_title}</p>
                    <p className="text-sm text-gray-500 mt-1">
                      Revision {item.revision} • Created{' '}
                      {new Date(item.created_at).toLocaleString()}
                      {item.reviewed_at
                        ? ` • Reviewed ${new Date(item.reviewed_at).toLocaleString()}`
                        : ''}
                    </p>
                  </div>
                  <ProposalStatusBadge status={item.status} />
                </div>
              </Link>
            ))}
          </div>
        )}

        {pagination && items.length > 0 && (
          <PaginationBar
            pagination={pagination}
            disabled={isLoading}
            onPageChange={goToPage}
          />
        )}
      </div>
    </div>
  );
}
