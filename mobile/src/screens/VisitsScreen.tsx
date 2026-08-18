import { useEffect, useState, type ReactNode } from "react";

import { claimVisit, listMyWork, listVisits, type Visit, type WorkItem } from "@/api/client";
import { signOut } from "@/auth/session";
import { dueIn, t, tCount, type Lang } from "@/i18n";
import { WorkDetailScreen } from "@/screens/WorkDetailScreen";
import { resetLangOnSignOut } from "@/i18n/preference";
import { releaseDevice } from "@/push/register";

/** Overdue first, then by deadline: a warning due in two hours outranks a
 *  critical due tomorrow, and sorting by severity alone would invert that. */
function ordered(visits: Visit[]): Visit[] {
  return [...visits].sort((a, b) => {
    if (!a.due_by) return 1;
    if (!b.due_by) return -1;
    return new Date(a.due_by).getTime() - new Date(b.due_by).getTime();
  });
}

/** A visit rendered as a work item, so one detail screen serves both. */
function asWorkItem(v: Visit, farmId: string): WorkItem {
  return {
    kind: "scouting_visit",
    id: v.id,
    farm_id: farmId,
    block_id: null,
    title: v.title,
    detail: v.instruction,
    status: v.status,
    category: v.origin,
    severity: v.severity,
    priority: v.priority,
    due_at: v.due_by,
    // The visit list does not return a template; /me/work does.
    template_id: null,
  };
}

function isOverdue(v: Visit): boolean {
  return Boolean(v.due_by && new Date(v.due_by).getTime() < Date.now());
}

function VisitRow({
  lang,
  visit,
  onClaim,
  onOpen,
}: {
  lang: Lang;
  visit: Visit;
  onClaim?: () => void;
  onOpen?: () => void;
}) {
  return (
    <li
      className={`visit sev-${visit.severity}${onOpen ? " tappable" : ""}`}
      onClick={onOpen}
    >
      <span className="ring">{dueIn(lang, visit.due_by)}</span>
      <div className="body">
        <div className="title">{visit.title}</div>
        {/* Only ad-hoc visits carry a human instruction, so it gets its own
            treatment rather than being folded into the generated title. */}
        {visit.instruction ? <div className="instruction">{visit.instruction}</div> : null}
        <div className="meta">
          <span className={`origin origin-${visit.origin}`}>{visit.origin}</span>
          {/* One visit, several zones. Without this the scout walks to a block
              knowing only that "something" fired, and has no idea whether they
              are checking one corner or half the field. */}
          {visit.source.is_group && visit.source.member_count > 0 ? (
            <span className="zones">
              {visit.source.member_count === 1
                ? t(lang, "visits.zonesOne")
                : tCount(lang, "visits.zones", visit.source.member_count)}
            </span>
          ) : null}
          {/* Direction, when there is a yesterday to compare against. Nine
              zones holding steady and nine zones up from four are different
              walks. */}
          {visit.source.trend === "spreading" || visit.source.trend === "receding" ? (
            <span className={`trend trend-${visit.source.trend}`}>
              {visit.source.trend === "spreading"
                ? `▲ ${t(lang, "visits.spreading")}`
                : `▼ ${t(lang, "visits.receding")}`}
            </span>
          ) : null}
          {/* How long it has been true. A six-day-old problem presented as this
              morning's news is how a scout learns to distrust the queue. */}
          {visit.source.day_streak > 1 ? (
            <span className="streak">
              {visit.source.day_streak === 2
                ? t(lang, "visits.sinceYesterday")
                : tCount(lang, "visits.daysRunning", visit.source.day_streak)}
            </span>
          ) : null}
        </div>
      </div>
      {onClaim ? (
        <button
          type="button"
          onClick={(e) => {
            // The row opens the detail; the button claims. Without this the
            // tap would do both.
            e.stopPropagation();
            onClaim();
          }}
        >
          {t(lang, "visits.claim")}
        </button>
      ) : null}
    </li>
  );
}

