import { formatDistanceToNow, parseISO } from "date-fns";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Navigate } from "react-router-dom";

import {
  type SignalDefinition,
  type SignalObservationCreatePayload,
  initSignalAttachment,
  uploadAttachmentToS3,
} from "@/api/signals";
import { Pill } from "@/components/Pill";
import { Skeleton } from "@/components/Skeleton";
import { useActiveFarmId } from "@/hooks/useActiveFarm";
import { useDateLocale } from "@/hooks/useDateLocale";
import { useCapability } from "@/rbac/useCapability";
import {
  useCreateSignalObservation,
  useSignalDefinitions,
  useSignalObservations,
} from "@/queries/signals";

export function SignalsLogPage(): ReactNode {
  const farmId = useActiveFarmId();
  const { t } = useTranslation("signals");
  const canRecord = useCapability("signal.record", { farmId });
  const { data: defs, isLoading: defsLoading } = useSignalDefinitions();
  const [selectedDefId, setSelectedDefId] = useState<string | null>(null);

  // Auto-select the first definition once data lands.
  useEffect(() => {
    if (selectedDefId === null && defs && defs.length > 0) {
      setSelectedDefId(defs[0].id);
    }
  }, [defs, selectedDefId]);

  const selectedDef = useMemo(
    () => defs?.find((d) => d.id === selectedDefId) ?? null,
    [defs, selectedDefId],
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

      {defsLoading ? (
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
      )}
    </div>
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

function ValueInput({
  defn,
  valueText,
  setValueText,
  valueBool,
  setValueBool,
  lat,
  setLat,
  lon,
  setLon,
}: {
  defn: SignalDefinition;
  valueText: string;
  setValueText: (v: string) => void;
  valueBool: boolean;
  setValueBool: (v: boolean) => void;
  lat: string;
  setLat: (v: string) => void;
  lon: string;
  setLon: (v: string) => void;
}): ReactNode {
  const { t } = useTranslation("signals");
  if (defn.value_kind === "numeric") {
    return (
      <Field
        label={defn.unit ? t("log.form.valueWithUnit", { unit: defn.unit }) : t("log.form.value")}
      >
        <input
          required
          inputMode="decimal"
          value={valueText}
          onChange={(e) => setValueText(e.target.value)}
          className={inputCls}
        />
      </Field>
    );
  }
  if (defn.value_kind === "categorical") {
    return (
      <Field label={t("log.form.value")}>
        <select
          required
          value={valueText}
          onChange={(e) => setValueText(e.target.value)}
          className={inputCls}
        >
          <option value="" disabled>
            {t("log.form.pickOne")}
          </option>
          {(defn.categorical_values ?? []).map((v) => (
            <option key={v} value={v}>
              {v}
            </option>
          ))}
        </select>
      </Field>
    );
  }
  if (defn.value_kind === "event") {
    return (
      <Field label={t("log.form.description")}>
        <input
          required
          maxLength={500}
          value={valueText}
          onChange={(e) => setValueText(e.target.value)}
          className={inputCls}
        />
      </Field>
    );
  }
  if (defn.value_kind === "boolean") {
    return (
      <Field label={t("log.form.value")}>
        <label className="inline-flex items-center gap-2">
          <input
            type="checkbox"
            checked={valueBool}
            onChange={(e) => setValueBool(e.target.checked)}
          />
          <span>{valueBool ? "true" : "false"}</span>
        </label>
      </Field>
    );
  }
  // geopoint
  return (
    <div className="grid grid-cols-2 gap-3">
      <Field label={t("log.form.lat")}>
        <input
          required
          inputMode="decimal"
          value={lat}
          onChange={(e) => setLat(e.target.value)}
          className={inputCls}
        />
      </Field>
      <Field label={t("log.form.lon")}>
        <input
          required
          inputMode="decimal"
          value={lon}
          onChange={(e) => setLon(e.target.value)}
          className={inputCls}
        />
      </Field>
    </div>
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

function Field({ label, children }: { label: string; children: ReactNode }): ReactNode {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs font-medium text-ap-muted">{label}</span>
      {children}
    </label>
  );
}
