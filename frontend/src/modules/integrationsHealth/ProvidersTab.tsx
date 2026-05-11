import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

/**
 * Placeholder — implemented by PR-IH6.
 */
export interface ProvidersTabProps {
  basePath: string;
  platformScope: boolean;
}

export function ProvidersTab(_: ProvidersTabProps): ReactNode {
  const { t } = useTranslation("integrationsHealth");
  return (
    <div className="rounded-xl border border-dashed border-ap-line bg-ap-panel px-4 py-12 text-center text-sm text-ap-muted">
      {t("providers.placeholder")}
    </div>
  );
}
