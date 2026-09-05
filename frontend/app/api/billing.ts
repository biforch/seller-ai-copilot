import { apiClient } from '@/app/api/client';

export type BillingPlan = 'free' | 'plus' | 'pro';

export interface BillingEntitlement {
  plan: BillingPlan;
  limit: number | null;
  used: number;
  reserved: number;
  remaining: number | null;
  period_start: string;
  period_end: string;
  subscription_status: string | null;
  cancel_at_period_end: boolean;
}

export interface CheckoutConfig {
  enabled: boolean;
  environment: 'sandbox' | 'production';
  client_token: string | null;
  user_id: string | null;
  user_signature: string | null;
  prices: { plus: string; pro: string };
}

export const billingApi = {
  entitlement: () => apiClient.get<BillingEntitlement>('/billing/entitlement'),
  checkoutConfig: () => apiClient.get<CheckoutConfig>('/billing/checkout-config'),
  portal: () => apiClient.post<{ url: string }>('/billing/portal'),
};
