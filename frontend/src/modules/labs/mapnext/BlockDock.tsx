// Block Dock — the block detail surface for the Farm Console.
//
// Replaces the 372px right-hand inspector. A block's detail is mostly
// side-by-side comparisons (alerts vs. recommendations, value vs. trend,
// check vs. threshold) and a narrow column forced all of that into a single
// stack of collapsed expanders. The dock runs under the map instead, so each
// view lays out in 2–3 columns with nothing collapsed.
//
// It spans the map canvas only — it lives inside the map column, so it
// tracks the units rail as that collapses rather than sliding under it.
//
// Views: Overview · one tab per index family · Water & environment ·
// Conditions · Field & plan · Manage.
//
// The index families — Vigour & canopy, Nutrition, Moisture — are the
// grouping the first Farm Console inspector had and the 7-index flattening
// lost (see INDEX_FAMILIES). Each is a tab rather than a heading inside one
// "Index" tab, so a reader picks the question first and the acronym second.
//
// Every tab owns its data outright: water and weather live in Water &
// environment and nowhere else, activities and sources in Field & plan, and
// Overview carries only forward-looking summaries that link onward.
// See docs/proposals/block-dock.html for the design it implements.
import { useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { IndexCode as ApiIndexCode } from "@/api/indices";
import { useCapability } from "@/rbac/useCapability";
import { clearDetailCache } from "../map/api";
import type { UnitDetail, UnitIntegration } from "../map/types";
import {
  HEALTH_DOT,
  INDEX_FAMILIES,
  INDEX_META,
  isBlockLevel,
  type IndexFamilyKey,
} from "./constants";
import { DockConditionsView } from "./DockConditionsView";
import { DockFamilyView } from "./DockFamilyView";
import { cropLabel, deltaLabel, fmt, humanize, longDate, shortDate, weekday } from "./dockFormat";
import { useCropAttributeRows } from "@/modules/farms/lib/useCropAttributeRows";
import { ManagePanel, type ManageMode } from "./ManagePanel";
import { Dot, ghostBtn } from "./ui";

export type DockTab =
  | "overview"
  | "vigour"
  | "nutrition"
  | "moisture"
  | "environment"
  | "conditions"
  | "field"
  | "manage";

const TABS: DockTab[] = [
  "overview",
  "vigour",
  "nutrition",
  "moisture",
  "environment",
  "conditions",
  "field",
  "manage",
];

const FAMILY_TABS = new Set<DockTab>(INDEX_FAMILIES.map((f) => f.key));

// Conditions is the only tab behind a capability: it calls the tree-explain
// endpoint, which is gated on `recommendation.read`. Hide it rather than let
// it render and 403.
const TAB_CAPABILITY = "recommendation.read" as const;

// Height is user-draggable and remembered. The bar alone is COLLAPSED_H.
const HEIGHT_KEY = "labs/map/dockHeight";
const DEFAULT_H = 300;
const MIN_H = 160;
const COLLAPSED_H = 52;
/** Never let the dock squeeze the map to nothing. */
function maxHeight(): number {
  return typeof window === "undefined"
    ? 640
    : Math.max(MIN_H, Math.round(window.innerHeight * 0.72));
}
function clampHeight(h: number): number {
  return Math.min(maxHeight(), Math.max(MIN_H, h));
}

interface Props {
  detail: UnitDetail | undefined;
  // Loads on its own clock, off the map's critical path — may still be
  // null after `detail` has arrived.
  integration: UnitIntegration | null;
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

// ---- title-bar chip -------------------------------------------------------
// Every field in the bar is one of these, so they all share a type scale and
// only the border/value colour carries meaning.

function Chip({
  label,
  value,
  color,
}: {
  label: string;
  value: ReactNode;
  color?: string;
}): ReactNode {
  return (
    <span
      className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-lg border px-2.5 py-1 text-xs leading-none"
      style={{ borderColor: color ?? "var(--ap-line, #e8e5db)" }}
    >
      <span className="font-semibold uppercase tracking-wide text-ap-muted">{label}</span>
      <span className="font-semibold text-ap-ink" style={color ? { color } : undefined}>
        {value}
      </span>
    </span>
  );
}

// ---- column + rows --------------------------------------------------------

function Col({ title, children }: { title: ReactNode; children: ReactNode }): ReactNode {
  return (
    <div className="flex min-h-0 flex-col gap-2 overflow-auto">
      <span className="text-xs font-bold uppercase tracking-wide text-ap-primary">{title}</span>
      {children}
    </div>
  );
}

function Rows({ items }: { items: [ReactNode, ReactNode][] }): ReactNode {
  return (
    <div className="rounded-xl border border-ap-line px-3 py-1">
      {items.map(([k, v], i) => (
        <div
          key={i}
          className="flex justify-between gap-3 border-b border-ap-line/70 py-1.5 text-sm last:border-b-0"
        >
          <span className="text-ap-muted">{k}</span>
          <span className="text-end font-semibold tabular-nums text-ap-ink">{v}</span>
        </div>
      ))}
    </div>
  );
}

// Columns are sized, not stretched: on a wide screen three equal fractions
// left most of each one empty.
const COLS_3 =
  "grid h-full grid-cols-1 content-start justify-start gap-8 lg:grid-cols-[minmax(240px,360px)_minmax(240px,360px)_minmax(220px,320px)]";
const COLS_2 =
  "grid h-full grid-cols-1 content-start justify-start gap-8 lg:grid-cols-[minmax(240px,360px)_minmax(240px,400px)]";

export function BlockDock({
  detail,
  integration,
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
  // `insights` carries the shared activity-type catalogue and `weather` the
  // day labels; both are bundled eagerly, so borrowing them costs nothing and
  // beats keeping a second copy of the same words under `farmConsole`.
  const { t, i18n } = useTranslation(["farmConsole", "insights", "weather"]);
  const lang = i18n.language;
  const qc = useQueryClient();
  const [tab, setTab] = useState<DockTab>("overview");
  const [collapsed, setCollapsed] = useState(false);
  const [manageMode, setManageMode] = useState<ManageMode | null>(null);
  // Crop-attribute values for the read-only "Crop & plan" column. Shares the
  // Manage → Crop editor's query key, so the two never disagree and opening
  // the editor after viewing the summary costs no extra request. `detail` is
  // undefined while the dock loads, so guard rather than assert — the hook
  // just stays disabled until an assignment exists.
  const cropAttributeRows = useCropAttributeRows(detail?.crop_assignment?.id ?? null);
  const [failingCount, setFailingCount] = useState<number | null>(null);
  const [height, setHeight] = useState<number>(() => {
    if (typeof window === "undefined") return DEFAULT_H;
    const saved = Number(window.localStorage.getItem(HEIGHT_KEY));
    return Number.isFinite(saved) && saved > 0 ? clampHeight(saved) : DEFAULT_H;
  });
  const [dragging, setDragging] = useState(false);
  const canReadConditions = useCapability(TAB_CAPABILITY, { farmId });
  const tabs = canReadConditions ? TABS : TABS.filter((v) => v !== "conditions");

  const selId = detail?.id;
  // A new selection always lands on Overview — carrying the previous block's
  // tab (especially Manage) into a different block invites mis-edits.
  useEffect(() => {
    setTab("overview");
    setManageMode(null);
    setFailingCount(null);
  }, [selId, resetKey]);

  const onFailingCountChange = useCallback((n: number | null) => setFailingCount(n), []);

  // ---- drag-to-resize ----
  const dragRef = useRef<{ startY: number; startH: number } | null>(null);
  const startDrag = useCallback(
    (e: React.PointerEvent<HTMLButtonElement>) => {
      e.preventDefault();
      if (collapsed) return;
      dragRef.current = { startY: e.clientY, startH: height };
      setDragging(true);
      const move = (ev: PointerEvent): void => {
        const d = dragRef.current;
        if (!d) return;
        // Dragging the top edge upward makes the dock taller.
        setHeight(clampHeight(d.startH - (ev.clientY - d.startY)));
      };
      const up = (): void => {
        dragRef.current = null;
        setDragging(false);
        window.removeEventListener("pointermove", move);
        window.removeEventListener("pointerup", up);
      };
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", up);
    },
    [collapsed, height],
  );

  useEffect(() => {
    if (typeof window === "undefined" || dragging) return;
    window.localStorage.setItem(HEIGHT_KEY, String(height));
  }, [height, dragging]);

  // Keyboard resize, so the handle isn't mouse-only.
  const nudge = useCallback((delta: number) => setHeight((h) => clampHeight(h + delta)), []);

  // After any manage action, drop BOTH caches. `loadUnitDetail` keeps its own
  // 30s module-level cache that react-query invalidation does not reach, so
  // without this a freshly assigned crop keeps reading as "no crop" until it
  // ages out — which reads as "the save didn't work".
  const afterManage = useCallback(() => {
    clearDetailCache();
    void qc.invalidateQueries({ queryKey: ["labs/mapnext/detail"] });
    void qc.invalidateQueries({ queryKey: ["labs/mapnext/summary"] });
    setManageMode(null);
  }, [qc]);

  // Activity types arrive as raw enum values (`soil_prep`). The catalogue is
  // the same one the Insights calendar reads; `label` is the server-side
  // English humanisation, which is the right fallback for a type nobody has
  // translated yet.
  const activityLabel = (a: { activity_type: string; label: string }): string =>
    t(`insights:activityType.${a.activity_type}`, { defaultValue: a.label });

  if (error) {
    return (
      <DockShell onClose={onClose} title={t("inspector.errorTitle")} height={height}>
        <div className="p-6 text-sm text-ap-muted">{t("inspector.errorBody")}</div>
      </DockShell>
    );
  }
  if (loading || !detail) {
    return (
      <DockShell onClose={onClose} title={t("inspector.loading")} height={height}>
        <div className="grid grid-cols-3 gap-8 p-4">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-24 animate-pulse rounded-xl bg-ap-line/50" />
          ))}
        </div>
      </DockShell>
    );
  }

  const crit = detail.alerts.filter((a) => a.severity === "critical").length;
  const featured = isBlockLevel(activeIndex) ? detail.indices[activeIndex] : undefined;
  const healthColor = HEALTH_DOT[detail.health];
  const activeFamily = INDEX_META[activeIndex].family;
  const activeDelta = deltaLabel(featured?.trend_7d_delta);

  return (
    <section
      aria-label={t("dock.regionLabel")}
      className="flex flex-none flex-col border-t border-ap-line bg-ap-panel"
      style={{ height: collapsed ? COLLAPSED_H : height }}
    >
      {/* ---- resize handle ---- */}
      {collapsed ? null : (
        /* A button, not a bare div with role=separator: the handle must be
           focusable for the arrow keys to be reachable without a mouse. */
        <button
          type="button"
          aria-label={t("dock.resize")}
          onPointerDown={startDrag}
          onKeyDown={(e) => {
            if (e.key === "ArrowUp") {
              e.preventDefault();
              nudge(24);
            } else if (e.key === "ArrowDown") {
              e.preventDefault();
              nudge(-24);
            }
          }}
          className={clsx(
            "group relative -mt-px h-1.5 w-full flex-none cursor-row-resize",
            dragging ? "bg-ap-primary/40" : "hover:bg-ap-primary/25",
          )}
        >
          <span className="pointer-events-none absolute left-1/2 top-1/2 h-0.5 w-10 -translate-x-1/2 -translate-y-1/2 rounded-full bg-ap-line group-hover:bg-ap-primary/60" />
        </button>
      )}

      {/* ---- title bar ---- */}
      <div className="flex flex-none flex-wrap items-center gap-2 border-b border-ap-line px-4 py-2">
        <Chip label={t("dock.title.block")} value={detail.name} />
        <Chip
          label={t("dock.title.crop")}
          value={cropLabel(detail.crop_assignment) ?? t("dock.noCrop")}
        />
        <Chip
          label={t("dock.title.health")}
          value={
            <span className="inline-flex items-center gap-1.5">
              <Dot color={healthColor} />
              {t(`health.${detail.health}`)}
            </span>
          }
          color={healthColor}
        />
        <Chip
          label={t("dock.title.alerts")}
          value={
            crit
              ? t("dock.title.alertsCrit", { count: detail.alerts.length, crit })
              : detail.alerts.length
          }
          color={crit ? HEALTH_DOT.critical : undefined}
        />
        <Chip label={t("dock.title.date")} value={longDate(detail.last_updated, lang)} />

        <span className="ms-auto flex items-center gap-2">
          <span className="text-xs text-ap-muted">
            {INDEX_META[activeIndex].label} {fmt(featured?.current ?? null)}
          </span>
          <button
            type="button"
            onClick={() => setCollapsed((c) => !c)}
            aria-expanded={!collapsed}
            title={collapsed ? t("dock.expand") : t("dock.collapse")}
            className="h-7 w-7 rounded-lg border border-ap-line text-xs text-ap-muted hover:bg-ap-bg/60"
          >
            {collapsed ? "▴" : "▾"}
          </button>
          <button
            type="button"
            onClick={onClose}
            title={t("dock.close")}
            aria-label={t("dock.close")}
            className="h-7 w-7 rounded-lg border border-ap-line text-xs text-ap-muted hover:bg-ap-bg/60"
          >
            ✕
          </button>
        </span>
      </div>

      {collapsed ? null : (
        <>
          {/* ---- tabs ---- */}
          {/* Eight tabs do not fit a narrow map column, so the strip scrolls
              rather than wrapping into a second row that eats the viewport. */}
          <div
            role="tablist"
            aria-label={t("dock.regionLabel")}
            className="flex flex-none gap-1 overflow-x-auto border-b border-ap-line px-3"
          >
            {tabs.map((v) => (
              <button
                key={v}
                type="button"
                role="tab"
                aria-selected={tab === v}
                onClick={() => setTab(v)}
                className={clsx(
                  "-mb-px whitespace-nowrap border-b-2 px-3 py-2 text-sm font-semibold",
                  tab === v
                    ? "border-ap-primary text-ap-ink"
                    : "border-transparent text-ap-muted hover:text-ap-ink",
                )}
              >
                {/* A family tab is labelled from `dock.family.*`, the same key
                    the ViewBar hint and the family view read. It used to have
                    its own copy under `dock.tab.*`, so renaming a family
                    renamed it in one place and not the other. */}
                {v === "manage"
                  ? `✎ ${t("dock.tab.manage")}`
                  : FAMILY_TABS.has(v)
                    ? t(`dock.family.${v}`)
                    : t(`dock.tab.${v}`)}
                {v === "conditions" && failingCount ? (
                  <span className="ms-1.5 rounded-full bg-ap-crit px-1.5 py-0.5 text-xs font-bold text-white">
                    {failingCount}
                  </span>
                ) : null}
              </button>
            ))}
          </div>

          {/* ---- viewport ---- */}
          <div className="min-h-0 flex-1 overflow-auto px-4 py-3">
            {tab === "overview" ? (
              <div className={COLS_3}>
                <Col title={t("inspector.alertsTitle")}>
                  {detail.alerts.length ? (
                    <div className="flex flex-col gap-1.5">
                      {detail.alerts.slice(0, 4).map((a) => (
                        <div
                          key={a.id}
                          className="flex gap-2 rounded-lg border border-ap-line px-2.5 py-1.5 text-sm"
                        >
                          <span
                            className="mt-0.5 w-1 flex-none rounded-full"
                            style={{
                              backgroundColor:
                                a.severity === "critical" ? HEALTH_DOT.critical : HEALTH_DOT.watch,
                            }}
                          />
                          <span className="text-ap-ink">{a.message}</span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-sm text-ap-muted">{t("inspector.noAlerts")}</p>
                  )}
                  {detail.recommendations.length ? (
                    <div className="flex flex-col gap-1.5">
                      {detail.recommendations.slice(0, 2).map((r, i) => (
                        <div
                          key={i}
                          className="rounded-lg bg-ap-bg/60 px-2.5 py-1.5 text-sm text-ap-ink"
                        >
                          {r}
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-sm text-ap-muted">{t("inspector.noRecs")}</p>
                  )}
                </Col>

                <Col title={t("inspector.indicesSection")}>
                  <div className="flex items-end gap-3">
                    <span className="text-2xl font-bold tabular-nums text-ap-ink">
                      {fmt(featured?.current ?? null)}
                    </span>
                    <span className="pb-1 text-xs text-ap-muted">
                      {INDEX_META[activeIndex].label}
                      <br />
                      {t("inspector.trend7d")}:{" "}
                      <span style={{ color: activeDelta.color }} className="font-semibold">
                        {activeDelta.arrow} {activeDelta.text}
                      </span>
                    </span>
                  </div>
                  {/* Points at the family the map's current index belongs to,
                      so the summary and the detail are never a guess apart. */}
                  <button
                    type="button"
                    onClick={() => setTab(activeFamily)}
                    className="self-start text-sm font-semibold text-ap-primary hover:underline"
                  >
                    {t("dock.openFamily", { family: t(`dock.family.${activeFamily}`) })}
                  </button>
                </Col>

                {/* Forward-looking only. Soil moisture is a current reading, so
                    it belongs to Water & environment and is not repeated. */}
                <Col title={t("dock.nextUp")}>
                  <Rows
                    items={[
                      [
                        t("inspector.next"),
                        detail.irrigation.next
                          ? `${detail.irrigation.next.volume_mm} mm · ${shortDate(detail.irrigation.next.date, lang)}`
                          : t("inspector.none"),
                      ],
                      [
                        t("dock.nextActivity"),
                        detail.activities.length
                          ? `${activityLabel(detail.activities[0])} · ${shortDate(detail.activities[0].date, lang)}`
                          : t("inspector.noActivities"),
                      ],
                    ]}
                  />
                </Col>
              </div>
            ) : null}

            {FAMILY_TABS.has(tab) ? (
              <DockFamilyView
                blockId={detail.id}
                family={tab as IndexFamilyKey}
                indices={detail.indices}
                activeIndex={activeIndex}
                onActiveIndexChange={onActiveIndexChange}
              />
            ) : null}

            {tab === "environment" ? (
              <div className={COLS_2}>
                <Col title={t("inspector.irrigation")}>
                  <Rows
                    items={[
                      [
                        t("inspector.last"),
                        detail.irrigation.last
                          ? `${detail.irrigation.last.volume_mm} mm · ${shortDate(detail.irrigation.last.date, lang)}`
                          : t("inspector.none"),
                      ],
                      [
                        t("inspector.next"),
                        detail.irrigation.next ? (
                          // The emergency flag was computed and then dropped by
                          // the dock, so an urgent run read like a routine one.
                          <span
                            style={
                              detail.irrigation.next.is_emergency
                                ? { color: HEALTH_DOT.critical }
                                : undefined
                            }
                            title={
                              detail.irrigation.next.is_emergency ? t("dock.emergency") : undefined
                            }
                          >
                            {detail.irrigation.next.volume_mm} mm ·{" "}
                            {shortDate(detail.irrigation.next.date, lang)}
                            {detail.irrigation.next.is_emergency ? " ⚠" : ""}
                          </span>
                        ) : (
                          t("inspector.none")
                        ),
                      ],
                      [
                        t("inspector.soilMoisture"),
                        detail.irrigation.soil_moisture_pct == null
                          ? "—"
                          : `${detail.irrigation.soil_moisture_pct}% · ${t(`soilStatus.${detail.irrigation.soil_status}`)}`,
                      ],
                    ]}
                  />
                  <p className="text-xs text-ap-muted">{t("dock.soilFromSchedule")}</p>
                </Col>

                <Col title={t("inspector.weather")}>
                  {detail.weather_3d.length ? (
                    <div className="flex gap-2">
                      {detail.weather_3d.map((w, i) => (
                        <div
                          key={w.date || w.day}
                          className="flex-1 rounded-lg border border-ap-line px-2 py-1.5 text-center"
                        >
                          {/* `w.day` is a pre-rendered en-US weekday; render
                              from the raw date so the column heads follow the
                              UI language. */}
                          <div className="text-xs text-ap-muted">
                            {i === 0 ? t("weather:day.today") : weekday(w.date, lang)}
                          </div>
                          <div className="text-sm font-semibold tabular-nums text-ap-ink">
                            {w.temp_c_max == null ? "—" : `${w.temp_c_max}°`}
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    // An absent forecast used to render as nothing at all,
                    // which reads as "no weather here" rather than "no
                    // subscription, or the call failed".
                    <p className="text-sm text-ap-muted">{t("dock.noWeather")}</p>
                  )}
                </Col>
              </div>
            ) : null}

            {tab === "conditions" && canReadConditions ? (
              <DockConditionsView
                blockId={detail.id}
                farmId={farmId}
                onFailingCountChange={onFailingCountChange}
              />
            ) : null}

            {tab === "field" ? (
              <div className={COLS_3}>
                {/* The tab was called "Field & plan" while showing no plan at
                    all: crop, growth stage and season had no home after the
                    drawer's Plan section was dropped. This is that home. */}
                <Col title={t("dock.cropAndPlan")}>
                  {detail.crop_assignment || detail.plan || cropAttributeRows.length ? (
                    <Rows
                      items={[
                        ...(detail.crop_assignment
                          ? ([
                              [t("inspector.cropName"), cropLabel(detail.crop_assignment) ?? "—"],
                              [
                                t("inspector.growthStage"),
                                // Stage codes are per-crop phenology, not a
                                // fixed enum, so a crop with a bespoke stage
                                // still falls back to the humanised code.
                                detail.crop_assignment.growth_stage
                                  ? t(`growthStage.${detail.crop_assignment.growth_stage}`, {
                                      defaultValue: humanize(detail.crop_assignment.growth_stage),
                                    })
                                  : "—",
                              ],
                            ] as [ReactNode, ReactNode][])
                          : []),
                        // Platform-curated crop fields that hold a value. Empty
                        // for crops with no definitions, so this column is
                        // unchanged for anything outside the seeded set.
                        ...cropAttributeRows,
                        ...(detail.plan
                          ? ([
                              [
                                t("inspector.season"),
                                `${detail.plan.season_label} (${detail.plan.season_year})`,
                              ],
                            ] as [ReactNode, ReactNode][])
                          : []),
                      ]}
                    />
                  ) : (
                    <p className="text-sm text-ap-muted">{t("dock.noCropPlan")}</p>
                  )}
                </Col>

                <Col title={t("inspector.activities")}>
                  {detail.activities.length ? (
                    <Rows
                      items={detail.activities
                        .slice(0, 6)
                        .map(
                          (a) =>
                            [activityLabel(a), shortDate(a.date, lang)] as [ReactNode, ReactNode],
                        )}
                    />
                  ) : (
                    <p className="text-sm text-ap-muted">{t("inspector.noActivities")}</p>
                  )}
                </Col>

                <Col title={t("dock.signalsAndSources")}>
                  {detail.signals.length ? (
                    <Rows
                      items={detail.signals
                        .slice(0, 5)
                        .map(
                          (s) =>
                            [
                              s.code,
                              `${s.value}${s.unit ? ` ${s.unit}` : ""} · ${shortDate(s.recorded_at, lang)}`,
                            ] as [ReactNode, ReactNode],
                        )}
                    />
                  ) : (
                    <p className="text-sm text-ap-muted">{t("dock.noSignals")}</p>
                  )}
                  {integration ? (
                    <Rows
                      items={[
                        [t("dock.imagerySubs"), String(integration.imagery.active_subs)],
                        [t("dock.weatherSubs"), String(integration.weather.active_subs)],
                      ]}
                    />
                  ) : null}
                </Col>
              </div>
            ) : null}

            {tab === "manage" ? (
              manageMode ? (
                <div className="h-full overflow-auto">
                  <button
                    type="button"
                    onClick={() => setManageMode(null)}
                    className="mb-2 text-sm font-semibold text-ap-primary hover:underline"
                  >
                    ‹ {t("dock.tab.manage")}
                  </button>
                  <ManagePanel
                    mode={manageMode}
                    blockId={detail.id}
                    farmId={farmId}
                    gridProductId={gridProductId}
                    responsibleMembershipId={detail.responsible_membership_id}
                    onDone={afterManage}
                  />
                </div>
              ) : (
                <div className="flex flex-wrap gap-2">
                  <button type="button" className={ghostBtn} onClick={() => setManageMode("edit")}>
                    ✎ {t("inspector.editDetails")}
                  </button>
                  <button
                    type="button"
                    className={ghostBtn}
                    onClick={() => setManageMode("responsible")}
                  >
                    👤 {t("responsible.manageButton")}
                  </button>
                  <button type="button" className={ghostBtn} onClick={() => setManageMode("crop")}>
                    🌱 {t("inspector.assignCrop")}
                  </button>
                  <button
                    type="button"
                    className={ghostBtn}
                    onClick={() => setManageMode("signals")}
                  >
                    📋 {t("inspector.recordSignal")}
                  </button>
                  <button type="button" className={ghostBtn} onClick={onReshape}>
                    ⬡ {t("inspector.reshape")}
                  </button>
                  <button type="button" className={ghostBtn} onClick={() => setManageMode("grid")}>
                    ◫ {t("inspector.gridConfig")}
                  </button>
                  <button
                    type="button"
                    className={clsx(ghostBtn, "border-ap-crit/40 text-ap-crit")}
                    onClick={onInactivate}
                  >
                    ⊘ {t("inspector.inactivate")}
                  </button>
                </div>
              )
            ) : null}
          </div>
        </>
      )}
    </section>
  );
}

function DockShell({
  title,
  onClose,
  height,
  children,
}: {
  title: ReactNode;
  onClose: () => void;
  height: number;
  children: ReactNode;
}): ReactNode {
  const { t } = useTranslation("farmConsole");
  return (
    <section
      aria-label={t("dock.regionLabel")}
      className="flex flex-none flex-col border-t border-ap-line bg-ap-panel"
      style={{ height }}
    >
      <div className="flex flex-none items-center gap-3 border-b border-ap-line px-4 py-2">
        <span className="text-sm font-bold text-ap-ink">{title}</span>
        <button
          type="button"
          onClick={onClose}
          aria-label={t("dock.close")}
          className="ms-auto h-7 w-7 rounded-lg border border-ap-line text-xs text-ap-muted hover:bg-ap-bg/60"
        >
          ✕
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-auto">{children}</div>
    </section>
  );
}
