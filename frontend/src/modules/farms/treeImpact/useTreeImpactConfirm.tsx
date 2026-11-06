// Ask before a change that moves which decision trees a farm runs.
//
//   const impact = useTreeImpactConfirm();
//   if (!(await impact.confirm(farmId, { blocks: [{ block_id, crop_removed: true }] }))) return;
//   ...save...
//   return <>{...}{impact.dialog}</>;
//
// `confirm` asks the server what the change would do. When the answer is
// "nothing", it resolves true without showing anything — most soil edits and
// many crop assignments move no tree, and a dialog that lists nothing teaches
// people to click through it. When the preview itself fails, it also resolves
// true: the dialog is information, and failing to fetch information is no
// reason to refuse a save the user is allowed to make.
import { useCallback, useRef, useState, type ReactNode } from "react";

import {
  previewFarmTreeImpact,
  type TreeImpactRequest,
  type TreeImpactResponse,
} from "@/api/farmDecisionTrees";

import { TreeImpactDialog } from "./TreeImpactDialog";

export interface TreeImpactConfirm {
  confirm: (farmId: string, change: TreeImpactRequest, title?: string) => Promise<boolean>;
  /** Render this somewhere in the calling component. */
  dialog: ReactNode;
  /** True while the preview is being fetched. */
  checking: boolean;
}

export function useTreeImpactConfirm(): TreeImpactConfirm {
  const [pending, setPending] = useState<{ impact: TreeImpactResponse; title?: string } | null>(
    null,
  );
  const [checking, setChecking] = useState(false);
  const resolver = useRef<((ok: boolean) => void) | null>(null);

  const settle = useCallback((ok: boolean) => {
    resolver.current?.(ok);
    resolver.current = null;
    setPending(null);
  }, []);

  const confirm = useCallback(
    async (farmId: string, change: TreeImpactRequest, title?: string): Promise<boolean> => {
      setChecking(true);
      let impact: TreeImpactResponse;
      try {
        impact = await previewFarmTreeImpact(farmId, change);
      } catch {
        return true;
      } finally {
        setChecking(false);
      }
      if (!impact.changes_anything && impact.exclusions_cleared.length === 0) return true;
      return new Promise<boolean>((resolve) => {
        resolver.current = resolve;
        setPending({ impact, title });
      });
    },
    [],
  );

  const dialog = pending ? (
    <TreeImpactDialog
      impact={pending.impact}
      title={pending.title}
      onConfirm={() => settle(true)}
      onCancel={() => settle(false)}
    />
  ) : null;

  return { confirm, dialog, checking };
}
