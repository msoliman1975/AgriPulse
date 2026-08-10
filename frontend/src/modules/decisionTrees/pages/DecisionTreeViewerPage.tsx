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

import clsx from "clsx";
import type { ComponentProps, ReactNode } from "react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { formatDistanceToNow, parseISO, type Locale } from "date-fns";

import { Card } from "@/components/Card";
import { ErrorState } from "@/components/ErrorState";
import { Modal } from "@/components/Modal";
import { Page } from "@/components/Page";
import { PageHeader } from "@/components/PageHeader";
import { Pill } from "@/components/Pill";
import { Skeleton } from "@/components/Skeleton";
import { useDateLocale } from "@/hooks/useDateLocale";
import { useCapability } from "@/rbac/useCapability";
import { listSignalDefinitions } from "@/api/signals";
import { SignalRefPicker } from "@/modules/signals/components/SignalRefPicker";
import {
  readTreeProvenance,
  type DecisionTreeVersion,
  type DryRunResponse,
} from "@/api/decisionTrees";
import {
  useAppendDecisionTreeVersion,
  useDecisionTree,
  useDecisionTreeCandidateBlocks,
  useDryRunDecisionTree,
  usePublishDecisionTreeVersion,
  useUpdateDecisionTree,
} from "@/queries/decisionTrees";

import { AddChildDialog } from "../components/AddChildDialog";
import { CanvasDryRunPanel } from "../components/CanvasDryRunPanel";
import { MutationErrorBanner } from "../components/MutationErrorBanner";
import { NodeDetailsPanel } from "../components/NodeDetailsPanel";
import { ParameterOverridesPanel } from "../components/ParameterOverridesPanel";
import { ParametersPanel } from "../components/ParametersPanel";
import { ProvenancePanel } from "../components/ProvenancePanel";
import { TreeCanvas } from "../components/TreeCanvas";
import { TreeMetadataPanel } from "../components/TreeMetadataPanel";
import { applyTreeMetaToYaml, readTreeMeta, type TreeMetaFields } from "../lib/metadataEdit";
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

interface TargetingBuffer {
  crop_paths: string[];
  country_codes: string[];
  soil_textures: string[];
  scope: "block" | "cell";
}

/** Order-insensitive equality for the small targeting string arrays. */
function sameSet(a: string[], b: string[]): boolean {
  if (a.length !== b.length) return false;
  const sb = new Set(b);
  return a.every((v) => sb.has(v));
}

