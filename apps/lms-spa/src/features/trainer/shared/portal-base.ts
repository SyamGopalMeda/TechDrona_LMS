"use client";

import { usePathname } from "next/navigation";

export type GradingBase = "/trainer" | "/evaluator";

/** Pure: which staff portal a path belongs to for the shared grading screens. */
export function gradingBaseFor(pathname: string | null | undefined): GradingBase {
  return pathname === "/evaluator" || pathname?.startsWith("/evaluator/") ? "/evaluator" : "/trainer";
}

/**
 * The grading screens (assignment / test evaluation, integrity review, publish results) are shared
 * by the Trainer portal and the Evaluator portal (plan §4.2). Links stay inside the current portal:
 * the Evaluator portal's grading queue lives at `/evaluator` (not `/evaluator/grading`).
 */
export function useGradingBase(): { base: GradingBase; isEvaluator: boolean; gradingHome: string } {
  const base = gradingBaseFor(usePathname());
  return { base, isEvaluator: base === "/evaluator", gradingHome: base === "/evaluator" ? "/evaluator" : "/trainer/grading" };
}
