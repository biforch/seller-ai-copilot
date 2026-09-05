import type { Metadata } from 'next';
import Link from 'next/link';

import { AmazonIndependenceNotice } from '@/components/marketing/AmazonIndependenceNotice';
import { LegalEntityNotice } from '@/components/marketing/LegalEntityNotice';
import { PublicPageShell } from '@/components/marketing/PublicPageShell';
import {
  PRODUCT_CORE_DESCRIPTION,
  SP_API_READ_OPERATIONS,
  SP_API_ROLES,
} from '@/lib/legal-entity';
import { PUBLIC_SITE_URL } from '@/lib/site-url';

export const metadata: Metadata = {
  title: 'Amazon Integration — Listnara',
  description:
    'How Listnara optionally connects to Amazon Selling Partner API to import listing data for seller-authorized listing analysis.',
  alternates: { canonical: '/amazon-integration' },
};

const workflow = [
  'You authorize Listnara through Amazon OAuth when connectivity is enabled for your environment.',
  'Listnara reads eligible marketplace, listing, and catalog information you approved.',
  'Imported listings can be associated with products you manage in Listnara.',
  'Listnara checks listing clarity, completeness, and consistency.',
  'Listnara generates bounded, verifiable improvement suggestions.',
  'You review every suggestion before acting.',
  'Listnara does not automatically publish or modify Amazon listings.',
];

