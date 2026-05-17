// Mirrors backend/app/modules/notifications/schemas.py.

import { apiClient } from "./client";

export type InboxAction = "read" | "archive";

export interface InboxItem {
  id: string;
  alert_id: string | null;
  recommendation_id: string | null;
  severity: "info" | "warning" | "critical" | null;
  title: string;
  body: string;
  link_url: string | null;
  read_at: string | null;
  archived_at: string | null;
  created_at: string;
}

export interface ListInboxParams {
  include_archived?: boolean;
  limit?: number;
}

export async function listInbox(params: ListInboxParams = {}): Promise<InboxItem[]> {
  const { data } = await apiClient.get<InboxItem[]>("/v1/inbox", { params });
  return data;
}

export async function getUnreadCount(): Promise<number> {
  const { data } = await apiClient.get<{ count: number }>("/v1/inbox/unread-count");
  return data.count;
}

export async function transitionInboxItem(itemId: string, action: InboxAction): Promise<InboxItem> {
  const { data } = await apiClient.patch<InboxItem>(`/v1/inbox/${itemId}`, { action });
  return data;
}
