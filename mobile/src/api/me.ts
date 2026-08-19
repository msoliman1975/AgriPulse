/**
 * The signed-in person's own record: which farms they may work, and the
 * language chosen for them.
 *
 * Both answers come from one call. `GET /api/v1/me` returns the whole profile,
 * and asking twice on every cold start would be two round trips on a field
 * connection to learn things the same response already carried.
 *
 * **The farm** used to be `VITE_FARM_ID`, baked in at build time. That made one
 * APK per farm, and it failed in the worst direction: a scout on any other farm
 * signed in perfectly well and then got "couldn't load visits". In production
 * the compiled farm belonged to a different *tenant* than the scout using the
 * app, so the request could never have succeeded. `farm_scopes` is exactly the
 * set of farms this person is allowed to work — both the correct source and the
 * one that cannot disagree with what the API will authorize.
 *
 * **The language** is what makes setting it per person at enrolment mean
 * anything on the handset. A choice made on the device still wins; that rule
 * lives in `i18n/preference`, not here.
 */

import { authedGet } from "@/api/client";
import { isLang, type Lang } from "@/i18n";

export interface FarmScope {
  farm_id: string;
  role: string;
  granted_at: string;
}

interface MeResponse {
  id?: string;
  full_name?: string;
  preferences?: { language?: string };
  farm_scopes?: FarmScope[];
}

export interface Me {
  /** Needed because the observations endpoint has no `recorded_by` filter:
   *  the Records screen keeps its own rows out of the farm's recent ones. */
  userId: string | null;
  name: string | null;
  farms: FarmScope[];
  /**
   * Null covers three cases the caller treats identically: the request failed,
   * the field is missing, or the stored code is a language this build has no
   * catalogue for — that last one is why `isLang` is checked rather than
   * trusted. The API's supported list (`app/shared/i18n.py`) and this app's
   * locale registry are separate lists, and a value can legitimately exist in
   * one before the other catches up.
   */
  language: Lang | null;
}

/**
 * Never throws. The caller has to render *something*, and an empty farm list
 * is a real state — enrolled, signed in, and not yet put on a farm — which
 * deserves its own screen rather than a generic failure.
 */
export async function fetchMe(): Promise<Me> {
  try {
    const me = await authedGet<MeResponse>("/me");
    const lang = me.preferences?.language;
    return {
      userId: me.id ?? null,
      name: me.full_name ?? null,
      farms: me.farm_scopes ?? [],
      language: isLang(lang) ? lang : null,
    };
  } catch {
    return { userId: null, name: null, farms: [], language: null };
  }
}
