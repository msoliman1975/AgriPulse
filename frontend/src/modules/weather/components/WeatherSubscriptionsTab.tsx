import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { isApiError } from "@/api/errors";
import {
  createSubscription,
  listSubscriptions,
  revokeSubscription,
  type Subscription,
} from "@/api/weather";
import { useCapability } from "@/rbac/useCapability";

interface Props {
  blockId: string;
  farmId: string;
}

const PROVIDER_CODE = "open_meteo";

/**
 * Tab on `BlockDetailPage` that lets a TenantAdmin / FarmManager
 * subscribe a block to a weather provider (Open-Meteo only in MVP) and
 * revoke active subscriptions.
 *
 * Visibility:
 *   - Hidden if the user lacks `weather.read` (BlockDetailPage gate).
 *   - Read-only when the user has `weather.read` but not
 *     `weather.subscription.manage` (subscribe + revoke buttons hidden).
 */
export function WeatherSubscriptionsTab({ blockId, farmId }: Props): JSX.Element {
  const { t } = useTranslation("weather");
  const canManage = useCapability("weather.subscription.manage", { farmId });

  const [subscriptions, setSubscriptions] = useState<Subscription[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const reload = async (): Promise<void> => {
    setLoading(true);
    setError(null);
    try {
      const subs = await listSubscriptions(blockId, { include_inactive: false });
      setSubscriptions(subs);
    } catch (err) {
      setError(isApiError(err) ? (err.problem.detail ?? err.problem.title) : String(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [blockId]);

  const handleSubscribe = async (): Promise<void> => {
    setBusy(true);
    setError(null);
    try {
      await createSubscription(blockId, { provider_code: PROVIDER_CODE });
      await reload();
    } catch (err) {
      // 409 surfaces as ApiError with status 409.
      if (isApiError(err) && err.problem.status === 409) {
        setError(t("subscriptions.alreadySubscribed"));
      } else {
        setError(isApiError(err) ? (err.problem.detail ?? err.problem.title) : String(err));
      }
    } finally {
      setBusy(false);
    }
  };

  const handleRevoke = async (subscriptionId: string): Promise<void> => {
    setBusy(true);
    setError(null);
    try {
      await revokeSubscription(blockId, subscriptionId);
      await reload();
    } catch (err) {
      setError(isApiError(err) ? (err.problem.detail ?? err.problem.title) : String(err));
    } finally {
      setBusy(false);
    }
  };

  const dateFmt = useMemo(() => new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }), []);
  const alreadySubscribed = subscriptions.some((s) => s.provider_code === PROVIDER_CODE);

  return (
    <section className="card space-y-3" aria-label={t("subscriptions.heading")}>
      <header>
        <h2 className="text-lg font-semibold text-slate-800">{t("subscriptions.heading")}</h2>
      </header>

      {error ? (
        <p role="alert" className="text-sm text-red-700">
          {error}
        </p>
      ) : null}

      {loading ? (
        <p role="status">{t("panel.loading")}</p>
      ) : subscriptions.length === 0 ? (
        <p className="text-sm text-slate-600">{t("subscriptions.empty")}</p>
      ) : (
        <ul className="divide-y divide-slate-200">
          {subscriptions.map((sub) => (
            <li key={sub.id} className="flex items-center justify-between py-2">
              <div className="text-sm">
                <p className="font-medium text-slate-800">
                  {t("subscriptions.providerLabel")}:{" "}
                  {t(`providers.${sub.provider_code}`, { defaultValue: sub.provider_code })}
                </p>
                <p className="text-slate-600">
                  {t("subscriptions.createdAt", {
                    date: dateFmt.format(new Date(sub.created_at)),
                  })}
                </p>
                <p className="text-slate-600">
                  {sub.last_successful_ingest_at
                    ? t("subscriptions.lastIngest", {
                        date: dateFmt.format(new Date(sub.last_successful_ingest_at)),
                      })
                    : t("subscriptions.neverIngested")}
                </p>
              </div>
              {canManage ? (
                <button
                  type="button"
                  className="btn btn-ghost"
                  onClick={() => void handleRevoke(sub.id)}
                  disabled={busy}
                >
                  {busy ? t("subscriptions.revoking") : t("subscriptions.revokeButton")}
                </button>
              ) : null}
            </li>
          ))}
        </ul>
      )}

      {canManage ? (
        <div className="flex justify-end">
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => void handleSubscribe()}
            disabled={busy || alreadySubscribed}
          >
            {busy ? t("subscriptions.subscribing") : t("subscriptions.subscribeButton")}
          </button>
        </div>
      ) : null}
    </section>
  );
}
