import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { ChevronDown, ChevronLeft, ChevronRight, ChevronUp, Clock, Search, User } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import * as apiClient from "@/lib/api"
import type { AuditLogEntry } from "@/lib/api"
import { cn } from "@/lib/utils"

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

function SnapshotBlock({
  label,
  data,
  type = "before"
}: {
  label: string
  data: Record<string, unknown>
  type?: "before" | "after"
}) {
  const markerColor = type === "before" ? "bg-accent-red" : "bg-accent-green"
  const markerText = type === "before" ? "text-accent-red" : "text-accent-green"

  return (
    <div className="min-w-0 flex-1 flex flex-col rounded-lg border border-hairline-strong overflow-hidden bg-[#040407]">
      {/* Code window chrome bar */}
      <div className="flex h-9 items-center justify-between border-b border-hairline bg-surface-deep px-4 select-none">
        <div className="flex items-center gap-1.5">
          <span className="size-1.5 rounded-full bg-accent-red/80" />
          <span className="size-1.5 rounded-full bg-accent-yellow/80" />
          <span className="size-1.5 rounded-full bg-accent-green/80" />
          <span className={cn("ml-2 font-mono text-[9px] font-bold tracking-wider", markerText)}>
            {label.toUpperCase()}_STATE
          </span>
        </div>
        <div className="flex items-center gap-1">
          <span className={cn("size-1.5 rounded-full", markerColor)} />
          <span className="font-mono text-[8px] text-mute uppercase tracking-widest">{type}</span>
        </div>
      </div>

      {/* Code window content */}
      <pre className="overflow-x-auto p-4 text-code-md text-body leading-relaxed font-mono scrollbar-thin">
        <code>{JSON.stringify(data, null, 2)}</code>
      </pre>
    </div>
  )
}

