// Mirrors backend/app/modules/irrigation/schemas.py — keep in lock-step.

import { apiClient } from "./client";

export type IrrigationScheduleStatus = "pending" | "applied" | "skipped";

export interface IrrigationSchedule {
  id: string;
  block_id: string;
  scheduled_for: string;
  recommended_mm: string;
  kc_used: string | null;
  et0_mm_used: string | null;
  recent_precip_mm: string | null;
  growth_stage_context: string | null;
  soil_moisture_pct: string | null;
  status: IrrigationScheduleStatus;
  applied_at: string | null;
  applied_by: string | null;
  applied_volume_mm: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface ListIrrigationSchedulesParams {
  from?: string;
  to?: string;
  status?: IrrigationScheduleStatus[];
}

export async function listIrrigationSchedules(
  farmId: string,
  params: ListIrrigationSchedulesParams = {},
): Promise<IrrigationSchedule[]> {
  const { data } = await apiClient.get<IrrigationSchedule[]>(
    `/v1/farms/${farmId}/irrigation/schedules`,
    { params },
  );
  return data;
}

export interface IrrigationApplyPayload {
  action: "apply" | "skip";
  applied_volume_mm?: number | null;
  notes?: string | null;
}

export async function applyOrSkipIrrigation(
  scheduleId: string,
  payload: IrrigationApplyPayload,
): Promise<IrrigationSchedule> {
  const { data } = await apiClient.patch<IrrigationSchedule>(
    `/v1/irrigation/schedules/${scheduleId}`,
    payload,
  );
  return data;
}

export async function generateIrrigationForBlock(
  blockId: string,
  scheduledFor?: string,
): Promise<IrrigationSchedule | null> {
  const { data } = await apiClient.post<IrrigationSchedule | null>(
    `/v1/blocks/${blockId}/irrigation/generate`,
    { scheduled_for: scheduledFor ?? null },
  );
  return data;
}
