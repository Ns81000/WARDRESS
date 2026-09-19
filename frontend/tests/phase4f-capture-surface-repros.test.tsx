/*
 * Audit Phase 4F — Frontend capture & detection surfaces: characterization
 * repros (diagnosis only, no production file was modified).
 *
 * Every test here pins CURRENT behaviour that the Phase 4F fresh-eyes audit
 * found defective or mechanism-level, in the same spirit as the backend
 * `test_phase4x_*_repros.py` files: a remediation that fixes the finding is
 * expected to make the corresponding test fail, which is the point.
 *
 * Findings exercised:
 *   AUDIT-4F-1  capture-health.test.tsx flake mechanism (implicit 1 s waitFor
 *               budget vs an unbounded data path) — deterministic repro
 *   AUDIT-4F-2  a degraded scan renders exactly like a healthy clean scan
 *   AUDIT-4F-3  the client type drops the structured `degraded` flag the API
 *               ships on `Scan.layer_scores`, and never reads
 *               `SiteDetailOut.consecutive_degraded_scans` (drift guard)
 *   AUDIT-4F-4  layer-score severity tiers are hardwired (0.15/0.5) and
 *               ignore the site's own flag_threshold
 *   AUDIT-4F-5  risk-gauge.tsx asserts the wrong constant in a comment
 *               (AUDIT-2B-5 / O-8) — executable drift guard incl. the backend
 *   AUDIT-4F-6  alert/remediation risk chips are unconditional accent-red,
 *               including for a null (unmeasured) risk score
 *   AUDIT-4F-7  mixed-script site names render with no bidi isolation
 *   AUDIT-4F-8  the risk gauge is an unnamed `role="application"` surface
 *   AUDIT-4F-9  an unexpected 200 response shape blanks the whole dashboard
 */
import { readFileSync, readdirSync } from "node:fs"
import { join, relative } from "node:path"

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { cleanup, fireEvent, render, waitFor } from "@testing-library/react"
import { MemoryRouter, Route, Routes } from "react-router"
import { afterEach, describe, expect, it, vi } from "vitest"

import { scoreTone } from "../src/components/finding-card"
import { RiskGauge, riskTone } from "../src/components/risk-gauge"
import { SiteDetailPage } from "../src/pages/site-detail"

const SRC_ROOT = join(__dirname, "..", "src")
const BACKEND_ROOT = join(__dirname, "..", "..", "backend")

function readSrc(...parts: string[]): string {
  return readFileSync(join(SRC_ROOT, ...parts), "utf8")
}

function sitePayload(overrides: Record<string, unknown> = {}) {
  return {
    id: "site-1",
    name: "Example",
    url: "https://example.com/",
    allow_private_networks: false,
    is_active: true,
    flag_threshold: 0.5,
    auto_scan_enabled: true,
    scan_interval_minutes: 60,
    current_interval_minutes: null,
    next_scan_at: null,
    muted_until: null,
    created_at: new Date().toISOString(),
    baseline_id: "baseline-1",
    baseline_status: "ready",
    baseline_captured_at: new Date().toISOString(),
    baseline_error: null,
    consecutive_degraded_scans: 0,
    baseline_capture_method_version: 2,
    current_capture_method_version: 2,
    needs_rebaseline: false,
    ...overrides,
  }
}

function emptyScanPage(limit: number) {
  return { items: [], total: 0, offset: 0, limit }
}

/** Route table keyed by an exact URL fragment; first match wins, so the more
 * specific scan-page URLs must be listed before the bare site URL. */
function stubFetch(routes: [string, unknown][]) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString()
      for (const [fragment, body] of routes) {
        if (url.includes(fragment)) {
          return new Response(JSON.stringify(body), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          })
        }
      }
      return new Response("{}", {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    })
  )
}

function mount(ui: React.ReactElement) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>)
}

