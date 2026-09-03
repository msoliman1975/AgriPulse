// Which decision trees this farm runs.
//
// Every tree the tenant can see is listed and every one is on until somebody
// turns it off. That is an opt-out and not a saved selection on purpose: a
// tree published after this screen was last opened still reaches the farm,
// where a saved allow-list would leave it out and report nothing.
//
// Turning a tree off stops the next sweep from evaluating it here. It does
// not close the recommendations or alerts the tree already opened — those
// describe something that was true in the field, and a person still has to
// answer them. The panel says so, because "off" otherwise reads as "gone".
//
// A change saves immediately, like the imagery, weather and zone panels
// beside it. A failed save puts the switch back where it was, so the row can
// never show a state the server does not hold.
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { isApiError } from "@/api/errors";
import {
  listFarmDecisionTrees,
  setFarmDecisionTree,
  type FarmDecisionTree,
} from "@/api/farmDecisionTrees";
import { localizedName } from "@/lib/localizedField";

interface Props {
  farmId: string;
}

const rowCls = "flex flex-wrap items-center gap-2 rounded-lg border border-ap-line/70 p-2 text-sm";

export function FarmDecisionTreesPanel({ farmId }: Props): ReactNode {
  const { t, i18n } = useTranslation("farmConsole");
  const [trees, setTrees] = useState<FarmDecisionTree[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [busyTreeId, setBusyTreeId] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoadError(null);
    try {
      const bag = await listFarmDecisionTrees(farmId);
      setTrees(bag.trees);
    } catch (err) {
      // A tenant whose user cannot manage this farm gets a 403 here. Show the
      // same inline notice rather than an empty list, which would read as
      // "this farm runs no trees".
      setLoadError(
        isApiError(err) ? (err.problem.detail ?? err.problem.title) : t("farmTrees.loadFailed"),
      );
      setTrees([]);
    }
  }, [farmId, t]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const toggle = async (tree: FarmDecisionTree, next: boolean): Promise<void> => {
    setSaveError(null);
    setBusyTreeId(tree.tree_id);
    setTrees((prev) =>
      (prev ?? []).map((row) => (row.tree_id === tree.tree_id ? { ...row, enabled: next } : row)),
    );
    try {
      await setFarmDecisionTree(farmId, tree.tree_id, next);
    } catch (err) {
      setSaveError(
        isApiError(err) ? (err.problem.detail ?? err.problem.title) : t("farmTrees.saveFailed"),
      );
      setTrees((prev) =>
        (prev ?? []).map((row) =>
          row.tree_id === tree.tree_id ? { ...row, enabled: !next } : row,
        ),
      );
    } finally {
      setBusyTreeId(null);
    }
  };

  const running = (trees ?? []).filter((tree) => tree.enabled).length;

  return (
    <section className="rounded-xl border border-ap-line bg-ap-bg/40 p-4">
      <h3 className="mb-1 text-sm font-bold text-ap-ink">{t("farmTrees.title")}</h3>
      <p className="mb-3 text-xs text-ap-muted">{t("farmTrees.intro")}</p>

      {trees === null ? (
        <p className="text-xs text-ap-muted">{t("farmTrees.loading")}</p>
      ) : loadError !== null ? (
        <p className="text-xs text-ap-crit">{loadError}</p>
      ) : trees.length === 0 ? (
        <p className="text-xs text-ap-muted">{t("farmTrees.empty")}</p>
      ) : (
        <>
          <p className="text-xs text-ap-muted">
            {t("farmTrees.count", { running, total: trees.length })}
          </p>
          <ul className="flex flex-col gap-1.5">
            {trees.map((tree) => (
              <li key={tree.tree_id} className={rowCls}>
                <label className="flex flex-1 items-center gap-2">
                  <input
                    type="checkbox"
                    checked={tree.enabled}
                    disabled={busyTreeId === tree.tree_id}
                    onChange={(e) => void toggle(tree, e.target.checked)}
                    aria-label={t("farmTrees.toggleLabel", {
                      name: localizedName(i18n.language, tree.name_en, tree.name_ar),
                    })}
                  />
                  <span className="text-ap-ink">
                    {localizedName(i18n.language, tree.name_en, tree.name_ar)}
                  </span>
                </label>
                <span className="rounded-md border border-ap-line px-1.5 py-0.5 text-[11px] text-ap-muted">
                  {t(`farmTrees.source.${tree.source}`)}
                </span>
                <code className="font-mono text-[11px] text-ap-muted">{tree.code}</code>
              </li>
            ))}
          </ul>
          <p className="text-xs text-ap-muted">{t("farmTrees.openItemsNote")}</p>
        </>
      )}

      {saveError !== null ? <p className="mt-2 text-xs text-ap-crit">{saveError}</p> : null}
    </section>
  );
}
