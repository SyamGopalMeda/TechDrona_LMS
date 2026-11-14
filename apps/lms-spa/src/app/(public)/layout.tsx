import { use, useState, type ReactNode } from "react";
import { PublicShell } from "@/components/shell/PublicShell";
import { probeSession } from "@/spa/session";

/**
 * SPA override of apps/web/src/app/(public)/layout.tsx: `signedIn` came from the session cookie on
 * the server; here it comes from one API probe when the public area mounts (like a Next layout,
 * it is not re-evaluated on navigation inside the area).
 */
export default function PublicLayout({ children }: { children: ReactNode }) {
  const [state] = useState(() => probeSession());
  return <PublicShell signedIn={use(state) === "yes"}>{children}</PublicShell>;
}