function mountSiteDetail() {
  return mount(
    <MemoryRouter initialEntries={["/sites/site-1"]}>
      <Routes>
        <Route path="/sites/:siteId" element={<SiteDetailPage />} />
      </Routes>
    </MemoryRouter>
  )
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe("AUDIT-4F-1 — capture-health flake mechanism", () => {
  it("fails iff the data path outlives the implicit 1000 ms waitFor budget", async () => {
    // The two capture-health tests await a payload-dependent string with no
    // `timeout` option, so React Testing Library's 1000 ms default is the
    // whole budget. Measured this session: an immediately-failing waitFor
    // rejects at ~1018 ms, and the site-detail render those tests await costs
    // 14-514 ms with a ~25 ms median on an idle machine — a ~35x spread, which
    // is what makes the assertion load-sensitive rather than wrong.
    const delayMs = 1400
    const slowStub = () =>
      vi.stubGlobal(
        "fetch",
        vi.fn(async (input: RequestInfo | URL) => {
          const url = typeof input === "string" ? input : input.toString()
          const body = url.includes("/scans") ? emptyScanPage(20) : sitePayload()
          return new Promise<Response>((resolve) => {
            setTimeout(
              () =>
                resolve(
                  new Response(JSON.stringify(body), {
                    status: 200,
                    headers: { "Content-Type": "application/json" },
                  })
                ),
              delayMs
            )
          })
        })
      )

    // (a) The extant assertion shape, with a payload that is merely one
    // request-latency late: it must reject — this is the flake's failure text,
    // the component still showing its loading state.
    slowStub()
    const first = mountSiteDetail()
    const started = performance.now()
    let failure = ""
    try {
      await waitFor(() => {
        expect(first.container.textContent).toContain("Example")
      })
    } catch (err) {
      failure = (err as Error).message
    }
    const elapsed = performance.now() - started
    cleanup()
    vi.unstubAllGlobals()
    expect(failure).toContain("Loading")
    // The rejection can only come from the budget elapsing, never from a wrong
    // payload: it cannot fire before the budget has elapsed.
    expect(elapsed).toBeGreaterThan(900)

    // (b) Byte-identical payload, identical assertion, explicit budget: passes.
    // The payload was never the problem — the budget was.
    slowStub()
    const second = mountSiteDetail()
    await waitFor(
      () => {
        expect(second.container.textContent).toContain("Example")
      },
      { timeout: 6000 }
    )
    expect(second.container.textContent).toContain("Example")
  }, 25000)
})

describe("AUDIT-4F-2 — a degraded scan is indistinguishable from a healthy clean one", () => {
  it("renders Clean/0% with no degradation signal for a scan whose layers went dark", async () => {
    // `_summarize_layer_scores` (worker/scan_tasks.py) stamps `degraded: true`
    // on every layer whose capture/probe side failed, and sites.py exposes
    // `consecutive_degraded_scans` on the detail payload precisely so the UI
    // can surface systematic capture failure. Neither reaches this page.
    const degradedScan = {
      id: "scan-1",
      site_id: "site-1",
      baseline_id: "baseline-1",
      status: "completed",
      verdict: "clean",
      content_hash: "abc",
      layer_scores: {
        // The authoritative degraded shape (worker/detection/types.py::
        // degraded_result): score None, skipped True, degraded True.
        layer1_hash: { score: null, skipped: true, degraded: true },
        layer9_fusion: { score: 0, skipped: false, degraded: false },
      },
      risk_score: 0,
      error: null,
      created_at: new Date().toISOString(),
      started_at: new Date().toISOString(),
      finished_at: new Date().toISOString(),
    }
    stubFetch([
      [
        "/api/sites/site-1/scans?offset=0&limit=20",
        { items: [degradedScan], total: 1, offset: 0, limit: 20 },
      ],
      ["/api/sites/site-1/scans?offset=0&limit=200", emptyScanPage(200)],
      ["/api/sites/site-1", sitePayload({ consecutive_degraded_scans: 4 })],
    ])
    const { container } = mountSiteDetail()
    await waitFor(() => {
      expect(container.textContent).toContain("Example")
    })
    // The verdict/dot/risk row lives in the Scans tab, which is not the
    // default view — the page an operator lands on shows no verdict at all.
    fireEvent.click(container.querySelector("#site-tab-scans") as Element)
    await waitFor(() => {
      expect(container.textContent).toContain("Clean")
    })
    const text = container.textContent ?? ""
    // The healthy-looking reading …
    expect(text).toContain("Clean")
    expect(text).toContain("0%")
    // … while the structured degradation signal the API sent — both on the
    // scan's layer_scores and as consecutive_degraded_scans=4 — is nowhere.
    expect(text.toLowerCase()).not.toContain("degraded")
    // The layer summary counts a dark channel as "did not run", exactly like a
    // structurally gated layer: the two are conflated on this surface.
    expect(text).toContain("0/1 layers ran")
  })
})

function backendSource(...parts: string[]): string {
  return readFileSync(join(BACKEND_ROOT, ...parts), "utf8")
}

function collectSources(dir: string): string[] {
  const out: string[] = []
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name)
    if (entry.isDirectory()) out.push(...collectSources(full))
    else if (/\.tsx?$/.test(entry.name)) out.push(full)
  }
  return out
}

