import type { ReactNode } from "react";

import type { Holding, Snapshot } from "@/api/client";
import { formatDate, formatFeddan, formatNumber, t, treeAgeYears, type Lang } from "@/i18n";

interface Props {
  lang: Lang;
  snapshot: Snapshot;
  onOpen: (h: Holding) => void;
}

export function pick(lang: Lang, en: string | null, ar: string | null): string {
  return (lang === "ar" ? ar || en : en || ar) ?? "";
}

function HoldingCard({ lang, h, onOpen }: { lang: Lang; h: Holding; onOpen: () => void }) {
  const crop = [pick(lang, h.crop_name_en, h.crop_name_ar), pick(lang, h.variety_name_en, h.variety_name_ar)]
    .filter(Boolean)
    .join(" · ");
  const age = treeAgeYears(h.planting_date);
  const facts = [
    crop,
    h.tree_count !== null ? t(lang, "holdings.trees", { n: formatNumber(lang, h.tree_count, 0) }) : "",
    age !== null ? t(lang, "holdings.years", { n: age }) : "",
  ].filter(Boolean);
  return (
    <button type="button" className="card holding-card" onClick={onOpen}>
      <div className="row-between">
        <strong>{pick(lang, h.name, h.name_ar)}</strong>
        <span className="code">{h.code}</span>
      </div>
      <div className="muted">
        {pick(lang, h.farm_name, h.farm_name_ar)} › {pick(lang, h.block_name, h.block_name_ar) || h.block_code}
      </div>
      <div className="row-between">
        <span>{formatFeddan(lang, h.area_m2)}</span>
        {h.period === "past" && h.end_date ? (
          <span className="muted small">{t(lang, "holdings.until", { d: formatDate(h.end_date) })}</span>
        ) : h.period === "future" ? (
          <span className="muted small">{t(lang, "holdings.from", { d: formatDate(h.start_date) })}</span>
        ) : null}
      </div>
      {facts.length > 0 ? <div className="muted small">{facts.join(" · ")}</div> : null}
    </button>
  );
}

export function HoldingsScreen({ lang, snapshot, onOpen }: Props): ReactNode {
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
        groups
          .filter(([, list]) => list.length > 0)
          .map(([title, list]) => (
            <div key={title} className="group">
              <h2 className="group-title">{title}</h2>
              {list.map((h) => (
                <HoldingCard key={h.holding_id} lang={lang} h={h} onOpen={() => onOpen(h)} />
              ))}
            </div>
          ))
      )}
    </section>
  );
}
