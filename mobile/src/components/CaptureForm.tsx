import { useEffect, useRef, useState, type ReactNode } from "react";

import {
  ApiError,
  getSignalTemplate,
  listSignalDefinitions,
  recordObservation,
  type Geopoint,
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
  const [boolValue, setBoolValue] = useState<boolean | null>(null);
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
  // The API accepts EXACTLY ONE value column and it must be the one matching
  // the definition's kind: `value_event` for an event, `value_boolean` for a
  // boolean, and so on. Sending `value_categorical` for the seeded
  // `scout_photo` signal — an event, and a REQUIRED member of the default
  // scouting template — was rejected every single time, which is why saving a
  // photo never worked.
  //
  // Read straight off the definition, with NO `?? "categorical"` fallback.
  // That fallback is what hid the field-name bug: `value_type` is not a field
  // the API sends, so it was always undefined, the fallback always won, and
  // every signal on the phone became a free-text categorical one. A kind we
  // cannot read is now an unusable form and a visible message, not a wrong
  // form that fails on save.
  const kind = chosen?.value_kind;
  const numeric = kind === "numeric";
  const canAttach = chosen?.attachment_allowed === true;
  // The lookup list the tenant defined. The server requires a non-empty one
  // for every categorical definition, so an empty list here means a legacy row
  // — fall back to free text rather than showing a picker with nothing in it.
  const options = chosen?.categorical_values ?? [];
  const usePicker = kind === "categorical" && options.length > 0;
  // Decimal-as-string on the wire. `Number(null)` is 0, which would silently
  // impose a floor of zero on every unbounded signal, so the null check is
  // deliberate and must stay.
  const min = chosen?.value_min == null ? null : Number(chosen.value_min);
  const max = chosen?.value_max == null ? null : Number(chosen.value_max);
  // An event is a thing that happened: the act is the value, so text is
  // optional and the signal's own code stands in when nothing is typed.
  // Numeric and categorical carry a measurement, and an empty one is not a
  // reading at all.
  const needsValue = kind === "numeric" || kind === "categorical";

  /** "0 – 100 %", or null when the signal has no bounds to show. Written next
   *  to the box so the scout knows the range BEFORE typing, rather than after
   *  the server rejects the reading. */
  function rangeHint(): string | null {
    if (kind !== "numeric") return null;
    const unit = chosen?.unit ? ` ${chosen.unit}` : "";
    if (min !== null && max !== null) return `${min} – ${max}${unit}`;
    if (min !== null) return `≥ ${min}${unit}`;
    if (max !== null) return `≤ ${max}${unit}`;
    return null;
  }

  /**
   * The same checks the server runs, run here first.
   *
   * Not belt-and-braces: on a field connection a rejected POST costs the scout
   * a round trip and tells them nothing until it comes back. `_validate_value`
   * in signals/service.py is the authority — these messages mirror its rules
   * so the two can never disagree about what is acceptable.
   */
  function localValueError(): string | null {
    if (!chosen || !kind) return t(lang, "work.unknownKind");
    if (kind === "boolean") return boolValue === null ? t(lang, "work.needValue") : null;
    if (kind === "geopoint") return fix ? null : t(lang, "work.needPosition");
    if (needsValue && value === "") return t(lang, "work.needValue");
    if (kind === "numeric") {
      // Not `Number(value)` alone: `Number("")` is 0 and `Number(" ")` is 0,
      // so a blank box would pass as a valid zero reading.
      const n = Number(value);
      if (value.trim() === "" || !Number.isFinite(n)) return t(lang, "work.needNumber");
      if (min !== null && n < min) return t(lang, "work.belowMin").replace("{min}", String(min));
      if (max !== null && n > max) return t(lang, "work.aboveMax").replace("{max}", String(max));
    }
    if (usePicker && !options.includes(value)) {
      return t(lang, "work.notAllowed").replace("{allowed}", options.join(", "));
    }
    return null;
  }

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

  /** The one value column this definition's kind expects, and only that one. */
  function valueColumns(): {
    value_numeric: number | null;
    value_categorical: string | null;
    value_event: string | null;
    value_boolean: boolean | null;
    value_geopoint: Geopoint | null;
  } {
    const empty = {
      value_numeric: null,
      value_categorical: null,
      value_event: null,
      value_boolean: null,
      value_geopoint: null,
    };
    if (kind === "numeric") return { ...empty, value_numeric: value === "" ? null : Number(value) };
    if (kind === "boolean") return { ...empty, value_boolean: boolValue };
    if (kind === "event") return { ...empty, value_event: value.trim() || (chosen?.code ?? "observed") };
    // A geopoint signal records a place, so the reading IS the fix. `save()`
    // refuses to run without one, which is why this cannot post a null.
    if (kind === "geopoint") return { ...empty, value_geopoint: fix?.point ?? null };
    return { ...empty, value_categorical: value === "" ? null : value };
  }

  async function save(): Promise<void> {
    if (!defId) return;
    // Checked here rather than left to the server: a scout in a field should
    // be told what is wrong by the form, not "could not save" by a request
    // that was never going to succeed. One call covers every kind, including
    // the range and lookup-list rules the server enforces.
    const problem = localValueError();
    if (problem) {
      setError(problem);
      return;
    }
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
          ...valueColumns(),
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
      setBoolValue(null);
      setNotes("");
      setPhotos([]);
    } catch (e) {
      // The API writes `detail` for a person to read — "value_categorical must
      // be one of [...]" tells a scout what to change; "could not save that
      // reading" tells them nothing and tells us nothing either.
      setError(e instanceof ApiError && e.message ? e.message : t(lang, "work.recordFailed"));
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
      <select
        id="def"
        value={defId}
        onChange={(e) => {
          setDefId(e.target.value);
          // The old value belongs to the old signal, and so does the old error.
          setValue("");
          setBoolValue(null);
          setError(null);
        }}
      >
        {defs.map((d) => (
          <option key={d.id} value={d.id}>
            {d.name}
          </option>
        ))}
      </select>

      <label htmlFor="val">
        {kind === "event" ? t(lang, "work.whatHappened") : t(lang, "work.value")}
        {chosen?.unit ? ` (${chosen.unit})` : ""}
      </label>
      {kind === "boolean" ? (
        <div className="chips">
          {[true, false].map((v) => (
            <button
              key={String(v)}
              type="button"
              className={`chip${boolValue === v ? " on" : ""}`}
              onClick={() => setBoolValue(v)}
            >
              {t(lang, v ? "work.yes" : "work.no")}
            </button>
          ))}
        </div>
      ) : usePicker ? (
        /* The tenant's lookup list, and nothing else. A scout cannot type a
           value the server will reject, which is the whole point of defining
           the list — before this, every one of these was a free-text box and
           the reading came back "value_categorical must be one of [...]". */
        <select id="val" value={value} onChange={(e) => setValue(e.target.value)}>
          <option value="">—</option>
          {options.map((v) => (
            <option key={v} value={v}>
              {v}
            </option>
          ))}
        </select>
      ) : kind === "geopoint" ? (
        /* Nothing to type: the position below IS the reading. */
        <p className="hint">{fix ? t(lang, "work.positionIsValue") : t(lang, "work.needPosition")}</p>
      ) : (
        <input
          id="val"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          inputMode={numeric ? "decimal" : "text"}
          // The browser enforces nothing here — this is a controlled React
          // input inside a WebView, and `type="number"` on Android hides the
          // minus sign on some keyboards. The bounds are checked in
          // `localValueError()`; these attributes only shape the keypad and
          // the stepper.
          type={numeric ? "number" : "text"}
          min={numeric && min !== null ? min : undefined}
          max={numeric && max !== null ? max : undefined}
          placeholder={kind === "event" ? t(lang, "work.optional") : ""}
        />
      )}
      {/* Shown before the scout types, not after the server refuses. */}
      {rangeHint() ? <p className="hint">{t(lang, "work.range")} {rangeHint()}</p> : null}

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
