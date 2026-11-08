import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SafeMarkdown } from "./SafeMarkdown";
import { PricingPlans } from "./PricingPlans";
import { VerifyCodeForm } from "./VerifyCodeForm";

describe("SafeMarkdown (FE-21)", () => {
  it("renders lists, bold and safe links instead of raw markdown", () => {
    const { container } = render(<SafeMarkdown source={"All **aptitude** courses.\n\n- Mock tests\n- [Syllabus](/courses)\n- [x](javascript:alert(1))"} />);
    expect(container.querySelector("strong")).toHaveTextContent("aptitude");
    expect(screen.getAllByRole("listitem")).toHaveLength(3);
    expect(screen.getByRole("link", { name: "Syllabus" })).toHaveAttribute("href", "/courses");
    expect(container.querySelector('a[href^="javascript"]')).toBeNull();
    expect(container.textContent).not.toContain("**");
  });

  it("never interprets HTML in the source", () => {
    const { container } = render(<SafeMarkdown source={'<img src=x onerror="alert(1)"> hi'} />);
    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toContain("<img");
  });

  it("is used by the pricing cards", () => {
    render(<PricingPlans signedIn={false} products={[{ product_id: "p", sku: "S", name: "Pro", product_kind: "subscription", description_md: "- **All** mocks", plans: [] }]} />);
    expect(screen.getByText("All").tagName).toBe("STRONG");
  });
});

describe("VerifyCodeForm (FE-13)", () => {
  it("is a GET form to /verify with a labelled code field", () => {
    const { container } = render(<VerifyCodeForm />);
    const form = container.querySelector("form")!;
    expect(form).toHaveAttribute("method", "get");
    expect(form).toHaveAttribute("action", "/verify");
    expect(screen.getByLabelText("Certificate code")).toHaveAttribute("name", "code");
  });

  it("shows an error for a malformed code", () => {
    render(<VerifyCodeForm initial="ABC" invalid />);
    expect(screen.getByRole("alert")).toHaveTextContent("10–16 letters and digits");
  });
});
