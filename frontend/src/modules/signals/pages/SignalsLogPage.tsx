import { useQuery } from "@tanstack/react-query";
import { formatDistanceToNow, parseISO } from "date-fns";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Navigate } from "react-router-dom";

import { listBlocks } from "@/api/blocks";
import {
  type SignalDefinition,
  type SignalObservationCreatePayload,
  type SignalTemplate,
  type SignalTemplateObservationCreatePayload,
  type SignalTemplateObservationMemberSubmission,
  initSignalAttachment,
  uploadAttachmentToS3,
} from "@/api/signals";
import { Pill } from "@/components/Pill";
import { Skeleton } from "@/components/Skeleton";
import { useActiveFarmId } from "@/hooks/useActiveFarm";
import { useDateLocale } from "@/hooks/useDateLocale";
import { useCapability } from "@/rbac/useCapability";
import { SignalsCsvImport } from "../components/SignalsCsvImport";
import { ObservedAtPicker } from "../components/ObservedAtPicker";
import { ValueInput } from "../components/ValueInput";
import {
  useCreateSignalObservation,
  useCreateTemplateObservation,
  useSignalDefinitions,
  useSignalObservations,
  useSignalTemplate,
  useSignalTemplates,
} from "@/queries/signals";

type Mode = "single" | "template";

