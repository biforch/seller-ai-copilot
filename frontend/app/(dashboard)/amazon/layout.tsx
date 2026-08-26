import { notFound } from 'next/navigation';

import { AMAZON_WORKSPACE_VISIBLE } from '@/lib/feature-flags';

export default function AmazonWorkspaceLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  if (!AMAZON_WORKSPACE_VISIBLE) {
    notFound();
  }

  return children;
}
