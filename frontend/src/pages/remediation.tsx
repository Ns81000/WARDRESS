import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Check, ChevronLeft, ChevronRight, X, Inbox } from "lucide-react"
import { Link } from "react-router"
import { toast } from "sonner"

import { StatusDot, type DotState } from "@/components/status-dot"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import * as apiClient from "@/lib/api"
import { ApiError, type RemediationExecution } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import { cn } from "@/lib/utils"

/*
 * Remediation queue (Phase 5, §6/§9). Pending firings wait here for an
 * explicit operator decision — nothing is POSTed until confirmed
 * (auto-execute hooks are a labeled per-hook opt-in and appear here as
 * history). Viewers see the queue read-only.
 */

const PAGE_SIZE = 25

const ACTION_LABELS: Record<string, string> = {
  git_rollback: "Git rollback",
  docker_restart: "Docker restart",
  maintenance_page_swap: "Maintenance page swap",
  custom_webhook: "Custom webhook",
}

function getActionTypeIcon(type: string, className?: string) {
  const classStr = cn("size-4 shrink-0", className)
  switch (type) {
    case "git_rollback":
      return (
        <svg className={classStr} xmlns="http://www.w3.org/2000/svg" preserveAspectRatio="xMidYMid" viewBox="0 0 256 256">
          <path d="M251.17 116.6 139.4 4.82a16.49 16.49 0 0 0-23.31 0l-23.21 23.2 29.44 29.45a19.57 19.57 0 0 1 24.8 24.96l28.37 28.38a19.61 19.61 0 1 1-11.75 11.06L137.28 95.4v69.64a19.62 19.62 0 1 1-16.13-.57V94.2a19.61 19.61 0 0 1-10.65-25.73L81.46 39.44 4.83 116.08a16.49 16.49 0 0 0 0 23.32L116.6 251.17a16.49 16.49 0 0 0 23.32 0l111.25-111.25a16.5 16.5 0 0 0 0-23.33" fill="#DE4C36" />
        </svg>
      )
    case "docker_restart":
      return (
        <svg className={classStr} xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="#008fe2">
          <path d="M13.98 11.08h2.12a.19.19 0 0 0 .19-.19V9.01a.19.19 0 0 0-.19-.19h-2.12a.18.18 0 0 0-.18.18v1.9c0 .1.08.18.18.18m-2.95-5.43h2.12a.19.19 0 0 0 .18-.19V3.57a.19.19 0 0 0-.18-.18h-2.12a.18.18 0 0 0-.19.18v1.9c0 .1.09.18.19.18m0 2.71h2.12a.19.19 0 0 0 .18-.18V6.29a.19.19 0 0 0-.18-.18h-2.12a.18.18 0 0 0-.19.18v1.89c0 .1.09.18.19.18m-2.93 0h2.12a.19.19 0 0 0 .18-.18V6.29a.18.18 0 0 0-.18-.18H8.1a.18.18 0 0 0-.18.18v1.89c0 .1.08.18.18.18m-2.96 0h2.11a.19.19 0 0 0 .19-.18V6.29a.18.18 0 0 0-.19-.18H5.14a.19.19 0 0 0-.19.18v1.89c0 .1.08.18.19.18m5.89 2.72h2.12a.19.19 0 0 0 .18-.19V9.01a.19.19 0 0 0-.18-.19h-2.12a.18.18 0 0 0-.19.18v1.9c0 .1.09.18.19.18m-2.93 0h2.12a.18.18 0 0 0 .18-.19V9.01a.18.18 0 0 0-.18-.19H8.1a.18.18 0 0 0-.18.18v1.9c0 .1.08.18.18.18m-2.96 0h2.11a.18.18 0 0 0 .19-.19V9.01a.18.18 0 0 0-.18-.19H5.14a.19.19 0 0 0-.19.19v1.88c0 .1.08.19.19.19m-2.92 0h2.12a.18.18 0 0 0 .18-.19V9.01a.18.18 0 0 0-.18-.19H2.22a.18.18 0 0 0-.19.18v1.9c0 .1.08.18.19.18m21.54-1.19c-.06-.05-.67-.51-1.95-.51-.34 0-.68.03-1.01.09a3.77 3.77 0 0 0-1.72-2.57l-.34-.2-.23.33a4.6 4.6 0 0 0-.6 1.43c-.24.97-.1 1.88.4 2.66a4.7 4.7 0 0 1-1.75.42H.76a.75.75 0 0 0-.76.75 11.38 11.38 0 0 0 .7 4.06 6.03 6.03 0 0 0 2.4 3.12c1.18.73 3.1 1.14 5.28 1.14.98 0 1.96-.08 2.93-.26a12.25 12.25 0 0 0 3.82-1.4 10.5 10.5 0 0 0 2.61-2.13c1.25-1.42 2-3 2.55-4.4h.23c1.37 0 2.21-.55 2.68-1 .3-.3.55-.66.7-1.06l.1-.28Z" />
        </svg>
      )
    case "custom_webhook":
      return (
        <svg className={classStr} xmlns="http://www.w3.org/2000/svg" preserveAspectRatio="xMidYMid" viewBox="0 0 256 239" id="webhooks">
          <path fill="#C73A63" d="M119.54 100.503c-10.61 17.836-20.775 35.108-31.152 52.25-2.665 4.401-3.984 7.986-1.855 13.58 5.878 15.454-2.414 30.493-17.998 34.575-14.697 3.851-29.016-5.808-31.932-21.543-2.584-13.927 8.224-27.58 23.58-29.757 1.286-.184 2.6-.205 4.762-.367l23.358-39.168C73.612 95.465 64.868 78.39 66.803 57.23c1.368-14.957 7.25-27.883 18-38.477 20.59-20.288 52.002-23.573 76.246-8.001 23.284 14.958 33.948 44.094 24.858 69.031-6.854-1.858-13.756-3.732-21.343-5.79 2.854-13.865.743-26.315-8.608-36.981-6.178-7.042-14.106-10.733-23.12-12.093-18.072-2.73-35.815 8.88-41.08 26.618-5.976 20.13 3.069 36.575 27.784 48.967z" />
          <path fill="#4B4B4B" d="M149.841 79.41c7.475 13.187 15.065 26.573 22.587 39.836 38.02-11.763 66.686 9.284 76.97 31.817 12.422 27.219 3.93 59.457-20.465 76.25-25.04 17.238-56.707 14.293-78.892-7.851 5.654-4.733 11.336-9.487 17.407-14.566 21.912 14.192 41.077 13.524 55.305-3.282 12.133-14.337 11.87-35.714-.615-49.75-14.408-16.197-33.707-16.691-57.035-1.143-9.677-17.168-19.522-34.199-28.893-51.491-3.16-5.828-6.648-9.21-13.77-10.443-11.893-2.062-19.571-12.275-20.032-23.717-.453-11.316 6.214-21.545 16.634-25.53 10.322-3.949 22.435-.762 29.378 8.014 5.674 7.17 7.477 15.24 4.491 24.083-.83 2.466-1.905 4.852-3.07 7.774z" />
          <path fill="#4A4A4A" d="M167.707 187.21h-45.77c-4.387 18.044-13.863 32.612-30.19 41.876-12.693 7.2-26.373 9.641-40.933 7.29-26.808-4.323-48.728-28.456-50.658-55.63-2.184-30.784 18.975-58.147 47.178-64.293 1.947 7.071 3.915 14.21 5.862 21.264-25.876 13.202-34.832 29.836-27.59 50.636 6.375 18.304 24.484 28.337 44.147 24.457 20.08-3.962 30.204-20.65 28.968-47.432 19.036 0 38.088-.197 57.126.097 7.434.117 13.173-.654 18.773-7.208 9.22-10.784 26.191-9.811 36.121.374 10.148 10.409 9.662 27.157-1.077 37.127-10.361 9.62-26.73 9.106-36.424-1.26-1.992-2.136-3.562-4.673-5.533-7.298z" />
        </svg>
      )
    default:
      return (
        <svg className={classStr} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect x="2" y="3" width="20" height="14" rx="2" ry="2" />
          <line x1="8" y1="21" x2="16" y2="21" />
          <line x1="12" y1="17" x2="12" y2="21" />
        </svg>
      )
  }
}

