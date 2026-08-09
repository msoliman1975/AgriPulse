// Visual condition builder for the NodeDetailsPanel.
//
// Renders the condition AST recursively, so nested all_of / any_of
// groups, NOT wrappers, `between` ranges and `in` value lists are all
// editable here. Previously any of those dropped the author into a
// read-only JSON blob with a "use the YAML editor" hint; the engine has
// supported them since day one, and since decision trees became a
// top-level tenant surface that fallback was a visible dead end.
//
// Edits apply eagerly to the parent's draft YAML (via `onChange`) so the
// structural validator + canvas re-layout reflect the change
// immediately.

import { useTranslation } from "react-i18next";
import { type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";

import { listCropAttributeCatalog } from "@/api/crops";
import { listSignalDefinitions } from "@/api/signals";
import {
  BLOCK_FIELDS,
  CROP_ATTRIBUTE_KEYS,
  GRID_FIELDS,
  INDEX_CODES,
  INDICES_KEYS,
  MAX_GROUP_DEPTH,
  SIGNAL_KEYS,
  TERM_OPS,
  WEATHER_FIELDS,
  WEATHER_INDEX_CODES,
  WEATHER_INDEX_KEYS,
  WEATHER_RISK_CODES,
  WEATHER_RISK_CROP_PREFIX,
  WEATHER_RISK_FIELDS,
  WEATHER_SCOPES,
  attributePathAppliesToCrops,
  changeTermOp,
  defaultGroupNode,
  defaultTermNode,
  defaultValueRef,
  leftOperandType,
  leftOperandValues,
  retypeTermForLeft,
  riskAppliesToCrops,
  serializeNode,
  signalKeysForValueKind,
  type ConditionNode,
  type EditableCondition,
  type GroupMode,
  type RightOperand,
  type Term,
  type TermOp,
  type ValueRef,
  type ValueRefSource,
} from "../lib/conditionEdit";

interface ConditionBuilderProps {
  value: EditableCondition;
  /** The tree's targeted crop paths, when the host knows them. Used to hide
   *  crop attributes and risk models that can never resolve for the blocks
   *  this tree runs on. */
  cropPaths?: string[];
  /** Fires with the new condition AST ready to be written back to
   *  YAML (`condition.tree`). Caller serializes + persists. */
  onChange: (nextTree: unknown) => void;
  readOnly?: boolean;
}

export function ConditionBuilder({
  value,
  onChange,
  cropPaths = [],
  readOnly = false,
}: ConditionBuilderProps): ReactNode {
  const { t } = useTranslation("decisionTrees");

  if (value.kind === "unsupported") {
    return (
      <div className="rounded-md border border-ap-warn/40 bg-ap-warn/5 p-2 text-xs">
        <p className="font-medium text-ap-warn">{t("editor.condition.unsupportedHeading")}</p>
        <p className="mt-1 text-ap-ink">{value.reason}</p>
        <pre className="mt-2 max-h-48 overflow-auto rounded bg-ap-bg/60 p-2 text-[11px] leading-relaxed text-ap-ink">
          {JSON.stringify(value.raw, null, 2)}
        </pre>
      </div>
    );
  }

  const emit = (next: ConditionNode | null): void => {
    onChange(next ? serializeNode(next) : undefined);
  };

  const root = value.kind === "node" ? value.node : null;

  if (!root) {
    return (
      <div className="flex flex-col gap-2 text-xs">
        <p className="text-ap-muted">{t("editor.condition.empty")}</p>
        {!readOnly ? (
          <div className="flex flex-wrap gap-2">
            <AddButton
              label={t("editor.condition.addTerm")}
              onClick={() => emit(defaultTermNode())}
            />
            <AddButton
              label={t("editor.condition.addGroup")}
              onClick={() => emit(defaultGroupNode())}
            />
          </div>
        ) : null}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2 text-xs">
      <NodeEditor node={root} depth={0} readOnly={readOnly} cropPaths={cropPaths} onChange={emit} />
      {/* A bare term or NOT at the root has nowhere to put a sibling, so
          offer to wrap it in a group rather than making the author
          rebuild the condition from scratch. */}
      {!readOnly && root.kind !== "group" ? (
        <AddButton
          label={t("editor.condition.addTerm")}
          onClick={() => emit({ kind: "group", mode: "all", children: [root, defaultTermNode()] })}
        />
      ) : null}
    </div>
  );
}

// ---- Recursive node editor -----------------------------------------

interface NodeEditorProps {
  node: ConditionNode;
  depth: number;
  readOnly: boolean;
  cropPaths: string[];
  /** `null` means "remove me". */
  onChange: (next: ConditionNode | null) => void;
  onRemove?: () => void;
}

function NodeEditor({
  node,
  depth,
  readOnly,
  cropPaths,
  onChange,
  onRemove,
}: NodeEditorProps): ReactNode {
  if (node.kind === "term") {
    return (
      <TermRow
        term={node.term}
        readOnly={readOnly}
        cropPaths={cropPaths}
        onChange={(term) => onChange({ kind: "term", term })}
        onRemove={onRemove}
      />
    );
  }
  if (node.kind === "not") {
    return (
      <NotBox
        node={node}
        depth={depth}
        readOnly={readOnly}
        cropPaths={cropPaths}
        onChange={onChange}
        onRemove={onRemove}
      />
    );
  }
  return (
    <GroupBox
      node={node}
      depth={depth}
      readOnly={readOnly}
      cropPaths={cropPaths}
      onChange={onChange}
      onRemove={onRemove}
    />
  );
}

function GroupBox({
  node,
  depth,
  readOnly,
  cropPaths,
  onChange,
  onRemove,
}: {
  node: Extract<ConditionNode, { kind: "group" }>;
  depth: number;
  readOnly: boolean;
  cropPaths: string[];
  onChange: (next: ConditionNode | null) => void;
  onRemove?: () => void;
}): ReactNode {
  const { t } = useTranslation("decisionTrees");

  const replaceChild = (idx: number, next: ConditionNode | null): void => {
    const children = next
      ? node.children.map((c, i) => (i === idx ? next : c))
      : node.children.filter((_, i) => i !== idx);
    // An empty group is not a meaningful condition — drop the group
    // itself rather than leaving an `all_of: []` behind.
    if (children.length === 0) {
      onChange(null);
      return;
    }
    onChange({ ...node, children });
  };

  const append = (child: ConditionNode): void => {
    onChange({ ...node, children: [...node.children, child] });
  };

  return (
    <div className="rounded-md border border-ap-line bg-ap-bg/30 p-2">
      <div className="flex items-center gap-2">
        <span className="text-ap-muted">{t("editor.condition.match")}</span>
        <select
          disabled={readOnly}
          value={node.mode}
          onChange={(e) => onChange({ ...node, mode: e.target.value as GroupMode })}
          className="rounded-md border border-ap-line bg-white px-2 py-1 text-xs"
          aria-label={t("editor.condition.match")}
        >
          <option value="all">{t("editor.condition.modeAll")}</option>
          <option value="any">{t("editor.condition.modeAny")}</option>
        </select>
        {onRemove && !readOnly ? (
          <RemoveButton label={t("editor.condition.removeGroup")} onClick={onRemove} />
        ) : null}
      </div>

      <div className="mt-2 flex flex-col gap-2 border-s-2 border-ap-line ps-2">
        {node.children.map((child, idx) => (
          <NodeEditor
            key={idx}
            node={child}
            depth={depth + 1}
            readOnly={readOnly}
            cropPaths={cropPaths}
            onChange={(next) => replaceChild(idx, next)}
            onRemove={() => replaceChild(idx, null)}
          />
        ))}
      </div>

      {!readOnly ? (
        <div className="mt-2 flex flex-wrap gap-2">
          <AddButton
            label={t("editor.condition.addTerm")}
            onClick={() => append(defaultTermNode())}
          />
          {depth + 1 < MAX_GROUP_DEPTH ? (
            <AddButton
              label={t("editor.condition.addGroup")}
              onClick={() => append(defaultGroupNode(node.mode === "all" ? "any" : "all"))}
            />
          ) : null}
          <AddButton
            label={t("editor.condition.addNot")}
            onClick={() => append({ kind: "not", child: defaultTermNode() })}
          />
        </div>
      ) : null}
    </div>
  );
}

function NotBox({
  node,
  depth,
  readOnly,
  cropPaths,
  onChange,
  onRemove,
}: {
  node: Extract<ConditionNode, { kind: "not" }>;
  depth: number;
  readOnly: boolean;
  cropPaths: string[];
  onChange: (next: ConditionNode | null) => void;
  onRemove?: () => void;
}): ReactNode {
  const { t } = useTranslation("decisionTrees");
  return (
    <div className="rounded-md border border-ap-warn/40 bg-ap-warn/5 p-2">
      <div className="flex items-center gap-2">
        <span className="rounded bg-ap-warn/20 px-1.5 py-0.5 font-mono text-[11px] font-medium text-ap-warn">
          {t("editor.condition.notLabel")}
        </span>
        {onRemove && !readOnly ? (
          <RemoveButton label={t("editor.condition.removeNot")} onClick={onRemove} />
        ) : null}
      </div>
      <div className="mt-2">
        <NodeEditor
          node={node.child}
          depth={depth + 1}
          readOnly={readOnly}
          cropPaths={cropPaths}
          // Removing the inner node removes the whole NOT — a NOT with
          // nothing under it has no meaning.
          onChange={(next) => onChange(next ? { kind: "not", child: next } : null)}
        />
      </div>
    </div>
  );
}

// ---- Term row ------------------------------------------------------

interface TermRowProps {
  term: Term;
  readOnly: boolean;
  cropPaths: string[];
  onChange: (next: Term) => void;
  onRemove?: () => void;
}

function TermRow({ term, readOnly, cropPaths, onChange, onRemove }: TermRowProps): ReactNode {
  const { t } = useTranslation("decisionTrees");
  // The node details panel is a fixed, narrow (~360px) column, so the
  // comparison fields stack vertically. A previous `sm:grid-cols-[…]`
  // 4-column layout keyed off the *viewport* width (≥640px), not the
  // panel width, so it activated inside the narrow panel and the
  // selects/inputs spilled outside the panel border. `min-w-0` on each
  // child keeps long option text (e.g. "baseline_deviation") from
  // forcing the column wider than the panel.
  return (
    <div className="rounded-md border border-ap-line bg-ap-bg/40 p-2">
      <div className="grid grid-cols-1 gap-2 [&>*]:min-w-0">
        <ValueRefEditor
          label={t("editor.condition.left")}
          value={term.left}
          disallowParams
          readOnly={readOnly}
          cropPaths={cropPaths}
          // Retype rather than assign: the right side follows what the new
          // left actually resolves to, so switching to a categorical field
          // can't silently leave a `= 0` that never matches.
          onChange={(next) => onChange(retypeTermForLeft(term, next))}
        />
        <OperatorPicker
          value={term.op}
          readOnly={readOnly}
          onChange={(next) => onChange(changeTermOp(term, next))}
        />
        <TermOperands term={term} readOnly={readOnly} onChange={onChange} />
        {onRemove && !readOnly ? (
          <button
            type="button"
            onClick={onRemove}
            aria-label={t("editor.condition.removeTerm")}
            className="justify-self-start rounded-md border border-ap-line bg-white px-2 py-0.5 text-[11px] text-ap-crit hover:bg-ap-crit/10"
          >
            ✕
          </button>
        ) : null}
      </div>
    </div>
  );
}

/** The right-hand side of a term, whose shape follows the operator:
 *  one operand for the binary ops, a low/high pair for `between`, and a
 *  variable-length list for `in`. */
function TermOperands({
  term,
  readOnly,
  onChange,
}: {
  term: Term;
  readOnly: boolean;
  onChange: (next: Term) => void;
}): ReactNode {
  const { t } = useTranslation("decisionTrees");

  if (term.op === "between") {
    return (
      <>
        <RightEditor
          label={t("editor.condition.low")}
          value={term.low}
          left={term.left}
          readOnly={readOnly}
          onChange={(low) => onChange({ ...term, low })}
        />
        <RightEditor
          label={t("editor.condition.high")}
          value={term.high}
          left={term.left}
          readOnly={readOnly}
          onChange={(high) => onChange({ ...term, high })}
        />
      </>
    );
  }

  if (term.op === "in") {
    const setValue = (idx: number, next: RightOperand): void => {
      onChange({ ...term, values: term.values.map((v, i) => (i === idx ? next : v)) });
    };
    const removeValue = (idx: number): void => {
      onChange({ ...term, values: term.values.filter((_, i) => i !== idx) });
    };
    return (
      <div className="flex flex-col gap-2">
        <span className="text-[11px] text-ap-muted">{t("editor.condition.values")}</span>
        {term.values.map((v, idx) => (
          <div key={idx} className="flex items-end gap-1">
            <div className="min-w-0 flex-1">
              <RightEditor
                label={`#${idx + 1}`}
                value={v}
                left={term.left}
                readOnly={readOnly}
                onChange={(next) => setValue(idx, next)}
              />
            </div>
            {/* Keep at least one entry: an `in` with no values can never
                match, which is a confusing thing to leave behind. */}
            {!readOnly && term.values.length > 1 ? (
              <RemoveButton
                label={t("editor.condition.removeValue")}
                onClick={() => removeValue(idx)}
              />
            ) : null}
          </div>
        ))}
        {!readOnly ? (
          <AddButton
            label={t("editor.condition.addValue")}
            onClick={() => onChange({ ...term, values: [...term.values, newInValue(term.left)] })}
          />
        ) : null}
      </div>
    );
  }

  return (
    <RightEditor
      label={t("editor.condition.right")}
      value={term.right}
      left={term.left}
      readOnly={readOnly}
      onChange={(right) => onChange({ ...term, right })}
    />
  );
}

// ---- Value-ref editor ----------------------------------------------

interface ValueRefEditorProps {
  label: string;
  value: ValueRef;
  readOnly: boolean;
  cropPaths?: string[];
  /** Params refs are only legal on the right operand — set true for
   *  `left`. */
  disallowParams?: boolean;
  onChange: (next: ValueRef) => void;
}

function ValueRefEditor({
  label,
  value,
  readOnly,
  cropPaths = [],
  disallowParams = false,
  onChange,
}: ValueRefEditorProps): ReactNode {
  const { t } = useTranslation("decisionTrees");
  const sources: ValueRefSource[] = disallowParams
    ? [
        "indices",
        "block",
        "weather",
        "weather_index",
        "weather_risk",
        "signals",
        "grid",
        "crop_attribute",
      ]
    : [
        "indices",
        "block",
        "weather",
        "weather_index",
        "weather_risk",
        "signals",
        "grid",
        "crop_attribute",
        "params",
      ];

  const onSourceChange = (next: ValueRefSource): void => {
    if (next === value.source) return;
    onChange(defaultValueRef(next));
  };

  return (
    <div className="flex flex-col gap-1">
      <span className="text-[11px] text-ap-muted">{label}</span>
      <select
        disabled={readOnly}
        value={value.source}
        onChange={(e) => onSourceChange(e.target.value as ValueRefSource)}
        className="rounded-md border border-ap-line bg-white px-2 py-1 text-xs"
      >
        {sources.map((s) => (
          <option key={s} value={s}>
            {t(`editor.condition.source.${s}`)}
          </option>
        ))}
      </select>
      <SourceSpecificFields
        value={value}
        readOnly={readOnly}
        cropPaths={cropPaths}
        onChange={onChange}
      />
    </div>
  );
}

function SourceSpecificFields({
  value,
  readOnly,
  cropPaths,
  onChange,
}: {
  value: ValueRef;
  readOnly: boolean;
  cropPaths: string[];
  onChange: (next: ValueRef) => void;
}): ReactNode {
  const { t } = useTranslation("decisionTrees");
  // Tenant signal definitions for the signals-source code dropdown. Loaded
  // once and shared across every condition row via react-query dedupe.
  const signalDefs = useQuery({
    queryKey: ["signal_definitions", "list"] as const,
    queryFn: () => listSignalDefinitions(),
    staleTime: 60_000,
  });
  // Crop attribute codes are the one condition source whose vocabulary is
  // data, not a constant in this file — they come from the platform crop
  // catalog and grow with it. Fetched once and shared across every condition
  // row by react-query dedupe, same as the signal definitions above.
  const cropAttrDefs = useQuery({
    queryKey: ["crop_attribute_definitions", "catalog"] as const,
    queryFn: () => listCropAttributeCatalog(),
    staleTime: 60_000,
  });
  if (value.source === "indices") {
    return (
      <>
        <select
          disabled={readOnly}
          value={value.index_code}
          onChange={(e) => onChange({ ...value, index_code: e.target.value })}
          className="rounded-md border border-ap-line bg-white px-2 py-1 text-xs"
          aria-label={t("editor.condition.indexCode")}
        >
          <option value="">—</option>
          {INDEX_CODES.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
        <select
          disabled={readOnly}
          value={value.key}
          onChange={(e) =>
            onChange({ ...value, key: e.target.value as (typeof INDICES_KEYS)[number] })
          }
          className="rounded-md border border-ap-line bg-white px-2 py-1 text-xs"
        >
          {INDICES_KEYS.map((k) => (
            <option key={k} value={k}>
              {k}
            </option>
          ))}
        </select>
      </>
    );
  }
  if (value.source === "block") {
    return (
      <select
        disabled={readOnly}
        value={value.field}
        onChange={(e) => onChange({ ...value, field: e.target.value as typeof value.field })}
        className="rounded-md border border-ap-line bg-white px-2 py-1 text-xs"
        aria-label={t("editor.condition.blockField")}
      >
        {BLOCK_FIELDS.map((f) => (
          <option key={f} value={f}>
            {f}
          </option>
        ))}
      </select>
    );
  }
  if (value.source === "weather") {
    // Field names differ per scope (`air_temp_c` hourly, `air_temp_c_max` in a
    // forecast window, `temp_max_c` in the derived daily row), and the backend
    // deliberately doesn't validate them — an unknown field resolves to None
    // and the tree just never fires. This used to be a free-text box with one
    // placeholder against 28 valid names, so switching scopes was the easy way
    // to author a dead predicate.
    const fields = WEATHER_FIELDS[value.scope];
    // A field authored in YAML that isn't in the list stays selectable rather
    // than being silently dropped — same as the signals / crop_attribute codes.
    const fieldOptions =
      value.field && !fields.includes(value.field) ? [value.field, ...fields] : fields;
    const onScopeChange = (scope: (typeof WEATHER_SCOPES)[number]): void => {
      // Carry the field over when the new scope also has it (the two forecast
      // windows share a vocabulary); otherwise move to that scope's first
      // field. Keeping a field the new scope can't resolve would leave a term
      // that looks authored and can never match.
      const next = WEATHER_FIELDS[scope];
      onChange({
        ...value,
        scope,
        field: next.includes(value.field) ? value.field : next[0],
      });
    };
    return (
      <>
        <select
          disabled={readOnly}
          value={value.scope}
          onChange={(e) => onScopeChange(e.target.value as (typeof WEATHER_SCOPES)[number])}
          className="rounded-md border border-ap-line bg-white px-2 py-1 text-xs"
        >
          {WEATHER_SCOPES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <select
          disabled={readOnly}
          value={value.field}
          onChange={(e) => onChange({ ...value, field: e.target.value })}
          className="rounded-md border border-ap-line bg-white px-2 py-1 text-xs"
          aria-label={t("editor.condition.weatherField")}
        >
          {fieldOptions.map((f) => (
            <option key={f} value={f}>
              {f}
            </option>
          ))}
        </select>
      </>
    );
  }
  if (value.source === "weather_index") {
    return (
      <>
        <select
          disabled={readOnly}
          value={value.index_code}
          onChange={(e) =>
            onChange({
              ...value,
              index_code: e.target.value as (typeof WEATHER_INDEX_CODES)[number],
            })
          }
          className="rounded-md border border-ap-line bg-white px-2 py-1 text-xs"
          aria-label={t("editor.condition.weatherIndexCode")}
        >
          {WEATHER_INDEX_CODES.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
        <select
          disabled={readOnly}
          value={value.key}
          onChange={(e) =>
            onChange({ ...value, key: e.target.value as (typeof WEATHER_INDEX_KEYS)[number] })
          }
          className="rounded-md border border-ap-line bg-white px-2 py-1 text-xs"
        >
          {WEATHER_INDEX_KEYS.map((k) => (
            <option key={k} value={k}>
              {k}
            </option>
          ))}
        </select>
      </>
    );
  }
  if (value.source === "weather_risk") {
    // Every model in the registry is registered for a crop prefix and only
    // ever scores blocks under it, so a tree targeting citrus branching on
    // `anthracnose` reads as authored and can never fire. Hide the ones this
    // tree's crops can't be scored for, and name the crop on the rest.
    const applicable = WEATHER_RISK_CODES.filter((c) => riskAppliesToCrops(c, cropPaths));
    const riskOptions =
      value.risk_code && !applicable.includes(value.risk_code)
        ? [value.risk_code, ...applicable]
        : applicable;
    return (
      <>
        <select
          disabled={readOnly}
          value={value.risk_code}
          onChange={(e) =>
            onChange({
              ...value,
              risk_code: e.target.value as (typeof WEATHER_RISK_CODES)[number],
            })
          }
          className="rounded-md border border-ap-line bg-white px-2 py-1 text-xs"
          aria-label={t("editor.condition.weatherRiskCode")}
        >
          {riskOptions.map((c) => (
            <option key={c} value={c}>
              {WEATHER_RISK_CROP_PREFIX[c] ? `${c} (${WEATHER_RISK_CROP_PREFIX[c]})` : c}
            </option>
          ))}
        </select>
        <select
          disabled={readOnly}
          value={value.field}
          onChange={(e) =>
            onChange({ ...value, field: e.target.value as (typeof WEATHER_RISK_FIELDS)[number] })
          }
          className="rounded-md border border-ap-line bg-white px-2 py-1 text-xs"
        >
          {WEATHER_RISK_FIELDS.map((f) => (
            <option key={f} value={f}>
              {f}
            </option>
          ))}
        </select>
      </>
    );
  }
  if (value.source === "signals") {
    const knownCodes = (signalDefs.data ?? []).map((d) => d.code);
    // Keep an out-of-catalog code (e.g. authored in YAML) selectable so
    // switching to the dropdown never silently drops it.
    const codeOptions =
      value.code && !knownCodes.includes(value.code) ? [value.code, ...knownCodes] : knownCodes;
    return (
      <>
        <select
          disabled={readOnly}
          value={value.code}
          onChange={(e) => onChange({ ...value, code: e.target.value })}
          className="rounded-md border border-ap-line bg-white px-2 py-1 text-xs"
          aria-label={t("editor.condition.signalCode")}
        >
          <option value="">—</option>
          {codeOptions.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
        <select
          disabled={readOnly}
          value={value.key}
          onChange={(e) =>
            onChange({ ...value, key: e.target.value as (typeof SIGNAL_KEYS)[number] })
          }
          className="rounded-md border border-ap-line bg-white px-2 py-1 text-xs"
        >
          {/* Exactly one `value_*` column is populated per definition, so the
              other six keys are six ways to write a term that never matches. */}
          {signalKeysForValueKind(
            (signalDefs.data ?? []).find((d) => d.code === value.code)?.value_kind,
          ).map((k) => (
            <option key={k} value={k}>
              {k}
            </option>
          ))}
        </select>
      </>
    );
  }
  if (value.source === "grid") {
    return (
      <>
        <select
          disabled={readOnly}
          value={value.index_code}
          onChange={(e) => onChange({ ...value, index_code: e.target.value })}
          className="rounded-md border border-ap-line bg-white px-2 py-1 text-xs"
          aria-label={t("editor.condition.indexCode")}
        >
          <option value="">—</option>
          {INDEX_CODES.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
        <select
          disabled={readOnly}
          value={value.field}
          onChange={(e) =>
            onChange({ ...value, field: e.target.value as (typeof GRID_FIELDS)[number] })
          }
          className="rounded-md border border-ap-line bg-white px-2 py-1 text-xs"
          aria-label={t("editor.condition.gridField")}
        >
          {GRID_FIELDS.map((f) => (
            <option key={f} value={f}>
              {f}
            </option>
          ))}
        </select>
      </>
    );
  }
  if (value.source === "crop_attribute") {
    // One entry per distinct code: the same code can be defined at several
    // taxonomy nodes (a variety narrowing a crop-level range), and a tree
    // targets by crop path, so the code is what it branches on.
    // Definitions are inherited down the taxonomy, so a `mango` attribute
    // resolves for `mango.keitt`. Anything outside the tree's targeted paths
    // can never resolve for a block this tree runs on — offering it is
    // offering a predicate that always fails closed.
    const catalog = (cropAttrDefs.data ?? []).filter((d) =>
      attributePathAppliesToCrops(d.path, cropPaths),
    );
    const byCode = new Map<string, (typeof catalog)[number]>();
    for (const def of catalog) if (!byCode.has(def.code)) byCode.set(def.code, def);
    // Keep an out-of-catalog code (authored in YAML, or since retired)
    // selectable so switching to the dropdown never silently drops it.
    const codes = [...byCode.keys()];
    const codeOptions = value.code && !codes.includes(value.code) ? [value.code, ...codes] : codes;
    return (
      <>
        <select
          disabled={readOnly}
          value={value.code}
          onChange={(e) => onChange({ ...value, code: e.target.value })}
          className="rounded-md border border-ap-line bg-white px-2 py-1 text-xs"
          aria-label={t("editor.condition.cropAttributeCode")}
        >
          <option value="">—</option>
          {codeOptions.map((c) => {
            const def = byCode.get(c);
            return (
              <option key={c} value={c}>
                {def ? `${def.name_en} (${c})` : c}
              </option>
            );
          })}
        </select>
        <select
          disabled={readOnly}
          value={value.key}
          onChange={(e) =>
            onChange({ ...value, key: e.target.value as (typeof CROP_ATTRIBUTE_KEYS)[number] })
          }
          className="rounded-md border border-ap-line bg-white px-2 py-1 text-xs"
        >
          {CROP_ATTRIBUTE_KEYS.map((k) => (
            <option key={k} value={k}>
              {k}
            </option>
          ))}
        </select>
      </>
    );
  }
  // params
  return (
    <input
      type="text"
      disabled={readOnly}
      placeholder="threshold_name"
      value={value.name}
      onChange={(e) => onChange({ ...value, name: e.target.value })}
      className="rounded-md border border-ap-line bg-white px-2 py-1 text-xs"
      aria-label={t("editor.condition.paramName")}
    />
  );
}

// ---- Operator picker -----------------------------------------------

interface OperatorPickerProps {
  value: TermOp;
  readOnly: boolean;
  onChange: (next: TermOp) => void;
}

function OperatorPicker({ value, readOnly, onChange }: OperatorPickerProps): ReactNode {
  const { t } = useTranslation("decisionTrees");
  return (
    <div className="flex flex-col gap-1 self-end">
      <span className="text-[11px] text-ap-muted">{t("editor.condition.operator")}</span>
      <select
        disabled={readOnly}
        value={value}
        onChange={(e) => onChange(e.target.value as TermOp)}
        className="rounded-md border border-ap-line bg-white px-2 py-1 text-xs font-mono"
      >
        {TERM_OPS.map((op) => (
          <option key={op} value={op}>
            {opSymbol(op)} {op}
          </option>
        ))}
      </select>
    </div>
  );
}

function opSymbol(op: TermOp): string {
  switch (op) {
    case "lt":
      return "<";
    case "le":
      return "≤";
    case "gt":
      return ">";
    case "ge":
      return "≥";
    case "eq":
      return "=";
    case "ne":
      return "≠";
    case "between":
      return "↔";
    case "in":
      return "∈";
  }
}

// ---- Right operand editor -----------------------------------------

interface RightEditorProps {
  label: string;
  value: RightOperand;
  /** The term's left ref — decides whether this operand is a number, a
   *  boolean or a categorical, and supplies the vocabulary when there is
   *  a closed one. */
  left: ValueRef;
  readOnly: boolean;
  onChange: (next: RightOperand) => void;
}

function RightEditor({ label, value, left, readOnly, onChange }: RightEditorProps): ReactNode {
  const { t } = useTranslation("decisionTrees");
  // The user picks between "literal" (number/string/boolean) and "ref"
  // (typically a params ref). Number is the default and most common.
  const kindLabel = value.kind === "ref" ? "params ref" : value.kind;
  // Closed vocabularies (soil texture, risk level, trend direction, …) become
  // a picker: those are exactly the comparisons an author gets wrong by
  // typing, and a wrong value fails closed with no error anywhere.
  const vocabulary = leftOperandValues(left);
  return (
    <div className="flex flex-col gap-1">
      <span className="text-[11px] text-ap-muted">
        {label} <span className="text-ap-muted">({kindLabel})</span>
      </span>
      <select
        disabled={readOnly}
        value={value.kind}
        onChange={(e) => onChange(coerceRight(e.target.value as RightOperand["kind"], value))}
        className="rounded-md border border-ap-line bg-white px-2 py-1 text-xs"
      >
        <option value="number">{t("editor.condition.rightNumber")}</option>
        <option value="string">{t("editor.condition.rightString")}</option>
        <option value="boolean">{t("editor.condition.rightBoolean")}</option>
        <option value="ref">{t("editor.condition.rightRef")}</option>
      </select>
      {value.kind === "number" ? (
        <input
          type="number"
          step="any"
          disabled={readOnly}
          value={value.value}
          onChange={(e) => {
            const n = Number(e.target.value);
            if (!Number.isNaN(n)) onChange({ kind: "number", value: n });
          }}
          className="rounded-md border border-ap-line bg-white px-2 py-1 text-xs font-mono"
        />
      ) : value.kind === "string" && vocabulary ? (
        <select
          disabled={readOnly}
          value={value.value}
          onChange={(e) => onChange({ kind: "string", value: e.target.value })}
          className="rounded-md border border-ap-line bg-white px-2 py-1 text-xs"
        >
          {/* An out-of-vocabulary value authored in YAML stays selectable. */}
          {(vocabulary.includes(value.value) ? vocabulary : [value.value, ...vocabulary]).map(
            (v) => (
              <option key={v} value={v}>
                {v}
              </option>
            ),
          )}
        </select>
      ) : value.kind === "string" ? (
        <input
          type="text"
          disabled={readOnly}
          value={value.value}
          onChange={(e) => onChange({ kind: "string", value: e.target.value })}
          className="rounded-md border border-ap-line bg-white px-2 py-1 text-xs"
        />
      ) : value.kind === "boolean" ? (
        <select
          disabled={readOnly}
          value={String(value.value)}
          onChange={(e) => onChange({ kind: "boolean", value: e.target.value === "true" })}
          className="rounded-md border border-ap-line bg-white px-2 py-1 text-xs"
        >
          <option value="true">true</option>
          <option value="false">false</option>
        </select>
      ) : (
        <input
          type="text"
          disabled={readOnly}
          placeholder="threshold_param"
          value={value.ref.source === "params" ? value.ref.name : ""}
          onChange={(e) =>
            onChange({ kind: "ref", ref: { source: "params", name: e.target.value } })
          }
          className="rounded-md border border-ap-line bg-white px-2 py-1 text-xs"
        />
      )}
    </div>
  );
}

/** A fresh `in` entry starts in the left ref's own shape — a number for a
 *  numeric left, and the first value of a closed vocabulary where there is
 *  one, rather than an empty string that can never match. */
function newInValue(left: ValueRef): RightOperand {
  if (leftOperandType(left) === "number") return { kind: "number", value: 0 };
  if (leftOperandType(left) === "boolean") return { kind: "boolean", value: true };
  const vocabulary = leftOperandValues(left);
  return { kind: "string", value: vocabulary ? vocabulary[0] : "" };
}

/** Switching the right-operand "kind" from one form to another resets
 *  to a sensible default value of the new kind. Numbers default to 0,
 *  strings to "", booleans to false, refs to an empty params ref. */
function coerceRight(kind: RightOperand["kind"], prev: RightOperand): RightOperand {
  if (kind === prev.kind) return prev;
  if (kind === "number") return { kind: "number", value: 0 };
  if (kind === "string") return { kind: "string", value: "" };
  if (kind === "boolean") return { kind: "boolean", value: false };
  return { kind: "ref", ref: { source: "params", name: "" } };
}

// ---- Small shared controls -----------------------------------------

function AddButton({ label, onClick }: { label: string; onClick: () => void }): ReactNode {
  return (
    <button
      type="button"
      onClick={onClick}
      className="self-start rounded-md border border-dashed border-ap-line bg-ap-bg/40 px-2 py-1 text-xs text-ap-ink hover:bg-ap-bg/60"
    >
      {label}
    </button>
  );
}

function RemoveButton({ label, onClick }: { label: string; onClick: () => void }): ReactNode {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      title={label}
      className="rounded-md border border-ap-line bg-white px-2 py-0.5 text-[11px] text-ap-crit hover:bg-ap-crit/10"
    >
      ✕
    </button>
  );
}
