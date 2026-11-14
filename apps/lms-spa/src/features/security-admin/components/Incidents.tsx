"use client";

import { useState } from "react";
import { Badge, Button, Checkbox, FormField, Input, PageHeader, Select, Table, useToast, type Column } from "@/components/ui";
import { api } from "@/lib/api/client";
import { ActionDialog, StateBadge, TextArea } from "@/features/admin/components/console-ui";
import { ifMatchFor, toOutcome } from "@/features/admin/lib/console";
import type { SecurityIncident } from "../lib/types";
import { useResource } from "@/lib/api/use-resource";
import { formatDateTime, formatTimeUntil } from "@/lib/format";
import { istLocalToIso } from "@/lib/time";

/** verified: api_engine.py IncidentIn / IncidentPatch literals. */
const SEVERITIES = ["low", "medium", "high", "critical"].map((s) => ({ value: s, label: s.charAt(0).toUpperCase() + s.slice(1) }));
const STATUSES = ["detected", "triaged", "contained", "notified", "remediated", "closed"].map((s) => ({ value: s, label: s.charAt(0).toUpperCase() + s.slice(1) }));

function nowIstLocal(): string {
  return new Date(Date.now() + 5.5 * 3_600_000).toISOString().slice(0, 16);
}

function DueCell({ due, done }: { due: string | null; done?: string | null }) {
  if (!due) return <span className="text-fg-muted">—</span>;
  if (done) return <Badge tone="success">Reported {formatDateTime(done)}</Badge>;
  const overdue = Date.parse(due) < Date.now();
  return <Badge tone={overdue ? "danger" : "warning"}>{overdue ? `Overdue (${formatDateTime(due)})` : `Due ${formatTimeUntil(due)}`}</Badge>;
}

/**
 * ADM-11 / INV-19: security incident register (SEC-37 `GET /security/incidents`, SEC-38 `POST`,
 * SEC-39 `PATCH /security/incidents/{id}` with If-Match). CERT-In reporting is due 6 h after
 * detection and the DPB report 72 h after, as computed by the api.
 */
