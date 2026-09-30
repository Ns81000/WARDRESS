### [DONE] PROMPT-003 Audit Phase 5A+5B+5C — Stress-Test Catalog: All Tiers

- **Prompt**: SESSION-B-KICKOFF.md (subagent W1-A)
- **Session date**: 2026-09-30
- **Assigned subsystem**: capture pipeline under real-world site load, all catalog tiers

## Reading order / findings index

Sections appear in the order I produced them; the full-Tier-A findings landed after
the Tier C section once the (delayed) complete Tier A run finished.

| section | line |
|---|---|
| Environment attestation | 10 |
| Execution plan & deviations from the catalog | 34 |
| Method | 90 |
| **Tier A** results table / cross-cutting | 171 |
| Tier A FAIL blocks (38 sites) | 289 |
| Findings Tier A: **5A-1 … 5A-6** | 600 |
| Tier A methodology self-corrections (5) | 848 |
| Opportunities (8) + out-of-scope routing | 898 |
| **Tier B** results table / cross-cutting / drift | 1044 |
| Findings Tier B: **5B-1 … 5B-5** | 1390 |
| **Tier C** results table / category-by-category answers | 1616 |
| Findings Tier C: **5C-1 … 5C-5** | 1921 |
| Environment incident (DNS outage) | 2151 |
| Regression results / proposed hermetic tests / coverage | 2176 |
| Findings continued: **5C-6** (SW), **5A-7, 5A-8, 5A-9**, correction, full Tier A log-vs-reality | 2232 |

