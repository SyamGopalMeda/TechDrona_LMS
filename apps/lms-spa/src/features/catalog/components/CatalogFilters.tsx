import { Button, FormField, Input, LinkButton, Select } from "@/components/ui";

export interface CatalogFilterValues {
  q?: string;
  category?: string;
  level?: string;
  price_type?: string;
  language?: string;
}

const LEVELS = [
  { value: "", label: "Any level" },
  { value: "beginner", label: "Beginner" },
  { value: "intermediate", label: "Intermediate" },
  { value: "advanced", label: "Advanced" },
];
const PRICES = [
  { value: "", label: "Free and paid" },
  { value: "free", label: "Free" },
  { value: "paid", label: "Paid" },
];
const LANGUAGES = [
  { value: "", label: "Any language" },
  { value: "en", label: "English" },
  { value: "hi", label: "Hindi" },
  { value: "te", label: "Telugu" },
];

/**
 * Catalog filters as a plain GET form (works without JavaScript; the URL is shareable and
 * the server re-renders with CAT-01 filters). Kit controls (44 px, same labels as every form);
 * not the kit `FilterBar`, which is client-side and prevents the native submit.
 */
export function CatalogFilters({ values }: { values: CatalogFilterValues }) {
  const active = Boolean(values.q || values.level || values.price_type || values.language || values.category);
  return (
    <form method="get" action="/courses" role="search" aria-label="Filter courses" className="grid items-end gap-3 rounded-xl border border-line bg-surface p-4 sm:grid-cols-2 lg:grid-cols-5">
      <div className="sm:col-span-2">
        <FormField label="Search">{(f) => <Input {...f} name="q" type="search" defaultValue={values.q ?? ""} placeholder="Course title or topic" />}</FormField>
      </div>
      <FormField label="Level">{(f) => <Select {...f} name="level" defaultValue={values.level ?? ""} options={LEVELS} />}</FormField>
      <FormField label="Price">{(f) => <Select {...f} name="price_type" defaultValue={values.price_type ?? ""} options={PRICES} />}</FormField>
      <FormField label="Language">{(f) => <Select {...f} name="language" defaultValue={values.language ?? ""} options={LANGUAGES} />}</FormField>
      {values.category ? <input type="hidden" name="category" value={values.category} /> : null}
      <div className="flex flex-wrap items-center gap-2 sm:col-span-2 lg:col-span-5">
        <Button type="submit">Apply filters</Button>
        {active ? (
          <LinkButton href="/courses" variant="ghost">
            Clear filters
          </LinkButton>
        ) : null}
      </div>
    </form>
  );
}
