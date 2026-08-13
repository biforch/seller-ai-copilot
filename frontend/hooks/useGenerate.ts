'use client';

import {
  useCallback,
  useRef,
  useState,
} from 'react';

import { apiClient } from '@/app/api/client';

import type {
  GenerateFormData,
  AnalyzeFormData,
  ListingResult,
  AnalyzeResult,
} from '@/types';

function createIdempotencyKey(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (char) => {
    const random = Math.floor(Math.random() * 16);
    const value = char === 'x' ? random : (random & 0x3) | 0x8;
    return value.toString(16);
  });
}

export function useGenerate() {
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [listingResult, setListingResult] = useState<ListingResult | null>(null);
  const [analyzeResult, setAnalyzeResult] = useState<AnalyzeResult | null>(null);

  const listingKeyRef = useRef<string | null>(null);
  const analyzeKeyRef = useRef<string | null>(null);

  const generateListing = useCallback(async (data: GenerateFormData, options?: { retry?: boolean }) => {
    setIsLoading(true);
    setError(null);

    if (!options?.retry || !listingKeyRef.current) {
      listingKeyRef.current = createIdempotencyKey();
    }

    try {
      const result = await apiClient.post<ListingResult>(
        '/generate/listing',
        data,
        { 'Idempotency-Key': listingKeyRef.current },
      );

      setListingResult(result);
      setAnalyzeResult(null);
      listingKeyRef.current = null;
      return result;
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Generation failed';
      setError(msg);
      throw err;
    } finally {
      setIsLoading(false);
    }
  }, []);

  const analyzeListing = useCallback(async (data: AnalyzeFormData, options?: { retry?: boolean }) => {
    setIsLoading(true);
    setError(null);

    if (!options?.retry || !analyzeKeyRef.current) {
      analyzeKeyRef.current = createIdempotencyKey();
    }

    try {
      const result = await apiClient.post<AnalyzeResult>(
        '/generate/analyze',
        data,
        { 'Idempotency-Key': analyzeKeyRef.current },
      );

      setAnalyzeResult(result);
      setListingResult(null);
      analyzeKeyRef.current = null;
      return result;
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Analysis failed';
      setError(msg);
      throw err;
    } finally {
      setIsLoading(false);
    }
  }, []);

  const reset = useCallback(() => {
    setListingResult(null);
    setAnalyzeResult(null);
    setError(null);
    listingKeyRef.current = null;
    analyzeKeyRef.current = null;
  }, []);

  return {
    isLoading,
    error,
    listingResult,
    analyzeResult,
    generateListing,
    analyzeListing,
    reset,
  };
}
