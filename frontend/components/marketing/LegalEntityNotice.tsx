import {
  INDIVIDUAL_DEVELOPER_ABOUT,
  INDIVIDUAL_DEVELOPER_PRIVACY,
  INDIVIDUAL_DEVELOPER_TERMS,
  LEGAL_PRIVACY_EMAIL,
  PRODUCT_NAME,
} from '@/lib/legal-entity';

type LegalEntityNoticeVariant = 'about' | 'privacy' | 'terms' | 'general';

interface LegalEntityNoticeProps {
  variant?: LegalEntityNoticeVariant;
}

const COPY: Record<LegalEntityNoticeVariant, string> = {
  about: INDIVIDUAL_DEVELOPER_ABOUT,
  privacy: INDIVIDUAL_DEVELOPER_PRIVACY,
  terms: INDIVIDUAL_DEVELOPER_TERMS,
  general: INDIVIDUAL_DEVELOPER_ABOUT,
};

export function LegalEntityNotice({ variant = 'general' }: LegalEntityNoticeProps) {
  return (
    <aside
      className="rounded-2xl border border-slate-200 bg-slate-50 p-6 text-sm leading-7 text-slate-700"
      aria-label="Operator identity"
    >
      <p>{COPY[variant]}</p>
      {variant === 'general' ? (
        <p className="mt-2">
          Contact:{' '}
          <a href={`mailto:${LEGAL_PRIVACY_EMAIL}`} className="font-semibold text-emerald-800 underline">
            {LEGAL_PRIVACY_EMAIL}
          </a>
        </p>
      ) : null}
      <p className="mt-2 text-slate-600">
        <strong>{PRODUCT_NAME}</strong> is not affiliated with or endorsed by Amazon.
      </p>
    </aside>
  );
}
