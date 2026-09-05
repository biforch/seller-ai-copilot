'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  AlertCircle,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  Link2,
  Loader2,
  PackageSearch,
  RefreshCw,
  RotateCcw,
  Store,
  Unplug,
  WandSparkles,
} from 'lucide-react';

import {
  amazonApi,
  type AmazonAccount,
  type AmazonCapabilities,
  type AmazonCatalogSnapshot,
  type AmazonListing,
  type AmazonLinkProduct,
  type AmazonMarketplace,
} from '@/app/api/amazon';
import { isAbortError } from '@/lib/abort-error';
import { ApiClientError } from '@/lib/api-client-error';
import { LatestRequestGate, type RequestLease } from '@/lib/latest-request';
import type { PaginatedResponse } from '@/types';

const MARKETPLACE_CODES = ['US', 'CA', 'MX', 'BR', 'UK', 'DE', 'FR', 'IT', 'ES', 'JP', 'AU'];
const PAGE_SIZE = 20;
const REGION_REAUTH_MARKETPLACE: Record<AmazonAccount['region'], string> = {
  na: 'US',
  eu: 'UK',
  fe: 'JP',
};

type ActionScope = {
  generation: number;
  accountId: string;
  marketplaceId?: string;
  listingId?: string;
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

function pickDefaultMarketplaceId(
  items: AmazonMarketplace[],
  current: string | null,
  preferredCountryCode?: string | null,
): string | null {
  if (current && items.some((item) => item.marketplace_id === current)) return current;
  if (preferredCountryCode) {
    const preferred = items.find((item) => item.country_code === preferredCountryCode && item.sync_eligible);
    if (preferred) return preferred.marketplace_id;
  }
  return items.find((item) => item.sync_eligible)?.marketplace_id ?? items[0]?.marketplace_id ?? null;
}

function commitListings(
  listingsRef: { current: AmazonListing[] },
  setListings: (items: AmazonListing[]) => void,
  next: AmazonListing[],
) {
  listingsRef.current = next;
  setListings(next);
}

function statusStyle(status: AmazonAccount['status']) {
  if (status === 'active') return 'bg-emerald-50 text-emerald-700 border-emerald-200';
  if (status === 'reauthorization_required') return 'bg-amber-50 text-amber-700 border-amber-200';
  if (status === 'disabled') return 'bg-slate-100 text-slate-600 border-slate-200';
  return 'bg-red-50 text-red-700 border-red-200';
}

export default function AmazonConnectionsPage() {
  const router = useRouter();
  const [accounts, setAccounts] = useState<AmazonAccount[]>([]);
  const [selectedAccountId, setSelectedAccountId] = useState<string | null>(null);
  const [marketplaces, setMarketplaces] = useState<AmazonMarketplace[]>([]);
  const [selectedMarketplaceId, setSelectedMarketplaceId] = useState<string | null>(null);
  const [listings, setListings] = useState<AmazonListing[]>([]);
  const [products, setProducts] = useState<AmazonLinkProduct[]>([]);
  const [catalogByListing, setCatalogByListing] = useState<Record<string, AmazonCatalogSnapshot>>({});
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
  const [targetAsin, setTargetAsin] = useState<string | null>(null);
  const [targetMarketplaceCode, setTargetMarketplaceCode] = useState<string | null>(null);
  const [capabilities, setCapabilities] = useState<AmazonCapabilities | null>(null);
  const [disconnectConfirmAccountId, setDisconnectConfirmAccountId] = useState<string | null>(null);

  const mountedRef = useRef(true);
  const accountsGateRef = useRef(new LatestRequestGate());
  const marketplaceGateRef = useRef(new LatestRequestGate());
  const listingGateRef = useRef(new LatestRequestGate());
  const productsGateRef = useRef(new LatestRequestGate());
  const actionGenerationRef = useRef(0);
  const selectedAccountIdRef = useRef<string | null>(null);
  const selectedMarketplaceIdRef = useRef<string | null>(null);
  const includeInactiveRef = useRef(false);
  const listingsRef = useRef<AmazonListing[]>([]);

  const bumpActionScope = useCallback(() => {
    actionGenerationRef.current += 1;
  }, []);

  const beginActionScope = useCallback(
    (accountId: string, marketplaceId?: string, listingId?: string): ActionScope => {
      actionGenerationRef.current += 1;
      return {
        generation: actionGenerationRef.current,
        accountId,
        marketplaceId,
        listingId,
      };
    },
    [],
  );

  const clearListingScopeState = useCallback(() => {
    commitListings(listingsRef, setListings, []);
    setCatalogByListing({});
    setPage(1);
    setTotalPages(0);
    setTotalListings(0);
  }, []);

  const isActionScopeActive = useCallback((scope: ActionScope) => {
    if (actionGenerationRef.current !== scope.generation) return false;
    if (selectedAccountIdRef.current !== scope.accountId) return false;
    if (scope.marketplaceId !== undefined && selectedMarketplaceIdRef.current !== scope.marketplaceId) {
      return false;
    }
    if (
      scope.listingId !== undefined
      && !listingsRef.current.some((listing) => listing.id === scope.listingId)
    ) {
      return false;
    }
    return true;
  }, []);

  const invalidateAccountSelection = useCallback(() => {
    marketplaceGateRef.current.invalidate();
    listingGateRef.current.invalidate();
    bumpActionScope();
    selectedMarketplaceIdRef.current = null;
    clearListingScopeState();
    setMarketplaces([]);
    setSelectedMarketplaceId(null);
    setLoadingListings(false);
    setAction(null);
  }, [bumpActionScope, clearListingScopeState]);

  const invalidateMarketplaceSelection = useCallback(() => {
    listingGateRef.current.invalidate();
    bumpActionScope();
    clearListingScopeState();
    setAction(null);
  }, [bumpActionScope, clearListingScopeState]);

  const handleSelectAccount = useCallback(
    (accountId: string) => {
      if (accountId === selectedAccountIdRef.current) return;
      invalidateAccountSelection();
      selectedAccountIdRef.current = accountId;
      setSelectedAccountId(accountId);
      setLoadingMarketplaces(true);
      setError(null);
    },
    [invalidateAccountSelection],
  );

  const handleSelectMarketplace = useCallback(
    (marketplaceId: string) => {
      if (marketplaceId === selectedMarketplaceIdRef.current) return;
      invalidateMarketplaceSelection();
      selectedMarketplaceIdRef.current = marketplaceId;
      setSelectedMarketplaceId(marketplaceId);
      setLoadingListings(true);
      setError(null);
    },
    [invalidateMarketplaceSelection],
  );

  const handleIncludeInactiveChange = useCallback(
    (checked: boolean) => {
      if (checked === includeInactiveRef.current) return;
      listingGateRef.current.invalidate();
      bumpActionScope();
      includeInactiveRef.current = checked;
      clearListingScopeState();
      setIncludeInactive(checked);
      setLoadingListings(true);
      setError(null);
    },
    [bumpActionScope, clearListingScopeState],
  );

  const selectedAccount = useMemo(
    () => accounts.find((account) => account.id === selectedAccountId) ?? null,
    [accounts, selectedAccountId],
  );
  const selectedMarketplace = useMemo(
    () => marketplaces.find((item) => item.marketplace_id === selectedMarketplaceId) ?? null,
    [marketplaces, selectedMarketplaceId],
  );
  const amazonOAuthEnabled = capabilities?.oauth_enabled ?? false;
  const showAmazonConnect = amazonOAuthEnabled;
  const showAmazonDisconnect = amazonOAuthEnabled && accounts.length > 0;

  const applyLoadedAccounts = useCallback(
    (result: { items: AmazonAccount[] }, lease: RequestLease) => {
      if (!mountedRef.current || !lease.isCurrent()) return;
      setError(null);
      setAccounts(result.items);

      const currentAccountId = selectedAccountIdRef.current;
      const nextAccountId =
        currentAccountId && result.items.some((account) => account.id === currentAccountId)
          ? currentAccountId
          : result.items[0]?.id ?? null;

      if (nextAccountId !== currentAccountId) {
        invalidateAccountSelection();
        selectedAccountIdRef.current = nextAccountId;
        setLoadingMarketplaces(Boolean(nextAccountId));
      }

      setSelectedAccountId(nextAccountId);
    },
    [invalidateAccountSelection],
  );

  const applyAccountsRequestError = useCallback((requestError: unknown, lease: RequestLease) => {
    if (isAbortError(requestError) || !lease.isCurrent() || !mountedRef.current) return;
    setError(errorMessage(requestError));
  }, []);

  const finishAccountsLease = useCallback((lease: RequestLease) => {
    if (mountedRef.current && lease.isCurrent()) {
      setLoadingAccounts(false);
    }
  }, []);

  const applyLoadedMarketplaces = useCallback(
    (accountId: string, result: { items: AmazonMarketplace[] }, lease: RequestLease) => {
      if (!mountedRef.current || !lease.isCurrent()) return;
      if (selectedAccountIdRef.current !== accountId) return;
      setError(null);
      setMarketplaces(result.items);

      const currentMarketplaceId = selectedMarketplaceIdRef.current;
      const nextMarketplaceId = pickDefaultMarketplaceId(result.items, currentMarketplaceId, targetMarketplaceCode);
      if (nextMarketplaceId !== currentMarketplaceId) {
        listingGateRef.current.invalidate();
        bumpActionScope();
        clearListingScopeState();
        setLoadingListings(Boolean(nextMarketplaceId));
      }
      selectedMarketplaceIdRef.current = nextMarketplaceId;
      setSelectedMarketplaceId(nextMarketplaceId);
    },
    [bumpActionScope, clearListingScopeState, targetMarketplaceCode],
  );

  const applyMarketplacesRequestError = useCallback(
    (accountId: string, requestError: unknown, lease: RequestLease) => {
      if (isAbortError(requestError) || !lease.isCurrent() || !mountedRef.current) return;
      if (selectedAccountIdRef.current !== accountId) return;
      setMarketplaces([]);
      selectedMarketplaceIdRef.current = null;
      clearListingScopeState();
      setSelectedMarketplaceId(null);
      setLoadingListings(false);
      setError(errorMessage(requestError));
    },
    [clearListingScopeState],
  );

  const finishMarketplacesLease = useCallback((lease: RequestLease) => {
    if (mountedRef.current && lease.isCurrent()) {
      setLoadingMarketplaces(false);
    }
  }, []);

  const applyLoadedListings = useCallback(
    (
      accountId: string,
      marketplaceId: string,
      expectedIncludeInactive: boolean,
      result: PaginatedResponse<AmazonListing>,
      lease: RequestLease,
    ) => {
      if (!mountedRef.current || !lease.isCurrent()) return;
      if (selectedAccountIdRef.current !== accountId) return;
      if (selectedMarketplaceIdRef.current !== marketplaceId) return;
      if (includeInactiveRef.current !== expectedIncludeInactive) return;
      setError(null);
      commitListings(listingsRef, setListings, result.items);
      setPage(result.pagination.page);
      setTotalPages(result.pagination.total_pages);
      setTotalListings(result.pagination.total);
    },
    [],
  );

  const applyListingsRequestError = useCallback(
    (
      accountId: string,
      marketplaceId: string,
      expectedIncludeInactive: boolean,
      requestError: unknown,
      lease: RequestLease,
    ) => {
      if (isAbortError(requestError) || !lease.isCurrent() || !mountedRef.current) return;
      if (selectedAccountIdRef.current !== accountId) return;
      if (selectedMarketplaceIdRef.current !== marketplaceId) return;
      if (includeInactiveRef.current !== expectedIncludeInactive) return;
      commitListings(listingsRef, setListings, []);
      setError(errorMessage(requestError));
    },
    [],
  );

  const finishListingsLease = useCallback((lease: RequestLease) => {
    if (mountedRef.current && lease.isCurrent()) {
      setLoadingListings(false);
    }
  }, []);

  const loadAccounts = useCallback(async () => {
    const lease = accountsGateRef.current.begin();
    try {
      const result = await amazonApi.listAccounts();
      applyLoadedAccounts(result, lease);
    } catch (requestError) {
      applyAccountsRequestError(requestError, lease);
    } finally {
      finishAccountsLease(lease);
    }
  }, [applyAccountsRequestError, applyLoadedAccounts, finishAccountsLease]);

  const loadMarketplaces = useCallback(async (accountId: string) => {
    const lease = marketplaceGateRef.current.begin();
    try {
      const result = await amazonApi.listMarketplaces(accountId, lease.signal);
      applyLoadedMarketplaces(accountId, result, lease);
    } catch (requestError) {
      applyMarketplacesRequestError(accountId, requestError, lease);
    } finally {
      finishMarketplacesLease(lease);
    }
  }, [applyLoadedMarketplaces, applyMarketplacesRequestError, finishMarketplacesLease]);

  const loadListings = useCallback(
    async (accountId: string, marketplaceId: string, targetPage: number) => {
      const lease = listingGateRef.current.begin();
      const expectedIncludeInactive = includeInactiveRef.current;
      try {
        const result = await amazonApi.listListings(
          accountId,
          marketplaceId,
          {
            page: targetPage,
            pageSize: PAGE_SIZE,
            includeInactive: expectedIncludeInactive,
            asin: targetAsin ?? undefined,
          },
          lease.signal,
        );
        applyLoadedListings(accountId, marketplaceId, expectedIncludeInactive, result, lease);
      } catch (requestError) {
        applyListingsRequestError(
          accountId,
          marketplaceId,
          expectedIncludeInactive,
          requestError,
          lease,
        );
      } finally {
        finishListingsLease(lease);
      }
    },
    [applyListingsRequestError, applyLoadedListings, finishListingsLease, targetAsin],
  );

  useEffect(() => {
    mountedRef.current = true;
    const accountsGate = accountsGateRef.current;
    const marketplaceGate = marketplaceGateRef.current;
    const listingGate = listingGateRef.current;
    const productsGate = productsGateRef.current;
    return () => {
      mountedRef.current = false;
      accountsGate.invalidate();
      marketplaceGate.invalidate();
      listingGate.invalidate();
      productsGate.invalidate();
    };
  }, []);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const asin = params.get('asin')?.trim().toUpperCase() ?? '';
    const marketplace = params.get('marketplace')?.trim().toUpperCase() ?? '';
    queueMicrotask(() => {
      if (/^[A-Z0-9]{10}$/.test(asin)) setTargetAsin(asin);
      if (MARKETPLACE_CODES.includes(marketplace)) setTargetMarketplaceCode(marketplace);
    });
  }, []);

  useEffect(() => {
    const accountsLease = accountsGateRef.current.begin();
    void Promise.all([amazonApi.getCapabilities(), amazonApi.listAccounts()])
      .then(([capabilityResult, accountResult]) => {
        if (mountedRef.current) {
          setCapabilities(capabilityResult);
        }
        applyLoadedAccounts(accountResult, accountsLease);
      })
      .catch((requestError) => {
        applyAccountsRequestError(requestError, accountsLease);
      })
      .finally(() => {
        finishAccountsLease(accountsLease);
      });

    const productsLease = productsGateRef.current.begin();
    void amazonApi.listLinkableProducts(productsLease.signal)
      .then((result) => {
        if (!mountedRef.current || !productsLease.isCurrent()) return;
        setProducts(result.items);
      })
      .catch((requestError) => {
        if (isAbortError(requestError) || !productsLease.isCurrent() || !mountedRef.current) return;
        setError(errorMessage(requestError));
      });
  }, [applyAccountsRequestError, applyLoadedAccounts, finishAccountsLease]);

  useEffect(() => {
    if (!selectedAccountId) {
      return;
    }
    const accountId = selectedAccountId;
    const lease = marketplaceGateRef.current.begin();
    void amazonApi.listMarketplaces(accountId, lease.signal)
      .then((result) => {
        applyLoadedMarketplaces(accountId, result, lease);
      })
      .catch((requestError) => {
        applyMarketplacesRequestError(accountId, requestError, lease);
      })
      .finally(() => {
        finishMarketplacesLease(lease);
      });
  }, [
    applyLoadedMarketplaces,
    applyMarketplacesRequestError,
    finishMarketplacesLease,
    selectedAccountId,
  ]);

  useEffect(() => {
    if (!selectedAccountId || !selectedMarketplaceId) {
      return;
    }
    const accountId = selectedAccountId;
    const marketplaceId = selectedMarketplaceId;
    const expectedIncludeInactive = includeInactive;
    const lease = listingGateRef.current.begin();
    void amazonApi.listListings(
      accountId,
      marketplaceId,
      {
        page: 1,
        pageSize: PAGE_SIZE,
        includeInactive: expectedIncludeInactive,
        asin: targetAsin ?? undefined,
      },
      lease.signal,
    )
      .then((result) => {
        applyLoadedListings(accountId, marketplaceId, expectedIncludeInactive, result, lease);
      })
      .catch((requestError) => {
        applyListingsRequestError(
          accountId,
          marketplaceId,
          expectedIncludeInactive,
          requestError,
          lease,
        );
      })
      .finally(() => {
        finishListingsLease(lease);
      });
  }, [
    applyListingsRequestError,
    applyLoadedListings,
    finishListingsLease,
    includeInactive,
    selectedAccountId,
    selectedMarketplaceId,
    targetAsin,
  ]);

  const startOAuth = async (intent: 'connect' | 'reauthorize', accountId?: string) => {
    if (!amazonOAuthEnabled) return;
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
    const scope = beginActionScope(selectedAccountId);
    setAction('refresh-marketplaces');
    setError(null);
    try {
      const result = await amazonApi.refreshMarketplaces(scope.accountId);
      if (!mountedRef.current || !isActionScopeActive(scope)) return;
      setNotice(`Marketplace refresh complete: ${result.items_written} updated.`);
      setLoadingAccounts(true);
      setLoadingMarketplaces(true);
      await Promise.all([loadAccounts(), loadMarketplaces(scope.accountId)]);
    } catch (requestError) {
      if (!mountedRef.current || !isActionScopeActive(scope)) return;
      setError(errorMessage(requestError));
    } finally {
      if (mountedRef.current && isActionScopeActive(scope)) {
        setAction(null);
      }
    }
  };

  const syncListings = async () => {
    if (!selectedAccountId || !selectedMarketplaceId) return;
    const scope = beginActionScope(selectedAccountId, selectedMarketplaceId);
    setAction('sync-listings');
    setError(null);
    try {
      const result = await amazonApi.syncListings(scope.accountId, scope.marketplaceId!);
      if (!mountedRef.current || !isActionScopeActive(scope)) return;
      setNotice(`Listing sync complete: ${result.items_written} written, ${result.items_deactivated} deactivated.`);
      setLoadingListings(true);
      await loadListings(scope.accountId, scope.marketplaceId!, 1);
    } catch (requestError) {
      if (!mountedRef.current || !isActionScopeActive(scope)) return;
      setError(errorMessage(requestError));
    } finally {
      if (mountedRef.current && isActionScopeActive(scope)) {
        setAction(null);
      }
    }
  };

  const linkProduct = async (listingId: string, productId: string | null) => {
    if (!selectedAccountId || !selectedMarketplaceId) return;
    const scope = beginActionScope(selectedAccountId, selectedMarketplaceId, listingId);
    setAction(`link:${listingId}`);
    setError(null);
    try {
      const updated = await amazonApi.linkListingProduct(
        scope.accountId,
        scope.marketplaceId!,
        listingId,
        productId,
      );
      if (!mountedRef.current || !isActionScopeActive(scope)) return;
      const nextListings = listingsRef.current.map((item) =>
        item.id === updated.id ? updated : item,
      );
      commitListings(listingsRef, setListings, nextListings);
      setNotice(productId ? 'Listing linked to a SellerAI product.' : 'Listing unlinked.');
    } catch (requestError) {
      if (!mountedRef.current || !isActionScopeActive(scope)) return;
      setError(errorMessage(requestError));
    } finally {
      if (mountedRef.current && isActionScopeActive(scope)) {
        setAction(null);
      }
    }
  };

  const refreshCatalog = async (listing: AmazonListing) => {
    if (!selectedAccountId || !selectedMarketplaceId || !listing.asin) return;
    const scope = beginActionScope(selectedAccountId, selectedMarketplaceId, listing.id);
    setAction(`catalog:${listing.id}`);
    setError(null);
    try {
      const snapshot = await amazonApi.refreshListingCatalog(
        scope.accountId,
        scope.marketplaceId!,
        listing.id,
      );
      if (!mountedRef.current || !isActionScopeActive(scope)) return;
      setCatalogByListing((current) => ({ ...current, [listing.id]: snapshot }));
      setNotice(snapshot.cache_hit ? 'Catalog summary loaded from cache.' : 'Catalog summary refreshed.');
    } catch (requestError) {
      if (!mountedRef.current || !isActionScopeActive(scope)) return;
      setError(errorMessage(requestError));
    } finally {
      if (mountedRef.current && isActionScopeActive(scope)) {
        setAction(null);
      }
    }
  };

  const auditListing = async (listing: AmazonListing) => {
    if (!selectedAccountId || !selectedMarketplaceId) return;
    const scope = beginActionScope(selectedAccountId, selectedMarketplaceId, listing.id);
    setAction(`audit:${listing.id}`);
    setError(null);
    try {
      const report = await amazonApi.auditListing(
        scope.accountId,
        scope.marketplaceId!,
        listing.id,
      );
      if (!mountedRef.current || !isActionScopeActive(scope)) return;
      router.push(`/audits/${report.report_id}`);
    } catch (requestError) {
      if (!mountedRef.current || !isActionScopeActive(scope)) return;
      setError(errorMessage(requestError));
      setAction(null);
    }
  };

  const disconnectAmazonAccount = async (accountId: string) => {
    const scope = beginActionScope(accountId);
    setAction(`disconnect:${accountId}`);
    setError(null);
    try {
      const result = await amazonApi.disconnectAccount(accountId);
      if (!mountedRef.current || !isActionScopeActive(scope)) return;
      setDisconnectConfirmAccountId(null);
      setNotice(
        result.already_disconnected
          ? 'This Amazon connection was already removed.'
          : 'Amazon connection removed. Imported listing data for this account has been deleted from Listnara.',
      );
      invalidateAccountSelection();
      selectedAccountIdRef.current = null;
      setSelectedAccountId(null);
      setAccounts([]);
      setLoadingAccounts(true);
      const accountsLease = accountsGateRef.current.begin();
      const accountResult = await amazonApi.listAccounts();
      applyLoadedAccounts(accountResult, accountsLease);
      finishAccountsLease(accountsLease);
    } catch (requestError) {
      if (!mountedRef.current || !isActionScopeActive(scope)) return;
      setError(errorMessage(requestError));
    } finally {
      if (mountedRef.current && isActionScopeActive(scope)) {
        setAction(null);
      }
    }
  };

  const openOptimizationWorkspace = (product: AmazonLinkProduct, listingId: string) => {
    const params = new URLSearchParams({
      product_id: product.id,
      project_id: product.project_id,
      amazon_listing_id: listingId,
    });
    router.push(`/generate?${params.toString()}`);
  };

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="text-sm font-semibold uppercase tracking-wider text-emerald-700">Import from Amazon</p>
          <h1 className="mt-1 text-3xl font-bold text-slate-950">Choose a live listing to audit</h1>
          <p className="mt-2 max-w-2xl text-slate-600">
            When Amazon connectivity is enabled, Listnara imports authorized listing content, captures an immutable
            snapshot, and supports evidence-based audits you review before acting.
          </p>
        </div>
        {showAmazonConnect ? (
          <div className="flex items-center gap-2 rounded-xl border bg-white p-2 shadow-sm">
            <select
              aria-label="Seller Central marketplace"
              value={marketplaceCode}
              onChange={(event) => setMarketplaceCode(event.target.value)}
              className="rounded-lg border-0 bg-slate-50 px-3 py-2 text-sm font-medium text-slate-700 focus:ring-2 focus:ring-orange-500"
            >
              {MARKETPLACE_CODES.map((code) => (
                <option key={code}>{code}</option>
              ))}
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
        ) : (
          <div className="max-w-md rounded-xl border border-slate-200 bg-white p-4 text-sm leading-6 text-slate-600 shadow-sm">
            Amazon OAuth is not enabled in this environment yet. When it becomes available, you will authorize Listnara
            through Amazon&apos;s consent screen to import eligible marketplace, listing, and catalog data for review.
          </div>
        )}
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
      {targetAsin && (
        <div className="flex flex-col gap-3 rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-900 sm:flex-row sm:items-center sm:justify-between">
          <span><strong>ASIN {targetAsin}</strong> · Showing only matching listings authorized by your connected account.</span>
          <button onClick={() => { setTargetAsin(null); setTargetMarketplaceCode(null); router.push('/amazon'); }} className="self-start font-semibold text-emerald-800 underline underline-offset-4">Clear filter</button>
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
              <p className="mt-1 text-sm text-slate-500">
                {showAmazonConnect
                  ? 'Choose a marketplace above to connect Seller Central.'
                  : 'Amazon connection will appear here after OAuth is enabled for your environment.'}
              </p>
            </div>
          ) : (
            <div className="space-y-2">
              {accounts.map((account) => (
                <button
                  key={account.id}
                  onClick={() => handleSelectAccount(account.id)}
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
                    {selectedAccount.status !== 'active' && showAmazonConnect && (
                      <button
                        onClick={() => void startOAuth('reauthorize', selectedAccount.id)}
                        disabled={action !== null}
                        className="inline-flex items-center gap-2 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm font-semibold text-amber-800 hover:bg-amber-100 disabled:opacity-50"
                      >
                        <RotateCcw className="h-4 w-4" /> Reauthorize
                      </button>
                    )}
                    {showAmazonDisconnect && (
                      <button
                        onClick={() => setDisconnectConfirmAccountId(selectedAccount.id)}
                        disabled={action !== null}
                        className="inline-flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm font-semibold text-red-800 hover:bg-red-100 disabled:opacity-50"
                      >
                        <Unplug className="h-4 w-4" /> Disconnect Amazon
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
                      onClick={() => handleSelectMarketplace(marketplace.marketplace_id)}
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
                          onChange={(event) => handleIncludeInactiveChange(event.target.checked)}
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
                      <p className="mt-3 font-medium text-slate-700">{targetAsin ? `ASIN ${targetAsin} was not found` : 'No synced listings'}</p>
                      <p className="mt-1 text-sm text-slate-500">{targetAsin ? 'Confirm the marketplace and run a listing sync. Only products belonging to the authorized seller account can be imported.' : 'Run a listing sync to import seller SKU identities.'}</p>
                    </div>
                  ) : (
                    <div className="overflow-x-auto">
                      <table className="min-w-full divide-y divide-slate-200 text-sm">
                        <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                          <tr><th className="px-5 py-3">SKU</th><th className="px-5 py-3">ASIN</th><th className="px-5 py-3">SellerAI product</th><th className="px-5 py-3">Product type</th><th className="px-5 py-3">Status</th><th className="px-5 py-3">Last seen</th><th className="px-5 py-3">Audit</th></tr>
                        </thead>
                        <tbody className="divide-y divide-slate-100">
                          {listings.map((listing) => {
                            const catalog = catalogByListing[listing.id];
                            return (
                            <tr key={listing.id} className="hover:bg-slate-50/70">
                              <td className="whitespace-nowrap px-5 py-4 font-medium text-slate-900">{listing.seller_sku}</td>
                              <td className="min-w-64 px-5 py-4 text-slate-600">
                                <div className="flex items-start gap-2">
                                  <div>
                                    <p className="whitespace-nowrap font-medium">{listing.asin ?? '—'}</p>
                                    {catalog && (
                                      <div className="mt-1 max-w-72 text-xs text-slate-500">
                                        <p className="line-clamp-2 text-slate-700">{catalog.item_name ?? 'Catalog title unavailable'}</p>
                                        {(catalog.brand || catalog.manufacturer) && (
                                          <p className="mt-0.5">{catalog.brand ?? catalog.manufacturer}</p>
                                        )}
                                      </div>
                                    )}
                                  </div>
                                  {listing.asin && (
                                    <button
                                      type="button"
                                      aria-label={`Load catalog summary for ${listing.seller_sku}`}
                                      title="Load catalog summary"
                                      disabled={action !== null}
                                      onClick={() => void refreshCatalog(listing)}
                                      className="rounded-lg border border-blue-200 bg-blue-50 p-1.5 text-blue-700 hover:bg-blue-100 disabled:opacity-50"
                                    >
                                      {action === `catalog:${listing.id}` ? (
                                        <Loader2 className="h-4 w-4 animate-spin" />
                                      ) : (
                                        <PackageSearch className="h-4 w-4" />
                                      )}
                                    </button>
                                  )}
                                </div>
                              </td>
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
                                  {products.find((product) => product.id === listing.product_id) && (
                                    <button
                                      type="button"
                                      aria-label={`Optimize ${listing.seller_sku} in AI workspace`}
                                      title="Optimize in AI workspace"
                                      onClick={() => {
                                        const product = products.find((item) => item.id === listing.product_id);
                                        if (product) openOptimizationWorkspace(product, listing.id);
                                      }}
                                      className="rounded-lg border border-purple-200 bg-purple-50 p-2 text-purple-700 hover:bg-purple-100"
                                    >
                                      <WandSparkles className="h-4 w-4" />
                                    </button>
                                  )}
                                </div>
                              </td>
                              <td className="whitespace-nowrap px-5 py-4 text-slate-600">{listing.product_type ?? '—'}</td>
                              <td className="px-5 py-4"><span className={`rounded-full px-2 py-1 text-xs font-semibold ${listing.is_active ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-500'}`}>{listing.is_active ? listing.status_codes.join(', ') || 'Active' : 'Inactive'}</span></td>
                              <td className="whitespace-nowrap px-5 py-4 text-slate-500">{formatDate(listing.last_seen_at)}</td>
                              <td className="whitespace-nowrap px-5 py-4">
                                <button
                                  type="button"
                                  disabled={action !== null || !listing.is_active}
                                  onClick={() => void auditListing(listing)}
                                  className="inline-flex items-center gap-2 rounded-lg bg-emerald-800 px-3 py-2 text-xs font-semibold text-white hover:bg-emerald-900 disabled:opacity-50"
                                >
                                  {action === `audit:${listing.id}` ? <Loader2 className="h-4 w-4 animate-spin" /> : <PackageSearch className="h-4 w-4" />}
                                  Audit listing
                                </button>
                              </td>
                            </tr>
                          )})}
                        </tbody>
                      </table>
                    </div>
                  )}

                  {totalPages > 1 && (
                    <div className="flex items-center justify-between border-t px-5 py-4 text-sm text-slate-600">
                      <span>Page {page} of {totalPages}</span>
                      <div className="flex gap-2">
                        <button
                          disabled={page <= 1 || loadingListings}
                          onClick={() => {
                            if (!selectedAccountId || !selectedMarketplaceId) return;
                            setLoadingListings(true);
                            setError(null);
                            void loadListings(selectedAccountId, selectedMarketplaceId, page - 1);
                          }}
                          className="rounded-lg border p-2 hover:bg-slate-50 disabled:opacity-40"
                          aria-label="Previous page"
                        >
                          <ChevronLeft className="h-4 w-4" />
                        </button>
                        <button
                          disabled={page >= totalPages || loadingListings}
                          onClick={() => {
                            if (!selectedAccountId || !selectedMarketplaceId) return;
                            setLoadingListings(true);
                            setError(null);
                            void loadListings(selectedAccountId, selectedMarketplaceId, page + 1);
                          }}
                          className="rounded-lg border p-2 hover:bg-slate-50 disabled:opacity-40"
                          aria-label="Next page"
                        >
                          <ChevronRight className="h-4 w-4" />
                        </button>
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
        Read-only Amazon access. Listnara imports listing content for analysis and cannot publish changes to Amazon.
      </div>

      {disconnectConfirmAccountId ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50 p-4"
          role="dialog"
          aria-modal="true"
          aria-labelledby="disconnect-amazon-title"
        >
          <div className="max-w-lg rounded-2xl border bg-white p-6 shadow-xl">
            <h2 id="disconnect-amazon-title" className="text-lg font-semibold text-slate-950">
              Disconnect this Amazon account?
            </h2>
            <p className="mt-3 text-sm leading-6 text-slate-600">
              This immediately stops SP-API access for the selected connection, deletes the stored refresh token, and
              removes imported marketplace, listing, catalog, and linked audit snapshot data from Listnara. This action
              cannot be undone from the app.
            </p>
            <p className="mt-3 text-sm leading-6 text-slate-600">
              You should also revoke Listnara in Amazon Seller Central under Apps and Services → Manage Your Apps.
            </p>
            <div className="mt-6 flex flex-wrap justify-end gap-3">
              <button
                type="button"
                onClick={() => setDisconnectConfirmAccountId(null)}
                disabled={action !== null}
                className="rounded-lg border px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => void disconnectAmazonAccount(disconnectConfirmAccountId)}
                disabled={action !== null}
                className="inline-flex items-center gap-2 rounded-lg bg-red-700 px-4 py-2 text-sm font-semibold text-white hover:bg-red-800 disabled:opacity-50"
              >
                {action === `disconnect:${disconnectConfirmAccountId}` ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Unplug className="h-4 w-4" />
                )}
                Disconnect and delete imported data
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
