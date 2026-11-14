"use client";

import { createContext, useContext, type ReactNode } from "react";

/**
 * Where the engage manager screens live. Trainer pages use the default; another portal can
 * wrap its pages in `<EngageScopeProvider base=…>`. UX only — the api authorises every call.
 */
export interface EngageScope {
  base: string;
}

const DEFAULT_SCOPE: EngageScope = { base: "/trainer/engage" };
const Ctx = createContext<EngageScope>(DEFAULT_SCOPE);

export function EngageScopeProvider({ base, children }: { base: string; children: ReactNode }) {
  return <Ctx.Provider value={{ base }}>{children}</Ctx.Provider>;
}

export function useEngageScope(): EngageScope {
  return useContext(Ctx);
}
