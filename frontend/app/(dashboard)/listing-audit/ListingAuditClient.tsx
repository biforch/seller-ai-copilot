'use client';

import { FormEvent, useEffect, useRef, useState } from 'react';
import { AlertTriangle, CheckCircle2, Loader2 } from 'lucide-react';

import {
  listingAuditApi,
  type ListingAuditInput,
  type ListingAuditMarketplace,
  type ListingAuditReport,
} from '@/app/api/listing-audit';
import { isAbortError } from '@/lib/abort-error';
import { ApiClientError } from '@/lib/api-client-error';
import { LatestRequestGate } from '@/lib/latest-request';

const MARKETPLACES: ListingAuditMarketplace[] = [
  'US', 'CA', 'MX', 'UK', 'DE', 'FR', 'IT', 'ES', 'JP', 'AU',
];

const DIMENSION_LABELS = {
  positioning: 'Positioning',
  buyer_clarity: 'Buyer clarity',
  information_quality: 'Information quality',
  conversion_readiness: 'Conversion readiness',
  discoverability: 'Discoverability',
} as const;

function splitLines(value: string, max: number): string[] {
  return value
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .slice(0, max);
}

function newIdempotencyKey(): string {
  if (!globalThis.crypto?.randomUUID) {
    throw new Error('Secure request identifiers are unavailable.');
  }
  return globalThis.crypto.randomUUID();
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiClientError) {
    return error.message;
  }
  return 'The audit could not be completed. Please try again.';
}

