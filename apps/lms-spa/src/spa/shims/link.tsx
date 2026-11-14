/**
 * `next/link` on React Router. Internal hrefs navigate client-side; external URLs, hash-only
 * links, downloads and links rendered outside a router (unit tests) are plain anchors.
 */
import { forwardRef, type AnchorHTMLAttributes, type ReactNode } from "react";
import { Link as RRLink, useInRouterContext } from "react-router";
import { isExternalHref, needsDocumentLoad, toAppPath } from "../nav-store";

export interface UrlObject {
  pathname?: string | null;
  query?: Record<string, string | number | boolean | readonly (string | number | boolean)[] | null | undefined> | string | null;
  hash?: string | null;
  search?: string | null;
}

export type LinkProps = Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "href"> & {
  href: string | UrlObject;
  replace?: boolean;
  scroll?: boolean;
  prefetch?: boolean | null | "auto";
  shallow?: boolean;
  passHref?: boolean;
  legacyBehavior?: boolean;
  locale?: string | false;
  children?: ReactNode;
};

export function formatHref(href: string | UrlObject): string {
  if (typeof href === "string") return href;
  let qs = href.search ?? "";
  if (!qs && href.query) {
    if (typeof href.query === "string") qs = href.query;
    else {
      const p = new URLSearchParams();
      for (const [k, v] of Object.entries(href.query)) {
        if (v === null || v === undefined) continue;
        if (Array.isArray(v)) for (const x of v) p.append(k, String(x));
        else p.set(k, String(v));
      }
      qs = p.toString();
    }
  }
  if (qs && !qs.startsWith("?")) qs = `?${qs}`;
  const hash = href.hash ? (href.hash.startsWith("#") ? href.hash : `#${href.hash}`) : "";
  return `${href.pathname ?? ""}${qs}${hash}`;
}

const Link = forwardRef<HTMLAnchorElement, LinkProps>(function Link(
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  { href, replace, scroll, prefetch, shallow, passHref, legacyBehavior, locale, children, ...rest },
  ref,
) {
  const url = formatHref(href);
  const inRouter = useInRouterContext();
  if (!inRouter || isExternalHref(url) || needsDocumentLoad(url) || url.startsWith("#") || rest.download !== undefined) {
    return (
      <a ref={ref} href={url} {...rest}>
        {children}
      </a>
    );
  }
  return (
    <RRLink ref={ref} to={toAppPath(url)} replace={replace} preventScrollReset={scroll === false} {...rest}>
      {children}
    </RRLink>
  );
});

export default Link;
