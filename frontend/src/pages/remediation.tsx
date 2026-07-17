import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Check, ChevronLeft, ChevronRight, X } from "lucide-react"
import { Link } from "react-router"
import { toast } from "sonner"

import { StatusDot, type DotState } from "@/components/status-dot"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import * as apiClient from "@/lib/api"
import { ApiError, type RemediationExecution } from "@/lib/api"
import { useAuth } from "@/lib/auth"

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
      return <Badge variant="pending">Awaiting confirmation</Badge>
    case "queued":
      return <Badge variant="pending">Queued</Badge>
    case "succeeded":
      return <Badge variant="clean">Succeeded</Badge>
    case "failed":
      return <Badge variant="threat">Failed</Badge>
    default:
      return <Badge variant="secondary">Dismissed</Badge>
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
    <li className="border-b border-hairline p-5 last:border-b-0">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-3">
            <StatusDot state={statusDot(execution.status)} />
            <span className="text-heading-sm text-ink">{execution.hook_name}</span>
            <Badge variant="secondary">
              {ACTION_LABELS[execution.action_type] ?? execution.action_type}
            </Badge>
            {statusBadge(execution.status)}
          </div>
          <p className="mt-1 text-caption text-mute">
            <Link
              to={`/sites/${execution.site_id}/scans/${execution.scan_id}`}
              className="hover:underline"
            >
              {execution.site_name ?? "Unknown site"}
            </Link>
            {" · risk "}
            <span className="text-code-md text-accent-red">{riskPct}</span>
            {" · flagged "}
            {new Date(execution.created_at).toLocaleString()}
            {execution.executed_at &&
              ` · executed ${new Date(execution.executed_at).toLocaleString()}`}
          </p>
          {execution.detail && (
            <p className="mt-1 text-body-sm text-charcoal">{execution.detail}</p>
          )}
        </div>
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
            >
              <Check />
              Confirm and fire
            </Button>
            <Button
              variant="ghost"
              size="sm"
              disabled={confirm.isPending || dismiss.isPending}
              onClick={() => dismiss.mutate()}
            >
              <X />
              Dismiss
            </Button>
          </div>
        )}
      </div>
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
    <div>
      <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-display-lg text-ink">Remediation</h1>
          <p className="mt-2 text-body-md text-charcoal">
            Outbound webhooks triggered by flagged scans. Manual confirmation
            is the default — nothing fires without a decision here.
          </p>
        </div>
        <label className="flex cursor-pointer items-center gap-2 text-body-sm text-charcoal">
          <input
            type="checkbox"
            checked={pendingOnly}
            onChange={(e) => {
              setPendingOnly(e.target.checked)
              setPage(0)
            }}
            className="size-4 accent-ink"
          />
          Awaiting confirmation only
        </label>
      </div>

      <div className="rounded-lg border border-hairline-strong bg-surface-card">
        {executions.isLoading ? (
          <p className="p-8 text-body-sm text-mute">Loading remediation queue…</p>
        ) : executions.isError ? (
          <p className="p-8 text-body-sm text-accent-red">
            Could not load the remediation queue.
          </p>
        ) : (executions.data?.items.length ?? 0) > 0 ? (
          <ul>
            {executions.data!.items.map((e) => (
              <ExecutionRow key={e.id} execution={e} canAct={canAct} />
            ))}
          </ul>
        ) : (
          <div className="flex flex-col items-center gap-3 p-16 text-center">
            <p className="text-heading-sm text-ink">
              {pendingOnly ? "Nothing awaiting confirmation" : "No remediation history"}
            </p>
            <p className="max-w-md text-body-sm text-charcoal">
              Configure remediation hooks on a site&rsquo;s detail page. When a
              flagged scan crosses a hook&rsquo;s threshold, its firing waits here
              for your confirmation.
            </p>
          </div>
        )}
      </div>

      {pageCount > 1 && (
        <div className="mt-4 flex items-center justify-end gap-2">
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label="Newer"
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
            aria-label="Older"
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
