import { useMemo, useState } from "react"
import { ChevronDown, ChevronRight } from "lucide-react"

import { useTextArtifact } from "@/lib/use-artifact"
import { cn } from "@/lib/utils"

/*
 * DOM diff tree viewer — §4 Wardress-specific component, custom renderer
 * (no react-json-view, no default theme). Added nodes get a subtle
 * accent-green left border, removed nodes accent-red, both low opacity,
 * on the surface-card background. Explicitly NOT the bright text-on-black
 * "hacker movie" look — text stays in the standard ink/body lane and only
 * the border + a faint wash carry the diff state.
 *
 * Both captured pages are parsed with DOMParser into inert documents
 * (captured HTML never renders or executes in the dashboard origin), and
 * diffed structurally: children are matched by tag signature, unmatched
 * ones become "removed"/"added". Text is compared per node. This is a
 * presentation diff — the authoritative structural evidence is layer 2's.
 */

type DiffState = "same" | "added" | "removed" | "modified"

interface DiffNode {
  tag: string
  attrs: string // rendered attr summary, e.g. `id="x" class="y"`
  text: string | null
  state: DiffState
  children: DiffNode[]
  /** true when some descendant differs — used to auto-expand paths */
  hasChanges: boolean
}

const SKIP_TAGS = new Set(["#comment"])
const ATTR_LIMIT = 3
const TEXT_LIMIT = 80
const CHILD_LIMIT = 120 // safety cap per level for pathological pages

function attrSummary(el: Element): string {
  const parts: string[] = []
  for (const name of ["id", "class", "src", "href"]) {
    const v = el.getAttribute(name)
    if (v) parts.push(`${name}="${v.length > 40 ? v.slice(0, 37) + "…" : v}"`)
    if (parts.length >= ATTR_LIMIT) break
  }
  return parts.join(" ")
}

function ownText(el: Element): string | null {
  let text = ""
  for (const child of el.childNodes) {
    if (child.nodeType === Node.TEXT_NODE) text += child.textContent ?? ""
  }
  text = text.replace(/\s+/g, " ").trim()
  if (!text) return null
  return text.length > TEXT_LIMIT ? text.slice(0, TEXT_LIMIT - 1) + "…" : text
}

/** Signature used to pair up children across the two trees. */
function signature(el: Element): string {
  return `${el.tagName.toLowerCase()}#${el.id || ""}.${el.className && typeof el.className === "string" ? el.className : ""}`
}

function subtree(el: Element, state: DiffState): DiffNode {
  const children: DiffNode[] = []
  let count = 0
  for (const child of el.children) {
    if (count++ >= CHILD_LIMIT) break
    if (SKIP_TAGS.has(child.tagName)) continue
    children.push(subtree(child, state))
  }
  return {
    tag: el.tagName.toLowerCase(),
    attrs: attrSummary(el),
    text: ownText(el),
    state,
    children,
    hasChanges: state !== "same",
  }
}

function diffElements(before: Element, after: Element): DiffNode {
  // Pair children by signature (first unmatched occurrence wins) so
  // reordered-but-same lists don't diff as full remove+add.
  const beforeChildren = [...before.children].filter((c) => !SKIP_TAGS.has(c.tagName))
  const afterChildren = [...after.children].filter((c) => !SKIP_TAGS.has(c.tagName))
  const matchedBefore = new Set<number>()
  const pairs: (readonly [number | null, number])[] = afterChildren.map((a, ai) => {
    const sig = signature(a)
    const bi = beforeChildren.findIndex((b, i) => !matchedBefore.has(i) && signature(b) === sig)
    if (bi >= 0) matchedBefore.add(bi)
    return [bi >= 0 ? bi : null, ai] as const
  })

  const children: DiffNode[] = []
  // Removed children appear where they were in the baseline order.
  beforeChildren.forEach((b, bi) => {
    if (!matchedBefore.has(bi)) children.push(subtree(b, "removed"))
  })
  for (const [bi, ai] of pairs) {
    if (children.length >= CHILD_LIMIT) break
    if (bi === null) children.push(subtree(afterChildren[ai], "added"))
    else children.push(diffElements(beforeChildren[bi], afterChildren[ai]))
  }

  const textChanged = ownText(before) !== ownText(after)
  const hasChanges = textChanged || children.some((c) => c.hasChanges)
  return {
    tag: after.tagName.toLowerCase(),
    attrs: attrSummary(after),
    text: ownText(after) ?? ownText(before),
    state: textChanged ? "modified" : "same",
    children,
    hasChanges,
  }
}

