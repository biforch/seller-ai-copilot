'use client';

import { useCallback, useRef, useState } from 'react';

import { apiClient } from '@/app/api/client';

import type { PaginatedResponse, PaginationMeta, Project } from '@/types';

export interface FetchProjectsOptions {
  page?: number;
  page_size?: number;
  sort_by?: string;
  sort_order?: 'asc' | 'desc';
}

export function useProjects() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [pagination, setPagination] = useState<PaginationMeta | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const requestSeq = useRef(0);

  const fetchProjects = useCallback(async (options: FetchProjectsOptions = {}) => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const seq = ++requestSeq.current;

    setIsLoading(true);
    setError(null);

    try {
      const data = await apiClient.get<PaginatedResponse<Project>>('/projects', {
        params: {
          page: options.page ?? 1,
          page_size: options.page_size ?? 20,
          sort_by: options.sort_by,
          sort_order: options.sort_order,
        },
        signal: controller.signal,
      });

      if (seq !== requestSeq.current || controller.signal.aborted) {
        return null;
      }

      setProjects(data.items);
      setPagination(data.pagination);
      return data;
    } catch (err) {
      if (controller.signal.aborted) {
        return null;
      }
      setError(err instanceof Error ? err.message : 'Failed to fetch projects');
      return null;
    } finally {
      if (seq === requestSeq.current) {
        setIsLoading(false);
      }
    }
  }, []);

  const createProject = useCallback(
    async (name: string, platform: string, market: string) => {
      const data = await apiClient.post<Project>('/projects', {
        name,
        platform,
        market,
      });

      await fetchProjects({ page: 1 });
      return data;
    },
    [fetchProjects]
  );

  return {
    projects,
    pagination,
    isLoading,
    error,
    fetchProjects,
    createProject,
  };
}
