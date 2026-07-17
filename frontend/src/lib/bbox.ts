/*
 * Normalized bounding-box helpers shared by the visual diff slider, the
 * suppression region picker, and the API layer. A Region is expressed in
 * fractions of the full-page screenshot (resolution-independent), and
 * serializes to the API's "x,y,w,h" bbox rule value.
 */

export interface Region {
  x: number
  y: number
  w: number
  h: number
}

/** Parse a stored bbox rule value ("x,y,w,h" fractions) for display. */
export function parseBboxValue(value: string): Region | null {
  const parts = value.split(",").map(Number)
  if (parts.length !== 4 || parts.some((n) => !Number.isFinite(n))) return null
  const [x, y, w, h] = parts
  if (x < 0 || y < 0 || w <= 0 || h <= 0 || x + w > 1.0001 || y + h > 1.0001) return null
  return { x, y, w, h }
}

/** Serialize a drawn region to the API's bbox value format. */
export function bboxValue(r: Region): string {
  const f = (n: number) => Math.min(1, Math.max(0, Math.round(n * 10000) / 10000))
  return `${f(r.x)},${f(r.y)},${f(r.w)},${f(r.h)}`
}
