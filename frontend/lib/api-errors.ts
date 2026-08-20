import type { ApiError } from '@/types';

export const AI_RESPONSE_INVALID = 'AI_RESPONSE_INVALID';
export const GENERATION_IN_PROGRESS = 'GENERATION_IN_PROGRESS';
export const IDEMPOTENCY_CONFLICT = 'IDEMPOTENCY_CONFLICT';
export const QUOTA_EXCEEDED = 'QUOTA_EXCEEDED';
export const LISTING_DECISIONS_INCOMPLETE = 'LISTING_DECISIONS_INCOMPLETE';
export const LISTING_NO_BASE_PARTIAL_ACCEPT_FORBIDDEN = 'LISTING_NO_BASE_PARTIAL_ACCEPT_FORBIDDEN';
export const LISTING_PROPOSAL_NOT_REVIEWING = 'LISTING_PROPOSAL_NOT_REVIEWING';
export const LISTING_PROPOSAL_REVISION_CONFLICT = 'LISTING_PROPOSAL_REVISION_CONFLICT';
export const LISTING_PROPOSAL_STALE = 'LISTING_PROPOSAL_STALE';
export const AUTH_SESSION_INVALID = 'AUTH_SESSION_INVALID';

const PROPOSAL_CONFLICT_MESSAGE =
  'This proposal was updated elsewhere. Reload to continue with the latest revision.';

export function formatApiErrorPayload(
  payload: ApiError,
  httpStatus: number
): string {
  if (payload.error_code === AI_RESPONSE_INVALID) {
    return (
      payload.message ||
      'The AI service returned an invalid response. Please try again.'
    );
  }

  if (payload.error_code === GENERATION_IN_PROGRESS) {
    return payload.message || 'Generation is already in progress. Please wait.';
  }

  if (payload.error_code === IDEMPOTENCY_CONFLICT) {
    return (
      payload.message ||
      'This request conflicts with a previous submission. Refresh and try again.'
    );
  }

  if (
    payload.error_code === LISTING_PROPOSAL_REVISION_CONFLICT ||
    payload.error_code === LISTING_PROPOSAL_STALE
  ) {
    return PROPOSAL_CONFLICT_MESSAGE;
  }

  if (payload.error_code === LISTING_PROPOSAL_NOT_REVIEWING) {
    return payload.message || 'This proposal is no longer open for review.';
  }

  if (payload.error_code === LISTING_DECISIONS_INCOMPLETE) {
    return payload.message || 'Accept or reject every listing field before continuing.';
  }

  if (payload.error_code === LISTING_NO_BASE_PARTIAL_ACCEPT_FORBIDDEN) {
    return (
      payload.message ||
      'Partial accept is not allowed when there is no base listing version.'
    );
  }

  if (payload.error_code === QUOTA_EXCEEDED || httpStatus === 403) {
    return payload.detail || payload.message || 'Your AI quota has been exceeded.';
  }

  if (httpStatus === 404) {
    return payload.message || 'The requested resource was not found.';
  }

  if (httpStatus === 422) {
    return payload.detail || payload.message || 'Validation Error';
  }

  if (httpStatus === 429) {
    return payload.detail || payload.message || 'Too many requests. Please wait and try again.';
  }

  if (httpStatus >= 500) {
    return payload.message || 'Something went wrong. Please try again later.';
  }

  return payload.detail || payload.message || 'Request failed';
}
