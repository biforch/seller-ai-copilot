import Link from 'next/link';
import { APP_NAME } from '@/lib/constants';
import { LEGAL_PRIVACY_EMAIL } from '@/lib/legal-entity';

export function Footer() {
  return (
    <footer className="mt-auto border-t bg-white">
      <div className="mx-auto grid max-w-7xl gap-7 px-5 py-10 text-sm text-slate-500 sm:grid-cols-[1fr_auto] sm:items-start lg:px-8">
        <div>
          <p>&copy; {new Date().getFullYear()} {APP_NAME}. Evidence-based Amazon Listing Audit.</p>
          <p className="mt-2 max-w-2xl leading-6">Listnara is an independent service and is not affiliated with or endorsed by Amazon. Amazon and related marks are trademarks of their respective owners.</p>
          <a className="mt-3 inline-block font-semibold text-emerald-800 hover:underline" href={`mailto:${LEGAL_PRIVACY_EMAIL}`}>
            {LEGAL_PRIVACY_EMAIL}
          </a>
        </div>
        <nav aria-label="Footer" className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-3">
          <Link href="/amazon-listing-audit" className="hover:text-slate-950">Listing audit</Link>
          <Link href="/amazon-integration" className="hover:text-slate-950">Amazon integration</Link>
          <Link href="/methodology" className="hover:text-slate-950">Methodology</Link>
          <Link href="/about" className="hover:text-slate-950">About</Link>
          <Link href="/pricing" className="hover:text-slate-950">Pricing</Link>
          <Link href="/contact" className="hover:text-slate-950">Contact</Link>
          <Link href="/privacy" className="hover:text-slate-950">Privacy</Link>
          <Link href="/terms" className="hover:text-slate-950">Terms</Link>
          <Link href="/refund" className="hover:text-slate-950">Refunds</Link>
        </nav>
      </div>
    </footer>
  );
}

