import { useMemo, useState, type ReactNode } from "react";
import { Navigate } from "react-router-dom";

import type {
  SignalDefinition,
  SignalDefinitionCreatePayload,
  ValueKind,
} from "@/api/signals";
import { Pill } from "@/components/Pill";
import { Skeleton } from "@/components/Skeleton";
import { useActiveFarmId } from "@/hooks/useActiveFarm";
import { useCapability } from "@/rbac/useCapability";
import {
  useCreateSignalDefinition,
  useDeleteSignalDefinition,
  useSignalDefinitions,
  useUpdateSignalDefinition,
} from "@/queries/signals";

const VALUE_KINDS: ValueKind[] = [
  "numeric",
  "categorical",
  "event",
  "boolean",
  "geopoint",
];

interface FormState {
  code: string;
  name: string;
  description: string;
  value_kind: ValueKind;
  unit: string;
  categorical_values: string;
  value_min: string;
  value_max: string;
  attachment_allowed: boolean;
}

const EMPTY_FORM: FormState = {
  code: "",
  name: "",
  description: "",
  value_kind: "numeric",
  unit: "",
  categorical_values: "",
  value_min: "",
  value_max: "",
  attachment_allowed: false,
};

export function SignalsConfigPage(): ReactNode {
  const farmId = useActiveFarmId();
  const canDefine = useCapability("signal.define");
  const { data, isLoading, isError } = useSignalDefinitions(true);
  const createMut = useCreateSignalDefinition();
  const deleteMut = useDeleteSignalDefinition();
  const updateMut = useUpdateSignalDefinition();
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [showForm, setShowForm] = useState(false);

  if (!farmId) {
    return <Navigate to="/" replace />;
  }

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    const payload: SignalDefinitionCreatePayload = {
      code: form.code.trim(),
      name: form.name.trim(),
      description: form.description.trim() || null,
      value_kind: form.value_kind,
      unit: form.unit.trim() || null,
      categorical_values:
        form.value_kind === "categorical"
          ? form.categorical_values
              .split(",")
              .map((v) => v.trim())
              .filter(Boolean)
          : null,
      value_min: form.value_min ? form.value_min : null,
      value_max: form.value_max ? form.value_max : null,
      attachment_allowed: form.attachment_allowed,
    };
    createMut.mutate(payload, {
      onSuccess: () => {
        setForm(EMPTY_FORM);
        setShowForm(false);
      },
    });
  };

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-ap-ink">Custom signals</h1>
          <p className="mt-1 text-sm text-ap-muted">
            Define data streams your team can record from the field — soil
            moisture, scout pest counts, irrigation events.
          </p>
        </div>
        {canDefine ? (
          <button
            type="button"
            onClick={() => setShowForm((s) => !s)}
            className="rounded-md bg-ap-primary px-3 py-1.5 text-sm font-medium text-white hover:bg-ap-primary/90"
          >
            {showForm ? "Cancel" : "New definition"}
          </button>
        ) : null}
      </header>

      {showForm && canDefine ? (
        <form
          onSubmit={submit}
          className="rounded-xl border border-ap-line bg-ap-panel p-4 text-sm"
        >
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Field label="Code (stable identifier)">
              <input
                required
                value={form.code}
                onChange={(e) => setForm({ ...form, code: e.target.value })}
                placeholder="soil_moisture"
                pattern="^[a-z0-9][a-z0-9_-]*$"
                className={inputCls}
              />
            </Field>
            <Field label="Display name">
              <input
                required
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder="Soil moisture"
                className={inputCls}
              />
            </Field>
            <Field label="Value kind">
              <select
                value={form.value_kind}
                onChange={(e) =>
                  setForm({ ...form, value_kind: e.target.value as ValueKind })
                }
                className={inputCls}
              >
                {VALUE_KINDS.map((k) => (
                  <option key={k} value={k}>
                    {k}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Unit (numeric only)">
              <input
                value={form.unit}
                onChange={(e) => setForm({ ...form, unit: e.target.value })}
                placeholder="%"
                className={inputCls}
                disabled={form.value_kind !== "numeric"}
              />
            </Field>
            {form.value_kind === "numeric" ? (
              <>
                <Field label="Min">
                  <input
                    inputMode="decimal"
                    value={form.value_min}
                    onChange={(e) => setForm({ ...form, value_min: e.target.value })}
                    className={inputCls}
                  />
                </Field>
                <Field label="Max">
                  <input
                    inputMode="decimal"
                    value={form.value_max}
                    onChange={(e) => setForm({ ...form, value_max: e.target.value })}
                    className={inputCls}
                  />
                </Field>
              </>
            ) : null}
            {form.value_kind === "categorical" ? (
              <Field label="Categories (comma-separated)" className="sm:col-span-2">
                <input
                  required
                  value={form.categorical_values}
                  onChange={(e) =>
                    setForm({ ...form, categorical_values: e.target.value })
                  }
                  placeholder="absent, low, medium, high"
                  className={inputCls}
                />
              </Field>
            ) : null}
            <Field label="Description (optional)" className="sm:col-span-2">
              <input
                value={form.description}
                onChange={(e) => setForm({ ...form, description: e.target.value })}
                className={inputCls}
              />
            </Field>
            <Field label="Allow photo attachment" className="sm:col-span-2">
              <label className="inline-flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={form.attachment_allowed}
                  onChange={(e) =>
                    setForm({ ...form, attachment_allowed: e.target.checked })
                  }
                />
                <span>Field operators can attach a photo when recording</span>
              </label>
            </Field>
          </div>
          <div className="mt-3 flex items-center justify-end gap-2">
            {createMut.isError ? (
              <span className="text-xs text-ap-crit">
                {(createMut.error as Error)?.message ?? "Save failed"}
              </span>
            ) : null}
            <button
              type="submit"
              disabled={createMut.isPending}
              className="rounded-md bg-ap-primary px-3 py-1.5 text-sm font-medium text-white hover:bg-ap-primary/90 disabled:opacity-60"
            >
              {createMut.isPending ? "Saving…" : "Save"}
            </button>
          </div>
        </form>
      ) : null}

      <div className="rounded-xl border border-ap-line bg-ap-panel">
        {isLoading ? (
          <div className="flex flex-col gap-2 p-4">
            <Skeleton className="h-12 w-full" />
            <Skeleton className="h-12 w-full" />
          </div>
        ) : isError ? (
          <p className="p-4 text-sm text-ap-crit">Failed to load definitions.</p>
        ) : !data || data.length === 0 ? (
          <p className="p-12 text-center text-sm text-ap-muted">
            No signals defined yet — start with one for the data your team
            already records.
          </p>
        ) : (
          <ul className="divide-y divide-ap-line">
            {data.map((d) => (
              <DefinitionRow
                key={d.id}
                defn={d}
                canEdit={canDefine}
                onArchive={() => deleteMut.mutate(d.id)}
                onToggleActive={() =>
                  updateMut.mutate({ id: d.id, payload: { is_active: !d.is_active } })
                }
              />
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function DefinitionRow({
  defn,
  canEdit,
  onArchive,
  onToggleActive,
}: {
  defn: SignalDefinition;
  canEdit: boolean;
  onArchive: () => void;
  onToggleActive: () => void;
}): ReactNode {
  const valueRange = useMemo(() => {
    if (defn.value_kind !== "numeric") return null;
    if (defn.value_min === null && defn.value_max === null) return null;
    return `${defn.value_min ?? "−∞"} … ${defn.value_max ?? "∞"} ${defn.unit ?? ""}`.trim();
  }, [defn]);
  return (
    <li className="flex items-start gap-3 p-4">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-medium text-ap-ink">{defn.name}</span>
          <span className="font-mono text-[11px] text-ap-muted">{defn.code}</span>
          <Pill kind={defn.is_active ? "ok" : "neutral"}>
            {defn.is_active ? "active" : "inactive"}
          </Pill>
          <Pill kind="info">{defn.value_kind}</Pill>
          {defn.attachment_allowed ? <Pill kind="neutral">photos</Pill> : null}
        </div>
        {defn.description ? (
          <p className="mt-1 text-sm text-ap-muted">{defn.description}</p>
        ) : null}
        <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-ap-muted">
          {defn.value_kind === "numeric" && defn.unit ? (
            <span>unit: {defn.unit}</span>
          ) : null}
          {valueRange ? <span>range: {valueRange}</span> : null}
          {defn.categorical_values ? (
            <span>values: {defn.categorical_values.join(", ")}</span>
          ) : null}
        </div>
      </div>
      {canEdit ? (
        <div className="flex flex-none gap-1">
          <button
            type="button"
            onClick={onToggleActive}
            className="rounded-md border border-ap-line bg-ap-panel px-2 py-1 text-xs font-medium text-ap-ink hover:bg-ap-line/40"
          >
            {defn.is_active ? "Deactivate" : "Activate"}
          </button>
          <button
            type="button"
            onClick={onArchive}
            className="rounded-md border border-ap-line bg-ap-panel px-2 py-1 text-xs font-medium text-ap-ink hover:bg-ap-line/40"
          >
            Archive
          </button>
        </div>
      ) : null}
    </li>
  );
}

const inputCls =
  "w-full rounded-md border border-ap-line bg-white px-2 py-1 text-sm text-ap-ink shadow-sm focus:border-ap-primary focus:outline-none focus:ring-1 focus:ring-ap-primary disabled:bg-ap-line/30";

function Field({
  label,
  children,
  className,
}: {
  label: string;
  children: ReactNode;
  className?: string;
}): ReactNode {
  return (
    <label className={`flex flex-col gap-1 ${className ?? ""}`}>
      <span className="text-xs font-medium text-ap-muted">{label}</span>
      {children}
    </label>
  );
}
