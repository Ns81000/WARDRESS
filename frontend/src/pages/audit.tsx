import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { ChevronDown, ChevronLeft, ChevronRight, ChevronUp } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import * as apiClient from "@/lib/api"
import type { AuditLogEntry } from "@/lib/api"

/*
 * Audit log (Phase 5, §6/§7) — admin-only. Filterable who/what/when
 * table; before/after snapshots expand inline. Secrets never reach these
 * rows (redacted server-side), so everything here is safe to display.
 */

const PAGE_SIZE = 50

const TARGET_TYPES = [
  "",
  "site",
  "suppression_rule",
  "settings",
  "notification_channel",
  "alert",
  "user",
  "api_key",
  "remediation_hook",
  "remediation_execution",
]

function auditActionClass(action: string): string {
  const family = action.split(".", 1)[0]
  if (action.endsWith(".delete") || action.endsWith(".deactivate") || action.endsWith(".revoke")) {
    return "border-glow-red bg-glow-red text-accent-red"
  }
  if (action.endsWith(".create") || action.endsWith(".reactivate") || action.endsWith(".ack")) {
    return "border-glow-green bg-glow-green text-accent-green"
  }
  if (action.endsWith(".update") || action.endsWith(".test") || action.endsWith(".reset")) {
    return "border-glow-orange bg-glow-orange text-accent-orange"
  }
  if (family === "settings" || family === "notification_channel" || family === "api_key") {
    return "border-glow-blue bg-glow-blue text-link"
  }
  return "border-hairline-strong bg-surface-elevated text-body"
}

function SnapshotBlock({ label, data }: { label: string; data: Record<string, unknown> }) {
  return (
    <div className="min-w-0 flex-1">
      <p className="mb-1 text-caption uppercase tracking-wide text-mute">{label}</p>
      <pre className="overflow-x-auto rounded-md border border-hairline bg-surface-elevated p-3 text-code-md text-body">
        {JSON.stringify(data, null, 2)}
      </pre>
    </div>
  )
}

function AuditRow({ entry }: { entry: AuditLogEntry }) {
  const [open, setOpen] = useState(false)
  const hasDetail = entry.before_json != null || entry.after_json != null
  const targetLabel = entry.target_label ?? entry.target_id ?? entry.target_type

  return (
    <li className="border-b border-hairline px-5 py-4 last:border-b-0">
      <div className="flex flex-wrap items-center gap-3">
        <span className="shrink-0 text-code-md text-charcoal">
          {new Date(entry.created_at).toLocaleString()}
        </span>
        <Badge variant="outline" className={auditActionClass(entry.action)}>
          {entry.action}
        </Badge>
        <span className="min-w-0 flex-1 truncate text-body-sm text-body" title={targetLabel}>
          {targetLabel}
        </span>
        <span className="ml-auto max-w-full truncate text-caption text-mute" title={entry.actor_email ?? "system"}>
          {entry.actor_email ?? "system"}
        </span>
        {hasDetail && (
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label={open ? "Hide detail" : "Show detail"}
            onClick={() => setOpen((v) => !v)}
          >
            {open ? <ChevronUp /> : <ChevronDown />}
          </Button>
        )}
      </div>
      {open && hasDetail && (
        <div className="mt-3 flex flex-col gap-3 sm:flex-row">
          {entry.before_json && <SnapshotBlock label="Before" data={entry.before_json} />}
          {entry.after_json && <SnapshotBlock label="After" data={entry.after_json} />}
        </div>
      )}
    </li>
  )
}

export function AuditPage() {
  const [page, setPage] = useState(0)
  const [action, setAction] = useState("")
  const [targetType, setTargetType] = useState("")
  const [actor, setActor] = useState("")

  const log = useQuery({
    queryKey: ["audit", { page, action, targetType, actor }],
    queryFn: () =>
      apiClient.listAuditLog({
        offset: page * PAGE_SIZE,
        limit: PAGE_SIZE,
        action: action || undefined,
        target_type: targetType || undefined,
        actor: actor || undefined,
      }),
  })

  const total = log.data?.total ?? 0
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE))

  return (
    <div>
      <div className="mb-8">
        <h1 className="text-display-lg text-ink">Audit log</h1>
        <p className="mt-2 text-body-md text-charcoal">
          Every configuration change, acknowledgement, and user-management
          action — who, what, and when. Rows are immutable.
        </p>
      </div>

      <div className="mb-4 flex flex-wrap items-end gap-3">
        <div className="w-48">
          <Input
            placeholder="Filter action (e.g. site)"
            value={action}
            onChange={(e) => {
              setAction(e.target.value)
              setPage(0)
            }}
          />
        </div>
        <select
          data-slot="select"
          value={targetType}
          onChange={(e) => {
            setTargetType(e.target.value)
            setPage(0)
          }}
          className="h-9 rounded-md border border-hairline-strong bg-surface-elevated px-3 text-body-sm text-ink outline-none focus:border-white/25"
        >
          {TARGET_TYPES.map((t) => (
            <option key={t} value={t}>
              {t === "" ? "All targets" : t.replaceAll("_", " ")}
            </option>
          ))}
        </select>
        <div className="w-48">
          <Input
            placeholder="Filter actor email"
            value={actor}
            onChange={(e) => {
              setActor(e.target.value)
              setPage(0)
            }}
          />
        </div>
        <span className="ml-auto text-caption text-mute">
          {total} {total === 1 ? "entry" : "entries"}
        </span>
      </div>

      <div className="rounded-lg border border-hairline-strong bg-surface-card">
        {log.isLoading ? (
          <p className="p-8 text-body-sm text-mute">Loading audit log…</p>
        ) : log.isError ? (
          <p className="p-8 text-body-sm text-accent-red">
            Could not load the audit log (admin role required).
          </p>
        ) : (log.data?.items.length ?? 0) > 0 ? (
          <ul>
            {log.data!.items.map((e) => (
              <AuditRow key={e.id} entry={e} />
            ))}
          </ul>
        ) : (
          <div className="flex flex-col items-center gap-3 p-16 text-center">
            <p className="text-heading-sm text-ink">No matching entries</p>
            <p className="max-w-sm text-body-sm text-charcoal">
              Actions appear here as they happen — try clearing the filters.
            </p>
          </div>
        )}
      </div>

      {pageCount > 1 && (
        <div className="mt-4 flex items-center justify-end gap-2">
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label="Newer entries"
            disabled={page === 0}
            onClick={() => setPage((p) => Math.max(0, p - 1))}
          >
            <ChevronLeft />
          </Button>
          <span className="text-caption text-mute">
            {page + 1} / {pageCount}
          </span>
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label="Older entries"
            disabled={page >= pageCount - 1}
            onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))}
          >
            <ChevronRight />
          </Button>
        </div>
      )}
    </div>
  )
}
