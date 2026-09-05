import type { Metadata } from 'next';

import { PolicyLayout } from '@/components/marketing/PolicyLayout';

export const metadata: Metadata = { title: 'Refund Policy — Listnara', description: 'Listnara cancellation and refund policy.' };

export default function RefundPage() {
  return (
    <PolicyLayout eyebrow="Billing" title="Refund Policy" summary="This policy describes refunds and cancellations for Listnara subscriptions.">
      <h2>1. Free plan</h2>
      <p>The Free plan does not require payment and therefore is not eligible for a monetary refund.</p>

      <h2>2. Canceling a subscription</h2>
      <p>When paid plans launch, you will be able to cancel at any time through the billing portal or by contacting support. Cancellation stops future renewals, and access to the paid plan ordinarily continues until the end of the current billing period.</p>

      <h2>3. Refund requests</h2>
      <p>If you believe a charge was made in error, contact us within 14 days of the charge. We will review duplicate charges, unauthorized transactions, material service failures, and other reasonable requests. Approval depends on the circumstances, usage, applicable law, and the payment provider&apos;s rules.</p>

      <h2>4. Usage and renewals</h2>
      <p>Except where required by law, completed audit usage and partially used billing periods are generally not refundable. Forgetting to cancel before renewal does not automatically guarantee a refund, but we will consider promptly submitted requests fairly.</p>

      <h2>5. Statutory rights</h2>
      <p>This policy does not limit mandatory consumer cancellation, refund, or withdrawal rights in your jurisdiction. The merchant of record identified at checkout may process refunds and apply additional buyer-protection requirements.</p>

      <h2>6. How to request help</h2>
      <p>Email <a href="mailto:support@listnara.com">support@listnara.com</a> with your account email, transaction identifier, charge date, and a brief explanation. Never send complete card numbers or security codes.</p>
    </PolicyLayout>
  );
}
