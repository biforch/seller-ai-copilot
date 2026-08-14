'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { ArrowLeft, RefreshCw } from 'lucide-react';

import { FieldDecisionsEditor } from '@/components/features/FieldDecisionsEditor';
import { ListingSnapshotPanel } from '@/components/features/ListingSnapshotPanel';
import { ProposalDiffPanel } from '@/components/features/ProposalDiffPanel';
import { ProposalStatusBadge } from '@/components/features/ProposalStatusBadge';
import { useListingProposalReview } from '@/hooks/useListingProposalReview';
import {
  canApproveProposal,
  isProposalReadonlyStatus,
  type ListingDecisionField,
} from '@/lib/listing-proposals';
import type { FieldDecisionValue } from '@/types';

interface ProposalReviewClientProps {
  productId: string;
  proposalId: string;
}

export function ProposalReviewClient({ productId, proposalId }: ProposalReviewClientProps) {
  const router = useRouter();
  const [showRejectConfirm, setShowRejectConfirm] = useState(false);
  const {
    detail,
    decisions,
    isLoading,
    isSaving,
    isApproving,
    isRejecting,
    error,
    notFound,
    conflictMessage,
    actionNotice,
    approveResult,
    load,
    saveDecisions,
    approve,
    reject,
    updateDecision,
  } = useListingProposalReview(productId, proposalId);

  const readonly = detail ? isProposalReadonlyStatus(detail.proposal.status) : false;
  const hasBaseVersion = Boolean(detail?.base_version);
  const approveState =
    detail && decisions
      ? canApproveProposal(detail.proposal.status, decisions, hasBaseVersion)
      : { allowed: false, reason: null };
  const mutationBusy = isSaving || isApproving || isRejecting;

  const handleDecisionChange = (field: ListingDecisionField, value: FieldDecisionValue) => {
    updateDecision(field, value);
  };

  const handleConfirmReject = async () => {
    const result = await reject();
    if (result) {
      setShowRejectConfirm(false);
    }
  };

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      <button
        type="button"
        onClick={() => router.push(`/products/${productId}/listing/reviews`)}
        className="flex items-center gap-2 text-gray-600 hover:text-gray-900 mb-6"
      >
        <ArrowLeft className="w-4 h-4" />
        Back to Reviews
      </button>

      {isLoading ? (
        <p className="text-gray-500">Loading proposal...</p>
      ) : notFound || !detail || !decisions ? (
        <div className="rounded-lg bg-red-50 p-4 text-sm text-red-600" role="alert">
          {error ?? 'Proposal not found or you do not have access.'}
        </div>
      ) : (
        <div className="space-y-6">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <div className="flex flex-wrap items-center gap-3 mb-2">
                <h1 className="text-3xl font-bold text-gray-900">Review AI Proposal</h1>
                <ProposalStatusBadge status={detail.proposal.status} />
              </div>
              <p className="text-gray-600">
                Revision {detail.proposal.revision}
                {detail.proposal.reviewed_at
                  ? ` • Reviewed ${new Date(detail.proposal.reviewed_at).toLocaleString()}`
                  : ''}
              </p>
            </div>
            <button
              type="button"
              onClick={() => void load()}
              disabled={mutationBusy}
              className="inline-flex items-center gap-2 rounded-lg border px-4 py-2 text-sm hover:bg-gray-50 disabled:opacity-50"
            >
              <RefreshCw className="h-4 w-4" />
              Reload
            </button>
          </div>

          {conflictMessage && (
            <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900" role="alert">
              <p>{conflictMessage}</p>
              <button
                type="button"
                onClick={() => void load()}
                className="mt-3 rounded-lg bg-amber-700 px-3 py-2 text-white text-sm hover:bg-amber-800"
              >
                Reload proposal
              </button>
            </div>
          )}

          {error && !conflictMessage && (
            <div className="rounded-lg bg-red-50 p-3 text-sm text-red-600" role="alert">
              {error}
            </div>
          )}

          {actionNotice && (
            <div className="rounded-lg bg-green-50 p-3 text-sm text-green-700" role="status">
              {actionNotice}
            </div>
          )}

          <div className="grid gap-6 xl:grid-cols-2">
            <ListingSnapshotPanel
              title="Candidate Listing"
              snapshot={detail.proposal.candidate_snapshot}
            />
            {detail.base_version ? (
              <ListingSnapshotPanel
                title="Base Listing"
                snapshot={{
                  title: detail.base_version.title,
                  bullets: detail.base_version.bullets,
                  description: detail.base_version.description,
                  backend_keywords: detail.base_version.backend_keywords,
                }}
              />
            ) : (
              <ListingSnapshotPanel
                title="Base Listing"
                emptyMessage="This is the first listing version for this product. There is no previous base listing to compare against."
              />
            )}
          </div>

          <ProposalDiffPanel diff={detail.diff} />

          <FieldDecisionsEditor
            decisions={decisions}
            readonly={readonly}
            onChange={handleDecisionChange}
          />

          {!readonly && (
            <div className="rounded-xl border bg-white p-6 space-y-4">
              <h3 className="text-sm font-medium text-gray-500">Actions</h3>
              {!approveState.allowed && approveState.reason && (
                <p className="text-sm text-amber-700">{approveState.reason}</p>
              )}
              <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap">
                <button
                  type="button"
                  onClick={() => void saveDecisions()}
                  disabled={mutationBusy}
                  className="rounded-lg bg-blue-600 px-4 py-2 text-white text-sm hover:bg-blue-700 disabled:opacity-50"
                >
                  {isSaving ? 'Saving...' : 'Save Decisions'}
                </button>
                <button
                  type="button"
                  onClick={() => void approve()}
                  disabled={mutationBusy || !approveState.allowed}
                  className="rounded-lg bg-green-600 px-4 py-2 text-white text-sm hover:bg-green-700 disabled:opacity-50"
                >
                  {isApproving ? 'Approving...' : 'Approve Proposal'}
                </button>
                {!showRejectConfirm ? (
                  <button
                    type="button"
                    onClick={() => setShowRejectConfirm(true)}
                    disabled={mutationBusy}
                    className="rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-red-700 text-sm hover:bg-red-100 disabled:opacity-50"
                  >
                    Reject Proposal
                  </button>
                ) : (
                  <div className="flex flex-col gap-2 rounded-lg border border-red-200 bg-red-50 p-3">
                    <p className="text-sm text-red-800">
                      Reject this proposal? No listing version will be created.
                    </p>
                    <div className="flex flex-wrap gap-2">
                      <button
                        type="button"
                        onClick={() => void handleConfirmReject()}
                        disabled={mutationBusy}
                        className="rounded-lg bg-red-600 px-4 py-2 text-white text-sm hover:bg-red-700 disabled:opacity-50"
                      >
                        {isRejecting ? 'Rejecting...' : 'Confirm Reject'}
                      </button>
                      <button
                        type="button"
                        onClick={() => setShowRejectConfirm(false)}
                        disabled={mutationBusy}
                        className="rounded-lg border px-4 py-2 text-sm hover:bg-white disabled:opacity-50"
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          {readonly && detail.approved_version && (
            <section className="rounded-xl border bg-white p-6">
              <h3 className="text-sm font-medium text-gray-500 mb-2">Approved Version</h3>
              <p className="text-sm text-gray-700">
                Version {detail.approved_version.version_number} •{' '}
                {detail.approved_version.title}
              </p>
            </section>
          )}

          {approveResult?.approved_version && (
            <section className="rounded-xl border border-green-200 bg-green-50 p-6">
              <h3 className="text-sm font-medium text-green-800 mb-2">Latest Approved Version</h3>
              <p className="text-sm text-green-900">
                Version {approveResult.approved_version.version_number} •{' '}
                {approveResult.approved_version.title}
              </p>
            </section>
          )}
        </div>
      )}
    </div>
  );
}
