'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { ChevronLeft, ChevronRight, Plus } from 'lucide-react';

import { useProjects } from '@/hooks/useProjects';

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
    <div className="mt-6 flex flex-wrap items-center justify-between gap-3">
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

export default function ProjectsPage() {
  const router = useRouter();
  const [page, setPage] = useState(1);
  const { projects, pagination, isLoading, error, fetchProjects } = useProjects();

  useEffect(() => {
    fetchProjects({ page });
  }, [fetchProjects, page]);

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      <div className="flex justify-between items-center mb-8">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">My Projects</h1>
          <p className="text-gray-600 mt-1">Manage your AI selling projects</p>
        </div>

        <button
          onClick={() => router.push('/projects/create')}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
        >
          <Plus className="w-5 h-5" />
          New Project
        </button>
      </div>

      {error && (
        <div className="mb-4 rounded-lg bg-red-50 p-3 text-sm text-red-600">{error}</div>
      )}

      {isLoading ? (
        <p className="text-gray-500">Loading...</p>
      ) : projects.length === 0 ? (
        <div className="bg-white border rounded-xl p-8 text-center">
          <p className="text-gray-500 mb-4">No projects yet</p>
          <button
            onClick={() => router.push('/projects/create')}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg"
          >
            Create your first project
          </button>
        </div>
      ) : (
        <>
          <div className="grid md:grid-cols-3 gap-5">
            {projects.map((project) => (
              <div
                key={project.id}
                onClick={() => router.push(`/projects/${project.id}`)}
                className="bg-white border rounded-xl p-6 cursor-pointer hover:shadow-md transition"
              >
                <h2 className="font-semibold text-lg">{project.name}</h2>
                <div className="mt-3 text-sm text-gray-500">
                  <p>Platform: {project.platform}</p>
                  <p>Market: {project.market}</p>
                  <p>Products: {project.product_count ?? 0}</p>
                </div>
              </div>
            ))}
          </div>
          {pagination && (
            <PaginationBar
              pagination={pagination}
              disabled={isLoading}
              onPageChange={setPage}
            />
          )}
        </>
      )}
    </div>
  );
}
