'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { ChevronLeft, ChevronRight, Trash2 } from 'lucide-react';

import { useProducts } from '@/hooks/useProducts';

function PaginationBar({
  pagination,
  onPageChange,
  disabled,
}: {
  pagination: {
    page: number;
    total_pages: number;
    has_next: boolean;
    has_previous: boolean;
  };
  onPageChange: (page: number) => void;
  disabled?: boolean;
}) {
  if (pagination.total_pages <= 1) {
    return null;
  }

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-t px-4 py-3">
      <p className="text-sm text-gray-500">
        Page {pagination.page} of {pagination.total_pages}
      </p>
      <div className="flex items-center gap-2">
        <button
          type="button"
          disabled={disabled || !pagination.has_previous}
          onClick={() => onPageChange(pagination.page - 1)}
          className="inline-flex items-center gap-1 rounded-lg border px-3 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-50 hover:bg-gray-50"
        >
          <ChevronLeft className="h-4 w-4" />
          Previous
        </button>
        <button
          type="button"
          disabled={disabled || !pagination.has_next}
          onClick={() => onPageChange(pagination.page + 1)}
          className="inline-flex items-center gap-1 rounded-lg border px-3 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-50 hover:bg-gray-50"
        >
          Next
          <ChevronRight className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}

export default function ProductsPage() {
  const router = useRouter();
  const { products, pagination, isLoading, error, fetchProducts, deleteProduct, setPage } =
    useProducts();

  useEffect(() => {
    fetchProducts({ page: 1 });
  }, [fetchProducts]);

  const handleDelete = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!confirm('Are you sure you want to delete this product?')) return;
    await deleteProduct(id);
  };

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">My Products</h1>
          <p className="text-gray-600 mt-1">All your generated product listings</p>
        </div>
      </div>

      {error && (
        <div className="bg-red-50 text-red-600 p-3 rounded-lg text-sm mb-4">{error}</div>
      )}

      <div className="bg-white rounded-xl border overflow-hidden">
        {isLoading ? (
          <p className="p-6 text-gray-500">Loading...</p>
        ) : products.length === 0 ? (
          <p className="p-6 text-gray-500">No products yet.</p>
        ) : (
          <div className="divide-y">
            {products.map((product) => (
              <div
                key={product.id}
                className="flex items-center justify-between p-4 hover:bg-gray-50 cursor-pointer"
                onClick={() => router.push(`/products/${product.id}`)}
              >
                <div>
                  <p className="font-medium">{product.name}</p>
                  <p className="text-sm text-gray-500">
                    {product.category || 'Uncategorized'} • {product.platform} • {product.market}
                  </p>
                  <p className="text-xs text-gray-400 mt-1">
                    {product.generations_count || 0} generations •{' '}
                    {new Date(product.created_at).toLocaleDateString()}
                  </p>
                </div>
                <button
                  onClick={(e) => handleDelete(product.id, e)}
                  className="p-2 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded-lg"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            ))}
          </div>
        )}
        {pagination && products.length > 0 && (
          <PaginationBar
            pagination={pagination}
            disabled={isLoading}
            onPageChange={(nextPage) => {
              void setPage(nextPage);
            }}
          />
        )}
      </div>
    </div>
  );
}
