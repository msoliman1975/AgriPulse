import { useEffect, useState, type ReactNode } from "react";

import {
  acceptVisit,
  listSignalDefinitions,
  recordObservation,
  startVisit,
  submitVisit,
  type SignalDefinition,
  type VisitOutcome,
  type WorkItem,
} from "@/api/client";
import { dueIn, t, type Lang } from "@/i18n";

/**
 * One job, and everything a scout can do about it.
 *
 * Until now the app could only *show* work. Tapping a row did nothing, because
 * there was nothing behind it — no detail, no actions, no way to record what
 * you saw. A scout could be told to go and look at a block and had no way to
 * report back from the handset.
 *
 * The lifecycle is deliberately not a wizard. A scout standing in a block has
 * one hand free and poor light; every step is a single large control, the
 * current state is always visible, and nothing is hidden behind a page they
 * have to navigate back out of.
 */
export function WorkDetailScreen({
  lang,
  farmId,
  item,
  onClose,
  onChanged,
}: {
  lang: Lang;
  farmId: string;
  item: WorkItem;
  onClose: () => void;
  onChanged: () => void;
}): ReactNode {
  const [status, setStatus] = useState(item.status);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isVisit = item.kind === "scouting_visit";

  async function act(fn: () => Promise<{ status: string }>): Promise<void> {
    setBusy(true);
    setError(null);
    try {
      const updated = await fn();
      setStatus(updated.status);
      onChanged();
    } catch {
      setError(t(lang, "work.actionFailed"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="screen detail">
      <header>
        <button type="button" className="link" onClick={onClose}>
          {t(lang, "work.back")}
        </button>
        <span className={`status status-${status}`}>{status}</span>
      </header>

      <h1>{item.title}</h1>
      {item.detail ? <p className="instruction">{item.detail}</p> : null}
      <p className="meta">
        <span className="ring">{dueIn(lang, item.due_at)}</span>
        {item.category ? <span className="origin">{item.category}</span> : null}
      </p>

      {error ? <p className="error">{error}</p> : null}

      {isVisit ? (
        <VisitActions
          lang={lang}
          farmId={farmId}
          visitId={item.id}
          blockId={item.block_id}
          status={status}
          busy={busy}
          onAct={act}
          onDone={onClose}
        />
      ) : (
        // Board work is read-only here on purpose. Completing a plan activity
        // needs `plan_activity.complete`, which a Scout does not hold — a
        // button that always 403s would be worse than none. Showing it at all
        // is still the point: before this the phone could not see it.
        <p className="hint">{t(lang, "work.boardReadOnly")}</p>
      )}
    </div>
  );
}

function VisitActions({
  lang,
  farmId,
  visitId,
  blockId,
  status,
  busy,
  onAct,
  onDone,
}: {
  lang: Lang;
  farmId: string;
  visitId: string;
  blockId: string | null;
  status: string;
  busy: boolean;
  onAct: (fn: () => Promise<{ status: string }>) => Promise<void>;
  onDone: () => void;
}): ReactNode {
  const [capturing, setCapturing] = useState(false);
  // Ids of observations recorded during this visit. The first one becomes the
  // group the submit points at, which is how the readings and the closure end
  // up linked without making capture depend on a successful submit.
  const [recorded, setRecorded] = useState<string[]>([]);

  if (status === "completed" || status === "cancelled") {
    return <p className="hint">{t(lang, "work.alreadyClosed")}</p>;
  }

  return (
    <div className="actions">
      {status === "assigned" ? (
        <button type="button" disabled={busy} onClick={() => void onAct(() => acceptVisit(visitId, farmId))}>
          {t(lang, "work.accept")}
        </button>
      ) : null}

      {status === "accepted" || status === "assigned" ? (
        <button type="button" disabled={busy} onClick={() => void onAct(() => startVisit(visitId, farmId))}>
          {t(lang, "work.start")}
        </button>
      ) : null}

      {status === "in_progress" ? (
        <>
          <button type="button" disabled={busy} onClick={() => setCapturing(true)}>
            {t(lang, "work.record")}
          </button>
          {recorded.length > 0 ? (
            <p className="hint">{t(lang, "work.recordedCount")} {recorded.length}</p>
          ) : null}
          <SubmitBar
            lang={lang}
            busy={busy}
            onSubmit={(outcome, note) =>
              void onAct(async () => {
                const done = await submitVisit(visitId, farmId, {
                  outcome,
                  summary_note: note || null,
                  observation_group_id: recorded[0] ?? null,
                  // Stable per visit: a retry after a dropped response replays
                  // rather than closing the visit twice.
                  idempotency_key: `visit-${visitId}`,
                });
                onDone();
                return done;
              })
            }
          />
        </>
      ) : null}

      {capturing ? (
        <CaptureForm
          lang={lang}
          farmId={farmId}
          blockId={blockId}
          onClose={() => setCapturing(false)}
          onRecorded={(id) => setRecorded((prev) => [...prev, id])}
        />
      ) : null}
    </div>
  );
}

function SubmitBar({
  lang,
  busy,
  onSubmit,
}: {
  lang: Lang;
  busy: boolean;
  onSubmit: (outcome: VisitOutcome, note: string) => void;
}): ReactNode {
  const [note, setNote] = useState("");
  return (
    <div className="submitbar">
      <label htmlFor="summary">{t(lang, "work.summary")}</label>
      <textarea id="summary" value={note} onChange={(e) => setNote(e.target.value)} rows={3} />
      {/* Three outcomes, not a single "done": "I looked and found nothing" and
          "I could not get to it" are different facts, and collapsing them
          loses the one a supervisor needs to act on. */}
      <div className="outcomes">
        {(["resolved", "inconclusive", "blocked"] as VisitOutcome[]).map((o) => (
          <button key={o} type="button" disabled={busy} onClick={() => onSubmit(o, note)}>
            {t(lang, `work.outcome.${o}` as never)}
          </button>
        ))}
      </div>
    </div>
  );
}

/**
 * Record one reading against the block.
 *
 * The definition list is the platform's scouting catalogue, so the scout picks
 * what they saw rather than typing a free-text note nobody can aggregate.
 */
function CaptureForm({
  lang,
  farmId,
  blockId,
  onClose,
  onRecorded,
}: {
  lang: Lang;
  farmId: string;
  blockId: string | null;
  onClose: () => void;
  onRecorded: (observationId: string) => void;
}): ReactNode {
  const [defs, setDefs] = useState<SignalDefinition[]>([]);
  const [defId, setDefId] = useState("");
  const [value, setValue] = useState("");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    void listSignalDefinitions(farmId)
      .then((d) => {
        if (!live) return;
        setDefs(d);
        if (d.length > 0) setDefId(d[0].id);
      })
      .catch(() => setError(t(lang, "work.loadDefsFailed")));
    return () => {
      live = false;
    };
  }, [farmId, lang]);

  const chosen = defs.find((d) => d.id === defId);
  const numeric = chosen?.value_type === "numeric";

  async function save(): Promise<void> {
    if (!defId) return;
    setBusy(true);
    setError(null);
    try {
      const created = await recordObservation(defId, {
        farm_id: farmId,
        block_id: blockId,
        value_numeric: numeric && value !== "" ? Number(value) : null,
        value_categorical: !numeric && value !== "" ? value : null,
        notes: notes || null,
      });
      onRecorded(created.id);
      // Cleared, not closed: a scout usually records several readings in one
      // visit, and making them reopen the form each time is friction in a
      // field with one hand free.
      setValue("");
      setNotes("");
    } catch {
      setError(t(lang, "work.recordFailed"));
    } finally {
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

      <label htmlFor="obsnotes">{t(lang, "work.notes")}</label>
      <textarea id="obsnotes" value={notes} onChange={(e) => setNotes(e.target.value)} rows={2} />

      <div className="row">
        <button type="button" disabled={busy || !defId} onClick={() => void save()}>
          {busy ? t(lang, "work.saving") : t(lang, "work.save")}
        </button>
        <button type="button" className="link" onClick={onClose}>
          {t(lang, "work.done")}
        </button>
      </div>
    </div>
  );
}
