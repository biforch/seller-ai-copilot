'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { CheckCircle2, Loader2 } from 'lucide-react';

export default function AmazonOAuthSuccessPage() {
  const router = useRouter();

  useEffect(() => {
    const timeout = window.setTimeout(() => router.replace('/amazon'), 900);
    return () => window.clearTimeout(timeout);
  }, [router]);

  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-50 px-4">
      <div className="w-full max-w-md rounded-2xl border bg-white p-8 text-center shadow-sm">
        <CheckCircle2 className="mx-auto h-12 w-12 text-emerald-500" />
        <h1 className="mt-4 text-2xl font-bold text-slate-950">Amazon connected</h1>
        <p className="mt-2 text-slate-600">Your authorization was saved securely. Opening your Amazon workspace now.</p>
        <Loader2 className="mx-auto mt-6 h-5 w-5 animate-spin text-orange-500" />
      </div>
    </main>
  );
}
