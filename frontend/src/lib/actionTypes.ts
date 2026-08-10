/**
 * The action-type vocabulary — one list, shared by everything that shows it.
 *
 * This is a closed set in three places already: the `ActionType` Literal in
 * `backend/app/modules/recommendations/schemas.py`, the
 * `ck_recommendations_action_type` CHECK added in tenant migration 0015, and
 * the engine's action→board-activity map. The decision-tree editor was the
 * odd one out — it offered a free-text box, so an author could type `sparying`
 * and get a clean save, a green publish, and a 500 at persist time when the
 * CHECK rejected it. Every other outcome field on that panel (kind, severity)
 * was already a dropdown.
 *
 * Keep in lock-step with the backend Literal; `actionTypes.test.ts` fails if
 * they drift.
 */
export const ACTION_TYPES = [
  "irrigate",
  "fertilize",
  "spray",
  "scout",
  "harvest_window",
  "prune",
  "no_action",
  "other",
] as const;

export type ActionType = (typeof ACTION_TYPES)[number];

/**
 * Order the Action Center groups by. Field workflow, not alphabet: scouting
 * finds the problem, spraying and irrigation act on it, harvest closes it out.
 * `no_action` never reaches the queue (the engine writes no row for it) but
 * stays in the vocabulary because a tree leaf can declare it.
 */
export const ACTION_TYPE_GROUP_ORDER: readonly ActionType[] = [
  "scout",
  "spray",
  "irrigate",
  "fertilize",
  "prune",
  "harvest_window",
  "other",
];

export function isActionType(value: string): value is ActionType {
  return (ACTION_TYPES as readonly string[]).includes(value);
}
