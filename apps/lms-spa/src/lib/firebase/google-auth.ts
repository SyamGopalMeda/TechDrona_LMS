/**
 * Google sign-in with the Firebase JS SDK (docs/firebase/MIGRATION-PLAN.md §5.1).
 *
 * Firebase is used only to obtain a Google-backed Firebase ID token; the LMS session comes from
 * `POST /api/v1/auth/login/google`. Callers sign out of Firebase as soon as the LMS answers, so
 * no parallel Firebase session lingers (session persistence: cleared with the tab anyway).
 * The SDK is bundled and loaded lazily on click (it never loads on other pages).
 *
 * Popup first (COOP `same-origin-allow-popups` on /login and /signup); when the popup is
 * blocked or unsupported, fall back to a full-page redirect and resume on return.
 */

import type { FirebaseWebConfig } from "./config";

const APP_NAME = "td-google-signin";
const REDIRECT_FLAG = "td.google_redirect";

export interface GoogleUser {
  email: string | null;
  displayName: string | null;
  /** Firebase ID token; `fresh` forces a new token (each token is accepted once by the API). */
  idToken(fresh?: boolean): Promise<string>;
  signOut(): Promise<void>;
}

async function authFor(config: FirebaseWebConfig) {
  const [appMod, authMod] = await Promise.all([import("firebase/app"), import("firebase/auth")]);
  const app =
    appMod.getApps().find((a) => a.name === APP_NAME) ??
    appMod.initializeApp({ apiKey: config.apiKey, authDomain: config.authDomain, projectId: config.projectId, appId: config.appId }, APP_NAME);
  let auth: import("firebase/auth").Auth;
  try {
    auth = authMod.initializeAuth(app, {
      persistence: authMod.browserSessionPersistence,
      popupRedirectResolver: authMod.browserPopupRedirectResolver,
    });
  } catch {
    auth = authMod.getAuth(app); // already initialised in this tab
  }
  return { auth, authMod };
}

function wrap(auth: import("firebase/auth").Auth, authMod: typeof import("firebase/auth"), user: import("firebase/auth").User): GoogleUser {
  return {
    email: user.email,
    displayName: user.displayName,
    idToken: (fresh = false) => user.getIdToken(fresh),
    signOut: () => authMod.signOut(auth),
  };
}

const FALLBACK_TO_REDIRECT = new Set(["auth/popup-blocked", "auth/operation-not-supported-in-this-environment", "auth/cancelled-popup-request"]);

/** Starts Google sign-in. Resolves to the user, or "redirecting" when the page navigates away. */
export async function signInWithGoogle(config: FirebaseWebConfig): Promise<GoogleUser | "redirecting"> {
  const { auth, authMod } = await authFor(config);
  const provider = new authMod.GoogleAuthProvider();
  provider.setCustomParameters({ prompt: "select_account" });
  try {
    const cred = await authMod.signInWithPopup(auth, provider);
    return wrap(auth, authMod, cred.user);
  } catch (e) {
    const code = (e as { code?: string }).code ?? "";
    if (!FALLBACK_TO_REDIRECT.has(code)) throw e;
    try {
      sessionStorage.setItem(REDIRECT_FLAG, "1");
    } catch {
      /* storage blocked: the redirect result cannot be resumed */
    }
    await authMod.signInWithRedirect(auth, provider);
    return "redirecting";
  }
}

/** After a redirect fallback: the signed-in user, or null when no redirect is pending. */
export async function resumeGoogleRedirect(config: FirebaseWebConfig): Promise<GoogleUser | null> {
  try {
    if (sessionStorage.getItem(REDIRECT_FLAG) !== "1") return null;
    sessionStorage.removeItem(REDIRECT_FLAG);
  } catch {
    return null;
  }
  const { auth, authMod } = await authFor(config);
  const res = await authMod.getRedirectResult(auth);
  return res ? wrap(auth, authMod, res.user) : null;
}

/** User-facing message for a Firebase Auth error; null when the user simply closed the popup. */
export function googleErrorMessage(e: unknown): string | null {
  const code = (e as { code?: string })?.code ?? "";
  if (code === "auth/popup-closed-by-user" || code === "auth/user-cancelled") return null;
  if (code === "auth/network-request-failed") return "We couldn't reach Google. Check your connection and try again.";
  if (code === "auth/unauthorized-domain") return "Google sign-in isn't set up for this address yet. Use your email and password.";
  return "Google sign-in didn't work. Try again, or use your email and password.";
}
