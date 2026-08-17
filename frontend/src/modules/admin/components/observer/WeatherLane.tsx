import clsx from "clsx";
import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Card } from "@/components/Card";
import { EmptyState } from "@/components/EmptyState";
import { Pill } from "@/components/Pill";
import { Skeleton } from "@/components/Skeleton";
import { Table, Tbody, Td, Th, Thead, Tr } from "@/components/Table";
import { StageRibbon } from "@/modules/admin/components/observer/StageRibbon";
import { useWeatherAttempts, useWeatherDayExplain, useWeatherOverview } from "@/queries/observer";

/**
 * The weather lane.
 *
 * No blocks: weather is measured at one farm centroid, so a block filter
 * would change nothing and offering one would be a lie about the data model.
 *
 * The hour-coverage strip is the piece that does not exist anywhere else in
 * the product. A day derived from nine hourly rows produces a confident ET₀
 * that is wrong, and nothing downstream distinguishes it from a full day —
 * so the days that would fail a coverage floor are called out even though the
 * derivation applies no floor of its own.
 */

function HourStrip({ hours, floor }: { hours: number; floor: number }): ReactNode {
  return (
    <span className="inline-flex gap-[2px]" aria-hidden>
      {Array.from({ length: 24 }, (_, h) => (
        <span
          key={h}
          className={clsx(
            "inline-block h-3 w-[5px] rounded-[1px]",
            h < hours ? (hours >= floor ? "bg-ap-primary" : "bg-ap-warn") : "bg-ap-line",
          )}
        />
      ))}
    </span>
  );
}

