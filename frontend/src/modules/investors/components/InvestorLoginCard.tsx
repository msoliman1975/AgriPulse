import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import {
  createInvestorLogin,
  resendInvestorLogin,
  setInvestorLoginEnabled,
  type Investor,
  type InvestorLoginResult,
} from "@/api/investors";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { Pill } from "@/components/Pill";
import { useCapability } from "@/rbac/useCapability";
import { INVESTOR_STATUS_PILL, errorText } from "../lib";

/**
 * The investor's app login: create it, resend the set-password email, or
 * disable and enable sign-in. The login is a user with the Investor role,
 * created only here, so it never appears on Settings > Team.
 */
export function InvestorLoginCard({ investor }: { investor: Investor }): JSX.Element {
  const { t, i18n } = useTranslation("investors");
  const queryClient = useQueryClient();
  const canInvite = useCapability("investor.invite");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const done = async (result?: InvestorLoginResult): Promise<void> => {
    setError(null);
    if (result) {
      setMessage(
        result.email_sent || !result.temporary_password
          ? t("login.sent", { email: investor.email })
          : t("login.emailFailed", { password: result.temporary_password }),
      );
    } else {
      setMessage(null);
    }
    await queryClient.invalidateQueries({ queryKey: ["investors"] });
  };
  const fail = (err: unknown): void => {
    setMessage(null);
    setError(errorText(err));
  };

  const create = useMutation({
    mutationFn: () => createInvestorLogin(investor.id),
    onSuccess: done,
    onError: fail,
  });
  const resend = useMutation({
    mutationFn: () => resendInvestorLogin(investor.id),
    onSuccess: done,
    onError: fail,
  });
  const toggle = useMutation({
    mutationFn: (enabled: boolean) => setInvestorLoginEnabled(investor.id, enabled),
    onSuccess: () => done(),
    onError: fail,
  });

  const busy = create.isPending || resend.isPending || toggle.isPending;
  const archived = investor.archived_at !== null;
  const linked = investor.user_id !== null;
  const suspended = investor.status === "suspended";
  const date = (iso: string | null): string =>
    iso ? new Date(iso).toLocaleDateString(i18n.language === "ar" ? "ar-u-nu-latn" : "en") : "—";

  return (
    <Card title={t("login.title")}>
      {!linked ? (
        <div className="flex flex-col gap-2">
          <p className="text-sm text-ap-muted">{t("login.none")}</p>
          {canInvite && !archived ? (
            <div className="flex flex-wrap items-center gap-3">
              <Button disabled={busy} onClick={() => create.mutate()}>
                {t("login.create")}
              </Button>
              <span className="text-xs text-ap-muted">
                {t("login.createHelp", { email: investor.email })}
              </span>
            </div>
          ) : null}
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <span className="text-ap-ink">{investor.email}</span>
            <Pill kind={INVESTOR_STATUS_PILL[investor.status]}>
              {t(`status.${investor.status}`)}
            </Pill>
            <span className="text-ap-muted">
              {t("login.invited", { date: date(investor.invited_at) })}
            </span>
            <span className="text-ap-muted">
              {investor.last_app_seen_at
                ? t("login.lastSeen", { date: date(investor.last_app_seen_at) })
                : t("login.neverSeen")}
            </span>
          </div>
          {suspended ? <p className="text-sm text-ap-warn">{t("login.disabled")}</p> : null}
          {canInvite && !archived ? (
            <div className="flex flex-wrap gap-2">
              {!suspended && !investor.last_app_seen_at ? (
                <Button variant="ghost" size="sm" disabled={busy} onClick={() => resend.mutate()}>
                  {t("login.resend")}
                </Button>
              ) : null}
              <Button
                variant="ghost"
                size="sm"
                disabled={busy}
                onClick={() => toggle.mutate(suspended)}
              >
                {suspended ? t("login.enable") : t("login.disable")}
              </Button>
            </div>
          ) : null}
        </div>
      )}
      {message ? <p className="mt-2 text-sm text-ap-primary">{message}</p> : null}
      {error ? (
        <p role="alert" className="mt-2 text-sm text-ap-crit">
          {error}
        </p>
      ) : null}
    </Card>
  );
}
