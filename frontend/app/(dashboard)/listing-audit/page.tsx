import { notFound } from 'next/navigation';

import ListingAuditClient from './ListingAuditClient';
import { LISTING_AUDIT_INTERNAL_VISIBLE } from '@/lib/feature-flags';

export default function ListingAuditPage() {
  if (!LISTING_AUDIT_INTERNAL_VISIBLE) {
    notFound();
  }

  return <ListingAuditClient />;
}
