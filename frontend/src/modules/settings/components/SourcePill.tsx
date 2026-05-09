import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Pill } from "@/components/Pill";
import type { SettingSource } from "@/api/integrations";

interface Props {
  source: SettingSource;
}

const KIND: Record<SettingSource, "neutral" | "ok" | "warn" | "info"> = {
  platform: "neutral",
  tenant: "info",
  farm: "info",
  resource: "warn",
};

/** Inheritance-source badge — "Default", "Tenant", "Farm", "Block". */
export function SourcePill({ source }: Props): ReactNode {
  const { t } = useTranslation("integrations");
  return <Pill kind={KIND[source]}>{t(`source.${source}`)}</Pill>;
}
