import { AlertTriangle, CheckCircle2, ImageIcon, Quote } from 'lucide-react';

import type { ListingAuditReport } from '@/app/api/listing-audit';

const dimensionLabels: Record<string, string> = {
  positioning: 'Positioning',
  buyer_clarity: 'Buyer clarity',
  information_quality: 'Information quality',
  conversion_readiness: 'Conversion readiness',
  discoverability: 'Search coverage',
};

const severityStyles = {
  high: 'bg-red-50 text-red-800 border-red-200',
  medium: 'bg-amber-50 text-amber-800 border-amber-200',
  low: 'bg-slate-50 text-slate-700 border-slate-200',
};

export function AuditReportView({ report }: { report: ListingAuditReport }) {
  const dimensions = Object.entries(report.result.dimension_scores);
  const biggestOpportunity = [...dimensions].sort((a, b) => a[1].score - b[1].score)[0];
  const highCount = report.result.issues.filter((issue) => issue.severity === 'high').length;

  return (
    <div className="space-y-8">
      <section className="grid gap-5 lg:grid-cols-[.75fr_1.25fr]">
        <div className="rounded-2xl bg-slate-950 p-7 text-white">
          <p className="text-xs font-bold uppercase tracking-[0.2em] text-slate-400">Listing health</p>
          <p className="mt-3 text-6xl font-semibold">{report.overall_score}<span className="text-2xl text-slate-500">/100</span></p>
          <div className="mt-8 border-t border-white/10 pt-5">
            <p className="text-sm text-slate-400">Biggest opportunity</p>
            <p className="mt-1 text-xl font-semibold">{dimensionLabels[biggestOpportunity[0]] ?? biggestOpportunity[0]}</p>
            <p className="mt-4 text-sm text-slate-300">{highCount} high-priority {highCount === 1 ? 'issue' : 'issues'}</p>
          </div>
        </div>

        <div className="rounded-2xl border bg-white p-7">
          <p className="text-xs font-bold uppercase tracking-[0.2em] text-emerald-800">Top actions</p>
          <div className="mt-5 space-y-5">
            {report.result.priority_actions.map((action) => (
              <div key={action.rank} className="flex gap-4">
                <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-emerald-800 text-sm font-bold text-white">{action.rank}</span>
                <div><p className="font-semibold text-slate-950">{action.action}</p><p className="mt-1 text-sm leading-6 text-slate-600">{action.why_now}</p><p className="mt-1 text-xs font-semibold uppercase tracking-wide text-slate-400">{action.effort} effort</p></div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {(report.result.image_observations?.length ?? 0) > 0 ? (
        <section>
          <div className="mb-4"><p className="text-xs font-bold uppercase tracking-[0.2em] text-slate-400">Image evidence</p><h2 className="mt-2 text-2xl font-semibold">What buyers can see</h2></div>
          <div className="grid gap-4 md:grid-cols-2">
            {report.result.image_observations?.map((item) => (
              <div key={`${item.image_index}-${item.observation}`} className="rounded-xl border bg-white p-5">
                <p className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-emerald-800"><ImageIcon className="h-4 w-4" />Image {item.image_index}</p>
                <p className="mt-3 font-semibold text-slate-900">{item.observation}</p>
                <p className="mt-2 text-sm leading-6 text-slate-600">{item.implication}</p>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      <section>
        <div className="mb-4"><p className="text-xs font-bold uppercase tracking-[0.2em] text-slate-400">Five dimensions</p><h2 className="mt-2 text-2xl font-semibold">Where the listing stands</h2></div>
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
          {dimensions.map(([name, dimension]) => (
            <div key={name} className="rounded-xl border bg-white p-5"><div className="flex items-center justify-between"><p className="font-semibold">{dimensionLabels[name] ?? name}</p><span className="text-xl font-semibold">{dimension.score}</span></div><div className="mt-3 h-1.5 rounded-full bg-slate-100"><div className="h-1.5 rounded-full bg-emerald-700" style={{ width: `${dimension.score}%` }} /></div><p className="mt-3 text-sm leading-6 text-slate-600">{dimension.rationale}</p></div>
          ))}
        </div>
      </section>

      <section>
        <div className="mb-4"><p className="text-xs font-bold uppercase tracking-[0.2em] text-slate-400">Issues</p><h2 className="mt-2 text-2xl font-semibold">Evidence → reasoning → action</h2></div>
        <div className="space-y-5">
          {report.result.issues.map((issue) => {
            const relatedAction = report.result.priority_actions.find((action) => action.issue_ids.includes(issue.id));

            return <article key={issue.id} className="rounded-2xl border bg-white p-6 sm:p-7">
              <div className="flex flex-wrap items-center gap-3"><span className={`rounded-full border px-3 py-1 text-xs font-bold uppercase ${severityStyles[issue.severity]}`}>{issue.severity} priority</span><span className="text-xs font-semibold text-slate-400">{issue.id} · {dimensionLabels[issue.category] ?? issue.category.replaceAll('_', ' ')}</span></div>
              <h3 className="mt-4 text-xl font-semibold">{issue.problem}</h3>
              <div className="mt-5 grid gap-5 lg:grid-cols-2">
                <div className="rounded-xl bg-slate-50 p-4"><p className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-slate-500"><Quote className="h-3.5 w-3.5" />Evidence</p>{issue.evidence.map((evidence, index) => <div key={`${evidence.source}-${index}`} className="mt-3"><p className="text-xs font-semibold uppercase text-slate-400">{evidence.source.replaceAll('_', ' ')}</p><blockquote className="mt-1 border-l-2 border-slate-300 pl-3 text-sm leading-6 text-slate-700">“{evidence.quote}”</blockquote></div>)}</div>
                <div><p className="text-xs font-bold uppercase tracking-wider text-slate-500">Why it matters</p><p className="mt-2 text-sm leading-6 text-slate-700">{issue.reason} {issue.impact}</p><p className="mt-5 text-xs font-bold uppercase tracking-wider text-emerald-800">What to add</p><p className="mt-2 text-sm leading-6 text-slate-700">{relatedAction?.action ?? issue.impact}</p>{relatedAction ? <><p className="mt-5 text-xs font-bold uppercase tracking-wider text-slate-500">Expected improvement</p><p className="mt-2 text-sm leading-6 text-slate-700">{relatedAction.expected_effect}</p></> : null}</div>
              </div>
            </article>
          })}
        </div>
      </section>

      <section className="rounded-2xl border border-amber-200 bg-amber-50 p-6">
        <div className="flex items-center gap-2 text-amber-900"><AlertTriangle className="h-5 w-5" /><h2 className="font-semibold">What this audit doesn&apos;t know</h2></div>
        {report.result.limitations.length ? <ul className="mt-4 space-y-2 text-sm leading-6 text-amber-950">{report.result.limitations.map((limitation) => <li key={limitation} className="flex gap-2"><CheckCircle2 className="mt-1 h-4 w-4 shrink-0" />{limitation}</li>)}</ul> : <p className="mt-3 text-sm text-amber-950">Recommendations are limited to the listing content and context you supplied.</p>}
      </section>
    </div>
  );
}
