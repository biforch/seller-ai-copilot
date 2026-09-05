import type { Metadata } from 'next';
import Link from 'next/link';
import { ArrowRight, CheckCircle2, ClipboardCheck, Quote, Target } from 'lucide-react';

import { Footer } from '@/components/common/Footer';
import { Header } from '@/components/common/Header';

export const metadata: Metadata = {
  title: 'Amazon Listing Audit Tool | Listnara',
  description: 'Audit your Amazon listing for buyer clarity, information gaps, conversion readiness, and search coverage.',
  alternates: { canonical: '/' },
};

const features = [
  { icon: ClipboardCheck, title: 'Find the problems', copy: 'Audit your title, bullets, and description across five consistent dimensions.' },
  { icon: Quote, title: 'See the evidence', copy: 'Every issue points to the exact part of your listing that triggered it.' },
  { icon: Target, title: 'Know what to fix first', copy: 'Get prioritized actions instead of a wall of generic suggestions.' },
];

export default function Home() {
  const structuredData = {
    '@context': 'https://schema.org',
    '@type': 'SoftwareApplication',
    name: 'Listnara',
    applicationCategory: 'BusinessApplication',
    operatingSystem: 'Web',
    url: 'https://listnara.com',
    description: 'Evidence-backed Amazon listing audits.',
    offers: { '@type': 'Offer', price: '0', priceCurrency: 'USD' },
  };

  return (
    <div className="flex min-h-screen flex-col bg-[#f6f4ee] text-slate-950">
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(structuredData) }} />
      <Header showAuth />
      <main className="flex-1">
        <section className="mx-auto grid max-w-7xl gap-14 px-5 pb-24 pt-16 lg:grid-cols-[1.05fr_.95fr] lg:items-center lg:px-8 lg:pt-24">
          <div>
            <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-emerald-900/10 bg-emerald-900/5 px-4 py-2 text-sm font-semibold text-emerald-900"><ClipboardCheck className="h-4 w-4" /> Amazon Listing Audit</div>
            <h1 className="max-w-3xl text-5xl font-semibold tracking-[-0.045em] sm:text-6xl lg:text-7xl">Find what your listing fails to explain.</h1>
            <p className="mt-7 max-w-2xl text-lg leading-8 text-slate-600 sm:text-xl">Audit your Amazon listing before you rewrite it. See evidence-backed issues, why they matter, and what to fix first.</p>
            <div className="mt-9 flex flex-wrap gap-3">
              <Link href="/register" className="inline-flex items-center gap-2 rounded-xl bg-emerald-800 px-6 py-3.5 font-semibold text-white hover:bg-emerald-900">Audit my listing <ArrowRight className="h-5 w-5" /></Link>
              <Link href="/sample-report" className="rounded-xl border border-slate-300 bg-white px-6 py-3.5 font-semibold text-slate-800 hover:border-emerald-700">View sample report</Link>
            </div>
            <p className="mt-3 text-sm text-slate-500">No credit card required</p>
          </div>
          <div className="rounded-[2rem] border border-slate-200 bg-white p-8 shadow-2xl shadow-slate-900/10">
            <div className="flex items-end justify-between border-b border-slate-100 pb-6">
              <div><p className="text-xs font-bold uppercase tracking-[0.2em] text-slate-500">Listing health</p><p className="mt-2 text-6xl font-semibold">72<span className="text-2xl text-slate-400">/100</span></p></div>
              <div className="rounded-xl bg-amber-50 px-4 py-3 text-right"><p className="text-xs font-semibold uppercase text-amber-700">Biggest opportunity</p><p className="mt-1 font-semibold text-amber-950">Differentiation</p></div>
            </div>
            <div className="py-6"><p className="text-xs font-bold uppercase tracking-wider text-red-700">High priority</p><h2 className="mt-3 text-xl font-semibold">Your main differentiator is buried.</h2><p className="mt-5 rounded-xl bg-slate-50 p-4 text-sm leading-6 text-slate-700">“Designed with double-wall stainless steel construction…”</p><p className="mt-5 text-sm leading-6 text-slate-600">Lead with the primary customer benefit, then support it with the construction detail.</p></div>
            <div className="border-t border-slate-100 pt-5 text-sm font-semibold text-emerald-800">3 high-priority issues found</div>
          </div>
        </section>
        <section className="border-y border-slate-200 bg-white">
          <div className="mx-auto grid max-w-7xl gap-10 px-5 py-20 md:grid-cols-3 lg:px-8">
            {features.map(({ icon: Icon, title, copy }, index) => <div key={title}><div className="mb-5 flex h-11 w-11 items-center justify-center rounded-xl bg-emerald-50 text-emerald-800"><Icon className="h-5 w-5" /></div><p className="text-xs font-bold tracking-[0.2em] text-slate-400">0{index + 1}</p><h2 className="mt-2 text-xl font-semibold">{title}</h2><p className="mt-3 leading-7 text-slate-600">{copy}</p></div>)}
          </div>
        </section>
        <section className="mx-auto max-w-4xl px-5 py-20 text-center"><CheckCircle2 className="mx-auto h-8 w-8 text-emerald-700" /><h2 className="mt-5 text-3xl font-semibold">A decision tool, not another listing writer.</h2><p className="mx-auto mt-4 max-w-2xl leading-7 text-slate-600">Listnara separates evidence from analysis and states what it cannot know from the listing alone.</p></section>
        <section className="bg-emerald-950 text-white"><div className="mx-auto flex max-w-7xl flex-col gap-8 px-5 py-16 sm:flex-row sm:items-center sm:justify-between lg:px-8"><div><p className="text-sm font-bold uppercase tracking-[0.2em] text-emerald-300">Start free</p><h2 className="mt-3 text-3xl font-semibold">Five completed audits each month.</h2><p className="mt-3 text-emerald-100">No credit card required. Paid plans remain unavailable until billing approval is complete.</p></div><div className="flex gap-3"><Link href="/pricing" className="rounded-xl border border-white/30 px-5 py-3 font-semibold">View pricing</Link><Link href="/register" className="rounded-xl bg-white px-5 py-3 font-semibold text-emerald-950">Create account</Link></div></div></section>
      </main>
      <Footer />
    </div>
  );
}
