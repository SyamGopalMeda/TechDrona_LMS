import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, problem, renderWithProviders } from "@/features/auth/test/mock-api";
import { validateEnquiry } from "../lib/enquiries";
import { EnquiryForm } from "./EnquiryForm";

// Typing-heavy dialog flows: allow for slow CI runners when the whole suite runs in parallel.
vi.setConfig({ testTimeout: 20000 });

let restore: (() => void) | undefined;
afterEach(() => restore?.());

async function fillValid(opts: { consent?: boolean; phone?: string } = {}) {
  await userEvent.type(screen.getByLabelText(/Your name/), "Priya Nair");
  await userEvent.type(screen.getByLabelText(/^Company/), "Acme Systems");
  await userEvent.type(screen.getByLabelText(/Work email/), "priya@acme.example");
  if (opts.phone) await userEvent.type(screen.getByLabelText(/Phone/), opts.phone);
  await userEvent.click(screen.getByLabelText(/How can we help/));
  await userEvent.paste("We want a Java and SQL programme for 40 new graduates in January.");
  if (opts.consent !== false) await userEvent.click(screen.getByRole("checkbox", { name: /I agree/ }));
}

describe("validateEnquiry", () => {
  const ok = { name: "Al", company: "Bo", email: "a@b.co", phone: "", message: "x".repeat(20), consent: true };
  it("accepts a valid enquiry with no phone", () => {
    expect(validateEnquiry(ok)).toEqual({});
  });
  it("rejects bad email, short phone, short message and missing consent", () => {
    const e = validateEnquiry({ ...ok, email: "nope", phone: "12", message: "hi", consent: false });
    expect(Object.keys(e).sort()).toEqual(["consent", "email", "message", "phone"]);
  });
});

describe("EnquiryForm (PUB-010, D8)", () => {
  it("shows an error summary and inline errors without calling the api", async () => {
    const api = mockApi({});
    restore = api.restore;
    renderWithProviders(<EnquiryForm />);
    await userEvent.click(screen.getByRole("button", { name: "Send enquiry" }));
    expect(await screen.findByText(/Please fix these 5 problems/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Your name/)).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByRole("checkbox", { name: /I agree/ })).toHaveAttribute("aria-invalid", "true");
    expect(api.calls).toHaveLength(0);
  });

  it("requires consent", async () => {
    const api = mockApi({});
    restore = api.restore;
    renderWithProviders(<EnquiryForm />);
    await fillValid({ consent: false });
    await userEvent.click(screen.getByRole("button", { name: "Send enquiry" }));
    expect(await screen.findByText(/Please fix this problem/)).toBeInTheDocument();
    expect(screen.getAllByText("Agree to be contacted about your enquiry.").length).toBeGreaterThan(0);
    expect(api.calls).toHaveLength(0);
  });

  it("posts the trimmed payload and shows the success state", async () => {
    const api = mockApi({ ["POST public/enquiries"]: { status: 202, body: { status: "received" } } });
    restore = api.restore;
    renderWithProviders(<EnquiryForm />);
    await fillValid({ phone: "+91 98765 43210" });
    await userEvent.click(screen.getByRole("button", { name: "Send enquiry" }));
    expect(await screen.findByText("Thank you, we have your enquiry")).toBeInTheDocument();
    expect(api.calls).toHaveLength(1);
    expect(api.calls[0]!.body).toEqual({
      name: "Priya Nair",
      company: "Acme Systems",
      email: "priya@acme.example",
      phone: "+91 98765 43210",
      message: "We want a Java and SQL programme for 40 new graduates in January.",
      consent: true,
    });
    expect(api.calls[0]!.headers["Idempotency-Key"] ?? api.calls[0]!.headers["idempotency-key"]).toBeTruthy();
  });

  it("maps api field errors and shows a rate-limit message", async () => {
    let n = 0;
    const api = mockApi({
      ["POST public/enquiries"]: () =>
        ++n === 1
          ? problem(422, "validation_failed", "Check the highlighted fields", { errors: [{ field: "email", message: "Use a company email address." }] })
          : { ...problem(429, "rate_limited", "Too many requests"), headers: { "retry-after": "120" } },
    });
    restore = api.restore;
    renderWithProviders(<EnquiryForm />);
    await fillValid();
    await userEvent.click(screen.getByRole("button", { name: "Send enquiry" }));
    expect((await screen.findAllByText("Use a company email address.")).length).toBeGreaterThan(0);
    await userEvent.click(screen.getByRole("button", { name: "Send enquiry" }));
    await waitFor(() => expect(screen.getByText("Too many enquiries from this connection")).toBeInTheDocument());
    expect(screen.getByText(/about 2 minutes/)).toBeInTheDocument();
  });
});
