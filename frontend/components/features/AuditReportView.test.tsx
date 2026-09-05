import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { AuditReportView } from '@/components/features/AuditReportView';
import type { ListingAuditReport } from '@/app/api/listing-audit';

const report: ListingAuditReport = {
  report_id: 'report-1',
  report_type: 'listing_audit',
  schema_version: 'listing-audit-schema-v1',
  prompt_version: 'listing-audit-prompt-v3',
  overall_score: 45,
  created_at: '2026-08-28T20:00:00Z',
  result: {
    dimension_scores: {
      positioning: { score: 60, rationale: 'The product category is clear.' },
      buyer_clarity: { score: 55, rationale: 'The use case is present.' },
      information_quality: { score: 30, rationale: 'Important details are missing.' },
      conversion_readiness: { score: 25, rationale: 'Buyers cannot confirm fit.' },
      discoverability: { score: 65, rationale: 'Core search terms are present.' },
    },
    issues: [{
      id: 'ISSUE-1',
      category: 'information_quality',
      severity: 'high',
      problem: 'Compatibility details are missing.',
      reason: 'The listing does not state compatible device sizes.',
      impact: 'Buyers cannot evaluate fit.',
      evidence: [{ source: 'bullet_1', quote: 'Holds a phone on a desk.' }],
    }],
    priority_actions: [{
      rank: 1,
      issue_ids: ['ISSUE-1'],
      action: 'Add verified device-size compatibility.',
      why_now: 'Fit is a primary purchase question.',
      expected_effect: 'Buyers can confirm compatibility.',
      effort: 'low',
    }],
    image_observations: [{ image_index: 1, observation: 'The product is shown from the front.', implication: 'Buyers can see the base shape.' }],
    limitations: ['No customer reviews were supplied.'],
  },
};

describe('AuditReportView', () => {
  afterEach(cleanup);

  it('renders the score, grounded evidence, linked action, and limitations', () => {
    render(<AuditReportView report={report} />);

    expect(screen.getByText('45')).toBeInTheDocument();
    expect(screen.getByText('“Holds a phone on a desk.”')).toBeInTheDocument();
    expect(screen.getAllByText('Add verified device-size compatibility.')).toHaveLength(2);
    expect(screen.getByText('No customer reviews were supplied.')).toBeInTheDocument();
    expect(screen.getByText('The product is shown from the front.')).toBeInTheDocument();
    expect(screen.getByText('Search coverage')).toBeInTheDocument();
    expect(screen.getByText('What to add')).toBeInTheDocument();
    expect(screen.queryByText('Search readiness')).not.toBeInTheDocument();
  });
});
