import { useEffect, useState, type ReactNode } from "react";

import { createSelfInitiatedVisit, listBlocks, type Block, type WorkItem } from "@/api/client";
import type { FarmScope } from "@/api/me";
import { CaptureForm } from "@/components/CaptureForm";
import { FarmField } from "@/components/FarmField";
import { RaiseFlagScreen } from "@/screens/RaiseFlagScreen";
import { t, type Lang } from "@/i18n";
import { WorkDetailScreen } from "@/screens/WorkDetailScreen";

/**
 * Recording something nobody asked for.
 *
 * Two ways in, named by the situation that produces them rather than by what
 * the system stores:
 *
 *   * **A round** — you chose to inspect a block. It becomes a real visit,
 *     opened straight into `in_progress`, and closes with an outcome exactly
 *     like a dispatched one. That is what makes a self-started walk show up in
 *     the same history as assigned work instead of vanishing.
 *   * **A reading** — one measurement, no visit and no outcome.
 *
 * Both need a **farm and then a block**, in that order, because a block name
 * is only unique inside a farm — two farms can both have a "North 3" and
 * filing a reading against the wrong one is a silent, unfixable mistake.
 * The farm used to be implicit: whatever was chosen in a settings screen,
 * possibly days earlier. Now it is asked here, where the answer is being used.
 *
 * A scout with one farm is not asked. The control is filled in and disabled
 * rather than hidden, so what the reading will be filed against is on screen
 * either way — a disabled field that states the answer beats no field at all.
 */

type Mode = "choose" | "where" | "round" | "reading" | "flag";

