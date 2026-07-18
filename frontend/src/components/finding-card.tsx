import { useState } from "react"
import { ChevronDown, ChevronRight } from "lucide-react"

import { StatusDot, type DotState } from "@/components/status-dot"
import { Badge } from "@/components/ui/badge"
import type { ScanFinding } from "@/lib/api"
import { cn } from "@/lib/utils"

/*
 * Per-layer evidence viewer for the scan drilldown (§5: evidence is
 * never just a bare number). Each layer gets a purpose-built renderer
 * for its evidence dict — matched signatures, added/removed links and
 * domains, header diffs, TLS changes, UA-variant comparison — with a
 * generic key/value fallback for anything unrecognized so no evidence
 * is ever silently dropped.
 */

export const LAYER_TITLES: Record<string, string> = {
  layer1_hash: "Content hash",
  layer2_dom_structure: "DOM structure",
  layer3_link_audit: "Links & scripts",
  layer4_visual_diff: "Visual diff",
  layer5_signatures: "Signature match",
  layer6_security_metadata: "Security metadata",
  layer7_cloaking: "Cloaking probe",
  layer8_semantics: "Semantic analysis",
  layer9_fusion: "Fused risk",
}

export const LAYER_BLURBS: Record<string, string> = {
  layer1_hash: "SHA-256 of normalized content against the baseline",
  layer2_dom_structure: "Tag-tree churn, script/iframe/hidden-element deltas",
  layer3_link_audit: "Reference-set diff — new external domains weigh heaviest",
  layer4_visual_diff: "SSIM + perceptual hashes over the full-page screenshots",
  layer5_signatures: "Known defacement phrasing, profanity bursts, script flips",
  layer6_security_metadata: "TLS certificate, security headers, robots.txt",
  layer7_cloaking: "Per-User-Agent content divergence (crawler vs browser)",
  layer8_semantics: "Aggression lexicon, topic keywords, embedding drift",
  layer9_fusion: "Calibrated combination of all eight sub-scores",
}

export function scoreTone(score: number | null): string {
  if (score == null) return "text-mute"
  if (score >= 0.5) return "text-accent-red"
  if (score >= 0.15) return "text-accent-orange"
  return "text-accent-green"
}

export function dotFor(finding: ScanFinding): DotState {
  if (finding.skipped) return "idle"
  const s = finding.score ?? 0
  if (s >= 0.5) return "threat"
  if (s >= 0.15) return "pending"
  return "clean"
}

// --- small building blocks ---

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <p className="text-caption font-medium text-charcoal">{title}</p>
      {children}
    </div>
  )
}

function Mono({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <span className={cn("rounded-xs bg-surface-deep px-1.5 py-0.5 text-code-md break-all", className)}>
      {children}
    </span>
  )
}

function UrlList({ urls, tone }: { urls: string[]; tone?: "added" | "removed" }) {
  if (!urls.length) return null
  return (
    <div className="overflow-y-auto max-h-[160px] border border-hairline bg-surface-deep/30 rounded-md p-2">
      <ul className="space-y-1">
        {urls.map((u) => (
          <li key={u} className="flex items-start gap-1.5">
            <span
              className={cn(
                "mt-1.5 inline-block size-1.5 shrink-0 rounded-full",
                tone === "added" && "bg-accent-red/70",
                tone === "removed" && "bg-stone",
                !tone && "bg-mute"
              )}
              aria-hidden
            />
            <Mono>{u}</Mono>
          </li>
        ))}
      </ul>
    </div>
  )
}

function KV({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-divider-soft py-1 last:border-0">
      <span className="text-caption text-mute">{label}</span>
      <span className="text-body-sm text-body">{value}</span>
    </div>
  )
}

/** Generic fallback: flat key/value rendering so unknown evidence keys
 * are still visible rather than silently dropped. */
