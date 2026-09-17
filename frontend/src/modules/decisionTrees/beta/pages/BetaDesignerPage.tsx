/**
 * The beta designer.
 *
 * Same page frame as the current editor — `<Page>`, `<PageHeader>`, a
 * `<Breadcrumb>` above the title, `<Card>` panels, `<AsyncBoundary>` for every
 * read — and the same draft model: the canvas lays out a draft YAML held in
 * component state, structural edits rewrite that string, and the save appends
 * a version. Nothing here touches the current editor.
 *
 * Three tabs: the canvas, the combinations table and the dry run. The publish
 * checks sit beside the canvas rather than behind the publish button, because
 * a rejection is about a node and the node is on screen.
 */

import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useParams } from "react-router-dom";

import { AsyncBoundary } from "@/components/AsyncBoundary";
import { Breadcrumb } from "@/components/Breadcrumb";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { EmptyState } from "@/components/EmptyState";
import { Modal } from "@/components/Modal";
import { Page } from "@/components/Page";
import { PageHeader } from "@/components/PageHeader";
import { Pill } from "@/components/Pill";
import { SegmentedControl } from "@/components/SegmentedControl";
import { StatusBanner } from "@/components/StatusBanner";
import { queryState, resolveErrorMessage } from "@/components/asyncState";
import { localizedField } from "@/lib/localizedField";
import { useCapability } from "@/rbac/useCapability";
import {
  useBetaCandidateBlocks,
  useBetaDryRun,
  useBetaTree,
  useCompileBetaTree,
  useFindingCatalogue,
  usePublishBetaTree,
  useSaveBetaDraft,
} from "@/queries/decisionTreesBeta";
import type { BetaDryRunResponse } from "@/api/decisionTreesBeta";

import { useAuthoringScope } from "../../lib/authoringScope";
import { BetaCanvas } from "../components/BetaCanvas";
import { BetaDryRunPanel } from "../components/BetaDryRunPanel";
import { BetaNodePanel } from "../components/BetaNodePanel";
import { CombinationsTab } from "../components/CombinationsTab";
import { PublishChecksPanel } from "../components/PublishChecksPanel";
import { compileBetaTree, type CompileRejection } from "../lib/betaCompile";
import { layoutBetaTree } from "../lib/betaLayout";
import type { FindingSeverity } from "../lib/betaConstants";
import {
  BETA_NODE_KINDS,
  attachBetaNode,
  betaNodeKind,
  buildBetaNode,
  deleteBetaNode,
  parseBetaDoc,
  readCombinations,
  readRegisters,
  setBetaNode,
  writeCombinations,
  writeRegisters,
  type BetaNode,
  type BetaNodeKind,
  type CombinationRule,
  type EdgeSlot,
} from "../lib/betaTree";
import { betaBasePath } from "../lib/betaRoutes";

type Tab = "canvas" | "combinations" | "dryRun";

interface PendingAdd {
  parentId: string;
  slot: EdgeSlot;
}

