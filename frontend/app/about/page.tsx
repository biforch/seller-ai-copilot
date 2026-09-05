import type { Metadata } from 'next';
import Link from 'next/link';
import { ArrowRight, ShieldCheck } from 'lucide-react';

import { AmazonIndependenceNotice } from '@/components/marketing/AmazonIndependenceNotice';
import { LegalEntityNotice } from '@/components/marketing/LegalEntityNotice';
import { PublicPageShell } from '@/components/marketing/PublicPageShell';

export const metadata: Metadata = {
  title: 'About Listnara',
  description: 'Listnara is building evidence-backed Amazon listing audits that separate supplied facts, reasoning, actions, and explicit limitations.',
  alternates: { canonical: '/about' },
};

export default function AboutPage() {
  return (
    <PublicPageShell>
      <article className="mx-auto max-w-4xl px-5 py-16 sm:py-20">
        <p className="text-sm font-bold uppercase tracking-[0.2em] text-emerald-800">About Listnara</p>
        <h1 className="mt-4 text-4xl font-semibold tracking-[-0.04em] sm:text-6xl">Know what to fix before you rewrite.</h1>
        <p className="mt-7 text-xl leading-9 text-slate-600">
          Listnara is an independent software product operated by an individual developer for Amazon sellers who want a
          structured review of listing content—not another ungrounded block of generated copy. We help sellers diagnose
          clarity, completeness, and consistency before they decide what to change.
        </p>
        <div className="mt-12 grid gap-6 sm:grid-cols-2"><section className="rounded-2xl border border-slate-200 bg-white p-7"><h2 className="text-xl font-semibold">Why it exists</h2><p className="mt-3 leading-7 text-slate-600">Listing rewrites often begin before anyone identifies what buyers cannot understand. Listnara starts with the diagnosis: evidence, reasoning, priority, and a bounded action.</p></section><section className="rounded-2xl border border-slate-200 bg-white p-7"><h2 className="text-xl font-semibold">What it will not claim</h2><p className="mt-3 leading-7 text-slate-600">An audit cannot guarantee rank, traffic, conversion, or sales. It should make supplied product information clearer while stating where external data or human verification is required.</p></section></div>
        <div className="mt-8 flex gap-4 rounded-2xl bg-emerald-950 p-7 text-white"><ShieldCheck className="mt-1 h-7 w-7 shrink-0 text-emerald-300" /><div><h2 className="text-xl font-semibold">Independent and seller-controlled</h2><p className="mt-2 leading-7 text-emerald-100">Listnara is not affiliated with or endorsed by Amazon. Sellers remain responsible for verifying product facts and approving every listing change.</p></div></div>
        <div className="mt-10">
          <AmazonIndependenceNotice />
        </div>
        <div className="mt-10">
          <LegalEntityNotice variant="about" />
        </div>
        <div className="mt-10 flex flex-wrap gap-3">
          <Link href="/sample-report" className="inline-flex items-center gap-2 rounded-xl bg-emerald-800 px-5 py-3 font-semibold text-white">
            View sample report <ArrowRight className="h-4 w-4" />
          </Link>
          <Link href="/amazon-integration" className="rounded-xl border border-slate-300 bg-white px-5 py-3 font-semibold">
            Amazon integration
          </Link>
          <Link href="/contact" className="rounded-xl border border-slate-300 bg-white px-5 py-3 font-semibold">
            Contact us
          </Link>
        </div>
      </article>
    </PublicPageShell>
  );
}