export function DecisionTreeViewerPage(): ReactNode {
  const { code = "" } = useParams<{ code: string }>();
  const { t, i18n } = useTranslation("decisionTrees");
  const isAr = i18n.language === "ar";
  const canManage = useCapability("decision_tree.manage");
  const detail = useDecisionTree(code);
  const append = useAppendDecisionTreeVersion();
  const publish = usePublishDecisionTreeVersion();
  const dryRun = useDryRunDecisionTree();
  const candidateBlocks = useDecisionTreeCandidateBlocks(code);
  const update = useUpdateDecisionTree();
  const dateLocale = useDateLocale();

  // Experience redesign: one workspace hosts a Visual | YAML toggle over the
  // same draft. `metaBuffer` holds name/description edits (applied to the
  // draft YAML at save); `targetingBuffer` holds crop/country/soil/scope
  // edits (persisted via PATCH at save).
  const [viewMode, setViewMode] = useState<"visual" | "yaml">("visual");
  const [metaBuffer, setMetaBuffer] = useState<Partial<TreeMetaFields>>({});
  const [targetingBuffer, setTargetingBuffer] = useState<TargetingBuffer | null>(null);
  const [targetingHydratedId, setTargetingHydratedId] = useState<string | null>(null);
  // Signal definitions power the YAML-mode SignalRefPicker helper.
  const signalDefsQ = useQuery({
    queryKey: ["dtree-workspace/signalDefinitions"],
    queryFn: () => listSignalDefinitions(),
    staleTime: 5 * 60_000,
  });

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
  const [hydratedFromVersionId, setHydratedFromVersionId] = useState<string | null>(null);
  const [addChildPending, setAddChildPending] = useState<PendingAddChild | null>(null);
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

  // Hydrate the targeting buffer from the persisted tree row. Re-fires
  // after a save (onSave clears `targetingHydratedId`) so the buffer
  // re-syncs with the freshly-PATCHed row.
  useEffect(() => {
    const d = detail.data;
    if (d && d.id !== targetingHydratedId) {
      setTargetingBuffer({
        crop_paths: d.crop_paths,
        country_codes: d.country_codes,
        soil_textures: d.soil_textures,
        scope: d.scope,
      });
      setTargetingHydratedId(d.id);
    }
  }, [detail.data, targetingHydratedId]);

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
      setStructuralError(err instanceof Error ? err.message : "Cleanup failed");
    }
  };

  // PR-D8: Cmd/Ctrl-Z = undo, Cmd-Shift-Z / Ctrl-Y = redo. Only fire
  // when no text input has focus so they don't fight in-form editing.
  useEffect(() => {
    if (!canManage) return;
    const handler = (e: KeyboardEvent): void => {
      const target = e.target as HTMLElement | null;
      const tag = target?.tagName?.toLowerCase();
      if (tag === "input" || tag === "textarea" || tag === "select" || target?.isContentEditable) {
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
    return (
      <Page>
        <ErrorState message={t("edit.loadFailed")} />
      </Page>
    );
  }
  if (detail.isLoading || !detail.data) {
    return (
      <Page>
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-96 w-full" />
      </Page>
    );
  }

  const tree = detail.data;
  const isDraftOnly = tree.current_version == null;
  const structuralDirty = draftYaml !== null && sourceYaml !== null && draftYaml !== sourceYaml;

  // Name/description are two projections of the draft YAML: the persisted
  // values parsed out of it, overlaid with any in-panel edits.
  const persistedMeta = readTreeMeta(draftYaml);
  const effectiveMeta: TreeMetaFields = { ...persistedMeta, ...metaBuffer };
  const metaDirty = (Object.keys(metaBuffer) as (keyof TreeMetaFields)[]).some(
    (k) => metaBuffer[k] !== undefined && metaBuffer[k] !== persistedMeta[k],
  );

  // Targeting comes from the buffer (falls back to the row before hydration).
  const targeting: TargetingBuffer = targetingBuffer ?? {
    crop_paths: tree.crop_paths,
    country_codes: tree.country_codes,
    soil_textures: tree.soil_textures,
    scope: tree.scope,
  };
  const targetingDirty =
    !sameSet(targeting.crop_paths, tree.crop_paths) ||
    !sameSet(targeting.country_codes, tree.country_codes) ||
    !sameSet(targeting.soil_textures, tree.soil_textures) ||
    targeting.scope !== tree.scope;

  // Anything that rewrites the YAML body → append a new draft version.
  const yamlDirty =
    hasEdits(editBuffer) || hasParameterEdits(paramsBuffer) || structuralDirty || metaDirty;
  const dirty = yamlDirty || targetingDirty;
  const declaredParams: Record<string, ParameterDeclaration> =
    (draftCompiled?.parameters as Record<string, ParameterDeclaration> | undefined) ?? {};
  const latestVersion = tree.versions[0];
  const hasUnpublishedDraft =
    latestVersion !== undefined &&
    (latestVersion.published_at == null || tree.current_version !== latestVersion.version);
  const rootId = draftCompiled?.root ?? null;
  // Provenance reads from the published/current compiled version (the
  // authoritative normalized shape), not the in-editor draft — it's
  // authored in raw YAML, not via the canvas.
  const provenance = readTreeProvenance(sourceVersion?.tree_compiled);

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
    setMetaBuffer({});
    setTargetingHydratedId(null); // re-hydrate targeting from the row
    if (sourceYaml) draft.replace(sourceYaml);
    setStructuralError(null);
    setSelectedNodeId(null);
    setDryRunResult(null);
  };

  // Load a historical version's YAML into the draft (from the version panel).
  const onLoadVersionIntoDraft = (v: DecisionTreeVersion): void => {
    draft.replace(v.tree_yaml);
    setHydratedFromVersionId(v.id);
    setEditBuffer({});
    setParamsBuffer({});
    setMetaBuffer({});
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
    dryRun.mutate({ code: tree.code, payload }, { onSuccess: (res) => setDryRunResult(res) });
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
      setAddChildError(err instanceof Error ? err.message : t("editor.addChild.failed"));
    }
  };
  // PR-D6: drag-to-rewire — drop a port onto a target node.
  const onRewire = (parentId: string, branch: "match" | "miss", targetId: string): void => {
    if (!draftYaml) return;
    try {
      const next = applyRewireBranch(draftYaml, { parentId, branch, toNodeId: targetId });
      setDraftYaml(next);
      setStructuralError(null);
    } catch (err) {
      setStructuralError(err instanceof Error ? err.message : t("editor.canvas.rewireFailed"));
    }
  };

  // PR-D5: rewrite a decision node's condition tree from the builder.
  const onConditionChange = (nodeId: string, nextTree: unknown): void => {
    if (!draftYaml) return;
    try {
      const next = applySetNodeCondition(draftYaml, nodeId, nextTree);
      setDraftYaml(next);
    } catch (err) {
      setStructuralError(err instanceof Error ? err.message : t("editor.condition.applyFailed"));
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
      setStructuralError(err instanceof Error ? err.message : t("editor.delete.failed"));
      setDeletePending(null);
    }
  };

  // Saving targeting requires a crop (backend enforces min-1 crop_paths).
  const metaBlocksSave = targetingDirty && targeting.crop_paths.length === 0;
  const canSave =
    dirty &&
    structuralErrors.length === 0 &&
    !append.isPending &&
    !update.isPending &&
    !metaBlocksSave;

  const onSave = async (): Promise<void> => {
    if (!draftYaml) return;
    // Structural + name/description edits land as a new draft version.
    if (yamlDirty) {
      let nextYaml = applyEditsToYaml(draftYaml, editBuffer);
      nextYaml = applyParameterEditsToYaml(nextYaml, paramsBuffer);
      nextYaml = applyTreeMetaToYaml(nextYaml, metaBuffer);
      await append.mutateAsync({ code, payload: { tree_yaml: nextYaml } });
    }
    // Targeting persists via PATCH (not versioned). name/description come
    // from the effective meta so the row stays consistent with the YAML.
    if (targetingDirty) {
      await update.mutateAsync({
        code,
        payload: {
          name_en: effectiveMeta.name_en,
          name_ar: effectiveMeta.name_ar || null,
          description_en: effectiveMeta.description_en || null,
          description_ar: effectiveMeta.description_ar || null,
          crop_paths: targeting.crop_paths,
          country_codes: targeting.country_codes,
          soil_textures: targeting.soil_textures,
          scope: targeting.scope,
        },
      });
    }
    setEditBuffer({});
    setParamsBuffer({});
    setMetaBuffer({});
    // Force re-hydration from the new latest version + row. Clearing the
    // hydrated-from ids triggers the useEffects above on the next render
    // once the detail query refetches.
    setHydratedFromVersionId(null);
    setTargetingHydratedId(null);
    setSelectedNodeId(null);
  };
  const onPublishLatest = async (): Promise<void> => {
    if (!latestVersion) return;
    await publish.mutateAsync({ code, version: latestVersion.version });
  };
  const onParameterChange = (name: string, decl: ParameterDeclaration | null): void => {
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
    // PR-8: give the canvas the full page width (capped on ultra-wide) so wide
    // trees render with minimal horizontal scroll.
    <Page width="full">
      <PageHeader
        title={isAr && tree.name_ar ? tree.name_ar : tree.name_en}
        badge={
          <>
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
          </>
        }
        subtitle={
          <>
            <span className="font-mono text-xs">{tree.code}</span>
            {(isAr && tree.description_ar) || tree.description_en ? (
              <span className="mt-2 block max-w-prose">
                {isAr && tree.description_ar ? tree.description_ar : tree.description_en}
              </span>
            ) : null}
          </>
        }
        actions={
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
                  title={structuralErrors.length > 0 ? t("editor.header.fixErrorsHint") : undefined}
                  className="rounded-md bg-ap-primary px-3 py-1.5 text-sm font-medium text-white hover:bg-ap-primary/90 disabled:opacity-50"
                >
                  {append.isPending ? t("editor.header.saving") : t("editor.header.saveDraft")}
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
            <div
              role="tablist"
              aria-label={t("workspace.metadata.heading")}
              className="inline-flex rounded-md border border-ap-line bg-ap-panel p-0.5"
            >
              {(["visual", "yaml"] as const).map((m) => (
                <button
                  key={m}
                  type="button"
                  role="tab"
                  aria-selected={viewMode === m}
                  onClick={() => setViewMode(m)}
                  className={clsx(
                    "rounded px-3 py-1 text-sm font-medium transition-colors",
                    viewMode === m ? "bg-ap-primary text-white" : "text-ap-ink hover:bg-ap-bg/60",
                  )}
                >
                  {t(`workspace.tab.${m}`)}
                </button>
              ))}
            </div>
          </div>
        }
      />

      {append.isError ? (
        <MutationErrorBanner error={append.error} fallback={t("editor.header.saveFailed")} />
      ) : null}
      {publish.isError ? (
        <MutationErrorBanner error={publish.error} fallback={t("editor.header.publishFailed")} />
      ) : null}
      {structuralError ? (
        <p className="rounded-md border border-ap-crit/40 bg-ap-crit/10 p-2 text-xs text-ap-crit">
          {structuralError}
        </p>
      ) : null}
      {update.isError ? (
        <MutationErrorBanner error={update.error} fallback={t("workspace.metadata.saveFailed")} />
      ) : null}

      <TreeMetadataPanel
        meta={effectiveMeta}
        onMetaChange={(patch) => setMetaBuffer((b) => ({ ...b, ...patch }))}
        cropPaths={targeting.crop_paths}
        countryCodes={targeting.country_codes}
        soilTextures={targeting.soil_textures}
        scope={targeting.scope}
        onCropPathsChange={(n) =>
          setTargetingBuffer((b) => ({ ...(b ?? targeting), crop_paths: n }))
        }
        onCountryCodesChange={(n) =>
          setTargetingBuffer((b) => ({ ...(b ?? targeting), country_codes: n }))
        }
        onSoilTexturesChange={(n) =>
          setTargetingBuffer((b) => ({ ...(b ?? targeting), soil_textures: n }))
        }
        onScopeChange={(s) => setTargetingBuffer((b) => ({ ...(b ?? targeting), scope: s }))}
        canEdit={canManage}
      />

      {viewMode === "yaml" ? (
        <YamlMode
          draftYaml={draftYaml ?? ""}
          onChange={setDraftYaml}
          canManage={canManage}
          signalDefs={signalDefsQ.data ?? []}
          signalDefsLoading={signalDefsQ.isLoading}
          signalDefsError={signalDefsQ.isError}
          structuralErrors={structuralErrors}
        />
      ) : (
        <>
          <Legend />

          <ProvenancePanel
            evidence={provenance.evidence}
            transferability={provenance.transferability}
          />

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_360px]">
            <div className="flex flex-col gap-4">
              <CanvasDryRunPanel
                blockId={dryRunBlockId}
                onBlockIdChange={setDryRunBlockId}
                candidateBlocks={candidateBlocks.data ?? []}
                candidatesLoading={candidateBlocks.isLoading}
                mode={dryRunMode}
                onModeChange={setDryRunMode}
                canUseCurrent={tree.current_version != null}
                isRunning={dryRun.isPending}
                result={dryRunResult}
                errorMessage={dryRun.isError ? (dryRun.error?.message ?? "") : undefined}
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
                    <p className="mt-1 text-ap-ink">{t("editor.unreachable.body")}</p>
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
                  <p className="mb-1 font-semibold text-ap-crit">{t("editor.errors.heading")}</p>
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
                cropPaths={targeting.crop_paths}
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
        </>
      )}

      <VersionHistorySection
        versions={tree.versions}
        currentVersion={tree.current_version}
        canManage={canManage}
        publishing={publish.isPending}
        dateLocale={dateLocale}
        onLoad={onLoadVersionIntoDraft}
        onPublish={(v) => publish.mutate({ code, version: v })}
      />

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
    </Page>
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
  return (
    <Modal open onClose={onCancel} labelledBy="delete-confirm-title" className="max-w-md">
      <h2 id="delete-confirm-title" className="text-base font-semibold text-ap-ink">
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
    </Modal>
  );
}

