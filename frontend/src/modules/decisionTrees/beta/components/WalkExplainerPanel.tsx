/**
 * The walk explainer as a right-hand panel over the page.
 *
 * Two jobs, and only two: fetch one cell's walk, and hold the drawer. The
 * reading of the walk is `WalkExplainer`, which takes steps and a layout and
 * fetches nothing, so the same screen serves a real run's stored trace
 * without going near this file.
 *
 * **The drift banner is the reason `cell` comes back from the server.** This
 * call re-walks: nothing stores a dry run, so an imagery or weather read that
 * landed between the run and this click can change the answer. When the
 * finding set or the severity differs from the row the author clicked, the
 * panel says so instead of drawing a path that explains a different result.
 */

import { useEffect, useMemo, useRef, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { createPortal } from "react-dom";

import { Button } from "@/components/Button";
import { StatusBanner } from "@/components/StatusBanner";
import { AsyncBoundary } from "@/components/AsyncBoundary";
import { queryState } from "@/components/asyncState";
import type { BetaDryRunCell } from "@/api/decisionTreesBeta";
import { useBetaCellWalk } from "@/queries/decisionTreesBeta";

import { WalkExplainer } from "./WalkExplainer";
import type { BetaLayoutResult } from "../lib/betaLayout";
import { walkStepsFromDryRun } from "../lib/walkTrace";

export interface WalkExplainerPanelProps {
  open: boolean;
  onClose: () => void;
  treeId: string | null;
  blockId: string | null;
  /** The row the author clicked. Null closes the panel. */
  cell: BetaDryRunCell | null;
  /** The version the dry run walked, so the explainer walks the same one. */
  versionId?: string | null;
  layout: BetaLayoutResult | null;
  /** Row and column, for the title. */
  title: string;
}

export function WalkExplainerPanel({
  open,
  onClose,
  treeId,
  blockId,
  cell,
  versionId = null,
  layout,
  title,
}: WalkExplainerPanelProps): ReactNode {
  const { t } = useTranslation("decisionTreesBeta");
  const ref = useRef<HTMLDivElement | null>(null);
  const previouslyFocused = useRef<HTMLElement | null>(null);

  const walk = useBetaCellWalk({
    treeId: open ? treeId : null,
    blockId: open ? blockId : null,
    cellId: open ? (cell?.cell_id ?? null) : null,
    versionId,
  });

  useEffect(() => {
    if (!open) return;
    previouslyFocused.current = document.activeElement as HTMLElement | null;
    return () => {
      previouslyFocused.current?.focus?.();
    };
  }, [open]);

  const steps = useMemo(() => walkStepsFromDryRun(walk.data?.path), [walk.data]);

  // Same cell, two walks, two answers. The identity is the key the whole
  // engine groups on, so a change in it is a change in the result.
  const drifted =
    walk.data !== undefined &&
    cell !== null &&
    (walk.data.cell.identity.join("|") !== cell.identity.join("|") ||
      walk.data.cell.severity !== cell.severity);

  if (!open) return null;

  return createPortal(
    <div className="fixed inset-0 z-50 flex justify-end">
      <button
        type="button"
        aria-label={t("explainer.close")}
        onClick={onClose}
        className="absolute inset-0 bg-black/40"
      />
      {/* eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions */}
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="beta-walk-explainer-title"
        ref={ref}
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            event.stopPropagation();
            onClose();
          }
        }}
        className="relative flex h-full w-full max-w-[50vw] flex-col overflow-y-auto bg-ap-panel shadow-2xl"
      >
        <header className="sticky top-0 z-10 flex items-baseline justify-between gap-3 border-b border-ap-line bg-ap-panel px-4 py-3">
          <div className="flex min-w-0 flex-col">
            <h2 id="beta-walk-explainer-title" className="text-sm font-medium text-ap-ink">
              {t("explainer.title")}
            </h2>
            <p className="text-meta text-ap-muted">{title}</p>
          </div>
          <Button variant="ghost" onClick={onClose}>
            {t("explainer.close")}
          </Button>
        </header>

        <div className="flex flex-col gap-3 p-4">
          {drifted ? <StatusBanner kind="warn">{t("explainer.drifted")}</StatusBanner> : null}
          <AsyncBoundary
            state={queryState(walk)}
            skeleton="lines"
            skeletonLines={6}
            errorMessage={t("explainer.failed")}
            // A walk is one object, never a list, so the empty rung of the
            // ladder cannot be reached. It is required, so it is answered.
            empty={<StatusBanner kind="info">{t("explainer.noSteps")}</StatusBanner>}
          >
            {(data) => (
              <WalkExplainer
                steps={steps}
                layout={layout}
                rule={data.rule}
                composedFrom={data.composed_from}
                textEn={data.cell.text_en}
                textAr={data.cell.text_ar}
                identity={data.cell.identity}
                error={data.cell.error}
              />
            )}
          </AsyncBoundary>
        </div>
      </div>
    </div>,
    document.body,
  );
}