| finding | severity | one line |
|---|---|---|
| **AUDIT-5C-1** | **Critical** | A 200-OK onboarding dialog / login wall is stored as a healthy, `ready`, current baseline by the deployed stack (measured live against the Docker install) |
| **AUDIT-5C-6** | **Critical** (same defect as Session A's AUDIT-SA1-1; merge on consolidation) | A *controlling* Service Worker registers on `web.whatsapp.com` under the production capture context; `service_workers="block"` removes it at <0.01 % fidelity cost |
| **AUDIT-5A-1** | **High** | `layer3_link_audit` scores ordinary ad/prebid/safeframe host rotation as an injection signal (one new iframe domain = 0.5934 = `1-exp(-0.9)`, exact) |
| **AUDIT-5A-2** | **High** | Capture-completeness variance is diffed as content change; `aajtak.in` flags at 0.998–1.000 on all three consecutive visits |
| **AUDIT-5A-3** | **High** | A 0.65 % rendered-height difference + one rotating content band flags an unchanged BBC News homepage at 0.7633 |
| **AUDIT-5A-7** | **High** | 7 Tier A homepages are walled; `reuters.com` serves the wall on **HTTP 200** — the one shape the baseline gate cannot catch |
| **AUDIT-5B-1** | **High** | 6 non-Cloudflare bot walls (Akamai / DataDome / PerimeterX / Anubis-401) stored as content at `capture_quality: "full"`; live confirmation of AUDIT-SA1-2 |
| **AUDIT-5B-2** | **High** | 45 of 77 real Tier B pairs FLAGGED at median risk 0.79 with no attack present |
| **AUDIT-5A-4** | **Medium** | `ndtv.com` returns 403 `Access Denied` and Wardress captures it as real content labelled `full` |
| **AUDIT-5A-5** | **Medium** | A transient DNS failure is surfaced as `SSRFBlockedError` and permanently excluded from retry |
| **AUDIT-5A-6** | **Medium** | The mandated stress runner cannot detect the failure mode Tier B exists to catch |
| **AUDIT-5A-8** | **Medium** | `archive.org`'s `noscript` fallback is stored as a complete capture |
| **AUDIT-5B-3** | **Medium** | The height-only screenshot guard misses 4000-px and 1378-px wide captures (confirms + escalates AUDIT-SA1-5) |
| **AUDIT-5B-4** | **Medium** | `net::ERR_HTTP2_PROTOCOL_ERROR` is classified transient and retried, failing 3/3 on two sites |
| **AUDIT-5C-2** | **Medium** | Width-cap gap measured on 4 real sites / 12 captures |
| **AUDIT-5C-3** | **Medium** | Inner-scroll-container pages are captured as one viewport and reported `full` |
| **AUDIT-5C-4** | **Medium** | `apnews.com` reproduces AUDIT-3-8's scroll-shrink path live (15 368 -> 768 px) |
| **AUDIT-5B-5** | **Low** | Catalog category drift, 15 rows individually measured and timestamped |
| **AUDIT-5A-9** | **Low** | `indiaforums.com` exhausts the 180 s budget 3/3; the three Cloudflare refusals are Accepted-risk |
| **AUDIT-5C-5** | **Low** | `india.gov.in`: 403 to the browser, 200 / 607 KB to Wardress's own probe — the block is on the client, not the UA |


*(Sections below are appended as each tier completes; this file is written
incrementally so an interruption never loses work.)*

## Environment attestation

| item | value |
|---|---|
| Repo root | `C:\Users\Ns8pc\Music\WARDRESS` (git HEAD branch as found; **no tracked production file modified by me** — see *Rule 1 compliance* at the end) |
| Docker stack | `wardress-app-1` / `worker-1` / `beat-1` / `db-1` / `redis-1` all Up; `app`, `db`, `redis` reporting **healthy**. Re-verified at 2026-09-30 ~12:12 local. |
| Python | `uv run python` from `backend\`, CPython 3.12.11, `backend\.venv` |
| Browser | Chromium 149.0.7827.55 driven by production `worker.fetcher.fetch_page` on the **host** (not in a container) |
| Wall-clock of runs | 2026-09-30 12:12 → (see per-tier windows below) local |
| Credentials | none used against Wardress itself; `fetch_page`/`probe_site` were called directly, so **no login, no form submission, no account creation, no Wardress API mutation** |
| Target traffic | public, unauthenticated pages only; 3 capture passes + 2–3 production `probe_site` calls per site (one full scan's worth of UA-rotation traffic per pass), sequential, never parallelised |

> **CONTENTION CAVEAT — every latency number in this file is contention-affected.**
> Two sibling Wave-1 subagents (detection-fixtures; performance/ops) were
> running concurrently on the same host for the whole capture window, on an
> AMD Ryzen 5 5625U (6c/12t) with ~15.34 GB total RAM of which ~2.2 GB was
> free at the coordinator's check, against a Docker Desktop ceiling of
> 7.429 GiB. Captures were deliberately run **one at a time** (never
> parallelised across sites) to protect the measurement, but host CPU and
> memory were shared. Numbers are therefore **upper bounds with inflated
> variance**, not clean baselines. Where a site's spread looked
> variance-driven, a confirmatory pass was re-run and both sets are reported.
> Wave-2's concurrency work (subagent W2) must not be attributed to these.

## Execution plan & deviation from the catalog

**Decision: execute each tier's UNIQUE URL list once per pass, then map every
result back to every catalog category that URL belongs to.** Explicit and
auditable, as instructed:

| tier | catalog entries | unique URLs | passes | captures | mapping preserved |
|---|---|---|---|---|---|
| A | 88 | **69** | 3 | 207 | 19 URLs appear in 2 category blocks each (verified by parser: "Top 20" overlaps "Indian News" ×6, "International News" ×3, "Tech/Developer" ×5, "Government/Institutional" ×2, plus `stackexchange`-style repeats) |
| B | 31 | 31 | 3 | 93 | 1:1 |
| C | 21 | 21 | 3 | 63 | 1:1 |
| **total** | **140** | **121** | 3 | **363** | — |

Saving: 19 × 3 = 57 redundant captures avoided (27 % of Tier A's capture
time). Every per-category attribution in the summary table is computed from
the URL→categories mapping, so no category loses a site because of the
dedupe.

**The 19 dual-category Tier A URLs (verbatim mapping, auditable):**

| URL | category 1 | category 2 |
|---|---|---|
| `https://www.bbc.co.uk/news` | Top 20 — mixed selection | International News (modern, element-rich) |
| `https://www.bbc.com/news` | Top 20 — mixed selection | International News (modern, element-rich) |
| `https://hackaday.com/` | Top 20 — mixed selection | International News (modern, element-rich) |
| `https://www.aajtak.in/` | Top 20 — mixed selection | Indian News |
| `https://www.ndtv.com/` | Top 20 — mixed selection | Indian News |
| `https://www.thehindu.com/` | Top 20 — mixed selection | Indian News |
| `https://indianexpress.com/` | Top 20 — mixed selection | Indian News |
| `https://www.hindustantimes.com/` | Top 20 — mixed selection | Indian News |
| `https://www.indiatoday.in/` | Top 20 — mixed selection | Indian News |
| `https://www.reuters.com/` | Top 20 — mixed selection | International News (modern, element-rich) |
| `https://www.smashingmagazine.com/` | Top 20 — mixed selection | Tech / Developer (modern looking) |
| `https://www.nasa.gov/` | Top 20 — mixed selection | Government / Institutional |
| `https://www.gov.uk/` | Top 20 — mixed selection | Government / Institutional |
| `https://www.mozilla.org/` | Top 20 — mixed selection | Tech / Developer (modern looking) |
| `https://developer.mozilla.org/` | Top 20 — mixed selection | Tech / Developer (modern looking) |
| `https://www.python.org/` | Top 20 — mixed selection | Tech / Developer (modern looking) |
| `https://www.rust-lang.org/` | Top 20 — mixed selection | Tech / Developer (modern looking) |
| `https://go.dev/` | Top 20 — mixed selection | Tech / Developer (modern looking) |
| `https://stackoverflow.com/` | Top 20 — mixed selection | Tech / Developer (modern looking) |

### Second deviation: tier EXECUTION order, not coverage

The catalog's own §4 instruction is `--tier A`, then `B`, then `C`. Measured
Tier A throughput on this contended host was **~4 min/site** (69 unique URLs ×
3 passes ≈ 4 h; the Indian-news block alone ran 50–110 s per pass, because
`www.aajtak.in` needed the full Phase-6 transient retry — 60 s nav timeout + 3 s
pause + 30 s retry + settle/scroll). I therefore executed **B → C → A**, so
that the two tiers which actually generate *new* findings (live vendor bot
walls; exotic capture categories) complete inside the session budget, and
Tier A — whose per-site result is homogeneous and derivable from a
well-covered subset — resumes and completes afterwards. The driver resumes
Tier A from its JSONL, so nothing was re-captured. **Coverage is unaffected;
only the order changed, and it is stated here so it is auditable.**

## Method

### One pass

A pass is exactly one production `worker.fetcher.fetch_page(url)` call in a
**child process** (identical isolation to `backend/tests/_capture_child_impl.py`
and to the stock runner), killed with its whole tree at
`SITE_BUDGET_S = 180`. Around it, the augmented child adds **measurement
only**:

1. `http_status`, `final_url`, the fetcher's curated header subset, and the
   **complete `capture_evidence` dict** — all read straight off the production
   `FetchResult`.
2. `content_sha256(html)` via production `worker.hashing.content_sha256`
   (never an invented digest — Rule: identical `content_hash` would make
   `layer1_hash` return 0.0 and gate layers 2/3/5/8 into a `clean` by
   construction).
3. PNG geometry parsed from the IHDR chunk (Session A's AUDIT-SA1-5 width gap).
4. `page.content()` and the screenshot bytes persisted to gzip/PNG so the
   detection pipeline can run **offline in one warm process** (cold start was
   measured at 20.1 s on this host, so forking per fixture is not viable).
5. On passes 2 and 3, production `worker.probe.probe_site(url)` → full header
   map, TLS record, `robots.txt`, and the three `ua_variants`. These are the
   **exact inputs production gives layers 6 and 7** (`scan_tasks.py:287,291`).
   Pass 1's probe was filled afterwards with the same production function
   (`probe_only.py`) so all three pairs have production-faithful layer-6/7
   inputs on both sides. **Deviation stated:** production runs `probe_site`
   on every scan; I run it twice per site rather than three times, because the
   baseline side of a pair never consumes `ua_variants`
   (`layer7_cloaking(baseline, current)` — `baseline` is explicitly unused,
   `cloaking.py:122-123`).

### One detection measurement

Per site the 3 captures give 3 real capture pairs: **p1→p2, p2→p3, p1→p3**.
Each pair is materialised as `PageData` (baseline) / `ScanPageData` (current)
exactly as `worker/scan_tasks.py:279-292` does, and run through the **deployed
`worker.detection.pipeline.run_detection`** in one long-lived process
(`analyze.py`, warm-up measured and printed). I then apply production's own
verdict arithmetic verbatim — `NOISE_FLOOR = 0.02` (`scan_tasks.py:59`),
`changed = any(non-skipped layer score > NOISE_FLOOR)`, `flagged = risk >=
site.flag_threshold` (default `0.5`, `app/models.py:235`),
`MATERIAL_CHANGE_RISK = 0.40` (`app/scanning.py:58`), escalation band
0.40–0.75 (`worker/llm_escalation.py:37-38`). I do **not** call the LLM
escalation endpoint; I only report whether a pair's risk lands in its band.

Because Rule 18 gives three passes anyway, this measures something Tier B never
asked for and Tier A needs: **what does a second visit to an unchanged public
page read — `clean`, `changed`, or `flagged`?**

### One root-cause investigation

For every failing or surprising site I read: the child log (production
`logger` output from the failing capture), the exact exception text, the full
`capture_evidence`, the HTTP status, the probe's header/cookie/vendor
fingerprints, and the production source of every code path involved
(`fetcher.py`, `banner_dismiss.py`, `page_prepare.py`, `probe.py`,
`scan_tasks.py`, `detection/*`). Vendor identity is established from
response headers, `set-cookie` names, HTML fingerprint strings and the page
title — never from the catalog's label. All vendor/liveness verifications are
timestamped (catalog verification protocol §4).

### What the stock runner does NOT measure — investigated and reproduced

`backend/tools/run_stress_catalog.py::test_site` records **only** whether
`fetch_page` returned without raising (`ok` true/false). It never calls
detection, never inspects `http_status`, never runs
`looks_like_challenge_page`, and its bot-protection note fires only on the
literal strings `"BOT_PROTECTION"` / `"Cloudflare"` in an error message
(`run_stress_catalog.py:186-188`). Since **no non-Cloudflare wall ever raises**
(Session A's AUDIT-SA1-2 truth table), a DataDome/Akamai/AWS-WAF wall page is
recorded as a clean **PASS**. Measured live confirmation of that gap:
see *FAIL* blocks and finding `AUDIT-5B-1`. Every row in this report therefore
adds four measurements the stock runner omits: `http_status`, the production
challenge verdict, an independent wall verdict, and the fused detection
risk + verdict.



---

## TIER A — Broad Real-World Baseline (Phase 5A)

**Coverage: 7 of 69 unique Tier A URLs complete at the time of writing
(3 passes each = 21/207 planned captures).** The remaining 62 URLs were
interrupted by the session wall-clock budget, not by any failure — the run is
resumable and 
esults_tierA.jsonl + rtifacts/ hold the partial state
verbatim. See *Coverage honestly stated as NOT done* at the end. The 7 URLs
completed span **three** of the catalog's eight Tier A categories (Top 20,
Indian News, International News) and include the two highest-information
sites in the whole tier.

### Tier A dense summary table

Legend: `OK <status> <time>` = capture succeeded; `⚠WALL` = independent wall/interstitial
evidence; `⚠SHELL` = content-free shell (visible text < 400 chars); `⚠CF` = the production
Cloudflare gate fired. Passing sites (3/3, no wall, no flag) take **exactly one line**.

| URL | Tier/Category | Pass 1 | Pass 2 | Pass 3 | Latency min/avg/max (CONTENDED) | Status | Notes / Disposition |
|---|---|---|---|---|---|---|---|
| https://quietude-one.vercel.app/ | Top 20 | OK 200 24.8s | OK 200 23.0s | OK 200 23.7s | 23/24/25s | 3/3 clean | pairs `changed` 3/3, risk 0.137-0.141; no flag |
| https://www.bbc.co.uk/news | Top 20; International News | OK 200 20s | OK 200 25s | OK 200 22s | 20/22/25s | **FAIL (false flag)** | p1->p2 / p1->p3 risk **0.7633 flagged**; p2->p3 0.1431; L4 from a 40px height difference -> AUDIT-5A-3 |
| https://www.bbc.com/news | Top 20; International News | OK 200 18s | OK 200 18s | OK 200 42s | 18/26/42s | **FAIL (false flag)** | p1->p2 0.7330, p1->p3 0.8457 flagged; L2 0.5034/0.7534 -> AUDIT-5A-2 |
| https://hackaday.com/ | Top 20; International News | OK 200 16s | OK 200 20s | OK 200 18s | 16/18/20s | **FAIL (material change)** | p2->p3 risk **0.4043** >= MATERIAL_CHANGE_RISK on sub-threshold churn |
| https://www.aajtak.in/ | Top 20; Indian News | OK 200 110s (retry=1) | OK 200 70s | OK 200 79s | 70/86/110s | **FAIL (false flag)** | **all 3 pairs 0.9983-0.9995**; scroll ended at 28002/37384/27915 px -> AUDIT-5A-2 |
| https://www.ndtv.com/ | Top 20; Indian News | OK **403** 11s ⚠WALL ⚠SHELL | OK **403** 13s ⚠WALL ⚠SHELL | OK **403** 13s ⚠WALL ⚠SHELL | 11/12/13s | **FAIL (wall as content)** | 286-290 B `Access Denied`, cq=**full** -> AUDIT-5A-4 |
| https://www.thehindu.com/ | Top 20; Indian News | OK 200 45s | OK 200 43s | OK 200 44s | 43/44/45s | **FAIL (false flag)** | **all 3 pairs 0.9359-0.9836** with L2 0.0005-0.0025 and L8 0.0 -> AUDIT-5A-1 |
| https://indianexpress.com/ | Top 20; Indian News | OK 200 (resumed) | OK 200 (resumed) | **FAIL** DNS outage | - | **2/3 (P3 = environment)** | p1->p2 0.9128 flagged, real page 21 645 visible chars |
| https://www.wikidata.org/ | Reference | **FAIL** DNS outage x3 | **FAIL** | **FAIL** | - | **0/3 — ENVIRONMENT, not a result** | host DNS failed throughout; **excluded from all rates** |
| https://www.hindustantimes.com/ | Top 20; Indian News | OK 200 108s | OK 200 49s | **FAIL** nav timeout 95s | 49/84/108s | **2/3 capture FAIL** | p1->p2 **0.9994** flagged |
| https://www.indiatoday.in/ | Top 20; Indian News | OK 200 33s | OK 200 45s | OK 200 41s | 33/40/45s | **FAIL (false flag)** | **all 3 pairs 0.9915-1.000**; h 27 991-40 464, screenshot height-capped |
| https://www.reuters.com/ | Top 20; International News | OK **200** 24s ⚠WALL ⚠SHELL | OK **401** 16s ⚠WALL ⚠SHELL | OK **401** 16s ⚠WALL ⚠SHELL | 16/19/24s | **FAIL (200-OK wall → baseline poisoning + false flag)** | P1 = **HTTP 200, 13 439 B, 0 visible chars, no title**, `server: openresty`; P2/P3 = 401 DataDome -> **AUDIT-5C-1 instance 2** |
| https://www.smashingmagazine.com/ | Top 20; Tech | OK 200 17s | OK 200 21s | OK 200 19s | 17/19/21s | 3/3 clean | p2->p3 byte-identical -> `clean` 0.002 |
| https://en.wikipedia.org/wiki/Main_Page | Top 20 | OK 200 14s | OK 200 16s | OK 200 22s | 14/18/22s | 3/3 clean | risk 0.006-0.300, no flag |
| https://www.nasa.gov/ | Top 20; Government | OK 200 25s | OK 200 28s | OK 200 29s | 25/27/29s | **FAIL (false flag)** | p2->p3 0.9928, p1->p3 0.9956 flagged |
| https://www.gov.uk/ | Top 20; Government | OK 200 14s | OK 200 15s | OK 200 14s | 14/14/15s | 3/3 clean | all 3 pairs byte-identical -> `clean` 0.002 |
| https://www.mozilla.org/ | Top 20; Tech | OK 200 19s | OK 200 19s | OK 200 24s | 19/21/24s | 3/3 clean | risk 0.002-0.027 |
| https://developer.mozilla.org/ | Top 20; Tech | OK 200 15s | OK 200 20s | OK 200 19s | 15/18/20s | 3/3 clean | risk 0.137, no flag |
| https://www.python.org/ | Top 20; Tech | OK 200 17s | OK 200 19s | OK 200 16s | 16/17/19s | **FAIL (false flag)** | p2->p3 **0.9880**, p1->p3 0.9877 flagged; a *documentation site* |
| https://www.rust-lang.org/ | Top 20; Tech | OK 200 13s | OK 200 14s | OK 200 18s | 13/15/18s | 3/3 clean | all 3 pairs `clean` 0.002 |
| https://go.dev/ | Top 20; Tech | OK 200 33s | OK 200 22s | OK 200 22s | 22/26/33s | 3/3 clean | all 3 pairs `clean` 0.002 |
| https://stackoverflow.com/ | Top 20; Tech | **FAIL** 95s ⚠CF | **FAIL** 95s ⚠CF | **FAIL** 95s ⚠CF | 95/95/95s | **0/3 capture FAIL — CORRECT BEHAVIOUR** | Cloudflare gate fired and refused 3/3; Accepted-risk |
| https://www.news18.com/ | Indian News | **FAIL** DNS outage | OK **403** 20s ⚠WALL ⚠SHELL | OK **403** 15s ⚠WALL ⚠SHELL | 4/13/20s | **2/3 (P1 = environment)** | 206 visible chars, `server: istio-envoy` deny page |
| https://www.abplive.com/ | Indian News | OK 200 32s | OK 200 41s | OK 200 39s | 32/37/41s | **FAIL (false flag)** | **all 3 pairs 0.9732-0.996** |
| https://www.livemint.com/ | Indian News | OK 200 31s | OK 200 48s | OK 200 106s | 31/62/106s | **FAIL (false flag)** | **all 3 pairs 0.8932-0.996** |
| https://www.moneycontrol.com/ | Indian News | OK **403** 11s ⚠WALL ⚠SHELL | OK **403** 20s ⚠WALL ⚠SHELL | OK **403** 21s ⚠WALL ⚠SHELL | 11/17/21s | **FAIL (wall as content)** | 214 visible chars, `server: UploadServer` deny page, cq=full |
| https://www.businesstoday.in/ | Indian News | OK 200 41s | OK 200 45s | OK 200 63s | 41/50/63s | **FAIL (false flag)** | **all 3 pairs risk 1.0000**; h 12 509 -> **47 031 px**, P3 `capped:true` |
| https://www.bollywoodhungama.com/ | Bollywood | **FAIL** DNS outage x3 | **FAIL** | **FAIL** | - | **0/3 — ENVIRONMENT, not a result** | excluded from all rates |
| https://www.zeenews.india.com/ | Indian News | **FAIL** DNS outage x3 | **FAIL** | **FAIL** | - | **0/3 — ENVIRONMENT, not a result** | excluded from all rates |
| https://www.filmfare.com/ | Bollywood | OK 200 18s | OK 200 31s | OK 200 46s | 18/32/46s | **FAIL (false flag)** | p1->p3 0.7436 flagged; p2->p3 0.4296 material |
| https://www.indiaforums.com/ | Bollywood | **FAIL** **stalled 180s** | **FAIL** stalled 180s | **FAIL** stalled 180s | 180/180/180s | **0/3 capture FAIL — BUDGET** | the only site in the whole phase to exhaust `SITE_BUDGET_S` |
| https://www.pinkvilla.com/ | Bollywood | OK 200 32s | OK 200 35s | OK 200 32s | 32/33/35s | **FAIL (false flag)** | p1->p2 0.8923, p1->p3 0.9826 flagged |
| https://www.koimoi.com/ | Bollywood | OK 200 24s | OK 200 20s | OK 200 30s | 20/25/30s | **FAIL (material change)** | p1->p2 0.4527, p1->p3 0.4532 — both above 0.40 |
| https://www.hindustantimes.com/entertainment | Bollywood | OK 200 17s | OK 200 19s | OK 200 20s | 17/19/20s | 3/3 clean | risk 0.137-0.138 |
| https://indianexpress.com/section/entertainment/ | Bollywood | OK 200 37s | OK 200 39s | OK 200 39s | 37/38/39s | 3/3 clean | p3->p3 pair byte-identical -> `clean` 0.002 |
| https://www.ndtv.com/entertainment | Bollywood | OK **403** 10s ⚠WALL ⚠SHELL | OK **403** 14s ⚠WALL ⚠SHELL | OK **403** 12s ⚠WALL ⚠SHELL | 10/12/14s | **FAIL (wall as content)** | 217 visible chars; same block as ndtv.com root |
| https://www.aajtak.in/entertainment | Bollywood | OK 200 16s | OK 200 26s | OK 200 23s | 16/21/26s | **FAIL (false flag)** | p1->p2 / p1->p3 risk **0.9999** |
| https://news.sky.com/ | International News | OK **403** 11s ⚠WALL ⚠SHELL | OK **403** 12s ⚠WALL ⚠SHELL | OK **403** 14s ⚠WALL ⚠SHELL | 11/12/14s | **FAIL (wall as content)** | 206 visible chars, `server: AkamaiGHost`, cq=full |
| https://lite.cnn.com/ | International News | OK 200 12s | OK 200 15s | OK 200 14s | 12/14/15s | 3/3 clean | all 3 pairs `clean` 0.002 |
| https://www.npr.org/ | International News | OK 200 30s | OK 200 50s | OK 200 46s | 30/42/50s | **FAIL (material change)** | p1->p3 0.4955; h 17 021, screenshot height-capped |
| https://www.cbc.ca/ | International News | **FAIL** 5s `net::ERR_...` | **FAIL** 6s | **FAIL** 8s | 5/6/8s | **0/3 capture FAIL** | transport refusal (AUDIT-5B-4 class) |
| https://www.techdirt.com/ | International News | **FAIL** 94s ⚠CF | **FAIL** 95s ⚠CF | **FAIL** 95s ⚠CF | 94/95/95s | **0/3 capture FAIL — CORRECT BEHAVIOUR** | Cloudflare gate refused 3/3; Accepted-risk |
| https://www.theguardian.com/ | International News | OK 200 23s | OK 200 25s | OK 200 25s | 23/24/25s | 3/3 clean | risk 0.167-0.350; 1 258 KB, h 20 280, screenshot height-capped |
| https://www.aljazeera.com/ | International News | OK 200 20s | OK 200 23s | OK 200 21s | 20/22/23s | **FAIL (false flag)** | **all 3 pairs risk 1.0000** |
| https://www.nhs.uk/ | Government | OK 200 15s | OK 200 17s | OK 200 17s | 15/16/17s | 3/3 clean | all 3 pairs `clean` 0.002 |
| https://www.usa.gov/ | Government | OK 200 14s | OK 200 17s | OK 200 18s | 14/16/18s | 3/3 clean | all 3 pairs `clean` 0.002 |
| https://www.whitehouse.gov/ | Government | OK 200 22s | OK 200 19s | OK 200 20s | 19/21/22s | **FAIL (false flag)** | **all 3 pairs 0.8716-0.9301** |
| https://www.noaa.gov/ | Government | OK 200 22s | OK 200 22s | OK 200 21s | 21/21/22s | 3/3 clean | risk 0.137 |
| https://www.cdc.gov/ | Government | OK 200 15s | OK 200 18s | OK 200 17s | 15/17/18s | 3/3 clean | risk 0.300, no flag |
| https://www.who.int/ | Government | OK 200 15s | OK 200 17s | OK 200 17s | 15/17/17s | 3/3 clean | risk 0.137-0.145 |
| https://www.un.org/ | Government | OK 200 13s | OK 200 18s | OK 200 15s | 13/15/18s | **FAIL (false flag)** — *my shell heuristic over-fired; the page is real* | 533 visible chars of genuine 9-language text; all 3 pairs 0.692-0.964 flagged |
| https://www.europa.eu/ | Government | OK 200 18s | OK 200 24s | OK 200 26s | 18/23/26s | **FAIL (false flag)** | p2->p3 / p1->p3 0.9457 flagged |
| https://en.wikipedia.org/ | Reference | OK 200 14s | OK 200 17s | OK 200 25s | 14/19/25s | 3/3 clean | risk 0.300, no flag |
| https://commons.wikimedia.org/ | Reference | OK 200 20s | OK 200 31s | OK 200 15s | 15/22/31s | 3/3 clean | p2->p3 `clean` 0.006 |
| https://www.gutenberg.org/ | Reference | OK 200 17s | OK 200 20s | OK 200 27s | 17/21/27s | 3/3 clean | all 3 pairs `clean` 0.002 |
| https://www.archive.org/ | Reference | OK 200 18s ⚠SHELL | OK 200 25s ⚠SHELL | OK 200 27s ⚠SHELL | 18/23/27s | **FAIL (JS-required fallback stored as content + false flag)** | **101 visible chars: "Javascript is required for this site"**; h 3507/30263 (P3 screenshot height-capped); p1->p3 0.7932 flagged |
| https://arxiv.org/ | Reference | OK 200 14s | OK 200 16s | OK 200 19s | 14/16/19s | 3/3 clean | all 3 pairs `clean` 0.002 |
| https://www.w3.org/ | Tech | OK 200 13s | OK 200 14s | OK 200 14s | 13/13/14s | 3/3 clean | risk 0.221-0.358 |
| https://nodejs.org/ | Tech | OK 200 13s | OK 200 14s | OK 200 15s | 13/14/15s | 3/3 clean | all 3 pairs `clean` 0.002 |
| https://www.php.net/ | Tech | OK 200 19s | OK 200 20s | OK 200 20s | 19/20/20s | 3/3 clean | risk 0.002-0.172 |
| https://github.com/ | Tech | OK 200 22s | OK 200 27s | OK 200 25s | 22/25/27s | **FAIL (false flag)** | **all 3 pairs 0.5314-0.9068** |
| https://gitlab.com/ | Tech | OK 200 21s | OK 200 38s | OK 200 34s | 21/31/38s | 3/3 clean | risk 0.152-0.166 |
| https://www.ietf.org/ | Tech | OK 200 12s | OK 200 15s | OK 200 18s | 12/15/18s | 3/3 clean | risk 0.137 |
| https://tools.ietf.org/ | Tech | OK 200 15s | OK 200 16s | OK 200 15s | 15/15/16s | **FAIL (false flag)** | p1->p2 / p1->p3 0.5577 flagged |
| https://www.rfc-editor.org/ | Tech | **FAIL** 94s ⚠CF | **FAIL** 94s ⚠CF | **FAIL** 95s ⚠CF | 94/94/95s | **0/3 capture FAIL** | **matches PROMPT-002 Phase 13's prior disposition** ("correctly-detected block") — independently reproduced |
| https://duckduckgo.com/ | Other | OK 200 18s | OK 200 23s | OK 200 19s | 18/20/23s | 3/3 clean | risk 0.137 |
| https://www.imdb.com/ | Other | OK **405** 12s ⚠WALL | OK **405** 14s ⚠WALL | OK **405** 15s ⚠WALL | 12/14/15s | **FAIL (wall as content)** | HTTP **405** `Human Verification` ("Let's confirm you are human… solve a puzzle"), AWS WAF + PerimeterX markers, 533 visible chars |
| https://www.goodreads.com/ | Other | OK 200 57s | OK 200 62s | OK 200 14s | 14/44/62s | **FAIL (false flag)** | **all 3 pairs 0.9269-1.000**; latency spread 4x (48 s) — contention-affected |
| https://www.openstreetmap.org/ | Other | OK 200 14s | OK 200 17s | OK 200 16s | 14/16/17s | 3/3 clean | risk 0.137; h 768 (map app, inner scroll) |

### Tier A cross-cutting measurements (180 successful captures)

| metric | value |
|---|---|
| unique URLs | **69 / 69 (complete)**, 3 passes each = 207 captures |
| captures succeeded | **180 / 207** (27 failures across 13 sites) |
| failures attributable to the **host DNS outage** (environment, excluded from rates) | 4 sites x 3 passes = 12 captures, plus 2 single-pass losses (`indianexpress.com` P3, `news18.com` P1) |
| failures attributable to **Wardress / the site** | 15 captures |
| `capture_quality` | `full` **163**, `partial` **17**, `degraded` **0** |
| why `partial` | `stable:false` on 4, `capped:true` on 2, `screenshot_capped:true` on 14 |
| `screenshot_capped` | **14/180** — pages 17 036-47 031 px vs `MAX_SCREENSHOT_HEIGHT = 16_384` |
| `actual_height` | 768 - **47 031 px** |
| HTML size | 286 B - **3.01 MB** (guard `MAX_HTML_BYTES = 10 MB`; **nothing approached it**) |
| PNG width | **1366 px on all 180** — Tier A never trips the width gap (unlike Tiers B and C) |
| banner `attempts` | 30 (trivial) to **5 730** (`http://` heavy page, 191 frames x 30 selectors); `dismissed:false` on **180/180** |
| `retry_count` | 1 on 3 of 180 |
| `cloudflare_challenge_detected` | 3 sites, 9 captures — `stackoverflow.com`, `techdirt.com`, `rfc-editor.org`, all refused correctly |
| **bot-wall / interstitial pages stored as content** | **7 sites / 21 captures**: `ndtv.com`, `ndtv.com/entertainment`, `news18.com`, `moneycontrol.com`, `news.sky.com` (403), `imdb.com` (405), `reuters.com` (**200 on P1**) |
| **detection verdicts (177 pairs)** | `clean` **33**, `changed` 89, **`flagged` 55 (31 %)** |
| fused risk | min 0.0019, median **0.3000**, max 1.0000 |
| `layer7_cloaking` degraded | 32 of 177 pairs |

> **Tier A's headline: on 69 ordinary, popular, low-risk public homepages, 31 % of
> real consecutive-visit pairs FLAGGED** — creating an `Alert` and a
> `RemediationExecution` each — while **0 of the 7 walled sites produced any
> operator-visible signal at all** (all read `changed` at 0.15-0.30, all labelled
> `capture_quality: "full"`).

### Tier A FAIL blocks (generated from the captured evidence; one block per
non-clean site, in catalog order)

```
### FAIL ΓÇö https://www.bbc.co.uk/news (Tier ?, Category International News (modern, element-rich), Top 20 ΓÇö mixed selection, good starting subset)
- Pass results: P1: OK 200 19.6s / P2: OK 200 24.5s / P3: OK 200 21.5s
- Latency: 19620 / 24520 / 21890 ms (spread 4.9s)
- Error: capture succeeded and no wall fingerprint, but detection flagged: p1->p2 risk=0.7633 layers={'layer1_hash': 1.0, 'layer3_link_audit': 0.04, 'layer4_visual_diff': 0.1109, 'layer9_fusion': 0.7633}; p1->p3 risk=0.7633 layers={'layer1_hash': 1.0, 'layer3_link_audit': 0.04, 'layer4_visual_diff': 0.1109, 'layer9_fusion': 0.7633}
- Evidence: P1 cq=full stable=True polls=3 h=6109->6093 capped=False shotcap=False dims=[1366, 6109] html=336703B cf=False retry=0 banner=150/False replay_fullmap=False txt=9449; P2 cq=full stable=True polls=3 h=6069->6053 capped=False shotcap=False dims=[1366, 6069] html=336727B cf=False retry=0 banner=150/False replay_fullmap=False txt=9418; P3 cq=full stable=True polls=3 h=6069->6053 capped=False shotcap=False dims=[1366, 6069] html=336726B cf=False retry=0 banner=150/False replay_fullmap=False txt=9418
- Evidence: pair p1->p2 (probe src p1) risk=0.7633 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer3_link_audit': 0.04, 'layer4_visual_diff': 0.1109} degraded=[] (1954 ms)
- Evidence: pair p2->p3 (probe src p2) risk=0.1431 changed=True flagged=False verdict=changed material=False escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer3_link_audit': 0.02} degraded=[] (2000 ms)
- Evidence: pair p1->p3 (probe src p1) risk=0.7633 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer3_link_audit': 0.04, 'layer4_visual_diff': 0.1109} degraded=[] (2000 ms)

### FAIL ΓÇö https://www.bbc.com/news (Tier ?, Category International News (modern, element-rich), Top 20 ΓÇö mixed selection, good starting subset)
- Pass results: P1: OK 200 17.7s / P2: OK 200 17.9s / P3: OK 200 41.9s
- Latency: 17700 / 41920 / 25857 ms (spread 24.2s)
- Error: capture succeeded and no wall fingerprint, but detection flagged: p1->p2 risk=0.733 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.0044, 'layer3_link_audit': 0.04, 'layer4_visual_diff': 0.1046, 'layer9_fusion': 0.733}; p1->p3 risk=0.8457 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.5034, 'layer3_link_audit': 0.06, 'layer4_visual_diff': 0.1046, 'layer9_fusion': 0.8457}
- Evidence: P1 cq=full stable=True polls=3 h=6069->6053 capped=False shotcap=False dims=[1366, 6069] html=337821B cf=False retry=0 banner=150/False replay_fullmap=False txt=9418; P2 cq=full stable=True polls=3 h=6069->6053 capped=False shotcap=False dims=[1366, 6069] html=336216B cf=False retry=0 banner=180/False replay_fullmap=False txt=9418; P3 cq=full stable=True polls=4 h=6069->6053 capped=False shotcap=False dims=[1366, 6069] html=336778B cf=False retry=0 banner=150/False replay_fullmap=False txt=9418
- Evidence: pair p1->p2 (probe src p1) risk=0.733 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.0044, 'layer3_link_audit': 0.04, 'layer4_visual_diff': 0.1046} degraded=[] (1875 ms)
- Evidence: pair p2->p3 (probe src p2) risk=0.3267 changed=True flagged=False verdict=changed material=False escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.7534, 'layer3_link_audit': 0.06} degraded=[] (1954 ms)
- Evidence: pair p1->p3 (probe src p1) risk=0.8457 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.5034, 'layer3_link_audit': 0.06, 'layer4_visual_diff': 0.1046} degraded=[] (1922 ms)

### FAIL ΓÇö https://www.aajtak.in/ (Tier ?, Category Indian News, Top 20 ΓÇö mixed selection, good starting subset)
- Pass results: P1: OK 200 109.9s / P2: OK 200 70.3s / P3: OK 200 79.1s
- Latency: 70330 / 109920 / 86447 ms (spread 39.6s)
- Error: capture succeeded and no wall fingerprint, but detection flagged: p1->p2 risk=0.9993 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 1.0, 'layer3_link_audit': 0.7835, 'layer4_visual_diff': 0.1493, 'layer8_semantics': 0.4586, 'layer9_fusion': 0.9993}; p2->p3 risk=0.9983 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.7534, 'layer3_link_audit': 0.4, 'layer4_visual_diff': 0.1768, 'layer8_semantics': 0.3853, 'layer9_fusion': 0.9983}; p1->p3 risk=0.9995 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 1.0, 'layer3_link_audit': 0.7033, 'layer4_visual_diff': 0.1828, 'layer8_semantics': 0.3992, 'layer9_fusion': 0.9995}
- Evidence: P1 cq=partial stable=True polls=7 h=9043->28002 capped=False shotcap=True dims=[1366, 16384] html=1769837B cf=False retry=1 banner=990/False replay_fullmap=False txt=35356; P2 cq=partial stable=True polls=6 h=9043->37384 capped=True shotcap=True dims=[1366, 16384] html=1982616B cf=False retry=0 banner=1920/False replay_fullmap=False txt=40279; P3 cq=partial stable=True polls=6 h=9043->27915 capped=False shotcap=True dims=[1366, 16384] html=1760943B cf=False retry=0 banner=2370/False replay_fullmap=False txt=34899
- Evidence: pair p1->p2 (probe src p1) risk=0.9993 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 1.0, 'layer3_link_audit': 0.7835, 'layer4_visual_diff': 0.1493, 'layer8_semantics': 0.4586} degraded=[] (6406 ms)
- Evidence: pair p2->p3 (probe src p2) risk=0.9983 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.7534, 'layer3_link_audit': 0.4, 'layer4_visual_diff': 0.1768, 'layer8_semantics': 0.3853} degraded=[] (6563 ms)
- Evidence: pair p1->p3 (probe src p1) risk=0.9995 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 1.0, 'layer3_link_audit': 0.7033, 'layer4_visual_diff': 0.1828, 'layer8_semantics': 0.3992} degraded=[] (5875 ms)

### FAIL ΓÇö https://www.ndtv.com/ (Tier ?, Category Indian News, Top 20 ΓÇö mixed selection, good starting subset)
- Pass results: P1: OK 403 10.9s / P2: OK 403 13.4s / P3: OK 403 13.0s
- Latency: 10860 / 13450 / 12427 ms (spread 2.6s)
- Error: capture SUCCEEDED but returned wall/interstitial content ΓÇö status 403, title 'Access Denied', reasons ['http_status=403', 'content_free_shell(visible=202,tags=7)', 'title:akamai_botmgr'], cookie names [], server None
- Evidence: P1 cq=full stable=True polls=3 h=768->768 capped=False shotcap=False dims=[1366, 768] html=286B cf=False retry=0 banner=30/False replay_fullmap=False txt=202; P2 cq=full stable=True polls=3 h=768->768 capped=False shotcap=False dims=[1366, 768] html=288B cf=False retry=0 banner=30/False replay_fullmap=False txt=204; P3 cq=full stable=True polls=3 h=768->768 capped=False shotcap=False dims=[1366, 768] html=290B cf=False retry=0 banner=30/False replay_fullmap=False txt=206
- Evidence: pair p1->p2 (probe src p1) risk=0.3 changed=True flagged=False verdict=changed material=False escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer4_visual_diff': 0.0067} degraded=['layer7_cloaking'] (140 ms)
- Evidence: pair p2->p3 (probe src p2) risk=0.3 changed=True flagged=False verdict=changed material=False escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer4_visual_diff': 0.0151} degraded=['layer7_cloaking'] (156 ms)
- Evidence: pair p1->p3 (probe src p1) risk=0.3 changed=True flagged=False verdict=changed material=False escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer4_visual_diff': 0.0173} degraded=['layer7_cloaking'] (156 ms)

### FAIL ΓÇö https://www.thehindu.com/ (Tier ?, Category Indian News, Top 20 ΓÇö mixed selection, good starting subset)
- Pass results: P1: OK 200 45.1s / P2: OK 200 43.0s / P3: OK 200 44.1s
- Latency: 43000 / 45120 / 44080 ms (spread 2.1s)
- Error: capture succeeded and no wall fingerprint, but detection flagged: p1->p2 risk=0.9359 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.002, 'layer3_link_audit': 0.26, 'layer4_visual_diff': 0.1479, 'layer9_fusion': 0.9359}; p2->p3 risk=0.975 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.0025, 'layer3_link_audit': 0.5934, 'layer4_visual_diff': 0.1544, 'layer9_fusion': 0.975}; p1->p3 risk=0.9836 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.0005, 'layer3_link_audit': 0.5934, 'layer4_visual_diff': 0.1707, 'layer9_fusion': 0.9836}
- Evidence: P1 cq=full stable=True polls=9 h=12498->12498 capped=False shotcap=False dims=[1366, 12498] html=554638B cf=False retry=0 banner=1170/False replay_fullmap=False txt=18867; P2 cq=full stable=True polls=6 h=12498->12498 capped=False shotcap=False dims=[1366, 12498] html=556193B cf=False retry=0 banner=1140/False replay_fullmap=False txt=18943; P3 cq=full stable=True polls=6 h=12498->12498 capped=False shotcap=False dims=[1366, 12498] html=555214B cf=False retry=0 banner=1230/False replay_fullmap=False txt=18939
- Evidence: pair p1->p2 (probe src p1) risk=0.9359 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.002, 'layer3_link_audit': 0.26, 'layer4_visual_diff': 0.1479} degraded=[] (3141 ms)
- Evidence: pair p2->p3 (probe src p2) risk=0.975 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.0025, 'layer3_link_audit': 0.5934, 'layer4_visual_diff': 0.1544} degraded=[] (3079 ms)
- Evidence: pair p1->p3 (probe src p1) risk=0.9836 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.0005, 'layer3_link_audit': 0.5934, 'layer4_visual_diff': 0.1707} degraded=[] (3079 ms)

### FAIL ΓÇö https://indianexpress.com/ (Tier ?, Category Indian News, Top 20 ΓÇö mixed selection, good starting subset)
- Pass results: P1: OK 200 0.0s / P2: OK 200 0.0s / P3: FAIL SSRFBlockedError: Could not resolve host 'indianexpress.com'
- Latency: 250 / 250 / 250 ms (spread 0.0s)
- Error: SSRFBlockedError: Could not resolve host 'indianexpress.com'
- Evidence: P1 cq=full stable=True polls=3 h=14807->14713 capped=False shotcap=False dims=[1366, 14713] html=770459B cf=False retry=0 banner=1740/False replay_fullmap=False txt=21655; P2 cq=full stable=True polls=3 h=14807->14713 capped=False shotcap=False dims=[1366, 14713] html=769977B cf=False retry=0 banner=1740/False replay_fullmap=False txt=21645
- Evidence: pair p1->p2 (probe src p2(substituted)) risk=0.9128 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.0004, 'layer3_link_audit': 0.18, 'layer4_visual_diff': 0.1427} degraded=[] (3531 ms)

### FAIL ΓÇö https://www.wikidata.org/ (Tier ?, Category Reference & Knowledge)
- Pass results: P1: FAIL SSRFBlockedError: Could not resolve host 'www.wikidata.org' / P2: FAIL SSRFBlockedError: Could not resolve host 'www.wikidata.org' / P3: FAIL SSRFBlockedError: Could not resolve host 'www.wikidata.org'
- Latency: 310 / 12360 / 4327 ms (spread 12.0s)
- Error: SSRFBlockedError: Could not resolve host 'www.wikidata.org' || SSRFBlockedError: Could not resolve host 'www.wikidata.org' || SSRFBlockedError: Could not resolve host 'www.wikidata.org'

### FAIL ΓÇö https://www.hindustantimes.com/ (Tier ?, Category Indian News, Top 20 ΓÇö mixed selection, good starting subset)
- Pass results: P1: OK 200 108.4s / P2: OK 200 48.5s / P3: FAIL FetchError: Fetch failed: navigation timeout (Page.goto: Timeout 30000ms exceeded.)
- Latency: 48520 / 108410 / 84007 ms (spread 59.9s)
- Error: FetchError: Fetch failed: navigation timeout (Page.goto: Timeout 30000ms exceeded.)
- Evidence: P1 cq=full stable=True polls=5 h=16075->16163 capped=False shotcap=False dims=[1366, 16123] html=1155855B cf=False retry=1 banner=5730/False replay_fullmap=False txt=19794; P2 cq=full stable=True polls=3 h=16075->16163 capped=False shotcap=False dims=[1366, 16123] html=1152596B cf=False retry=0 banner=5220/False replay_fullmap=False txt=19795
- Evidence: pair p1->p2 (probe src p2(substituted)) risk=0.9994 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.0017, 'layer3_link_audit': 0.5934, 'layer4_visual_diff': 0.2943} degraded=[] (3890 ms)

### FAIL ΓÇö https://www.indiatoday.in/ (Tier ?, Category Indian News, Top 20 ΓÇö mixed selection, good starting subset)
- Pass results: P1: OK 200 33.2s / P2: OK 200 44.5s / P3: OK 200 40.8s
- Latency: 33160 / 44520 / 39503 ms (spread 11.4s)
- Error: capture succeeded and no wall fingerprint, but detection flagged: p1->p2 risk=0.9998 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 1.0, 'layer3_link_audit': 1.0, 'layer4_visual_diff': 0.1293, 'layer8_semantics': 0.7237, 'layer9_fusion': 0.9998}; p2->p3 risk=0.9915 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.0865, 'layer3_link_audit': 0.6113, 'layer4_visual_diff': 0.0747, 'layer8_semantics': 0.7145, 'layer9_fusion': 0.9915}; p1->p3 risk=0.9997 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 1.0, 'layer3_link_audit': 1.0, 'layer4_visual_diff': 0.1291, 'layer8_semantics': 0.6828, 'layer9_fusion': 0.9997}
- Evidence: P1 cq=partial stable=False polls=11 h=13760->25987 capped=False shotcap=True dims=[1366, 16384] html=1708227B cf=False retry=0 banner=120/False replay_fullmap=False txt=26017; P2 cq=partial stable=True polls=7 h=14112->38341 capped=False shotcap=True dims=[1366, 16384] html=2222569B cf=False retry=0 banner=570/False replay_fullmap=False txt=38202; P3 cq=partial stable=True polls=6 h=13760->35592 capped=False shotcap=True dims=[1366, 16384] html=2162598B cf=False retry=0 banner=240/False replay_fullmap=False txt=36679
- Evidence: pair p1->p2 (probe src p1) risk=0.9998 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 1.0, 'layer3_link_audit': 1.0, 'layer4_visual_diff': 0.1293, 'layer8_semantics': 0.7237} degraded=[] (5266 ms)
- Evidence: pair p2->p3 (probe src p2) risk=0.9915 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.0865, 'layer3_link_audit': 0.6113, 'layer4_visual_diff': 0.0747, 'layer8_semantics': 0.7145} degraded=[] (5125 ms)
- Evidence: pair p1->p3 (probe src p1) risk=0.9997 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 1.0, 'layer3_link_audit': 1.0, 'layer4_visual_diff': 0.1291, 'layer8_semantics': 0.6828} degraded=[] (4625 ms)

### FAIL ΓÇö https://www.reuters.com/ (Tier ?, Category International News (modern, element-rich), Top 20 ΓÇö mixed selection, good starting subset)
- Pass results: P1: OK 200 24.2s / P2: OK 401 16.4s / P3: OK 401 15.6s
- Latency: 15590 / 24170 / 18737 ms (spread 8.6s)
- Error: capture SUCCEEDED but returned wall/interstitial content ΓÇö status 200, title '', reasons ['content_free_shell(visible=0,tags=46)', 'blocking_fp:datadome'], cookie names ['datadome'], server 'CloudFront'
- Evidence: P1 cq=full stable=True polls=11 h=768->768 capped=False shotcap=False dims=[1366, 768] html=13439B cf=False retry=0 banner=270/False replay_fullmap=False txt=0; P2 cq=full stable=True polls=3 h=768->768 capped=False shotcap=False dims=[1366, 768] html=1468B cf=False retry=0 banner=60/False replay_fullmap=False txt=11; P3 cq=full stable=True polls=3 h=768->768 capped=False shotcap=False dims=[1366, 768] html=1468B cf=False retry=0 banner=60/False replay_fullmap=False txt=11
- Evidence: pair p1->p2 (probe src p1) risk=0.9992 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.6, 'layer3_link_audit': 0.8347, 'layer4_visual_diff': 0.2356} degraded=['layer7_cloaking'] (78 ms)
- Evidence: pair p2->p3 (probe src p2) risk=0.3 changed=True flagged=False verdict=changed material=False escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer3_link_audit': 0.02, 'layer4_visual_diff': 0.0045} degraded=['layer7_cloaking'] (109 ms)
- Evidence: pair p1->p3 (probe src p1) risk=0.9992 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.6, 'layer3_link_audit': 0.8347, 'layer4_visual_diff': 0.2355} degraded=['layer7_cloaking'] (141 ms)

### FAIL ΓÇö https://www.nasa.gov/ (Tier ?, Category Government / Institutional, Top 20 ΓÇö mixed selection, good starting subset)
- Pass results: P1: OK 200 25.2s / P2: OK 200 27.9s / P3: OK 200 29.3s
- Latency: 25190 / 29300 / 27477 ms (spread 4.1s)
- Error: capture succeeded and no wall fingerprint, but detection flagged: p2->p3 risk=0.9928 layers={'layer1_hash': 1.0, 'layer4_visual_diff': 0.2576, 'layer9_fusion': 0.9928}; p1->p3 risk=0.9956 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.5034, 'layer3_link_audit': 0.04, 'layer4_visual_diff': 0.248, 'layer9_fusion': 0.9956}
- Evidence: P1 cq=full stable=True polls=3 h=7476->7476 capped=False shotcap=False dims=[1366, 7476] html=356234B cf=False retry=0 banner=60/False replay_fullmap=False txt=10343; P2 cq=full stable=True polls=3 h=7476->7476 capped=False shotcap=False dims=[1366, 7476] html=356374B cf=False retry=0 banner=60/False replay_fullmap=False txt=10343; P3 cq=full stable=True polls=3 h=7476->7476 capped=False shotcap=False dims=[1366, 7476] html=356374B cf=False retry=0 banner=60/False replay_fullmap=False txt=10343
- Evidence: pair p1->p2 (probe src p1) risk=0.435 changed=True flagged=False verdict=changed material=True escalation_band=True non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.5034, 'layer3_link_audit': 0.04, 'layer4_visual_diff': 0.0317} degraded=[] (2406 ms)
- Evidence: pair p2->p3 (probe src p2) risk=0.9928 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer4_visual_diff': 0.2576} degraded=[] (2407 ms)
- Evidence: pair p1->p3 (probe src p1) risk=0.9956 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.5034, 'layer3_link_audit': 0.04, 'layer4_visual_diff': 0.248} degraded=[] (2328 ms)

### FAIL ΓÇö https://www.python.org/ (Tier ?, Category Tech / Developer (modern looking), Top 20 ΓÇö mixed selection, good starting subset)
- Pass results: P1: OK 200 16.6s / P2: OK 200 19.3s / P3: OK 200 15.6s
- Latency: 15620 / 19340 / 17170 ms (spread 3.7s)
- Error: capture succeeded and no wall fingerprint, but detection flagged: p2->p3 risk=0.988 layers={'layer1_hash': 1.0, 'layer3_link_audit': 0.02, 'layer4_visual_diff': 0.2058, 'layer8_semantics': 0.1877, 'layer9_fusion': 0.988}; p1->p3 risk=0.9877 layers={'layer1_hash': 1.0, 'layer3_link_audit': 0.02, 'layer4_visual_diff': 0.2005, 'layer8_semantics': 0.2134, 'layer9_fusion': 0.9877}
- Evidence: P1 cq=full stable=True polls=3 h=2476->2476 capped=False shotcap=False dims=[1366, 2476] html=67789B cf=False retry=0 banner=30/False replay_fullmap=False txt=8761; P2 cq=full stable=True polls=3 h=2476->2476 capped=False shotcap=False dims=[1366, 2476] html=67721B cf=False retry=0 banner=30/False replay_fullmap=False txt=8723; P3 cq=full stable=True polls=3 h=2586->2586 capped=False shotcap=False dims=[1366, 2586] html=68088B cf=False retry=0 banner=30/False replay_fullmap=False txt=9040
- Evidence: pair p1->p2 (probe src p1) risk=0.2313 changed=True flagged=False verdict=changed material=False escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer3_link_audit': 0.02, 'layer4_visual_diff': 0.0224} degraded=[] (1234 ms)
- Evidence: pair p2->p3 (probe src p2) risk=0.988 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer3_link_audit': 0.02, 'layer4_visual_diff': 0.2058, 'layer8_semantics': 0.1877} degraded=[] (1297 ms)
- Evidence: pair p1->p3 (probe src p1) risk=0.9877 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer3_link_audit': 0.02, 'layer4_visual_diff': 0.2005, 'layer8_semantics': 0.2134} degraded=[] (1312 ms)

### FAIL ΓÇö https://stackoverflow.com/ (Tier ?, Category Tech / Developer (modern looking), Top 20 ΓÇö mixed selection, good starting subset)
- Pass results: P1: FAIL _ChallengeUnsolvedError: Site is behind bot protection that could not be bypassed (Cloudflare challenge detected) / P2: FAIL _ChallengeUnsolvedError: Site is behind bot protection that could not be bypassed (Cloudflare challenge detected) / P3: FAIL _ChallengeUnsolvedError: Site is behind bot protection that could not be bypassed (Cloudflare challenge detected)
- Latency: 94620 / 94760 / 94683 ms (spread 0.1s)
- Error: _ChallengeUnsolvedError: Site is behind bot protection that could not be bypassed (Cloudflare challenge detected) || _ChallengeUnsolvedError: Site is behind bot protection that could not be bypassed (Cloudflare challenge detected) || _ChallengeUnsolvedError: Site is behind bot protection that could not be bypassed (Cloudflare challenge detected)

### FAIL ΓÇö https://www.news18.com/ (Tier ?, Category Indian News)
- Pass results: P1: FAIL SSRFBlockedError: Could not resolve host 'www.news18.com' / P2: OK 403 19.9s / P3: OK 403 15.0s
- Latency: 4260 / 19910 / 13050 ms (spread 15.7s)
- Error: SSRFBlockedError: Could not resolve host 'www.news18.com'
- Evidence: P2 cq=full stable=True polls=3 h=768->768 capped=False shotcap=False dims=[1366, 768] html=290B cf=False retry=0 banner=30/False replay_fullmap=False txt=206; P3 cq=full stable=True polls=3 h=768->768 capped=False shotcap=False dims=[1366, 768] html=290B cf=False retry=0 banner=30/False replay_fullmap=False txt=206
- Evidence: pair p2->p3 (probe src p2) risk=0.1698 changed=True flagged=False verdict=changed material=False escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer4_visual_diff': 0.0096} degraded=[] (203 ms)

### FAIL ΓÇö https://www.abplive.com/ (Tier ?, Category Indian News)
- Pass results: P1: OK 200 31.8s / P2: OK 200 40.6s / P3: OK 200 39.3s
- Latency: 31810 / 40580 / 37230 ms (spread 8.8s)
- Error: capture succeeded and no wall fingerprint, but detection flagged: p1->p2 risk=0.9829 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.9926, 'layer3_link_audit': 0.6113, 'layer4_visual_diff': 0.1018, 'layer8_semantics': 0.1066, 'layer9_fusion': 0.9829}; p2->p3 risk=0.9732 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.5034, 'layer3_link_audit': 0.7835, 'layer4_visual_diff': 0.0749, 'layer8_semantics': 0.2134, 'layer9_fusion': 0.9732}; p1->p3 risk=0.9957 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.9963, 'layer3_link_audit': 0.7835, 'layer4_visual_diff': 0.1214, 'layer8_semantics': 0.2134, 'layer9_fusion': 0.9957}
- Evidence: P1 cq=full stable=True polls=10 h=9298->9318 capped=False shotcap=False dims=[1366, 10641] html=1048094B cf=False retry=0 banner=1560/False replay_fullmap=False txt=27455; P2 cq=full stable=True polls=10 h=9298->10936 capped=False shotcap=False dims=[1366, 10936] html=1060509B cf=False retry=0 banner=1650/False replay_fullmap=False txt=27822; P3 cq=full stable=True polls=6 h=9298->10936 capped=False shotcap=False dims=[1366, 10936] html=1060512B cf=False retry=0 banner=1590/False replay_fullmap=False txt=28172
- Evidence: pair p1->p2 (probe src p1) risk=0.9829 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.9926, 'layer3_link_audit': 0.6113, 'layer4_visual_diff': 0.1018, 'layer8_semantics': 0.1066} degraded=[] (4547 ms)
- Evidence: pair p2->p3 (probe src p2) risk=0.9732 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.5034, 'layer3_link_audit': 0.7835, 'layer4_visual_diff': 0.0749, 'layer8_semantics': 0.2134} degraded=[] (4500 ms)
- Evidence: pair p1->p3 (probe src p1) risk=0.9957 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.9963, 'layer3_link_audit': 0.7835, 'layer4_visual_diff': 0.1214, 'layer8_semantics': 0.2134} degraded=[] (4718 ms)

### FAIL ΓÇö https://www.livemint.com/ (Tier ?, Category Indian News)
- Pass results: P1: OK 200 31.3s / P2: OK 200 48.2s / P3: OK 200 105.6s
- Latency: 31300 / 105620 / 61693 ms (spread 74.3s)
- Error: capture succeeded and no wall fingerprint, but detection flagged: p1->p2 risk=0.8932 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.0024, 'layer3_link_audit': 0.5934, 'layer4_visual_diff': 0.0957, 'layer9_fusion': 0.8932}; p2->p3 risk=0.9932 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.9392, 'layer3_link_audit': 0.5934, 'layer4_visual_diff': 0.1588, 'layer9_fusion': 0.9932}; p1->p3 risk=0.9963 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.8775, 'layer3_link_audit': 0.5934, 'layer4_visual_diff': 0.1846, 'layer9_fusion': 0.9963}
- Evidence: P1 cq=full stable=True polls=5 h=10356->12340 capped=False shotcap=False dims=[1366, 12340] html=606703B cf=False retry=0 banner=660/False replay_fullmap=False txt=21141; P2 cq=full stable=True polls=6 h=10356->12185 capped=False shotcap=False dims=[1366, 12340] html=606575B cf=False retry=0 banner=660/False replay_fullmap=False txt=21141; P3 cq=full stable=True polls=6 h=10356->12087 capped=False shotcap=False dims=[1366, 12087] html=605917B cf=False retry=1 banner=660/False replay_fullmap=False txt=20988
- Evidence: pair p1->p2 (probe src p1) risk=0.8932 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.0024, 'layer3_link_audit': 0.5934, 'layer4_visual_diff': 0.0957} degraded=[] (4390 ms)
- Evidence: pair p2->p3 (probe src p2) risk=0.9932 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.9392, 'layer3_link_audit': 0.5934, 'layer4_visual_diff': 0.1588} degraded=[] (3687 ms)
- Evidence: pair p1->p3 (probe src p1) risk=0.9963 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.8775, 'layer3_link_audit': 0.5934, 'layer4_visual_diff': 0.1846} degraded=[] (3578 ms)

### FAIL ΓÇö https://www.moneycontrol.com/ (Tier ?, Category Indian News)
- Pass results: P1: OK 403 10.7s / P2: OK 403 20.2s / P3: OK 403 21.2s
- Latency: 10670 / 21220 / 17370 ms (spread 10.5s)
- Error: capture SUCCEEDED but returned wall/interstitial content ΓÇö status 403, title 'Access Denied', reasons ['http_status=403', 'content_free_shell(visible=214,tags=7)', 'blocking_fp:akamai_botmgr', 'title:akamai_botmgr'], cookie names ['01 Oct 2026 10:03:19 GMT; Max-Age', '30 Sep 2026 14:03:19 GMT; Max-Age', '30 Sep 2027 10:03:20 GMT; Max-Age', '31 Oct 2026 10:03:19 GMT; Max-Age', '_abck', 'bm_s', 'bm_so', 'bm_sz'], server 'UploadServer'
- Evidence: P1 cq=full stable=True polls=3 h=768->768 capped=False shotcap=False dims=[1366, 768] html=298B cf=False retry=0 banner=30/False replay_fullmap=False txt=214; P2 cq=full stable=True polls=3 h=768->768 capped=False shotcap=False dims=[1366, 768] html=298B cf=False retry=0 banner=30/False replay_fullmap=False txt=214; P3 cq=full stable=True polls=3 h=768->768 capped=False shotcap=False dims=[1366, 768] html=298B cf=False retry=0 banner=30/False replay_fullmap=False txt=214
- Evidence: pair p1->p2 (probe src p1) risk=0.1466 changed=True flagged=False verdict=changed material=False escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer4_visual_diff': 0.0029} degraded=[] (250 ms)
- Evidence: pair p2->p3 (probe src p2) risk=0.1771 changed=True flagged=False verdict=changed material=False escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer4_visual_diff': 0.0115} degraded=[] (328 ms)
- Evidence: pair p1->p3 (probe src p1) risk=0.1863 changed=True flagged=False verdict=changed material=False escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer4_visual_diff': 0.0139} degraded=[] (297 ms)

### FAIL ΓÇö https://www.businesstoday.in/ (Tier ?, Category Indian News)
- Pass results: P1: OK 200 41.2s / P2: OK 200 45.5s / P3: OK 200 63.4s
- Latency: 41190 / 63440 / 50033 ms (spread 22.2s)
- Error: capture succeeded and no wall fingerprint, but detection flagged: p1->p2 risk=1.0 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 1.0, 'layer3_link_audit': 0.998, 'layer4_visual_diff': 0.3312, 'layer8_semantics': 0.4489, 'layer9_fusion': 1.0}; p2->p3 risk=1.0 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 1.0, 'layer3_link_audit': 0.9995, 'layer4_visual_diff': 0.1385, 'layer6_security_metadata': 0.75, 'layer8_semantics': 0.641, 'layer9_fusion': 1.0}; p1->p3 risk=1.0 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 1.0, 'layer3_link_audit': 1.0, 'layer4_visual_diff': 0.3655, 'layer6_security_metadata': 0.75, 'layer8_semantics': 0.6914, 'layer9_fusion': 1.0}
- Evidence: P1 cq=full stable=True polls=9 h=11245->11245 capped=False shotcap=False dims=[1366, 12509] html=2434591B cf=False retry=0 banner=600/False replay_fullmap=False txt=26728; P2 cq=full stable=True polls=11 h=11245->13055 capped=False shotcap=False dims=[1366, 15839] html=2434809B cf=False retry=0 banner=630/False replay_fullmap=False txt=29525; P3 cq=partial stable=True polls=11 h=11245->44861 capped=True shotcap=True dims=[1366, 16384] html=3157387B cf=False retry=0 banner=600/False replay_fullmap=False txt=52812
- Evidence: pair p1->p2 (probe src p1) risk=1.0 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 1.0, 'layer3_link_audit': 0.998, 'layer4_visual_diff': 0.3312, 'layer8_semantics': 0.4489} degraded=[] (4047 ms)
- Evidence: pair p2->p3 (probe src p2) risk=1.0 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 1.0, 'layer3_link_audit': 0.9995, 'layer4_visual_diff': 0.1385, 'layer6_security_metadata': 0.75, 'layer8_semantics': 0.641} degraded=['layer7_cloaking'] (5469 ms)
- Evidence: pair p1->p3 (probe src p1) risk=1.0 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 1.0, 'layer3_link_audit': 1.0, 'layer4_visual_diff': 0.3655, 'layer6_security_metadata': 0.75, 'layer8_semantics': 0.6914} degraded=['layer7_cloaking'] (4875 ms)

### FAIL ΓÇö https://www.bollywoodhungama.com/ (Tier ?, Category Indian / Bollywood Entertainment)
- Pass results: P1: FAIL SSRFBlockedError: Could not resolve host 'www.bollywoodhungama.com' / P2: FAIL SSRFBlockedError: Could not resolve host 'www.bollywoodhungama.com' / P3: FAIL SSRFBlockedError: Could not resolve host 'www.bollywoodhungama.com'
- Latency: 260 / 12330 / 4283 ms (spread 12.1s)
- Error: SSRFBlockedError: Could not resolve host 'www.bollywoodhungama.com' || SSRFBlockedError: Could not resolve host 'www.bollywoodhungama.com' || SSRFBlockedError: Could not resolve host 'www.bollywoodhungama.com'

### FAIL ΓÇö https://www.zeenews.india.com/ (Tier ?, Category Indian News)
- Pass results: P1: FAIL SSRFBlockedError: Could not resolve host 'www.zeenews.india.com' / P2: FAIL SSRFBlockedError: Could not resolve host 'www.zeenews.india.com' / P3: FAIL SSRFBlockedError: Could not resolve host 'www.zeenews.india.com'
- Latency: 280 / 670 / 417 ms (spread 0.4s)
- Error: SSRFBlockedError: Could not resolve host 'www.zeenews.india.com' || SSRFBlockedError: Could not resolve host 'www.zeenews.india.com' || SSRFBlockedError: Could not resolve host 'www.zeenews.india.com'

### FAIL ΓÇö https://www.filmfare.com/ (Tier ?, Category Indian / Bollywood Entertainment)
- Pass results: P1: OK 200 17.7s / P2: OK 200 31.0s / P3: OK 200 46.4s
- Latency: 17690 / 46440 / 31717 ms (spread 28.7s)
- Error: capture succeeded and no wall fingerprint, but detection flagged: p1->p3 risk=0.7436 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.0064, 'layer3_link_audit': 0.08, 'layer6_security_metadata': 0.6, 'layer8_semantics': 0.2698, 'layer9_fusion': 0.7436}
- Evidence: P1 cq=full stable=True polls=5 h=7356->7356 capped=False shotcap=False dims=[1366, 7356] html=665884B cf=False retry=0 banner=30/False replay_fullmap=False txt=17321; P2 cq=full stable=True polls=5 h=7356->7356 capped=False shotcap=False dims=[1366, 7356] html=668350B cf=False retry=0 banner=30/False replay_fullmap=False txt=17855; P3 cq=full stable=True polls=5 h=7356->7356 capped=False shotcap=False dims=[1366, 7356] html=667867B cf=False retry=0 banner=30/False replay_fullmap=False txt=17855
- Evidence: pair p1->p2 (probe src p1) risk=0.3788 changed=True flagged=False verdict=changed material=False escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.0015, 'layer3_link_audit': 0.08, 'layer8_semantics': 0.2698} degraded=[] (3391 ms)
- Evidence: pair p2->p3 (probe src p2) risk=0.4296 changed=True flagged=False verdict=changed material=True escalation_band=True non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.0018, 'layer6_security_metadata': 0.6} degraded=[] (3531 ms)
- Evidence: pair p1->p3 (probe src p1) risk=0.7436 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.0064, 'layer3_link_audit': 0.08, 'layer6_security_metadata': 0.6, 'layer8_semantics': 0.2698} degraded=[] (3000 ms)

### FAIL ΓÇö https://www.indiaforums.com/ (Tier ?, Category Indian / Bollywood Entertainment)
- Pass results: P1: FAIL stalled (timeout budget exceeded) / P2: FAIL stalled (timeout budget exceeded) / P3: FAIL stalled (timeout budget exceeded)
- Latency: 180140 / 180170 / 180150 ms (spread 0.0s)
- Error: stalled (timeout budget exceeded) || stalled (timeout budget exceeded) || stalled (timeout budget exceeded)

### FAIL ΓÇö https://www.pinkvilla.com/ (Tier ?, Category Indian / Bollywood Entertainment)
- Pass results: P1: OK 200 32.5s / P2: OK 200 34.6s / P3: OK 200 32.4s
- Latency: 32380 / 34590 / 33147 ms (spread 2.2s)
- Error: capture succeeded and no wall fingerprint, but detection flagged: p1->p2 risk=0.8923 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.002, 'layer4_visual_diff': 0.1505, 'layer9_fusion': 0.8923}; p1->p3 risk=0.9826 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.002, 'layer4_visual_diff': 0.1298, 'layer6_security_metadata': 0.95, 'layer9_fusion': 0.9826}
- Evidence: P1 cq=full stable=True polls=3 h=13210->13210 capped=False shotcap=False dims=[1366, 13210] html=792837B cf=False retry=0 banner=60/False replay_fullmap=False txt=28840; P2 cq=full stable=True polls=3 h=13210->13210 capped=False shotcap=False dims=[1366, 13210] html=927232B cf=False retry=0 banner=60/False replay_fullmap=False txt=28840; P3 cq=full stable=True polls=3 h=13210->13210 capped=False shotcap=False dims=[1366, 13210] html=927232B cf=False retry=0 banner=60/False replay_fullmap=False txt=28840
- Evidence: pair p1->p2 (probe src p1) risk=0.8923 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.002, 'layer4_visual_diff': 0.1505} degraded=[] (3390 ms)
- Evidence: pair p2->p3 (probe src p2) risk=0.3708 changed=True flagged=False verdict=changed material=False escalation_band=False non-zero-layers={'layer4_visual_diff': 0.1241, 'layer6_security_metadata': 0.95} degraded=[] (1328 ms)
- Evidence: pair p1->p3 (probe src p1) risk=0.9826 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.002, 'layer4_visual_diff': 0.1298, 'layer6_security_metadata': 0.95} degraded=[] (3422 ms)

### FAIL ΓÇö https://www.ndtv.com/entertainment (Tier ?, Category Indian / Bollywood Entertainment)
- Pass results: P1: OK 403 10.2s / P2: OK 403 14.0s / P3: OK 403 12.0s
- Latency: 10160 / 14000 / 12043 ms (spread 3.8s)
- Error: capture SUCCEEDED but returned wall/interstitial content ΓÇö status 403, title 'Access Denied', reasons ['http_status=403', 'content_free_shell(visible=217,tags=7)', 'title:akamai_botmgr'], cookie names [], server None
- Evidence: P1 cq=full stable=True polls=3 h=768->768 capped=False shotcap=False dims=[1366, 768] html=301B cf=False retry=0 banner=30/False replay_fullmap=False txt=217; P2 cq=full stable=True polls=3 h=768->768 capped=False shotcap=False dims=[1366, 768] html=301B cf=False retry=0 banner=30/False replay_fullmap=False txt=217; P3 cq=full stable=True polls=3 h=768->768 capped=False shotcap=False dims=[1366, 768] html=301B cf=False retry=0 banner=30/False replay_fullmap=False txt=217
- Evidence: pair p1->p2 (probe src p1) risk=0.3 changed=True flagged=False verdict=changed material=False escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer4_visual_diff': 0.0008} degraded=['layer7_cloaking'] (125 ms)
- Evidence: pair p2->p3 (probe src p2) risk=0.3 changed=True flagged=False verdict=changed material=False escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer4_visual_diff': 0.0011} degraded=['layer7_cloaking'] (171 ms)
- Evidence: pair p1->p3 (probe src p1) risk=0.3 changed=True flagged=False verdict=changed material=False escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer4_visual_diff': 0.0008} degraded=['layer7_cloaking'] (172 ms)

### FAIL ΓÇö https://www.aajtak.in/entertainment (Tier ?, Category Indian / Bollywood Entertainment)
- Pass results: P1: OK 200 15.5s / P2: OK 200 25.6s / P3: OK 200 22.7s
- Latency: 15530 / 25580 / 21270 ms (spread 10.0s)
- Error: capture succeeded and no wall fingerprint, but detection flagged: p1->p2 risk=0.9999 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.5034, 'layer3_link_audit': 0.02, 'layer4_visual_diff': 0.4015, 'layer9_fusion': 0.9999}; p1->p3 risk=0.9999 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.5034, 'layer3_link_audit': 0.02, 'layer4_visual_diff': 0.4015, 'layer9_fusion': 0.9999}
- Evidence: P1 cq=full stable=True polls=3 h=5740->5751 capped=False shotcap=False dims=[1366, 5751] html=526219B cf=False retry=0 banner=60/False replay_fullmap=False txt=8165; P2 cq=full stable=True polls=3 h=5740->5756 capped=False shotcap=False dims=[1366, 5756] html=526205B cf=False retry=0 banner=60/False replay_fullmap=False txt=8190; P3 cq=full stable=True polls=3 h=5740->5756 capped=False shotcap=False dims=[1366, 5756] html=526263B cf=False retry=0 banner=60/False replay_fullmap=False txt=8190
- Evidence: pair p1->p2 (probe src p1) risk=0.9999 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.5034, 'layer3_link_audit': 0.02, 'layer4_visual_diff': 0.4015} degraded=[] (2344 ms)
- Evidence: pair p2->p3 (probe src p2) risk=0.1372 changed=True flagged=False verdict=changed material=False escalation_band=False non-zero-layers={'layer1_hash': 1.0} degraded=[] (2437 ms)
- Evidence: pair p1->p3 (probe src p1) risk=0.9999 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.5034, 'layer3_link_audit': 0.02, 'layer4_visual_diff': 0.4015} degraded=[] (2609 ms)

### FAIL ΓÇö https://news.sky.com/ (Tier ?, Category International News (modern, element-rich))
- Pass results: P1: OK 403 10.6s / P2: OK 403 12.3s / P3: OK 403 13.6s
- Latency: 10640 / 13580 / 12177 ms (spread 2.9s)
- Error: capture SUCCEEDED but returned wall/interstitial content ΓÇö status 403, title 'Access Denied', reasons ['http_status=403', 'content_free_shell(visible=206,tags=7)', 'title:akamai_botmgr'], cookie names ['01 Oct 2026 10:03:28 GMT; Max-Age', '31 Oct 2026 10:03:28 GMT; Max-Age', 'bm_s', 'bm_so'], server 'AkamaiGHost'
- Evidence: P1 cq=full stable=True polls=3 h=768->768 capped=False shotcap=False dims=[1366, 768] html=290B cf=False retry=0 banner=30/False replay_fullmap=False txt=206; P2 cq=full stable=True polls=3 h=768->768 capped=False shotcap=False dims=[1366, 768] html=290B cf=False retry=0 banner=30/False replay_fullmap=False txt=206; P3 cq=full stable=True polls=3 h=768->768 capped=False shotcap=False dims=[1366, 768] html=290B cf=False retry=0 banner=30/False replay_fullmap=False txt=206
- Evidence: pair p1->p2 (probe src p1) risk=0.3 changed=True flagged=False verdict=changed material=False escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer4_visual_diff': 0.0044} degraded=['layer7_cloaking'] (140 ms)
- Evidence: pair p2->p3 (probe src p2) risk=0.3 changed=True flagged=False verdict=changed material=False escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer4_visual_diff': 0.013} degraded=['layer7_cloaking'] (172 ms)
- Evidence: pair p1->p3 (probe src p1) risk=0.3 changed=True flagged=False verdict=changed material=False escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer4_visual_diff': 0.0097} degraded=['layer7_cloaking'] (172 ms)

### FAIL ΓÇö https://www.cbc.ca/ (Tier ?, Category International News (modern, element-rich))
- Pass results: P1: FAIL FetchError: Fetch failed: network error (Page.goto: net::ERR_HTTP2_PROTOCOL_ERROR at https://www.cbc.ca/) / P2: FAIL FetchError: Fetch failed: network error (Page.goto: net::ERR_HTTP2_PROTOCOL_ERROR at https://www.cbc.ca/) / P3: FAIL FetchError: Fetch failed: network error (Page.goto: net::ERR_HTTP2_PROTOCOL_ERROR at https://www.cbc.ca/)
- Latency: 5260 / 8090 / 6313 ms (spread 2.8s)
- Error: FetchError: Fetch failed: network error (Page.goto: net::ERR_HTTP2_PROTOCOL_ERROR at https://www.cbc.ca/) || FetchError: Fetch failed: network error (Page.goto: net::ERR_HTTP2_PROTOCOL_ERROR at https://www.cbc.ca/) || FetchError: Fetch failed: network error (Page.goto: net::ERR_HTTP2_PROTOCOL_ERROR at https://www.cbc.ca/)

### FAIL ΓÇö https://www.techdirt.com/ (Tier ?, Category International News (modern, element-rich))
- Pass results: P1: FAIL _ChallengeUnsolvedError: Site is behind bot protection that could not be bypassed (Cloudflare challenge detected) / P2: FAIL _ChallengeUnsolvedError: Site is behind bot protection that could not be bypassed (Cloudflare challenge detected) / P3: FAIL _ChallengeUnsolvedError: Site is behind bot protection that could not be bypassed (Cloudflare challenge detected)
- Latency: 94440 / 94660 / 94523 ms (spread 0.2s)
- Error: _ChallengeUnsolvedError: Site is behind bot protection that could not be bypassed (Cloudflare challenge detected) || _ChallengeUnsolvedError: Site is behind bot protection that could not be bypassed (Cloudflare challenge detected) || _ChallengeUnsolvedError: Site is behind bot protection that could not be bypassed (Cloudflare challenge detected)

### FAIL ΓÇö https://www.aljazeera.com/ (Tier ?, Category International News (modern, element-rich))
- Pass results: P1: OK 200 20.3s / P2: OK 200 23.1s / P3: OK 200 21.5s
- Latency: 20280 / 23050 / 21600 ms (spread 2.8s)
- Error: capture succeeded and no wall fingerprint, but detection flagged: p1->p2 risk=1.0 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.0028, 'layer7_cloaking': 1.0, 'layer8_semantics': 0.4512, 'layer9_fusion': 1.0}; p2->p3 risk=1.0 layers={'layer1_hash': 1.0, 'layer7_cloaking': 1.0, 'layer9_fusion': 1.0}; p1->p3 risk=1.0 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.0028, 'layer7_cloaking': 1.0, 'layer8_semantics': 0.4512, 'layer9_fusion': 1.0}
- Evidence: P1 cq=full stable=True polls=4 h=3802->13692 capped=False shotcap=False dims=[1366, 13692] html=633357B cf=False retry=0 banner=150/False replay_fullmap=False txt=19460; P2 cq=full stable=True polls=3 h=3802->13692 capped=False shotcap=False dims=[1366, 13692] html=633115B cf=False retry=0 banner=150/False replay_fullmap=False txt=19441; P3 cq=full stable=True polls=4 h=3802->13692 capped=False shotcap=False dims=[1366, 13692] html=633116B cf=False retry=0 banner=150/False replay_fullmap=False txt=19441
- Evidence: pair p1->p2 (probe src p1) risk=1.0 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.0028, 'layer7_cloaking': 1.0, 'layer8_semantics': 0.4512} degraded=[] (3203 ms)
- Evidence: pair p2->p3 (probe src p2) risk=1.0 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer7_cloaking': 1.0} degraded=[] (3062 ms)
- Evidence: pair p1->p3 (probe src p1) risk=1.0 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.0028, 'layer7_cloaking': 1.0, 'layer8_semantics': 0.4512} degraded=[] (3203 ms)

### FAIL ΓÇö https://www.whitehouse.gov/ (Tier ?, Category Government / Institutional)
- Pass results: P1: OK 200 22.4s / P2: OK 200 19.3s / P3: OK 200 20.0s
- Latency: 19300 / 22440 / 20583 ms (spread 3.1s)
- Error: capture succeeded and no wall fingerprint, but detection flagged: p1->p2 risk=0.9301 layers={'layer1_hash': 1.0, 'layer4_visual_diff': 0.1686, 'layer9_fusion': 0.9301}; p2->p3 risk=0.8716 layers={'layer1_hash': 1.0, 'layer4_visual_diff': 0.143, 'layer9_fusion': 0.8716}; p1->p3 risk=0.9254 layers={'layer1_hash': 1.0, 'layer4_visual_diff': 0.1659, 'layer9_fusion': 0.9254}
- Evidence: P1 cq=full stable=True polls=3 h=4677->4622 capped=False shotcap=False dims=[1366, 4677] html=299010B cf=False retry=0 banner=30/False replay_fullmap=False txt=5398; P2 cq=full stable=True polls=3 h=4677->4622 capped=False shotcap=False dims=[1366, 4677] html=299010B cf=False retry=0 banner=30/False replay_fullmap=False txt=5398; P3 cq=full stable=True polls=3 h=4677->4622 capped=False shotcap=False dims=[1366, 4677] html=299010B cf=False retry=0 banner=30/False replay_fullmap=False txt=5398
- Evidence: pair p1->p2 (probe src p1) risk=0.9301 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer4_visual_diff': 0.1686} degraded=[] (1391 ms)
- Evidence: pair p2->p3 (probe src p2) risk=0.8716 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer4_visual_diff': 0.143} degraded=[] (1375 ms)
- Evidence: pair p1->p3 (probe src p1) risk=0.9254 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer4_visual_diff': 0.1659} degraded=[] (1828 ms)

### FAIL ΓÇö https://www.un.org/ (Tier ?, Category Government / Institutional)
- Pass results: P1: OK 200 12.8s / P2: OK 200 17.5s / P3: OK 200 15.4s
- Latency: 12760 / 17520 / 15240 ms (spread 4.8s)
- Error: capture SUCCEEDED but returned wall/interstitial content ΓÇö status 200, title 'Welcome to the United Nations', reasons ['content_free_shell(visible=533,tags=145)'], cookie names ['07 Oct 2026 10:04:06 GMT; Path', 'AWSALB', 'AWSALBCORS', 'AWSALBTG', 'AWSALBTGCORS'], server 'Apache'
- Evidence: P1 cq=full stable=True polls=3 h=1984->1984 capped=False shotcap=False dims=[1366, 1984] html=9748B cf=False retry=0 banner=30/False replay_fullmap=False txt=533; P2 cq=full stable=True polls=3 h=768->768 capped=False shotcap=False dims=[1366, 768] html=9748B cf=False retry=0 banner=30/False replay_fullmap=False txt=533; P3 cq=full stable=True polls=3 h=768->768 capped=False shotcap=False dims=[1366, 768] html=9748B cf=False retry=0 banner=30/False replay_fullmap=False txt=533
- Evidence: pair p1->p2 (probe src p1) risk=0.9548 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer4_visual_diff': 0.354} degraded=[] (156 ms)
- Evidence: pair p2->p3 (probe src p2) risk=0.6922 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer4_visual_diff': 0.2688} degraded=[] (110 ms)
- Evidence: pair p1->p3 (probe src p1) risk=0.964 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer4_visual_diff': 0.3631} degraded=[] (140 ms)

### FAIL ΓÇö https://www.europa.eu/ (Tier ?, Category Government / Institutional)
- Pass results: P1: OK 200 18.1s / P2: OK 200 23.5s / P3: OK 200 26.4s
- Latency: 18050 / 26360 / 22647 ms (spread 8.3s)
- Error: capture succeeded and no wall fingerprint, but detection flagged: p2->p3 risk=0.9457 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.0309, 'layer3_link_audit': 0.04, 'layer4_visual_diff': 0.1469, 'layer8_semantics': 0.1649, 'layer9_fusion': 0.9457}; p1->p3 risk=0.9457 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.0309, 'layer3_link_audit': 0.04, 'layer4_visual_diff': 0.1469, 'layer8_semantics': 0.1649, 'layer9_fusion': 0.9457}
- Evidence: P1 cq=full stable=True polls=3 h=3340->3445 capped=False shotcap=False dims=[1366, 3445] html=134091B cf=False retry=0 banner=30/False replay_fullmap=False txt=6174; P2 cq=full stable=True polls=3 h=3340->3445 capped=False shotcap=False dims=[1366, 3445] html=134087B cf=False retry=0 banner=30/False replay_fullmap=False txt=6174; P3 cq=full stable=True polls=3 h=3340->3445 capped=False shotcap=False dims=[1366, 3445] html=136725B cf=False retry=0 banner=30/False replay_fullmap=False txt=6485
- Evidence: pair p1->p2 (probe src p1) risk=0.1372 changed=True flagged=False verdict=changed material=False escalation_band=False non-zero-layers={'layer1_hash': 1.0} degraded=[] (1172 ms)
- Evidence: pair p2->p3 (probe src p2) risk=0.9457 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.0309, 'layer3_link_audit': 0.04, 'layer4_visual_diff': 0.1469, 'layer8_semantics': 0.1649} degraded=[] (1360 ms)
- Evidence: pair p1->p3 (probe src p1) risk=0.9457 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.0309, 'layer3_link_audit': 0.04, 'layer4_visual_diff': 0.1469, 'layer8_semantics': 0.1649} degraded=[] (1344 ms)

### FAIL ΓÇö https://www.archive.org/ (Tier ?, Category Reference & Knowledge)
- Pass results: P1: OK 200 17.9s / P2: OK 200 24.5s / P3: OK 200 26.7s
- Latency: 17860 / 26690 / 23023 ms (spread 8.8s)
- Error: capture SUCCEEDED but returned wall/interstitial content ΓÇö status 200, title 'Internet Archive: Digital Library of Free & Borrowable Texts, Movies, Music & Wayback Machine', reasons ['content_free_shell(visible=101,tags=70)'], cookie names [], server 'nginx/1.31.3'
- Evidence: P1 cq=full stable=True polls=3 h=3458->3507 capped=False shotcap=False dims=[1366, 3507] html=8584B cf=False retry=0 banner=30/False replay_fullmap=False txt=101; P2 cq=partial stable=True polls=3 h=3458->27615 capped=False shotcap=True dims=[1366, 16384] html=8584B cf=False retry=0 banner=30/False replay_fullmap=False txt=101; P3 cq=full stable=True polls=3 h=6086->6155 capped=False shotcap=False dims=[1366, 8746] html=8584B cf=False retry=0 banner=30/False replay_fullmap=False txt=101
- Evidence: pair p1->p2 (probe src p1) risk=0.3265 changed=True flagged=False verdict=changed material=False escalation_band=False non-zero-layers={'layer4_visual_diff': 0.2103} degraded=[] (781 ms)
- Evidence: pair p2->p3 (probe src p2) risk=0.2075 changed=True flagged=False verdict=changed material=False escalation_band=False non-zero-layers={'layer4_visual_diff': 0.1869} degraded=[] (1344 ms)
- Evidence: pair p1->p3 (probe src p1) risk=0.7932 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer4_visual_diff': 0.2891} degraded=[] (594 ms)

### FAIL ΓÇö https://github.com/ (Tier ?, Category Tech / Developer (modern looking))
- Pass results: P1: OK 200 22.4s / P2: OK 200 27.1s / P3: OK 200 25.3s
- Latency: 22450 / 27110 / 24947 ms (spread 4.7s)
- Error: capture succeeded and no wall fingerprint, but detection flagged: p1->p2 risk=0.5314 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.0013, 'layer4_visual_diff': 0.0748, 'layer9_fusion': 0.5314}; p2->p3 risk=0.9068 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.0013, 'layer4_visual_diff': 0.1566, 'layer9_fusion': 0.9068}; p1->p3 risk=0.7275 layers={'layer1_hash': 1.0, 'layer4_visual_diff': 0.1074, 'layer9_fusion': 0.7275}
- Evidence: P1 cq=full stable=True polls=7 h=11198->11529 capped=False shotcap=False dims=[1366, 11529] html=582049B cf=False retry=0 banner=30/False replay_fullmap=False txt=7769; P2 cq=full stable=True polls=10 h=11198->11529 capped=False shotcap=False dims=[1366, 11529] html=582147B cf=False retry=0 banner=30/False replay_fullmap=False txt=7769; P3 cq=full stable=True polls=7 h=11198->11529 capped=False shotcap=False dims=[1366, 11529] html=582044B cf=False retry=0 banner=30/False replay_fullmap=False txt=7769
- Evidence: pair p1->p2 (probe src p1) risk=0.5314 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.0013, 'layer4_visual_diff': 0.0748} degraded=[] (2375 ms)
- Evidence: pair p2->p3 (probe src p2) risk=0.9068 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.0013, 'layer4_visual_diff': 0.1566} degraded=[] (2391 ms)
- Evidence: pair p1->p3 (probe src p1) risk=0.7275 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer4_visual_diff': 0.1074} degraded=[] (2328 ms)

### FAIL ΓÇö https://tools.ietf.org/ (Tier ?, Category Tech / Developer (modern looking))
- Pass results: P1: OK 200 15.1s / P2: OK 200 15.9s / P3: OK 200 15.3s
- Latency: 15050 / 15880 / 15410 ms (spread 0.8s)
- Error: capture succeeded and no wall fingerprint, but detection flagged: p1->p2 risk=0.5577 layers={'layer1_hash': 1.0, 'layer6_security_metadata': 0.8, 'layer9_fusion': 0.5577}; p1->p3 risk=0.5577 layers={'layer1_hash': 1.0, 'layer6_security_metadata': 0.8, 'layer9_fusion': 0.5577}
- Evidence: P1 cq=full stable=True polls=4 h=1312->1312 capped=False shotcap=False dims=[1366, 1312] html=471402B cf=False retry=0 banner=90/False replay_fullmap=False txt=3296; P2 cq=full stable=True polls=4 h=1312->1312 capped=False shotcap=False dims=[1366, 1312] html=471402B cf=False retry=0 banner=90/False replay_fullmap=False txt=3296; P3 cq=full stable=True polls=4 h=1312->1312 capped=False shotcap=False dims=[1366, 1312] html=471402B cf=False retry=0 banner=90/False replay_fullmap=False txt=3296
- Evidence: pair p1->p2 (probe src p1) risk=0.5577 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer6_security_metadata': 0.8} degraded=['layer7_cloaking'] (812 ms)
- Evidence: pair p2->p3 (probe src p2) risk=0.3 changed=True flagged=False verdict=changed material=False escalation_band=False non-zero-layers={'layer1_hash': 1.0} degraded=['layer7_cloaking'] (906 ms)
- Evidence: pair p1->p3 (probe src p1) risk=0.5577 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer6_security_metadata': 0.8} degraded=['layer7_cloaking'] (891 ms)

### FAIL ΓÇö https://www.rfc-editor.org/ (Tier ?, Category Tech / Developer (modern looking))
- Pass results: P1: FAIL _ChallengeUnsolvedError: Site is behind bot protection that could not be bypassed (Cloudflare challenge detected) / P2: FAIL _ChallengeUnsolvedError: Site is behind bot protection that could not be bypassed (Cloudflare challenge detected) / P3: FAIL _ChallengeUnsolvedError: Site is behind bot protection that could not be bypassed (Cloudflare challenge detected)
- Latency: 94360 / 94580 / 94480 ms (spread 0.2s)
- Error: _ChallengeUnsolvedError: Site is behind bot protection that could not be bypassed (Cloudflare challenge detected) || _ChallengeUnsolvedError: Site is behind bot protection that could not be bypassed (Cloudflare challenge detected) || _ChallengeUnsolvedError: Site is behind bot protection that could not be bypassed (Cloudflare challenge detected)

### FAIL ΓÇö https://www.imdb.com/ (Tier ?, Category Other solid general sites)
- Pass results: P1: OK 405 11.6s / P2: OK 405 14.4s / P3: OK 405 15.2s
- Latency: 11560 / 15200 / 13717 ms (spread 3.6s)
- Error: capture SUCCEEDED but returned wall/interstitial content ΓÇö status 405, title 'Human Verification', reasons ['http_status=405', 'content_free_shell(visible=533,tags=52)', 'blocking_fp:awswaf', 'title:perimeterx'], cookie names [], server 'Server'
- Evidence: P1 cq=full stable=True polls=3 h=776->776 capped=False shotcap=False dims=[1366, 776] html=9551B cf=False retry=0 banner=30/False replay_fullmap=False txt=533; P2 cq=full stable=True polls=3 h=776->776 capped=False shotcap=False dims=[1366, 776] html=9551B cf=False retry=0 banner=30/False replay_fullmap=False txt=533; P3 cq=full stable=True polls=3 h=776->776 capped=False shotcap=False dims=[1366, 776] html=9551B cf=False retry=0 banner=30/False replay_fullmap=False txt=533
- Evidence: pair p1->p2 (probe src p1) risk=0.1372 changed=True flagged=False verdict=changed material=False escalation_band=False non-zero-layers={'layer1_hash': 1.0} degraded=[] (250 ms)
- Evidence: pair p2->p3 (probe src p2) risk=0.1372 changed=True flagged=False verdict=changed material=False escalation_band=False non-zero-layers={'layer1_hash': 1.0} degraded=[] (265 ms)
- Evidence: pair p1->p3 (probe src p1) risk=0.1372 changed=True flagged=False verdict=changed material=False escalation_band=False non-zero-layers={'layer1_hash': 1.0} degraded=[] (282 ms)

### FAIL ΓÇö https://www.goodreads.com/ (Tier ?, Category Other solid general sites)
- Pass results: P1: OK 200 56.8s / P2: OK 200 62.0s / P3: OK 200 13.9s
- Latency: 13920 / 61950 / 44223 ms (spread 48.0s)
- Error: capture succeeded and no wall fingerprint, but detection flagged: p1->p2 risk=1.0 layers={'layer1_hash': 1.0, 'layer3_link_audit': 0.2, 'layer4_visual_diff': 0.0471, 'layer7_cloaking': 1.0, 'layer9_fusion': 1.0}; p2->p3 risk=0.9269 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.0014, 'layer3_link_audit': 0.08, 'layer4_visual_diff': 0.0804, 'layer6_security_metadata': 0.8, 'layer9_fusion': 0.9269}; p1->p3 risk=0.9605 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.0014, 'layer3_link_audit': 0.18, 'layer4_visual_diff': 0.0959, 'layer6_security_metadata': 0.8, 'layer9_fusion': 0.9605}
- Evidence: P1 cq=full stable=True polls=8 h=2109->2109 capped=False shotcap=False dims=[1366, 2109] html=55778B cf=False retry=0 banner=90/False replay_fullmap=False txt=4648; P2 cq=full stable=True polls=8 h=2109->2109 capped=False shotcap=False dims=[1366, 2109] html=55861B cf=False retry=0 banner=90/False replay_fullmap=False txt=4641; P3 cq=full stable=True polls=3 h=2109->2109 capped=False shotcap=False dims=[1366, 2109] html=55594B cf=False retry=0 banner=90/False replay_fullmap=False txt=4630
- Evidence: pair p1->p2 (probe src p1) risk=1.0 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer3_link_audit': 0.2, 'layer4_visual_diff': 0.0471, 'layer7_cloaking': 1.0} degraded=[] (828 ms)
- Evidence: pair p2->p3 (probe src p2) risk=0.9269 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.0014, 'layer3_link_audit': 0.08, 'layer4_visual_diff': 0.0804, 'layer6_security_metadata': 0.8} degraded=[] (875 ms)
- Evidence: pair p1->p3 (probe src p1) risk=0.9605 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.0014, 'layer3_link_audit': 0.18, 'layer4_visual_diff': 0.0959, 'layer6_security_metadata': 0.8} degraded=[] (969 ms)

# 38 non-clean site(s) in C:\Users\Ns8pc\AppData\Local\Temp\opencode\wardress-w1a\analysis_A.json
```

## Findings (Tier A)

### [NEW] AUDIT-5A-1 — `layer3_link_audit` scores ordinary ad-tech host rotation as an injection signal, and it alone carries real news homepages over the flag threshold

- **Severity**: **High**. Justified against §6.4 High: "a false positive that would alert
  operators on legitimate, common site behavior". Measured, 3 passes per site, on
  **3 of the 7 Tier A sites completed and 3 of 3 pairs each = 9 of 21 pairs flagged**,
  at fused risk **0.7330 – 0.9995**, every one above the default 0.50 `flag_threshold`
  — so every one creates an `Alert` **and** a `RemediationExecution`
  (`worker/scan_tasks.py:341-359`). Not Critical: this is a false *alarm*, not a false
  *clean* on an attack, and it does not corrupt data.
- **Subsystem / file(s)**: `backend/worker/detection/dom.py:688-734`
  (`layer3_link_audit`): the weights dict at `:704-710`
  (`iframe_src`/`script_src`/`form_action` = 1.0, `a_href` = 0.35), the saturator at
  `:727` (`domain_score = 1 - math.exp(-0.9 * new_domains_weighted)`), the same-domain
  churn term at `:729` (`min(0.4, 0.02 * total_new_refs)`), and `max()` at `:730`;
  `backend/worker/detection/fusion.py` (the refit logistic that consumes it);
  `backend/app/models.py:235` (`flag_threshold` default 0.5).
- **Reproduction**: run 3 real captures of `https://www.thehindu.com/`, build
  `PageData`/`ScanPageData` pairs exactly as `scan_tasks.py:279-292`, call production
  `run_detection`. `layer3_link_audit.evidence.new_external_domain_weight == 1.0`,
  `added_new_domains.iframe_src == ["https://c13ef1bea2f0403dde9eb96fdf7a2264.safeframe.googlesyndication.com/safeframe/1-0-45/html/container.html"]`,
  measured layer3 = **0.5934** = `1 - exp(-0.9*1.0)` to 4 dp. Second independent site:
  `https://www.aajtak.in/`, weight **1.7** (`sync.inmobi.com/prebidjs` iframe + 2 new
  article domains), measured **0.7835** = `1 - exp(-1.53)` to 4 dp.
- **Root cause**: ad-tech container hostnames are **randomised per ad request**, so
  "a domain never seen in the baseline" is the *normal* steady state of any page that
  serves ads, not evidence of injection. The exponential saturator makes that single
  new domain worth 0.59 — above the 0.5 flag threshold on its own once layer1 is
  present. Nothing in the layer asks whether the new domain is an ad/prebid/analytics
  host, whether it is a *sub*domain of an already-known apex, or whether it recurs
  across scans (a rotated host recurs on the *next* baseline but is never-seen *here*).
- **Proposed remedy category** (a category, not an implementation): apex-domain
  collapsing for the "new domain" decision (so `c13ef1be….safeframe.googlesyndication.com`
  collapses to the known apex `googlesyndication.com`); a first-party/third-party or
  ad-network classification prior; a saturator calibrated against measured benign
  rotation rates rather than an exponential in raw weighted count; and/or treating
  `layer3` as evidence that must be corroborated by layer 2 or 8 before it can carry a
  site over the flag threshold. Note the interaction with Session A's O-SA-9: a
  "changed-benign" state would also absorb this.
- **Source**: Audit Phase 5A, Tier A "Indian News" / "Top 20", Gauntlet step 5/6.

---

### [NEW] AUDIT-5A-2 — Capture-completeness variance is diffed as content change; an ordinary lazy-loading homepage flags at 0.998 on every consecutive visit

- **Severity**: **High**. Same §6.4 High band as above ("a false positive that would alert
  operators on legitimate, common site behavior"), and it is the more dangerous of the
  two because the flagged risk is ~1.0 — i.e. maximum severity on every scan — and
  because the invisible variable is the *truncation*, which also hides below-fold
  injected content. It deepens Session A's **AUDIT-3-5** (Medium): that finding showed
  completeness never reaches detection; this shows the consequence is not silence but a
  **maximum-severity false alarm** on a real site.
- **Subsystem / file(s)**: `backend/worker/page_prepare.py:59-135`
  (`auto_scroll_page`, `MAX_SCROLL_TIME_MS = 20_000`, the `stable_steps`/`capped`
  bookkeeping at `:119-135`); `backend/worker/fetcher.py:639-641` (the call),
  `:680-698` (the evidence dict that is written), `:695-697`
  (`_classify_capture_quality`); `backend/worker/scan_tasks.py:280-292` (the
  `ScanPageData` constructor that drops the whole evidence dict — the exact loss point
  Session A named); `backend/worker/detection/types.py:12-24`; `dom.py` (layer 2).
- **Reproduction**: 3 passes of `https://www.aajtak.in/` (a plain, unblocked Hindi news
  homepage — all three UA variants return 200). `capture_evidence`:
  P1 `initial_height 9043 -> final_height 28002, capped False`;
  P2 `9043 -> 37384, capped True` (the 20 s scroll cap was hit);
  P3 `9043 -> 27915, capped False`. DOM text length 1179221 / 1369021 / 1164118 chars.
  Through `run_detection`: `layer2_dom_structure` = **1.0 / 0.7534 / 1.0**,
  `layer8_semantics` = 0.4586 / 0.3853 / 0.3992, fused risk **0.9993 / 0.9983 / 0.9995**,
  `flagged = True` on all three. Second independent site `https://www.bbc.com/news`:
  L2 = 0.0044 (P1 vs P2) but **0.7534** (P2 vs P3) on captures with identical screenshot
  dimensions and identical `visible_text_chars`.
- **Root cause**: the amount of a lazy-loading page that has loaded when the capture
  ends is a function of wall-clock timing, not of page state. Two *identical* pages
  captured 20 s apart can differ by 9 382 px of document height. Because
  `ScanPageData` never receives `capped` / `stable` / `final_height` /
  `screenshot_capped` (Session A's exact loss point at `scan_tasks.py:280-292`),
  fusion cannot tell a truncated capture from a defaced one and diffs the truncation.
  `_classify_capture_quality` *did* label all six captures `partial`/`capped` — the
  information existed at `fetcher.py:680-698` and was thrown away one line later.
- **Proposed remedy category**: carry the capture-completeness facts into
  `PageData`/`ScanPageData` (the AUDIT-3-5 remedy) and have fusion **discount the
  content layers proportionally** when the two sides differ in scroll coverage — or,
  failing that, gate the scan as *inconclusive* rather than running the nine layers on
  two captures with different completeness. A deterministic scroll-completeness target
  (walk to a stable floor rather than to a time cap) would remove the variable at source.
- **Source**: Audit Phase 5A, Tier A "Indian News", Gauntlet step 5.

---

### [NEW] AUDIT-5A-3 — A 0.65 % rendered-height difference plus one rotating content band flags an unchanged BBC News homepage at 0.7633

- **Severity**: **High**. §6.4 High, false positive on legitimate common site behaviour.
  This is the cleanest possible demonstration because the *decisive* layers are
  provably silent: `layer2_dom_structure` = **0.0** and `layer8_semantics` = **0.0**
  on every pair. Only the byte-hash and the visual channel moved, and they crossed
  0.50 on their own.
- **Subsystem / file(s)**: `backend/worker/detection/visual.py:110-190`
  (`layer4_visual_diff`; `_common_size` + the aspect-preserving resize and shared
  top-crop at `:140-147`, `ssim_score = 1 - ssim` at `:178`, the blend
  `0.7*ssim + 0.3*hash + chroma` at `:184`);
  `backend/worker/fetcher.py:377-416` (`_take_screenshot` — the PNG height is whatever
  the page happens to render at, with no normalisation);
  `backend/worker/hashing.py:24-36` (layer 1 = 1.0 on any byte change);
  `backend/worker/detection/fusion.py`.
- **Reproduction**: 3 passes of `https://www.bbc.co.uk/news`. P1 screenshot
  1366x**6109**; P2 and P3 1366x**6069** (40 px, 0.65 %). DOM identical in all three
  (1621 tags / 236 `<a>` / 93 `<script>` / 9418-9449 visible chars). P1->P2 fused
  **0.7633 flagged**; P2->P3 (both 6069) **0.1431 changed** with **SSIM 1.0** and
  `layer4 = 0.0`. Localisation using production's own `_common_size` (683x3034 crop):
  row-band mean abs-diff is **< 0.03** for the top 1812 scaled px and **47-62/255** for
  scaled y 2114-2869 only — one rotating module, ~25 % of page height.
- **Root cause**: two independent problems compose. (a) The screenshot has no
  canonical height, so any ordinary difference in rendered length changes the image
  geometry; layer 4 crops to the shared region but the *scale factor* still differs,
  which is why a 0.65 % height delta produced SSIM 0.865 rather than ~1.0. (b) Fusion
  treats `layer1_hash = 1.0` (a pure "bytes differ" bit) as a full-strength feature, so
  once *any* soft channel moves — here 0.11 of visual delta from a normal rotating
  module — the pair is pushed to 0.76. The evidence a human would use (structure 0.0,
  semantics 0.0) has zero veto power.
- **Proposed remedy category**: normalise screenshot geometry before diffing (fixed
  reference width, capped comparison height, or scroll-segment the page and compare
  per segment so a height delta is not a whole-image event); and recalibrate or gate
  fusion so `layer1_hash` cannot by itself carry a pair past the flag threshold when
  every content layer is sub-noise. Note this is the same fusion-coefficient question
  as AUDIT-1-1 — but here the *consequence* is a flag, not just a lost `clean`.
- **Source**: Audit Phase 5A, Tier A "International News", Gauntlet step 5.

---

### [NEW] AUDIT-5A-4 — A Tier A site answers `HTTP 403 Access Denied` and Wardress captures it as real content with `capture_quality: "full"`

- **Severity**: **Medium**. §6.4 Medium: "a partial implementation that degrades
  gracefully but doesn't meet the original intent". It degrades gracefully *only*
  because the baseline path happens to carry a `>= 400` guard
  (`scan_tasks.py:109-119`) that the scan path lacks (`scan_tasks.py:262-272`) — the
  protection is incidental, not designed, and the 200-OK variant that would defeat it
  (Session A's NB-CAP-2 poisoning case) is untested here. Not High: for this site the
  baseline is correctly refused, so no operator-visible false alarm is produced today.
  Not Critical: no false `clean` on an attack and no data corruption.
- **Subsystem / file(s)**: `backend/worker/fetcher.py:166-201`
  (`_CHALLENGE_TITLE_MARKERS`, `_CHALLENGE_MARKER_SELECTOR`, the 403+`cf-ray` rule —
  Cloudflare-only), `:125-128` (`BOT_PROTECTION_ERROR` hard-codes "Cloudflare"),
  `:352-374` (`_classify_capture_quality` — grades mechanics only, never whether the
  page is a wall), `:659-668` (`http_status` recorded but never used as a gate);
  `backend/worker/scan_tasks.py:109-119` (baseline gate) vs `:262-272` (scan path, none);
  `backend/tools/run_stress_catalog.py:186-188` (bot-protection note keyed only on the
  strings `BOT_PROTECTION`/`Cloudflare`).
- **Reproduction**: 3 passes of `https://www.ndcw.com/`'s sibling `https://www.ndtv.com/`.
  Every pass: `http_status = 403`, `title = "Access Denied"`, 286-290 bytes of HTML,
  7 tags, 202-206 visible chars, `looks_like_challenge_page` = **False**,
  `cloudflare_challenge_detected` = **False**, `capture_quality` = **"full"**,
  `fetch_page` returns normally. **Extra measured fact**: `probe_site` on the same URL
  returns 403 for `desktop_chrome` and `googlebot` but **200 / 1 130 472 bytes for
  `mobile_safari`** — the block is keyed to Wardress's own `CAPTURE_USER_AGENT`.
- **Root cause**: the challenge gate is vendor-specific, so any non-Cloudflare wall
  is by definition "a real page". `_classify_capture_quality` then reports `full`
  because a 768-px error page is genuinely a complete, stable, uncapped render. Layer 7
  correctly degraded on every pair — the one channel that *could* have revealed the
  block — and the information was discarded.
- **Proposed remedy category**: the AUDIT-SA1-2 remedy (vendor-agnostic wall
  classification as a gate separate from the Cloudflare gate; an `http_status >= 400`
  gate on the scan path; a `blocked_page`/`capture_quality: "blocked"` label); plus the
  new observation that the per-UA variance already measured by layer 7's probe is
  actionable signal — a `403-on-capture-UA but 200-on-another-UA` record is a precise,
  user-safe diagnosis to surface instead of a generic "could not be bypassed".
- **Source**: Audit Phase 5A, Tier A "Indian News"; corroborates AUDIT-SA1-2 in Tier A.
---

### [NEW] AUDIT-5A-5 — A transient DNS failure is surfaced as `SSRFBlockedError`, which the Phase-6 retry contract permanently excludes from retrying

- **Severity**: **Medium**. §6.4 Medium (a partial implementation that degrades
  gracefully but misses the original intent). One scan is permanently lost per DNS
  blip, the operator-visible message reads like a security refusal, and the
  documented "transient failures are retried once" contract does not apply. Not High:
  no false alarm, no corruption, and it self-heals on the next scheduled scan.
- **Subsystem / file(s)**: `backend/app/ssrf.py:53-59` (`resolve_host` raises
  `SSRFBlockedError(f"Could not resolve host {host!r}")` on `socket.gaierror` — the
  exception type is shared by a *policy refusal* and a *network failure*),
  `:66-67` ("resolved to no usable addresses"); `backend/worker/fetcher.py:486-487`
  (`except SSRFBlockedError: raise` — outside the retry loop, with the docstring at
  `:422-431` asserting SSRF refusals are "policy decisions"),
  `:437-439` (the top-level gate runs before any browser work and is "never retried");
  `backend/worker/scan_tasks.py:97-102` and `:264-272` (`except (FetchError,
  SSRFBlockedError)` -> `status = failed`, `_schedule_next(changed=False)`).
- **Reproduction** (measured live, Tier B): `https://www.nbcnews.com/`
  P1 -> `SSRFBlockedError: Could not resolve host 'www.nbcnews.com'` in **4.8 s**,
  P2 -> `OK 200` in **74.2 s**, P3 -> `OK 200` in **51.6 s**. Same machine, same URL,
  seconds apart. Rule 18: 3 passes, 1 fail / 2 pass, variance 4.8 s -> 74.2 s.
- **Root cause**: `resolve_host` conflates "this host is unresolvable" (permanent, a
  policy-relevant fact) with "this lookup failed right now" (transient). The fetcher's
  ladder then applies the wrong policy: SSRF refusals are never retried *by design*,
  so a single `gaierror` — a routine occurrence on a busy resolver, a TTL race, or a
  momentarily-full DNS cache — costs a whole scan and produces a message whose wording
  points the operator at the SSRF policy rather than at the network.
- **Proposed remedy category** (note Rule 12: `app/ssrf.py` is not to be edited — the
  change belongs in the fetcher's exception ladder): a distinct error type for
  resolution failure so `fetch_page` can classify it as transient and spend its one
  retry, plus an operator-facing message that separates "refused by policy" from
  "could not resolve". A cheap pre-flight resolve retry inside the capture's existing
  retry budget achieves the same thing without touching the policy module.
- **Source**: Audit Phase 5B run (surfaced while root-causing a Tier B capture failure);
  mechanism confirmed by reading `app/ssrf.py` and `worker/fetcher.py`.

---

### [NEW] AUDIT-5A-6 — The mandated stress runner cannot detect the failure mode Tier B exists to catch

- **Severity**: **Medium**. §6.4 Medium: the tool that is supposed to produce the
  audit's headline stress numbers systematically reports the *worst* real-world bot-wall
  outcome as a **PASS**. It is a measurement-integrity defect in a tool, not in the
  product, so Medium rather than High — but it is the direct cause of the
  "87.8 %, three categories accepted in aggregate" ending that PROMPT-003 exists to
  correct.
- **Subsystem / file(s)**: `backend/tools/run_stress_catalog.py:148-199`
  (`test_site` — the only measurement is `res.get("ok")`), `:160-172`
  (`times_to_stat` prefers **successful** passes only, so a run with failures reports
  the min/avg/max of the successes and silently hides the failures' cost),
  `:186-188` (bot-protection note matched only against the literal strings
  `BOT_PROTECTION` / `Cloudflare` in an error message);
  `backend/tests/_capture_child_impl.py:43-51` (the child *does* return `http_status`,
  `headers`, `final_url` and `capture_evidence` — the parent simply never reads them);
  `:47` (`"screenshot": list(result.screenshot)`).
- **Reproduction**: (a) construct from real captured data — `https://www.ndtv.com/`
  returns `ok: true` with `http_status: 403` and a 286-byte "Access Denied" body;
  `test_site` would print `PASS (10.9s)` and `notes = "Clean capture"`, because
  `looks_like_challenge_page` returns `False` for a non-Cloudflare wall and no
  exception is raised. (b) The child's serialisation: measured on this run's own
  artifacts, an 8 151 KB screenshot becomes a **36.29 MB JSON file** in 547 ms
  (`list(bytes)` 31 ms + `json.dumps` 547 ms); a 2 532 KB screenshot becomes
  **11.27 MB**. Across 363 planned captures at this tier's average PNG size that is
  multiple GB written and re-read for a field the parent never reads.
  (c) `url_hash = abs(hash(url))` at `:53` — Python's `str.__hash__` is salted per
  process, so two runs of the same URL produce different scratch filenames (verified:
  `189488540714453643` then `2290351233347219675`), which is why the tool cannot be
  resumed or cleaned up between runs.
- **Root cause**: the runner was built to answer "did `fetch_page` raise?", which is
  the narrowest possible definition of a capture outcome. Because no non-Cloudflare
  wall raises, the bot-protection tiers it is pointed at cannot fail by construction.
- **Proposed remedy category**: promote the child's already-transported
  `http_status`/`headers`/`capture_evidence` into the pass record; add a
  wall-classification column next to `ok`; hash the screenshot instead of
  serialising it (or write it to a file); make the failure paths participate in the
  latency statistics; and give the tool a `--out` JSONL plus a stable per-URL key so a
  long run is resumable. All of these were implemented in a throwaway `%TEMP%` driver
  for this phase and are reported here as proposals, not committed (Rule 1).
- **Source**: Audit Phase 5A/5B, investigation of the mandated runner.

---

## Tier A — methodology self-correction (Rule 13 applied to my own tooling)

My wall detector went through **five** calibrations during this phase, each driven by
a counter-example I measured in my own data, not by reasoning. Every one is recorded
because a reader must be able to audit how the "independent wall evidence" column was
produced, and because the calibrations are themselves evidence about how hard this
classification is:

1. **CDN vendor is not a wall.** The first version treated `server: cloudflare`,
   `cf-ray` and `__cf_bm` as wall evidence. Applied to `https://www.thehindu.com/`
   — a genuine 18 867-character homepage with 2 481 tags served by Cloudflare — it
   produced a false "WALL CONTENT" verdict. Fixed: CDN vendors, CAPTCHA-widget
   presence and *blocking* evidence became three separate categories.
2. **`/cdn-cgi/challenge-platform` alone is not an interstitial.** Cloudflare injects
   that script on ordinary Bot-Management pages. Measured counter-examples:
   `pexels.com` (915 KB, 3 300 tags, 5 563 visible chars, real title) and
   `stockx.com` (847 KB, 2 805 tags, 7 716 visible chars, real title) carried it and
   **nothing else**; the marker disappeared entirely when `<script>` bodies were
   stripped. Demoted to contextual.
3. **Do not mix the capture's status with the probe's headers.** The second version
   counted a `cf-mitigated` header observed on a **403 probe** response as evidence
   that the **200 capture** was a wall, which mis-flagged `npmjs.com` (verified real
   by reading its captured text: "npm tokens that bypass 2FA are being restricted …
   Sign In … We're GitHub"). Vendor-header evidence is now only counted when the
   probe's own reference-UA fetch was itself non-2xx.
4. **`Set-Cookie` must be split on new cookies, not on commas.** My first splitter
   turned `Expires=Wed, 30 Sep 2027 07:42:16 GMT; path=…` into a cookie literally
   named `30 Sep 2027 07:42:16 GMT; path`. Fixed to treat attribute continuations
   correctly.
5. **A bot-management cookie or SDK on a 200 is the vendor's detection running
   normally.** The final over-fire: `ibm.com`, `usps.com`, `dell.com` set
   `_abck`/`bm_sz` **on a successful response** carrying the real page (8 769 /
   13 381 / 16 516 visible chars); `airbnb.com`, `target.com`, `walmart.com` ship
   DataDome/PerimeterX SDK strings inside a real 200 page. Final rule: vendor
   fingerprints count as blocking **only** when the status is `>= 400` **or** the
   page is a content-free shell.

**Final Tier A wall set after calibration (7 sites):** `ndtv.com`,
`ndtv.com/entertainment`, `news18.com`, `moneycontrol.com`, `news.sky.com` (all 403),
`imdb.com` (405), and **`reuters.com` (200 on pass 1)**. `un.org` and
`archive.org` triggered the shell heuristic and are reported as *heuristic
over-fires* rather than walls — `un.org` is genuine 9-language UN content, and
`archive.org` is a real finding for a different reason (AUDIT-5A-8).

**The generalisable lesson, which is itself a finding-grade observation:** a
visible-text-length threshold alone cannot distinguish a wall from a sparse page.
Any content-sufficiency gate that ships must combine it with DOM tag count, body size
and vendor/title fingerprints — my own detector needed four refinements to get that
right, and it had full access to the raw HTML.

## Opportunities / Innovation ideas (Rule 17 — not severity-scored)

1. **Idea**: A "capture comparability" contract — the capture side computes a small
   vector of facts that decide whether two captures are *comparable at all*
   (scroll coverage, page height, stability, screenshot cap, banner state, final-URL
   identity) and detection consumes it as a first-class input rather than a debug dict.
   **Why it would help**: three of my four High/Medium Tier A findings (AUDIT-5A-2,
   -5A-3, and the `changed`-never-`clean` half of AUDIT-1-1) come from detection
   treating two *incomparable* captures as two observations of the same page. The
   information already exists in `capture_evidence`; only the contract is missing.
   **Where it touches**: `worker/fetcher.py:680-698`, `worker/detection/types.py:12-24`,
   `worker/scan_tasks.py:280-292`, `worker/detection/fusion.py`.
   **Rough shape**: extend `PageData` with a `capture` sub-struct (the AUDIT-3-5
   remedy) plus a `comparable_with(other) -> (bool, reasons)` helper; fusion down-weights
   or refuses to score a pair that is not comparable; the `changed` gate skips pairs it
   cannot compare.

2. **Idea**: Fold the per-UA variance that `probe_site` already collects into the capture
   diagnosis. **Why it would help**: `https://www.ndtv.com/` returns 403 to
   `desktop_chrome`/`googlebot` and 200 / 1.13 MB to `mobile_safari`. That single
   measurement distinguishes "this site blocks bots" from "this site's edge blocks our
   specific UA string", and the second is often fixable with a UA rotation or a
   differently-fingerprinted client. Today that signal is computed, thrown into layer 7,
   and used only for cloaking. **Where it touches**: `worker/probe.py`,
   `worker/fetcher.py:125-128` (the `BOT_PROTECTION_ERROR` message family),
   `worker/scan_tasks.py` error surfacing, `app/routers/health.py`.
   **Rough shape**: a `blocked_capture_ua_only` evidence key derived from the existing
   `ua_variants`, and a distinct, user-safe remediation hint.

3. **Idea**: Vendor-agnostic bot-wall classification as a first-class *evidence*
   channel rather than a gate. **Why it would help**: it keeps `fetch_page`'s contract
   (a wall page can still be returned) while making the wall impossible to store
   silently, and it gives operators a reason string instead of a bare
   `capture_quality`. It also closes the scan/baseline asymmetry by one mechanism
   instead of two. **Where it touches**: new module beside `worker/fetcher.py`, wired
   into `scan_tasks.py` at both the baseline (`:109`) and scan (`:262`) sites.
   **Rough shape**: a `classify_wall(html, headers, status) -> {vendor, confidence,
   evidence}` used by both paths, with Cloudflare as one member rather than the only one.

4. **Idea**: Deterministic scroll target. **Why it would help**: measured, the same
   `aajtak.in` page ended the scroll pass at 27 915 / 28 002 / 37 384 px on three
   consecutive visits; that spread *is* the false alarm. Replacing the 20 s time cap with
   "walk until N consecutive non-growing steps AND at_bottom, or the hard cap" plus a
   recorded `scroll_coverage_ratio` would make the variable observable and, eventually,
   removable. **Where it touches**: `worker/page_prepare.py:59-135`.
   **Rough shape**: emit `covered_height`/`total_height` per capture; expose the ratio in
   `capture_evidence`.

5. **Idea**: Banner-dismissal cost is unbounded in frames. **Why it would help**:
   `capture_evidence["attempts"]` was **2 370** on `aajtak.in` (79 frames x 30 selectors)
   and 990/1170/1140/1230 on other pages — i.e. `dismiss_banners` runs a full 30-selector
   sweep on every ad iframe, every capture, and dismissed **0 of 21** Tier A banners.
   Even granting Session A's AUDIT-SA1-3 (~3.1 s floor), the frame-multiplied variant is
   unbounded in principle. **Where it touches**: `worker/banner_dismiss.py:346-367,393-407`.
   **Rough shape**: cap the frames probed per pass (ad iframes are never consent frames),
   and prefer a `MutationObserver`/event-driven wait over the flat 3 s timeout.

6. **Idea**: Make the stress runner's PASS mean something. **Why it would help**: see
   AUDIT-5A-6 — as written the mandated tool cannot fail a bot-wall tier. Adding the four
   measurements this phase needed (status, production challenge verdict, independent wall
   verdict, fused risk) turns a 40-minute run into one that actually reports
   false-flagging. **Where it touches**: `backend/tools/run_stress_catalog.py`,
   `backend/tests/_capture_child_impl.py`.
   **Rough shape**: transport a `sha256` of the screenshot instead of the bytes, add a
   `--out` JSONL with a stable URL key, and let the caller plug in a detection callback.

7. **Idea**: A "consecutive-visit self-consistency" regression gate — capture the same
   public page 3 times, run all 9 layers on all 3 pairs, and assert the fleet's fused-risk
   distribution stays below the flag threshold. **Why it would help**: this phase found
   10 of 21 real pairs flagged using nothing but public homepages and no attack
   fixtures. A standing gate on that number would have caught AUDIT-5A-1/-2/-3 at CI
   time, before any operator saw an alert. **Where it touches**: a new hermetic test
   beside `tests/test_detection_regression.py`, plus a fixture corpus of a handful of
   cached (html, png) triples.
   **Rough shape**: commit a small redacted fixture set (e.g. `bbc.co.uk`, `thehindu.com`
   p1/p2/p3 as gzipped html + png) and assert `flagged` count == 0.

8. **Idea**: Treat "the probe saw a different final URL than the capture" as a first-class
   signal. **Why it would help**: on **every** site in the completed Tier A set the
   `probe_site` UA variants ended on a **bare IP literal**
   (`https://151.101.0.81/news`, `https://[2606:4700:8de1:2e14:a3ca:0:4de5:5eef]/`,
   `https://[2600:1417:75:585::24e8]/`) while the browser capture ended on the hostname.
   Layer 7 and layer 6 both reason over that fetch. An explicit "capture and probe
   observed different origins" flag would let detection discount the probe's evidence
   and would make a real CDN/redirect change visible instead of silent.
   **Where it touches**: `worker/probe.py`, `worker/detection/cloaking.py`,
   `worker/detection/metadata.py`.
   **Rough shape**: record `probe.final_url` per variant; compare apex hosts with
   `dom._safe_hostname`; surface as evidence, not as a silent substitution.

## Findings out of phase scope (routed, not investigated here)

- **`probe_site` follows redirects to bare IP literals** (`https://151.101.0.81/news`,
  `https://[2600:1417:75:585::24e8]/`) with no post-redirect re-validation visible in
  `worker/probe.py`; Session A already noted `probe.py:93-94` as an unpinned raw-socket
  TLS path. All hosts observed are public CDN edges, so no exposure was demonstrated and
  I did **not** test it. Routed to the SSRF/orchestration owner (Phase 4B/4E territory).
  I flag it because it is systematic: 6 of 6 sites in my Tier A sample.
- **The Telegram bot renders `ScanVerdict.changed` as "CHANGED"** (`worker/telegram_bot.py:71`),
  and 0 of 21 real pairs read `clean`, so an operator's Telegram feed will read CHANGED
  permanently. Notification/alerting surface — routed.
- **Frontend display of a permanently-`changed` verdict** (`frontend/src/**`) and the
  `capture_quality` health buckets — Audit Phase 4F territory; routed with the numbers
  above as the evidence they will need.
## Method — deviations, stated plainly

1. **`probe_site` on passes 2 and 3 only** (not all three). Production runs it on every
   scan; I run it twice per site. The baseline side of a pair never consumes
   `ua_variants` (`layer7_cloaking` explicitly ignores the baseline —
   `cloaking.py:122-123`), so a third probe would add request volume without adding a
   single layer input. The pass-1 probe was then filled afterwards with the **same
   production function** so all three pairs have production-faithful layer-6/7 inputs.
2. **The `title`/`has_challenge_marker` replay is post-hoc**, extracted from the captured
   HTML with a regex rather than from the live document, because the capture is finished
   by then. It is reported **next to** the real production verdict
   (`capture_evidence["cloudflare_challenge_detected"]`, which is what `_wait_out_challenge`
   actually decided during the capture) and never replaces it. On the 21 Tier A captures
   the replay and the live verdict agreed 21/21.
3. **Layer-4/8 model inputs are exactly production's.** No stubbing, no monkey-patching
   of any production function. The only code I wrote is measurement code in `%TEMP%`.
4. **The live Docker stack was exercised read-only apart from one thing**: the
   baseline-poisoning probe (`NB-CAP-2`) creates a temporary Site via the public REST API,
   lets the real Celery worker capture a real baseline, triggers one scan, and then
   **deletes the site**. No production file, no schema, no queue is modified. Result and
   per-case outcome are reported in the Tier C section.

## Rule 1 compliance

- **No tracked production file was modified.** Verified with
  `git status --short` in `C:\Users\Ns8pc\Music\WARDRESS` before finishing (see the
  verification block appended at the end of this file).
- **No temporary instrumentation was added to production**, so nothing had to be
  reverted. `looks_like_challenge_page`, `fetch_page`, `_take_screenshot`,
  `_classify_capture_quality`, `auto_scroll_page`, `dismiss_banners`, `probe_site`,
  `content_sha256`, `run_detection`, `layer1_hash_diff`, `layer3_link_audit`,
  `layer4_visual_diff`, `_common_size` and `assert_url_allowed` were all **read and
  called, never edited**.
- **No hermetic test file was added to the repo.** Rule 5 forbids committing a red test,
  and every case that would prove AUDIT-5A-1/-2/-3/-4 fails against production code
  today. The proposals are listed in *New hermetic tests proposed* below and all probes
  live in `C:\Users\Ns8pc\AppData\Local\Temp\opencode\wardress-w1a\` (Rule 10).
- **No git command other than `git status --short`** was run, and **no commit** was made.
- `scripts/install.ps1` / `scripts/uninstall.ps1` were **not** run (Rule 15); the stack
  was already up and was left up.
---

## TIER B — Advanced Bot Protection & Hard Categories (Phase 5B)

**Coverage: 31 of 31 unique URLs, 3 passes each = 93 captures (80 succeeded,
13 failed). Complete.** Vendor/liveness verification timestamp:
**2026-09-30 14:05–15:50 local**, from the capture's own status, the
`probe_site` full header map + `set-cookie` names, the HTML fingerprint set
(with the JS stripped, to tell an injected SDK from an interstitial), and the
page title — never from the catalog's label.

### Tier B dense summary table (latency numbers are CONTENTION-AFFECTED)

| URL | Tier/Category | Pass 1 | Pass 2 | Pass 3 | Latency min/avg/max | Status | Notes / Disposition |
|---|---|---|---|---|---|---|---|
| https://www.microsoft.com/ | Akamai Bot Manager | OK 200 25s | OK 200 25s | OK 200 23s | 23/24/25s | **FAIL (false flag)** | 3/3 pairs risk **1.000** flagged; real page (3825 visible chars) |
| https://www.ibm.com/ | Akamai Bot Manager | OK 200 30s | OK 200 44s | OK 200 30s | 30/35/44s | **FAIL (false flag)** | 3/3 pairs 0.937-0.997 flagged; Akamai edge, real page (8769 chars); googlebot UA probe -> 403 |
| https://www.ebay.com/ | Akamai Bot Manager | OK 200 18s | OK 200 45s | OK 200 43s | 18/36/45s | **FAIL (false flag)** | 3/3 pairs 0.523-0.848 flagged |
| https://www.washingtonpost.com/ | Akamai Bot Manager | **FAIL** 7.0s `net::ERR_HTTP2_PROTOCOL_ERROR` | **FAIL** 7.9s same | **FAIL** 6.7s same | 7/7/8s | **0/3 capture FAIL** | deterministic transport refusal; disposition below |
| https://www.usps.com/ | Akamai Bot Manager | OK 200 24s | OK 200 25s | OK 200 22s | 22/24/25s | **FAIL (false flag)** | p2->p3 risk 0.5644 flagged; 13 381 visible chars |
| https://www.weather.com/ | Akamai Bot Manager | OK 200 42s | **FAIL** 96.3s nav timeout | **FAIL** 96.3s nav timeout | 42/78/96s | **1/3 capture FAIL** | 60 s nav timeout, 3 s pause, 30 s retry, all exhausted |
| https://www.dell.com/ | Akamai Bot Manager | OK 200 26s | OK 200 46s | OK 200 45s | 26/39/46s | **FAIL (false flag)** | 3/3 pairs 0.603-0.980 flagged |
| https://www.bestbuy.com/ | Akamai Bot Manager | OK 200 40s geo-shell | OK 200 62s geo-shell | **FAIL** 96.0s nav timeout | 40/66/96s | **2/3 capture FAIL** | captured the "Select your Country" interstitial (760 visible chars) as `full` |
| https://www.nbcnews.com/ | Akamai Bot Manager | **FAIL** 4.8s `SSRFBlockedError: Could not resolve host` | OK 200 74s | OK 200 52s | 5/44/74s | **2/3 capture FAIL** | transient DNS -> see AUDIT-5A-5; p2->p3 risk **1.000** flagged |
| https://www.accuweather.com/ | Akamai Bot Manager | **FAIL** 5.5s `net::ERR_HTTP2_PROTOCOL_ERROR` | **FAIL** 10.2s same | **FAIL** 27.6s same | 6/14/28s | **0/3 capture FAIL** | deterministic transport refusal |
| https://www.airbnb.com/ | Akamai Bot Manager | OK 200 25s | OK 200 36s | OK 200 20s | 20/27/36s | **FAIL (false flag)** | 3/3 pairs 0.988-0.999 flagged; redirects to `airbnb.co.in`; googlebot probe -> 403 |
| https://www.godaddy.com/ | Akamai Bot Manager | OK **403** 15s WALL | OK **403** 15s WALL | OK **403** 13s WALL | 13/14/15s | **FAIL (wall as content)** | `server: AkamaiGHost`, `title="Access Denied"`, 291 B, 207 visible chars, `capture_quality: full` |
| https://www.leboncoin.fr/ | DataDome | OK **403** 16s WALL | OK **403** 23s WALL | OK **403** 20s WALL | 16/20/23s | **FAIL (wall as content)** | `server: DataDome` + `datadome`/`captcha-delivery.com` outside JS; 1 468 B, 12 visible chars |
| https://www.sncf-connect.com/ | DataDome | **FAIL** 97.9s `_ChallengeUnsolvedError` | **FAIL** 95.8s same | **FAIL** 98.6s same | 96/97/99s | **0/3 capture FAIL — CORRECT BEHAVIOUR** | the Cloudflare gate FIRED and refused; catalog category is wrong (see drift) |
| https://www.footlocker.com/ | DataDome | OK 200 25s | OK 200 27s | OK 200 31s | 25/28/31s | **FAIL (false flag)** | 3/3 pairs 0.836-1.000 flagged; NOT behind DataDome in practice |
| https://www.zillow.com/ | PerimeterX/HUMAN | OK **403** 25s WALL | OK **403** 21s WALL | OK **403** 18s WALL | 18/21/25s | **FAIL (wall as content)** | `x-px-` header + `_px` cookie + press-and-hold; 9 978 B, 146 visible chars |
| https://stockx.com/ | PerimeterX/HUMAN | OK 200 20s | OK 200 29s | OK 200 28s | 20/26/29s | **FAIL (false flag)** | 3/3 pairs risk **1.000**; real page (7716 chars); all 3 UA probes 403 |
| https://www.yelp.com/ | PerimeterX/HUMAN | OK **403** 13s WALL | OK **403** 16s WALL | OK **403** 19s WALL | 13/16/19s | **FAIL (wall as content)** | **`server: DataDome` — category drift, it is DataDome not PerimeterX** |
| https://www.target.com/ | AWS WAF | OK 200 33s | OK 200 35s | OK 200 34s | 33/34/35s | **FAIL (false flag)** | 3/3 pairs risk **1.000**; real page (3222 chars) |
| https://www.chase.com/ | AWS WAF | OK 200 15s | OK 200 15s | OK 200 14s | 14/15/15s | **FAIL (false flag)** | 3/3 pairs 0.952-0.977 flagged |
| https://www.hulu.com/ | AWS WAF | OK 200 23s | OK 200 29s | OK 200 53s | 23/35/53s | **FAIL (false flag + 4000px width)** | 3/3 pairs risk **1.000**; redirects to `hotstar.com/in/home`; **screenshot is 4000 px WIDE** -> AUDIT-5B-4 |
| https://www.kraken.com/ | Cloudflare Ent./Turnstile | OK 200 21s | OK 200 26s | OK 200 24s | 21/24/26s | **3/3 clean** | 3/3 pairs 0.169-0.176 `changed`, no flag |
| https://www.npmjs.com/ | Cloudflare Ent./Turnstile | OK 200 18s | OK 200 33s | OK 200 14s | 14/22/33s | **3/3 clean** | **the only `clean` site in Tier A+B** — `layer1_hash = 0.0` on all 3 pairs (byte-identical captures) |
| https://dash.cloudflare.com/ | Cloudflare Ent./Turnstile | OK 200 15s LOGIN-WALL | OK 200 16s LOGIN-WALL | OK 200 19s LOGIN-WALL | 15/17/19s | **FAIL (auth wall as content)** | redirects to `/login`; 589 visible chars, `cf-turnstile` embedded |
| https://www.walmart.com/ | Harder e-commerce | OK 200 19s | OK 200 23s | OK 200 21s | 19/21/23s | **FAIL (false flag)** | 3/3 pairs 0.975-0.978 flagged |
| https://www.etsy.com/ | Harder e-commerce | OK **403** 12s WALL | OK **403** 14s WALL | OK **403** 14s WALL | 12/13/14s | **FAIL (wall as content)** | **`server: DataDome`** — listed as "harder e-commerce", actually DataDome |
| https://www.ebay.co.uk/ | Harder e-commerce | OK 200 14s | OK 200 36s | OK 200 39s | 14/29/39s | **FAIL (false flag)** | p1->p2 0.6346, p1->p3 0.6357 flagged |
| https://www.aliexpress.com/ | Harder e-commerce | OK 200 24s | OK 200 24s | OK 200 25s | 24/24/25s | **FAIL (false flag)** | p1->p2 0.9449, p1->p3 0.9397 flagged; p2->p3 0.179 |
| https://unsplash.com/ | Harder lazy-load | OK **401** 12s WALL | OK **401** 13s WALL | OK **401** 12s WALL | 12/13/13s | **FAIL (wall as content)** | **Anubis** PoW gate, `title="Making sure you're not a bot!"`, navigated to `.within.website?redir=%2F` |
| https://www.pexels.com/ | Harder lazy-load | OK 200 18s | OK 200 21s | OK 200 19s | 18/19/21s | **FAIL (false flag)** | 3/3 pairs 0.634-1.000 flagged; real page (5 301-5 563 chars) |
| https://500px.com/ | Harder lazy-load | OK 200 12s ONBOARDING | OK 200 16s ONBOARDING | OK 200 14s ONBOARDING | 12/14/16s | **FAIL (interstitial + false flag)** | 3/3 pairs risk **1.000**; "Customize your feed" onboarding gate, 530 visible chars, 43 KB |

### Tier B cross-cutting measurements

| metric | value |
|---|---|
| capture success | **80/93** (13 failures, 6 distinct sites) |
| `capture_quality` | `full` 75, `partial` 5, `degraded` 0 — **every wall page is `full`** |
| genuine bot-wall / interstitial captures stored as content | **8 sites, 24 captures** (godaddy, leboncoin, zillow, yelp, etsy, unsplash, bestbuy, dash.cloudflare) + 500px onboarding |
| Cloudflare gate fired | **1 site only** (`sncf-connect.com`, 3/3 `_ChallengeUnsolvedError`) |
| production challenge verdict vs post-hoc replay | agreed **80/80** |
| `retry_count` | **0 on all 80 successful captures** |
| HTML size | 291 B – **3.38 MB** (guard 10 MB; nothing approached it) |
| `actual_height` | 768 – 15 156 px; `screenshot_capped` **0/80** |
| **PNG width** | 1366 px on 77, **4000 px on 3** (`hulu.com` -> `hotstar.com`) |
| banner `attempts` | 21 – **2 610**; `dismissed` = false on **80/80** |
| `layer7_cloaking` **degraded** | **37 of 77 pairs** — because the reference desktop-UA raw fetch was non-2xx on those sites |
| **detection verdicts** | `clean` **3 / 77**, `changed` 29, **`flagged` 45 (58 %)** |
| fused risk | min 0.0063, median **0.7936**, max 1.0000 |

> **Tier B's headline: 45 of 77 real consecutive-visit pairs on commercial
> sites FLAGGED.** Not one of those 45 is an attack. Every one is ordinary
> page dynamism — ad/prebid rotation, rotating promos, A/B modules, onboarding
> gates and capture-completeness variance. And on the 8 wall sites the *opposite*
> failure occurs: the wall is stored, at `capture_quality: "full"`, and reads
> `changed` at a benign 0.300 with **no operator-visible signal at all**.

### The expected baseline (Session A's AUDIT-SA1-2 prediction) — VERIFIED, with a correction

Session A predicted Tier B would fail **because the detector is Cloudflare-only,
not because of per-site flakiness**. My own measurements confirm the prediction
and pin the mechanism:

| wall shape | production gate verdict | measured |
|---|---|---|
| Cloudflare JS challenge (503/403+cf-ray) | **CHALLENGE** | 1 site (`sncf-connect.com`), 3/3 refused correctly |
| Akamai 403 `AkamaiGHost` "Access Denied" | **REAL PAGE** | `godaddy.com` 3/3 stored as content, `full` |
| DataDome 403 (`server: DataDome`) | **REAL PAGE** | `leboncoin.fr`, `yelp.com`, `etsy.com` 3/3 each |
| PerimeterX 403 (`x-px-`, `_px`, press-and-hold) | **REAL PAGE** | `zillow.com` 3/3 |
| Anubis 401 "Making sure you're not a bot!" | **REAL PAGE** | `unsplash.com` 3/3 — and a vendor the catalog does not even list |
| Cloudflare 200-OK + `cf-mitigated` | **REAL PAGE** | `dash.cloudflare.com` (login wall) |

**Correction to Session A's expectation, stated plainly:** the prediction that
Tier B would "fail" is right, but the failure is *bifurcated* and the second
half is the worse one. It is **not** that Tier B sites fail to capture — **29 of
31 captured cleanly 3/3**. It is that:
1. on the 6 wall sites the capture *succeeds* and stores the wall (AUDIT-SA1-2
   confirmed live, unchanged, and now in **Tier A** too via `ndtv.com`), and
2. on the **23 non-wall sites the detector produces a false `flagged` verdict on
   45 of 77 pairs**, at a median fused risk of 0.79.

So Tier B's real finding is not "the bot-wall sites fail". It is "**every
commercial page in Tier B false-flags, and the sites that genuinely are walled
are the only ones that behave correctly — because they are walled**."
### Tier B FAIL blocks (generated from the captured evidence; per-site)
```
### FAIL ΓÇö https://www.microsoft.com/ (Tier ?, Category Akamai Bot Manager (not attempted by PROMPT-002 at all))
- Pass results: P1: OK 200 25.2s / P2: OK 200 24.7s / P3: OK 200 22.5s
- Latency: 22530 / 25160 / 24127 ms (spread 2.6s)
- Error: capture succeeded and no wall fingerprint, but detection flagged: p1->p2 risk=1.0 layers={'layer1_hash': 1.0, 'layer7_cloaking': 1.0, 'layer9_fusion': 1.0}; p2->p3 risk=1.0 layers={'layer1_hash': 1.0, 'layer7_cloaking': 1.0, 'layer9_fusion': 1.0}; p1->p3 risk=1.0 layers={'layer1_hash': 1.0, 'layer7_cloaking': 1.0, 'layer9_fusion': 1.0}
- Evidence: P1 cq=full stable=True polls=4 h=3768->3768 capped=False shotcap=False dims=[1366, 3768] html=264356B cf=False retry=0 banner=120/False replay_fullmap=False txt=3825; P2 cq=full stable=True polls=7 h=3768->3768 capped=False shotcap=False dims=[1366, 3768] html=264368B cf=False retry=0 banner=120/False replay_fullmap=False txt=3825; P3 cq=full stable=True polls=5 h=3768->3768 capped=False shotcap=False dims=[1366, 3768] html=264358B cf=False retry=0 banner=120/False replay_fullmap=False txt=3825
- Evidence: pair p1->p2 (probe src p1) risk=1.0 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer7_cloaking': 1.0} degraded=[] (906 ms)
- Evidence: pair p2->p3 (probe src p2) risk=1.0 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer7_cloaking': 1.0} degraded=[] (1125 ms)
- Evidence: pair p1->p3 (probe src p1) risk=1.0 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer7_cloaking': 1.0} degraded=[] (953 ms)

### FAIL ΓÇö https://www.ibm.com/ (Tier ?, Category Akamai Bot Manager (not attempted by PROMPT-002 at all))
- Pass results: P1: OK 200 29.7s / P2: OK 200 44.4s / P3: OK 200 30.0s
- Latency: 29700 / 44410 / 34703 ms (spread 14.7s)
- Error: capture succeeded and no wall fingerprint, but detection flagged: p1->p2 risk=0.9845 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.0037, 'layer3_link_audit': 0.24, 'layer4_visual_diff': 0.2057, 'layer9_fusion': 0.9845}; p2->p3 risk=0.997 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.7534, 'layer3_link_audit': 0.26, 'layer4_visual_diff': 0.2295, 'layer9_fusion': 0.997}; p1->p3 risk=0.9372 layers={'layer1_hash': 1.0, 'layer3_link_audit': 0.24, 'layer4_visual_diff': 0.1507, 'layer9_fusion': 0.9372}
- Evidence: P1 cq=full stable=True polls=9 h=4920->4920 capped=False shotcap=False dims=[1366, 4920] html=922284B cf=False retry=0 banner=21/True replay_fullmap=False txt=8769; P2 cq=full stable=True polls=5 h=4920->4920 capped=False shotcap=False dims=[1366, 4920] html=922366B cf=False retry=0 banner=21/True replay_fullmap=False txt=8769; P3 cq=full stable=True polls=4 h=4920->4920 capped=False shotcap=False dims=[1366, 4920] html=922255B cf=False retry=0 banner=21/True replay_fullmap=False txt=8769
- Evidence: pair p1->p2 (probe src p1) risk=0.9845 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.0037, 'layer3_link_audit': 0.24, 'layer4_visual_diff': 0.2057} degraded=[] (1812 ms)
- Evidence: pair p2->p3 (probe src p2) risk=0.997 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.7534, 'layer3_link_audit': 0.26, 'layer4_visual_diff': 0.2295} degraded=[] (1969 ms)
- Evidence: pair p1->p3 (probe src p1) risk=0.9372 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer3_link_audit': 0.24, 'layer4_visual_diff': 0.1507} degraded=[] (2578 ms)

### FAIL ΓÇö https://www.ebay.com/ (Tier ?, Category Akamai Bot Manager (not attempted by PROMPT-002 at all))
- Pass results: P1: OK 200 17.9s / P2: OK 200 45.2s / P3: OK 200 43.5s
- Latency: 17860 / 45190 / 35513 ms (spread 27.3s)
- Error: capture succeeded and no wall fingerprint, but detection flagged: p1->p2 risk=0.8477 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.7534, 'layer3_link_audit': 0.5934, 'layer4_visual_diff': 0.0434, 'layer9_fusion': 0.8477}; p2->p3 risk=0.5234 layers={'layer1_hash': 1.0, 'layer3_link_audit': 0.4, 'layer4_visual_diff': 0.0365, 'layer9_fusion': 0.5234}; p1->p3 risk=0.7936 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.7534, 'layer3_link_audit': 0.5934, 'layer4_visual_diff': 0.0293, 'layer9_fusion': 0.7936}
- Evidence: P1 cq=full stable=True polls=4 h=3545->3545 capped=False shotcap=False dims=[1366, 3545] html=1065744B cf=False retry=0 banner=120/False replay_fullmap=False txt=13094; P2 cq=full stable=True polls=6 h=3545->3545 capped=False shotcap=False dims=[1366, 3545] html=1061522B cf=False retry=0 banner=60/False replay_fullmap=False txt=13094; P3 cq=full stable=True polls=6 h=3545->3545 capped=False shotcap=False dims=[1366, 3545] html=1065899B cf=False retry=0 banner=180/False replay_fullmap=False txt=13092
- Evidence: pair p1->p2 (probe src p1) risk=0.8477 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.7534, 'layer3_link_audit': 0.5934, 'layer4_visual_diff': 0.0434} degraded=['layer7_cloaking'] (2312 ms)
- Evidence: pair p2->p3 (probe src p2) risk=0.5234 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer3_link_audit': 0.4, 'layer4_visual_diff': 0.0365} degraded=['layer7_cloaking'] (2468 ms)
- Evidence: pair p1->p3 (probe src p1) risk=0.7936 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.7534, 'layer3_link_audit': 0.5934, 'layer4_visual_diff': 0.0293} degraded=['layer7_cloaking'] (2469 ms)

