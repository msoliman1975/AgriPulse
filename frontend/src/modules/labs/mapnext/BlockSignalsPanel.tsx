// Record a signal observation against the block the inspector is already on,
// and read that block's full observation history underneath it.
//
// Before this panel the only capture surface was /signals → Log, where the
// operator re-picks the farm and then hunts for the block in a dropdown — the
// block context the console already has was thrown away, and mis-picking put
// the reading on the wrong unit silently.
//
// Unlike crop attributes, signals need no companion history table: every
// observation is an immutable timestamped row carrying `recorded_by`, so the
// list below IS the history. That is why this reuses `ObservationList`
// (pinned to the block) instead of growing a second history widget.
import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import {
  initSignalAttachment,
  uploadAttachmentToS3,
  type SignalDefinition,
  type SignalObservationCreatePayload,
} from "@/api/signals";
import { LocationCapture, type LocationValue } from "@/modules/signals/components/LocationCapture";
import { ObservationList } from "@/modules/signals/components/ObservationList";
import { ObservedAtPicker } from "@/modules/signals/components/ObservedAtPicker";
import { ValueInput } from "@/modules/signals/components/ValueInput";
import { useCreateSignalObservation, useSignalDefinitions } from "@/queries/signals";
import { useCapability } from "@/rbac/useCapability";

interface Props {
  blockId: string;
  farmId: string;
}

const inputCls =
  "w-full rounded-lg border border-ap-line bg-ap-panel px-3 py-2 text-sm text-ap-ink focus:border-ap-primary focus:outline-none";

const ENTITY_LOCATION: LocationValue = { location_mode: "entity", location_point: null };

export function BlockSignalsPanel({ blockId, farmId }: Props): ReactNode {
  const { t } = useTranslation("farmConsole");
  const canRecord = useCapability("signal.record", { farmId });
  const canDelete = useCapability("signal.delete_observation", { farmId });
  const { data: defs, isLoading, isError } = useSignalDefinitions(false, farmId);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  useEffect(() => {
    if (selectedId === null && defs && defs.length > 0) setSelectedId(defs[0].id);
  }, [defs, selectedId]);

  const selected = defs?.find((d) => d.id === selectedId) ?? null;

  if (isLoading) return <div className="text-sm text-ap-muted">{t("inspector.loading")}</div>;
  if (isError) return <div className="text-sm text-ap-crit">{t("signals.loadError")}</div>;
  if (!defs || defs.length === 0) {
    return <div className="text-sm text-ap-muted">{t("signals.noDefinitions")}</div>;
  }

  return (
    <div className="flex flex-col gap-3">
      {canRecord ? (
        <div className="rounded-xl border border-ap-line p-3">
          <label className="mb-3 block">
            <span className="mb-1 block text-xs font-semibold text-ap-muted">
              {t("signals.pickSignal")}
            </span>
            <select
              className={inputCls}
              value={selectedId ?? ""}
              onChange={(e) => setSelectedId(e.target.value || null)}
            >
              {defs.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name}
                </option>
              ))}
            </select>
          </label>
          {selected ? (
            <RecordForm
              key={`${selected.id}:${blockId}`}
              defn={selected}
              blockId={blockId}
              farmId={farmId}
            />
          ) : null}
        </div>
      ) : (
        <div className="rounded-xl border border-ap-line p-3 text-sm text-ap-muted">
          {t("signals.noRecordPermission")}
        </div>
      )}

      <div>
        <h4 className="mb-1 text-xs font-semibold uppercase tracking-wider text-ap-muted">
          {t("signals.historyHeading")}
        </h4>
        <ObservationList
          farmId={farmId}
          definitions={defs}
          canDelete={canDelete}
          lockedBlockId={blockId}
        />
      </div>
    </div>
  );
}

/**
 * Single-signal capture. Mirrors the RecordForm on the Signals Log page minus
 * the block picker — the block is the panel's subject and is not selectable.
 */
function RecordForm({
  defn,
  blockId,
  farmId,
}: {
  defn: SignalDefinition;
  blockId: string;
  farmId: string;
}): ReactNode {
  const { t } = useTranslation("farmConsole");
  const create = useCreateSignalObservation();

  const [valueText, setValueText] = useState("");
  const [valueBool, setValueBool] = useState(false);
  const [lat, setLat] = useState("");
  const [lon, setLon] = useState("");
  const [notes, setNotes] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [observedAt, setObservedAt] = useState<string | null>(null);
  const [location, setLocation] = useState<LocationValue>(ENTITY_LOCATION);
  const [locationReset, setLocationReset] = useState(0);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const submit = async (event: FormEvent): Promise<void> => {
    event.preventDefault();
    setError(null);
    setSaved(false);

    const payload: SignalObservationCreatePayload = { farm_id: farmId, block_id: blockId };
    if (defn.value_kind === "numeric") payload.value_numeric = valueText;
    else if (defn.value_kind === "categorical") payload.value_categorical = valueText;
    else if (defn.value_kind === "event") payload.value_event = valueText;
    else if (defn.value_kind === "boolean") payload.value_boolean = valueBool;
    else if (defn.value_kind === "geopoint") {
      const latNum = Number.parseFloat(lat);
      const lonNum = Number.parseFloat(lon);
      if (Number.isNaN(latNum) || Number.isNaN(lonNum)) {
        setError(t("signals.errorLatLon"));
        return;
      }
      payload.value_geopoint = { latitude: latNum, longitude: lonNum };
    }
    if (notes.trim()) payload.notes = notes.trim();
    if (observedAt) payload.time = observedAt;
    // Only send location on a non-default mode, matching the Log page: the
    // server treats `entity` as "the block itself" and validates
    // point_in_entity with ST_Within against this block's boundary.
    if (location.location_mode !== "entity") {
      if (!location.location_point) {
        setError(t("signals.errorLocationPoint"));
        return;
      }
      payload.location_mode = location.location_mode;
      payload.location_point = location.location_point;
    }

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
      setLocation(ENTITY_LOCATION);
      setLocationReset((k) => k + 1);
      setSaved(true);
    } catch (err) {
      setUploading(false);
      setError(err instanceof Error ? err.message : t("signals.errorGeneric"));
    }
  };

  return (
    <form onSubmit={submit} className="flex flex-col gap-3">
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
      <LocationCapture blockId={blockId} onChange={setLocation} resetKey={locationReset} />
      <label className="flex flex-col gap-1">
        <span className="text-xs font-medium text-ap-muted">{t("manage.notes")}</span>
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          rows={2}
          className={inputCls}
        />
      </label>
      {defn.attachment_allowed ? (
        <label className="flex flex-col gap-1">
          <span className="text-xs font-medium text-ap-muted">{t("signals.photo")}</span>
          <input
            type="file"
            accept="image/*"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="text-xs"
          />
        </label>
      ) : null}
      <div className="flex items-center gap-2">
        {error ? <span className="text-xs text-ap-crit">{error}</span> : null}
        {saved && !error ? (
          <span className="text-xs text-ap-good">{t("signals.saved")}</span>
        ) : null}
        <button
          type="submit"
          disabled={create.isPending || uploading}
          className="ms-auto h-9 rounded-lg bg-ap-primary px-4 text-sm font-semibold text-white hover:bg-ap-primary/90 disabled:opacity-60"
        >
          {uploading
            ? t("signals.uploading")
            : create.isPending
              ? t("signals.recording")
              : t("signals.record")}
        </button>
      </div>
    </form>
  );
}
