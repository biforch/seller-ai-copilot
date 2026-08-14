'use client';

import type { ListingFieldDiffEntry, ListingProposalDiff } from '@/types';

function formatDiffValue(value: string | string[] | null): string {
  if (value === null) {
    return '—';
  }
  if (Array.isArray(value)) {
    return value.join(' · ');
  }
  return value;
}

function DiffField({ label, entry }: { label: string; entry: ListingFieldDiffEntry }) {
  return (
    <div className="rounded-lg border p-4">
      <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
        <h4 className="text-sm font-medium text-gray-900">{label}</h4>
        <span
          className={`text-xs font-medium ${entry.changed ? 'text-amber-700' : 'text-gray-500'}`}
        >
          {entry.changed ? 'Changed' : 'Unchanged'}
        </span>
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        <div>
          <p className="text-xs uppercase tracking-wide text-gray-400 mb-1">Base</p>
          <p className="text-sm text-gray-700 break-words whitespace-pre-wrap">
            {formatDiffValue(entry.base)}
          </p>
        </div>
        <div>
          <p className="text-xs uppercase tracking-wide text-gray-400 mb-1">Candidate</p>
          <p className="text-sm text-gray-900 break-words whitespace-pre-wrap">
            {formatDiffValue(entry.candidate)}
          </p>
        </div>
      </div>
    </div>
  );
}

export function ProposalDiffPanel({ diff }: { diff: ListingProposalDiff }) {
  return (
    <section className="rounded-xl border bg-white p-6 space-y-4">
      <h3 className="text-sm font-medium text-gray-500">Field Differences</h3>
      <DiffField label="Title" entry={diff.title} />
      <DiffField label="Bullets" entry={diff.bullets} />
      <DiffField label="Description" entry={diff.description} />
      <DiffField label="Backend Keywords" entry={diff.backend_keywords} />
    </section>
  );
}
