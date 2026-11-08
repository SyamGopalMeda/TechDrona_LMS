import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api/errors";
import { useState } from "react";
import { Button, Dialog, ErrorState, FormField, Input, PageHeader, Pagination, StatTile, StatusBadge, Table, Tabs, ToastProvider, nextCursorStack, previousCursorStack, useToast } from "./index";

describe("FormField", () => {
  it("wires label, hint and error to the control", () => {
    render(
      <FormField label="Email" hint="We never share it" error="Enter a valid email" required>
        {(f) => <Input {...f} />}
      </FormField>,
    );
    const input = screen.getByLabelText(/Email/);
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAttribute("aria-required", "true");
    expect(input).toHaveAccessibleDescription("We never share it Enter a valid email");
    expect(screen.getByText("Enter a valid email")).toBeInTheDocument();
  });

  it("does not make each field error a live region (audit S7: one announcement per submit)", () => {
    render(
      <>
        <FormField label="A" error="Enter A">
          {(f) => <Input {...f} />}
        </FormField>
        <FormField label="B" error="Enter B">
          {(f) => <Input {...f} />}
        </FormField>
      </>,
    );
    expect(screen.queryAllByRole("alert")).toHaveLength(0);
    expect(screen.getByLabelText("B")).toHaveAccessibleDescription("Enter B");
  });
});

describe("Button", () => {
  it("stays focusable but ignores clicks while loading (audit S4)", async () => {
    const onClick = vi.fn();
    const onSubmit = vi.fn((e: { preventDefault: () => void }) => e.preventDefault());
    render(
      <form onSubmit={onSubmit}>
        <Button type="submit" loading onClick={onClick}>
          Save
        </Button>
      </form>,
    );
    const b = screen.getByRole("button", { name: "Save" });
    expect(b).not.toBeDisabled();
    expect(b).toHaveAttribute("aria-disabled", "true");
    expect(b).toHaveAttribute("aria-busy", "true");
    b.focus();
    await userEvent.click(b);
    expect(onClick).not.toHaveBeenCalled();
    expect(onSubmit).not.toHaveBeenCalled();
    expect(b).toHaveFocus();
  });

  it("is truly disabled when disabled", () => {
    render(<Button disabled>Save</Button>);
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  });
});

