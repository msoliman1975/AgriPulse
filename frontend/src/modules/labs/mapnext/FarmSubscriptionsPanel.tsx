// Farm-level imagery + weather subscriptions.
//
// Replaces the save-template-then-apply-to-blocks flow for these two
// categories. That flow reconciled blocks against the template *stored on the
// server*, so an unsaved edit made Apply a silent no-op, and an empty template
// made it report every block as already matching — which reads exactly like a
// broken button, and has been mistaken for one.
//
// There is nothing to reconcile now. The farm is the unit both are fetched
// for: imagery takes one AOI and weather takes one centroid. A change here is
// the subscription, so it takes effect on the next poll with no second step.
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { isApiError } from "@/api/errors";
import {
  listFarmImagerySubscriptions,
  listFarmWeatherSubscriptions,
  subscribeFarmImagery,
  subscribeFarmWeather,
  updateFarmImagerySubscription,
  updateFarmWeatherSubscription,
  type FarmImagerySubscription,
  type FarmWeatherSubscription,
} from "@/api/farmSubscriptions";
import { getConfig, type ImageryConfigEntry } from "@/api/config";
import { listWeatherProviders, type WeatherProvider } from "@/api/weather";

const rowCls = "flex flex-wrap items-center gap-2 rounded-lg border border-ap-line/70 p-2 text-sm";
const inputCls =
  "rounded-lg border border-ap-line bg-ap-panel px-2.5 py-1.5 text-sm text-ap-ink focus:border-ap-primary focus:outline-none";

interface Props {
  farmId: string;
}

/** A number input that reports null for "leave it to the default". */
function NumberField({
  value,
  onCommit,
  label,
  min = 1,
  max,
  width = "w-20",
}: {
  value: number | null;
  onCommit: (next: number | null) => void;
  label: string;
  min?: number;
  max?: number;
  width?: string;
}): ReactNode {
  const [draft, setDraft] = useState(value === null ? "" : String(value));
  useEffect(() => {
    setDraft(value === null ? "" : String(value));
  }, [value]);
  return (
    <label className="flex items-center gap-1 text-xs text-ap-muted">
      {label}
      <input
        type="number"
        min={min}
        max={max}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => {
          const trimmed = draft.trim();
          const next = trimmed === "" ? null : Number(trimmed);
          // A blank box means "use the tenant default", which is a real
          // choice — not the same as zero, and not a reason to reject.
          const outOfRange =
            next !== null &&
            (!Number.isFinite(next) || next < min || (max !== undefined && next > max));
          if (outOfRange) {
            setDraft(value === null ? "" : String(value));
            return;
          }
          if (next !== value) onCommit(next);
        }}
        className={inputCls + " " + width}
      />
    </label>
  );
}

/** Which AOI this farm is fetched on — reported, never set here.
 *
 * This was a "Whole farm" checkbox. It read as a preference and behaved like a
 * migration switch with teeth: `fetch_farm_aoi` is also what excludes a farm's
 * blocks from the block sweep, so ticking it on a farm the provider cannot
 * return in one request left that farm with no imagery from either path. The
 * cutover is driven platform-side; what an operator needs here is which path
 * this farm is on, and — when it is stuck on blocks — why.
 */
function FetchScope({ sub }: { sub: FarmImagerySubscription }): ReactNode {
  const { t } = useTranslation("farmConsole");
  if (sub.fetch_farm_aoi) {
    return <span className="text-xs text-ap-muted">{t("farmSubs.scope.wholeFarm")}</span>;
  }
  // `=== false`, not `!`: each chart is its own ArgoCD app, so the frontend can
  // reach prod before the api that answers this field. Absent must mean "not
  // measured", or a frontend-first promote reports every farm on the platform
  // as too large, with undefined for the numbers.
  if (sub.farm_aoi_fetchable === false) {
    return (
      <span className="text-xs text-ap-warn">
        {t("farmSubs.scope.tooLarge", {
          width: sub.farm_aoi_width_px,
          height: sub.farm_aoi_height_px,
          max: sub.farm_aoi_max_px,
        })}
      </span>
    );
  }
  return <span className="text-xs text-ap-muted">{t("farmSubs.scope.perBlock")}</span>;
}

