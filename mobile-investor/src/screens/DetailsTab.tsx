import { useEffect, useState, type ReactNode } from "react";

import { cachedCall, fetchSitePhoto, type Holding, type SitePhoto } from "@/api/client";
import { formatDate, formatFeddan, formatNumber, ltr, t, treeAgeYears, type Lang, type MessageKey } from "@/i18n";
import { stageRibbon, todayIso } from "@/logic/portfolio";
import { pick } from "@/screens/HoldingsScreen";

const ACQUIRED: Record<string, MessageKey> = {
  purchase: "acquired.purchase",
  transfer: "acquired.transfer",
  inheritance: "acquired.inheritance",
  other: "acquired.other",
};

/** The newest field photo of the holding's block; stored for offline. */
function useSitePhoto(holdingId: string): SitePhoto | null {
  const [photo, setPhoto] = useState<SitePhoto | null>(null);
  useEffect(() => {
    let live = true;
    cachedCall(`site-photo.${holdingId}`, () => fetchSitePhoto(holdingId))
      .then((r) => {
        if (live) setPhoto(r.data);
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [holdingId]);
  return photo;
}

function SitePhotoCard({ lang, photo }: { lang: Lang; photo: SitePhoto }): ReactNode {
  // The link is short-lived: offline, or once it expires, the card goes away.
  const [failed, setFailed] = useState(false);
  if (failed) return null;
  return (
    <div className="card">
      <h3 className="card-title">{t(lang, "details.photoTitle")}</h3>
      <img className="site-photo" src={photo.url} alt="" onError={() => setFailed(true)} />
      {photo.taken_at ? (
        <p className="muted small center-text">
          {t(lang, "details.photoTaken", { d: ltr(formatDate(photo.taken_at)) })}
        </p>
      ) : null}
    </div>
  );
}

export function StageCard({
  lang,
  h,
  today = todayIso(),
}: {
  lang: Lang;
  h: Holding;
  today?: string;
}): ReactNode {
  const unknown = t(lang, "details.unknown");
  if (h.period === "future") {
    return (
      <div className="card">
        <h3 className="card-title">{t(lang, "details.stageTitle")}</h3>
        <p className="muted small">{t(lang, "details.notStarted")}</p>
      </div>
    );
  }
  const ribbon = stageRibbon(h.stages, h.stage_code, today);
  const first = ribbon.segments[0];
  const last = ribbon.segments[ribbon.segments.length - 1];
  return (
    <div className="card">
      <h3 className="card-title">{t(lang, "details.stageTitle")}</h3>
      <p className="stage-name">{pick(lang, h.stage_name_en, h.stage_name_ar) || unknown}</p>
      {ribbon.segments.length > 0 ? (
        <>
          <div className="ribbon" role="img" aria-label={t(lang, "details.ribbon")}>
            {ribbon.segments.map((s) => (
              <span
                key={s.code}
                className={s.code === h.stage_code ? "ribbon-seg ribbon-on" : "ribbon-seg"}
                style={{ width: `${s.widthPct}%`, background: s.color }}
                title={pick(lang, s.name_en, s.name_ar)}
              />
            ))}
            {ribbon.markerPct !== null ? (
              <span
                className="ribbon-marker"
                style={{ insetInlineStart: `${ribbon.markerPct.toFixed(1)}%` }}
              />
            ) : null}
          </div>
          <div className="ribbon-labels muted">
            <span>{pick(lang, first.name_en, first.name_ar)}</span>
            {ribbon.segments.length > 1 ? <span>{pick(lang, last.name_en, last.name_ar)}</span> : null}
          </div>
        </>
      ) : null}
      <dl className="details-inner">
        <div className="details-row">
          <dt>{t(lang, "details.stageStarted")}</dt>
          <dd>{formatDate(h.stage_started_on) || unknown}</dd>
        </div>
        <div className="details-row">
          <dt>{t(lang, "details.stageEnds")}</dt>
          <dd>{formatDate(h.stage_expected_end) || unknown}</dd>
        </div>
        <div className="details-row">
          <dt>{t(lang, "details.expectedHarvest")}</dt>
          <dd>{formatDate(h.expected_harvest_on ?? null) || unknown}</dd>
        </div>
      </dl>
    </div>
  );
}

export function factRows(lang: Lang, h: Holding): Array<[string, string]> {
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
    [t(lang, "details.season"), h.current_season || unknown],
    [t(lang, "details.planted"), formatDate(h.planting_date) || unknown],
    [t(lang, "details.age"), age !== null ? t(lang, "holdings.years", { n: age }) : unknown],
    [t(lang, "details.ownerFrom"), formatDate(h.start_date)],
  ];
  if (h.end_date) rows.push([t(lang, "details.ownerTo"), formatDate(h.end_date)]);
  if (h.acquired_by) {
    const key = ACQUIRED[h.acquired_by];
    rows.push([t(lang, "details.acquiredBy"), key ? t(lang, key) : h.acquired_by]);
  }
  if (h.contract_ref) rows.push([t(lang, "details.contractRef"), h.contract_ref]);
  return rows;
}

export function DetailsTab({ lang, holding: h }: { lang: Lang; holding: Holding }): ReactNode {
  const photo = useSitePhoto(h.holding_id);
  return (
    <div className="details-tab">
      {photo ? <SitePhotoCard lang={lang} photo={photo} /> : null}
      <StageCard lang={lang} h={h} />
      <dl className="details card">
        {factRows(lang, h).map(([k, v]) => (
          <div key={k} className="details-row">
            <dt>{k}</dt>
            <dd>{v}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
