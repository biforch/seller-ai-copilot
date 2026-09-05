import type { Metadata } from 'next';
import Link from 'next/link';
import { Check, ShieldCheck } from 'lucide-react';

import { PublicPageShell } from '@/components/marketing/PublicPageShell';

export const metadata: Metadata = {
  title: 'Pricing — Listnara',
  description: 'Simple monthly plans for evidence-based Amazon listing audits.',
  alternates: { canonical: '/pricing' },
};

const plans = [
  { name: 'Free', price: '$0', audits: '5 audits / month', description: 'Explore structured listing audits at no cost.', cta: 'Start free', href: '/register', featured: false },
  { name: 'Plus', price: '$9.90', audits: '25 audits / month', description: 'For individual sellers reviewing listings regularly.', cta: 'Coming soon', href: '', featured: true },
  { name: 'Pro', price: '$19.90', audits: '60 audits / month', description: 'For sellers and small teams with a larger catalog.', cta: 'Coming soon', href: '', featured: false },
];

export default function PricingPage() {
  return (
    <PublicPageShell>
      <section className="mx-auto max-w-7xl px-5 pb-12 pt-16 text-center sm:pt-20 lg:px-8">
        <p className="text-sm font-bold uppercase tracking-[0.2em] text-emerald-800">Simple pricing</p>
        <h1 className="mt-4 text-4xl font-semibold tracking-[-0.04em] sm:text-6xl">Choose the audit volume that fits.</h1>
        <p className="mx-auto mt-5 max-w-2xl text-lg leading-8 text-slate-600">Start free, then upgrade when you need more completed audits.</p>
      </section>

      <section className="mx-auto grid max-w-7xl gap-6 px-5 pb-16 md:grid-cols-3 lg:px-8">
        {plans.map((plan) => (
          <div key={plan.name} className={`flex flex-col rounded-[1.75rem] border bg-white p-7 shadow-sm ${plan.featured ? 'border-emerald-700 ring-2 ring-emerald-700/10' : 'border-slate-200'}`}>
            {plan.featured ? <p className="mb-4 w-fit rounded-full bg-emerald-50 px-3 py-1 text-xs font-bold uppercase tracking-wider text-emerald-800">Most popular</p> : null}
            <h2 className="text-2xl font-semibold">{plan.name}</h2>
            <p className="mt-4 text-4xl font-semibold tracking-tight">{plan.price}<span className="text-base font-normal text-slate-500"> / month</span></p>
            <p className="mt-3 font-semibold text-emerald-800">{plan.audits}</p>
            <p className="mt-4 min-h-14 leading-7 text-slate-600">{plan.description}</p>
            <ul className="mt-6 space-y-3 text-sm text-slate-700">
              {['Evidence-based findings', 'Prioritized recommendations', 'Audit report history'].map((feature) => <li key={feature} className="flex gap-2"><Check className="mt-0.5 h-4 w-4 shrink-0 text-emerald-700" />{feature}</li>)}
            </ul>
            {plan.href ? <Link href={plan.href} className={`mt-8 rounded-xl px-5 py-3 text-center font-semibold ${plan.featured ? 'bg-emerald-800 text-white hover:bg-emerald-900' : 'border border-slate-300 bg-white hover:bg-slate-50'}`}>{plan.cta}</Link> : <span className="mt-8 cursor-not-allowed rounded-xl border border-slate-200 bg-slate-100 px-5 py-3 text-center font-semibold text-slate-500" aria-disabled="true">{plan.cta}</span>}
          </div>
        ))}
      </section>

      <section className="border-y border-slate-200 bg-white">
        <div className="mx-auto max-w-4xl px-5 py-12">
          <div className="flex gap-4 rounded-2xl bg-emerald-50 p-6 text-emerald-950"><ShieldCheck className="mt-1 h-6 w-6 shrink-0" /><div><h2 className="font-semibold">Fair-use billing</h2><p className="mt-2 leading-7">An audit counts against your allowance only after it completes successfully. Failed audits do not consume an allowance. Monthly allowances reset each billing cycle and do not roll over.</p></div></div>
          <p className="mt-6 text-sm leading-6 text-slate-500">Subscriptions renew monthly until canceled. Taxes, if applicable, are calculated at checkout by Paddle.</p>
        </div>
      </section>
    </PublicPageShell>
  );
}