export function SignalsLogPage(): ReactNode {
  const farmId = useActiveFarmId();
  const { t } = useTranslation("signals");
  const canRecord = useCapability("signal.record", { farmId });
  const { data: defs, isLoading: defsLoading } = useSignalDefinitions();
  const { data: templates, isLoading: tplsLoading } = useSignalTemplates();
  const [mode, setMode] = useState<Mode>("single");
  const [selectedDefId, setSelectedDefId] = useState<string | null>(null);
  const [selectedTplId, setSelectedTplId] = useState<string | null>(null);

  // Auto-select the first definition / template once data lands.
  useEffect(() => {
    if (selectedDefId === null && defs && defs.length > 0) {
      setSelectedDefId(defs[0].id);
    }
  }, [defs, selectedDefId]);
  useEffect(() => {
    if (selectedTplId === null && templates && templates.length > 0) {
      const firstActive = templates.find((t) => t.is_active) ?? templates[0];
      setSelectedTplId(firstActive.id);
    }
  }, [templates, selectedTplId]);

  const selectedDef = useMemo(
    () => defs?.find((d) => d.id === selectedDefId) ?? null,
    [defs, selectedDefId],
  );
  const activeTemplates = useMemo(
    () => (templates ?? []).filter((t) => t.is_active),
    [templates],
  );
  const selectedTpl = useMemo(
    () => activeTemplates.find((t) => t.id === selectedTplId) ?? null,
    [activeTemplates, selectedTplId],
  );

  const { data: observations, isLoading: obsLoading } = useSignalObservations({
    farm_id: farmId,
    limit: 50,
  });

  if (!farmId) {
    return <Navigate to="/" replace />;
  }

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-4">
      <header>
        <h1 className="text-2xl font-semibold text-ap-ink">{t("log.title")}</h1>
        <p className="mt-1 text-sm text-ap-muted">{t("log.subtitle")}</p>
      </header>

      {/* Bulk import — same capability gate as the record form (signal.record).
          Operators who can submit one observation can submit many. The
          widget renders its own success/error state inline. */}
      {canRecord ? <SignalsCsvImport farmId={farmId} /> : null}

      <div
        className="inline-flex rounded-md border border-ap-line bg-ap-panel p-0.5 text-xs"
        role="tablist"
        aria-label={t("log.mode.label")}
      >
        <ModeTab active={mode === "single"} onClick={() => setMode("single")}>
          {t("log.mode.single")}
        </ModeTab>
        <ModeTab active={mode === "template"} onClick={() => setMode("template")}>
          {t("log.mode.template")}
        </ModeTab>
      </div>

      {mode === "single" ? (
        defsLoading ? (
          <Skeleton className="h-64 w-full rounded-xl" />
        ) : !defs || defs.length === 0 ? (
          <div className="rounded-xl border border-ap-line bg-ap-panel p-8 text-center text-sm text-ap-muted">
            {t("log.noDefinitions")}
          </div>
        ) : (
          <div className="grid gap-4 lg:grid-cols-[18rem_1fr]">
            <aside className="rounded-xl border border-ap-line bg-ap-panel p-2">
              <ul className="flex flex-col gap-0.5">
                {defs.map((d) => (
                  <li key={d.id}>
                    <button
                      type="button"
                      onClick={() => setSelectedDefId(d.id)}
                      className={`flex w-full flex-col items-start gap-0.5 rounded-md px-2 py-1.5 text-start text-sm hover:bg-ap-line/40 ${
                        selectedDefId === d.id ? "bg-ap-primary-soft text-ap-primary" : "text-ap-ink"
                      }`}
                    >
                      <span className="font-medium">{d.name}</span>
                      <span className="font-mono text-[10px] text-ap-muted">
                        {d.code} · {d.value_kind}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </aside>

            <section className="flex flex-col gap-3">
              {selectedDef ? (
                canRecord ? (
                  <RecordForm key={selectedDef.id} defn={selectedDef} farmId={farmId} />
                ) : (
                  <div className="rounded-xl border border-ap-line bg-ap-panel p-4 text-sm text-ap-muted">
                    {t("log.missingCapability", { capability: "signal.record" })}
                  </div>
                )
              ) : null}
              <ObservationList
                isLoading={obsLoading}
                observations={observations ?? []}
                definitionFilter={selectedDef?.id}
              />
            </section>
          </div>
        )
      ) : tplsLoading ? (
        <Skeleton className="h-64 w-full rounded-xl" />
      ) : activeTemplates.length === 0 ? (
        <div className="rounded-xl border border-ap-line bg-ap-panel p-8 text-center text-sm text-ap-muted">
          {t("log.template.empty")}
        </div>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[18rem_1fr]">
          <aside className="rounded-xl border border-ap-line bg-ap-panel p-2">
            <ul className="flex flex-col gap-0.5">
              {activeTemplates.map((tpl) => (
                <li key={tpl.id}>
                  <button
                    type="button"
                    onClick={() => setSelectedTplId(tpl.id)}
                    className={`flex w-full flex-col items-start gap-0.5 rounded-md px-2 py-1.5 text-start text-sm hover:bg-ap-line/40 ${
                      selectedTplId === tpl.id
                        ? "bg-ap-primary-soft text-ap-primary"
                        : "text-ap-ink"
                    }`}
                  >
                    <span className="font-medium">{tpl.name}</span>
                    <span className="font-mono text-[10px] text-ap-muted">{tpl.code}</span>
                  </button>
                </li>
              ))}
            </ul>
          </aside>

          <section className="flex flex-col gap-3">
            {selectedTpl ? (
              canRecord ? (
                <TemplateRecordForm
                  key={selectedTpl.id}
                  template={selectedTpl}
                  farmId={farmId}
                  definitions={defs ?? []}
                />
              ) : (
                <div className="rounded-xl border border-ap-line bg-ap-panel p-4 text-sm text-ap-muted">
                  {t("log.missingCapability", { capability: "signal.record" })}
                </div>
              )
            ) : null}
            <ObservationList
              isLoading={obsLoading}
              observations={observations ?? []}
              definitionFilter={undefined}
            />
          </section>
        </div>
      )}
    </div>
  );
}

function ModeTab({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: ReactNode;
}): ReactNode {
  return (
    <button
      type="button"
      onClick={onClick}
      role="tab"
      aria-selected={active}
      className={`rounded-sm px-3 py-1 font-medium ${
        active ? "bg-ap-primary text-white" : "text-ap-ink hover:bg-ap-line/40"
      }`}
    >
      {children}
    </button>
  );
}

function useFarmBlocks(farmId: string | undefined) {
  return useQuery({
    queryKey: ["blocks", "list", farmId] as const,
    queryFn: () => listBlocks(farmId!),
    enabled: Boolean(farmId),
    staleTime: 60_000,
  });
}

function BlockSelect({
  farmId,
  value,
  onChange,
}: {
  farmId: string;
  value: string | null;
  onChange: (v: string | null) => void;
}): ReactNode {
  const { t } = useTranslation("signals");
  const { data } = useFarmBlocks(farmId);
  const blocks = data?.items ?? [];
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs font-medium text-ap-muted">{t("log.form.block")}</span>
      <select
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value || null)}
        className={inputCls}
      >
        <option value="">{t("log.form.blockOptional")}</option>
        {blocks.map((b) => (
          <option key={b.id} value={b.id}>
            {b.name}
          </option>
        ))}
      </select>
    </label>
  );
}

