'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import {
  approveListingProposal,
  getListingProposal,
  patchListingProposalDecisions,
  rejectListingProposal,
} from '@/app/api/listing-proposals';
import { isApiClientError } from '@/lib/api-client-error';
import { isProposalRefreshRequiredError } from '@/lib/listing-proposals';
import type {
  ApproveProposalResponse,
  FieldDecisions,
  ListingProposalDetail,
  RejectProposalResponse,
} from '@/types';

export function useListingProposalReview(productId: string, proposalId: string) {
  const [detail, setDetail] = useState<ListingProposalDetail | null>(null);
  const [decisions, setDecisions] = useState<FieldDecisions | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [isApproving, setIsApproving] = useState(false);
  const [isRejecting, setIsRejecting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [conflictMessage, setConflictMessage] = useState<string | null>(null);
  const [actionNotice, setActionNotice] = useState<string | null>(null);
  const [approveResult, setApproveResult] = useState<ApproveProposalResponse | null>(null);
  const [rejectResult, setRejectResult] = useState<RejectProposalResponse | null>(null);

  const abortRef = useRef<AbortController | null>(null);
  const requestSeq = useRef(0);
  const paramKey = `${productId}:${proposalId}`;
  const [seenKey, setSeenKey] = useState(paramKey);

  if (paramKey !== seenKey) {
    setSeenKey(paramKey);
    setIsLoading(true);
    setError(null);
    setNotFound(false);
    setActionNotice(null);
  }

  const applyDetail = useCallback((next: ListingProposalDetail) => {
    setDetail(next);
    setDecisions({ ...next.proposal.field_decisions });
    setConflictMessage(null);
  }, []);

  const load = useCallback(async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const seq = ++requestSeq.current;

    setIsLoading(true);
    setError(null);
    setNotFound(false);
    setActionNotice(null);

    try {
      const data = await getListingProposal(productId, proposalId, controller.signal);
      if (controller.signal.aborted || seq !== requestSeq.current) {
        return null;
      }
      applyDetail(data);
      return data;
    } catch (err) {
      if (controller.signal.aborted || seq !== requestSeq.current) {
        return null;
      }
      if (isApiClientError(err) && err.httpStatus === 404) {
        setNotFound(true);
        setDetail(null);
        setDecisions(null);
        setError('Proposal not found or you do not have access.');
      } else {
        setError(err instanceof Error ? err.message : 'Failed to load proposal');
      }
      return null;
    } finally {
      if (!controller.signal.aborted && seq === requestSeq.current) {
        setIsLoading(false);
      }
    }
  }, [applyDetail, productId, proposalId]);

  useEffect(() => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const seq = ++requestSeq.current;
    const requestedProductId = productId;
    const requestedProposalId = proposalId;

    void getListingProposal(requestedProductId, requestedProposalId, controller.signal)
      .then((data) => {
        if (controller.signal.aborted || seq !== requestSeq.current) {
          return;
        }
        applyDetail(data);
      })
      .catch((err) => {
        if (controller.signal.aborted || seq !== requestSeq.current) {
          return;
        }
        if (isApiClientError(err) && err.httpStatus === 404) {
          setNotFound(true);
          setDetail(null);
          setDecisions(null);
          setError('Proposal not found or you do not have access.');
        } else {
          setError(err instanceof Error ? err.message : 'Failed to load proposal');
        }
      })
      .finally(() => {
        if (!controller.signal.aborted && seq === requestSeq.current) {
          setIsLoading(false);
        }
      });

    return () => {
      abortRef.current?.abort();
    };
  }, [applyDetail, productId, proposalId]);

  const handleMutationError = useCallback((err: unknown) => {
    if (isProposalRefreshRequiredError(err)) {
      setConflictMessage(
        err instanceof Error
          ? err.message
          : 'This proposal was updated elsewhere. Reload to continue with the latest revision.',
      );
      return;
    }
    setError(err instanceof Error ? err.message : 'Request failed');
  }, []);

  const saveDecisions = useCallback(async () => {
    if (!detail || !decisions) {
      return null;
    }
    setIsSaving(true);
    setError(null);
    setActionNotice(null);
    try {
      const response = await patchListingProposalDecisions(productId, proposalId, {
        expected_revision: detail.proposal.revision,
        decisions,
      });
      const refreshed = await getListingProposal(productId, proposalId);
      applyDetail(refreshed);
      setActionNotice('Decisions saved.');
      return response;
    } catch (err) {
      handleMutationError(err);
      return null;
    } finally {
      setIsSaving(false);
    }
  }, [applyDetail, decisions, detail, handleMutationError, productId, proposalId]);

  const approve = useCallback(async () => {
    if (!detail || !decisions) {
      return null;
    }
    setIsApproving(true);
    setError(null);
    setActionNotice(null);
    try {
      const response = await approveListingProposal(productId, proposalId, {
        expected_revision: detail.proposal.revision,
        decisions,
      });
      setApproveResult(response);
      const refreshed = await getListingProposal(productId, proposalId);
      applyDetail(refreshed);
      setActionNotice(
        response.replay
          ? 'Approval replayed — listing version already exists.'
          : `Approved. Created listing version v${response.approved_version.version_number}.`,
      );
      return response;
    } catch (err) {
      handleMutationError(err);
      return null;
    } finally {
      setIsApproving(false);
    }
  }, [applyDetail, decisions, detail, handleMutationError, productId, proposalId]);

  const reject = useCallback(async () => {
    if (!detail) {
      return null;
    }
    setIsRejecting(true);
    setError(null);
    setActionNotice(null);
    try {
      const response = await rejectListingProposal(productId, proposalId, {
        expected_revision: detail.proposal.revision,
      });
      setRejectResult(response);
      const refreshed = await getListingProposal(productId, proposalId);
      applyDetail(refreshed);
      setActionNotice(
        response.replay ? 'Reject replayed — proposal was already rejected.' : 'Proposal rejected.',
      );
      return response;
    } catch (err) {
      handleMutationError(err);
      return null;
    } finally {
      setIsRejecting(false);
    }
  }, [applyDetail, detail, handleMutationError, productId, proposalId]);

  const updateDecision = useCallback(
    (field: keyof FieldDecisions, value: FieldDecisions[keyof FieldDecisions]) => {
      setDecisions((prev) => (prev ? { ...prev, [field]: value } : prev));
    },
    [],
  );

  return {
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
    rejectResult,
    load,
    saveDecisions,
    approve,
    reject,
    updateDecision,
  };
}
