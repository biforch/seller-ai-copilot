import type { ReactNode } from 'react';

import { PublicPageShell } from '@/components/marketing/PublicPageShell';

interface PolicyLayoutProps {
  eyebrow: string;
  title: string;
  summary: string;
  children: ReactNode;
}

export function PolicyLayout({ eyebrow, title, summary, children }: PolicyLayoutProps) {
  return (
    <PublicPageShell>
      <section className="border-b border-slate-200 bg-white">
        <div className="mx-auto max-w-4xl px-5 py-16 sm:py-20">
          <p className="text-sm font-bold uppercase tracking-[0.2em] text-emerald-800">{eyebrow}</p>
          <h1 className="mt-4 text-4xl font-semibold tracking-[-0.035em] sm:text-5xl">{title}</h1>
          <p className="mt-5 max-w-3xl text-lg leading-8 text-slate-600">{summary}</p>
          <p className="mt-4 text-sm text-slate-500">Effective August 31, 2026</p>
        </div>
      </section>
      <article className="mx-auto max-w-4xl px-5 py-14 text-[1.02rem] leading-8 text-slate-700 [&_a]:font-semibold [&_a]:text-emerald-800 [&_a]:underline [&_h2]:mb-3 [&_h2]:mt-10 [&_h2]:text-2xl [&_h2]:font-semibold [&_h2]:tracking-tight [&_h2]:text-slate-950 [&_li]:mb-2 [&_p]:mb-5 [&_ul]:mb-6 [&_ul]:list-disc [&_ul]:pl-6">
        {children}
      </article>
    </PublicPageShell>
  );
}

