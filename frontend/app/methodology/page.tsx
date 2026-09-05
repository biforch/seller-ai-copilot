import type { Metadata } from 'next';
import Link from 'next/link';
import { ArrowRight, CircleHelp, FileSearch, ListChecks, ShieldCheck } from 'lucide-react';

import { PublicPageShell } from '@/components/marketing/PublicPageShell';

export const metadata: Metadata = {
  title: 'Amazon Listing Audit Methodology | Listnara',
  description: 'Learn how Listnara separates supplied evidence, bounded reasoning, prioritized actions, and explicit limitations in an Amazon listing audit.',
  alternates: { canonical: '/methodology' },
  openGraph: {
    url: '/methodology',
    title: 'Amazon Listing Audit Methodology | Listnara',
    description: 'How Listnara turns listing evidence into bounded, prioritized recommendations.',
  },
};

const dimensions = [
  ['Buyer clarity', 'Can a shopper quickly understand what the product is, who it is for, and the primary benefit?'],
  ['Information completeness', 'Are important dimensions, compatibility details, materials, use conditions, or limitations missing?'],
  ['Differentiation', 'Does the listing explain why this offer is meaningfully different without inventing unsupported claims?'],
  ['Conversion readiness', 'Does the supplied content resolve likely objections and make the next decision easier?'],
  ['Search coverage', 'Does the listing text cover relevant product language supplied by the seller? This is not keyword-volume or ranking analysis.'],
];

export default function MethodologyPage() {
  return (
    <PublicPageShell>
      <article>
        <header className="border-b border-slate-200 bg-white">
          <div className="mx-auto max-w-4xl px-5 py-16 sm:py-20">
            <p className="text-sm font-bold uppercase tracking-[0.2em] text-emerald-800">Methodology</p>
            <h1 className="mt-4 text-4xl font-semibold tracking-[-0.04em] sm:text-6xl">Evidence first. Recommendations second.</h1>
            <p className="mt-6 max-w-3xl text-lg leading-8 text-slate-600">Listnara audits only the information supplied to it. Each finding should connect a cited fact or customer signal to bounded reasoning and a practical next step.</p>
          </div>
        </header>

        <section className="mx-auto max-w-4xl px-5 py-14">
          <h2 className="text-3xl font-semibold tracking-tight">The audit chain</h2>
          <div className="mt-8 grid gap-5 md:grid-cols-3">
            {[
              [FileSearch, '1. Evidence', 'A specific title phrase, bullet, product fact, competitor claim, or supplied review.'],
              [CircleHelp, '2. Reasoning', 'A limited explanation of the buyer question or information gap that evidence supports.'],
              [ListChecks, '3. Action', 'A prioritized recommendation describing what to add, clarify, verify, or move.'],
            ].map(([Icon, title, copy]) => {
              const ItemIcon = Icon as typeof FileSearch;
              return <div key={String(title)} className="rounded-2xl border border-slate-200 bg-white p-6"><ItemIcon className="h-6 w-6 text-emerald-700" /><h3 className="mt-4 text-lg font-semibold">{String(title)}</h3><p className="mt-2 leading-7 text-slate-600">{String(copy)}</p></div>;
            })}
          </div>
        </section>

        <section className="border-y border-slate-200 bg-white">
          <div className="mx-auto max-w-4xl px-5 py-14">
            <h2 className="text-3xl font-semibold tracking-tight">What the score covers</h2>
            <div className="mt-7 divide-y divide-slate-200">
              {dimensions.map(([title, copy]) => <div key={title} className="grid gap-2 py-5 sm:grid-cols-[13rem_1fr]"><h3 className="font-semibold text-slate-950">{title}</h3><p className="leading-7 text-slate-600">{copy}</p></div>)}
            </div>
            <p className="mt-6 rounded-2xl bg-amber-50 p-5 leading-7 text-amber-950">The score is a structured diagnostic, not a forecast of sales, conversion rate, organic rank, or advertising performance.</p>
          </div>
        </section>

        <section className="mx-auto max-w-4xl px-5 py-14">
          <div className="flex gap-4 rounded-2xl bg-emerald-950 p-7 text-white"><ShieldCheck className="mt-1 h-7 w-7 shrink-0 text-emerald-300" /><div><h2 className="text-2xl font-semibold">What the audit does not know</h2><p className="mt-3 leading-7 text-emerald-100">Unless supplied or verified, Listnara does not know actual dimensions, performance, certifications, keyword demand, search rank, conversion data, inventory, price competitiveness, or whether a product claim is legally supportable. Missing information should be verified—not invented.</p></div></div>
          <div className="mt-10 flex flex-wrap gap-3"><Link href="/sample-report" className="inline-flex items-center gap-2 rounded-xl bg-emerald-800 px-5 py-3 font-semibold text-white">View sample report <ArrowRight className="h-4 w-4" /></Link><Link href="/amazon-listing-audit" className="rounded-xl border border-slate-300 bg-white px-5 py-3 font-semibold">How listing audits work</Link></div>
        </section>
      </article>
    </PublicPageShell>
  );
}
