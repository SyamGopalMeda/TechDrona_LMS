/**
 * Temporary body of every portal route until its screen is ported (docs/colleges-react/PORTING-GUIDE.md).
 * Shows the route's title, the old view it replaces and a link to the old portal page meanwhile.
 */
import { useLocation } from "react-router";
import { matchPortalRoute, OLD_PORTAL_ENTRY, PORTAL_BASE } from "../lib/routes";
import { LinkButton } from "../ui/Button";
import { EmptyState, PageHeader } from "../ui/Feedback";

export function ComingInThePort({ title }: { title: string }) {
  const { pathname, search } = useLocation();
  const route = matchPortalRoute(pathname)?.route;
  const legacy = `${pathname.slice(PORTAL_BASE.length) || "/"}${search}`;
  return (
    <div>
      <PageHeader title={title} scope />
      <div className="td-card">
        <EmptyState
          icon="sparkle"
          title="Coming in the port"
          text={
            <>
              This screen is being rebuilt in React{route ? ` (from js/views/${route.oldView})` : ""}. Until then, use the current portal.
            </>
          }
          actions={[
            <LinkButton key="old" to={`${OLD_PORTAL_ENTRY}#${legacy}`} reload tone="primary" icon="external">
              Open in the current portal
            </LinkButton>,
          ]}
        />
      </div>
    </div>
  );
}
