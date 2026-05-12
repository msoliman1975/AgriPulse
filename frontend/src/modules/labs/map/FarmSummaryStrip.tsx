import type { FarmDetail } from "@/api/farms";

interface Props {
  farm: FarmDetail;
  onOpenDrawer: () => void;
}

// Slim always-visible status band between toolbar and map. Quick-glance
// fields only — the full edit surface lives in FarmDrawer (opened by
// clicking the row or the Details button).
export function FarmSummaryStrip({ farm, onOpenDrawer }: Props) {
  const hectares = (farm.area_m2 / 10_000).toFixed(2);
  const updated = formatRelative(farm.updated_at);

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onOpenDrawer}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onOpenDrawer();
        }
      }}
      className="flex h-8 cursor-pointer items-center justify-between border-b border-slate-200 bg-slate-50 px-3 text-[11px] text-slate-700 hover:bg-slate-100"
    >
      <div className="flex min-w-0 items-center gap-3">
        <span className="font-medium text-slate-900">{farm.code}</span>
        <span className="truncate text-slate-700">{farm.name}</span>
        <span className="text-slate-500">{hectares} ha</span>
        {farm.governorate ? (
          <span className="text-slate-500">{farm.governorate}</span>
        ) : null}
        <span className="text-slate-500">{farm.farm_type}</span>
        {farm.primary_water_source ? (
          <span className="text-slate-500">{farm.primary_water_source}</span>
        ) : null}
        <StatusBadge active={farm.is_active} activeTo={farm.active_to} />
        {farm.tags.length > 0 ? (
          <span className="truncate text-slate-500">
            {farm.tags.slice(0, 3).join(" · ")}
            {farm.tags.length > 3 ? ` +${farm.tags.length - 3}` : ""}
          </span>
        ) : null}
      </div>
      <div className="flex shrink-0 items-center gap-2 text-[10px] text-slate-500">
        <span>updated {updated}</span>
        <span className="rounded border border-slate-300 px-1.5 py-0.5 text-[10px] text-slate-700">
          Details
        </span>
      </div>
    </div>
  );
}

function StatusBadge({
  active,
  activeTo,
}: {
  active: boolean;
  activeTo: string | null;
}) {
  if (active) {
    return (
      <span className="rounded bg-emerald-100 px-1.5 py-0.5 text-[10px] font-medium text-emerald-800">
        Active
      </span>
    );
  }
  return (
    <span
      className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium text-amber-900"
      title={activeTo ? `Inactive since ${activeTo}` : "Inactive"}
    >
      {activeTo ? `Inactive · ${activeTo}` : "Inactive"}
    </span>
  );
}

function formatRelative(iso: string): string {
  const t = new Date(iso).getTime();
  const diff = Date.now() - t;
  const hours = Math.round(diff / 3_600_000);
  if (hours < 1) return "just now";
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days}d ago`;
  const months = Math.round(days / 30);
  return `${months}mo ago`;
}
