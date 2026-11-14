"use client";

import { useRef, useState } from "react";
import { Card } from "@/components/ui";
import { api } from "@/lib/api/client";

type State = { state: "idle" | "busy" | "match" | "nomatch" | "error"; name: string; msg?: string };

/** SHA-256 of a file, as lowercase hex (computed in the browser; the file is never uploaded). */
export async function sha256Hex(data: ArrayBuffer): Promise<string> {
  const d = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(d), (b) => b.toString(16).padStart(2, "0")).join("");
}

/**
 * "Check a PDF copy": the visitor picks the PDF they were given; its fingerprint is compared with
 * the copies Tech Drona issued for this number (GET certificates/verify/{code}/check).
 */
export function PdfCheck({ code }: { code: string }) {
  const [st, setSt] = useState<State>({ state: "idle", name: "" });
  const input = useRef<HTMLInputElement>(null);

  async function check(file: File | undefined) {
    if (!file) return;
    if (file.size > 25 * 1024 * 1024) {
      setSt({ state: "error", name: file.name, msg: "That file is too large to be one of our documents." });
      return;
    }
    setSt({ state: "busy", name: file.name });
    try {
      const sha256 = await sha256Hex(await file.arrayBuffer());
      const r = await api.get<{ match: boolean; status: string }>(`certificates/verify/${encodeURIComponent(code)}/check`, {
        query: { sha256 },
        handle: { auth: false, restriction: false, sessionChoice: false },
      });
      setSt({ state: r.match ? "match" : "nomatch", name: file.name });
    } catch {
      setSt({ state: "error", name: file.name, msg: "The file couldn't be checked. Try again, or another browser." });
    }
  }

  return (
    <Card title="Check a PDF copy" icon="shield" description="Choose the PDF you were given. Its fingerprint is computed in this browser (the file is not uploaded) and compared with the copies we issued.">
      <div className="flex flex-wrap items-center gap-3">
        <label className="cursor-pointer rounded-md border border-line px-3 py-2 text-sm font-semibold text-fg-link hover:border-line-strong">
          <span>Choose PDF</span>
          <input ref={input} type="file" accept="application/pdf" className="sr-only" aria-label="Choose a PDF to check" onChange={(e) => void check(e.target.files?.[0])} />
        </label>
        <p role="status" className="text-sm">
          {st.state === "busy" ? `Checking ${st.name}…` : null}
          {st.state === "match" ? <span className="font-semibold text-success-fg">{`${st.name} matches a copy we issued: it hasn't been altered.`}</span> : null}
          {st.state === "nomatch" ? <span className="font-semibold text-danger-fg">{`${st.name} does not match any copy we issued. It may have been edited, or it is a different document.`}</span> : null}
          {st.state === "error" ? <span className="text-danger-fg">{st.msg}</span> : null}
        </p>
      </div>
    </Card>
  );
}
