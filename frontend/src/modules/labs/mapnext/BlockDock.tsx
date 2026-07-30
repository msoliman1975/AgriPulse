// Block Dock — the block detail surface for the Farm Console.
//
// Replaces the 372px right-hand inspector. A block's detail is mostly
// side-by-side comparisons (alerts vs. recommendations, value vs. trend,
// check vs. threshold) and a narrow column forced all of that into a single
// stack of collapsed expanders. The dock runs the full width under the map
// instead, so each view lays out in 2–3 columns with nothing collapsed.
//
// Views: Overview · Index · Conditions · Field & plan · Manage.
// See docs/proposals/block-dock.html for the design it implements.
import clsx from "clsx";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { IndexCode as ApiIndexCode } from "@/api/indices";
import { AreaDisplay } from "@/modules/farms/components/AreaDisplay";
import type { UnitDetail } from "../map/types";
import { HEALTH_DOT, INDEX_META, isBlockLevel } from "./constants";
import { DockConditionsView } from "./DockConditionsView";
import { DockIndexView } from "./DockIndexView";
import { fmt, shortDate } from "./dockFormat";
import { ManagePanel, type ManageMode } from "./ManagePanel";
import { Dot, ghostBtn } from "./ui";

export type DockTab = "overview" | "index" | "conditions" | "field" | "manage";

const TABS: DockTab[] = ["overview", "index", "conditions", "field", "manage"];

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

// ---- small layout primitives, flush (no margin) so they tile in columns ----

