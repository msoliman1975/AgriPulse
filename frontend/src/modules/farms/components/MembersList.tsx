import { useTranslation } from "react-i18next";

import type { FarmMember } from "@/api/farmMembers";

interface Props {
  members: FarmMember[];
  canRevoke: boolean;
  onRevoke?: (farmScopeId: string) => void;
}

export function MembersList({ members, canRevoke, onRevoke }: Props): JSX.Element {
  const { t, i18n } = useTranslation("farms");
  const active = members.filter((m) => m.revoked_at === null);
  if (active.length === 0) {
    return <p className="text-sm text-slate-600">{t("members.empty")}</p>;
  }
  return (
    <ul className="divide-y divide-slate-200">
      {active.map((m) => (
        <li key={m.id} className="flex items-center justify-between py-2 text-sm">
          <span>
            <span className="font-medium text-slate-800">{t(`roles.${m.role}`)}</span>
            <span className="ms-2 text-xs text-slate-500">{m.membership_id.slice(0, 8)}…</span>
          </span>
          <span className="flex items-center gap-3">
            <time className="text-xs text-slate-500">
              {new Date(m.granted_at).toLocaleDateString(i18n.language)}
            </time>
            {canRevoke && onRevoke ? (
              <button
                type="button"
                className="btn btn-ghost text-red-700"
                onClick={() => onRevoke(m.id)}
              >
                {t("members.revoke")}
              </button>
            ) : null}
          </span>
        </li>
      ))}
    </ul>
  );
}
