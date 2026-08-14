'use client';

import type { ListingSnapshot } from '@/types';

interface ListingSnapshotPanelProps {
  title: string;
  snapshot?: ListingSnapshot;
  emptyMessage?: string;
}

export function ListingSnapshotPanel({ title, snapshot, emptyMessage }: ListingSnapshotPanelProps) {
  if (emptyMessage) {
    return (
      <section className="rounded-xl border bg-white p-6">
        <h3 className="text-sm font-medium text-gray-500 mb-2">{title}</h3>
        <p className="text-sm text-gray-600">{emptyMessage}</p>
      </section>
    );
  }

  if (!snapshot) {
    return null;
  }

  return (
    <section className="rounded-xl border bg-white p-6 space-y-5">
      <h3 className="text-sm font-medium text-gray-500">{title}</h3>

      <div>
        <p className="text-xs uppercase tracking-wide text-gray-400 mb-1">Title</p>
        <p className="text-base font-semibold text-gray-900 break-words">{snapshot.title}</p>
      </div>

      <div>
        <p className="text-xs uppercase tracking-wide text-gray-400 mb-2">Bullets</p>
        <ul className="space-y-2">
          {snapshot.bullets.map((bullet, index) => (
            <li key={index} className="flex gap-2 text-sm text-gray-800 break-words">
              <span className="text-blue-600 shrink-0">•</span>
              <span>{bullet}</span>
            </li>
          ))}
        </ul>
      </div>

      <div>
        <p className="text-xs uppercase tracking-wide text-gray-400 mb-1">Description</p>
        <p className="text-sm text-gray-800 break-words whitespace-pre-wrap">
          {snapshot.description}
        </p>
      </div>

      <div>
        <p className="text-xs uppercase tracking-wide text-gray-400 mb-2">Backend Keywords</p>
        <div className="flex flex-wrap gap-2">
          {snapshot.backend_keywords.map((keyword) => (
            <span
              key={keyword}
              className="rounded-full bg-blue-50 px-3 py-1 text-sm text-blue-700 break-all"
            >
              {keyword}
            </span>
          ))}
        </div>
      </div>
    </section>
  );
}
