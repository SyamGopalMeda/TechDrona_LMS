import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { FirebaseWebConfig } from "@/lib/firebase/config";
import { mockApi, problem, renderWithProviders } from "../test/mock-api";
import { GoogleSignIn } from "./GoogleSignIn";

/** Recorded api calls minus the shell's GET public/integrations status check. */
const apiCalls = (api: { calls: { path: string }[] }) => api.calls.filter((c) => c.path !== "public/integrations") as ReturnType<typeof mockApi>["calls"];


const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push, replace: push, back: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() }) }));

// The Firebase SDK is never loaded in tests: the wrapper is mocked.
const signOut = vi.fn(async () => undefined);
const idToken = vi.fn(async (fresh?: boolean) => (fresh ? "fresh-token" : "first-token"));
vi.mock("@/lib/firebase/google-auth", () => ({
  signInWithGoogle: vi.fn(async () => ({ email: "meera@example.com", displayName: "Meera Iyer", idToken, signOut })),
  resumeGoogleRedirect: vi.fn(async () => null),
  googleErrorMessage: () => "Google sign-in didn't work.",
}));

const CONFIG: FirebaseWebConfig = { apiKey: "k", authDomain: "techdrona-lms.firebaseapp.com", projectId: "techdrona-lms", appId: "1:2:web:3" };
let restore: (() => void) | undefined;
beforeEach(() => {
  push.mockReset();
  signOut.mockClear();
  idToken.mockClear();
  sessionStorage.clear();
});
afterEach(() => restore?.());

describe("GoogleSignIn", () => {
  it("signs an existing student in with the ID token and signs out of Firebase", async () => {
    const api = mockApi({ "POST auth/login/google": { body: { result: "authenticated", redirect: "/app", new_account: false } } });
    restore = api.restore;
    renderWithProviders(<GoogleSignIn config={CONFIG} next="/app/courses" />);
    await userEvent.click(screen.getByRole("button", { name: /Continue with Google/ }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/app/courses"));
    expect(apiCalls(api)[0]!.body).toEqual({ id_token: "first-token", remember_device: false });
    expect(apiCalls(api)[0]!.headers["x-csrf-token"]).toBe("test-csrf-token");
    expect(signOut).toHaveBeenCalled();
  });

  it("collects signup details for a new account and resends with a fresh token", async () => {
    let n = 0;
    const api = mockApi({
      "POST auth/login/google": () =>
        ++n === 1
          ? problem(409, "google_signup_required", "Finish creating your account", { suggested_name: "Meera Iyer" })
          : { body: { result: "authenticated", redirect: "/app", new_account: true } },
    });
    restore = api.restore;
    renderWithProviders(<GoogleSignIn config={CONFIG} />);
    await userEvent.click(screen.getByRole("button", { name: /Continue with Google/ }));
    expect(await screen.findByRole("heading", { name: "Create your account" })).toBeInTheDocument();
    expect(screen.getByLabelText(/Full name/)).toHaveValue("Meera Iyer");
    expect(signOut).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: "Create account" }));
    expect(await screen.findByText(/Enter your date of birth/)).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Day"), "20");
    await userEvent.selectOptions(screen.getByLabelText("Month"), "5");
    await userEvent.selectOptions(screen.getByLabelText("Year"), "2001");
    await userEvent.click(screen.getByLabelText(/I agree to the/));
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/app"));
    const body = apiCalls(api)[1]!.body as { id_token: string; signup: { date_of_birth: string; consents: { purpose: string; granted: boolean }[]; guardian: unknown } };
    expect(body.id_token).toBe("fresh-token");
    expect(body.signup.date_of_birth).toBe("2001-05-20");
    expect(body.signup.guardian).toBeNull();
    expect(body.signup.consents.filter((c) => c.granted).map((c) => c.purpose)).toEqual(["terms", "privacy_notice", "core_service"]);
    expect(signOut).toHaveBeenCalled();
  });

  it("tells staff to use their password", async () => {
    const api = mockApi({ "POST auth/login/google": problem(403, "google_signin_not_allowed", "Use your password to sign in") });
    restore = api.restore;
    renderWithProviders(<GoogleSignIn config={CONFIG} />);
    await userEvent.click(screen.getByRole("button", { name: /Continue with Google/ }));
    expect(await screen.findByText(/Staff accounts sign in with email, password/)).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
    expect(signOut).toHaveBeenCalled();
  });
});
