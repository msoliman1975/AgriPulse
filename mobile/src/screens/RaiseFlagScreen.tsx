import { useEffect, useRef, useState, type ReactNode } from "react";

import { ApiError, listBlocks, raiseFieldFlag, type Block, type FlagSeverity } from "@/api/client";
import type { FarmScope } from "@/api/me";
import { currentFix, type Fix } from "@/capture/location";
import { FarmField } from "@/components/FarmField";
import { MAX_PHOTOS, uploadFlagPhoto } from "@/capture/photos";
import { t, type Lang, type MessageKey } from "@/i18n";

/**
 * Something caught the scout's eye.
 *
 * The only thing in this app that is not an answer to a question somebody
 * already posed. Severity is asked in the scout's words rather than the
 * platform's — "needs attention" is a judgement a person can make standing in
 * a block; `warning` is a token they would have to learn.
 *
 * A farm and then a block are required, in that order. Every flag belongs to a
 * block, so a broken gate is attached to the block it sits beside — and a
 * block name is only unique inside a farm, so the farm has to be settled
 * first. Both pickers resolve to something rather than to nothing.
 *
 * A scout with one farm is not asked: the farm control is filled in and
 * disabled, which still says what the flag will be filed against.
 */

const SEVERITIES: { key: FlagSeverity; label: MessageKey }[] = [
  { key: "info", label: "flag.sev.info" },
  { key: "warning", label: "flag.sev.warning" },
  { key: "critical", label: "flag.sev.critical" },
];

export function RaiseFlagScreen({
  lang,
  farms,
  farmName,
  farm,
  onClose,
  onRaised,
}: {
  lang: Lang;
  /** Every farm this scout is granted. Never empty — the caller handles that. */
  farms: FarmScope[];
  farmName: (farmId: string) => string;
  /** The rail's position, inherited rather than re-asked. Empty when the rail
   *  is on "All farms". */
  farm: string;
  onClose: () => void;
  onRaised: () => void;
}): ReactNode {
  const single = farms.length === 1 ? farms[0].farm_id : null;
  const [farmId, setFarmId] = useState<string>(
    () => single ?? (farms.some((f) => f.farm_id === farm) ? farm : ""),
  );
  const [blocks, setBlocks] = useState<Block[] | null>(null);
  const [blockId, setBlockId] = useState("");
  const [severity, setSeverity] = useState<FlagSeverity>("warning");
  const [note, setNote] = useState("");
  const [photos, setPhotos] = useState<File[]>([]);
  const [fix, setFix] = useState<Fix | null>(null);
  const [fixState, setFixState] = useState<"idle" | "asking" | "denied" | "unavailable">("idle");
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const cameraRef = useRef<HTMLInputElement>(null);
  const galleryRef = useRef<HTMLInputElement>(null);

  // Blocks belong to a farm, so changing the farm invalidates the block. A
  // flag raised against a block id from the previously selected farm would be
  // filed somewhere nobody is looking.
  useEffect(() => {
    let live = true;
    setBlocks(null);
    setBlockId("");
    if (!farmId) return;
    void listBlocks(farmId)
      .then((b) => {
        if (!live) return;
        setBlocks(b);
        if (b.length > 0) setBlockId(b[0].id);
      })
      .catch(() => {
        if (!live) return;
        setBlocks([]);
        setError(t(lang, "record.blocksFailed"));
      });
    return () => {
      live = false;
    };
  }, [farmId, lang]);

  function addFiles(list: FileList | null): void {
    if (!list) return;
    // Copied out of the live FileList before the input is cleared — see
    // CaptureForm: reading it later finds it empty and drops every photo.
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
      setFixState(result.reason === "denied" ? "denied" : "unavailable");
    }
  }

  async function raise(): Promise<void> {
    if (!farmId || !blockId) return;
    if (note.trim() === "") {
      setError(t(lang, "flag.needNote"));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      // Photographs first, for the same reason a reading uploads first: the
      // flag row is written only once its bytes are in storage, so a failed
      // upload never leaves a flag pointing at a photo that does not exist.
      const keys: string[] = [];
      for (const [i, file] of photos.entries()) {
        setProgress(`${i + 1}/${photos.length}`);
        keys.push(await uploadFlagPhoto({ file, farmId }));
      }
      setProgress(null);
      await raiseFieldFlag(farmId, {
        block_id: blockId,
        note: note.trim(),
        severity,
        point: fix ? fix.point : null,
        accuracy_m: fix ? fix.accuracy_m : null,
        attachment_s3_keys: keys,
      });
      onRaised();
    } catch (e) {
      setError(e instanceof ApiError && e.message ? e.message : t(lang, "flag.raiseFailed"));
    } finally {
      setProgress(null);
      setBusy(false);
    }
  }

  return (
    <div className="screen detail overlay">
      <header>
        <button type="button" className="link" onClick={onClose}>
          {t(lang, "record.cancel")}
        </button>
      </header>
      <h1>{t(lang, "flag.title")}</h1>
      {error ? <p className="error">{error}</p> : null}

      <div className="capture">
        <label>{t(lang, "flag.howSerious")}</label>
        <div className="chips">
          {SEVERITIES.map((s) => (
            <button
              key={s.key}
              type="button"
              className={`chip sev-${s.key}${severity === s.key ? " on" : ""}`}
              onClick={() => setSeverity(s.key)}
            >
              {t(lang, s.label)}
            </button>
          ))}
        </div>
        <p className="hint">{t(lang, "flag.severityHint")}</p>

        <FarmField
          lang={lang}
          farms={farms}
          farmName={farmName}
          value={farmId}
          disabled={single !== null}
          onChange={setFarmId}
        />

        <label htmlFor="flagblk">{t(lang, "record.whichBlock")}</label>
        <select
          id="flagblk"
          value={blockId}
          disabled={blocks === null || blocks.length === 0}
          onChange={(e) => setBlockId(e.target.value)}
        >
          {blocks === null ? (
            <option value="">{t(lang, "farms.loading")}</option>
          ) : (
            blocks.map((b) => (
              <option key={b.id} value={b.id}>
                {b.name || b.code}
              </option>
            ))
          )}
        </select>
        {blocks !== null && blocks.length === 0 ? (
          <p className="hint">{t(lang, "record.noBlocks")}</p>
        ) : null}

        <label htmlFor="flagnote">{t(lang, "flag.whatDidYouSee")}</label>
        <textarea
          id="flagnote"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          rows={4}
        />

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
          <button
            type="button"
            className="link"
            disabled={fixState === "asking"}
            onClick={() => void askForFix()}
          >
            {fixState === "asking"
              ? t(lang, "work.positionAsking")
              : fix
                ? t(lang, "work.positionRedo")
                : t(lang, "work.positionUse")}
          </button>
        </div>

        <button type="button" className="btn-raise" disabled={busy || !blockId} onClick={() => void raise()}>
          {busy
            ? progress
              ? `${t(lang, "work.uploading")} ${progress}`
              : t(lang, "work.saving")
            : t(lang, "flag.raise")}
        </button>
      </div>
    </div>
  );
}
