// Sidebar that surfaces a selected node's data and provides inline
// edit forms for the safe-to-edit fields (PR-D2).
//
// Edit scope:
//   * Decision nodes: label_en / label_ar (the visible explanatory
//     text on the canvas; doesn't affect evaluation).
//   * Leaf nodes: label_en / label_ar + outcome fields. A leaf is one
//     of four kinds — alert, recommendation, status, no_action — and the
//     kind decides which fields mean anything: alert takes a severity,
//     recommendation a confidence, status a status code, and no_action
//     none of them.
//
// NOT editable from this panel (deferred to a follow-up PR or kept in
// the YAML editor):
//   * Condition trees on decision nodes — render as a JSON code
//     block, read-only. The condition-builder UX is substantial and
//     warrants its own design pass.
//   * on_match / on_miss pointers — would need a node-id picker.
//   * outcome.parameters (the $params ref dict structure from PR-B) —
//     surfaced as a JSON block; tenant-side parameter overrides go
//     through the PR-C settings UI (built in PR-D3).
//   * Adding / deleting nodes — needs a node-id-uniqueness UX.

import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { PositionedNode } from "../layout/treeLayout";
import type { LeafKind, LeafOutcomePatch, NodePatch } from "../lib/treeEdit";
import { parseConditionTree } from "../lib/conditionEdit";
import { ConditionBuilder } from "./ConditionBuilder";
import { Card } from "@/components/Card";
import { ACTION_TYPES } from "@/lib/actionTypes";
import { useVerdictStatuses } from "@/lib/verdictStatuses";

interface NodeDetailsPanelProps {
  node: PositionedNode;
  pendingPatch?: NodePatch;
  canEdit: boolean;
  /** True when this node is the tree's root. Disables Delete because
   *  the root has no parent to clean up after removal. */
  isRoot?: boolean;
  onPatch: (nodeId: string, patch: NodePatch) => void;
  onClearPatch: (nodeId: string) => void;
  /** PR-D4: delete this node + its subtree. Caller surfaces the
   *  confirm dialog. */
  onDelete?: (nodeId: string) => void;
  /** PR-D4: add a child under one of this decision's empty branches.
   *  Caller surfaces the kind-picker. */
  onAddChild?: (parentId: string, branch: "match" | "miss") => void;
  /** PR-D5: rewrite this decision's condition.tree. Caller commits the
   *  change to the draft YAML and re-validates. */
  onConditionChange?: (nodeId: string, nextTree: unknown) => void;
  /** The tree's targeted crop paths. The condition builder uses them to
   *  offer only the crop attributes and risk models that can actually
   *  resolve for the blocks this tree runs on. */
  cropPaths?: string[];
  /** Parameter names the tree declares — completions for a params ref. */
  paramNames?: string[];
}

