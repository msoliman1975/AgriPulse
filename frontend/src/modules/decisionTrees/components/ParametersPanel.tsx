// Tree-author UI for the `parameters:` declaration block (PR-D3).
//
// Shows every currently-declared parameter as a row with type, default,
// and the type-specific constraints (min/max for numeric, values for
// enum). The author can add a new parameter, edit an existing one's
// fields inline, or delete one.
//
// Edits accumulate in a `ParametersEditBuffer`; the page-level Save
// flow merges them with the tree-edit buffer and round-trips through
// `applyParameterEditsToYaml`. PR-D2 already wires `Save as new
// draft` + `Discard all` at the page level — D3 adds this panel as
// another contributor to the same buffer.

import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type {
  ParameterDeclaration,
  ParameterType,
  ParametersEditBuffer,
} from "../lib/parametersEdit";
import { validateParameterDeclaration } from "../lib/parametersEdit";

interface ParametersPanelProps {
  /** Current declarations from the loaded tree's compiled JSON. */
  declared: Record<string, ParameterDeclaration>;
  /** Pending edits the page-level Save will flush. */
  buffer: ParametersEditBuffer;
  canEdit: boolean;
  onChange: (paramName: string, decl: ParameterDeclaration | null) => void;
}

/** Merge declared + buffer into the effective shape (what the row
 *  should render). null in the buffer means "deleted"; the row is
 *  hidden in that case. */
function effectiveParams(
  declared: Record<string, ParameterDeclaration>,
  buffer: ParametersEditBuffer,
): Array<{ name: string; decl: ParameterDeclaration; pending: boolean; deleted: boolean }> {
  const names = new Set([...Object.keys(declared), ...Object.keys(buffer)]);
  const out: ReturnType<typeof effectiveParams> = [];
  for (const name of names) {
    const inBuf = name in buffer;
    if (inBuf && buffer[name] === null) {
      out.push({
        name,
        decl: declared[name] ?? { type: "string", default: "" },
        pending: true,
        deleted: true,
      });
      continue;
    }
    const decl = (inBuf ? buffer[name] : declared[name]) as ParameterDeclaration;
    out.push({ name, decl, pending: inBuf, deleted: false });
  }
  out.sort((a, b) => a.name.localeCompare(b.name));
  return out;
}

export function ParametersPanel({
  declared,
  buffer,
  canEdit,
  onChange,
}: ParametersPanelProps): JSX.Element {
  const { t } = useTranslation("decisionTrees");
  const rows = effectiveParams(declared, buffer);
  const [adding, setAdding] = useState(false);

  return (
    <aside className="flex flex-col gap-3 rounded-xl border border-ap-line bg-ap-panel p-4">
      <header className="flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-ap-ink">{t("parameters.heading")}</h2>
        {canEdit ? (
          <button
            type="button"
            onClick={() => setAdding((a) => !a)}
            className="rounded-md border border-ap-line bg-ap-bg/60 px-2 py-1 text-xs font-medium text-ap-ink hover:bg-ap-bg"
          >
            {adding ? t("parameters.cancelAdd") : t("parameters.addNew")}
          </button>
        ) : null}
      </header>

      {rows.length === 0 && !adding ? (
        <p className="rounded-md border border-dashed border-ap-line p-4 text-center text-xs text-ap-muted">
          {t("parameters.empty")}
        </p>
      ) : null}

      {adding ? (
        <AddParameterForm
          existingNames={new Set(rows.map((r) => r.name))}
          onCancel={() => setAdding(false)}
          onAdd={(name, decl) => {
            onChange(name, decl);
            setAdding(false);
          }}
        />
      ) : null}

      <div className="flex flex-col divide-y divide-ap-line">
        {rows
          .filter((r) => !r.deleted)
          .map((row) => (
            <ParameterRow
              key={row.name}
              name={row.name}
              decl={row.decl}
              pending={row.pending}
              canEdit={canEdit}
              onChange={(decl) => onChange(row.name, decl)}
              onDelete={() => onChange(row.name, null)}
            />
          ))}
      </div>
    </aside>
  );
}

// ---- Add form ------------------------------------------------------