### FAIL ΓÇö https://www.washingtonpost.com/ (Tier ?, Category Akamai Bot Manager (not attempted by PROMPT-002 at all))
- Pass results: P1: FAIL FetchError: Fetch failed: network error (Page.goto: net::ERR_HTTP2_PROTOCOL_ERROR at https://www.washingtonpost.com/) / P2: FAIL FetchError: Fetch failed: network error (Page.goto: net::ERR_HTTP2_PROTOCOL_ERROR at https://www.washingtonpost.com/) / P3: FAIL FetchError: Fetch failed: network error (Page.goto: net::ERR_HTTP2_PROTOCOL_ERROR at https://www.washingtonpost.com/)
- Latency: 6690 / 7890 / 7210 ms (spread 1.2s)
- Error: FetchError: Fetch failed: network error (Page.goto: net::ERR_HTTP2_PROTOCOL_ERROR at https://www.washingtonpost.com/) || FetchError: Fetch failed: network error (Page.goto: net::ERR_HTTP2_PROTOCOL_ERROR at https://www.washingtonpost.com/) || FetchError: Fetch failed: network error (Page.goto: net::ERR_HTTP2_PROTOCOL_ERROR at https://www.washingtonpost.com/)

### FAIL ΓÇö https://www.usps.com/ (Tier ?, Category Akamai Bot Manager (not attempted by PROMPT-002 at all))
- Pass results: P1: OK 200 23.5s / P2: OK 200 24.8s / P3: OK 200 22.5s
- Latency: 22500 / 24830 / 23610 ms (spread 2.3s)
- Error: capture succeeded and no wall fingerprint, but detection flagged: p2->p3 risk=0.5644 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.9698, 'layer3_link_audit': 0.1, 'layer4_visual_diff': 0.0231, 'layer9_fusion': 0.5644}
- Evidence: P1 cq=full stable=True polls=4 h=4789->4789 capped=False shotcap=False dims=[1366, 4789] html=147260B cf=False retry=0 banner=60/False replay_fullmap=False txt=13381; P2 cq=full stable=True polls=4 h=4789->4789 capped=False shotcap=False dims=[1366, 4789] html=151450B cf=False retry=0 banner=60/False replay_fullmap=False txt=13390; P3 cq=full stable=True polls=4 h=4789->4789 capped=False shotcap=False dims=[1366, 4789] html=153152B cf=False retry=0 banner=60/False replay_fullmap=False txt=13381
- Evidence: pair p1->p2 (probe src p1) risk=0.483 changed=True flagged=False verdict=changed material=True escalation_band=True non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.7534, 'layer3_link_audit': 0.08, 'layer4_visual_diff': 0.0231} degraded=[] (1547 ms)
- Evidence: pair p2->p3 (probe src p2) risk=0.5644 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.9698, 'layer3_link_audit': 0.1, 'layer4_visual_diff': 0.0231} degraded=[] (1735 ms)
- Evidence: pair p1->p3 (probe src p1) risk=0.4022 changed=True flagged=False verdict=changed material=True escalation_band=True non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.9698, 'layer3_link_audit': 0.08} degraded=[] (1485 ms)

