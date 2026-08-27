import type { ReactNode } from "react";
import { useAuth } from "react-oidc-context";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/Button";
import { useMe } from "@/hooks/useMe";
import { localizedField } from "@/lib/localizedField";

export function UserMenu(): ReactNode {
  const auth = useAuth();
  const { t, i18n } = useTranslation("common");
  // The Arabic name lives in `public.users`, not in the token: the OIDC
  // profile carries whatever Keycloak holds, which is the Latin name. Reading
  // the cached /me here costs nothing — the shell already has it — and is the
  // difference between an Arabic page headed by an Arabic name and one headed
  // by a Latin one.
  const me = useMe();

  if (!auth.isAuthenticated || !auth.user) {
    return null;
  }

  const profile = auth.user.profile;
  const displayName =
    localizedField(i18n.language, me.data?.full_name ?? null, me.data?.full_name_ar) ??
    profile.name ??
    profile.preferred_username ??
    profile.email ??
    "user";

  const onSignOut = (): void => {
    void auth.signoutRedirect();
  };

  return (
    <div className="flex items-center gap-2">
      <span className="hidden text-sm text-ap-ink sm:inline" data-testid="user-display-name">
        {displayName}
      </span>
      <Button
        variant="ghost"
        className="px-2 py-1 text-xs"
        onClick={onSignOut}
        aria-label={t("shell.userMenu")}
      >
        {t("shell.signOut")}
      </Button>
    </div>
  );
}
