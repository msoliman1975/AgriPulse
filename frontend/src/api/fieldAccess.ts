/**
 * Field access — giving a worker who has a phone but no email a way in.
 *
 * Mirrors `backend/app/modules/iam/field_enrolment.py`; keep in lock-step.
 *
 * Every call here is farm-scoped. `user.field_enrol` resolves against the farm
 * named in the request, so a farm manager can run this for their own crew
 * without holding tenant-wide `user.invite` — which is the whole reason the
 * capability exists.
 */

import { apiClient } from "@/api/client";

/** Just enough to act on — the audit is a worklist, not a directory. */
export interface WorkerBrief {
  id: string;
  name: string;
  role: string | null;
  /** The number the farm already recorded. The phone IS the username, so
   *  retyping it is how a second account gets minted by a typo. */
  phone: string | null;
  has_phone: boolean;
  /** Set only for people already enrolled. PIN reissue is keyed on the user. */
  user_id: string | null;
}

/**
 * Four buckets, each implying a different next step. Two of them are silent
 * failures rather than errors, which is why the pre-flight exists at all:
 * a `FieldWorker` holds no capabilities and can never sign in, and the phone
 * *is* the username so no phone means no possible account.
 */
export interface FieldEnrolmentAudit {
  total: number;
  enrolled: WorkerBrief[];
  ready_to_enrol: WorkerBrief[];
  blocked_by_role: WorkerBrief[];
  missing_phone: WorkerBrief[];
}

export interface EnrolPayload {
  phone: string;
  full_name: string;
  farm_id: string;
  role: "Scout" | "FieldOperator";
  worker_id?: string | null;
  language?: "en" | "ar";
}

/** The PIN comes back once. It is never stored and never returned again. */
export interface EnrolmentResult {
  user_id: string;
  membership_id: string;
  worker_id: string | null;
  phone: string;
  pin: string;
}

export async function fetchFieldEnrolmentAudit(farmId: string): Promise<FieldEnrolmentAudit> {
  const { data } = await apiClient.get<FieldEnrolmentAudit>("/v1/users/field-enrolment/audit", {
    params: { farm_id: farmId },
  });
  return data;
}

export async function enrolFieldWorker(payload: EnrolPayload): Promise<EnrolmentResult> {
  const { data } = await apiClient.post<EnrolmentResult>("/v1/users/field-enrolment", payload);
  return data;
}

/**
 * Promote worker-only rows so they can hold a login. Scoped to one farm and to
 * `FieldWorker` rows: a bulk action that could rewrite any role would be a way
 * to grant Agronomist to a dozen people at once.
 */
export async function reRoleFieldWorkers(args: {
  farm_id: string;
  worker_ids: string[];
  role?: "Scout" | "FieldOperator";
}): Promise<{ updated: number }> {
  const { data } = await apiClient.post<{ updated: number }>(
    "/v1/users/field-enrolment/re-role",
    { role: "Scout", ...args },
  );
  return data;
}

/**
 * A PIN cannot be looked up — Keycloak stores only its hash — so recovery is
 * replacement, and the old one stops working immediately.
 */
export async function reissueFieldPin(args: {
  user_id: string;
  farm_id: string;
}): Promise<{ user_id: string; pin: string }> {
  const { data } = await apiClient.post<{ user_id: string; pin: string }>(
    `/v1/users/${args.user_id}/field-pin:reissue`,
    null,
    { params: { farm_id: args.farm_id } },
  );
  return data;
}