export function NodeDetailsPanel({
  node,
  pendingPatch,
  canEdit,
  isRoot = false,
  onPatch,
  onClearPatch,
  onDelete,
  onAddChild,
  onConditionChange,
  cropPaths,
  paramNames,
}: NodeDetailsPanelProps): JSX.Element {
  const { t } = useTranslation("decisionTrees");
  const [mode, setMode] = useState<"view" | "edit">("view");

  const isLeaf = node.data.outcome !== undefined;
  const hasPending = pendingPatch !== undefined && Object.keys(pendingPatch).length > 0;
  // Add-child buttons surface for decision nodes with empty branches.
  const canAddMatch =
    !isLeaf &&
    canEdit &&
    onAddChild !== undefined &&
    !(node.data as { on_match?: string }).on_match;
  const canAddMiss =
    !isLeaf && canEdit && onAddChild !== undefined && !(node.data as { on_miss?: string }).on_miss;

  return (
    <Card noPadding className="flex flex-col gap-3 overflow-hidden p-4">
      <header className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="font-mono text-xs text-ap-muted">{t("editor.panel.nodeId")}</p>
          <p className="break-all font-mono text-sm font-semibold text-ap-ink">{node.id}</p>
        </div>
        {canEdit ? (
          <button
            type="button"
            onClick={() => setMode((current) => (current === "view" ? "edit" : "view"))}
            className="shrink-0 rounded-md border border-ap-line bg-ap-bg/60 px-2 py-1 text-xs font-medium text-ap-ink hover:bg-ap-bg"
          >
            {mode === "view" ? t("editor.panel.edit") : t("editor.panel.done")}
          </button>
        ) : null}
      </header>

      <KeyValue label={t("editor.panel.role")} value={roleLabel(node.role, t)} />

      <LabelsSection node={node} mode={mode} pendingPatch={pendingPatch} onPatch={onPatch} />

      {isLeaf ? (
        <LeafOutcomeSection node={node} mode={mode} pendingPatch={pendingPatch} onPatch={onPatch} />
      ) : (
        <DecisionConditionSection
          node={node}
          mode={mode}
          canEdit={canEdit}
          onConditionChange={onConditionChange}
          cropPaths={cropPaths}
          paramNames={paramNames}
        />
      )}

      {hasPending ? (
        <div className="flex items-center justify-between gap-2 border-t border-ap-line pt-3 text-xs">
          <span className="text-ap-muted">{t("editor.panel.pendingNote")}</span>
          <button
            type="button"
            onClick={() => onClearPatch(node.id)}
            className="text-ap-crit hover:underline"
          >
            {t("editor.panel.discardNode")}
          </button>
        </div>
      ) : null}

      {/* PR-D4: structural actions. Always rendered (when canEdit) so
       *  the author can see *where* add/delete live — even if a given
       *  node has no applicable add target. We surface contextual
       *  hints in place of buttons when an action isn't available.
       */}
      {canEdit ? (
        <div className="flex flex-col gap-2 border-t border-ap-line pt-3 text-xs">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-ap-muted">
            {t("editor.panel.actions")}
          </p>
          {!isLeaf ? (
            canAddMatch || canAddMiss ? (
              <div className="flex flex-wrap gap-2">
                {canAddMatch ? (
                  <button
                    type="button"
                    onClick={() => onAddChild(node.id, "match")}
                    className="rounded-md border border-ap-line bg-ap-bg/60 px-2 py-1 font-medium text-ap-ink hover:bg-ap-bg"
                  >
                    {t("editor.panel.addMatch")}
                  </button>
                ) : null}
                {canAddMiss ? (
                  <button
                    type="button"
                    onClick={() => onAddChild(node.id, "miss")}
                    className="rounded-md border border-ap-line bg-ap-bg/60 px-2 py-1 font-medium text-ap-ink hover:bg-ap-bg"
                  >
                    {t("editor.panel.addMiss")}
                  </button>
                ) : null}
              </div>
            ) : (
              <p className="text-ap-muted">{t("editor.panel.branchesFilledHint")}</p>
            )
          ) : null}
          {onDelete ? (
            <button
              type="button"
              disabled={isRoot}
              onClick={() => onDelete(node.id)}
              title={isRoot ? t("editor.panel.deleteRootBlocked") : undefined}
              className="self-start rounded-md border border-ap-crit/40 px-2 py-1 font-medium text-ap-crit hover:bg-ap-crit/10 disabled:opacity-50 disabled:hover:bg-transparent"
            >
              {t("editor.panel.deleteNode")}
            </button>
          ) : null}
          {isRoot ? <p className="text-ap-muted">{t("editor.panel.deleteRootBlocked")}</p> : null}
        </div>
      ) : null}
    </Card>
  );
}

// ---- Subcomponents -------------------------------------------------

function LabelsSection({
  node,
  mode,
  pendingPatch,
  onPatch,
}: {
  node: PositionedNode;
  mode: "view" | "edit";
  pendingPatch?: NodePatch;
  onPatch: (nodeId: string, patch: NodePatch) => void;
}): ReactNode {
  const { t } = useTranslation("decisionTrees");
  const labelEn = pendingPatch?.label_en ?? node.data.label_en ?? "";
  const labelAr = pendingPatch?.label_ar ?? node.data.label_ar ?? "";

  if (mode === "view") {
    return (
      <Section title={t("editor.panel.labels.heading")}>
        <KeyValue label={t("editor.panel.labels.en")} value={labelEn || "—"} />
        <KeyValue label={t("editor.panel.labels.ar")} value={labelAr || "—"} dir="rtl" />
      </Section>
    );
  }
  return (
    <Section title={t("editor.panel.labels.heading")}>
      <TextField
        label={t("editor.panel.labels.en")}
        value={labelEn}
        onChange={(v) => onPatch(node.id, { label_en: v })}
      />
      <TextField
        label={t("editor.panel.labels.ar")}
        value={labelAr}
        dir="rtl"
        onChange={(v) => onPatch(node.id, { label_ar: v })}
      />
    </Section>
  );
}

