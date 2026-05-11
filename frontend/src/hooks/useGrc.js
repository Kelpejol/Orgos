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
  rolesApi,
} from "../api/grcApi.js";

// =============================================================================
//  Query keys — centralised to avoid typos across components
// =============================================================================

export const QUERY_KEYS = {
  documents: (filters) => ["documents", filters],
  document: (id) => ["documents", id],
  roles: (filters) => ["roles", filters],
  role: (id) => ["roles", id],
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
//  Role Register hooks
// =============================================================================

/** Fetch all roles, optionally filtered by department. */
export const useRoles = (filters = {}) =>
  useQuery({
    queryKey: QUERY_KEYS.roles(filters),
    queryFn: () => rolesApi.list(filters),
    staleTime: 120_000, // Roles change infrequently — 2 min stale time
  });

/** Fetch a single role. */
export const useRole = (id) =>
  useQuery({
    queryKey: QUERY_KEYS.role(id),
    queryFn: () => rolesApi.get(id),
    enabled: !!id,
  });

/** Create a new role. */
export const useCreateRole = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (role) => rolesApi.create(role),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["roles"] });
    },
  });
};

/** Update a role — primary use case: reassigning current_holder_id. */
export const useUpdateRole = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, updates }) => rolesApi.update(id, updates),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["roles"] });
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


/** Fetch all unassigned roles — used by Work Hub urgency stream. */
export const useUnassignedRoles = () =>
  useQuery({
    queryKey: ["roles", "unassigned"],
    queryFn: () => rolesApi.listUnassigned(),
    staleTime: 30_000,
  });

/** Assign a person to an unassigned role. */
export const useAssignRole = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, holderOid }) =>
      rolesApi.assign(id, holderOid),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["roles"] });
    },
  });
};
