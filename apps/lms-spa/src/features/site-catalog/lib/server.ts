import "server-only";
import { cache } from "react";
import { fetchSiteCatalog } from "./catalog";

/**
 * The website catalogue for server components, memoised per request (the page and a dashboard
 * strip on it share one load). Upstream fetches are cached by Next for 5 minutes.
 */
export const loadSiteCatalog = cache(() => fetchSiteCatalog());
