import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Navigate } from "react-router-dom";

import type {
  Aggregation,
  SignalDefinition,
  SignalDefinitionCreatePayload,
  SignalTemplate,
  SignalTemplateCreatePayload,
  SignalTemplateMember,
  SignalTemplateUpdatePayload,
  ValueKind,
} from "@/api/signals";
import { Pill } from "@/components/Pill";
import { Skeleton } from "@/components/Skeleton";
import { useActiveFarmId } from "@/hooks/useActiveFarm";
import { useCapability } from "@/rbac/useCapability";
import {
  useCreateSignalDefinition,
  useCreateSignalTemplate,
  useDeleteSignalDefinition,
  useDeleteSignalTemplate,
  useSignalDefinitions,
  useSignalTemplate,
  useSignalTemplates,
  useUpdateSignalDefinition,
  useUpdateSignalTemplate,
} from "@/queries/signals";

const VALUE_KINDS: ValueKind[] = ["numeric", "categorical", "event", "boolean", "geopoint"];
const AGGREGATIONS: Aggregation[] = ["latest", "mean", "median", "max", "min"];

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
  aggregation: Aggregation;
  aggregation_window_days: string;
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
  aggregation: "latest",
  aggregation_window_days: "",
};

export function SignalsConfigPage(): ReactNode {
  const farmId = useActiveFarmId();
  const { t } = useTranslation("signals");
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
    const isNumeric = form.value_kind === "numeric";
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
      aggregation: isNumeric ? form.aggregation : "latest",
      aggregation_window_days:
        isNumeric && form.aggregation_window_days
          ? Number.parseInt(form.aggregation_window_days, 10)
          : null,
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
          <h1 className="text-2xl font-semibold text-ap-ink">{t("config.title")}</h1>
          <p className="mt-1 text-sm text-ap-muted">{t("config.subtitle")}</p>
        </div>
        {canDefine ? (
          <button
            type="button"
            onClick={() => setShowForm((s) => !s)}
            className="rounded-md bg-ap-primary px-3 py-1.5 text-sm font-medium text-white hover:bg-ap-primary/90"
          >
            {showForm ? t("config.cancel") : t("config.newDefinition")}
          </button>
        ) : null}
      </header>

      {showForm && canDefine ? (
        <form
          onSubmit={submit}
          className="rounded-xl border border-ap-line bg-ap-panel p-4 text-sm"
        >
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Field label={t("config.form.code")}>
              <input
                required
                value={form.code}
                onChange={(e) => setForm({ ...form, code: e.target.value })}
                placeholder={t("config.form.codePlaceholder")}
                pattern="^[a-z0-9][a-z0-9_-]*$"
                className={inputCls}
              />
            </Field>
            <Field label={t("config.form.name")}>
              <input
                required
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder={t("config.form.namePlaceholder")}
                className={inputCls}
              />
            </Field>
            <Field label={t("config.form.valueKind")}>
              <select
                value={form.value_kind}
                onChange={(e) => setForm({ ...form, value_kind: e.target.value as ValueKind })}
                className={inputCls}
              >
                {VALUE_KINDS.map((k) => (
                  <option key={k} value={k}>
                    {t(`valueKind.${k}`)}
                  </option>
                ))}
              </select>
            </Field>
            <Field label={t("config.form.unit")}>
              <input
                value={form.unit}
                onChange={(e) => setForm({ ...form, unit: e.target.value })}
                placeholder={t("config.form.unitPlaceholder")}
                className={inputCls}
                disabled={form.value_kind !== "numeric"}
              />
            </Field>
            {form.value_kind === "numeric" ? (
              <>
                <Field label={t("config.form.min")}>
                  <input
                    inputMode="decimal"
                    value={form.value_min}
                    onChange={(e) => setForm({ ...form, value_min: e.target.value })}
                    className={inputCls}
                  />
                </Field>
                <Field label={t("config.form.max")}>
                  <input
                    inputMode="decimal"
                    value={form.value_max}
                    onChange={(e) => setForm({ ...form, value_max: e.target.value })}
                    className={inputCls}
                  />
                </Field>
                <Field label={t("config.form.aggregation.label")}>
                  <select
                    value={form.aggregation}
                    onChange={(e) =>
                      setForm({ ...form, aggregation: e.target.value as Aggregation })
                    }
                    className={inputCls}
                  >
                    {AGGREGATIONS.map((a) => (
                      <option key={a} value={a}>
                        {t(`config.form.aggregation.options.${a}`)}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label={t("config.form.aggregation.windowLabel")}>
                  <input
                    type="number"
                    min={1}
                    step={1}
                    value={form.aggregation_window_days}
                    onChange={(e) =>
                      setForm({ ...form, aggregation_window_days: e.target.value })
                    }
                    placeholder={t("config.form.aggregation.windowHint")}
                    className={inputCls}
                    disabled={form.aggregation === "latest"}
                  />
                </Field>
              </>
            ) : null}
            {form.value_kind === "categorical" ? (
              <Field label={t("config.form.categoricalValues")} className="sm:col-span-2">
                <input
                  required
                  value={form.categorical_values}
                  onChange={(e) => setForm({ ...form, categorical_values: e.target.value })}
                  placeholder={t("config.form.categoricalPlaceholder")}
                  className={inputCls}
                />
              </Field>
            ) : null}
            <Field label={t("config.form.description")} className="sm:col-span-2">
              <input
                value={form.description}
                onChange={(e) => setForm({ ...form, description: e.target.value })}
                className={inputCls}
              />
            </Field>
            <Field label={t("config.form.attachmentAllowed")} className="sm:col-span-2">
              <label className="inline-flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={form.attachment_allowed}
                  onChange={(e) => setForm({ ...form, attachment_allowed: e.target.checked })}
                />
                <span>{t("config.form.attachmentHint")}</span>
              </label>
            </Field>
          </div>
          <div className="mt-3 flex items-center justify-end gap-2">
            {createMut.isError ? (
              <span className="text-xs text-ap-crit">
                {createMut.error?.message ?? t("config.form.saveFailed")}
              </span>
            ) : null}
            <button
              type="submit"
              disabled={createMut.isPending}
              className="rounded-md bg-ap-primary px-3 py-1.5 text-sm font-medium text-white hover:bg-ap-primary/90 disabled:opacity-60"
            >
              {createMut.isPending ? t("config.form.saving") : t("config.form.save")}
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
          <p className="p-4 text-sm text-ap-crit">{t("config.loadFailed")}</p>
        ) : !data || data.length === 0 ? (
          <p className="p-12 text-center text-sm text-ap-muted">{t("config.empty")}</p>
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

      <TemplatesCard canDefine={canDefine} definitions={data ?? []} />
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
  const { t } = useTranslation("signals");
  const valueRange = useMemo(() => {
    if (defn.value_kind !== "numeric") return null;
    if (defn.value_min === null && defn.value_max === null) return null;
    return `${defn.value_min ?? "−∞"} … ${defn.value_max ?? "∞"} ${defn.unit ?? ""}`.trim();
  }, [defn]);
  const aggLabel = useMemo(() => {
    if (defn.value_kind !== "numeric") return null;
    if (defn.aggregation === "latest") return t("config.form.aggregation.options.latest");
    const rule = t(`config.form.aggregation.options.${defn.aggregation}`);
    return defn.aggregation_window_days
      ? `${rule} / ${defn.aggregation_window_days}d`
      : rule;
  }, [defn, t]);
  return (
    <li className="flex items-start gap-3 p-4">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-medium text-ap-ink">{defn.name}</span>
          <span className="font-mono text-[11px] text-ap-muted">{defn.code}</span>
          <Pill kind={defn.is_active ? "ok" : "neutral"}>
            {defn.is_active ? t("config.row.active") : t("config.row.inactive")}
          </Pill>
          <Pill kind="info">{t(`valueKind.${defn.value_kind}`)}</Pill>
          {aggLabel ? <Pill kind="neutral">{aggLabel}</Pill> : null}
          {defn.attachment_allowed ? <Pill kind="neutral">{t("config.row.photos")}</Pill> : null}
        </div>
        {defn.description ? <p className="mt-1 text-sm text-ap-muted">{defn.description}</p> : null}
        <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-ap-muted">
          {defn.value_kind === "numeric" && defn.unit ? (
            <span>{t("config.row.unit", { unit: defn.unit })}</span>
          ) : null}
          {valueRange ? <span>{t("config.row.range", { range: valueRange })}</span> : null}
          {defn.categorical_values ? (
            <span>{t("config.row.values", { values: defn.categorical_values.join(", ") })}</span>
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
            {defn.is_active ? t("config.row.deactivate") : t("config.row.activate")}
          </button>
          <button
            type="button"
            onClick={onArchive}
            className="rounded-md border border-ap-line bg-ap-panel px-2 py-1 text-xs font-medium text-ap-ink hover:bg-ap-line/40"
          >
            {t("config.row.archive")}
          </button>
        </div>
      ) : null}
    </li>
  );
}

// ---- Templates ------------------------------------------------------------

interface TemplateFormState {
  code: string;
  name: string;
  description: string;
  members: SignalTemplateMember[];
}

const EMPTY_TEMPLATE_FORM: TemplateFormState = {
  code: "",
  name: "",
  description: "",
  members: [],
};

function TemplatesCard({
  canDefine,
  definitions,
}: {
  canDefine: boolean;
  definitions: SignalDefinition[];
}): ReactNode {
  const { t } = useTranslation("signals");
  const { data: templates, isLoading } = useSignalTemplates(true);
  const createMut = useCreateSignalTemplate();
  const updateMut = useUpdateSignalTemplate();
  const deleteMut = useDeleteSignalTemplate();
  const [editingId, setEditingId] = useState<string | null>(null);
  const [showNew, setShowNew] = useState(false);

  const startNew = () => {
    setEditingId(null);
    setShowNew(true);
  };
  const stop = () => {
    setEditingId(null);
    setShowNew(false);
  };

  const onCreate = (payload: SignalTemplateCreatePayload) => {
    void createMut.mutateAsync(payload).then(stop);
  };
  const onUpdate = (id: string, payload: SignalTemplateUpdatePayload) => {
    void updateMut.mutateAsync({ id, payload }).then(stop);
  };

  return (
    <section className="rounded-xl border border-ap-line bg-ap-panel">
      <header className="flex items-center justify-between border-b border-ap-line px-4 py-2">
        <div>
          <h2 className="text-sm font-semibold text-ap-ink">{t("config.templates.heading")}</h2>
          <p className="mt-0.5 text-xs text-ap-muted">{t("config.templates.subtitle")}</p>
        </div>
        {canDefine && !showNew && editingId === null ? (
          <button
            type="button"
            onClick={startNew}
            className="rounded-md bg-ap-primary px-3 py-1 text-xs font-medium text-white hover:bg-ap-primary/90"
          >
            {t("config.templates.new")}
          </button>
        ) : null}
      </header>

      {showNew && canDefine ? (
        <div className="border-b border-ap-line p-4">
          <TemplateEditor
            mode="create"
            definitions={definitions}
            initial={EMPTY_TEMPLATE_FORM}
            onSubmit={(s) =>
              onCreate({
                code: s.code.trim(),
                name: s.name.trim(),
                description: s.description.trim() || null,
                members: s.members,
              })
            }
            onCancel={stop}
            isSubmitting={createMut.isPending}
            error={createMut.error?.message ?? null}
          />
        </div>
      ) : null}

      {isLoading ? (
        <div className="flex flex-col gap-2 p-4">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
        </div>
      ) : !templates || templates.length === 0 ? (
        <p className="p-8 text-center text-xs text-ap-muted">{t("config.templates.empty")}</p>
      ) : (
        <ul className="divide-y divide-ap-line">
          {templates.map((tpl) =>
            editingId === tpl.id ? (
              <li key={tpl.id} className="p-4">
                <TemplateEditor
                  mode="edit"
                  definitions={definitions}
                  templateId={tpl.id}
                  fallback={{
                    code: tpl.code,
                    name: tpl.name,
                    description: tpl.description ?? "",
                    members: [],
                  }}
                  onSubmit={(s) =>
                    onUpdate(tpl.id, {
                      name: s.name.trim(),
                      description: s.description.trim() || null,
                      members: s.members,
                    })
                  }
                  onCancel={stop}
                  isSubmitting={updateMut.isPending}
                  error={updateMut.error?.message ?? null}
                />
              </li>
            ) : (
              <TemplateRow
                key={tpl.id}
                template={tpl}
                canEdit={canDefine}
                onEdit={() => {
                  setShowNew(false);
                  setEditingId(tpl.id);
                }}
                onArchive={() => deleteMut.mutate(tpl.id)}
              />
            ),
          )}
        </ul>
      )}
    </section>
  );
}

function TemplateRow({
  template,
  canEdit,
  onEdit,
  onArchive,
}: {
  template: SignalTemplate;
  canEdit: boolean;
  onEdit: () => void;
  onArchive: () => void;
}): ReactNode {
  const { t } = useTranslation("signals");
  const { data: detail } = useSignalTemplate(template.id);
  const memberCount = detail?.members.length ?? null;
  return (
    <li className="flex items-start gap-3 p-4">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-medium text-ap-ink">{template.name}</span>
          <span className="font-mono text-[11px] text-ap-muted">{template.code}</span>
          <Pill kind={template.is_active ? "ok" : "neutral"}>
            {template.is_active ? t("config.row.active") : t("config.row.inactive")}
          </Pill>
          {memberCount !== null ? (
            <Pill kind="neutral">
              {t("config.templates.memberCount", { count: memberCount })}
            </Pill>
          ) : null}
        </div>
        {template.description ? (
          <p className="mt-1 text-sm text-ap-muted">{template.description}</p>
        ) : null}
      </div>
      {canEdit ? (
        <div className="flex flex-none gap-1">
          <button
            type="button"
            onClick={onEdit}
            className="rounded-md border border-ap-line bg-ap-panel px-2 py-1 text-xs font-medium text-ap-ink hover:bg-ap-line/40"
          >
            {t("config.templates.edit")}
          </button>
          <button
            type="button"
            onClick={onArchive}
            className="rounded-md border border-ap-line bg-ap-panel px-2 py-1 text-xs font-medium text-ap-ink hover:bg-ap-line/40"
          >
            {t("config.templates.archive")}
          </button>
        </div>
      ) : null}
    </li>
  );
}

interface TemplateEditorProps {
  mode: "create" | "edit";
  definitions: SignalDefinition[];
  /** For create-mode the caller supplies a starting state directly. */
  initial?: TemplateFormState;
  /** For edit-mode we hydrate from the detail endpoint, falling back to this. */
  templateId?: string;
  fallback?: TemplateFormState;
  onSubmit: (state: TemplateFormState) => void;
  onCancel: () => void;
  isSubmitting: boolean;
  error: string | null;
}

function TemplateEditor({
  mode,
  definitions,
  initial,
  templateId,
  fallback,
  onSubmit,
  onCancel,
  isSubmitting,
  error,
}: TemplateEditorProps): ReactNode {
  const { t } = useTranslation("signals");
  const { data: detail } = useSignalTemplate(mode === "edit" ? templateId : undefined);
  const [state, setState] = useState<TemplateFormState>(initial ?? fallback ?? EMPTY_TEMPLATE_FORM);
  const [hydrated, setHydrated] = useState(mode === "create");
  // For edit-mode, hydrate from server detail once.
  useEffect(() => {
    if (mode === "edit" && detail && !hydrated) {
      setState({
        code: detail.template.code,
        name: detail.template.name,
        description: detail.template.description ?? "",
        members: detail.members
          .slice()
          .sort((a, b) => a.position - b.position)
          .map((m) => ({
            signal_definition_id: m.signal_definition_id,
            position: m.position,
            is_required: m.is_required,
          })),
      });
      setHydrated(true);
    }
  }, [detail, hydrated, mode]);

  const defById = useMemo(() => {
    const map: Record<string, SignalDefinition> = {};
    for (const d of definitions) map[d.id] = d;
    return map;
  }, [definitions]);
  const memberIds = useMemo(() => new Set(state.members.map((m) => m.signal_definition_id)), [
    state.members,
  ]);
  const candidates = definitions.filter((d) => d.is_active && !memberIds.has(d.id));

  const addMember = (id: string) => {
    setState((s) => ({
      ...s,
      members: [
        ...s.members,
        { signal_definition_id: id, position: s.members.length, is_required: false },
      ],
    }));
  };
  const removeMember = (id: string) => {
    setState((s) => ({
      ...s,
      members: s.members
        .filter((m) => m.signal_definition_id !== id)
        .map((m, i) => ({ ...m, position: i })),
    }));
  };
  const move = (id: string, delta: -1 | 1) => {
    setState((s) => {
      const idx = s.members.findIndex((m) => m.signal_definition_id === id);
      const swapWith = idx + delta;
      if (idx < 0 || swapWith < 0 || swapWith >= s.members.length) return s;
      const next = s.members.slice();
      [next[idx], next[swapWith]] = [next[swapWith], next[idx]];
      return { ...s, members: next.map((m, i) => ({ ...m, position: i })) };
    });
  };
  const toggleRequired = (id: string, value: boolean) => {
    setState((s) => ({
      ...s,
      members: s.members.map((m) =>
        m.signal_definition_id === id ? { ...m, is_required: value } : m,
      ),
    }));
  };

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (state.members.length === 0) return;
    void onSubmit(state);
  };

  return (
    <form onSubmit={submit} className="flex flex-col gap-3 text-sm">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Field label={t("config.form.code")}>
          <input
            required
            value={state.code}
            onChange={(e) => setState({ ...state, code: e.target.value })}
            pattern="^[a-z0-9][a-z0-9_-]*$"
            disabled={mode === "edit"}
            className={inputCls}
          />
        </Field>
        <Field label={t("config.form.name")}>
          <input
            required
            value={state.name}
            onChange={(e) => setState({ ...state, name: e.target.value })}
            className={inputCls}
          />
        </Field>
        <Field label={t("config.form.description")} className="sm:col-span-2">
          <input
            value={state.description}
            onChange={(e) => setState({ ...state, description: e.target.value })}
            className={inputCls}
          />
        </Field>
      </div>

      <div className="flex flex-col gap-2">
        <span className="text-xs font-medium text-ap-muted">
          {t("config.templates.memberPicker.label")}
        </span>
        {state.members.length === 0 ? (
          <p className="rounded-md border border-dashed border-ap-line p-3 text-xs text-ap-muted">
            {t("config.templates.memberPicker.emptyHint")}
          </p>
        ) : (
          <ol className="flex flex-col gap-1">
            {state.members.map((m, i) => {
              const d = defById[m.signal_definition_id];
              return (
                <li
                  key={m.signal_definition_id}
                  className="flex items-center gap-2 rounded-md border border-ap-line bg-white px-2 py-1"
                >
                  <span className="text-xs text-ap-muted">{i + 1}.</span>
                  <span className="min-w-0 flex-1 truncate text-sm text-ap-ink">
                    {d ? d.name : m.signal_definition_id}
                    {d ? (
                      <span className="ms-1 font-mono text-[11px] text-ap-muted">{d.code}</span>
                    ) : null}
                  </span>
                  <label className="inline-flex items-center gap-1 text-[11px] text-ap-muted">
                    <input
                      type="checkbox"
                      checked={m.is_required}
                      onChange={(e) =>
                        toggleRequired(m.signal_definition_id, e.target.checked)
                      }
                    />
                    {t("config.templates.memberPicker.required")}
                  </label>
                  <button
                    type="button"
                    onClick={() => move(m.signal_definition_id, -1)}
                    disabled={i === 0}
                    aria-label={t("config.templates.memberPicker.moveUp")}
                    className="rounded border border-ap-line px-1 text-xs text-ap-ink hover:bg-ap-line/40 disabled:opacity-40"
                  >
                    ↑
                  </button>
                  <button
                    type="button"
                    onClick={() => move(m.signal_definition_id, 1)}
                    disabled={i === state.members.length - 1}
                    aria-label={t("config.templates.memberPicker.moveDown")}
                    className="rounded border border-ap-line px-1 text-xs text-ap-ink hover:bg-ap-line/40 disabled:opacity-40"
                  >
                    ↓
                  </button>
                  <button
                    type="button"
                    onClick={() => removeMember(m.signal_definition_id)}
                    className="rounded border border-ap-line px-1 text-xs text-ap-ink hover:bg-ap-line/40"
                    aria-label={t("config.templates.memberPicker.remove")}
                  >
                    ×
                  </button>
                </li>
              );
            })}
          </ol>
        )}
        <MemberAdder candidates={candidates} onAdd={addMember} />
      </div>

      <div className="flex items-center justify-end gap-2">
        {state.members.length === 0 ? (
          <span className="text-xs text-ap-crit">{t("config.templates.memberPicker.required_min")}</span>
        ) : null}
        {error ? <span className="text-xs text-ap-crit">{error}</span> : null}
        <button
          type="button"
          onClick={onCancel}
          className="rounded-md border border-ap-line bg-ap-panel px-3 py-1.5 text-xs font-medium text-ap-ink hover:bg-ap-line/40"
        >
          {t("config.cancel")}
        </button>
        <button
          type="submit"
          disabled={isSubmitting || state.members.length === 0}
          className="rounded-md bg-ap-primary px-3 py-1.5 text-xs font-medium text-white hover:bg-ap-primary/90 disabled:opacity-60"
        >
          {isSubmitting ? t("config.form.saving") : t("config.form.save")}
        </button>
      </div>
    </form>
  );
}

function MemberAdder({
  candidates,
  onAdd,
}: {
  candidates: SignalDefinition[];
  onAdd: (id: string) => void;
}): ReactNode {
  const { t } = useTranslation("signals");
  const [query, setQuery] = useState("");
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return candidates.slice(0, 8);
    return candidates
      .filter(
        (d) => d.name.toLowerCase().includes(q) || d.code.toLowerCase().includes(q),
      )
      .slice(0, 8);
  }, [candidates, query]);
  if (candidates.length === 0) {
    return (
      <p className="text-[11px] text-ap-muted">{t("config.templates.memberPicker.noMore")}</p>
    );
  }
  return (
    <div className="flex flex-col gap-1">
      <input
        type="search"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder={t("config.templates.memberPicker.searchPlaceholder")}
        className={inputCls}
      />
      {filtered.length === 0 ? (
        <p className="text-[11px] text-ap-muted">
          {t("config.templates.memberPicker.noMatches")}
        </p>
      ) : (
        <ul className="flex max-h-40 flex-col gap-0.5 overflow-auto">
          {filtered.map((d) => (
            <li key={d.id}>
              <button
                type="button"
                onClick={() => {
                  onAdd(d.id);
                  setQuery("");
                }}
                className="flex w-full items-center justify-between rounded-md px-2 py-1 text-start text-xs hover:bg-ap-line/40"
              >
                <span className="text-ap-ink">{d.name}</span>
                <span className="font-mono text-[10px] text-ap-muted">
                  {d.code} · {d.value_kind}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
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
