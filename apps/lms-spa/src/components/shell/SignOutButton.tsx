"use client";

import { useState, type ReactNode } from "react";
import { api } from "@/lib/api/client";
import { Button, Dialog, useToast } from "@/components/ui";
import { ApiError } from "@/lib/api/errors";
import { setAnalyticsConsent } from "@/lib/firebase/analytics";
import { clearLastPage } from "@/features/hub/last-page";

/** Lazy: keeps the assessment storage code out of every portal page until sign-out. */
const deviceData = () => import("@/features/assessment/lib/device-cleanup");

/**
 * AUTH-15 POST /auth/logout through the BFF, then back to /login.
 * FE-17: test answers kept on this device (IndexedDB / `td.attempt.*`) are removed on sign-out;
 * if some were never synced, the learner is warned first and can stay signed in to sync them.
 *
 * The logic is a hook so the header account menu can offer "Sign out" too: render `dialog`
 * somewhere that stays mounted (not inside a menu that closes) and call `start()`.
 */
export function useSignOut(): { busy: boolean; start: () => Promise<void>; dialog: ReactNode } {
  const [busy, setBusy] = useState(false);
  const [unsynced, setUnsynced] = useState(0);
  const toast = useToast();

  const signOut = async () => {
    setBusy(true);
    try {
      await api.post("auth/logout", undefined, { handle: { auth: false } });
      await clearLocal();
      window.location.assign("/login");
    } catch (err) {
      const e = err instanceof ApiError ? err : null;
      if (e && (e.status === 401 || e.code === "unauthenticated")) {
        await clearLocal();
        window.location.assign("/login");
        return;
      }
      toast.show({ tone: "danger", title: e?.title ?? "Sign out failed", description: e?.detail, requestId: e?.requestId });
    } finally {
      setBusy(false);
    }
  };

  const start = async () => {
    setBusy(true);
    let count = 0;
    try {
      count = (await (await deviceData()).inspectDeviceAttemptData()).unsyncedAttempts;
    } catch {
      count = 0;
    }
    setBusy(false);
    if (count > 0) {
      setUnsynced(count);
      return;
    }
    await signOut();
  };

  const dialog = (
    <Dialog
      open={unsynced > 0}
      onClose={() => setUnsynced(0)}
      title="Some test answers haven't synced yet"
      description={`${unsynced} test${unsynced === 1 ? " has" : "s have"} answers saved only on this device. Signing out deletes them from this device.`}
      footer={
        <>
          <Button variant="secondary" onClick={() => setUnsynced(0)}>
            Stay signed in
          </Button>
          <Button
            variant="danger"
            loading={busy}
            onClick={() => {
              setUnsynced(0);
              void signOut();
            }}
          >
            Sign out anyway
          </Button>
        </>
      }
    >
      <p className="text-sm text-fg-secondary">Open the test again while online to sync them, then sign out.</p>
    </Dialog>
  );

  return { busy, start, dialog };
}

/** Plain "Sign out" button (+ the unsynced-answers warning). */
export function SignOutButton() {
  const { busy, start, dialog } = useSignOut();
  return (
    <>
      <Button variant="ghost" size="sm" loading={busy} onClick={() => void start()}>
        Sign out
      </Button>
      {dialog}
    </>
  );
}

async function clearLocal(): Promise<void> {
  // Analytics consent is per account: a shared browser must not keep measuring after sign-out.
  setAnalyticsConsent(false);
  // The remembered "last page" (/continue) belongs to this account.
  clearLastPage();
  try {
    await (await deviceData()).clearDeviceAttemptData();
  } catch {
    /* best effort */
  }
}