function AddParameterForm({
  existingNames,
  onCancel,
  onAdd,
}: {
  existingNames: Set<string>;
  onCancel: () => void;
  onAdd: (name: string, decl: ParameterDeclaration) => void;
}): JSX.Element {
  const { t } = useTranslation("decisionTrees");
  const [name, setName] = useState("");
  const [decl, setDecl] = useState<ParameterDeclaration>({
    type: "number",
    default: 0,
  });
  const nameTaken = existingNames.has(name);
  const validationErr = name ? validateParameterDeclaration(name, decl) : null;
  const disabled = !name || nameTaken || validationErr !== null;

  return (
    <div className="flex flex-col gap-2 rounded-md border border-ap-line bg-ap-bg/30 p-3">
      <label className="flex flex-col gap-1 text-xs">
        <span className="text-ap-muted">{t("parameters.fields.name")}</span>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="ndvi_drop_threshold"
          className="rounded-md border border-ap-line bg-ap-panel px-2 py-1 font-mono text-sm text-ap-ink"
        />
      </label>
      {nameTaken ? (
        <p className="text-xs text-ap-crit">{t("parameters.errors.nameTaken")}</p>
      ) : null}
      <DeclarationFields decl={decl} onChange={setDecl} />
      {validationErr ? (
        <p className="text-xs text-ap-crit">{validationErr}</p>
      ) : null}
      <div className="flex justify-end gap-2">
        <button
          type="button"
          onClick={onCancel}
          className="rounded-md border border-ap-line bg-ap-panel px-2 py-1 text-xs"
        >
          {t("parameters.cancel")}
        </button>
        <button
          type="button"
          disabled={disabled}
          onClick={() => onAdd(name, decl)}
          className="rounded-md bg-ap-primary px-2 py-1 text-xs font-medium text-white disabled:opacity-50"
        >
          {t("parameters.add")}
        </button>
      </div>
    </div>
  );
}

// ---- Row -----------------------------------------------------------

function ParameterRow({
  name,
  decl,
  pending,
  canEdit,
  onChange,
  onDelete,
}: {
  name: string;
  decl: ParameterDeclaration;
  pending: boolean;
  canEdit: boolean;
  onChange: (decl: ParameterDeclaration) => void;
  onDelete: () => void;
}): ReactNode {
  const { t } = useTranslation("decisionTrees");
  const [editing, setEditing] = useState(false);
  const validationErr = editing ? validateParameterDeclaration(name, decl) : null;

  return (
    <div className="flex flex-col gap-2 py-3">
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0">
          <span className="break-all font-mono text-sm text-ap-ink">{name}</span>
          {pending ? (
            <span className="ms-2 inline-block rounded-full bg-ap-info/10 px-2 py-0.5 text-[10px] font-medium text-ap-info">
              {t("parameters.pendingBadge")}
            </span>
          ) : null}
        </div>
        {canEdit ? (
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setEditing((e) => !e)}
              className="text-xs font-medium text-ap-primary hover:underline"
            >
              {editing ? t("parameters.done") : t("parameters.edit")}
            </button>
            <button
              type="button"
              onClick={onDelete}
              className="text-xs font-medium text-ap-crit hover:underline"
            >
              {t("parameters.delete")}
            </button>
          </div>
        ) : null}
      </div>
      {editing ? (
        <div className="flex flex-col gap-2">
          <DeclarationFields decl={decl} onChange={onChange} />
          {validationErr ? (
            <p className="text-xs text-ap-crit">{validationErr}</p>
          ) : null}
        </div>
      ) : (
        <div className="grid grid-cols-[80px_1fr] gap-1 text-xs">
          <span className="text-ap-muted">{t("parameters.fields.type")}</span>
          <span className="font-mono text-ap-ink">{decl.type}</span>
          <span className="text-ap-muted">{t("parameters.fields.default")}</span>
          <span className="font-mono text-ap-ink">{JSON.stringify(decl.default)}</span>
          {decl.min != null || decl.max != null ? (
            <>
              <span className="text-ap-muted">{t("parameters.fields.range")}</span>
              <span className="font-mono text-ap-ink">
                [{decl.min ?? "−∞"}, {decl.max ?? "+∞"}]
              </span>
            </>
          ) : null}
          {decl.type === "enum" && decl.values ? (
            <>
              <span className="text-ap-muted">{t("parameters.fields.values")}</span>
              <span className="font-mono text-ap-ink">
                {decl.values.map((v) => JSON.stringify(v)).join(", ")}
              </span>
            </>
          ) : null}
          {decl.description ? (
            <>
              <span className="text-ap-muted">{t("parameters.fields.description")}</span>
              <span className="text-ap-ink">{decl.description}</span>
            </>
          ) : null}
        </div>
      )}
    </div>
  );
}

// ---- Shared field editor ------------------------------------------

