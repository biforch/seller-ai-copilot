import type { Metadata } from 'next';

import { PolicyLayout } from '@/components/marketing/PolicyLayout';

export const metadata: Metadata = { title: 'Privacy Policy — Listnara', description: 'How Listnara collects, uses, and protects personal data.' };

export default function PrivacyPage() {
  return (
    <PolicyLayout eyebrow="Legal" title="Privacy Policy" summary="This policy explains what information Listnara collects, why we use it, and the choices available to you.">
      <h2>1. Information we collect</h2>
      <p>We collect account information such as your email address, authentication and MFA status, and security session data. When you use the service, we process listing text, product facts, customer-review excerpts, competitor content, Amazon listing identifiers, and other material you choose to provide. If image review is introduced, this policy will be updated before image uploads are enabled.</p>
      <p>We also collect operational information such as audit status, token usage, timestamps, error records, IP-derived security signals, and limited product events including registration, audit completion, allowance usage, and Amazon connection status.</p>

      <h2>2. How we use information</h2>
      <ul><li>Provide, secure, troubleshoot, and improve Listnara.</li><li>Generate listing-audit reports requested by you.</li><li>Maintain your account, audit history, and monthly usage allowance.</li><li>Prevent abuse and respond to support or legal requests.</li><li>Measure aggregate product adoption without storing listing content in analytics events.</li></ul>

      <h2>3. AI processing</h2>
      <p>Content submitted for an audit is sent to an AI service provider to generate the requested report. We currently route model requests through OpenRouter and may use underlying model providers such as OpenAI. We configure requests not to be stored where the provider supports that option. Do not submit confidential information, buyer personal information, payment data, credentials, or material you are not authorized to process.</p>

      <h2>4. Amazon data</h2>
      <p>If you connect an Amazon selling account, Listnara accesses only the data authorized by you and permitted by the approved Amazon Selling Partner API roles. Listnara is an independent service and is not endorsed by or affiliated with Amazon. We do not request buyer personal information, payment information, or Amazon account passwords.</p>

      <h2>5. Service providers</h2>
      <p>We use service providers for hosting, database infrastructure, security, DNS and traffic analytics, email, AI processing, Amazon connectivity, and—when launched—payment processing. They process information only to provide their services and under their own contractual and legal obligations.</p>

      <h2>6. Retention and security</h2>
      <p>We retain account and audit information while your account is active and as reasonably necessary for security, support, dispute resolution, and legal compliance. We use encryption in transit, access controls, MFA, backups, and security logging, but no internet service can guarantee absolute security.</p>

      <h2>7. Your choices</h2>
      <p>You may request access, correction, export, or deletion of your personal information, subject to identity verification and applicable retention obligations. You may disconnect Amazon access and revoke authorization through Amazon. Contact <a href="mailto:support@listnara.com">support@listnara.com</a>.</p>

      <h2>8. International processing and children</h2>
      <p>Your information may be processed in countries other than your own. Listnara is intended for business users who are at least 18 years old and is not directed to children.</p>

      <h2>9. Changes and contact</h2>
      <p>We may update this policy as the product and legal requirements evolve. Material changes will be posted here with a revised effective date. Questions may be sent to <a href="mailto:support@listnara.com">support@listnara.com</a>.</p>
    </PolicyLayout>
  );
}
