// Redesigned block inspector for /labs/map-next.
//
// Monitor view (read-only) is the default; sections are ordered
// urgency -> cause -> response -> sources. "Manage" is a one-click menu
// that delegates to the existing edit routes for v1 (write flows are
// reused, not rebuilt — see docs/proposals/farm-management-redesign.md).
import clsx from "clsx";
import { useRef, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";

import type { IndexCode, IndexSeries, UnitDetail } from "../map/types";
import { HEALTH_DOT, INDEX_META, INDEX_ORDER } from "./constants";
import {
  Dot,
  Expander,
  KV,
  MCard,
  Popover,
  PopItem,
  PopDivider,
  PopHeading,
  SectionHeader,
  Sparkline,
} from "./ui";

function fmt(v: number | null, digits = 2): string {
  return v == null ? "—" : v.toFixed(digits);
}

function deltaLabel(d: number | null): { text: string; arrow: string; color: string } {
  if (d == null) return { text: "—", arrow: "→", color: "var(--ap-muted, #6c7268)" };
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
  activeIndex: IndexCode;
  onActiveIndexChange: (c: IndexCode) => void;
  onClose: () => void;
  farmId: string;
  onScout: () => void;
}

export function Inspector({
  detail,
  loading,
  error,
  activeIndex,
  onActiveIndexChange,
  onClose,
  farmId,
  onScout,
}: Props): ReactNode {
  const { t } = useTranslation("farmConsole");
  const navigate = useNavigate();
  const manageRef = useRef<HTMLButtonElement>(null);
  const [manageOpen, setManageOpen] = useState(false);

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
  const featured = detail.indices[activeIndex];

  const manage = (path: string) => {
    setManageOpen(false);
    navigate(path);
  };

  return (
    <Shell
      onClose={onClose}
      eyebrow={`${typeLabel(detail.type, t)}${detail.crop_assignment ? ` · ${detail.crop_assignment.crop_name}` : ""}`}
      title={detail.name}
      status={
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <Badge tone={detail.health}>
            <Dot color={HEALTH_DOT[detail.health]} />
            {healthLabel(detail.health, t)}
          </Badge>
          {detail.alerts.length > 0 ? (
            <Badge tone="critical">
              ⚠ {t("inspector.alertCount", { count: detail.alerts.length })}
            </Badge>
          ) : null}
          <Badge tone="muted">{detail.area_ha.toFixed(1)} ha</Badge>
        </div>
      }
      actions={
        <div className="mt-3 flex gap-2">
          <button
            ref={manageRef}
            type="button"
            onClick={() => setManageOpen((o) => !o)}
            className="inline-flex h-8 flex-1 items-center justify-center gap-1.5 rounded-lg border border-ap-line bg-ap-panel text-[13px] font-semibold text-ap-ink hover:bg-ap-primary-soft"
          >
            ✎ {t("inspector.manage")} ▾
          </button>
          <button
            type="button"
            onClick={onScout}
            className="inline-flex h-8 flex-1 items-center justify-center gap-1.5 rounded-lg border border-ap-line bg-ap-panel text-[13px] font-semibold text-ap-ink hover:bg-ap-primary-soft"
          >
            📍 {t("inspector.scout")}
          </button>
          <Popover open={manageOpen} onClose={() => setManageOpen(false)} anchorRef={manageRef}>
            <PopHeading>{t("inspector.manageHeading")}</PopHeading>
            <PopItem icon="✎" onClick={() => manage(`/farms/${farmId}/blocks/${detail.id}/edit`)}>
              {t("inspector.editDetails")}
            </PopItem>
            <PopItem icon="🌱" onClick={() => manage(`/farms/${farmId}/blocks/${detail.id}/edit`)}>
              {t("inspector.assignCrop")}
            </PopItem>
            <PopItem icon="⬡" onClick={() => manage(`/labs/map/${farmId}?unit=${detail.id}`)}>
              {t("inspector.reshape")}
            </PopItem>
            <PopItem icon="◫" onClick={() => manage(`/labs/map/${farmId}?unit=${detail.id}`)}>
              {t("inspector.gridConfig")}
            </PopItem>
            <PopDivider />
            <PopItem icon="⊘" danger onClick={() => manage(`/labs/map/${farmId}?unit=${detail.id}`)}>
              {t("inspector.inactivate")}
            </PopItem>
          </Popover>
        </div>
      }
    >
      {/* 1 · Alerts & watches */}
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
              {[
                crit > 0 ? t("inspector.nCritical", { count: crit }) : null,
                watch > 0 ? t("inspector.nWatch", { count: watch }) : null,
              ]
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
                  "flex items-start gap-2 rounded-lg px-2.5 py-2 text-[13px]",
                  a.severity === "critical"
                    ? "bg-ap-crit-soft text-ap-crit"
                    : "bg-ap-warn-soft text-ap-warn",
                )}
              >
                <span>{a.severity === "critical" ? "🔴" : "🟠"}</span>
                <div>{a.message}</div>
              </div>
            ))}
          </div>
        )}
      </Expander>

      {/* 2 · Vegetation indices */}
      <SectionHeader>{t("inspector.indicesSection")}</SectionHeader>
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
        <div className="mt-1 text-[12px] text-ap-muted">{plainStatus(featured, t)}</div>
      </MCard>
      <div className="mx-4 mb-1 mt-2 text-[11.5px] text-ap-muted">{t("inspector.indexHint")}</div>
      <div className="mx-4 mb-2">
        {INDEX_ORDER.map((code) => {
          const s = detail.indices[code];
          const d = deltaLabel(s.trend_7d_delta);
          return (
            <div key={code} className="mt-2">
              <div className="mb-1.5 text-[11px] font-bold uppercase tracking-wide text-ap-primary">
                {INDEX_META[code].family}
              </div>
              <button
                type="button"
                onClick={() => onActiveIndexChange(code)}
                className={clsx(
                  "relative flex w-full flex-col items-start gap-0.5 rounded-xl border px-3 py-2.5 text-start transition-colors",
                  code === activeIndex
                    ? "border-ap-primary bg-ap-primary-soft"
                    : "border-ap-line hover:bg-ap-primary-soft/50",
                )}
              >
                <Dot color={trendDot(s)} className="absolute end-3 top-3" />
                <span className="text-[11.5px] font-bold tracking-wide">{INDEX_META[code].label}</span>
                <span className="text-base font-bold leading-tight tabular-nums">{fmt(s.current)}</span>
                <span className="text-[12px] font-bold" style={{ color: d.color }}>
                  {d.arrow} {d.text}
                </span>
              </button>
            </div>
          );
        })}
      </div>

      {/* 3 · Water & environment */}
      <SectionHeader>{t("inspector.waterSection")}</SectionHeader>
      <MCard icon="💧" title={t("inspector.irrigation")}>
        <KV k={t("inspector.last")} v={irrLabel(detail.irrigation.last)} />
        <KV
          k={t("inspector.next")}
          v={detail.irrigation.next?.is_emergency ? `${irrLabel(detail.irrigation.next)} ⚠` : irrLabel(detail.irrigation.next)}
          vColor={detail.irrigation.next?.is_emergency ? HEALTH_DOT.critical : undefined}
        />
        <KV
          k={t("inspector.soilMoisture")}
          v={
            detail.irrigation.soil_moisture_pct != null
              ? `${detail.irrigation.soil_moisture_pct.toFixed(0)}% · ${detail.irrigation.soil_status}`
              : "—"
          }
        />
      </MCard>
      {detail.weather_3d.length > 0 ? (
        <MCard icon="🌡️" title={t("inspector.weather")}>
          <div className="flex gap-2">
            {detail.weather_3d.map((w, i) => (
              <div key={i} className="flex-1 rounded-lg border border-ap-line py-2 text-center">
                <div className="text-[11px] text-ap-muted">{w.day}</div>
                <div className="font-bold">{w.temp_c_max != null ? `${w.temp_c_max.toFixed(0)}°C` : "—"}</div>
              </div>
            ))}
          </div>
        </MCard>
      ) : null}

      {/* 4 · Agronomy & plan */}
      <SectionHeader>{t("inspector.agronomySection")}</SectionHeader>
      <MCard icon="💡" title={t("inspector.recommendations")}>
        {detail.recommendations.length === 0 ? (
          <div className="text-[13px] text-ap-muted">{t("inspector.noRecs")}</div>
        ) : (
          <div className="space-y-1">
            {detail.recommendations.map((r, i) => (
              <div key={i} className="flex gap-2 text-[13px]">
                <span className="font-extrabold text-ap-primary">›</span>
                <span>{r}</span>
              </div>
            ))}
          </div>
        )}
      </MCard>
      {detail.activities.length > 0 ? (
        <MCard icon="📋" title={t("inspector.activities")}>
          {detail.activities.map((a, i) => (
            <KV key={i} k={a.label} v={shortDate(a.date)} />
          ))}
        </MCard>
      ) : null}
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
          {detail.plan ? (
            <KV k={t("inspector.season")} v={`${detail.plan.season_label} (${detail.plan.season_year})`} />
          ) : null}
        </MCard>
      ) : null}

      {/* 5 · Field data & sources */}
      <SectionHeader>{t("inspector.sourcesSection")}</SectionHeader>
      <Expander icon="📡" title={t("inspector.signals", { count: detail.signals.length })}>
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
  status,
  actions,
  children,
}: {
  onClose: () => void;
  eyebrow: ReactNode;
  title: ReactNode;
  status?: ReactNode;
  actions?: ReactNode;
  children?: ReactNode;
}): ReactNode {
  return (
    <div className="flex h-full flex-col bg-ap-panel">
      <div className="flex-none border-b border-ap-line px-4 py-3.5">
        <div className="text-[11px] font-bold uppercase tracking-wide text-ap-muted">{eyebrow}</div>
        <div className="mt-0.5 flex items-center gap-2.5">
          <h3 className="text-lg font-bold tracking-tight text-ap-ink">{title}</h3>
          <button
            type="button"
            onClick={onClose}
            className="ms-auto grid h-7 w-7 place-items-center rounded-lg text-ap-muted hover:bg-ap-line/50"
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
    <span className={clsx("inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[12px] font-semibold", cls[tone])}>
      {children}
    </span>
  );
}

function healthLabel(h: UnitDetail["health"], t: (k: string) => string): string {
  return t(`health.${h}`);
}
function typeLabel(ty: UnitDetail["type"], t: (k: string) => string): string {
  return t(`unitType.${ty}`);
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
