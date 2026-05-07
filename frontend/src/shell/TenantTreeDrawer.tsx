import type { ReactNode } from "react";

import { Drawer } from "./Drawer";
import { TenantTree } from "./TenantTree";

interface Props {
  open: boolean;
  onClose: () => void;
}

/**
 * Houses the legacy tenant/farm/block tree behind a drawer toggle. Useful
 * for org-admin users who still need the cross-tenant overview the
 * AgriPulse IA hides by default.
 */
export function TenantTreeDrawer({ open, onClose }: Props): ReactNode {
  return (
    <Drawer open={open} onClose={onClose} title="Organization tree" side="start">
      <TenantTree />
    </Drawer>
  );
}