export function BetaDesignerPage(): ReactNode {
  const { code = "" } = useParams<{ code: string }>();
  const { t, i18n } = useTranslation("decisionTreesBeta");
  const scope = useAuthoringScope();
  const base = betaBasePath(scope);
  const canManage = useCapability("decision_tree.manage");

  const treeQ = useBetaTree(code);
  const findingsQ = useFindingCatalogue();
  const save = useSaveBetaDraft();
  const publish = usePublishBetaTree();
  const remoteCompile = useCompileBetaTree();
  const dryRun = useBetaDryRun();
  const blocksQ = useBetaCandidateBlocks(code);

  const [tab, setTab] = useState<Tab>("canvas");
  const [draftYaml, setDraftYaml] = useState<string | null>(null);
  const [hydratedFrom, setHydratedFrom] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [canvasHeight, setCanvasHeight] = useState(640);
  const [pendingAdd, setPendingAdd] = useState<PendingAdd | null>(null);
  const [blockId, setBlockId] = useState("");
  const [dryRunResult, setDryRunResult] = useState<BetaDryRunResponse | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  // Hydrate the draft from the newest version, once per version. The editor
  // always opens on the latest body, published or not.
  const latest = treeQ.data?.versions[treeQ.data.versions.length - 1] ?? null;
  useEffect(() => {
    if (!latest) return;
    const stamp = `${code}:${latest.version}`;
    if (hydratedFrom === stamp) return;
    setHydratedFrom(stamp);
    setDraftYaml(latest.tree_yaml);
    setDirty(false);
  }, [code, latest, hydratedFrom]);

  const doc = useMemo(() => (draftYaml ? parseBetaDoc(draftYaml) : null), [draftYaml]);
  const layout = useMemo(() => layoutBetaTree(doc), [doc]);
  const declaredCodes = useMemo(() => readRegisters(doc), [doc]);
  const rules = useMemo(() => readCombinations(doc), [doc]);
  const nodeIds = useMemo(() => Object.keys(doc?.nodes ?? {}).sort(), [doc]);

  /** Severity per code, read off the register nodes. The highest wins, which
   *  is the rule the fold uses when one code is registered twice. */
  const severityByCode = useMemo(() => {
    const out = new Map<string, FindingSeverity>();
    const rank = { info: 0, warning: 1, critical: 2 } as const;
    for (const node of Object.values(doc?.nodes ?? {})) {
      const code2 = node.register?.code;
      const severity = node.register?.severity;
      if (!code2 || !severity) continue;
      const held = out.get(code2);
      if (!held || rank[severity] > rank[held]) out.set(code2, severity);
    }
    return out;
  }, [doc]);

  /** Variable names any `set` node writes, offered to a `vars` reference. */
  const knownVarNames = useMemo(() => {
    const names = new Set<string>();
    for (const node of Object.values(doc?.nodes ?? {})) {
      for (const name of Object.keys(node.set ?? {})) names.add(name);
    }
    return [...names].sort();
  }, [doc]);

  const knownFindingCodes = useMemo(
    () => (findingsQ.data ?? []).filter((f) => !f.shadowed).map((f) => f.code),
    [findingsQ.data],
  );

  // The same rules the compiler runs, run locally on every edit. The remote
  // check is authoritative and overrides this the moment it answers.
  const localRejections: CompileRejection[] = useMemo(
    () => (draftYaml === null ? [] : compileBetaTree({ yaml: draftYaml, knownFindingCodes })),
    [draftYaml, knownFindingCodes],
  );
  const rejections = remoteCompile.data?.rejections ?? localRejections;

  const rejectedNodeIds = useMemo(
    () => new Set(rejections.map((r) => r.node_id).filter((id): id is string => Boolean(id))),
    [rejections],
  );
  const rejectedEdgeKeys = useMemo(
    () => new Set(rejections.map((r) => r.edge_key).filter((k): k is string => Boolean(k))),
    [rejections],
  );

  const readOnly = !canManage;

  const applyYaml = (next: string): void => {
    setDraftYaml(next);
    setDirty(true);
    // A local edit invalidates the last authoritative answer; falling back to
    // the local rules is honest, holding a stale "clean" would not be.
    remoteCompile.reset();
  };

  const onAddNode = (kind: BetaNodeKind): void => {
    if (!pendingAdd || draftYaml === null) return;
    try {
      const result = attachBetaNode(draftYaml, {
        parentId: pendingAdd.parentId,
        slot: pendingAdd.slot,
        kind,
      });
      applyYaml(result.yaml);
      setSelectedNodeId(result.newNodeId);
    } catch (err) {
      setActionError(resolveErrorMessage(err, t("canvas.deleteFailed")));
    }
    setPendingAdd(null);
  };

  const onChangeNode = (node: BetaNode): void => {
    if (!selectedNodeId || draftYaml === null) return;
    applyYaml(setBetaNode(draftYaml, selectedNodeId, node));
  };

  /**
   * Change a node's kind.
   *
   * The new body keeps the labels and, where the kinds agree, the
   * continuation. A new switch takes its default from whatever the old node
   * continued to, so the pre-fill rule holds here as well as on add.
   */
  const onChangeKind = (kind: BetaNodeKind): void => {
    if (!selectedNodeId || draftYaml === null || !doc) return;
    const current = doc.nodes?.[selectedNodeId];
    if (!current || betaNodeKind(current) === kind) return;
    const carriedNext = current.next ?? current.on_match ?? current.switch?.default ?? undefined;
    const next = buildBetaNode(kind, {
      labelEn: current.label_en,
      next: carriedNext,
      defaultGo: carriedNext,
    });
    next.label_ar = current.label_ar;
    applyYaml(setBetaNode(draftYaml, selectedNodeId, next));
  };

  const onDeleteNode = (): void => {
    if (!selectedNodeId || draftYaml === null) return;
    try {
      applyYaml(deleteBetaNode(draftYaml, selectedNodeId).yaml);
      setSelectedNodeId(null);
      setActionError(null);
    } catch (err) {
      setActionError(resolveErrorMessage(err, t("canvas.deleteFailed")));
    }
  };

  const onDeclareCode = (nextCode: string): void => {
    if (draftYaml === null) return;
    applyYaml(writeRegisters(draftYaml, [...declaredCodes, nextCode]));
  };

  const onChangeRules = (next: CombinationRule[]): void => {
    if (draftYaml === null) return;
    applyYaml(writeCombinations(draftYaml, next));
  };

  const onSave = (): void => {
    if (draftYaml === null) return;
    setActionError(null);
    save.mutate(
      { code, tree_yaml: draftYaml },
      {
        onSuccess: () => setDirty(false),
        onError: (err) => setActionError(resolveErrorMessage(err, t("designer.saveFailed"))),
      },
    );
  };

  const onCheck = (): void => {
    if (draftYaml === null) return;
    setActionError(null);
    remoteCompile.mutate(
      { code, tree_yaml: draftYaml },
      { onError: (err) => setActionError(resolveErrorMessage(err, t("publish.failed"))) },
    );
  };

  const onPublish = (): void => {
    const version = treeQ.data?.current_version;
    if (!version) return;
    setActionError(null);
    publish.mutate(
      { code, version },
      { onError: (err) => setActionError(resolveErrorMessage(err, t("designer.publishFailed"))) },
    );
  };

  const onRunDryRun = (): void => {
    if (!blockId || draftYaml === null) return;
    setActionError(null);
    dryRun.mutate(
      { code, payload: { block_id: blockId, tree_yaml: draftYaml } },
      {
        onSuccess: setDryRunResult,
        onError: (err) => setActionError(resolveErrorMessage(err, t("dryRun.failed"))),
      },
    );
  };

  const selectedNode = selectedNodeId ? (doc?.nodes?.[selectedNodeId] ?? null) : null;

  return (
    <Page width="full">
      <AsyncBoundary
        state={queryState(treeQ)}
        errorMessage={t("designer.loadFailed")}
        empty={<EmptyState message={t("designer.loadFailed")} />}
      >
        {(tree) => (
          <>
            <PageHeader
              above={
                <Breadcrumb items={[{ label: t("list.title"), to: base }, { label: tree.code }]} />
              }
              title={localizedField(i18n.language, tree.name_en, tree.name_ar) ?? tree.code}
              badge={<Pill kind="info">{t("beta.badge")}</Pill>}
              subtitle={
                tree.published_version
                  ? t("designer.publishedVersion", { version: tree.published_version })
                  : t("list.notPublished")
              }
              actions={
                <>
                  {dirty ? <Pill kind="warn">{t("designer.unsaved")}</Pill> : null}
                  <Button
                    variant="secondary"
                    onClick={onSave}
                    disabled={readOnly || !dirty || save.isPending}
                  >
                    {save.isPending ? t("designer.saving") : t("designer.save")}
                  </Button>
                </>
              }
            />

            {readOnly ? <StatusBanner kind="info">{t("designer.readOnly")}</StatusBanner> : null}
            {actionError ? <StatusBanner kind="crit">{actionError}</StatusBanner> : null}

            <SegmentedControl<Tab>
              ariaLabel={t("designer.tabs.canvas")}
              value={tab}
              onChange={setTab}
              items={[
                { value: "canvas", label: t("designer.tabs.canvas") },
                { value: "combinations", label: t("designer.tabs.combinations") },
                { value: "dryRun", label: t("designer.tabs.dryRun") },
              ]}
            />

            {tab === "canvas" ? (
              <div className="grid gap-4 xl:grid-cols-[minmax(0,2fr)_minmax(320px,1fr)]">
                <div className="flex flex-col gap-4">
                  <BetaCanvas
                    layout={layout}
                    selectedNodeId={selectedNodeId}
                    onSelectNode={setSelectedNodeId}
                    onAddNode={
                      readOnly ? undefined : (parentId, slot) => setPendingAdd({ parentId, slot })
                    }
                    rejectedNodeIds={rejectedNodeIds}
                    rejectedEdgeKeys={rejectedEdgeKeys}
                    height={canvasHeight}
                    onHeightChange={setCanvasHeight}
                  />
                  <RegistersPanel
                    declaredCodes={declaredCodes}
                    severityByCode={severityByCode}
                    readOnly={readOnly}
                    onRemove={(removed) => {
                      if (draftYaml === null) return;
                      applyYaml(
                        writeRegisters(
                          draftYaml,
                          declaredCodes.filter((c) => c !== removed),
                        ),
                      );
                    }}
                  />
                </div>
                <div className="flex flex-col gap-4">
                  <PublishChecksPanel
                    rejections={rejections}
                    checking={remoteCompile.isPending}
                    publishing={publish.isPending}
                    canPublish={!readOnly && !dirty && Boolean(tree.current_version)}
                    onCheck={onCheck}
                    onPublish={onPublish}
                    onSelectNode={(id) => {
                      setTab("canvas");
                      setSelectedNodeId(id);
                    }}
                  />
                  {selectedNode && selectedNodeId ? (
                    <BetaNodePanel
                      nodeId={selectedNodeId}
                      node={selectedNode}
                      nodeIds={nodeIds}
                      findings={findingsQ.data ?? []}
                      declaredCodes={declaredCodes}
                      knownVarNames={knownVarNames}
                      readOnly={readOnly}
                      onChange={onChangeNode}
                      onChangeKind={onChangeKind}
                      onDeclareCode={onDeclareCode}
                      onDelete={doc?.root === selectedNodeId ? undefined : onDeleteNode}
                    />
                  ) : null}
                </div>
              </div>
            ) : null}

            {tab === "combinations" ? (
              <CombinationsTab
                doc={doc}
                declaredCodes={declaredCodes}
                severityByCode={severityByCode}
                findings={findingsQ.data ?? []}
                rules={rules}
                readOnly={readOnly}
                onChangeRules={onChangeRules}
              />
            ) : null}

            {tab === "dryRun" ? (
              <BetaDryRunPanel
                blocks={queryState(blocksQ)}
                blockId={blockId}
                onBlockChange={setBlockId}
                onRun={onRunDryRun}
                running={dryRun.isPending}
                result={dryRunResult}
              />
            ) : null}

            {pendingAdd ? (
              <Modal
                open
                onClose={() => setPendingAdd(null)}
                labelledBy="beta-add-node-title"
                className="max-w-md"
              >
                <div className="flex flex-col gap-3 p-4">
                  <h2
                    id="beta-add-node-title"
                    className="text-card-title font-semibold text-ap-ink"
                  >
                    {t("canvas.addAfter", { node: pendingAdd.parentId })}
                  </h2>
                  <div className="flex flex-col gap-2">
                    {BETA_NODE_KINDS.map((kind) => (
                      <Button key={kind} variant="secondary" onClick={() => onAddNode(kind)}>
                        {t(`canvas.kind.${kind}`)}
                      </Button>
                    ))}
                  </div>
                </div>
              </Modal>
            ) : null}
          </>
        )}
      </AsyncBoundary>
    </Page>
  );
}

