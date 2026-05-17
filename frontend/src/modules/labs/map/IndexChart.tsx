import type { IndexCode, IndexSeries } from "./types";

const W = 280;
const H = 110;
const PAD = { top: 14, right: 18, bottom: 18, left: 24 };

const META: Record<IndexCode, { label: string; baseline: number; description: string }> = {
  ndvi: { label: "Vegetation Index", baseline: 0.7, description: "vegetation vigor" },
  ndre: { label: "Red-Edge Index", baseline: 0.4, description: "canopy nitrogen" },
  ndwi: { label: "Water Index", baseline: 0.25, description: "water status" },
};

interface Props {
  code: IndexCode;
  series: IndexSeries;
}

export function IndexChart({ code, series }: Props) {
  const meta = META[code];
  const points = series.series_30d.map((p) => p.value).map((v) => (v == null ? null : v));

  const validValues = points.filter((v): v is number => v != null);
  if (validValues.length < 2) {
    return (
      <div className="mt-2 rounded-md border border-slate-200 p-3 text-xs text-slate-500">
        Not enough data to draw the chart.
      </div>
    );
  }

  const yMin = Math.min(0, ...validValues);
  const yMax = Math.max(1, ...validValues);
  const xMax = points.length - 1;

  const xScale = (i: number) => PAD.left + (i / xMax) * (W - PAD.left - PAD.right);
  const yScale = (v: number) =>
    PAD.top + (1 - (v - yMin) / (yMax - yMin)) * (H - PAD.top - PAD.bottom);

  let pathD = "";
  for (let i = 0; i < points.length; i++) {
    const v = points[i];
    if (v == null) continue;
    pathD += pathD === "" ? "M" : "L";
    pathD += `${xScale(i).toFixed(1)},${yScale(v).toFixed(1)}`;
  }

  // Area fill below curve, dropping back down to yMin.
  let areaD = pathD;
  if (areaD) {
    const lastIdx = points.findLastIndex((v) => v != null);
    const firstIdx = points.findIndex((v) => v != null);
    if (lastIdx >= 0 && firstIdx >= 0) {
      areaD += ` L ${xScale(lastIdx).toFixed(1)},${yScale(yMin).toFixed(1)}`;
      areaD += ` L ${xScale(firstIdx).toFixed(1)},${yScale(yMin).toFixed(1)} Z`;
    }
  }

  const current = series.current ?? validValues[validValues.length - 1];
  const trend = series.trend_7d_delta ?? 0;
  const baseline = meta.baseline;
  const lineColor = trend >= 0 ? "#3B6D11" : current < baseline ? "#A32D2D" : "#854F0B";

  const lastIdx = points.findLastIndex((v) => v != null);
  const cx = xScale(lastIdx);
  const cy = yScale(points[lastIdx]!);

  return (
    <div className="mt-2 rounded-md border border-slate-200 bg-white p-2">
      <div className="flex items-baseline justify-between text-[11px]">
        <div>
          <strong className="uppercase">{code}</strong> · {meta.label}
        </div>
        <span className="text-slate-500">30 days</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="mt-1 w-full" role="img">
        {/* Y axis labels */}
        <text x={4} y={PAD.top + 3} fontSize="8.5" fill="#999">
          {yMax.toFixed(1)}
        </text>
        <text x={4} y={H - PAD.bottom + 8} fontSize="8.5" fill="#999">
          {yMin.toFixed(1)}
        </text>
        {/* Healthy threshold */}
        <line
          x1={PAD.left}
          x2={W - PAD.right}
          y1={yScale(baseline)}
          y2={yScale(baseline)}
          stroke="#3B6D11"
          strokeDasharray="3,3"
          strokeOpacity={0.6}
          strokeWidth={1}
        />
        <text
          x={W - PAD.right - 2}
          y={yScale(baseline) - 3}
          fontSize="9"
          fill="#3B6D11"
          textAnchor="end"
        >
          healthy ≥ {baseline}
        </text>
        {/* Area + line */}
        {areaD ? <path d={areaD} fill={lineColor} fillOpacity={0.13} stroke="none" /> : null}
        <path d={pathD} fill="none" stroke={lineColor} strokeWidth={1.6} />
        {/* Current point */}
        <circle cx={cx} cy={cy} r={3.5} fill={lineColor} stroke="#ffffff" strokeWidth={1.5} />
        <text
          x={cx - 6}
          y={cy - 8}
          fontSize="10"
          fontWeight="500"
          fill={lineColor}
          textAnchor="end"
        >
          {current.toFixed(2)}
        </text>
        {/* X axis labels */}
        <text x={PAD.left} y={H - 4} fontSize="9" fill="#666">
          30d ago
        </text>
        <text x={W / 2} y={H - 4} fontSize="9" fill="#888" textAnchor="middle">
          {meta.description}
        </text>
        <text x={W - PAD.right} y={H - 4} fontSize="9" fill="#666" textAnchor="end">
          today
        </text>
      </svg>
    </div>
  );
}
