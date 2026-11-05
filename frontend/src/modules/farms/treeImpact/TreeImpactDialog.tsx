// What a pending crop / soil / country / block change does to the decision
// trees the farm runs. Shown before the change is saved, and informational
// only: the farm opts out of a tree afterwards, in the farm settings, the same
// way it opts out of any other tree.
//
// Per block: the trees that start and stop on that block, with how many other
// blocks a stopping tree still runs on. Per farm (a country change has no
// single block): the trees that reach the farm or leave it entirely. A tree
// the farm had turned off that no longer matches any block loses that choice,
// so it comes back on if the crop does — the dialog says so.
import { type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { TreeImpactResponse, TreeImpactTree } from "@/api/farmDecisionTrees";
import { Button } from "@/components/Button";
import { Modal } from "@/components/Modal";
import { localizedName } from "@/lib/localizedField";

interface Props {
  impact: TreeImpactResponse;
  /** What the user is about to do, already phrased: "Change the crop on B3". */
  title?: string;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

function TreeList({
  trees,
  tone,
  note,
}: {
  trees: TreeImpactTree[];
  tone: "start" | "stop";
  note: (tree: TreeImpactTree) => string | null;
}): ReactNode {
  const { i18n, t } = useTranslation("farmConsole");
  return (
    <ul className="flex flex-col gap-1">
      {trees.map((tree) => {
        const extra = note(tree);
        return (
          <li
            key={tree.tree_id}
            className="flex flex-wrap items-baseline gap-x-2 rounded-md border border-ap-line/70 px-2 py-1 text-sm"
          >
            <span className={tone === "start" ? "text-ap-ink" : "text-ap-muted line-through"}>
              {localizedName(i18n.language, tree.name_en, tree.name_ar)}
            </span>
            <code className="font-mono text-[11px] text-ap-muted">{tree.code}</code>
            {!tree.enabled ? (
              <span className="text-[11px] text-ap-warn">{t("treeImpact.turnedOff")}</span>
            ) : null}
            {extra ? <span className="text-[11px] text-ap-muted">{extra}</span> : null}
          </li>
        );
      })}
    </ul>
  );
}

export function TreeImpactDialog({ impact, title, busy, onConfirm, onCancel }: Props): ReactNode {
  const { t, i18n } = useTranslation("farmConsole");
  const isAr = i18n.language === "ar";
  const blockSections = impact.blocks.filter((b) => b.starting.length || b.stopping.length);
  // A block-level change already names its trees per block; repeat at farm
  // level only what a block list cannot show (a country change).
  const showFarm = blockSections.length === 0;

  return (
    <Modal open onClose={onCancel} labelledBy="tree-impact-title" className="max-w-lg">
      <div className="flex max-h-[80vh] flex-col gap-3 overflow-y-auto p-5">
        <h2 id="tree-impact-title" className="text-base font-bold text-ap-ink">
          {title ?? t("treeImpact.title")}
        </h2>
        <p className="text-xs text-ap-muted">{t("treeImpact.intro")}</p>

        {blockSections.map((block) => (
          <section key={block.block_id} className="flex flex-col gap-2">
            {impact.blocks.length > 1 || block.label ? (
              <h3 className="text-sm font-semibold text-ap-ink">
                {t("treeImpact.block", {
                  name: (isAr ? block.label_ar : null) ?? block.label ?? "",
                })}
              </h3>
            ) : null}
            {block.stopping.length ? (
              <div className="flex flex-col gap-1">
                <span className="text-xs font-medium text-ap-crit">
                  {t("treeImpact.stopping", { count: block.stopping.length })}
                </span>
                <TreeList
                  trees={block.stopping}
                  tone="stop"
                  note={(tree) =>
                    tree.other_blocks
                      ? t("treeImpact.stillRunsElsewhere", { count: tree.other_blocks })
                      : null
                  }
                />
              </div>
            ) : null}
            {block.starting.length ? (
              <div className="flex flex-col gap-1">
                <span className="text-xs font-medium text-ap-primary">
                  {t("treeImpact.starting", { count: block.starting.length })}
                </span>
                <TreeList trees={block.starting} tone="start" note={() => null} />
              </div>
            ) : null}
          </section>
        ))}

        {showFarm && impact.farm_stopping.length ? (
          <div className="flex flex-col gap-1">
            <span className="text-xs font-medium text-ap-crit">
              {t("treeImpact.farmStopping", { count: impact.farm_stopping.length })}
            </span>
            <TreeList trees={impact.farm_stopping} tone="stop" note={() => null} />
          </div>
        ) : null}
        {showFarm && impact.farm_starting.length ? (
          <div className="flex flex-col gap-1">
            <span className="text-xs font-medium text-ap-primary">
              {t("treeImpact.farmStarting", { count: impact.farm_starting.length })}
            </span>
            <TreeList
              trees={impact.farm_starting}
              tone="start"
              note={(tree) =>
                tree.blocks ? t("treeImpact.onBlocks", { count: tree.blocks }) : null
              }
            />
          </div>
        ) : null}

        {impact.exclusions_cleared.length ? (
          <p className="rounded-md bg-ap-warn-soft px-2 py-1.5 text-xs text-ap-ink">
            {t("treeImpact.exclusionsCleared", {
              names: impact.exclusions_cleared
                .map((tree) => localizedName(i18n.language, tree.name_en, tree.name_ar))
                .join(", "),
            })}
          </p>
        ) : null}
        {impact.has_crops_before && !impact.has_crops_after ? (
          <p className="text-xs text-ap-muted">{t("treeImpact.noCropsAfter")}</p>
        ) : null}
        <p className="text-xs text-ap-muted">{t("treeImpact.openItemsNote")}</p>

        <div className="flex justify-end gap-2 pt-1">
          <Button variant="secondary" onClick={onCancel} disabled={busy}>
            {t("treeImpact.cancel")}
          </Button>
          <Button onClick={onConfirm} disabled={busy}>
            {t("treeImpact.confirm")}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
