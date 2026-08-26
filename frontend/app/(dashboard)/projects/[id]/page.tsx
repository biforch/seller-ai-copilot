'use client';

import { useEffect, useRef, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { ChevronLeft, ChevronRight } from 'lucide-react';

import { apiClient } from '@/app/api/client';
import type { ProjectDetail } from '@/types';

export default function ProjectDetailPage() {
  const params = useParams();
  const id = params.id as string;

  if (!id) {
    return <div className="p-8 text-red-600">Project not found.</div>;
  }

  return <ProjectDetailSession key={id} id={id} />;
}

function ProjectDetailSession({ id }: { id: string }) {
  const router = useRouter();

  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [page, setPage] = useState(1);
  const requestSeq = useRef(0);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const seq = ++requestSeq.current;
    const requestedPage = page;

    void apiClient.get<ProjectDetail>(`/projects/${id}`, {
      params: { page: requestedPage, page_size: 10 },
      signal: controller.signal,
    }).then((data) => {
      if (seq !== requestSeq.current || controller.signal.aborted) {
        return;
      }
      setProject(data);
    }).catch((err) => {
      if (controller.signal.aborted) {
        return;
      }
      if (seq !== requestSeq.current) {
        return;
      }
      setError(err instanceof Error ? err.message : 'Failed to load project');
    }).finally(() => {
      if (seq === requestSeq.current) {
        setIsLoading(false);
      }
    });

    return () => {
      abortRef.current?.abort();
    };
  }, [id, page]);

  const goToPage = (nextPage: number) => {
    setPage(nextPage);
    setIsLoading(true);
    setError(null);
  };

  if (isLoading && !project) {
    return <div className="p-8">Loading...</div>;
  }

  if (error || !project) {
    return <div className="p-8 text-red-600">{error || 'Project not found.'}</div>;
  }

  const productItems = project.products.items;
  const productPagination = project.products.pagination;

  return (
    <div className="max-w-5xl mx-auto px-4 py-8">
      <div className="bg-white border rounded-xl p-8">
        <div className="flex items-start justify-between">
          <div>
            <h1 className="text-3xl font-bold">{project.name}</h1>
            {project.description && (
              <p className="text-gray-500 mt-1">{project.description}</p>
            )}
          </div>
          <span className="px-3 py-1 rounded-full text-xs font-medium bg-gray-100 text-gray-700 capitalize">
            {project.status || 'active'}
          </span>
        </div>

        <div className="mt-4 text-gray-600 space-y-2">
          <p>Platform: {project.platform}</p>
          <p>Market: {project.market}</p>
          <p>Products: {project.product_count ?? productPagination.total}</p>
        </div>

      </div>

      <div className="bg-white border rounded-xl p-8 mt-6">
        <h2 className="text-lg font-semibold mb-4">Products</h2>

        {productItems.length === 0 ? (
          <p className="text-gray-500">No products yet — generate a listing to add one.</p>
        ) : (
          <>
            <div className="divide-y">
              {productItems.map((p) => (
                <button
                  key={p.id}
                  onClick={() => router.push(`/products/${p.id}`)}
                  className="w-full flex items-center justify-between py-3 text-left hover:bg-gray-50 px-2 rounded-lg"
                >
                  <div>
                    <p className="font-medium text-gray-900">{p.name}</p>
                    <p className="text-sm text-gray-500">
                      {p.category || 'Uncategorized'} • {p.platform} • {p.market}
                    </p>
                  </div>
                  <span className="text-sm text-gray-400">
                    {p.generations_count} generation{p.generations_count === 1 ? '' : 's'}
                  </span>
                </button>
              ))}
            </div>

            {productPagination.total_pages > 1 && (
              <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
                <p className="text-sm text-gray-500">
                  Page {productPagination.page} of {productPagination.total_pages}
                </p>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    disabled={isLoading || !productPagination.has_previous}
                    onClick={() => goToPage(page - 1)}
                    className="inline-flex items-center gap-1 rounded-lg border px-3 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-50 hover:bg-gray-50"
                  >
                    <ChevronLeft className="h-4 w-4" />
                    Previous
                  </button>
                  <button
                    type="button"
                    disabled={isLoading || !productPagination.has_next}
                    onClick={() => goToPage(page + 1)}
                    className="inline-flex items-center gap-1 rounded-lg border px-3 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-50 hover:bg-gray-50"
                  >
                    Next
                    <ChevronRight className="h-4 w-4" />
                  </button>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
