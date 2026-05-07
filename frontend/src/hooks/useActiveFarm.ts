import { useParams } from "react-router-dom";

/**
 * Resolves the active farm id from the URL `:farmId` segment. Pages that
 * are farm-scoped (Insights, Plan, Alerts, Reports, Configuration) use
 * this so they don't repeat `useParams<{ farmId: string }>()` everywhere.
 *
 * Returns undefined when there is no farm in the route — the side-nav
 * uses that to render Workspace items as disabled.
 */
export function useActiveFarmId(): string | undefined {
  const { farmId } = useParams<{ farmId?: string }>();
  return farmId;
}
