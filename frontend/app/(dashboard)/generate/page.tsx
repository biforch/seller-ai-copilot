import { Suspense } from 'react';

import { GeneratePageClient } from './GeneratePageClient';
import { GeneratePageFallback } from './GeneratePageFallback';

export default function GeneratePage() {
  return (
    <Suspense fallback={<GeneratePageFallback />}>
      <GeneratePageClient />
    </Suspense>
  );
}
