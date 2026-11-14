"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";

interface SsoResponse {
  token: string;
  url: string;
  role: string;
}

/**
 * Hands the signed-in LMS user over to the Company Website Admin Panel without a second sign-in.
 * POST /sso/website (through the BFF, so CSRF applies) returns a one-hour Firebase custom token
 * for the user's verified email, issued only to an active member of the website team. The token
 * travels in the URL fragment, which browsers never send to a server; the website signs in with
 * it and removes it from the address bar at once.
 */
export function WebsiteSso() {
  const [error, setError] = useState<string | null>(null);
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    api
      .post<SsoResponse>("sso/website")
      .then((res) => {
        if (res.kind !== "ok") throw new Error("unexpected response");
        const target = new URL(res.data.url);
        target.hash = `sso=${encodeURIComponent(res.data.token)}`;
        window.location.replace(target.toString());
      })
      .catch((e: unknown) => {
        const detail = e instanceof ApiError ? e.problem?.detail : null;
        setError(typeof detail === "string" && detail ? detail : "The website admin could not be opened. Please try again.");
      });
  }, []);

  return (
    <main id="main" className="grid min-h-dvh place-items-center bg-surface-canvas px-4 text-fg">
      <div className="w-full max-w-md rounded-xl border border-line bg-surface p-6 text-center shadow-sm">
        {error ? (
          <>
            <h1 className="font-display text-lg font-bold text-fg-heading">Couldn&apos;t open the website admin</h1>
            <p role="alert" className="mt-2 text-sm text-fg-secondary">
              {error}
            </p>
            <Link href="/modules" className="mt-4 inline-block font-semibold text-brand">
              Back to modules
            </Link>
          </>
        ) : (
          <p aria-live="polite" className="font-display text-base font-semibold text-fg-heading">
            Opening the Company Website Admin…
          </p>
        )}
      </div>
    </main>
  );
}
