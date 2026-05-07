import type { ReactNode } from "react";

interface SparklineProps {
  points: number[];
  width?: number;
  height?: number;
  stroke?: string;
  fill?: string;
  ariaLabel?: string;
}

export function Sparkline({
  points,
  width = 120,
  height = 32,
  stroke = "currentColor",
  fill = "none",
  ariaLabel,
}: SparklineProps): ReactNode {
  if (points.length === 0) {
    return <svg width={width} height={height} aria-hidden="true" />;
  }
  const min = Math.min(...points);
  const max = Math.max(...points);
  const range = max - min || 1;
  const dx = points.length > 1 ? width / (points.length - 1) : width;
  const path = points
    .map((p, i) => {
      const x = i * dx;
      const y = height - ((p - min) / range) * height;
      return `${i === 0 ? "M" : "L"}${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(" ");
  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      role={ariaLabel ? "img" : undefined}
      aria-label={ariaLabel}
      aria-hidden={ariaLabel ? undefined : "true"}
    >
      <path d={path} stroke={stroke} fill={fill} strokeWidth={1.5} />
    </svg>
  );
}
