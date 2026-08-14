'use client';

import { formatProposalStatusLabel } from '@/lib/listing-proposals';

const STATUS_STYLES: Record<string, string> = {
  reviewing: 'bg-blue-50 text-blue-700 border-blue-200',
  approved: 'bg-green-50 text-green-700 border-green-200',
  rejected: 'bg-red-50 text-red-700 border-red-200',
  superseded: 'bg-gray-100 text-gray-700 border-gray-200',
};

export function ProposalStatusBadge({ status }: { status: string }) {
  const label = formatProposalStatusLabel(status);
  const styles = STATUS_STYLES[status] ?? 'bg-gray-100 text-gray-700 border-gray-200';

  return (
    <span className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium ${styles}`}>
      {label}
    </span>
  );
}
