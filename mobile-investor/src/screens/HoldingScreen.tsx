import { useEffect, useState, type ReactNode } from "react";

import { fetchLatestPhoto, type Holding, type LatestPhoto } from "@/api/client";
import { HoldingMap } from "@/components/HoldingMap";
import { formatDate, t, type Lang } from "@/i18n";
import { DetailsTab } from "@/screens/DetailsTab";
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
  const [photo, setPhoto] = useState<LatestPhoto | null>(null);
  // Sharp base first: the photo is current but 10 m per pixel. One tap away.
  const [showPhoto, setShowPhoto] = useState(false);
  const [baseDate, setBaseDate] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    void fetchLatestPhoto(h.holding_id).then((p) => {
      if (live) setPhoto(p);
    });
    return () => {
      live = false;
    };
  }, [h.holding_id]);
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
          <HoldingMap
            holding={h.boundary}
            block={h.block_boundary}
            photoTileUrl={photo?.tile_url ?? null}
            photoBounds={photo?.bounds ?? null}
            showPhoto={showPhoto}
            onBaseDate={setBaseDate}
            resetLabel={t(lang, "map.reset")}
          />
          {photo ? (
            <div
              className="basemap-switch pad"
              role="radiogroup"
              aria-label={t(lang, "map.background")}
            >
              {([false, true] as const).map((latest) => (
                <button
                  key={String(latest)}
                  type="button"
                  role="radio"
                  aria-checked={showPhoto === latest}
                  className={showPhoto === latest ? "chip chip-on" : "chip"}
                  onClick={() => setShowPhoto(latest)}
                >
                  {t(lang, latest ? "map.latest" : "map.highres")}
                </button>
              ))}
            </div>
          ) : null}
          <p className="muted small pad">{t(lang, "map.hint")}</p>
          <p className="muted small pad">{t(lang, "map.legend")}</p>
          {photo && showPhoto ? (
            <p className="muted small pad">
              {t(lang, "map.photoDate", { date: formatDate(photo.scene_datetime) })}
            </p>
          ) : null}
          <p className="muted small pad">
            {baseDate
              ? t(lang, photo && showPhoto ? "map.aroundDate" : "map.baseDate", {
                  date: formatDate(baseDate),
                })
              : t(lang, "map.imagery")}
          </p>
        </div>
      ) : (
        <DetailsTab lang={lang} holding={h} />
      )}
    </section>
  );
}
