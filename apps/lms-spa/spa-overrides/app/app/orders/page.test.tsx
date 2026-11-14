import { describe, expect, it, vi } from "vitest";

const redirect = vi.fn();
vi.mock("next/navigation", () => ({ redirect: (to: string) => redirect(to) }));

import Page from "./page";

describe("/app/orders (live audit F-11)", () => {
  it("forwards the bare URL to Billing instead of rendering a blank page", () => {
    Page();
    expect(redirect).toHaveBeenCalledWith("/app/billing");
  });
});
