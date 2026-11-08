"use client";

/** Route base of the path authoring screens (trainer portal). Single-company: there is no
 * separate partner portal any more, so the base is constant; kept as a hook so callers need
 * no change if another portal reuses the screens later. */
export function pathsBaseFor(_pathname?: string | null): string {
  return "/trainer/paths";
}

export function usePathsBase(): string {
  return pathsBaseFor();
}
