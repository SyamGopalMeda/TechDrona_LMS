import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SignupForm, SignupResult } from "./SignupForm";
import { LoginForm } from "./LoginForm";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() }) }));

describe("Signup keeps ?next= (FE-10)", () => {
  it("result screen continues to the next path", () => {
    render(<SignupResult result={{ next_steps: ["verify_email"] } as never} email="a@example.com" next="/courses/dsa" />);
    expect(screen.getByRole("link", { name: "Continue" })).toHaveAttribute("href", "/courses/dsa");
  });

  it("falls back to the dashboard without next", () => {
    render(<SignupResult result={{ next_steps: ["verify_email"] } as never} />);
    expect(screen.getByRole("link", { name: "Go to my dashboard" })).toHaveAttribute("href", "/app");
  });

  it("the sign-in links keep next in both directions", () => {
    const { unmount } = render(<SignupForm next="/app/checkout/new?price_id=p1" />);
    expect(screen.getByRole("link", { name: "Sign in" })).toHaveAttribute("href", `/login?next=${encodeURIComponent("/app/checkout/new?price_id=p1")}`);
    unmount();
    render(<LoginForm next="/courses/dsa" />);
    expect(screen.getByRole("link", { name: "Create an account" })).toHaveAttribute("href", "/signup?next=%2Fcourses%2Fdsa");
  });
});

describe("Signup result focus (FE-22)", () => {
  it("moves focus to the result heading", () => {
    render(<SignupResult result={{ next_steps: ["verify_email"] } as never} />);
    expect(screen.getByRole("heading", { name: "Check your inbox" })).toHaveFocus();
  });
});
