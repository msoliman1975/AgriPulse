import { useEffect, useState, type ReactNode } from "react";

import {
  acceptVisit,
  completeActivity,
  getSignalTemplate,
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
          templateId={item.template_id}
          status={status}
          busy={busy}
          onAct={act}
          onDone={onClose}
        />
      ) : (
        <BoardActions
          lang={lang}
          farmId={farmId}
          activityId={item.id}
          blockId={item.block_id}
          templateId={item.template_id}
          status={status}
          onDone={onClose}
        />
      )}
    </div>
  );
}

function VisitActions({
  lang,
  farmId,
  visitId,
  blockId,
  templateId,
  status,
  busy,
  onAct,
  onDone,
}: {
  lang: Lang;
  farmId: string;
  visitId: string;
  blockId: string | null;
  templateId: string | null;
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
          templateId={templateId}
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
 * Board work: no lifecycle, but the scout can still record what they see.
 *
 * Completing a plan activity needs `plan_activity.complete`, which a Scout
 * does not hold — so there is no Done button here. Recording needs only
 * `signal.record`, which they do hold, and for an activity of type
 * "observation" that IS the job. Telling a scout their assignment is
 * read-only, when the readings they take are the whole point, was wrong.
 */
function BoardActions({
  lang,
  farmId,
  activityId,
  blockId,
  templateId,
  status,
  onDone,
}: {
  lang: Lang;
  farmId: string;
  activityId: string;
  blockId: string | null;
  templateId: string | null;
  status: string;
  onDone: () => void;
}): ReactNode {
  const [capturing, setCapturing] = useState(false);
  const [count, setCount] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (status === "completed" || status === "skipped") {
    return <p className="hint">{t(lang, "work.alreadyClosed")}</p>;
  }

  async function close(state: "completed" | "skipped"): Promise<void> {
    setBusy(true);
    setError(null);
    try {
      await completeActivity(activityId, state);
      onDone();
    } catch {
      setError(t(lang, "work.actionFailed"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="actions">
      {error ? <p className="error">{error}</p> : null}
      <button type="button" onClick={() => setCapturing(true)}>
        {t(lang, "work.record")}
      </button>
      {count > 0 ? (
        <p className="hint">
          {t(lang, "work.recordedCount")} {count}
        </p>
      ) : null}
      {/* Two ways to close, because "I did it" and "it did not need doing"
          are different facts and the schedule is wrong in different ways. */}
      <button type="button" disabled={busy} onClick={() => void close("completed")}>
        {t(lang, "work.markDone")}
      </button>
      <button type="button" disabled={busy} onClick={() => void close("skipped")}>
        {t(lang, "work.markSkipped")}
      </button>
      {capturing ? (
        <CaptureForm
          lang={lang}
          farmId={farmId}
          blockId={blockId}
          templateId={templateId}
          onClose={() => setCapturing(false)}
          onRecorded={() => setCount((n) => n + 1)}
        />
      ) : null}
    </div>
  );
}

/**
 * Record one reading against the block.
 *
 * When the visit carries a signal template, the form shows *that* form —
 * the supervisor already said which signals this visit is about, and putting
 * the full catalogue in front of the scout is how the wrong ones get
 * recorded. Without a template it falls back to everything available.
 */
function CaptureForm({
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
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