function RecordForm({ defn, farmId }: { defn: SignalDefinition; farmId: string }): ReactNode {
  const { t } = useTranslation("signals");
  const create = useCreateSignalObservation();
  const [valueText, setValueText] = useState("");
  const [valueBool, setValueBool] = useState(false);
  const [lat, setLat] = useState("");
  const [lon, setLon] = useState("");
  const [notes, setNotes] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [observedAt, setObservedAt] = useState<string | null>(null);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    const payload: SignalObservationCreatePayload = { farm_id: farmId };
    if (defn.value_kind === "numeric") payload.value_numeric = valueText;
    else if (defn.value_kind === "categorical") payload.value_categorical = valueText;
    else if (defn.value_kind === "event") payload.value_event = valueText;
    else if (defn.value_kind === "boolean") payload.value_boolean = valueBool;
    else if (defn.value_kind === "geopoint") {
      const latNum = Number.parseFloat(lat);
      const lonNum = Number.parseFloat(lon);
      if (Number.isNaN(latNum) || Number.isNaN(lonNum)) {
        setError(t("log.form.errorLatLon"));
        return;
      }
      payload.value_geopoint = { latitude: latNum, longitude: lonNum };
    }
    if (notes.trim()) payload.notes = notes.trim();
    // Backwards-compat: untouched picker submits no `time`; server falls
    // back to now(), preserving CS-1..CS-8 client behavior.
    if (observedAt) payload.time = observedAt;

    try {
      if (defn.attachment_allowed && file) {
        setUploading(true);
        const init = await initSignalAttachment({
          signal_definition_id: defn.id,
          farm_id: farmId,
          content_type: file.type || "application/octet-stream",
          content_length: file.size,
          filename: file.name,
        });
        await uploadAttachmentToS3(init, file);
        payload.attachment_s3_key = init.attachment_s3_key;
        setUploading(false);
      }
      await create.mutateAsync({ definitionId: defn.id, payload });
      setValueText("");
      setValueBool(false);
      setLat("");
      setLon("");
      setNotes("");
      setFile(null);
      setObservedAt(null);
    } catch (err) {
      setUploading(false);
      const message = err instanceof Error ? err.message : t("log.form.errorGeneric");
      setError(message);
    }
  };

  return (
    <form
      onSubmit={submit}
      className="flex flex-col gap-3 rounded-xl border border-ap-line bg-ap-panel p-4 text-sm"
    >
      <div className="flex items-center gap-2">
        <span className="text-sm font-medium text-ap-ink">{defn.name}</span>
        <Pill kind="info">{t(`valueKind.${defn.value_kind}`)}</Pill>
        {defn.unit ? (
          <span className="text-xs text-ap-muted">{t("config.row.unit", { unit: defn.unit })}</span>
        ) : null}
      </div>
      <ValueInput
        defn={defn}
        valueText={valueText}
        setValueText={setValueText}
        valueBool={valueBool}
        setValueBool={setValueBool}
        lat={lat}
        setLat={setLat}
        lon={lon}
        setLon={setLon}
      />
      <ObservedAtPicker value={observedAt} onChange={setObservedAt} />
      <label className="flex flex-col gap-1">
        <span className="text-xs font-medium text-ap-muted">{t("log.form.notes")}</span>
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          rows={2}
          className="w-full rounded-md border border-ap-line bg-white px-2 py-1 text-sm shadow-sm focus:border-ap-primary focus:outline-none focus:ring-1 focus:ring-ap-primary"
        />
      </label>
      {defn.attachment_allowed ? (
        <label className="flex flex-col gap-1">
          <span className="text-xs font-medium text-ap-muted">{t("log.form.photo")}</span>
          <input
            type="file"
            accept="image/*"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="text-xs"
          />
        </label>
      ) : null}
      <div className="flex items-center justify-end gap-2">
        {error ? <span className="text-xs text-ap-crit">{error}</span> : null}
        <button
          type="submit"
          disabled={create.isPending || uploading}
          className="rounded-md bg-ap-primary px-3 py-1.5 text-sm font-medium text-white hover:bg-ap-primary/90 disabled:opacity-60"
        >
          {uploading
            ? t("log.form.uploading")
            : create.isPending
              ? t("log.form.recording")
              : t("log.form.record")}
        </button>
      </div>
    </form>
  );
}

// ---- Template entry -------------------------------------------------------

interface MemberDraft {
  valueText: string;
  valueBool: boolean;
  lat: string;
  lon: string;
}

const EMPTY_MEMBER_DRAFT: MemberDraft = {
  valueText: "",
  valueBool: false,
  lat: "",
  lon: "",
};