function DecisionConditionSection({
  node,
  mode,
  canEdit,
  onConditionChange,
  cropPaths,
  paramNames,
}: {
  node: PositionedNode;
  mode: "view" | "edit";
  canEdit: boolean;
  onConditionChange?: (nodeId: string, nextTree: unknown) => void;
  cropPaths?: string[];
  /** Parameter names the tree declares — completions for a params ref. */
  paramNames?: string[];
}): ReactNode {
  const { t } = useTranslation("decisionTrees");
  const condition = (node.data as { condition?: { tree?: unknown } }).condition;
  const tree = condition?.tree;
  const editable = parseConditionTree(tree);
  // Builder edits flow back through the host page's
  // `applySetNodeCondition` helper; here we just adapt the prop.
  const handleChange = (next: unknown): void => {
    onConditionChange?.(node.id, next);
  };
  return (
    <Section title={t("editor.panel.condition.heading")}>
      {mode === "edit" && canEdit && onConditionChange ? (
        <ConditionBuilder
          value={editable}
          onChange={handleChange}
          cropPaths={cropPaths}
          paramNames={paramNames}
        />
      ) : (
        <>
          {editable.kind === "unsupported" ? (
            <p className="text-xs text-ap-muted">{t("editor.panel.condition.unsupportedNote")}</p>
          ) : null}
          <ConditionBuilder
            value={editable}
            onChange={() => {}}
            cropPaths={cropPaths}
            paramNames={paramNames}
            readOnly
          />
        </>
      )}
      <KeyValue
        label={t("editor.panel.condition.onMatch")}
        value={(node.data as { on_match?: string }).on_match ?? "—"}
        mono
      />
      <KeyValue
        label={t("editor.panel.condition.onMiss")}
        value={(node.data as { on_miss?: string }).on_miss ?? "—"}
        mono
      />
    </Section>
  );
}

