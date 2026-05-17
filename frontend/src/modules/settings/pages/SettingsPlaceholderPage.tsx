import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

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
  return (
    <div className="rounded-xl border border-dashed border-ap-line bg-ap-panel/50 p-10 text-center">
      <h1 className="text-lg font-semibold text-ap-ink">{t(`placeholder.${i18nKey}.title`)}</h1>
      <p className="mt-2 text-sm text-ap-muted">{t(`placeholder.${i18nKey}.body`)}</p>
    </div>
  );
}
