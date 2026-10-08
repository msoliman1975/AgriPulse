import { useState, type ReactNode } from "react";

import type { Holding } from "@/api/client";
import { HoldingMap } from "@/components/HoldingMap";
import { formatDate, formatFeddan, formatNumber, t, treeAgeYears, type Lang } from "@/i18n";
import { pick } from "@/screens/HoldingsScreen";

type Tab = "map" | "details";

export function HoldingScreen({
  lang,
  holding: h,
  onBack,
}: {
  lang: Lang;
  holding: Holding;
  onBack: () => void;
}): ReactNode {
  const [tab, setTab] = useState<Tab>("map");
  const unknown = t(lang, "details.unknown");
  const age = treeAgeYears(h.planting_date);
  const rows: Array<[string, string]> = [
    [t(lang, "details.code"), h.code],
    [t(lang, "details.farm"), pick(lang, h.farm_name, h.farm_name_ar) || unknown],
    [t(lang, "details.block"), pick(lang, h.block_name, h.block_name_ar) || h.block_code || unknown],
    [t(lang, "details.area"), formatFeddan(lang, h.area_m2)],
    [t(lang, "details.trees"), h.tree_count !== null ? formatNumber(lang, h.tree_count, 0) : unknown],
    [t(lang, "details.crop"), pick(lang, h.crop_name_en, h.crop_name_ar) || unknown],
    [t(lang, "details.variety"), pick(lang, h.variety_name_en, h.variety_name_ar) || unknown],
    [t(lang, "details.planted"), formatDate(h.planting_date) || unknown],
    [t(lang, "details.age"), age !== null ? t(lang, "holdings.years", { n: age }) : unknown],
    [t(lang, "details.ownerFrom"), formatDate(h.start_date)],
  ];
  if (h.end_date) rows.push([t(lang, "details.ownerTo"), formatDate(h.end_date)]);

  return (
    <section className="screen holding-screen">
      <header className="bar">
        <button
          type="button"
          className="icon-btn"
          onClick={onBack}
          aria-label={t(lang, "common.back")}
        >
          <span aria-hidden className="back-arrow">
            ‹
          </span>
        </button>
        <div className="bar-title">
          <strong>{pick(lang, h.name, h.name_ar)}</strong>
          <span className="code">{h.code}</span>
        </div>
      </header>
      <div className="tabs" role="tablist">
        {(["map", "details"] as Tab[]).map((k) => (
          <button
            key={k}
            type="button"
            role="tab"
            aria-selected={tab === k}
            className={tab === k ? "tab tab-on" : "tab"}
            onClick={() => setTab(k)}
          >
            {t(lang, k === "map" ? "tab.map" : "tab.details")}
          </button>
        ))}
      </div>
      {tab === "map" ? (
        <div className="map-wrap">
          <HoldingMap holding={h.boundary} block={h.block_boundary} />
          <p className="muted small pad">{t(lang, "map.legend")}</p>
          <p className="muted small pad">{t(lang, "map.imagery")}</p>
        </div>
      ) : (
        <dl className="details card">
          {rows.map(([k, v]) => (
            <div key={k} className="details-row">
              <dt>{k}</dt>
              <dd>{v}</dd>
            </div>
          ))}
        </dl>
      )}
    </section>
  );
}
