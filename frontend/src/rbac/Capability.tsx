import type { ReactNode } from "react";
import { useCapability, type CapabilityScope } from "./useCapability";
import type { Capability } from "./capabilities";

interface Props {
  capability: Capability;
  scope?: CapabilityScope;
  fallback?: ReactNode;
  children: ReactNode;
}

/** Renders children only if the current user has the capability. */
export function RequireCapability({
  capability,
  scope,
  fallback = null,
  children,
}: Props): ReactNode {
  const granted = useCapability(capability, scope ?? {});
  return granted ? <>{children}</> : <>{fallback}</>;
}
