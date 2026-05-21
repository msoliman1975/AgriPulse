// Visual viewer + editor for a decision tree.
//
// PR-D1 introduced this page as read-only. PR-D2 layered click-to-select
// + inline editing for the safe-to-edit fields (labels, leaf outcome
// fields). PR-D3 added the parameters editor + publish-from-canvas.
//
// PR-D4 introduces *structural* authoring: add child, delete subtree,
// build a tree from scratch. The canvas now layouts off a **draft
// YAML** held in component state (not the persisted compiled JSON),
// so add/delete shows immediately. Property patches (labels, outcome
// fields) still live in `editBuffer` and apply at save time. The
// "Open YAML editor" link remains for things D4 doesn't cover —
// condition expressions, on_match/on_miss re-wiring after creation.
//
// Save flow:
//   draftYaml + editBuffer + paramsBuffer
//      → applyEditsToYaml (label/outcome patches)
//      → applyParameterEditsToYaml (top-level params block)
//      → POST decision-trees/{code}/versions

import type { ReactNode } from "react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";

import { Pill } from "@/components/Pill";
import { Skeleton } from "@/components/Skeleton";
import { useCapability } from "@/rbac/useCapability";
import type { DryRunResponse } from "@/api/decisionTrees";
import {
  useAppendDecisionTreeVersion,
  useDecisionTree,
  useDryRunDecisionTree,
  usePublishDecisionTreeVersion,
} from "@/queries/decisionTrees";

import { AddChildDialog } from "../components/AddChildDialog";
import { CanvasDryRunPanel } from "../components/CanvasDryRunPanel";
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
import {
  applyAddNode,
  applyDeleteNode,
  applyDeleteUnreachable,
  applyRewireBranch,
  applySetNodeCondition,
  findUnreachableNodes,
  generateNodeId,
  parseYamlDoc,
  validateTreeStructure,
  type NodeKind,
} from "../lib/treeStructure";
import { pathHighlight } from "../lib/dryRunHighlight";
import { useUndoableYaml } from "../lib/useUndoableYaml";

interface PendingAddChild {
  parentId: string;
  branch: "match" | "miss";
  suggestedId: string;
}

