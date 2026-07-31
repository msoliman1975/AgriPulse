import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { PageHeader } from "@/components/PageHeader";
import { useCapability } from "@/rbac/useCapability";
import type { Capability } from "@/rbac/capabilities";

interface Props {
  /** i18n namespace key under `settings:placeholder.<key>`. */
  i18nKey: "org" | "notifications" | "integrations";
  /** Capability gating this tab. Empty body if missing. */
  requires: Capability;
}

/**
 * Reusable "coming soon" body for settings tabs that ship with PR-Set1
 * but get their real implementation in later PRs (Set4 fills out
 * Integrations; Set5/Set6/Set7 fill out the rest of the tree).
 */
export function SettingsPlaceholderPage({ i18nKey, requires }: Props): ReactNode {
  const { t } = useTranslation("settings");
  const has = useCapability(requires);
  if (!has) {
    return (
      <div className="mx-auto max-w-3xl py-12 text-center">
        <p className="text-sm text-ap-muted">
          {t("noAccess.missingCapability", { capability: requires })}
        </p>
      </div>
    );
  }
  // The placeholder IS the whole route, so its title is the page title.
  // Demoting it to <h2> to satisfy the no-raw-<h1> rule left /settings/org
  // and /settings/notifications with no page heading at all; <PageHeader> is
  // what the rule was pointing at. The dashed panel stays — it reads as
  // "not built yet" in a way a normal Card does not.
  return (
    <div className="flex flex-col gap-6">
      <PageHeader title={t(`placeholder.${i18nKey}.title`)} />
      <div className="rounded-xl border border-dashed border-ap-line bg-ap-panel/50 p-10 text-center">
        <p className="text-sm text-ap-muted">{t(`placeholder.${i18nKey}.body`)}</p>
      </div>
    </div>
  );
}
