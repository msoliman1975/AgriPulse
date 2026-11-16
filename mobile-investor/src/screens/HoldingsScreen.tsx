import { useEffect, useState, type ReactNode } from "react";

import { cachedCall, fetchActivities, type Holding, type Snapshot } from "@/api/client";
import { CropAvatar } from "@/components/CropAvatar";
import { formatDate, formatNumber, ltr, M2_PER_FEDDAN, t, type Lang } from "@/i18n";
import { completedActivities, portfolioStats, stageColor } from "@/logic/portfolio";

interface Props {
  lang: Lang;
  snapshot: Snapshot;
  onOpen: (h: Holding) => void;
}

export function pick(lang: Lang, en: string | null, ar: string | null): string {
  return (lang === "ar" ? ar || en : en || ar) ?? "";
}

export function HoldingCard({
  lang,
  h,
  onOpen,
}: {
  lang: Lang;
  h: Holding;
  onOpen: () => void;
}): ReactNode {
  const crop = [pick(lang, h.crop_name_en, h.crop_name_ar), pick(lang, h.variety_name_en, h.variety_name_ar)]
    .filter(Boolean)
    .join(" ");
  const color = stageColor(h.stages, h.stage_code);
  const stage = pick(lang, h.stage_name_en, h.stage_name_ar);
  const place = [
    pick(lang, h.farm_name, h.farm_name_ar),
    pick(lang, h.block_name, h.block_name_ar) || h.block_code,
  ]
    .filter(Boolean)
    .join(" › ");
  return (
    <button type="button" className="card holding-card" onClick={onOpen}>
      <CropAvatar
        src={h.crop_icon_url ?? h.crop_image_url}
        name={pick(lang, h.crop_name_en, h.crop_name_ar)}
        color={color}
      />
      <span className="holding-main">
        <span className="row-between">
          <strong>{pick(lang, h.name, h.name_ar)}</strong>
          <span className="code">{h.code}</span>
        </span>
        <span className="muted small block">{[place, crop].filter(Boolean).join(" · ")}</span>
        <span className="holding-meta">
          <span className="pill">
            {formatNumber(lang, Number(h.area_m2) / M2_PER_FEDDAN, 2)} {t(lang, "unit.feddan")}
          </span>
          {h.tree_count !== null ? (
            <span className="pill">
              {t(lang, "holdings.trees", { n: formatNumber(lang, h.tree_count, 0) })}
            </span>
          ) : null}
          {h.period === "current" && stage ? (
            <span className="pill pill-stage" style={{ borderColor: color }}>
              <span className="pill-dot" style={{ background: color }} />
              {stage}
            </span>
          ) : null}
          {h.period === "past" && h.end_date ? (
            <span className="muted small">{t(lang, "holdings.until", { d: ltr(formatDate(h.end_date)) })}</span>
          ) : h.period === "future" ? (
            <span className="muted small">{t(lang, "holdings.from", { d: ltr(formatDate(h.start_date)) })}</span>
          ) : null}
        </span>
      </span>
      <span className="chev" aria-hidden>
        ›
      </span>
    </button>
  );
}

/**
 * Decision D6: the activities completed this season across current holdings,
 * from each holding's activities call (stored for offline like /holdings).
 * Null while loading or when a call fails with nothing stored.
 */
function useCompletedThisSeason(snapshot: Snapshot): number | null {
  const [n, setN] = useState<number | null>(null);
  useEffect(() => {
    let live = true;
    const current = snapshot.holdings.filter((h) => h.period === "current");
    Promise.all(
      current.map((h) =>
        cachedCall(`activities.${h.holding_id}`, () => fetchActivities(h.holding_id)).then(
          (r) => r.data,
        ),
      ),
    )
      .then((lists) => {
        if (live) setN(completedActivities(lists));
      })
      .catch(() => {
        if (live) setN(null);
      });
    return () => {
      live = false;
    };
  }, [snapshot.savedAt, snapshot.holdings]);
  return n;
}

export function PortfolioStats({
  lang,
  holdings,
  completed,
}: {
  lang: Lang;
  holdings: Holding[];
  completed: number | null;
}): ReactNode {
  const s = portfolioStats(holdings);
  const tiles: Array<[string, string]> = [
    [formatNumber(lang, s.currentCount, 0), t(lang, "stats.current")],
    [formatNumber(lang, s.currentAreaM2 / M2_PER_FEDDAN, 1), t(lang, "stats.area")],
    [completed === null ? "–" : formatNumber(lang, completed, 0), t(lang, "stats.activities")],
  ];
  return (
    <div className="stats">
      {tiles.map(([n, l]) => (
        <div key={l} className="stat">
          <div className="stat-n">{n}</div>
          <div className="stat-l">{l}</div>
        </div>
      ))}
    </div>
  );
}

export function HoldingsScreen({ lang, snapshot, onOpen }: Props): ReactNode {
  const completed = useCompletedThisSeason(snapshot);
  const groups: Array<[string, Holding[]]> = [
    [t(lang, "holdings.current"), snapshot.holdings.filter((h) => h.period === "current")],
    [t(lang, "holdings.future"), snapshot.holdings.filter((h) => h.period === "future")],
    [t(lang, "holdings.previous"), snapshot.holdings.filter((h) => h.period === "past")],
  ];
  return (
    <section className="screen">
      {snapshot.holdings.length === 0 ? (
        <p className="empty">{t(lang, "holdings.empty")}</p>
      ) : (
        <>
          <PortfolioStats lang={lang} holdings={snapshot.holdings} completed={completed} />
          {groups
            .filter(([, list]) => list.length > 0)
            .map(([title, list]) => (
              <div key={title} className="group">
                <h2 className="group-title">{title}</h2>
                {list.map((h) => (
                  <HoldingCard key={h.holding_id} lang={lang} h={h} onOpen={() => onOpen(h)} />
                ))}
              </div>
            ))}
        </>
      )}
    </section>
  );
}
