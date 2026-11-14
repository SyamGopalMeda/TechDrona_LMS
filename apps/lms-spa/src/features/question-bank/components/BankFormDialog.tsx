"use client";

import { useEffect, useState } from "react";
import { Button, Dialog, FormField, Input, useToast } from "@/components/ui";
import { api } from "@/lib/api/client";
import { fieldErrorsOf, TextArea, useFailToast } from "@/features/trainer/shared/ui";
import { seg } from "@/features/trainer/shared/use-api";
import type { Bank } from "../lib/types";

/** Create a bank (`POST studio/question-banks`) or edit its name/subject/description (`PATCH`). */
export function BankFormDialog({ open, onClose, bank, onSaved }: { open: boolean; onClose: () => void; bank?: Bank | null; onSaved: (b: Bank) => void }) {
  const toast = useToast();
  const fail = useFailToast();
  const [name, setName] = useState("");
  const [subject, setSubject] = useState("");
  const [description, setDescription] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    setName(bank?.name ?? "");
    setSubject(bank?.subject ?? "");
    setDescription(bank?.description ?? "");
    setErrors({});
  }, [open, bank]);

  const save = async () => {
    if (!name.trim()) {
      setErrors({ name: "Give the bank a name." });
      return;
    }
    setBusy(true);
    try {
      const body = { name: name.trim(), subject: subject.trim() || null, description: description.trim() || null };
      const res = bank ? await api.patch<Bank>(`studio/question-banks/${seg(bank.id)}`, body) : await api.post<Bank>("studio/question-banks", body);
      if (res.kind === "ok") {
        toast.show({ tone: "success", title: bank ? "Bank updated" : "Bank created" });
        onSaved(res.data);
      }
    } catch (err) {
      const fe = fieldErrorsOf(err);
      if (Object.keys(fe).length) setErrors(fe);
      else fail(err, bank ? "Couldn't update the bank" : "Couldn't create the bank");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      dismissible={!busy}
      title={bank ? "Edit bank" : "New bank"}
      description={bank ? undefined : "A bank groups reusable questions by subject or topic."}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={() => void save()} loading={busy}>
            {bank ? "Save" : "Create bank"}
          </Button>
        </>
      }
    >
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          void save();
        }}
      >
        <FormField label="Bank name" required error={errors.name}>
          {(p) => <Input {...p} value={name} maxLength={120} placeholder="e.g. Python lists" onChange={(e) => setName(e.target.value)} />}
        </FormField>
        <FormField label="Subject" hint="Optional. Banks are grouped by subject." error={errors.subject}>
          {(p) => <Input {...p} value={subject} maxLength={120} placeholder="e.g. Programming" onChange={(e) => setSubject(e.target.value)} />}
        </FormField>
        <FormField label="Description" error={errors.description}>
          {(p) => <TextArea {...p} rows={3} maxLength={1000} value={description} onChange={(e) => setDescription(e.target.value)} />}
        </FormField>
      </form>
    </Dialog>
  );
}
