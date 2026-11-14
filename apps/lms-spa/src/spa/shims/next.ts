/**
 * Type-only stand-ins for the `next` package types used by the copied pages
 * (`Metadata`, `Viewport`, `MetadataRoute`). Metadata is applied at runtime by src/spa/metadata.ts.
 */
export type MetadataTitle = string | { default?: string; template?: string; absolute?: string } | null;

export interface Metadata {
  title?: MetadataTitle;
  description?: string | null;
  applicationName?: string;
  robots?: string | { index?: boolean; follow?: boolean; [k: string]: unknown } | null;
  icons?: unknown;
  openGraph?: unknown;
  alternates?: unknown;
  [key: string]: unknown;
}

export interface Viewport {
  width?: string;
  initialScale?: number;
  colorScheme?: string;
  themeColor?: string;
  [key: string]: unknown;
}

export interface ResolvingMetadata {
  title?: MetadataTitle;
}

// eslint-disable-next-line @typescript-eslint/no-namespace
export namespace MetadataRoute {
  export interface Manifest {
    name?: string;
    short_name?: string;
    start_url?: string;
    display?: string;
    theme_color?: string;
    background_color?: string;
    icons?: { src: string; sizes?: string; type?: string; purpose?: string }[];
    [key: string]: unknown;
  }
  export interface Robots {
    rules: { userAgent?: string | string[]; allow?: string | string[]; disallow?: string | string[]; crawlDelay?: number }[] | { userAgent?: string | string[]; allow?: string | string[]; disallow?: string | string[] };
    sitemap?: string | string[];
    host?: string;
  }
  export type Sitemap = { url: string; lastModified?: string | Date; changeFrequency?: string; priority?: number }[];
}
