import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { useTranslation } from "react-i18next";

// Placeholder side navigation. Module pages slot themselves in here in
// later prompts (farms, alerts, etc.). The structure is logical-property-
// safe so RTL mirroring happens automatically.
export function SideNav(): ReactNode {
  const { t } = useTranslation("common");
  const { t: tFarms } = useTranslation("farms");

  const linkClass = ({ isActive }: { isActive: boolean }): string =>
    [
      "flex items-center rounded-md px-3 py-2 text-sm",
      isActive ? "bg-brand-50 text-brand-700 font-medium" : "text-slate-700 hover:bg-slate-100",
    ].join(" ");

  return (
    <nav
      aria-label="Primary"
      className="hidden w-56 flex-shrink-0 border-e border-slate-200 bg-white p-4 md:block"
    >
      <ul className="flex flex-col gap-1">
        <li>
          <NavLink to="/" end className={linkClass}>
            {t("nav.home")}
          </NavLink>
        </li>
        <li>
          <NavLink to="/farms" className={linkClass}>
            {tFarms("nav.farms")}
          </NavLink>
        </li>
        <li>
          <NavLink to="/me" className={linkClass}>
            {t("nav.me")}
          </NavLink>
        </li>
      </ul>
    </nav>
  );
}
