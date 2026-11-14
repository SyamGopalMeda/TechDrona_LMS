import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PublicShell } from "@/components/shell/PublicShell";
import { mockApi, renderWithProviders } from "@/features/auth/test/mock-api";
import type { TaxonomyNode } from "@/features/practice/lib/types";
import { HELP_ARTICLES, findHelpArticle } from "../content/help";
import { LEGAL_DOCS } from "../content/legal";
import { CompaniesIndex, CompanyHub } from "./CompanyHubs";
import { ContentDocView } from "./ContentDoc";
import { FreeResourceList } from "./FreeResources";
import { HelpCentre } from "./HelpCentre";
import { MyDeviceLimits } from "./MyDeviceLimits";
import { PlacementHub, PlacementTopic, findTopic } from "./PlacementHub";
import { ServiceStatus, coreStatusFrom } from "./ServiceStatus";

let restore: (() => void) | undefined;
afterEach(() => restore?.());

describe("Legal pages (FE-01 / FE-02, PUB-018)", () => {
  it.each(Object.values(LEGAL_DOCS))("$title renders structured sections with the draft banner", (doc) => {
    render(<ContentDocView doc={doc} kind="policy" />);
    expect(screen.getByRole("heading", { level: 1, name: doc.title })).toBeInTheDocument();
    expect(screen.getByText("Draft — pending legal review")).toBeInTheDocument();
    expect(screen.getByText(/Effective date: not set yet/)).toBeInTheDocument();
    for (const s of doc.sections) expect(screen.getByRole("heading", { level: 2, name: s.heading })).toBeInTheDocument();
    expect(screen.queryByText("Not yet implemented")).not.toBeInTheDocument();
  });

  it("privacy notice lists data, retention and rights from privacy-and-data-retention", () => {
    render(<ContentDocView doc={LEGAL_DOCS.privacy} kind="policy" />);
    expect(screen.getByRole("table", { name: /Data we collect/ })).toBeInTheDocument();
    expect(screen.getByRole("rowheader", { name: /Sign-in and access logs/ })).toBeInTheDocument();
    expect(screen.getByRole("table", { name: /Your rights/ })).toBeInTheDocument();
  });

  it("device policy publishes the sitemap numbers (3 · 2 · 1 · 2/30 d)", () => {
    render(<ContentDocView doc={LEGAL_DOCS["device-policy"]} kind="policy" />);
    const table = screen.getByRole("table", { name: /Default limits/ });
    expect(within(table).getByRole("row", { name: /Trusted \(registered\) devices 3/ })).toBeInTheDocument();
    expect(within(table).getByRole("row", { name: /Signed-in sessions at the same time 2/ })).toBeInTheDocument();
    expect(within(table).getByRole("row", { name: /Videos playing at the same time 1/ })).toBeInTheDocument();
    expect(within(table).getByRole("row", { name: /2 per 30 days/ })).toBeInTheDocument();
  });

  it("refund policy states the one rule, including discounted purchases", () => {
    render(<ContentDocView doc={LEGAL_DOCS["refund-policy"]} kind="policy" />);
    expect(screen.getByText(/within 7 days of purchase if less than 20% .* This includes discounted purchases\./)).toBeInTheDocument();
  });

  it("shows the signed-in learner's own limits from me/device-policy", () => {
    render(
      <MyDeviceLimits
        policy={{ devices: { max_trusted: 4, max_replacements_per_30d: 2, trusted_inactivity_expiry_days: 90 }, sessions: { max_concurrent: 2 }, streams: { max_concurrent: 1 } }}
      />,
    );
    expect(screen.getByText("Trusted devices").nextSibling).toHaveTextContent("4");
  });
});

describe("Help centre (FE-01 / FE-14, PUB-019)", () => {
  it("links every article and the grievance officer page", () => {
    render(<HelpCentre signedIn={false} />);
    for (const a of HELP_ARTICLES) expect(screen.getAllByRole("link", { name: a.title })[0]).toHaveAttribute("href", `/help/${a.slug}`);
    for (const l of screen.getAllByRole("link", { name: "Grievance officer and complaints" })) expect(l).toHaveAttribute("href", "/help/grievance");
    expect(screen.getByRole("link", { name: "Log in to open a ticket" })).toHaveAttribute("href", "/login?next=%2Fapp%2Fsupport%2Fnew");
  });

  it("offers a ticket directly when signed in", () => {
    render(<HelpCentre signedIn />);
    expect(screen.getByRole("link", { name: "Open a ticket" })).toHaveAttribute("href", "/app/support/new");
  });

  it("the grievance article is honest about the unnamed officer and gives the timelines", () => {
    const doc = findHelpArticle("grievance")!;
    render(<ContentDocView doc={doc} kind="article" />);
    expect(screen.getByText(/will be published on this page after legal review/)).toBeInTheDocument();
    expect(screen.getByText("We acknowledge a grievance within 48 hours.")).toBeInTheDocument();
    expect(findHelpArticle("does-not-exist")).toBeNull();
  });
});

