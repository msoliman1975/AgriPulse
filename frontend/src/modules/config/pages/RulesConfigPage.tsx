import type { ReactNode } from "react";

export function RulesConfigPage(): ReactNode {
  return (
    <div className="mx-auto max-w-3xl py-12 text-center">
      <h1 className="text-xl font-semibold text-ap-ink">Rules &amp; thresholds</h1>
      <p className="mt-2 text-sm text-ap-muted">
        Per-rule overrides, severity tweaks, and kill-switches will live here.
      </p>
    </div>
  );
}