function Col({ title, tag, children }: { title: ReactNode; tag?: ReactNode; children: ReactNode }): ReactNode {
  return (
    <div className="flex min-h-0 flex-col gap-2 overflow-auto">
      <div className="flex items-center gap-2">
        <span className="text-xs font-bold uppercase tracking-wide text-ap-primary">{title}</span>
        {tag}
      </div>
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

export function BlockDock({
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
  const { t } = useTranslation("farmConsole");
  const [tab, setTab] = useState<DockTab>("overview");
  const [collapsed, setCollapsed] = useState(false);
  const [manageMode, setManageMode] = useState<ManageMode | null>(null);
  const [failingCount, setFailingCount] = useState<number | null>(null);

  const selId = detail?.id;
  // A new selection always lands on Overview — carrying the previous block's
  // tab (especially Manage) into a different block invites mis-edits.
  useEffect(() => {
    setTab("overview");
    setManageMode(null);
    setFailingCount(null);
  }, [selId, resetKey]);

  const onFailingCountChange = useCallback((n: number | null) => setFailingCount(n), []);

  if (error) {
    return (
      <DockShell onClose={onClose} title={t("inspector.errorTitle")}>
        <div className="p-6 text-sm text-ap-muted">{t("inspector.errorBody")}</div>
      </DockShell>
    );
  }
  if (loading || !detail) {
    return (
      <DockShell onClose={onClose} title={t("inspector.loading")}>
        <div className="grid grid-cols-3 gap-6 p-4">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-24 animate-pulse rounded-xl bg-ap-line/50" />
          ))}
        </div>
      </DockShell>
    );
  }

  const crit = detail.alerts.filter((a) => a.severity === "critical").length;
  const featured = isBlockLevel(activeIndex) ? detail.indices[activeIndex] : undefined;

  return (
    <section
      aria-label={t("dock.regionLabel")}
      className={clsx(
        "flex flex-none flex-col border-t border-ap-line bg-ap-panel",
        collapsed ? "h-[52px]" : "h-[344px]",
      )}
    >
      {/* ---- identity bar ---- */}
      <div className="flex flex-none items-center gap-3 border-b border-ap-line px-4 py-2.5">
        <h2 className="text-sm font-bold text-ap-ink">{detail.name}</h2>
        <span className="text-xs text-ap-muted">
          {detail.crop ?? t("dock.noCrop")} · <AreaDisplay areaM2={detail.area_ha * 10_000} />
        </span>
        <span className="flex items-center gap-1.5 rounded-full border border-ap-line px-2 py-0.5 text-xs font-semibold text-ap-ink">
          <Dot color={HEALTH_DOT[detail.health]} />
          {t(`health.${detail.health}`)}
        </span>

        {/* At-a-glance stats stay visible when the dock is collapsed. */}
        <div className="hidden items-center gap-4 md:flex">
          <PeekStat label={INDEX_META[activeIndex].label} value={fmt(featured?.current ?? null)} />
          <PeekStat
            label={t("dock.peek.soil")}
            value={
              detail.irrigation.soil_moisture_pct == null
                ? "—"
                : `${detail.irrigation.soil_moisture_pct}%`
            }
          />
          <PeekStat
            label={t("dock.peek.alerts")}
            value={crit ? `${detail.alerts.length} (${crit})` : String(detail.alerts.length)}
          />
        </div>

        <div className="ms-auto flex items-center gap-2">
          <span className="text-xs text-ap-muted">
            {detail.last_updated ? shortDate(detail.last_updated) : "—"}
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
        </div>
      </div>

      {collapsed ? null : (
        <>
          {/* ---- tabs ---- */}
          <div role="tablist" aria-label={t("dock.regionLabel")} className="flex flex-none gap-1 border-b border-ap-line px-3">
            {TABS.map((v) => (
              <button
                key={v}
                type="button"
                role="tab"
                aria-selected={tab === v}
                onClick={() => setTab(v)}
                className={clsx(
                  "-mb-px border-b-2 px-3 py-2 text-sm font-semibold",
                  tab === v
                    ? "border-ap-primary text-ap-ink"
                    : "border-transparent text-ap-muted hover:text-ap-ink",
                )}
              >
                {v === "manage" ? `✎ ${t("dock.tab.manage")}` : t(`dock.tab.${v}`)}
                {v === "conditions" && failingCount ? (
                  <span className="ms-1.5 rounded-full bg-ap-crit px-1.5 py-0.5 text-[10px] font-bold text-white">
                    {failingCount}
                  </span>
                ) : null}
              </button>
            ))}
          </div>

          {/* ---- viewport ---- */}
          <div className="min-h-0 flex-1 overflow-auto px-4 py-3">
            {tab === "overview" ? (
              <div className="grid h-full grid-cols-1 gap-6 lg:grid-cols-3">
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
                        <div key={i} className="rounded-lg bg-ap-bg/60 px-2.5 py-1.5 text-sm text-ap-ink">
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
                    <span className="text-3xl font-bold tabular-nums text-ap-ink">
                      {fmt(featured?.current ?? null)}
                    </span>
                    <span className="pb-1 text-xs text-ap-muted">
                      {INDEX_META[activeIndex].label}
                      <br />
                      {t("inspector.trend7d")}: {fmt(featured?.trend_7d_delta ?? null)}
                    </span>
                  </div>
                  <button
                    type="button"
                    onClick={() => setTab("index")}
                    className="self-start text-sm font-semibold text-ap-primary hover:underline"
                  >
                    {t("dock.openIndexDetail")}
                  </button>
                </Col>

                <Col title={t("dock.nextUp")}>
                  <Rows
                    items={[
                      [
                        t("inspector.next"),
                        detail.irrigation.next
                          ? `${detail.irrigation.next.volume_mm} mm · ${shortDate(detail.irrigation.next.date)}`
                          : t("inspector.none"),
                      ],
                      [
                        t("inspector.soilMoisture"),
                        detail.irrigation.soil_moisture_pct == null
                          ? "—"
                          : `${detail.irrigation.soil_moisture_pct}%`,
                      ],
                      [
                        t("dock.nextActivity"),
                        detail.activities.length
                          ? `${detail.activities[0].label} · ${shortDate(detail.activities[0].date)}`
                          : t("inspector.noActivities"),
                      ],
                    ]}
                  />
                </Col>
              </div>
            ) : null}

            {tab === "index" ? (
              <DockIndexView
                blockId={detail.id}
                activeIndex={activeIndex}
                onActiveIndexChange={onActiveIndexChange}
              />
            ) : null}

            {tab === "conditions" ? (
              <DockConditionsView blockId={detail.id} onFailingCountChange={onFailingCountChange} />
            ) : null}

            {tab === "field" ? (
              <div className="grid h-full grid-cols-1 gap-6 lg:grid-cols-3">
                <Col title={t("inspector.waterSection")}>
                  <Rows
                    items={[
                      [
                        t("inspector.last"),
                        detail.irrigation.last
                          ? `${detail.irrigation.last.volume_mm} mm · ${shortDate(detail.irrigation.last.date)}`
                          : t("inspector.none"),
                      ],
                      [
                        t("inspector.next"),
                        detail.irrigation.next
                          ? `${detail.irrigation.next.volume_mm} mm · ${shortDate(detail.irrigation.next.date)}`
                          : t("inspector.none"),
                      ],
                      [
                        t("inspector.soilMoisture"),
                        detail.irrigation.soil_moisture_pct == null
                          ? "—"
                          : `${detail.irrigation.soil_moisture_pct}% · ${detail.irrigation.soil_status}`,
                      ],
                    ]}
                  />
                  <div className="flex gap-2">
                    {detail.weather_3d.map((w) => (
                      <div
                        key={w.day}
                        className="flex-1 rounded-lg border border-ap-line px-2 py-1.5 text-center"
                      >
                        <div className="text-xs text-ap-muted">{w.day}</div>
                        <div className="text-sm font-semibold tabular-nums text-ap-ink">
                          {w.temp_c_max == null ? "—" : `${w.temp_c_max}°`}
                        </div>
                      </div>
                    ))}
                  </div>
                </Col>

                <Col title={t("inspector.activities")}>
                  {detail.activities.length ? (
                    <Rows
                      items={detail.activities
                        .slice(0, 6)
                        .map((a) => [a.label, shortDate(a.date)] as [ReactNode, ReactNode])}
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
                              `${s.value}${s.unit ? ` ${s.unit}` : ""} · ${shortDate(s.recorded_at)}`,
                            ] as [ReactNode, ReactNode],
                        )}
                    />
                  ) : (
                    <p className="text-sm text-ap-muted">{t("dock.noSignals")}</p>
                  )}
                  {detail.integration ? (
                    <Rows
                      items={[
                        [t("dock.imagerySubs"), String(detail.integration.imagery.active_subs)],
                        [t("dock.weatherSubs"), String(detail.integration.weather.active_subs)],
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
                    hasCurrentCrop={detail.crop_assignment != null}
                    gridProductId={gridProductId}
                    onDone={() => setManageMode(null)}
                  />
                </div>
              ) : (
                <div className="flex flex-wrap gap-2">
                  <button type="button" className={ghostBtn} onClick={() => setManageMode("edit")}>
                    ✎ {t("inspector.editDetails")}
                  </button>
                  <button type="button" className={ghostBtn} onClick={() => setManageMode("crop")}>
                    🌱 {t("inspector.assignCrop")}
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

function PeekStat({ label, value }: { label: string; value: string }): ReactNode {
  return (
    <span className="flex flex-col leading-tight">
      <span className="text-[10px] uppercase tracking-wide text-ap-muted">{label}</span>
      <span className="text-sm font-bold tabular-nums text-ap-ink">{value}</span>
    </span>
  );
}

function DockShell({
  title,
  onClose,
  children,
}: {
  title: ReactNode;
  onClose: () => void;
  children: ReactNode;
}): ReactNode {
  const { t } = useTranslation("farmConsole");
  return (
    <section
      aria-label={t("dock.regionLabel")}
      className="flex h-[344px] flex-none flex-col border-t border-ap-line bg-ap-panel"
    >
      <div className="flex flex-none items-center gap-3 border-b border-ap-line px-4 py-2.5">
        <h2 className="text-sm font-bold text-ap-ink">{title}</h2>
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
