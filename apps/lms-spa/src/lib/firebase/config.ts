/**
 * Firebase web config and feature switches (docs/firebase/MIGRATION-PLAN.md §5, docs/firebase/p1.md).
 *
 * The values are public (they identify the Firebase project; they are not secrets) and come
 * from the root `.env` as `NEXT_PUBLIC_FIREBASE_*`. They are read at REQUEST time on the server
 * (dynamic `env[name]` lookups are not inlined by the bundler) and handed to client components
 * as props, so the switches below take effect on restart without a rebuild:
 *
 * - `TD_GOOGLE_SIGNIN_ENABLED=false` hides "Continue with Google" (the API reads the same
 *   variable and refuses `/auth/login/google`).
 * - `TD_FIREBASE_ANALYTICS_ENABLED=false` never loads Google Analytics (and drops its CSP hosts).
 */

export interface FirebaseWebConfig {
  apiKey: string;
  authDomain: string;
  projectId: string;
  appId: string;
  messagingSenderId?: string;
  measurementId?: string;
}

type Env = Record<string, string | undefined>;

const read = (env: Env, name: string): string => (env[name] ?? "").trim();
const isOff = (v: string) => ["0", "false", "off", "no"].includes(v.toLowerCase());

export function firebaseWebConfig(env: Env = process.env): FirebaseWebConfig | null {
  const apiKey = read(env, "NEXT_PUBLIC_FIREBASE_API_KEY");
  const projectId = read(env, "NEXT_PUBLIC_FIREBASE_PROJECT_ID");
  const appId = read(env, "NEXT_PUBLIC_FIREBASE_APP_ID");
  if (!apiKey || !projectId || !appId) return null;
  const authDomain = read(env, "NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN") || `${projectId}.firebaseapp.com`;
  const cfg: FirebaseWebConfig = { apiKey, authDomain, projectId, appId };
  const sender = read(env, "NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID");
  const measurementId = read(env, "NEXT_PUBLIC_FIREBASE_MEASUREMENT_ID");
  if (sender) cfg.messagingSenderId = sender;
  if (/^G-[A-Z0-9]{4,20}$/.test(measurementId)) cfg.measurementId = measurementId;
  return cfg;
}

/** Config for Google sign-in, or null when it is not configured or switched off. */
export function googleSignInConfig(env: Env = process.env): FirebaseWebConfig | null {
  if (isOff(read(env, "TD_GOOGLE_SIGNIN_ENABLED"))) return null;
  return firebaseWebConfig(env);
}

/** Config for Firebase Analytics (needs a measurement id), or null when off. */
export function analyticsConfig(env: Env = process.env): FirebaseWebConfig | null {
  if (isOff(read(env, "TD_FIREBASE_ANALYTICS_ENABLED"))) return null;
  const cfg = firebaseWebConfig(env);
  return cfg?.measurementId ? cfg : null;
}
