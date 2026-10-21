import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { setupTestI18n } from "@/i18n/testing";
import type { FarmMember } from "@/api/farmMembers";
import { MembersList } from "./MembersList";

vi.mock("@/rbac/useCapability", () => ({
  useCapability: () => true,
}));

vi.mock("@/queries/users", () => ({
  useTenantUsers: () => ({
    data: [
      {
        membership_id: "dac59e9d-0000-0000-0000-000000000001",
        full_name: "Sara Hassan",
        email: "sara@example.com",
        identity_kind: "email",
      },
      {
        membership_id: "f54428de-0000-0000-0000-000000000002",
        full_name: null,
        email: "+201002203402@scouts.agripulse.cloud",
        phone: "+201002203402",
        identity_kind: "phone",
      },
    ],
    isLoading: false,
    isError: false,
  }),
}));

const members: FarmMember[] = [
  {
    id: "s1",
    membership_id: "dac59e9d-0000-0000-0000-000000000001",
    farm_id: "f1",
    role: "FarmManager",
    granted_at: "2026-08-26T00:00:00Z",
    revoked_at: null,
  },
  {
    id: "s2",
    membership_id: "f54428de-0000-0000-0000-000000000002",
    farm_id: "f1",
    role: "Scout",
    granted_at: "2026-08-27T00:00:00Z",
    revoked_at: null,
  },
  {
    id: "s3",
    membership_id: "99999999-0000-0000-0000-000000000003",
    farm_id: "f1",
    role: "Viewer",
    granted_at: "2026-08-27T00:00:00Z",
    revoked_at: null,
  },
];

describe("MembersList", () => {
  it("names each member instead of printing their membership id", async () => {
    await setupTestI18n("en");
    render(<MembersList members={members} canRevoke={false} />);

    expect(screen.getByText("Sara Hassan")).toBeInTheDocument();
    // A scout's email is synthesised from their phone, so the phone is the
    // only handle worth showing.
    expect(screen.getByText("+201002203402")).toBeInTheDocument();
    expect(screen.queryByText(/scouts\.agripulse\.cloud/)).toBeNull();
    expect(screen.queryByText("dac59e9d…")).toBeNull();
  });

  it("falls back to a short id for a membership the user list does not cover", async () => {
    await setupTestI18n("en");
    render(<MembersList members={members} canRevoke={false} />);

    expect(screen.getByText("99999999…")).toBeInTheDocument();
  });
});
