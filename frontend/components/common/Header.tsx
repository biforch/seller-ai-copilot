'use client';

import { useRouter } from 'next/navigation';
import { BarChart3, ClipboardCheck, CreditCard, LogOut, ShoppingBag } from 'lucide-react';

import { APP_NAME } from '@/lib/constants';
import type { User } from '@/types';

interface HeaderProps {
  user?: User | null;
  onLogout?: () => void;
  showAuth?: boolean;
}

export function Header({ user, onLogout, showAuth = false }: HeaderProps) {
  const router = useRouter();

  return (
    <nav className="border-b bg-white/80 backdrop-blur-sm sticky top-0 z-50">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4 flex justify-between items-center">
        <button
          onClick={() => router.push(user ? '/dashboard' : '/')}
          className="flex items-center gap-2"
        >
          <ClipboardCheck className="w-6 h-6 text-emerald-700" />
          <span className="text-xl font-bold text-slate-950">
            {APP_NAME}
          </span>
        </button>

        <div className="flex items-center gap-4">
          {user ? (
            <>
              <button onClick={() => router.push('/audits/new')} className="hidden rounded-lg px-3 py-2 text-sm font-semibold text-emerald-800 hover:bg-emerald-50 sm:block">New Audit</button>
              <button onClick={() => router.push('/amazon-integration')} className="hidden rounded-lg px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-100 lg:inline-flex"><ShoppingBag className="mr-2 h-4 w-4" />Amazon SP-API</button>
              <button onClick={() => router.push('/billing')} className="hidden rounded-lg px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-100 sm:inline-flex"><CreditCard className="mr-2 h-4 w-4" />Billing</button>
              {user.is_admin ? <button onClick={() => router.push('/analytics')} className="hidden rounded-lg px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-100 sm:inline-flex"><BarChart3 className="mr-2 h-4 w-4" />Analytics</button> : null}
              <span className="text-sm text-gray-600 hidden sm:inline">{user.email}</span>
              <button
                onClick={onLogout}
                className="p-2 text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded-lg transition-colors"
                title="Sign out"
              >
                <LogOut className="w-5 h-5" />
              </button>
            </>
          ) : showAuth ? (
            <>
              <button onClick={() => router.push('/amazon-listing-audit')} className="hidden text-sm font-medium text-gray-600 hover:text-gray-900 lg:block">How it works</button>
              <button onClick={() => router.push('/methodology')} className="hidden text-sm font-medium text-gray-600 hover:text-gray-900 lg:block">Methodology</button>
              <button onClick={() => router.push('/pricing')} className="hidden text-sm font-medium text-gray-600 hover:text-gray-900 sm:block">Pricing</button>
              <button onClick={() => router.push('/contact')} className="hidden text-sm font-medium text-gray-600 hover:text-gray-900 sm:block">Contact</button>
              <button
                onClick={() => router.push('/login')}
                className="text-sm font-medium text-gray-600 hover:text-gray-900"
              >
                Sign In
              </button>
              <button
                onClick={() => router.push('/register')}
                className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors"
              >
                Audit My Listing
              </button>
            </>
          ) : null}
        </div>
      </div>
    </nav>
  );
}
