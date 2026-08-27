// Inline dry-run panel for the canvas editor (PR-D7).
//
// Replaces the YAML editor's dry-run section as the primary path so
// authors can test the *draft they're editing* against a real block
// without committing a new version. The path highlight on TreeCanvas
// is driven by the result this component returns to its parent.

import { type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { DryRunCandidateBlock, DryRunResponse } from "@/api/decisionTrees";
import { Card } from "@/components/Card";
import { Pill } from "@/components/Pill";
import { localizedName } from "@/lib/localizedField";

interface CanvasDryRunPanelProps {
  blockId: string;
  onBlockIdChange: (next: string) => void;
  candidateBlocks: DryRunCandidateBlock[];
  candidatesLoading: boolean;
  mode: "draft" | "current";
  onModeChange: (next: "draft" | "current") => void;
  canUseCurrent: boolean;
  isRunning: boolean;
  result: DryRunResponse | null;
  errorMessage?: string;
  onRun: () => void;
  onClear: () => void;
}

export function CanvasDryRunPanel({
  blockId,
  onBlockIdChange,
  candidateBlocks,
  candidatesLoading,
  mode,
  onModeChange,
  canUseCurrent,
  isRunning,
  result,
  errorMessage,
  onRun,
  onClear,
}: CanvasDryRunPanelProps): ReactNode {
  const { t, i18n } = useTranslation("decisionTrees");
  const matched = result?.matched ?? false;
  const noCandidates = !candidatesLoading && candidateBlocks.length === 0;
  return (
    <Card noPadding className="flex flex-col gap-3 p-3">
      <header className="flex flex-wrap items-end gap-3">
        <div className="flex flex-1 flex-col gap-1">
          <span className="text-xs font-medium text-ap-muted">{t("editor.dryRun.heading")}</span>
          {noCandidates ? (
            <p className="text-xs text-ap-muted">{t("editor.dryRun.noCandidateBlocks")}</p>
          ) : (
            <select
              value={blockId}
              onChange={(e) => onBlockIdChange(e.target.value)}
              disabled={candidatesLoading}
              className="rounded-md border border-ap-line bg-white px-2 py-1 text-xs shadow-sm focus:border-ap-primary focus:outline-none focus:ring-1 focus:ring-ap-primary"
            >
              <option value="">
                {candidatesLoading
                  ? t("editor.dryRun.loadingBlocks")
                  : t("editor.dryRun.selectBlock")}
              </option>
              {candidateBlocks.map((b) => (
                <option key={b.block_id} value={b.block_id}>
                  {localizedName(i18n.language, b.label, b.label_ar)}
                </option>
              ))}
            </select>
          )}
        </div>
        <fieldset className="flex flex-col gap-1 text-xs">
          <legend className="font-medium text-ap-muted">{t("editor.dryRun.mode")}</legend>
          <label className="flex items-center gap-1">
            <input
              type="radio"
              name="dryrun-mode"
              value="draft"
              checked={mode === "draft"}
              onChange={() => onModeChange("draft")}
            />
            {t("editor.dryRun.useDraft")}
          </label>
          <label className="flex items-center gap-1">
            <input
              type="radio"
              name="dryrun-mode"
              value="current"
              disabled={!canUseCurrent}
              checked={mode === "current"}
              onChange={() => onModeChange("current")}
            />
            {t("editor.dryRun.useCurrent")}
          </label>
        </fieldset>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onRun}
            disabled={isRunning || !blockId.trim()}
            className="rounded-md bg-ap-primary px-3 py-1.5 text-sm font-medium text-white hover:bg-ap-primary/90 disabled:opacity-60"
          >
            {isRunning ? t("editor.dryRun.running") : t("editor.dryRun.run")}
          </button>
          {result ? (
            <button
              type="button"
              onClick={onClear}
              className="rounded-md border border-ap-line bg-white px-3 py-1.5 text-sm text-ap-ink hover:bg-ap-bg/40"
            >
              {t("editor.dryRun.clear")}
            </button>
          ) : null}
        </div>
      </header>

      {errorMessage ? <p className="text-xs text-ap-crit">{errorMessage}</p> : null}

      {result ? (
        <div className="flex flex-col gap-2 border-t border-ap-line pt-2">
          {/* A tree the sweep would not run on this block used to dry-run as
              though it did. The picker filters to targeted blocks, so this
              only shows for a block reached some other way — but silence here
              was the bug. */}
          {result.targeting && !result.targeting.matched ? (
            <p className="rounded-md bg-ap-warn-soft p-2 text-xs text-ap-warn">
              {t("editor.dryRun.notTargeted", {
                axis: t(`traces.skipAxis.${result.targeting.axis ?? "crop"}`),
                required: result.targeting.required.join(", ") || "—",
                actual: result.targeting.actual ?? t("traces.unset"),
              })}
            </p>
          ) : null}

          {/* Cell-scoped trees have no single block-level verdict: the sweep
              runs them once per zone. Reporting one walk without saying which
              zone it came from is what made this preview misleading. */}
          {result.scope === "cell" ? (
            <p className="text-xs text-ap-muted">
              {result.cells_evaluated === 0
                ? t("editor.dryRun.cellNoGrid")
                : t("editor.dryRun.cellSummary", {
                    matched: result.cells_matched,
                    total: result.cells_evaluated,
                  })}
            </p>
          ) : null}

          <div className="flex items-center gap-2 text-xs">
            <span className="text-ap-muted">
              {result.scope === "cell"
                ? t("editor.dryRun.outcomeRepresentative")
                : t("editor.dryRun.outcome")}
            </span>
            {matched ? (
              <Pill kind="ok">{t("editor.dryRun.matched")}</Pill>
            ) : (
              <Pill kind="neutral">{t("editor.dryRun.noMatch")}</Pill>
            )}
            {result.outcome?.action_type ? (
              <span className="font-mono">{result.outcome.action_type}</span>
            ) : null}
            {result.outcome?.severity ? (
              <span className="text-ap-muted">· {result.outcome.severity}</span>
            ) : null}
          </div>
          {result.outcome?.text_en ? (
            <p className="text-sm text-ap-ink">{result.outcome.text_en}</p>
          ) : null}
          {result.error ? (
            <p className="text-xs text-ap-crit">
              {t("editor.dryRun.error")}: {result.error}
            </p>
          ) : null}
          {result.scope === "cell" && result.cells.length > 0 ? (
            <details>
              <summary className="cursor-pointer text-[11px] font-medium text-ap-primary">
                {t("editor.dryRun.perZone")}
              </summary>
              <ul className="mt-1 flex flex-col gap-0.5">
                {result.cells.map((cell) => (
                  <li key={cell.cell_id} className="flex items-center gap-2 text-[11px]">
                    <span className="font-mono text-ap-muted">
                      {cell.cell_row === null || cell.cell_col === null
                        ? cell.cell_id.slice(0, 8)
                        : `R${cell.cell_row}·C${cell.cell_col}`}
                    </span>
                    {cell.matched ? (
                      <Pill kind="ok">{t("editor.dryRun.matched")}</Pill>
                    ) : (
                      <Pill kind="neutral">{t("editor.dryRun.noMatch")}</Pill>
                    )}
                    {cell.action_type ? (
                      <span className="font-mono text-ap-ink">{cell.action_type}</span>
                    ) : null}
                    {cell.error ? <span className="text-ap-crit">{cell.error}</span> : null}
                  </li>
                ))}
              </ul>
            </details>
          ) : null}

          {Object.keys(result.evaluation_snapshot).length > 0 ? (
            <details>
              <summary className="cursor-pointer text-[11px] font-medium text-ap-primary">
                {t("editor.dryRun.snapshot")}
              </summary>
              <pre className="mt-1 overflow-x-auto whitespace-pre-wrap font-mono text-[10px] text-ap-ink">
                {JSON.stringify(result.evaluation_snapshot, null, 2)}
              </pre>
            </details>
          ) : null}
        </div>
      ) : null}
    </Card>
  );
}