export function GenericEvidence({ evidence }: { evidence: Record<string, unknown> }) {
  return (
    <div>
      {Object.entries(evidence).map(([k, v]) => (
        <KV
          key={k}
          label={k}
          value={
            typeof v === "object" && v !== null ? (
              <Mono>{JSON.stringify(v).slice(0, 400)}</Mono>
            ) : (
              String(v)
            )
          }
        />
      ))}
    </div>
  )
}

// --- per-layer renderers ---

export function HashEvidence({ e }: { e: Record<string, unknown> }) {
  const isIdentical = e.identical === true
  return (
    <div className="space-y-4">
      <div className={cn(
        "rounded-md border p-3 flex items-center justify-between",
        isIdentical ? "bg-accent-green/5 border-accent-green/20" : "bg-accent-red/5 border-accent-red/20"
      )}>
        <span className="text-body-sm font-medium text-ink">Identical Content Hash</span>
        <span className={cn(
          "text-body-sm font-mono font-semibold px-2 py-0.5 rounded",
          isIdentical ? "bg-accent-green/20 text-accent-green" : "bg-accent-red/20 text-accent-red"
        )}>
          {isIdentical ? "Yes" : "No"}
        </span>
      </div>
      
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="relative overflow-hidden rounded-md border border-hairline bg-surface-deep p-4 flex flex-col justify-between">
          <div className="absolute left-0 top-0 bottom-0 w-1 bg-accent-red/50" />
          <div>
            <p className="text-caption font-mono text-mute mb-1">Baseline SHA-256</p>
            <p className="font-mono text-code-md text-accent-red/90 break-all select-all">{String(e.baseline_sha256 ?? "—")}</p>
          </div>
        </div>
        
        <div className="relative overflow-hidden rounded-md border border-hairline bg-surface-deep p-4 flex flex-col justify-between">
          <div className="absolute left-0 top-0 bottom-0 w-1 bg-accent-green/50" />
          <div>
            <p className="text-caption font-mono text-mute mb-1">Current SHA-256</p>
            <p className="font-mono text-code-md text-accent-green/90 break-all select-all">{String(e.current_sha256 ?? "—")}</p>
          </div>
        </div>
      </div>
    </div>
  )
}

