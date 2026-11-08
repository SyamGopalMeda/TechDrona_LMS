import { Button, Input } from "@/components/ui";

/**
 * FE-13: enter a certificate code. A plain GET form (works without JavaScript); `/verify`
 * redirects a well-formed code to `/verify/{code}` (PUB-017).
 */
export function VerifyCodeForm({ initial = "", invalid = false }: { initial?: string; invalid?: boolean }) {
  return (
    <form method="get" action="/verify" className="space-y-3 rounded-xl border border-line bg-surface p-5" role="search" aria-label="Verify a certificate">
      <label htmlFor="certificate-code" className="block text-sm font-medium text-fg">
        Certificate code
      </label>
      <Input
        id="certificate-code"
        name="code"
        defaultValue={initial}
        autoComplete="off"
        autoCapitalize="characters"
        spellCheck={false}
        maxLength={32}
        aria-invalid={invalid ? true : undefined}
        aria-describedby={invalid ? "certificate-code-hint certificate-code-err" : "certificate-code-hint"}
        className="font-mono uppercase"
      />
      <p id="certificate-code-hint" className="text-xs text-fg-muted">
        10–16 letters and digits, as printed on the certificate.
      </p>
      {invalid ? (
        <p id="certificate-code-err" role="alert" className="text-xs font-medium text-danger-fg">
          Enter a code of 10–16 letters and digits.
        </p>
      ) : null}
      <Button type="submit">Verify</Button>
    </form>
  );
}
