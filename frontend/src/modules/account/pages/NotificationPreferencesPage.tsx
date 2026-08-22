import { useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import {
  NOTIFICATION_CHANNELS,
  type ChannelAvailability,
  type MyNotificationPreferences,
  type NotificationChannel,
} from "@/api/notificationPreferences";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { ErrorState } from "@/components/ErrorState";
import { Page } from "@/components/Page";
import { PageHeader } from "@/components/PageHeader";
import { Skeleton } from "@/components/Skeleton";
import { StatusBanner } from "@/components/StatusBanner";
import {
  useMyNotificationPreferences,
  useUpdateMyNotificationPreferences,
} from "@/queries/notificationPreferences";

/**
 * /account/notifications — the caller's own notification settings.
 *
 * Not under /settings. That hub is tenant-wide configuration and every tab in
 * it is capability-gated, so a Scout or an Agronomist following the link in a
 * notification email would be refused at the door. This page has no gate: the
 * row belongs to the person reading it.
 *
 * Two things live here, and they are the only two the notification fan-out
 * reads off `user_preferences`: which channels, and which language the alert
 * and recommendation templates render in.
 *
 * Draft-then-save rather than save-on-toggle. Turning email off and push on is
 * one decision, and firing two writes mid-thought means a moment where the
 * person receives nothing at all.
 */
export function NotificationPreferencesPage(): ReactNode {
  const { t } = useTranslation("account");
  const query = useMyNotificationPreferences();
  const update = useUpdateMyNotificationPreferences();

  return (
    <Page width="standard">
      <div className="flex flex-col gap-6">
        <PageHeader title={t("notifications.title")} subtitle={t("notifications.subtitle")} />
        {query.isLoading ? (
          <Skeleton className="h-72 w-full" />
        ) : query.isError ? (
          <ErrorState
            message={t("notifications.loadFailed")}
            action={
              <Button variant="secondary" size="sm" onClick={() => void query.refetch()}>
                {t("notifications.retry")}
              </Button>
            }
          />
        ) : query.data ? (
          <PreferencesForm
            prefs={query.data}
            onSave={(patch) => update.mutate(patch)}
            isSaving={update.isPending}
            saveFailed={update.isError}
            savedAt={update.isSuccess ? update.submittedAt : null}
          />
        ) : null}
      </div>
    </Page>
  );
}

interface FormProps {
  prefs: MyNotificationPreferences;
  onSave: (patch: { channels: NotificationChannel[]; language: "en" | "ar" }) => void;
  isSaving: boolean;
  saveFailed: boolean;
  savedAt: number | null;
}

function PreferencesForm({ prefs, onSave, isSaving, saveFailed, savedAt }: FormProps): ReactNode {
  const { t } = useTranslation("account");
  const [channels, setChannels] = useState<NotificationChannel[]>(prefs.channels);
  const [language, setLanguage] = useState<"en" | "ar">(prefs.language);

  // The mutation writes the server's own answer back into the cache, so the
  // draft has to follow it. Without this, saving leaves the form showing what
  // was typed rather than what was stored — which differ if the server
  // normalised anything.
  useEffect(() => {
    setChannels(prefs.channels);
    setLanguage(prefs.language);
  }, [prefs]);

  const byChannel = new Map<string, ChannelAvailability>(
    prefs.availability.map((a) => [a.channel, a]),
  );
  const dirty =
    language !== prefs.language ||
    channels.length !== prefs.channels.length ||
    channels.some((c) => !prefs.channels.includes(c));

  const toggle = (channel: NotificationChannel): void => {
    setChannels((prev) =>
      prev.includes(channel) ? prev.filter((c) => c !== channel) : [...prev, channel],
    );
  };

  return (
    <>
      <Card
        as="form"
        title={t("notifications.channels.heading")}
        onSubmit={(event) => {
          event.preventDefault();
          onSave({ channels, language });
        }}
        footer={
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p aria-live="polite" className="text-sm text-ap-muted">
              {saveFailed
                ? t("notifications.saveFailed")
                : isSaving
                  ? t("notifications.saving")
                  : savedAt !== null && !dirty
                    ? t("notifications.saved")
                    : ""}
            </p>
            <Button type="submit" disabled={!dirty || isSaving}>
              {t("notifications.save")}
            </Button>
          </div>
        }
      >
        <p className="text-sm text-ap-muted">{t("notifications.channels.hint")}</p>

        <fieldset className="mt-4 flex flex-col gap-3 border-0 p-0">
          <legend className="sr-only">{t("notifications.channels.heading")}</legend>
          {NOTIFICATION_CHANNELS.map((channel) => (
            <ChannelRow
              key={channel}
              channel={channel}
              checked={channels.includes(channel)}
              availability={byChannel.get(channel)}
              emailAddress={prefs.email_address}
              deviceCount={prefs.registered_device_count}
              onToggle={() => toggle(channel)}
            />
          ))}
        </fieldset>

        {channels.length === 0 ? (
          <div className="mt-4">
            <StatusBanner kind="warn" detail={t("notifications.allOffDetail")}>
              {t("notifications.allOff")}
            </StatusBanner>
          </div>
        ) : null}

        <hr className="my-5 border-ap-line" />

        <div>
          <label htmlFor="notification-language" className="block text-sm font-medium text-ap-ink">
            {t("notifications.language.label")}
          </label>
          <p className="mt-1 text-sm text-ap-muted">{t("notifications.language.hint")}</p>
          <select
            id="notification-language"
            value={language}
            onChange={(event) => setLanguage(event.target.value as "en" | "ar")}
            className="mt-2 rounded-md border border-ap-line bg-white px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-ap-primary"
          >
            <option value="en">{t("notifications.language.en")}</option>
            <option value="ar">{t("notifications.language.ar")}</option>
          </select>
        </div>
      </Card>

      <p className="text-sm text-ap-muted">{t("notifications.scopeNote")}</p>
    </>
  );
}

interface RowProps {
  channel: NotificationChannel;
  checked: boolean;
  availability: ChannelAvailability | undefined;
  emailAddress: string | null;
  deviceCount: number;
  onToggle: () => void;
}

/**
 * One channel. The tick box stays usable even when the channel cannot
 * currently deliver — a person whose organisation has email switched off
 * should still be able to record that they want it, so it starts working the
 * day it is switched back on. What changes is that the row says why nothing
 * is arriving, which is the question the screen exists to answer.
 */
function ChannelRow({
  channel,
  checked,
  availability,
  emailAddress,
  deviceCount,
  onToggle,
}: RowProps): ReactNode {
  const { t } = useTranslation("account");
  const blocked = availability !== undefined && !availability.deliverable;
  const reasonKey = availability?.reason;
  const inputId = `channel-${channel}`;
  const detailId = `${inputId}-detail`;

  return (
    <div className="rounded-md border border-ap-line p-3">
      <div className="flex items-start gap-3">
        {/* `htmlFor` rather than wrapping the input, so the checkbox's
            accessible name is the channel label alone. Nesting it inside the
            <label> swept the hint and the address into that name, which is
            what a screen reader then reads out on focus. */}
        <input
          id={inputId}
          type="checkbox"
          className="mt-1"
          checked={checked}
          onChange={onToggle}
          aria-describedby={detailId}
        />
        <div className="min-w-0">
          <label htmlFor={inputId} className="block text-sm font-medium text-ap-ink">
            {t(`notifications.channel.${channel}.label`)}
          </label>
          <p id={detailId} className="mt-0.5 text-sm text-ap-muted">
            {channel === "email" && emailAddress
              ? t("notifications.channel.email.to", { address: emailAddress })
              : channel === "push" && deviceCount > 0
                ? t("notifications.channel.push.devices", { count: deviceCount })
                : t(`notifications.channel.${channel}.hint`)}
          </p>
          {checked && blocked && reasonKey ? (
            <p className="mt-2 text-sm text-ap-warn">{t(`notifications.reason.${reasonKey}`)}</p>
          ) : null}
        </div>
      </div>
    </div>
  );
}
