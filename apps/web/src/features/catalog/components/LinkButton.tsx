/**
 * Compatibility path. This used to be a feature-local copy of the kit button (40/32px, Inter
 * medium, grey "secondary") that drifted off-brand next to the kit on the busiest pages. Importers
 * now get the design-system `LinkButton` (44px, Jakarta semibold, navy secondary) and the kit
 * `ProgressBar`. Its variants ("primary" | "secondary" | "ghost") and sizes ("sm" | "md") are a
 * subset of the kit's, so no importer changes. New code should import from "@/components/ui".
 */
export { LinkButton, ProgressBar, type LinkButtonProps } from "@/components/ui";
