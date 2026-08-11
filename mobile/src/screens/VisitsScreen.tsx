import { useEffect, useState, type ReactNode } from "react";

import { claimVisit, listMyWork, listVisits, type Visit, type WorkItem } from "@/api/client";
import { signOut } from "@/auth/session";
import { dueIn, t, type Lang } from "@/i18n";
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

function isOverdue(v: Visit): boolean {
  return Boolean(v.due_by && new Date(v.due_by).getTime() < Date.now());
}

function VisitRow({ lang, visit, onClaim }: { lang: Lang; visit: Visit; onClaim?: () => void }) {
  return (
    <li className={`visit sev-${visit.severity}`}>
      <span className="ring">{dueIn(lang, visit.due_by)}</span>
      <div className="body">
        <div className="title">{visit.title}</div>
        {/* Only ad-hoc visits carry a human instruction, so it gets its own
            treatment rather than being folded into the generated title. */}
        {visit.instruction ? <div className="instruction">{visit.instruction}</div> : null}
        <div className="meta">
          <span className={`origin origin-${visit.origin}`}>{visit.origin}</span>
        </div>
      </div>
      {onClaim ? (
        <button type="button" onClick={onClaim}>
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

  const overdue = mine.filter(isOverdue);
  const current = mine.filter((v) => !isOverdue(v));

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
              <VisitRow key={v.id} lang={lang} visit={v} />
            ))}
          </ul>
        </>
      ) : null}

      <h2 className="section">{t(lang, "visits.assigned")}</h2>
      <ul>
        {current.map((v) => (
          <VisitRow key={v.id} lang={lang} visit={v} />
        ))}
      </ul>

      {board.length > 0 ? (
        <>
          <h2 className="section">{t(lang, "work.board")}</h2>
          <ul>
            {board.map((w) => (
              <li key={w.id} className="visit work">
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
