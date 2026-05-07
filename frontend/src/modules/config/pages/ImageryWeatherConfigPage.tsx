import type { ReactNode } from "react";

export function ImageryWeatherConfigPage(): ReactNode {
  return (
    <div className="mx-auto max-w-3xl py-12 text-center">
      <h1 className="text-xl font-semibold text-ap-ink">Imagery &amp; weather</h1>
      <p className="mt-2 text-sm text-ap-muted">
        Provider configuration, cadence, and cloud-cover thresholds — wiring
        through from the per-block panels.
      </p>
    </div>
  );
}