// YAML editing mode — the same draft the canvas renders, as raw text.
// Kept structurally parallel to the visual mode (shared header/metadata/
// version history) so the two are just different bodies over one draft.
function YamlMode({
  draftYaml,
  onChange,
  canManage,
  signalDefs,
  signalDefsLoading,
  signalDefsError,
  structuralErrors,
}: {
  draftYaml: string;
  onChange: (next: string) => void;
  canManage: boolean;
  signalDefs: ComponentProps<typeof SignalRefPicker>["definitions"];
  signalDefsLoading: boolean;
  signalDefsError: boolean;
  structuralErrors: ReturnType<typeof validateTreeStructure>;
}): JSX.Element {
  const { t } = useTranslation("decisionTrees");
  return (
    <Card noPadding>
      <header className="border-b border-ap-line px-4 py-3">
        <h2 className="text-sm font-semibold text-ap-ink">{t("workspace.yaml.heading")}</h2>
        <p className="text-xs text-ap-muted">{t("workspace.yaml.subtitle")}</p>
      </header>
      <div className="p-4">
        {canManage ? (
          <div className="mb-3">
            <SignalRefPicker
              definitions={signalDefs}
              isLoading={signalDefsLoading}
              isError={signalDefsError}
              format="yaml"
            />
          </div>
        ) : null}
        <textarea
          value={draftYaml}
          onChange={(e) => onChange(e.target.value)}
          readOnly={!canManage}
          rows={30}
          spellCheck={false}
          aria-label={t("workspace.yaml.ariaLabel")}
          className="w-full rounded-md border border-ap-line bg-ap-bg/40 px-3 py-2 font-mono text-xs text-ap-ink shadow-inner focus:border-ap-primary focus:outline-none focus:ring-1 focus:ring-ap-primary"
        />
        {structuralErrors.length > 0 ? (
          <div className="mt-3 rounded-md border border-ap-crit/40 bg-ap-crit/5 p-3 text-xs">
            <p className="mb-1 font-semibold text-ap-crit">{t("editor.errors.heading")}</p>
            <ul className="space-y-0.5 text-ap-ink">
              {structuralErrors.map((e, i) => (
                <li key={i}>
                  {e.nodeId ? <span className="font-mono text-ap-muted">[{e.nodeId}] </span> : null}
                  {e.message}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
    </Card>
  );
}

// Version history — shared across both modes; collapsed by default to keep
// the workspace focused. Load-into-draft + publish, ported from the old
// standalone YAML editor page.
function VersionHistorySection({
  versions,
  currentVersion,
  canManage,
  publishing,
  dateLocale,
  onLoad,
  onPublish,
}: {
  versions: DecisionTreeVersion[];
  currentVersion: number | null;
  canManage: boolean;
  publishing: boolean;
  dateLocale: Locale;
  onLoad: (v: DecisionTreeVersion) => void;
  onPublish: (version: number) => void;
}): JSX.Element {
  const { t } = useTranslation("decisionTrees");
  const [open, setOpen] = useState(false);
  return (
    <Card noPadding>
      <header className="flex items-center justify-between border-b border-ap-line px-4 py-3">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-semibold text-ap-ink">{t("workspace.versions.heading")}</h2>
          <span className="text-xs text-ap-muted">{versions.length}</span>
        </div>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="text-xs font-medium text-ap-primary hover:underline"
          aria-expanded={open}
        >
          {open ? t("workspace.metadata.collapse") : t("workspace.metadata.expand")}
        </button>
      </header>
      {open ? (
        <ul className="divide-y divide-ap-line">
          {versions.map((v) => {
            const isCurrent = v.version === currentVersion;
            return (
              <li key={v.id} className="flex flex-col gap-1 px-4 py-3 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-ap-ink">v{v.version}</span>
                  {isCurrent ? (
                    <Pill kind="ok">{t("edit.versions.currentBadge")}</Pill>
                  ) : v.published_at ? (
                    <Pill kind="info">published</Pill>
                  ) : (
                    <Pill kind="neutral">{t("edit.versions.draftBadge")}</Pill>
                  )}
                  {v.notes ? (
                    <span className="text-[11px] italic text-ap-muted">{v.notes}</span>
                  ) : null}
                </div>
                <div className="text-[11px] text-ap-muted">
                  {v.published_at
                    ? t("edit.versions.publishedAt", {
                        when: formatDistanceToNow(parseISO(v.published_at), {
                          addSuffix: true,
                          locale: dateLocale,
                        }),
                      })
                    : t("edit.versions.createdAt", {
                        when: formatDistanceToNow(parseISO(v.created_at), {
                          addSuffix: true,
                          locale: dateLocale,
                        }),
                      })}
                </div>
                <div className="mt-1 flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => onLoad(v)}
                    className="rounded-md border border-ap-line bg-ap-panel px-2 py-0.5 text-[11px] font-medium text-ap-ink hover:bg-ap-line/40"
                  >
                    {t("edit.versions.load")}
                  </button>
                  {canManage && !isCurrent ? (
                    <button
                      type="button"
                      onClick={() => onPublish(v.version)}
                      disabled={publishing}
                      className="rounded-md bg-ap-primary px-2 py-0.5 text-[11px] font-medium text-white hover:bg-ap-primary/90 disabled:opacity-60"
                    >
                      {publishing ? t("edit.versions.publishing") : t("edit.versions.publish")}
                    </button>
                  ) : null}
                </div>
              </li>
            );
          })}
        </ul>
      ) : null}
    </Card>
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
