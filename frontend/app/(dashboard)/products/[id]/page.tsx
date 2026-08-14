'use client';

import { useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { ArrowLeft, ClipboardList } from 'lucide-react';

import { ListingResultView } from '@/components/features/ListingResult';
import { ScoreCard } from '@/components/features/ScoreCard';
import { useProducts } from '@/hooks/useProducts';
import type { ProductDetail, Generation, ListingScore } from '@/types';

function groupLabel(dateStr: string): string {
  const date = new Date(dateStr);
  const now = new Date();

  const startOfDay = (d: Date) =>
    new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();

  const diffDays = Math.round(
    (startOfDay(now) - startOfDay(date)) / (1000 * 60 * 60 * 24)
  );

  if (diffDays <= 0) return 'Today';
  if (diffDays === 1) return 'Yesterday';
  if (diffDays <= 7) return 'This week';
  return 'Earlier';
}

export default function ProductDetailPage() {
  const params = useParams();
  const router = useRouter();
  const { fetchProduct, isLoading, error } = useProducts();
  const [product, setProduct] = useState<ProductDetail | null>(null);

  useEffect(() => {
    if (params.id) {
      fetchProduct(params.id as string).then(setProduct);
    }
  }, [params.id, fetchProduct]);

  // group generations by relative time bucket, preserving newest-first order
  const groups: { label: string; items: Generation[] }[] = [];
  if (product) {
    for (const gen of product.generations) {
      const label = groupLabel(gen.created_at);
      const existing = groups.find((g) => g.label === label);
      if (existing) {
        existing.items.push(gen);
      } else {
        groups.push({ label, items: [gen] });
      }
    }
  }

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      <button
        onClick={() => router.push('/products')}
        className="flex items-center gap-2 text-gray-600 hover:text-gray-900 mb-6"
      >
        <ArrowLeft className="w-4 h-4" />
        Back to Products
      </button>

      {isLoading ? (
        <p className="text-gray-500">Loading...</p>
      ) : error ? (
        <div className="bg-red-50 text-red-600 p-3 rounded-lg text-sm">{error}</div>
      ) : product ? (
        <div>
          <div className="mb-8">
            {product.project && (
              <button
                onClick={() => router.push(`/projects/${product.project!.id}`)}
                className="text-sm text-blue-600 hover:underline mb-1"
              >
                {product.project.name}
              </button>
            )}
            <h1 className="text-3xl font-bold text-gray-900">{product.name}</h1>
            <p className="text-gray-600 mt-1">
              {product.category || 'Uncategorized'} • {product.platform} • {product.market}
            </p>
            {product.target_customer && (
              <p className="text-gray-500 text-sm mt-1">
                Target customer: {product.target_customer}
              </p>
            )}
            <div className="mt-4">
              <button
                type="button"
                onClick={() => router.push(`/products/${product.id}/listing/reviews`)}
                className="inline-flex items-center gap-2 rounded-lg border border-blue-200 bg-blue-50 px-4 py-2 text-sm font-medium text-blue-700 hover:bg-blue-100"
              >
                <ClipboardList className="h-4 w-4" />
                AI Listing Reviews
              </button>
              <p className="text-sm text-gray-500 mt-2">
                Review AI suggestions before creating a new listing version.
              </p>
            </div>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-10">
            <div className="lg:col-span-2 space-y-6">
              {product.score ? (
                <ScoreCard score={product.score} />
              ) : (
                <div className="bg-white rounded-xl border p-6 text-sm text-gray-500">
                  No listing generated yet — generate one to see a quality score.
                </div>
              )}
            </div>

            <div className="bg-white rounded-xl border p-6">
              <h3 className="text-sm font-medium text-gray-500 mb-3">
                Next Actions
              </h3>
              {product.next_actions.length === 0 ? (
                <p className="text-sm text-gray-400">Nothing pending.</p>
              ) : (
                <ul className="space-y-3">
                  {product.next_actions.map((action, i) => (
                    <li key={i} className="text-sm">
                      <p className="font-medium text-gray-900">{action.title}</p>
                      <p className="text-gray-500">{action.reason}</p>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>

          <h2 className="text-lg font-semibold mb-4">Generation Timeline</h2>
          {product.generations.length === 0 ? (
            <p className="text-gray-500">No generations yet.</p>
          ) : (
            <div className="space-y-10">
              {groups.map((group) => (
                <div key={group.label}>
                  <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-4">
                    {group.label}
                  </h3>
                  <div className="space-y-8">
                    {group.items.map((gen) => (
                      <div key={gen.id}>
                        <div className="flex items-center gap-2 mb-4">
                          <span className="px-2 py-1 bg-blue-50 text-blue-700 text-xs rounded-full uppercase">
                            {gen.type}
                          </span>
                          <span className="text-sm text-gray-400">
                            {new Date(gen.created_at).toLocaleString()}
                          </span>
                        </div>
                        {gen.type === 'listing' && (
                          <ListingResultView
                            result={{
                              product_id: product.id,
                              title: (gen.output.title as string) || '',
                              bullets: (gen.output.bullets as string[]) || [],
                              description: (gen.output.description as string) || '',
                              keywords: (gen.output.keywords as string[]) || [],
                              score: gen.output.score as ListingScore | undefined,
                              tokens_used: gen.tokens_used,
                            }}
                          />
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      ) : (
        <p className="text-gray-500">Product not found.</p>
      )}
    </div>
  );
}
