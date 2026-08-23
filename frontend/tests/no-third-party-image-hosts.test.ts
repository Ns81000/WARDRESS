import { readFileSync, readdirSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"

// Tripwire: the dashboard must never construct image URLs pointing at
// third-party hosts. The previous implementation disclosed every monitored
// hostname to an external favicon service and fanned provider-logo requests
// out across five CDNs (one pinned to a moving branch). All imagery is now
// bundled same-origin or generated locally; this scan keeps it that way by
// failing loudly if any banned host literal reappears in src/.
const BANNED_HOSTS = [
  "google.com/s2/favicons",
  "svgl.app",
  "cdn.jsdelivr.net",
  "cdn.simpleicons.org",
  "api.iconify.design",
  "models.dev/logos",
]

function listFiles(dir: string): string[] {
  const out: string[] = []
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name)
    if (entry.isDirectory()) out.push(...listFiles(full))
    else if (/\.(ts|tsx|css)$/.test(entry.name)) out.push(full)
  }
  return out
}

describe("no third-party image hosts in frontend source", () => {
  it("src/ contains no reference to any external image CDN", () => {
    const srcDir = join(__dirname, "..", "src")
    const offenders: string[] = []
    for (const file of listFiles(srcDir)) {
      const text = readFileSync(file, "utf8")
      for (const host of BANNED_HOSTS) {
        if (text.includes(host)) offenders.push(`${file}: ${host}`)
      }
    }
    expect(offenders).toEqual([])
  })
})
