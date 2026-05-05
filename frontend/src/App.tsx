import type { ReactNode } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { AuthCallback } from "@/auth/AuthCallback";
import { AuthProvider } from "@/auth/AuthProvider";
import { AuthSync } from "@/auth/AuthSync";
import { ProtectedRoute } from "@/auth/ProtectedRoute";
import { ConfigProvider } from "@/config/ConfigContext";
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
        <ConfigProvider>
          <BrowserRouter>
            <Routes>
              <Route path="/login" element={<LoginPage />} />
              {/* /auth/callback MUST live outside ProtectedRoute. The
                  user lands here unauthenticated (with `?code=...` in
                  the URL); react-oidc-context exchanges the code for
                  tokens asynchronously. If ProtectedRoute saw the
                  unauth-yet state and bounced to /login, /login would
                  signinRedirect to Keycloak, Keycloak would round-trip
                  back to /auth/callback — a redirect loop. */}
              <Route path="/auth/callback" element={<AuthCallback />} />
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
                <Route path="*" element={<Navigate to="/" replace />} />
              </Route>
            </Routes>
          </BrowserRouter>
        </ConfigProvider>
      </PrefsProvider>
    </AuthProvider>
  );
}
