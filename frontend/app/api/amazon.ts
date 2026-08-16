import { apiClient } from '@/app/api/client';
import type { PaginatedResponse } from '@/types';

export type AmazonAccountStatus =
  | 'active'
  | 'reauthorization_required'
  | 'disabled'
  | 'error';

export interface AmazonAccount {
  id: string;
  region: 'na' | 'eu' | 'fe';
  endpoint_mode: 'sandbox' | 'production';
  status: AmazonAccountStatus;
  last_verified_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface AmazonMarketplace {
  marketplace_id: string;
  marketplace_name: string;
  country_code: string;
  default_currency_code: string | null;
  default_language_code: string | null;
  domain_name: string | null;
  participating: boolean;
  suspended_listings: boolean;
  is_active: boolean;
  sync_eligible: boolean;
  last_seen_at: string;
  created_at: string;
  updated_at: string;
}

export interface AmazonListing {
  id: string;
  marketplace_id: string;
  seller_sku: string;
  asin: string | null;
  product_id: string | null;
  status_codes: string[];
  product_type: string | null;
  upstream_created_at: string | null;
  upstream_last_updated_at: string | null;
  is_active: boolean;
  first_seen_at: string;
  last_seen_at: string;
  created_at: string;
  updated_at: string;
}

export interface AmazonLinkProduct {
  id: string;
  project_id: string;
  name: string;
  category: string | null;
  platform: string;
  market: string;
}

interface AmazonAccountList {
  items: AmazonAccount[];
  total: number;
}

interface AmazonMarketplaceList {
  items: AmazonMarketplace[];
  total: number;
}

interface OAuthStartResult {
  authorization_url: string;
  marketplace_code: string;
  region: string;
  expires_at: string;
}

export interface AmazonSyncResult {
  account_id: string;
  sync_log_id: string;
  items_seen: number;
  items_written: number;
  items_deactivated: number;
  pages_seen?: number;
  marketplace_id?: string;
}

export const amazonApi = {
  listAccounts: () => apiClient.get<AmazonAccountList>('/amazon/accounts'),

  listLinkableProducts: () =>
    apiClient.get<PaginatedResponse<AmazonLinkProduct>>('/products', {
      params: { page: 1, page_size: 100 },
    }),

  startAuthorization: (
    marketplaceCode: string,
    intent: 'connect' | 'reauthorize',
    targetAccountId?: string,
  ) =>
    apiClient.post<OAuthStartResult>('/amazon/oauth/start', {
      marketplace_code: marketplaceCode,
      intent,
      target_account_id: targetAccountId ?? null,
    }),

  listMarketplaces: (accountId: string) =>
    apiClient.get<AmazonMarketplaceList>(`/amazon/accounts/${accountId}/marketplaces`),

  refreshMarketplaces: (accountId: string) =>
    apiClient.post<AmazonSyncResult>(`/amazon/accounts/${accountId}/marketplaces/refresh`),

  listListings: (
    accountId: string,
    marketplaceId: string,
    options: { page: number; pageSize: number; includeInactive: boolean },
  ) =>
    apiClient.get<PaginatedResponse<AmazonListing>>(
      `/amazon/accounts/${accountId}/marketplaces/${encodeURIComponent(marketplaceId)}/listings`,
      {
        params: {
          page: options.page,
          page_size: options.pageSize,
          include_inactive: options.includeInactive ? 'true' : 'false',
        },
      },
    ),

  syncListings: (accountId: string, marketplaceId: string) =>
    apiClient.post<AmazonSyncResult>(
      `/amazon/accounts/${accountId}/marketplaces/${encodeURIComponent(marketplaceId)}/listings/sync`,
    ),

  linkListingProduct: (
    accountId: string,
    marketplaceId: string,
    listingId: string,
    productId: string | null,
  ) =>
    apiClient.patch<AmazonListing>(
      `/amazon/accounts/${accountId}/marketplaces/${encodeURIComponent(marketplaceId)}/listings/${listingId}/product-link`,
      { product_id: productId },
    ),
};
