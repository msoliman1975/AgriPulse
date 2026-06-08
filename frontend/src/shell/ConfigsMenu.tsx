import { useEffect, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";

import { GearIcon, ImageryIcon, RulesIcon, SignalsIcon } from "./icons";

/*
 * Configuration entry point in the top bar (UX feedback: config moved out of
 * the left workspace nav). A gear button opens a small menu of the config
 * destinations — per-farm Imagery & weather and the tenant Settings hub
 * (integrations, rules, users, decision trees). Closes on outside-click /
 * Escape, the conventional menu-button pattern.
 */
export function ConfigsMenu(): ReactNode {
  const { t } = useTranslation("common");
  const { farmId } = useParams<{ farmId?: string }>();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onPointer = (e: MouseEvent): void => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("mousedown", onPointer);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("mousedown", onPointer);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const itemClass =
    "flex items-center gap-2 px-3 py-2 text-sm text-ap-ink hover:bg-ap-line/50";

  return (
    <div className="relative" ref={rootRef}>
      <button
        type="button"
        aria-label={t("shell.configsTitle")}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="rounded-md p-2 text-ap-muted hover:bg-ap-line/40 focus:outline-none focus-visible:ring-2 focus-visible:ring-ap-primary"
      >
        <GearIcon className="h-5 w-5" />
      </button>
      {open ? (
        <div
          role="menu"
          className="absolute end-0 z-30 mt-1 w-56 overflow-hidden rounded-md border border-ap-line bg-ap-panel py-1 shadow-lg"
        >
          <ConfigFarmLink
            to={farmId ? `/config/imagery/${farmId}` : undefined}
            icon={<ImageryIcon className="h-4 w-4" />}
            label={t("workspaceNav.imageryWeather")}
            pickFarmTitle={t("workspaceNav.pickFarm")}
            itemClass={itemClass}
            onNavigate={() => setOpen(false)}
          />
          <ConfigFarmLink
            to={farmId ? `/config/signals/${farmId}` : undefined}
            icon={<SignalsIcon className="h-4 w-4" />}
            label={t("workspaceNav.customSignals")}
            pickFarmTitle={t("workspaceNav.pickFarm")}
            itemClass={itemClass}
            onNavigate={() => setOpen(false)}
          />
          <Link
            to="/settings"
            role="menuitem"
            onClick={() => setOpen(false)}
            className={itemClass}
          >
            <RulesIcon className="h-4 w-4" />
            {t("shell.configTenantSettings")}
          </Link>
        </div>
      ) : null}
    </div>
  );
}

function ConfigFarmLink({
  to,
  icon,
  label,
  pickFarmTitle,
  itemClass,
  onNavigate,
}: {
  to?: string;
  icon: ReactNode;
  label: string;
  pickFarmTitle: string;
  itemClass: string;
  onNavigate: () => void;
}): ReactNode {
  // Per-farm config needs an active farm. Without one, show a disabled row
  // with a "pick a farm" tooltip rather than a dead link.
  if (!to) {
    return (
      <span
        className="flex items-center gap-2 px-3 py-2 text-sm text-ap-muted/60"
        title={pickFarmTitle}
      >
        {icon}
        {label}
      </span>
    );
  }
  return (
    <Link to={to} role="menuitem" onClick={onNavigate} className={itemClass}>
      {icon}
      {label}
    </Link>
  );
}
