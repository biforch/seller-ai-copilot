import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import ListingAuditClient from './ListingAuditClient';
import { listingAuditApi, type ListingAuditReport } from '@/app/api/listing-audit';

vi.mock('@/app/api/listing-audit', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/app/api/listing-audit')>();
  return { ...original, listingAuditApi: { create: vi.fn() } };
});

const report: ListingAuditReport = {
  report_id: '11111111-1111-4111-8111-111111111111',
  report_type: 'listing_audit',
  schema_version: 'listing-audit-schema-v1',
  prompt_version: 'listing-audit-prompt-v2',
  overall_score: 72,
  result: {
    dimension_scores: {
      positioning: { score: 70, rationale: 'Clear category.' },
      buyer_clarity: { score: 75, rationale: 'Buyer fit is visible.' },
      information_quality: { score: 65, rationale: 'Needs dimensions.' },
      conversion_readiness: { score: 70, rationale: 'Benefits need proof.' },
      discoverability: { score: 80, rationale: 'Core terms are present.' },
    },
    issues: [{
      id: 'ISSUE-1',
      category: 'information_quality',
      severity: 'medium',
      problem: 'Dimensions are missing',
      reason: 'The buyer cannot confirm fit.',
      impact: 'May increase returns.',
      evidence: [{ source: 'description', quote: 'Compact phone stand' }],
    }],
    priority_actions: [{
      rank: 1,
      issue_ids: ['ISSUE-1'],
      action: 'Add exact dimensions.',
      why_now: 'This resolves a buying objection.',
      expected_effect: 'Improve buyer confidence.',
      effort: 'low',
    }],
    limitations: ['No keyword volume data was supplied.'],
  },
  created_at: '2026-08-26T00:00:00Z',
};

async function completeRequiredForm() {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText('Title'), 'Compact phone stand');
  await user.type(screen.getByLabelText('Bullet points'), 'Stable base\nFolds flat');
  await user.type(screen.getByLabelText('Description'), 'A compact phone stand for desks.');
  return user;
}

afterEach(() => {
  cleanup();
  vi.mocked(listingAuditApi.create).mockReset();
});

describe('ListingAuditClient', () => {
  it('submits the strict input contract and renders the report without token metadata', async () => {
    vi.mocked(listingAuditApi.create).mockResolvedValue(report);
    const randomUuid = vi
      .spyOn(globalThis.crypto, 'randomUUID')
      .mockReturnValue('22222222-2222-4222-8222-222222222222');
    render(<ListingAuditClient />);
    const user = await completeRequiredForm();
    await user.type(screen.getByLabelText('Customer reviews (optional)'), 'Works well\nEasy to pack');
    await user.click(screen.getByRole('button', { name: 'Run audit' }));

    await waitFor(() => expect(listingAuditApi.create).toHaveBeenCalledTimes(1));
    expect(listingAuditApi.create).toHaveBeenCalledWith(
      expect.objectContaining({
        marketplace: 'US',
        language: 'en-US',
        listing: {
          title: 'Compact phone stand',
          bullets: ['Stable base', 'Folds flat'],
          description: 'A compact phone stand for desks.',
        },
        customer_reviews: ['Works well', 'Easy to pack'],
      }),
      '22222222-2222-4222-8222-222222222222',
      expect.any(AbortSignal),
    );
    expect(await screen.findByText('72')).toBeInTheDocument();
    expect(screen.getByText(/Add exact dimensions\./)).toBeInTheDocument();
    expect(screen.queryByText(/tokens/i)).not.toBeInTheDocument();
    randomUuid.mockRestore();
  });

  it('rejects an empty bullet list before making a request', async () => {
    render(<ListingAuditClient />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText('Title'), 'Compact phone stand');
    await user.type(screen.getByLabelText('Bullet points'), '   ');
    await user.type(screen.getByLabelText('Description'), 'A compact phone stand.');
    await user.click(screen.getByRole('button', { name: 'Run audit' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Add at least one bullet point.');
    expect(listingAuditApi.create).not.toHaveBeenCalled();
  });

  it('aborts the in-flight request on unmount and ignores its stale result', async () => {
    let signal: AbortSignal | undefined;
    vi.mocked(listingAuditApi.create).mockImplementation((_input, _key, requestSignal) => {
      signal = requestSignal;
      return new Promise(() => undefined);
    });
    const view = render(<ListingAuditClient />);
    const user = await completeRequiredForm();
    fireEvent.submit(screen.getByRole('button', { name: 'Run audit' }).closest('form')!);
    await waitFor(() => expect(signal).toBeDefined());

    view.unmount();
    expect(signal?.aborted).toBe(true);
  });
});
