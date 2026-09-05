import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Create Account — Listnara',
  description: 'Create a free Listnara account for evidence-backed Amazon listing audits.',
  robots: { index: false, follow: true },
};

export default function RegisterLayout({ children }: { children: React.ReactNode }) {
  return children;
}
