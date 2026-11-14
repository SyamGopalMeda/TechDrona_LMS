"use client";

import { useEffect } from "react";
import { isPortalApiError } from "@/features/colleges/lib/api";
import { PORTAL_BASE } from "@/features/colleges/lib/routes";
import { LinkButton } from "@/features/colleges/ui/Button";
import { ErrorCard } from "@/features/colleges/ui/Feedback";

/** A screen that throws renders this inside the portal shell (top bar and navigation stay). */
export default function CollegesError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => console.error(error), [error]);
  const notFound = isPortalApiError(error) && error.status === 404;
  const adminsOnly = isPortalApiError(error) && error.isAdminsOnly;
  return (
    <div className="td-view-error">
      <ErrorCard
        title={notFound ? "Not found" : adminsOnly ? "Admins only" : "This page could not be shown"}
        text={notFound ? "This record does not exist or was removed." : adminsOnly ? "The College Data Portal is available to LMS admins only." : undefined}
        error={error}
        retry={adminsOnly ? undefined : reset}
      />
      <p>
        <LinkButton to={PORTAL_BASE} icon="home">
          Go to Home
        </LinkButton>
      </p>
    </div>
  );
}
