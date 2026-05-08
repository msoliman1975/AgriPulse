import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate, useParams } from "react-router-dom";

import { listFarms } from "@/api/farms";
import { useCapability } from "@/rbac/useCapability";
import { ChevronIcon } from "./icons";

const PINNED_PREFIXES = ["/insights/", "/plan/", "/alerts/", "/reports/", "/config/"];

/**
 * Breadcrumb-anchored farm switcher. Keeps the user on the current view
 * but swaps the `:farmId` segment when they pick a different farm.
 */
export function FarmSwitcher(): ReactNode {
  const { farmId } = useParams<{ farmId?: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const { t } = useTranslation("common");
  const canCreateFarm = useCapability("farm.create");
  const [open, setOpen] = useState(false);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);

  const { data: page } = useQuery({
    queryKey: ["farms", "list", "switcher"] as const,
    queryFn: () => listFarms(),
    staleTime: 60_000,
  });
  const farms = page?.items ?? [];
  const active = farms.find((f) => f.id === farmId);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (
        !buttonRef.current?.contains(e.target as Node) &&
        !popoverRef.current?.contains(e.target as Node)
      ) {
        setOpen(false);
      }
    };
    window.addEventListener("mousedown", handler);
    return () => window.removeEventListener("mousedown", handler);
  }, [open]);

  const goTo = (id: string): void => {
    // If the current pathname has a farm segment we recognise, swap it.
    // Otherwise default to /insights/<id>.
    let nextPath = `/insights/${id}`;
    for (const prefix of PINNED_PREFIXES) {
      if (location.pathname.startsWith(prefix)) {
        // Replace the segment after the prefix (handles /config/rules/<id>).
        const segments = location.pathname.split("/");
        // Last segment is the farmId for our current pinned routes.
        if (segments.length >= 2) {
          segments[segments.length - 1] = id;
          nextPath = segments.join("/");
        }
        break;
      }
    }
    setOpen(false);
    navigate(nextPath);
  };

  if (farms.length === 0) {
    if (canCreateFarm) {
      return (
        <button
          type="button"
          onClick={() => navigate("/farms/new")}
          className="rounded-md bg-ap-primary px-2 py-1 text-sm font-medium text-white hover:bg-ap-primary/90 focus:outline-none focus-visible:ring-2 focus-visible:ring-ap-primary"
        >
          {t("home.createFirstFarm")}
        </button>
      );
    }
    return <span className="text-sm text-ap-muted">{t("home.noFarmsTitle")}</span>;
  }

  return (
    <div className="relative">
      <button
        ref={buttonRef}
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="listbox"
        aria-expanded={open}
        className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-sm font-medium text-ap-ink hover:bg-ap-line/50 focus:outline-none focus-visible:ring-2 focus-visible:ring-ap-primary"
      >
        <span className="truncate">{active?.name ?? "Pick a farm"}</span>
        <ChevronIcon className="h-3 w-3 rotate-90" />
      </button>
      {open ? (
        <div
          ref={popoverRef}
          role="listbox"
          className="absolute start-0 top-full z-40 mt-1 max-h-80 w-64 overflow-auto rounded-lg border border-ap-line bg-ap-panel p-1 shadow-card"
        >
          {farms.map((f) => {
            const selected = f.id === farmId;
            return (
              <button
                type="button"
                key={f.id}
                role="option"
                aria-selected={selected}
                onClick={() => goTo(f.id)}
                className={`flex w-full flex-col items-start gap-0.5 rounded-md px-3 py-2 text-start text-sm hover:bg-ap-line/40 ${
                  selected ? "bg-ap-primary-soft" : ""
                }`}
              >
                <span className="font-medium text-ap-ink">{f.name}</span>
                <span className="text-[11px] text-ap-muted">{f.code}</span>
              </button>
            );
          })}
          {canCreateFarm ? (
            <>
              <div role="separator" className="my-1 border-t border-ap-line" />
              <button
                type="button"
                onClick={() => {
                  setOpen(false);
                  navigate("/farms/new");
                }}
                className="flex w-full items-center rounded-md px-3 py-2 text-start text-sm font-medium text-ap-primary hover:bg-ap-line/40"
              >
                {t("farmSwitcher.newFarm")}
              </button>
            </>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