export function FarmSubscriptionsPanel({ farmId }: Props): ReactNode {
  const { t } = useTranslation("farmConsole");
  const [products, setProducts] = useState<ImageryConfigEntry[]>([]);
  const [providers, setProviders] = useState<WeatherProvider[]>([]);
  const [imagery, setImagery] = useState<FarmImagerySubscription[]>([]);
  const [weather, setWeather] = useState<FarmWeatherSubscription[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [cfg, provs, img, wx] = await Promise.all([
        getConfig(),
        listWeatherProviders(),
        listFarmImagerySubscriptions(farmId),
        listFarmWeatherSubscriptions(farmId),
      ]);
      setProducts(cfg.products);
      setProviders(provs);
      setImagery(img);
      setWeather(wx);
    } catch (err: unknown) {
      setError(isApiError(err) ? (err.problem.detail ?? err.message) : t("farmSubs.loadFailed"));
    } finally {
      setLoading(false);
    }
  }, [farmId, t]);

  useEffect(() => {
    void load();
  }, [load]);

  /** Fold one mutation's answer back into state.
   *
   * Deliberately does NOT re-run `load()`. Refetching all four endpoints
   * flipped `loading` back on, so the whole panel unmounted and rebuilt on
   * every click — a checkbox toggle read as a page reload. The mutation
   * already returns the updated row, so patching it in is both correct and
   * invisible.
   */
  function upsert<T extends { id: string }>(rows: T[], updated: T): T[] {
    const i = rows.findIndex((r) => r.id === updated.id);
    return i === -1 ? [...rows, updated] : rows.map((r) => (r.id === updated.id ? updated : r));
  }

  async function runImagery(
    key: string,
    fn: () => Promise<FarmImagerySubscription>,
  ): Promise<void> {
    setBusy(key);
    setError(null);
    try {
      const updated = await fn();
      setImagery((rows) => upsert(rows, updated));
    } catch (err: unknown) {
      setError(isApiError(err) ? (err.problem.detail ?? err.message) : t("farmSubs.saveFailed"));
    } finally {
      setBusy(null);
    }
  }

  async function runWeather(
    key: string,
    fn: () => Promise<FarmWeatherSubscription>,
  ): Promise<void> {
    setBusy(key);
    setError(null);
    try {
      const updated = await fn();
      setWeather((rows) => upsert(rows, updated));
    } catch (err: unknown) {
      setError(isApiError(err) ? (err.problem.detail ?? err.message) : t("farmSubs.saveFailed"));
    } finally {
      setBusy(null);
    }
  }

  if (loading) return <p className="text-xs text-ap-muted">{t("farmSubs.loading")}</p>;

  const imageryByProduct = new Map(imagery.map((s) => [s.product_id, s]));
  const weatherByProvider = new Map(weather.map((s) => [s.provider_code, s]));

  return (
    <div className="space-y-4">
      {error ? <p className="text-xs text-ap-crit">{error}</p> : null}

      <section className="rounded-xl border border-ap-line bg-ap-bg/40 p-4">
        <h3 className="mb-1 text-sm font-bold text-ap-ink">{t("farmSubs.imageryTitle")}</h3>
        <p className="mb-3 text-xs text-ap-muted">{t("farmSubs.imageryHint")}</p>
        <ul className="space-y-2">
          {products.map((p) => {
            const sub = imageryByProduct.get(p.product_id);
            const on = Boolean(sub?.is_active);
            return (
              <li key={p.product_id} className={rowCls}>
                <label className="flex flex-1 items-center gap-2 font-semibold text-ap-ink">
                  <input
                    type="checkbox"
                    checked={on}
                    disabled={busy !== null}
                    onChange={() =>
                      void runImagery(p.product_id, () =>
                        sub
                          ? updateFarmImagerySubscription(farmId, sub.id, { is_active: !on })
                          : subscribeFarmImagery(farmId, { product_id: p.product_id }),
                      )
                    }
                  />
                  {p.product_name}
                </label>
                {on && sub ? (
                  <>
                    <NumberField
                      label={t("farmSubs.cadence")}
                      value={sub.cadence_hours}
                      onCommit={(next) =>
                        void runImagery(sub.id, () =>
                          updateFarmImagerySubscription(farmId, sub.id, { cadence_hours: next }),
                        )
                      }
                    />
                    <NumberField
                      label={t("farmSubs.cloudCap")}
                      value={sub.cloud_cover_max_pct}
                      min={0}
                      max={100}
                      width="w-16"
                      onCommit={(next) =>
                        void runImagery(sub.id, () =>
                          updateFarmImagerySubscription(farmId, sub.id, {
                            cloud_cover_max_pct: next,
                          }),
                        )
                      }
                    />
                    <FetchScope sub={sub} />
                  </>
                ) : null}
              </li>
            );
          })}
        </ul>
        <p className="mt-2 text-xs text-ap-muted">{t("farmSubs.fetchScopeHint")}</p>
      </section>

      <section className="rounded-xl border border-ap-line bg-ap-bg/40 p-4">
        <h3 className="mb-1 text-sm font-bold text-ap-ink">{t("farmSubs.weatherTitle")}</h3>
        <p className="mb-3 text-xs text-ap-muted">{t("farmSubs.weatherHint")}</p>
        <ul className="space-y-2">
          {providers.map((prov) => {
            const sub = weatherByProvider.get(prov.code);
            const on = Boolean(sub?.is_active);
            return (
              <li key={prov.code} className={rowCls}>
                <label className="flex flex-1 items-center gap-2 font-semibold text-ap-ink">
                  <input
                    type="checkbox"
                    checked={on}
                    disabled={busy !== null}
                    onChange={() =>
                      void runWeather(prov.code, () =>
                        sub
                          ? updateFarmWeatherSubscription(farmId, sub.id, { is_active: !on })
                          : subscribeFarmWeather(farmId, { provider_code: prov.code }),
                      )
                    }
                  />
                  {prov.name}
                </label>
                {on && sub ? (
                  <NumberField
                    label={t("farmSubs.cadence")}
                    value={sub.cadence_hours}
                    onCommit={(next) =>
                      void runWeather(sub.id, () =>
                        updateFarmWeatherSubscription(farmId, sub.id, { cadence_hours: next }),
                      )
                    }
                  />
                ) : null}
              </li>
            );
          })}
        </ul>
      </section>
    </div>
  );
}
