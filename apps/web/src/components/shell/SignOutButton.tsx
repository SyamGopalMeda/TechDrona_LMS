"use client";

import { useState } from "react";
import { api } from "@/lib/api/client";
import { Button, Dialog, useToast } from "@/components/ui";
import { ApiError } from "@/lib/api/errors";

/** Lazy: keeps the assessment storage code out of every portal page until sign-out. */
const deviceData = () => import("@/features/assessment/lib/device-cleanup");

/**
 * AUTH-15 POST /auth/logout through the BFF, then back to /login.
 * FE-17: test answers kept on this device (IndexedDB / `td.attempt.*`) are removed on sign-out;
 * if some were never synced, the learner is warned first and can stay signed in to sync them.
 */
export function SignOutButton() {
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

  return (
    <>
      <Button variant="ghost" size="sm" loading={busy} onClick={() => void start()}>
        Sign out
      </Button>
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
    </>
  );
}

async function clearLocal(): Promise<void> {
  try {
    await (await deviceData()).clearDeviceAttemptData();
  } catch {
    /* best effort */
  }
}
