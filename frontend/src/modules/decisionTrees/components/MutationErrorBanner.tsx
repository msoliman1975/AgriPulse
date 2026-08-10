// The red bar above the tree workspace when a save / publish / metadata
// update comes back an error.
//
// It shows the server's own words. The API answers with an RFC 7807 problem
// whose `detail` names the actual fault — "crop attribute(s) seed_generation
// are not defined for crop path(s) mango", a params ref that isn't declared,
// a dangling node pointer — and `ApiError` carries that through as `message`.
//
// Each of the three call sites used to render a fixed string instead, one of
// which told the author to look in the YAML editor for detail the YAML editor
// never had. An error you cannot act on is barely better than a silent one,
// and the create page had been doing this correctly all along — the drift was
// only here.

import { type ReactNode } from "react";

interface MutationErrorBannerProps {
  /** The mutation's error, when it has one. */
  error: Error | null | undefined;
  /** Shown when the error carries no message of its own. */
  fallback: string;
}

export function MutationErrorBanner({ error, fallback }: MutationErrorBannerProps): ReactNode {
  // An Error with an empty message would otherwise render an empty red bar.
  const text = error?.message?.trim() ? error.message : fallback;
  return (
    <p
      role="alert"
      className="rounded-md border border-ap-crit/40 bg-ap-crit/10 p-2 text-xs text-ap-crit"
    >
      {text}
    </p>
  );
}
