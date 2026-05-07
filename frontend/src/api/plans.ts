// Mirrors backend/app/modules/plans/schemas.py — keep in lock-step.

import { apiClient } from "./client";

export type PlanStatus = "draft" | "active" | "completed" | "archived";
export type ActivityStatus = "scheduled" | "in_progress" | "completed" | "skipped";
export type ActivityType =
  | "planting"
  | "fertilizing"
  | "spraying"
  | "pruning"
  | "harvesting"
  | "irrigation"
  | "soil_prep"
  | "observation";

export interface Plan {
  id: string;
  farm_id: string;
  season_label: string;
  season_year: number;
  name: string | null;
  notes: string | null;
  status: PlanStatus;
  created_at: string;
  updated_at: string;
}

export interface PlanActivity {
  id: string;
  plan_id: string;
  block_id: string;
  activity_type: ActivityType;
  scheduled_date: string;
  duration_days: number;
  start_time: string | null; // HH:MM:SS or null
  product_name: string | null;
  dosage: string | null;
  notes: string | null;
  status: ActivityStatus;
  completed_at: string | null;
  completed_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface PlanCreatePayload {
  season_label: string;
  season_year: number;
  name?: string | null;
  notes?: string | null;
}

export interface PlanUpdatePayload {
  name?: string | null;
  notes?: string | null;
  status?: PlanStatus;
}

export interface ActivityCreatePayload {
  block_id: string;
  activity_type: ActivityType;
  scheduled_date: string;
  duration_days?: number;
  start_time?: string | null;
  product_name?: string | null;
  dosage?: string | null;
  notes?: string | null;
}

export interface ActivityUpdatePayload {
  scheduled_date?: string;
  duration_days?: number;
  start_time?: string | null;
  product_name?: string | null;
  dosage?: string | null;
  notes?: string | null;
  state?: "start" | "complete" | "skip";
}

// --- Plans ---------------------------------------------------------------

export async function listPlans(
  farmId: string,
  options: { season_year?: number; include_archived?: boolean } = {},
): Promise<Plan[]> {
  const { data } = await apiClient.get<Plan[]>(`/v1/farms/${farmId}/plans`, { params: options });
  return data;
}

export async function getPlan(planId: string): Promise<Plan> {
  const { data } = await apiClient.get<Plan>(`/v1/plans/${planId}`);
  return data;
}

export async function createPlan(farmId: string, payload: PlanCreatePayload): Promise<Plan> {
  const { data } = await apiClient.post<Plan>(`/v1/farms/${farmId}/plans`, payload);
  return data;
}

export async function updatePlan(planId: string, payload: PlanUpdatePayload): Promise<Plan> {
  const { data } = await apiClient.patch<Plan>(`/v1/plans/${planId}`, payload);
  return data;
}

export async function archivePlan(planId: string): Promise<void> {
  await apiClient.delete(`/v1/plans/${planId}`);
}

// --- Activities ----------------------------------------------------------

export async function listActivities(planId: string): Promise<PlanActivity[]> {
  const { data } = await apiClient.get<PlanActivity[]>(`/v1/plans/${planId}/activities`);
  return data;
}

export async function createActivity(
  planId: string,
  payload: ActivityCreatePayload,
): Promise<PlanActivity> {
  const { data } = await apiClient.post<PlanActivity>(
    `/v1/plans/${planId}/activities`,
    payload,
  );
  return data;
}

export async function updateActivity(
  activityId: string,
  payload: ActivityUpdatePayload,
): Promise<PlanActivity> {
  const { data } = await apiClient.patch<PlanActivity>(`/v1/activities/${activityId}`, payload);
  return data;
}

// --- Calendar ------------------------------------------------------------

export interface CalendarResponse {
  farm_id: string;
  activities: PlanActivity[];
}

export async function listCalendar(
  farmId: string,
  fromDate: string,
  toDate: string,
): Promise<CalendarResponse> {
  const { data } = await apiClient.get<CalendarResponse>(
    `/v1/farms/${farmId}/plans/calendar`,
    { params: { from: fromDate, to: toDate } },
  );
  return data;
}
