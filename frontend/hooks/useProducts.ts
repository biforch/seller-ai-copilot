'use client';

import { useCallback, useState } from 'react';

import { apiClient } from '@/app/api/client';
import type { Product, ProductDetail } from '@/types';

export function useProducts() {
  const [products, setProducts] = useState<Product[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchProducts = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await apiClient.get<Product[]>('/products');
      setProducts(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch products');
    } finally {
      setIsLoading(false);
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

  const deleteProduct = useCallback(async (id: string) => {
    await apiClient.delete(`/products/${id}`);
    setProducts((prev) => prev.filter((p) => p.id !== id));
  }, []);

  return { products, isLoading, error, fetchProducts, fetchProduct, deleteProduct };
}
