/**
 * The platform switch between the old decision-tree engine and the beta one.
 *
 * One engine runs at a time, for every tenant. Flipping closes what the
 * outgoing trees left open — recommendations expire, tree alerts resolve and
 * current verdicts end — in the same transaction as the flip. The confirm
 * dialog says all of that before the click, because none of it is undone by
 * flipping back: flipping back closes the other side's output the same way.
 *
 * Platform scope only. The route refuses a tenant caller, so the card is not
 * rendered for one.
 */

import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/Button";
import { Modal } from "@/components/Modal";
import { Pill } from "@/components/Pill";
import { StatusBanner } from "@/components/StatusBanner";
import { resolveErrorMessage } from "@/components/asyncState";
import type { DecisionEngine, DecisionEngineState } from "@/api/decisionTreesBeta";
import { useDecisionEngine, useSwitchDecisionEngine } from "@/queries/decisionTreesBeta";

interface Props {
  /** Published beta trees. Shown in the dialog so nobody flips onto nothing. */
  publishedBetaTrees: number;
}

function totals(state: DecisionEngineState): Record<string, number> {
  const out = {
    recommendations_expired: 0,
    alerts_resolved: 0,
    verdicts_closed: 0,
  };
  for (const counts of Object.values(state.last_close_out?.tenants ?? {})) {
    out.recommendations_expired += counts.recommendations_expired;
    out.alerts_resolved += counts.alerts_resolved;
    out.verdicts_closed += counts.verdicts_closed;
  }
  return out;
}

export function DecisionEngineSwitch({ publishedBetaTrees }: Props): ReactNode {
  const { t, i18n } = useTranslation("decisionTreesBeta");
  const query = useDecisionEngine(true);
  const flip = useSwitchDecisionEngine();
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (query.status === "pending") {
    return <p className="text-sm text-ap-muted">{t("engine.loading")}</p>;
  }
  if (query.status === "error") {
    return (
      <StatusBanner kind="crit">
        {resolveErrorMessage(query.error, t("engine.loadFailed"))}
      </StatusBanner>
    );
  }

  const state = query.data;
  const target: DecisionEngine = state.engine === "old" ? "beta" : "old";
  const sum = state.last_close_out ? totals(state) : null;
  const switchedAt = state.switched_at
    ? new Date(state.switched_at).toLocaleString(i18n.language)
    : null;

  const onConfirm = (): void => {
    setError(null);
    flip.mutate(target, {
      onSuccess: () => setConfirming(false),
      onError: (err) => setError(resolveErrorMessage(err, t("engine.failed"))),
    });
  };

  return (
    <section
      aria-labelledby="decision-engine-title"
      className="flex flex-col gap-2 rounded-xl border border-ap-line p-3"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <h2 id="decision-engine-title" className="text-sm font-semibold text-ap-ink">
            {t("engine.title")}
          </h2>
          <Pill kind={state.engine === "beta" ? "info" : "neutral"}>
            {t(`engine.name.${state.engine}`)}
          </Pill>
        </div>
        <Button
          variant={target === "beta" ? "primary" : "secondary"}
          onClick={() => setConfirming(true)}
        >
          {t(`engine.switchTo.${target}`)}
        </Button>
      </div>
      <p className="text-sm text-ap-muted">{t(`engine.explain.${state.engine}`)}</p>
      {switchedAt && sum ? (
        <p className="text-xs text-ap-muted">
          {t("engine.lastFlip", {
            at: switchedAt,
            recommendations: sum.recommendations_expired,
            alerts: sum.alerts_resolved,
            verdicts: sum.verdicts_closed,
          })}
        </p>
      ) : null}

      {confirming ? (
        <Modal
          open
          onClose={() => setConfirming(false)}
          labelledBy="decision-engine-confirm-title"
          className="max-w-lg"
        >
          <div className="flex flex-col gap-3 p-4">
            <h2
              id="decision-engine-confirm-title"
              className="text-card-title font-semibold text-ap-ink"
            >
              {t(`engine.confirm.title.${target}`)}
            </h2>
            <ul className="list-disc ps-5 text-sm text-ap-ink">
              <li>{t(`engine.confirm.stops.${target}`)}</li>
              <li>{t("engine.confirm.closes")}</li>
              <li>{t("engine.confirm.history")}</li>
              {target === "beta" ? (
                <li>{t("engine.confirm.publishedCount", { n: publishedBetaTrees })}</li>
              ) : null}
            </ul>
            {target === "beta" && publishedBetaTrees === 0 ? (
              <StatusBanner kind="warn">{t("engine.confirm.noBetaTrees")}</StatusBanner>
            ) : null}
            {error ? <StatusBanner kind="crit">{error}</StatusBanner> : null}
            <div className="flex justify-end gap-2">
              <Button variant="secondary" onClick={() => setConfirming(false)}>
                {t("designer.cancel")}
              </Button>
              <Button variant="danger" onClick={onConfirm} disabled={flip.isPending}>
                {flip.isPending ? t("engine.switching") : t(`engine.switchTo.${target}`)}
              </Button>
            </div>
          </div>
        </Modal>
      ) : null}
    </section>
  );
}
