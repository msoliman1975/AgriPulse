// The five platform status codes, fetched once and shared.
//
// Lives here, not under decisionTrees: the tree editor authors a status,
// the block dock reads one, and the map will paint one. Three modules, one
// list.
//
// Fetched rather than hard-coded. A frontend copy of a backend list has
// drifted here before, and this one decides what colour a block is painted
// on the map — a code the frontend does not know about would be silently
// unpaintable, and a colour it disagreed about would make two screens tell
// two stories about one block.
//
// The fallback below is the same five rows. It exists so the tree editor
// still opens when the request fails; it is never the source of truth, and
// anything that has to be right — the map legend — should read the query's
// own state rather than this hook's value.

import { useQuery } from "@tanstack/react-query";

import { getVerdictStatuses, type VerdictStatusDefinition } from "@/api/decisionTrees";

/** Ranked lowest first, matching what the endpoint returns. */
const FALLBACK: VerdictStatusDefinition[] = [
  { code: "na", rank: 0, color: "#9AA0A6", label_en: "Not applicable", label_ar: "لا ينطبق" },
  { code: "very_good", rank: 1, color: "#1B873F", label_en: "Very good", label_ar: "ممتاز" },
  { code: "good", rank: 2, color: "#6FBF4B", label_en: "Good", label_ar: "جيد" },
  { code: "issue", rank: 3, color: "#E8A33D", label_en: "Issue", label_ar: "مشكلة" },
  { code: "alert", rank: 4, color: "#D64545", label_en: "Alert", label_ar: "إنذار" },
];

export const VERDICT_STATUSES_QUERY_KEY = ["decisionTrees/verdictStatuses"];

export function useVerdictStatuses(): VerdictStatusDefinition[] {
  const query = useQuery({
    queryKey: VERDICT_STATUSES_QUERY_KEY,
    queryFn: getVerdictStatuses,
    // The list changes when the platform ships a new one, which is a deploy.
    staleTime: 60 * 60 * 1000,
  });
  return query.data ?? FALLBACK;
}

/** The winning status over several verdicts, or null for none.
 *
 * Highest rank wins, so a block with one `issue` and six `good` reads as an
 * issue. `na` is rank 0 and never outranks a real answer. Null means no tree
 * has run, which is not the same as `na` and must not be painted as one.
 */
export function worstStatus(
  codes: string[],
  statuses: VerdictStatusDefinition[],
): VerdictStatusDefinition | null {
  let winner: VerdictStatusDefinition | null = null;
  for (const code of codes) {
    const found = statuses.find((s) => s.code === code);
    if (!found) continue;
    if (winner === null || found.rank > winner.rank) winner = found;
  }
  return winner;
}
