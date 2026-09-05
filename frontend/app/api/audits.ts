import { apiClient } from '@/app/api/client';
import type { ListingAuditInput, ListingAuditReport } from '@/app/api/listing-audit';

function idempotencyKey(): string {
  if (!globalThis.crypto?.randomUUID) {
    throw new Error('Secure request identifiers are unavailable.');
  }
  return globalThis.crypto.randomUUID();
}

export const auditsApi = {
  create: (input: ListingAuditInput, signal?: AbortSignal) =>
    apiClient.post<ListingAuditReport>('/analysis/listing-audit', input, {
      signal,
      headers: { 'Idempotency-Key': idempotencyKey() },
    }),
  list: (signal?: AbortSignal) =>
    apiClient.get<ListingAuditReport[]>('/audits', { signal }),
  get: (reportId: string, signal?: AbortSignal) =>
    apiClient.get<ListingAuditReport>(`/audits/${reportId}`, { signal }),
};
