import { useEffect, useState, type ReactNode } from "react";

import { createSelfInitiatedVisit, listBlocks, type Block, type WorkItem } from "@/api/client";
import { CaptureForm } from "@/components/CaptureForm";
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
 * Both need a block. Every observation and every visit is block-scoped, and a
 * reading attributed to nowhere cannot be aggregated with anything.
 */

type Mode = "choose" | "block" | "round" | "reading" | "flag";

export function RecordSheet({
  lang,
  farmId,
  onClose,
}: {
  lang: Lang;
  farmId: string;
  onClose: () => void;
}): ReactNode {
  const [mode, setMode] = useState<Mode>("choose");
  const [intent, setIntent] = useState<"round" | "reading">("round");
  const [blocks, setBlocks] = useState<Block[]>([]);
  const [blockId, setBlockId] = useState("");
  const [visit, setVisit] = useState<WorkItem | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    void listBlocks(farmId)
      .then((b) => {
        if (!live) return;
        setBlocks(b);
        if (b.length > 0) setBlockId(b[0].id);
      })
      .catch(() => setError(t(lang, "record.blocksFailed")));
    return () => {
      live = false;
    };
  }, [farmId, lang]);

  async function go(): Promise<void> {
    if (!blockId) return;
    if (intent === "reading") {
      setMode("reading");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const created = await createSelfInitiatedVisit(farmId, { block_id: blockId });
      const name = blocks.find((b) => b.id === blockId);
      setVisit({
        kind: "scouting_visit",
        id: created.id,
        farm_id: farmId,
        block_id: created.block_id,
        block_name: name ? name.name || name.code : null,
        title: created.title,
        detail: created.instruction,
        status: created.status,
        category: created.origin,
        severity: created.severity,
        priority: created.priority,
        due_at: created.due_by,
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
      <WorkDetailScreen lang={lang} farmId={farmId} item={visit} onClose={onClose} onChanged={() => undefined} />
    );
  }

  if (mode === "flag") {
    return (
      <RaiseFlagScreen lang={lang} farmId={farmId} onClose={onClose} onRaised={onClose} />
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
        <p className="where">{blocks.find((b) => b.id === blockId)?.name || ""}</p>
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
                setMode("block");
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
                setMode("block");
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
            <label htmlFor="blk">{t(lang, "record.whichBlock")}</label>
            <select id="blk" value={blockId} onChange={(e) => setBlockId(e.target.value)}>
              {blocks.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name || b.code}
                </option>
              ))}
            </select>
            {blocks.length === 0 ? <p className="hint">{t(lang, "record.noBlocks")}</p> : null}
            <button type="button" disabled={busy || !blockId} onClick={() => void go()}>
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
