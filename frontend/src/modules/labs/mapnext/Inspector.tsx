// Redesigned block inspector for /labs/map-next.
//
// Monitor view (read-only) by default: every section is a collapsed
// expander whose header carries a brief summary; expand for detail.
// Order: alerts → recommendations → vegetation → water → plan → sources.
// "Manage" flips the inspector into an in-place edit sub-view (ManagePanel).
import clsx from "clsx";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { IndexCode as ApiIndexCode } from "@/api/indices";
import { AreaDisplay } from "@/modules/farms/components/AreaDisplay";
import type { IndexSeries, UnitDetail } from "../map/types";
import { BLOCK_LEVEL_INDICES, HEALTH_DOT, INDEX_META, isBlockLevel } from "./constants";
import { ManagePanel, type ManageMode } from "./ManagePanel";
import { Dot, Expander, KV, MCard, Popover, PopItem, PopDivider, PopHeading, Sparkline } from "./ui";

function fmt(v: number | null, digits = 2): string {
  return v == null ? "—" : v.toFixed(digits);
}

function deltaLabel(d: number | null): { text: string; arrow: string; color: string } {
  if (d == null) return { text: "—", arrow: "→", color: HEALTH_DOT.unknown };
  if (d > 0.01) return { text: `+${d.toFixed(2)}`, arrow: "▲", color: HEALTH_DOT.healthy };
  if (d < -0.05) return { text: d.toFixed(2), arrow: "▼", color: HEALTH_DOT.critical };
  if (d < -0.01) return { text: d.toFixed(2), arrow: "▼", color: HEALTH_DOT.watch };
  return { text: "±0", arrow: "→", color: HEALTH_DOT.unknown };
}

function trendDot(s: IndexSeries): string {
  return deltaLabel(s.trend_7d_delta).color;
}

function shortDate(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
  } catch {
    return iso;
  }
}

interface Props {
  detail: UnitDetail | undefined;
  loading: boolean;
  error: boolean;
  activeIndex: ApiIndexCode;
  onActiveIndexChange: (c: ApiIndexCode) => void;
  onClose: () => void;
  farmId: string;
  gridProductId: string | null;
  onReshape: () => void;
  onInactivate: () => void;
  resetKey?: number;
}