export function WeatherLane({
  tenantId,
  farmId,
  windowFrom,
  windowTo,
}: {
  tenantId: string;
  farmId: string;
  windowFrom: string;
  windowTo: string;
}): ReactNode {
  const { t, i18n } = useTranslation("admin");
  const [openDay, setOpenDay] = useState<string | null>(null);

  const overview = useWeatherOverview(tenantId, farmId, windowFrom, windowTo);
  const attempts = useWeatherAttempts(tenantId, farmId, windowFrom, windowTo);
  const explain = useWeatherDayExplain(tenantId, farmId, "evapotranspiration", openDay);

  if (overview.isPending) return <Skeleton className="h-64 w-full" />;
  if (!overview.data) return null;

  const w = overview.data;

  return (
    <>
      <Card title={t("observer.weather.notice")} bodyClassName="text-xs text-ap-muted">
        {t("observer.weather.farmScoped")}
      </Card>

      {!w.subscribed ? (
        <Card title={t("observer.weather.title")}>
          <EmptyState message={t("observer.weather.notSubscribed")} />
        </Card>
      ) : (
        <>
          <StageRibbon
            overview={{
              farm_id: w.farm_id,
              block_count: 1,
              window_from: w.window_from,
              window_to: w.window_to,
              stages: w.stages,
              calc_versions: [],
              problems: [],
              trend_product_ambiguous: false,
              consumers_are_window_proxy: false,
            }}
            selectedStage={null}
            onSelectStage={() => undefined}
          />

          <Card
            title={t("observer.weather.coverage")}
            actions={
              w.thin_days.length ? (
                <Pill kind="warn">
                  {t("observer.weather.thinDays", { count: w.thin_days.length })}
                </Pill>
              ) : null
            }
          >
            <p className="mb-3 text-xs text-ap-muted">
              {t("observer.weather.coverageExplain", { floor: w.coverage_floor_hours })}
            </p>
            {!w.derivation_enforces_floor ? (
              <p className="mb-3 border-s-2 border-ap-warn ps-3 text-xs">
                {t("observer.weather.noFloor")}
              </p>
            ) : null}

            {w.coverage.length === 0 ? (
              <EmptyState message={t("observer.weather.noObservations")} />
            ) : (
              <Table className="text-xs">
                <Thead>
                  <Tr>
                    <Th>{t("observer.weather.day")}</Th>
                    <Th>{t("observer.weather.hours")}</Th>
                    <Th className="text-end">{t("observer.weather.hoursCount")}</Th>
                    <Th>{t("observer.weather.derived")}</Th>
                    <Th className="text-end">{t("observer.weather.indexRows")}</Th>
                    <Th />
                  </Tr>
                </Thead>
                <Tbody>
                  {w.coverage.map((d) => {
                    const thin = d.hours < w.coverage_floor_hours;
                    return (
                      <Tr
                        key={d.day}
                        className={clsx(thin && d.has_derived && "bg-ap-warn-soft/30")}
                      >
                        <Td className="tabular-nums">{d.day}</Td>
                        <Td>
                          <HourStrip hours={d.hours} floor={w.coverage_floor_hours} />
                        </Td>
                        <Td className="text-end tabular-nums">{d.hours} / 24</Td>
                        <Td>
                          {d.has_derived ? (
                            <Pill kind={thin ? "warn" : "ok"}>
                              {thin
                                ? t("observer.weather.derivedThin")
                                : t("observer.weather.derivedOk")}
                            </Pill>
                          ) : (
                            <span className="text-ap-muted">—</span>
                          )}
                        </Td>
                        <Td className="text-end tabular-nums">{d.index_rows}</Td>
                        <Td>
                          <button
                            type="button"
                            className="text-ap-accent underline"
                            onClick={() => setOpenDay(openDay === d.day ? null : d.day)}
                          >
                            {t("observer.weather.explain")}
                          </button>
                        </Td>
                      </Tr>
                    );
                  })}
                </Tbody>
              </Table>
            )}
          </Card>

          {openDay ? (
            <Card title={t("observer.weather.explainTitle", { day: openDay })}>
              {explain.isPending ? (
                <Skeleton className="h-32 w-full" />
              ) : explain.data ? (
                <>
                  <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
                    <Pill kind={explain.data.coverage_sufficient ? "ok" : "warn"}>
                      {t("observer.weather.builtFrom", {
                        present: explain.data.hours_present,
                        expected: explain.data.hours_expected,
                      })}
                    </Pill>
                  </div>
                  <pre className="whitespace-pre-wrap rounded bg-ap-bg/60 p-3 font-mono text-xs leading-relaxed">
                    {JSON.stringify(
                      {
                        index: explain.data.index,
                        derived: explain.data.derived,
                        hourly_rows: explain.data.hourly.length,
                      },
                      null,
                      2,
                    )}
                  </pre>
                </>
              ) : (
                <p className="text-xs text-ap-muted">{t("observer.weather.noIndexRow")}</p>
              )}
            </Card>
          ) : null}

          <Card title={t("observer.weather.attempts")} noPadding>
            {(attempts.data ?? []).length === 0 ? (
              <p className="p-4 text-xs text-ap-muted">{t("observer.weather.noAttempts")}</p>
            ) : (
              <Table className="text-xs">
                <Thead>
                  <Tr>
                    <Th>{t("observer.weather.started")}</Th>
                    <Th>{t("observer.weather.provider")}</Th>
                    <Th>{t("observer.scenes.status")}</Th>
                    <Th className="text-end">{t("observer.weather.rows")}</Th>
                    <Th className="text-end">{t("observer.scenes.duration")}</Th>
                    <Th>{t("observer.scenes.error")}</Th>
                  </Tr>
                </Thead>
                <Tbody>
                  {(attempts.data ?? []).map((a) => (
                    <Tr key={a.id}>
                      <Td className="tabular-nums">
                        {new Date(a.started_at).toLocaleString(i18n.language)}
                      </Td>
                      <Td>{a.provider_code}</Td>
                      <Td>
                        <Pill kind={a.status === "succeeded" ? "ok" : "crit"}>{a.status}</Pill>
                      </Td>
                      <Td className="text-end tabular-nums">{a.rows_ingested ?? "—"}</Td>
                      <Td className="text-end tabular-nums">{a.duration_ms ?? "—"}</Td>
                      <Td className="truncate" title={a.error_message ?? ""}>
                        {a.error_code ?? ""}
                      </Td>
                    </Tr>
                  ))}
                </Tbody>
              </Table>
            )}
          </Card>
        </>
      )}
    </>
  );
}