export function VisitsScreen({ lang, farmId }: { lang: Lang; farmId: string }): ReactNode {
  const [mine, setMine] = useState<Visit[]>([]);
  const [claimable, setClaimable] = useState<Visit[]>([]);
  const [board, setBoard] = useState<WorkItem[]>([]);
  const [error, setError] = useState<string | null>(null);

  async function load(): Promise<void> {
    try {
      // `/me/work` merges the three key spaces a person can be assigned in;
      // the visit calls stay because claiming still needs the visit shape and
      // `claimable` is work assigned to nobody, which is not "mine" by any
      // definition.
      const [assigned, open, work] = await Promise.all([
        listVisits(farmId, { mine: true }),
        listVisits(farmId, { claimable: true }),
        listMyWork(farmId),
      ]);
      setMine(ordered(assigned));
      setClaimable(ordered(open));
      // Visits already have their own sections above; showing them twice
      // would make one job look like two.
      setBoard(work.filter((w) => w.kind !== "scouting_visit"));
      setError(null);
    } catch {
      setError(t(lang, "visits.loadFailed"));
    }
  }

  // The list is the source of truth, not the push: a dropped notification must
  // never mean lost work, so every open reconciles.
  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [farmId]);

  const [signingOut, setSigningOut] = useState(false);
  const [open, setOpen] = useState<WorkItem | null>(null);

  const overdue = mine.filter(isOverdue);
  const current = mine.filter((v) => !isOverdue(v));

  if (open) {
    return (
      <WorkDetailScreen
        lang={lang}
        farmId={farmId}
        item={open}
        onClose={() => {
          setOpen(null);
          void load();
        }}
        onChanged={() => void load()}
      />
    );
  }

  return (
    <div className="screen visits">
      <header>
        <h1>{t(lang, "visits.title")}</h1>
        <button
          type="button"
          className="link"
          disabled={signingOut}
          onClick={() => {
            setSigningOut(true);
            // A handset passed to the next scout should open in *their*
            // language, unless somebody deliberately set this device's.
            resetLangOnSignOut();
            // Revoke first and await it: the request authenticates with the
            // access token, so clearing the session or reloading before it
            // lands would cancel it and leave this handset receiving a
            // departed scout's visits.
            void releaseDevice().finally(() => {
              signOut();
              location.reload();
            });
          }}
        >
          {t(lang, signingOut ? "visits.signingOut" : "visits.signOut")}
        </button>
      </header>

      {error ? <p className="error">{error}</p> : null}

      {overdue.length > 0 ? (
        <>
          <h2 className="section overdue">{t(lang, "visits.overdue")}</h2>
          <ul>
            {overdue.map((v) => (
              <VisitRow key={v.id} lang={lang} visit={v} onOpen={() => setOpen(asWorkItem(v, farmId))} />
            ))}
          </ul>
        </>
      ) : null}

      <h2 className="section">{t(lang, "visits.assigned")}</h2>
      <ul>
        {current.map((v) => (
          <VisitRow key={v.id} lang={lang} visit={v} onOpen={() => setOpen(asWorkItem(v, farmId))} />
        ))}
      </ul>

      {board.length > 0 ? (
        <>
          <h2 className="section">{t(lang, "work.board")}</h2>
          <ul>
            {board.map((w) => (
              <li key={w.id} className="visit work tappable" onClick={() => setOpen(w)}>
                <span className="ring">{dueIn(lang, w.due_at)}</span>
                <div className="body">
                  <div className="title">{w.title}</div>
                  {w.detail ? <div className="instruction">{w.detail}</div> : null}
                  <div className="meta">
                    <span className="origin origin-plan">{w.status}</span>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </>
      ) : null}

      <h2 className="section">{t(lang, "visits.claimable")}</h2>
      <ul>
        {claimable.map((v) => (
          <VisitRow
            key={v.id}
            lang={lang}
            visit={v}
            onClaim={async () => {
              // A 409 here means somebody else got there first; reloading shows
              // the truth rather than arguing with it.
              await claimVisit(v.id, farmId).catch(() => undefined);
              await load();
            }}
          />
        ))}
      </ul>

      {mine.length === 0 && claimable.length === 0 && board.length === 0 && !error ? (
        <p className="empty">{t(lang, "visits.empty")}</p>
      ) : null}
    </div>
  );
}