describe("AUDIT-4F-3 — the client drops the structured degradation flag", () => {
  it("omits a key the worker's layer summary emits, and never reads the streak", () => {
    const apiSrc = readSrc("lib", "api.ts")
    const typeLine = apiSrc
      .split("\n")
      .find((line) => line.includes("layer_scores: Record<string,"))
    expect(typeLine).toBeDefined()

    const worker = backendSource("worker", "scan_tasks.py")
    const start = worker.indexOf("def _summarize_layer_scores")
    expect(start).toBeGreaterThan(-1)
    const body = worker.slice(start, worker.indexOf("\ndef ", start + 10))
    const emitted = [...body.matchAll(/"(\w+)":\s/g)].map((match) => match[1])
    expect(emitted).toEqual(["score", "skipped", "degraded"])

    // Pinned gap: the worker ships score/skipped/degraded per layer; the client
    // declares only two of the three, so no component can key on degradation
    // from the scan payload it already holds.
    const missing = emitted.filter((key) => !(typeLine ?? "").includes(key))
    expect(missing).toEqual(["degraded"])

    // Second half of the gap, measured rather than assumed: the per-site
    // degradation streak the API computes for this very page (sites.py:231)
    // is referenced by NOTHING in the client — it is not even declared as a
    // type, so no component could read it without a contract change.
    const users = collectSources(SRC_ROOT)
      .filter((file) => readFileSync(file, "utf8").includes("consecutive_degraded_scans"))
      .map((file) => relative(SRC_ROOT, file).replaceAll("\\", "/"))
    expect(users).toEqual([])
  })
})

describe("AUDIT-4F-4 — layer-score tiers ignore the site's flag threshold", () => {
  it("tones one layer reading two ways depending on which helper renders it", () => {
    // finding-card scoreTone/dotFor and scan-detail's inline pill hardwire
    // 0.15/0.5; risk-gauge and the verdict badge use the site's threshold.
    expect(scoreTone(0.45)).toBe("text-accent-orange")
    expect(riskTone(0.45, 0.3)).toBe("red")
    expect(riskTone(0.45, 0.5)).toBe("orange")
    // Same value, same scan, two different severity colours.
    expect(scoreTone(0.45)).not.toBe(riskTone(0.45, 0.3))
  })

  it("defines the tier functions without any threshold input", () => {
    const card = readSrc("components", "finding-card.tsx")
    const start = card.indexOf("export function scoreTone")
    const body = card.slice(start, card.indexOf("\n}", start))
    expect(body.length).toBeGreaterThan(0)
    expect(body).not.toContain("threshold")
    expect(body).toContain("0.15")
    expect(body).toContain("0.5")
  })
})

describe("AUDIT-4F-5 — a comment that asserts a constant which has since moved", () => {
  it("labels the gauge's 0.15 tier as the scheduler's material-change band (0.40)", () => {
    const gauge = readSrc("components", "risk-gauge.tsx")
    const tier = /if \(risk >= (\d+\.\d+)\) return "orange"[^\n]*/.exec(gauge)
    expect(tier).not.toBeNull()
    expect(tier?.[0]).toContain("material-change band")
    expect(Number(tier?.[1])).toBe(0.15)

    const scanning = backendSource("app", "scanning.py")
    const material = /MATERIAL_CHANGE_RISK = (\d+\.\d+)/.exec(scanning)
    expect(material).not.toBeNull()
    expect(Number(material?.[1])).toBe(0.4)
    // The asserted provenance is false against current code (AUDIT-2B-5).
    expect(Number(tier?.[1])).not.toBeCloseTo(Number(material?.[1]), 5)
  })

  it("hard-codes the beat tick the worker declares, with no shared source", () => {
    // Same class, second instance: health.tsx prints "60s" twice as the beat
    // tick. It agrees with the worker today (beat_tasks.py:46) — this guard
    // exists so it keeps agreeing.
    const health = readSrc("pages", "health.tsx")
    expect(health).toContain("tick interval")
    const beat = backendSource("worker", "beat_tasks.py")
    const tick = /DISPATCH_TICK_SECONDS = (\d+)/.exec(beat)
    expect(tick).not.toBeNull()
    expect(health).toContain(`${Number(tick?.[1])}s`)
  })
})

