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

/** One block-day of crop water accounting: precipitation + irrigation - ETc.
 *
 * Carries the whole derivation rather than just `balance_mm`, because the
 * headline alone is not actionable — peak crop demand, absent rain, and
 * irrigation nobody logged all produce a deficit and call for different
 * responses. Decimals arrive as strings, per the platform convention.
 */
export interface WaterBalanceDay {
  date: string;
  balance_mm: string;
  etc_mm: string;
  et0_mm: string;
  kc_used: string;
  /** How the crop coefficient resolved. A balance built on `generic_default`
   *  deserves less confidence than one built on a per-stage catalog value. */
  kc_source: "phenology" | "stage_default" | "generic_default";
  growth_stage: string | null;
  precip_mm: string;
  irrigation_mm: string;
  /** False means no irrigation was RECORDED, not that none was applied. A
   *  farm that never logs irrigation shows a permanent deficit that is missing
   *  bookkeeping, not dry soil — never present that as a shortfall. */
  irrigation_logged: boolean;
}

export async function getWaterBalance(
  blockId: string,
  params: { from?: string; to?: string } = {},
): Promise<WaterBalanceDay[]> {
  const { data } = await apiClient.get<WaterBalanceDay[]>(
    `/v1/blocks/${blockId}/water-balance`,
    { params },
  );
  return data;
}