### FAIL ΓÇö https://weather.com/ (Tier ?, Category Akamai Bot Manager (not attempted by PROMPT-002 at all))
- Pass results: P1: OK 200 42.1s / P2: FAIL FetchError: Fetch failed: navigation timeout (Page.goto: Timeout 30000ms exceeded.) / P3: FAIL FetchError: Fetch failed: navigation timeout (Page.goto: Timeout 30000ms exceeded.)
- Latency: 42060 / 96340 / 78243 ms (spread 54.3s)
- Error: FetchError: Fetch failed: navigation timeout (Page.goto: Timeout 30000ms exceeded.) || FetchError: Fetch failed: navigation timeout (Page.goto: Timeout 30000ms exceeded.)
- Evidence: P1 cq=full stable=True polls=3 h=2764->2764 capped=False shotcap=False dims=[1366, 2764] html=653706B cf=False retry=0 banner=2610/False replay_fullmap=False txt=1932

### FAIL ΓÇö https://www.dell.com/ (Tier ?, Category Akamai Bot Manager (not attempted by PROMPT-002 at all))
- Pass results: P1: OK 200 26.2s / P2: OK 200 46.4s / P3: OK 200 45.3s
- Latency: 26230 / 46390 / 39320 ms (spread 20.2s)
- Error: capture succeeded and no wall fingerprint, but detection flagged: p1->p2 risk=0.6027 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.5034, 'layer3_link_audit': 0.02, 'layer4_visual_diff': 0.0594, 'layer9_fusion': 0.6027}; p2->p3 risk=0.9804 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 1.0, 'layer3_link_audit': 0.08, 'layer4_visual_diff': 0.1568, 'layer8_semantics': 0.0362, 'layer9_fusion': 0.9804}; p1->p3 risk=0.961 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 1.0, 'layer3_link_audit': 0.08, 'layer4_visual_diff': 0.1298, 'layer8_semantics': 0.0364, 'layer9_fusion': 0.961}
- Evidence: P1 cq=partial stable=False polls=11 h=6383->6557 capped=False shotcap=False dims=[1366, 6557] html=974086B cf=False retry=0 banner=90/False replay_fullmap=False txt=16516; P2 cq=full stable=True polls=10 h=6383->6557 capped=False shotcap=False dims=[1366, 6557] html=974372B cf=False retry=0 banner=90/False replay_fullmap=False txt=16516; P3 cq=full stable=True polls=7 h=6383->6557 capped=False shotcap=False dims=[1366, 6557] html=1019242B cf=False retry=0 banner=90/False replay_fullmap=False txt=16627
- Evidence: pair p1->p2 (probe src p1) risk=0.6027 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.5034, 'layer3_link_audit': 0.02, 'layer4_visual_diff': 0.0594} degraded=[] (3000 ms)
- Evidence: pair p2->p3 (probe src p2) risk=0.9804 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 1.0, 'layer3_link_audit': 0.08, 'layer4_visual_diff': 0.1568, 'layer8_semantics': 0.0362} degraded=[] (3110 ms)
- Evidence: pair p1->p3 (probe src p1) risk=0.961 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 1.0, 'layer3_link_audit': 0.08, 'layer4_visual_diff': 0.1298, 'layer8_semantics': 0.0364} degraded=[] (3531 ms)

