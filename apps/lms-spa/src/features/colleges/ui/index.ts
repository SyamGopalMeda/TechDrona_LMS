/**
 * Shared portal UI (React ports of the old js/ui/components.js). Import from here:
 *   import { DataTable, Kpi, KpiRow, StatusChip, Modal, toast, confirm } from "@/features/colleges/ui";
 * Every component uses the old `td-*` class names; their CSS is styles/components.css (scoped under `.tdp`).
 */
export { Icon, ICON_NAMES, type IconName } from "./Icon";
export { Button, LinkButton, buttonClass, type ButtonProps, type ButtonTone } from "./Button";
export { Badge, StatusBadge, StatusChip, Provenance, ValueWithBasis, VerifiedBadge, Chip } from "./Badges";
export { Kpi, KpiRow, StatCard, ProgressBar, type KpiProps, type ProgressBarProps } from "./Kpi";
export { EmptyState, ListEmpty, ErrorCard, Skeleton, ViewSkeleton, Spinner, Section, Kv, PageHeader, ScopePill, hasFilters } from "./Feedback";
export { Tabs, LinkTabs, Segmented, useScrollStrip, bestMatch, type TabDef, type LinkTab, type SegOption } from "./Tabs";
export { Modal, Drawer, OverlayHost, confirm, toast, type ToastTone } from "./Overlay";
export { Menu, type MenuItem } from "./Menu";
export { Field, PortalForm, FormDialog, normOptions, type FieldSpec, type FieldType, type Option, type OptionInput } from "./Form";
export { DataTable, Pagination, type Column, type RowAction, type SortState, type DataTableProps } from "./DataTable";
export { FilterBar, type FilterDef, type FilterValues } from "./FilterBar";
export { ContactActions, telHref, waNumber, whatsappHref } from "./ContactActions";
export { WriteOnly, cx, usePortalUi, PortalUiProvider, type PortalUi } from "./context";
export { STATUS_META, PERF_STATUS_ORDER, STATUS_KINDS, DIAG_TIPS, BASIS_META, statusMeta, humanize, type Tone, type StatusMeta } from "./status";
