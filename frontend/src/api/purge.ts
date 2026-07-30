// Mirrors backend/app/modules/purge/router.py — keep in lock-step.
// All endpoints sit at `/api/v1/admin/purge/*` and require the
// `platform.purge_data` capability, which is deliberately separate from
// `platform.manage_tenants`: purge is the only irreversible delete in the
// product, so it can be withheld from someone who otherwise administers
// tenants.

import { apiClient } from "./client";

export type PurgeKind = "block" | "farm" | "tenant_data";

export interface PurgeBlocker {
  reason: string;
  detail: string;
}

export interface PurgeTableCount {
  table: string;
  rows: number;
}

export interface PurgePreview {
  kind: PurgeKind;
  id: string;
  label: string;
  /** What the admin must type to confirm — entity name/code, or tenant slug. */
  confirmation_phrase: string;
  tenant_id: string;
  tenant_slug: string | null;
  archived: boolean;
  /** Empty means ready to purge. Non-empty is why the button stays disabled. */
  blocking: PurgeBlocker[];
  db_rows: PurgeTableCount[];
  total_rows: number;
  storage: {
    attachment_objects: number;
    imagery_objects: number;
    /** Kept because another block — possibly another tenant — shares the AOI. */
    imagery_objects_kept_shared: number;
  };
  pgstac: { items: number; collections: number };
}

export interface PurgeReceipt {
  id: string;
  kind: string;
  target_label: string | null;
  actor_email: string | null;
  reason: string | null;
  started_at: string | null;
  finished_at: string | null;
  deleted: Record<string, unknown>;
  /** orphans_found > 0 means the purge did not finish. */
  verification: Record<string, unknown>;
  errors: string[];
  created_at: string;
}

export interface PurgeJob {
  id: string;
  kind: string;
  target_id: string;
  target_label: string | null;
  tenant_id: string | null;
  tenant_slug: string | null;
  status: "queued" | "running" | "succeeded" | "failed";
  phase: string | null;
  phases: { name: string; detail: Record<string, unknown> }[];
  preview: PurgePreview;
  dry_run: boolean;
  reason: string | null;
  error: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  created_by_email: string | null;
  receipt: PurgeReceipt | null;
}

export interface PurgeSubmitPayload {
  kind: PurgeKind;
  id: string;
  tenant_id: string;
  confirmation: string;
  reason?: string | null;
  dry_run?: boolean;
}

export interface TenantBlockEntity {
  id: string;
  name: string | null;
  code: string | null;
  unit_type: string;
  archived: boolean;
}

export interface TenantFarmEntity {
  id: string;
  name: string | null;
  code: string | null;
  archived: boolean;
  blocks: TenantBlockEntity[];
}

export interface TenantEntities {
  tenant_id: string;
  tenant_slug: string;
  tenant_status: string;
  farms: TenantFarmEntity[];
}

export interface OrphanRow {
  schema: string;
  table: string;
  column: string;
  rows: number;
}

export interface OrphanScan {
  orphans: OrphanRow[];
  orphans_found: number;
  orphan_rows: number;
  scanned_tables: number;
  schemas: string[];
  /** Schemas on disk with no tenants row — residue of a half-completed purge. */
  stray_schemas: string[];
}

export async function getPurgePreview(params: {
  kind: PurgeKind;
  id: string;
  tenantId: string;
}): Promise<PurgePreview> {
  const { data } = await apiClient.get<PurgePreview>("/v1/admin/purge/preview", {
    params: { kind: params.kind, id: params.id, tenant_id: params.tenantId },
  });
  return data;
}

export async function submitPurge(payload: PurgeSubmitPayload): Promise<PurgeJob> {
  const { data } = await apiClient.post<PurgeJob>("/v1/admin/purge", payload);
  return data;
}

export async function getPurgeJob(jobId: string): Promise<PurgeJob> {
  const { data } = await apiClient.get<PurgeJob>(`/v1/admin/purge/jobs/${jobId}`);
  return data;
}

export async function listPurgeJobs(tenantId?: string): Promise<PurgeJob[]> {
  const { data } = await apiClient.get<PurgeJob[]>("/v1/admin/purge/jobs", {
    params: tenantId ? { tenant_id: tenantId } : undefined,
  });
  return data;
}

export async function getTenantEntities(tenantId: string): Promise<TenantEntities> {
  const { data } = await apiClient.get<TenantEntities>(
    `/v1/admin/purge/tenants/${tenantId}/entities`,
  );
  return data;
}

export async function scanOrphans(): Promise<OrphanScan> {
  const { data } = await apiClient.get<OrphanScan>("/v1/admin/purge/orphans");
  return data;
}
