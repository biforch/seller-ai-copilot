import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { GeneratePageClient } from '@/app/(dashboard)/generate/GeneratePageClient';
import { apiClient } from '@/app/api/client';
import { createDeferred } from '@/test/deferred';
import type { ProductDetail } from '@/types';

const navigation = vi.hoisted(() => {
  const params = new Map<string, string>();
  return {
    params,
    push: vi.fn(),
    replace: vi.fn(),
    set(entries: Record<string, string | undefined>) {
      params.clear();
      Object.entries(entries).forEach(([key, value]) => {
        if (value) params.set(key, value);
      });
    },
  };
});

vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: navigation.push,
    replace: navigation.replace,
  }),
  useSearchParams: () => ({
    get: (key: string) => navigation.params.get(key) ?? null,
  }),
}));

vi.mock('@/hooks/useProjects', () => ({
  useProjects: () => ({
    projects: [{ id: 'proj-1', name: 'Project One', platform: 'Amazon', market: 'USA', created_at: '2026-01-01T00:00:00.000Z' }],
    isLoading: false,
    fetchProjects: vi.fn(),
  }),
}));

vi.mock('@/hooks/useGenerate', () => ({
  useGenerate: () => ({
    isLoading: false,
    error: null,
    listingResult: null,
    analyzeResult: null,
    generateListing: vi.fn(),
    analyzeListing: vi.fn(),
    reset: vi.fn(),
  }),
}));

function productDetail(overrides: Partial<ProductDetail> & { id: string; name: string }): ProductDetail {
  return {
    category: 'Gadgets',
    platform: 'Amazon',
    market: 'USA',
    created_at: '2026-01-01T00:00:00.000Z',
    project: { id: 'proj-1', name: 'Project One' },
    stats: { total_generations: 0, last_generated: null, generation_types: {} },
    score: null,
    next_actions: [],
    generations: [],
    target_customer: null,
    advantages: null,
    ...overrides,
  };
}

function productNameInput() {
  return screen.getAllByRole('textbox')[0] as HTMLInputElement;
}

