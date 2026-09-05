'use client';

import { useEffect, useMemo, useState } from 'react';
import { Activity, Loader2, ShieldCheck, Users } from 'lucide-react';

import { analyticsApi, type AnalyticsSummary } from '@/app/api/analytics';
import { ApiClientError } from '@/lib/api-client-error';

const metricLabels = {
  registration_completed: 'Registrations',
  audit_started: 'Audits started',
  audit_completed: 'Audits completed',
  audit_failed: 'Audits failed',
  amazon_connect_started: 'Amazon connects started',
  amazon_connected: 'Amazon accounts connected',
};

export default function AnalyticsPage() {
  const [days, setDays] = useState(30);
  const [summary, setSummary] = useState<AnalyticsSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    const controller = new AbortController();
    void analyticsApi.summary(days, controller.signal)
      .then(setSummary)
      .catch((caught) => {
        if (controller.signal.aborted) return;
        setError(caught instanceof ApiClientError ? caught.message : 'Analytics could not be loaded.');
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [days]);

  const maxDaily = useMemo(() => Math.max(1, ...(summary?.daily.map((day) => day.audit_started) ?? [])), [summary]);

  return (
    <div className="mx-auto max-w-7xl px-4 py-10 sm:px-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div><p className="text-xs font-bold uppercase tracking-[0.2em] text-emerald-800">Private product analytics</p><h1 className="mt-2 text-4xl font-semibold tracking-tight text-slate-950">Activation and audit funnel</h1><p className="mt-3 text-slate-600">Server-confirmed events only. No listing content, email addresses, ASINs, images, or OAuth credentials are stored here.</p></div>
        <select value={days} onChange={(event) => { setLoading(true); setError(''); setDays(Number(event.target.value)); }} className="rounded-xl border bg-white px-4 py-3 text-sm font-semibold"><option value={7}>Last 7 days</option><option value={30}>Last 30 days</option><option value={90}>Last 90 days</option></select>
      </div>

      {error ? <div className="mt-8 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{error}</div> : null}
      {loading ? <div className="flex justify-center py-24"><Loader2 className="h-8 w-8 animate-spin text-emerald-700" /></div> : null}

      {!loading && summary ? <div className="mt-8 space-y-8">
        <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <div className="rounded-2xl border bg-white p-6"><Users className="h-5 w-5 text-emerald-700" /><p className="mt-4 text-3xl font-semibold">{summary.counts.registration_completed}</p><p className="mt-1 text-sm text-slate-500">Registrations</p></div>
          <div className="rounded-2xl border bg-white p-6"><Activity className="h-5 w-5 text-emerald-700" /><p className="mt-4 text-3xl font-semibold">{summary.counts.audit_started}</p><p className="mt-1 text-sm text-slate-500">Audits started</p></div>
          <div className="rounded-2xl border bg-white p-6"><ShieldCheck className="h-5 w-5 text-emerald-700" /><p className="mt-4 text-3xl font-semibold">{summary.counts.audit_completed}</p><p className="mt-1 text-sm text-slate-500">Audits completed</p></div>
          <div className="rounded-2xl bg-slate-950 p-6 text-white"><p className="text-sm text-slate-400">Audit success rate</p><p className="mt-4 text-3xl font-semibold">{summary.audit_success_rate === null ? '—' : `${summary.audit_success_rate}%`}</p><p className="mt-1 text-sm text-slate-400">Completed ÷ finished attempts</p></div>
        </section>

        <section className="rounded-2xl border bg-white p-6 sm:p-8"><h2 className="text-xl font-semibold">Conversion funnel</h2><div className="mt-6 space-y-4">{(['registration_completed', 'audit_started', 'audit_completed', 'amazon_connect_started', 'amazon_connected'] as const).map((key) => { const value = summary.unique_users[key]; const base = Math.max(1, summary.unique_users.registration_completed); return <div key={key}><div className="flex justify-between text-sm"><span className="font-medium text-slate-700">{metricLabels[key]}</span><span className="font-semibold">{value} users</span></div><div className="mt-2 h-3 rounded-full bg-slate-100"><div className="h-3 rounded-full bg-emerald-700" style={{ width: `${Math.min(100, value / base * 100)}%` }} /></div></div>; })}</div></section>

        <section className="rounded-2xl border bg-white p-6 sm:p-8"><h2 className="text-xl font-semibold">Daily audit activity</h2><div className="mt-6 flex h-56 items-end gap-1 overflow-x-auto border-b border-slate-200 pb-1">{summary.daily.map((day) => <div key={day.date} title={`${day.date}: ${day.audit_started} started, ${day.audit_completed} completed`} className="flex min-w-3 flex-1 items-end"><div className="w-full rounded-t bg-emerald-600" style={{ height: `${Math.max(day.audit_started ? 4 : 0, day.audit_started / maxDaily * 100)}%` }} /></div>)}</div><div className="mt-3 flex justify-between text-xs text-slate-400"><span>{summary.daily[0]?.date}</span><span>{summary.daily.at(-1)?.date}</span></div></section>

        <section className="grid gap-4 md:grid-cols-3">{(['audit_failed', 'amazon_connect_started', 'amazon_connected'] as const).map((key) => <div key={key} className="rounded-xl border bg-white p-5"><p className="text-sm text-slate-500">{metricLabels[key]}</p><p className="mt-2 text-2xl font-semibold">{summary.counts[key]}</p></div>)}</section>
      </div> : null}
    </div>
  );
}
