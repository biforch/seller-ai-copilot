import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { StrictMode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import AmazonConnectionsPage from '@/app/(dashboard)/amazon/page';
import { amazonApi, type AmazonAccount, type AmazonCatalogSnapshot, type AmazonListing, type AmazonMarketplace } from '@/app/api/amazon';
import { ApiClientError } from '@/lib/api-client-error';
import { LatestRequestGate } from '@/lib/latest-request';
import type { PaginatedResponse } from '@/types';

vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: vi.fn(),
  }),
}));

function createDeferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

const baseAccount = (id: string, region: AmazonAccount['region'] = 'na'): AmazonAccount => ({
  id,
  region,
  endpoint_mode: 'sandbox',
  status: 'active',
  last_verified_at: '2026-01-01T00:00:00.000Z',
  created_at: '2026-01-01T00:00:00.000Z',
  updated_at: '2026-01-01T00:00:00.000Z',
});

const marketplace = (
  accountSuffix: string,
  marketplaceId: string,
  name: string,
): AmazonMarketplace => ({
  marketplace_id: marketplaceId,
  marketplace_name: name,
  country_code: 'US',
  default_currency_code: 'USD',
  default_language_code: 'en_US',
  domain_name: 'amazon.com',
  participating: true,
  suspended_listings: false,
  is_active: true,
  sync_eligible: true,
  last_seen_at: '2026-01-01T00:00:00.000Z',
  created_at: '2026-01-01T00:00:00.000Z',
  updated_at: '2026-01-01T00:00:00.000Z',
});

const listing = (
  id: string,
  sellerSku: string,
  marketplaceId: string,
): AmazonListing => ({
  id,
  marketplace_id: marketplaceId,
  seller_sku: sellerSku,
  asin: `ASIN-${sellerSku}`,
  product_id: null,
  status_codes: ['BUYABLE'],
  product_type: 'PRODUCT',
  upstream_created_at: null,
  upstream_last_updated_at: null,
  is_active: true,
  first_seen_at: '2026-01-01T00:00:00.000Z',
  last_seen_at: '2026-01-01T00:00:00.000Z',
  created_at: '2026-01-01T00:00:00.000Z',
  updated_at: '2026-01-01T00:00:00.000Z',
});

const catalogSnapshot = (listingId: string): AmazonCatalogSnapshot => ({
  id: `catalog-${listingId}`,
  listing_id: listingId,
  asin: 'ASIN-1',
  marketplace_id: 'M1',
  item_name: 'Catalog title',
  brand: 'Brand',
  manufacturer: null,
  color: null,
  size: null,
  style: null,
  model_number: null,
  part_number: null,
  product_type: 'PRODUCT',
  fetched_at: '2026-01-01T00:00:00.000Z',
  expires_at: '2026-01-02T00:00:00.000Z',
  cache_hit: false,
});

function paginatedListings(
  items: AmazonListing[],
  page = 1,
  pageSize = 20,
): PaginatedResponse<AmazonListing> {
  const total = items.length;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  return {
    items,
    pagination: {
      page,
      page_size: pageSize,
      total,
      total_pages: totalPages,
      has_next: page < totalPages,
      has_previous: page > 1,
    },
  };
}

