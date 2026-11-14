/**
 * Segment error boundary: the SPA equivalent of a Next segment's error.tsx boundary plus its
 * redirect / not-found handling.
 *
 * - `redirect()` (RedirectError) → client navigation (full page load for another origin);
 * - `notFound()` (NotFoundError) → re-thrown up to the root boundary, which renders the root
 *   not-found page (apps/web has only app/not-found.tsx);
 * - anything else → this segment's error component with `{ error, reset }`, or re-thrown to the
 *   parent segment when it has none.
 * The boundary resets on navigation (new location key), like Next.
 */
import { Component, useEffect, type ComponentType, type ReactNode } from "react";
import { useInRouterContext, useLocation, useNavigate } from "react-router";
import { isNotFoundError, isRedirectError } from "./shims/navigation";
import { bumpRefresh, isExternalHref, navigateTo, needsDocumentLoad, toAppPath } from "./nav-store";

export type ErrorComponent = ComponentType<{ error: Error & { digest?: string }; reset: () => void }>;

export function ClientRedirect({ to, replace = true }: { to: string; replace?: boolean }) {
  // In or out of a router is fixed for a tree, so the conditional hook is stable.
  const navigate = useInRouterContext() ? useNavigate() : null;
  useEffect(() => {
    if (navigate && !isExternalHref(to) && !needsDocumentLoad(to)) void navigate(toAppPath(to), { replace });
    else navigateTo(to, { replace });
  }, [navigate, to, replace]);
  return null;
}

interface Props {
  resetKey: string;
  errorComponent?: ErrorComponent;
  notFound?: ComponentType;
  children: ReactNode;
}

interface State {
  error: unknown;
  key: string;
}

class Boundary extends Component<Props, State> {
  override state: State = { error: null, key: this.props.resetKey };

  static getDerivedStateFromError(error: unknown): Partial<State> {
    return { error };
  }

  static getDerivedStateFromProps(props: Props, state: State): Partial<State> | null {
    if (props.resetKey !== state.key) return { error: null, key: props.resetKey };
    return null;
  }

  reset = () => {
    bumpRefresh();
    this.setState({ error: null });
  };

  override render(): ReactNode {
    const { error } = this.state;
    if (error === null) return this.props.children;
    if (isRedirectError(error)) return <ClientRedirect to={error.url} replace={error.replace} />;
    if (isNotFoundError(error)) {
      const NotFound = this.props.notFound;
      if (NotFound) return <NotFound />;
      throw error;
    }
    const ErrorView = this.props.errorComponent;
    if (!ErrorView) throw error;
    const err = error instanceof Error ? error : new Error(String(error));
    return <ErrorView error={err as Error & { digest?: string }} reset={this.reset} />;
  }
}

export function SegmentBoundary(props: Omit<Props, "resetKey">) {
  const { key } = useLocation();
  return <Boundary resetKey={key} {...props} />;
}
