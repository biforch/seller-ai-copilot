import { apiClient } from '@/app/api/client';

export type ListingAuditMarketplace =
  | 'US'
  | 'CA'
  | 'MX'
  | 'UK'
  | 'DE'
  | 'FR'
  | 'IT'
  | 'ES'
  | 'JP'
  | 'AU';

export interface ListingAuditInput {
  marketplace: ListingAuditMarketplace;
  language: string;
  listing: {
    title: string;
    bullets: string[];
    description: string;
  };
  competitor_listing: string | null;
  customer_reviews: string[];
}

export interface ListingAuditReport {
  report_id: string;
  report_type: 'listing_audit';
  schema_version: 'listing-audit-schema-v1';
  prompt_version: 'listing-audit-prompt-v2';
  overall_score: number;
  result: {
    dimension_scores: Record<
      'positioning' | 'buyer_clarity' | 'information_quality' | 'conversion_readiness' | 'discoverability',
      { score: number; rationale: string }
    >;
    issues: Array<{
      id: string;
      category: string;
      severity: 'high' | 'medium' | 'low';
      problem: string;
      reason: string;
      impact: string;
      evidence: Array<{ source: string; quote: string }>;
    }>;
    priority_actions: Array<{
      rank: number;
      issue_ids: string[];
      action: string;
      why_now: string;
      expected_effect: string;
      effort: 'low' | 'medium' | 'high';
    }>;
    limitations: string[];
  };
  created_at: string;
}

export const listingAuditApi = {
  create(input: ListingAuditInput, idempotencyKey: string, signal?: AbortSignal) {
    return apiClient.post<ListingAuditReport>('/analysis/listing-audit', input, {
      headers: { 'Idempotency-Key': idempotencyKey },
      signal,
    });
  },
};
