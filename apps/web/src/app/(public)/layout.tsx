import type { ReactNode } from "react";
import { PublicShell } from "@/components/shell/PublicShell";
import { hasSessionCookie } from "@/lib/api/server";

export default async function PublicLayout({ children }: { children: ReactNode }) {
  return <PublicShell signedIn={await hasSessionCookie()}>{children}</PublicShell>;
}