function DeclarationFields({
  decl,
  onChange,
}: {
  decl: ParameterDeclaration;
  onChange: (decl: ParameterDeclaration) => void;
}): JSX.Element {
  const { t } = useTranslation("decisionTrees");

  const setField = <K extends keyof ParameterDeclaration>(
    key: K,
    value: ParameterDeclaration[K],
  ): void => {
    onChange({ ...decl, [key]: value });
  };

  // When the type changes, snap default to a sensible value of the
  // new type so the form doesn't show "0" in a string field etc.
  const onTypeChange = (next: ParameterType): void => {
    const defaults: Record<ParameterType, unknown> = {
      number: 0,
      integer: 0,
      boolean: false,
      string: "",
      enum: "",
    };
    onChange({
      type: next,
      default: defaults[next],
      description: decl.description,
      min: next === "number" || next === "integer" ? decl.min : null,
      max: next === "number" || next === "integer" ? decl.max : null,
      values: next === "enum" ? (decl.values ?? []) : null,
    });
  };

  return (
    <div className="grid grid-cols-2 gap-2 text-xs">
      <label className="flex flex-col gap-1">
        <span className="text-ap-muted">{t("parameters.fields.type")}</span>
        <select
          value={decl.type}
          onChange={(e) => onTypeChange(e.target.value as ParameterType)}
          className="rounded-md border border-ap-line bg-ap-panel px-2 py-1 text-sm text-ap-ink"
        >
          <option value="number">number</option>
          <option value="integer">integer</option>
          <option value="boolean">boolean</option>
          <option value="string">string</option>
          <option value="enum">enum</option>
        </select>
      </label>

      <label className="flex flex-col gap-1">
        <span className="text-ap-muted">{t("parameters.fields.default")}</span>
        <DefaultInput decl={decl} onChange={(v) => setField("default", v)} />
      </label>

      {decl.type === "number" || decl.type === "integer" ? (
        <>
          <label className="flex flex-col gap-1">
            <span className="text-ap-muted">{t("parameters.fields.min")}</span>
            <input
              type="number"
              value={decl.min ?? ""}
              onChange={(e) => {
                const v = e.target.value === "" ? null : Number(e.target.value);
                setField("min", v);
              }}
              className="rounded-md border border-ap-line bg-ap-panel px-2 py-1 text-sm text-ap-ink"
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-ap-muted">{t("parameters.fields.max")}</span>
            <input
              type="number"
              value={decl.max ?? ""}
              onChange={(e) => {
                const v = e.target.value === "" ? null : Number(e.target.value);
                setField("max", v);
              }}
              className="rounded-md border border-ap-line bg-ap-panel px-2 py-1 text-sm text-ap-ink"
            />
          </label>
        </>
      ) : null}

      {decl.type === "enum" ? (
        <label className="col-span-2 flex flex-col gap-1">
          <span className="text-ap-muted">{t("parameters.fields.values")}</span>
          <input
            type="text"
            value={(decl.values ?? []).map((v) => String(v)).join(", ")}
            placeholder="a, b, c"
            onChange={(e) => {
              const next = e.target.value
                .split(",")
                .map((s) => s.trim())
                .filter(Boolean);
              setField("values", next);
            }}
            className="rounded-md border border-ap-line bg-ap-panel px-2 py-1 font-mono text-sm text-ap-ink"
          />
        </label>
      ) : null}

      <label className="col-span-2 flex flex-col gap-1">
        <span className="text-ap-muted">{t("parameters.fields.description")}</span>
        <input
          type="text"
          value={decl.description ?? ""}
          onChange={(e) => setField("description", e.target.value || null)}
          className="rounded-md border border-ap-line bg-ap-panel px-2 py-1 text-sm text-ap-ink"
        />
      </label>
    </div>
  );
}

function DefaultInput({
  decl,
  onChange,
}: {
  decl: ParameterDeclaration;
  onChange: (value: unknown) => void;
}): JSX.Element {
  switch (decl.type) {
    case "boolean":
      return (
        <select
          value={String(decl.default)}
          onChange={(e) => onChange(e.target.value === "true")}
          className="rounded-md border border-ap-line bg-ap-panel px-2 py-1 text-sm text-ap-ink"
        >
          <option value="true">true</option>
          <option value="false">false</option>
        </select>
      );
    case "number":
    case "integer":
      return (
        <input
          type="number"
          value={typeof decl.default === "number" ? decl.default : 0}
          step={decl.type === "integer" ? 1 : "any"}
          onChange={(e) => {
            const v = Number(e.target.value);
            if (!Number.isNaN(v)) onChange(decl.type === "integer" ? Math.round(v) : v);
          }}
          className="rounded-md border border-ap-line bg-ap-panel px-2 py-1 text-sm text-ap-ink"
        />
      );
    case "enum":
      // Drop-down constrained to declared values; if no values yet,
      // fall back to a text input so the author can populate values
      // first then come back.
      if (decl.values && decl.values.length > 0) {
        return (
          <select
            value={String(decl.default)}
            onChange={(e) => onChange(e.target.value)}
            className="rounded-md border border-ap-line bg-ap-panel px-2 py-1 text-sm text-ap-ink"
          >
            {decl.values.map((v) => (
              <option key={String(v)} value={String(v)}>
                {String(v)}
              </option>
            ))}
          </select>
        );
      }
      return (
        <input
          type="text"
          value={typeof decl.default === "string" ? decl.default : ""}
          onChange={(e) => onChange(e.target.value)}
          className="rounded-md border border-ap-line bg-ap-panel px-2 py-1 text-sm text-ap-ink"
        />
      );
    case "string":
    default:
      return (
        <input
          type="text"
          value={typeof decl.default === "string" ? decl.default : ""}
          onChange={(e) => onChange(e.target.value)}
          className="rounded-md border border-ap-line bg-ap-panel px-2 py-1 text-sm text-ap-ink"
        />
      );
  }
}
