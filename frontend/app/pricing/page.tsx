import type { Metadata } from 'next';
import Link from 'next/link';
import { Check, ShieldCheck } from 'lucide-react';

import { PublicPageShell } from '@/components/marketing/PublicPageShell';

export const metadata: Metadata = {
  title: 'Pricing — Listnara',
  description: 'Simple monthly plans for evidence-based Amazon listing audits.',
  alternates: { canonical: '/pricing' },
};

const freePlan = {
  name: 'Free',
  price: '$0',
  audits: '5 audits / month',
  description: 'Explore structured listing audits at no cost.',
  cta: 'Start free',
  href: '/register',
};

export default function PricingPage() {
  return (
    <PublicPageShell>
      <section className="mx-auto max-w-7xl px-5 pb-12 pt-16 text-center sm:pt-20 lg:px-8">
        <p className="text-sm font-bold uppercase tracking-[0.2em] text-emerald-800">Simple pricing</p>
        <h1 className="mt-4 text-4xl font-semibold tracking-[-0.04em] sm:text-6xl">Start with the Free plan.</h1>
        <p className="mx-auto mt-5 max-w-2xl text-lg leading-8 text-slate-600">
          Listnara currently offers one available plan. Run evidence-backed listing audits without payment while you
          evaluate the product.
        </p>
      </section>

      <section className="mx-auto max-w-md px-5 pb-16 lg:px-8">
        <div className="flex flex-col rounded-[1.75rem] border border-slate-200 bg-white p-7 shadow-sm">
          <h2 className="text-2xl font-semibold">{freePlan.name}</h2>
          <p className="mt-4 text-4xl font-semibold tracking-tight">
            {freePlan.price}
            <span className="text-base font-normal text-slate-500"> / month</span>
          </p>
          <p className="mt-3 font-semibold text-emerald-800">{freePlan.audits}</p>
          <p className="mt-4 min-h-14 leading-7 text-slate-600">{freePlan.description}</p>
          <ul className="mt-6 space-y-3 text-sm text-slate-700">
            {['Evidence-based findings', 'Prioritized recommendations', 'Audit report history'].map((feature) => (
              <li key={feature} className="flex gap-2">
                <Check className="mt-0.5 h-4 w-4 shrink-0 text-emerald-700" />
                {feature}
              </li>
            ))}
          </ul>
          <Link
            href={freePlan.href}
            className="mt-8 rounded-xl border border-slate-300 bg-white px-5 py-3 text-center font-semibold hover:bg-slate-50"
          >
            {freePlan.cta}
          </Link>
        </div>
      </section>

      <section className="border-y border-slate-200 bg-white">
        <div className="mx-auto max-w-4xl px-5 py-12">
          <div className="flex gap-4 rounded-2xl bg-emerald-50 p-6 text-emerald-950">
            <ShieldCheck className="mt-1 h-6 w-6 shrink-0" />
            <div>
              <h2 className="font-semibold">Fair-use billing</h2>
              <p className="mt-2 leading-7">
                An audit counts against your allowance only after it completes successfully. Failed audits do not consume
                an allowance. Monthly allowances reset each billing cycle and do not roll over.
              </p>
            </div>
          </div>
        </div>
      </section>
    </PublicPageShell>
  );
}
