// =============================================================================
// hooks/useGrc.js — React Query hooks for GRC data
// One hook per register + mutation hooks for create/update.
// React Query v5 syntax: useQuery({ queryKey, queryFn })
// Depends on: @tanstack/react-query, api/grcApi.js
// =============================================================================

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  complianceApi,
  contractsApi,
  documentsApi,
  orgRolesApi,
  groupsApi,
} from "../api/grcApi.js";

// Re-export for convenience in pages that need raw API access
export { complianceApi, contractsApi };

// =============================================================================
//  Query keys — centralised to avoid typos across components
// =============================================================================

export const QUERY_KEYS = {
  documents: (filters) => ["documents", filters],
  document: (id) => ["documents", id],
  obligations: (filters) => ["obligations", filters],
  obligation: (id) => ["obligations", id],
  obligationsOverdue: ["obligations", "overdue"],
  obligationsDueSoon: ["obligations", "due-soon"],
  contracts: (filters) => ["contracts", filters],
  contract: (id) => ["contracts", id],
  contractsExpiring: ["contracts", "expiring"],
};

// =============================================================================
//  Document Register hooks
// =============================================================================

/**
 * Fetch all documents, optionally filtered.
 * @param {{ status?: string, department?: string }} filters
 */
export const useDocuments = (filters = {}) =>
  useQuery({
    queryKey: QUERY_KEYS.documents(filters),
    queryFn: () => documentsApi.list(filters),
    staleTime: 60_000, // 1 minute before refetch
  });

/** Fetch a single document by SharePoint item ID. */
export const useDocument = (id) =>
  useQuery({
    queryKey: QUERY_KEYS.document(id),
    queryFn: () => documentsApi.get(id),
    enabled: !!id,
  });

/** Create a new document in the Document Register. */
export const useCreateDocument = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (doc) => documentsApi.create(doc),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["documents"] });
    },
  });
};

/** Update a document entry. */
export const useUpdateDocument = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, updates }) => documentsApi.update(id, updates),
    onSuccess: (_, { id }) => {
      queryClient.invalidateQueries({ queryKey: ["documents"] });
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.document(id) });
    },
  });
};

/** Soft-delete (Withdraw) a document. */
export const useSoftDeleteDocument = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id) => documentsApi.softDelete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["documents"] });
    },
  });
};

// =============================================================================
//  Compliance Calendar hooks
// =============================================================================

/** Fetch all obligations. Status is calculated server-side on each read. */
export const useObligations = (filters = {}) =>
  useQuery({
    queryKey: QUERY_KEYS.obligations(filters),
    queryFn: () => complianceApi.list(filters),
    staleTime: 30_000, // Status can change daily — 30s stale time
  });

/** Fetch overdue obligations only. */
export const useOverdueObligations = () =>
  useQuery({
    queryKey: QUERY_KEYS.obligationsOverdue,
    queryFn: () => complianceApi.listOverdue(),
    staleTime: 30_000,
  });

/** Create a new obligation. */
export const useCreateObligation = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (obligation) => complianceApi.create(obligation),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["obligations"] });
    },
  });
};

/** Update an obligation (e.g. update due_date when completed). */
export const useUpdateObligation = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, updates }) => complianceApi.update(id, updates),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["obligations"] });
    },
  });
};

/**
 * Mark an obligation complete. For recurring obligations, rolls the due date
 * forward one period server-side.
 */
export const useCompleteObligation = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, completion_notes }) =>
      complianceApi.complete(id, { completion_notes }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["obligations"] });
    },
  });
};

/**
 * Escalate an overdue obligation to the Gap Analysis register.
 * Idempotent — safe to call multiple times.
 */
export const useEscalateObligation = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, escalation_notes }) =>
      complianceApi.escalate(id, { escalation_notes }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["obligations"] });
      // Gap Analysis list has likely changed too
      queryClient.invalidateQueries({ queryKey: ["gaps"] });
    },
  });
};

/** Soft-delete (Withdraw) an obligation. */
export const useSoftDeleteObligation = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id) => complianceApi.softDelete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["obligations"] });
    },
  });
};

// =============================================================================
//  Contract Register hooks
// =============================================================================

/** Fetch all contracts. Status calculated server-side. */
export const useContracts = (filters = {}) =>
  useQuery({
    queryKey: QUERY_KEYS.contracts(filters),
    queryFn: () => contractsApi.list(filters),
    staleTime: 60_000,
  });

/** Fetch contracts expiring within 60 days. */
export const useExpiringContracts = () =>
  useQuery({
    queryKey: QUERY_KEYS.contractsExpiring,
    queryFn: () => contractsApi.listExpiring(),
    staleTime: 60_000,
  });

/** Create a new contract. */
export const useCreateContract = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (contract) => contractsApi.create(contract),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["contracts"] });
    },
  });
};

/** Update a contract record. */
export const useUpdateContract = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, updates }) => contractsApi.update(id, updates),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["contracts"] });
    },
  });
};

/**
 * Update contract lifecycle status — Terminate, put Under Review, or Supersede.
 * Requires Compliance role (enforced by backend).
 */
export const useUpdateContractLifecycle = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, lifecycleStatus }) =>
      contractsApi.updateLifecycle(id, lifecycleStatus),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["contracts"] });
    },
  });
};

/**
 * Create a Compliance Calendar entry linked to a contract.
 * Invalidates both contracts and obligations.
 */
export const useAddContractObligation = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ contractId, obligation }) =>
      contractsApi.addObligation(contractId, obligation),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["obligations"] });
      queryClient.invalidateQueries({ queryKey: ["contracts"] });
    },
  });
};

/** Soft-delete (Withdraw) a contract. */
export const useSoftDeleteContract = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id) => contractsApi.softDelete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["contracts"] });
    },
  });
};

// =============================================================================
//  Org Roles hooks
// =============================================================================

/** Fetch every user with an org_role assigned, read live from Entra ID. */
export const useOrgRoles = () =>
  useQuery({
    queryKey: ["org-roles"],
    queryFn: () => orgRolesApi.list(),
    staleTime: 120_000,
  });

/** Controls/evidence owned per role — "who owns what". */
export const useOwnershipSummary = () =>
  useQuery({
    queryKey: ["ownership-summary"],
    queryFn: () => orgRolesApi.ownershipSummary(),
    staleTime: 120_000,
    retry: false,
  });

/** The distinct real Dragnet job titles — role vocabulary for control ownership. */
export const useJobTitles = () =>
  useQuery({
    queryKey: ["job-titles"],
    queryFn: () => orgRolesApi.jobTitles(),
    staleTime: 600_000,
  });

/** OrgOS-managed people groups (full objects with members). */
export const useGroups = () =>
  useQuery({
    queryKey: ["groups"],
    queryFn: () => groupsApi.list(),
    staleTime: 60_000,
  });

/** Active group names — the group contribution to the owner vocabulary. */
export const useGroupNames = () =>
  useQuery({
    queryKey: ["group-names"],
    queryFn: () => groupsApi.names(),
    staleTime: 120_000,
    // Groups are optional; never surface an error if the list isn't provisioned.
    retry: false,
  });

