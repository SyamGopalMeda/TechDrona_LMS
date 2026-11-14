import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api/errors";
import {
  Checkbox,
  Chip,
  ConfirmDialog,
  Dialog,
  EmptyState,
  FilterBar,
  KeyValueList,
  LoadingBlock,
  PageContainer,
  PageHeader,
  ProgressRing,
  STATUS_VOCABULARY,
  SectionHeader,
  Segmented,
  StatGrid,
  StatTile,
  StatusBadge,
  Table,
  TextArea,
  Textarea,
  statusLabel,
  statusTone,
  standaloneLinkClass,
} from "./index";

describe("status vocabulary (Phase 1.4: one colour per status everywhere)", () => {
  it("covers the admin, commerce, support and learner statuses that used local maps", () => {
    for (const s of ["under_review", "executed", "shadow", "retired", "paused", "halted", "partially_refunded", "in_progress", "spam", "pending_user", "pending_internal", "available", "grace"]) {
      expect(STATUS_VOCABULARY[s], s).toBeDefined();
    }
    expect(statusTone("available")).toBe("brand");
    expect(statusTone("in_review")).toBe(statusTone("under_review"));
    expect(statusTone("pending_payment")).toBe(statusTone("awaiting_payment"));
    expect(statusTone("something_new")).toBe("neutral");
    expect(statusLabel("partially_refunded")).toBe("Partially refunded");
    expect(statusLabel("awaiting.evaluator")).toBe("Awaiting evaluator");
  });

  it("keeps the vocabulary tone when only the label is overridden, and shows a dash for no status", () => {
    render(
      <>
        <StatusBadge status="grace" label="Payment due soon" />
        <StatusBadge status={null} />
      </>,
    );
    expect(screen.getByText("Payment due soon").className).toContain("bg-warning-subtle");
    expect(screen.getByText("—")).toHaveClass("text-fg-muted");
  });
});

describe("LoadingBlock (one loading pattern)", () => {
  it("accepts rows and a size and stays one polite status", () => {
    const { container } = render(<LoadingBlock label="Loading tests…" rows={2} size="card" />);
    const status = screen.getByRole("status");
    expect(status).toHaveAttribute("aria-busy", "true");
    expect(status).toHaveTextContent("Loading tests…");
    expect(container.querySelectorAll(".h-16")).toHaveLength(2);
  });
});

describe("EmptyState", () => {
  it("has an inline variant without the dashed box and named topic icons", () => {
    const { container, rerender } = render(<EmptyState title="No results" variant="inline" icon="search" />);
    expect(container.firstElementChild).not.toHaveClass("border-dashed");
    expect(container.querySelector("svg path")?.getAttribute("d")).toMatch(/^M11 18/);
    rerender(<EmptyState title="No results" />);
    expect(container.firstElementChild).toHaveClass("border-dashed");
  });
});

