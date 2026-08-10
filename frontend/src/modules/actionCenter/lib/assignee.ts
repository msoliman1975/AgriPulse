import type { ActionItem } from "@/api/actionCenter";

/**
 * The assignee a dispatch batch should start on.
 *
 * Returns `""` meaning "let the server resolve per item" whenever the batch's
 * blocks do not agree on one owner — which covers both a multi-block batch and
 * a block that names nobody.
 *
 * This deliberately reads `responsible_membership_id` (the block's owner) and
 * NOT `assigned_membership_id`. The latter is only populated *after* an item
 * has been dispatched, so defaulting from it meant an undispatched item — the
 * only kind you can actually dispatch — always fell back to the placeholder.
 * That was the shipped bug.
 */
export function defaultAssignee(items: readonly ActionItem[]): string {
  const distinct = new Set(items.map((i) => i.responsible_membership_id ?? ""));
  if (distinct.size !== 1) return "";
  const [only] = [...distinct];
  return only ?? "";
}
