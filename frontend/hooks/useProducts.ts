'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import { apiClient } from '@/app/api/client';
import type { PaginatedResponse, PaginationMeta, Product, ProductDetail } from '@/types';

export interface FetchProductsOptions {
  page?: number;
  page_size?: number;
  sort_by?: string;
  sort_order?: 'asc' | 'desc';
}

export function useProducts() {
  const [products, setProducts] = useState<Product[]>([]);
  const [pagination, setPagination] = useState<PaginationMeta | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const requestSeq = useRef(0);
  const pageRef = useRef(1);
  const productsRef = useRef<Product[]>([]);

  useEffect(() => {
    productsRef.current = products;
  }, [products]);

  const fetchProducts = useCallback(async (options: FetchProductsOptions = {}) => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const seq = ++requestSeq.current;
    const page = options.page ?? pageRef.current;

    setIsLoading(true);
    setError(null);

    try {
      const data = await apiClient.get<PaginatedResponse<Product>>('/products', {
        params: {
          page,
          page_size: options.page_size ?? 20,
          sort_by: options.sort_by,
          sort_order: options.sort_order,
        },
        signal: controller.signal,
      });

      if (seq !== requestSeq.current || controller.signal.aborted) {
        return null;
      }

      pageRef.current = data.pagination.page;
      productsRef.current = data.items;
      setProducts(data.items);
      setPagination(data.pagination);
      return data;
    } catch (err) {
      if (controller.signal.aborted) {
        return null;
      }
      setError(err instanceof Error ? err.message : 'Failed to fetch products');
      return null;
    } finally {
      if (seq === requestSeq.current) {
        setIsLoading(false);
      }
    }
  }, []);

  const fetchProduct = useCallback(async (id: string) => {
    setIsLoading(true);
    setError(null);
    try {
      return await apiClient.get<ProductDetail>(`/products/${id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch product');
      return null;
    } finally {
      setIsLoading(false);
    }
  }, []);

  const deleteProduct = useCallback(
    async (id: string) => {
      await apiClient.delete(`/products/${id}`);

      const currentPage = pageRef.current;
      const remainingItems = productsRef.current.filter((product) => product.id !== id);
      productsRef.current = remainingItems;

      if (remainingItems.length === 0 && currentPage > 1) {
        const previousPage = currentPage - 1;
        pageRef.current = previousPage;
        await fetchProducts({ page: previousPage });
        return;
      }

      setProducts(remainingItems);
      setPagination((prev) => {
        if (!prev) {
          return prev;
        }
        const total = Math.max(0, prev.total - 1);
        const totalPages = total > 0 ? Math.ceil(total / prev.page_size) : 0;
        const page = total === 0 ? 1 : prev.page;
        if (total === 0) {
          pageRef.current = 1;
        }
        return {
          ...prev,
          page,
          total,
          total_pages: totalPages,
          has_next: page < totalPages,
          has_previous: page > 1 && total > 0,
        };
      });
    },
    [fetchProducts]
  );

  const setPage = useCallback(
    (page: number) => {
      pageRef.current = page;
      return fetchProducts({ page });
    },
    [fetchProducts]
  );

  return {
    products,
    pagination,
    isLoading,
    error,
    fetchProducts,
    fetchProduct,
    deleteProduct,
    setPage,
  };
}
