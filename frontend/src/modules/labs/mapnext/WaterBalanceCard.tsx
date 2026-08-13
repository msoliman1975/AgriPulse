// Crop water balance for one block: precipitation + irrigation - ETc.
//
// Lives in the dock's Water & environment tab, beside irrigation and weather,
// because that tab owns water outright (see BlockDock's header note).
//
// The design problem this card solves is that `balance_mm` alone is not
// actionable. A deficit caused by peak crop demand, by absent rain, and by
// irrigation nobody wrote down all look identical at the headline and call for
// completely different responses — irrigate, wait for weather, or go fix the
// bookkeeping. So the derivation is shown, not hidden behind the answer.
//
// The unlogged-irrigation case gets a warning rather than a number, because a
// farm that never records irrigation shows a permanent shortfall that is an
// artefact. Presenting that as drought would train operators to ignore the
// card, which is worse than not shipping it.
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import type { ReactNode } from "react";

import { getWaterBalance, type WaterBalanceDay } from "@/api/irrigation";

interface Props {
  blockId: string;
}

/** The verdict colour for a balance, mirroring the dock's health palette. */
function toneFor(mm: number): string {
  if (mm < -5) return "#b24430"; // a real shortfall
  if (mm < 0) return "#c98a18"; // mild
  return "#4f8e4a";
}

export function WaterBalanceCard({ blockId }: Props): ReactNode {
  const { t } = useTranslation("farmConsole");
  const q = useQuery({
    queryKey: ["labs/dock/waterBalance", blockId],
    queryFn: () => getWaterBalance(blockId),
    staleTime: 5 * 60_000,
  });

  if (q.isPending) {
    return <p className="text-sm text-ap-muted">{t("dock.waterBalance.loading")}</p>;
  }
  // A failed call and an empty history are different facts and get different
  // copy: one is "we could not ask", the other "the sweep has nothing here".
  if (q.isError) {
    return <p className="text-sm text-ap-muted">{t("dock.waterBalance.loadFailed")}</p>;
  }
  const days: WaterBalanceDay[] = q.data ?? [];
  if (days.length === 0) {
    return <p className="text-sm text-ap-muted">{t("dock.waterBalance.empty")}</p>;
  }

  const latest = days[days.length - 1];
  const balance = Number(latest.balance_mm);
  const logged = latest.irrigation_logged;

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-baseline gap-2">
        <span
          className="text-lg font-semibold tabular-nums"
          style={{ color: logged ? toneFor(balance) : undefined }}
        >
          {balance > 0 ? "+" : ""}
          {balance.toFixed(1)} mm
        </span>
        <span className="text-xs text-ap-muted">
          {t("dock.waterBalance.asOf", { date: latest.date })}
        </span>
      </div>

      {/* The derivation, so the number can be argued with. */}
      <dl className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-xs">
        {(
          [
            ["cropUsed", `${Number(latest.etc_mm).toFixed(1)} mm`],
            ["rain", `${Number(latest.precip_mm).toFixed(1)} mm`],
            [
              "irrigation",
              logged ? `${Number(latest.irrigation_mm).toFixed(1)} mm` : t("dock.waterBalance.notLogged"),
            ],
            [
              "kc",
              `${Number(latest.kc_used).toFixed(2)}${
                latest.kc_source === "generic_default" ? ` · ${t("dock.waterBalance.kcGeneric")}` : ""
              }`,
            ],
          ] as const
        ).map(([key, value]) => (
          <div key={key} className="flex justify-between gap-2">
            <dt className="text-ap-muted">{t(`dock.waterBalance.${key}`)}</dt>
            <dd className="tabular-nums text-ap-ink">{value}</dd>
          </div>
        ))}
      </dl>

      {!logged ? (
        <p className="text-xs" style={{ color: "#c98a18" }}>
          {t("dock.waterBalance.unloggedWarning")}
        </p>
      ) : null}
    </div>
  );
}
