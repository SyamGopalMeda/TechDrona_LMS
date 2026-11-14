import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { QrCode } from "./QrCode";

describe("QrCode (qrcode package, byte mode, level M)", () => {
  it("draws a join link as a version 4 symbol with a 4-module quiet zone", () => {
    render(<QrCode value="https://lms.techdrona.in/app/engage/join/ABCD2345" label="Join QR" />);
    const svg = screen.getByRole("img", { name: "Join QR" });
    expect(svg.getAttribute("viewBox")).toBe("0 0 41 41");
    // finder pattern corner module (0,0) sits just inside the quiet zone
    expect(svg.querySelector("path")?.getAttribute("d")).toMatch(/^M4 4h1v1h-1z/);
  });

  it("keeps the version 10 limit: 213 bytes draw, 214 show a message", () => {
    const { unmount } = render(<QrCode value={"a".repeat(213)} />);
    expect(screen.getByRole("img").getAttribute("viewBox")).toBe("0 0 65 65");
    unmount();
    render(<QrCode value={"a".repeat(214)} />);
    expect(screen.getByText("This link is too long for a QR code.")).toBeInTheDocument();
  });
});
