import type { Metadata } from 'next';
import Link from 'next/link';

import { LegalEntityNotice } from '@/components/marketing/LegalEntityNotice';
import { PolicyLayout } from '@/components/marketing/PolicyLayout';

export const metadata: Metadata = { title: 'Terms of Service — Listnara', description: 'Terms governing use of Listnara.' };

export default function TermsPage() {
  return (
    <PolicyLayout eyebrow="Legal" title="Terms of Service" summary="These terms govern your access to and use of Listnara, including its listing-audit and optional Amazon connectivity features.">
      <LegalEntityNotice variant="terms" />

      <h2>1. Eligibility and accounts</h2>
      <p>You must be at least 18 years old and legally able to enter into these terms. You are responsible for accurate account information, protecting your credentials and MFA recovery methods, and activity under your account.</p>

      <h2>2. The service</h2>
      <p>Listnara provides software-assisted analysis of product listing content. Reports are recommendations based on the information supplied and are not guarantees of ranking, traffic, conversion, sales, regulatory compliance, or marketplace approval. You remain responsible for reviewing every recommendation and for all publishing decisions.</p>

      <h2>3. Your content and permissions</h2>
      <p>You retain ownership of content you submit. You grant Listnara a limited license to host, copy, process, and transmit that content solely to operate, secure, and improve the requested service. You represent that you have the rights and permissions necessary to submit the content.</p>

      <h2>4. Acceptable use</h2>
      <p>You may not use Listnara to violate law or marketplace rules; infringe intellectual-property or privacy rights; process buyer personal information without authorization; distribute malware; probe or bypass security or usage limits; automate abusive traffic; resell access without permission; or submit instructions intended to manipulate the AI system or expose confidential information.</p>

      <h2>5. Amazon</h2>
      <p>Amazon and its trademarks belong to their respective owners. Listnara is independent and is not endorsed by or affiliated with Amazon. Optional Amazon connectivity uses OAuth authorization you initiate. Your use of Amazon services remains subject to your agreements with Amazon. Amazon may change, restrict, or revoke API access, which can affect Listnara features. See our <Link href="/amazon-integration">Amazon Integration</Link> page for scope and limitations.</p>

      <h2>6. Plans, allowances, and payment</h2>
      <p>
        Plans include a monthly allowance of completed audits. Failed audits do not consume allowance; unused allowance
        does not roll over. The Free plan is currently available without payment. If paid plans are introduced later,
        price, renewal period, taxes, and payment provider will be disclosed before purchase.
      </p>

      <h2>7. Availability and changes</h2>
      <p>We may modify, suspend, rate-limit, or discontinue features to maintain security, comply with law or third-party requirements, or improve the service. Beta and pre-release features may change and may be unavailable or contain errors.</p>

      <h2>8. Disclaimer and limitation</h2>
      <p>To the maximum extent permitted by law, the service is provided “as is” and “as available,” without warranties of merchantability, fitness for a particular purpose, non-infringement, or uninterrupted operation. Listnara is not liable for indirect, incidental, special, consequential, or lost-profit damages. Nothing in these terms excludes rights or liabilities that cannot legally be excluded.</p>

      <h2>9. Suspension and termination</h2>
      <p>You may stop using the service at any time. We may suspend or terminate access for material breach, fraud, abuse, security risk, nonpayment, or legal necessity. You may request account deletion by contacting support.</p>

      <h2>10. Contact and changes</h2>
      <p>We may update these terms and will post the revised version with a new effective date. Questions may be sent to <a href="mailto:support@listnara.com">support@listnara.com</a>.</p>
    </PolicyLayout>
  );
}
