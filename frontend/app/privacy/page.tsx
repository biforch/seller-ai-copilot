import type { Metadata } from 'next';
import Link from 'next/link';

import { LegalEntityNotice } from '@/components/marketing/LegalEntityNotice';
import { PolicyLayout } from '@/components/marketing/PolicyLayout';
import { SP_API_READ_OPERATIONS, SP_API_ROLES } from '@/lib/legal-entity';
import { PUBLIC_SITE_URL } from '@/lib/site-url';

export const metadata: Metadata = {
  title: 'Privacy Policy — Listnara',
  description: 'How Listnara collects, uses, stores, and protects personal and Amazon seller data.',
  alternates: { canonical: '/privacy' },
};

export default function PrivacyPage() {
  return (
    <PolicyLayout
      eyebrow="Legal"
      title="Privacy Policy"
      summary="This policy explains what information Listnara collects, why we use it, how we protect it, and the choices available to you—including Amazon seller data accessed through SP-API when that feature is enabled."
    >
      <LegalEntityNotice variant="privacy" />

      <h2>1. Information we collect</h2>
      <h3>Account and security</h3>
      <p>
        We collect account information such as your email address, authentication and MFA status, and security session
        data needed to operate a secure login.
      </p>
      <h3>Listing audit content</h3>
      <p>
        When you run a listing audit, we process the listing text, specifications, images, customer-review excerpts,
        competitor content, and other material you choose to provide for that audit.
      </p>
      <h3>Amazon seller data (optional)</h3>
      <p>
        Production Amazon connectivity is currently disabled, and Listnara does not currently process production Amazon
        Information. If you connect an Amazon selling account after connectivity is enabled, we may process selling
        partner identifiers, marketplace participation, listing identifiers (such as seller SKU and ASIN), listing
        content fields, and bounded catalog summary attributes retrieved through read-oriented Selling Partner API
        operations described on our <Link href="/amazon-integration">Amazon Integration</Link> page.
      </p>
      <p>
        Before production Amazon connectivity is enabled, operational backup retention and deletion controls for
        Amazon-derived data will be activated and verified.
      </p>
      <h3>Operational data</h3>
      <p>
        We collect operational information such as audit status, token usage, timestamps, error records, IP-derived
        security signals, and limited product events including registration, audit completion, allowance usage, and
        Amazon connection status. Analytics events are designed not to include listing body text.
      </p>

      <h2>2. How we use information</h2>
      <ul>
        <li>Provide, secure, troubleshoot, and improve Listnara.</li>
        <li>Generate listing-audit reports you request.</li>
        <li>Maintain your account, audit history, and monthly usage allowance.</li>
        <li>
          Import Amazon listing data you authorize, solely to support listing analysis and reduce manual entry, when
          Amazon connectivity is enabled.
        </li>
        <li>Prevent abuse and respond to support or legal requests.</li>
        <li>Measure aggregate product adoption without storing listing content in analytics events.</li>
      </ul>

      <h2>3. AI processing</h2>
      <p>
        Content you manually submit for a listing audit may be sent to a configured AI service provider to generate the
        requested report. Depending on environment configuration, requests may route through OpenRouter to an underlying
        model provider or directly to the OpenAI API. Where supported by the provider, we configure requests with{' '}
        <code>store=false</code> so the provider does not retain request content for provider-side storage by default.
      </p>
      <p>
        We do not use your listing content to train our own models. Do not submit confidential information, buyer
        personal information, payment data, credentials, or material you are not authorized to process.
      </p>
      <p>
        <strong>Amazon-derived data and AI:</strong> in the current production configuration (
        <code>OPENAI_AMAZON_DATA_ENABLED=false</code>), Amazon-imported listing attributes are not sent to OpenAI,
        OpenRouter, or other AI providers. If that behavior changes in the future, we will update technical controls,
        this policy, and our Amazon disclosure before enabling it.
      </p>

      <h2>4. Amazon seller data</h2>
      <p>
        Listnara is an independent service and is not endorsed by or affiliated with Amazon. We do not request Amazon
        account passwords, buyer personal information, or payment card data through SP-API.
      </p>
      <h3>Approved SP-API roles</h3>
      <p>
        Our Amazon Developer application is registered for these roles only: {SP_API_ROLES.join(' and ')}. Read-oriented
        API families used in the application include {SP_API_READ_OPERATIONS.join(', ')}. Role names and API names are not
        identical; we describe both for transparency.
      </p>
      <h3>Sources</h3>
      <p>
        When Amazon connectivity is enabled, Amazon seller data comes only from your explicit OAuth authorization and
        subsequent import actions you initiate.
      </p>
      <h3>Storage</h3>
      <p>
        OAuth refresh tokens are stored encrypted in our PostgreSQL database while a connection remains active. Imported
        listing and catalog snapshots are stored in application tables associated with your user account. Audit inputs and
        completed audit reports are stored as part of your account history.
      </p>
      <h3>Security</h3>
      <p>
        We use encryption in transit (HTTPS), encrypted refresh-token storage, access controls, MFA for accounts, tenant
        isolation in database queries, and log redaction for OAuth and credential patterns.
      </p>
      <h3>Disconnect and deletion</h3>
      <p>
        When you disconnect an Amazon account in Listnara, we immediately stop subsequent SP-API calls for that
        connection, delete the stored refresh token, finalize in-flight sync work, and remove imported Amazon account
        records—including marketplace participation, listings, catalog snapshots, and Amazon-linked audit snapshots—from
        active application databases. You should also revoke Listnara in Amazon Seller Central under{' '}
        <strong>Apps and Services → Manage Your Apps</strong>.
      </p>
      <p>
        You may request account deletion by emailing{' '}
        <a href="mailto:support@listnara.com">support@listnara.com</a> from your account email. After we verify a valid
        request, we remove user-owned records, including associated Amazon data and audit history, from active application
        systems within 30 days.
      </p>

      <h2>5. Retention</h2>
      <p>
        This section distinguishes <strong>active application systems</strong> (the live database used by the product)
        from <strong>encrypted operational backups</strong> (private backup copies used only for disaster recovery).
        Backups are not used for normal business queries.
      </p>
      <ul>
        <li>
          <strong>Active accounts:</strong> account, audit, and any imported Amazon data are retained while your account
          remains active and you continue using the service.
        </li>
        <li>
          <strong>After Amazon disconnect (active systems):</strong> refresh tokens are deleted immediately; imported
          Amazon account, listing, catalog, and linked audit snapshot data are removed from active application databases as
          part of the disconnect operation.
        </li>
        <li>
          <strong>After verified account deletion (active systems):</strong> user-owned records are removed from active
          application systems within 30 days of a verified deletion request. There is no automated self-service purge
          worker; deletions are performed through an operator-controlled administrative process.
        </li>
        <li>
          <strong>Encrypted operational backups:</strong> automated scheduled backup upload is a target control and is not
          yet confirmed enabled in production. Manual backup copies may exist; their final location and retention are not
          yet fully confirmed. When operational backups are enabled, any backup that may contain Amazon-derived data,
          including refresh-token ciphertext, is subject to a maximum retention of 35 days. Deleted active-system data may
          therefore remain in encrypted operational backups until that backup rotation completes. If disaster recovery
          restores from backup, disconnect and deletion actions must be re-applied where required.
        </li>
        <li>
          <strong>Long-term archives:</strong> Listnara does not currently retain 12-month full-database archives that
          contain Amazon-derived data. A separate long-term archive that excludes Amazon tables and Amazon-linked audit
          content may be introduced only after it is implemented and restore-tested.
        </li>
        <li>
          <strong>Legal and security exceptions:</strong> we may retain minimal records longer when required by law,
          fraud prevention, or active disputes. Those records do not include refresh tokens or unnecessary full listing
          content.
        </li>
      </ul>

      <h2>6. Your choices</h2>
      <p>
        You may request access, correction, export, or deletion of your personal information, subject to identity
        verification and applicable retention obligations. Contact{' '}
        <a href="mailto:support@listnara.com">support@listnara.com</a>.
      </p>

      <h2>7. International processing and children</h2>
      <p>
        Your information may be processed in countries other than your own. Listnara is intended for business users who
        are at least 18 years old and is not directed to children.
      </p>

      <h2>8. Changes and contact</h2>
      <p>
        We may update this policy as the product and legal requirements evolve. Material changes will be posted at{' '}
        <Link href="/privacy">{PUBLIC_SITE_URL}/privacy</Link> with a revised effective date. Questions may be sent to{' '}
        <a href="mailto:support@listnara.com">support@listnara.com</a>.
      </p>
    </PolicyLayout>
  );
}
