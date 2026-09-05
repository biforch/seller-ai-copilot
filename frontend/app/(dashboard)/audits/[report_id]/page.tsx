'use client';

import { useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { ArrowLeft, Loader2 } from 'lucide-react';

import { auditsApi } from '@/app/api/audits';
import { AuditReportView } from '@/components/features/AuditReportView';
import type { ListingAuditReport } from '@/app/api/listing-audit';

export default function AuditReportPage() {
  const params = useParams<{ report_id: string }>();
  const router = useRouter();
  const [report, setReport] = useState<ListingAuditReport | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    const controller = new AbortController();
    auditsApi.get(params.report_id, controller.signal).then(setReport).catch((caught) => {
      if (caught instanceof DOMException && caught.name === 'AbortError') return;
      setError('This audit report could not be loaded.');
    });
    return () => controller.abort();
  }, [params.report_id]);

  if (error) return <div className="mx-auto max-w-5xl px-4 py-16 text-center text-red-700">{error}</div>;
  if (!report) return <div className="flex min-h-[50vh] items-center justify-center"><Loader2 className="h-7 w-7 animate-spin text-emerald-800" aria-label="Loading audit" /></div>;

  return <div className="mx-auto max-w-7xl px-4 py-10 sm:px-6"><div className="mb-8 flex flex-wrap items-center justify-between gap-4"><div><button onClick={() => router.push('/dashboard')} className="flex items-center gap-2 text-sm font-semibold text-slate-500 hover:text-slate-900"><ArrowLeft className="h-4 w-4" />Dashboard</button><h1 className="mt-4 text-3xl font-semibold tracking-tight">Listing audit</h1><p className="mt-1 text-sm text-slate-500">{new Date(report.created_at).toLocaleString()}</p></div><button onClick={() => router.push('/audits/new')} className="rounded-xl bg-emerald-800 px-5 py-3 text-sm font-semibold text-white hover:bg-emerald-900">Run another audit</button></div><AuditReportView report={report} /></div>;
}
