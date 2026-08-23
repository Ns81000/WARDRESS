/*
 * Pure logic for the local site avatar. The avatar replaces the
 * third-party favicon service this product previously sent every monitored
 * hostname to on each dashboard view: it is generated entirely client-side
 * from the hostname alone — no network request, air-gap safe.
 */

// Complete class strings so Tailwind's scanner sees every variant.
const TONES = [
  "bg-accent-blue/15 text-accent-blue",
  "bg-accent-green/15 text-accent-green",
  "bg-accent-orange/15 text-accent-orange",
  "bg-accent-red/10 text-accent-red",
  "bg-purple-500/15 text-purple-400",
  "bg-cyan-500/15 text-cyan-300",
] as const

function fnv1a(text: string): number {
  let hash = 0x811c9dc5
  for (let i = 0; i < text.length; i++) {
    hash ^= text.charCodeAt(i)
    hash = Math.imul(hash, 0x01000193)
  }
  return hash >>> 0
}

export function siteAvatarFor(url: string): { initial: string; tone: string } {
  let hostname = ""
  try {
    hostname = new URL(url).hostname
  } catch {
    hostname = ""
  }
  const first = [...hostname].find((ch) => /[a-z0-9]/i.test(ch))
  const initial = first ? first.toUpperCase() : "?"
  const tone = TONES[fnv1a(hostname) % TONES.length]
  return { initial, tone }
}
