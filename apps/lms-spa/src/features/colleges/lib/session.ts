/**
 * The portal session (GET /college-portal/api/session). Behind the LMS proxy every request is signed in as the
 * LMS admin (`sso: true`) and the proxy asserts role `editor`, so `canWrite` is true today; the portal server
 * still supports a `viewer` role (read-only) and the UI keeps honouring it, like the old shell did:
 * hide write controls with `<WriteOnly>` / `canWrite`, and the server refuses writes with 403 `read_only`.
 */
import { usePortalQuery } from "./cache";
import type { PortalSession } from "./types";

export const ROLE_LABEL: Record<string, string> = { admin: "Admin", editor: "Editor", viewer: "View only" };

export interface PortalSessionState {
  session: PortalSession | undefined;
  /** display name ("Name (email)" from the LMS proxy) */
  user: string | null;
  role: PortalSession["role"];
  /** false only for read-only (viewer) sessions */
  canWrite: boolean;
  loading: boolean;
  error: unknown;
}

/** false only for read-only (viewer) sessions; unknown (loading) counts as writable, as before. */
export function canWriteFor(session: Pick<PortalSession, "role"> | null | undefined): boolean {
  return session?.role !== "viewer";
}

export function usePortalSession(): PortalSessionState {
  const { data, loading, error } = usePortalQuery<PortalSession>("session", { ttl: 5 * 60_000 });
  const clean = (v: unknown) => (typeof v === "string" && v.trim() && !/^(null|undefined)$/i.test(v.trim()) ? v.trim() : null);
  return {
    session: data,
    user: clean(data?.user),
    role: data?.role ?? null,
    canWrite: canWriteFor(data),
    loading,
    error,
  };
}