export function Inspector({
  detail,
  loading,
  error,
  activeIndex,
  onActiveIndexChange,
  onClose,
  farmId,
  gridProductId,
  onReshape,
  onInactivate,
  resetKey,
}: Props): ReactNode {
  const { t, i18n } = useTranslation("farmConsole");
  // Directional glyphs (back chevron, rec bullet) point toward the inline
  // start, which flips under RTL.
  const rtl = i18n.dir() === "rtl";
  const manageRef = useRef<HTMLButtonElement>(null);
  const [manageOpen, setManageOpen] = useState(false);
  const [manageMode, setManageMode] = useState<ManageMode | null>(null);

  const selId = detail?.id;
  useEffect(() => {
    setManageMode(null);
    setManageOpen(false);
  }, [selId, resetKey]);

  if (error) {
    return (
      <Shell onClose={onClose} eyebrow="" title={t("inspector.errorTitle")}>
        <div className="p-6 text-center text-sm text-ap-muted">{t("inspector.errorBody")}</div>
      </Shell>
    );
  }
  if (loading || !detail) {
    return (
      <Shell onClose={onClose} eyebrow="" title={t("inspector.loading")}>
        <div className="space-y-2 p-4">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="h-20 animate-pulse rounded-xl bg-ap-line/50" />
          ))}
        </div>
      </Shell>
    );
  }

  const crit = detail.alerts.filter((a) => a.severity === "critical").length;
  const watch = detail.alerts.length - crit;
  const featured = isBlockLevel(activeIndex) ? detail.indices[activeIndex] : undefined;
  const otherIndices = BLOCK_LEVEL_INDICES.filter((c) => c !== activeIndex);

  // Manage sub-view (edit / crop / grid). Reshape + inactivate are page-level.
  if (manageMode) {
    const titles: Record<ManageMode, string> = {
      edit: t("inspector.editDetails"),
      crop: t("inspector.assignCrop"),
      grid: t("inspector.gridConfig"),
    };
    return (
      <Shell
        onClose={onClose}
        eyebrow={t("inspector.manageHeading")}
        title={
          <button type="button" onClick={() => setManageMode(null)} className="flex items-center gap-2 text-start">
            <span className="text-ap-muted">{rtl ? "›" : "‹"}</span> {titles[manageMode]}
          </button>
        }
      >
        <ManagePanel
          mode={manageMode}
          blockId={detail.id}
          farmId={farmId}
          hasCurrentCrop={detail.crop_assignment != null}
          gridProductId={gridProductId}
          onDone={() => setManageMode(null)}
        />
      </Shell>
    );
  }

  const nextIrr = detail.irrigation.next;
  const soil = detail.irrigation.soil_moisture_pct;
  const nextAct = detail.activities[0];

  return (
    <Shell
      onClose={onClose}
      eyebrow={`${t(`unitType.${detail.type}`)}${detail.crop_assignment ? ` · ${detail.crop_assignment.crop_name}` : ""}`}
      title={detail.name}
      area={<AreaDisplay areaM2={detail.area_ha * 10_000} />}
      status={
        <div className="mt-2 flex items-center gap-2">
          <Badge tone={detail.health}>
            <Dot color={HEALTH_DOT[detail.health]} />
            {t(`health.${detail.health}`)}
          </Badge>
        </div>
      }
      actions={
        <div className="relative mt-3">
          <button
            ref={manageRef}
            type="button"
            onClick={() => setManageOpen((o) => !o)}
            className="inline-flex h-8 w-full items-center justify-center gap-1.5 rounded-lg border border-ap-line bg-ap-panel text-sm font-semibold text-ap-ink hover:bg-ap-primary-soft"
          >
            ✎ {t("inspector.manage")} ▾
          </button>
          <Popover open={manageOpen} onClose={() => setManageOpen(false)} anchorRef={manageRef}>
            <PopHeading>{t("inspector.manageHeading")}</PopHeading>
            <PopItem icon="✎" onClick={() => { setManageOpen(false); setManageMode("edit"); }}>
              {t("inspector.editDetails")}
            </PopItem>
            <PopItem icon="🌱" onClick={() => { setManageOpen(false); setManageMode("crop"); }}>
              {t("inspector.assignCrop")}
            </PopItem>
            <PopItem icon="⬡" onClick={() => { setManageOpen(false); onReshape(); }}>
              {t("inspector.reshape")}
            </PopItem>
            <PopItem icon="◫" onClick={() => { setManageOpen(false); setManageMode("grid"); }}>
              {t("inspector.gridConfig")}
            </PopItem>
            <PopDivider />
            <PopItem icon="⊘" danger onClick={() => { setManageOpen(false); onInactivate(); }}>
              {t("inspector.inactivate")}
            </PopItem>
          </Popover>
        </div>
      }
    >
      {/* 1 · Alerts & watches — carries the alert summary in its header */}
      <Expander
        icon="🚨"
        title={t("inspector.alertsTitle")}
        defaultOpen={crit > 0}
        badge={
          detail.alerts.length === 0 ? (
            <Badge tone="healthy">
              <Dot color={HEALTH_DOT.healthy} /> {t("inspector.clear")}
            </Badge>
          ) : (
            <Badge tone={crit > 0 ? "critical" : "watch"}>
              {[crit > 0 ? t("inspector.nCritical", { count: crit }) : null, watch > 0 ? t("inspector.nWatch", { count: watch }) : null]
                .filter(Boolean)
                .join(" · ")}
            </Badge>
          )
        }
      >
        {detail.alerts.length === 0 ? (
          <div className="text-ap-muted">{t("inspector.noAlerts")}</div>
        ) : (
          <div className="space-y-1.5">
            {detail.alerts.map((a) => (
              <div
                key={a.id}
                className={clsx(
                  "flex items-start gap-2 rounded-lg px-2.5 py-2 text-sm",
                  a.severity === "critical" ? "bg-ap-crit-soft text-ap-crit" : "bg-ap-warn-soft text-ap-warn",
                )}
              >
                <span>{a.severity === "critical" ? "🔴" : "🟠"}</span>
                <div>{a.message}</div>
              </div>
            ))}
          </div>
        )}
      </Expander>

      {/* 2 · Recommendations — promoted to right after alerts */}
      <Expander
        icon="💡"
        title={t("inspector.recommendations")}
        defaultOpen={crit > 0 && detail.recommendations.length > 0}
        badge={<Brief>{detail.recommendations.length > 0 ? String(detail.recommendations.length) : t("inspector.none")}</Brief>}
      >
        {detail.recommendations.length === 0 ? (
          <div className="text-ap-muted">{t("inspector.noRecs")}</div>
        ) : (
          <div className="space-y-1">
            {detail.recommendations.map((r, i) => (
              <div key={i} className="flex gap-2 text-sm">
                <span className="font-extrabold text-ap-primary">{rtl ? "‹" : "›"}</span>
                <span>{r}</span>
              </div>
            ))}
          </div>
        )}
      </Expander>

      {/* 3 · Vegetation index — selected featured; the rest collapsed here */}
      <Expander
        icon="🛰️"
        title={t("inspector.indicesSection")}
        badge={
          <Brief>
            {INDEX_META[activeIndex].label}
            {featured ? ` ${fmt(featured.current)} ${deltaLabel(featured.trend_7d_delta).arrow}` : ""}
          </Brief>
        }
      >
        {featured ? (
          <MCard
            icon="🛰️"
            title={`${INDEX_META[activeIndex].label} · ${INDEX_META[activeIndex].meaning}`}
            value={fmt(featured.current)}
            valueColor={trendDot(featured)}
          >
            <Sparkline points={featured.series_30d.map((p) => p.value)} color="#356b30" />
            <KV
              k={t("inspector.trend7d")}
              v={`${deltaLabel(featured.trend_7d_delta).arrow} ${deltaLabel(featured.trend_7d_delta).text}`}
              vColor={deltaLabel(featured.trend_7d_delta).color}
            />
            <div className="mt-1 text-xs text-ap-muted">{plainStatus(featured, t)}</div>
          </MCard>
        ) : (
          <div className="mx-1 mb-2 rounded-lg bg-ap-bg/60 px-3 py-2 text-xs text-ap-muted">
            {t("inspector.gridOnlyIndex", { code: INDEX_META[activeIndex].label })}
          </div>
        )}
        <div className="mx-1 mb-1 mt-1 text-xs text-ap-muted">{t("inspector.otherIndices")}</div>
        <div className="grid grid-cols-3 gap-1.5">
          {otherIndices.map((code) => {
            const s = detail.indices[code];
            const d = deltaLabel(s.trend_7d_delta);
            return (
              <button
                key={code}
                type="button"
                onClick={() => onActiveIndexChange(code)}
                title={INDEX_META[code].meaning}
                className="relative flex flex-col items-start gap-0.5 rounded-lg border border-ap-line px-2.5 py-2 text-start hover:bg-ap-primary-soft/50"
              >
                <Dot color={trendDot(s)} className="absolute end-2 top-2" />
                <span className="text-xs font-bold tracking-wide">{INDEX_META[code].label}</span>
                <span className="text-base font-bold leading-tight tabular-nums">{fmt(s.current)}</span>
                <span className="text-xs font-bold" style={{ color: d.color }}>
                  {d.arrow} {d.text}
                </span>
              </button>
            );
          })}
        </div>
      </Expander>

      {/* 4 · Water & environment */}
      <Expander
        icon="💧"
        title={t("inspector.waterSection")}
        badge={
          <Brief>
            {soil != null ? `${soil.toFixed(0)}%` : nextIrr ? shortDate(nextIrr.date) : "—"}
          </Brief>
        }
      >
        <MCard icon="💧" title={t("inspector.irrigation")}>
          <KV k={t("inspector.last")} v={irrLabel(detail.irrigation.last)} />
          <KV
            k={t("inspector.next")}
            v={nextIrr?.is_emergency ? `${irrLabel(nextIrr)} ⚠` : irrLabel(nextIrr)}
            vColor={nextIrr?.is_emergency ? HEALTH_DOT.critical : undefined}
          />
          <KV
            k={t("inspector.soilMoisture")}
            v={soil != null ? `${soil.toFixed(0)}% · ${detail.irrigation.soil_status}` : "—"}
          />
        </MCard>
        {detail.weather_3d.length > 0 ? (
          <MCard icon="🌡️" title={t("inspector.weather")}>
            <div className="flex gap-2">
              {detail.weather_3d.map((w, i) => (
                <div key={i} className="flex-1 rounded-lg border border-ap-line py-2 text-center">
                  <div className="text-xs text-ap-muted">{w.day}</div>
                  <div className="text-sm font-bold">{w.temp_c_max != null ? `${w.temp_c_max.toFixed(0)}°C` : "—"}</div>
                </div>
              ))}
            </div>
          </MCard>
        ) : null}
      </Expander>

      {/* 5 · Plan & activities */}
      <Expander
        icon="📋"
        title={t("inspector.agronomySection")}
        badge={<Brief>{nextAct ? `${nextAct.label} · ${shortDate(nextAct.date)}` : t("inspector.none")}</Brief>}
      >
        {detail.activities.length > 0 ? (
          <MCard icon="📋" title={t("inspector.activities")}>
            {detail.activities.map((a, i) => (
              <KV key={i} k={a.label} v={shortDate(a.date)} />
            ))}
          </MCard>
        ) : (
          <div className="mb-2 text-sm text-ap-muted">{t("inspector.noActivities")}</div>
        )}
        {detail.crop_assignment || detail.plan ? (
          <MCard icon="🌱" title={t("inspector.crop")}>
            {detail.crop_assignment ? (
              <>
                <KV
                  k={t("inspector.cropName")}
                  v={[detail.crop_assignment.crop_name, detail.crop_assignment.variety_name, detail.crop_assignment.strain_name]
                    .filter(Boolean)
                    .join(" · ")}
                />
                {detail.crop_assignment.growth_stage ? (
                  <KV k={t("inspector.growthStage")} v={detail.crop_assignment.growth_stage} />
                ) : null}
              </>
            ) : null}
            {detail.plan ? <KV k={t("inspector.season")} v={`${detail.plan.season_label} (${detail.plan.season_year})`} /> : null}
          </MCard>
        ) : null}
      </Expander>

      {/* 6 · Field data & sources */}
      <Expander icon="📡" title={t("inspector.signals", { count: detail.signals.length })} badge={<Brief>{String(detail.signals.length)}</Brief>}>
        {detail.signals.length === 0 ? (
          <div className="text-ap-muted">{t("inspector.noSignals")}</div>
        ) : (
          detail.signals.map((s, i) => (
            <KV key={i} k={s.code} v={`${s.value}${s.unit ? ` ${s.unit}` : ""} · ${shortDate(s.recorded_at)}`} />
          ))
        )}
      </Expander>
      <Expander icon="🔌" title={t("inspector.integration")}>
        {detail.integration ? (
          <div className="space-y-1">
            <KV
              k={t("inspector.imagery")}
              v={t("inspector.subsActive", { count: detail.integration.imagery.active_subs })}
              vColor={detail.integration.imagery.failed_24h > 0 ? HEALTH_DOT.critical : undefined}
            />
            <KV
              k={t("inspector.weatherInteg")}
              v={t("inspector.subsActive", { count: detail.integration.weather.active_subs })}
              vColor={detail.integration.weather.failed_24h > 0 ? HEALTH_DOT.critical : undefined}
            />
          </div>
        ) : (
          <div className="text-ap-muted">{t("inspector.noInteg")}</div>
        )}
      </Expander>
      <div className="h-6" />
    </Shell>
  );
}