function AuditRow({ entry }: { entry: AuditLogEntry }) {
  const [open, setOpen] = useState(false)
  const hasDetail = entry.before_json != null || entry.after_json != null
  const targetLabel = entry.target_label ?? entry.target_id ?? entry.target_type

  const formattedDate = new Date(entry.created_at).toLocaleString(undefined, {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  })

  return (
    <li className="border-b border-hairline last:border-b-0">
      {/* Clickable Row Header Container */}
      <div
        onClick={() => hasDetail && setOpen((v) => !v)}
        className={cn(
          "px-6 py-3.5 transition-all duration-150 select-none",
          hasDetail ? "cursor-pointer hover:bg-white/[0.015]" : "cursor-default",
          open && "bg-white/[0.01]"
        )}
      >
        <div className="flex flex-col gap-2 sm:grid sm:grid-cols-[180px_160px_1fr_220px_32px] sm:items-center sm:gap-4">
          {/* Timestamp */}
          <span className="font-mono text-code-md text-charcoal flex items-center gap-1.5">
            <Clock className="size-3.5 text-mute sm:hidden" />
            {formattedDate}
          </span>

          {/* Action Badge */}
          <div className="flex items-center">
            <Badge variant="outline" className={cn("px-2.5 py-0.5 text-[10px] font-mono tracking-wider", auditActionClass(entry.action))}>
              {entry.action}
            </Badge>
          </div>

          {/* Target Label */}
          <span className="min-w-0 truncate text-body-sm font-medium text-ink" title={targetLabel}>
            {targetLabel}
          </span>

          {/* Actor Email */}
          <span className="truncate font-mono text-caption text-mute" title={entry.actor_email ?? "system"}>
            {entry.actor_email ?? "system"}
          </span>

          {/* Details toggle chevron */}
          <div className="flex justify-end">
            {hasDetail ? (
              <span className="text-mute hover:text-ink transition-colors">
                {open ? <ChevronUp className="size-4" /> : <ChevronDown className="size-4" />}
              </span>
            ) : (
              <span className="text-stone select-none font-mono text-[10px]">—</span>
            )}
          </div>
        </div>
      </div>

      {/* Expanded Diff Block */}
      {open && hasDetail && (
        <div className="animate-detail-in bg-surface-deep/30 border-t border-hairline p-6 flex flex-col gap-4 sm:flex-row">
          {entry.before_json && <SnapshotBlock label="Before" data={entry.before_json} type="before" />}
          {entry.after_json && <SnapshotBlock label="After" data={entry.after_json} type="after" />}
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
  const [dropdownOpen, setDropdownOpen] = useState(false)

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
    <div className="relative">
      {/* Ambient background glow */}
      <div className="pointer-events-none absolute top-[-100px] left-1/2 h-[350px] w-full max-w-[800px] -translate-x-1/2 rounded-full opacity-5 blur-[140px] transition-all duration-1000 bg-glow-blue" />

      {/* Page Header */}
      <div className="relative z-10 mb-8">
        <h1 className="text-display-lg text-ink">Audit log</h1>
        <p className="mt-2 text-body-md text-charcoal">
          Every configuration change, acknowledgement, and user-management
          action — who, what, and when. Rows are immutable.
        </p>
      </div>

      {/* Filters Toolbar */}
      <div className="relative z-20 mb-6 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-wrap items-center gap-3">
          {/* Action Filter Input */}
          <div className="relative w-full sm:w-56">
            <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-charcoal pointer-events-none" />
            <Input
              placeholder="Filter action (e.g. site)"
              value={action}
              onChange={(e) => {
                setAction(e.target.value)
                setPage(0)
              }}
              className="pl-9 h-9 bg-surface-card border-hairline-strong text-ink placeholder:text-mute focus:border-ink rounded-md transition-colors"
            />
          </div>

          {/* Target Type Selector */}
          <div className="relative w-full sm:w-48">
            <button
              type="button"
              onClick={() => setDropdownOpen((prev) => !prev)}
              className="w-full h-9 rounded-md border border-hairline-strong bg-surface-card px-3 text-left text-body-sm text-ink outline-none focus:border-ink transition-colors flex items-center justify-between cursor-pointer"
            >
              <span>{targetType === "" ? "All targets" : targetType.replaceAll("_", " ")}</span>
              <ChevronDown className={cn("size-4 text-charcoal transition-transform duration-200", dropdownOpen && "rotate-180")} />
            </button>

            {dropdownOpen && (
              <>
                {/* Backdrop to close list when clicking outside */}
                <div className="fixed inset-0 z-40" onClick={() => setDropdownOpen(false)} />
                <div className="absolute left-0 mt-1 w-full rounded-md border border-hairline-strong bg-surface-card py-1 shadow-2xl z-50 max-h-60 overflow-y-auto animate-detail-in font-mono text-code-md">
                  {TARGET_TYPES.map((t) => (
                    <button
                      key={t}
                      type="button"
                      onClick={() => {
                        setTargetType(t)
                        setPage(0)
                        setDropdownOpen(false)
                      }}
                      className={cn(
                        "w-full text-left px-3 py-1.5 cursor-pointer transition-colors text-charcoal hover:bg-white/[0.04] hover:text-ink flex items-center justify-between",
                        t === targetType && "text-ink bg-white/[0.02] font-semibold"
                      )}
                    >
                      <span>{t === "" ? "All targets" : t.replaceAll("_", " ")}</span>
                      {t === targetType && <span className="size-1.5 rounded-full bg-accent-blue" />}
                    </button>
                  ))}
                </div>
              </>
            )}
          </div>

          {/* Actor Email Filter Input */}
          <div className="relative w-full sm:w-56">
            <User className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-charcoal pointer-events-none" />
            <Input
              placeholder="Filter actor email"
              value={actor}
              onChange={(e) => {
                setActor(e.target.value)
                setPage(0)
              }}
              className="pl-9 h-9 bg-surface-card border-hairline-strong text-ink placeholder:text-mute focus:border-ink rounded-md transition-colors"
            />
          </div>
        </div>

        {/* Count Badge */}
        <span className="text-caption font-mono text-mute bg-surface-elevated px-3 py-1.5 rounded-full border border-hairline-strong">
          {total} {total === 1 ? "entry" : "entries"}
        </span>
      </div>

      {/* Main Logs Table Box */}
      <div className="relative z-10 rounded-lg border border-hairline-strong bg-surface-card overflow-hidden">
        {/* Table header (visible on desktop) */}
        {!log.isLoading && !log.isError && (log.data?.items.length ?? 0) > 0 && (
          <div className="hidden border-b border-hairline px-6 py-2.5 text-[10px] font-mono uppercase tracking-wider text-charcoal sm:grid sm:grid-cols-[180px_160px_1fr_220px_32px] sm:items-center sm:gap-4 bg-surface-deep/45">
            <span>Timestamp</span>
            <span>Action</span>
            <span>Target Label</span>
            <span>Actor</span>
            <span className="text-right font-mono">Detail</span>
          </div>
        )}

        {log.isLoading ? (
          <div className="flex h-40 items-center justify-center">
            <p className="font-mono text-body-sm text-mute animate-pulse">Loading audit log...</p>
          </div>
        ) : log.isError ? (
          <div className="flex h-40 items-center justify-center p-8 text-center">
            <p className="font-mono text-body-sm text-accent-red">
              Could not load the audit log (admin role required).
            </p>
          </div>
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

      {/* Pagination controls */}
      {pageCount > 1 && (
        <div className="relative z-10 mt-4 flex items-center justify-end gap-3 font-mono">
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label="Newer entries"
            disabled={page === 0}
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            className="border border-hairline-strong bg-surface-card hover:bg-surface-elevated disabled:opacity-30 rounded-md"
          >
            <ChevronLeft className="size-4" />
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
            className="border border-hairline-strong bg-surface-card hover:bg-surface-elevated disabled:opacity-30 rounded-md"
          >
            <ChevronRight className="size-4" />
          </Button>
        </div>
      )}
    </div>
  )
}