function buildMemberSubmission(
  defn: SignalDefinition,
  draft: MemberDraft,
): SignalTemplateObservationMemberSubmission | null {
  const sub: SignalTemplateObservationMemberSubmission = {
    signal_definition_id: defn.id,
  };
  switch (defn.value_kind) {
    case "numeric":
      if (!draft.valueText.trim()) return null;
      sub.value_numeric = draft.valueText;
      return sub;
    case "categorical":
      if (!draft.valueText) return null;
      sub.value_categorical = draft.valueText;
      return sub;
    case "event":
      if (!draft.valueText.trim()) return null;
      sub.value_event = draft.valueText;
      return sub;
    case "boolean":
      // Boolean is tri-state in spirit (true/false/blank). The current
      // ValueInput doesn't model "blank", so a boolean member always
      // submits whatever the checkbox shows. CS-16 covers tri-state.
      sub.value_boolean = draft.valueBool;
      return sub;
    case "geopoint": {
      if (!draft.lat.trim() || !draft.lon.trim()) return null;
      const latNum = Number.parseFloat(draft.lat);
      const lonNum = Number.parseFloat(draft.lon);
      if (Number.isNaN(latNum) || Number.isNaN(lonNum)) return null;
      sub.value_geopoint = { latitude: latNum, longitude: lonNum };
      return sub;
    }
  }
  return null;
}

