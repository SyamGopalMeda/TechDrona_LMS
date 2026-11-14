import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PortalApiError } from "../lib/api";
import { PortalUiProvider, type PortalUi } from "./context";
import { DataTable } from "./DataTable";
import { StatusChip, StatusBadge, ValueWithBasis } from "./Badges";
import { ProgressBar } from "./Kpi";
import { FormDialog } from "./Form";
import { OverlayHost, confirm, resetOverlaysForTests, toast } from "./Overlay";
import { ContactActions, whatsappHref } from "./ContactActions";

const ui = (over: Partial<PortalUi> = {}): PortalUi => ({ overlayRoot: document.body, form: "desktop", coarse: false, canWrite: true, ...over });

function wrap(node: React.ReactNode, over: Partial<PortalUi> = {}) {
  return render(
    <MemoryRouter>
      <PortalUiProvider value={ui(over)}>
        {node}
        <OverlayHost />
      </PortalUiProvider>
    </MemoryRouter>,
  );
}

afterEach(() => act(() => resetOverlaysForTests()));

type Row = { id: number; name: string; enrolled: number };
const rows: Row[] = Array.from({ length: 12 }, (_, i) => ({ id: i + 1, name: `College ${String.fromCharCode(65 + i)}`, enrolled: (i * 7) % 10 }));
const columns = [
  { key: "name", label: "College", primary: true },
  { key: "enrolled", label: "Enrolled", align: "right" as const },
];