/** The tree's declared findings, with how many nodes register each. A code
 *  declared and never registered is not a rejection, but it is worth seeing. */
function RegistersPanel({
  declaredCodes,
  severityByCode,
  readOnly,
  onRemove,
}: {
  declaredCodes: readonly string[];
  severityByCode: ReadonlyMap<string, FindingSeverity>;
  readOnly: boolean;
  onRemove: (code: string) => void;
}): ReactNode {
  const { t } = useTranslation("decisionTreesBeta");
  return (
    <Card title={t("registers.title")} bodyClassName="flex flex-col gap-2">
      <p className="text-meta text-ap-muted">{t("registers.help")}</p>
      {declaredCodes.length === 0 ? (
        <p className="text-sm text-ap-muted">{t("registers.empty")}</p>
      ) : (
        <ul className="flex flex-wrap gap-2">
          {declaredCodes.map((code) => {
            const severity = severityByCode.get(code);
            return (
              <li
                key={code}
                className="flex items-center gap-2 rounded-lg border border-ap-line px-2.5 py-1.5 text-sm"
              >
                <span dir="ltr" className="font-mono text-xs">
                  {code}
                </span>
                {severity ? (
                  <Pill kind={severity === "critical" ? "crit" : "neutral"}>
                    {t(`severity.${severity}`)}
                  </Pill>
                ) : (
                  <Pill kind="warn">{t("registers.unused")}</Pill>
                )}
                {!readOnly ? (
                  <button
                    type="button"
                    aria-label={t("registers.remove", { code })}
                    onClick={() => onRemove(code)}
                    className="text-ap-muted hover:text-ap-crit"
                  >
                    ×
                  </button>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}
