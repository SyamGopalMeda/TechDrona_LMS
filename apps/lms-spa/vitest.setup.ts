import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(async () => {
  cleanup();
  // The session-scoped identity cache (me, me/grants, me/modules) must not leak between tests.
  // Imported lazily so a test file's vi.mock() of its dependencies still applies.
  const { resetIdentityCacheForTests } = await import("@/lib/api/session-cache");
  resetIdentityCacheForTests();
});
