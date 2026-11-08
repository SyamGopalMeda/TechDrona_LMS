"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { configureApiClient } from "@/lib/api/client";
import { ToastProvider } from "@/components/ui";
import { StepUpDialog, type StepUpRequest } from "./StepUpDialog";

/**
 * Client-wide providers: toast region and the API client hooks (navigation + step-up modal).
 * Portal agents can override `onPlaybackConflict` / `onSessionChoiceRequired` locally with
 * configureApiClient() inside the relevant screen (it returns a restore function).
 */
export function Providers({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [stepUp, setStepUp] = useState<StepUpRequest | null>(null);

  useEffect(
    () =>
      configureApiClient({
        navigate: (href) => router.push(href),
        requestStepUp: (challenge) => new Promise<boolean>((resolve) => setStepUp({ challenge, resolve })),
      }),
    [router],
  );

  return (
    <ToastProvider>
      {children}
      <StepUpDialog request={stepUp} onDone={() => setStepUp(null)} />
    </ToastProvider>
  );
}
