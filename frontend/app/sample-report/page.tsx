import type { Metadata } from 'next';
import Link from 'next/link';
import { ArrowRight } from 'lucide-react';

import { Footer } from '@/components/common/Footer';
import { Header } from '@/components/common/Header';
import { AuditReportView } from '@/components/features/AuditReportView';
import { sampleAuditReport } from '@/lib/sample-audit-report';

export const metadata: Metadata = {
  title: 'Sample Amazon Listing Audit Report | Listnara',
  description: 'See a complete evidence-backed Amazon listing audit with prioritized issues, cited evidence, actions, and explicit limitations.',
  alternates: { canonical: '/sample-report' },
  openGraph: { url: '/sample-report', title: 'Sample Amazon Listing Audit Report | Listnara', description: 'See what a Listnara evidence-backed audit looks like before creating an account.' },
};

export default function SampleReportPage() {
  return <div className="min-h-screen bg-[#f6f4ee] text-slate-950"><Header showAuth /><main className="mx-auto max-w-7xl px-5 py-12 lg:px-8"><div className="mb-10 flex flex-col justify-between gap-6 border-b border-slate-200 pb-8 sm:flex-row sm:items-end"><div><p className="inline-flex rounded-full bg-emerald-100 px-3 py-1 text-xs font-bold tracking-[0.18em] text-emerald-900">SAMPLE REPORT</p><h1 className="mt-4 text-4xl font-semibold tracking-tight sm:text-5xl">Evidence-backed Amazon listing audit</h1><p className="mt-4 max-w-3xl leading-7 text-slate-600">This fictional phone-stand example shows how Listnara connects each issue to supplied evidence, explains the consequence, and recommends a bounded next step.</p></div><Link href="/register" className="inline-flex shrink-0 items-center justify-center gap-2 rounded-xl bg-emerald-800 px-5 py-3 font-semibold text-white hover:bg-emerald-900">Audit my listing <ArrowRight className="h-4 w-4" /></Link></div><AuditReportView report={sampleAuditReport} /><section className="mt-12 rounded-2xl bg-emerald-950 px-6 py-10 text-center text-white sm:px-10"><h2 className="text-3xl font-semibold">See what your listing fails to explain.</h2><p className="mx-auto mt-3 max-w-2xl text-emerald-100">Start with five completed audits each month. No credit card required.</p><Link href="/register" className="mt-6 inline-flex items-center gap-2 rounded-xl bg-white px-5 py-3 font-semibold text-emerald-950">Start free <ArrowRight className="h-4 w-4" /></Link></section></main><Footer /></div>;
}
