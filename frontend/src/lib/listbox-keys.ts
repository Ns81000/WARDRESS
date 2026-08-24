/*
 * Shared keyboard model for the app's listbox-style dropdown menus
 * (ui/select.tsx and the hand-rolled menu variants in users-card,
 * remediation-hooks-panel, audit). Pure so every menu behaves identically
 * and the contract stays unit-testable.
 *
 * Escape is intentionally absent: it must also work while focus is on the
 * trigger or elsewhere in the open menu, so each menu owns it via its
 * window-level listener.
 */
export type ListboxAction =
  | "prev"
  | "next"
  | "first"
  | "last"
  | "commit"
  | "dismiss"

export function listboxAction(
  key: string,
  index: number,
  count: number
): ListboxAction | null {
  switch (key) {
    case "ArrowDown":
      return index < count - 1 ? "next" : null
    case "ArrowUp":
      return index > 0 ? "prev" : null
    case "Home":
      return index !== 0 ? "first" : null
    case "End":
      return index !== count - 1 ? "last" : null
    case "Enter":
    case " ":
      // Handled here (with the event default-prevented) rather than left
      // to native button activation so the behavior is identical in every
      // environment and can never double-fire.
      return "commit"
    case "Tab":
      // Let Tab proceed naturally (focus leaves the open menu) without the
      // close path yanking focus back to the trigger.
      return "dismiss"
    default:
      return null
  }
}
