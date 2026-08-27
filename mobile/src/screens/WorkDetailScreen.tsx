import { useEffect, useState, type ReactNode } from "react";

import {
  ApiError,
  acceptVisit,
  completeActivity,
  getVisit,
  startVisit,
  submitVisit,
  type Block,
  type Visit,
  type VisitOutcome,
  type WorkItem,
} from "@/api/client";
import { CaptureForm } from "@/components/CaptureForm";
import { dueIn, t, type Lang, type MessageKey } from "@/i18n";
import { destinationOf, directionsUrl, type Destination } from "@/work/where";

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
  block,
  onClose,
  onChanged,
}: {
  lang: Lang;
  farmId: string;
  item: WorkItem;
  /** The item's block, from the list the caller already holds. Carries the
   *  centroid, which is the coarsest — and for board work the only — position
   *  a job has. Null when the block list failed or the job has no block. */
  block: Block | null;
  onClose: () => void;
  onChanged: () => void;
}): ReactNode {
  const [status, setStatus] = useState(item.status);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isVisit = item.kind === "scouting_visit";
  // One fetch, two readers: the reason text and the position. It used to sit
  // inside WhyBlock, and adding a second consumer there would have meant a
  // second request for a row the screen already had.
  const visit = useVisit(isVisit ? item.id : null, farmId);
  const destination = destinationOf(item, visit, block);

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
    // `overlay` so a round started from the capture sheet covers the tab
    // content it was opened from, rather than stacking below it.
    <div className="screen detail overlay">
      <header>
        <button type="button" className="link" onClick={onClose}>
          {t(lang, "work.back")}
        </button>
        <span className={`status status-${status}`}>{status}</span>
      </header>

      <h1>{item.title}</h1>
      {/* Where, before why: a scout reads this to decide whether to start
          walking, and a block id they cannot resolve is worse than nothing. */}
      {item.block_name ? <p className="where">{item.block_name}</p> : null}
      {item.detail ? <p className="instruction">{item.detail}</p> : null}
      <p className="meta">
        <span className="ring">{dueIn(lang, item.due_at)}</span>
        {item.category ? <span className="origin">{item.category}</span> : null}
      </p>

      <TakeMeThere lang={lang} destination={destination} />

      {isVisit ? <WhyBlock lang={lang} reason={visit?.reason_snapshot ?? null} /> : null}

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
 * A Scout DOES hold `plan_activity.complete` — #418 granted it so the work
 * could be done from the phone — so both closing buttons belong here. An
 * older comment in this spot claimed the opposite; it was stale, and believing
 * it would have removed two working controls.
 *
 * Recording needs only `signal.record`, and for an activity of type
 * "observation" the readings ARE the job.
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

  async function close(action: "complete" | "skip"): Promise<void> {
    setBusy(true);
    setError(null);
    try {
      await completeActivity(activityId, action);
      onDone();
    } catch (e) {
      // Show what the API said. A fixed string hid a 422 about the `state`
      // verb for as long as this screen has existed.
      setError(e instanceof ApiError && e.message ? e.message : t(lang, "work.actionFailed"));
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
      <button type="button" disabled={busy} onClick={() => void close("complete")}>
        {t(lang, "work.markDone")}
      </button>
      <button type="button" disabled={busy} onClick={() => void close("skip")}>
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
 * Why this job exists.
 *
 * `reason_snapshot` is untyped JSON written by whichever rule raised the
 * visit, so this renders it defensively: primitive key/value pairs, keys
 * turned back into words, and nothing at all when the shape is unrecognisable.
 * A scout who is told *why* records something useful; one who is only told
 * "go and look" records what they happen to notice.
 *
 * The reason is fetched by the parent rather than here, because the same row
 * also carries the two positions the directions control reads. A missing
 * reason is normal — ad-hoc visits carry a human instruction instead — so this
 * renders nothing rather than an error.
 */
function WhyBlock({
  lang,
  reason,
}: {
  lang: Lang;
  reason: Record<string, unknown> | null;
}): ReactNode {
  const lines = readableReason(reason);
  if (lines.length === 0) return null;

  return (
    <div className="why">
      <h2>{t(lang, "work.why")}</h2>
      {lines.map(([label, value]) => (
        <p key={label}>
          <span className="k">{label}</span> <span className="v">{value}</span>
        </p>
      ))}
    </div>
  );
}

/**
 * The visit behind this row, or null.
 *
 * `/me/work` merges two kinds of work into one shape and sends neither the
 * reason nor the position, so the detail screen asks for the visit itself. One
 * extra request on a screen the scout opened deliberately is a fair price; a
 * failure costs the "why" block and the exact pin, and the block centroid
 * still answers the directions control.
 */
function useVisit(visitId: string | null, farmId: string): Visit | null {
  const [visit, setVisit] = useState<Visit | null>(null);

  useEffect(() => {
    if (!visitId) {
      setVisit(null);
      return;
    }
    let live = true;
    void getVisit(visitId, farmId)
      .then((v) => {
        if (live) setVisit(v);
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [farmId, visitId]);

  return visit;
}

/**
 * "Take me there."
 *
 * Always rendered, and disabled rather than hidden when there is nowhere to
 * go. A control that comes and goes between two jobs teaches a scout to hunt
 * for it; one that is visibly greyed out, with a line saying why, teaches them
 * that this particular job has no position — which is a fact about the job and
 * worth knowing before they set off.
 *
 * The note under it is the honest half. Two of the three positions are the
 * middle of an area rather than a place: the maps app will still draw a
 * confident pin on the centre of a 12-hectare block, and the scout has to be
 * told that is what it is or they will walk to it and find nothing.
 */
function TakeMeThere({
  lang,
  destination,
}: {
  lang: Lang;
  destination: Destination | null;
}): ReactNode {
  if (!destination) {
    return (
      <div className="goto">
        <button type="button" className="go" disabled>
          {t(lang, "work.takeMeThere")}
        </button>
        <p className="hint">{t(lang, "work.noLocation")}</p>
      </div>
    );
  }

  const NOTE: Record<Destination["precision"], MessageKey | null> = {
    // The one case with nothing to apologise for: somebody stood on the map
    // and put the pin where they meant it.
    exact: null,
    cell: "work.atCellCentre",
    block: "work.atBlockCentre",
  };
  const note = NOTE[destination.precision];

  return (
    <div className="goto">
      {/* An anchor, not a button with a handler. Capacitor hands an external
          https URL to the system, which is what opens Google Maps on the
          directions screen; a `window.open` inside the WebView is the path
          that ends with a map rendered inside the app with no way back. */}
      <a
        className="go"
        href={directionsUrl(destination)}
        target="_blank"
        rel="noreferrer"
        // The coordinates are a number, not prose: they must read
        // left-to-right on an Arabic screen like every other number here.
        dir="ltr"
      >
        {t(lang, "work.takeMeThere")}
      </a>
      {note ? <p className="hint">{t(lang, note)}</p> : null}
    </div>
  );
}

/** At most four primitive pairs, in the order the rule wrote them. */
function readableReason(reason: Record<string, unknown> | null): [string, string][] {
  if (!reason) return [];
  return Object.entries(reason)
    .filter(([, v]) => typeof v === "string" || typeof v === "number" || typeof v === "boolean")
    .slice(0, 4)
    .map(([k, v]) => [k.replace(/_/g, " "), String(v)]);
}