function LeafOutcomeSection({
  node,
  mode,
  pendingPatch,
  onPatch,
}: {
  node: PositionedNode;
  mode: "view" | "edit";
  pendingPatch?: NodePatch;
  onPatch: (nodeId: string, patch: NodePatch) => void;
}): ReactNode {
  const { t } = useTranslation("decisionTrees");
  const statuses = useVerdictStatuses();
  const outcome = node.data.outcome ?? {};
  const pending: LeafOutcomePatch = pendingPatch?.outcome ?? {};
  // The compiled-node outcome types `kind` as a plain string, and a tree
  // published before the four kinds existed carries no `kind` at all — it
  // says `action_type: no_action` instead. Read both spellings here, the
  // same way the loader and the engine do, or every one of those leaves
  // would show as a recommendation in the editor.
  const rawKind = pending.kind ?? outcome.kind;
  const kind: LeafKind = ((): LeafKind => {
    if (rawKind === "alert" || rawKind === "status") return rawKind;
    if ((pending.action_type ?? outcome.action_type) === "no_action") return "no_action";
    if (rawKind === "recommendation" || rawKind === "no_action") return rawKind;
    return "recommendation";
  })();
  const asksForWork = kind === "alert" || kind === "recommendation";
  const effective: {
    action_type?: string;
    status?: string;
    severity?: string;
    confidence?: number | string;
    text_en?: string | null;
    text_ar?: string | null;
  } = {
    action_type: pending.action_type ?? outcome.action_type,
    status: pending.status ?? outcome.status,
    severity: pending.severity ?? outcome.severity,
    confidence: pending.confidence ?? outcome.confidence,
    text_en: pending.text_en ?? outcome.text_en,
    text_ar: pending.text_ar ?? outcome.text_ar,
  };
  const statusCode = effective.status ?? "good";
  const statusOf = statuses.find((s) => s.code === statusCode);

  if (mode === "view") {
    return (
      <Section title={t("editor.panel.outcome.heading")}>
        <KeyValue label={t("editor.panel.outcome.kind")} value={t(`leafKind.${kind}`)} />
        {kind === "status" ? (
          <KeyValue
            label={t("editor.panel.outcome.status")}
            value={statusOf ? statusOf.label_en : statusCode}
            swatch={statusOf?.color}
          />
        ) : null}
        {asksForWork ? (
          <KeyValue
            label={t("editor.panel.outcome.actionType")}
            value={effective.action_type ?? "—"}
            mono
          />
        ) : null}
        {kind === "alert" ? (
          <KeyValue
            label={t("editor.panel.outcome.severity")}
            value={effective.severity ?? "—"}
            mono
          />
        ) : null}
        {kind === "recommendation" ? (
          <KeyValue
            label={t("editor.panel.outcome.confidence")}
            value={effective.confidence !== undefined ? String(effective.confidence) : "—"}
            mono
          />
        ) : null}
        {kind === "no_action" ? (
          <p className="text-xs text-ap-muted">{t("editor.panel.outcome.noActionHint")}</p>
        ) : (
          <>
            <KeyValue label={t("editor.panel.outcome.textEn")} value={effective.text_en ?? "—"} />
            <KeyValue
              label={t("editor.panel.outcome.textAr")}
              value={effective.text_ar ?? "—"}
              dir="rtl"
            />
          </>
        )}
      </Section>
    );
  }

  const updateOutcome = (patch: LeafOutcomePatch): void => {
    onPatch(node.id, { outcome: patch });
  };
  return (
    <Section title={t("editor.panel.outcome.heading")}>
      <SelectField
        label={t("editor.panel.outcome.kind")}
        value={kind}
        options={[
          { value: "alert", label: t("leafKind.alert") },
          { value: "recommendation", label: t("leafKind.recommendation") },
          { value: "status", label: t("leafKind.status") },
          { value: "no_action", label: t("leafKind.no_action") },
        ]}
        onChange={(v) => updateOutcome({ kind: v as LeafKind })}
      />
      <p className="text-xs text-ap-muted">{t(`leafKindHint.${kind}`)}</p>
      {kind === "status" ? (
        <>
          <SelectField
            label={t("editor.panel.outcome.status")}
            value={statusCode}
            options={statuses.map((s) => ({ value: s.code, label: s.label_en }))}
            onChange={(v) => updateOutcome({ status: v })}
          />
          {/* The colour is the platform's, not the author's. Showing it here
              is what stops "good" and "issue" being picked by feel. */}
          {statusOf ? (
            <div className="flex items-center gap-2 text-xs text-ap-muted">
              <span
                className="inline-block h-3 w-3 rounded-sm border border-ap-line"
                style={{ backgroundColor: statusOf.color }}
                aria-hidden
              />
              <span>{t("editor.panel.outcome.statusColorHint")}</span>
            </div>
          ) : null}
        </>
      ) : null}
      {/* Was a free-text box sitting between two dropdowns. `action_type` is a
          closed set enforced by a CHECK constraint at persist time, so a typo
          here saved and published cleanly and then 500'd when a tree actually
          fired. The vocabulary is shared with the Action Center. */}
      {asksForWork ? (
        <SelectField
          label={t("editor.panel.outcome.actionType")}
          value={effective.action_type ?? ""}
          options={[
            { value: "", label: t("editor.panel.outcome.actionTypeUnset") },
            ...ACTION_TYPES.filter((a) => a !== "no_action").map((a) => ({
              value: a,
              label: t(`actionType.${a}`, { ns: "actionCenter", defaultValue: a }),
            })),
          ]}
          onChange={(v) => updateOutcome({ action_type: v })}
        />
      ) : null}
      {kind === "alert" ? (
        <SelectField
          label={t("editor.panel.outcome.severity")}
          value={effective.severity ?? "info"}
          options={[
            { value: "info", label: "info" },
            { value: "warning", label: "warning" },
            { value: "critical", label: "critical" },
          ]}
          onChange={(v) => updateOutcome({ severity: v })}
        />
      ) : null}
      {kind === "recommendation" ? (
        <NumberField
          label={t("editor.panel.outcome.confidence")}
          value={typeof effective.confidence === "number" ? effective.confidence : 0.5}
          min={0}
          max={1}
          step={0.05}
          onChange={(v) => updateOutcome({ confidence: v })}
        />
      ) : null}
      {kind === "no_action" ? (
        <p className="text-xs text-ap-muted">{t("editor.panel.outcome.noActionHint")}</p>
      ) : (
        <>
          <TextField
            label={t("editor.panel.outcome.textEn")}
            value={effective.text_en ?? ""}
            multiline
            onChange={(v) => updateOutcome({ text_en: v })}
          />
          <TextField
            label={t("editor.panel.outcome.textAr")}
            value={effective.text_ar ?? ""}
            dir="rtl"
            multiline
            onChange={(v) => updateOutcome({ text_ar: v || null })}
          />
        </>
      )}
    </Section>
  );
}