export function TemplateRecordForm({
  template,
  farmId,
  definitions,
}: {
  template: SignalTemplate;
  farmId: string;
  definitions: SignalDefinition[];
}): ReactNode {
  const { t } = useTranslation("signals");
  const { data: detail, isLoading: detailLoading } = useSignalTemplate(template.id);
  const create = useCreateTemplateObservation();
  const [drafts, setDrafts] = useState<Record<string, MemberDraft>>({});
  const [notes, setNotes] = useState("");
  const [observedAt, setObservedAt] = useState<string | null>(null);
  const [blockId, setBlockId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const orderedMembers = useMemo(() => {
    if (!detail) return [];
    return detail.members
      .slice()
      .sort((a, b) => a.position - b.position)
      .map((m) => {
        const defn = definitions.find((d) => d.id === m.signal_definition_id);
        return defn ? { member: m, defn } : null;
      })
      .filter((x): x is { member: typeof detail.members[number]; defn: SignalDefinition } =>
        Boolean(x),
      );
  }, [detail, definitions]);

  const getDraft = (id: string): MemberDraft => drafts[id] ?? EMPTY_MEMBER_DRAFT;
  const patch = (id: string, p: Partial<MemberDraft>) =>
    setDrafts((s) => ({ ...s, [id]: { ...(s[id] ?? EMPTY_MEMBER_DRAFT), ...p } }));

  const reset = () => {
    setDrafts({});
    setNotes("");
    setObservedAt(null);
    setBlockId(null);
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    const memberSubs: SignalTemplateObservationMemberSubmission[] = [];
    for (const { member, defn } of orderedMembers) {
      const draft = getDraft(defn.id);
      const sub = buildMemberSubmission(defn, draft);
      if (sub) {
        if (notes.trim()) sub.notes = notes.trim();
        memberSubs.push(sub);
      } else if (member.is_required) {
        setError(t("log.template.requiredMissing", { name: defn.name }));
        return;
      }
    }
    if (memberSubs.length === 0) {
      setError(t("log.template.emptySubmission"));
      return;
    }
    const payload: SignalTemplateObservationCreatePayload = {
      farm_id: farmId,
      block_id: blockId,
      observed_at: observedAt,
      members: memberSubs,
    };
    try {
      await create.mutateAsync({ templateId: template.id, payload });
      reset();
    } catch (err) {
      const message = err instanceof Error ? err.message : t("log.form.errorGeneric");
      setError(message);
    }
  };

  if (detailLoading) {
    return <Skeleton className="h-64 w-full rounded-xl" />;
  }

  return (
    <form
      onSubmit={submit}
      className="flex flex-col gap-3 rounded-xl border border-ap-line bg-ap-panel p-4 text-sm"
    >
      <div>
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-ap-ink">{template.name}</span>
          <span className="font-mono text-[11px] text-ap-muted">{template.code}</span>
        </div>
        {template.description ? (
          <p className="mt-1 text-xs text-ap-muted">{template.description}</p>
        ) : null}
      </div>

      {orderedMembers.length === 0 ? (
        <p className="rounded-md border border-dashed border-ap-line p-3 text-xs text-ap-muted">
          {t("log.template.noMembers")}
        </p>
      ) : (
        <div className="flex flex-col gap-3">
          {orderedMembers.map(({ member, defn }) => {
            const draft = getDraft(defn.id);
            return (
              <div
                key={defn.id}
                className="flex flex-col gap-1 rounded-md border border-ap-line p-3"
              >
                <div className="flex items-center gap-2">
                  <span className="text-xs font-semibold text-ap-ink">{defn.name}</span>
                  <span className="font-mono text-[10px] text-ap-muted">{defn.code}</span>
                  {member.is_required ? (
                    <span
                      aria-label={t("config.templates.memberPicker.required")}
                      className="text-[11px] font-medium text-ap-crit"
                    >
                      * {t("config.templates.memberPicker.required")}
                    </span>
                  ) : null}
                </div>
                <ValueInput
                  defn={defn}
                  valueText={draft.valueText}
                  setValueText={(v) => patch(defn.id, { valueText: v })}
                  valueBool={draft.valueBool}
                  setValueBool={(v) => patch(defn.id, { valueBool: v })}
                  lat={draft.lat}
                  setLat={(v) => patch(defn.id, { lat: v })}
                  lon={draft.lon}
                  setLon={(v) => patch(defn.id, { lon: v })}
                  optional
                />
              </div>
            );
          })}
        </div>
      )}

      <ObservedAtPicker value={observedAt} onChange={setObservedAt} />
      <BlockSelect farmId={farmId} value={blockId} onChange={setBlockId} />
      <label className="flex flex-col gap-1">
        <span className="text-xs font-medium text-ap-muted">{t("log.form.notes")}</span>
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          rows={2}
          className="w-full rounded-md border border-ap-line bg-white px-2 py-1 text-sm shadow-sm focus:border-ap-primary focus:outline-none focus:ring-1 focus:ring-ap-primary"
        />
      </label>

      <div className="flex items-center justify-end gap-2">
        {error ? <span className="text-xs text-ap-crit">{error}</span> : null}
        <button
          type="submit"
          disabled={create.isPending || orderedMembers.length === 0}
          className="rounded-md bg-ap-primary px-3 py-1.5 text-sm font-medium text-white hover:bg-ap-primary/90 disabled:opacity-60"
        >
          {create.isPending ? t("log.form.recording") : t("log.template.submit")}
        </button>
      </div>
    </form>
  );
}

function ObservationList({
  isLoading,
  observations,
  definitionFilter,
}: {
  isLoading: boolean;
  observations: ReturnType<typeof useSignalObservations>["data"] extends infer T
    ? T extends Array<infer R>
      ? R[]
      : never
    : never;
  definitionFilter: string | undefined;
}): ReactNode {
  const { t } = useTranslation("signals");
  const dateLocale = useDateLocale();
  const filtered = definitionFilter
    ? observations.filter((o) => o.signal_definition_id === definitionFilter)
    : observations;
  return (
    <div className="rounded-xl border border-ap-line bg-ap-panel">
      <div className="flex items-center justify-between border-b border-ap-line px-4 py-2">
        <span className="text-xs font-semibold uppercase tracking-wider text-ap-muted">
          {t("log.list.heading")}
        </span>
        <span className="text-xs text-ap-muted">{filtered.length}</span>
      </div>
      {isLoading ? (
        <div className="flex flex-col gap-2 p-4">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
        </div>
      ) : filtered.length === 0 ? (
        <p className="p-6 text-center text-xs text-ap-muted">{t("log.list.empty")}</p>
      ) : (
        <ul className="divide-y divide-ap-line">
          {filtered.map((o) => (
            <li key={o.id} className="flex flex-wrap items-center gap-2 px-4 py-2 text-sm">
              <span className="font-mono text-xs text-ap-muted">{o.signal_code}</span>
              <span className="font-medium text-ap-ink">{formatValue(o)}</span>
              {o.notes ? <span className="text-xs text-ap-muted">— {o.notes}</span> : null}
              <span className="ms-auto text-[11px] text-ap-muted">
                {formatDistanceToNow(parseISO(o.time), {
                  addSuffix: true,
                  locale: dateLocale,
                })}
              </span>
              {o.attachment_download_url ? (
                <a
                  href={o.attachment_download_url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-[11px] font-medium text-ap-primary hover:underline"
                >
                  {t("log.list.photo")}
                </a>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function formatValue(o: {
  value_numeric: string | null;
  value_categorical: string | null;
  value_event: string | null;
  value_boolean: boolean | null;
  value_geopoint: { latitude: number; longitude: number } | null;
}): string {
  if (o.value_numeric !== null) return o.value_numeric;
  if (o.value_categorical !== null) return o.value_categorical;
  if (o.value_event !== null) return o.value_event;
  if (o.value_boolean !== null) return String(o.value_boolean);
  if (o.value_geopoint) return `${o.value_geopoint.latitude}, ${o.value_geopoint.longitude}`;
  return "—";
}

const inputCls =
  "w-full rounded-md border border-ap-line bg-white px-2 py-1 text-sm shadow-sm focus:border-ap-primary focus:outline-none focus:ring-1 focus:ring-ap-primary";
