import { useEffect, useState, type ReactNode } from "react";

import { ApiError, cachedCall, fetchHarvest, type Harvest, type HarvestPick, type Holding } from "@/api/client";
import { formatDate, formatDateTime, formatMoney, formatNumber, ltr, t, type Lang } from "@/i18n";
import { barHeights, inPickOrder } from "@/logic/harvest";

type Load =
  | { state: "loading" }
  | { state: "error" }
  | { state: "ready"; data: Harvest; savedAt: number; offline: boolean };

export function pickLabel(lang: Lang, p: HarvestPick): string {
  const own = lang === "ar" ? p.label_ar || p.label : p.label || p.label_ar;
  return own || t(lang, "harvest.pick", { n: p.pick_no });
}

const kg = (lang: Lang, v: string | number): string =>
  t(lang, "harvest.kg", { n: formatNumber(lang, Number(v), 0) });

/** The note when a season has no picks to show. */
export function emptyNote(lang: Lang, h: Holding): string {
  if (h.period === "future") return t(lang, "harvest.notStarted");
  if (h.period === "current" && h.expected_harvest_on) {
    return t(lang, "harvest.noneYetExpected", { d: ltr(formatDate(h.expected_harvest_on)) });
  }
  return t(lang, "harvest.noneYet");
}

export function HarvestView({
  lang,
  h,
  data,
  onSeason = () => undefined,
}: {
  lang: Lang;
  h: Holding;
  data: Harvest;
  onSeason?: (s: string) => void;
}): ReactNode {
  const picks = inPickOrder(data.picks);
  const heights = barHeights(picks);
  const money = (v: string | null): string =>
    v === null ? "–" : formatMoney(lang, Number(v), data.currency);
  return (
    <>
      {h.period === "past" ? <p className="muted small">{t(lang, "harvest.ended")}</p> : null}
      {data.seasons.length > 1 ? (
        <div className="basemap-switch" role="radiogroup" aria-label={t(lang, "harvest.season")}>
          {data.seasons.map((s) => (
            <button
              key={s}
              type="button"
              role="radio"
              aria-checked={s === data.season}
              className={s === data.season ? "chip chip-on" : "chip"}
              onClick={() => onSeason(s)}
            >
              {s}
            </button>
          ))}
        </div>
      ) : null}
      {picks.length === 0 ? (
        <div className="card">
          <p className="muted small center-text">{emptyNote(lang, h)}</p>
        </div>
      ) : (
        <>
          <div className="card stats harvest-stats">
            <div className="stat-plain">
              <div className="stat-n">{formatNumber(lang, Number(data.total_weight_kg), 0)}</div>
              <div className="stat-l">{t(lang, "harvest.totalWeight")}</div>
            </div>
            <div className="stat-plain">
              <div className="stat-n">{money(data.total_revenue)}</div>
              <div className="stat-l">{t(lang, "harvest.totalRevenue")}</div>
            </div>
            <div className="stat-plain">
              <div className="stat-n">
                {data.average_price_per_kg === null
                  ? "–"
                  : formatNumber(lang, Number(data.average_price_per_kg), 2)}
              </div>
              <div className="stat-l">{t(lang, "harvest.avgPrice")}</div>
            </div>
          </div>
          <div className="card">
            <h3 className="card-title">{t(lang, "harvest.byPick")}</h3>
            <div className="chart" role="img" aria-label={t(lang, "harvest.byPick")}>
              {picks.map((p, i) => (
                <div key={p.pick_no} className="chart-col">
                  <div className="chart-bar" style={{ height: `${heights[i].toFixed(0)}%` }} />
                  <div className="chart-lbl">{p.pick_no}</div>
                </div>
              ))}
            </div>
          </div>
          <ul className="card pick-list">
            {picks.map((p) => (
              <li key={p.pick_no} className="pick">
                <span className="pick-main">
                  <span className="pick-title">{pickLabel(lang, p)}</span>
                  <span className="muted small block">
                    {ltr(formatDate(p.harvested_on))}
                    {p.price_per_kg !== null
                      ? ` · ${t(lang, "harvest.perKg", { p: formatNumber(lang, Number(p.price_per_kg), 2) })}`
                      : ""}
                  </span>
                </span>
                <span className="pick-nums">
                  <span className="pick-weight">{kg(lang, p.weight_kg)}</span>
                  {p.revenue !== null ? <span className="pick-revenue">{money(p.revenue)}</span> : null}
                </span>
              </li>
            ))}
          </ul>
          {data.total_revenue !== null ? (
            <p className="muted small center-text">{t(lang, "harvest.revenueNote")}</p>
          ) : null}
        </>
      )}
    </>
  );
}

export function HarvestTab({ lang, holding: h }: { lang: Lang; holding: Holding }): ReactNode {
  const [season, setSeason] = useState<string | null>(null);
  const [load, setLoad] = useState<Load>({ state: "loading" });
  useEffect(() => {
    if (h.period === "future") return;
    let live = true;
    setLoad({ state: "loading" });
    cachedCall(`harvest.${h.holding_id}.${season ?? "latest"}`, () => fetchHarvest(h.holding_id, season))
      .then((r) => {
        if (live) setLoad({ state: "ready", data: r.data, savedAt: r.savedAt, offline: r.offline });
      })
      .catch((err: unknown) => {
        if (!live) return;
        if (err instanceof ApiError && err.status === 404) {
          // An api before investor app v2 has no harvest route.
          const empty: Harvest = {
            holding_id: h.holding_id,
            season: null,
            seasons: [],
            currency: null,
            picks: [],
            total_weight_kg: "0",
            total_revenue: null,
            average_price_per_kg: null,
          };
          setLoad({ state: "ready", data: empty, savedAt: Date.now(), offline: false });
        } else setLoad({ state: "error" });
      });
    return () => {
      live = false;
    };
  }, [h.holding_id, h.period, season]);

  return (
    <div className="details-tab">
      {h.period === "future" ? (
        <div className="card">
          <p className="muted small center-text">{t(lang, "harvest.notStarted")}</p>
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
          <HarvestView lang={lang} h={h} data={load.data} onSeason={setSeason} />
        </>
      )}
    </div>
  );
}