describe("Table", () => {
  const columns = [{ key: "name", header: "Name", cell: (r: { id: string; name: string }) => r.name }];

  it("renders loading, empty, error and data states", () => {
    const { rerender } = render(<Table caption="Users" columns={columns} rows={undefined} rowKey={(r) => r.id} loading />);
    expect(screen.getByText("Loading…")).toBeInTheDocument();

    rerender(<Table caption="Users" columns={columns} rows={[]} rowKey={(r) => r.id} empty={{ title: "No users yet" }} />);
    expect(screen.getByText("No users yet")).toBeInTheDocument();

    const err = new ApiError(503, { type: "x", title: "Service unavailable", status: 503, detail: "Try later", code: "service_unavailable", request_id: "REQ-42" }, "REQ-42");
    rerender(<Table caption="Users" columns={columns} rows={[]} rowKey={(r) => r.id} error={err} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Service unavailable");
    expect(screen.getByText("REQ-42")).toBeInTheDocument();

    rerender(<Table caption="Users" columns={columns} rows={[{ id: "1", name: "Asha" }]} rowKey={(r) => r.id} />);
    expect(screen.getByRole("table", { name: "Users" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "Asha" })).toBeInTheDocument();
  });
});

describe("ErrorState", () => {
  it("shows the request id and retries", async () => {
    const onRetry = vi.fn();
    render(<ErrorState title="Could not load" requestId="REQ-9" onRetry={onRetry} />);
    expect(screen.getByText("REQ-9")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(onRetry).toHaveBeenCalled();
  });
});

describe("Tabs", () => {
  it("supports arrow-key navigation with roving tabindex", async () => {
    render(
      <Tabs
        label="Sections"
        items={[
          { id: "a", label: "Alpha", content: "Panel A" },
          { id: "b", label: "Beta", content: "Panel B" },
          { id: "c", label: "Gamma", content: "Panel C", disabled: true },
        ]}
      />,
    );
    const alpha = screen.getByRole("tab", { name: "Alpha" });
    expect(alpha).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tabpanel")).toHaveTextContent("Panel A");
    alpha.focus();
    await userEvent.keyboard("{ArrowRight}");
    expect(screen.getByRole("tab", { name: "Beta" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "Beta" })).toHaveFocus();
    expect(screen.getByRole("tabpanel")).toHaveTextContent("Panel B");
    await userEvent.keyboard("{ArrowRight}"); // skips disabled, wraps
    expect(screen.getByRole("tab", { name: "Alpha" })).toHaveAttribute("aria-selected", "true");
  });
});

describe("Dialog", () => {
  it("renders an accessible modal and closes on Escape", async () => {
    const onClose = vi.fn();
    render(
      <Dialog open onClose={onClose} title="Confirm" description="Are you sure?">
        <button type="button">Inside</button>
      </Dialog>,
    );
    const dialog = screen.getByRole("dialog", { hidden: true });
    expect(dialog).toHaveAccessibleName("Confirm");
    expect(dialog).toHaveAccessibleDescription("Are you sure?");
    dialog.dispatchEvent(new Event("cancel", { cancelable: true }));
    expect(onClose).toHaveBeenCalled();
  });
});

describe("Toast", () => {
  function Trigger() {
    const t = useToast();
    return <button onClick={() => t.show({ tone: "danger", title: "Payment failed", requestId: "REQ-7" })}>go</button>;
  }
  it("announces errors with the reference", async () => {
    render(
      <ToastProvider>
        <Trigger />
      </ToastProvider>,
    );
    await userEvent.click(screen.getByRole("button", { name: "go" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Payment failed");
    expect(screen.getByRole("alert")).toHaveTextContent("Reference: REQ-7");
  });
});

describe("Pagination and StatTile", () => {
  it("disables controls at the ends and keeps a cursor stack", () => {
    render(<Pagination hasMore={false} hasPrevious={false} onNext={() => {}} onPrevious={() => {}} />);
    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
    const s = nextCursorStack([undefined], "c1");
    expect(s).toEqual([undefined, "c1"]);
    expect(previousCursorStack(s)).toEqual([undefined]);
    expect(nextCursorStack(s, null)).toBe(s);
  });

  it("never invents a value", () => {
    render(<StatTile label="Learning time" value={null} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });
});

describe("Table scroll region (E2E-07)", () => {
  it("is the containing block for its sr-only caption so it cannot widen the page at 360 px", () => {
    render(<Table caption="Orders" columns={[{ key: "n", header: "N", cell: (r: { id: string }) => r.id }]} rows={[{ id: "1" }]} rowKey={(r) => r.id} />);
    const region = screen.getByRole("region", { name: "Orders" });
    expect(region.className).toMatch(/\brelative\b/);
    expect(region.className).toMatch(/\boverflow-x-auto\b/);
  });
});

describe("Table stacked mobile layout (audit S1)", () => {
  it("labels every cell with its column header and keeps table semantics", () => {
    render(
      <Table
        caption="Tests"
        columns={[
          { key: "t", header: "Title", cell: (r: { id: string }) => r.id },
          { key: "a", header: "Actions", cell: () => <button type="button">Assign</button> },
        ]}
        rows={[{ id: "Mock 1" }]}
        rowKey={(r) => r.id}
      />,
    );
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Title" })).toBeInTheDocument();
    const cells = screen.getAllByRole("cell");
    expect(cells.map((c) => c.getAttribute("data-label"))).toEqual(["Title", "Actions"]);
    expect(screen.getByRole("button", { name: "Assign" })).toBeInTheDocument();
  });
});

describe("Dialog focus return on unmount (audit S5)", () => {
  function Harness() {
    const [show, setShow] = useState(false);
    return (
      <>
        <button type="button" onClick={() => setShow(true)}>
          New test
        </button>
        {show ? <Dialog open onClose={() => setShow(false)} title="New test" /> : null}
      </>
    );
  }

  it("returns focus to the opener when the caller unmounts the dialog", async () => {
    render(<Harness />);
    const opener = screen.getByRole("button", { name: "New test" });
    await userEvent.click(opener);
    expect(screen.getByRole("heading", { name: "New test" })).toBeInTheDocument();
    // jsdom has no native Escape → cancel; dispatch the event the browser would fire.
    act(() => {
      screen.getByRole("dialog", { hidden: true }).dispatchEvent(new Event("cancel", { cancelable: true }));
    });
    expect(screen.queryByRole("heading", { name: "New test" })).not.toBeInTheDocument();
    expect(opener).toHaveFocus();
  });
});

describe("PageHeader and StatusBadge", () => {
  it("never shows internal screen codes as the eyebrow", () => {
    const { rerender } = render(<PageHeader title="Users" eyebrow="ADM-004" />);
    expect(screen.queryByText("ADM-004")).not.toBeInTheDocument();
    rerender(<PageHeader title="Policies" eyebrow="SEC · ADM-006" />);
    expect(screen.queryByText(/ADM-006/)).not.toBeInTheDocument();
    rerender(<PageHeader title="Users" eyebrow="Admin" />);
    expect(screen.getByText("Admin")).toBeInTheDocument();
  });

  it("maps statuses to one vocabulary and humanises unknown ones", () => {
    render(
      <>
        <StatusBadge status="pending_review" />
        <StatusBadge status="APPROVED" />
        <StatusBadge status="awaiting_evaluator" />
      </>,
    );
    expect(screen.getByText("Pending review")).toBeInTheDocument();
    expect(screen.getByText("Approved")).toBeInTheDocument();
    expect(screen.getByText("Awaiting evaluator")).toBeInTheDocument();
  });
});