export function DecisionTreeViewerPage(): ReactNode {
  const { code = "" } = useParams<{ code: string }>();
  const { t } = useTranslation("decisionTrees");
  const canManage = useCapability("decision_tree.manage");
  const detail = useDecisionTree(code);
  const append = useAppendDecisionTreeVersion();
  const publish = usePublishDecisionTreeVersion();
  const dryRun = useDryRunDecisionTree();

  // PR-D2: edit buffer + selection. Selection survives across re-renders
  // even when the tree refetches because the node id is stable.
  const [editBuffer, setEditBuffer] = useState<NodeEditBuffer>({});
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  // PR-D3: parameters declaration buffer.
  const [paramsBuffer, setParamsBuffer] = useState<ParametersEditBuffer>({});

  // PR-D4: draft YAML drives the canvas. Hydrated from the published
  // version's YAML once; structural edits mutate this in place. Property
  // patches in `editBuffer` are applied on save.
  //
  // PR-D8: tracked through useUndoableYaml so the author can Cmd/Ctrl-Z
  // back through structural edits. `replace()` is called on hydrate +
  // save to clear the stack (history doesn't survive a version switch).
  const draft = useUndoableYaml(null);
  const draftYaml = draft.value;
  const setDraftYaml = draft.setValue;
  const [hydratedFromVersionId, setHydratedFromVersionId] = useState<string | null>(
    null,
  );
  const [addChildPending, setAddChildPending] = useState<PendingAddChild | null>(
    null,
  );
  const [addChildError, setAddChildError] = useState<string | null>(null);
  const [deletePending, setDeletePending] = useState<string | null>(null);
  const [structuralError, setStructuralError] = useState<string | null>(null);

  // PR-D7: dry-run state. `result` drives the canvas path highlight
  // and the outcome banner. Cleared on save / discard / version
  // switch so a stale highlight doesn't outlive its YAML.
  const [dryRunBlockId, setDryRunBlockId] = useState("");
  const [dryRunMode, setDryRunMode] = useState<"draft" | "current">("draft");
  const [dryRunResult, setDryRunResult] = useState<DryRunResponse | null>(null);

  // Resolve the version we hydrate from: prefer the current published
  // version, fall back to the latest version if nothing is published.
  const sourceVersion = useMemo(() => {
    const versions = detail.data?.versions ?? [];
    if (versions.length === 0) return null;
    const currentVersionNum = detail.data?.current_version ?? null;
    const current = currentVersionNum
      ? versions.find((v) => v.version === currentVersionNum)
      : null;
    return current ?? versions[0];
  }, [detail.data]);

  const sourceYaml = sourceVersion?.tree_yaml ?? null;

  // Hydrate the draft from source on first load and on version switch.
  // We deliberately don't refresh the draft when only `tree.versions`
  // changes (e.g. after a successful append) — `onSave` resets local
  // state explicitly so the new version becomes the source-of-truth
  // without blowing away unrelated state.
  useEffect(() => {
    if (sourceVersion && sourceVersion.id !== hydratedFromVersionId) {
      draft.replace(sourceVersion.tree_yaml);
      setHydratedFromVersionId(sourceVersion.id);
    }
  }, [sourceVersion, hydratedFromVersionId, draft]);

  // Parse the draft into a CompiledTree-shaped object for layout.
  // The YAML schema already matches CompiledTree (root + nodes +
  // parameters), so jsYaml.load is a one-step "compile" for layout.
  // This is intentionally lighter than backend compile_tree (no
  // expression validation), since the backend is authoritative on save.
  const draftCompiled = useMemo<CompiledTree | null>(() => {
    if (!draftYaml) return null;
    const doc = parseYamlDoc(draftYaml);
    if (!doc) return null;
    return doc as CompiledTree;
  }, [draftYaml]);

  const layout = useMemo(() => layoutTree(draftCompiled), [draftCompiled]);
  const dirtyIds = useMemo(
    () => new Set(Object.keys(editBuffer).filter((id) => Object.keys(editBuffer[id]).length > 0)),
    [editBuffer],
  );
  const selectedNode = useMemo(() => {
    if (!selectedNodeId) return null;
    return layout.nodes.find((n) => n.id === selectedNodeId) ?? null;
  }, [layout.nodes, selectedNodeId]);

  // Surfaced as the bottom-of-panel error list / Save-button gate.
  const structuralErrors = useMemo(
    () => (draftYaml ? validateTreeStructure(draftYaml) : []),
    [draftYaml],
  );

  // PR-D7: highlight sets fed into TreeCanvas. Empty when no result.
  const highlight = useMemo(
    () => (dryRunResult ? pathHighlight(dryRunResult.path) : null),
    [dryRunResult],
  );

  // Orphan-after-rewire detector (E2E fix). The canvas only renders
  // nodes reachable from root; rewires can silently strand subtrees in
  // the YAML. Surface them so the author can decide whether to clean
  // up or re-wire.
  const unreachableNodes = useMemo(
    () => (draftYaml ? findUnreachableNodes(draftYaml) : []),
    [draftYaml],
  );

  const onCleanupUnreachable = (): void => {
    if (!draftYaml) return;
    try {
      const next = applyDeleteUnreachable(draftYaml);
      setDraftYaml(next);
    } catch (err) {
      setStructuralError(
        err instanceof Error ? err.message : "Cleanup failed",
      );
    }
  };

  // PR-D8: Cmd/Ctrl-Z = undo, Cmd-Shift-Z / Ctrl-Y = redo. Only fire
  // when no text input has focus so they don't fight in-form editing.
  useEffect(() => {
    if (!canManage) return;
    const handler = (e: KeyboardEvent): void => {
      const target = e.target as HTMLElement | null;
      const tag = target?.tagName?.toLowerCase();
      if (
        tag === "input" ||
        tag === "textarea" ||
        tag === "select" ||
        target?.isContentEditable
      ) {
        return;
      }
      const isMod = e.metaKey || e.ctrlKey;
      if (!isMod) return;
      const key = e.key.toLowerCase();
      if (key === "z" && !e.shiftKey) {
        e.preventDefault();
        draft.undo();
      } else if ((key === "z" && e.shiftKey) || key === "y") {
        e.preventDefault();
        draft.redo();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [canManage, draft]);

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
  const structuralDirty =
    draftYaml !== null && sourceYaml !== null && draftYaml !== sourceYaml;
  const dirty =
    hasEdits(editBuffer) ||
    hasParameterEdits(paramsBuffer) ||
    structuralDirty;
  const declaredParams: Record<string, ParameterDeclaration> =
    (draftCompiled?.parameters as Record<string, ParameterDeclaration> | undefined) ?? {};
  const latestVersion = tree.versions[0];
  const hasUnpublishedDraft =
    latestVersion !== undefined &&
    (latestVersion.published_at == null ||
      tree.current_version !== latestVersion.version);
  const rootId = draftCompiled?.root ?? null;

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
    if (sourceYaml) draft.replace(sourceYaml);
    setStructuralError(null);
    setSelectedNodeId(null);
    setDryRunResult(null);
  };

  // PR-D7: fire the dry-run mutation. Draft mode sends the in-editor
  // YAML so the canvas reflects the *current* edits (matches author
  // expectations); current mode tests the published version for
  // before-vs-after comparisons.
  const onDryRun = (): void => {
    if (!dryRunBlockId.trim()) return;
    const payload =
      dryRunMode === "draft"
        ? { block_id: dryRunBlockId.trim(), tree_yaml: draftYaml ?? "" }
        : {
            block_id: dryRunBlockId.trim(),
            version: tree.current_version ?? undefined,
          };
    dryRun.mutate(
      { code: tree.code, payload },
      { onSuccess: (res) => setDryRunResult(res) },
    );
  };
  const onClearDryRun = (): void => {
    setDryRunResult(null);
  };

  // PR-D4 structural ops.
  const onRequestAddChild = (parentId: string, branch: "match" | "miss"): void => {
    if (!draftYaml) return;
    const doc = parseYamlDoc(draftYaml);
    if (!doc) return;
    setAddChildError(null);
    setAddChildPending({
      parentId,
      branch,
      suggestedId: generateNodeId(doc, "decision"),
    });
  };
  const onConfirmAddChild = (kind: NodeKind, nodeId: string): void => {
    if (!draftYaml || !addChildPending) return;
    try {
      const result = applyAddNode(draftYaml, {
        parentId: addChildPending.parentId,
        branch: addChildPending.branch,
        kind,
        newNodeId: nodeId,
      });
      setDraftYaml(result.yaml);
      setSelectedNodeId(result.newNodeId);
      setAddChildPending(null);
      setAddChildError(null);
    } catch (err) {
      setAddChildError(
        err instanceof Error ? err.message : t("editor.addChild.failed"),
      );
    }
  };
  // PR-D6: drag-to-rewire — drop a port onto a target node.
  const onRewire = (
    parentId: string,
    branch: "match" | "miss",
    targetId: string,
  ): void => {
    if (!draftYaml) return;
    try {
      const next = applyRewireBranch(draftYaml, { parentId, branch, toNodeId: targetId });
      setDraftYaml(next);
      setStructuralError(null);
    } catch (err) {
      setStructuralError(
        err instanceof Error ? err.message : t("editor.canvas.rewireFailed"),
      );
    }
  };

  // PR-D5: rewrite a decision node's condition tree from the builder.
  const onConditionChange = (nodeId: string, nextTree: unknown): void => {
    if (!draftYaml) return;
    try {
      const next = applySetNodeCondition(draftYaml, nodeId, nextTree);
      setDraftYaml(next);
    } catch (err) {
      setStructuralError(
        err instanceof Error ? err.message : t("editor.condition.applyFailed"),
      );
    }
  };

  const onRequestDelete = (nodeId: string): void => {
    setStructuralError(null);
    setDeletePending(nodeId);
  };
  const onConfirmDelete = (): void => {
    if (!draftYaml || !deletePending) return;
    try {
      const result = applyDeleteNode(draftYaml, deletePending);
      setDraftYaml(result.yaml);
      // If the selected node was inside the removed subtree, clear it.
      if (selectedNodeId && result.removed.includes(selectedNodeId)) {
        setSelectedNodeId(null);
      }
      // Strip patches that pointed at removed nodes — saving them
      // would no-op but they'd still show as "dirty" in the panel.
      setEditBuffer((buf) => {
        const next = { ...buf };
        for (const id of result.removed) delete next[id];
        return next;
      });
      setDeletePending(null);
    } catch (err) {
      setStructuralError(
        err instanceof Error ? err.message : t("editor.delete.failed"),
      );
      setDeletePending(null);
    }
  };

  const canSave =
    dirty && structuralErrors.length === 0 && !append.isPending;

  const onSave = async (): Promise<void> => {
    if (!draftYaml) return;
    let nextYaml = applyEditsToYaml(draftYaml, editBuffer);
    nextYaml = applyParameterEditsToYaml(nextYaml, paramsBuffer);
    await append.mutateAsync({ code, payload: { tree_yaml: nextYaml } });
    setEditBuffer({});
    setParamsBuffer({});
    // Force re-hydration from the new latest version. Clearing the
    // hydrated-from id triggers the useEffect above on the next render
    // once the detail query refetches.
    setHydratedFromVersionId(null);
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

  const deleteSubtreeSize = (() => {
    if (!deletePending || !draftYaml) return 0;
    const doc = parseYamlDoc(draftYaml);
    if (!doc) return 0;
    // Cheap recount — collectSubtree lives behind applyDeleteNode but
    // we don't have the result yet. Walk locally.
    const nodes = doc.nodes ?? {};
    const visited = new Set<string>();
    const stack = [deletePending];
    while (stack.length > 0) {
      const id = stack.pop()!;
      if (visited.has(id)) continue;
      visited.add(id);
      const n = nodes[id];
      if (!n) continue;
      if (n.on_match) stack.push(n.on_match);
      if (n.on_miss) stack.push(n.on_miss);
    }
    return visited.size;
  })();

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
            {structuralErrors.length > 0 ? (
              <Pill kind="crit">
                {t("editor.header.invalidCount", { n: structuralErrors.length })}
              </Pill>
            ) : null}
          </div>
          <p className="mt-1 font-mono text-xs text-ap-muted">{tree.code}</p>
          {tree.description_en ? (
            <p className="mt-2 max-w-prose text-sm text-ap-muted">{tree.description_en}</p>
          ) : null}
        </div>
        <div className="flex items-center gap-2">
          {canManage ? (
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => draft.undo()}
                disabled={!draft.canUndo}
                title={t("editor.header.undoTitle")}
                className="rounded-md border border-ap-line bg-ap-panel px-2 py-1.5 text-sm font-medium text-ap-ink hover:bg-ap-bg/60 disabled:opacity-40"
              >
                ↶ {t("editor.header.undo")}
              </button>
              <button
                type="button"
                onClick={() => draft.redo()}
                disabled={!draft.canRedo}
                title={t("editor.header.redoTitle")}
                className="rounded-md border border-ap-line bg-ap-panel px-2 py-1.5 text-sm font-medium text-ap-ink hover:bg-ap-bg/60 disabled:opacity-40"
              >
                ↷ {t("editor.header.redo")}
              </button>
            </div>
          ) : null}
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
                disabled={!canSave}
                title={
                  structuralErrors.length > 0
                    ? t("editor.header.fixErrorsHint")
                    : undefined
                }
                className="rounded-md bg-ap-primary px-3 py-1.5 text-sm font-medium text-white hover:bg-ap-primary/90 disabled:opacity-50"
              >
                {append.isPending
                  ? t("editor.header.saving")
                  : t("editor.header.saveDraft")}
              </button>
            </>
          ) : null}
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
      {structuralError ? (
        <p className="rounded-md border border-ap-crit/40 bg-ap-crit/10 p-2 text-xs text-ap-crit">
          {structuralError}
        </p>
      ) : null}

      <Legend />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_360px]">
        <div className="flex flex-col gap-4">
          <CanvasDryRunPanel
            blockId={dryRunBlockId}
            onBlockIdChange={setDryRunBlockId}
            mode={dryRunMode}
            onModeChange={setDryRunMode}
            canUseCurrent={tree.current_version != null}
            isRunning={dryRun.isPending}
            result={dryRunResult}
            errorMessage={
              dryRun.isError ? (dryRun.error?.message ?? "") : undefined
            }
            onRun={onDryRun}
            onClear={onClearDryRun}
          />
          <TreeCanvas
            layout={layout}
            selectedNodeId={selectedNodeId}
            onSelectNode={setSelectedNodeId}
            dirtyNodeIds={dirtyIds}
            onAddChild={canManage ? onRequestAddChild : undefined}
            onRewire={canManage ? onRewire : undefined}
            pathNodeIds={highlight?.nodes}
            pathEdgeKeys={highlight?.edges}
            terminalNodeId={highlight?.terminalNodeId ?? null}
          />
          {unreachableNodes.length > 0 ? (
            <div className="flex items-start justify-between gap-3 rounded-md border border-ap-warn/40 bg-ap-warn/5 p-3 text-xs">
              <div>
                <p className="font-semibold text-ap-warn">
                  {t("editor.unreachable.heading", { count: unreachableNodes.length })}
                </p>
                <p className="mt-1 text-ap-ink">
                  {t("editor.unreachable.body")}
                </p>
                <p className="mt-1 font-mono text-[11px] text-ap-muted">
                  {unreachableNodes.join(", ")}
                </p>
              </div>
              {canManage ? (
                <button
                  type="button"
                  onClick={onCleanupUnreachable}
                  className="shrink-0 rounded-md border border-ap-warn/60 bg-white px-2 py-1 text-xs font-medium text-ap-warn hover:bg-ap-warn/10"
                >
                  {t("editor.unreachable.cleanup")}
                </button>
              ) : null}
            </div>
          ) : null}
          {structuralErrors.length > 0 ? (
            <div className="rounded-md border border-ap-crit/40 bg-ap-crit/5 p-3 text-xs">
              <p className="mb-1 font-semibold text-ap-crit">
                {t("editor.errors.heading")}
              </p>
              <ul className="space-y-0.5 text-ap-ink">
                {structuralErrors.map((e, i) => (
                  <li key={i}>
                    {e.nodeId ? (
                      <span className="font-mono text-ap-muted">[{e.nodeId}] </span>
                    ) : null}
                    {e.message}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          <ParametersPanel
            declared={declaredParams}
            buffer={paramsBuffer}
            canEdit={canManage}
            onChange={onParameterChange}
          />
          {Object.keys(declaredParams).length > 0 ? (
            <ParameterOverridesPanel code={tree.code} canManage={canManage} />
          ) : null}
        </div>
        {selectedNode ? (
          <NodeDetailsPanel
            node={selectedNode}
            pendingPatch={editBuffer[selectedNode.id]}
            canEdit={canManage}
            isRoot={rootId === selectedNode.id}
            onPatch={onPatch}
            onClearPatch={onClearNodePatch}
            onDelete={canManage ? onRequestDelete : undefined}
            onAddChild={canManage ? onRequestAddChild : undefined}
            onConditionChange={canManage ? onConditionChange : undefined}
          />
        ) : (
          <aside className="flex h-fit flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-ap-line bg-ap-panel p-6 text-center text-sm text-ap-muted">
            <p>{t("editor.panel.selectHint")}</p>
            {canManage ? (
              <p className="text-xs">{t("editor.panel.selectHintActions")}</p>
            ) : null}
          </aside>
        )}
      </div>

      {draftCompiled === null && !isDraftOnly ? (
        <p className="text-xs text-ap-crit">{t("viewer.compiledMissing")}</p>
      ) : null}

      {addChildPending ? (
        <AddChildDialog
          parentId={addChildPending.parentId}
          branch={addChildPending.branch}
          suggestedId={addChildPending.suggestedId}
          error={addChildError}
          onCancel={() => {
            setAddChildPending(null);
            setAddChildError(null);
          }}
          onSubmit={onConfirmAddChild}
        />
      ) : null}

      {deletePending ? (
        <DeleteConfirmDialog
          nodeId={deletePending}
          subtreeSize={deleteSubtreeSize}
          onCancel={() => setDeletePending(null)}
          onConfirm={onConfirmDelete}
        />
      ) : null}
    </div>
  );
}

interface DeleteConfirmDialogProps {
  nodeId: string;
  subtreeSize: number;
  onCancel: () => void;
  onConfirm: () => void;
}

function DeleteConfirmDialog({
  nodeId,
  subtreeSize,
  onCancel,
  onConfirm,
}: DeleteConfirmDialogProps): JSX.Element {
  const { t } = useTranslation("decisionTrees");
  // Minimal modal — no resource-pool fetches needed; keep it inline
  // to avoid widening the Modal component's surface.
  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onCancel}
    >
      <div
        className="w-full max-w-md rounded-xl bg-ap-panel p-4 shadow-card"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-base font-semibold text-ap-ink">
          {t("editor.delete.title")}
        </h2>
        <p className="mt-2 text-sm text-ap-ink">
          {subtreeSize > 1
            ? t("editor.delete.cascadeBody", { nodeId, count: subtreeSize })
            : t("editor.delete.singleBody", { nodeId })}
        </p>
        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="rounded-md px-3 py-1.5 text-sm text-ap-muted"
          >
            {t("editor.delete.cancel")}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            className="rounded-md bg-ap-crit px-3 py-1.5 text-sm font-medium text-white hover:bg-ap-crit/90"
          >
            {t("editor.delete.confirm")}
          </button>
        </div>
      </div>
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
