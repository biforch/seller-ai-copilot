'use client';

import { useParams } from 'next/navigation';

import { ProposalReviewClient } from '@/components/features/ProposalReviewClient';

export default function ListingReviewDetailPage() {
  const params = useParams();
  const productId = params.id as string;
  const proposalId = params.proposal_id as string;

  return <ProposalReviewClient productId={productId} proposalId={proposalId} />;
}
