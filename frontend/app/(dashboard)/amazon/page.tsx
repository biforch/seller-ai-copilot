'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertCircle,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  Link2,
  Loader2,
  RefreshCw,
  RotateCcw,
  Store,
} from 'lucide-react';

import {
  amazonApi,
  type AmazonAccount,
  type AmazonListing,
  type AmazonLinkProduct,
  type AmazonMarketplace,
} from '@/app/api/amazon';
import { ApiClientError } from '@/lib/api-client-error';

const MARKETPLACE_CODES = ['US', 'CA', 'MX', 'BR', 'UK', 'DE', 'FR', 'IT', 'ES', 'JP', 'AU'];
const PAGE_SIZE = 20;
const REGION_REAUTH_MARKETPLACE: Record<AmazonAccount['region'], string> = {
  na: 'US',
  eu: 'UK',
  fe: 'JP',
};

function formatDate(value: string | null) {
  if (!value) return 'Not yet';
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value));
}

function errorMessage(error: unknown) {
  if (error instanceof ApiClientError) return error.message;
  return 'Something went wrong. Please try again.';
}

function statusStyle(status: AmazonAccount['status']) {
  if (status === 'active') return 'bg-emerald-50 text-emerald-700 border-emerald-200';
  if (status === 'reauthorization_required') return 'bg-amber-50 text-amber-700 border-amber-200';
  if (status === 'disabled') return 'bg-slate-100 text-slate-600 border-slate-200';
  return 'bg-red-50 text-red-700 border-red-200';
}