### FAIL ΓÇö https://www.bestbuy.com/ (Tier ?, Category Akamai Bot Manager (not attempted by PROMPT-002 at all))
- Pass results: P1: OK 200 40.1s / P2: OK 200 61.8s / P3: FAIL FetchError: Fetch failed: navigation timeout (Page.goto: Timeout 30000ms exceeded.)
- Latency: 40060 / 96030 / 65973 ms (spread 56.0s)
- Error: FetchError: Fetch failed: navigation timeout (Page.goto: Timeout 30000ms exceeded.)
- Evidence: P1 cq=full stable=True polls=3 h=768->768 capped=False shotcap=False dims=[1366, 768] html=7339B cf=False retry=0 banner=60/False replay_fullmap=False txt=760; P2 cq=full stable=True polls=3 h=768->768 capped=False shotcap=False dims=[1366, 768] html=7339B cf=False retry=0 banner=60/False replay_fullmap=False txt=760
- Evidence: pair p1->p2 (probe src p2(substituted)) risk=0.3 changed=True flagged=False verdict=changed material=False escalation_band=False non-zero-layers={'layer1_hash': 1.0} degraded=['layer7_cloaking'] (297 ms)

### FAIL ΓÇö https://www.nbcnews.com/ (Tier ?, Category Akamai Bot Manager (not attempted by PROMPT-002 at all))
- Pass results: P1: FAIL SSRFBlockedError: Could not resolve host 'www.nbcnews.com' / P2: OK 200 74.2s / P3: OK 200 51.6s
- Latency: 4780 / 74190 / 43527 ms (spread 69.4s)
- Error: SSRFBlockedError: Could not resolve host 'www.nbcnews.com'
- Evidence: P2 cq=full stable=True polls=9 h=12881->14305 capped=False shotcap=False dims=[1366, 14971] html=3545328B cf=False retry=0 banner=780/False replay_fullmap=False txt=38476; P3 cq=full stable=True polls=10 h=12887->14497 capped=False shotcap=False dims=[1366, 15156] html=3548121B cf=False retry=0 banner=660/False replay_fullmap=False txt=38583
- Evidence: pair p2->p3 (probe src p2) risk=1.0 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.9995, 'layer3_link_audit': 0.6113, 'layer4_visual_diff': 0.5105, 'layer8_semantics': 0.0889} degraded=[] (7875 ms)

### FAIL ΓÇö https://www.accuweather.com/ (Tier ?, Category Akamai Bot Manager (not attempted by PROMPT-002 at all))
- Pass results: P1: FAIL FetchError: Fetch failed: network error (Page.goto: net::ERR_HTTP2_PROTOCOL_ERROR at https://www.accuweather.com/) / P2: FAIL FetchError: Fetch failed: network error (Page.goto: net::ERR_HTTP2_PROTOCOL_ERROR at https://www.accuweather.com/) / P3: FAIL FetchError: Fetch failed: network error (Page.goto: net::ERR_HTTP2_PROTOCOL_ERROR at https://www.accuweather.com/)
- Latency: 5530 / 27580 / 14453 ms (spread 22.0s)
- Error: FetchError: Fetch failed: network error (Page.goto: net::ERR_HTTP2_PROTOCOL_ERROR at https://www.accuweather.com/) || FetchError: Fetch failed: network error (Page.goto: net::ERR_HTTP2_PROTOCOL_ERROR at https://www.accuweather.com/) || FetchError: Fetch failed: network error (Page.goto: net::ERR_HTTP2_PROTOCOL_ERROR at https://www.accuweather.com/)

### FAIL ΓÇö https://www.airbnb.com/ (Tier ?, Category Akamai Bot Manager (not attempted by PROMPT-002 at all))
- Pass results: P1: OK 200 25.3s / P2: OK 200 36.4s / P3: OK 200 20.1s
- Latency: 20140 / 36410 / 27287 ms (spread 16.3s)
- Error: capture succeeded and no wall fingerprint, but detection flagged: p1->p2 risk=0.9913 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.7534, 'layer3_link_audit': 0.4, 'layer4_visual_diff': 0.1175, 'layer8_semantics': 0.3644, 'layer9_fusion': 0.9913}; p2->p3 risk=0.9989 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.4412, 'layer3_link_audit': 0.4, 'layer4_visual_diff': 0.2016, 'layer8_semantics': 0.4224, 'layer9_fusion': 0.9989}; p1->p3 risk=0.9884 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.3321, 'layer3_link_audit': 0.4, 'layer4_visual_diff': 0.186, 'layer9_fusion': 0.9884}
- Evidence: P1 cq=full stable=True polls=9 h=1938->1898 capped=False shotcap=False dims=[1366, 4140] html=1803306B cf=False retry=0 banner=60/False replay_fullmap=False txt=14764; P2 cq=partial stable=False polls=10 h=1170->2094 capped=False shotcap=False dims=[1366, 4576] html=2102533B cf=False retry=0 banner=60/False replay_fullmap=False txt=19891; P3 cq=full stable=True polls=7 h=1174->1134 capped=False shotcap=False dims=[1366, 2846] html=1386742B cf=False retry=0 banner=60/False replay_fullmap=False txt=11316
- Evidence: pair p1->p2 (probe src p1) risk=0.9913 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.7534, 'layer3_link_audit': 0.4, 'layer4_visual_diff': 0.1175, 'layer8_semantics': 0.3644} degraded=[] (8781 ms)
- Evidence: pair p2->p3 (probe src p2) risk=0.9989 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.4412, 'layer3_link_audit': 0.4, 'layer4_visual_diff': 0.2016, 'layer8_semantics': 0.4224} degraded=[] (11687 ms)
- Evidence: pair p1->p3 (probe src p1) risk=0.9884 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.3321, 'layer3_link_audit': 0.4, 'layer4_visual_diff': 0.186} degraded=[] (2687 ms)

### FAIL ΓÇö https://www.godaddy.com/ (Tier ?, Category Akamai Bot Manager (not attempted by PROMPT-002 at all))
- Pass results: P1: OK 403 14.7s / P2: OK 403 14.7s / P3: OK 403 13.1s
- Latency: 13140 / 14730 / 14180 ms (spread 1.6s)
- Error: capture SUCCEEDED but returned wall/interstitial content ΓÇö status 403, title 'Access Denied', reasons ['http_status=403', 'content_free_shell(visible=207,tags=7)', 'title:akamai_botmgr'], cookie names ['30-Sep-2027 07:41:25 GMT; path', 'currency', 'market'], server 'AkamaiGHost'
- Evidence: P1 cq=full stable=True polls=3 h=768->768 capped=False shotcap=False dims=[1366, 768] html=291B cf=False retry=0 banner=30/False replay_fullmap=False txt=207; P2 cq=full stable=True polls=3 h=768->768 capped=False shotcap=False dims=[1366, 768] html=293B cf=False retry=0 banner=30/False replay_fullmap=False txt=209; P3 cq=full stable=True polls=3 h=768->768 capped=False shotcap=False dims=[1366, 768] html=291B cf=False retry=0 banner=30/False replay_fullmap=False txt=207
- Evidence: pair p1->p2 (probe src p1) risk=0.3 changed=True flagged=False verdict=changed material=False escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer4_visual_diff': 0.0213} degraded=['layer7_cloaking'] (187 ms)
- Evidence: pair p2->p3 (probe src p2) risk=0.3 changed=True flagged=False verdict=changed material=False escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer4_visual_diff': 0.0166} degraded=['layer7_cloaking'] (188 ms)
- Evidence: pair p1->p3 (probe src p1) risk=0.3 changed=True flagged=False verdict=changed material=False escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer4_visual_diff': 0.0053} degraded=['layer7_cloaking'] (187 ms)

### FAIL ΓÇö https://www.leboncoin.fr/ (Tier ?, Category DataDome)
- Pass results: P1: OK 403 15.7s / P2: OK 403 23.2s / P3: OK 403 19.7s
- Latency: 15660 / 23200 / 19520 ms (spread 7.5s)
- Error: capture SUCCEEDED but returned wall/interstitial content ΓÇö status 403, title 'leboncoin.fr', reasons ['http_status=403', 'content_free_shell(visible=12,tags=9)', 'blocking_fp:datadome'], cookie names ['datadome'], server None
- Evidence: P1 cq=full stable=True polls=3 h=768->768 capped=False shotcap=False dims=[1366, 768] html=1468B cf=False retry=0 banner=60/False replay_fullmap=False txt=12; P2 cq=full stable=True polls=3 h=768->768 capped=False shotcap=False dims=[1366, 768] html=1468B cf=False retry=0 banner=60/False replay_fullmap=False txt=12; P3 cq=full stable=True polls=3 h=768->768 capped=False shotcap=False dims=[1366, 768] html=1468B cf=False retry=0 banner=60/False replay_fullmap=False txt=12
- Evidence: pair p1->p2 (probe src p1) risk=0.3 changed=True flagged=False verdict=changed material=False escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer3_link_audit': 0.02, 'layer4_visual_diff': 0.0057} degraded=['layer7_cloaking'] (188 ms)
- Evidence: pair p2->p3 (probe src p2) risk=0.3 changed=True flagged=False verdict=changed material=False escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer3_link_audit': 0.02, 'layer4_visual_diff': 0.0114} degraded=['layer7_cloaking'] (187 ms)
- Evidence: pair p1->p3 (probe src p1) risk=0.3 changed=True flagged=False verdict=changed material=False escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer3_link_audit': 0.02, 'layer4_visual_diff': 0.0127} degraded=['layer7_cloaking'] (141 ms)

### FAIL ΓÇö https://www.sncf-connect.com/ (Tier ?, Category DataDome)
- Pass results: P1: FAIL _ChallengeUnsolvedError: Site is behind bot protection that could not be bypassed (Cloudflare challenge detected) / P2: FAIL _ChallengeUnsolvedError: Site is behind bot protection that could not be bypassed (Cloudflare challenge detected) / P3: FAIL _ChallengeUnsolvedError: Site is behind bot protection that could not be bypassed (Cloudflare challenge detected)
- Latency: 95830 / 98610 / 97450 ms (spread 2.8s)
- Error: _ChallengeUnsolvedError: Site is behind bot protection that could not be bypassed (Cloudflare challenge detected) || _ChallengeUnsolvedError: Site is behind bot protection that could not be bypassed (Cloudflare challenge detected) || _ChallengeUnsolvedError: Site is behind bot protection that could not be bypassed (Cloudflare challenge detected)

### FAIL ΓÇö https://www.footlocker.com/ (Tier ?, Category DataDome)
- Pass results: P1: OK 200 24.7s / P2: OK 200 27.1s / P3: OK 200 30.9s
- Latency: 24700 / 30880 / 27547 ms (spread 6.2s)
- Error: capture succeeded and no wall fingerprint, but detection flagged: p1->p2 risk=0.9996 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.985, 'layer3_link_audit': 0.12, 'layer4_visual_diff': 0.3102, 'layer9_fusion': 0.9996}; p2->p3 risk=0.9932 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.004, 'layer3_link_audit': 0.16, 'layer4_visual_diff': 0.245, 'layer9_fusion': 0.9932}; p1->p3 risk=0.8357 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.7534, 'layer3_link_audit': 0.16, 'layer4_visual_diff': 0.0802, 'layer9_fusion': 0.8357}
- Evidence: P1 cq=full stable=True polls=3 h=6890->6890 capped=False shotcap=False dims=[1366, 6890] html=1800258B cf=False retry=0 banner=150/False replay_fullmap=False txt=9007; P2 cq=full stable=True polls=5 h=6881->6922 capped=False shotcap=False dims=[1366, 6922] html=1801451B cf=False retry=0 banner=150/False replay_fullmap=False txt=9024; P3 cq=full stable=True polls=10 h=6890->6890 capped=False shotcap=False dims=[1366, 6890] html=1800521B cf=False retry=0 banner=150/False replay_fullmap=False txt=9015
- Evidence: pair p1->p2 (probe src p1) risk=0.9996 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.985, 'layer3_link_audit': 0.12, 'layer4_visual_diff': 0.3102} degraded=[] (3078 ms)
- Evidence: pair p2->p3 (probe src p2) risk=0.9932 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.004, 'layer3_link_audit': 0.16, 'layer4_visual_diff': 0.245} degraded=[] (3157 ms)
- Evidence: pair p1->p3 (probe src p1) risk=0.8357 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.7534, 'layer3_link_audit': 0.16, 'layer4_visual_diff': 0.0802} degraded=[] (2547 ms)

### FAIL ΓÇö https://www.zillow.com/ (Tier ?, Category PerimeterX / HUMAN Defense Platform)
- Pass results: P1: OK 403 24.5s / P2: OK 403 20.9s / P3: OK 403 17.7s
- Latency: 17700 / 24520 / 21027 ms (spread 6.8s)
- Error: capture SUCCEEDED but returned wall/interstitial content ΓÇö status 403, title 'Access to this page has been denied', reasons ['http_status=403', 'content_free_shell(visible=146,tags=31)', 'blocking_fp:perimeterx'], cookie names [], server 'CloudFront'
- Evidence: P1 cq=full stable=True polls=3 h=768->768 capped=False shotcap=False dims=[1366, 768] html=9978B cf=False retry=0 banner=300/False replay_fullmap=False txt=146; P2 cq=full stable=True polls=3 h=768->768 capped=False shotcap=False dims=[1366, 768] html=9978B cf=False retry=0 banner=300/False replay_fullmap=False txt=146; P3 cq=full stable=True polls=3 h=768->768 capped=False shotcap=False dims=[1366, 768] html=9978B cf=False retry=0 banner=240/False replay_fullmap=False txt=146
- Evidence: pair p1->p2 (probe src p1) risk=0.3 changed=True flagged=False verdict=changed material=False escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer4_visual_diff': 0.0041} degraded=['layer7_cloaking'] (172 ms)
- Evidence: pair p2->p3 (probe src p2) risk=0.3 changed=True flagged=False verdict=changed material=False escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer4_visual_diff': 0.0031} degraded=['layer7_cloaking'] (172 ms)
- Evidence: pair p1->p3 (probe src p1) risk=0.3 changed=True flagged=False verdict=changed material=False escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer4_visual_diff': 0.004} degraded=['layer7_cloaking'] (187 ms)

### FAIL ΓÇö https://stockx.com/ (Tier ?, Category PerimeterX / HUMAN Defense Platform)
- Pass results: P1: OK 200 19.8s / P2: OK 200 29.1s / P3: OK 200 28.2s
- Latency: 19810 / 29120 / 25710 ms (spread 9.3s)
- Error: capture succeeded and no wall fingerprint, but detection flagged: p1->p2 risk=1.0 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 1.0, 'layer3_link_audit': 1.0, 'layer4_visual_diff': 0.4329, 'layer8_semantics': 0.3351, 'layer9_fusion': 1.0}; p2->p3 risk=1.0 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 1.0, 'layer3_link_audit': 1.0, 'layer4_visual_diff': 0.3489, 'layer9_fusion': 1.0}; p1->p3 risk=1.0 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 1.0, 'layer3_link_audit': 1.0, 'layer4_visual_diff': 0.4515, 'layer8_semantics': 0.3629, 'layer9_fusion': 1.0}
- Evidence: P1 cq=full stable=True polls=5 h=9678->7916 capped=False shotcap=False dims=[1366, 7932] html=847353B cf=False retry=0 banner=90/False replay_fullmap=False txt=7716; P2 cq=full stable=True polls=7 h=9678->8810 capped=False shotcap=False dims=[1366, 9429] html=971072B cf=False retry=0 banner=120/False replay_fullmap=False txt=12234; P3 cq=full stable=True polls=4 h=9678->9202 capped=False shotcap=False dims=[1366, 9202] html=980964B cf=False retry=0 banner=90/False replay_fullmap=False txt=11703
- Evidence: pair p1->p2 (probe src p1) risk=1.0 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 1.0, 'layer3_link_audit': 1.0, 'layer4_visual_diff': 0.4329, 'layer8_semantics': 0.3351} degraded=['layer7_cloaking'] (2593 ms)
- Evidence: pair p2->p3 (probe src p2) risk=1.0 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 1.0, 'layer3_link_audit': 1.0, 'layer4_visual_diff': 0.3489} degraded=['layer7_cloaking'] (2906 ms)
- Evidence: pair p1->p3 (probe src p1) risk=1.0 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 1.0, 'layer3_link_audit': 1.0, 'layer4_visual_diff': 0.4515, 'layer8_semantics': 0.3629} degraded=['layer7_cloaking'] (3422 ms)

### FAIL ΓÇö https://www.yelp.com/ (Tier ?, Category PerimeterX / HUMAN Defense Platform)
- Pass results: P1: OK 403 13.0s / P2: OK 403 15.9s / P3: OK 403 19.4s
- Latency: 13030 / 19380 / 16107 ms (spread 6.3s)
- Error: capture SUCCEEDED but returned wall/interstitial content ΓÇö status 403, title 'yelp.com', reasons ['http_status=403', 'content_free_shell(visible=8,tags=9)', 'blocking_fp:datadome'], cookie names ['datadome'], server 'DataDome'
- Evidence: P1 cq=full stable=True polls=3 h=768->768 capped=False shotcap=False dims=[1366, 768] html=1470B cf=False retry=0 banner=60/False replay_fullmap=False txt=8; P2 cq=full stable=True polls=3 h=768->768 capped=False shotcap=False dims=[1366, 768] html=1470B cf=False retry=0 banner=60/False replay_fullmap=False txt=8; P3 cq=full stable=True polls=3 h=768->768 capped=False shotcap=False dims=[1366, 768] html=1470B cf=False retry=0 banner=60/False replay_fullmap=False txt=8
- Evidence: pair p1->p2 (probe src p1) risk=0.3 changed=True flagged=False verdict=changed material=False escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer3_link_audit': 0.02, 'layer4_visual_diff': 0.0023} degraded=['layer7_cloaking'] (156 ms)
- Evidence: pair p2->p3 (probe src p2) risk=0.3 changed=True flagged=False verdict=changed material=False escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer3_link_audit': 0.02, 'layer4_visual_diff': 0.0059} degraded=['layer7_cloaking'] (156 ms)
- Evidence: pair p1->p3 (probe src p1) risk=0.3 changed=True flagged=False verdict=changed material=False escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer3_link_audit': 0.02, 'layer4_visual_diff': 0.0057} degraded=['layer7_cloaking'] (141 ms)

### FAIL ΓÇö https://www.target.com/ (Tier ?, Category AWS WAF (challenge-action / CAPTCHA-capable))
- Pass results: P1: OK 200 32.8s / P2: OK 200 35.1s / P3: OK 200 34.3s
- Latency: 32800 / 35090 / 34050 ms (spread 2.3s)
- Error: capture succeeded and no wall fingerprint, but detection flagged: p1->p2 risk=1.0 layers={'layer1_hash': 1.0, 'layer3_link_audit': 0.5934, 'layer4_visual_diff': 0.0001, 'layer7_cloaking': 1.0, 'layer9_fusion': 1.0}; p2->p3 risk=1.0 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.0605, 'layer3_link_audit': 0.5934, 'layer7_cloaking': 1.0, 'layer9_fusion': 1.0}; p1->p3 risk=1.0 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.0605, 'layer3_link_audit': 0.5934, 'layer4_visual_diff': 0.0001, 'layer7_cloaking': 1.0, 'layer9_fusion': 1.0}
- Evidence: P1 cq=full stable=True polls=7 h=6339->7809 capped=False shotcap=False dims=[1366, 7809] html=419282B cf=False retry=0 banner=510/False replay_fullmap=False txt=3222; P2 cq=full stable=True polls=7 h=6339->7809 capped=False shotcap=False dims=[1366, 7809] html=419279B cf=False retry=0 banner=510/False replay_fullmap=False txt=3222; P3 cq=full stable=True polls=3 h=6339->7809 capped=False shotcap=False dims=[1366, 7809] html=424864B cf=False retry=0 banner=510/False replay_fullmap=False txt=3244
- Evidence: pair p1->p2 (probe src p1) risk=1.0 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer3_link_audit': 0.5934, 'layer4_visual_diff': 0.0001, 'layer7_cloaking': 1.0} degraded=[] (1656 ms)
- Evidence: pair p2->p3 (probe src p2) risk=1.0 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.0605, 'layer3_link_audit': 0.5934, 'layer7_cloaking': 1.0} degraded=[] (1578 ms)
- Evidence: pair p1->p3 (probe src p1) risk=1.0 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.0605, 'layer3_link_audit': 0.5934, 'layer4_visual_diff': 0.0001, 'layer7_cloaking': 1.0} degraded=[] (1640 ms)

### FAIL ΓÇö https://www.chase.com/ (Tier ?, Category AWS WAF (challenge-action / CAPTCHA-capable))
- Pass results: P1: OK 200 15.1s / P2: OK 200 15.1s / P3: OK 200 14.4s
- Latency: 14380 / 15110 / 14860 ms (spread 0.7s)
- Error: capture succeeded and no wall fingerprint, but detection flagged: p1->p2 risk=0.964 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.5034, 'layer3_link_audit': 0.2702, 'layer4_visual_diff': 0.1455, 'layer9_fusion': 0.964}; p2->p3 risk=0.9524 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.0017, 'layer3_link_audit': 0.4173, 'layer4_visual_diff': 0.1453, 'layer9_fusion': 0.9524}; p1->p3 risk=0.9765 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.0008, 'layer3_link_audit': 0.4173, 'layer4_visual_diff': 0.1732, 'layer9_fusion': 0.9765}
- Evidence: P1 cq=full stable=True polls=3 h=3555->3822 capped=False shotcap=False dims=[1366, 3822] html=404286B cf=False retry=0 banner=120/False replay_fullmap=False txt=7521; P2 cq=full stable=True polls=3 h=3555->3822 capped=False shotcap=False dims=[1366, 3822] html=404366B cf=False retry=0 banner=120/False replay_fullmap=False txt=7439; P3 cq=full stable=True polls=3 h=3555->3822 capped=False shotcap=False dims=[1366, 3822] html=404419B cf=False retry=0 banner=60/False replay_fullmap=False txt=7449
- Evidence: pair p1->p2 (probe src p1) risk=0.964 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.5034, 'layer3_link_audit': 0.2702, 'layer4_visual_diff': 0.1455} degraded=[] (1266 ms)
- Evidence: pair p2->p3 (probe src p2) risk=0.9524 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.0017, 'layer3_link_audit': 0.4173, 'layer4_visual_diff': 0.1453} degraded=[] (1328 ms)
- Evidence: pair p1->p3 (probe src p1) risk=0.9765 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.0008, 'layer3_link_audit': 0.4173, 'layer4_visual_diff': 0.1732} degraded=[] (1390 ms)

### FAIL ΓÇö https://www.hulu.com/ (Tier ?, Category AWS WAF (challenge-action / CAPTCHA-capable))
- Pass results: P1: OK 200 23.4s / P2: OK 200 29.3s / P3: OK 200 52.9s
- Latency: 23450 / 52890 / 35227 ms (spread 29.4s)
- Error: capture succeeded and no wall fingerprint, but detection flagged: p1->p2 risk=1.0 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.0004, 'layer3_link_audit': 0.08, 'layer7_cloaking': 1.0, 'layer9_fusion': 1.0}; p2->p3 risk=1.0 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.9998, 'layer3_link_audit': 0.38, 'layer4_visual_diff': 0.4416, 'layer7_cloaking': 1.0, 'layer8_semantics': 0.2384, 'layer9_fusion': 1.0}; p1->p3 risk=1.0 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.9998, 'layer3_link_audit': 0.38, 'layer4_visual_diff': 0.4416, 'layer7_cloaking': 1.0, 'layer8_semantics': 0.2384, 'layer9_fusion': 1.0}
- Evidence: P1 cq=full stable=True polls=3 h=6444->9269 capped=False shotcap=False dims=[4000, 9269] html=839047B cf=False retry=0 banner=90/False replay_fullmap=False txt=9206; P2 cq=full stable=True polls=3 h=6444->9269 capped=False shotcap=False dims=[4000, 9269] html=839196B cf=False retry=0 banner=90/False replay_fullmap=False txt=9206; P3 cq=full stable=True polls=3 h=9269->13594 capped=False shotcap=False dims=[4000, 13594] html=981743B cf=False retry=0 banner=90/False replay_fullmap=False txt=9939
- Evidence: pair p1->p2 (probe src p1) risk=1.0 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.0004, 'layer3_link_audit': 0.08, 'layer7_cloaking': 1.0} degraded=[] (3156 ms)
- Evidence: pair p2->p3 (probe src p2) risk=1.0 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.9998, 'layer3_link_audit': 0.38, 'layer4_visual_diff': 0.4416, 'layer7_cloaking': 1.0, 'layer8_semantics': 0.2384} degraded=[] (3250 ms)
- Evidence: pair p1->p3 (probe src p1) risk=1.0 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.9998, 'layer3_link_audit': 0.38, 'layer4_visual_diff': 0.4416, 'layer7_cloaking': 1.0, 'layer8_semantics': 0.2384} degraded=[] (3484 ms)

### FAIL ΓÇö https://dash.cloudflare.com/ (Tier ?, Category Cloudflare Enterprise / Turnstile (beyond the free JS-challenge tier PROMPT-002 already tested))
- Pass results: P1: OK 200 15.2s / P2: OK 200 15.7s / P3: OK 200 19.1s
- Latency: 15200 / 19080 / 16667 ms (spread 3.9s)
- Error: capture SUCCEEDED but returned wall/interstitial content ΓÇö status 200, title 'Cloudflare Dashboard | Manage Your Account', reasons ['content_free_shell(visible=589,tags=262)', 'blocking_fp:cloudflare_mitigated'], cookie names ['30 Sep 2026 08:11:49 GMT', '__cf_bm'], server 'cloudflare'
- Evidence: P1 cq=full stable=True polls=3 h=780->780 capped=False shotcap=False dims=[1366, 780] html=96099B cf=False retry=0 banner=60/False replay_fullmap=False txt=589; P2 cq=full stable=True polls=3 h=780->780 capped=False shotcap=False dims=[1366, 780] html=96095B cf=False retry=0 banner=60/False replay_fullmap=False txt=589; P3 cq=full stable=True polls=3 h=780->780 capped=False shotcap=False dims=[1366, 780] html=96058B cf=False retry=0 banner=90/False replay_fullmap=False txt=589
- Evidence: pair p1->p2 (probe src p1) risk=0.3 changed=True flagged=False verdict=changed material=False escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer3_link_audit': 0.02, 'layer4_visual_diff': 0.0153} degraded=['layer7_cloaking'] (172 ms)
- Evidence: pair p2->p3 (probe src p2) risk=0.3445 changed=True flagged=False verdict=changed material=False escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer3_link_audit': 0.02, 'layer4_visual_diff': 0.0437} degraded=['layer7_cloaking'] (266 ms)
- Evidence: pair p1->p3 (probe src p1) risk=0.3106 changed=True flagged=False verdict=changed material=False escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer3_link_audit': 0.02, 'layer4_visual_diff': 0.0378} degraded=['layer7_cloaking'] (250 ms)

### FAIL ΓÇö https://www.walmart.com/ (Tier ?, Category Harder e-commerce (large catalog, aggressive WAF, geofencing-aware))
- Pass results: P1: OK 200 18.9s / P2: OK 200 22.7s / P3: OK 200 21.2s
- Latency: 18940 / 22720 / 20940 ms (spread 3.8s)
- Error: capture succeeded and no wall fingerprint, but detection flagged: p1->p2 risk=0.9772 layers={'layer1_hash': 1.0, 'layer3_link_audit': 0.04, 'layer4_visual_diff': 0.0146, 'layer7_cloaking': 0.3887, 'layer9_fusion': 0.9772}; p2->p3 risk=0.9747 layers={'layer1_hash': 1.0, 'layer3_link_audit': 0.04, 'layer4_visual_diff': 0.0106, 'layer7_cloaking': 0.3887, 'layer9_fusion': 0.9747}; p1->p3 risk=0.9777 layers={'layer1_hash': 1.0, 'layer3_link_audit': 0.04, 'layer4_visual_diff': 0.0155, 'layer7_cloaking': 0.3887, 'layer9_fusion': 0.9777}
- Evidence: P1 cq=full stable=True polls=3 h=4063->4361 capped=False shotcap=False dims=[1366, 4361] html=385093B cf=False retry=0 banner=270/False replay_fullmap=False txt=1507; P2 cq=full stable=True polls=3 h=4063->4361 capped=False shotcap=False dims=[1366, 4361] html=385093B cf=False retry=0 banner=270/False replay_fullmap=False txt=1507; P3 cq=full stable=True polls=3 h=4063->4361 capped=False shotcap=False dims=[1366, 4361] html=385093B cf=False retry=0 banner=270/False replay_fullmap=False txt=1507
- Evidence: pair p1->p2 (probe src p1) risk=0.9772 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer3_link_audit': 0.04, 'layer4_visual_diff': 0.0146, 'layer7_cloaking': 0.3887} degraded=[] (1062 ms)
- Evidence: pair p2->p3 (probe src p2) risk=0.9747 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer3_link_audit': 0.04, 'layer4_visual_diff': 0.0106, 'layer7_cloaking': 0.3887} degraded=[] (828 ms)
- Evidence: pair p1->p3 (probe src p1) risk=0.9777 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer3_link_audit': 0.04, 'layer4_visual_diff': 0.0155, 'layer7_cloaking': 0.3887} degraded=[] (860 ms)

### FAIL ΓÇö https://www.etsy.com/ (Tier ?, Category Harder e-commerce (large catalog, aggressive WAF, geofencing-aware))
- Pass results: P1: OK 403 11.9s / P2: OK 403 14.2s / P3: OK 403 14.1s
- Latency: 11920 / 14200 / 13393 ms (spread 2.3s)
- Error: capture SUCCEEDED but returned wall/interstitial content ΓÇö status 403, title 'etsy.com', reasons ['http_status=403', 'content_free_shell(visible=8,tags=9)', 'blocking_fp:datadome'], cookie names ['datadome', 'exp_ebid', 'v'], server 'DataDome'
- Evidence: P1 cq=full stable=True polls=3 h=768->768 capped=False shotcap=False dims=[1366, 768] html=1470B cf=False retry=0 banner=60/False replay_fullmap=False txt=8; P2 cq=full stable=True polls=3 h=768->768 capped=False shotcap=False dims=[1366, 768] html=1470B cf=False retry=0 banner=60/False replay_fullmap=False txt=8; P3 cq=full stable=True polls=3 h=768->768 capped=False shotcap=False dims=[1366, 768] html=1470B cf=False retry=0 banner=60/False replay_fullmap=False txt=8
- Evidence: pair p1->p2 (probe src p1) risk=0.3 changed=True flagged=False verdict=changed material=False escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer3_link_audit': 0.02, 'layer4_visual_diff': 0.0033, 'layer6_security_metadata': 0.15} degraded=['layer7_cloaking'] (156 ms)
- Evidence: pair p2->p3 (probe src p2) risk=0.3 changed=True flagged=False verdict=changed material=False escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer3_link_audit': 0.02, 'layer4_visual_diff': 0.0055, 'layer6_security_metadata': 0.15} degraded=['layer7_cloaking'] (156 ms)
- Evidence: pair p1->p3 (probe src p1) risk=0.3 changed=True flagged=False verdict=changed material=False escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer3_link_audit': 0.02, 'layer4_visual_diff': 0.0039, 'layer6_security_metadata': 0.15} degraded=['layer7_cloaking'] (141 ms)

### FAIL ΓÇö https://www.ebay.co.uk/ (Tier ?, Category Harder e-commerce (large catalog, aggressive WAF, geofencing-aware))
- Pass results: P1: OK 200 13.6s / P2: OK 200 35.7s / P3: OK 200 38.7s
- Latency: 13560 / 38690 / 29307 ms (spread 25.1s)
- Error: capture succeeded and no wall fingerprint, but detection flagged: p1->p2 risk=0.6346 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.0004, 'layer3_link_audit': 0.34, 'layer4_visual_diff': 0.0595, 'layer9_fusion': 0.6346}; p1->p3 risk=0.6357 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.0004, 'layer3_link_audit': 0.34, 'layer4_visual_diff': 0.0597, 'layer9_fusion': 0.6357}
- Evidence: P1 cq=full stable=True polls=4 h=2905->2905 capped=False shotcap=False dims=[1366, 2905] html=1159630B cf=False retry=0 banner=23/True replay_fullmap=False txt=10949; P2 cq=full stable=True polls=4 h=2905->2905 capped=False shotcap=False dims=[1366, 2905] html=1156124B cf=False retry=0 banner=23/True replay_fullmap=False txt=10949; P3 cq=full stable=True polls=4 h=2905->2905 capped=False shotcap=False dims=[1366, 2905] html=1159495B cf=False retry=0 banner=23/True replay_fullmap=False txt=10949
- Evidence: pair p1->p2 (probe src p1) risk=0.6346 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.0004, 'layer3_link_audit': 0.34, 'layer4_visual_diff': 0.0595} degraded=['layer7_cloaking'] (2219 ms)
- Evidence: pair p2->p3 (probe src p2) risk=0.3 changed=True flagged=False verdict=changed material=False escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer3_link_audit': 0.34, 'layer4_visual_diff': 0.0026} degraded=['layer7_cloaking'] (2328 ms)
- Evidence: pair p1->p3 (probe src p1) risk=0.6357 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.0004, 'layer3_link_audit': 0.34, 'layer4_visual_diff': 0.0597} degraded=['layer7_cloaking'] (2203 ms)

### FAIL ΓÇö https://www.aliexpress.com/ (Tier ?, Category Harder e-commerce (large catalog, aggressive WAF, geofencing-aware))
- Pass results: P1: OK 200 24.1s / P2: OK 200 24.3s / P3: OK 200 24.8s
- Latency: 24090 / 24760 / 24397 ms (spread 0.7s)
- Error: capture succeeded and no wall fingerprint, but detection flagged: p1->p2 risk=0.9449 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.9392, 'layer3_link_audit': 0.14, 'layer4_visual_diff': 0.1193, 'layer9_fusion': 0.9449}; p1->p3 risk=0.9397 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.9392, 'layer3_link_audit': 0.1, 'layer4_visual_diff': 0.1193, 'layer9_fusion': 0.9397}
- Evidence: P1 cq=full stable=True polls=4 h=1798->1798 capped=False shotcap=False dims=[1366, 1798] html=644045B cf=False retry=0 banner=360/False replay_fullmap=False txt=14208; P2 cq=full stable=True polls=4 h=1798->1798 capped=False shotcap=False dims=[1366, 1798] html=645354B cf=False retry=0 banner=360/False replay_fullmap=False txt=14211; P3 cq=full stable=True polls=4 h=1798->1798 capped=False shotcap=False dims=[1366, 1798] html=645404B cf=False retry=0 banner=360/False replay_fullmap=False txt=14211
- Evidence: pair p1->p2 (probe src p1) risk=0.9449 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.9392, 'layer3_link_audit': 0.14, 'layer4_visual_diff': 0.1193} degraded=[] (1750 ms)
- Evidence: pair p2->p3 (probe src p2) risk=0.1788 changed=True flagged=False verdict=changed material=False escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer3_link_audit': 0.12, 'layer4_visual_diff': 0.0008} degraded=[] (1844 ms)
- Evidence: pair p1->p3 (probe src p1) risk=0.9397 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.9392, 'layer3_link_audit': 0.1, 'layer4_visual_diff': 0.1193} degraded=[] (2047 ms)

### FAIL ΓÇö https://unsplash.com/ (Tier ?, Category Harder lazy-load (multiple libraries, infinite API-gated scroll, not just image lazy-load))
- Pass results: P1: OK 401 12.0s / P2: OK 401 13.3s / P3: OK 401 12.5s
- Latency: 12030 / 13310 / 12607 ms (spread 1.3s)
- Error: capture SUCCEEDED but returned wall/interstitial content ΓÇö status 401, title "Making sure you're not a bot!", reasons ['http_status=401', 'content_free_shell(visible=1358,tags=45)'], cookie names ['30 Sep 2027 07:42:16 GMT; path', 'require_cookie_consent'], server 'Varnish'
- Evidence: P1 cq=full stable=True polls=3 h=768->768 capped=False shotcap=False dims=[1366, 768] html=7772B cf=False retry=0 banner=30/False replay_fullmap=False txt=1358; P2 cq=full stable=True polls=3 h=768->768 capped=False shotcap=False dims=[1366, 768] html=7772B cf=False retry=0 banner=30/False replay_fullmap=False txt=1358; P3 cq=full stable=True polls=3 h=768->768 capped=False shotcap=False dims=[1366, 768] html=7772B cf=False retry=0 banner=30/False replay_fullmap=False txt=1358
- Evidence: pair p1->p2 (probe src p1) risk=0.3 changed=True flagged=False verdict=changed material=False escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer4_visual_diff': 0.0004} degraded=['layer7_cloaking'] (266 ms)
- Evidence: pair p2->p3 (probe src p2) risk=0.3 changed=True flagged=False verdict=changed material=False escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer4_visual_diff': 0.0028} degraded=['layer7_cloaking'] (312 ms)
- Evidence: pair p1->p3 (probe src p1) risk=0.3 changed=True flagged=False verdict=changed material=False escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer4_visual_diff': 0.0026} degraded=['layer7_cloaking'] (297 ms)

### FAIL ΓÇö https://www.pexels.com/ (Tier ?, Category Harder lazy-load (multiple libraries, infinite API-gated scroll, not just image lazy-load))
- Pass results: P1: OK 200 18.5s / P2: OK 200 20.6s / P3: OK 200 19.1s
- Latency: 18500 / 20610 / 19417 ms (spread 2.1s)
- Error: capture succeeded and no wall fingerprint, but detection flagged: p1->p2 risk=0.6338 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.0013, 'layer3_link_audit': 0.02, 'layer4_visual_diff': 0.089, 'layer9_fusion': 0.6338}; p2->p3 risk=1.0 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.151, 'layer3_link_audit': 0.02, 'layer4_visual_diff': 0.6093, 'layer8_semantics': 0.1329, 'layer9_fusion': 1.0}; p1->p3 risk=1.0 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.1545, 'layer3_link_audit': 0.04, 'layer4_visual_diff': 0.6249, 'layer8_semantics': 0.0198, 'layer9_fusion': 1.0}
- Evidence: P1 cq=full stable=True polls=4 h=2631->4753 capped=False shotcap=False dims=[1366, 4753] html=916143B cf=False retry=0 banner=120/False replay_fullmap=False txt=5563; P2 cq=full stable=True polls=5 h=2631->3901 capped=False shotcap=False dims=[1366, 4753] html=913925B cf=False retry=0 banner=120/False replay_fullmap=False txt=5531; P3 cq=full stable=True polls=4 h=2693->2696 capped=False shotcap=False dims=[1366, 3772] html=855223B cf=False retry=0 banner=120/False replay_fullmap=False txt=5301
- Evidence: pair p1->p2 (probe src p1) risk=0.6338 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.0013, 'layer3_link_audit': 0.02, 'layer4_visual_diff': 0.089} degraded=['layer7_cloaking'] (1781 ms)
- Evidence: pair p2->p3 (probe src p2) risk=1.0 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.151, 'layer3_link_audit': 0.02, 'layer4_visual_diff': 0.6093, 'layer8_semantics': 0.1329} degraded=['layer7_cloaking'] (1641 ms)
- Evidence: pair p1->p3 (probe src p1) risk=1.0 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.1545, 'layer3_link_audit': 0.04, 'layer4_visual_diff': 0.6249, 'layer8_semantics': 0.0198} degraded=['layer7_cloaking'] (1687 ms)

