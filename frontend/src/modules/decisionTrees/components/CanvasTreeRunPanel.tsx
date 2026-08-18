// "Run this tree on a farm" — the dry-run's committing counterpart.
//
// The dry-run above it asks "what would this decide here?" and writes
// nothing. This one decides it: the tree's *published* version is evaluated
// across every targeted block of a farm and the recommendations it produces
// land in the Action Center, where the farm team works them.
//
// Three things this panel has to make unmissable, because getting any of
// them wrong turns a helpful button into an unpleasant surprise:
//
//  * it writes, and to a shared surface — hence the two-step confirm rather
//    than a single click next to a dry-run button that does not;
//  * it runs the published version, never the draft in the editor — an
//    author mid-edit would otherwise assume their unsaved work ran;
//  * a re-run legitimately opens nothing, because an already-open
//    recommendation from this tree dedupes it away. "0 opened, 4 already
//    open" is a success message, and is written as one.

import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { TreeRunCandidateFarm, TreeRunResponse } from "@/api/decisionTrees";
import { Card } from "@/components/Card";
import { Pill } from "@/components/Pill";

interface CanvasTreeRunPanelProps {
  farmId: string;
  onFarmIdChange: (next: string) => void;
  candidateFarms: TreeRunCandidateFarm[];
  candidatesLoading: boolean;
  /** False when the tree has no published version — nothing to run. */
  canRun: boolean;
  /** True while the editor holds unsaved changes; the run ignores them. */
  hasUnsavedDraft: boolean;
  isRunning: boolean;
  result: TreeRunResponse | null;
  errorMessage?: string;
  onRun: () => void;
  onClear: () => void;
}