describe("AUDIT-4F-6 — risk chips are unconditional accent-red", () => {
  it("paints the unmeasured placeholder red on both queue surfaces", () => {
    for (const file of ["alerts.tsx", "remediation.tsx"]) {
      const src = readSrc("pages", file)
      // The null-risk placeholder exists on both surfaces …
      expect(src).toContain(': "—"')
      const chip = /\{riskPct\}/.exec(src)
      expect(chip, `${file} should render a risk chip`).not.toBeNull()
      const sameLine = src.slice(0, chip?.index).split("\n").pop() ?? ""
      // … and the chip's tone is a literal, so a missing measurement and a
      // 95 % reading render in the same threat colour.
      expect(sameLine).toContain("text-accent-red")
      expect(sameLine).not.toContain("?")
      expect(sameLine).not.toContain("scoreTone")
    }
  })
})

describe("AUDIT-4F-7 — mixed-script names carry no bidi isolation", () => {
  it("keeps the code points intact but adds neither dir nor bdi", async () => {
    const name = "موقع الفجر — Журнал 東京"
    stubFetch([
      ["/api/sites/site-1/scans?offset=0&limit=20", emptyScanPage(20)],
      ["/api/sites/site-1/scans?offset=0&limit=200", emptyScanPage(200)],
      ["/api/sites/site-1", sitePayload({ name })],
    ])
    const { container } = mountSiteDetail()
    await waitFor(() => {
      expect(container.textContent).toContain("東京")
    })
    // The bytes survive round-trip untouched …
    expect(container.textContent).toContain(name)
    // … but nothing isolates the RTL run: no dir attribute, no <bdi>, and no
    // bidi control in the stylesheet, so an Arabic site name in an LTR,
    // neutral-aligned heading is reordered by the bidi algorithm (the
    // trailing " — " and the nav/heading neighbours can land inside the run).
    expect(container.querySelectorAll("[dir]")).toHaveLength(0)
    expect(container.querySelectorAll("bdi")).toHaveLength(0)
    expect(container.innerHTML).not.toContain("unicode-bidi")
  })
})

describe("AUDIT-4F-8 — the risk gauge is an unnamed application surface", () => {
  it("exposes role=application with no accessible name and no role=img", () => {
    const { container } = render(<RiskGauge risk={0.42} threshold={0.5} />)
    const svg = container.querySelector("svg")
    expect(svg?.getAttribute("role")).toBe("application")
    expect(svg?.getAttribute("aria-label")).toBeNull()
    expect(container.querySelector('[role="img"]')).toBeNull()
    expect(container.querySelector("[aria-label]")).toBeNull()
    // The severity is carried by the arc colour; the only programmatic signal
    // is unlabelled text, and nothing states the site threshold it is
    // compared against.
    expect(container.textContent).toBe("42%Fused risk")
    expect(container.textContent?.toLowerCase()).not.toContain("threshold")
  })
})

describe("AUDIT-4F-9 — an unexpected 200 shape blanks the dashboard", () => {
  it("tears the page down when the scans payload has no items array", async () => {
    // site-detail.tsx guards `data`, never `items`
    // (`query.state.data?.items.some(...)` in both refetchInterval callbacks
    // and in the render-time `scanInFlight`), and the frontend has no error
    // boundary anywhere, so a 200 body that lacks `items` — version skew
    // between a long-lived SPA tab and a newer API, an intercepting proxy, or
    // any contract drift — throws out of React Query's observer and leaves
    // the operator with a blank page and no message.
    const escaped: string[] = []
    const capture = (err: unknown) => {
      escaped.push(err instanceof Error ? err.message : String(err))
    }
    process.on("uncaughtException", capture)
    process.on("unhandledRejection", capture)
    stubFetch([
      ["/api/sites/site-1/scans?offset=0&limit=20", { total: 1, offset: 0, limit: 20 }],
      ["/api/sites/site-1", sitePayload()],
    ])
    const { container } = mountSiteDetail()
    await waitFor(
      () => {
        expect(container.textContent).toBe("")
      },
      { timeout: 5000 }
    )
    process.off("uncaughtException", capture)
    process.off("unhandledRejection", capture)
    expect(container.innerHTML).toBe("")
    // The mechanism, captured for the log (the assertion above is the
    // observable contract; this is the escaping error it came from).
    console.log("PROBE4F_SHAPE_SKEW_ESCAPED=" + JSON.stringify(escaped.slice(0, 3)))
  }, 15000)
})

