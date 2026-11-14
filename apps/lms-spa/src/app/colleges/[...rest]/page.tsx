import type { Metadata } from "next";
import { useLocation } from "react-router";
import { PORTAL_BASE, resolveAlias } from "@/features/colleges/lib/routes";
import { ClientRedirect } from "@/spa/boundary";
import { LinkButton } from "@/features/colleges/ui/Button";
import { EmptyState } from "@/features/colleges/ui/Feedback";

export const metadata: Metadata = { title: { absolute: "Page not found · Tech Drona Outreach Portal" }, robots: { index: false, follow: false } };

/** Old alias paths (/colleges/team, /colleges/reports…) redirect to the canonical page; anything else: not found. */
export default function Page() {
  const { pathname, search } = useLocation();
  const to = resolveAlias(pathname);
  if (to) return <ClientRedirect to={`${to}${search}`} />;
  return (
    <div className="td-view-error td-notfound">
      <div className="td-card">
        <EmptyState
          title="Page not found"
          icon="warn"
          text={
            <>
              The link <code>{pathname}</code> does not match any page. It may be mistyped or the record may have moved.
            </>
          }
          actions={[
            <LinkButton key="home" to={PORTAL_BASE} tone="primary" icon="home">
              Go to Home
            </LinkButton>,
            <LinkButton key="colleges" to={`${PORTAL_BASE}/colleges`} icon="college">
              Browse colleges
            </LinkButton>,
          ]}
        />
      </div>
    </div>
  );
}
