// Sidebar that surfaces a selected node's data and provides inline
// edit forms for the safe-to-edit fields (PR-D2).
//
// Edit scope:
//   * Decision nodes: label_en / label_ar (the visible explanatory
//     text on the canvas; doesn't affect evaluation).
//   * Leaf nodes: label_en / label_ar + outcome fields (kind,
//     action_type, severity OR confidence depending on kind, text_en,
//     text_ar).
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
import type { LeafOutcomePatch, NodePatch } from "../lib/treeEdit";

interface NodeDetailsPanelProps {
  node: PositionedNode;
  pendingPatch?: NodePatch;
  canEdit: boolean;
  onPatch: (nodeId: string, patch: NodePatch) => void;
  onClearPatch: (nodeId: string) => void;
}

export function NodeDetailsPanel({
  node,
  pendingPatch,
  canEdit,
  onPatch,
  onClearPatch,
}: NodeDetailsPanelProps): JSX.Element {
  const { t } = useTranslation("decisionTrees");
  const [mode, setMode] = useState<"view" | "edit">("view");

  const isLeaf = node.data.outcome !== undefined;
  const hasPending =
    pendingPatch !== undefined && Object.keys(pendingPatch).length > 0;

  return (
    <aside className="flex flex-col gap-3 rounded-xl border border-ap-line bg-ap-panel p-4">
      <header className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="font-mono text-xs text-ap-muted">{t("editor.panel.nodeId")}</p>
          <p className="break-all font-mono text-sm font-semibold text-ap-ink">
            {node.id}
          </p>
        </div>
        {canEdit ? (
          <button
            type="button"
            onClick={() =>
              setMode((current) => (current === "view" ? "edit" : "view"))
            }
            className="shrink-0 rounded-md border border-ap-line bg-ap-bg/60 px-2 py-1 text-xs font-medium text-ap-ink hover:bg-ap-bg"
          >
            {mode === "view" ? t("editor.panel.edit") : t("editor.panel.done")}
          </button>
        ) : null}
      </header>

      <KeyValue label={t("editor.panel.role")} value={roleLabel(node.role, t)} />

      <LabelsSection
        node={node}
        mode={mode}
        pendingPatch={pendingPatch}
        onPatch={onPatch}
      />

      {isLeaf ? (
        <LeafOutcomeSection
          node={node}
          mode={mode}
          pendingPatch={pendingPatch}
          onPatch={onPatch}
        />
      ) : (
        <DecisionConditionSection node={node} />
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
    </aside>
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

function DecisionConditionSection({ node }: { node: PositionedNode }): ReactNode {
  const { t } = useTranslation("decisionTrees");
  const condition = (node.data as { condition?: unknown }).condition;
  return (
    <Section title={t("editor.panel.condition.heading")}>
      <p className="text-xs text-ap-muted">
        {t("editor.panel.condition.deferredNote")}
      </p>
      <pre className="max-h-64 overflow-auto rounded bg-ap-bg/60 p-2 text-[11px] leading-relaxed text-ap-ink">
        {JSON.stringify(condition, null, 2)}
      </pre>
      <KeyValue
        label={t("editor.panel.condition.onMatch")}
        value={
          (node.data as { on_match?: string }).on_match ?? "—"
        }
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
  const outcome = node.data.outcome ?? {};
  const pending: LeafOutcomePatch = pendingPatch?.outcome ?? {};
  // The compiled-node outcome has `kind: string` (looser than the
  // patch's `"alert" | "recommendation"`); narrow at the boundary
  // here so the form fields below get a stable union type.
  const rawKind = pending.kind ?? outcome.kind;
  const kind: "recommendation" | "alert" = rawKind === "alert" ? "alert" : "recommendation";
  const effective: {
    action_type?: string;
    severity?: string;
    confidence?: number | string;
    text_en?: string;
    text_ar?: string | null;
  } = {
    action_type: pending.action_type ?? outcome.action_type,
    severity: pending.severity ?? outcome.severity,
    confidence: pending.confidence ?? outcome.confidence,
    text_en: pending.text_en ?? outcome.text_en,
    text_ar: pending.text_ar ?? outcome.text_ar,
  };

  if (mode === "view") {
    return (
      <Section title={t("editor.panel.outcome.heading")}>
        <KeyValue label={t("editor.panel.outcome.kind")} value={kind} mono />
        <KeyValue
          label={t("editor.panel.outcome.actionType")}
          value={effective.action_type ?? "—"}
          mono
        />
        {kind === "alert" ? (
          <KeyValue
            label={t("editor.panel.outcome.severity")}
            value={effective.severity ?? "—"}
            mono
          />
        ) : (
          <KeyValue
            label={t("editor.panel.outcome.confidence")}
            value={
              effective.confidence !== undefined
                ? String(effective.confidence)
                : "—"
            }
            mono
          />
        )}
        <KeyValue
          label={t("editor.panel.outcome.textEn")}
          value={effective.text_en ?? "—"}
        />
        <KeyValue
          label={t("editor.panel.outcome.textAr")}
          value={effective.text_ar ?? "—"}
          dir="rtl"
        />
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
          { value: "recommendation", label: t("viewer.legend.recommendation") },
          { value: "alert", label: t("viewer.legend.alert") },
        ]}
        onChange={(v) => updateOutcome({ kind: v as "recommendation" | "alert" })}
      />
      <TextField
        label={t("editor.panel.outcome.actionType")}
        value={effective.action_type ?? ""}
        onChange={(v) => updateOutcome({ action_type: v })}
      />
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
      ) : (
        <NumberField
          label={t("editor.panel.outcome.confidence")}
          value={typeof effective.confidence === "number" ? effective.confidence : 0.5}
          min={0}
          max={1}
          step={0.05}
          onChange={(v) => updateOutcome({ confidence: v })}
        />
      )}
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
    </Section>
  );
}

// ---- Atoms ---------------------------------------------------------

function Section({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}): JSX.Element {
  return (
    <div className="flex flex-col gap-2 border-t border-ap-line pt-3">
      <p className="text-xs font-semibold uppercase tracking-wide text-ap-muted">
        {title}
      </p>
      {children}
    </div>
  );
}

function KeyValue({
  label,
  value,
  mono,
  dir,
}: {
  label: string;
  value: string;
  mono?: boolean;
  dir?: "rtl";
}): JSX.Element {
  return (
    <div className="grid grid-cols-[120px_1fr] gap-2 text-xs">
      <span className="text-ap-muted">{label}</span>
      <span
        className={mono ? "break-all font-mono text-ap-ink" : "text-ap-ink"}
        dir={dir}
      >
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

function roleLabel(role: PositionedNode["role"], t: ReturnType<typeof useTranslation>["t"]): string {
  switch (role) {
    case "leaf-alert":
      return t("viewer.legend.alert");
    case "leaf-recommendation":
      return t("viewer.legend.recommendation");
    case "leaf-noop":
      return t("viewer.legend.noop");
    case "decision":
    default:
      return t("viewer.legend.decision");
  }
}
