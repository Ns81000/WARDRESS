/*
 * Site icon state machine: idle/loading → ok(objectUrl) | fallback. The
 * fetch carries the Authorization header (plain <img src> cannot), so
 * fetch+blob is a necessity, not a style choice.
 */

export type SiteIconState =
  | { phase: "loading" }
  | { phase: "ok"; url: string }
  | { phase: "fallback" }
