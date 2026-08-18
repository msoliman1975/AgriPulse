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

/**
 * How loudly the queue says "this again".
 *
 * `new` is the absence of a badge, not a badge. Severity is deliberately NOT
 * derived from this — the decision tree decided the agronomy, and how long a
 * supervisor has left an item alone is a different fact that must not be
 * allowed to rewrite the first.
 */
export type RecurrenceState = "new" | "recurring" | "persistent";

/**
 * Which way an aggregated finding is moving between evaluation days.
 *
 * `unknown` is a group with no yesterday to compare against — the first day,
 * or a backfilled one. It is deliberately not `steady`: claiming stability
 * nobody has observed is worse than admitting there is no baseline yet.
 */
export type SpreadTrend = "unknown" | "steady" | "spreading" | "receding";

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

/**
 * How many cells one row stands for.
 *
 * `is_group` false with `member_count` 0 is an ordinary block-scoped item —
 * one place, one finding. `is_group` true means the row aggregates
 * `member_count` grid cells that all hit the same leaf of the same tree at the
 * same severity on the same block; the cells themselves are one request away
 * at `/action-items/{id}/members`.
 */
export interface Aggregation {
  is_group: boolean;
  member_count: number;
  /** What the count was at the end of the previous evaluation day. Without a
   *  baseline the card cannot distinguish a 12-cell finding from a 20-cell
   *  one — a count with no baseline is not a trend. */
  previous_member_count: number;
  trend: SpreadTrend;
}

/** How long this finding has been true, and whether anyone has moved. */
export interface Recurrence {
  state: RecurrenceState;
  /** Distinct days this item has fired, first day included. */
  occurrence_count: number;
  /** Consecutive firing days. 6 means six mornings in a row. */
  day_streak: number;
  first_seen_at: string | null;
  last_seen_at: string | null;
}

/**
 * One cell under a group. Never actionable on its own — the group is the unit
 * a supervisor decides about; this is what the map colours and the drill-down
 * lists.
 */
export interface ActionItemMember {
  id: string;
  cell: CellLocation | null;
  severity: ItemSeverity;
  native_status: string;
  text_en: string | null;
  text_ar: string | null;
  created_at: string;
  last_seen_at: string | null;
  /** Set once this cell stopped firing. Kept, not dropped: a receding
   *  outbreak and one that never spread look identical otherwise. */
  cleared_at: string | null;
  occurrence_count: number;
  day_streak: number;
}

export interface ActionItemMembersResponse {
  item_id: string;
  kind: ItemKind;
  total: number;
  /** Members still firing as of the last evaluation. */
  active: number;
  members: ActionItemMember[];
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

  /** The member responsible for this item's block. Present regardless of
   *  dispatch state — it is what the dispatch dialog defaults to. */
  responsible_membership_id: string | null;
  assigned_membership_id: string | null;
  activity_id: string | null;
  scheduled_date: string | null;

  why: string | null;
  reasoning: Record<string, unknown>;

  /** Both always present, so no consumer has to branch on absence. */
  aggregation: Aggregation;
  recurrence: Recurrence;
}

export interface ActionItemGroup {
  key: string;
  label: string;
  count: number;
  critical_count: number;
  block_count: number;
  /** Cells covered, not rows shown: a group of 14 contributes 14. */
  cell_count: number;
  /** Rows in this group that are themselves aggregates of several cells. */
  aggregate_count: number;
  /** Rows firing on consecutive days with nobody acting on them. */
  recurring_count: number;
  /** Aggregates covering materially more cells today than yesterday. The count
   *  to read first — a spreading finding outranks a merely persistent one. */
  spreading_count: number;
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

export async function listActionItemMembers(
  farmId: string,
  itemId: string,
): Promise<ActionItemMembersResponse> {
  const { data } = await apiClient.get<ActionItemMembersResponse>(
    `/v1/action-items/${itemId}/members`,
    { params: { farm_id: farmId } },
  );
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
