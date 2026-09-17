/**
 * The beta designer.
 *
 * Same page frame as the current editor — `<Page>`, `<PageHeader>`, a
 * `<Breadcrumb>` above the title, `<Card>` panels, `<AsyncBoundary>` for every
 * read — and the same draft model: the canvas lays out a draft held in
 * component state and structural edits rewrite it.
 *
 * The draft is a YAML string, and that is an editing buffer, not a format.
 * Every helper in `lib/betaTree.ts` takes and returns one, because a text
 * rewrite is how a structural edit stays one pure function. The wire carries
 * JSON: the version row holds a `definition` JSONB column, so the save parses
 * the buffer and posts the object, and the load dumps the object back into a
 * buffer. Nothing between here and the server ever sees YAML.
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
  useBetaDryRun,
  useBetaTree,
  useDiscardBetaDraft,
  useDryRunBlocks,
  useFindingCatalogue,
  usePublishBetaTree,
  useSaveBetaDraft,
} from "@/queries/decisionTreesBeta";
import {
  draftVersion,
  latestVersion,
  readValidationErrors,
  type BetaDryRunResponse,
  type BetaValidationError,
} from "@/api/decisionTreesBeta";

import { useAuthoringScope } from "../../lib/authoringScope";
import { BetaCanvas } from "../components/BetaCanvas";
import { BetaDryRunPanel } from "../components/BetaDryRunPanel";
import { BetaNodePanel } from "../components/BetaNodePanel";
import { CombinationsTab } from "../components/CombinationsTab";
import { PublishChecksPanel } from "../components/PublishChecksPanel";
import { betaEditorHints, type EditorHint } from "../lib/betaCompile";
import { layoutBetaTree } from "../lib/betaLayout";
import type { FindingSeverity } from "../lib/betaConstants";
import {
  BETA_NODE_KINDS,
  attachBetaNode,
  betaNodeKind,
  buildBetaNode,
  deleteBetaNode,
  dumpBetaDoc,
  fillSwitchDefaults,
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
  const findingsQ = useFindingCatalogue(scope);
  const save = useSaveBetaDraft();
  const publish = usePublishBetaTree();
  const discard = useDiscardBetaDraft();
  const dryRun = useBetaDryRun();
  const blocksQ = useDryRunBlocks(scope);

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
  const [confirmDiscard, setConfirmDiscard] = useState(false);
  /**
   * The compiler's answer to the body this screen last sent.
   *
   * Null until a save or a publish has asked. Cleared on the next edit,
   * because the answer was about a body that no longer exists — holding it
   * would either block a publish over a mistake the author has just fixed, or
   * report clean on a body nobody has checked.
   */
  const [serverErrors, setServerErrors] = useState<BetaValidationError[] | null>(null);

  // Hydrate the buffer from the newest version, once per version. The editor
  // always opens on the latest body, published or not. `definition` is JSON;
  // the dump is what makes it editable by the structural helpers.
  const tree = treeQ.data ?? null;
  const treeId = tree?.id ?? "";
  const latest = tree ? latestVersion(tree) : null;
  const draft = tree ? draftVersion(tree) : null;
  useEffect(() => {
    if (!latest) return;
    const stamp = `${code}:${latest.id}:${latest.version}`;
    if (hydratedFrom === stamp) return;
    setHydratedFrom(stamp);
    setDraftYaml(dumpBetaDoc(latest.definition));
    setDirty(false);
    setServerErrors(null);
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

  // Advisory, on every edit. The server decides — see `PublishChecksPanel`.
  const hints: EditorHint[] = useMemo(
    () => (draftYaml === null ? [] : betaEditorHints({ yaml: draftYaml, knownFindingCodes })),
    [draftYaml, knownFindingCodes],
  );

  // The canvas marks a node the server named as well as one a hint named, so
  // a rejection that only the compiler knows about still points somewhere.
  const rejectedNodeIds = useMemo(() => {
    const ids = new Set<string>();
    for (const hint of hints) if (hint.node_id) ids.add(hint.node_id);
    for (const err of serverErrors ?? []) for (const id of err.node_ids) ids.add(id);
    return ids;
  }, [hints, serverErrors]);
  const rejectedEdgeKeys = useMemo(
    () => new Set(hints.map((h) => h.edge_key).filter((k): k is string => Boolean(k))),
    [hints],
  );

  const readOnly = !canManage;

  const applyYaml = (next: string): void => {
    setDraftYaml(next);
    setDirty(true);
    // The compiler's answer was about the previous body. Keeping it would
    // either block a publish over a mistake just fixed, or report clean on a
    // body the server has not seen.
    setServerErrors(null);
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

  /**
   * Sort a failure into the two kinds this screen shows differently.
   *
   * A 422 carries the compiler's errors and belongs in the checks panel,
   * beside the nodes it names. Anything else — a 403, a network failure — is
   * one sentence at the top of the page, because there is no node to go to.
   */
  const handleFailure = (err: unknown, fallback: string): void => {
    const errors = readValidationErrors(err);
    if (errors) {
      setServerErrors(errors);
      setActionError(null);
      setTab("canvas");
      return;
    }
    setActionError(resolveErrorMessage(err, fallback));
  };

  const onSave = (): void => {
    if (draftYaml === null || !treeId) return;
    // Never send a switch with an empty default: the server refuses it, and
    // the author would read a rejection about a field the editor left blank.
    const body = fillSwitchDefaults(draftYaml);
    const definition = parseBetaDoc(body);
    if (!definition) {
      setActionError(t("designer.saveFailed"));
      return;
    }
    setActionError(null);
    setDraftYaml(body);
    save.mutate(
      { code, treeId, definition },
      {
        onSuccess: () => {
          setDirty(false);
          // Cleared, not marked accepted. A save that came back 200 only
          // says the server did not refuse the write; whether it ran the
          // whole check is the publish's answer to give.
          setServerErrors(null);
        },
        onError: (err) => handleFailure(err, t("designer.saveFailed")),
      },
    );
  };

  const onPublish = (): void => {
    if (!treeId || !latest) return;
    setActionError(null);
    publish.mutate(
      { code, treeId, versionId: latest.id },
      {
        onSuccess: () => setServerErrors([]),
        onError: (err) => handleFailure(err, t("designer.publishFailed")),
      },
    );
  };

  /**
   * Remove the draft.
   *
   * Not the same as saving over it. Appending an identical body writes no
   * version, so a draft that will not compile cannot be edited back to the
   * published one — it has to go, or it blocks every later author.
   */
  const onDiscard = (): void => {
    if (!treeId) return;
    setActionError(null);
    discard.mutate(
      { code, treeId },
      {
        onSuccess: () => {
          setConfirmDiscard(false);
          setServerErrors(null);
          setDirty(false);
          // Force a re-hydrate: the version that was on screen is gone.
          setHydratedFrom(null);
        },
        onError: (err) => {
          setConfirmDiscard(false);
          setActionError(resolveErrorMessage(err, t("designer.discardFailed")));
        },
      },
    );
  };

  /** The run walks the stored version, so an unsaved edit would be answered
   *  about the previous body. The panel holds the button and says why. */
  const onRunDryRun = (): void => {
    if (!blockId || !treeId || dirty) return;
    setActionError(null);
    dryRun.mutate(
      { treeId, blockId },
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
                  {draft && !readOnly ? (
                    <Button
                      variant="danger"
                      onClick={() => setConfirmDiscard(true)}
                      disabled={discard.isPending}
                    >
                      {discard.isPending ? t("designer.discarding") : t("designer.discard")}
                    </Button>
                  ) : null}
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
                    errors={serverErrors ?? []}
                    serverState={
                      serverErrors === null
                        ? "unchecked"
                        : serverErrors.length > 0
                          ? "refused"
                          : "accepted"
                    }
                    hints={hints}
                    publishing={publish.isPending}
                    canPublish={!readOnly && !dirty && latest !== null}
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
                platformScope={scope === "platform"}
                dirty={dirty}
              />
            ) : null}

            {confirmDiscard && draft ? (
              <Modal
                open
                onClose={() => setConfirmDiscard(false)}
                labelledBy="beta-discard-title"
                className="max-w-md"
              >
                <div className="flex flex-col gap-3 p-4">
                  <h2 id="beta-discard-title" className="text-card-title font-semibold text-ap-ink">
                    {t("designer.discardTitle", { version: draft.version })}
                  </h2>
                  <p className="text-sm text-ap-ink">{t("designer.discardConfirm")}</p>
                  <p className="text-meta text-ap-muted">{t("designer.discardWhy")}</p>
                  <div className="flex justify-end gap-2">
                    <Button variant="secondary" onClick={() => setConfirmDiscard(false)}>
                      {t("designer.cancel")}
                    </Button>
                    <Button variant="danger" onClick={onDiscard} disabled={discard.isPending}>
                      {discard.isPending ? t("designer.discarding") : t("designer.discard")}
                    </Button>
                  </div>
                </div>
              </Modal>
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