export default function ListingAuditClient() {
  const gateRef = useRef(new LatestRequestGate());
  const [title, setTitle] = useState('');
  const [bullets, setBullets] = useState('');
  const [description, setDescription] = useState('');
  const [marketplace, setMarketplace] = useState<ListingAuditMarketplace>('US');
  const [language, setLanguage] = useState('en-US');
  const [competitorListing, setCompetitorListing] = useState('');
  const [customerReviews, setCustomerReviews] = useState('');
  const [report, setReport] = useState<ListingAuditReport | null>(null);
  const [error, setError] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    const gate = gateRef.current;
    return () => gate.invalidate();
  }, []);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const parsedBullets = splitLines(bullets, 5);
    if (parsedBullets.length === 0) {
      setError('Add at least one bullet point.');
      return;
    }

    const lease = gateRef.current.begin();
    setIsSubmitting(true);
    setError('');
    setReport(null);

    const input: ListingAuditInput = {
      marketplace,
      language: language.trim(),
      listing: {
        title: title.trim(),
        bullets: parsedBullets,
        description: description.trim(),
      },
      competitor_listing: competitorListing.trim() || null,
      customer_reviews: splitLines(customerReviews, 30),
    };

    try {
      const result = await listingAuditApi.create(input, newIdempotencyKey(), lease.signal);
      if (lease.isCurrent()) {
        setReport(result);
      }
    } catch (caught) {
      if (lease.isCurrent() && !isAbortError(caught)) {
        setError(errorMessage(caught));
      }
    } finally {
      if (lease.isCurrent()) {
        setIsSubmitting(false);
      }
    }
  };

  return (
    <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6 lg:px-8">
      <div className="mb-8">
        <p className="text-sm font-semibold uppercase tracking-wide text-blue-600">Internal preview</p>
        <h1 className="mt-1 text-3xl font-bold text-slate-900">Listing Audit</h1>
        <p className="mt-2 max-w-3xl text-slate-600">
          Review listing clarity, positioning, discoverability, and conversion readiness. Submitted
          text is processed by the configured AI provider; do not enter credentials or private data.
        </p>
      </div>

      <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
        <form onSubmit={submit} className="space-y-5 rounded-xl border bg-white p-6 shadow-sm">
          <div>
            <label htmlFor="audit-title" className="mb-1 block text-sm font-medium text-slate-700">Title</label>
            <input id="audit-title" required maxLength={300} value={title} onChange={(event) => setTitle(event.target.value)} className="w-full rounded-lg border px-3 py-2" />
          </div>
          <div>
            <label htmlFor="audit-bullets" className="mb-1 block text-sm font-medium text-slate-700">Bullet points</label>
            <textarea id="audit-bullets" required rows={5} value={bullets} onChange={(event) => setBullets(event.target.value)} className="w-full rounded-lg border px-3 py-2" placeholder="One bullet per line (up to 5)" />
          </div>
          <div>
            <label htmlFor="audit-description" className="mb-1 block text-sm font-medium text-slate-700">Description</label>
            <textarea id="audit-description" required maxLength={5000} rows={6} value={description} onChange={(event) => setDescription(event.target.value)} className="w-full rounded-lg border px-3 py-2" />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label htmlFor="audit-marketplace" className="mb-1 block text-sm font-medium text-slate-700">Marketplace</label>
              <select id="audit-marketplace" value={marketplace} onChange={(event) => setMarketplace(event.target.value as ListingAuditMarketplace)} className="w-full rounded-lg border px-3 py-2">
                {MARKETPLACES.map((value) => <option key={value}>{value}</option>)}
              </select>
            </div>
            <div>
              <label htmlFor="audit-language" className="mb-1 block text-sm font-medium text-slate-700">Language</label>
              <input id="audit-language" required maxLength={20} value={language} onChange={(event) => setLanguage(event.target.value)} className="w-full rounded-lg border px-3 py-2" />
            </div>
          </div>
          <div>
            <label htmlFor="audit-competitor" className="mb-1 block text-sm font-medium text-slate-700">Competitor listing (optional)</label>
            <textarea id="audit-competitor" maxLength={8000} rows={4} value={competitorListing} onChange={(event) => setCompetitorListing(event.target.value)} className="w-full rounded-lg border px-3 py-2" />
          </div>
          <div>
            <label htmlFor="audit-reviews" className="mb-1 block text-sm font-medium text-slate-700">Customer reviews (optional)</label>
            <textarea id="audit-reviews" rows={4} value={customerReviews} onChange={(event) => setCustomerReviews(event.target.value)} className="w-full rounded-lg border px-3 py-2" placeholder="One review per line (up to 30)" />
          </div>
          {error ? <div role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</div> : null}
          <button type="submit" disabled={isSubmitting} className="flex w-full items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 py-3 font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60">
            {isSubmitting ? <Loader2 className="h-5 w-5 animate-spin" aria-hidden="true" /> : null}
            {isSubmitting ? 'Auditing…' : 'Run audit'}
          </button>
        </form>

        <section aria-live="polite" className="min-h-96 rounded-xl border bg-white p-6 shadow-sm">
          {!report ? (
            <div className="flex h-full min-h-80 items-center justify-center text-center text-slate-500">
              {isSubmitting ? 'Evaluating the listing…' : 'Your structured audit will appear here.'}
            </div>
          ) : (
            <div className="space-y-7">
              <div className="flex items-center justify-between">
                <div><p className="text-sm text-slate-500">Overall score</p><p className="text-4xl font-bold text-slate-900">{report.overall_score}</p></div>
                <CheckCircle2 className="h-9 w-9 text-emerald-600" aria-hidden="true" />
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                {Object.entries(report.result.dimension_scores).map(([name, dimension]) => (
                  <div key={name} className="rounded-lg border p-3"><div className="flex justify-between gap-3 font-medium"><span>{DIMENSION_LABELS[name as keyof typeof DIMENSION_LABELS]}</span><span>{dimension.score}</span></div><p className="mt-1 text-sm text-slate-600">{dimension.rationale}</p></div>
                ))}
              </div>
              <div><h2 className="mb-3 text-xl font-semibold">Priority actions</h2><ol className="space-y-3">{report.result.priority_actions.map((action) => <li key={action.rank} className="rounded-lg bg-blue-50 p-4"><p className="font-semibold">{action.rank}. {action.action}</p><p className="mt-1 text-sm text-slate-700">{action.why_now}</p><p className="mt-1 text-sm text-slate-600">Expected: {action.expected_effect}</p></li>)}</ol></div>
              <div><h2 className="mb-3 text-xl font-semibold">Issues</h2><div className="space-y-3">{report.result.issues.map((issue) => <article key={issue.id} className="rounded-lg border p-4"><div className="flex items-center gap-2"><AlertTriangle className="h-4 w-4 text-amber-600" aria-hidden="true" /><h3 className="font-semibold">{issue.problem}</h3><span className="ml-auto text-xs uppercase text-slate-500">{issue.severity}</span></div><p className="mt-2 text-sm text-slate-700">{issue.reason}</p><ul className="mt-2 space-y-1 text-sm text-slate-600">{issue.evidence.map((evidence, index) => <li key={`${issue.id}-${index}`}>&ldquo;{evidence.quote}&rdquo; <span className="text-slate-400">({evidence.source})</span></li>)}</ul></article>)}</div></div>
              {report.result.limitations.length ? <div className="rounded-lg bg-amber-50 p-4"><h2 className="font-semibold text-amber-900">Limitations</h2><ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-amber-900">{report.result.limitations.map((limitation) => <li key={limitation}>{limitation}</li>)}</ul></div> : null}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
