import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import type { ReactNode } from "react";

import { getGridCellHistory } from "../../api/grid";
import type { IndexCode } from "../../api/indices";
import { Drawer } from "../../shell/Drawer";

interface Props {
  open: boolean;
  cellId: string | null;
  productId: string | null;
  indexCode: IndexCode;
  onClose: () => void;
}

// Sparkline dimensions kept small so the drawer doesn't dominate the
// map; the user can always click out to the full block-level chart.
const W = 320;
const H = 120;
const PAD = { top: 8, right: 8, bottom: 18, left: 28 };

export function GridCellDrawer({
  open,
  cellId,
  productId,
  indexCode,
  onClose,
}: Props): ReactNode {
  const { t } = useTranslation("farms");

  const { data, isLoading, isError } = useQuery({
    queryKey: ["grid-cell-history", cellId, productId, indexCode],
    queryFn: () => {
      if (!cellId || !productId) throw new Error("cellId + productId required");
      return getGridCellHistory(cellId, productId, indexCode);
    },
    enabled: open && cellId !== null && productId !== null,
  });

  return (
    <Drawer
      open={open}
      onClose={onClose}
      title={t("subblockGrid.cellDrawerTitle", { defaultValue: "Cell history" })}
    >
      {isLoading && (
        <p className="text-sm text-ap-muted">{t("common.loading", { defaultValue: "Loading…" })}</p>
      )}
      {isError && (
        <p className="text-sm text-ap-crit">
          {t("subblockGrid.historyError", { defaultValue: "Could not load cell history." })}
        </p>
      )}
      {data && (
        <>
          <p className="mb-2 text-xs uppercase tracking-wide text-ap-muted">{indexCode}</p>
          <CellSparkline points={data.points} />
          <CellSummary points={data.points} />
        </>
      )}
    </Drawer>
  );
}

function CellSparkline({
  points,
}: {
  points: { time: string; mean: string | null }[];
}): ReactNode {
  const { t } = useTranslation("farms");
  const values = points
    .map((p) => (p.mean === null ? null : Number(p.mean)))
    .filter((v): v is number => v != null);

  if (values.length < 2) {
    return (
      <div className="rounded-md border border-ap-line p-3 text-xs text-ap-muted">
        {t("subblockGrid.notEnoughObs", {
          defaultValue: "Not enough observations yet to draw a trend.",
        })}
      </div>
    );
  }

  const yMin = Math.min(...values);
  const yMax = Math.max(...values);
  const span = yMax === yMin ? 1 : yMax - yMin;
  const xMax = points.length - 1;
  const xScale = (i: number) => PAD.left + (i / xMax) * (W - PAD.left - PAD.right);
  const yScale = (v: number) =>
    PAD.top + (1 - (v - yMin) / span) * (H - PAD.top - PAD.bottom);

  let path = "";
  let firstIdx = -1;
  let lastIdx = -1;
  for (let i = 0; i < points.length; i++) {
    const raw = points[i].mean;
    if (raw === null) continue;
    const v = Number(raw);
    path += path === "" ? "M" : "L";
    path += `${xScale(i).toFixed(1)},${yScale(v).toFixed(1)}`;
    if (firstIdx === -1) firstIdx = i;
    lastIdx = i;
  }

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="block w-full" aria-label="Cell index history">
      <text x={4} y={12} className="fill-ap-muted" fontSize={10}>
        {yMax.toFixed(2)}
      </text>
      <text x={4} y={H - 4} className="fill-ap-muted" fontSize={10}>
        {yMin.toFixed(2)}
      </text>
      <path d={path} fill="none" stroke="#10b981" strokeWidth={2} />
      {firstIdx >= 0 && lastIdx >= 0 && (
        <>
          <circle
            cx={xScale(lastIdx)}
            cy={yScale(Number(points[lastIdx].mean))}
            r={3}
            fill="#10b981"
          />
        </>
      )}
    </svg>
  );
}

function CellSummary({
  points,
}: {
  points: { time: string; mean: string | null; min: string | null; max: string | null }[];
}): ReactNode {
  const { t } = useTranslation("farms");
  const last = [...points].reverse().find((p) => p.mean !== null);
  if (!last) return null;
  const dt = new Date(last.time);
  return (
    <dl className="mt-3 grid grid-cols-3 gap-2 text-xs">
      <Stat label={t("subblockGrid.statMean", { defaultValue: "Mean" })} value={last.mean} />
      <Stat label={t("subblockGrid.statMin", { defaultValue: "Min" })} value={last.min} />
      <Stat label={t("subblockGrid.statMax", { defaultValue: "Max" })} value={last.max} />
      <p className="col-span-3 mt-1 text-[11px] text-ap-muted">
        {t("subblockGrid.latestScene", {
          defaultValue: "Latest scene: {{date}}",
          date: dt.toLocaleString(),
        })}
      </p>
    </dl>
  );
}

function Stat({ label, value }: { label: string; value: string | null }): ReactNode {
  return (
    <div className="rounded border border-ap-line px-2 py-1">
      <dt className="text-ap-muted">{label}</dt>
      <dd className="text-sm font-medium text-ap-ink">
        {value === null ? "—" : Number(value).toFixed(3)}
      </dd>
    </div>
  );
}
