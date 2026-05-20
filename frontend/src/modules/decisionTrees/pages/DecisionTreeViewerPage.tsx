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
  usePublishDecisionTreeVersion,
} from "@/queries/decisionTrees";

import { NodeDetailsPanel } from "../components/NodeDetailsPanel";
import { ParameterOverridesPanel } from "../components/ParameterOverridesPanel";
import { ParametersPanel } from "../components/ParametersPanel";
import { TreeCanvas } from "../components/TreeCanvas";
import { layoutTree, type CompiledTree } from "../layout/treeLayout";
import {
  applyParameterEditsToYaml,
  hasParameterEdits,
  type ParameterDeclaration,
  type ParametersEditBuffer,
} from "../lib/parametersEdit";
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
  const publish = usePublishDecisionTreeVersion();

  // PR-D2: edit buffer + selection. Selection survives across re-renders
  // even when the tree refetches because the node id is stable.
  const [editBuffer, setEditBuffer] = useState<NodeEditBuffer>({});
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  // PR-D3: parameters declaration buffer (separate from node edit
  // buffer because parameter edits patch the top-level `parameters:`
  // block rather than per-node `nodes.<id>`).
  const [paramsBuffer, setParamsBuffer] = useState<ParametersEditBuffer>({});

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
  const dirty = hasEdits(editBuffer) || hasParameterEdits(paramsBuffer);
  // PR-D3: surface declared parameters off the compiled JSON so the
  // ParametersPanel can render them without an extra fetch.
  const declaredParams: Record<string, ParameterDeclaration> =
    (compiled?.parameters as Record<string, ParameterDeclaration> | undefined) ?? {};
  // The latest draft (whether or not it's published) drives the
  // "Publish" button. When `current_version` lags the latest version,
  // there's an unpublished draft to push live.
  const latestVersion = tree.versions[0];
  const hasUnpublishedDraft =
    latestVersion !== undefined &&
    (latestVersion.published_at == null ||
      tree.current_version !== latestVersion.version);

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
    setParamsBuffer({});
  };
  const onSave = async (): Promise<void> => {
    if (!sourceYaml) return;
    // Apply both buffers in sequence (order doesn't matter — node
    // edits patch `nodes.*`, parameter edits patch the top-level
    // `parameters:` block; they don't intersect).
    let nextYaml = applyEditsToYaml(sourceYaml, editBuffer);
    nextYaml = applyParameterEditsToYaml(nextYaml, paramsBuffer);
    await append.mutateAsync({ code, payload: { tree_yaml: nextYaml } });
    setEditBuffer({});
    setParamsBuffer({});
    setSelectedNodeId(null);
  };
  const onPublishLatest = async (): Promise<void> => {
    if (!latestVersion) return;
    await publish.mutateAsync({ code, version: latestVersion.version });
  };
  const onParameterChange = (
    name: string,
    decl: ParameterDeclaration | null,
  ): void => {
    setParamsBuffer((buf) => ({ ...buf, [name]: decl }));
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
          {/* PR-D3: publish-from-canvas. Visible only when there's an
              unpublished draft AND the buffer is clean (we don't want
              to publish a version that lags the user's pending edits). */}
          {canManage && !dirty && hasUnpublishedDraft && latestVersion ? (
            <button
              type="button"
              onClick={() => {
                void onPublishLatest();
              }}
              disabled={publish.isPending}
              className="rounded-md bg-ap-info px-3 py-1.5 text-sm font-medium text-white hover:bg-ap-info/90 disabled:opacity-50"
            >
              {publish.isPending
                ? t("editor.header.publishing")
                : t("editor.header.publish", { n: latestVersion.version })}
            </button>
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
      {publish.isError ? (
        <p className="rounded-md border border-ap-crit/40 bg-ap-crit/10 p-2 text-xs text-ap-crit">
          {t("editor.header.publishFailed")}
        </p>
      ) : null}

      <Legend />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_360px]">
        <div className="flex flex-col gap-4">
          <TreeCanvas
            layout={layout}
            selectedNodeId={selectedNodeId}
            onSelectNode={setSelectedNodeId}
            dirtyNodeIds={dirtyIds}
          />
          {/* PR-D3: author-side parameters declaration editor. Renders
              under the canvas so it's discoverable without taking
              over the right-side selection panel. */}
          <ParametersPanel
            declared={declaredParams}
            buffer={paramsBuffer}
            canEdit={canManage}
            onChange={onParameterChange}
          />
          {/* PR-D3 consumer of PR-C: tenant-side overrides. Only
              renders when the tree declares at least one parameter
              the tenant can override; otherwise it stays empty and
              clutters the layout, so we gate on declaredParams. */}
          {Object.keys(declaredParams).length > 0 ? (
            <ParameterOverridesPanel code={tree.code} canManage={canManage} />
          ) : null}
        </div>
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
