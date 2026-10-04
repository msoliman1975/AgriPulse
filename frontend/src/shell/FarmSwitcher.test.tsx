import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { FarmSwitcher } from "./FarmSwitcher";

const mockUseAuth = vi.fn();
vi.mock("react-oidc-context", () => ({
  useAuth: () => mockUseAuth(),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: "en" } }),
}));

const listFarms = vi.fn();
vi.mock("@/api/farms", () => ({
  listFarms: (...args: unknown[]) => listFarms(...args),
}));

function jwt(payload: object): string {
  const b64 = (s: string) => btoa(s).replace(/=+$/g, "").replace(/\+/g, "-").replace(/\//g, "_");
  return `${b64("{}")}.${b64(JSON.stringify(payload))}.sig`;
}

function renderSwitcher(): ReturnType<typeof render> {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <FarmSwitcher />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  listFarms.mockReset();
  listFarms.mockResolvedValue({ items: [], next_cursor: null });
});

describe("<FarmSwitcher> without a tenant", () => {
  it("renders nothing and never lists farms for a platform admin with no tenant", () => {
    mockUseAuth.mockReturnValue({
      user: { access_token: jwt({ platform_role: "PlatformAdmin" }) },
    });
    const { container } = renderSwitcher();
    expect(container).toBeEmptyDOMElement();
    expect(listFarms).not.toHaveBeenCalled();
  });

  it("lists farms when the token names a tenant", () => {
    mockUseAuth.mockReturnValue({
      user: { access_token: jwt({ tenant_id: "t-1", tenant_role: "TenantOwner" }) },
    });
    renderSwitcher();
    expect(listFarms).toHaveBeenCalledTimes(1);
  });
});
