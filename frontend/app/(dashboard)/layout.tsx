'use client';

import { useEffect } from 'react';

import { Header } from '@/components/common/Header';
import { Footer } from '@/components/common/Footer';
import { useAuth } from '@/hooks/useAuth';

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const { user, logout, requireAuth } = useAuth();

  useEffect(() => {
    requireAuth();
  }, [requireAuth]);

  return (
    <div className="min-h-screen bg-slate-50 flex flex-col">
      <Header user={user} onLogout={logout} />
      <main className="flex-1">{children}</main>
      <Footer />
    </div>
  );
}
