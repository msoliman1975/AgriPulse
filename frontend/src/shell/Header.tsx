import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { LanguageToggle } from "./LanguageToggle";
import { UnitToggle } from "./UnitToggle";
import { UserMenu } from "./UserMenu";

export function Header(): ReactNode {
  const { t } = useTranslation("common");
  return (
    <header className="border-b border-slate-200 bg-white">
      <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-4 py-3">
        <Link
          to="/"
          className="flex items-center gap-2 text-lg font-semibold text-brand-700 focus:outline-none focus:ring-2 focus:ring-brand-500"
        >
          <span aria-hidden="true" className="inline-block h-3 w-3 rounded-full bg-brand-600" />
          {t("app.name")}
        </Link>
        <div className="flex items-center gap-4">
          <LanguageToggle />
          <UnitToggle />
          <UserMenu />
        </div>
      </div>
    </header>
  );
}
