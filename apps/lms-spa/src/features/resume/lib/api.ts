import { api, type RequestOptions } from "@/lib/api/client";

type SendOpts = Omit<RequestOptions, "method" | "body">;

/** POST/PUT/PATCH/DELETE that returns the body (the résumé api has no dual-control actions). */
export async function send<T>(method: "post" | "put" | "patch" | "delete", path: string, body?: unknown, opts: SendOpts = {}): Promise<T> {
  const res = method === "delete" ? await api.delete<T>(path, opts) : await api[method]<T>(path, body ?? {}, opts);
  if (res.kind !== "ok") throw new Error("Unexpected approval response");
  return res.data;
}
