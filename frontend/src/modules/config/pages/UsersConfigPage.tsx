import type { ReactNode } from "react";

export function UsersConfigPage(): ReactNode {
  return (
    <div className="mx-auto max-w-3xl py-12 text-center">
      <h1 className="text-xl font-semibold text-ap-ink">Users &amp; roles</h1>
      <p className="mt-2 text-sm text-ap-muted">
        Farm members and role assignments — see Land units → Members for the
        per-farm flow.
      </p>
    </div>
  );
}
