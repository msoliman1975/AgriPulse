import { useEffect, useState, type ReactNode } from "react";

import { ApiError, cachedCall, fetchActivities, type Activity, type ActivityPhoto, type Holding } from "@/api/client";
import { formatDate, formatDateTime, ltr, t, type Lang, type MessageKey } from "@/i18n";
import { activityDay, activitySummary, newestFirst } from "@/logic/activities";

type Load =
  | { state: "loading" }
  | { state: "error" }
  | { state: "ready"; list: Activity[]; savedAt: number; offline: boolean };

/** The activity's own title in the reading language, else its type. */
export function activityTitle(lang: Lang, a: Activity): string {
  const own = lang === "ar" ? a.title_ar || a.title : a.title || a.title_ar;
  if (own) return own;
  const key = `activityType.${a.activity_type}` as MessageKey;
  const label = t(lang, key);
  return label === key || label === undefined ? a.activity_type : label;
}

const DOT: Record<Activity["status"], string> = {
  completed: "✓",
  in_progress: "●",
  upcoming: "",
};

export function ActivityRow({
  lang,
  a,
  onPhoto,
}: {
  lang: Lang;
  a: Activity;
  onPhoto: (p: ActivityPhoto) => void;
}): ReactNode {
  const day = ltr(formatDate(activityDay(a)));
  return (
    <li className={`activity activity-${a.status}`}>
      <span className="activity-dot" aria-hidden>
        {DOT[a.status]}
      </span>
      <span className="activity-main">
        <span className="activity-title">{activityTitle(lang, a)}</span>
        <span className="muted small block">
          {t(lang, a.status === "completed" ? "activities.doneOn" : "activities.plannedFor", { d: day })}
        </span>
        {a.photos.length > 0 ? (
          <span className="activity-photos">
            {a.photos.slice(0, 4).map((p) => (
              <button
                key={p.url}
                type="button"
                className="activity-thumb"
                aria-label={t(lang, "activities.photo")}
                onClick={() => onPhoto(p)}
              >
                <img src={p.thumb_url} alt="" loading="lazy" />
              </button>
            ))}
          </span>
        ) : null}
      </span>
      <span className={`status-pill status-${a.status}`}>
        {t(lang, `activities.status.${a.status}` as MessageKey)}
      </span>
    </li>
  );
}

export function ActivityList({
  lang,
  list,
  onPhoto = () => undefined,
}: {
  lang: Lang;
  list: Activity[];
  onPhoto?: (p: ActivityPhoto) => void;
}): ReactNode {
  if (list.length === 0) {
    return (
      <div className="card">
        <p className="muted small center-text">{t(lang, "activities.empty")}</p>
      </div>
    );
  }
  const s = activitySummary(list);
  return (
    <>
      <div className="progress">
        <div className="progress-track">
          <div className="progress-fill" style={{ width: `${s.pct}%` }} />
        </div>
        <span className="progress-text">{ltr(`${s.pct}%`)}</span>
      </div>
      <ul className="card activity-list">
        {newestFirst(list).map((a) => (
          <ActivityRow key={a.id} lang={lang} a={a} onPhoto={onPhoto} />
        ))}
      </ul>
      <p className="muted small center-text">
        {t(lang, "activities.doneOf", { d: s.done, n: s.total })}
      </p>
    </>
  );
}

function PhotoViewer({
  lang,
  photo,
  onClose,
}: {
  lang: Lang;
  photo: ActivityPhoto;
  onClose: () => void;
}): ReactNode {
  return (
    <div className="viewer" role="dialog" aria-modal="true" onClick={onClose}>
      <img src={photo.url} alt="" />
      {photo.taken_at ? (
        <p className="viewer-caption">{ltr(formatDate(photo.taken_at))}</p>
      ) : null}
      <button type="button" className="btn viewer-close" onClick={onClose}>
        {t(lang, "activities.close")}
      </button>
    </div>
  );
}

export function ActivitiesTab({ lang, holding: h }: { lang: Lang; holding: Holding }): ReactNode {
  const [load, setLoad] = useState<Load>({ state: "loading" });
  const [photo, setPhoto] = useState<ActivityPhoto | null>(null);
  useEffect(() => {
    if (h.period === "future") return;
    let live = true;
    setLoad({ state: "loading" });
    cachedCall(`activities.${h.holding_id}`, () => fetchActivities(h.holding_id))
      .then((r) => {
        if (live) setLoad({ state: "ready", list: r.data, savedAt: r.savedAt, offline: r.offline });
      })
      .catch((err: unknown) => {
        // An api before investor app v2 has no route: show the empty state.
        if (!live) return;
        if (err instanceof ApiError && err.status === 404) {
          setLoad({ state: "ready", list: [], savedAt: Date.now(), offline: false });
        } else setLoad({ state: "error" });
      });
    return () => {
      live = false;
    };
  }, [h.holding_id, h.period]);

  return (
    <div className="details-tab">
      {h.period === "future" ? (
        <div className="card">
          <p className="muted small center-text">{t(lang, "activities.notStarted")}</p>
        </div>
      ) : load.state === "loading" ? (
        <p className="empty muted">…</p>
      ) : load.state === "error" ? (
        <p className="empty">{t(lang, "common.loadFailed")}</p>
      ) : (
        <>
          {load.offline ? (
            <p className="banner">
              {t(lang, "common.offline", { t: formatDateTime(lang, load.savedAt) })}
            </p>
          ) : null}
          <ActivityList lang={lang} list={load.list} onPhoto={setPhoto} />
        </>
      )}
      {photo ? <PhotoViewer lang={lang} photo={photo} onClose={() => setPhoto(null)} /> : null}
    </div>
  );
}
