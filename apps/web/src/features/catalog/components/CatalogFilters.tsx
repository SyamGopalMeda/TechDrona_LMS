import Link from "next/link";
import { Button } from "@/components/ui";

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

const control =
  "h-10 w-full rounded-md border border-line-control bg-surface px-3 text-sm text-fg focus-visible:shadow-focus focus-visible:outline-none";

/**
 * Catalog filters as a plain GET form (works without JavaScript; the URL is shareable and
 * the server re-renders with CAT-01 filters).
 */
export function CatalogFilters({ values }: { values: CatalogFilterValues }) {
  return (
    <form method="get" action="/courses" role="search" aria-label="Filter courses" className="grid gap-3 rounded-xl border border-line bg-surface p-4 sm:grid-cols-2 lg:grid-cols-5">
      <div className="lg:col-span-2">
        <label htmlFor="cat-q" className="mb-1 block text-sm font-medium text-fg">
          Search
        </label>
        <input id="cat-q" name="q" type="search" defaultValue={values.q ?? ""} placeholder="Course title or topic" className={control} />
      </div>
      <div>
        <label htmlFor="cat-level" className="mb-1 block text-sm font-medium text-fg">
          Level
        </label>
        <select id="cat-level" name="level" defaultValue={values.level ?? ""} className={control}>
          {LEVELS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </div>
      <div>
        <label htmlFor="cat-price" className="mb-1 block text-sm font-medium text-fg">
          Price
        </label>
        <select id="cat-price" name="price_type" defaultValue={values.price_type ?? ""} className={control}>
          {PRICES.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </div>
      <div>
        <label htmlFor="cat-lang" className="mb-1 block text-sm font-medium text-fg">
          Language
        </label>
        <select id="cat-lang" name="language" defaultValue={values.language ?? ""} className={control}>
          {LANGUAGES.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </div>
      {values.category ? <input type="hidden" name="category" value={values.category} /> : null}
      <div className="flex items-end gap-2 sm:col-span-2 lg:col-span-5">
        <Button type="submit">Apply filters</Button>
        <Link href="/courses" className="text-sm font-medium text-fg-link hover:text-fg-link-hover">
          Clear
        </Link>
      </div>
    </form>
  );
}
