'use client';

import { useEffect, useState } from 'react';
import { useParams, useSearchParams } from 'next/navigation';

import { ProposalInboxClient } from '@/components/features/ProposalInboxClient';
import { useProducts } from '@/hooks/useProducts';
import type { ProposalListStatus } from '@/types';

const VALID_STATUSES = new Set<ProposalListStatus>([
  'reviewing',
  'approved',
  'rejected',
  'superseded',
  'all',
]);

function parseStatus(value: string | null): ProposalListStatus {
  if (value && VALID_STATUSES.has(value as ProposalListStatus)) {
    return value as ProposalListStatus;
  }
  return 'reviewing';
}

export default function ListingReviewsPage() {
  const params = useParams();
  const searchParams = useSearchParams();
  const productId = params.id as string;
  const initialStatus = parseStatus(searchParams.get('status'));
  const { fetchProduct } = useProducts();
  const [productName, setProductName] = useState<string | undefined>();

  useEffect(() => {
    void fetchProduct(productId).then((product) => {
      if (product) {
        setProductName(product.name);
      }
    });
  }, [fetchProduct, productId]);

  return (
    <ProposalInboxClient
      productId={productId}
      productName={productName}
      initialStatus={initialStatus}
    />
  );
}
