import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

export function HomePage(): ReactNode {
  const { t } = useTranslation("common");
  return (
    <div className="card max-w-2xl">
      <h1 className="text-2xl font-semibold text-brand-800">{t("home.welcome")}</h1>
      <p className="mt-2 text-slate-600">{t("home.comingSoon")}</p>
    </div>
  );
}