export function CanvasTreeRunPanel({
  farmId,
  onFarmIdChange,
  candidateFarms,
  candidatesLoading,
  canRun,
  hasUnsavedDraft,
  isRunning,
  result,
  errorMessage,
  onRun,
  onClear,
}: CanvasTreeRunPanelProps): ReactNode {
  const { t } = useTranslation("decisionTrees");
  const [confirming, setConfirming] = useState(false);
  const selected = candidateFarms.find((f) => f.farm_id === farmId);
  const noCandidates = !candidatesLoading && candidateFarms.length === 0;

  const handleRun = (): void => {
    setConfirming(false);
    onRun();
  };

  return (
    <Card noPadding className="flex flex-col gap-3 border-ap-warn/40 p-3">
      <header className="flex flex-wrap items-end gap-3">
        <div className="flex flex-1 flex-col gap-1">
          <span className="text-xs font-medium text-ap-muted">{t("editor.run.heading")}</span>
          <p className="text-[11px] text-ap-muted">{t("editor.run.subheading")}</p>
          {noCandidates ? (
            <p className="mt-1 text-xs text-ap-muted">{t("editor.run.noCandidateFarms")}</p>
          ) : (
            <select
              value={farmId}
              onChange={(e) => {
                onFarmIdChange(e.target.value);
                setConfirming(false);
              }}
              disabled={candidatesLoading || !canRun}
              className="mt-1 rounded-md border border-ap-line bg-white px-2 py-1 text-xs shadow-sm focus:border-ap-primary focus:outline-none focus:ring-1 focus:ring-ap-primary"
            >
              <option value="">
                {candidatesLoading ? t("editor.run.loadingFarms") : t("editor.run.selectFarm")}
              </option>
              {candidateFarms.map((f) => (
                <option key={f.farm_id} value={f.farm_id}>
                  {t("editor.run.farmOption", {
                    name: f.name,
                    targeted: f.blocks_targeted,
                    total: f.blocks_total,
                  })}
                </option>
              ))}
            </select>
          )}
        </div>
        <div className="flex items-center gap-2">
          {confirming ? (
            <>
              <button
                type="button"
                onClick={handleRun}
                disabled={isRunning}
                className="rounded-md bg-ap-warn px-3 py-1.5 text-sm font-medium text-white hover:bg-ap-warn/90 disabled:opacity-60"
              >
                {t("editor.run.confirm")}
              </button>
              <button
                type="button"
                onClick={() => setConfirming(false)}
                className="rounded-md border border-ap-line bg-white px-3 py-1.5 text-sm text-ap-ink hover:bg-ap-bg/40"
              >
                {t("editor.run.cancel")}
              </button>
            </>
          ) : (
            <button
              type="button"
              onClick={() => setConfirming(true)}
              disabled={isRunning || !canRun || !farmId.trim()}
              className="rounded-md border border-ap-warn bg-white px-3 py-1.5 text-sm font-medium text-ap-warn hover:bg-ap-warn-soft disabled:opacity-60"
            >
              {isRunning ? t("editor.run.running") : t("editor.run.run")}
            </button>
          )}
          {result ? (
            <button
              type="button"
              onClick={onClear}
              className="rounded-md border border-ap-line bg-white px-3 py-1.5 text-sm text-ap-ink hover:bg-ap-bg/40"
            >
              {t("editor.run.clear")}
            </button>
          ) : null}
        </div>
      </header>

      {/* The one state where the button is right there but nothing can run.
          Without this the disabled control reads as a bug. */}
      {!canRun ? (
        <p className="rounded-md bg-ap-warn-soft p-2 text-xs text-ap-warn">
          {t("editor.run.needsPublishedVersion")}
        </p>
      ) : null}

      {confirming && selected ? (
        <p className="rounded-md bg-ap-warn-soft p-2 text-xs text-ap-warn">
          {t("editor.run.confirmBody", {
            farm: selected.name,
            blocks: selected.blocks_targeted,
          })}
        </p>
      ) : null}

      {/* An author who just edited the canvas will assume the run uses what
          they are looking at. It does not — it uses the published version. */}
      {canRun && hasUnsavedDraft ? (
        <p className="text-[11px] text-ap-muted">{t("editor.run.draftIgnored")}</p>
      ) : null}

      {errorMessage ? <p className="text-xs text-ap-crit">{errorMessage}</p> : null}

      {result ? (
        <div className="flex flex-col gap-2 border-t border-ap-line pt-2">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            {result.recommendations_opened > 0 ? (
              <Pill kind="ok">
                {t("editor.run.opened", { count: result.recommendations_opened })}
              </Pill>
            ) : (
              <Pill kind="neutral">{t("editor.run.openedNone")}</Pill>
            )}
            {/* Deduped is why a second run reports zero. Shown at the same
                weight as the opened count so it cannot be missed. */}
            {result.deduped > 0 ? (
              <Pill kind="info">{t("editor.run.deduped", { count: result.deduped })}</Pill>
            ) : null}
            {result.errors > 0 ? (
              <Pill kind="crit">{t("editor.run.errors", { count: result.errors })}</Pill>
            ) : null}
            <span className="text-ap-muted">
              {t("editor.run.summary", {
                version: result.tree_version,
                targeted: result.blocks_targeted,
                blocks: result.blocks_evaluated,
              })}
            </span>
          </div>

          {result.recommendations_opened > 0 ? (
            <p className="text-xs text-ap-ink">{t("editor.run.whereToLook")}</p>
          ) : null}

          <details>
            <summary className="cursor-pointer text-[11px] font-medium text-ap-primary">
              {t("editor.run.perBlock")}
            </summary>
            <ul className="mt-1 flex flex-col gap-0.5">
              {result.blocks.map((b) => (
                <li key={b.block_id} className="flex flex-wrap items-center gap-2 text-[11px]">
                  <span className="font-medium text-ap-ink">{b.label}</span>
                  {b.skipped_targeting ? (
                    <Pill kind="neutral">{t("editor.run.blockSkipped")}</Pill>
                  ) : b.recommendations_opened > 0 ? (
                    <Pill kind="ok">
                      {t("editor.run.blockOpened", { count: b.recommendations_opened })}
                    </Pill>
                  ) : b.deduped > 0 ? (
                    <Pill kind="info">{t("editor.run.blockDeduped")}</Pill>
                  ) : (
                    <Pill kind="neutral">{t("editor.run.blockClear")}</Pill>
                  )}
                  {b.errors > 0 ? (
                    <span className="text-ap-crit">{t("editor.run.blockError")}</span>
                  ) : null}
                </li>
              ))}
            </ul>
          </details>
        </div>
      ) : null}
    </Card>
  );
}