describe('GeneratePageClient query/product loading', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    navigation.params.clear();
    navigation.replace.mockReset();
    navigation.push.mockReset();
    vi.spyOn(apiClient, 'get');
  });

  afterEach(() => {
    cleanup();
  });

  it('starts with a blank form when productId is absent', () => {
    navigation.set({ project_id: 'proj-1' });
    render(<GeneratePageClient />);

    expect(screen.queryByText('Select a project above before generating')).not.toBeInTheDocument();
    expect(screen.getByText('Project attached')).toBeInTheDocument();
    expect(productNameInput().value).toBe('');
    expect(screen.queryByText('Loading your linked SellerAI product…')).not.toBeInTheDocument();
    expect(apiClient.get).not.toHaveBeenCalled();
  });

  it('loads a linked product into the form on success', async () => {
    navigation.set({ product_id: 'prod-1', project_id: 'stale-project' });
    vi.mocked(apiClient.get).mockResolvedValue(
      productDetail({ id: 'prod-1', name: 'Loaded Product', category: 'Kitchen' }),
    );

    render(<GeneratePageClient />);
    expect(screen.getByText('Loading your linked SellerAI product…')).toBeInTheDocument();

    await waitFor(() => {
      expect(productNameInput().value).toBe('Loaded Product');
    });
    expect(screen.getByText('Project attached')).toBeInTheDocument();
    expect(navigation.replace).toHaveBeenCalledWith(
      '/generate?product_id=prod-1&project_id=proj-1',
    );
  });

  it('shows an error when the linked product cannot be loaded', async () => {
    navigation.set({ product_id: 'missing' });
    vi.mocked(apiClient.get).mockRejectedValue(new Error('boom'));

    render(<GeneratePageClient />);

    await waitFor(() => {
      expect(
        screen.getByText('The linked product could not be loaded. Return to Amazon and choose another product.'),
      ).toBeInTheDocument();
    });
    expect(productNameInput().value).toBe('');
  });

  it('aborts the in-flight product request on unmount', async () => {
    navigation.set({ product_id: 'prod-1' });
    const deferred = createDeferred<ProductDetail>();
    let capturedSignal: AbortSignal | undefined;
    vi.mocked(apiClient.get).mockImplementation((_path, options) => {
      capturedSignal = options?.signal;
      return deferred.promise;
    });

    const { unmount } = render(<GeneratePageClient />);
    await waitFor(() => {
      expect(capturedSignal).toBeDefined();
    });
    unmount();
    expect(capturedSignal?.aborted).toBe(true);
  });

  it('ignores a stale product success after a faster productId switch', async () => {
    const first = createDeferred<ProductDetail>();
    const second = createDeferred<ProductDetail>();
    vi.mocked(apiClient.get).mockImplementation((path) => {
      if (String(path).includes('prod-a')) return first.promise;
      if (String(path).includes('prod-b')) return second.promise;
      throw new Error(`unexpected ${path}`);
    });

    navigation.set({ product_id: 'prod-a' });
    const { rerender } = render(<GeneratePageClient />);
    await waitFor(() => {
      expect(apiClient.get).toHaveBeenCalled();
    });

    navigation.set({ product_id: 'prod-b' });
    rerender(<GeneratePageClient />);

    first.resolve(productDetail({ id: 'prod-a', name: 'Stale Product' }));
    second.resolve(productDetail({ id: 'prod-b', name: 'Fresh Product' }));

    await waitFor(() => {
      expect(productNameInput().value).toBe('Fresh Product');
    });
    expect(screen.queryByDisplayValue('Stale Product')).not.toBeInTheDocument();
  });

  it('ignores a stale product error after a newer request succeeds', async () => {
    const first = createDeferred<ProductDetail>();
    const second = createDeferred<ProductDetail>();
    vi.mocked(apiClient.get).mockImplementation((path) => {
      if (String(path).includes('prod-a')) return first.promise;
      return second.promise;
    });

    navigation.set({ product_id: 'prod-a' });
    const { rerender } = render(<GeneratePageClient />);
    navigation.set({ product_id: 'prod-b' });
    rerender(<GeneratePageClient />);

    second.resolve(productDetail({ id: 'prod-b', name: 'Fresh Product' }));
    await waitFor(() => {
      expect(productNameInput().value).toBe('Fresh Product');
    });

    first.reject(new Error('stale'));
    await waitFor(() => {
      expect(productNameInput().value).toBe('Fresh Product');
    });
    expect(
      screen.queryByText('The linked product could not be loaded. Return to Amazon and choose another product.'),
    ).not.toBeInTheDocument();
  });

  it('updates only project_id when the project query changes', async () => {
    navigation.set({ project_id: 'proj-1' });
    const { rerender } = render(<GeneratePageClient />);

    fireEvent.change(productNameInput(), { target: { value: 'User Edited Name' } });
    expect(productNameInput().value).toBe('User Edited Name');

    navigation.set({ project_id: 'proj-2' });
    rerender(<GeneratePageClient />);

    expect(productNameInput().value).toBe('User Edited Name');
    expect(screen.getByText('Project attached')).toBeInTheDocument();
  });

  it('does not let a project query change overwrite a loaded product', async () => {
    navigation.set({ product_id: 'prod-1', project_id: 'proj-1' });
    vi.mocked(apiClient.get).mockResolvedValue(
      productDetail({ id: 'prod-1', name: 'Loaded Product' }),
    );
    const { rerender } = render(<GeneratePageClient />);
    await waitFor(() => {
      expect(productNameInput().value).toBe('Loaded Product');
    });

    navigation.set({ product_id: 'prod-1', project_id: 'other-project' });
    rerender(<GeneratePageClient />);

    expect(productNameInput().value).toBe('Loaded Product');
  });

  it('refetches when amazonListingId changes', async () => {
    const first = createDeferred<ProductDetail>();
    const second = createDeferred<ProductDetail>();
    let calls = 0;
    vi.mocked(apiClient.get).mockImplementation(() => {
      calls += 1;
      return calls === 1 ? first.promise : second.promise;
    });

    navigation.set({ product_id: 'prod-1', amazon_listing_id: 'listing-a' });
    const { rerender } = render(<GeneratePageClient />);
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledTimes(1));

    navigation.set({ product_id: 'prod-1', amazon_listing_id: 'listing-b' });
    rerender(<GeneratePageClient />);
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledTimes(2));

    first.resolve(productDetail({ id: 'prod-1', name: 'From Listing A' }));
    second.resolve(productDetail({ id: 'prod-1', name: 'From Listing B' }));

    await waitFor(() => {
      expect(productNameInput().value).toBe('From Listing B');
    });
    expect(navigation.replace).toHaveBeenCalledWith(
      '/generate?product_id=prod-1&project_id=proj-1&amazon_listing_id=listing-b',
    );
  });
});