export function buildDomDiff(baselineHtml: string, currentHtml: string): DiffNode | null {
  try {
    const parser = new DOMParser()
    const before = parser.parseFromString(baselineHtml, "text/html").documentElement
    const after = parser.parseFromString(currentHtml, "text/html").documentElement
    return diffElements(before, after)
  } catch {
    return null
  }
}

function stateClasses(state: DiffState): string {
  // Low-opacity washes + accent left border — never bright fills (§4).
  switch (state) {
    case "added":
      return "border-l-2 border-l-accent-green/50 bg-accent-green/[0.04]"
    case "removed":
      return "border-l-2 border-l-accent-red/50 bg-accent-red/[0.04] opacity-70"
    case "modified":
      return "border-l-2 border-l-accent-orange/40 bg-accent-orange/[0.04]"
    default:
      return "border-l-2 border-l-transparent"
  }
}

function NodeRow({ node, depth }: { node: DiffNode; depth: number }) {
  // Auto-expand any path that contains changes; collapsed otherwise.
  const [open, setOpen] = useState(node.hasChanges && depth < 12)
  const toggleable = node.children.length > 0

  return (
    <div className={cn("rounded-xs", stateClasses(node.state))}>
      <button
        type="button"
        disabled={!toggleable}
        onClick={() => setOpen((o) => !o)}
        className={cn(
          "flex w-full items-baseline gap-1.5 px-2 py-0.5 text-left text-code-md",
          toggleable && "cursor-pointer hover:bg-surface-elevated/60"
        )}
        style={{ paddingLeft: `${depth * 14 + 8}px` }}
      >
        {toggleable ? (
          open ? (
            <ChevronDown className="size-3 shrink-0 self-center text-mute" aria-hidden />
          ) : (
            <ChevronRight className="size-3 shrink-0 self-center text-mute" aria-hidden />
          )
        ) : (
          <span className="w-3 shrink-0" aria-hidden />
        )}
        <span className="text-body">&lt;{node.tag}&gt;</span>
        {node.attrs && <span className="truncate text-mute">{node.attrs}</span>}
        {node.text && <span className="truncate text-charcoal">{node.text}</span>}
        {node.state !== "same" && (
          <span
            className={cn(
              "ml-auto shrink-0 text-caption",
              node.state === "added" && "text-accent-green/80",
              node.state === "removed" && "text-accent-red/80",
              node.state === "modified" && "text-accent-orange/80"
            )}
          >
            {node.state}
          </span>
        )}
      </button>
      {open &&
        node.children.map((child, i) => <NodeRow key={i} node={child} depth={depth + 1} />)}
    </div>
  )
}

export function DomDiffTree({
  baselineHtmlPath,
  currentHtmlPath,
  className,
}: {
  baselineHtmlPath: string
  currentHtmlPath: string
  className?: string
}) {
  const baseline = useTextArtifact(baselineHtmlPath)
  const current = useTextArtifact(currentHtmlPath)

  const root = useMemo(() => {
    if (baseline.text == null || current.text == null) return null
    return buildDomDiff(baseline.text, current.text)
  }, [baseline.text, current.text])

  if (baseline.loading || current.loading) {
    return (
      <div className={cn("rounded-lg border border-hairline-strong bg-surface-card p-8", className)}>
        <p className="text-body-sm text-mute">Loading DOM snapshots…</p>
      </div>
    )
  }
  if (baseline.error || current.error || !root) {
    return (
      <div className={cn("rounded-lg border border-hairline-strong bg-surface-card p-8", className)}>
        <p className="text-body-sm text-mute">
          DOM snapshots unavailable for this comparison.
        </p>
      </div>
    )
  }

  return (
    <div className={cn("rounded-lg border border-hairline-strong bg-surface-card", className)}>
      <div className="flex items-center gap-4 border-b border-hairline px-4 py-2.5">
        <span className="flex items-center gap-1.5 text-caption text-charcoal">
          <span className="inline-block h-3 w-0.5 bg-accent-green/50" aria-hidden />
          Added
        </span>
        <span className="flex items-center gap-1.5 text-caption text-charcoal">
          <span className="inline-block h-3 w-0.5 bg-accent-red/50" aria-hidden />
          Removed
        </span>
        <span className="flex items-center gap-1.5 text-caption text-charcoal">
          <span className="inline-block h-3 w-0.5 bg-accent-orange/40" aria-hidden />
          Text changed
        </span>
        {!root.hasChanges && (
          <span className="ml-auto text-caption text-mute">No structural differences</span>
        )}
      </div>
      <div className="max-h-[480px] overflow-auto py-2">
        <NodeRow node={root} depth={0} />
      </div>
    </div>
  )
}
