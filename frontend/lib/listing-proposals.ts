import { ApiClientError } from '@/lib/api-client-error';
import {
  LISTING_DECISIONS_INCOMPLETE,
  LISTING_NO_BASE_PARTIAL_ACCEPT_FORBIDDEN,
  LISTING_PROPOSAL_NOT_REVIEWING,
  LISTING_PROPOSAL_REVISION_CONFLICT,
  LISTING_PROPOSAL_STALE,
} from '@/lib/api-errors';
import type { FieldDecisions, FieldDecisionValue, ProposalListStatus } from '@/types';

export const LISTING_DECISION_FIELDS = [
  'title',
  'bullets',
  'description',
  'backend_keywords',
] as const;

export type ListingDecisionField = (typeof LISTING_DECISION_FIELDS)[number];

export const PROPOSAL_LIST_STATUSES: { value: ProposalListStatus; label: string }[] = [
  { value: 'reviewing', label: 'Reviewing' },
  { value: 'approved', label: 'Approved' },
  { value: 'rejected', label: 'Rejected' },
  { value: 'superseded', label: 'Superseded' },
  { value: 'all', label: 'All' },
];

export function hasPendingDecisions(decisions: FieldDecisions): boolean {
  return LISTING_DECISION_FIELDS.some((field) => decisions[field] === 'pending');
}

export function hasRejectedDecision(decisions: FieldDecisions): boolean {
  return LISTING_DECISION_FIELDS.some((field) => decisions[field] === 'reject');
}

export function canApproveProposal(
  status: string,
  decisions: FieldDecisions,
  hasBaseVersion: boolean,
): { allowed: boolean; reason: string | null } {
  if (status !== 'reviewing') {
    return { allowed: false, reason: 'This proposal is no longer open for review.' };
  }
  if (hasPendingDecisions(decisions)) {
    return {
      allowed: false,
      reason: 'Accept or reject every listing field before approving.',
    };
  }
  if (!hasBaseVersion && hasRejectedDecision(decisions)) {
    return {
      allowed: false,
      reason:
        'This is the first listing version. Accept every field to approve, or reject the proposal.',
    };
  }
  return { allowed: true, reason: null };
}

export function shouldResetPageOnStatusChange(
  previousStatus: ProposalListStatus,
  nextStatus: ProposalListStatus,
): boolean {
  return previousStatus !== nextStatus;
}

export function isProposalRefreshRequiredError(error: unknown): boolean {
  if (!(error instanceof ApiClientError)) {
    return false;
  }
  return (
    error.errorCode === LISTING_PROPOSAL_REVISION_CONFLICT ||
    error.errorCode === LISTING_PROPOSAL_STALE ||
    error.errorCode === LISTING_PROPOSAL_NOT_REVIEWING
  );
}

export function isProposalReadonlyStatus(status: string): boolean {
  return status === 'approved' || status === 'rejected' || status === 'superseded';
}

export function formatProposalStatusLabel(status: string): string {
  switch (status) {
    case 'reviewing':
      return 'Reviewing';
    case 'approved':
      return 'Approved';
    case 'rejected':
      return 'Rejected';
    case 'superseded':
      return 'Superseded';
    default:
      return status;
  }
}

export function buildReviewPath(productId: string, proposalId: string): string {
  return `/products/${productId}/listing/reviews/${proposalId}`;
}

export function buildInboxPath(productId: string, status?: ProposalListStatus): string {
  if (!status || status === 'reviewing') {
    return `/products/${productId}/listing/reviews`;
  }
  return `/products/${productId}/listing/reviews?status=${status}`;
}

export function normalizeDecisionValue(value: FieldDecisionValue): FieldDecisionValue {
  return value;
}

export const PROPOSAL_ERROR_CODES = {
  REVISION_CONFLICT: LISTING_PROPOSAL_REVISION_CONFLICT,
  STALE: LISTING_PROPOSAL_STALE,
  NOT_REVIEWING: LISTING_PROPOSAL_NOT_REVIEWING,
  DECISIONS_INCOMPLETE: LISTING_DECISIONS_INCOMPLETE,
  NO_BASE_PARTIAL: LISTING_NO_BASE_PARTIAL_ACCEPT_FORBIDDEN,
} as const;
