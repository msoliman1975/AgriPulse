import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Drawer } from "./Drawer";

interface Props {
  open: boolean;
  onClose: () => void;
}

// Placeholder until the alerts service is wired. Renders an empty state
// with the same drawer chrome the live list will use.
export function AlertsDrawer({ open, onClose }: Props): ReactNode {
  const { t } = useTranslation("common");
  return (
    <Drawer open={open} onClose={onClose} title={t("shell.alertsTitle")}>
      <p className="text-sm text-slate-600">{t("shell.alertsEmpty")}</p>
    </Drawer>
  );
}