export default function AmazonConnectionsPage() {
  const [accounts, setAccounts] = useState<AmazonAccount[]>([]);
  const [selectedAccountId, setSelectedAccountId] = useState<string | null>(null);
  const [marketplaces, setMarketplaces] = useState<AmazonMarketplace[]>([]);
  const [selectedMarketplaceId, setSelectedMarketplaceId] = useState<string | null>(null);
  const [listings, setListings] = useState<AmazonListing[]>([]);
  const [products, setProducts] = useState<AmazonLinkProduct[]>([]);
  const [marketplaceCode, setMarketplaceCode] = useState('US');
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(0);
  const [totalListings, setTotalListings] = useState(0);
  const [includeInactive, setIncludeInactive] = useState(false);
  const [loadingAccounts, setLoadingAccounts] = useState(true);
  const [loadingMarketplaces, setLoadingMarketplaces] = useState(false);
  const [loadingListings, setLoadingListings] = useState(false);
  const [action, setAction] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const selectedAccount = useMemo(
    () => accounts.find((account) => account.id === selectedAccountId) ?? null,
    [accounts, selectedAccountId],
  );
  const selectedMarketplace = useMemo(
    () => marketplaces.find((item) => item.marketplace_id === selectedMarketplaceId) ?? null,
    [marketplaces, selectedMarketplaceId],
  );

  const loadAccounts = useCallback(async () => {
    setLoadingAccounts(true);
    setError(null);
    try {
      const result = await amazonApi.listAccounts();
      setAccounts(result.items);
      setSelectedAccountId((current) => {
        if (current && result.items.some((account) => account.id === current)) return current;
        return result.items[0]?.id ?? null;
      });
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setLoadingAccounts(false);
    }
  }, []);

  const loadProducts = useCallback(async () => {
    try {
      const result = await amazonApi.listLinkableProducts();
      setProducts(result.items);
    } catch (requestError) {
      setError(errorMessage(requestError));
    }
  }, []);

  const loadMarketplaces = useCallback(async (accountId: string) => {
    setLoadingMarketplaces(true);
    setError(null);
    try {
      const result = await amazonApi.listMarketplaces(accountId);
      setMarketplaces(result.items);
      setSelectedMarketplaceId((current) => {
        if (current && result.items.some((item) => item.marketplace_id === current)) return current;
        return result.items.find((item) => item.sync_eligible)?.marketplace_id ?? result.items[0]?.marketplace_id ?? null;
      });
    } catch (requestError) {
      setMarketplaces([]);
      setSelectedMarketplaceId(null);
      setError(errorMessage(requestError));
    } finally {
      setLoadingMarketplaces(false);
    }
  }, []);

  const loadListings = useCallback(
    async (accountId: string, marketplaceId: string, targetPage: number) => {
      setLoadingListings(true);
      setError(null);
      try {
        const result = await amazonApi.listListings(accountId, marketplaceId, {
          page: targetPage,
          pageSize: PAGE_SIZE,
          includeInactive,
        });
        setListings(result.items);
        setPage(result.pagination.page);
        setTotalPages(result.pagination.total_pages);
        setTotalListings(result.pagination.total);
      } catch (requestError) {
        setListings([]);
        setError(errorMessage(requestError));
      } finally {
        setLoadingListings(false);
      }
    },
    [includeInactive],
  );

  useEffect(() => {
    void loadAccounts();
    void loadProducts();
  }, [loadAccounts, loadProducts]);

  useEffect(() => {
    if (!selectedAccountId) {
      setMarketplaces([]);
      return;
    }
    setSelectedMarketplaceId(null);
    setListings([]);
    void loadMarketplaces(selectedAccountId);
  }, [loadMarketplaces, selectedAccountId]);

  useEffect(() => {
    if (!selectedAccountId || !selectedMarketplaceId) {
      setListings([]);
      return;
    }
    void loadListings(selectedAccountId, selectedMarketplaceId, 1);
  }, [includeInactive, loadListings, selectedAccountId, selectedMarketplaceId]);

  const startOAuth = async (intent: 'connect' | 'reauthorize', accountId?: string) => {
    setAction(intent === 'connect' ? 'connect' : `reauthorize:${accountId}`);
    setError(null);
    try {
      const targetAccount = accounts.find((account) => account.id === accountId);
      const authorizationMarketplace =
        intent === 'reauthorize' && targetAccount
          ? REGION_REAUTH_MARKETPLACE[targetAccount.region]
          : marketplaceCode;
      const result = await amazonApi.startAuthorization(
        authorizationMarketplace,
        intent,
        accountId,
      );
      window.location.assign(result.authorization_url);
    } catch (requestError) {
      setError(errorMessage(requestError));
      setAction(null);
    }
  };

  const refreshMarketplaces = async () => {
    if (!selectedAccountId) return;
    setAction('refresh-marketplaces');
    setError(null);
    try {
      const result = await amazonApi.refreshMarketplaces(selectedAccountId);
      setNotice(`Marketplace refresh complete: ${result.items_written} updated.`);
      await Promise.all([loadAccounts(), loadMarketplaces(selectedAccountId)]);
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setAction(null);
    }
  };

  const syncListings = async () => {
    if (!selectedAccountId || !selectedMarketplaceId) return;
    setAction('sync-listings');
    setError(null);
    try {
      const result = await amazonApi.syncListings(selectedAccountId, selectedMarketplaceId);
      setNotice(`Listing sync complete: ${result.items_written} written, ${result.items_deactivated} deactivated.`);
      await loadListings(selectedAccountId, selectedMarketplaceId, 1);
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setAction(null);
    }
  };

  const linkProduct = async (listingId: string, productId: string | null) => {
    if (!selectedAccountId || !selectedMarketplaceId) return;
    setAction(`link:${listingId}`);
    setError(null);
    try {
      const updated = await amazonApi.linkListingProduct(
        selectedAccountId,
        selectedMarketplaceId,
        listingId,
        productId,
      );
      setListings((current) =>
        current.map((listing) => (listing.id === updated.id ? updated : listing)),
      );
      setNotice(productId ? 'Listing linked to a SellerAI product.' : 'Listing unlinked.');
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setAction(null);
    }
  };

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="text-sm font-semibold uppercase tracking-wider text-orange-600">Amazon workspace</p>
          <h1 className="mt-1 text-3xl font-bold text-slate-950">Connections & listings</h1>
          <p className="mt-2 max-w-2xl text-slate-600">
            Connect Seller Central, refresh eligible marketplaces, and bring your live listing identities into SellerAI.
          </p>
        </div>
        <div className="flex items-center gap-2 rounded-xl border bg-white p-2 shadow-sm">
          <select
            aria-label="Seller Central marketplace"
            value={marketplaceCode}
            onChange={(event) => setMarketplaceCode(event.target.value)}
            className="rounded-lg border-0 bg-slate-50 px-3 py-2 text-sm font-medium text-slate-700 focus:ring-2 focus:ring-orange-500"
          >
            {MARKETPLACE_CODES.map((code) => <option key={code}>{code}</option>)}
          </select>
          <button
            onClick={() => void startOAuth('connect')}
            disabled={action !== null}
            className="inline-flex items-center gap-2 rounded-lg bg-orange-500 px-4 py-2 text-sm font-semibold text-white transition hover:bg-orange-600 disabled:opacity-50"
          >
            {action === 'connect' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Link2 className="h-4 w-4" />}
            Connect Amazon
          </button>
        </div>
      </div>

      {error && (
        <div className="flex items-start gap-3 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800">
          <AlertCircle className="mt-0.5 h-5 w-5 shrink-0" />
          <span>{error}</span>
        </div>
      )}
      {notice && (
        <div className="flex items-start gap-3 rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-800">
          <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0" />
          <span>{notice}</span>
        </div>
      )}

      <div className="grid gap-6 xl:grid-cols-[340px_minmax(0,1fr)]">
        <aside className="rounded-2xl border bg-white p-4 shadow-sm">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="font-semibold text-slate-900">Connected accounts</h2>
            <span className="rounded-full bg-slate-100 px-2 py-1 text-xs font-semibold text-slate-600">{accounts.length}</span>
          </div>
          {loadingAccounts ? (
            <div className="flex justify-center py-12"><Loader2 className="h-6 w-6 animate-spin text-orange-500" /></div>
          ) : accounts.length === 0 ? (
            <div className="rounded-xl border border-dashed p-6 text-center">
              <Store className="mx-auto h-8 w-8 text-slate-400" />
              <p className="mt-3 font-medium text-slate-800">No Amazon account yet</p>
              <p className="mt-1 text-sm text-slate-500">Choose a marketplace above to connect Seller Central.</p>
            </div>
          ) : (
            <div className="space-y-2">
              {accounts.map((account) => (
                <button
                  key={account.id}
                  onClick={() => setSelectedAccountId(account.id)}
                  className={`w-full rounded-xl border p-4 text-left transition ${selectedAccountId === account.id ? 'border-orange-300 bg-orange-50/60 ring-1 ring-orange-200' : 'hover:border-slate-300 hover:bg-slate-50'}`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <p className="font-semibold text-slate-900">{account.region.toUpperCase()} account</p>
                      <p className="mt-1 text-xs text-slate-500">Updated {formatDate(account.updated_at)}</p>
                    </div>
                    <span className={`rounded-full border px-2 py-1 text-[11px] font-semibold ${statusStyle(account.status)}`}>
                      {account.status.replaceAll('_', ' ')}
                    </span>
                  </div>
                </button>
              ))}
            </div>
          )}
        </aside>

        <section className="space-y-6">
          {!selectedAccount ? (
            <div className="rounded-2xl border border-dashed bg-white p-12 text-center text-slate-500">Select or connect an Amazon account to continue.</div>
          ) : (
            <>
              <div className="rounded-2xl border bg-white p-5 shadow-sm">
                <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                  <div>
                    <div className="flex items-center gap-2">
                      <h2 className="text-lg font-semibold text-slate-950">Marketplace access</h2>
                      <span className="text-sm text-slate-500">{selectedAccount.region.toUpperCase()} · {selectedAccount.endpoint_mode}</span>
                    </div>
                    <p className="mt-1 text-sm text-slate-500">Last verified: {formatDate(selectedAccount.last_verified_at)}</p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {selectedAccount.status !== 'active' && (
                      <button
                        onClick={() => void startOAuth('reauthorize', selectedAccount.id)}
                        disabled={action !== null}
                        className="inline-flex items-center gap-2 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm font-semibold text-amber-800 hover:bg-amber-100 disabled:opacity-50"
                      >
                        <RotateCcw className="h-4 w-4" /> Reauthorize
                      </button>
                    )}
                    <button
                      onClick={() => void refreshMarketplaces()}
                      disabled={action !== null || selectedAccount.status !== 'active'}
                      className="inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                    >
                      <RefreshCw className={`h-4 w-4 ${action === 'refresh-marketplaces' ? 'animate-spin' : ''}`} />
                      Refresh marketplaces
                    </button>
                  </div>
                </div>

                <div className="mt-5 grid gap-3 md:grid-cols-2">
                  {loadingMarketplaces ? (
                    <div className="col-span-full flex justify-center py-8"><Loader2 className="h-6 w-6 animate-spin text-orange-500" /></div>
                  ) : marketplaces.length === 0 ? (
                    <div className="col-span-full rounded-xl border border-dashed p-6 text-center text-sm text-slate-500">
                      Refresh marketplace access to discover where this seller can sync listings.
                    </div>
                  ) : marketplaces.map((marketplace) => (
                    <button
                      key={marketplace.marketplace_id}
                      onClick={() => setSelectedMarketplaceId(marketplace.marketplace_id)}
                      className={`rounded-xl border p-4 text-left transition ${selectedMarketplaceId === marketplace.marketplace_id ? 'border-blue-300 bg-blue-50/60 ring-1 ring-blue-200' : 'hover:bg-slate-50'}`}
                    >
                      <div className="flex items-center justify-between gap-3">
                        <div>
                          <p className="font-semibold text-slate-900">{marketplace.marketplace_name}</p>
                          <p className="mt-1 text-xs text-slate-500">{marketplace.country_code} · {marketplace.default_currency_code ?? 'Currency unavailable'}</p>
                        </div>
                        <span className={`rounded-full px-2 py-1 text-xs font-semibold ${marketplace.sync_eligible ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-600'}`}>
                          {marketplace.sync_eligible ? 'Sync ready' : 'Unavailable'}
                        </span>
                      </div>
                    </button>
                  ))}
                </div>
              </div>

              {selectedMarketplace && (
                <div className="overflow-hidden rounded-2xl border bg-white shadow-sm">
                  <div className="flex flex-col gap-4 border-b p-5 sm:flex-row sm:items-center sm:justify-between">
                    <div>
                      <h2 className="text-lg font-semibold text-slate-950">Synced listings</h2>
                      <p className="mt-1 text-sm text-slate-500">{selectedMarketplace.marketplace_name} · {totalListings} listing{totalListings === 1 ? '' : 's'}</p>
                    </div>
                    <div className="flex flex-wrap items-center gap-3">
                      <label className="flex items-center gap-2 text-sm text-slate-600">
                        <input
                          type="checkbox"
                          checked={includeInactive}
                          onChange={(event) => setIncludeInactive(event.target.checked)}
                          className="rounded border-slate-300 text-orange-500 focus:ring-orange-500"
                        />
                        Include inactive
                      </label>
                      <button
                        onClick={() => void syncListings()}
                        disabled={action !== null || !selectedMarketplace.sync_eligible}
                        className="inline-flex items-center gap-2 rounded-lg bg-slate-950 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-800 disabled:opacity-50"
                      >
                        {action === 'sync-listings' ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                        Sync listings
                      </button>
                    </div>
                  </div>

                  {loadingListings ? (
                    <div className="flex justify-center py-16"><Loader2 className="h-7 w-7 animate-spin text-orange-500" /></div>
                  ) : listings.length === 0 ? (
                    <div className="p-12 text-center">
                      <Store className="mx-auto h-9 w-9 text-slate-300" />
                      <p className="mt-3 font-medium text-slate-700">No synced listings</p>
                      <p className="mt-1 text-sm text-slate-500">Run a listing sync to import seller SKU identities.</p>
                    </div>
                  ) : (
                    <div className="overflow-x-auto">
                      <table className="min-w-full divide-y divide-slate-200 text-sm">
                        <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                          <tr><th className="px-5 py-3">SKU</th><th className="px-5 py-3">ASIN</th><th className="px-5 py-3">SellerAI product</th><th className="px-5 py-3">Product type</th><th className="px-5 py-3">Status</th><th className="px-5 py-3">Last seen</th></tr>
                        </thead>
                        <tbody className="divide-y divide-slate-100">
                          {listings.map((listing) => (
                            <tr key={listing.id} className="hover:bg-slate-50/70">
                              <td className="whitespace-nowrap px-5 py-4 font-medium text-slate-900">{listing.seller_sku}</td>
                              <td className="whitespace-nowrap px-5 py-4 text-slate-600">{listing.asin ?? '—'}</td>
                              <td className="min-w-56 px-5 py-4">
                                <div className="flex items-center gap-2">
                                  <select
                                    aria-label={`SellerAI product for ${listing.seller_sku}`}
                                    value={listing.product_id ?? ''}
                                    disabled={action !== null}
                                    onChange={(event) =>
                                      void linkProduct(listing.id, event.target.value || null)
                                    }
                                    className="w-full rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-sm text-slate-700 focus:border-orange-400 focus:ring-orange-400 disabled:opacity-50"
                                  >
                                    <option value="">Unlinked</option>
                                    {listing.product_id && !products.some((product) => product.id === listing.product_id) && (
                                      <option value={listing.product_id}>Linked product</option>
                                    )}
                                    {products.map((product) => (
                                      <option key={product.id} value={product.id}>{product.name}</option>
                                    ))}
                                  </select>
                                  {action === `link:${listing.id}` && (
                                    <Loader2 className="h-4 w-4 shrink-0 animate-spin text-orange-500" />
                                  )}
                                </div>
                              </td>
                              <td className="whitespace-nowrap px-5 py-4 text-slate-600">{listing.product_type ?? '—'}</td>
                              <td className="px-5 py-4"><span className={`rounded-full px-2 py-1 text-xs font-semibold ${listing.is_active ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-500'}`}>{listing.is_active ? listing.status_codes.join(', ') || 'Active' : 'Inactive'}</span></td>
                              <td className="whitespace-nowrap px-5 py-4 text-slate-500">{formatDate(listing.last_seen_at)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}

                  {totalPages > 1 && (
                    <div className="flex items-center justify-between border-t px-5 py-4 text-sm text-slate-600">
                      <span>Page {page} of {totalPages}</span>
                      <div className="flex gap-2">
                        <button disabled={page <= 1 || loadingListings} onClick={() => selectedAccountId && selectedMarketplaceId && void loadListings(selectedAccountId, selectedMarketplaceId, page - 1)} className="rounded-lg border p-2 hover:bg-slate-50 disabled:opacity-40" aria-label="Previous page"><ChevronLeft className="h-4 w-4" /></button>
                        <button disabled={page >= totalPages || loadingListings} onClick={() => selectedAccountId && selectedMarketplaceId && void loadListings(selectedAccountId, selectedMarketplaceId, page + 1)} className="rounded-lg border p-2 hover:bg-slate-50 disabled:opacity-40" aria-label="Next page"><ChevronRight className="h-4 w-4" /></button>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </>
          )}
        </section>
      </div>

      <div className="flex items-center gap-2 text-xs text-slate-500">
        <ExternalLink className="h-3.5 w-3.5" />
        SellerAI reads listing identities only. Publishing changes to Amazon is not enabled.
      </div>
    </div>
  );
}
