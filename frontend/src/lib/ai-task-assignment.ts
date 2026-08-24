import { ApiError } from "@/lib/api"

export type AiTaskKind = "explanation" | "agent_chat"

export interface AssignmentFailure {
  task: AiTaskKind
  message: string
}

/*
 * Assign one model to each wanted AI task, collecting per-task failures
 * instead of throwing on the first one or swallowing them silently
 * (Finding 8.7: a failed auto-assignment used to be invisible — the dialog
 * reported success while the model was never wired to the task). The
 * assigner is injected so callers bind the provider/model and tests can
 * stub it; surfacing the returned failures is the caller's job.
 */
export async function assignModelToTasks(
  assign: (task: AiTaskKind) => Promise<unknown>,
  tasks: { task: AiTaskKind; wanted: boolean }[],
): Promise<AssignmentFailure[]> {
  const failures: AssignmentFailure[] = []
  for (const { task, wanted } of tasks) {
    if (!wanted) continue
    try {
      await assign(task)
    } catch (err) {
      failures.push({
        task,
        message: err instanceof ApiError ? err.message : "request failed",
      })
    }
  }
  return failures
}
