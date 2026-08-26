'use client';

import { useRouter } from 'next/navigation';
import { LogOut, Sparkles } from 'lucide-react';

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
          <Sparkles className="w-6 h-6 text-blue-600" />
          <span className="text-xl font-bold bg-gradient-to-r from-blue-600 to-purple-600 bg-clip-text text-transparent">
            {APP_NAME}
          </span>
        </button>

        <div className="flex items-center gap-4">
          {user ? (
            <>
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
                Get Started Free
              </button>
            </>
          ) : null}
        </div>
      </div>
    </nav>
  );
}
