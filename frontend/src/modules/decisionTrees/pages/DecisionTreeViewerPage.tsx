// Read-only visual viewer for a decision tree (PR-D1).
//
// Fetches the tree detail via the existing query hook (same one the
// YAML editor uses) and renders the *current published* version's
// compiled JSON through TreeCanvas. When no version is published yet,
// shows an empty-state with a link to the YAML editor so the author
// can publish v1.
//
// PR-D2 adds in-canvas node editing; D1 is intentionally read-only so
// the visual + YAML editors stay decoupled — opening the viewer never
// dirties the editor buffer.

import type { ReactNode } from "react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";

import { Pill } from "@/components/Pill";
import { Skeleton } from "@/components/Skeleton";
import { useDecisionTree } from "@/queries/decisionTrees";

import { TreeCanvas } from "../components/TreeCanvas";
import { layoutTree, type CompiledTree } from "../layout/treeLayout";

export function DecisionTreeViewerPage(): ReactNode {
  const { code = "" } = useParams<{ code: string }>();
  const { t } = useTranslation("decisionTrees");
  const detail = useDecisionTree(code);

  // Resolve the compiled JSON to render. Prefer the current published
  // version (most-up-to-date authoritative shape); fall back to the
  // latest draft so an author who hasn't published yet still sees
  // their work.
  const compiled = useMemo<CompiledTree | null>(() => {
    const versions = detail.data?.versions ?? [];
    if (versions.length === 0) return null;
    const currentVersionNum = detail.data?.current_version ?? null;
    const current = currentVersionNum
      ? versions.find((v) => v.version === currentVersionNum)
      : null;
    const target = current ?? versions[0];
    if (!target?.tree_compiled) return null;
    // The API types `tree_compiled` as `Record<string, unknown>`;
    // CompiledTree has only optional fields so structural assignment
    // is safe without a cast.
    return target.tree_compiled;
  }, [detail.data]);

  const layout = useMemo(() => layoutTree(compiled), [compiled]);

  if (detail.isError) {
    return <p className="p-4 text-sm text-ap-crit">{t("edit.loadFailed")}</p>;
  }
  if (detail.isLoading || !detail.data) {
    return (
      <div className="mx-auto flex max-w-5xl flex-col gap-4 p-4">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-96 w-full" />
      </div>
    );
  }

  const tree = detail.data;
  const isDraftOnly = tree.current_version == null;

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-semibold text-ap-ink">{tree.name_en}</h1>
            {isDraftOnly ? (
              <Pill kind="neutral">{t("viewer.header.draftOnly")}</Pill>
            ) : (
              <Pill kind="ok">{t("list.row.v", { n: tree.current_version })}</Pill>
            )}
          </div>
          <p className="mt-1 font-mono text-xs text-ap-muted">{tree.code}</p>
          {tree.description_en ? (
            <p className="mt-2 max-w-prose text-sm text-ap-muted">{tree.description_en}</p>
          ) : null}
        </div>
        <div className="flex items-center gap-2">
          <Link
            to={`/settings/decision-trees/${tree.code}`}
            className="rounded-md border border-ap-line bg-ap-panel px-3 py-1.5 text-sm font-medium text-ap-ink hover:bg-ap-bg/60"
          >
            {t("viewer.header.openYamlEditor")}
          </Link>
        </div>
      </header>

      <Legend />

      <TreeCanvas layout={layout} />

      {compiled === null && !isDraftOnly ? (
        // Compiled JSON missing despite a published version exists —
        // shouldn't happen in practice (loader always inserts compiled
        // alongside YAML), but render a defensive note.
        <p className="text-xs text-ap-crit">{t("viewer.compiledMissing")}</p>
      ) : null}
    </div>
  );
}

function Legend(): JSX.Element {
  const { t } = useTranslation("decisionTrees");
  // Mirrors the palette from treeLayout / TreeCanvas; intentionally
  // duplicated as inline-style swatches so the legend doesn't need to
  // import internals. PR-D2 will likely move palette into a shared
  // const file once the editor also reuses it.
  const swatches: Array<{ label: string; bg: string; border: string }> = [
    { label: t("viewer.legend.decision"), bg: "#ffffff", border: "#94a3b8" },
    {
      label: t("viewer.legend.recommendation"),
      bg: "#ecfdf5",
      border: "#10b981",
    },
    { label: t("viewer.legend.alert"), bg: "#fffbeb", border: "#f59e0b" },
    { label: t("viewer.legend.noop"), bg: "#f8fafc", border: "#cbd5e1" },
  ];
  return (
    <div className="flex flex-wrap items-center gap-3 text-xs text-ap-muted">
      <span className="font-medium text-ap-ink">{t("viewer.legend.title")}</span>
      {swatches.map((sw) => (
        <span key={sw.label} className="inline-flex items-center gap-1.5">
          <span
            className="inline-block h-3 w-3 rounded-sm"
            style={{ backgroundColor: sw.bg, borderColor: sw.border, borderWidth: 1, borderStyle: "solid" }}
            aria-hidden
          />
          {sw.label}
        </span>
      ))}
    </div>
  );
}
