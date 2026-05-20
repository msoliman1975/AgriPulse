// Visual viewer + editor for a decision tree.
//
// PR-D1 introduced this page as read-only. PR-D2 layers click-to-select +
// inline editing for the safe-to-edit fields (labels, leaf outcome
// fields). The "Open YAML editor" link is the escape hatch for the
// things D2 doesn't surface (condition trees, on_match/on_miss
// pointers, add/delete nodes).
//
// Save flow: edits accumulate in a `NodeEditBuffer` keyed by node id;
// `applyEditsToYaml` patches the source YAML (parse, mutate, dump)
// and the existing `appendDecisionTreeVersion` mutation persists the
// result as a new draft. The author then publishes from the YAML
// editor (PR-D3 will add publish from this page too).

import type { ReactNode } from "react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";

import { Pill } from "@/components/Pill";
import { Skeleton } from "@/components/Skeleton";
import { useCapability } from "@/rbac/useCapability";
import {
  useAppendDecisionTreeVersion,
  useDecisionTree,
} from "@/queries/decisionTrees";

import { NodeDetailsPanel } from "../components/NodeDetailsPanel";
import { TreeCanvas } from "../components/TreeCanvas";
import { layoutTree, type CompiledTree } from "../layout/treeLayout";
import {
  applyEditsToYaml,
  hasEdits,
  patchBuffer,
  type NodeEditBuffer,
  type NodePatch,
} from "../lib/treeEdit";