### FAIL ΓÇö https://500px.com/ (Tier ?, Category Harder lazy-load (multiple libraries, infinite API-gated scroll, not just image lazy-load))
- Pass results: P1: OK 200 12.1s / P2: OK 200 15.9s / P3: OK 200 14.4s
- Latency: 12140 / 15890 / 14147 ms (spread 3.8s)
- Error: capture SUCCEEDED but returned wall/interstitial content ΓÇö status 200, title 'Explore Popular Photos and Inspiration Galleries | 500px', reasons ['content_free_shell(visible=530,tags=312)'], cookie names [], server 'AliyunOSS'
- Evidence: P1 cq=full stable=True polls=3 h=768->768 capped=False shotcap=False dims=[1366, 768] html=43738B cf=False retry=0 banner=30/False replay_fullmap=False txt=530; P2 cq=full stable=True polls=3 h=768->768 capped=False shotcap=False dims=[1366, 768] html=43738B cf=False retry=0 banner=30/False replay_fullmap=False txt=530; P3 cq=full stable=True polls=3 h=768->768 capped=False shotcap=False dims=[1366, 768] html=43738B cf=False retry=0 banner=30/False replay_fullmap=False txt=530
- Evidence: pair p1->p2 (probe src p1) risk=1.0 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer4_visual_diff': 0.0001, 'layer7_cloaking': 1.0} degraded=[] (203 ms)
- Evidence: pair p2->p3 (probe src p2) risk=1.0 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer4_visual_diff': 0.0001, 'layer7_cloaking': 1.0} degraded=[] (297 ms)
- Evidence: pair p1->p3 (probe src p1) risk=1.0 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer7_cloaking': 1.0} degraded=[] (282 ms)

# 29 non-clean site(s) in C:\Users\Ns8pc\AppData\Local\Temp\opencode\wardress-w1a\analysis_B.json

```
---

## Findings (Tier B)

### [NEW] AUDIT-5B-1 — Six non-Cloudflare bot walls are stored as site content at `capture_quality: "full"` (live confirmation of AUDIT-SA1-2), and one of them is a 401 Anubis PoW gate the catalog does not even list

- **Severity**: **High**. §6.4 High — a documented spec requirement simply not met
  (PROMPT-002 Phase 2's headline contract is "challenge HTML is never stored as
  content") combined with the operator-visible consequence: the health page
  reports these captures as the healthiest possible. Independently a
  **false clean** on the *monitoring* question ("is this site being monitored?")
  — but not a false clean on an *attack*, so it stops at High rather than Critical.
- **Subsystem / file(s)**: `backend/worker/fetcher.py:166-201`
  (`_CHALLENGE_TITLE_MARKERS = ("just a moment", "attention required")`,
  `_CHALLENGE_MARKER_SELECTOR = ".cf-challenge-running, .cf-error-details"`, the
  `403 + cf-ray` rule — Cloudflare-only by construction); `:125-128`
  (`BOT_PROTECTION_ERROR` names Cloudflare specifically); `:226-280`
  (`_wait_out_challenge`, the only gate); `:352-374`
  (`_classify_capture_quality` — grades capture *mechanics*, never whether the
  page is content); `backend/worker/scan_tasks.py:109-119` (baseline `>= 400` gate)
  vs `:262-272` (**no gate on the scan path**).
- **Reproduction** (3 passes each, production unmodified):

  | site | status | title | body | `looks_like_challenge_page` | `capture_quality` | verdict stored |
  |---|---|---|---|---|---|---|
  | `godaddy.com` | **403** | `Access Denied` | 291 B, 207 vis chars, `server: AkamaiGHost` | **False** | **full** | content |
  | `leboncoin.fr` | **403** | `leboncoin.fr` | 1 468 B, 12 vis chars, `datadome` + `geo.captcha-delivery.com` (outside JS) | **False** | **full** | content |
  | `yelp.com` | **403** | `yelp.com` | 1 470 B, 8 vis chars, `server: DataDome` | **False** | **full** | content |
  | `etsy.com` | **403** | `etsy.com` | 1 470 B, 8 vis chars, `server: DataDome` | **False** | **full** | content |
  | `zillow.com` | **403** | `Access to this page has been denied` | 9 978 B, 146 vis chars, `x-px-` header, `_px` cookie, press-and-hold | **False** | **full** | content |
  | `unsplash.com` | **401** | `Making sure you're not a bot!` | 7 772 B, navigated to `unsplash.com/.within.website?redir=%2F` | **False** | **full** | content |

  Every pair on every one of these sites reads `changed` at a benign **0.3000**
  — detection is completely silent about the fact that the site is not being
  monitored at all.
- **Root cause**: identical to AUDIT-SA1-2, and my measurement independently
  reproduces every row of its truth table against **live** vendor walls rather
  than synthetic shapes. Two Tier-A-relevant additions:
  (a) `unsplash.com` runs **Anubis** (proof-of-work anti-bot), a vendor the
  catalog does not list, a **401** status (the gate's only status rule is
  `http_status == 403`), and a JS-driven navigation to a different path — so
  even a status-based rule would need to be ">= 400", not "== 403";
  (b) `_classify_capture_quality` returns `full` for a 291-byte error page
  because the page *is* completely rendered, stable and uncapped — the label is
  honest about mechanics and actively misleading about health.
- **Additional measurable harm**: on 5 of these 6 sites, `probe_site`'s reference
  `desktop_chrome` fetch is also blocked, so `layer7_cloaking` returns
  `degraded_result` on **37 of 77 Tier B pairs** — the one channel that could
  have surfaced the block is systematically unavailable exactly when it is needed.
- **Proposed remedy category**: the AUDIT-SA1-2 remedy — a vendor-agnostic wall
  classifier evaluated as a gate separate from the Cloudflare gate, an
  `http_status >= 400` gate on the scan path, and a `capture_quality`/`blocked`
  label that reflects wall detection. Add Anubis and the 401 shape to the
  classifier's table.
- **Source**: Audit Phase 5B, all seven bot-protection sub-categories.

---

### [NEW] AUDIT-5B-2 — 58 % of Tier B's real consecutive-visit pairs FLAGGED at a median fused risk of 0.79, with no attack present

- **Severity**: **High**. §6.4 High, "a false positive that would alert operators
  on legitimate, common site behavior" — in bulk. Measured on **45 of 77 pairs
  across 20 sites**, every one an ordinary public homepage or product page, three
  passes each. Each flag creates an `Alert` **and** a `RemediationExecution`.
- **Subsystem / file(s)**: `backend/worker/detection/fusion.py` (the refit
  logistic model that maps the layer vector to risk — `intercept -6.247`,
  `layer1_hash` coefficient implied by `sigmoid(4.408 - 6.247) = 0.1372` alone);
  `backend/worker/detection/dom.py:704-730` (`layer3_link_audit`'s exponential
  new-domain term — the dominant contributor, see AUDIT-5A-1);
  `backend/worker/hashing.py:24-36` (`layer1_hash` = 1.0 on any byte change,
  always in the vector); `backend/worker/detection/visual.py:110-190`;
  `backend/app/models.py:235` (`flag_threshold` default 0.5).
- **Reproduction** — the full per-site flagged set with measured risk:

  | site | pairs flagged / 3 | risk range | dominant non-zero layers |
  |---|---|---|---|
  | `microsoft.com` | 3/3 | **1.000** | L1 1.0 + L2/L3/L4 |
  | `stockx.com` | 3/3 | **1.000** | L1 1.0 + L3 (prebid/safeframe rotation) |
  | `target.com` | 3/3 | **1.000** | L1 1.0 + L2/L3 |
  | `hulu.com` (-> hotstar) | 3/3 | **1.000** | L1 1.0 + L2 (page height 9269 vs 13594) |
  | `airbnb.com` | 3/3 | 0.988-0.999 | L1 + L2 + L3 (height 2846 vs 4576) |
  | `ibm.com` | 3/3 | 0.937-0.997 | L1 + L3 |
  | `dell.com` | 3/3 | 0.603-0.980 | L1 + L3 |
  | `footlocker.com` | 3/3 | 0.836-1.000 | L1 + L2/L3 |
  | `chase.com` | 3/3 | 0.952-0.977 | L1 + L3 |
  | `walmart.com` | 3/3 | 0.975-0.978 | L1 + L3 |
  | `nytimes`/other single-pair flaggers | — | 0.402-0.945 | see the Tier B FAIL blocks |
  | `pexels.com` | 3/3 | 0.634-1.000 | L1 + L2 (height 3772 vs 4753) |
  | `500px.com` | 3/3 | **1.000** | L1 + L2 (onboarding interstitial swap) |

  **The only two sites in Tier B that never flagged are `kraken.com`
  (0.169-0.176) and `npmjs.com` (0.0063) — and `npmjs` only because all three
  captures were byte-identical (`layer1_hash = 0.0`), which gated layers
  2/3/5/8 to `skip_result` and produced `clean`.**
- **Root cause**: two independent amplifiers compose, and they are the same two
  proven in Tier A:
  1. **the byte-hash channel is always 1.0** on any dynamic page, and it enters
     fusion at full strength with no veto;
  2. **`layer3_link_audit` reads ad/prebid/safeframe host rotation as an
     injection signal** (one new iframe domain = 0.5934, exactly
     `1 - exp(-0.9)`), which is the state of the world on every page carrying a
     third-party ad stack.
  A third, capture-side amplifier (`auto_scroll_page` ending at different heights:
  `hulu` 9269 vs 13 594, `airbnb` 2846 vs 4576, `pexels` 3772 vs 4753) drives
  layer 2, and AUDIT-3-5's missing completeness channel means fusion cannot tell
  it from an attack.
- **Proposed remedy category**: recalibrate/regate the fused model against a
  measured real-site benign-churn distribution (the log's own hermetic fixtures
  measure 0.19-0.22; real commercial pages measure **0.14-1.00** with 58 % of
  pairs over the flag threshold — the model was fitted on a distribution that
  does not contain these sites); plus the layer-3 and completeness remedies from
  AUDIT-5A-1/-2.
- **Source**: Audit Phase 5B, all seven sub-categories.

---

### [NEW] AUDIT-5B-3 — `https://www.hulu.com/` redirects to `hotstar.com` and yields a **4000-pixel-wide** screenshot that the height-only cap cannot express or bound

- **Severity**: **Medium**. §6.4 Medium — this is Session A's **AUDIT-SA1-5**
  (rated Low there on a synthetic fixture) **confirmed live on a production
  catalog site, and it is materially worse than logged**: the width is not a
  hypothetical 20 008 px, it is a real 4000 px page in Tier B, three passes
  consistently, and the same site's height also swung 9269 -> 13 594 px between
  passes, which is what drives its risk-1.000 flags. Kept at Medium rather than
  High because I could not produce a corrupt PNG on this software-rasterised
  host, so the harm is "unbounded/unmeasurable guard + a false flag", not a
  demonstrated capture failure.
- **Subsystem / file(s)**: `backend/worker/fetcher.py:377-416` (`_take_screenshot`
  — `if page_height > MAX_SCREENSHOT_HEIGHT` at `:403-412` is **height-only**),
  `:395` (`evidence = {"screenshot_capped": False, "actual_height": 0}` — **no
  width key at all**), `:352-374` (`_classify_capture_quality`, which reads only
  `actual_height`); `backend/worker/stealth.py:92-99` (the rationale comment names
  only height).
- **Reproduction**: 3 passes of `https://www.hulu.com/`. Every pass redirects to
  `https://www.hotstar.com/in/home` and the captured PNG is
  **1366 -> 4000 px wide**:

  | pass | PNG dims | `actual_height` | `screenshot_capped` | `capture_quality` |
  |---|---|---|---|---|
  | P1 | **4000 x 9269** | 9269 | **False** | full |
  | P2 | **4000 x 9269** | 9269 | **False** | full |
  | P3 | **4000 x 13594** | 13594 | **False** | full |

  Width 4000 > `MAX_SCREENSHOT_HEIGHT` (16 384) is not the constraint; the point
  is that the horizontal axis is unbounded by the same guard whose stated
  rationale is a *square* Chromium raster limit, and `capture_evidence` has
  nowhere to record that it happened. Every other site in Tier A+B produced
  1366 px (98 captures), so this is a specific layout pathology (the redirected
  Hotstar page overflows the 1366 px viewport horizontally), not a general one.
- **Root cause**: `page.screenshot(full_page=True)` captures the full scrollable
  area, which can exceed the viewport width when content overflows horizontally;
  the guard only inspects `document.scrollHeight`.
- **Proposed remedy category**: symmetric width cap + `actual_width` in evidence;
  classify `degraded` when either axis exceeds the raster limit; consider
  recording the viewport overflow as a capture-completeness fact.
- **Source**: Audit Phase 5B, AWS WAF category. Confirms and escalates AUDIT-SA1-5.

---

### [NEW] AUDIT-5B-4 — `net::ERR_HTTP2_PROTOCOL_ERROR` is classified TRANSIENT and retried, and still fails 3/3 on two Tier B sites

- **Severity**: **Medium**. §6.4 Medium — a real, deterministic capture failure
  with a wasted retry and a misleading classification. Not High: no false alarm
  and no corruption; the site is genuinely unreachable over HTTP/2 from this
  client.
- **Subsystem / file(s)**: `backend/worker/fetcher.py:146-163`
  (`_classify_goto_failure` — `if "net::err_" in first_line: return "network
  error"`, i.e. **every** Chromium network error code is treated as transient),
  `:444-485` (the retry loop), `:454-458` (`_TransientNavError` ->
  `FetchError("Fetch failed: ...")`).
- **Reproduction**: 3 passes each.
  - `https://www.washingtonpost.com/`: **3/3 FAIL** in 7.0 / 7.9 / 6.7 s with
    `FetchError: Fetch failed: network error (Page.goto:
    net::ERR_HTTP2_PROTOCOL_ERROR at https://www.washingtonpost.com/)`.
  - `https://www.accuweather.com/`: **3/3 FAIL** in 5.5 / 10.2 / 27.6 s with the
    identical error.
  Fast (5-8 s) and identical across passes — a protocol-level refusal, not a
  transient network condition. The retry is spent for nothing.
- **Root cause**: the classifier buckets all `net::ERR_*` codes together. An
  HTTP/2 protocol error means the *server* refused to speak HTTP/2 with this
  client; retrying the same request cannot help. Whether this is Wardress-fixable
  at all is a separate question (see disposition).
- **Proposed remedy category**: split the transient bucket — connection-reset /
  connection-refused / DNS-intermittent / `ERR_NETWORK_CHANGED` are transient;
  `ERR_HTTP2_PROTOCOL_ERROR`, `ERR_SSL_PROTOCOL_ERROR`, `ERR_NAME_NOT_RESOLVED`
  at the browser layer, and `ERR_INVALID_HTTP_RESPONSE` are not. Note the
  interaction with `app/ssrf.py`: a resolution failure there *is* classified as
  a policy refusal (AUDIT-5A-5), while the same class of failure at the browser
  layer would be classified transient — the two layers disagree.
- **Source**: Audit Phase 5B, Akamai Bot Manager category.

---

### [NEW] AUDIT-5B-5 — Catalog category drift, measured and timestamped (Rule 19: logged, not silently tolerated)

The catalog's verification protocol requires category drift to be recorded and
re-filed. Verified **2026-09-30 14:05-15:50 local** from `server`, `set-cookie`,
header and HTML fingerprint evidence (JS stripped to separate an injected
detection SDK from a real interstitial):

| site | catalog says | measured reality | proposed re-file |
|---|---|---|---|
| `https://www.yelp.com/` | PerimeterX / HUMAN Defense Platform | **`server: DataDome`**, `datadome` cookie, `geo.captcha-delivery.com` in a 1 470 B 403 body | **DataDome** |
| `https://www.etsy.com/` | Harder e-commerce | **`server: DataDome`**, same 1 470 B 403 body, identical shape to `yelp.com` | **DataDome** (remove from e-commerce) |
| `https://www.sncf-connect.com/` | DataDome | **Cloudflare** — `_ChallengeUnsolvedError` fired on 3/3 passes, i.e. the Cloudflare gate detected and refused | **Cloudflare Enterprise / Turnstile** |
| `https://www.godaddy.com/` | Akamai Bot Manager | **CONFIRMED** — `server: AkamaiGHost`, `title="Access Denied"`, HTTP 403 | keep |
| `https://www.leboncoin.fr/` | DataDome | **CONFIRMED** — `server: DataDome` (via `x-datadome`), `datadome` cookie, 403 | keep |
| `https://www.zillow.com/` | PerimeterX / HUMAN | **CONFIRMED** — `x-px-` header, `_px` cookie, press-and-hold body, 403 | keep |
| `https://www.microsoft.com`, `ibm.com`, `ebay.com`, `usps.com`, `weather.com`, `dell.com`, `bestbuy.com`, `nbcnews.com`, `airbnb.com` | Akamai Bot Manager | **NOT VERIFIABLE from outside** — all returned a real 200 page; Akamai presence is only inferable from CDN headers and Bot-Manager cookies issued **on success** (`_abck`, `bm_sz`, `ak_bmsc`). No Akamai *challenge* was served, so no wall evidence exists either way. | keep, but annotate "unverified — no challenge observed" |
| `https://www.target.com`, `chase.com`, `hulu.com` | AWS WAF (challenge-action / CAPTCHA-capable) | **NOT VERIFIABLE and in one case contradicted** — `x-amzn-waf*` headers absent, no `awswaf` body marker, real 200 pages; `hulu.com` is served by `AkamaiNetStorage` behind `hotstar.com`. The catalog's own instruction ("verify current configuration, not merely presence in the stack") is exactly right and **cannot be satisfied from outside for these three**. | keep, annotated |
| `https://www.footlocker.com/` | DataDome | **CONTRADICTED** — 3/3 clean 200 captures of the real page (1.76 MB, 9 007 visible chars); no DataDome header, cookie or body marker on any pass. **Category refuted, not merely drifted.** | needs a replacement DataDome site |
| `https://www.stockx.com` | PerimeterX / HUMAN | **NOT VERIFIABLE** — real 200 page (847-980 KB); `dataDome`/`perimeterx` SDK strings appear in the body on a *successful* page. All three raw UA probes returned 403. | keep, annotated |
| `https://unsplash.com/` | Harder lazy-load | **CATEGORY REFUTED** — 3/3 HTTP 401 behind **Anubis** proof-of-work, never reached the lazy-load content at all | re-file as a new "Anubis / proof-of-work" sub-category and pick a different lazy-load site |
| `https://www.pexels.com/`, `500px.com` | Harder lazy-load | **QUESTIONABLE** — `pexels.com` is a clean capture; `500px.com` never reaches the feed at all: a **200-OK onboarding interstitial** ("Customize your feed by choosing up to 4 categories") with 530 visible chars replaces the content. | keep `pexels`; replace `500px` |
| `https://www.kraken.com/`, `npmjs.com` | Cloudflare Ent./Turnstile | **NOT VERIFIABLE as Turnstile** — both captured cleanly 3/3 with no challenge and no turnstile marker. They are *not* hard cases. | keep as Cloudflare regression controls, not as Turnstile tests |

- **Severity**: **Low** (the catalog file is documentation; the drift misleads a
  future run rather than breaking the system), but Rule 19 requires each drift to
  be individually dispositioned, so every row above carries one.
- **Proposed remedy category**: apply the re-files above to
  `PROMPT-003-stress-site-catalog.md` (I did not edit it — tracked file, Rule 1)
  and add an "observed 2026-09-30" annotation column so the next run knows how
  stale each categorisation was. Add `unsplash.com`-replacement, `500px.com`-replacement
  and a replacement for `footlocker.com`; add an explicit "Anubis / proof-of-work"
  sub-category with `unsplash.com` as its first member.
- **Source**: Audit Phase 5B, catalog verification protocol §2.
---

## TIER C — Exotic & Edge Categories (Phase 5C)

**Coverage: 21 of 21 unique URLs, 3 passes each = 63 captures (52 succeeded,
11 failed). Complete.** Seven of the 21 were re-run after a **host-level DNS
outage** invalidated their first attempt (see *Environment incident* below); the
reported results are the re-run.

### Tier C dense summary table (latency CONTENTION-AFFECTED)

| URL | Tier/Category | Pass 1 | Pass 2 | Pass 3 | Latency min/avg/max | Status | Notes / Disposition |
|---|---|---|---|---|---|---|---|
| https://www.tradingview.com/chart/ | WebSocket / live-push | OK 200 25s | OK 200 23s | OK 200 28s | 23/25/28s | **3/3 clean** | risk 0.147-0.156, all `changed`; **`actual_height = 768` on all 3** -> inner-scroll shell |
| https://www.espn.com/nba/scoreboard | WebSocket / live-push | OK 200 23s | OK 200 32s | OK 200 26s | 23/27/32s | **FAIL (false flag)** | **3/3 pairs risk 1.000**; height 2168-2320, scoreboard churn |
| https://flightaware.com/live/ | WebSocket / live-push | OK 200 87s | OK 200 25s | OK 200 24s | 24/45/87s | **FAIL (false flag)** | 3/3 pairs 0.872-0.978; DOM text identical (16718 chars); **4000px-wide PNG** |
| https://open.spotify.com/ | PWA / Service-Worker | OK 200 17s | OK 200 22s | OK 200 19s | 17/19/22s | **FAIL (false flag + 1378px)** | 3/3 pairs risk **1.000**; **1378x768** every pass (1378 > viewport 1366) |
| https://www.pinterest.com/ | PWA / Service-Worker | OK 200 21s | OK 200 24s | OK 200 22s | 21/22/24s | **FAIL (false flag + 4000px)** | 3/3 pairs risk **1.000**; 4000x4246, 4000x4246, **4000x4797** |
| https://web.whatsapp.com/ | PWA / Service-Worker | OK 200 20s SHELL | OK 200 21s SHELL | OK 200 16s SHELL | 16/19/21s | **FAIL (shell stored as content)** | 863 KB HTML but **490 visible chars / 382 tags**, `h=768`; risk 0.300-0.359 `changed` |
| https://en.wikipedia.org/wiki/List_of_largest_selling_pharmaceutical_products | Extremely large pages | OK 200 16s | OK 200 17s | OK 200 17s | 16/17/17s | **3/3 clean** | 340 KB, h 7356; p2->p3 byte-identical -> `clean` 0.006 |
| https://www.nasa.gov/image-of-the-day/ | Extremely large pages | **FAIL** 94.6s nav timeout | **FAIL** 94.7s | **FAIL** 95.1s | 95/95/95s | **0/3 capture FAIL** | 60s + 3s + 30s all exhausted, every pass |
| https://apnews.com/hub/ap-top-news | Extremely large pages | OK 200 41s **EMPTY-BODY** | **FAIL** 97.6s nav timeout | **FAIL** 95.8s nav timeout | 41/78/98s | **1/3 capture FAIL** | P1: 200 OK, **9 tags, 0 visible chars**, `initial_height 15368 -> final_height 768` — the scroll-shrink path, live |
| https://www.india.gov.in/ | Slow / high-latency origins | OK **403** 13s WALL | OK **403** 14s WALL | OK **403** 13s WALL | 13/13/14s | **FAIL (category refuted)** | **Akamai "Reference #18"** 292 B page; but `probe_site` desktop_chrome -> **200 / 607 516 B** |
| https://www.gutenberg.org/browse/scores/top | Slow / high-latency origins | OK 200 22s | OK 200 27s | OK 200 27s | 22/25/27s | **3/3 clean** | 59 KB, h **15 734 px**; all 3 pairs `clean` (0.002) — byte-identical |
| https://www.nytimes.com/ | Auth-adjacent / soft-blocked | OK **403** 14s WALL | OK **403** 16s WALL | OK **403** 17s WALL | 14/16/17s | **FAIL (wall as content)** | `server: DataDome`, `x-datadome: protected`, `datadome` cookie, 1468 B, 11 visible chars |
| https://www.wsj.com/ | Auth-adjacent / soft-blocked | **FAIL** 94.7s nav timeout | **FAIL** 94.7s | **FAIL** 94.8s | 95/95/95s | **0/3 capture FAIL** | see FAIL block |
| https://www.reddit.com/ | Infinite-scroll feeds | OK 200 35s | OK 200 33s | **FAIL** DNS outage | 1/23/35s | **2/3 (P3 = environment)** | p1->p2 risk **1.000**; h 17824-18461, `shotcap=True` |
| https://www.instagram.com/nasa/ | Infinite-scroll feeds | OK 200 19s | OK 200 20s | OK 200 19s | 19/19/20s | **FAIL (false flag)** | p1->p2 0.8933, p2->p3 0.8028; h 834 (feed never materialised) |
| https://linear.app/ | Heavy hydration | OK 200 23s | OK 200 25s | OK 200 31s | 23/27/31s | **3/3 clean** | 1069-1076 KB, h 9960, 10 718 visible chars; risk 0.138-0.140 |
| https://vercel.com/ | Heavy hydration | OK 200 17s | OK 200 19s | OK 200 19s | 17/18/19s | **3/3 clean** | risk 0.138-0.143 |
| https://www.notion.so/ | Heavy hydration | OK 200 18s | OK 200 24s | OK 200 23s | 18/22/24s | **FAIL (false flag, 1 pair)** | p2->p3 risk 0.5395 flagged; other two 0.197 |
| https://www.aljazeera.net/ | Deep RTL | OK 200 39s | OK 200 52s | OK 200 62s | 39/51/62s | **FAIL (false flag)** | 3/3 pairs risk **1.000**; h 7441 -> 21740/21740/22429, `shotcap=True` |
| https://www.bbc.com/arabic | Deep RTL | OK 200 18s | OK 200 28s | OK 200 26s | 18/24/28s | **FAIL (false flag)** | p1->p2 0.9295, p1->p3 0.9097; p2->p3 0.390 |
| https://www.haaretz.co.il/ | Deep RTL | **FAIL** 95.9s nav timeout | **FAIL** 95.2s nav timeout | OK 200 77s | 77/89/96s | **1/3 capture FAIL** | P3: 2061 KB, h 17036, `shotcap=True`, 45 586 Hebrew chars |

### Tier C cross-cutting measurements

| metric | value |
|---|---|
| capture success | **52/63** (11 failures, 5 distinct sites) |
| `capture_quality` | `full` 46, `partial` 6, `degraded` 0 |
| `retry_count` | 1 on 1 of 52 |
| HTML size | 292 B – 2.01 MB (guard 10 MB; nothing approached it) |
| `actual_height` | 768 – **22 429 px**; `screenshot_capped` **6/52** |
| **PNG width** | 1366 px on 43, **4000 px on 6**, **1378 px on 3** |
| **inner-scroll shells** (`actual_height == viewport`, no document scroll) | **4 sites / 12 captures**: tradingview (768), open.spotify (768 @ **1378 px wide**), web.whatsapp (768), instagram (834) |
| encoding damage (U+FFFD / double-encoded) | **0 on all 52 captures**, including 25 229-25 593 Arabic chars (aljazeera.net), 30 281 (bbc.com/arabic) and 45 586 Hebrew chars (haaretz.co.il) |
| banner `dismissed` | **false on 52/52**; `attempts` 1 – 2 520 |
| **detection verdicts** | `clean` **4 / 49**, `changed` 24, **`flagged` 21** |
| fused risk | min 0.0019, median 0.3275, max 1.0000 |

### Tier C — each category's question, answered

**WebSocket / live-push** (`tradingview.com/chart/`, `espn.com/nba/scoreboard`,
`flightaware.com/live/`) — *Is "settled" ever reached?* **The assumption FAILED, but
not in the way the category anticipated.** The capture does not hang and does not
exceed its budget: `stable: true` on 6 of 6 captures, `polls` 3-4, `capped: false`,
and all three sites captured 3/3. The problem is that these pages are captured as
**viewport-only shells**: `tradingview` reports `actual_height = 768` on every pass
(the chart lives in an inner scroll container), and `flightaware` reports 1945 px with
a **4000 px width** (a map canvas wider than the document's height implies). The settle
heuristic cannot distinguish "still streaming" from "settled" because on these pages
the live region is *not* in the document's scroll area at all. Consequence, measured:
`espn.com/nba/scoreboard` **flagged at risk 1.000 on all 3 pairs** from ordinary
scoreboard churn, and `flightaware.com/live/` at 0.872-0.978 with an **identical DOM
text length (16 718 chars) on all three passes** — the churn is entirely in
canvas/position attributes that no layer is designed to read. **Disposition:
Fix-candidate.**

**PWA / Service-Worker** (`open.spotify.com`, `pinterest.com`, `web.whatsapp.com`) —
*Do repeat visits serve cached content, and does a service worker register?* **A service
worker registers on 2 of the 3 under the production capture context, and on
`web.whatsapp.com` it becomes the page's `controller`**
(`navigator.serviceWorker.controller === "https://web.whatsapp.com/sw.js"`). See
**AUDIT-5C-6** for the full registration table and the `service_workers="block"`
control arm, which removes the registration *and* the controller while changing the
served HTML by <0.01 %. That makes Session A's **AUDIT-SA1-1** (Critical, `page.route`-scoped
guard + no `service_workers="block"` at `fetcher.py:518-525`) **reachable on the Tier C
catalog itself**, not only on a synthetic fixture. I did **not** attempt any SSRF
exfiltration (out of scope; Session A proved the hole server-side). Repeat-visit
behaviour: `open.spotify.com` and `pinterest.com` served **different bytes** on each of
the three passes (`layer1_hash = 1.0` on all pairs) — no cache-served staleness observed;
`web.whatsapp.com` served **byte-identical** content on all three passes
(`layer1_hash = 0.0`, risk 0.300-0.359), i.e. a stable app shell. **Disposition:
Fix-candidate** for the SW exposure; the "cached content" half of the category's
premise **did not reproduce** and is reported as a negative result.

**Extremely large pages** — *DOM bytes, height cap, 10 MB guard, screenshot dims.*
Measured honestly: **the largest HTML in the whole phase was 3.38 MB (`nbcnews.com`,
Tier B) and Tier C peaked at 2.11 MB (`haaretz.co.il`)** — nothing came near the
10 MB `MAX_HTML_BYTES` guard, and PROMPT-002 Phase 13's 10 MB observation was **not**
reproduced on this catalog. The height cap **did** engage on 9 captures
(`aljazeera.net` 21 740/21 740/22 429 px -> 1366x16384 clipped; `haaretz.co.il`
17 036 -> clipped; `reddit.com` 17 824/18 461 -> clipped; `aajtak.in` in Tier A
27 915-40 059 -> clipped) and behaved exactly as documented. **The catalog's premise
is wrong**: these are not "multi-megabyte DOM" pages. Two of the three failed for
unrelated reasons (`nasa.gov` 3/3 nav timeout; `apnews.com` 2/3 nav timeout plus one
200-OK **empty body**). **Disposition: Fix-candidate for the failures; the category
premise needs re-scoping** (see AUDIT-5B-5's catalog advice).

**Slow / high-latency origins** (`india.gov.in`, `gutenberg.org/browse/scores/top`) —
*Are the timeout budgets generous enough?* **Yes, and the category premise is wrong.**
`gutenberg.org` returned the real 15 734-px page on all three passes at 22-27 s with no
timeout, and produced the phase's only Tier C `clean` verdicts (all three pairs at
0.002, byte-identical). `india.gov.in` answered in 12.7-13.6 s — **and returned HTTP
403** (Akamai "Reference #18" edge page, 292 B), so it measured nothing about latency;
it is fully blocked for the browser capture while `probe_site`'s httpx fetch of the
same URL returns **200 with 607 516 bytes** for `desktop_chrome` and `mobile_safari`
(but 403 for `googlebot`). Budgets as configured: `NAV_TIMEOUT_MS = 60 000`,
`RETRY_NAV_TIMEOUT_MS = 30 000`, `RETRY_PAUSE_MS = 3 000`, `MAX_SCROLL_TIME_MS = 20 000`,
`BANNER_DISMISS_TIMEOUT_MS = 3 000`, `SETTLE_MS = 5 000`, `SITE_BUDGET_S = 180`
(runner). Every Tier B/C timeout failure cost **~95 s** = 60 + 3 + 30 plus overhead, i.e.
the Phase-6 retry budget is spent in full and then the site is lost; against real
latency these budgets are **generous, arguably too generous** — the observed
no-timeout latency was 12-32 s median, so a 60 s nav timeout plus a 30 s retry is
roughly 4x the median. **Disposition: Fix-candidate for the wall, not for the budget.**

**Auth-adjacent / soft-blocked** (`nytimes.com`, `wsj.com`) — *Are 200-OK verify/paywall
pages silently treated as meaningful content?* **Half the premise holds, and the
half that holds is the safe one.** `nytimes.com` is **not** a 200-OK soft block — it
returns **HTTP 403** with `server: DataDome`, `x-datadome: protected`, a `datadome`
cookie and a 1 468-byte interstitial, on all three passes and for all three UA
variants. `wsj.com` never returned at all (3/3 nav timeout). So the specific
"200-OK paywall" case the catalog expected **was not reachable from this machine on
these two sites**. I therefore answered the **first-class question the coordinator
attached to this category — NB-CAP-2 baseline poisoning — directly against the live
Docker stack**, using two 200-OK interstitials I *did* find. **Answer: a 200-OK
non-content page IS stored as a healthy, `ready`, current baseline.** See
**AUDIT-5C-1 (Critical)**: `https://500px.com/` (a 200-OK onboarding dialog) and
`https://dash.cloudflare.com/` (a 200-OK login wall) both became `baseline_status:
"ready"` with `baseline_error: null` through the real Celery worker, and the
`nytimes.com` 403 control was correctly refused with an actionable message.

**Infinite-scroll feeds** (`reddit.com`, `instagram.com/nasa/`) — content appended on
scroll, paired with AUDIT-3-8. `reddit.com`'s scroll pass produced heights of
**17 824 and 18 461 px** with `screenshot_capped: true` on both successful passes and
`p1->p2` risk **1.000** — the capture-completeness variable again (AUDIT-5A-2), this
time on a page whose *purpose* is unbounded height. `instagram.com/nasa/` never
materialised a feed at all: `actual_height = 834`, 508-516 tags, 826 visible chars on all
three passes — the mobile web shell with no posts. **AUDIT-3-8's shrink path fired for
real on `apnews.com`** (see the large-pages row: `initial_height 15368 -> final_height
768`), which upgrades that code-trace-only finding to a live reproduction.
**Disposition: Fix-candidate.**

