'use client';

import { FormEvent, useState } from 'react';
import { useRouter } from 'next/navigation';
import { ArrowLeft, ClipboardPaste, Link2, Loader2, Plus, ShieldCheck, Store, X } from 'lucide-react';

import { auditsApi } from '@/app/api/audits';
import { ApiClientError } from '@/lib/api-client-error';
import { parseAmazonReference } from '@/lib/amazon-asin';

type SpecificationRow = { id: number; name: string; value: string };
type Marketplace = 'US' | 'CA' | 'MX' | 'UK' | 'DE' | 'FR' | 'IT' | 'ES' | 'JP' | 'AU';

export default function NewAuditPage() {
  const router = useRouter();
  const [title, setTitle] = useState('');
  const [bullets, setBullets] = useState(['']);
  const [description, setDescription] = useState('');
  const [specifications, setSpecifications] = useState<SpecificationRow[]>([{ id: 1, name: '', value: '' }]);
  const [competitor, setCompetitor] = useState('');
  const [reviews, setReviews] = useState('');
  const [showContext, setShowContext] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [amazonReference, setAmazonReference] = useState('');
  const [referenceAsin, setReferenceAsin] = useState('');
  const [marketplace, setMarketplace] = useState<Marketplace>('US');
  const [mode, setMode] = useState<'choose' | 'asin' | 'manual'>('choose');

  const importByReference = (event: FormEvent) => {
    event.preventDefault();
    setError('');
    const parsed = parseAmazonReference(amazonReference);
    if (!parsed) {
      setError('Enter a valid 10-character ASIN or a supported Amazon product URL.');
      return;
    }
    const nextMarketplace = (parsed.marketplaceCode ?? marketplace) as Marketplace;
    setReferenceAsin(parsed.asin);
    setMarketplace(nextMarketplace);
    setSpecifications((current) => {
      const withoutAsin = current.filter((row) => row.name.trim().toLowerCase() !== 'asin');
      const populated = withoutAsin.filter((row) => row.name.trim() || row.value.trim());
      return [{ id: Math.max(0, ...current.map((row) => row.id)) + 1, name: 'ASIN', value: parsed.asin }, ...populated];
    });
    setMode('manual');
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError('');
    const cleanedBullets = bullets.map((bullet) => bullet.trim()).filter(Boolean);
    if (!title.trim() || !description.trim() || cleanedBullets.length === 0) {
      setError('Add a title, at least one bullet, and a description.');
      return;
    }
    const incompleteSpecification = specifications.some((item) => Boolean(item.name.trim()) !== Boolean(item.value.trim()));
    const specificationNames = specifications.map((item) => item.name.trim()).filter(Boolean);
    if (incompleteSpecification) {
      setError('Complete both fields for each product specification, or remove the unfinished row.');
      return;
    }
    if (new Set(specificationNames.map((name) => name.toLowerCase())).size !== specificationNames.length) {
      setError('Each product specification must have a unique name.');
      return;
    }
    const productFacts = specifications
      .map((item) => [item.name.trim(), item.value.trim()] as const)
      .filter(([name, value]) => name && value);
    const contextLines = productFacts.map(([name, value]) => `${name}: ${value}`);
    const auditDescription = contextLines.length
      ? `${description.trim()}\n\nVerified product context supplied by the seller:\n${contextLines.join('\n')}`
      : description.trim();
    if (auditDescription.length > 5000) {
      setError('The description and product facts must be 5,000 characters or fewer in total.');
      return;
    }
    setIsSubmitting(true);
    try {
      const report = await auditsApi.create({
        marketplace,
        language: 'en-US',
        listing: { title: title.trim(), bullets: cleanedBullets, description: auditDescription },
        competitor_listing: competitor.trim() || null,
        customer_reviews: reviews.split('\n').map((review) => review.trim()).filter(Boolean),
      });
      router.push(`/audits/${report.report_id}`);
    } catch (caught) {
      setError(caught instanceof ApiClientError ? caught.message : 'The audit could not be completed. Please try again.');
    } finally {
      setIsSubmitting(false);
    }
  };

  if (mode === 'choose') {
    return (
      <div className="mx-auto max-w-4xl px-4 py-10 sm:px-6">
        <button onClick={() => router.push('/dashboard')} className="mb-7 flex items-center gap-2 text-sm font-semibold text-slate-500 hover:text-slate-900"><ArrowLeft className="h-4 w-4" />Dashboard</button>
        <div className="mb-8"><p className="text-xs font-bold uppercase tracking-[0.2em] text-emerald-800">New audit</p><h1 className="mt-2 text-4xl font-semibold tracking-tight text-slate-950">Choose your listing source</h1><p className="mt-3 max-w-2xl leading-7 text-slate-600">Import a live listing from Seller Central, or paste any draft or competitor listing manually.</p></div>
        <div className="grid gap-5 md:grid-cols-3">
          <button onClick={() => router.push('/amazon')} className="group rounded-2xl border-2 border-emerald-700 bg-emerald-50/40 p-7 text-left transition hover:bg-emerald-50">
            <Store className="h-8 w-8 text-emerald-800" /><p className="mt-5 text-xl font-semibold text-slate-950">Import from Amazon</p><p className="mt-2 text-sm leading-6 text-slate-600">Connect Seller Central, choose a live listing, and audit it without copying and pasting.</p><p className="mt-5 text-sm font-semibold text-emerald-800">Read-only access →</p>
          </button>
          <button onClick={() => { setError(''); setMode('asin'); }} className="rounded-2xl border bg-white p-7 text-left transition hover:border-emerald-500 hover:bg-emerald-50/40">
            <Link2 className="h-8 w-8 text-emerald-800" /><p className="mt-5 text-xl font-semibold text-slate-950">Start with ASIN or URL</p><p className="mt-2 text-sm leading-6 text-slate-600">Capture the product reference and marketplace, then add listing content without connecting Amazon.</p><p className="mt-5 text-sm font-semibold text-emerald-800">Enter a reference →</p>
          </button>
          <button onClick={() => setMode('manual')} className="rounded-2xl border bg-white p-7 text-left transition hover:border-slate-400 hover:bg-slate-50">
            <ClipboardPaste className="h-8 w-8 text-slate-700" /><p className="mt-5 text-xl font-semibold text-slate-950">Paste manually</p><p className="mt-2 text-sm leading-6 text-slate-600">Audit a draft, competitor listing, or product that is not connected to your account.</p><p className="mt-5 text-sm font-semibold text-slate-700">Continue manually →</p>
          </button>
        </div>
        <div className="mt-6 rounded-xl border border-slate-200 bg-white px-5 py-4 text-sm text-slate-600"><ShieldCheck className="mr-2 inline h-4 w-4 text-emerald-700" />Listnara imports listing content for analysis and cannot modify your Amazon listings.</div>
      </div>
    );
  }

  if (mode === 'asin') {
    return (
      <div className="mx-auto max-w-3xl px-4 py-10 sm:px-6">
        <button onClick={() => { setError(''); setMode('choose'); }} className="mb-7 flex items-center gap-2 text-sm font-semibold text-slate-500 hover:text-slate-900"><ArrowLeft className="h-4 w-4" />Choose another source</button>
        <div className="mb-8"><p className="text-xs font-bold uppercase tracking-[0.2em] text-emerald-800">Start with a reference</p><h1 className="mt-2 text-4xl font-semibold tracking-tight text-slate-950">Paste an ASIN or Amazon link</h1><p className="mt-3 max-w-2xl leading-7 text-slate-600">We&apos;ll capture the ASIN and marketplace. You can continue immediately with seller-supplied content while direct Amazon import is awaiting approval.</p></div>
        <form onSubmit={importByReference} className="rounded-2xl border bg-white p-6 sm:p-8">
          <label className="block text-sm font-semibold text-slate-800">ASIN or product URL</label>
          <input autoFocus value={amazonReference} onChange={(event) => setAmazonReference(event.target.value)} className="mt-2 w-full rounded-xl border border-slate-300 px-4 py-3.5 focus:border-emerald-700 focus:outline-none focus:ring-2 focus:ring-emerald-100" placeholder="B0XXXXXXXXX or https://www.amazon.com/dp/B0XXXXXXXXX" />
          <p className="mt-3 text-sm leading-6 text-slate-500">Listnara does not scrape public Amazon pages. The reference is retained as verified product context; you&apos;ll add the title, bullets, description, and known facts on the next step.</p>
          {error ? <div className="mt-5 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div> : null}
          <button className="mt-6 inline-flex items-center justify-center gap-2 rounded-xl bg-emerald-800 px-6 py-3.5 font-semibold text-white hover:bg-emerald-900"><ClipboardPaste className="h-4 w-4" />Continue with listing details</button>
        </form>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-4xl px-4 py-10 sm:px-6">
      <button onClick={() => setMode('choose')} className="mb-7 flex items-center gap-2 text-sm font-semibold text-slate-500 hover:text-slate-900"><ArrowLeft className="h-4 w-4" />Choose another source</button>
      <div className="mb-8"><p className="text-xs font-bold uppercase tracking-[0.2em] text-emerald-800">New audit</p><h1 className="mt-2 text-4xl font-semibold tracking-tight text-slate-950">Paste your Amazon listing</h1><p className="mt-3 max-w-2xl leading-7 text-slate-600">We&apos;ll identify the most important content risks, quote the evidence, and prioritize what to fix first.</p></div>

      {referenceAsin ? <div className="mb-6 flex flex-col justify-between gap-3 rounded-xl border border-emerald-200 bg-emerald-50 px-5 py-4 text-sm sm:flex-row sm:items-center"><div><span className="font-semibold text-emerald-950">Product reference saved:</span> <span className="font-mono text-emerald-900">{referenceAsin}</span> · {marketplace}</div><button type="button" onClick={() => { setReferenceAsin(''); setSpecifications((current) => current.filter((row) => row.name.trim().toLowerCase() !== 'asin')); }} className="text-left font-semibold text-emerald-800 hover:text-emerald-950">Remove reference</button></div> : null}

      <form onSubmit={submit} className="space-y-6">
        <section className="rounded-2xl border bg-white p-6 sm:p-8">
          <label className="block text-sm font-semibold text-slate-800">Amazon marketplace</label>
          <select value={marketplace} onChange={(event) => setMarketplace(event.target.value as Marketplace)} className="mt-2 w-full rounded-xl border border-slate-300 bg-white px-4 py-3 focus:border-emerald-700 focus:outline-none focus:ring-2 focus:ring-emerald-100 sm:w-64">
            <option value="US">United States</option><option value="CA">Canada</option><option value="MX">Mexico</option><option value="UK">United Kingdom</option><option value="DE">Germany</option><option value="FR">France</option><option value="IT">Italy</option><option value="ES">Spain</option><option value="JP">Japan</option><option value="AU">Australia</option>
          </select>
          <label className="mt-6 block text-sm font-semibold text-slate-800">Product title</label>
          <textarea value={title} onChange={(event) => setTitle(event.target.value)} maxLength={300} rows={3} className="mt-2 w-full rounded-xl border border-slate-300 px-4 py-3 focus:border-emerald-700 focus:outline-none focus:ring-2 focus:ring-emerald-100" placeholder="Paste the exact Amazon title" />
          <div className="mt-6 flex items-center justify-between"><label className="text-sm font-semibold text-slate-800">Bullet points</label><span className="text-xs text-slate-400">Up to 5</span></div>
          <div className="mt-2 space-y-3">{bullets.map((bullet, index) => <div key={index} className="flex gap-2"><span className="mt-3 text-sm font-semibold text-slate-400">{index + 1}</span><textarea value={bullet} onChange={(event) => setBullets((current) => current.map((item, itemIndex) => itemIndex === index ? event.target.value : item))} maxLength={1000} rows={3} className="w-full rounded-xl border border-slate-300 px-4 py-3 focus:border-emerald-700 focus:outline-none focus:ring-2 focus:ring-emerald-100" placeholder="Paste one bullet point" />{bullets.length > 1 ? <button type="button" onClick={() => setBullets((current) => current.filter((_, itemIndex) => itemIndex !== index))} className="mt-2 self-start rounded-lg p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-700" aria-label={`Remove bullet ${index + 1}`}><X className="h-4 w-4" /></button> : null}</div>)}</div>
          {bullets.length < 5 ? <button type="button" onClick={() => setBullets((current) => [...current, ''])} className="mt-3 inline-flex items-center gap-2 text-sm font-semibold text-emerald-800"><Plus className="h-4 w-4" />Add bullet</button> : null}
          <label className="mt-6 block text-sm font-semibold text-slate-800">Description</label>
          <textarea value={description} onChange={(event) => setDescription(event.target.value)} maxLength={5000} rows={9} className="mt-2 w-full rounded-xl border border-slate-300 px-4 py-3 focus:border-emerald-700 focus:outline-none focus:ring-2 focus:ring-emerald-100" placeholder="Paste the product description" />
        </section>

        <section className="rounded-2xl border bg-white p-6 sm:p-8">
          <div><p className="font-semibold text-slate-900">Product facts</p><p className="mt-1 text-sm text-slate-500">Add verified dimensions, materials, compatibility, included items, or other buyer-relevant specifications.</p></div>
          <div className="mt-5 space-y-3">
            {specifications.map((item) => (
              <div key={item.id} className="grid gap-2 sm:grid-cols-[0.8fr_1.2fr_auto]">
                <input value={item.name} onChange={(event) => setSpecifications((current) => current.map((row) => row.id === item.id ? { ...row, name: event.target.value } : row))} maxLength={100} className="rounded-xl border border-slate-300 px-4 py-3" placeholder="Specification (e.g. Height range)" />
                <input value={item.value} onChange={(event) => setSpecifications((current) => current.map((row) => row.id === item.id ? { ...row, value: event.target.value } : row))} maxLength={1000} className="rounded-xl border border-slate-300 px-4 py-3" placeholder="Verified value" />
                <button type="button" onClick={() => setSpecifications((current) => current.length === 1 ? [{ ...current[0], name: '', value: '' }] : current.filter((row) => row.id !== item.id))} className="rounded-lg p-3 text-slate-400 hover:bg-slate-100 hover:text-slate-700" aria-label="Remove specification"><X className="h-4 w-4" /></button>
              </div>
            ))}
          </div>
          {specifications.length < 40 ? <button type="button" onClick={() => setSpecifications((current) => [...current, { id: Math.max(0, ...current.map((item) => item.id)) + 1, name: '', value: '' }])} className="mt-3 inline-flex items-center gap-2 text-sm font-semibold text-emerald-800"><Plus className="h-4 w-4" />Add specification</button> : null}
        </section>

        <section className="rounded-2xl border bg-white p-6 sm:p-8">
          <button type="button" onClick={() => setShowContext((value) => !value)} className="flex w-full items-center justify-between text-left"><div><p className="font-semibold text-slate-900">Optional context</p><p className="mt-1 text-sm text-slate-500">Competitor content and customer reviews are treated only as supporting evidence.</p></div><span className="text-sm font-semibold text-emerald-800">{showContext ? 'Hide' : 'Add context'}</span></button>
          {showContext ? <div className="mt-6 grid gap-5"><div><label className="text-sm font-semibold text-slate-800">Competitor listing</label><textarea value={competitor} onChange={(event) => setCompetitor(event.target.value)} maxLength={8000} rows={5} className="mt-2 w-full rounded-xl border border-slate-300 px-4 py-3" /></div><div><label className="text-sm font-semibold text-slate-800">Customer reviews</label><p className="mt-1 text-xs text-slate-400">One review per line</p><textarea value={reviews} onChange={(event) => setReviews(event.target.value)} rows={5} className="mt-2 w-full rounded-xl border border-slate-300 px-4 py-3" /></div></div> : null}
        </section>

        {error ? <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div> : null}
        <div className="flex flex-col-reverse gap-4 sm:flex-row sm:items-center sm:justify-between"><p className="flex items-center gap-2 text-sm text-slate-500"><ShieldCheck className="h-4 w-4" />Recommendations are limited to the content you provide.</p><button disabled={isSubmitting} className="inline-flex min-w-40 items-center justify-center gap-2 rounded-xl bg-emerald-800 px-6 py-3.5 font-semibold text-white hover:bg-emerald-900 disabled:cursor-not-allowed disabled:opacity-60">{isSubmitting ? <><Loader2 className="h-4 w-4 animate-spin" />Running audit…</> : 'Run Audit'}</button></div>
      </form>
    </div>
  );
}
