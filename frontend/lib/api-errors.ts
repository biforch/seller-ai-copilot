import type { ApiError } from '@/types';

export const AI_RESPONSE_INVALID = 'AI_RESPONSE_INVALID';
export const GENERATION_IN_PROGRESS = 'GENERATION_IN_PROGRESS';
export const IDEMPOTENCY_CONFLICT = 'IDEMPOTENCY_CONFLICT';
export const QUOTA_EXCEEDED = 'QUOTA_EXCEEDED';

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

  if (payload.error_code === QUOTA_EXCEEDED || httpStatus === 403) {
    return payload.detail || payload.message || 'Your AI quota has been exceeded.';
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
