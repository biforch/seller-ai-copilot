'use client';

import { Suspense } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { AlertCircle, ArrowLeft } from 'lucide-react';

const ERROR_MESSAGES: Record<string, string> = {
  AMAZON_OAUTH_STATE_EXPIRED: 'This connection request expired. Start a new connection from SellerAI.',
  AMAZON_OAUTH_STATE_REPLAY: 'This connection request was already used. Start a new connection if needed.',
  AMAZON_OAUTH_SELLER_ALREADY_LINKED: 'This Amazon seller is already linked to another SellerAI account.',
  AMAZON_OAUTH_SELLER_MISMATCH: 'The Amazon seller does not match the account being reauthorized.',
  AMAZON_OAUTH_TOKEN_EXCHANGE_FAILED: 'Amazon could not complete the authorization. Please try again.',
  AMAZON_OAUTH_REDIRECT_INVALID: 'Amazon did not return a complete authorization response.',
};

function ErrorContent() {
  const router = useRouter();
  const params = useSearchParams();
  const code = params.get('error_code') ?? '';
  const message = ERROR_MESSAGES[code] ?? 'The Amazon connection could not be completed. Please try again.';

  return (
    <div className="w-full max-w-md rounded-2xl border bg-white p-8 text-center shadow-sm">
      <AlertCircle className="mx-auto h-12 w-12 text-red-500" />
      <h1 className="mt-4 text-2xl font-bold text-slate-950">Connection not completed</h1>
      <p className="mt-2 text-slate-600">{message}</p>
      <button onClick={() => router.replace('/amazon')} className="mx-auto mt-6 inline-flex items-center gap-2 rounded-lg bg-slate-950 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-800">
        <ArrowLeft className="h-4 w-4" /> Back to Amazon workspace
      </button>
    </div>
  );
}

export default function AmazonOAuthErrorPage() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-50 px-4">
      <Suspense fallback={<div className="text-sm text-slate-500">Loading…</div>}>
        <ErrorContent />
      </Suspense>
    </main>
  );
}
