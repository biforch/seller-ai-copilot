import type { Metadata } from 'next';
import { Clock3, Mail } from 'lucide-react';

import { PublicPageShell } from '@/components/marketing/PublicPageShell';

export const metadata: Metadata = { title: 'Contact — Listnara', description: 'Contact Listnara support.' };

export default function ContactPage() {
  return (
    <PublicPageShell>
      <section className="mx-auto max-w-5xl px-5 py-16 sm:py-24">
        <p className="text-sm font-bold uppercase tracking-[0.2em] text-emerald-800">Contact</p>
        <h1 className="mt-4 text-4xl font-semibold tracking-[-0.04em] sm:text-5xl">How can we help?</h1>
        <p className="mt-5 max-w-2xl text-lg leading-8 text-slate-600">Questions about your account, listing audits, privacy, billing plans, or Amazon connectivity are welcome.</p>
        <div className="mt-10 grid gap-5 sm:grid-cols-2">
          <a href="mailto:support@listnara.com" className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm transition hover:border-emerald-700"><Mail className="h-6 w-6 text-emerald-700" /><h2 className="mt-5 text-xl font-semibold">Email support</h2><p className="mt-2 text-slate-600">support@listnara.com</p></a>
          <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm"><Clock3 className="h-6 w-6 text-emerald-700" /><h2 className="mt-5 text-xl font-semibold">Response time</h2><p className="mt-2 leading-7 text-slate-600">We aim to respond within two business days, Monday through Friday.</p></div>
        </div>
        <div className="mt-10 rounded-2xl bg-white p-7 text-sm leading-7 text-slate-600"><p className="font-semibold text-slate-950">When contacting support</p><p className="mt-2">Include the email address associated with your Listnara account and a concise description of the issue. Do not email passwords, MFA codes, payment card details, Amazon credentials, or API secrets.</p></div>
      </section>
    </PublicPageShell>
  );
}
