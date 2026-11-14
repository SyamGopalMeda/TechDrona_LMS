import fs from "node:fs";
import path from "node:path";

/** QA accounts (synthetic, qa-*@qa.techdrona.test). Credentials come from Secret Manager
 * (`td-qa-creds`, JSON {password, accounts:{admin,content,trainer,evaluator,student}}) via env QA_CREDS. */
export type RoleKey = "admin" | "content" | "trainer" | "evaluator" | "student";
export const ROLES: RoleKey[] = ["admin", "content", "trainer", "evaluator", "student"];
export const HOME: Record<RoleKey, string> = { admin: "/admin", content: "/studio", trainer: "/trainer", evaluator: "/evaluator", student: "/app" };

export function creds(): { password: string; accounts: Record<RoleKey, string> } {
  const raw = process.env.QA_CREDS;
  if (!raw) throw new Error("QA_CREDS missing (Secret Manager td-qa-creds)");
  return JSON.parse(raw);
}
export const stateFile = (r: RoleKey) => path.join(__dirname, "..", "out", "state", `${r}.json`);
export const roles = (): RoleKey[] => {
  const only = (process.env.ROLE_ONLY ?? "").split(",").map((s) => s.trim()).filter(Boolean) as RoleKey[];
  return only.length ? ROLES.filter((r) => only.includes(r)) : ROLES;
};
export const hasState = (r: RoleKey) => fs.existsSync(stateFile(r));
