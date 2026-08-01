import type { ReactNode } from "react";
import { useAuth } from "react-oidc-context";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/Button";

export function UserMenu(): ReactNode {
  const auth = useAuth();
  const { t } = useTranslation("common");

  if (!auth.isAuthenticated || !auth.user) {
    return null;
  }

  const profile = auth.user.profile;
  const displayName = profile.name ?? profile.preferred_username ?? profile.email ?? "user";

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