describe('AmazonConnectionsPage async races', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(amazonApi, 'listAccounts').mockResolvedValue({
      items: [baseAccount('acc-a'), baseAccount('acc-b', 'eu')],
      total: 2,
    });
    vi.spyOn(amazonApi, 'listLinkableProducts').mockResolvedValue({
      items: [],
      pagination: {
        page: 1,
        page_size: 100,
        total: 0,
        total_pages: 0,
        has_next: false,
        has_previous: false,
      },
    });
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  async function renderAndWaitForAccounts() {
    render(<AmazonConnectionsPage />);
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /NA account/i })).toBeInTheDocument();
    });
  }

  it('keeps account B marketplaces when account A resolves later', async () => {
    const accountADeferred = createDeferred<{ items: AmazonMarketplace[]; total: number }>();
    const accountBDeferred = createDeferred<{ items: AmazonMarketplace[]; total: number }>();

    vi.spyOn(amazonApi, 'listMarketplaces').mockImplementation((accountId: string) => {
      if (accountId === 'acc-a') return accountADeferred.promise;
      if (accountId === 'acc-b') return accountBDeferred.promise;
      throw new Error(`Unexpected account ${accountId}`);
    });

    const user = userEvent.setup();
    await renderAndWaitForAccounts();

    const accountBButton = screen.getByRole('button', { name: /EU account/i });
    await user.click(accountBButton);

    accountBDeferred.resolve({
      items: [marketplace('b', 'M-B1', 'Germany')],
      total: 1,
    });
    await waitFor(() => {
      expect(screen.getByText('Germany')).toBeInTheDocument();
    });

    accountADeferred.resolve({
      items: [marketplace('a', 'M-A1', 'United States')],
      total: 1,
    });

    await waitFor(() => {
      expect(screen.getByText('Germany')).toBeInTheDocument();
    });
    expect(screen.queryByText('United States')).not.toBeInTheDocument();
  });

  it('keeps marketplace M2 listings when M1 resolves later', async () => {
    const m1Deferred = createDeferred<PaginatedResponse<AmazonListing>>();
    const m2Deferred = createDeferred<PaginatedResponse<AmazonListing>>();

    vi.spyOn(amazonApi, 'listMarketplaces').mockResolvedValue({
      items: [
        marketplace('a', 'M1', 'United States'),
        marketplace('a', 'M2', 'Canada'),
      ],
      total: 2,
    });

    vi.spyOn(amazonApi, 'listListings').mockImplementation((_accountId, marketplaceId) => {
      if (marketplaceId === 'M1') return m1Deferred.promise;
      if (marketplaceId === 'M2') return m2Deferred.promise;
      throw new Error(`Unexpected marketplace ${marketplaceId}`);
    });

    const user = userEvent.setup();
    await renderAndWaitForAccounts();

    await waitFor(() => {
      expect(screen.getByText('United States')).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /Canada/i }));

    m2Deferred.resolve(paginatedListings([listing('l-ca', 'SKU-CA', 'M2')], 1, 20));
    await waitFor(() => {
      expect(screen.getByText('SKU-CA')).toBeInTheDocument();
      expect(screen.getByText(/Canada · 1 listing/i)).toBeInTheDocument();
    });

    m1Deferred.resolve(paginatedListings([listing('l-us', 'SKU-US', 'M1')], 2, 20));

    await waitFor(() => {
      expect(screen.getByText('SKU-CA')).toBeInTheDocument();
    });
    expect(screen.queryByText('SKU-US')).not.toBeInTheDocument();
    expect(screen.queryByText(/Page 2 of/)).not.toBeInTheDocument();
  });

  it('ignores stale listing errors after a newer request succeeds', async () => {
    vi.spyOn(amazonApi, 'listMarketplaces').mockResolvedValue({
      items: [
        marketplace('a', 'M1', 'United States'),
        marketplace('a', 'M2', 'Canada'),
      ],
      total: 2,
    });

    const staleDeferred = createDeferred<never>();
    const freshDeferred = createDeferred<PaginatedResponse<AmazonListing>>();

    vi.spyOn(amazonApi, 'listListings').mockImplementation((_accountId, marketplaceId) => {
      if (marketplaceId === 'M1') return staleDeferred.promise;
      return freshDeferred.promise;
    });

    const user = userEvent.setup();
    await renderAndWaitForAccounts();
    await waitFor(() => {
      expect(screen.getByText('United States')).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /Canada/i }));

    freshDeferred.resolve(paginatedListings([listing('l-ca', 'SKU-FRESH', 'M2')]));
    await waitFor(() => {
      expect(screen.getByText('SKU-FRESH')).toBeInTheDocument();
    });

    staleDeferred.reject(new ApiClientError('Stale failure', 500));
    await waitFor(() => {
      expect(screen.getByText('SKU-FRESH')).toBeInTheDocument();
    });
    expect(screen.queryByText('Stale failure')).not.toBeInTheDocument();
  });

  it('keeps listings spinner until the latest request finishes', async () => {
    vi.spyOn(amazonApi, 'listMarketplaces').mockResolvedValue({
      items: [
        marketplace('a', 'M1', 'United States'),
        marketplace('a', 'M2', 'Canada'),
      ],
      total: 2,
    });

    const staleDeferred = createDeferred<PaginatedResponse<AmazonListing>>();
    const freshDeferred = createDeferred<PaginatedResponse<AmazonListing>>();

    vi.spyOn(amazonApi, 'listListings').mockImplementation((_accountId, marketplaceId) => {
      if (marketplaceId === 'M1') return staleDeferred.promise;
      return freshDeferred.promise;
    });

    const user = userEvent.setup();
    await renderAndWaitForAccounts();
    await waitFor(() => {
      expect(screen.getByText('United States')).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /Canada/i }));

    const listingsPanel = screen.getByRole('heading', { name: 'Synced listings' }).closest('.overflow-hidden')!;
    await waitFor(() => {
      expect(listingsPanel.querySelector('.animate-spin')).toBeTruthy();
    });

    staleDeferred.resolve(paginatedListings([listing('l-us', 'SKU-US', 'M1')]));
    expect(listingsPanel.querySelector('.animate-spin')).toBeTruthy();

    freshDeferred.resolve(paginatedListings([listing('l-ca', 'SKU-CA', 'M2')]));

    await waitFor(() => {
      expect(screen.getByText('SKU-CA')).toBeInTheDocument();
    });
    expect(screen.queryByText('SKU-US')).not.toBeInTheDocument();
  });

  it('aborts in-flight requests on unmount without state update warnings', async () => {
    const marketplacesDeferred = createDeferred<{ items: AmazonMarketplace[]; total: number }>();
    let capturedSignal: AbortSignal | undefined;
    const invalidateSpy = vi.spyOn(LatestRequestGate.prototype, 'invalidate');
    vi.spyOn(amazonApi, 'listMarketplaces').mockImplementation((_accountId, signal) => {
      capturedSignal = signal;
      return marketplacesDeferred.promise;
    });

    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const { unmount } = render(<AmazonConnectionsPage />);

    await waitFor(() => {
      expect(amazonApi.listMarketplaces).toHaveBeenCalled();
      expect(capturedSignal).toBeDefined();
    });

    invalidateSpy.mockClear();
    unmount();
    expect(capturedSignal?.aborted).toBe(true);
    expect(invalidateSpy).toHaveBeenCalledTimes(4);

    marketplacesDeferred.resolve({
      items: [marketplace('a', 'M1', 'United States')],
      total: 1,
    });

    await Promise.resolve();
    expect(consoleError).not.toHaveBeenCalled();
    consoleError.mockRestore();
  });

  it('does not reload listings for a stale sync scope', async () => {
    vi.spyOn(amazonApi, 'listMarketplaces').mockResolvedValue({
      items: [
        marketplace('a', 'M1', 'United States'),
        marketplace('a', 'M2', 'Canada'),
      ],
      total: 2,
    });

    vi.spyOn(amazonApi, 'listListings').mockImplementation((_accountId, marketplaceId) => {
      if (marketplaceId === 'M1') {
        return Promise.resolve(paginatedListings([listing('l-us', 'SKU-US', 'M1')]));
      }
      return Promise.resolve(paginatedListings([listing('l-ca', 'SKU-CA', 'M2')]));
    });

    const syncDeferred = createDeferred<{
      account_id: string;
      sync_log_id: string;
      items_seen: number;
      items_written: number;
      items_deactivated: number;
      marketplace_id?: string;
    }>();

    vi.spyOn(amazonApi, 'syncListings').mockReturnValue(syncDeferred.promise);

    const user = userEvent.setup();
    await renderAndWaitForAccounts();
    await waitFor(() => {
      expect(screen.getByText('United States')).toBeInTheDocument();
    });
    await user.click(screen.getByRole('button', { name: /United States/i }));
    await waitFor(() => {
      expect(screen.getByText('SKU-US')).toBeInTheDocument();
    });

    const listListingsCallsBefore = vi.mocked(amazonApi.listListings).mock.calls.length;
    await user.click(screen.getByRole('button', { name: 'Sync listings' }));
    await user.click(screen.getByRole('button', { name: /Canada/i }));
    await waitFor(() => {
      expect(screen.getByText('SKU-CA')).toBeInTheDocument();
    });

    syncDeferred.resolve({
      account_id: 'acc-a',
      sync_log_id: 'sync-1',
      items_seen: 1,
      items_written: 1,
      items_deactivated: 0,
      marketplace_id: 'M1',
    });

    await waitFor(() => {
      expect(amazonApi.syncListings).toHaveBeenCalled();
    });

    expect(vi.mocked(amazonApi.listListings).mock.calls.length).toBe(listListingsCallsBefore + 1);
    expect(screen.queryByText(/Listing sync complete/i)).not.toBeInTheDocument();
  });

  it('does not write stale catalog refresh results', async () => {
    vi.spyOn(amazonApi, 'listMarketplaces').mockResolvedValue({
      items: [
        marketplace('a', 'M1', 'United States'),
        marketplace('a', 'M2', 'Canada'),
      ],
      total: 2,
    });

    vi.spyOn(amazonApi, 'listListings').mockImplementation((_accountId, marketplaceId) =>
      Promise.resolve(paginatedListings([listing(`l-${marketplaceId}`, `SKU-${marketplaceId}`, marketplaceId)])),
    );

    const catalogDeferred = createDeferred<AmazonCatalogSnapshot>();
    vi.spyOn(amazonApi, 'refreshListingCatalog').mockReturnValue(catalogDeferred.promise);

    const user = userEvent.setup();
    await renderAndWaitForAccounts();
    await waitFor(() => {
      expect(screen.getByText('United States')).toBeInTheDocument();
    });
    await user.click(screen.getByRole('button', { name: /United States/i }));
    await waitFor(() => {
      expect(screen.getByText('SKU-M1')).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /Load catalog summary for SKU-M1/i }));
    await user.click(screen.getByRole('button', { name: /Canada/i }));
    await waitFor(() => {
      expect(screen.getByText('SKU-M2')).toBeInTheDocument();
    });

    catalogDeferred.resolve(catalogSnapshot('l-us'));
    await Promise.resolve();

    expect(screen.queryByText('Catalog title')).not.toBeInTheDocument();
    expect(screen.queryByText(/Catalog summary refreshed/i)).not.toBeInTheDocument();
  });

  it('serializes workspace actions through the global action lock', async () => {
    vi.spyOn(amazonApi, 'listMarketplaces').mockResolvedValue({
      items: [marketplace('a', 'M1', 'United States')],
      total: 1,
    });
    vi.spyOn(amazonApi, 'listListings').mockResolvedValue(
      paginatedListings([listing('l-M1', 'SKU-M1', 'M1')]),
    );

    const syncDeferred = createDeferred<{
      account_id: string;
      sync_log_id: string;
      items_seen: number;
      items_written: number;
      items_deactivated: number;
    }>();
    vi.spyOn(amazonApi, 'syncListings').mockReturnValue(syncDeferred.promise);

    const user = userEvent.setup();
    await renderAndWaitForAccounts();
    await waitFor(() => {
      expect(screen.getByText('United States')).toBeInTheDocument();
    });
    await user.click(screen.getByRole('button', { name: /United States/i }));
    await waitFor(() => {
      expect(screen.getByText('SKU-M1')).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: 'Sync listings' }));

    expect(screen.getByRole('button', { name: 'Sync listings' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Refresh marketplaces' })).toBeDisabled();
    expect(
      screen.getByRole('button', { name: /Load catalog summary for SKU-M1/i }),
    ).toBeDisabled();

    syncDeferred.resolve({
      account_id: 'acc-a',
      sync_log_id: 'sync-1',
      items_seen: 1,
      items_written: 1,
      items_deactivated: 0,
    });
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Sync listings' })).not.toBeDisabled();
    });
  });

  it('does not apply stale link results after account switch', async () => {
    vi.spyOn(amazonApi, 'listMarketplaces').mockImplementation((accountId) => {
      if (accountId === 'acc-a') {
        return Promise.resolve({
          items: [marketplace('a', 'M1', 'United States')],
          total: 1,
        });
      }
      return Promise.resolve({
        items: [marketplace('b', 'M-B1', 'Germany')],
        total: 1,
      });
    });

    vi.spyOn(amazonApi, 'listListings').mockImplementation((_accountId, marketplaceId) =>
      Promise.resolve(paginatedListings([listing(`l-${marketplaceId}`, `SKU-${marketplaceId}`, marketplaceId)])),
    );

    vi.spyOn(amazonApi, 'listLinkableProducts').mockResolvedValue({
      items: [{ id: 'prod-1', project_id: 'proj-1', name: 'Product One', category: null, platform: 'amazon', market: 'US' }],
      pagination: {
        page: 1,
        page_size: 100,
        total: 1,
        total_pages: 1,
        has_next: false,
        has_previous: false,
      },
    });

    const linkDeferred = createDeferred<AmazonListing>();
    vi.spyOn(amazonApi, 'linkListingProduct').mockReturnValue(linkDeferred.promise);

    const user = userEvent.setup();
    await renderAndWaitForAccounts();
    await waitFor(() => {
      expect(screen.getByText('United States')).toBeInTheDocument();
    });
    await user.click(screen.getByRole('button', { name: /United States/i }));
    await waitFor(() => {
      expect(screen.getByText('SKU-M1')).toBeInTheDocument();
    });

    const productSelect = screen.getByRole('combobox', { name: /SellerAI product for SKU-M1/i });
    await user.selectOptions(productSelect, 'prod-1');
    await user.click(screen.getByRole('button', { name: /EU account/i }));
    await waitFor(() => {
      expect(screen.getByText('Germany')).toBeInTheDocument();
    });

    linkDeferred.resolve({
      ...listing('l-M1', 'SKU-M1', 'M1'),
      product_id: 'prod-1',
    });
    await Promise.resolve();

    expect(screen.queryByText('Listing linked to a SellerAI product.')).not.toBeInTheDocument();
    expect(screen.getByText('SKU-M-B1')).toBeInTheDocument();
  });

  it('rejects stale listing success after account switch before a new listings fetch', async () => {
    const staleListings = createDeferred<PaginatedResponse<AmazonListing>>();
    const nextMarketplaces = createDeferred<{ items: AmazonMarketplace[]; total: number }>();

    vi.spyOn(amazonApi, 'listMarketplaces').mockImplementation((accountId: string) => {
      if (accountId === 'acc-a') {
        return Promise.resolve({ items: [marketplace('a', 'M1', 'United States')], total: 1 });
      }
      return nextMarketplaces.promise;
    });
    vi.spyOn(amazonApi, 'listListings').mockImplementation((_accountId, marketplaceId) => {
      if (marketplaceId === 'M1') return staleListings.promise;
      throw new Error(`Unexpected marketplace ${marketplaceId}`);
    });

    const user = userEvent.setup();
    await renderAndWaitForAccounts();
    await waitFor(() => {
      expect(amazonApi.listListings).toHaveBeenCalled();
    });
    const listingCalls = vi.mocked(amazonApi.listListings).mock.calls.length;

    await user.click(screen.getByRole('button', { name: /EU account/i }));
    expect(vi.mocked(amazonApi.listListings).mock.calls.length).toBe(listingCalls);

    staleListings.resolve(paginatedListings([listing('l-us', 'SKU-STALE', 'M1')]));
    await Promise.resolve();
    await Promise.resolve();

    expect(screen.queryByText('SKU-STALE')).not.toBeInTheDocument();
    expect(screen.queryByText('United States')).not.toBeInTheDocument();
  });

  it('rejects stale listing failure after account switch before a new listings fetch', async () => {
    const staleListings = createDeferred<PaginatedResponse<AmazonListing>>();
    const nextMarketplaces = createDeferred<{ items: AmazonMarketplace[]; total: number }>();

    vi.spyOn(amazonApi, 'listMarketplaces').mockImplementation((accountId: string) => {
      if (accountId === 'acc-a') {
        return Promise.resolve({ items: [marketplace('a', 'M1', 'United States')], total: 1 });
      }
      return nextMarketplaces.promise;
    });
    vi.spyOn(amazonApi, 'listListings').mockImplementation((_accountId, marketplaceId) => {
      if (marketplaceId === 'M1') return staleListings.promise;
      throw new Error(`Unexpected marketplace ${marketplaceId}`);
    });

    const user = userEvent.setup();
    await renderAndWaitForAccounts();
    await waitFor(() => {
      expect(amazonApi.listListings).toHaveBeenCalled();
    });

    await user.click(screen.getByRole('button', { name: /EU account/i }));
    staleListings.reject(new ApiClientError('Stale listing failure', 500));
    await Promise.resolve();
    await Promise.resolve();

    expect(screen.queryByText('Stale listing failure')).not.toBeInTheDocument();
    expect(screen.queryByText('SKU-STALE')).not.toBeInTheDocument();
  });

  it('rejects a stale marketplace listing response after marketplace switch before the new result', async () => {
    const m1Deferred = createDeferred<PaginatedResponse<AmazonListing>>();
    const m2Deferred = createDeferred<PaginatedResponse<AmazonListing>>();

    vi.spyOn(amazonApi, 'listMarketplaces').mockResolvedValue({
      items: [
        marketplace('a', 'M1', 'United States'),
        marketplace('a', 'M2', 'Canada'),
      ],
      total: 2,
    });
    vi.spyOn(amazonApi, 'listListings').mockImplementation((_accountId, marketplaceId) => {
      if (marketplaceId === 'M1') return m1Deferred.promise;
      if (marketplaceId === 'M2') return m2Deferred.promise;
      throw new Error(`Unexpected marketplace ${marketplaceId}`);
    });

    const user = userEvent.setup();
    await renderAndWaitForAccounts();
    await waitFor(() => {
      expect(screen.getByText('United States')).toBeInTheDocument();
    });
    await waitFor(() => {
      expect(amazonApi.listListings).toHaveBeenCalled();
    });

    await user.click(screen.getByRole('button', { name: /Canada/i }));
    m1Deferred.resolve(paginatedListings([listing('l-us', 'SKU-US-STALE', 'M1')]));
    await Promise.resolve();
    await Promise.resolve();

    expect(screen.queryByText('SKU-US-STALE')).not.toBeInTheDocument();
    const listingsPanel = screen.getByRole('heading', { name: 'Synced listings' }).closest('.overflow-hidden')!;
    expect(listingsPanel.querySelector('.animate-spin')).toBeTruthy();
  });

  it('rejects a stale includeInactive response before the new listings result', async () => {
    const activeDeferred = createDeferred<PaginatedResponse<AmazonListing>>();
    const inactiveDeferred = createDeferred<PaginatedResponse<AmazonListing>>();

    vi.spyOn(amazonApi, 'listMarketplaces').mockResolvedValue({
      items: [marketplace('a', 'M1', 'United States')],
      total: 1,
    });
    vi.spyOn(amazonApi, 'listListings').mockImplementation((_accountId, _marketplaceId, options) => {
      if (options.includeInactive) return inactiveDeferred.promise;
      return activeDeferred.promise;
    });

    const user = userEvent.setup();
    await renderAndWaitForAccounts();
    await waitFor(() => {
      expect(screen.getByText('United States')).toBeInTheDocument();
    });
    await waitFor(() => {
      expect(amazonApi.listListings).toHaveBeenCalled();
    });

    await user.click(screen.getByRole('checkbox', { name: /Include inactive/i }));
    activeDeferred.resolve(paginatedListings([listing('l-active', 'SKU-ACTIVE-STALE', 'M1')]));
    await Promise.resolve();
    await Promise.resolve();

    expect(screen.queryByText('SKU-ACTIVE-STALE')).not.toBeInTheDocument();
  });

  it('writes the auto-selected account ref so clicking it does not retrigger marketplaces', async () => {
    vi.spyOn(amazonApi, 'listMarketplaces').mockResolvedValue({
      items: [marketplace('a', 'M1', 'United States')],
      total: 1,
    });
    vi.spyOn(amazonApi, 'listListings').mockResolvedValue(paginatedListings([]));

    const user = userEvent.setup();
    await renderAndWaitForAccounts();
    await waitFor(() => {
      expect(screen.getByText('United States')).toBeInTheDocument();
    });
    const marketplaceCalls = vi.mocked(amazonApi.listMarketplaces).mock.calls.length;

    await user.click(screen.getByRole('button', { name: /NA account/i }));
    expect(vi.mocked(amazonApi.listMarketplaces).mock.calls.length).toBe(marketplaceCalls);
  });

  it('writes the auto-selected marketplace ref so clicking it does not retrigger listings', async () => {
    vi.spyOn(amazonApi, 'listMarketplaces').mockResolvedValue({
      items: [marketplace('a', 'M1', 'United States')],
      total: 1,
    });
    vi.spyOn(amazonApi, 'listListings').mockResolvedValue(
      paginatedListings([listing('l-us', 'SKU-US', 'M1')]),
    );

    const user = userEvent.setup();
    await renderAndWaitForAccounts();
    await waitFor(() => {
      expect(screen.getByText('SKU-US')).toBeInTheDocument();
    });
    const listingCalls = vi.mocked(amazonApi.listListings).mock.calls.length;

    await user.click(screen.getByRole('button', { name: /United States/i }));
    expect(vi.mocked(amazonApi.listListings).mock.calls.length).toBe(listingCalls);
  });

  it('selects the remaining account when a refresh removes the current account', async () => {
    let accountItems = [baseAccount('acc-a'), baseAccount('acc-b', 'eu')];
    vi.mocked(amazonApi.listAccounts).mockImplementation(async () => ({
      items: accountItems,
      total: accountItems.length,
    }));
    vi.spyOn(amazonApi, 'listMarketplaces').mockImplementation(async (accountId: string) => {
      if (accountId === 'acc-a') {
        return { items: [marketplace('a', 'M1', 'United States')], total: 1 };
      }
      return { items: [marketplace('b', 'M-B1', 'Germany')], total: 1 };
    });
    vi.spyOn(amazonApi, 'listListings').mockImplementation(async (_accountId, marketplaceId) =>
      paginatedListings([listing(`l-${marketplaceId}`, `SKU-${marketplaceId}`, marketplaceId)]),
    );
    vi.spyOn(amazonApi, 'refreshMarketplaces').mockResolvedValue({
      account_id: 'acc-b',
      sync_log_id: 'mp-1',
      items_seen: 1,
      items_written: 1,
      items_deactivated: 0,
    });

    const user = userEvent.setup();
    await renderAndWaitForAccounts();
    await user.click(screen.getByRole('button', { name: /EU account/i }));
    await waitFor(() => {
      expect(screen.getByText('Germany')).toBeInTheDocument();
    });

    accountItems = [baseAccount('acc-a')];
    await user.click(screen.getByRole('button', { name: 'Refresh marketplaces' }));

    await waitFor(() => {
      expect(screen.queryByRole('button', { name: /EU account/i })).not.toBeInTheDocument();
    });
    expect(screen.getByRole('button', { name: /NA account/i })).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText('United States')).toBeInTheDocument();
    });
    expect(screen.queryByText('Germany')).not.toBeInTheDocument();
  });

  it('selects a remaining marketplace when refresh removes the current marketplace', async () => {
    let marketplaceItems = [
      marketplace('a', 'M1', 'United States'),
      marketplace('a', 'M2', 'Canada'),
    ];
    vi.spyOn(amazonApi, 'listMarketplaces').mockImplementation(async () => ({
      items: marketplaceItems,
      total: marketplaceItems.length,
    }));
    vi.spyOn(amazonApi, 'listListings').mockImplementation(async (_accountId, marketplaceId) =>
      paginatedListings([listing(`l-${marketplaceId}`, `SKU-${marketplaceId}`, marketplaceId)]),
    );
    vi.spyOn(amazonApi, 'refreshMarketplaces').mockResolvedValue({
      account_id: 'acc-a',
      sync_log_id: 'mp-2',
      items_seen: 1,
      items_written: 1,
      items_deactivated: 0,
    });

    const user = userEvent.setup();
    await renderAndWaitForAccounts();
    await waitFor(() => {
      expect(screen.getByText('United States')).toBeInTheDocument();
    });
    await user.click(screen.getByRole('button', { name: /Canada/i }));
    await waitFor(() => {
      expect(screen.getByText('SKU-M2')).toBeInTheDocument();
    });

    marketplaceItems = [marketplace('a', 'M1', 'United States')];
    await user.click(screen.getByRole('button', { name: 'Refresh marketplaces' }));

    await waitFor(() => {
      expect(screen.queryByRole('button', { name: /Canada/i })).not.toBeInTheDocument();
    });
    await waitFor(() => {
      expect(screen.getByText('SKU-M1')).toBeInTheDocument();
    });
    expect(screen.queryByText('SKU-M2')).not.toBeInTheDocument();
  });

  it('clears listings after a failed load so later actions cannot use stale rows', async () => {
    vi.spyOn(amazonApi, 'listMarketplaces').mockResolvedValue({
      items: [marketplace('a', 'M1', 'United States')],
      total: 1,
    });
    vi.spyOn(amazonApi, 'listListings').mockRejectedValue(new ApiClientError('Listing load failed', 500));

    await renderAndWaitForAccounts();
    await waitFor(() => {
      expect(screen.getByText('Listing load failed')).toBeInTheDocument();
    });
    expect(screen.queryByText(/SKU-/)).not.toBeInTheDocument();
    expect(screen.getByText(/No synced listings/i)).toBeInTheDocument();
  });

  it('updates the latest listings snapshot when linking a product', async () => {
    vi.spyOn(amazonApi, 'listMarketplaces').mockResolvedValue({
      items: [marketplace('a', 'M1', 'United States')],
      total: 1,
    });
    vi.spyOn(amazonApi, 'listListings').mockResolvedValue(
      paginatedListings([listing('l-M1', 'SKU-M1', 'M1')]),
    );
    vi.spyOn(amazonApi, 'listLinkableProducts').mockResolvedValue({
      items: [{ id: 'prod-1', project_id: 'proj-1', name: 'Product One', category: null, platform: 'amazon', market: 'US' }],
      pagination: {
        page: 1,
        page_size: 100,
        total: 1,
        total_pages: 1,
        has_next: false,
        has_previous: false,
      },
    });
    vi.spyOn(amazonApi, 'linkListingProduct').mockResolvedValue({
      ...listing('l-M1', 'SKU-M1', 'M1'),
      product_id: 'prod-1',
    });

    const user = userEvent.setup();
    await renderAndWaitForAccounts();
    await waitFor(() => {
      expect(screen.getByText('SKU-M1')).toBeInTheDocument();
    });

    await user.selectOptions(
      screen.getByRole('combobox', { name: /SellerAI product for SKU-M1/i }),
      'prod-1',
    );
    await waitFor(() => {
      expect(screen.getByText('Listing linked to a SellerAI product.')).toBeInTheDocument();
    });
    expect(screen.getByRole('combobox', { name: /SellerAI product for SKU-M1/i })).toHaveValue('prod-1');
  });

  it('aborts the first StrictMode accounts request and keeps loading until the latest lease finishes', async () => {
    const accountsDeferred = createDeferred<{ items: AmazonAccount[]; total: number }>();
    vi.mocked(amazonApi.listAccounts).mockImplementation(() => accountsDeferred.promise);
    vi.spyOn(amazonApi, 'listMarketplaces').mockResolvedValue({ items: [], total: 0 });

    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    render(
      <StrictMode>
        <AmazonConnectionsPage />
      </StrictMode>,
    );

    await waitFor(() => {
      expect(vi.mocked(amazonApi.listAccounts).mock.calls.length).toBeGreaterThanOrEqual(2);
    });
    expect(document.querySelector('.animate-spin')).toBeTruthy();

    accountsDeferred.resolve({
      items: [baseAccount('acc-a'), baseAccount('acc-b', 'eu')],
      total: 2,
    });

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /NA account/i })).toBeInTheDocument();
    });
    expect(consoleError).not.toHaveBeenCalled();
    consoleError.mockRestore();
  });

  it('does not start OAuth twice for a single connect click in StrictMode', async () => {
    vi.spyOn(amazonApi, 'listAccounts').mockResolvedValue({ items: [], total: 0 });
    const startDeferred = createDeferred<{
      authorization_url: string;
      marketplace_code: string;
      region: string;
      expires_at: string;
    }>();
    vi.spyOn(amazonApi, 'startAuthorization').mockReturnValue(startDeferred.promise);

    const user = userEvent.setup();
    render(
      <StrictMode>
        <AmazonConnectionsPage />
      </StrictMode>,
    );
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Connect Amazon/i })).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /Connect Amazon/i }));
    expect(amazonApi.startAuthorization).toHaveBeenCalledTimes(1);
  });
});

describe('AmazonConnectionsPage listing write paths', () => {
  it('routes every listings state write through commitListings', () => {
    const source = readFileSync(
      path.join(process.cwd(), 'app/(dashboard)/amazon/page.tsx'),
      'utf8',
    );
    const helperStart = source.indexOf('function commitListings(');
    const helperEnd = source.indexOf('function statusStyle(');
    expect(helperStart).toBeGreaterThan(-1);
    expect(helperEnd).toBeGreaterThan(helperStart);

    const helper = source.slice(helperStart, helperEnd);
    const rest = `${source.slice(0, helperStart)}${source.slice(helperEnd)}`;
    expect(helper).toContain('listingsRef.current = next');
    expect(helper).toContain('setListings(next)');
    expect(rest).not.toMatch(/setListings\(/);
    expect(rest).not.toMatch(/listingsRef\.current\s*=/);
  });
});