describe("PublicShell (website header/footer)", () => {
  const SITE = "https://35-244-50-26.sslip.io";

  it("mirrors the website header: website sections (absolute), Login and an in-LMS Contact us pill; no LMS marketing nav", () => {
    render(<PublicShell>body</PublicShell>);
    const header = screen.getByRole("banner");
    const main = within(header).getByRole("navigation", { name: "Main" });
    for (const [name, href] of [
      ["Home", `${SITE}/`],
      ["Solutions", `${SITE}/solutions`],
      ["Training & Careers", `${SITE}/training`],
      ["Courses", `${SITE}/courses`],
      ["Projects", `${SITE}/projects`],
      ["About", `${SITE}/about`],
    ] as const) {
      expect(within(main).getByRole("link", { name })).toHaveAttribute("href", href);
    }
    expect(within(header).getByRole("link", { name: "Login" })).toHaveAttribute("href", "/login");
    // Contact and the logo stay in the LMS (help centre contact section, LMS home).
    expect(within(header).getByRole("link", { name: /Contact/ })).toHaveAttribute("href", "/help#help-contact");
    expect(within(header).getByRole("link", { name: "Tech Drona LMS home" })).toHaveAttribute("href", "/");
    for (const gone of ["Placement prep", "Companies", "Pricing", "For teams", "Sign up"]) {
      expect(within(header).queryByRole("link", { name: gone })).not.toBeInTheDocument();
    }
  });

  it("has the website footer columns plus the LMS support and policy links", () => {
    render(<PublicShell>body</PublicShell>);
    const footer = screen.getByRole("contentinfo");
    expect(within(footer).getByRole("link", { name: "All courses" })).toHaveAttribute("href", `${SITE}/courses`);
    expect(within(footer).getByRole("link", { name: "About us" })).toHaveAttribute("href", `${SITE}/about`);
    expect(within(footer).getByRole("link", { name: "Contact" })).toHaveAttribute("href", "/help#help-contact");
    for (const [name, href] of [
      ["Help", "/help"],
      ["Grievance officer", "/help/grievance"],
      ["Certificate verification", "/verify"],
      ["Terms", "/legal/terms"],
      ["Privacy", "/legal/privacy"],
      ["Refund policy", "/legal/refund-policy"],
      ["Device policy", "/legal/device-policy"],
    ] as const) {
      expect(within(footer).getByRole("link", { name })).toHaveAttribute("href", href);
    }
    for (const gone of ["Placement", "Companies", "Pricing", "Corporate enquiries", "Status"]) {
      expect(within(footer).queryByRole("link", { name: gone })).not.toBeInTheDocument();
    }
  });

  it("shows Go to dashboard instead of Login when signed in", () => {
    render(<PublicShell signedIn>body</PublicShell>);
    const header = screen.getByRole("banner");
    expect(within(header).getByRole("link", { name: "Go to dashboard" })).toHaveAttribute("href", "/app");
    expect(within(header).queryByRole("link", { name: "Login" })).not.toBeInTheDocument();
    // Signed in, Courses opens the in-app catalogue (header and footer) instead of the website.
    expect(within(within(header).getByRole("navigation", { name: "Main" })).getByRole("link", { name: "Courses" })).toHaveAttribute("href", "/app/courses");
    expect(within(screen.getByRole("contentinfo")).getByRole("link", { name: "All courses" })).toHaveAttribute("href", "/app/courses");
  });

  it("opens the website-style slide-in menu (dialog) and closes it on Escape and on a link", async () => {
    render(<PublicShell>body</PublicShell>);
    const header = screen.getByRole("banner");
    const menu = within(header).getByRole("button", { name: "Menu" });
    expect(menu).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(menu);
    expect(menu).toHaveAttribute("aria-expanded", "true");
    const dialog = screen.getByRole("dialog", { name: "Menu" });
    for (const name of ["Home", "Solutions", "Training & Careers", "Courses", "Projects", "About"]) {
      expect(within(dialog).getByRole("link", { name })).toBeInTheDocument();
    }
    expect(within(dialog).getByRole("link", { name: /Log in to Tech Drona/ })).toHaveAttribute("href", "/login");
    expect(within(dialog).getByRole("link", { name: /Contact us/ })).toHaveAttribute("href", "/help#help-contact");
    await userEvent.keyboard("{Escape}");
    expect(menu).toHaveAttribute("aria-expanded", "false");
    expect(menu).toHaveFocus();
    await userEvent.click(menu);
    const stop = (e: MouseEvent) => e.preventDefault();
    window.addEventListener("click", stop);
    await userEvent.click(within(screen.getByRole("dialog", { name: "Menu" })).getByRole("link", { name: "Projects" }));
    window.removeEventListener("click", stop);
    expect(menu).toHaveAttribute("aria-expanded", "false");
  });

  it("opens a website dropdown from its arrow button", async () => {
    render(<PublicShell>body</PublicShell>);
    const btn = screen.getByRole("button", { name: "Show Solutions menu" });
    await userEvent.click(btn);
    const open = screen.getByRole("button", { name: "Hide Solutions menu" });
    expect(open).toHaveAttribute("aria-expanded", "true");
    expect(within(document.getElementById(open.getAttribute("aria-controls")!)!).getByRole("link", { name: /Applied AI/ })).toHaveAttribute("href", "https://35-244-50-26.sslip.io/solutions#ai");
  });
});

