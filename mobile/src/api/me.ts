/**
 * Who is signed in, and which farms they may work.
 *
 * The farm used to be `VITE_FARM_ID`, baked in at build time. That made one
 * APK per farm, and worse, it failed silently in the wrong direction: a scout
 * on a different farm signed in perfectly well and then got "couldn't load
 * visits", because the app was asking for visits on somebody else's farm. If
 * that farm belonged to another tenant the request could not have succeeded
 * under any circumstances.
 *
 * The token already carries the answer. `farm_scopes` is exactly the set of
 * farms this person is allowed to work, so it is both the correct source and
 * the one that cannot disagree with what the API will authorize.
 */

import { authedGet } from "@/api/client";

export interface FarmScope {
  farm_id: string;
  role: string;
  granted_at: string;
}

interface MeResponse {
  preferences?: { language?: string };
  farm_scopes?: FarmScope[];
}

/**
 * The farms this scout may work, in grant order.
 *
 * Returns an empty list rather than throwing: the caller has to render
 * *something*, and "you are not assigned to a farm yet" is a far more useful
 * screen than a generic failure — it is also a real state, produced by
 * enrolling somebody and forgetting the scope.
 */
export async function fetchMyFarms(): Promise<FarmScope[]> {
  try {
    const me = await authedGet<MeResponse>("/me");
    return me.farm_scopes ?? [];
  } catch {
    return [];
  }
}
