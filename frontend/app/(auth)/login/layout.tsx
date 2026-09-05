import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Sign In — Listnara',
  description: 'Sign in to your Listnara account to run evidence-backed Amazon listing audits.',
  robots: { index: false, follow: true },
};

export default function LoginLayout({ children }: { children: React.ReactNode }) {
  return children;
}
