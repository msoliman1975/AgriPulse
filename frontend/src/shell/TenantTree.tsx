import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { NavLink, useLocation, useMatch } from "react-router-dom";
import { useAuth } from "react-oidc-context";
import { useTranslation } from "react-i18next";

import { fetchMe, type Me, type TenantMembership } from "@/api/me";
import { listFarms, type Farm } from "@/api/farms";
import { listBlocks, type Block } from "@/api/blocks";
import { isApiError } from "@/api/errors";
import { decodeJwt } from "@/rbac/jwt";
import { BlockIcon, ChevronIcon, FarmIcon, HomeIcon, TenantIcon } from "./icons";

const homeLinkClass = ({ isActive }: { isActive: boolean }): string =>
  [
    "flex items-center gap-2 rounded-md px-3 py-2 text-sm",
    isActive ? "bg-brand-50 text-brand-700 font-medium" : "text-slate-700 hover:bg-slate-100",
  ].join(" ");

export function TenantTree(): ReactNode {
  const { t } = useTranslation("common");
  const auth = useAuth();
  const accessToken = auth.user?.access_token;
  const activeTenantId = decodeJwt(accessToken)?.tenant_id ?? null;

  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // Wait until the OIDC token is in hand. Without this gate, the first
    // mount can fire fetchMe() before AuthSync has populated the token
    // registry → 401 → sign-in redirect loop on every page that mounts
    // the shell.
    if (!accessToken) return;
    let cancelled = false;
    fetchMe()
      .then((data) => {
        if (!cancelled) setMe(data);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (isApiError(err)) setError(err.problem.detail ?? err.problem.title);
        else setError(String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [accessToken]);

  const tenants: TenantMembership[] = me?.tenant_memberships ?? [];

  return (
    <nav
      aria-label="Primary"
      className="hidden w-72 flex-shrink-0 overflow-y-auto border-e border-slate-200 bg-white p-3 md:block"
    >
      <ul className="flex flex-col gap-1">
        <li>
          <NavLink to="/" end className={homeLinkClass}>
            <HomeIcon className="h-4 w-4" />
            {t("nav.home")}
          </NavLink>
        </li>
      </ul>

      <div className="mt-3 border-t border-slate-100 pt-3">
        {error ? (
          <p role="alert" className="px-2 text-xs text-red-700">
            {error}
          </p>
        ) : !me ? (
          <p role="status" className="px-2 text-xs text-slate-500">
            {t("actions.loading")}
          </p>
        ) : tenants.length === 0 ? (
          <p className="px-2 text-xs text-slate-500">{t("nav.noTenants")}</p>
        ) : (
          <ul className="flex flex-col gap-1">
            {tenants.map((tenant) => (
              <TenantNode
                key={tenant.tenant_id}
                tenant={tenant}
                isActiveTenant={tenant.tenant_id === activeTenantId}
              />
            ))}
          </ul>
        )}
      </div>
    </nav>
  );
}

interface TenantNodeProps {
  tenant: TenantMembership;
  isActiveTenant: boolean;
}

function TenantNode({ tenant, isActiveTenant }: TenantNodeProps): ReactNode {
  const location = useLocation();
  const tenantMatch = useMatch({ path: `/tenants/${tenant.tenant_id}`, end: true });

  // Open by default when this tenant is the user's active session tenant —
  // farms can only be listed for that tenant in the current backend model.
  const [open, setOpen] = useState<boolean>(isActiveTenant);
  const [farms, setFarms] = useState<Farm[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || !isActiveTenant || farms !== null) return;
    let cancelled = false;
    listFarms()
      .then((page) => {
        if (!cancelled) setFarms(page.items);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (isApiError(err)) setError(err.problem.detail ?? err.problem.title);
        else setError(String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [open, isActiveTenant, farms]);

  const isSelected = Boolean(tenantMatch);

  return (
    <li>
      <div className="flex items-center">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          aria-label={open ? "Collapse" : "Expand"}
          className="rounded p-1 text-slate-500 hover:bg-slate-100"
        >
          <ChevronIcon className="h-3.5 w-3.5" open={open} />
        </button>
        <NavLink
          to={`/tenants/${tenant.tenant_id}`}
          className={[
            "flex flex-1 items-center gap-2 rounded-md px-2 py-1.5 text-sm",
            isSelected
              ? "bg-brand-50 text-brand-700 font-medium"
              : "text-slate-800 hover:bg-slate-100",
          ].join(" ")}
        >
          <TenantIcon className="h-4 w-4 text-brand-700" />
          <span className="truncate">{tenant.tenant_name}</span>
        </NavLink>
      </div>

      {open ? (
        <div className="ms-5 mt-1 border-s border-slate-200 ps-2">
          {!isActiveTenant ? (
            <p className="px-2 py-1 text-xs text-slate-500">
              {/* Multi-tenant switch isn't wired yet; only active tenant lists farms. */}
              {/* Falls back to a tenant-only entry. */}
              <span>—</span>
            </p>
          ) : error ? (
            <p role="alert" className="px-2 py-1 text-xs text-red-700">
              {error}
            </p>
          ) : farms === null ? (
            <p className="px-2 py-1 text-xs text-slate-500">…</p>
          ) : farms.length === 0 ? (
            <p className="px-2 py-1 text-xs text-slate-500">—</p>
          ) : (
            <ul className="flex flex-col gap-0.5">
              {farms.map((f) => (
                <FarmNode key={f.id} farm={f} pathname={location.pathname} />
              ))}
            </ul>
          )}
        </div>
      ) : null}
    </li>
  );
}

interface FarmNodeProps {
  farm: Farm;
  pathname: string;
}

function FarmNode({ farm, pathname }: FarmNodeProps): ReactNode {
  const farmMatch = useMatch({ path: `/farms/${farm.id}`, end: true });
  const blockUnderFarm = pathname.startsWith(`/farms/${farm.id}/blocks/`);

  const [open, setOpen] = useState<boolean>(blockUnderFarm);
  const [blocks, setBlocks] = useState<Block[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || blocks !== null) return;
    let cancelled = false;
    listBlocks(farm.id)
      .then((page) => {
        if (!cancelled) setBlocks(page.items);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (isApiError(err)) setError(err.problem.detail ?? err.problem.title);
        else setError(String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [open, blocks, farm.id]);

  const isSelected = Boolean(farmMatch);

  return (
    <li>
      <div className="flex items-center">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          aria-label={open ? "Collapse" : "Expand"}
          className="rounded p-1 text-slate-500 hover:bg-slate-100"
        >
          <ChevronIcon className="h-3.5 w-3.5" open={open} />
        </button>
        <NavLink
          to={`/farms/${farm.id}`}
          className={[
            "flex flex-1 items-center gap-2 rounded-md px-2 py-1 text-sm",
            isSelected
              ? "bg-brand-50 text-brand-700 font-medium"
              : "text-slate-700 hover:bg-slate-100",
          ].join(" ")}
        >
          <FarmIcon className="h-4 w-4 text-emerald-700" />
          <span className="truncate">
            {farm.name}
            <span className="ms-1 text-xs text-slate-400">{farm.code}</span>
          </span>
        </NavLink>
      </div>

      {open ? (
        <div className="ms-5 mt-0.5 border-s border-slate-200 ps-2">
          {error ? (
            <p role="alert" className="px-2 py-1 text-xs text-red-700">
              {error}
            </p>
          ) : blocks === null ? (
            <p className="px-2 py-1 text-xs text-slate-500">…</p>
          ) : blocks.length === 0 ? (
            <p className="px-2 py-1 text-xs text-slate-500">—</p>
          ) : (
            <ul className="flex flex-col gap-0.5">
              {blocks.map((b) => (
                <BlockNode key={b.id} block={b} farmId={farm.id} />
              ))}
            </ul>
          )}
        </div>
      ) : null}
    </li>
  );
}

interface BlockNodeProps {
  block: Block;
  farmId: string;
}

function BlockNode({ block, farmId }: BlockNodeProps): ReactNode {
  const match = useMatch({ path: `/farms/${farmId}/blocks/${block.id}`, end: true });
  return (
    <li>
      <NavLink
        to={`/farms/${farmId}/blocks/${block.id}`}
        className={[
          "flex items-center gap-2 rounded-md px-2 py-1 text-sm",
          match ? "bg-brand-50 text-brand-700 font-medium" : "text-slate-700 hover:bg-slate-100",
        ].join(" ")}
      >
        <BlockIcon className="h-4 w-4 text-amber-700" />
        <span className="truncate">
          {block.code}
          {block.name ? <span className="ms-1 text-xs text-slate-500">{block.name}</span> : null}
        </span>
      </NavLink>
    </li>
  );
}
