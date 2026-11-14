// Platform > Operation manuals: the manual catalogue (draft, published,
// archived). Same list as the old plan templates page; rows open the
// Agri Operation editor.

import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { PlatformPlanTemplatesPage } from "@/modules/admin/pages/PlatformPlanTemplatesPage";

export function ManualListPage(): ReactNode {
  const { t } = useTranslation("agriOperation");
  return (
    <PlatformPlanTemplatesPage
      basePath="/platform/operation-manuals"
      title={t("editor.listTitle")}
      subtitle={t("editor.listSubtitle")}
    />
  );
}
