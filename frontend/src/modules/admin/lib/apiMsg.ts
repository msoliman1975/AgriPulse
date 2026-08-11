// The message an author should actually read when a save is refused.
//
// The catalog endpoints answer a bad payload with an RFC 7807 problem whose
// `detail` names the offending field ("stage codes must be unique"). Falling
// back to `title` alone loses that, and `String(err)` loses everything — so
// the detail wins where there is one.

import { isApiError } from "@/api/errors";

export function apiMsg(err: unknown): string {
  return isApiError(err) ? (err.problem.detail ?? err.problem.title) : String(err);
}
