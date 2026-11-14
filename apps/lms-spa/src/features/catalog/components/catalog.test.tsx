import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, problem, renderWithProviders } from "@/features/auth/test/mock-api";
import { formatDate, formatDateTime, formatMoney, languageName } from "../lib/format";
import { accessOptionsForCourse } from "../lib/products";
import type { ProductDto } from "../lib/types";
import { CertificateVerification } from "./CertificateVerification";
import { CourseAccess } from "./CourseAccess";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push, replace: vi.fn() }) }));

let restore: (() => void) | undefined;
afterEach(() => {
  restore?.();
  push.mockReset();
});

const free = { id: "c1", slug: "dsa-foundations", title: "DSA Foundations", price_type: "free" as const, refund_rule: null, access_options: [] };

describe("format", () => {
  it("formats paise in Indian rupees and dates in IST", () => {
    expect(formatMoney(149900)).toBe("₹1,499");
    expect(formatMoney(12345678)).toBe("₹1,23,456.78");
    expect(formatMoney(null)).toBe("—");
    expect(formatDate("2026-11-03T20:00:00.000Z")).toBe("4 Nov 2026");
    expect(formatDateTime("2026-11-03T04:45:00.000Z")).toBe("3 Nov 2026, 10:15 IST");
    expect(formatDate("2026-10-28")).toBe("28 Oct 2026");
  });
});

describe("CourseAccess (PUB-003)", () => {
  it("enrols a signed-in learner in a free course and opens the course overview", async () => {
    const api = mockApi({ "POST me/enrolments": { status: 201, body: { enrolment_id: "e1" } } });
    restore = api.restore;
    renderWithProviders(<CourseAccess course={free} signedIn />);
    await userEvent.click(screen.getByRole("button", { name: "Enrol for free" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/app/courses/dsa-foundations"));
    const call = api.calls.find((c) => c.method === "POST")!;
    expect(call.body).toEqual({ course_id: "c1" });
    expect(call.headers["idempotency-key"]).toBeTruthy();
    expect(call.headers["x-csrf-token"]).toBe("test-csrf-token");
  });

  it("asks a signed-out visitor to sign up, keeping the course as the next page", () => {
    render(<CourseAccess course={free} signedIn={false} />);
    expect(screen.getByRole("link", { name: "Sign up to enrol for free" })).toHaveAttribute("href", "/signup?next=%2Fcourses%2Fdsa-foundations");
    expect(screen.getByRole("link", { name: "Log in" })).toHaveAttribute("href", "/login?next=%2Fcourses%2Fdsa-foundations");
  });

  it("lists paid access options that link to checkout with the price", () => {
    render(
      <CourseAccess
        signedIn
        course={{ ...free, price_type: "paid", refund_rule: "Full refund within 7 days.", access_options: [{ sku: "C-DSA-180", price_id: "p1", name: "DSA path", total_paise: 149900, access_days: 180 }] }}
      />,
    );
    const link = screen.getByRole("link", { name: "Buy DSA path for ₹1,499" });
    expect(link.getAttribute("href")).toBe("/app/checkout/new?price_id=p1&return_to=%2Fapp%2Fcourses%2Fdsa-foundations");
    expect(screen.getByText(/180 days access/)).toBeInTheDocument();
    expect(screen.getByText("Full refund within 7 days.")).toBeInTheDocument();
  });

  it("shows the problem title and request id when enrolment is refused", async () => {
    const api = mockApi({ "POST me/enrolments": problem(403, "entitlement_required", "This course needs access", { reason_code: "NO_ENTITLEMENT" }) });
    restore = api.restore;
    renderWithProviders(<CourseAccess course={free} signedIn />);
    await userEvent.click(screen.getByRole("button", { name: "Enrol for free" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("This course needs access");
    expect(screen.getByText("req-123")).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
  });

  it("lets a signed-in learner with existing access start a paid course via LRN-03", async () => {
    const api = mockApi({ "POST me/enrolments": { status: 200, body: { id: "e1", course_id: "c1" } } });
    restore = api.restore;
    renderWithProviders(<CourseAccess course={{ ...free, price_type: "paid" }} signedIn />);
    await userEvent.click(screen.getByRole("button", { name: "Start learning" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/app/courses/dsa-foundations"));
  });
});

function price(price_id: string, amount_paise: number) {
  return { price_id, amount_paise, currency: "INR", tax_inclusive: true, is_recurring: true, valid_from: "2026-01-01T00:00:00+00:00", valid_until: null, is_active: true };
}

describe("accessOptionsForCourse", () => {
  it("derives a course's buy options from COM-01 products that unlock it", () => {
    const products: ProductDto[] = [
      { product_id: "p", sku: "C-DSA-180", name: "DSA path", product_kind: "course", unlocks: [{ item_type: "course", ref_id: "c1", feature_key: null, quantity: 1 }], plans: [{ plan_id: "pl", code: "180d", billing_type: "one_time", interval_unit: null, interval_count: null, access_duration_days: 180, prices: [price("p1", 149900)] }] },
      { product_id: "q", sku: "OTHER", name: "Other", product_kind: "course", unlocks: [{ item_type: "course", ref_id: "c2", feature_key: null, quantity: 1 }], plans: [] },
    ];
    expect(accessOptionsForCourse(products, "c1")).toEqual([{ sku: "C-DSA-180", price_id: "p1", name: "DSA path", product_kind: "course", total_paise: 149900, access_days: 180, interval: null }]);
  });
});

describe("languageName", () => {
  it("maps language codes to names for course meta", () => {
    expect(languageName("en")).toBe("English");
    expect(languageName("hi")).toBe("Hindi");
    expect(languageName(null)).toBeNull();
    expect(languageName("not a code!")).toBe("not a code!");
  });
});

describe("CertificateVerification (PUB-017)", () => {
  it("shows a valid certificate", () => {
    render(
      <CertificateVerification
        code="K7Q2M9XH4TPA"
        data={{ public_code: "K7Q2M9XH4TPA", status: "valid", name_on_certificate: "Ananya Reddy", course_title: "Data Structures for Placements", issued_at: "2026-10-28", identity_verified: true, issuer: "Tech Drona" }}
      />,
    );
    expect(screen.getByText("Valid certificate")).toBeInTheDocument();
    expect(screen.getByText("Ananya Reddy")).toBeInTheDocument();
    expect(screen.getByText("28 Oct 2026")).toBeInTheDocument();
    expect(screen.getByText("Identity verified")).toBeInTheDocument();
  });

  it("shows a revoked certificate with the date only", () => {
    render(<CertificateVerification code="K7Q2M9XH4TPA" data={{ status: "revoked", revoked_on: "2026-11-02" }} />);
    expect(screen.getByText("Revoked on 2 Nov 2026")).toBeInTheDocument();
    expect(screen.queryByText("Awarded to")).not.toBeInTheDocument();
  });

  it("gives one neutral message for unknown codes", () => {
    render(<CertificateVerification code="NOPE" data={null} />);
    expect(screen.getByText(/couldn.t verify this certificate/)).toBeInTheDocument();
  });
});
