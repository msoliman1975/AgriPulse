/**
 * A person's own notification settings.
 *
 * Mirrors `backend/app/modules/iam/schemas.py::MyNotificationPreferencesResponse`
 * and the two routes in `iam/router.py`. Keep in lock-step — the two ends are
 * hand-mirrored, and a silently missing field here degrades the screen with no
 * error.
 *
 * Neither route is capability-gated. The row belongs to the caller, and the
 * footer of every notification email links to the screen that uses it.
 */

import { apiClient } from "@/api/client";

/** The three channels a person can choose. `webhook` is tenant-wide and is
 *  deliberately not one of them. */
export const NOTIFICATION_CHANNELS = ["in_app", "email", "push"] as const;
export type NotificationChannel = (typeof NOTIFICATION_CHANNELS)[number];

/** Why a channel cannot reach this person right now. Absent when it can. */
export type UndeliverableReason =
  | "tenant_disabled"
  | "no_email_address"
  | "no_registered_device";

export interface ChannelAvailability {
  channel: NotificationChannel;
  /** False when something outside the tick box stops delivery. */
  deliverable: boolean;
  reason: UndeliverableReason | null;
}

export interface MyNotificationPreferences {
  /** What this person chose, or the fan-out's defaults when they have no row. */
  channels: NotificationChannel[];
  /** Which locale the alert and recommendation templates render in. */
  language: "en" | "ar";
  email_address: string | null;
  registered_device_count: number;
  /** What the organisation allows, before this person's choice narrows it. */
  tenant_channels: string[];
  availability: ChannelAvailability[];
}

export interface NotificationPreferencesPatch {
  /** Omit to leave unchanged. `[]` means "send me nothing", which is allowed. */
  channels?: NotificationChannel[];
  language?: "en" | "ar";
}

export async function fetchMyNotificationPreferences(): Promise<MyNotificationPreferences> {
  const { data } = await apiClient.get<MyNotificationPreferences>(
    "/v1/me/notification-preferences",
  );
  return data;
}

export async function patchMyNotificationPreferences(
  patch: NotificationPreferencesPatch,
): Promise<MyNotificationPreferences> {
  const { data } = await apiClient.patch<MyNotificationPreferences>(
    "/v1/me/notification-preferences",
    patch,
  );
  return data;
}