export default function AmazonIntegrationPage() {
  return (
    <PublicPageShell>
      <article className="mx-auto max-w-4xl px-5 py-16 sm:py-20">
        <p className="text-sm font-bold uppercase tracking-[0.2em] text-emerald-800">Amazon integration</p>
        <h1 className="mt-4 text-4xl font-semibold tracking-[-0.04em] sm:text-5xl">
          Optional Amazon connectivity for seller-controlled listing analysis
        </h1>
        <p className="mt-6 text-lg leading-8 text-slate-600">{PRODUCT_CORE_DESCRIPTION}</p>

        <div className="mt-8 rounded-2xl border border-slate-200 bg-white p-6">
          <h2 className="text-xl font-semibold text-slate-950">Availability</h2>
          <p className="mt-3 leading-7 text-slate-600">
            Production Amazon connectivity is currently disabled. You can run listing audits from content you enter
            manually without connecting Amazon. When connectivity becomes available, authorization will be offered through
            Amazon&apos;s standard OAuth consent flow.
          </p>
        </div>

        <section className="mt-10 space-y-4 text-[1.02rem] leading-8 text-slate-700">
          <h2 className="text-2xl font-semibold text-slate-950">Product workflow</h2>
          <ol className="list-decimal space-y-2 pl-6">
            {workflow.map((step) => (
              <li key={step}>{step}</li>
            ))}
          </ol>

          <h2 className="pt-6 text-2xl font-semibold text-slate-950">How authorization works</h2>
          <ul className="list-disc space-y-2 pl-6">
            <li>
              Connection uses Amazon&apos;s OAuth flow. You sign in with your selling account and grant permission in
              Amazon&apos;s consent screen.
            </li>
            <li>Listnara never asks for your Amazon password. We receive OAuth tokens only after you approve access.</li>
            <li>
              Refresh tokens are encrypted at rest in our application database. Access tokens are used transiently for
              API calls and are not stored as long-term credentials in application logs.
            </li>
          </ul>

          <h2 className="pt-6 text-2xl font-semibold text-slate-950">Registered SP-API roles</h2>
          <p>
            Our Amazon Developer application is registered for these roles only:{' '}
            <strong>{SP_API_ROLES.join(' and ')}</strong>. We do not claim any other SP-API roles.
          </p>

          <h2 className="pt-6 text-2xl font-semibold text-slate-950">Read-oriented API families implemented</h2>
          <p>
            When Amazon connectivity is enabled, our backend calls these API families for read-only import and analysis
            support:
          </p>
          <ul className="list-disc space-y-2 pl-6">
            <li>
              <strong>Sellers API</strong> — marketplace participations for connected accounts.
            </li>
            <li>
              <strong>Listings Items API</strong> — listing identifiers, content, and status for analysis (no publish or
              update operations).
            </li>
            <li>
              <strong>Catalog Items API</strong> — bounded catalog summaries to enrich analysis context where an ASIN is
              available.
            </li>
          </ul>
          <p className="text-sm text-slate-600">
            Role names and API names are related but not identical. We list both for transparency:{' '}
            {SP_API_READ_OPERATIONS.join(', ')}.
          </p>

          <h2 className="pt-6 text-2xl font-semibold text-slate-950">Categories of Amazon seller data we may access</h2>
          <p>When you connect and import, Listnara may process:</p>
          <ul className="list-disc space-y-2 pl-6">
            <li>Selling partner identifier and connected account metadata.</li>
            <li>Marketplace identifiers and participation status.</li>
            <li>Listing identifiers such as seller SKU and ASIN.</li>
            <li>Listing content fields used for audit analysis (for example title, bullet points, and description).</li>
            <li>Bounded catalog summary attributes where retrieved for context.</li>
          </ul>

          <h2 className="pt-6 text-2xl font-semibold text-slate-950">What we do not access or do</h2>
          <ul className="list-disc space-y-2 pl-6">
            <li>
              <strong>We do not modify Amazon listings</strong> through SP-API. Listnara does not publish, patch, or
              delete live listings on your behalf.
            </li>
            <li>
              We do not request orders, buyer communications, payment information, tax documents, or shipping labels.
            </li>
            <li>We do not use SP-API to collect buyer personally identifiable information.</li>
            <li>
              Amazon-derived listing attributes are not sent to OpenAI, OpenRouter, or other AI providers in the current
              configuration.
            </li>
          </ul>

          <h2 className="pt-6 text-2xl font-semibold text-slate-950">Disconnecting and revoking access</h2>
          <h3 className="text-lg font-semibold text-slate-900">Inside Listnara</h3>
          <p>
            When Amazon connectivity is enabled in your account, you can disconnect a linked selling account from the
            Amazon workspace. Disconnect immediately stops subsequent SP-API calls for that connection, deletes the stored
            refresh token, and removes imported Amazon account, listing, catalog, and linked audit snapshot data from
            active application databases.
          </p>
          <p>
            You can also email{' '}
            <a href="mailto:support@listnara.com" className="font-semibold text-emerald-800 underline">
              support@listnara.com
            </a>{' '}
            from your account email to request account deletion or additional data removal.
          </p>
          <h3 className="mt-4 text-lg font-semibold text-slate-900">In Amazon Seller Central</h3>
          <p>You should also revoke Listnara&apos;s authorization in Seller Central:</p>
          <ol className="list-decimal space-y-2 pl-6">
            <li>Sign in to Seller Central with the selling account you connected.</li>
            <li>Open <strong>Apps and Services</strong> → <strong>Manage Your Apps</strong> (wording may vary by region).</li>
            <li>Locate the Listnara application and choose <strong>Revoke access</strong> or equivalent.</li>
          </ol>
          <p>
            After revocation, Listnara cannot call SP-API with your prior refresh token. Data removed from active systems
            may remain in encrypted operational backups until backup rotation completes, as described in our{' '}
            <Link href="/privacy" className="font-semibold text-emerald-800 underline">
              Privacy Policy
            </Link>
            .
          </p>

          <h2 className="pt-6 text-2xl font-semibold text-slate-950">Production status and data retention</h2>
          <p>
            Production Amazon connectivity is currently disabled, and Listnara does not currently process production
            Amazon Information. Before production Amazon connectivity is enabled, operational backup retention and
            deletion controls for Amazon-derived data will be activated and verified.
          </p>
          <p>
            When you disconnect in Listnara, we immediately remove the stored refresh token and imported Amazon account,
            listing, catalog, and linked audit snapshot data from active application systems. Encrypted operational
            backups are used only for disaster recovery, not for normal business queries. When Amazon connectivity is
            enabled, backups that may contain Amazon-derived data will be retained for no longer than 35 days; deleted
            active-system data may remain in those backups until that rotation period ends.
          </p>

          <h2 className="pt-6 text-2xl font-semibold text-slate-950">Support</h2>
          <p>
            Questions about Amazon connectivity, data deletion, or Developer Profile alignment:{' '}
            <a href="mailto:support@listnara.com" className="font-semibold text-emerald-800 underline">
              support@listnara.com
            </a>
            . Public site: <Link href="/">{PUBLIC_SITE_URL}</Link>.
          </p>

          <div className="mt-8">
            <AmazonIndependenceNotice />
          </div>
        </section>

        <div className="mt-12">
          <LegalEntityNotice variant="general" />
        </div>
      </article>
    </PublicPageShell>
  );
}