export function DecisionTreeViewerPage(): ReactNode {
  const { code = "" } = useParams<{ code: string }>();
  const { t } = useTranslation("decisionTrees");
  const canManage = useCapability("decision_tree.manage");
  const detail = useDecisionTree(code);
  const append = useAppendDecisionTreeVersion();

  // PR-D2: edit buffer + selection. Selection survives across re-renders
  // even when the tree refetches because the node id is stable.
  const [editBuffer, setEditBuffer] = useState<NodeEditBuffer>({});
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);

  const compiled = useMemo<CompiledTree | null>(() => {
    const versions = detail.data?.versions ?? [];
    if (versions.length === 0) return null;
    const currentVersionNum = detail.data?.current_version ?? null;
    const current = currentVersionNum
      ? versions.find((v) => v.version === currentVersionNum)
      : null;
    const target = current ?? versions[0];
    if (!target?.tree_compiled) return null;
    return target.tree_compiled;
  }, [detail.data]);

  // Source YAML for the save round-trip. Same version-resolution
  // logic as `compiled` above so the visual edits patch the YAML the
  // viewer is showing.
  const sourceYaml = useMemo<string | null>(() => {
    const versions = detail.data?.versions ?? [];
    if (versions.length === 0) return null;
    const currentVersionNum = detail.data?.current_version ?? null;
    const current = currentVersionNum
      ? versions.find((v) => v.version === currentVersionNum)
      : null;
    return (current ?? versions[0])?.tree_yaml ?? null;
  }, [detail.data]);

  const layout = useMemo(() => layoutTree(compiled), [compiled]);
  const dirtyIds = useMemo(
    () => new Set(Object.keys(editBuffer).filter((id) => Object.keys(editBuffer[id]).length > 0)),
    [editBuffer],
  );
  const selectedNode = useMemo(() => {
    if (!selectedNodeId) return null;
    return layout.nodes.find((n) => n.id === selectedNodeId) ?? null;
  }, [layout.nodes, selectedNodeId]);

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
  const dirty = hasEdits(editBuffer);

  const onPatch = (nodeId: string, patch: NodePatch): void => {
    setEditBuffer((buf) => patchBuffer(buf, nodeId, patch));
  };
  const onClearNodePatch = (nodeId: string): void => {
    setEditBuffer((buf) => {
      const next = { ...buf };
      delete next[nodeId];
      return next;
    });
  };
  const onDiscardAll = (): void => {
    setEditBuffer({});
  };
  const onSave = async (): Promise<void> => {
    if (!sourceYaml) return;
    const nextYaml = applyEditsToYaml(sourceYaml, editBuffer);
    await append.mutateAsync({ code, payload: { tree_yaml: nextYaml } });
    // Drop the buffer after a successful save — the refetch will
    // bring in the new draft as the latest version.
    setEditBuffer({});
    setSelectedNodeId(null);
  };

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-semibold text-ap-ink">{tree.name_en}</h1>
            {isDraftOnly ? (
              <Pill kind="neutral">{t("viewer.header.draftOnly")}</Pill>
            ) : (
              <Pill kind="ok">{t("list.row.v", { n: tree.current_version })}</Pill>
            )}
            {dirty ? <Pill kind="warn">{t("editor.header.unsaved")}</Pill> : null}
          </div>
          <p className="mt-1 font-mono text-xs text-ap-muted">{tree.code}</p>
          {tree.description_en ? (
            <p className="mt-2 max-w-prose text-sm text-ap-muted">{tree.description_en}</p>
          ) : null}
        </div>
        <div className="flex items-center gap-2">
          {canManage && dirty ? (
            <>
              <button
                type="button"
                onClick={onDiscardAll}
                disabled={append.isPending}
                className="rounded-md border border-ap-line bg-ap-panel px-3 py-1.5 text-sm font-medium text-ap-ink hover:bg-ap-bg/60 disabled:opacity-50"
              >
                {t("editor.header.discardAll")}
              </button>
              <button
                type="button"
                onClick={() => {
                  void onSave();
                }}
                disabled={append.isPending}
                className="rounded-md bg-ap-primary px-3 py-1.5 text-sm font-medium text-white hover:bg-ap-primary/90 disabled:opacity-50"
              >
                {append.isPending
                  ? t("editor.header.saving")
                  : t("editor.header.saveDraft")}
              </button>
            </>
          ) : null}
          <Link
            to={`/settings/decision-trees/${tree.code}`}
            className="rounded-md border border-ap-line bg-ap-panel px-3 py-1.5 text-sm font-medium text-ap-ink hover:bg-ap-bg/60"
          >
            {t("viewer.header.openYamlEditor")}
          </Link>
        </div>
      </header>

      {append.isError ? (
        <p className="rounded-md border border-ap-crit/40 bg-ap-crit/10 p-2 text-xs text-ap-crit">
          {t("editor.header.saveFailed")}
        </p>
      ) : null}

      <Legend />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_360px]">
        <TreeCanvas
          layout={layout}
          selectedNodeId={selectedNodeId}
          onSelectNode={setSelectedNodeId}
          dirtyNodeIds={dirtyIds}
        />
        {selectedNode ? (
          <NodeDetailsPanel
            node={selectedNode}
            pendingPatch={editBuffer[selectedNode.id]}
            canEdit={canManage}
            onPatch={onPatch}
            onClearPatch={onClearNodePatch}
          />
        ) : (
          <aside className="flex h-fit items-center justify-center rounded-xl border border-dashed border-ap-line bg-ap-panel p-8 text-center text-sm text-ap-muted">
            {t("editor.panel.selectHint")}
          </aside>
        )}
      </div>

      {compiled === null && !isDraftOnly ? (
        <p className="text-xs text-ap-crit">{t("viewer.compiledMissing")}</p>
      ) : null}
    </div>
  );
}

function Legend(): JSX.Element {
  const { t } = useTranslation("decisionTrees");
  const swatches: Array<{ label: string; bg: string; border: string }> = [
    { label: t("viewer.legend.decision"), bg: "#ffffff", border: "#94a3b8" },
    { label: t("viewer.legend.recommendation"), bg: "#ecfdf5", border: "#10b981" },
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
            style={{
              backgroundColor: sw.bg,
              borderColor: sw.border,
              borderWidth: 1,
              borderStyle: "solid",
            }}
            aria-hidden
          />
          {sw.label}
        </span>
      ))}
    </div>
  );
}
