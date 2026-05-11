// Tenant-portal entry point. The page body now lives in the shared
// `modules/integrationsHealth` package so the platform drill-in
// (PR-IH7) reuses the exact same tabs.

import type { ReactNode } from "react";

import { IntegrationsHealthPage as SharedIntegrationsHealthPage } from "@/modules/integrationsHealth";

export function IntegrationsHealthPage(): ReactNode {
  return <SharedIntegrationsHealthPage basePath="/v1" platformProviderScope={false} />;
}