describe("Table upgrades (Phase 1.10)", () => {
  type R = { id: string; name: string; note: string | null };
  const columns = [
    { key: "name", header: "Name", cell: (r: R) => r.name },
    { key: "note", header: "Note", cell: (r: R) => r.note ?? "—", priority: "secondary" as const },
  ];

  it("keeps the toolbar visible when the list is empty", () => {
    render(<Table caption="Users" columns={columns} rows={[]} rowKey={(r) => r.id} toolbar={<button type="button">Clear filters</button>} empty={{ title: "No matches" }} />);
    expect(screen.getByRole("button", { name: "Clear filters" })).toBeInTheDocument();
    expect(screen.getByText("No matches")).toBeInTheDocument();
  });

  it("hides blank cells in the stacked phone layout and secondary columns at tablet widths", () => {
    render(<Table caption="Users" columns={columns} rows={[{ id: "1", name: "Asha", note: null }]} rowKey={(r) => r.id} />);
    const [name, note] = screen.getAllByRole("cell");
    expect(name).not.toHaveClass("max-sm:hidden");
    expect(note).toHaveClass("max-sm:hidden", "sm:max-lg:hidden");
    expect(screen.getByRole("columnheader", { name: "Note" })).toHaveClass("sm:max-lg:hidden");
  });

  it("shows a visible title outside the table without duplicating the accessible name, and supports a sticky header", () => {
    const { container } = render(<Table caption="Orders" showCaption stickyHeader columns={columns} rows={[{ id: "1", name: "A", note: "x" }]} rowKey={(r) => r.id} />);
    expect(screen.getByRole("table", { name: "Orders" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Orders" })).toHaveClass("overflow-y-auto");
    expect(container.querySelector("thead")).toHaveClass("sticky");
    expect(container.querySelector("caption")).toHaveClass("sr-only");
  });
});

describe("Dialog upgrades", () => {
  it("has a labelled close button that comes after the content, and sizes", async () => {
    const onClose = vi.fn();
    render(
      <Dialog open onClose={onClose} title="Edit" size="lg">
        <input aria-label="Name" />
      </Dialog>,
    );
    const dialog = screen.getByRole("dialog", { hidden: true });
    expect(dialog.className).toContain("sm:max-w-2xl");
    const close = within(dialog).getByRole("button", { name: "Close dialog", hidden: true });
    const input = within(dialog).getByRole("textbox", { name: "Name", hidden: true });
    expect(input.compareDocumentPosition(close) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    await userEvent.click(close);
    expect(onClose).toHaveBeenCalled();
  });

  it("hides the close button while not dismissible and lets a legacy max-w class win over size", () => {
    render(<Dialog open onClose={() => {}} title="Busy" dismissible={false} className="max-w-3xl" />);
    const dialog = screen.getByRole("dialog", { hidden: true });
    expect(within(dialog).queryByRole("button", { name: "Close dialog", hidden: true })).toBeNull();
    expect(dialog.className).not.toContain("sm:max-w-lg");
  });
});

describe("ConfirmDialog (kit)", () => {
  function Harness({ onConfirm }: { onConfirm: () => Promise<void> }) {
    const [open, setOpen] = useState(true);
    return (
      <>
        <p>{open ? "open" : "closed"}</p>
        <ConfirmDialog open={open} onClose={() => setOpen(false)} title="Delete batch?" confirmLabel="Delete batch" danger onConfirm={onConfirm} />
      </>
    );
  }

  it("closes after the action succeeds", async () => {
    const onConfirm = vi.fn(async () => undefined);
    render(<Harness onConfirm={onConfirm} />);
    await userEvent.click(screen.getByRole("button", { name: "Delete batch", hidden: true }));
    await waitFor(() => expect(screen.getByText("closed")).toBeInTheDocument());
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("shows the problem inline and stays open when the action fails", async () => {
    const err = new ApiError(409, { type: "x", title: "Batch has students", status: 409, detail: "Move them first.", code: "conflict", request_id: "R-1" }, "R-1");
    render(
      <Harness
        onConfirm={async () => {
          throw err;
        }}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Delete batch", hidden: true }));
    expect(await screen.findByText("Batch has students")).toBeInTheDocument();
    expect(screen.getByText("open")).toBeInTheDocument();
    expect(screen.getByText("R-1")).toBeInTheDocument();
  });
});

describe("StatTile and StatGrid", () => {
  it("links the whole tile, colours the status dot by tone, and lays out 2 per row on phones", () => {
    const { container } = render(
      <StatGrid columns={3}>
        <StatTile label="Pending approvals" value={4} href="/admin/approvals" tone="warning" size="compact" />
      </StatGrid>,
    );
    expect(container.firstElementChild).toHaveClass("grid-cols-2", "lg:grid-cols-3");
    const link = screen.getByRole("link", { name: /Pending approvals/ });
    expect(link).toHaveAttribute("href", "/admin/approvals");
    expect(link.querySelector(".bg-warning-solid")).not.toBeNull();
    expect(screen.getByText("4")).toHaveClass("text-xl");
  });
});

describe("PageHeader, SectionHeader and layout", () => {
  it("renders breadcrumbs with the current page, meta beside the h1 and a back link", () => {
    render(<PageHeader title="Batch A" breadcrumbs={[{ label: "Batches", href: "/admin/batches" }, { label: "Batch A" }]} back={{ href: "/admin/batches", label: "All batches" }} meta={<StatusBadge status="active" />} />);
    const trail = screen.getByRole("navigation", { name: "Breadcrumb" });
    expect(within(trail).getByRole("link", { name: "Batches" })).toHaveAttribute("href", "/admin/batches");
    expect(within(trail).getByText("Batch A")).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("heading", { level: 1, name: "Batch A" })).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /All batches/ })).toBeInTheDocument();
  });

  it("keeps the phone title no larger than the desktop one (audit F1)", () => {
    render(<PageHeader title="Certificates & documents" />);
    const h1 = screen.getByRole("heading", { level: 1 });
    expect(h1).toHaveClass("text-[1.5rem]", "leading-8", "sm:text-[1.75rem]", "sm:leading-9");
    expect(h1).not.toHaveClass("text-2xl");
  });

  it("gives checkboxes and option-card radios a 24px box on touch screens (audit F4)", () => {
    render(
      <>
        <Checkbox label="Keep me signed in" />
        <Segmented legend="When" name="when" value="a" onChange={() => undefined} options={[{ value: "a", label: "Now" }, { value: "b", label: "Later" }]} />
      </>,
    );
    expect(screen.getByRole("checkbox", { name: "Keep me signed in" })).toHaveClass("h-5", "w-5", "[@media(pointer:coarse)]:h-6", "[@media(pointer:coarse)]:w-6");
    expect(screen.getByRole("radio", { name: "Now" })).toHaveClass("h-4", "w-4", "[@media(pointer:coarse)]:h-6", "[@media(pointer:coarse)]:w-6");
  });

  it("exports a standalone-link class with a 24px minimum height (audit F3)", () => {
    expect(standaloneLinkClass.split(" ")).toEqual(expect.arrayContaining(["inline-flex", "min-h-6", "items-center"]));
  });

  it("gives a 20px section heading level and named page widths", () => {
    const { container } = render(
      <PageContainer width="prose">
        <SectionHeader title="Upcoming" />
      </PageContainer>,
    );
    expect(container.firstElementChild).toHaveClass("max-w-prose");
    expect(screen.getByRole("heading", { level: 2, name: "Upcoming" })).toHaveClass("text-lg");
  });

  it("KeyValueList shows an em dash for missing values", () => {
    render(<KeyValueList items={[{ label: "Email", value: "a@b.c" }, { label: "Phone", value: null }]} />);
    expect(screen.getByText("Phone").nextElementSibling).toHaveTextContent("—");
  });
});

describe("controls", () => {
  it("FilterBar is a named search landmark that never navigates", async () => {
    const onSubmit = vi.fn();
    render(
      <FilterBar label="Order filters" onSubmit={onSubmit}>
        <input aria-label="Search" />
        <button type="submit">Apply</button>
      </FilterBar>,
    );
    expect(screen.getByRole("search", { name: "Order filters" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(onSubmit).toHaveBeenCalled();
  });

  it("Segmented pills are a radio group", async () => {
    function S() {
      const [v, setV] = useState<"list" | "grid">("list");
      return <Segmented legend="View" hideLegend name="view" value={v} onChange={setV} variant="pills" options={[{ value: "list", label: "List" }, { value: "grid", label: "Grid" }]} />;
    }
    render(<S />);
    expect(screen.getByRole("group", { name: "View" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("radio", { name: "Grid" }));
    expect(screen.getByRole("radio", { name: "Grid" })).toBeChecked();
  });

  it("Chip is a toggle button with a 44px touch target", async () => {
    const onClick = vi.fn();
    render(
      <Chip active={false} onClick={onClick} count={3}>
        MCQ
      </Chip>,
    );
    const chip = screen.getByRole("button", { name: /MCQ/ });
    expect(chip).toHaveAttribute("aria-pressed", "false");
    expect(chip).toHaveClass("min-h-touch");
    await userEvent.click(chip);
    expect(onClick).toHaveBeenCalled();
  });

  it("ProgressRing reports its value; TextArea is the kit Textarea", () => {
    render(<ProgressRing value={33.3} label="Path progress" />);
    expect(screen.getByRole("progressbar", { name: "Path progress" })).toHaveAttribute("aria-valuenow", "33");
    expect(TextArea).toBe(Textarea);
  });
});
