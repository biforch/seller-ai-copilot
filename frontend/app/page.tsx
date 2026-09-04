'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { ArrowRight, FileSearch, ListChecks, ShieldCheck, Sparkles } from 'lucide-react';

import { Header } from '@/components/common/Header';
import { Footer } from '@/components/common/Footer';
import { useAuth } from '@/hooks/useAuth';

export default function Home() {
  const router = useRouter();
  const { user, isLoading } = useAuth();

  useEffect(() => {
    if (!isLoading && user) {
      router.push('/dashboard');
    }
  }, [user, isLoading, router]);

  return (
    <div className="min-h-screen bg-gradient-to-b from-slate-50 to-white flex flex-col">
      <Header showAuth />

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-20 pb-32 flex-1">
        <div className="text-center">
          <div className="inline-flex items-center gap-2 bg-blue-50 text-blue-700 px-4 py-2 rounded-full text-sm font-medium mb-6">
            <FileSearch className="w-4 h-4" />
            Evidence-grounded Listing Audit
          </div>

          <h1 className="text-5xl sm:text-6xl font-bold text-gray-900 leading-tight mb-6">
            Find What Is Holding Your
            <span className="bg-gradient-to-r from-blue-600 to-purple-600 bg-clip-text text-transparent">
              {' '}Listing Back
            </span>
          </h1>

          <p className="text-xl text-gray-600 max-w-2xl mx-auto mb-10">
            Paste your listing and get a structured score, evidence-backed issues,
            clear limitations, and the three actions worth prioritizing first.
          </p>

          <button
            onClick={() => router.push('/register')}
            className="px-8 py-4 bg-blue-600 text-white text-lg font-semibold rounded-xl hover:bg-blue-700 transition-all hover:scale-105 shadow-lg shadow-blue-200 inline-flex items-center gap-2"
          >
            Audit Your Listing
            <ArrowRight className="w-5 h-5" />
          </button>

          <p className="text-sm text-gray-500 mt-4">
            Internal registered-user release • Amazon connection not required
          </p>
        </div>

        <div className="grid md:grid-cols-3 gap-8 mt-24">
          <div className="bg-white p-6 rounded-2xl border shadow-sm hover:shadow-md transition-shadow">
            <div className="w-12 h-12 bg-blue-50 rounded-xl flex items-center justify-center mb-4">
              <FileSearch className="w-6 h-6 text-blue-600" />
            </div>
            <h3 className="text-lg font-semibold mb-2">Structured Audit</h3>
            <p className="text-gray-600 text-sm">
              Score positioning, buyer clarity, information quality, conversion readiness, and discoverability.
            </p>
          </div>

          <div className="bg-white p-6 rounded-2xl border shadow-sm hover:shadow-md transition-shadow">
            <div className="w-12 h-12 bg-purple-50 rounded-xl flex items-center justify-center mb-4">
              <ShieldCheck className="w-6 h-6 text-purple-600" />
            </div>
            <h3 className="text-lg font-semibold mb-2">Grounded Findings</h3>
            <p className="text-gray-600 text-sm">
              Every issue points back to supplied listing evidence and states what the audit cannot know.
            </p>
          </div>

          <div className="bg-white p-6 rounded-2xl border shadow-sm hover:shadow-md transition-shadow">
            <div className="w-12 h-12 bg-green-50 rounded-xl flex items-center justify-center mb-4">
              <ListChecks className="w-6 h-6 text-green-600" />
            </div>
            <h3 className="text-lg font-semibold mb-2">Prioritized Actions</h3>
            <p className="text-gray-600 text-sm">
              Focus on no more than three concrete improvements, ranked by urgency and expected effect.
            </p>
          </div>
        </div>
      </div>

      <Footer />
    </div>
  );
}
