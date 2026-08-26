import { describe, expect, it, vi } from 'vitest';

import { apiClient } from '@/app/api/client';
import { listingAuditApi, type ListingAuditInput } from '@/app/api/listing-audit';

vi.mock('@/app/api/client', () => ({
  apiClient: { post: vi.fn() },
}));

describe('listingAuditApi', () => {
  it('uses the internal endpoint with an idempotency header and abort signal', () => {
    const input: ListingAuditInput = {
      marketplace: 'US',
      language: 'en-US',
      listing: {
        title: 'Phone stand',
        bullets: ['Folds flat'],
        description: 'A compact stand.',
      },
      competitor_listing: null,
      customer_reviews: [],
    };
    const controller = new AbortController();

    listingAuditApi.create(
      input,
      '33333333-3333-4333-8333-333333333333',
      controller.signal,
    );

    expect(apiClient.post).toHaveBeenCalledWith('/analysis/listing-audit', input, {
      headers: { 'Idempotency-Key': '33333333-3333-4333-8333-333333333333' },
      signal: controller.signal,
    });
  });
});
