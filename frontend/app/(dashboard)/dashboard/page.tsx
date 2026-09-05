'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { ArrowRight, ClipboardCheck, History, Loader2 } from 'lucide-react';

import { auditsApi } from '@/app/api/audits';
import type { ListingAuditReport } from '@/app/api/listing-audit';

export default function DashboardPage() {
  const router = useRouter();
  const [reports, setReports] = useState<ListingAuditReport[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const controller = new AbortController();
    auditsApi.list(controller.signal).then(setReports).finally(() => setIsLoading(false));
    return () => controller.abort();
  }, []);

  return (
    <div className="mx-auto max-w-6xl px-4 py-10 sm:px-6">
      <div className="grid gap-6 lg:grid-cols-[1.2fr_.8fr]">
        <section className="rounded-3xl bg-slate-950 p-8 text-white sm:p-10">
          <p className="text-xs font-bold uppercase tracking-[0.2em] text-emerald-400">Amazon Listing Audit</p>
          <h1 className="mt-4 max-w-2xl text-4xl font-semibold tracking-tight sm:text-5xl">Know what to fix before you rewrite.</h1>
          <p className="mt-5 max-w-xl leading-7 text-slate-300">Paste your title, bullets, and description. Listnara will find evidence-backed issues and rank the three actions that matter most.</p>
          <button onClick={() => router.push('/audits/new')} className="mt-8 inline-flex items-center gap-2 rounded-xl bg-emerald-500 px-5 py-3 font-semibold text-emerald-950 hover:bg-emerald-400">New Audit <ArrowRight className="h-4 w-4" /></button>
        </section>
        <section className="rounded-3xl border bg-white p-8">
          <ClipboardCheck className="h-8 w-8 text-emerald-800" />
          <p className="mt-6 text-sm font-semibold text-slate-500">Your audit history</p>
          <p className="mt-2 text-5xl font-semibold">{reports.length}</p>
          <p className="mt-3 text-sm leading-6 text-slate-500">Reports preserve the evidence and priorities from each review.</p>
        </section>
      </div>

      <section className="mt-10">
        <div className="mb-4 flex items-center gap-2"><History className="h-5 w-5 text-slate-500" /><h2 className="text-xl font-semibold">Recent audits</h2></div>
        {isLoading ? <div className="flex justify-center py-16"><Loader2 className="h-6 w-6 animate-spin text-emerald-800" /></div> : reports.length === 0 ? <div className="rounded-2xl border border-dashed bg-white px-6 py-14 text-center"><p className="font-semibold text-slate-900">No audits yet</p><p className="mt-2 text-sm text-slate-500">Run your first audit to see prioritized issues here.</p><button onClick={() => router.push('/audits/new')} className="mt-5 text-sm font-semibold text-emerald-800">Audit my listing →</button></div> : <div className="divide-y rounded-2xl border bg-white">{reports.map((report) => { const dimensions = Object.entries(report.result.dimension_scores); const opportunity = dimensions.sort((a, b) => a[1].score - b[1].score)[0][0].replaceAll('_', ' '); const highCount = report.result.issues.filter((issue) => issue.severity === 'high').length; return <button key={report.report_id} onClick={() => router.push(`/audits/${report.report_id}`)} className="grid w-full gap-3 px-5 py-5 text-left hover:bg-slate-50 sm:grid-cols-[90px_1fr_auto] sm:items-center"><div className="text-2xl font-semibold">{report.overall_score}<span className="text-sm text-slate-400">/100</span></div><div><p className="font-semibold capitalize">Focus: {opportunity}</p><p className="mt-1 text-sm text-slate-500">{highCount} high-priority issues · {new Date(report.created_at).toLocaleDateString()}</p></div><ArrowRight className="h-4 w-4 text-slate-400" /></button>; })}</div>}
      </section>
    </div>
  );
}
