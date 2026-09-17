/**
 * The label for one finding status.
 *
 * The five codes already have translated labels: `verdictStatus.*` in the
 * `decisionTrees` namespace, shown on the current editor's canvas and on the
 * map legend. A second copy in the beta namespace would be five more strings
 * to keep in step, and the first time they disagreed the same block would read
 * "Issue" on one screen and something else on another.
 *
 * So the beta screens borrow those. This hook is the only place that knows
 * which namespace they live in.
 */

import { useCallback } from "react";
import { useTranslation } from "react-i18next";

import type { FindingStatus } from "./betaConstants";

export function useFindingStatusLabel(): (status: FindingStatus) => string {
  const { t } = useTranslation("decisionTrees");
  return useCallback(
    (status: FindingStatus) => t(`verdictStatus.${status}`, { defaultValue: status }),
    [t],
  );
}
