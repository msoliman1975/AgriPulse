import { useEffect, useRef, useState, type ReactNode } from "react";

import {
  getSignalTemplate,
  listSignalDefinitions,
  recordObservation,
  type SignalDefinition,
} from "@/api/client";
import { currentFix, type Fix } from "@/capture/location";
import { MAX_PHOTOS, uploadPhoto } from "@/capture/photos";
import { t, type Lang } from "@/i18n";

/**
 * Record what you see: a reading, where you were standing, and photographs.
 *
 * One form serves every way of capturing. A dispatched visit, a round the
 * scout started themselves, and a standalone reading all land here, because
 * from the scout's side they are the same act — the only difference is what
 * opened it.
 *
 * When the work carries a signal template the form shows *that* form, in the
 * order the template names. The supervisor has already said which signals this
 * job is about, and putting the whole catalogue in front of a scout is how the
 * wrong ones get recorded.
 */
export function CaptureForm({
  lang,
  farmId,
  blockId,
  templateId,
  onClose,
  onRecorded,
}: {
  lang: Lang;
  farmId: string;
  blockId: string | null;
  templateId: string | null;
  onClose: () => void;
  onRecorded: (observationId: string) => void;
}): ReactNode {
  const [defs, setDefs] = useState<SignalDefinition[]>([]);
  const [defId, setDefId] = useState("");
  const [value, setValue] = useState("");
  const [notes, setNotes] = useState("");
  const [photos, setPhotos] = useState<File[]>([]);
  const [fix, setFix] = useState<Fix | null>(null);
  const [fixState, setFixState] = useState<"idle" | "asking" | "denied" | "unavailable">("idle");
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const cameraRef = useRef<HTMLInputElement>(null);
  const galleryRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let live = true;
    async function load(): Promise<SignalDefinition[]> {
      const all = await listSignalDefinitions(farmId);
      if (!templateId) return all;
      // Narrow to the template, keeping its order — position is the sequence
      // the form was designed to be filled in.
      try {
        const { members } = await getSignalTemplate(templateId);
        const order = new Map(members.map((m) => [m.signal_definition_id, m.position]));
        const picked = all
          .filter((d) => order.has(d.id))
          .sort((a, b) => (order.get(a.id) ?? 0) - (order.get(b.id) ?? 0));
        // A template naming nothing this farm can record is a misconfiguration,
        // not a reason to give the scout an empty form.
        return picked.length > 0 ? picked : all;
      } catch {
        return all;
      }
    }
    void load()
      .then((d) => {
        if (!live) return;
        setDefs(d);
        if (d.length > 0) setDefId(d[0].id);
      })
      .catch(() => setError(t(lang, "work.loadDefsFailed")));
    return () => {
      live = false;
    };
  }, [farmId, lang, templateId]);

  const chosen = defs.find((d) => d.id === defId);
  const numeric = chosen?.value_type === "numeric";
  const canAttach = chosen?.attachment_allowed === true;

  function addFiles(list: FileList | null): void {
    if (!list) return;
    // Copied out of the FileList NOW, not inside the state updater. A FileList
    // is a live view of the input element, and the handler clears that input
    // straight after calling this so the same photo can be picked twice —
    // reading it later would find it empty and silently drop every photo.
    const picked = Array.from(list);
    setPhotos((prev) => [...prev, ...picked].slice(0, MAX_PHOTOS));
  }

  async function askForFix(): Promise<void> {
    setFixState("asking");
    const result = await currentFix();
    if (result.ok) {
      setFix(result.fix);
      setFixState("idle");
    } else {
      setFix(null);
      // A refused fix and a missing one read differently to a scout: one they
      // can fix in settings, the other they cannot.
      setFixState(result.reason === "denied" ? "denied" : "unavailable");
    }
  }

  async function save(): Promise<void> {
    if (!defId) return;
    setBusy(true);
    setError(null);
    try {
      // Uploads first. An observation row is only written once its bytes are
      // safely in storage, so a failed upload never leaves a row pointing at
      // a photo that does not exist.
      const keys: string[] = [];
      for (const [i, file] of photos.entries()) {
        setProgress(`${i + 1}/${photos.length}`);
        keys.push(await uploadPhoto({ file, farmId, signalDefinitionId: defId }));
      }
      setProgress(null);

      // One row per photo, matching how the platform's own `scout_photo`
      // signal is defined: each photograph is its own observation, carrying
      // the position and the moment it was taken. With no photos this is a
      // single row, exactly as before.
      const rows = keys.length > 0 ? keys : [null];
      let first: string | null = null;
      for (const key of rows) {
        const created = await recordObservation(defId, {
          farm_id: farmId,
          block_id: blockId,
          value_numeric: numeric && value !== "" ? Number(value) : null,
          value_categorical: !numeric && value !== "" ? value : null,
          notes: notes || null,
          attachment_s3_key: key,
          // See recordObservation: `free_point` never rejects on GPS drift,
          // and `entity` is the honest answer when there is no fix.
          location_mode: fix ? "free_point" : "entity",
          location_point: fix ? fix.point : null,
        });
        first ??= created.id;
      }
      if (first) onRecorded(first);

      // Cleared, not closed: a scout usually records several readings in one
      // visit, and making them reopen the form each time is friction in a
      // field with one hand free. The position is kept — they have not moved.
      setValue("");
      setNotes("");
      setPhotos([]);
    } catch {
      setError(t(lang, "work.recordFailed"));
    } finally {
      setProgress(null);
      setBusy(false);
    }
  }

  return (
    <div className="capture">
      <h2>{t(lang, "work.record")}</h2>
      {error ? <p className="error">{error}</p> : null}

      <label htmlFor="def">{t(lang, "work.what")}</label>
      <select id="def" value={defId} onChange={(e) => setDefId(e.target.value)}>
        {defs.map((d) => (
          <option key={d.id} value={d.id}>
            {d.name}
          </option>
        ))}
      </select>

      <label htmlFor="val">{t(lang, "work.value")}</label>
      {chosen?.allowed_values && chosen.allowed_values.length > 0 ? (
        <select id="val" value={value} onChange={(e) => setValue(e.target.value)}>
          <option value="">—</option>
          {chosen.allowed_values.map((v) => (
            <option key={v} value={v}>
              {v}
            </option>
          ))}
        </select>
      ) : (
        <input
          id="val"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          inputMode={numeric ? "decimal" : "text"}
        />
      )}

      {/* Photos only where the signal permits them. A definition with
          attachments switched off silently drops the key, so offering a camera
          there would lose the scout's work without saying so. */}
      {canAttach ? (
        <>
          <label>
            {t(lang, "work.photos")} {photos.length}/{MAX_PHOTOS}
          </label>
          <div className="thumbs">
            {photos.map((f, i) => (
              <button
                key={`${f.name}-${i}`}
                type="button"
                className="thumb"
                onClick={() => setPhotos((prev) => prev.filter((_, j) => j !== i))}
                aria-label={t(lang, "work.removePhoto")}
              >
                <img src={URL.createObjectURL(f)} alt="" />
                <span className="x">✕</span>
              </button>
            ))}
          </div>
          <div className="row">
            <button
              type="button"
              disabled={busy || photos.length >= MAX_PHOTOS}
              onClick={() => cameraRef.current?.click()}
            >
              {t(lang, "work.takePhoto")}
            </button>
            <button
              type="button"
              className="link"
              disabled={busy || photos.length >= MAX_PHOTOS}
              onClick={() => galleryRef.current?.click()}
            >
              {t(lang, "work.choosePhoto")}
            </button>
          </div>
          {/* Two inputs, not one: Android ignores `multiple` when `capture` is
              set, so a single control could either open the camera or allow
              several files, never both. */}
          <input
            ref={cameraRef}
            type="file"
            accept="image/*"
            capture="environment"
            hidden
            onChange={(e) => {
              addFiles(e.target.files);
              e.target.value = "";
            }}
          />
          <input
            ref={galleryRef}
            type="file"
            accept="image/*"
            multiple
            hidden
            onChange={(e) => {
              addFiles(e.target.files);
              e.target.value = "";
            }}
          />
        </>
      ) : null}

      <label htmlFor="obsnotes">{t(lang, "work.notes")}</label>
      <textarea id="obsnotes" value={notes} onChange={(e) => setNotes(e.target.value)} rows={2} />

      {/* Position is opt-in and shown with its accuracy, so a poor fix is a
          fact the scout can see rather than a number the map implies. */}
      <div className={`gps${fix ? " on" : ""}`}>
        {fix ? (
          <span>
            {t(lang, "work.positionSet")} ±{fix.accuracy_m} m
          </span>
        ) : (
          <span>
            {fixState === "denied"
              ? t(lang, "work.positionDenied")
              : fixState === "unavailable"
                ? t(lang, "work.positionUnavailable")
                : t(lang, "work.positionOff")}
          </span>
        )}
        <button type="button" className="link" disabled={fixState === "asking"} onClick={() => void askForFix()}>
          {fixState === "asking"
            ? t(lang, "work.positionAsking")
            : fix
              ? t(lang, "work.positionRedo")
              : t(lang, "work.positionUse")}
        </button>
      </div>

      <div className="row">
        <button type="button" disabled={busy || !defId} onClick={() => void save()}>
          {busy ? (progress ? `${t(lang, "work.uploading")} ${progress}` : t(lang, "work.saving")) : t(lang, "work.save")}
        </button>
        <button type="button" className="link" onClick={onClose}>
          {t(lang, "work.done")}
        </button>
      </div>
    </div>
  );
}
