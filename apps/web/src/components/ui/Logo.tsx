import { cn } from "@/lib/ui/cn";

/**
 * Official Tech Drona logo, copied unmodified from the website source
 * (`tech drona/dist/img/logo-lockup-*.svg`, `logo-mark-navy.svg`) into `public/brand/`.
 *
 * - `lockup` (default): archer mark + "TECH DRONA" wordmark, 922×200 (4.61:1). Use in headers/footers.
 * - `mark`: the archer mark alone, square. Use where space is tight (≤ 40px wide), never stretched.
 * - `tone="white"` only on the navy brand band (`bg-surface-brand`); `mark` exists in navy only.
 *
 * Size it with a height class only (e.g. `h-8`); width follows the aspect ratio.
 *
 * Plain <img> (not next/image): the SVGs are static, tiny when cached, and must not be re-encoded.
 */
export function Logo({
  variant = "lockup",
  tone = "navy",
  className,
  alt = "Tech Drona",
}: {
  variant?: "lockup" | "mark";
  tone?: "navy" | "white";
  className?: string;
  /** Pass "" when a visible text label next to it already names the brand. */
  alt?: string;
}) {
  const src = variant === "mark" ? "/brand/logo-mark-navy.svg" : `/brand/logo-lockup-${tone}.svg`;
  const [w, h] = variant === "mark" ? [40, 40] : [184, 40];
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img src={src} alt={alt} width={w} height={h} decoding="async" className={cn("w-auto", className ?? "h-8")} />
  );
}
