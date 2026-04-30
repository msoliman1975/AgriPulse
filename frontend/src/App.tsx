import type { ReactNode } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { AuthProvider } from "@/auth/AuthProvider";
import { AuthSync } from "@/auth/AuthSync";
import { ProtectedRoute } from "@/auth/ProtectedRoute";
import { PrefsProvider } from "@/prefs/PrefsContext";
import { AppShell } from "@/shell/AppShell";
import { HomePage } from "@/pages/HomePage";
import { LoginPage } from "@/pages/LoginPage";
import { MePage } from "@/pages/MePage";
import { FarmListPage } from "@/modules/farms/pages/FarmListPage";
import { FarmCreatePage } from "@/modules/farms/pages/FarmCreatePage";
import { FarmDetailPage } from "@/modules/farms/pages/FarmDetailPage";
import { FarmEditPage } from "@/modules/farms/pages/FarmEditPage";
import { FarmMembersPage } from "@/modules/farms/pages/FarmMembersPage";
import { BlockCreatePage } from "@/modules/farms/pages/BlockCreatePage";
import { BlockAutoGridPage } from "@/modules/farms/pages/BlockAutoGridPage";
import { BlockDetailPage } from "@/modules/farms/pages/BlockDetailPage";
import { BlockEditPage } from "@/modules/farms/pages/BlockEditPage";

export function App(): ReactNode {
  return (
    <AuthProvider>
      <AuthSync />
      <PrefsProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            {/* The OIDC callback URL is handled internally by react-oidc-context;
                we just need a route that renders so the provider can finish the
                code exchange. AppShell is fine — onSigninCallback strips the
                query params right after. */}
            <Route
              element={
                <ProtectedRoute>
                  <AppShell />
                </ProtectedRoute>
              }
            >
              <Route path="/" element={<HomePage />} />
              <Route path="/me" element={<MePage />} />
              <Route path="/farms" element={<FarmListPage />} />
              <Route path="/farms/new" element={<FarmCreatePage />} />
              <Route path="/farms/:farmId" element={<FarmDetailPage />} />
              <Route path="/farms/:farmId/edit" element={<FarmEditPage />} />
              <Route path="/farms/:farmId/members" element={<FarmMembersPage />} />
              <Route path="/farms/:farmId/blocks/new" element={<BlockCreatePage />} />
              <Route path="/farms/:farmId/blocks/auto-grid" element={<BlockAutoGridPage />} />
              <Route path="/farms/:farmId/blocks/:blockId" element={<BlockDetailPage />} />
              <Route path="/farms/:farmId/blocks/:blockId/edit" element={<BlockEditPage />} />
              <Route path="/auth/callback" element={<Navigate to="/" replace />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </PrefsProvider>
    </AuthProvider>
  );
}