describe("Status (PUB-020)", () => {
  it("maps health/ready to operational / disruption and never claims judge, video or payments are up", () => {
    const ok = coreStatusFrom({ ok: true, data: { status: "ok", checks: { database: "ok", redis_cache: "ok" }, release: "r1" } });
    const { unmount } = render(<ServiceStatus core={ok} checkedAt="3 Nov 2026, 10:15 IST" />);
    expect(screen.getByText("Operational")).toBeInTheDocument();
    expect(screen.getByText("Database: OK")).toBeInTheDocument();
    expect(screen.getByText(/not monitored on this page yet/)).toBeInTheDocument();
    unmount();
    render(<ServiceStatus core={coreStatusFrom({ ok: false, status: 503 })} checkedAt="now" />);
    expect(screen.getByText("Disruption")).toBeInTheDocument();
  });
});

const tree: TaxonomyNode[] = [
  {
    id: "s1",
    parent_id: null,
    kind: "subject",
    slug: "quant",
    name: "Quantitative aptitude",
    path: "quant",
    depth: 0,
    position: 0,
    is_active: true,
    question_count: 12,
    children: [
      {
        id: "t1",
        parent_id: "s1",
        kind: "topic",
        slug: "percentages",
        name: "Percentages",
        path: "quant/percentages",
        depth: 1,
        position: 0,
        is_active: true,
        question_count: 7,
        children: [{ id: "u1", parent_id: "t1", kind: "subtopic", slug: "successive", name: "Successive change", path: "quant/percentages/successive", depth: 2, position: 0, is_active: true, question_count: 3, children: [] }],
      },
    ],
  },
];

describe("Placement hub and topic (PUB-004/005)", () => {
  it("lists subjects with counts and links topics by slug", () => {
    render(<PlacementHub subjects={tree} signedIn={false} />);
    expect(screen.getByRole("heading", { name: "Quantitative aptitude" })).toBeInTheDocument();
    expect(screen.getByText("12 questions")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Percentages" })).toHaveAttribute("href", "/placement/quant/percentages");
    expect(screen.getByRole("link", { name: "Sign up to practise" })).toHaveAttribute("href", "/signup?next=%2Fapp%2Fpractice");
  });

  it("resolves nested topics and gates practice behind sign-in with next", () => {
    expect(findTopic(tree, "quant", "successive")?.topic.name).toBe("Successive change");
    expect(findTopic(tree, "quant", "nope")).toBeNull();
    const found = findTopic(tree, "quant", "percentages")!;
    render(<PlacementTopic subject={found.subject} topic={found.topic} signedIn={false} />);
    expect(screen.getByRole("heading", { level: 1, name: "Percentages" })).toBeInTheDocument();
    expect(screen.getByText(/Successive change/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Create a free account" })).toHaveAttribute("href", "/signup?next=%2Fapp%2Fpractice%2Fquant");
  });
});

describe("Companies (PUB-006/007) — honest state, no invented data", () => {
  it("explains hubs are not published and links to what exists", () => {
    render(<CompaniesIndex />);
    expect(screen.getByText("Company guides are coming soon")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "Companies" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Placement topics" })).toHaveAttribute("href", "/placement");
  });

  it("sends a signed-in learner to the in-app company path", () => {
    render(<CompanyHub slug="tcs-nqt" signedIn />);
    expect(screen.getByRole("link", { name: "Open in the app" })).toHaveAttribute("href", "/app/companies/tcs-nqt");
  });
});

describe("Free resources (PUB-009)", () => {
  const resources = [
    { id: "r1", title: "Aptitude cheat sheet", resource_type: "pdf", course_slug: null, download_url: "/api/v1/media/downloads", url: null },
    { id: "r2", title: "External guide", resource_type: "link", course_slug: null, download_url: null, url: "https://example.org/guide" },
  ];

  it("gates file downloads behind sign-in for visitors", () => {
    render(<FreeResourceList resources={resources} signedIn={false} />);
    expect(screen.getByRole("link", { name: /Log in to download Aptitude cheat sheet/ })).toHaveAttribute("href", "/login?next=%2Ffree-resources");
    expect(screen.getByRole("link", { name: /Open External guide/ })).toHaveAttribute("href", "https://example.org/guide");
  });

  it("downloads through media/downloads when signed in", async () => {
    const api = mockApi({ "POST media/downloads": { body: { url: "https://cdn.example/x.pdf" } } });
    restore = api.restore;
    const open = vi.spyOn(window, "open").mockReturnValue(null);
    renderWithProviders(<FreeResourceList resources={resources} signedIn />);
    await userEvent.click(screen.getByRole("button", { name: "Download Aptitude cheat sheet" }));
    await waitFor(() => expect(open).toHaveBeenCalledWith("https://cdn.example/x.pdf", "_blank", "noopener,noreferrer"));
    expect(api.calls[0]!.body).toEqual({ resource_id: "r1" });
    open.mockRestore();
  });
});