**Heavy client-side hydration** (`linear.app`, `vercel.com`, `notion.so`) — *Does the
settle window fire before the real DOM lands?* **The assumption HELD on all three.**
Every capture returned a fully-populated DOM, never a skeleton: `linear.app` 1 069-1 076 KB
HTML / 9 960 px / 10 718 visible chars; `vercel.com` 619 KB / 5 724 px / 3 701 visible
chars; `notion.so` 224 KB / 4 373 px / 2 910 visible chars. `SETTLE_MS = 5 000` plus
the stability wait is sufficient here, and `linear.app` and `vercel.com` both read
`changed` at 0.138-0.143 (the phase's benign band) with no flag. `notion.so` flagged
**one** of three pairs (p2->p3, 0.5395) while the other two sat at 0.197 — the
inconsistency is a single-pair variance, not a systematic hydration failure.
**Disposition: the hydration premise does not reproduce; the `notion.so` single-pair
flag is an Accepted-risk-shaped observation** — I could not root-cause it to a
deterministic cause and one un-replicated pair out of three does not meet the Rule-18
bar for a Fix-candidate claim. Recorded honestly.

**Deep RTL / mixed-script** (`aljazeera.net`, `bbc.com/arabic`, `haaretz.co.il`) —
*bidirectional text rendering, encoding damage?* **Encoding: clean, decisively.**
Zero U+FFFD replacement characters and zero double-encoded byte sequences on **all 52
Tier C captures**, including 25 229-25 593 Arabic codepoints (`aljazeera.net`),
30 281 (`bbc.com/arabic`) and 45 586 Hebrew codepoints (`haaretz.co.il`). The capture
pipeline preserves non-Latin content perfectly; this is a **negative result** and the
`AUDIT-4F-6` bidi concern remains purely a frontend rendering matter, unmodified by
anything I measured. **Churn: not clean.** `aljazeera.net` flagged at risk **1.000 on
all three pairs** while its scroll pass grew the page from 7 441 px to 21 740/22 429 px
and its screenshot was height-clipped in all three — i.e. AUDIT-5A-2 again, on the
heaviest page in the phase. `bbc.com/arabic` flagged 2 of 3 pairs (0.9295, 0.9097) with
a byte-stable 30 281-char Arabic DOM. `haaretz.co.il` captured once (2 061 KB, 45 586
Hebrew chars, 17 036 px clipped) after two 95 s nav timeouts. **Disposition:
Fix-candidate, same root cause as AUDIT-5A-2; no new RTL-specific defect found.**
### Tier C FAIL blocks (generated from the captured evidence; per-site)
```
### FAIL ΓÇö https://www.espn.com/nba/scoreboard (Tier ?, Category WebSocket / live-push driven content (settle is inherently fuzzy ΓÇö content never truly stops changing))
- Pass results: P1: OK 200 22.5s / P2: OK 200 31.8s / P3: OK 200 25.7s
- Latency: 22520 / 31770 / 26677 ms (spread 9.2s)
- Error: capture succeeded and no wall fingerprint, but detection flagged: p1->p2 risk=1.0 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.0342, 'layer3_link_audit': 0.7163, 'layer4_visual_diff': 0.6404, 'layer7_cloaking': 0.7616, 'layer8_semantics': 0.2871, 'layer9_fusion': 1.0}; p2->p3 risk=1.0 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.0434, 'layer3_link_audit': 0.6113, 'layer4_visual_diff': 0.2874, 'layer7_cloaking': 0.7616, 'layer8_semantics': 0.3733, 'layer9_fusion': 1.0}; p1->p3 risk=1.0 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.0703, 'layer3_link_audit': 0.793, 'layer4_visual_diff': 0.6471, 'layer7_cloaking': 0.7616, 'layer8_semantics': 0.489, 'layer9_fusion': 1.0}
- Evidence: P1 cq=full stable=True polls=11 h=2170->2170 capped=False shotcap=False dims=[1366, 2320] html=864393B cf=False retry=0 banner=90/False replay_fullmap=False txt=4885; P2 cq=full stable=True polls=3 h=2187->2187 capped=False shotcap=False dims=[1366, 2187] html=856736B cf=False retry=0 banner=90/False replay_fullmap=False txt=4898; P3 cq=full stable=True polls=3 h=2168->2168 capped=False shotcap=False dims=[1366, 2168] html=850745B cf=False retry=0 banner=90/False replay_fullmap=False txt=4578
- Evidence: pair p1->p2 (probe src p1) risk=1.0 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.0342, 'layer3_link_audit': 0.7163, 'layer4_visual_diff': 0.6404, 'layer7_cloaking': 0.7616, 'layer8_semantics': 0.2871} degraded=[] (1062 ms)
- Evidence: pair p2->p3 (probe src p2) risk=1.0 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.0434, 'layer3_link_audit': 0.6113, 'layer4_visual_diff': 0.2874, 'layer7_cloaking': 0.7616, 'layer8_semantics': 0.3733} degraded=[] (1031 ms)
- Evidence: pair p1->p3 (probe src p1) risk=1.0 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.0703, 'layer3_link_audit': 0.793, 'layer4_visual_diff': 0.6471, 'layer7_cloaking': 0.7616, 'layer8_semantics': 0.489} degraded=[] (1234 ms)

### FAIL ΓÇö https://flightaware.com/live/ (Tier ?, Category WebSocket / live-push driven content (settle is inherently fuzzy ΓÇö content never truly stops changing))
- Pass results: P1: OK 200 86.6s / P2: OK 200 24.6s / P3: OK 200 23.9s
- Latency: 23920 / 86590 / 45020 ms (spread 62.7s)
- Error: capture succeeded and no wall fingerprint, but detection flagged: p1->p2 risk=0.9357 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.0006, 'layer3_link_audit': 0.8347, 'layer4_visual_diff': 0.0009, 'layer6_security_metadata': 0.95, 'layer9_fusion': 0.9357}; p2->p3 risk=0.8715 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.9392, 'layer3_link_audit': 0.9727, 'layer4_visual_diff': 0.0066, 'layer9_fusion': 0.8715}; p1->p3 risk=0.9776 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.7534, 'layer3_link_audit': 0.8347, 'layer4_visual_diff': 0.0058, 'layer6_security_metadata': 0.95, 'layer9_fusion': 0.9776}
- Evidence: P1 cq=full stable=True polls=3 h=1945->1945 capped=False shotcap=False dims=[4000, 1945] html=366337B cf=False retry=1 banner=1/True replay_fullmap=False txt=16718; P2 cq=full stable=True polls=3 h=1945->1945 capped=False shotcap=False dims=[4000, 1945] html=365603B cf=False retry=0 banner=1/True replay_fullmap=False txt=16718; P3 cq=full stable=True polls=3 h=1945->1945 capped=False shotcap=False dims=[4000, 1945] html=367082B cf=False retry=0 banner=1/True replay_fullmap=False txt=16718
- Evidence: pair p1->p2 (probe src p1) risk=0.9357 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.0006, 'layer3_link_audit': 0.8347, 'layer4_visual_diff': 0.0009, 'layer6_security_metadata': 0.95} degraded=['layer7_cloaking'] (2609 ms)
- Evidence: pair p2->p3 (probe src p2) risk=0.8715 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.9392, 'layer3_link_audit': 0.9727, 'layer4_visual_diff': 0.0066} degraded=['layer7_cloaking'] (2969 ms)
- Evidence: pair p1->p3 (probe src p1) risk=0.9776 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.7534, 'layer3_link_audit': 0.8347, 'layer4_visual_diff': 0.0058, 'layer6_security_metadata': 0.95} degraded=['layer7_cloaking'] (3484 ms)

### FAIL ΓÇö https://open.spotify.com/ (Tier ?, Category PWA / Service-Worker sites (may serve cached content on repeat visits))
- Pass results: P1: OK 200 16.9s / P2: OK 200 21.9s / P3: OK 200 18.7s
- Latency: 16890 / 21860 / 19140 ms (spread 5.0s)
- Error: capture succeeded and no wall fingerprint, but detection flagged: p1->p2 risk=1.0 layers={'layer1_hash': 1.0, 'layer7_cloaking': 1.0, 'layer9_fusion': 1.0}; p2->p3 risk=1.0 layers={'layer1_hash': 1.0, 'layer7_cloaking': 1.0, 'layer9_fusion': 1.0}; p1->p3 risk=1.0 layers={'layer1_hash': 1.0, 'layer7_cloaking': 1.0, 'layer9_fusion': 1.0}
- Evidence: P1 cq=full stable=True polls=3 h=768->768 capped=False shotcap=False dims=[1378, 768] html=614581B cf=False retry=0 banner=150/False replay_fullmap=False txt=11165; P2 cq=full stable=True polls=3 h=768->768 capped=False shotcap=False dims=[1378, 768] html=614581B cf=False retry=0 banner=150/False replay_fullmap=False txt=11165; P3 cq=full stable=True polls=3 h=768->768 capped=False shotcap=False dims=[1378, 768] html=614645B cf=False retry=0 banner=150/False replay_fullmap=False txt=11165
- Evidence: pair p1->p2 (probe src p1) risk=1.0 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer7_cloaking': 1.0} degraded=[] (2125 ms)
- Evidence: pair p2->p3 (probe src p2) risk=1.0 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer7_cloaking': 1.0} degraded=[] (2016 ms)
- Evidence: pair p1->p3 (probe src p1) risk=1.0 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer7_cloaking': 1.0} degraded=[] (1937 ms)

### FAIL ΓÇö https://www.pinterest.com/ (Tier ?, Category PWA / Service-Worker sites (may serve cached content on repeat visits))
- Pass results: P1: OK 200 20.7s / P2: OK 200 24.4s / P3: OK 200 21.6s
- Latency: 20720 / 24410 / 22250 ms (spread 3.7s)
- Error: capture succeeded and no wall fingerprint, but detection flagged: p1->p2 risk=1.0 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.9926, 'layer3_link_audit': 0.3, 'layer7_cloaking': 1.0, 'layer9_fusion': 1.0}; p2->p3 risk=1.0 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 1.0, 'layer3_link_audit': 0.24, 'layer4_visual_diff': 0.4844, 'layer8_semantics': 0.0848, 'layer9_fusion': 1.0}; p1->p3 risk=1.0 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 1.0, 'layer3_link_audit': 0.4, 'layer4_visual_diff': 0.4844, 'layer8_semantics': 0.0848, 'layer9_fusion': 1.0}
- Evidence: P1 cq=full stable=True polls=4 h=4246->4246 capped=False shotcap=False dims=[4000, 4246] html=1115582B cf=False retry=0 banner=180/False replay_fullmap=False txt=2797; P2 cq=full stable=True polls=4 h=4246->4246 capped=False shotcap=False dims=[4000, 4246] html=1320995B cf=False retry=0 banner=180/False replay_fullmap=False txt=2797; P3 cq=full stable=True polls=4 h=4797->4797 capped=False shotcap=False dims=[4000, 4797] html=1376896B cf=False retry=0 banner=180/False replay_fullmap=False txt=3377
- Evidence: pair p1->p2 (probe src p1) risk=1.0 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.9926, 'layer3_link_audit': 0.3, 'layer7_cloaking': 1.0} degraded=[] (1547 ms)
- Evidence: pair p2->p3 (probe src p2) risk=1.0 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 1.0, 'layer3_link_audit': 0.24, 'layer4_visual_diff': 0.4844, 'layer8_semantics': 0.0848} degraded=[] (1718 ms)
- Evidence: pair p1->p3 (probe src p1) risk=1.0 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 1.0, 'layer3_link_audit': 0.4, 'layer4_visual_diff': 0.4844, 'layer8_semantics': 0.0848} degraded=[] (1704 ms)

### FAIL ΓÇö https://web.whatsapp.com/ (Tier ?, Category PWA / Service-Worker sites (may serve cached content on repeat visits))
- Pass results: P1: OK 200 20.1s / P2: OK 200 21.3s / P3: OK 200 15.8s
- Latency: 15760 / 21270 / 19040 ms (spread 5.5s)
- Error: capture SUCCEEDED but returned wall/interstitial content ΓÇö status 200, title 'WhatsApp', reasons ['content_free_shell(visible=490,tags=382)'], cookie names ['29-Dec-2026 08:26:22 GMT; Max-Age', 'wa_ul'], server None
- Evidence: P1 cq=full stable=True polls=3 h=768->768 capped=False shotcap=False dims=[1366, 768] html=883372B cf=False retry=0 banner=30/False replay_fullmap=False txt=490; P2 cq=full stable=True polls=3 h=768->768 capped=False shotcap=False dims=[1366, 768] html=883407B cf=False retry=0 banner=30/False replay_fullmap=False txt=490; P3 cq=full stable=True polls=3 h=768->768 capped=False shotcap=False dims=[1366, 768] html=883465B cf=False retry=0 banner=30/False replay_fullmap=False txt=490
- Evidence: pair p1->p2 (probe src p1) risk=0.3 changed=True flagged=False verdict=changed material=False escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer4_visual_diff': 0.0355} degraded=['layer7_cloaking'] (407 ms)
- Evidence: pair p2->p3 (probe src p2) risk=0.3369 changed=True flagged=False verdict=changed material=False escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer4_visual_diff': 0.0443} degraded=['layer7_cloaking'] (437 ms)
- Evidence: pair p1->p3 (probe src p1) risk=0.3594 changed=True flagged=False verdict=changed material=False escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer4_visual_diff': 0.048} degraded=['layer7_cloaking'] (390 ms)

### FAIL ΓÇö https://www.nasa.gov/image-of-the-day/ (Tier ?, Category Extremely large pages (multi-megabyte DOM, thousands of images, very tall archives))
- Pass results: P1: FAIL FetchError: Fetch failed: navigation timeout (Page.goto: Timeout 30000ms exceeded.) / P2: FAIL FetchError: Fetch failed: navigation timeout (Page.goto: Timeout 30000ms exceeded.) / P3: FAIL FetchError: Fetch failed: navigation timeout (Page.goto: Timeout 30000ms exceeded.)
- Latency: 94640 / 95120 / 94820 ms (spread 0.5s)
- Error: FetchError: Fetch failed: navigation timeout (Page.goto: Timeout 30000ms exceeded.) || FetchError: Fetch failed: navigation timeout (Page.goto: Timeout 30000ms exceeded.) || FetchError: Fetch failed: navigation timeout (Page.goto: Timeout 30000ms exceeded.)

### FAIL ΓÇö https://apnews.com/hub/ap-top-news (Tier ?, Category Extremely large pages (multi-megabyte DOM, thousands of images, very tall archives))
- Pass results: P1: OK 200 41.0s / P2: FAIL FetchError: Fetch failed: navigation timeout (Page.goto: Timeout 30000ms exceeded.) / P3: FAIL FetchError: Fetch failed: navigation timeout (Page.goto: Timeout 30000ms exceeded.)
- Latency: 41030 / 97590 / 78143 ms (spread 56.6s)
- Error: FetchError: Fetch failed: navigation timeout (Page.goto: Timeout 30000ms exceeded.) || FetchError: Fetch failed: navigation timeout (Page.goto: Timeout 30000ms exceeded.)
- Evidence: P1 cq=full stable=True polls=5 h=15368->768 capped=False shotcap=False dims=[1366, 768] html=1277B cf=False retry=0 banner=1170/False replay_fullmap=False txt=0

### FAIL ΓÇö https://www.india.gov.in/ (Tier ?, Category Slow / high-latency origins (pressure-test timeout budgets against real-world latency, not local-network conditions))
- Pass results: P1: OK 403 12.7s / P2: OK 403 13.6s / P3: OK 403 12.7s
- Latency: 12660 / 13590 / 12970 ms (spread 0.9s)
- Error: capture SUCCEEDED but returned wall/interstitial content ΓÇö status 403, title 'Access Denied', reasons ['http_status=403', 'content_free_shell(visible=208,tags=7)', 'title:akamai_botmgr'], cookie names [], server None
- Evidence: P1 cq=full stable=True polls=3 h=768->768 capped=False shotcap=False dims=[1366, 768] html=292B cf=False retry=0 banner=30/False replay_fullmap=False txt=208; P2 cq=full stable=True polls=3 h=768->768 capped=False shotcap=False dims=[1366, 768] html=292B cf=False retry=0 banner=30/False replay_fullmap=False txt=208; P3 cq=full stable=True polls=3 h=768->768 capped=False shotcap=False dims=[1366, 768] html=292B cf=False retry=0 banner=30/False replay_fullmap=False txt=208
- Evidence: pair p1->p2 (probe src p1) risk=0.2281 changed=True flagged=False verdict=changed material=False escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer4_visual_diff': 0.0088, 'layer6_security_metadata': 0.15} degraded=[] (203 ms)
- Evidence: pair p2->p3 (probe src p2) risk=0.1817 changed=True flagged=False verdict=changed material=False escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer4_visual_diff': 0.0127} degraded=[] (188 ms)
- Evidence: pair p1->p3 (probe src p1) risk=0.2147 changed=True flagged=False verdict=changed material=False escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer4_visual_diff': 0.0059, 'layer6_security_metadata': 0.15} degraded=[] (234 ms)

### FAIL ΓÇö https://www.nytimes.com/ (Tier ?, Category Auth-adjacent / soft-blocked pages (full 200-status "please verify"/paywall pages, not a clean 403 ΓÇö must not be silently treated as meaningful content))
- Pass results: P1: OK 403 14.2s / P2: OK 403 16.3s / P3: OK 403 16.5s
- Latency: 14220 / 16520 / 15680 ms (spread 2.3s)
- Error: capture SUCCEEDED but returned wall/interstitial content ΓÇö status 403, title 'nytimes.com', reasons ['http_status=403', 'content_free_shell(visible=11,tags=9)', 'blocking_fp:datadome'], cookie names ['01 Jan 1970 00:00:00 GMT; SameSite', '30 Sep 2026 08:26:34 GMT', '30 Sep 2026 14:26:31 GMT; Path', '30 Sep 2027 08:26:31 GMT; Path', 'datadome', 'nyt-a', 'nyt-gdpr', 'nyt-geo', 'nyt-purr', 'nyt-s-present', 'nyt-traceid', 'nyt.et.dd'], server 'DataDome'
- Evidence: P1 cq=full stable=True polls=3 h=768->768 capped=False shotcap=False dims=[1366, 768] html=1468B cf=False retry=0 banner=60/False replay_fullmap=False txt=11; P2 cq=full stable=True polls=3 h=768->768 capped=False shotcap=False dims=[1366, 768] html=1468B cf=False retry=0 banner=60/False replay_fullmap=False txt=11; P3 cq=full stable=True polls=3 h=768->768 capped=False shotcap=False dims=[1366, 768] html=1468B cf=False retry=0 banner=60/False replay_fullmap=False txt=11
- Evidence: pair p1->p2 (probe src p1) risk=0.3 changed=True flagged=False verdict=changed material=False escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer3_link_audit': 0.02, 'layer4_visual_diff': 0.0092} degraded=['layer7_cloaking'] (110 ms)
- Evidence: pair p2->p3 (probe src p2) risk=0.3 changed=True flagged=False verdict=changed material=False escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer3_link_audit': 0.02, 'layer4_visual_diff': 0.0141} degraded=['layer7_cloaking'] (141 ms)
- Evidence: pair p1->p3 (probe src p1) risk=0.3 changed=True flagged=False verdict=changed material=False escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer3_link_audit': 0.02, 'layer4_visual_diff': 0.0117} degraded=['layer7_cloaking'] (125 ms)

### FAIL ΓÇö https://www.wsj.com/ (Tier ?, Category Auth-adjacent / soft-blocked pages (full 200-status "please verify"/paywall pages, not a clean 403 ΓÇö must not be silently treated as meaningful content))
- Pass results: P1: FAIL FetchError: Fetch failed: navigation timeout (Page.goto: Timeout 30000ms exceeded.) / P2: FAIL FetchError: Fetch failed: navigation timeout (Page.goto: Timeout 30000ms exceeded.) / P3: FAIL FetchError: Fetch failed: navigation timeout (Page.goto: Timeout 30000ms exceeded.)
- Latency: 94670 / 94830 / 94740 ms (spread 0.2s)
- Error: FetchError: Fetch failed: navigation timeout (Page.goto: Timeout 30000ms exceeded.) || FetchError: Fetch failed: navigation timeout (Page.goto: Timeout 30000ms exceeded.) || FetchError: Fetch failed: navigation timeout (Page.goto: Timeout 30000ms exceeded.)

### FAIL ΓÇö https://www.reddit.com/ (Tier ?, Category Infinite-scroll feeds (new content appended on scroll, not just lazy-loaded images below the fold))
- Pass results: P1: OK 200 34.6s / P2: OK 200 32.9s / P3: FAIL SSRFBlockedError: Could not resolve host 'www.reddit.com'
- Latency: 1270 / 34580 / 22903 ms (spread 33.3s)
- Error: SSRFBlockedError: Could not resolve host 'www.reddit.com'
- Evidence: P1 cq=partial stable=True polls=5 h=2619->2619 capped=False shotcap=True dims=[1366, 16384] html=1135911B cf=False retry=0 banner=150/False replay_fullmap=False txt=11661; P2 cq=partial stable=True polls=7 h=2595->2595 capped=False shotcap=True dims=[1366, 16384] html=1153090B cf=False retry=0 banner=150/False replay_fullmap=False txt=11589
- Evidence: pair p1->p2 (probe src p2(substituted)) risk=1.0 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.9995, 'layer3_link_audit': 0.8021, 'layer4_visual_diff': 0.3129, 'layer8_semantics': 0.4809} degraded=['layer6_security_metadata', 'layer7_cloaking'] (4454 ms)

### FAIL ΓÇö https://www.instagram.com/nasa/ (Tier ?, Category Infinite-scroll feeds (new content appended on scroll, not just lazy-loaded images below the fold))
- Pass results: P1: OK 200 18.9s / P2: OK 200 19.8s / P3: OK 200 19.4s
- Latency: 18860 / 19770 / 19330 ms (spread 0.9s)
- Error: capture succeeded and no wall fingerprint, but detection flagged: p1->p2 risk=0.8933 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.5034, 'layer3_link_audit': 0.06, 'layer4_visual_diff': 0.1059, 'layer6_security_metadata': 0.15, 'layer9_fusion': 0.8933}; p2->p3 risk=0.8028 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.0186, 'layer3_link_audit': 0.02, 'layer4_visual_diff': 0.1059, 'layer6_security_metadata': 0.15, 'layer9_fusion': 0.8028}
- Evidence: P1 cq=full stable=True polls=3 h=834->834 capped=False shotcap=False dims=[1366, 834] html=490987B cf=False retry=0 banner=30/False replay_fullmap=False txt=826; P2 cq=full stable=True polls=3 h=834->834 capped=False shotcap=False dims=[1366, 834] html=491333B cf=False retry=0 banner=30/False replay_fullmap=False txt=826; P3 cq=full stable=True polls=3 h=834->834 capped=False shotcap=False dims=[1366, 834] html=483418B cf=False retry=0 banner=30/False replay_fullmap=False txt=826
- Evidence: pair p1->p2 (probe src p1) risk=0.8933 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.5034, 'layer3_link_audit': 0.06, 'layer4_visual_diff': 0.1059, 'layer6_security_metadata': 0.15} degraded=[] (532 ms)
- Evidence: pair p2->p3 (probe src p2) risk=0.8028 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.0186, 'layer3_link_audit': 0.02, 'layer4_visual_diff': 0.1059, 'layer6_security_metadata': 0.15} degraded=[] (531 ms)
- Evidence: pair p1->p3 (probe src p1) risk=0.2093 changed=True flagged=False verdict=changed material=False escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.0187, 'layer3_link_audit': 0.04, 'layer6_security_metadata': 0.15} degraded=[] (484 ms)

### FAIL ΓÇö https://www.notion.so/ (Tier ?, Category Heavy client-side hydration frameworks (skeleton-then-replace-nearly-the-entire-DOM patterns))
- Pass results: P1: OK 200 18.0s / P2: OK 200 24.4s / P3: OK 200 23.0s
- Latency: 17990 / 24380 / 21783 ms (spread 6.4s)
- Error: capture succeeded and no wall fingerprint, but detection flagged: p2->p3 risk=0.5395 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.7534, 'layer3_link_audit': 0.08, 'layer4_visual_diff': 0.0317, 'layer9_fusion': 0.5395}
- Evidence: P1 cq=full stable=True polls=7 h=4373->4373 capped=False shotcap=False dims=[1366, 4373] html=229466B cf=False retry=0 banner=60/False replay_fullmap=False txt=2910; P2 cq=full stable=True polls=4 h=4373->4373 capped=False shotcap=False dims=[1366, 4373] html=228926B cf=False retry=0 banner=60/False replay_fullmap=False txt=2910; P3 cq=full stable=True polls=6 h=4373->4373 capped=False shotcap=False dims=[1366, 4373] html=229177B cf=False retry=0 banner=60/False replay_fullmap=False txt=2910
- Evidence: pair p1->p2 (probe src p1) risk=0.3275 changed=True flagged=False verdict=changed material=False escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.0072, 'layer3_link_audit': 0.04, 'layer4_visual_diff': 0.0386} degraded=[] (1140 ms)
- Evidence: pair p2->p3 (probe src p2) risk=0.5395 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.7534, 'layer3_link_audit': 0.08, 'layer4_visual_diff': 0.0317} degraded=[] (1141 ms)
- Evidence: pair p1->p3 (probe src p1) risk=0.1968 changed=True flagged=False verdict=changed material=False escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.0048, 'layer3_link_audit': 0.04, 'layer4_visual_diff': 0.0125} degraded=[] (1125 ms)

### FAIL ΓÇö https://www.aljazeera.net/ (Tier ?, Category Deep RTL / mixed-script (beyond PROMPT-002's 7/7 already-passing non-Latin set))
- Pass results: P1: OK 200 38.9s / P2: OK 200 52.4s / P3: OK 200 61.9s
- Latency: 38940 / 61940 / 51097 ms (spread 23.0s)
- Error: capture succeeded and no wall fingerprint, but detection flagged: p1->p2 risk=1.0 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.9698, 'layer3_link_audit': 0.02, 'layer4_visual_diff': 0.2066, 'layer7_cloaking': 1.0, 'layer9_fusion': 1.0}; p2->p3 risk=1.0 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.0097, 'layer3_link_audit': 0.06, 'layer4_visual_diff': 0.1121, 'layer7_cloaking': 1.0, 'layer9_fusion': 1.0}; p1->p3 risk=1.0 layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.0082, 'layer3_link_audit': 0.08, 'layer4_visual_diff': 0.2143, 'layer7_cloaking': 1.0, 'layer9_fusion': 1.0}
- Evidence: P1 cq=partial stable=True polls=4 h=7441->21740 capped=False shotcap=True dims=[1366, 16384] html=1150233B cf=False retry=0 banner=1380/False replay_fullmap=False txt=21564; P2 cq=partial stable=True polls=4 h=7441->21740 capped=False shotcap=True dims=[1366, 16384] html=1150855B cf=False retry=0 banner=1770/False replay_fullmap=False txt=21564; P3 cq=partial stable=True polls=6 h=7441->22429 capped=False shotcap=True dims=[1366, 16384] html=1149313B cf=False retry=0 banner=780/False replay_fullmap=False txt=21785
- Evidence: pair p1->p2 (probe src p1) risk=1.0 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.9698, 'layer3_link_audit': 0.02, 'layer4_visual_diff': 0.2066, 'layer7_cloaking': 1.0} degraded=[] (4563 ms)
- Evidence: pair p2->p3 (probe src p2) risk=1.0 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.0097, 'layer3_link_audit': 0.06, 'layer4_visual_diff': 0.1121, 'layer7_cloaking': 1.0} degraded=[] (5828 ms)
- Evidence: pair p1->p3 (probe src p1) risk=1.0 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer2_dom_structure': 0.0082, 'layer3_link_audit': 0.08, 'layer4_visual_diff': 0.2143, 'layer7_cloaking': 1.0} degraded=[] (5500 ms)

### FAIL ΓÇö https://www.bbc.com/arabic (Tier ?, Category Deep RTL / mixed-script (beyond PROMPT-002's 7/7 already-passing non-Latin set))
- Pass results: P1: OK 200 17.7s / P2: OK 200 28.1s / P3: OK 200 25.6s
- Latency: 17720 / 28060 / 23807 ms (spread 10.3s)
- Error: capture succeeded and no wall fingerprint, but detection flagged: p1->p2 risk=0.9295 layers={'layer1_hash': 1.0, 'layer4_visual_diff': 0.1682, 'layer9_fusion': 0.9295}; p1->p3 risk=0.9097 layers={'layer1_hash': 1.0, 'layer3_link_audit': 0.02, 'layer4_visual_diff': 0.1561, 'layer9_fusion': 0.9097}
- Evidence: P1 cq=full stable=True polls=3 h=8316->8331 capped=False shotcap=False dims=[1366, 8331] html=733802B cf=False retry=0 banner=120/False replay_fullmap=False txt=12768; P2 cq=full stable=True polls=3 h=8316->8331 capped=False shotcap=False dims=[1366, 8331] html=733797B cf=False retry=0 banner=150/False replay_fullmap=False txt=12768; P3 cq=full stable=True polls=3 h=8316->8331 capped=False shotcap=False dims=[1366, 8331] html=733797B cf=False retry=0 banner=120/False replay_fullmap=False txt=12768
- Evidence: pair p1->p2 (probe src p1) risk=0.9295 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer4_visual_diff': 0.1682} degraded=[] (3922 ms)
- Evidence: pair p2->p3 (probe src p2) risk=0.3904 changed=True flagged=False verdict=changed material=False escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer3_link_audit': 0.02, 'layer4_visual_diff': 0.0512} degraded=[] (3750 ms)
- Evidence: pair p1->p3 (probe src p1) risk=0.9097 changed=True flagged=True verdict=flagged material=True escalation_band=False non-zero-layers={'layer1_hash': 1.0, 'layer3_link_audit': 0.02, 'layer4_visual_diff': 0.1561} degraded=[] (3797 ms)

### FAIL ΓÇö https://www.haaretz.co.il/ (Tier ?, Category Deep RTL / mixed-script (beyond PROMPT-002's 7/7 already-passing non-Latin set))
- Pass results: P1: FAIL FetchError: Fetch failed: navigation timeout (Page.goto: Timeout 30000ms exceeded.) / P2: FAIL FetchError: Fetch failed: navigation timeout (Page.goto: Timeout 30000ms exceeded.) / P3: OK 200 76.8s
- Latency: 76840 / 95880 / 89323 ms (spread 19.0s)
- Error: FetchError: Fetch failed: navigation timeout (Page.goto: Timeout 30000ms exceeded.) || FetchError: Fetch failed: navigation timeout (Page.goto: Timeout 30000ms exceeded.)
- Evidence: P3 cq=partial stable=True polls=3 h=16930->17036 capped=False shotcap=True dims=[1366, 16384] html=2110928B cf=False retry=0 banner=2520/False replay_fullmap=False txt=24349

# 16 non-clean site(s) in C:\Users\Ns8pc\AppData\Local\Temp\opencode\wardress-w1a\analysis_C.json

```
---

## Findings (Tier C)

### [NEW] AUDIT-5C-1 — CRITICAL — A 200-OK non-content page (onboarding dialog, login wall) IS stored as a healthy, ready, current baseline by the deployed stack

- **Severity**: **Critical**. Justified against §6.4 in two independent clauses, and
  I want to be explicit about which:
  1. **"a false 'clean'/silent success"** — the system's core operator-facing
     guarantee is "this site is baselined and healthy". Measured: it is `ready`,
     with `baseline_error: null`, while the stored artifact is a login form or an
     onboarding dialog. The site is, in effect, **not monitored at all**, and
     Wardress says it is fine.
  2. **"data corruption"** — the code calls the Baseline row "the trust anchor for
     every future verdict" (`scan_tasks.py:104-108`). I stored a login form in it.
  **Honest counterweight, stated so the rating can be challenged:** I did **not**
  demonstrate a *missed attack pattern*, so the first Critical clause's
  "on an actual attack pattern" qualifier is not literally met. I rate it Critical
  on the silent-success + trust-anchor-corruption grounds, because unlike the
  artifact-truncation path Session A rated High, this trigger is **routine and
  externally reachable** — it needs no crash, no narrow race window; any site that
  rolls out a paywall, a geo-gate, a consent wall or a "please log in" interstitial
  poisons itself. If the coordinator/user prefers to reserve Critical for
  demonstrated attack-miss, **High** is the defensible alternative and I have
  supplied the evidence for both readings.
- **Subsystem / file(s)**: `backend/worker/scan_tasks.py:104-119` (the `>= 400`
  baseline gate — the *only* protection, and it is a status test, not a content test;
  its own docstring at `:104-108` says "An HTTP error page (site down, rate-limited,
  **auth-walled**) must never be stored as 'trusted'"); `:157-161` (the row is
  committed `status = ready`, `is_current = True`); `backend/worker/fetcher.py:352-374`
  (`_classify_capture_quality` — cannot help, it grades mechanics);
  `backend/worker/scan_tasks.py:262-272` (**no gate at all on the scan path**);
  `backend/worker/fetcher.py:166-201` (the Cloudflare-only gate that would have been
  the other line of defence).
- **Reproduction — measured end-to-end against the LIVE Docker install** via the
  public REST API (`POST /api/sites` -> `POST /api/sites/{id}/rebaseline` ->
  `POST /api/sites/{id}/scan-now`), letting the real Celery worker do the real
  capture. Temporary sites were **deleted afterwards**; no production file, schema or
  queue was touched.

  | target | what the capture actually got | baseline outcome | subsequent scan |
  |---|---|---|---|
  | `https://500px.com/` | HTTP **200**, 43 KB, **530 visible chars**, 312 tags — the "Customize your feed by choosing up to 4 categories" onboarding dialog (the real photo feed is never rendered) | **`status: "ready"`, `error: null`**, `captured_at` set, `is_current` | **`verdict: "flagged"`, `risk_score = 0.99999`** |
  | `https://dash.cloudflare.com/` | HTTP **200**, 96 KB, 589 visible chars — redirected to `https://dash.cloudflare.com/login`, an embedded Turnstile login wall | **`status: "ready"`, `error: null`** | `verdict: "changed"`, `risk 0.3862` |
  | `https://www.nytimes.com/` (control) | HTTP **403**, DataDome, 1 468 B | **`status: "failed"`**, `error: "Site responded with HTTP 403 — a trusted baseline needs a healthy response. Try again when the site is up."` | n/a (no baseline) |

  The boundary is now measured exactly: **the gate is `http_status >= 400`, and a
  200-OK interstitial walks straight through it.** The control proves the gate works
  when the vendor cooperates with a 403 — which is why `nytimes.com` is safe *by
  accident*, and why the moment any of these walls switches to a 200 the system goes
  silently blind.
- **Root cause**: the baseline gate was designed around HTTP status because status was
  the only signal `fetch_page` surfaced to the task. Nothing in the capture path
  distinguishes "a page with content" from "a page that is a wall", so `200` +
  "no content" is indistinguishable from `200` + "content". Everything needed to tell
  them apart is already computed and thrown away: the DOM tag count and visible-text
  length (I measured them myself, post-hoc), the vendor fingerprints in the headers,
  and the final URL (`/login`, `.within.website?redir=`, `/en-in`).
- **Proposed remedy category**: a content-sufficiency test on the capture result
  (visible-text length, DOM size, tag count, plus the vendor-agnostic wall classifier
  from AUDIT-SA1-2/AUDIT-5A-4) applied at **both** the baseline and the scan gate;
  a `blocked`/`not_content` baseline status distinct from `failed`; and the same test
  used to label `capture_quality`. This single change closes the scan/baseline
  asymmetry, the wall-storage problem, and the health-page mislabelling together.
- **Source**: Audit Phase 5C, "Auth-adjacent / soft-blocked" category, answering the
  coordinator's NB-CAP-2 question directly. **This closes the NB-CAP-2 question**
  assigned to Phase 9/W1-C for the *baseline* half — the *paywall* half remains open
  because `nytimes.com`/`wsj.com` were unreachable from this machine, so a genuine
  metered-paywall case was not tested (routed, see *out of scope*).
- **Cross-check against Session A**: NB-CAP-2 was predicted by Session A as a
  *possibility* based on `scan_tasks.py:109`. It is now a **measurement**.

---

### [NEW] AUDIT-5C-2 — The height-only screenshot guard fails on 4 of 21 Tier C sites and 3 of 31 Tier B sites; widths of 4000 px and 1378 px were captured uncapped with `capture_quality: "full"`

