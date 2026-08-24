/*
 * SVG path-data validation for Finding 8.6's defect class.
 *
 * The topology scheduler icon's Python-logo path carried an arc command
 * missing its second radius parameter (`a1.393 0 0 1-1.395-1.395` — six
 * arguments where SVG 1.1 requires seven). Chromium dropped the malformed
 * subpath and logged a console error on every health-page visit. The two
 * copies of that icon had drifted apart precisely because the path data
 * was pasted rather than validated anywhere.
 *
 * This suite parses EVERY inline `d="..."` attribute under src/ against
 * the SVG 1.1 path grammar's per-command argument counts (arc commands
 * take rx ry x-axis-rotation large-arc-flag sweep-flag x y = 7), so any
 * future paste corruption or hand edit that unbalances a command fails
 * CI loudly instead of shipping a broken glyph.
 */
import { readFileSync, readdirSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"

const SRC_ROOT = join(import.meta.dirname, "..", "src")

// Argument count of one repeating group per SVG path command.
const ARITY: Record<string, number> = {
  M: 2,
  L: 2,
  H: 1,
  V: 1,
  C: 6,
  S: 4,
  Q: 4,
  T: 2,
  A: 7,
  Z: 0,
}

const NUMBER_RE = /[+-]?(?:\d*\.\d+|\d+\.?)(?:[eE][+-]?\d+)?/y

function collectFiles(dir: string): string[] {
  const out: string[] = []
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name)
    if (entry.isDirectory()) out.push(...collectFiles(full))
    else if (/\.tsx?$/.test(entry.name)) out.push(full)
  }
  return out
}

function extractPathData(source: string): { d: string; line: number }[] {
  const found: { d: string; line: number }[] = []
  const attrRe = /\bd="([^"]*)"/g
  let m: RegExpExecArray | null
  while ((m = attrRe.exec(source)) !== null) {
    if (!m[1]) continue
    const line = source.slice(0, m.index).split("\n").length
    found.push({ d: m[1], line })
  }
  return found
}

/**
 * Returns null when `d` is grammatically valid, else a description of the
 * first violation. Arc flag positions are read as single '0'/'1' characters
 * per spec (so `0 0 1-1.395` tokenizes correctly), everything else as full
 * numbers.
 */
export function validatePathData(d: string): string | null {
  let i = 0
  let cmd = ""
  let cycleLen = 0
  let pos = 0

  const skipSeparators = () => {
    while (i < d.length && (d[i] === " " || d[i] === "\t" || d[i] === "\n" || d[i] === ",")) i++
  }
  const readNumber = (): boolean => {
    skipSeparators()
    NUMBER_RE.lastIndex = i
    const m = NUMBER_RE.exec(d)
    if (!m || m[0].length === 0) return false
    i = NUMBER_RE.lastIndex
    return true
  }
  const readFlag = (): boolean => {
    skipSeparators()
    if (d[i] === "0" || d[i] === "1") {
      i++
      return true
    }
    return false
  }

  while (i < d.length) {
    skipSeparators()
    if (i >= d.length) break
    const ch = d[i]
    if (/[a-zA-Z]/.test(ch)) {
      const upper = ch.toUpperCase()
      if (!(upper in ARITY)) return `unknown command '${ch}'`
      cmd = ch
      cycleLen = ARITY[upper]
      pos = 0
      i++
      continue
    }
    if (!cmd) return `number before any command`
    if (cycleLen === 0) return `arguments after closepath '${cmd}'`
    if (cmd.toUpperCase() === "A") {
      // Positions within each 7-arg group: 3 = large-arc-flag, 4 = sweep-flag.
      const ok = pos === 3 || pos === 4 ? readFlag() : readNumber()
      if (!ok) {
        return pos === 3 || pos === 4
          ? `arc flag missing or invalid in '${cmd}' (offset ${i})`
          : `expected a number in '${cmd}' (offset ${i})`
      }
    } else if (!readNumber()) {
      return `expected ${cycleLen} arguments per '${cmd}' group; ran out at offset ${i}`
    }
    pos = (pos + 1) % cycleLen
  }
  if (cmd && cycleLen > 0 && pos !== 0) {
    return `trailing partial '${cmd}' group (${pos} of ${cycleLen} arguments)`
  }
  return null
}

describe("inline SVG path data integrity", () => {
  it("every d attribute under src/ satisfies the SVG 1.1 path grammar", () => {
    const violations: string[] = []
    for (const file of collectFiles(SRC_ROOT)) {
      const source = readFileSync(file, "utf8")
      for (const { d, line } of extractPathData(source)) {
        const error = validatePathData(d)
        if (error) {
          violations.push(`${file}:${line} — ${error} (d starts "${d.slice(0, 60)}…")`)
        }
      }
    }
    expect(violations).toEqual([])
  })

  it("rejects an arc command missing its second radius (the filed defect shape)", () => {
    // Six arguments where the grammar requires seven: Chromium logs
    // "Expected arc flag ('0' or '1')" and drops the subpath.
    const malformed = "M31.885 16zm-4.275 2.454a1.394 1.394 0 1 1 0 2.79 1.393 0 0 1-1.395-1.395c0-.771z"
    expect(validatePathData(malformed)).toMatch(/arc flag|ran out|expected/i)
    // The repaired sibling shape parses cleanly.
    const repaired = "M31.885 16zm-4.275 2.454a1.394 1.394 0 1 1 0 2.79 1.393 1.393 0 0 1-1.395-1.395c0-.771z"
    expect(validatePathData(repaired)).toBeNull()
  })
})
