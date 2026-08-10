import { apiClient } from "@/api/client";

/**
 * Action Center — recommendations and alerts as one queue.
 *
 * Two status vocabularies travel on every row and both are load-bearing:
 * `status` is the unified lifecycle the tabs are built from, `native_status`
 * is the row's real state in its own table. The row's action buttons and the
 * audit trail need the second; collapsing them would make an acknowledged
 * alert indistinguishable from a deferred recommendation.
 */
export type ItemKind = "recommendation" | "alert";
export type UnifiedStatus = "needs_action" | "dispatched" | "done" | "dismissed";
export type DueBucket = "overdue" | "today" | "week" | "later" | "monitoring" | "none";
export type GroupBy = "none" | "action_type" | "block" | "due";
export type ItemSeverity = "info" | "warning" | "critical";

/** Named windows the toolbar offers; `custom` is expressed as explicit bounds. */
export type DateRange = "1d" | "7d" | "30d" | "90d" | "all" | "custom";

export interface CellLocation {
  cell_id: string;
  row: number;
  col: number;
  ordinal: number | null;
  total: number | null;
  /** Cell centroid. The UI leads with this — a zone code means nothing to
   *  someone standing in a field, and decimal degrees paste into a map app. */
  lat: number | null;
  lon: number | null;
  area_m2: string | null;
}

export interface ActionItem {
  id: string;
  kind: ItemKind;
  status: UnifiedStatus;
  native_status: string;

  farm_id: string;
  block_id: string;
  block_code: string;
  block_name: string | null;
  cell: CellLocation | null;

  /** NULL only for alerts raised before migration 0063 — shown as
   *  unclassified rather than guessed. */
  action_type: string | null;
  severity: ItemSeverity;
  title_en: string;
  title_ar: string | null;
  detail_en: string | null;
  detail_ar: string | null;

  tree_code: string | null;
  tree_version: number | null;
  confidence: string | null;

  created_at: string;
  valid_until: string | null;
  due_bucket: DueBucket;
  due_date: string | null;

  assigned_membership_id: string | null;
  activity_id: string | null;
  scheduled_date: string | null;

  why: string | null;
  reasoning: Record<string, unknown>;
}

export interface ActionItemGroup {
  key: string;
  label: string;
  count: number;
  critical_count: number;
  block_count: number;
  cell_count: number;
  responsible_membership_id: string | null;
  items: ActionItem[];
}

export interface ActionItemListResponse {
  total: number;
  /** Per-tab counts for the filtered set with the tab NOT applied, so a tab
   *  never promises rows the active date range has already excluded. */
  status_counts: Record<string, number>;
  grouped_by: GroupBy;
  groups: ActionItemGroup[];
}

export interface ListActionItemsParams {
  farm_id: string;
  status?: UnifiedStatus | "all";
  kind?: ItemKind[];
  block_id?: string;
  action_type?: string[];
  severity?: ItemSeverity[];
  assigned_membership_id?: string;
  date_range?: Exclude<DateRange, "custom">;
  raised_from?: string;
  raised_to?: string;
  group_by?: GroupBy;
  limit?: number;
}

export async function listActionItems(
  params: ListActionItemsParams,
): Promise<ActionItemListResponse> {
  const { data } = await apiClient.get<ActionItemListResponse>("/v1/action-items", { params });
  return data;
}

export interface DispatchPayload {
  item_ids: string[];
  /** Omit to let the server default each item to its block's responsible
   *  member; explicit wins for the whole batch. */
  assigned_membership_id?: string | null;
  scheduled_date?: string | null;
  notes?: string | null;
}

export interface DispatchResultItem {
  item_id: string;
  kind: ItemKind;
  activity_id: string | null;
  assigned_membership_id: string | null;
  /** True when the assignee came from the block rather than the request — the
   *  UI says so rather than assigning silently. */
  assignee_defaulted: boolean;
  error: string | null;
}

export interface DispatchResponse {
  dispatched: number;
  failed: number;
  results: DispatchResultItem[];
}

export async function dispatchActionItems(
  farmId: string,
  payload: DispatchPayload,
): Promise<DispatchResponse> {
  const { data } = await apiClient.post<DispatchResponse>("/v1/action-items:dispatch", payload, {
    params: { farm_id: farmId },
  });
  return data;
}