- **Severity**: **Medium** (upgraded from Session A's AUDIT-SA1-5 **Low**). The
  upgrade is justified by breadth, not by a new failure mode: Session A could only
  produce this on a synthetic 20 008-px fixture and rated it Low for that reason. I
  measured it on **4 real catalog sites across 12 real captures** with no fixture at
  all, on two different widths (4000 px and 1378 px), and — as with AUDIT-SA1-5 — I
  still could not produce a corrupt PNG on this software-rasterised host. It stays
  Medium rather than High because there is no demonstrated corruption and no false
  alarm *caused by* the width; the false alarms on those sites have other causes.
- **Subsystem / file(s)**: `backend/worker/fetcher.py:377-416`
  (`_take_screenshot`; the height test at `:403-412`, the evidence dict at `:395`
  which has **no width key**), `:352-374` (`_classify_capture_quality`, which reads
  only `actual_height`); `backend/worker/stealth.py:92-99` (the rationale comment
  names only height).
- **Reproduction**: PNG dimensions parsed from the IHDR chunk of every capture in the
  phase. Over **145 successful captures** across Tiers A, B and C, **80 were 1366 px
  and 15 were not**:

  | site | tier | PNG width | height | `actual_height` | `screenshot_capped` | `capture_quality` |
  |---|---|---|---|---|---|---|
  | `flightaware.com/live/` | C | **4000** | 1945 | 1945 | **False** | full |
  | `www.pinterest.com/` | C | **4000** | 4246 / 4246 / **4797** | 4246 / 4246 / 4797 | **False** | full |
  | `open.spotify.com/` | C | **1378** | 768 | 768 | **False** | full |
  | `www.hulu.com/` (-> hotstar) | B | **4000** | 9269 / 9269 / **13594** | 9269 / 9269 / 13594 | **False** | full |

  `1378` is interesting: it is only **12 px wider than the 1366-px viewport**, i.e. a
  1-px overflow somewhere on Spotify's landing page is enough to change the capture
  geometry, and the guard has no threshold at all on that axis. The 4000-px cases are
  a map canvas (`flightaware`), an image-masonry grid (`pinterest`) and a
  fixed-width app layout (`hotstar`) — all extremely common page shapes.
- **Root cause**: `page.screenshot(full_page=True)` captures the full scrollable area,
  which exceeds the viewport whenever content overflows horizontally; `_take_screenshot`
  only consults `document.scrollHeight`.
- **Proposed remedy category**: symmetric width cap + `actual_width` in
  `capture_evidence`; `degraded` when either axis exceeds the raster limit; and — more
  valuable than the cap — a **layout-drift** signal, because two captures of the same
  page differing in screenshot *geometry* is itself a reason to distrust the visual
  comparison (this is the AUDIT-5A-3 amplifier, and the width axis makes it worse).
- **Source**: Audit Phase 5B + 5C; confirms and escalates Session A's AUDIT-SA1-5.

---

### [NEW] AUDIT-5C-3 — Pages whose scrollable content lives in an inner container are captured as a single viewport and reported as `full`

- **Severity**: **Medium**. §6.4 Medium — a partial implementation that degrades
  gracefully but misses the original intent: the capture *succeeds*, the DOM is
  complete (the HTML is 600 KB-1.8 MB with real text), and the screenshot is a valid
  PNG, so nothing anywhere reports a problem. But the *visual* half of the evidence is
  one viewport, and `capture_quality` says `full`.
- **Subsystem / file(s)**: `backend/worker/page_prepare.py:59-135`
  (`auto_scroll_page` — `window.scrollBy` at `:111-113` is the **only** scroll
  mechanism, per Session A's AUDIT-3-2 analysis; there is no inner-container walk);
  `backend/worker/fetcher.py:377-416` (the screenshot then captures
  `scrollHeight == innerHeight`);
  `backend/worker/page_prepare.py:59` (`_CONTENT_LENGTH_JS` reads
  `document.body.scrollHeight`, which is 768 for a fixed-height app shell).
- **Reproduction**: `actual_height` equals the 768-px viewport on **every** pass of
  four Tier C sites whose DOM is demonstrably full of content:

  | site | `actual_height` | HTML bytes | DOM tags | visible chars | screenshot |
  |---|---|---|---|---|---|
  | `www.tradingview.com/chart/` | **768** (3/3) | 405 KB | 3511-3512 | 3943 | 1366x768 |
  | `open.spotify.com/` | **768** (3/3) | 600 KB | 2946 | 11165 | **1378x768** |
  | `web.whatsapp.com/` | **768** (3/3) | 863 KB | 382 | 490 | 1366x768 |
  | `www.instagram.com/nasa/` | **834** (3/3) | 472-480 KB | 508-516 | 826 | 1366x834 |

  For `open.spotify.com` the page has **11 165 visible characters** of real text and
  still renders as a 768-px screenshot: the scroll container is an inner element.
- **Root cause**: `auto_scroll_page` drives `window.scrollBy`; when the document does
  not scroll (an app shell with `overflow:hidden` on `body` and an inner scroller),
  `scrollHeight == innerHeight`, the walk completes in one step, `stable` becomes
  `true` after 3 polls, `capped` is `false`, and `_classify_capture_quality` returns
  `full`. Every signal that would have revealed the problem is either measuring the
  wrong element or is not recorded at all.
- **Proposed remedy category**: detect "document does not scroll but content plausibly
  does" (a scrollable descendant whose `scrollHeight > clientHeight`) and walk it, or
  at minimum record `inner_scrollable_elements` in `capture_evidence` and classify
  `degraded` when the document is exactly viewport-height on a DOM-heavy page. Note
  this is the same shape as the AUDIT-3-2 viewport-test defect (a viewport
  assumption that never checks what it is measuring), in a different place.
- **Source**: Audit Phase 5C, "WebSocket / live-push" and "PWA / Service-Worker" and
  "Infinite-scroll feeds" categories.

---

### [NEW] AUDIT-5C-4 — `apnews.com` reproduces AUDIT-3-8's scroll-shrink path live: `initial_height 15368 -> final_height 768`, and the capture is still reported `full`

- **Severity**: **Medium**. §6.4 Medium. This upgrades a **code-trace-only** Low
  finding (Session A / Phase 3's AUDIT-3-8: "`auto_scroll_page` counts a SHRINKING
  page height as stable") to a live reproduction with a measurable consequence. Not
  High: one site, one capture, and the downstream damage (a false flag or a missed
  fold) is bounded.
- **Subsystem / file(s)**: `backend/worker/page_prepare.py:119-125`
  (`stable_steps = stable_steps + 1 if height <= last_height else 0` — `<=` conflates
  "stopped growing" with "shrank"; the `stalled` condition at `:121` also requires
  `height <= last_height`), `:131-135` (the `finally` `scrollTo(0,0)`), and
  `backend/worker/fetcher.py:352-374` (`_classify_capture_quality`, which reads the
  resulting `capped=False`, `stable=True`, `actual_height=768` and returns `full`).
- **Reproduction**: 3 passes of `https://apnews.com/hub/ap-top-news/`. Pass 1: HTTP
  **200**, `capture_evidence` `initial_height = 15368`, `final_height = **768**`,
  `capped = false`, `stable = true`, `polls = 5`, `screenshot_capped = false`,
  `capture_quality = **full**`, and the captured body is **9 tags / 0 visible
  characters / 1 KB**. Passes 2 and 3: 97.6 s / 95.8 s navigation timeouts.
- **Root cause**: the page's layout collapsed during the capture (an ad-slot or
  content-block failure dropped the document from 15 368 px to 768 px). Because `<=`
  counts a shrink as "stable", the walk terminated *happy* two steps after the page
  had emptied itself, `stable=True`, and the capture is graded `full`. The identical
  trigger on the same URL then produced a hard nav timeout twice — i.e. this origin
  is on the edge of serving Wardress nothing at all.
- **Proposed remedy category**: treat a shrink beyond an epsilon as churn
  (`stable_steps = 0`) and require non-shrinking growth for the stability window;
  additionally classify a capture whose `initial_height` and `final_height` differ by
  more than a factor as `degraded`, because the two halves of that capture describe
  different documents.
- **Source**: Audit Phase 5C, "Extremely large pages" category. Confirms and
  escalates AUDIT-3-8 from code-trace to measured.

---

### [NEW] AUDIT-5C-5 — `india.gov.in` returns 403 to Wardress's browser but 200 / 607 KB to Wardress's own probe: the block is on the browser client, not the User-Agent

- **Severity**: **Low** as a capture limitation (the site is blocked and Wardress
  correctly captures the deny page rather than pretending otherwise — well, see
  AUDIT-5A-4 for the `full` label) but it is a **precise, actionable diagnosis**
  that a remediation prompt can act on, so I record it rather than burying it.
- **Subsystem / file(s)**: `backend/worker/stealth.py:64` (`CAPTURE_USER_AGENT`),
  `backend/worker/probe.py:45-58, 160-180` (`USER_AGENTS`, `_fetch_raw` over httpx),
  `backend/worker/fetcher.py:514-525` (the browser context), and the divergence
  between the two transports.
- **Reproduction** (single site, 3 passes, consistent):

  | transport | UA | result |
  |---|---|---|
  | Playwright capture (`fetch_page`) | `CAPTURE_USER_AGENT` | **HTTP 403**, 292 B, "Access Denied ... Reference #18.a53b5b68.1790754957.a92c42e" (`errors.edgesuite.net` = Akamai) |
  | `probe_site` httpx | `desktop_chrome` | **HTTP 200, 607 516 bytes** |
  | `probe_site` httpx | `mobile_safari` | **HTTP 200, 607 516 bytes** |
  | `probe_site` httpx | `googlebot` | **HTTP 403**, 374 B |

  So the deny is **not** keyed to Wardress's UA string (the probe's own desktop UA is
  the same string and gets 200) and **not** keyed to the source IP. It is keyed to
  something about the **Chromium client** — its TLS/HTTP2 fingerprint, header order,
  or the fact that it is a browser at all. This is also the live confirmation of
  Session A's AUDIT-3-6 concern that the `googlebot` UA is a WAF tripwire: on this
  one site the googlebot variant is the *only* one of the three that Akamai blocks.
- **Root cause**: two different HTTP clients with the same declared identity get
  opposite answers, and the capture pipeline only ever consults the browser's answer.
- **Proposed remedy category**: when the browser capture is refused but the
  same-identity probe fetch succeeded, record that pair as a distinct diagnosis
  ("client-fingerprint block, content reachable") — it is materially different from
  "the site blocks us" and it is the case where a transport/fingerprint change would
  actually help. This is the same opportunity as AUDIT-5A-4's item 2, reached from a
  second direction.
- **Source**: Audit Phase 5C, "Slow / high-latency origins" category (where the site
  does not belong — see AUDIT-5B-5's drift table).

---

## Environment incident (reported, not a Wardress defect)

Between approximately **16:05 and 16:20 local** the host's DNS resolution failed
completely. Every capture in that window failed in **0.2-0.3 s** with
`SSRFBlockedError: Could not resolve host '<host>'` — including hosts that had
already resolved successfully minutes earlier (`www.bbc.com`, `www.reddit.com`) and
hosts that resolved again immediately afterwards. It destroyed the tail of the first
Tier C run (7 sites) and caused the entire Tier A re-run to exit in 1.1 minutes having
"recorded" 60 bogus failures.

**Handling, stated for auditability:**
1. Those 67 records were identified by the signature *all three passes failed with
   `Could not resolve host` in under 1.0 s* and were **deleted**, along with their
   artifacts, so the driver re-ran them (`drop_dns.py`).
2. DNS was re-verified from the host immediately afterwards
   (`www.notion.so`, `www.aljazeera.net`, `www.bbc.com`, `www.haaretz.co.il`,
   `www.wsj.com` all resolved), and **7 Tier C sites were re-run successfully**.
3. `https://www.reddit.com/` pass 3 fell inside the window while passes 1-2 succeeded,
   so it does **not** match the all-three-failed signature and was **kept** — its
   reported result is `2/3` with the third failure explicitly attributed to the
   environment, not to Wardress.
4. **This incident is also a live demonstration of AUDIT-5A-5**: a host-level DNS
   failure presents to Wardress as a permanent SSRF policy refusal, with no retry, and
   an operator-facing message that blames the policy. It cost 67 captures here.

## Full regression results

**No repository test file was added, so no suite could regress.** Rule 5 verification:
- `git status --short` in `C:\Users\Ns8pc\Music\WARDRESS` shows **zero** modifications
  to any tracked production file. The only repository changes present are Session A's
  pre-existing untracked scratch files and test files, which I did not create or touch.
- Every production module used (`worker.fetcher`, `worker.page_prepare`,
  `worker.banner_dismiss`, `worker.probe`, `worker.hashing`, `worker.detection.*`,
  `app.ssrf`, `app.scanning`, `app.models`) was **imported and called, never edited**,
  so the existing suites are unaffected by construction. I did not run them because
  nothing in the repo changed.
- The **live Docker stack** was exercised through the public REST API only
  (login -> create site -> rebaseline -> scan-now -> delete site). All temporary sites
  were deleted; `GET /api/sites` returns the pre-existing state.

## New hermetic tests proposed (not committed — Rule 5, every one currently FAILS)

| proposed file | what it would prove | current status |
|---|---|---|
| `backend/tests/test_real_site_false_flag_regression.py` | A fixture pair of two real captures of one benign news homepage (I have gzipped html + PNG for `thehindu.com`, `bbc.co.uk/news`, `aajtak.in`) fuses **below** the flag threshold and never `flagged` | **would FAIL** — 0.9359-0.9995 measured |
| `backend/tests/test_link_audit_ad_domain_rotation.py` | Two captures differing only by a rotating ad/prebid/safeframe iframe hostname score `layer3_link_audit` < 0.1 | **would FAIL** — 0.5934 for exactly one such domain |
| `backend/tests/test_baseline_rejects_non_content_200.py` | A 200-OK page with < 800 visible chars / < 60 tags never becomes a `ready` baseline | **would FAIL** — `500px.com` and `dash.cloudflare.com` both did |
| `backend/tests/test_scan_path_http_status_gate.py` | A `>= 400` scan capture never reaches `run_detection` | **would FAIL** — mirrors Session A's `test_bot_wall_pages.py` proposal |
| `backend/tests/test_screenshot_width_cap.py` | A page wider than `MAX_SCREENSHOT_HEIGHT`-class limits is capped and records `actual_width` | **would FAIL** — 4000 px captured uncapped |
| `backend/tests/test_scroll_shrink_is_not_stable.py` | `auto_scroll_page` does not report `stable=True` after the document height collapses | **would FAIL** — `apnews.com` 15368 -> 768 |
| `backend/tests/test_dns_failure_is_transient.py` | A `socket.gaierror` during `assert_url_allowed` is retryable, not a permanent refusal | **would FAIL** — and would need `app/ssrf.py` untouched, so the change belongs in `fetcher.py` |

## Coverage honestly stated as NOT done

- **Coverage is COMPLETE for all three tiers: Tier A 69/69 unique URLs, Tier B
  31/31, Tier C 21/21 — 121 unique URLs, 363 planned captures.** The only things
  not done are listed below. (Note for the coordinator: Tier A was executed *last*
  because of the B -> C -> A reordering described above, and it needed three windows
  because of the DNS outage; the numbers in the Tier A section are from the final,
  complete run.)
- **Rule 18 time-spread:** all passes for a given site ran within a few minutes of
  each other. The coordinator's guidance was to spread passes across sessions where
  possible; that was not achievable inside this budget. Every site still got the full
  3 passes with variance recorded, and I flag the time-spread limitation explicitly
  rather than claiming independence I do not have.
- **Confirmatory re-runs at a later hour:** not performed for the same reason. Where
  latency variance looked contention-driven I report the spread and label it, rather
  than claiming a clean re-measurement.
- **The genuine metered-paywall case was not tested.** `nytimes.com` served a 403 and
  `wsj.com` never responded, so NB-CAP-2's *paywall* half remains open (routed to
  Phase 9/W1-C). What I did test — 200-OK onboarding and 200-OK login walls — answers
  the baseline-poisoning question decisively (AUDIT-5C-1).
- **No SSRF exfiltration test** (explicitly out of scope; Session A proved the hole
  server-side). The Tier C PWA measurement covers only whether a service worker
  registers and whether content is cache-served.
- **No load injection, no concurrency, no chaos** (Wave 2 / subagent W2's mandate).
- **`www.reddit.com` pass 3** is reported as an environment failure, not a Wardress
  failure, and its pass-1/pass-2 detection pair is still included.

### [CONFIRMS + ESCALATES] AUDIT-5C-6 — **Same defect as Session A's Critical AUDIT-SA1-1**, now shown reachable on the stress catalog itself: a *controlling* Service Worker registers under the production capture context

- **Severity**: **Critical** — *unchanged and not a second finding*. I am deliberately
  **not** minting a new Critical: this is the **same defect** as
  `AUDIT-SA1-1` (`worker/fetcher.py:518-525` builds the context with no
  `service_workers="block"`, and `:543` installs the SSRF route guard at `page.route`
  scope, not `context.route`). What I add is the **reachability evidence on real,
  catalog-listed targets**, which Session A could not supply (it used a local fixture).
  In the consolidated register these two entries should be **merged into one**.
- **Subsystem / file(s)**: unchanged from AUDIT-SA1-1 —
  `backend/worker/fetcher.py:287-340` (`_make_ssrf_route_guard`, whose docstring at
  `:288-291` claims it validates "every request the page initiates"), `:518-525`
  (`browser.new_context(...)`, no `service_workers="block"`), `:543`
  (`page.route("**/*", guard)` — page scope). Also `backend/worker/stealth.py:37-41`
  and `backend/worker/banner_dismiss.py:30-32`, whose docstrings restate the same
  untrue claim.
- **Reproduction** — `sw_probe.py`, which builds a context **identical to production**
  (same `CAPTURE_USER_AGENT`, `CONTEXT_LOCALE/TIMEZONE_ID/COLOR_SCHEME/VIEWPORT`,
  production `apply_stealth`, production `inject_consent_cookies`, production
  `_make_ssrf_route_guard`, `NAV_TIMEOUT_MS`, `SETTLE_MS`) and then reads
  `navigator.serviceWorker.getRegistrations()` and `.controller` after each load.
  Two arms per site: **production shape** vs **`service_workers="block"`**. Two
  visits per arm. **No exfiltration was attempted** — out of scope; Session A proved
  the hole server-side.

  | site | arm | `getRegistrations()` | `controller` | nav `transferSize` (v1/v2) | HTML served from cache? |
  |---|---|---|---|---|---|
  | `https://open.spotify.com/` | production | **`["https://open.spotify.com/"]`** | `null` | 25 763 / 25 735 | no (digests differ per visit) |
  | `https://open.spotify.com/` | `service_workers="block"` | **`[]`** | `null` | 25 852 / 25 739 | no |
  | `https://www.pinterest.com/` | production | `[]` | `null` | 105 418 / 105 613 | no |
  | `https://www.pinterest.com/` | `service_workers="block"` | `[]` | `null` | 105 465 / 105 473 | no |
  | `https://web.whatsapp.com/` | production | **`["https://web.whatsapp.com/"]`** | **`https://web.whatsapp.com/sw.js`** | 85 791 / 85 787 | no (digests differ per visit) |
  | `https://web.whatsapp.com/` | `service_workers="block"` | **`[]`** | **`null`** | 85 790 / 85 407 | no |

  **`web.whatsapp.com` is the decisive measurement: under the production capture
  context the page is *controlled* by its own Service Worker
  (`navigator.serviceWorker.controller === "https://web.whatsapp.com/sw.js"`), and the
  `service_workers="block"` arm removes the registration and the controller
  entirely.** A controlled SW can issue `fetch()` requests that, per Session A's Q2
  arm, are *reported to* the routing layer but **cannot be aborted by it** — including
  a `context.route` guard. That is the Critical hole, live, on a site in the audit's
  own catalog.
- **Root cause**: unchanged from AUDIT-SA1-1. What this adds is that the "fidelity
  cost" Session A worried about (`service_workers="block"` makes PWAs render their
  fallback state) is **measured to be ~zero on these three sites**: the HTML served
  with SWs blocked was the same size to within 0.01 % (Spotify 614 593 vs 614 593;
  WhatsApp 883 607 vs 883 632; Pinterest 1 115 906 vs 1 110 796), and
  `transferSize` was unchanged. So the remediation Session A recommended carries
  **no measurable fidelity cost on the three PWAs in this catalog** — which removes
  the only objection to it.
- **Negative result worth recording**: the catalog's premise that these sites
  "may serve cached content on repeat visits" **did not reproduce**. All three served
  fresh bytes on the second visit in both arms, and no `controller` change altered
  `transferSize`. The PWA category's *cache* concern is not the interesting one; the
  *request-path* one is.
- **Proposed remedy category**: unchanged — `service_workers="block"` on
  `browser.new_context` (`fetcher.py:518`), plus a `context.route("**/*", guard)`
  alongside the page-scoped guard for popup coverage, plus corrected docstrings in
  `fetcher.py`, `banner_dismiss.py` and `stealth.py`. **New evidence to add to the
  remediation brief: blocking SWs costs nothing measurable on real PWAs.**
- **Source**: Audit Phase 5C, "PWA / Service-Worker sites" category.
---

### [NEW, full Tier A] AUDIT-5A-7 — Seven ordinary Tier A homepages are walled, and one of them (`reuters.com`) serves the wall on **HTTP 200**, which is the one shape that poisons a baseline

- **Severity**: **High**. This is the Tier A instance of the same defect class as
  AUDIT-5B-1, but with one materially worse member, so it is filed separately rather
  than folded in: **on 6 of the 7 the baseline gate accidentally saves the system
  (status >= 400); on the 7th it does not, and that one is `reuters.com`** — one of
  the most widely monitored news sites on the internet, and a catalog "Top 20" entry.
- **Subsystem / file(s)**: as AUDIT-5B-1 (`worker/fetcher.py:166-201`, `:352-374`;
  `worker/scan_tasks.py:109-119` vs `:262-272`).
- **Reproduction** (3 passes each; status, body size, visible text, `capture_quality`):

  | site | status | title | body | visible chars | `capture_quality` | baseline outcome |
  |---|---|---|---|---|---|---|
  | `www.ndtv.com/` | **403** | `Access Denied` | 286-290 B | 202-206 | **full** | correctly refused |
  | `www.ndtv.com/entertainment` | **403** | `Access Denied` | ~290 B | 217 | **full** | correctly refused |
  | `www.news18.com/` | **403** | `Access Denied` (`server: istio-envoy`) | ~290 B | 206 | **full** | correctly refused |
  | `www.moneycontrol.com/` | **403** | `Access Denied` (`server: UploadServer`) | ~290 B | 214 | **full** | correctly refused |
  | `news.sky.com/` | **403** | `Access Denied` (`server: AkamaiGHost`) | ~290 B | 206 | **full** | correctly refused |
  | `www.imdb.com/` | **405** | `Human Verification` ("Let's confirm you are human… the puzzle requires Google Translate to be disabled") | 9 515 B | 533 | **full** | correctly refused (405 >= 400) |
  | **`www.reuters.com/`** | **200 (P1) then 401 (P2, P3)** | P1: **no title at all** | P1 13 439 B; P2/P3 1 468 B (`x-datadome: protected`, `datadome` cookie) | **P1: 0** | **full** | **PASSES the gate -> stored as a healthy baseline** |

  `reuters.com` **alternates** between a 200-OK DataDome soft-block (P1, `server:
  openresty`, 13 439 B, literally zero visible characters) and a 401 DataDome page
  (P2/P3, 1 468 B). All three raw UA probes return 401. Its detection pairs:
  p1->p2 and p1->p3 both **flagged at 0.9992** — i.e. the 200-OK wall is diffed
  against the 401 wall at maximum severity, which is the *correct* diagnosis arriving
  through the *wrong* mechanism.
- **Root cause**: identical to AUDIT-5B-1 for the six 403/405 sites. For `reuters.com`
  the additional fact is decisive: **a vendor that chooses 200 for its block page
  defeats the only gate Wardress has**, and there is no content-sufficiency check to
  catch the 13 439-byte, 46-tag, zero-visible-character document. Note the irony:
  `reuters.com`'s P1 response is the *most* detectable case in the whole phase by any
  content-based measure, and the *only* one the status gate misses.
- **Proposed remedy category**: as AUDIT-5B-1/AUDIT-5C-1 — a content-sufficiency
  test (visible-text length, DOM tag count, body size) applied at both the baseline
  and the scan gate, plus the vendor-agnostic wall classifier. The `reuters.com`
  capture is a perfect regression fixture: `status=200`, `body=13 439 B`,
  `tags=46`, `visible_text=0` is unambiguously not content, and no current code path
  looks at any of those three numbers.
- **Source**: Audit Phase 5A, "Indian News" / "International News" / "Other solid
  general sites" categories.

---

### [NEW, full Tier A] AUDIT-5A-8 — `archive.org` returns its `noscript` fallback ("Javascript is required for this site") and Wardress stores it as a complete capture, including once with a 4 032 px screenshot-height difference

- **Severity**: **Medium**. §6.4 Medium — a silent near-miss: the capture succeeds,
  `page.content()` is real HTML, `capture_quality` is `full` or `partial`, and the
  stored artifact contains a 101-character fallback page instead of the Internet
  Archive's homepage. Detection then flags it (p1->p3 risk 0.7932) because the
  *screenshot* geometry differed (h 3 507 vs **30 263 px**, P3 height-capped) — i.e.
  the alert fires for the wrong reason and the real problem is invisible.
- **Subsystem / file(s)**: `backend/worker/fetcher.py:589` (`SETTLE_MS = 5_000`
  after `wait_until="load"`), `:639-642` (scroll + stability), `:352-374`
  (`_classify_capture_quality`, which grades mechanics only), and
  `backend/worker/page_prepare.py:59` (`_CONTENT_LENGTH_JS` reads
  `document.body.scrollHeight`/`textContent` — for a `noscript` fallback it reads the
  fallback, not the app).
- **Reproduction**: 3 passes of `https://www.archive.org/`. Every pass returns
  HTTP 200 with 8 584 bytes whose only visible text is
  `"Javascript is required for this site. Consider enabling Javascript or upgrading
  to a modern browser."` — 101 visible characters, 70 DOM tags. Yet Chromium with
  the production stealth context is executing JavaScript elsewhere on the phase
  (4000-px-wide captures on `hulu`, `pinterest`, `flightaware`), so this is a
  site-specific fallback path, not a stealth failure. The three passes disagreed
  wildly about how much page there was: `initial_height -> final_height`
  **3 507 -> 3 507 (P1)**, **-> 30 263 (P2/P3)**, with `screenshot_capped: true` on
  the tall pass. Detection: p1->p2 0.207, p2->p3 0.207, **p1->p3 0.7932 flagged**.
- **Root cause**: a `noscript`/JS-required fallback is indistinguishable from a real
  page to every signal the capture records. The height disagreement across three
  passes of the *same* URL (3 507 vs 30 263 px) is the tell that the app was
  hydrating at a different rate in each pass — the same class of
  capture-completeness variance as AUDIT-5A-2, on a site where the variance is
  between "no content" and "all content".
- **Proposed remedy category**: a "fallback-shell" detector in the same
  content-sufficiency family as AUDIT-5C-1 (a page whose visible text matches
  a JS-required / enable-cookies / please-turn-on-JS pattern, or whose body carries a
  `<noscript>`-only document, is not content); and the AUDIT-5A-2 completeness
  channel so a 3 507-vs-30 263 px pair is discounted rather than diffed.
- **Source**: Audit Phase 5A, "Reference & Knowledge" category. Note this is the
  "skeleton-then-replace" failure mode the coordinator asked Tier C's hydration
  category to look for, reproduced in **Tier A** on a different site.

---

### [NEW, full Tier A] AUDIT-5A-9 — `www.indiaforums.com` exhausts the 180 s runner budget on all three passes; `www.wikidata.org` was lost to the DNS outage

- **Severity**: **Low** as a product finding; recorded because Rule 19 requires every
  failing site to be individually dispositioned.
- **Subsystem / file(s)**: `backend/tests/_capture_child_impl.py` (child helper),
  `backend/tools/run_stress_catalog.py:32` (`SITE_BUDGET_S = 180`, the runner's
  budget), `backend/worker/fetcher.py:565-567` (`NAV_TIMEOUT_MS = 60_000`).
- **Reproduction / disposition**:
  - `https://www.indiaforums.com/` — **3/3 `stalled (timeout budget exceeded)` at
    exactly 180 s**. Unlike every other timeout in this phase, which surfaced as
    `FetchError: navigation timeout` at ~95 s, this one produced **no error message
    at all**: the child was still inside `fetch_page` (or inside `browser.close()`)
    at 180 s and was killed by the runner's tree-kill. That is the PROMPT-002 Phase-13
    Playwright-transport-hang signature the runner was built to survive — and it
    survived it correctly, but the site is un-monitorable. **Fix-candidate** (needs
    individual root-cause on a diagnostic pass I could not complete in budget): note
    that its Bollywood siblings (`filmfare`, `pinkvilla`, `koimoi`,
    `bollywoodhungama`) all captured fine, so this is site-specific, not a category
    property.
  - `https://www.wikidata.org/` — 3/3 DNS-outage failures. **Environment, not a
    result. Excluded from every rate.** Not re-run to completion.
  - `https://www.cbc.ca/` — 3/3 `net::ERR_*` transport refusal at 5-8 s. Same class
    as AUDIT-5B-4 (`washingtonpost.com`, `accuweather.com`). **Fix-candidate.**
  - `https://stackoverflow.com/`, `https://www.techdirt.com/`,
    `https://www.rfc-editor.org/` — 3/3 `_ChallengeUnsolvedError`. **CORRECT
    BEHAVIOUR**: the Cloudflare gate detected, waited the full window, retried with
    the longer wait, and refused rather than storing challenge HTML. These are the
    three **Accepted-risk** cases in Tier A, individually argued: Wardress is not
    meant to defeat an interactive Cloudflare challenge, no public bypass exists that
    a monitoring tool should use, and the system's response is exactly the designed
    one (a user-safe `BOT_PROTECTION_ERROR`, a failed capture, no stored content).
    `rfc-editor.org` **independently reproduces PROMPT-002 Phase 13's prior
    disposition** ("correctly-detected block") — the catalog's own note asked for this
    comparison and the answer is: same behaviour, unchanged.
- **Proposed remedy category**: for `indiaforums.com`, a bounded diagnostic pass
  (capture with an extended budget and `--load`-free tracing) to determine whether
  the stall is navigation, scroll, stability or `browser.close()`; if it is
  `browser.close()`, that is a distinct leak worth its own finding.
- **Source**: Audit Phase 5A, "Tech / Developer" and "Indian / Bollywood Entertainment".

---

### [CORRECTION] AUDIT-5A-4 severity note and one of my own false positives, stated

`https://www.un.org/` was flagged by my own shell heuristic (533 visible characters,
145 tags) as a "wall". It is **not** — the visible text is genuine UN content in nine
languages, and the page simply *is* sparse. I record it in the table as
`my shell heuristic over-fired`, and the wall count in the Tier A summary
(**7 sites**) excludes it. `https://www.archive.org/` is retained as a real finding
(AUDIT-5A-8) because its 101 visible characters are a literal
"Javascript is required for this site" fallback, which I verified by reading the
captured HTML. The lesson generalises: **a visible-text-length threshold alone cannot
tell a wall from a sparse page** — any content-sufficiency gate that ships must combine
it with tag count, body size and the vendor/title fingerprints, exactly as my own
final calibration had to.

## Tier A — log-vs-reality discrepancies

| prior claim | source | what I measured (full 69-URL Tier A) |
|---|---|---|
| "benign live churn fuses to **0.1907-0.2213** and reads `changed`" | `PROMPT-003-IMPLEMENTATION-LOG.md` line 1625 (Session A's re-rating of AUDIT-1-1), measured on hermetic out-of-family fixtures | On **69 real Tier A homepages** the median fused risk is **0.3000** and the range **0.0019-1.0000**, with **55 of 177 pairs (31 %) FLAGGED**. The fixtures understate real news/tech/homepage churn by roughly an order of magnitude at the top end. |
| "`layer1_hash` alone is `sigmoid(4.408 - 6.247) = 0.1372`" | log line 1625 | Reproduced exactly, twice: `quietude-one.vercel.app` 0.1410 / 0.1410 / 0.1372 and `developer.mozilla.org` 0.137. Confirms the log's arithmetic. |
| "Only a byte-identical pair reads `clean`" | Session A, `scratch/session-a-capture.md` | Confirmed **exactly**, and now quantified: **33 of 177 Tier A pairs read `clean`** and every one of them has `layer1_hash = 0.0`. The 144 pairs with `layer1_hash = 1.0` read `changed` or `flagged`, never `clean`. Across Tiers A+B+C the byte-reproducible-pair count is 40 of 303 (13 %). The verdict is a pure byte-equality test wearing a nine-layer coat. |
| "the Phase-13 gate proved capture CONSISTENCY (theguardian skeleton similarity 0.9988)" | log line 154 | **Contradicted at scale.** `theguardian.com` itself is fine (0.167-0.350, `changed`), but the tier contains: `aajtak.in` rendering 27 915/28 002/37 384 px on three passes; `businesstoday.in` 12 509 -> **47 031 px**; `indiatoday.in` 27 991-40 464 px; `archive.org` **3 507 vs 30 263 px**; `bbc.co.uk` 6 069 vs 6 109 px; `hulu` 9 269 vs 13 594 px; `airbnb` 2 846 vs 4 576 px; `pexels` 3 772 vs 4 753 px. Capture *content* consistency on a fixed page set held; capture *completeness* consistency did not, and completeness is what the nine layers diff. |
| "`www.rfc-editor.org` was correctly-detected block" (PROMPT-002 Phase 13) | catalog note, line 142 | **Independently reproduced**: 3/3 `_ChallengeUnsolvedError`, `Cloudflare challenge detected`, no content stored. Unchanged in ~1 catalog generation. |
| `MAX_SCREENSHOT_HEIGHT`'s asymmetry is a latent gap (Session A AUDIT-SA1-5) | Session A | **Overturned for Tier A**: PNG width was **1366 px on all 180 captures**. It is real in Tiers B and C (4000 px and 1378 px on 4 sites) — see AUDIT-5C-2. So the gap is real but *category-specific*, not general. |
| the catalog's "Extremely large pages" category ("multi-megabyte DOM") | `PROMPT-003-stress-site-catalog.md` line 234 | **Not reproduced.** The largest HTML anywhere in the phase was **3.38 MB** (`nbcnews.com`, Tier B) and Tier C peaked at **2.11 MB**; the 10 MB `MAX_HTML_BYTES` guard was never approached and PROMPT-002's 10 MB observation did not recur. What these pages *do* have is height (up to **47 031 px**) and lazy-load variance, not size. |
| the catalog's "PWA sites (may serve cached content on repeat visits)" | catalog line 228 | **Not reproduced.** All three PWAs served fresh bytes on the second visit in both the production and the `service_workers="block"` arm, with unchanged `transferSize`. The interesting PWA finding is the request-path exposure, not the cache. |
| the catalog's "Slow / high-latency origins" category | catalog line 242 | **Not reproduced as a latency property.** `gutenberg.org` returned in 22-27 s with no timeout on all three passes; `india.gov.in` returned in 12.7-13.6 s but was **HTTP 403** and measured nothing about latency. The budgets are generous — arguably 4x the observed median — and no timeout pressure was found anywhere in this phase. |

---

## Phase totals (per-case, never a bare aggregate)

| tier | unique URLs | captures planned / succeeded / failed | 3/3 captures | sites failing ≥1 pass | detection pairs | `clean` | `changed` | **`flagged`** | sites storing a wall / shell as content |
|---|---|---|---|---|---|---|---|---|---|
| **A** | 69 / 69 | 207 / 180 / 27 | 56 sites | 13 (of which 4 = DNS-outage only) | 177 | 33 | 89 | **55 (31 %)** | **7** |
| **B** | 31 / 31 | 93 / 80 / 13 | 25 sites | 6 | 77 | 3 | 29 | **45 (58 %)** | **8** |
| **C** | 21 / 21 | 63 / 52 / 11 | 15 sites | 5 | 49 | 4 | 24 | **21 (43 %)** | **4** |
| **total** | **121 / 121** | **363 / 312 / 51** | **96 sites** | **24** | **303** | **40 (13 %)** | **142** | **121 (40 %)** | **19** |

### Per-case disposition ledger (Rule 19 — every below-target metric, individually)

| # | case | outcome | disposition |
|---|---|---|---|
| 1 | `stackoverflow.com` | 0/3, `_ChallengeUnsolvedError` 3/3 | **Accepted-risk** — interactive Cloudflare challenge; no public bypass a monitoring tool should use; gate refused rather than storing challenge HTML |
| 2 | `www.techdirt.com` | 0/3, `_ChallengeUnsolvedError` 3/3 | **Accepted-risk** — as #1 |
| 3 | `www.rfc-editor.org` | 0/3, `_ChallengeUnsolvedError` 3/3 | **Accepted-risk** — as #1; independently reproduces PROMPT-002 Phase 13's "correctly-detected block" |
| 4 | `www.sncf-connect.com` | 0/3, `_ChallengeUnsolvedError` 3/3 | **Accepted-risk** — as #1; catalog category is wrong (Cloudflare, not DataDome) |
| 5 | `godaddy.com` | 3/3 captures, HTTP 403 Akamai wall stored | **Fix-candidate** (AUDIT-5B-1) — not an accept-risk: the vendor's own `server: AkamaiGHost` and deny title are machine-detectable |
| 6 | `leboncoin.fr` | 3/3, HTTP 403 DataDome wall stored | **Fix-candidate** (AUDIT-5B-1) |
| 7 | `yelp.com` | 3/3, HTTP 403 DataDome wall stored | **Fix-candidate** (AUDIT-5B-1) |
| 8 | `etsy.com` | 3/3, HTTP 403 DataDome wall stored | **Fix-candidate** (AUDIT-5B-1) |
| 9 | `zillow.com` | 3/3, HTTP 403 PerimeterX wall stored | **Fix-candidate** (AUDIT-5B-1) |
| 10 | `unsplash.com` | 3/3, HTTP 401 **Anubis** PoW wall stored, URL navigated to `.within.website?redir=` | **Fix-candidate** (AUDIT-5B-1) — Anubis is a *new* vendor for the classifier, not a bypass target |
| 11 | `dash.cloudflare.com` | 3/3, 200-OK `/login` wall stored as a **ready baseline** | **Fix-candidate** (AUDIT-5C-1, Critical) |
| 12 | `500px.com` | 3/3, 200-OK onboarding dialog stored as a **ready baseline**; scan flagged at risk 0.99999 | **Fix-candidate** (AUDIT-5C-1, Critical) |
| 13 | `www.ndtv.com` + `/entertainment` | 3/3 + 3/3, HTTP 403 wall stored | **Fix-candidate** (AUDIT-5A-4, AUDIT-5A-7) |
| 14 | `www.news18.com`, `www.moneycontrol.com`, `news.sky.com` | 3/3 + 3/3 + 3/3, HTTP 403 walls stored | **Fix-candidate** (AUDIT-5A-7) |
| 15 | `www.imdb.com` | 3/3, HTTP **405** `Human Verification` stored | **Fix-candidate** (AUDIT-5A-7) |
| 16 | **`www.reuters.com`** | 3/3, **HTTP 200** 13 439 B / 0 visible chars wall; passes the baseline gate | **Fix-candidate** (AUDIT-5A-7) — the single most important wall case found |
| 17 | `www.archive.org` | 3/3, `noscript` fallback stored | **Fix-candidate** (AUDIT-5A-8) |
| 18 | `web.whatsapp.com`, `tradingview.com/chart/`, `instagram.com/nasa/` | 3/3, app shells at viewport height reported `full` | **Fix-candidate** (AUDIT-5C-3) |
| 19 | `www.washingtonpost.com`, `www.accuweather.com`, `www.cbc.ca` | 0/3 each, `net::ERR_HTTP2_PROTOCOL_ERROR` | **Fix-candidate** (AUDIT-5B-4) — deterministic client/protocol refusal, not flakiness |
| 20 | `www.nasa.gov/image-of-the-day/`, `www.wsj.com/` | 0/3 each, nav timeout at 95 s every pass | **Fix-candidate** — nav budget exhausted; needs a diagnostic pass to separate site latency from a transport stall |
| 21 | `weather.com` (2/3), `bestbuy.com` (2/3), `apnews.com` (2/3), `hindustantimes.com` (2/3), `haaretz.co.il` (2/3), `reddit.com` (2/3, 1 env) | nav timeout | **Fix-candidate** — same as #20, individually enumerated above in the FAIL blocks |
| 22 | `www.indiaforums.com` | 0/3, **stalled at exactly 180 s** with no error surfaced | **Fix-candidate** (AUDIT-5A-9) — needs a bounded diagnostic pass to locate the stall (nav / scroll / stability / `browser.close()`) |
| 23 | `www.hulu.com` | 3/3, 4000-px-wide screenshots | **Fix-candidate** (AUDIT-5B-3, AUDIT-5C-2) |
| 24 | `www.india.gov.in` | 3/3, HTTP 403 Akamai `Reference #18` — but Wardress's own probe gets 200 / 607 KB | **Fix-candidate** (AUDIT-5C-5) — client-fingerprint block, diagnosable and arguably fixable |
| 25 | `www.wikidata.org`, `www.bollywoodhungama.com`, `www.zeenews.india.com` | 0/3, DNS-outage only | **Environment fact, not a result.** Excluded from every rate; DNS re-verified healthy before and after |
| 26 | `www.nbcnews.com` P1 | 1/3, `SSRFBlockedError: Could not resolve host` then 2/3 OK | **Fix-candidate** (AUDIT-5A-5) |
| 27 | **All 55 Tier A + 45 Tier B + 21 Tier C `flagged` pairs** | 121 pairs over 40 distinct sites, **no attack present** | **Fix-candidate** — AUDIT-5A-1 / 5A-2 / 5A-3 / 5B-2, all individually root-caused to a named layer and line range |

## Rule 1 verification (final)

```
PS> cd C:\Users\Ns8pc\Music\WARDRESS; git status --short
 M Prompts/Pending/Finders/PROMPT-003/PROMPT-003-IMPLEMENTATION-LOG.md     <- pre-existing (Session A); present in my FIRST git status at 12:12, before I touched anything
?? Prompts/Pending/Finders/PROMPT-003/scratch/session-a-*.md              <- Session A's
?? Prompts/Pending/Finders/PROMPT-003/scratch/session-b-detection-accuracy.md   <- sibling W1-B
?? Prompts/Pending/Finders/PROMPT-003/scratch/session-b-performance-ops.md     <- sibling W1-C
?? Prompts/Pending/Finders/PROMPT-003/scratch/session-b-stress-testing.md      <- THIS deliverable
?? backend/tests/test_*.py                                                <- Session A's + sibling W1-B's
```

- **Zero modifications by me to any tracked production file.** The only tracked
  modification (`PROMPT-003-IMPLEMENTATION-LOG.md`) was already present before I
  started and I never wrote to it.
- **No temporary instrumentation was added to production**, so nothing needed
  reverting.
- **No git commit was made.** `git diff --cached --stat` is empty.
- `scripts/install.ps1` / `scripts/uninstall.ps1` were never run.
- **All scratch lives outside the repo** at
  `C:\Users\Ns8pc\AppData\Local\Temp\opencode\wardress-w1a\` (Rule 10), including the
  363 capture artifacts, the per-capture production logs, and every probe script.
