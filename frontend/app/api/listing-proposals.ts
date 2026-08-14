import { apiClient } from '@/app/api/client';
import type {
  ApproveProposalResponse,
  FieldDecisions,
  ListListingProposalsParams,
  ListingProposalDetail,
  PaginatedResponse,
  PatchProposalDecisionsResponse,
  RejectProposalResponse,
  ListingProposalListItem,
} from '@/types';

function proposalBasePath(productId: string, proposalId?: string): string {
  const base = `/products/${productId}/listing/proposals`;
  return proposalId ? `${base}/${proposalId}` : base;
}

export function listListingProposals(
  productId: string,
  params: ListListingProposalsParams = {},
  signal?: AbortSignal,
) {
  return apiClient.get<PaginatedResponse<ListingProposalListItem>>(
    proposalBasePath(productId),
    {
      params: {
        page: params.page ?? 1,
        page_size: params.page_size ?? 20,
        status: params.status ?? 'reviewing',
      },
      signal,
    },
  );
}

export function getListingProposal(
  productId: string,
  proposalId: string,
  signal?: AbortSignal,
) {
  return apiClient.get<ListingProposalDetail>(
    proposalBasePath(productId, proposalId),
    { signal },
  );
}

export function patchListingProposalDecisions(
  productId: string,
  proposalId: string,
  body: { expected_revision: number; decisions: FieldDecisions },
  signal?: AbortSignal,
) {
  return apiClient.patch<PatchProposalDecisionsResponse>(
    `${proposalBasePath(productId, proposalId)}/decisions`,
    body,
    { signal },
  );
}

export function approveListingProposal(
  productId: string,
  proposalId: string,
  body: { expected_revision: number; decisions?: FieldDecisions },
  signal?: AbortSignal,
) {
  return apiClient.post<ApproveProposalResponse>(
    `${proposalBasePath(productId, proposalId)}/approve`,
    body,
    { signal },
  );
}

export function rejectListingProposal(
  productId: string,
  proposalId: string,
  body: { expected_revision: number },
  signal?: AbortSignal,
) {
  return apiClient.post<RejectProposalResponse>(
    `${proposalBasePath(productId, proposalId)}/reject`,
    body,
    { signal },
  );
}