function statusDot(status: RemediationExecution["status"]): DotState {
  switch (status) {
    case "pending_confirm":
      return "pending"
    case "queued":
      return "pending"
    case "succeeded":
      return "clean"
    case "failed":
      return "threat"
    default:
      return "idle"
  }
}

function statusBadge(status: RemediationExecution["status"]) {
  switch (status) {
    case "pending_confirm":
      return <Badge variant="pending" className="h-[22px] inline-flex items-center text-[11px] leading-none">awaiting confirm</Badge>
    case "queued":
      return <Badge variant="pending" className="h-[22px] inline-flex items-center text-[11px] leading-none">queued</Badge>
    case "succeeded":
      return <Badge variant="clean" className="h-[22px] inline-flex items-center text-[11px] leading-none">succeeded</Badge>
    case "failed":
      return <Badge variant="threat" className="h-[22px] inline-flex items-center text-[11px] leading-none">failed</Badge>
    default:
      return <Badge variant="secondary" className="h-[22px] inline-flex items-center text-[11px] leading-none">dismissed</Badge>
  }
}

function ExecutionRow({
  execution,
  canAct,
}: {
  execution: RemediationExecution
  canAct: boolean
}) {
  const queryClient = useQueryClient()
  const invalidate = () =>
    void queryClient.invalidateQueries({ queryKey: ["remediation-executions"] })

  const confirm = useMutation({
    mutationFn: () => apiClient.confirmRemediation(execution.id),
    onSuccess: () => {
      invalidate()
      toast.success("Remediation confirmed — the webhook is firing")
    },
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.message : "Could not confirm"),
  })
  const dismiss = useMutation({
    mutationFn: () => apiClient.dismissRemediation(execution.id),
    onSuccess: () => {
      invalidate()
      toast.success("Remediation dismissed")
    },
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.message : "Could not dismiss"),
  })

  const riskPct =
    execution.risk_score != null ? `${Math.round(execution.risk_score * 100)}%` : "—"

  return (
    <li className={cn(
      "relative overflow-hidden rounded-lg border bg-surface-card p-3.5 transition-all duration-150 border-hairline-strong mb-2.5",
      execution.status === "pending_confirm" 
        ? "border-l-4 border-l-accent-orange bg-surface-card shadow-md shadow-accent-orange/2" 
        : execution.status === "succeeded" 
        ? "border-l-4 border-l-accent-green bg-surface-card/65" 
        : execution.status === "failed" 
        ? "border-l-4 border-l-accent-red bg-surface-card" 
        : "border-l-4 border-l-stone/30 bg-surface-card/50"
    )}>
      <div className="flex flex-wrap items-center justify-between gap-4">
        {/* Left side hook info */}
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 min-w-0">
          <div className="flex items-center gap-2.5">
            <StatusDot state={statusDot(execution.status)} />
            {getActionTypeIcon(execution.action_type, "size-4.5")}
            <span className="text-body-sm font-semibold text-ink">{execution.hook_name}</span>
            <Badge variant="secondary" className="h-[22px] inline-flex items-center text-[11px] leading-none select-none">
              {ACTION_LABELS[execution.action_type] ?? execution.action_type}
            </Badge>
            {statusBadge(execution.status)}
          </div>

          <div className="flex items-center gap-2 text-caption text-mute">
            <Link
              to={`/sites/${execution.site_id}/scans/${execution.scan_id}`}
              className="hover:underline text-mute font-medium"
            >
              {execution.site_name ?? "Unknown site"}
            </Link>
            <span>·</span>
            <span>risk</span>
            <span className="h-[22px] inline-flex items-center font-mono text-xs font-bold text-accent-red bg-accent-red/5 px-1.5 rounded border border-accent-red/20 leading-none">{riskPct}</span>
          </div>

          <span className="text-caption text-mute">
            Flagged {new Date(execution.created_at).toLocaleDateString()} at {new Date(execution.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
          </span>

          <span className="font-mono text-xs text-charcoal bg-surface-deep px-1.5 py-0.5 rounded border border-hairline select-none">
            {execution.id.slice(0, 8)}
          </span>
        </div>

        {/* Right side controls */}
        {canAct && execution.status === "pending_confirm" && (
          <div className="flex shrink-0 gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={confirm.isPending || dismiss.isPending}
              onClick={() => {
                if (
                  window.confirm(
                    `Fire the "${execution.hook_name}" webhook now? This tells your infrastructure to act.`
                  )
                ) {
                  confirm.mutate()
                }
              }}
              className="h-8 hover:-translate-y-[1px] active:scale-[0.97] transition-all px-2.5 text-caption font-semibold"
            >
              <Check className="mr-1.5 size-3.5 shrink-0 text-accent-green" />
              Confirm & Fire
            </Button>
            <Button
              variant="ghost"
              size="sm"
              disabled={confirm.isPending || dismiss.isPending}
              onClick={() => dismiss.mutate()}
              className="h-8 hover:bg-surface-elevated active:scale-[0.97] transition-all px-2.5 text-caption text-mute hover:text-ink font-semibold"
            >
              <X className="mr-1.5 size-3.5 shrink-0 text-accent-red" />
              Dismiss
            </Button>
          </div>
        )}
      </div>

      {execution.detail && (
        <div className="mt-2.5 rounded border border-hairline-strong/60 bg-surface-deep/30 p-2.5 font-mono text-code-md text-charcoal break-all leading-relaxed">
          {execution.detail}
        </div>
      )}
    </li>
  )
}

export function RemediationPage() {
  const { user } = useAuth()
  const canAct = user?.role === "admin" || user?.role === "analyst"
  const [page, setPage] = useState(0)
  const [pendingOnly, setPendingOnly] = useState(true)

  const executions = useQuery({
    queryKey: ["remediation-executions", { page, pendingOnly }],
    queryFn: () => apiClient.listRemediationExecutions(page * PAGE_SIZE, PAGE_SIZE, pendingOnly),
    refetchInterval: 15000,
  })

  const total = executions.data?.total ?? 0
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE))

  return (
    <div className="max-w-5xl mx-auto py-4">
      <div className="mb-8 flex flex-wrap items-end justify-between gap-4 border-b border-hairline pb-6">
        <div>
          <h1 className="text-display-lg text-ink font-display">Remediation</h1>
          <p className="mt-2 text-body-md text-charcoal">
            Outbound webhooks triggered by flagged scans. Manual confirmation is the default — nothing fires without an operator's approval here.
          </p>
        </div>
        <label className="flex items-center gap-2 px-3 py-1.5 rounded-full border border-hairline-strong bg-surface-card hover:bg-surface-elevated/40 cursor-pointer select-none text-body-sm text-charcoal transition-all">
          <input
            type="checkbox"
            checked={pendingOnly}
            onChange={(e) => {
              setPendingOnly(e.target.checked)
              setPage(0)
            }}
            className="size-3.5 accent-primary cursor-pointer rounded"
          />
          <span className="font-medium text-ink">Awaiting confirmation only</span>
        </label>
      </div>

      <div>
        {executions.isLoading ? (
          <div className="rounded-lg border border-hairline-strong bg-surface-card p-12 text-center">
            <p className="text-body-sm text-mute">Loading remediation queue…</p>
          </div>
        ) : executions.isError ? (
          <div className="rounded-lg border border-hairline-strong bg-surface-card p-12 text-center">
            <p className="text-body-sm text-accent-red font-medium">
              Could not load the remediation queue — is the API reachable?
            </p>
          </div>
        ) : (executions.data?.items.length ?? 0) > 0 ? (
          <ul className="space-y-2">
            {executions.data!.items.map((e) => (
              <ExecutionRow key={e.id} execution={e} canAct={canAct} />
            ))}
          </ul>
        ) : (
          <div className="flex flex-col items-center gap-3 p-16 text-center border border-dashed border-hairline-strong rounded-lg bg-surface-card/40">
            <div className="rounded-full bg-surface-deep border border-hairline p-4 mb-2">
              <Inbox className="size-8 text-mute/50" />
            </div>
            <p className="text-heading-sm font-semibold text-ink">
              {pendingOnly ? "Nothing awaiting confirmation" : "No remediation history"}
            </p>
            <p className="max-w-md text-body-sm text-charcoal leading-relaxed">
              Configure remediation webhooks on a site's detail page. When a flagged scan crosses your hook's trigger threshold, the firing wait-parks in this queue for validation.
            </p>
          </div>
        )}
      </div>

      {pageCount > 1 && (
        <div className="mt-6 flex items-center justify-end gap-2 border-t border-hairline pt-4">
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label="Newer"
            disabled={page === 0}
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            className="hover:bg-surface-elevated"
          >
            <ChevronLeft className="size-4" />
          </Button>
          <span className="text-caption text-mute font-medium px-2">
            {page + 1} / {pageCount}
          </span>
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label="Older"
            disabled={page >= pageCount - 1}
            onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))}
            className="hover:bg-surface-elevated"
          >
            <ChevronRight className="size-4" />
          </Button>
        </div>
      )}
    </div>
  )
}
