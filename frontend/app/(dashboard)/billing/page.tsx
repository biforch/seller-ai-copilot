'use client';

import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { Check, Loader2 } from 'lucide-react';

import { billingApi, type BillingEntitlement, type BillingPlan, type CheckoutConfig } from '@/app/api/billing';

type PaddleCheckout = { open: (options: Record<string, unknown>) => void };
type PaddleSdk = {
  Environment: { set: (environment: 'sandbox') => void };
  Initialize: (options: { token: string; eventCallback?: (event: { name?: string }) => void }) => void;
  Checkout: PaddleCheckout;
};

declare global { interface Window { Paddle?: PaddleSdk } }

const plans: Array<{ id: BillingPlan; name: string; price: string; limit: number }> = [
  { id: 'free', name: 'Free', price: '$0', limit: 5 },
  { id: 'plus', name: 'Plus', price: '$9.90', limit: 25 },
  { id: 'pro', name: 'Pro', price: '$19.90', limit: 60 },
];

function loadPaddle(): Promise<PaddleSdk> {
  if (window.Paddle) return Promise.resolve(window.Paddle);
  return new Promise((resolve, reject) => {
    const existing = document.querySelector<HTMLScriptElement>('script[data-listnara-paddle]');
    const script = existing ?? document.createElement('script');
    if (!existing) {
      script.src = 'https://cdn.paddle.com/paddle/v2/paddle.js';
      script.async = true;
      script.dataset.listnaraPaddle = 'true';
      document.head.appendChild(script);
    }
    script.addEventListener('load', () => window.Paddle ? resolve(window.Paddle) : reject(new Error('Paddle did not load')), { once: true });
    script.addEventListener('error', () => reject(new Error('Paddle could not load')), { once: true });
  });
}

export default function BillingPage() {
  const searchParams = useSearchParams();
  const requestedPlan = searchParams.get('plan');
  const [entitlement, setEntitlement] = useState<BillingEntitlement | null>(null);
  const [config, setConfig] = useState<CheckoutConfig | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState('');

  const refresh = async () => {
    const [nextEntitlement, nextConfig] = await Promise.all([billingApi.entitlement(), billingApi.checkoutConfig()]);
    setEntitlement(nextEntitlement);
    setConfig(nextConfig);
  };

  useEffect(() => {
    let active = true;
    void Promise.all([billingApi.entitlement(), billingApi.checkoutConfig()])
      .then(([nextEntitlement, nextConfig]) => {
        if (active) {
          setEntitlement(nextEntitlement);
          setConfig(nextConfig);
        }
      })
      .catch(() => { if (active) setMessage('Billing details could not be loaded.'); });
    return () => { active = false; };
  }, []);
  const usageLabel = useMemo(() => entitlement ? `${entitlement.used} of ${entitlement.limit ?? 'unlimited'} completed audits used` : '', [entitlement]);

  const checkout = async (plan: 'plus' | 'pro') => {
    if (
      !config?.enabled ||
      !config.client_token ||
      !config.user_id ||
      !config.user_signature ||
      !config.prices[plan]
    ) {
      setMessage('Sandbox checkout is not enabled on the server yet.');
      return;
    }
    setBusy(plan); setMessage('');
    try {
      const paddle = await loadPaddle();
      if (config.environment === 'sandbox') paddle.Environment.set('sandbox');
      paddle.Initialize({
        token: config.client_token,
        eventCallback: (event) => {
          if (event.name === 'checkout.completed') {
            setMessage('Payment completed. Your plan will update after Paddle confirms the subscription.');
            window.setTimeout(() => refresh().catch(() => undefined), 2000);
          }
        },
      });
      paddle.Checkout.open({
        items: [{ priceId: config.prices[plan], quantity: 1 }],
        customData: { user_id: config.user_id, user_signature: config.user_signature },
        settings: { displayMode: 'overlay', theme: 'light', locale: 'en' },
      });
    } catch {
      setMessage('Checkout could not be opened. Please try again.');
    } finally { setBusy(null); }
  };

  const manage = async () => {
    setBusy('portal'); setMessage('');
    try { window.location.assign((await billingApi.portal()).url); }
    catch { setMessage('Subscription management is not available yet.'); setBusy(null); }
  };

  return (
    <div className="mx-auto max-w-6xl px-5 py-12">
      <div className="flex flex-col justify-between gap-5 sm:flex-row sm:items-end">
        <div><p className="text-sm font-bold uppercase tracking-[0.18em] text-emerald-800">Billing</p><h1 className="mt-2 text-4xl font-semibold tracking-tight">Plan and audit allowance</h1><p className="mt-3 text-slate-600">{usageLabel || 'Loading your current allowance…'}</p></div>
        {entitlement?.subscription_status ? <button onClick={manage} disabled={busy === 'portal'} className="rounded-xl border border-slate-300 bg-white px-5 py-3 font-semibold hover:bg-slate-50 disabled:opacity-50">Manage subscription</button> : null}
      </div>
      {message ? <div className="mt-6 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">{message}</div> : null}
      {config && !config.enabled ? <div className="mt-6 rounded-xl border border-blue-200 bg-blue-50 p-4 text-sm text-blue-900">Checkout code is ready. Add the Sandbox credentials to the server to enable test purchases.</div> : null}
      <div className="mt-8 grid gap-6 md:grid-cols-3">
        {plans.map((plan) => {
          const current = entitlement?.plan === plan.id;
          const highlighted = requestedPlan === plan.id || plan.id === 'plus';
          return <section key={plan.id} className={`rounded-3xl border bg-white p-7 shadow-sm ${highlighted ? 'border-emerald-700' : 'border-slate-200'}`}>
            <h2 className="text-2xl font-semibold">{plan.name}</h2><p className="mt-4 text-4xl font-semibold">{plan.price}<span className="text-base font-normal text-slate-500"> / month</span></p>
            <p className="mt-4 flex gap-2 text-sm text-slate-700"><Check className="h-5 w-5 text-emerald-700" />{plan.limit} completed audits each month</p>
            {current ? <div className="mt-8 rounded-xl bg-emerald-50 px-4 py-3 text-center font-semibold text-emerald-900">Current plan</div> : plan.id === 'free' ? <div className="mt-8 rounded-xl border px-4 py-3 text-center font-semibold text-slate-500">Included</div> : <button onClick={() => checkout(plan.id as 'plus' | 'pro')} disabled={busy !== null || !config?.enabled} className="mt-8 flex w-full items-center justify-center rounded-xl bg-emerald-800 px-4 py-3 font-semibold text-white hover:bg-emerald-900 disabled:cursor-not-allowed disabled:opacity-50">{busy === plan.id ? <Loader2 className="h-5 w-5 animate-spin" /> : `Choose ${plan.name}`}</button>}
          </section>;
        })}
      </div>
      <p className="mt-6 text-sm text-slate-500">Failed audits do not use allowance. Unused audits do not roll over. Taxes are calculated at checkout.</p>
    </div>
  );
}
