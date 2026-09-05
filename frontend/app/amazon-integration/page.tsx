import type { Metadata } from 'next';
import Link from 'next/link';

import { PublicPageShell } from '@/components/marketing/PublicPageShell';

export const metadata: Metadata = {
  title: 'Amazon SP-API Integration | Listnara',
  description: 'Connect eligible Amazon seller accounts to import listing data into Listnara audits.',
  alternates: { canonical: '/amazon-integration' },
};

export default function AmazonIntegrationPage() {
  return (
    <PublicPageShell>
      <main className="mx-auto max-w-4xl px-5 py-16 lg:px-8">
        <p className="text-sm font-bold uppercase tracking-[0.2em] text-emerald-700">Optional integration</p>
        <h1 className="mt-3 text-4xl font-semibold tracking-tight">Amazon SP-API connection</h1>
        <p className="mt-6 text-lg leading-8 text-slate-600">
          Listnara can use an authorized Selling Partner API connection to import a seller&apos;s
          own listing content. Manual ASIN and listing submission remains available while public
          application approval is pending.
        </p>
        <section className="mt-10 rounded-2xl border border-amber-200 bg-amber-50 p-6">
          <h2 className="text-lg font-semibold text-amber-950">Current availability</h2>
          <p className="mt-2 leading-7 text-amber-900">
            The integration is retained but disabled by default until Amazon completes its review.
            We will never ask you to share Seller Central credentials directly.
          </p>
        </section>
        <div className="mt-10 flex flex-wrap gap-3">
          <Link href="/audits/new" className="rounded-xl bg-emerald-800 px-5 py-3 font-semibold text-white hover:bg-emerald-900">Submit a listing manually</Link>
          <Link href="/contact" className="rounded-xl border border-slate-300 bg-white px-5 py-3 font-semibold text-slate-800">Contact support</Link>
        </div>
      </main>
    </PublicPageShell>
  );
}
