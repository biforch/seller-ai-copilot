'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { Trash2 } from 'lucide-react';

import { useProducts } from '@/hooks/useProducts';

export default function ProductsPage() {
  const router = useRouter();
  const { products, isLoading, error, fetchProducts, deleteProduct } = useProducts();

  useEffect(() => {
    fetchProducts();
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
        <button
          onClick={() => router.push('/generate')}
          className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
        >
          New Listing
        </button>
      </div>

      {error && (
        <div className="bg-red-50 text-red-600 p-3 rounded-lg text-sm mb-4">{error}</div>
      )}

      <div className="bg-white rounded-xl border">
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
                    {product.category || 'Uncategorized'} • {product.platform} •{' '}
                    {product.market}
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
      </div>
    </div>
  );
}
