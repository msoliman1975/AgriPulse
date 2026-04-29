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
              <Route path="/auth/callback" element={<Navigate to="/" replace />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </PrefsProvider>
    </AuthProvider>
  );
}
