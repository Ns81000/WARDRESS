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

function getTargetIcon(type: string, action: string, label: string) {
  const baseClass = "size-4 shrink-0"
  const t = type.toLowerCase()
  const a = action.toLowerCase()
  const l = label.toLowerCase()

  switch (t) {
    case "site":
      return (
        <svg className={cn(baseClass, "text-cyan-400")} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="10" />
          <line x1="2" y1="12" x2="22" y2="12" />
          <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
        </svg>
      )
    case "suppression_rule":
      return (
        <svg className={cn(baseClass, "text-amber-500")} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="10" />
          <line x1="4.93" y1="4.93" x2="19.07" y2="19.07" />
        </svg>
      )
    case "settings":
      return (
        <svg className={cn(baseClass, "text-stone-400")} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="3" />
          <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
        </svg>
      )
    case "notification_channel":
      return (
        <svg className={cn(baseClass, "text-purple-400")} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
          <path d="M13.73 21a2 2 0 0 1-3.46 0" />
        </svg>
      )
    case "alert":
      return (
        <svg className={cn(baseClass, "text-accent-red")} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
          <line x1="12" y1="9" x2="12" y2="13" />
          <line x1="12" y1="17" x2="12.01" y2="17" />
        </svg>
      )
    case "user":
      return (
        <svg className={cn(baseClass, "text-accent-green")} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
          <circle cx="12" cy="7" r="4" />
        </svg>
      )
    case "api_key":
      return (
        <svg className={cn(baseClass, "text-accent-yellow")} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4" />
        </svg>
      )
    case "remediation_hook":
    case "remediation_execution":
      if (a.includes("git") || l.includes("git")) {
        return (
          <svg className="size-4 shrink-0" xmlns="http://www.w3.org/2000/svg" preserveAspectRatio="xMidYMid" viewBox="0 0 256 256">
            <path d="M251.17 116.6 139.4 4.82a16.49 16.49 0 0 0-23.31 0l-23.21 23.2 29.44 29.45a19.57 19.57 0 0 1 24.8 24.96l28.37 28.38a19.61 19.61 0 1 1-11.75 11.06L137.28 95.4v69.64a19.62 19.62 0 1 1-16.13-.57V94.2a19.61 19.61 0 0 1-10.65-25.73L81.46 39.44 4.83 116.08a16.49 16.49 0 0 0 0 23.32L116.6 251.17a16.49 16.49 0 0 0 23.32 0l111.25-111.25a16.5 16.5 0 0 0 0-23.33" fill="#DE4C36" />
          </svg>
        )
      }
      if (a.includes("docker") || l.includes("docker")) {
        return (
          <svg className="size-4 shrink-0" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="#008fe2">
            <path d="M13.98 11.08h2.12a.19.19 0 0 0 .19-.19V9.01a.19.19 0 0 0-.19-.19h-2.12a.18.18 0 0 0-.18.18v1.9c0 .1.08.18.18.18m-2.95-5.43h2.12a.19.19 0 0 0 .18-.19V3.57a.19.19 0 0 0-.18-.18h-2.12a.18.18 0 0 0-.19.18v1.9c0 .1.09.18.19.18m0 2.71h2.12a.19.19 0 0 0 .18-.18V6.29a.19.19 0 0 0-.18-.18h-2.12a.18.18 0 0 0-.19.18v1.89c0 .1.09.18.19.18m-2.93 0h2.12a.19.19 0 0 0 .18-.18V6.29a.18.18 0 0 0-.18-.18H8.1a.18.18 0 0 0-.18.18v1.89c0 .1.08.18.18.18m-2.96 0h2.11a.19.19 0 0 0 .19-.18V6.29a.18.18 0 0 0-.19-.18H5.14a.19.19 0 0 0-.19.18v1.89c0 .1.08.18.19.18m5.89 2.72h2.12a.19.19 0 0 0 .18-.19V9.01a.19.19 0 0 0-.18-.19h-2.12a.18.18 0 0 0-.19.18v1.9c0 .1.09.18.19.18m-2.93 0h2.12a.18.18 0 0 0 .18-.19V9.01a.18.18 0 0 0-.18-.19H8.1a.18.18 0 0 0-.18.18v1.9c0 .1.08.18.18.18m-2.96 0h2.11a.18.18 0 0 0 .19-.19V9.01a.18.18 0 0 0-.18-.19H5.14a.19.19 0 0 0-.19.19v1.88c0 .1.08.19.19.19m-2.92 0h2.12a.18.18 0 0 0 .18-.19V9.01a.18.18 0 0 0-.18-.19H2.22a.18.18 0 0 0-.19.18v1.9c0 .1.08.18.19.18m21.54-1.19c-.06-.05-.67-.51-1.95-.51-.34 0-.68.03-1.01.09a3.77 3.77 0 0 0-1.72-2.57l-.34-.2-.23.33a4.6 4.6 0 0 0-.6 1.43c-.24.97-.1 1.88.4 2.66a4.7 4.7 0 0 1-1.75.42H.76a.75.75 0 0 0-.76.75 11.38 11.38 0 0 0 .7 4.06 6.03 6.03 0 0 0 2.4 3.12c1.18.73 3.1 1.14 5.28 1.14.98 0 1.96-.08 2.93-.26a12.25 12.25 0 0 0 3.82-1.4 10.5 10.5 0 0 0 2.61-2.13c1.25-1.42 2-3 2.55-4.4h.23c1.37 0 2.21-.55 2.68-1 .3-.3.55-.66.7-1.06l.1-.28Z" />
          </svg>
        )
      }
      return (
        <svg className="size-4 shrink-0" xmlns="http://www.w3.org/2000/svg" preserveAspectRatio="xMidYMid" viewBox="0 0 256 239" id="webhooks">
          <path fill="#C73A63" d="M119.54 100.503c-10.61 17.836-20.775 35.108-31.152 52.25-2.665 4.401-3.984 7.986-1.855 13.58 5.878 15.454-2.414 30.493-17.998 34.575-14.697 3.851-29.016-5.808-31.932-21.543-2.584-13.927 8.224-27.58 23.58-29.757 1.286-.184 2.6-.205 4.762-.367l23.358-39.168C73.612 95.465 64.868 78.39 66.803 57.23c1.368-14.957 7.25-27.883 18-38.477 20.59-20.288 52.002-23.573 76.246-8.001 23.284 14.958 33.948 44.094 24.858 69.031-6.854-1.858-13.756-3.732-21.343-5.79 2.854-13.865.743-26.315-8.608-36.981-6.178-7.042-14.106-10.733-23.12-12.093-18.072-2.73-35.815 8.88-41.08 26.618-5.976 20.13 3.069 36.575 27.784 48.967z" />
          <path fill="#4B4B4B" d="M149.841 79.41c7.475 13.187 15.065 26.573 22.587 39.836 38.02-11.763 66.686 9.284 76.97 31.817 12.422 27.219 3.93 59.457-20.465 76.25-25.04 17.238-56.707 14.293-78.892-7.851 5.654-4.733 11.336-9.487 17.407-14.566 21.912 14.192 41.077 13.524 55.305-3.282 12.133-14.337 11.87-35.714-.615-49.75-14.408-16.197-33.707-16.691-57.035-1.143-9.677-17.168-19.522-34.199-28.893-51.491-3.16-5.828-6.648-9.21-13.77-10.443-11.893-2.062-19.571-12.275-20.032-23.717-.453-11.316 6.214-21.545 16.634-25.53 10.322-3.949 22.435-.762 29.378 8.014 5.674 7.17 7.477 15.24 4.491 24.083-.83 2.466-1.905 4.852-3.07 7.774z" />
          <path fill="#4A4A4A" d="M167.707 187.21h-45.77c-4.387 18.044-13.863 32.612-30.19 41.876-12.693 7.2-26.373 9.641-40.933 7.29-26.808-4.323-48.728-28.456-50.658-55.63-2.184-30.784 18.975-58.147 47.178-64.293 1.947 7.071 3.915 14.21 5.862 21.264-25.876 13.202-34.832 29.836-27.59 50.636 6.375 18.304 24.484 28.337 44.147 24.457 20.08-3.962 30.204-20.65 28.968-47.432 19.036 0 38.088-.197 57.126.097 7.434.117 13.173-.654 18.773-7.208 9.22-10.784 26.191-9.811 36.121.374 10.148 10.409 9.662 27.157-1.077 37.127-10.361 9.62-26.73 9.106-36.424-1.26-1.992-2.136-3.562-4.673-5.533-7.298z" />
        </svg>
      )
    default:
      return (
        <svg className={cn(baseClass, "text-charcoal")} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="10" />
          <line x1="12" y1="16" x2="12" y2="12" />
          <line x1="12" y1="8" x2="12.01" y2="8" />
        </svg>
      )
  }
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
        <code className="font-mono text-code-md bg-surface-card px-1.5 py-0.5 rounded border border-hairline-strong">{JSON.stringify(data, null, 2)}</code>
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
          <span className="min-w-0 truncate text-body-sm font-medium text-ink flex items-center gap-2" title={targetLabel}>
            {getTargetIcon(entry.target_type, entry.action, targetLabel)}
            <span className="truncate">{targetLabel}</span>
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
                <div className="absolute left-0 mt-1 w-full rounded-md border border-hairline-strong bg-surface-card py-1 z-50 max-h-60 overflow-y-auto animate-detail-in font-mono text-code-md">
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
                        t === targetType && "text-ink bg-white/[0.02]"
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