export function Incidents() {
  const toast = useToast();
  const res = useResource<{ data: SecurityIncident[] }>("security/incidents");
  const [openNew, setOpenNew] = useState(false);
  const [title, setTitle] = useState("");
  const [severity, setSeverity] = useState("medium");
  const [detectedAt, setDetectedAt] = useState(nowIstLocal);
  const [breach, setBreach] = useState(false);
  const [certin, setCertin] = useState(false);
  const [edit, setEdit] = useState<SecurityIncident | null>(null);
  const [status, setStatus] = useState("");
  const [entry, setEntry] = useState("");
  const [certinReported, setCertinReported] = useState("");

  const startEdit = (i: SecurityIncident) => {
    setEdit(i);
    setStatus(i.status);
    setEntry("");
    setCertinReported("");
  };

  const cols: Column<SecurityIncident>[] = [
    { key: "ref", header: "Reference", cell: (i) => <span className="font-mono text-xs">{i.incident_ref}</span> },
    { key: "title", header: "Title", cell: (i) => i.title },
    { key: "sev", header: "Severity", cell: (i) => <Badge tone={i.severity === "critical" || i.severity === "high" ? "danger" : i.severity === "medium" ? "warning" : "neutral"}>{SEVERITIES.find((s) => s.value === i.severity)?.label ?? i.severity}</Badge> },
    { key: "status", header: "Status", cell: (i) => <StateBadge state={i.status} /> },
    { key: "det", header: "Detected", cell: (i) => formatDateTime(i.detected_at) },
    { key: "certin", header: "CERT-In (6 h)", cell: (i) => <DueCell due={i.certin_due_at} done={i.certin_reported_at} /> },
    { key: "dpb", header: "DPB (72 h)", cell: (i) => <DueCell due={i.dpb_report_due_at} /> },
    {
      key: "act",
      header: <span className="sr-only">Actions</span>,
      cell: (i) => (
        <Button size="sm" variant="secondary" onClick={() => startEdit(i)} aria-label={`Update ${i.incident_ref}`}>
          Update
        </Button>
      ),
    },
  ];

  return (
    <div>
      <PageHeader
        breadcrumbs={[{ label: "Security", href: "/security" }, { label: "Incidents" }]}
        title="Incidents"
        description="Record security incidents and track the CERT-In (6 h) and Data Protection Board (72 h) reporting deadlines."
        actions={<Button onClick={() => setOpenNew(true)}>Open incident</Button>}
      />
      <Table
        caption="Security incidents"
        columns={cols}
        rows={res.data?.data}
        rowKey={(i) => i.incident_id}
        loading={res.loading}
        error={res.error}
        onRetry={() => void res.reload()}
        empty={{ title: "No incidents recorded", description: "If you detect a breach or attack, open an incident straight away so the reporting clocks start." }}
      />

      <ActionDialog
        open={openNew}
        onClose={() => setOpenNew(false)}
        onOpen={() => {
          setTitle("");
          setSeverity("medium");
          setDetectedAt(nowIstLocal());
          setBreach(false);
          setCertin(false);
        }}
        title="Open a security incident"
        submitLabel="Open incident"
        validate={() => (title.trim().length < 3 ? "Give the incident a title (3+ characters)." : !istLocalToIso(detectedAt) ? "Enter when it was detected." : null)}
        onSubmit={async () =>
          toOutcome(
            await api.post<SecurityIncident>("security/incidents", {
              title: title.trim(),
              severity,
              detected_at: istLocalToIso(detectedAt),
              is_personal_data_breach: breach,
              certin_reportable: certin,
            }),
          )
        }
        onDone={(o) => {
          if (o.kind === "ok") toast.show({ title: `Incident ${o.data.incident_ref} opened`, tone: "success" });
          setTitle("");
          setBreach(false);
          setCertin(false);
          void res.reload();
        }}
      >
        <FormField label="Title" required>
          {(f) => <Input {...f} value={title} onChange={(e) => setTitle(e.target.value)} maxLength={300} />}
        </FormField>
        <FormField label="Severity" required>
          {(f) => <Select {...f} value={severity} onChange={(e) => setSeverity(e.target.value)} options={SEVERITIES} />}
        </FormField>
        <FormField label="Detected at (IST)" required>
          {(f) => <Input {...f} type="datetime-local" value={detectedAt} onChange={(e) => setDetectedAt(e.target.value)} />}
        </FormField>
        <Checkbox label="Personal data breach" description="Starts the 72 h Data Protection Board deadline." checked={breach} onChange={(e) => setBreach(e.target.checked)} />
        <Checkbox label="CERT-In reportable" description="Starts the 6 h CERT-In deadline." checked={certin} onChange={(e) => setCertin(e.target.checked)} />
      </ActionDialog>

      <ActionDialog
        open={!!edit}
        onClose={() => setEdit(null)}
        title={edit ? `Update ${edit.incident_ref}` : "Update incident"}
        description={edit?.title}
        submitLabel="Save"
        validate={() => (certinReported && !istLocalToIso(certinReported) ? "Enter a valid CERT-In report time." : null)}
        onSubmit={async () => {
          const body: Record<string, unknown> = {};
          if (status && status !== edit!.status) body.status = status;
          if (entry.trim()) body.timeline_entry = entry.trim();
          const reported = istLocalToIso(certinReported);
          if (reported) body.certin_reported_at = reported;
          return toOutcome(await api.patch<SecurityIncident>(`security/incidents/${edit!.incident_id}`, body, { ifMatch: ifMatchFor(null, edit!.version) }));
        }}
        onDone={() => {
          toast.show({ title: "Incident updated", tone: "success" });
          void res.reload();
        }}
      >
        <FormField label="Status">{(f) => <Select {...f} value={status} onChange={(e) => setStatus(e.target.value)} options={STATUSES} />}</FormField>
        {edit?.certin_due_at && !edit.certin_reported_at ? (
          <FormField label="Reported to CERT-In at (IST)">{(f) => <Input {...f} type="datetime-local" value={certinReported} onChange={(e) => setCertinReported(e.target.value)} />}</FormField>
        ) : null}
        <FormField label="Timeline entry">{(f) => <TextArea {...f} value={entry} onChange={(e) => setEntry(e.target.value)} maxLength={2000} />}</FormField>
      </ActionDialog>
    </div>
  );
}
