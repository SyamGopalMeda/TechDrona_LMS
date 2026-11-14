import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const replace = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));

import { ContinueRedirect } from "./ContinueRedirect";
import { recordLastPage } from "./last-page";

afterEach(() => {
  window.localStorage.clear();
  replace.mockReset();
});

describe("/continue", () => {
  it("opens the remembered page of the requested module", () => {
    recordLastPage("/admin/batches?tab=open");
    render(<ContinueRedirect area="lms" portals={["/admin", "/app"]} fallback="/admin" />);
    expect(screen.getByText("Opening your last page…", { selector: "p" })).toBeInTheDocument();
    expect(replace).toHaveBeenCalledWith("/admin/batches?tab=open");
  });

  it("falls back when nothing is remembered for that module", () => {
    recordLastPage("/admin/college-data");
    render(<ContinueRedirect area="lms" portals={["/admin", "/app"]} fallback="/modules" />);
    expect(replace).toHaveBeenCalledWith("/modules");
  });
});