// ---- Atoms ---------------------------------------------------------

function Section({ title, children }: { title: string; children: ReactNode }): JSX.Element {
  return (
    <div className="flex flex-col gap-2 border-t border-ap-line pt-3">
      <p className="text-xs font-semibold uppercase tracking-wide text-ap-muted">{title}</p>
      {children}
    </div>
  );
}

function KeyValue({
  label,
  value,
  mono,
  dir,
  swatch,
}: {
  label: string;
  value: string;
  mono?: boolean;
  dir?: "rtl";
  /** A colour to show beside the value. Used for a status code, where the
   *  colour is half of what the reader is being told. */
  swatch?: string;
}): JSX.Element {
  return (
    <div className="grid grid-cols-[120px_1fr] gap-2 text-xs">
      <span className="text-ap-muted">{label}</span>
      <span
        className={mono ? "break-all font-mono text-ap-ink" : "text-ap-ink"}
        dir={dir}
      >
        {swatch ? (
          <span
            className="mr-1.5 inline-block h-2.5 w-2.5 rounded-sm border border-ap-line align-middle"
            style={{ backgroundColor: swatch }}
            aria-hidden
          />
        ) : null}
        {value}
      </span>
    </div>
  );
}

function TextField({
  label,
  value,
  onChange,
  multiline,
  dir,
}: {
  label: string;
  value: string;
  onChange: (next: string) => void;
  multiline?: boolean;
  dir?: "rtl";
}): JSX.Element {
  return (
    <label className="flex flex-col gap-1 text-xs">
      <span className="text-ap-muted">{label}</span>
      {multiline ? (
        <textarea
          value={value}
          onChange={(e) => onChange(e.target.value)}
          dir={dir}
          rows={3}
          className="rounded-md border border-ap-line bg-ap-bg/40 px-2 py-1 text-sm text-ap-ink"
        />
      ) : (
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          dir={dir}
          className="rounded-md border border-ap-line bg-ap-bg/40 px-2 py-1 text-sm text-ap-ink"
        />
      )}
    </label>
  );
}

function NumberField({
  label,
  value,
  min,
  max,
  step,
  onChange,
}: {
  label: string;
  value: number;
  min?: number;
  max?: number;
  step?: number;
  onChange: (next: number) => void;
}): JSX.Element {
  return (
    <label className="flex flex-col gap-1 text-xs">
      <span className="text-ap-muted">{label}</span>
      <input
        type="number"
        value={value}
        min={min}
        max={max}
        step={step}
        onChange={(e) => {
          const next = Number(e.target.value);
          if (!Number.isNaN(next)) onChange(next);
        }}
        className="rounded-md border border-ap-line bg-ap-bg/40 px-2 py-1 text-sm text-ap-ink"
      />
    </label>
  );
}

function SelectField({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: Array<{ value: string; label: string }>;
  onChange: (next: string) => void;
}): JSX.Element {
  return (
    <label className="flex flex-col gap-1 text-xs">
      <span className="text-ap-muted">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-md border border-ap-line bg-ap-bg/40 px-2 py-1 text-sm text-ap-ink"
      >
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    </label>
  );
}

function roleLabel(
  role: PositionedNode["role"],
  t: ReturnType<typeof useTranslation>["t"],
): string {
  switch (role) {
    case "leaf-alert":
      return t("viewer.legend.alert");
    case "leaf-recommendation":
      return t("viewer.legend.recommendation");
    case "leaf-status":
      return t("leafKind.status");
    case "leaf-noop":
      return t("viewer.legend.noop");
    case "decision":
    default:
      return t("viewer.legend.decision");
  }
}
