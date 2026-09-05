import type { Metadata } from 'next';
import Link from 'next/link';
import { ArrowRight, CheckCircle2, ClipboardCheck, Search, TriangleAlert } from 'lucide-react';

import { PublicPageShell } from '@/components/marketing/PublicPageShell';

export const metadata: Metadata = {
  title: 'Amazon Listing Audit: Find Content Gaps | Listnara',
  description: 'Audit an Amazon product listing for buyer clarity, missing information, differentiation, conversion readiness, and search coverage.',
  alternates: { canonical: '/amazon-listing-audit' },
  openGraph: {
    url: '/amazon-listing-audit',
    title: 'Amazon Listing Audit: Find Content Gaps | Listnara',
    description: 'Find what an Amazon listing fails to explain before rewriting it.',
  },
};

const checklist = [
  'The title identifies the product and its primary use without unnecessary repetition.',
  'Bullets answer compatibility, size, material, setup, care, and limitation questions where relevant.',
  'The main differentiator appears before secondary construction or feature details.',
  'Important claims are supported by supplied product facts rather than assumptions.',
  'Customer objections found in reviews are answered by the listing when the facts are verified.',
  'Relevant product language is covered naturally without treating keyword presence as ranking readiness.',
];

export default function AmazonListingAuditPage() {
  const faq = [
    { q: 'What is an Amazon listing audit?', a: 'A structured review of listing content that identifies unclear, missing, unsupported, or poorly prioritized information before content is rewritten.' },
    { q: 'Does a listing audit guarantee higher rankings or sales?', a: 'No. Listing quality is only one input. Rank and sales also depend on demand, competition, price, reviews, advertising, availability, and other factors outside a content audit.' },
    { q: 'Is search coverage the same as keyword research?', a: 'No. Search coverage examines language present in supplied content. Keyword research requires external demand and competition data.' },
  ];
  const structuredData = {
    '@context': 'https://schema.org',
    '@type': 'FAQPage',
    mainEntity: faq.map(({ q, a }) => ({ '@type': 'Question', name: q, acceptedAnswer: { '@type': 'Answer', text: a } })),
  };

  return (
    <PublicPageShell>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(structuredData) }} />
      <article>
        <header className="mx-auto grid max-w-7xl gap-12 px-5 py-16 lg:grid-cols-[1.1fr_.9fr] lg:items-center lg:px-8 lg:py-24">
          <div><p className="text-sm font-bold uppercase tracking-[0.2em] text-emerald-800">Amazon listing audit</p><h1 className="mt-4 text-4xl font-semibold tracking-[-0.045em] sm:text-6xl">Find the information gaps before you rewrite.</h1><p className="mt-6 max-w-3xl text-lg leading-8 text-slate-600">A good audit does more than rewrite sentences. It shows what buyers may not understand, the evidence behind each finding, and which changes deserve attention first.</p><div className="mt-8 flex flex-wrap gap-3"><Link href="/sample-report" className="inline-flex items-center gap-2 rounded-xl bg-emerald-800 px-5 py-3 font-semibold text-white">See a sample audit <ArrowRight className="h-4 w-4" /></Link><Link href="/methodology" className="rounded-xl border border-slate-300 bg-white px-5 py-3 font-semibold">Read the methodology</Link></div></div>
          <div className="rounded-[2rem] border border-slate-200 bg-white p-7 shadow-xl shadow-slate-900/5"><Search className="h-7 w-7 text-emerald-700" /><h2 className="mt-5 text-2xl font-semibold">Questions an audit should answer</h2><ul className="mt-5 space-y-4 text-slate-700">{['What will a buyer still need to ask?', 'Which useful fact is buried or missing?', 'Which claim needs verification?', 'What should be fixed first?'].map((item) => <li key={item} className="flex gap-3"><CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-emerald-700" />{item}</li>)}</ul></div>
        </header>

        <section className="border-y border-slate-200 bg-white"><div className="mx-auto max-w-4xl px-5 py-14"><ClipboardCheck className="h-7 w-7 text-emerald-700" /><h2 className="mt-4 text-3xl font-semibold tracking-tight">Amazon listing audit checklist</h2><div className="mt-7 space-y-4">{checklist.map((item, index) => <div key={item} className="flex gap-4 rounded-xl bg-slate-50 p-4"><span className="font-semibold text-emerald-800">0{index + 1}</span><p className="leading-7 text-slate-700">{item}</p></div>)}</div></div></section>

        <section className="mx-auto max-w-4xl px-5 py-14"><div className="rounded-2xl border border-amber-200 bg-amber-50 p-6"><div className="flex gap-4"><TriangleAlert className="mt-1 h-6 w-6 shrink-0 text-amber-700" /><div><h2 className="text-xl font-semibold text-amber-950">Audit before generating copy</h2><p className="mt-2 leading-7 text-amber-900">Rewriting too early can make incomplete information sound more polished without making it more useful. First identify the gap, then verify the product fact, then change the listing.</p></div></div></div><h2 className="mt-14 text-3xl font-semibold tracking-tight">Frequently asked questions</h2><div className="mt-6 divide-y divide-slate-200">{faq.map(({ q, a }) => <section key={q} className="py-5"><h3 className="text-lg font-semibold">{q}</h3><p className="mt-2 leading-7 text-slate-600">{a}</p></section>)}</div></section>
      </article>
    </PublicPageShell>
  );
}