export function DomEvidence({ e }: { e: Record<string, unknown> }) {
  const counts = (key: string) => e[key] as { baseline?: number; current?: number } | undefined
  const tagMap = (key: string) => (e[key] ?? {}) as Record<string, number>
  const added = Object.entries(tagMap("tags_added"))
  const removed = Object.entries(tagMap("tags_removed"))
  
  const metrics = [
    { key: "script_count", label: "Scripts" },
    { key: "iframe_count", label: "Iframes" },
    { key: "hidden_count", label: "Hidden Elements" },
  ] as const

  const baselineElements = e.baseline_elements as number | undefined
  const currentElements = e.current_elements as number | undefined

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {metrics.map((m) => {
          const c = counts(m.key)
          const baseline = c?.baseline ?? 0
          const current = c?.current ?? 0
          const diff = current - baseline
          const grew = diff > 0
          
          return (
            <div key={m.key} className="rounded-lg border border-hairline bg-surface-deep/40 p-4 flex flex-col justify-between hover:border-hairline-strong transition-colors">
              <span className="text-caption text-mute font-medium">{m.label}</span>
              <div className="mt-2 flex items-baseline gap-2">
                <span className="text-heading-sm font-bold text-ink">{current}</span>
                {diff !== 0 && (
                  <span className={cn(
                    "text-caption font-semibold font-mono",
                    grew ? "text-accent-red" : "text-accent-green"
                  )}>
                    {grew ? `+${diff}` : diff}
                  </span>
                )}
              </div>
              <span className="mt-1 text-caption text-stone">baseline: {baseline}</span>
            </div>
          )
        })}

        {/* Total Elements Card */}
        <div className="rounded-lg border border-hairline bg-surface-deep/40 p-4 flex flex-col justify-between hover:border-hairline-strong transition-colors">
          <span className="text-caption text-mute font-medium">Total Elements</span>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-heading-sm font-bold text-ink">{currentElements ?? 0}</span>
            {baselineElements !== undefined && currentElements !== undefined && (currentElements - baselineElements !== 0) && (
              <span className={cn(
                "text-caption font-semibold font-mono",
                (currentElements - baselineElements) > 0 ? "text-accent-red" : "text-accent-green"
              )}>
                {(currentElements - baselineElements) > 0 ? `+${currentElements - baselineElements}` : currentElements - baselineElements}
              </span>
            )}
          </div>
          <span className="mt-1 text-caption text-stone">baseline: {baselineElements ?? 0}</span>
        </div>
      </div>

      {(added.length > 0 || removed.length > 0) && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 pt-2">
          {added.length > 0 && (
            <div className="rounded-lg border border-hairline bg-surface-deep/20 p-4">
              <h4 className="text-caption font-medium text-mute mb-2">Tags Added</h4>
              <div className="flex flex-wrap gap-1.5">
                {added.map(([tag, n]) => (
                  <Badge key={tag} variant="threat">{`<${tag}> ×${n}`}</Badge>
                ))}
              </div>
            </div>
          )}
          
          {removed.length > 0 && (
            <div className="rounded-lg border border-hairline bg-surface-deep/20 p-4">
              <h4 className="text-caption font-medium text-mute mb-2">Tags Removed</h4>
              <div className="flex flex-wrap gap-1.5">
                {removed.map(([tag, n]) => (
                  <Badge key={tag} variant="secondary">{`<${tag}> ×${n}`}</Badge>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

const REF_KIND_LABELS: Record<string, string> = {
  script_src: "Script sources",
  iframe_src: "Iframe sources",
  form_action: "Form targets",
  link_href: "Stylesheet / link refs",
  a_href: "Anchor links",
}

function LinksEvidence({ e }: { e: Record<string, unknown> }) {
  const kinds = Object.keys(REF_KIND_LABELS).filter((k) => {
    const v = e[k] as { added_count?: number; removed_count?: number } | undefined
    return v && ((v.added_count ?? 0) > 0 || (v.removed_count ?? 0) > 0)
  })
  if (!kinds.length)
    return <p className="text-body-sm text-mute">No reference-set changes.</p>
  return (
    <div className="space-y-4">
      {kinds.map((k) => {
        const v = e[k] as {
          added?: string[]
          removed?: string[]
          added_new_domains?: string[]
        }
        return (
          <div key={k} className="space-y-2">
            <p className="text-body-sm font-medium text-ink">{REF_KIND_LABELS[k]}</p>
            {(v.added_new_domains?.length ?? 0) > 0 && (
              <Section title="Pointing at never-seen domains">
                <UrlList urls={v.added_new_domains!} tone="added" />
              </Section>
            )}
            {(v.added?.length ?? 0) > 0 && (
              <Section title={`Added (${v.added!.length})`}>
                <UrlList
                  urls={v.added!.filter((u) => !v.added_new_domains?.includes(u))}
                  tone="added"
                />
              </Section>
            )}
            {(v.removed?.length ?? 0) > 0 && (
              <Section title={`Removed (${v.removed!.length})`}>
                <UrlList urls={v.removed!} tone="removed" />
              </Section>
            )}
          </div>
        )
      })}
    </div>
  )
}

function VisualEvidence({ e }: { e: Record<string, unknown> }) {
  return (
    <div className="grid grid-cols-2 gap-x-6 sm:grid-cols-3">
      <KV label="SSIM (1 = identical)" value={String(e.ssim ?? "—")} />
      <KV
        label="pHash distance"
        value={`${String(e.phash_distance_bits ?? "—")} / ${String(e.hash_bits ?? "—")} bits`}
      />
      <KV
        label="dHash distance"
        value={`${String(e.dhash_distance_bits ?? "—")} / ${String(e.hash_bits ?? "—")} bits`}
      />
      {Array.isArray(e.suppressed_regions) && e.suppressed_regions.length > 0 && (
        <KV label="Suppressed regions" value={`${e.suppressed_regions.length} masked`} />
      )}
    </div>
  )
}

function SignaturesEvidence({ e }: { e: Record<string, unknown> }) {
  const matches = (e.signature_matches ?? []) as { matched: string; weight: number }[]
  const profanity = (e.profanity_matches ?? []) as string[]
  return (
    <div className="space-y-3">
      {matches.length > 0 ? (
        <Section title={`Matched phrases (${matches.length})`}>
          <div className="overflow-y-auto max-h-[160px] border border-hairline bg-surface-deep/30 rounded-md p-2">
            <ul className="space-y-1">
              {matches.map((m, i) => (
                <li key={i} className="flex items-center gap-2">
                  <Badge variant={m.weight >= 0.9 ? "threat" : "pending"}>
                    {m.weight >= 0.9 ? "strong" : m.weight >= 0.5 ? "medium" : "weak"}
                  </Badge>
                  <Mono>{m.matched}</Mono>
                </li>
              ))}
            </ul>
          </div>
        </Section>
      ) : (
        <p className="text-body-sm text-mute">No signature phrases matched.</p>
      )}
      {profanity.length > 0 && (
        <KV label="Profanity burst" value={`${profanity.length} match(es) in new text`} />
      )}
      {e.script_flip === true && (
        <KV
          label="Dominant script flipped"
          value={
            <span className="text-accent-red">
              {String(e.baseline_dominant_script)} → {String(e.current_dominant_script)}
            </span>
          }
        />
      )}
    </div>
  )
}

function MetadataEvidence({ e }: { e: Record<string, unknown> }) {
  const tls = (e.tls ?? {}) as Record<string, unknown>
  const headers = (e.headers ?? {}) as Record<string, unknown>
  const robots = (e.robots_txt ?? {}) as Record<string, unknown>
  const removed = (headers.security_headers_removed ?? []) as string[]
  const changed = (headers.security_headers_changed ?? []) as {
    header: string
    baseline: string
    current: string
  }[]
  const added = (headers.security_headers_added ?? []) as string[]
  return (
    <div className="space-y-4">
      <Section title="TLS certificate">
        {tls.note ? (
          <p className="text-body-sm text-mute">{String(tls.note)}</p>
        ) : (
          <div>
            <KV
              label="Fingerprint changed"
              value={
                tls.fingerprint_changed ? (
                  <span className={tls.issuer_changed || tls.subject_changed ? "text-accent-red" : "text-accent-orange"}>
                    Yes{tls.issuer_changed ? " — different issuer" : ""}
                    {tls.subject_changed ? " — different subject" : ""}
                  </span>
                ) : (
                  "No"
                )
              }
            />
            {tls.expired === true && (
              <KV label="Expired" value={<span className="text-accent-red">Yes</span>} />
            )}
            {tls.fingerprint_changed === true && (
              <>
                <KV label="Baseline issuer" value={<Mono>{String(tls.baseline_issuer ?? "—")}</Mono>} />
                <KV label="Current issuer" value={<Mono>{String(tls.current_issuer ?? "—")}</Mono>} />
              </>
            )}
            <KV label="Valid until" value={String(tls.current_not_after ?? "—")} />
          </div>
        )}
      </Section>
      <Section title="Security headers">
        {headers.note ? (
          <p className="text-body-sm text-mute">{String(headers.note)}</p>
        ) : removed.length + changed.length + added.length === 0 ? (
          <p className="text-body-sm text-mute">No security-header changes.</p>
        ) : (
          <div className="space-y-2">
            {removed.length > 0 && (
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="text-caption text-accent-red">Removed:</span>
                {removed.map((h) => (
                  <Badge key={h} variant="threat">{h}</Badge>
                ))}
              </div>
            )}
            {changed.map((c) => (
              <div key={c.header} className="space-y-1">
                <p className="text-caption text-accent-orange">{c.header} changed</p>
                <Mono className="block">− {c.baseline}</Mono>
                <Mono className="block">+ {c.current}</Mono>
              </div>
            ))}
            {added.length > 0 && (
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="text-caption text-accent-green">Added:</span>
                {added.map((h) => (
                  <Badge key={h} variant="clean">{h}</Badge>
                ))}
              </div>
            )}
          </div>
        )}
      </Section>
      {robots.changed === true && (
        <Section title="robots.txt">
          <div className="overflow-y-auto max-h-[160px] border border-hairline bg-surface-deep/30 rounded-md p-2 space-y-1">
            {((robots.lines_removed ?? []) as string[]).map((l, i) => (
              <Mono key={`r${i}`} className="block text-accent-red/80">− {l}</Mono>
            ))}
            {((robots.lines_added ?? []) as string[]).map((l, i) => (
              <Mono key={`a${i}`} className="block text-accent-green/80">+ {l}</Mono>
            ))}
          </div>
        </Section>
      )}
    </div>
  )
}

function CloakingEvidence({ e }: { e: Record<string, unknown> }) {
  const variants = (e.variants ?? []) as {
    ua: string
    http_status?: number
    comparable?: boolean
    similarity?: number
    identical_hash?: boolean
    note?: string
    error?: string
  }[]
  if (e.note) return <p className="text-body-sm text-mute">{String(e.note)}</p>
  return (
    <div className="space-y-2">
      <p className="text-caption text-mute">
        Each rotated User-Agent compared against the desktop reference fetch
      </p>
      {variants.map((v) => (
        <div
          key={v.ua}
          className="flex items-center justify-between gap-4 rounded-md border border-hairline bg-surface-deep px-3 py-2"
        >
          <div className="flex items-center gap-2">
            <Mono>{v.ua}</Mono>
            <span className="text-caption text-mute">HTTP {v.http_status ?? "—"}</span>
          </div>
          {v.comparable ? (
            <span
              className={cn(
                "text-body-sm",
                (v.similarity ?? 1) < 0.5 ? "text-accent-red" : "text-accent-green"
              )}
            >
              {v.identical_hash ? "identical" : `similarity ${v.similarity}`}
            </span>
          ) : (
            <span className="text-caption text-mute">{v.note ?? v.error ?? "not comparable"}</span>
          )}
        </div>
      ))}
    </div>
  )
}

function SemanticsEvidence({ e }: { e: Record<string, unknown> }) {
  const aggression = (e.aggression_hits ?? []) as { matched: string; weight: number }[]
  const topics = (e.topic_hits ?? {}) as Record<string, string[]>
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-x-6">
        <KV
          label="Semantic similarity"
          value={
            e.semantic_similarity == null ? (
              "unavailable"
            ) : (
              <span className={Number(e.semantic_similarity) < 0.5 ? "text-accent-red" : undefined}>
                {String(e.semantic_similarity)}
              </span>
            )
          }
        />
        <KV label="New visible text" value={`${String(e.new_text_chars ?? 0)} chars`} />
      </div>
      {aggression.length > 0 && (
        <Section title="Aggression lexicon hits">
          <div className="flex flex-wrap gap-1.5">
            {aggression.map((a, i) => (
              <Badge key={i} variant="pending">{a.matched}</Badge>
            ))}
          </div>
        </Section>
      )}
      {Object.keys(topics).length > 0 && (
        <Section title="Topic keywords">
          {Object.entries(topics).map(([topic, hits]) => (
            <div key={topic} className="flex flex-wrap items-center gap-1.5">
              <span className="text-caption text-charcoal">{topic.replaceAll("_", " ")}:</span>
              {hits.map((h, i) => (
                <Mono key={i}>{h}</Mono>
              ))}
            </div>
          ))}
        </Section>
      )}
    </div>
  )
}

function FusionEvidence({ e }: { e: Record<string, unknown> }) {
  const features = (e.features ?? {}) as Record<string, number>
  const ran = (e.layers_ran ?? {}) as Record<string, boolean>
  return (
    <div className="space-y-3">
      <KV label="Model" value={String(e.model ?? "—")} />
      <Section title="Per-layer inputs">
        <div className="space-y-1.5">
          {Object.entries(features).map(([k, v]) => (
            <div key={k} className="flex items-center gap-3">
              <span className="w-44 shrink-0 text-caption text-mute">
                {LAYER_TITLES[k] ?? k}
              </span>
              <div className="h-1 flex-1 overflow-hidden rounded-full bg-surface-elevated">
                <div
                  className={cn(
                    "h-full rounded-full",
                    v >= 0.5 ? "bg-accent-red/70" : v >= 0.15 ? "bg-accent-orange/70" : "bg-accent-green/60"
                  )}
                  style={{ width: `${Math.round(v * 100)}%` }}
                />
              </div>
              <span className={cn("w-14 text-right text-code-md", scoreTone(v))}>
                {ran[k] === false ? "skip" : v.toFixed(2)}
              </span>
            </div>
          ))}
        </div>
      </Section>
    </div>
  )
}

export const RENDERERS: Record<string, (props: { e: Record<string, unknown> }) => React.ReactNode> = {
  layer1_hash: HashEvidence,
  layer2_dom_structure: DomEvidence,
  layer3_link_audit: LinksEvidence,
  layer4_visual_diff: VisualEvidence,
  layer5_signatures: SignaturesEvidence,
  layer6_security_metadata: MetadataEvidence,
  layer7_cloaking: CloakingEvidence,
  layer8_semantics: SemanticsEvidence,
  layer9_fusion: FusionEvidence,
}

export function FindingCard({ finding }: { finding: ScanFinding }) {
  const signaled = !finding.skipped && (finding.score ?? 0) >= 0.15
  const [open, setOpen] = useState(signaled)
  const title = LAYER_TITLES[finding.layer_key] ?? finding.layer_key
  const Renderer = RENDERERS[finding.layer_key]
  const evidence = finding.evidence ?? {}

  return (
    <div className="rounded-lg border border-hairline-strong bg-surface-card">
      <button
        type="button"
        className="flex w-full items-center gap-3 px-5 py-3.5 text-left hover:bg-surface-elevated/40"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
      >
        {open ? (
          <ChevronDown className="size-4 shrink-0 text-mute" aria-hidden />
        ) : (
          <ChevronRight className="size-4 shrink-0 text-mute" aria-hidden />
        )}
        <StatusDot state={dotFor(finding)} />
        <span className="text-caption text-mute">L{finding.layer}</span>
        <span className="text-body-sm font-medium text-ink">{title}</span>
        <span className="hidden truncate text-caption text-mute sm:inline">
          {LAYER_BLURBS[finding.layer_key]}
        </span>
        <span className={cn("ml-auto shrink-0 text-code-md", scoreTone(finding.score))}>
          {finding.skipped ? "skipped" : `${Math.round((finding.score ?? 0) * 100)}%`}
        </span>
      </button>
      {open && (
        <div className="border-t border-hairline px-5 py-4">
          {finding.skipped ? (
            <p className="text-body-sm text-mute">
              {String(evidence.reason ?? "Layer did not run for this scan.")}
            </p>
          ) : Renderer ? (
            <Renderer e={evidence} />
          ) : (
            <GenericEvidence evidence={evidence} />
          )}
          {evidence.suppression_applied != null && !finding.skipped && (
            <p className="mt-3 border-t border-divider-soft pt-2 text-caption text-mute">
              Suppression rules were applied to this comparison — excluded
              content did not contribute to the score.
            </p>
          )}
        </div>
      )}
    </div>
  )
}
