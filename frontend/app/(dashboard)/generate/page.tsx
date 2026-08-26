import { Suspense } from 'react';
import { notFound } from 'next/navigation';

import { GeneratePageClient } from './GeneratePageClient';
import { GeneratePageFallback } from './GeneratePageFallback';
import { LEGACY_GENERATION_VISIBLE } from '@/lib/feature-flags';

export default function GeneratePage() {
  if (!LEGACY_GENERATION_VISIBLE) {
    notFound();
  }

  return (
    <Suspense fallback={<GeneratePageFallback />}>
      <GeneratePageClient />
    </Suspense>
  );
}
