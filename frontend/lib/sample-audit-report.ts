import type { ListingAuditReport } from '@/app/api/listing-audit';

export const sampleAuditReport: ListingAuditReport = {
  report_id: 'sample-phone-stand',
  report_type: 'listing_audit',
  schema_version: 'listing-audit-schema-v1',
  prompt_version: 'listing-audit-prompt-v4',
  overall_score: 52,
  created_at: '2026-08-31T00:00:00Z',
  result: {
    dimension_scores: {
      positioning: { score: 61, rationale: 'The product and desk use case are clear, but differentiation is mostly feature-led.' },
      buyer_clarity: { score: 48, rationale: 'Important fit, adjustment, and charging details are not specific enough for comparison.' },
      information_quality: { score: 43, rationale: 'Several useful claims lack the measurements buyers need to verify them.' },
      conversion_readiness: { score: 39, rationale: 'The listing leaves common stability and charging objections unresolved.' },
      discoverability: { score: 70, rationale: 'Core category and compatibility terms are present naturally in the supplied copy.' },
    },
    issues: [
      {
        id: 'ISSUE-1', category: 'information_quality', severity: 'high',
        problem: 'The height and adjustment range are not stated.',
        reason: 'The supplied review asks for exact height and adjustment information, but the listing provides no measurements.',
        impact: 'Buyers cannot compare the stand’s viewing range with their desk setup.',
        evidence: [{ source: 'customer_review', quote: 'I wish the product page showed the exact height and adjustment range.' }],
      },
      {
        id: 'ISSUE-2', category: 'conversion', severity: 'high',
        problem: 'The charging-access claim does not resolve the reported cable problem.',
        reason: 'The listing promises charging-port access while a supplied review reports difficulty connecting a cable during use.',
        impact: 'Buyers who charge at their desk may doubt whether the feature works for their setup.',
        evidence: [
          { source: 'bullet_3', quote: 'Open design provides easy charging-port access.' },
          { source: 'customer_review', quote: 'The charging cable is difficult to connect while the phone is on the stand.' },
        ],
      },
      {
        id: 'ISSUE-3', category: 'buyer_clarity', severity: 'medium',
        problem: 'Stability expectations for larger phones are unclear.',
        reason: 'A supplied review reports backward tipping with a larger phone, while the listing gives no tested weight or device-size limit.',
        impact: 'Buyers with larger devices cannot confidently assess stability.',
        evidence: [{ source: 'customer_review', quote: 'It tips backward when I place a larger phone on it.' }],
      },
    ],
    priority_actions: [
      { rank: 1, issue_ids: ['ISSUE-1'], action: 'Add verified minimum and maximum height plus the supported angle range.', why_now: 'These are direct comparison facts requested in the supplied feedback.', expected_effect: 'Buyers can judge whether the stand fits their desk and viewing position.', effort: 'low' },
      { rank: 2, issue_ids: ['ISSUE-2'], action: 'Clarify the cable opening dimensions and show a verified charging setup in the copy or images.', why_now: 'The current claim conflicts with a reported use problem.', expected_effect: 'The charging-access benefit becomes specific and easier to trust.', effort: 'medium' },
      { rank: 3, issue_ids: ['ISSUE-3'], action: 'State the verified device-size or weight range and explain the stability limit.', why_now: 'Larger-device stability is an unresolved purchase objection.', expected_effect: 'Buyers can determine whether their device is within the supported range.', effort: 'medium' },
    ],
    image_observations: [],
    limitations: [
      'No verified height, angle, cable-opening, device-weight, or stability-test specifications were supplied.',
      'No product images were supplied, so visual claims and charging clearance could not be assessed.',
      'The audit does not know search volume, ranking, traffic, conversion rate, or competitor performance.',
    ],
  },
};