export function RecordSheet({
  lang,
  farms,
  farmName,
  farm,
  onClose,
}: {
  lang: Lang;
  /** Every farm this scout is granted. Never empty — the caller handles that. */
  farms: FarmScope[];
  farmName: (farmId: string) => string;
  /** The rail's position, inherited rather than re-asked. Empty when the rail
   *  is on "All farms", which is the one case this sheet asks outright. */
  farm: string;
  onClose: () => void;
}): ReactNode {
  const single = farms.length === 1 ? farms[0].farm_id : null;

  const [mode, setMode] = useState<Mode>("choose");
  const [intent, setIntent] = useState<"round" | "reading">("round");
  // Inherited, never defaulted. A farm picked for the scout is a wrong answer
  // waiting to be accepted, and a reading filed against the wrong farm is not
  // visibly wrong afterwards.
  const [farmId, setFarmId] = useState<string>(
    () => single ?? (farms.some((f) => f.farm_id === farm) ? farm : ""),
  );
  const [blocks, setBlocks] = useState<Block[] | null>(null);
  const [blockId, setBlockId] = useState("");
  const [visit, setVisit] = useState<WorkItem | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Blocks belong to a farm, so changing the farm invalidates the block —
  // keeping the old id would post a reading to a block in a farm the scout is
  // no longer naming, which the server accepts only by coincidence of ids.
  useEffect(() => {
    let live = true;
    setBlocks(null);
    setBlockId("");
    // Nothing to ask for until a farm is settled.
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

  async function go(): Promise<void> {
    if (!farmId || !blockId) return;
    if (intent === "reading") {
      setMode("reading");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const created = await createSelfInitiatedVisit(farmId, { block_id: blockId });
      const name = (blocks ?? []).find((b) => b.id === blockId);
      setVisit({
        kind: "scouting_visit",
        id: created.id,
        farm_id: farmId,
        farm_name: farmName(farmId),
        block_id: created.block_id,
        block_name: name ? name.name || name.code : null,
        title: created.title,
        detail: created.instruction,
        status: created.status,
        category: created.origin,
        severity: created.severity,
        priority: created.priority,
        due_at: created.due_by,
        completed_at: null,
        template_id: created.template_id,
      });
      setMode("round");
    } catch {
      setError(t(lang, "record.roundFailed"));
    } finally {
      setBusy(false);
    }
  }

  // A started round is a real visit on the server from the moment it is
  // created, so the scout finishes it on the normal detail screen — including
  // the outcome. Closing this sheet without submitting leaves it in progress
  // and waiting in the Tasks list, which is the truth.
  if (mode === "round" && visit) {
    return (
      <WorkDetailScreen
        lang={lang}
        farmId={farmId}
        item={visit}
        // The block the scout just picked, already loaded above. A self-started
        // round is walked to like any other job.
        block={(blocks ?? []).find((b) => b.id === blockId) ?? null}
        onClose={onClose}
        onChanged={() => undefined}
      />
    );
  }

  if (mode === "flag") {
    return (
      <RaiseFlagScreen
        lang={lang}
        farms={farms}
        farmName={farmName}
        farm={farmId}
        onClose={onClose}
        onRaised={onClose}
      />
    );
  }

  if (mode === "reading") {
    return (
      // `overlay` because this renders alongside the tab content rather than
      // instead of it — without it the task list shows through underneath.
      <div className="screen detail overlay">
        <header>
          <button type="button" className="link" onClick={onClose}>
            {t(lang, "work.back")}
          </button>
        </header>
        <h1>{t(lang, "record.reading")}</h1>
        {/* Farm as well as block: a reading filed against the wrong farm is
            not visibly wrong afterwards, so it is stated before it is taken. */}
        <p className="where">
          {(blocks ?? []).find((b) => b.id === blockId)?.name || ""}
          {single ? "" : ` · ${farmName(farmId)}`}
        </p>
        <CaptureForm
          lang={lang}
          farmId={farmId}
          blockId={blockId}
          templateId={null}
          onClose={onClose}
          onRecorded={() => undefined}
        />
      </div>
    );
  }

  return (
    <div className="sheet-wrap" onClick={onClose}>
      <div className="sheet" onClick={(e) => e.stopPropagation()}>
        <span className="grab" />
        <h2>{t(lang, "record.title")}</h2>
        {error ? <p className="error">{error}</p> : null}

        {mode === "choose" ? (
          <>
            {/* First, because it is the one thing this app could not do at
                all: report something nobody asked about. */}
            <button type="button" className="opt" onClick={() => setMode("flag")}>
              <b>{t(lang, "flag.chooser")}</b>
              <span>{t(lang, "flag.chooserHint")}</span>
            </button>
            <button
              type="button"
              className="opt"
              onClick={() => {
                setIntent("round");
                setMode("where");
              }}
            >
              <b>{t(lang, "record.round")}</b>
              <span>{t(lang, "record.roundHint")}</span>
            </button>
            <button
              type="button"
              className="opt"
              onClick={() => {
                setIntent("reading");
                setMode("where");
              }}
            >
              <b>{t(lang, "record.reading")}</b>
              <span>{t(lang, "record.readingHint")}</span>
            </button>
            <button type="button" className="link" onClick={onClose}>
              {t(lang, "record.cancel")}
            </button>
          </>
        ) : (
          <>
            <FarmField
              lang={lang}
              farms={farms}
              farmName={farmName}
              value={farmId}
              disabled={single !== null}
              onChange={setFarmId}
            />

            <label htmlFor="blk">{t(lang, "record.whichBlock")}</label>
            <select
              id="blk"
              value={blockId}
              // Nothing to choose between until the farm's blocks arrive, and a
              // select that is empty for a moment invites a tap that does
              // nothing.
              disabled={!farmId || blocks === null || blocks.length === 0}
              onChange={(e) => setBlockId(e.target.value)}
            >
              {!farmId ? (
                <option value="">{t(lang, "record.farmFirst")}</option>
              ) : blocks === null ? (
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

            <button type="button" disabled={busy || !farmId || !blockId} onClick={() => void go()}>
              {busy ? t(lang, "work.saving") : t(lang, "record.start")}
            </button>
            <button type="button" className="link" onClick={() => setMode("choose")}>
              {t(lang, "work.back")}
            </button>
          </>
        )}
      </div>
    </div>
  );
}
