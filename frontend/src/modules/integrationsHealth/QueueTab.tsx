import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

/**
 * Placeholder — implemented by PR-IH4.
 */
export interface QueueTabProps {
  basePath: string;
}

export function QueueTab(_: QueueTabProps): ReactNode {
  const { t } = useTranslation("integrationsHealth");
  return (
    <div className="rounded-xl border border-dashed border-ap-line bg-ap-panel px-4 py-12 text-center text-sm text-ap-muted">
      {t("queue.placeholder")}
    </div>
  );
}
