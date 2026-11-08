import { describe, expect, it } from "vitest";
import { pathsBaseFor } from "./base";

describe("pathsBaseFor", () => {
  it("always uses the trainer path screens (single portal)", () => {
    expect(pathsBaseFor("/trainer/paths")).toBe("/trainer/paths");
    expect(pathsBaseFor(null)).toBe("/trainer/paths");
  });
});