describe("DataTable", () => {
  it("sorts and paginates on the client", () => {
    wrap(<DataTable<Row> caption="Colleges" rows={rows} columns={columns} pageSize={5} pageLabel="colleges" />);
    expect(screen.getByText("1–5 of 12 colleges")).toBeInTheDocument();
    expect(screen.getAllByRole("row")).toHaveLength(6);
    fireEvent.click(screen.getByRole("button", { name: "Enrolled" }));
    const first = screen.getAllByRole("row")[1]!;
    expect(within(first).getByText("0")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    expect(screen.getByText("6–10 of 12 colleges")).toBeInTheDocument();
  });

  it("renders cards on phones, hides write-only row actions for viewers and shows empty / error states", () => {
    const edit = vi.fn();
    const { unmount } = wrap(<DataTable<Row> rows={rows.slice(0, 2)} columns={columns} rowActions={(r) => [{ label: "Edit", onClick: () => edit(r.id), writeOnly: true }]} />, { form: "phone", canWrite: false });
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(screen.queryByRole("button", { name: "Edit" })).toBeNull();
    unmount();
    wrap(<DataTable<Row> rows={[]} columns={columns} empty="No colleges yet" rowActions={(r) => [{ label: "Edit", onClick: () => edit(r.id) }]} />);
    expect(screen.getByText("No colleges yet")).toBeInTheDocument();
  });

  it("clears the selection when clearSelectionKey changes (no remount)", () => {
    const onSelect = vi.fn();
    const table = (k: number) => <DataTable<Row> rows={rows.slice(0, 3)} columns={columns} selectable onSelect={onSelect} clearSelectionKey={k} />;
    const { rerender } = wrap(table(0));
    fireEvent.click(screen.getAllByRole("checkbox", { name: "Select row" })[0]!);
    expect(onSelect).toHaveBeenLastCalledWith([rows[0]]);
    expect(screen.getAllByRole("checkbox", { name: "Select row" })[0]).toBeChecked();
    rerender(
      <MemoryRouter>
        <PortalUiProvider value={ui()}>
          {table(1)}
          <OverlayHost />
        </PortalUiProvider>
      </MemoryRouter>,
    );
    expect(screen.getAllByRole("checkbox", { name: "Select row" }).some((c) => (c as HTMLInputElement).checked)).toBe(false);
  });

  it("calls server sort / page handlers when given", () => {
    const onSort = vi.fn();
    const onPage = vi.fn();
    wrap(<DataTable<Row> rows={rows.slice(0, 5)} columns={columns} pageSize={5} total={40} page={1} onPage={onPage} onSort={onSort} sort={null} />);
    fireEvent.click(screen.getByRole("button", { name: "College" }));
    expect(onSort).toHaveBeenCalledWith("name", "asc");
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    expect(onPage).toHaveBeenCalledWith(2);
  });
});

describe("badges and bars", () => {
  it("uses the shared status vocabulary", () => {
    wrap(
      <>
        <StatusChip status="behind" />
        <StatusBadge kind="op_status" value={null} />
        <ValueWithBasis value={{ value: 180, basis: "estimated" }} />
        <ProgressBar actual={12} target={10} />
        <ProgressBar actual={3} target={8} status="partial_target" />
      </>,
    );
    expect(screen.getByText("Behind").closest(".td-badge")).toHaveClass("td-badge--bad");
    expect(screen.getByText("Status pending")).toBeInTheDocument();
    expect(screen.getByText("≈ Estimated")).toBeInTheDocument();
    expect(screen.getByText("+2 over target")).toBeInTheDocument();
    expect(screen.getByText("Not judged")).toBeInTheDocument();
  });

  it("builds tel / WhatsApp links", () => {
    expect(whatsappHref("98765 43210")).toBe("https://wa.me/919876543210");
    expect(whatsappHref("123")).toBeNull();
    wrap(<ContactActions phone="+91 98765 43210" email={null} whatsapp name="Ravi" />);
    expect(screen.getByRole("link", { name: /Call Ravi/ })).toHaveAttribute("href", "tel:+919876543210");
    expect(screen.getByRole("link", { name: "WhatsApp Ravi" })).toHaveAttribute("href", "https://wa.me/919876543210");
  });
});

describe("overlays and forms", () => {
  it("confirm resolves with the answer; toasts render", async () => {
    wrap(null);
    let answer: boolean | undefined;
    act(() => {
      void confirm({ title: "Deactivate this lead?", confirmLabel: "Deactivate" }).then((v) => (answer = v));
    });
    fireEvent.click(await screen.findByRole("button", { name: "Deactivate" }));
    await waitFor(() => expect(answer).toBe(true));
    act(() => toast("Saved", "good"));
    expect(screen.getByText("Saved")).toBeInTheDocument();
  });

  it("FormDialog validates, maps server field errors and reuses the key only after a network failure", async () => {
    const keys: string[] = [];
    const onSubmit = vi
      .fn()
      .mockImplementationOnce((_v: unknown, { idempotencyKey }: { idempotencyKey: string }) => {
        keys.push(idempotencyKey);
        throw new PortalApiError(0, "offline");
      })
      .mockImplementationOnce((_v: unknown, { idempotencyKey }: { idempotencyKey: string }) => {
        keys.push(idempotencyKey);
        throw new PortalApiError(400, "Please fix 1 field", { phone: "Use 10 digits" });
      })
      .mockImplementationOnce(() => ({ id: 7 }));
    const onDone = vi.fn();
    wrap(
      <FormDialog
        open
        title="Add a person"
        fields={[
          { name: "full_name", label: "Full name", required: true },
          { name: "phone", label: "Phone", type: "tel" },
          { name: "role", label: "Role", type: "select", options: [["ambassador", "Ambassador"]], value: "ambassador" },
        ]}
        onSubmit={onSubmit}
        onDone={onDone}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Full name is required")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/Full name/), { target: { value: "Ravi" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    fireEvent.click(await screen.findByRole("button", { name: "Save" }));
    expect(await screen.findByText("Use 10 digits")).toBeInTheDocument();
    expect(keys[0]).toBe(keys[1]);
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(onDone).toHaveBeenCalledWith({ id: 7 }));
    expect(onSubmit.mock.calls[2]![0]).toEqual({ full_name: "Ravi", phone: null, role: "ambassador" });
  });
});
