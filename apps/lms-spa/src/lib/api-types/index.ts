/**
 * Typed views over the generated OpenAPI schema (`npm run gen:api` regenerates schema.d.ts from
 * openapi/openapi.json, which is dumped from the FastAPI app factory — see openapi/README note in
 * package.json `gen:api`).
 *
 * Most backend routes return `dict[str, Any]`, so their generated response type is an open
 * object; feature `lib/types.ts` files therefore keep hand-written response interfaces that were
 * verified against the router/service code. Request bodies and query parameters ARE fully typed
 * by the backend's Pydantic models — use `Body<>` / `Query<>` / `Schema<>` for those.
 */
import type { components, paths } from "./schema";

export type { components, paths } from "./schema";

/** A named Pydantic model from the backend (`components.schemas`). */
export type Schema<K extends keyof components["schemas"]> = components["schemas"][K];

/** Path as the frontend calls it (relative to /api/v1, no leading slash). */
type StripBase<P> = P extends `/api/v1/${infer R}` ? R : never;
export type ApiPath = StripBase<keyof paths>;

type Op<P extends ApiPath, M extends string> = `/api/v1/${P}` extends keyof paths
  ? M extends keyof paths[`/api/v1/${P}`]
    ? paths[`/api/v1/${P}`][M]
    : never
  : never;

type Method = "get" | "post" | "put" | "patch" | "delete";

/** JSON request body of an operation. */
export type Body<P extends ApiPath, M extends Method> =
  Op<P, M> extends { requestBody?: { content: { "application/json": infer B } } } ? B : never;

/** Query parameters of an operation. */
export type Query<P extends ApiPath, M extends Method = "get"> =
  Op<P, M> extends { parameters: { query?: infer Q } } ? NonNullable<Q> : never;

/** Successful (2xx) JSON response of an operation. */
export type Ok<P extends ApiPath, M extends Method = "get"> =
  Op<P, M> extends { responses: infer R }
    ? R extends Record<number, unknown>
      ? {
          [S in keyof R]: S extends 200 | 201 | 202
            ? R[S] extends { content: { "application/json": infer C } }
              ? C
              : never
            : never;
        }[keyof R]
      : never
    : never;
