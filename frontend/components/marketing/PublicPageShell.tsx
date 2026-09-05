import type { ReactNode } from 'react';

import { Footer } from '@/components/common/Footer';
import { Header } from '@/components/common/Header';

export function PublicPageShell({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col bg-[#f6f4ee] text-slate-950">
      <Header showAuth />
      <main className="flex-1">{children}</main>
      <Footer />
    </div>
  );
}
