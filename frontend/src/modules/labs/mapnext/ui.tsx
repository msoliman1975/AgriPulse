// Shared presentational primitives for the redesigned Farm Console
// (/labs/map-next). Kept local to the module so iteration here never
// risks the existing /labs/map surface. See
// docs/proposals/farm-management-redesign.md.
import clsx from "clsx";
import {
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useTranslation } from "react-i18next";

export function Dot({ color, className }: { color: string; className?: string }): ReactNode {
  return (
    <span
      className={clsx("inline-block h-2 w-2 rounded-full", className)}
      style={{ backgroundColor: color }}
    />
  );
}

// ---- section header -------------------------------------------------------
export function SectionHeader({ children }: { children: ReactNode }): ReactNode {
  return (
    <div className="mt-4 mb-1.5 flex items-center gap-2 px-4">
      <span className="text-xs font-bold uppercase tracking-wide text-ap-primary">
        {children}
      </span>
      <span className="h-px flex-1 bg-ap-line" />
    </div>
  );
}

// ---- monitor card ---------------------------------------------------------
export function MCard({
  icon,
  title,
  value,
  valueColor,
  children,
}: {
  icon?: ReactNode;
  title: ReactNode;
  value?: ReactNode;
  valueColor?: string;
  children?: ReactNode;
}): ReactNode {
  return (
    <div className="mx-4 my-2 overflow-hidden rounded-xl border border-ap-line">
      <div className="flex items-center gap-2 bg-ap-bg/60 px-3 py-2.5">
        {icon ? <span className="text-base leading-none">{icon}</span> : null}
        <span className="flex-1 text-xs font-bold text-ap-ink">{title}</span>
        {value != null ? (
          <span className="text-sm font-bold tabular-nums" style={valueColor ? { color: valueColor } : undefined}>
            {value}
          </span>
        ) : null}
      </div>
      {children != null ? (
        <div className="border-t border-ap-line px-3 py-2.5">{children}</div>
      ) : null}
    </div>
  );
}

export function KV({ k, v, vColor }: { k: ReactNode; v: ReactNode; vColor?: string }): ReactNode {
  return (
    <div className="flex justify-between py-1 text-sm">
      <span className="text-ap-muted">{k}</span>
      <span className="font-semibold tabular-nums" style={vColor ? { color: vColor } : undefined}>
        {v}
      </span>
    </div>
  );
}

// ---- collapsible expander -------------------------------------------------
export function Expander({
  icon,
  title,
  badge,
  defaultOpen = false,
  children,
}: {
  icon?: ReactNode;
  title: ReactNode;
  badge?: ReactNode;
  defaultOpen?: boolean;
  children: ReactNode;
}): ReactNode {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="mx-4 my-2 overflow-hidden rounded-xl border border-ap-line">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 px-3 py-2.5 text-start text-sm font-semibold text-ap-ink hover:bg-ap-bg/50"
      >
        {icon ? <span className="leading-none">{icon}</span> : null}
        <span>{title}</span>
        {badge != null ? <span className="ms-auto">{badge}</span> : null}
        <span className={clsx("text-ap-muted transition-transform", badge == null && "ms-auto", open && "rotate-90")}>
          ›
        </span>
      </button>
      {open ? <div className="border-t border-ap-line px-3 py-2.5 text-sm">{children}</div> : null}
    </div>
  );
}

// ---- sparkline ------------------------------------------------------------
export function Sparkline({
  points,
  color = "#356b30",
  height = 36,
}: {
  points: (number | null)[];
  color?: string;
  height?: number;
}): ReactNode {
  const { t } = useTranslation("farmConsole");
  const vals = points.filter((p): p is number => p != null);
  if (vals.length < 2) {
    return <div className="text-xs text-ap-muted">{t("sparkline.notEnough")}</div>;
  }
  const min = Math.min(...vals);
  const max = Math.max(...vals);
  const span = max - min || 1;
  const w = 100;
  const n = points.length;
  const coords: string[] = [];
  points.forEach((p, i) => {
    if (p == null) return;
    const x = (i / (n - 1)) * w;
    const y = height - ((p - min) / span) * (height - 4) - 2;
    coords.push(`${x.toFixed(1)},${y.toFixed(1)}`);
  });
  return (
    <svg viewBox={`0 0 ${w} ${height}`} preserveAspectRatio="none" className="h-9 w-full">
      <polyline points={coords.join(" ")} fill="none" stroke={color} strokeWidth={2} vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

// ---- popover (anchored dropdown) ------------------------------------------
export function Popover({
  open,
  onClose,
  anchorRef,
  align = "start",
  children,
}: {
  open: boolean;
  onClose: () => void;
  anchorRef: React.RefObject<HTMLElement>;
  align?: "start" | "end";
  children: ReactNode;
}): ReactNode {
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ top: number; left?: number; right?: number } | null>(null);

  useEffect(() => {
    if (!open || !anchorRef.current) return;
    const r = anchorRef.current.getBoundingClientRect();
    const rtl = document.documentElement.dir === "rtl";
    const top = r.bottom + 6;
    // Align the popover edge to the anchor edge, respecting direction.
    if (align === "end") {
      setPos(rtl ? { top, left: r.left } : { top, right: window.innerWidth - r.right });
    } else {
      setPos(rtl ? { top, right: window.innerWidth - r.right } : { top, left: r.left });
    }
  }, [open, anchorRef, align]);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current?.contains(e.target as Node)) return;
      if (anchorRef.current?.contains(e.target as Node)) return;
      onClose();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, onClose, anchorRef]);

  if (!open || !pos) return null;
  return (
    <div
      ref={ref}
      className="fixed z-50 min-w-[230px] rounded-xl border border-ap-line bg-ap-panel p-1.5 shadow-card"
      style={{ top: pos.top, left: pos.left, right: pos.right }}
    >
      {children}
    </div>
  );
}

export function PopHeading({ children }: { children: ReactNode }): ReactNode {
  return (
    <div className="px-2.5 pb-1 pt-2 text-xs font-bold uppercase tracking-wide text-ap-muted">
      {children}
    </div>
  );
}

export function PopItem({
  icon,
  children,
  onClick,
  danger,
  disabled,
  hint,
}: {
  icon?: ReactNode;
  children: ReactNode;
  onClick?: () => void;
  danger?: boolean;
  disabled?: boolean;
  hint?: ReactNode;
}): ReactNode {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={clsx(
        "flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-start text-sm font-medium transition-colors",
        disabled ? "cursor-not-allowed opacity-50" : "hover:bg-ap-primary-soft",
        danger ? "text-ap-crit" : "text-ap-ink",
      )}
    >
      {icon ? <span className="w-4 text-center leading-none">{icon}</span> : null}
      <span className="flex-1">{children}</span>
      {hint != null ? <span className="text-xs font-normal text-ap-muted">{hint}</span> : null}
    </button>
  );
}

export function PopDivider(): ReactNode {
  return <div className="mx-1 my-1.5 h-px bg-ap-line" />;
}