// ---- shell + small bits ---------------------------------------------------
function Shell({
  onClose,
  eyebrow,
  title,
  area,
  status,
  actions,
  children,
}: {
  onClose: () => void;
  eyebrow: ReactNode;
  title: ReactNode;
  area?: ReactNode;
  status?: ReactNode;
  actions?: ReactNode;
  children?: ReactNode;
}): ReactNode {
  return (
    <div className="flex h-full flex-col bg-ap-panel">
      <div className="flex-none border-b border-ap-line px-4 py-3.5">
        <div className="text-xs font-bold uppercase tracking-wide text-ap-muted">{eyebrow}</div>
        <div className="mt-0.5 flex items-baseline gap-2">
          <h3 className="text-lg font-bold tracking-tight text-ap-ink">{title}</h3>
          {area ? <span className="text-xs text-ap-muted">{area}</span> : null}
          <button
            type="button"
            onClick={onClose}
            className="ms-auto grid h-7 w-7 place-items-center self-start rounded-lg text-ap-muted hover:bg-ap-line/50"
            aria-label="Close"
          >
            ✕
          </button>
        </div>
        {status}
        {actions}
      </div>
      <div className="flex-1 overflow-auto pb-4">{children}</div>
    </div>
  );
}

function Brief({ children }: { children: ReactNode }): ReactNode {
  return <span className="text-xs font-semibold text-ap-muted">{children}</span>;
}

function Badge({
  tone,
  children,
}: {
  tone: "healthy" | "watch" | "critical" | "unknown" | "muted";
  children: ReactNode;
}): ReactNode {
  const cls: Record<string, string> = {
    healthy: "bg-ap-primary-soft text-ap-primary",
    watch: "bg-ap-warn-soft text-ap-warn",
    critical: "bg-ap-crit-soft text-ap-crit",
    unknown: "bg-ap-line/50 text-ap-muted",
    muted: "bg-ap-line/40 text-ap-muted",
  };
  return (
    <span className={clsx("inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold", cls[tone])}>
      {children}
    </span>
  );
}

function irrLabel(e: { date: string; volume_mm: number } | null): string {
  if (!e) return "—";
  return `${e.volume_mm.toFixed(0)} mm · ${shortDate(e.date)}`;
}
function plainStatus(s: IndexSeries, t: (k: string) => string): string {
  const d = s.trend_7d_delta;
  if (d == null) return t("inspector.statusFlat");
  if (d > 0.01) return t("inspector.statusUp");
  if (d < -0.05) return t("inspector.statusDownHard");
  if (d < -0.01) return t("inspector.statusDown");
  return t("inspector.statusFlat");
}
