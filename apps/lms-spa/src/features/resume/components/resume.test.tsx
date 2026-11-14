import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, renderWithProviders } from "@/features/auth/test/mock-api";
import { StudentResume } from "./Resume";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));

let restore: (() => void) | undefined;
afterEach(() => restore?.());

const future = new Date(Date.now() + 2 * 86400_000).toISOString();

const resume = {
  id: "r1",
  template_key: "ats_classic",
  version_no: 1,
  content: { headline: "SDE intern", summary: "", education: [], skills: ["Python"], projects: [], internships: [], achievements: [], certifications: [] },
  checklist_score: 40,
  checklist: [{ key: "skills", label: "List at least 5 skills", done: false }],
  is_current: true,
  has_pdf: false,
  pdf_uploaded_at: null,
  created_at: future,
  updated_at: future,
};

describe("StudentResume (STU-014)", () => {
  it("saves the résumé with suggested certificates", async () => {
    const api = mockApi({
      "GET me/resumes": { body: { data: [resume], suggested_certifications: [{ title: "Python Basics", issuer: "Tech Drona" }] } },
      "PUT me/resumes/r1": ({ body }) => ({ body: { ...resume, ...(body as object), checklist_score: 55 } }),
    });
    restore = api.restore;
    renderWithProviders(<StudentResume />);
    expect(await screen.findByText("Checklist score 40/100")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/Skills/), { target: { value: "Python, SQL" } });
    fireEvent.click(screen.getByRole("button", { name: /Add my Tech Drona certificates/ }));
    fireEvent.click(screen.getByRole("button", { name: "Save résumé" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "PUT")).toBe(true));
    const put = api.calls.find((c) => c.method === "PUT")!.body as { content: { skills: string[]; certifications: { title: string }[] } };
    expect(put.content.skills).toEqual(["Python", "SQL"]);
    expect(put.content.certifications[0]!.title).toBe("Python Basics");
    expect((await screen.findAllByText("Checklist score 55/100", { exact: false })).length).toBeGreaterThan(0);
    // Mentor reviews were removed with the mentoring feature.
    expect(screen.queryByRole("button", { name: "Request mentor review" })).not.toBeInTheDocument();
  });

  it("offers to start a résumé when there is none", async () => {
    const api = mockApi({ "GET me/resumes": { body: { data: [], suggested_certifications: [] } } });
    restore = api.restore;
    renderWithProviders(<StudentResume />);
    fireEvent.click(await screen.findByRole("button", { name: "Start my résumé" }));
    expect(screen.getByRole("button", { name: "Save résumé" })).toBeInTheDocument();
  });
});
