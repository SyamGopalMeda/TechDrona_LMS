/**
 * Touch-target helpers (WCAG 2.5.8 Target Size, 24px minimum; live responsive audit F3/F4).
 * Plain class strings so any element can use them; Tailwind picks them up from src/**.
 */

/**
 * A link that stands on its own line or list item (not inside running text): at least 24px tall
 * without changing its font size or colour. Inline links in sentences are exempt and keep their
 * normal flow, so do not use this inside paragraphs of prose.
 */
export const standaloneLinkClass = "inline-flex min-h-6 items-center";

/**
 * Native checkbox / radio size: 20px on a mouse, 24px on touch screens (coarse pointer), so the
 * box itself meets the 24px target where fingers are used and the desktop look is unchanged.
 */
export const choiceInputClass = "h-5 w-5 [@media(pointer:coarse)]:h-6 [@media(pointer:coarse)]:w-6";
