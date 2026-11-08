import type { ComponentProps } from "react";
import { cn } from "@/lib/ui/cn";
import { controlBase, controlBorder, controlFocus, isInvalid } from "./Input";

export interface SelectOption {
  value: string;
  label: string;
  disabled?: boolean;
}

export interface SelectProps extends Omit<ComponentProps<"select">, "children"> {
  options: SelectOption[];
  placeholder?: string;
}

/** Native <select>: keyboard and screen-reader behaviour come from the platform. */
export function Select({ options, placeholder, className, ...props }: SelectProps) {
  return (
    <select className={cn(controlBase, "h-11 cursor-pointer pr-9", controlBorder(isInvalid(props["aria-invalid"])), controlFocus, className)} {...props}>
      {placeholder !== undefined ? (
        <option value="" disabled>
          {placeholder}
        </option>
      ) : null}
      {options.map((o) => (
        <option key={o.value} value={o.value} disabled={o.disabled}>
          {o.label}
        </option>
      ))}
    </select>
  );
}
