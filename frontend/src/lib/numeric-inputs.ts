/*
 * Strict numeric parsing for config inputs where silently coercing garbage
 * to a default would save values the user never typed (Finding 8.7: a hook
 * trigger threshold of "abc" submitted 0.5; an SMTP port of "abc" submitted
 * 587 — both with a success toast). Blank/whitespace, non-numeric and
 * out-of-range input are rejected as null; callers surface an inline error
 * or toast instead of submitting.
 */

/** Decimal in [min, max]; blank, NaN/Infinity and out-of-range return null. */
export function parseDecimalInRange(raw: string, min: number, max: number): number | null {
  const trimmed = raw.trim()
  if (!trimmed) return null
  const value = Number(trimmed)
  if (!Number.isFinite(value) || value < min || value > max) return null
  return value
}

/** Whole TCP port in [1, 65535] — digits only; anything else returns null. */
export function parsePort(raw: string): number | null {
  const trimmed = raw.trim()
  if (!trimmed || !/^\d+$/.test(trimmed)) return null
  const port = Number(trimmed)
  if (port < 1 || port > 65535) return null
  return port
}
