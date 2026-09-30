# SESSION A — SUBAGENT 1 — Capture Pipeline Deep Verification

**Scope:** Audit Phase 1 (capture traceability) + Audit Phase 3 (capture fresh-eyes), re-verified and deepened.
**Method standard:** Rule 4 (every finding reproduced), Rule 13 (nothing docstring- or test-asserted was trusted), Rule 18 (3 passes with variance recorded for every measurement), Rule 16 (one honest severity each, justified against §6.4).
**Rule 1 compliance:** zero production files were modified. All probes live in `C:\Users\Ns8pc\AppData\Local\Temp\opencode\wardress-session-a\capture\`. No test files were added to the repo (see *Summary* — the hermetic cases that would be safe to ship are listed as proposals instead, because every one of them currently *fails* against production code and a committed failing test is a Rule-5 violation).

**Environment:** Docker stack up; real Chromium via `backend\.venv`; all network interaction local-only (127.0.0.1 fixtures). Dedicated test DB not needed (no DB-backed probes were run).

---

## Findings

### [CONFIRMED] AUDIT-3-1 — Banner click can store the WRONG page (root cause reproduced end-to-end through production `fetch_page`)
- **Original phase:** Audit Phase 3, scratch probe `probe_banner_click_navigation.py`
- **Severity:** **High** (upgraded from Medium — see *Deeper analysis*). Justification against §6.4: "a documented spec requirement simply not met (a true Gap)" — the Phase-5/Phase-7 contract is that a dismissal is a presentation-layer operation that cannot change *what* is captured, and the Phase-2 contract "challenge HTML is never stored as content" is defeated through it. Not Critical: no attack pattern produces a false "clean"; the damage is a wrong/poisoned comparison, not a missed defacement.
- **Subsystem / file(s):** `backend/worker/banner_dismiss.py:229-231` (generic `button[aria-label*='Accept'/'accept'/'Agree']`), `:342-367` (`_find_and_click` clicks without verifying consent context or post-click navigation), `backend/worker/fetcher.py:590` (`final_url = page.url` — captured **before** dismissal), `:626-628` (dismissal), `:649` (`page.content()` — captured **after**), `:659` (`latest = nav_responses[-1]` — captured **after**).
- **Verification method:** live probe, real Chromium, **3 passes, 3/3 deterministic**, production `fetch_page` unmodified.
- **Evidence:** `probe_banner_nav2.py`. Server request log per arm:

  | Arm | Server saw | `final_url` returned | Captured HTML | `cf_detected` | `capture_quality` |
  |---|---|---|---|---|---|
  | A control (button inert) | `['200 /ctl']` | `/ctl` | `REAL-CONTENT-MARKER` | False | full |
  | B click → ordinary page | `['200 /ctl-to-other', '200 /other']` | `/ctl-to-other` ← **stale** | `WRONG-PAGE-MARKER` | False | full |
  | C click → CF challenge page | `['200 /ctl-to-challenge', '200 /challenge']` | `/ctl-to-challenge` ← **stale** | **`CHALLENGE-PAGE-MARKER`**, `<title>Just a moment...</title>` | **False** | full |

  `fetch_page` returned successfully in all three arms — it never raised `FetchError(BOT_PROTECTION_ERROR)`.
- **Deeper analysis (what Phase 3 did not see):**
  1. **The challenge gate is defeatable through the banner click.** `_wait_out_challenge` runs at `fetcher.py:609`, dismissal at `:626`. A page whose accept-looking control navigates into a Cloudflare interstitial is captured as **challenge HTML with `cloudflare_challenge_detected: False` and `capture_quality: "full"`**. That is a direct, deterministic violation of the Phase-2 headline contract. `nav_responses` *does* record the post-click navigation — the guard just never looks at it after dismissal.
  2. **`FetchResult` is internally self-contradictory.** `final_url` is the pre-click URL; `http_status`/`headers` come from the post-click `nav_responses[-1]`. Two halves of one record describe two different pages.
  3. **Cross-subsystem consequence of the stale `final_url`:** `worker/scan_tasks.py:140` writes it into `baseline.capture_meta["final_url"]`, `:283` into the scan's `ScanPageData.final_url`. `worker/detection/dom.py:651` uses `page.final_url` as the **base URL for relative-URL resolution**, and `dom.py:699` compares `_safe_hostname(current.final_url)` against the baseline's. A wrong `final_url` therefore corrupts relative-link resolution *and* mis-fires the same-host allowance check. Per §6.4's cross-subsystem note this is where a presentation-layer bug becomes a detection-accuracy bug.
  4. **Retry contract is untouched:** the capture *succeeds*, so neither the transient nor the challenge retry path is entered — there is no safety net.
- **Cross-subsystem interactions:** detection (`dom.py` base-URL + host logic), baselines (`scan_tasks.py:140`), API/frontend (`capture_meta` is served on site detail), alerting (a wrong-page capture diffs maximally against a real baseline → false alert).
- **Proposed remedy category (sketch only, Rule 1):** re-read `page.url` after `dismiss_banners` and record a `main_frame_navigations_during_dismissal` signal (Phase 3's own O-idea); if the click navigated, discard the click (re-navigate to the pre-click `final_url`) or re-run the challenge gate and mark `capture_quality: "degraded"`; narrow the generic fallbacks to a consent-context container.

---

### [DEEPENED] AUDIT-3-2 — Stale frame snapshot, **plus a second, independent cause the log did not find: consent iframes below the fold are never clicked at all**
- **Original phase:** Audit Phase 3, scratch probe `probe_frame_wait_budget.py`
- **Severity:** **Medium** (unchanged — the widened blast radius does not reach §6.4's High bar; the effect is a degraded but *labelled-full* capture, not a wrong-page capture or a false alert).
- **Subsystem / file(s):** `backend/worker/banner_dismiss.py:393` (`frames = _frames(page)` snapshotted once), `:404` (`page.wait_for_selector` — main frame only by Playwright semantics), `:407` (final pass reuses the stale snapshot), **`:314-334` (`_clickable_in_viewport`) — newly implicated**, `backend/worker/page_prepare.py:111-113` (`scrollBy` is the only scroll mechanism).
- **Verification method:** two live probes, real Chromium, production `dismiss_banners`/`_clickable_in_viewport` unmodified. 3 passes on the first probe; 1 pass each arm on the second (deterministic, single-cause).
- **Evidence:**

  **Cause 1 (as logged) — stale snapshot, reproduced exactly:** `probe_browser.py` B1.
  | Fixture | frames at entry | frames at end | `attempts` | `dismissed` | wall |
  |---|---|---|---|---|---|
  | banner iframe attaches 2.5 s after load | 1 | **2** | **30** | False | 3.141 s |
  | banner iframe present at load | 2 | 2 | 60 | False | 3.39 s |
  | 3-level nested iframe | 4 | 4 | 120 | False | 3.578 s |

  The late-attaching case proves the point exactly: the server logged `200 /late-child` (the consent iframe **was** fetched), `page.frames` grew to 2, yet `attempts == 30` = one pass over the single frame captured at entry. The final pass never re-snapshots.

  **Cause 2 (NEW, precise root cause) — below-the-fold consent iframes:** `probe_frame_place.py`, identical button, only iframe placement differs.
  | Fixture | frames | element `is_visible` | bounding box | `clickable_in_viewport` | result |
  |---|---|---|---|---|---|
  | I1 iframe first in `<body>` | 2 | True | `y=78.4` | **True** | `dismissed: True`, `#cookie_action_accept`, 36 attempts |
  | I2 iframe after a 2500 px spacer | 2 | True | `y=2578.4` | **False** | `dismissed: False`, 60 attempts |

  `_clickable_in_viewport` compares an element's **page-coordinate** box against `page.viewport_size` (`banner_dismiss.py:329-334`) and **never scrolls the element into view** before testing. Every `position:fixed` control inside an iframe appended at the end of `<body>` — where Quantcast, Sourcepoint, and a large share of CMP hosts put them — is rejected.
- **Deeper analysis:**
  - Deep nesting is *not* the problem: `page.frames` is a flat list including grandchildren (4 frames found at 3 levels). The log's implied "nested iframe" framing is a red herring; the real defects are (a) snapshot staleness and (b) the viewport test.
  - **The budget is always fully burned when nothing is dismissible.** `dismiss_banners` costs **3.09–3.14 s** on a banner-free page (3 measurements, variance 0.05 s) — see AUDIT-SA1-3.
  - **Compounding, confirmed by code:** an undismissed full-viewport overlay typically installs a body scroll-lock, `auto_scroll_page`'s `window.scrollBy` then no-ops, no lazy content loads — and `capture_quality` still reads `full`, because `_classify_capture_quality` (`fetcher.py:352-374`) only grades scroll-cap / stability / screenshot-cap and by design never looks at banner evidence.
- **Cross-subsystem interactions:** scroll pass (lazy content), visual-diff layer (the overlay is in the PNG), `capture_quality` health buckets on the health page, DOM-diff layer (overlay nodes churn between captures).
- **Proposed remedy category:** re-snapshot frames before the final pass; `scroll_into_view_if_needed()` (or drop the viewport gate for elements already `is_visible()` inside a frame whose own viewport contains them); consider surfacing an `unclicked-consent-overlay-detected` signal for `capture_quality`.

---

### [NEW] AUDIT-SA1-1 — **CRITICAL** — The Playwright SSRF route guard is `page.route`-scoped: Service Workers and popups bypass SSRF validation completely, and the bypass is not limited to the same origin
- **Original phase:** none — surfaced by Session A's cold read of `_make_ssrf_route_guard`'s request-coverage claim. Related to AUDIT-3-3 but **distinct**: AUDIT-3-3 is a *time window*; this is a *missing request path*, and it does not require DNS rebinding at all.
- **Severity:** **Critical**, automatic per §1 Rule 12 ("any finding here is automatically Critical") and §6.4 ("SSRF/security boundary weakness"). No inflation: the bypass is proven by **server-side truth**, not by argument.
- **Subsystem / file(s):** `backend/worker/fetcher.py:287-340` (`_make_ssrf_route_guard` — docstring at :288-291 claims it validates "every request the page initiates"), `backend/worker/fetcher.py:543` (`await page.route("**/*", _make_ssrf_route_guard(...))` — **page** scope, not context scope), `backend/worker/fetcher.py:518-525` (`browser.new_context(...)` — no `service_workers="block"`), `backend/worker/banner_dismiss.py:30-32` and `backend/worker/stealth.py:37-41` (both docstrings restate the "guard is the last word" claim). `backend/tests/test_stealth.py:209-237` is the suite's only guard-coverage test and exercises **only a top-level navigation**.
- **Verification method:** live probe, real Chromium, local HTTP fixtures, **3 passes, 3/3 deterministic**; truth source is the *internal server's own request counter*, never a browser-side claim.
- **Evidence:**

  **Matrix (`probe_sw_ssrf4.py`, `probe_sw_ssrf5.py`) — production policy stubbed only to let the loopback "public" fixture be reachable; the guard handler itself is production code.**

  | Arm | config | guard saw the internal URL? | **internal server received the request?** | body readable back by the hostile page? |
  |---|---|---|---|---|
  | **Q1 = PRODUCTION** | `page.route` + `service_workers='allow'` | **No** | **YES** (`['/secret']`) | **YES** — `BODY:INTERNAL-SECTOKEN-a1b2c3d4-iam-role-admin-creds` |
  | Q2 | `context.route` + `allow` | Yes | **YES** (abort did not stop it) | No |
  | Q3 | `page.route` + `service_workers='block'` | No | **No** (`[]`) | n/a — SW never registers |
  | Q4 | `context.route` + `block` | No | **No** (`[]`) | n/a |
  | **Popups** (`probe_popup_ssrf.py`) | `page.route` (production shape) + `window.open()` | **No** (`guard saw: ['http://127.0.0.1:9061/']`) | **YES** (`['/secret?via=popup']`) | — |

  3 consecutive passes of the Q1/B1/B2 matrix produced byte-identical output (`sw5_3pass.out`).

  **Two facts that materially sharpen the remediation:**
  - **Switching to `context.route` is NOT sufficient.** Q2 shows the guard *does* observe the SW-issued request and calls `route.abort("blockedbyclient")` — yet the internal server still logged the hit. SW-initiated requests are reported to the routing layer but cannot be aborted by it.
  - **`service_workers="block"` on `new_context` is the only armoured option** (Q3/Q4: zero internal hits).
- **Deeper analysis (blast radius, all code-traced):**
  - **Trigger:** any target Wardress captures that can register a Service Worker or open a popup. That is attacker-reachable on a monitored site the moment anyone can inject script into it (the exact scenario defacement monitoring exists for) — and trivially reachable by whoever controls the monitored domain.
  - **Read-back is full, not blind.** `probe_sw_ssrf5.py` B1 (internal service sends `Access-Control-Allow-Origin: *`) **and** B2 (CORS-strict, Redis/Postgres-shaped) both returned the complete secret. The hostile page then wrote it into the DOM, so it landed in the very string `fetcher.py:649` persists: **`page.content()` contained the secret ⇒ the exfiltrated internal response becomes Wardress's stored `page.html` artifact**, downloadable through the artifacts API/frontend.
  - **Network reach:** `docker-compose.yml` puts `app`, `worker`, `beat`, `db` and `redis` on one default network with `REDIS_URL: redis://redis:6379/0` (`docker-compose.yml:41,96,126,146`). The capture browser therefore has internal neighbours to reach, plus whatever the host exposes.
  - **Docs/comments assert an invariant the code does not hold** — `fetcher.py:288-291`, `banner_dismiss.py:30-32`, `stealth.py:37-41`. Under §6.4's "docs drift that could mislead an operator", and under Rule 13 (the docstring was the only thing asserting coverage, and it is false).
  - **Why this is bigger than AUDIT-3-3:** no attacker-controlled DNS, no TTL race, no timing luck. `window.open()` alone is a one-line trigger.
- **Cross-subsystem interactions:** `app/routers/artifacts.py` serves whatever `store_artifacts` wrote; any Wardress account with artifact read access retrieves the exfiltrated internal response. `worker/scan_tasks.py` then diffs it against the real baseline → maximal change → false alert.
- **Proposed remedy category (Rule 12 note: `app/ssrf.py` must not be edited — the fix is entirely in `fetcher.py`'s context construction):** add `service_workers="block"` to `browser.new_context(...)` at `fetcher.py:518` (proven sufficient by Q3/Q4); move the guard to `context.route("**/*", ...)` for popup coverage **in addition to** (not instead of) the block; add a hermetic regression test that asserts *server-side* zero hits, not a browser-side `ERR_BLOCKED_BY_CLIENT`; correct the three docstrings. Consider a startup assertion/log line naming the residual, now-closed vectors.

---

### [DEEPENED] AUDIT-3-3 — SSRF rebinding window on the Playwright path: cache widening confirmed, **and the log understates the guard's real weakness in a different way**
- **Original phase:** Audit Phase 3, scratch probe `probe_ssrf_verdict_cache.py`
- **Severity:** **Medium** (unchanged), but the *reason* should be restated: this finding is now largely subsumed by AUDIT-SA1-1, which is a strictly larger and non-timing-dependent hole in the same guard.
- **Subsystem / file(s):** `backend/worker/fetcher.py:301` (`verdict_cache: dict[str, bool]`), `:312` (`cache_key = f"{scheme}://{host}"`), `:326` (write, never invalidated, never re-validated), `:328` (`route.continue_()` — Chromium resolves independently), `backend/app/ssrf.py:11-20` (docstring concedes the Playwright gap), `backend/worker/probe.py:93-94` (`asyncio.open_connection` — unpinned raw-socket TLS path).
- **Verification method:** hermetic unit probe with fake `Route` objects (`probe_unit.py` A1) + code trace.
- **Evidence:** 10 URLs offered to the production guard → **3 `assert_url_allowed` calls**:

  ```
  https://cdn.example.com/a.js      -> continue   ┐
  https://cdn.example.com/b.css     -> continue   │ one validation
  https://cdn.example.com/c.woff2   -> continue   │ covers all five
  https://cdn.example.com:8443/d.js -> continue   │  (port NOT in the key)
  https://cdn.example.com/e.js?v=2  -> continue   ┘
  http://cdn.example.com/f.js       -> continue   (separate scheme key)
  data: / blob: / about:            -> continue   (documented, no egress)
  https://other.example.org/g.js    -> continue   (separate host)
  → assert_url_allowed calls: 3
  ```
- **Deeper analysis:**
  - **New defect inside the cache: the key omits the port.** `https://cdn.example.com:8443/x` inherits the verdict recorded for `https://cdn.example.com:443/y`. SSRF impact is nil (policy is host-scoped) but the cache is objectively wrong, and it means a future port-scoped policy would be silently bypassed.
  - **Honest counter-argument the log did not make:** the per-host cache widening is **less** exploitable than the log implies. Chromium maintains its own per-profile host resolver cache honouring the record TTL, so a same-host rebinding flip within a single page load is unlikely to be re-resolved at all. The real risk of this cache is therefore **staleness against policy changes**, not rebinding. AUDIT-3-3's Medium severity survives, but its stated rationale ("extends the unvalidated window from one request to the whole page load") overstates exploitability.
  - `probe_tls`'s unpinned raw-socket path is confirmed by code read (`probe.py:93-94` — `asyncio.open_connection(host, ...)` after a *separate* validation in `probe_site`), unchanged from the log. Not separately exploited; kept as logged.
  - **Compounding:** with AUDIT-SA1-1 in play, the SW/popup paths are **never validated at all** — so a rebinding-free, TTL-free bypass strictly dominates the rebinding one. Remediation should sequence SA1-1 first.
- **Cross-subsystem interactions:** none beyond the capture path itself; `app/ssrf_transport.py` already closes this properly for the httpx probe path, so the fix pattern exists in-repo.
- **Proposed remedy category:** re-snapshot-free minimal change — include the port in the cache key; longer term, extend DNS pinning to the browser path (proxy subresource fulfilment through `SSRFPinningTransport`) and pin `probe_tls`.

---

### [DEEPENED] AUDIT-3-4 — Artifact janitor gaps: the exact indefinite-survival paths enumerated, plus a **data-corruption** path the log rated under the wrong severity band
- **Original phase:** Audit Phase 3 (code-trace only)
- **Severity:** **High** for the partial-write path (§6.4: "data corruption"); the retention/orphan paths as logged are **Medium** (unbounded retention under sustained load). I am splitting the log's single Low into two honestly-rated halves rather than inflating or deflating one number.
- **Subsystem / file(s):** `backend/worker/artifacts.py:23-24` (`write_text`/`write_bytes`, no tmp+rename), `backend/worker/scan_tasks.py:126-127` (baseline `store_artifacts` before commit), `:276` (scan `store_artifacts` before commit), `backend/worker/beat_tasks.py:271-291` (`if orphan_id in existing: continue`), `:55` (`JANITOR_MAX_REMOVALS_PER_RUN = 500`), `:426` (janitor is periodic), `backend/worker/celery_app.py` (beat schedule).
- **Verification method:** code trace (no probe needed — the ordering is unambiguous), plus exhaustive grep for row retention.
- **Evidence — the complete enumeration of indefinite-survival paths:**
  1. **No age-based retention exists at all.** Repo-wide grep for row deletion: the *only* `delete(...)` on a scan-side table is `scan_tasks.py:207` (`delete(ScanFinding).where(scan_id == scan.id)` — findings for one scan). **Nothing ever deletes `Scan` or `Baseline` rows.** The janitor's only criterion is *row absence* (`beat_tasks.py:279-282`), so **every artifact directory whose row still exists survives forever**, regardless of age or terminal state — `failed`, `error`, `capturing`, `pending`, superseded. This is the dominant, permanent leak.
  2. **Post-`store_artifacts`-pre-commit kill.** `store_artifacts` runs at `scan_tasks.py:276`, the commit at `:350` — a ~74-line window. If the transaction rolls back and the row was never committed, the dir *is* a true orphan and the janitor will remove it (correct, but only after a full `JANITOR_INTERVAL_SECONDS` cycle and subject to the 500/run cap at `beat_tasks.py:282`, which can leave a backlog draining over many runs).
  3. **Backlog never fully drains at scale.** 500 removals per run, and `beat_tasks.py:282` `return`s on cap. If orphan creation exceeds 500/cycle the volume grows without bound. Fleet scale makes this plausible.
  4. **Duplicate-writer overwrite (already logged).** The `running`-status guard at `scan_tasks.py:243` deliberately admits re-entry, so two writers share `scans/<id>/page.html` with no fencing and no atomicity; the loser's write can land after the winner's commit, breaking the row's `content_hash` ↔ artifact correspondence.
- **Deeper analysis — why path 4 is worse than "Low":** because writes are non-atomic, a kill between `write_text` and `write_bytes` (or mid-`write_text`) leaves a **truncated or empty `page.html` with a valid-looking row**: the row keeps its `status='completed'`, its `content_hash` (computed from the *full* html at `scan_tasks.py:277`, before the write is read back), and a `html_path` pointing at a partial file. `_baseline_page_data`/`ScanPageData` then hand the truncated string to all nine layers (`scan_tasks.py:279-292`), producing a maximal bogus diff → `flagged` → alert. The janitor cannot help: the row exists. That is data corruption with a user-visible false alert, which §6.4 places at Critical/High; I rate it **High** because the trigger requires a worker kill in a narrow window rather than being continuously reachable.
- **Cross-subsystem interactions:** `app/routers/artifacts.py` serves the partial file to operators; the artifacts volume is the only copy of the evidence an operator uses to adjudicate an alert.
- **Proposed remedy category:** atomic writes (`tmp` + `os.replace`); state- and age-aware janitor scope (terminal-state + `captured_at`/`started_at` older than N days) plus a real row-retention policy; bump or remove the 500 cap in favour of a time-budgeted loop; optional capture generation-token fencing.

---

### [DEEPENED] AUDIT-3-5 — Capture-completeness never reaches detection: the exact data-loss point, plus the full inventory of **write-only evidence**
- **Original phase:** Audit Phase 3
- **Severity:** **Medium** (unchanged) — a partial implementation that degrades gracefully but misses the original intent.
- **Subsystem / file(s):** the loss happens in **one constructor call**: `backend/worker/scan_tasks.py:280-292` (`ScanPageData(...)` receives 9 fields, none of them a completeness flag). Downstream shape: `backend/worker/detection/types.py:12-24` (`PageData` fields: `html, screenshot, final_url, http_status, headers, tls, robots_txt, content_hash`) and `:39-42` (`ScanPageData` adds only `ua_variants`). Storage: `backend/worker/scan_tasks.py:339` (`scan.capture_evidence = result.capture_evidence`).
- **Verification method:** code trace + exhaustive repo-wide consumer grep per evidence key.
- **Evidence — production consumers of every `capture_evidence` key (non-test):**

  | key | production consumer |
  |---|---|
  | `capture_method_version` | `app/routers/sites.py:105`, `worker/scan_tasks.py:148` |
  | `capture_quality` | `app/routers/health.py:220` (fleet aggregate only) |
  | `capture_wall_clock_ms`, `stealth_applied`, `scroll_steps`, `initial_height`, `final_height`, `scroll_time_ms`, `capped`, `stable`, `polls`, `final_length`, `actual_height`, `screenshot_capped`, `dismissed`, `selector`, `attempts`, `cloudflare_challenge_detected`, `cloudflare_challenge_resolved`, `retry_count` | **none** — zero production reads |

  Independently confirms Audit Phase 1's Phase-4 matrix row ("grep-verified NOTHING in `worker/detection/` reads `capture_quality`") and extends it: 17 of the 19 keys are write-only. `retry_count` — added specifically by Phase 6 — is written at `fetcher.py:693` and never read; `capture_wall_clock_ms` — added by Phase 7 for exactly this kind of triage — likewise.
- **Deeper analysis:** the data loss is not a "missing flag" but a **whole-dict drop at a constructor boundary**: `capture_evidence` is assembled at `fetcher.py:680-698` and stored on the row, while `ScanPageData` is built from `result.*` scalars only. Any remediation must change `ScanPageData`/`PageData`, not just the fetcher. The consequence chain is concrete: a baseline captured `full` vs a scan capped at the 20 s scroll limit on an infinite-scroll site produces a diff **of the truncation**, and truncation hides below-fold injected content — a miss path, not merely a noise path.
- **Cross-subsystem interactions:** all nine layers; the `changed`/`flagged` gate at `scan_tasks.py:304-309`; LLM escalation input at `:316-322` (an LLM is asked to adjudicate a change that is actually a capture artifact); `app/routers/health.py` aggregate.
- **Proposed remedy category:** extend `PageData`/`ScanPageData` with a `capture` completeness sub-struct; `capture_quality` + `capped` + `screenshot_capped` + `stable` are the minimum viable set; detection's weighting of them is Phase 4's half.

---

### [DEEPENED] AUDIT-3-8 (logged as AUDIT-3-6 in the coordinator's brief) — `auto_scroll_page` counts a SHRINKING page height as "stable"
- **Original phase:** Audit Phase 3 (code-trace only)
- **Severity:** **Low** (unchanged).
- **Subsystem / file(s):** `backend/worker/page_prepare.py:119` (`stable_steps = stable_steps + 1 if height <= last_height else 0`), `:120-125` (break condition), `:131-135` (return-to-top).
- **Verification method:** code trace, cross-checked against a live 40,016 px capture (B2) and a 108,000 px capture (perf probe C).
- **Evidence:** `<=` conflates "stopped growing" with "shrank". Two consecutive shrinking steps plus `at_bottom` (or `stalled`, which *also* requires `height <= last_height` at `:121`) satisfies the break while lazy content is still pending. Both live captures in this session (`scroll_steps`, `final_height`) were taken on *growing* pages, so the shrink path was not triggered in the wild here — I report it as still-present, not newly-worse.
- **Deeper analysis:** the related `stalled` condition at `:121` compounds it — a page that collapses (e.g. a virtualised list unmounting on scroll-up, or an ad slot collapsing after lazy-load) reports `scroll_y == last_scroll_y` *and* shrinking height simultaneously, ending the walk early with the page still scrolled mid-document. The `finally` block's `scrollTo(0,0)` (`:133`) then fires, so the screenshot starts at the top of a page whose lazy content below the break never loaded, and nothing in `capture_quality` reflects it (`capped=False`, `stable` may be `True`).
- **Cross-subsystem interactions:** lazy-content layer, visual diff, `capture_quality` health buckets.
- **Proposed remedy category:** treat shrink beyond an epsilon as churn (`stable_steps = 0`), or require non-shrinking growth for the stability window.

---

### [DEEPENED] AUDIT-3-6 (WAF-escalation feedback loop) — confirmed by measurement; the `googlebot` tripfire and the request budget are real
- **Original phase:** Audit Phase 3 (arithmetic trace)
- **Severity:** **Low** (unchanged — no measured operator-visible harm yet; it is a policy gap, and Phase 5A owns the live-site evidence).
- **Subsystem / file(s):** `backend/worker/probe.py:231-235` (the 3-UA sequential loop), `:216-227` (robots), `:45-58` (`USER_AGENTS` incl. `googlebot`), `backend/app/scanning.py:36` (cadence floor), `backend/worker/celery_app.py` (limits).
- **Verification method:** measurement with an injected per-request latency (hermetic, deterministic).
- **Evidence — `probe_site` serialisation, 3 passes, server injecting 400 ms/request:**
  ```
  requests probe_site makes : 1 robots.txt + 3 UA fetches = 4
  probe_site wall clock (s) : [1.766, 1.609, 1.625]   (mean 1.667, spread 0.157)
  serial lower bound        : 1.6 s
  ```
  On a real site the 3 UA fetches are 3 sequential TLS handshakes plus RTTs; the loop is the log's own claim, now measured. The `googlebot` UA is sent from Wardress's IP on **every** scan — the classic WAF tripwire the log flagged — and `desktop_chrome` doubles as the layer-6 header source, so it cannot simply be dropped without a layer-6 data change.
- **Deeper analysis:** the loop holds `max_connections=4` (`probe.py:198`) idle for 3 of 4 slots, so the parallelism headroom is already provisioned and unused. Combined with `app/scanning.py:36` tightening cadence to a 5-minute floor on a detected change, the escalation loop the log described is arithmetically sound; what is missing is any per-host request budget or post-block cooldown, and `RETRY_PAUSE_MS` is a fixed 3 s with no jitter.
- **Cross-subsystem interactions:** `app/scanning.py` cadence coupling, layer 6 (`headers`) and layer 7 (`ua_variants`) inputs, Celery soft-limit budget.
- **Proposed remedy category:** operational policy — per-host cooldown after repeated bot-protection failures; gate or verify-source the `googlebot` variant; run the UA fetches concurrently.

---

### [DEEPENED] AUDIT-3-7 — `hashing.py`: latent `content_sha256(None)` crash re-confirmed, plus one now-provable dead branch elsewhere in the same layer family
- **Original phase:** Audit Phase 3, scratch probe `probe_hashing_edges.py`
- **Severity:** **Low** (unchanged for `hashing.py` itself). The separately-discovered dead branch in `probe.py` is **Low** too.
- **Subsystem / file(s):** `backend/worker/hashing.py:20-21`; `backend/worker/probe.py:127-131` (the unreachable fallback) and `backend/worker/probe.py:69-75` (`_name_attrs`).
- **Verification method:** direct call (`probe_unit.py` A3) + code trace + dependency check.
- **Evidence:**
  ```
  content_sha256(None)  -> RAISED AttributeError: 'NoneType' object has no attribute 'replace'
  content_sha256(b'..') -> RAISED TypeError: a bytes-like object is required, not 'str'
  content_sha256(12345)-> RAISED AttributeError: 'int' object has no attribute 'replace'
  ```
  Normalization itself remains sound (Phase 3 verified determinism/conservatism; I did not find a counter-example and `tests/test_hashing.py` is the untouched 12-test suite).
  **Dead branch:** `probe.py:104` calls `ssl_obj.getpeercert()`, which CPython returns as `{}` when `verify_mode=CERT_NONE` — and `pyproject.toml:59` pins `cryptography==50.0.0` as a hard dependency, so `cryptography`-parse failure is the only way into the `except` block. Inside it, `if peer:` is falsy (`_name_attrs({}) == {}`, verified), so lines 129-131 can never execute. `_name_attrs` is therefore **effectively dead**: 3 repo-wide hits, all inside `probe.py`, both call sites behind an always-falsy guard.
- **Deeper analysis:** the `content_sha256` crash is a *latent* task-killer, not a live bug — every current caller passes `str`. It becomes live the moment a degraded capture path passes `None` (`read_artifact_text` returns `None`, and `baseline.content_hash or ""` guards the ORM side but nothing guards a future fetch-side degradation). The `_name_attrs` dead branch is more than cosmetic: it means **`subject`/`issuer` are silently missing from every TLS record** whenever `cryptography` parsing fails, i.e. a *silent evidence gap* in layer 6 — consistent with the log's "latent hardening note" spirit but a different defect.
- **Cross-subsystem interactions:** layer 1 (`hashing.py`); layer 6 metadata (`probe.py`) → `baseline.capture_meta["tls"]`.
- **Proposed remedy category:** assert the `str` invariant at `content_sha256`; drop `_name_attrs` and the unreachable branch, or make the `cryptography` parse failure an explicit, observable degradation signal instead of a silent one.

---

### [NEW] AUDIT-SA1-2 — **High** — Non-Cloudflare bot walls are captured as real content on the **scan** path and deterministically produce false alerts
- **Original phase:** none. Distinct from AUDIT-3-x and from Phase 2B; this is the capture-side cause of the below-target bot-protection categories in AUDIT-1-2.
- **Severity:** **High**, justified against §6.4: "a false positive that would alert operators on legitimate, common site behavior". Measured `fusion risk 0.917–0.931` against a 0.40 flag threshold on three real vendor wall shapes, with `flagged=True` in all three.
- **Subsystem / file(s):** `backend/worker/fetcher.py:166-201` (`_CHALLENGE_TITLE_MARKERS = ("just a moment", "attention required")`, `_CHALLENGE_MARKER_SELECTOR = ".cf-challenge-running, .cf-error-details"`, and the 403+`cf-ray` rule — **Cloudflare-only by construction**), `:125-128` (`BOT_PROTECTION_ERROR` hard-codes "Cloudflare"), `backend/worker/scan_tasks.py:262-272` (**no `http_status` gate on the scan path** — contrast the baseline gate at `scan_tasks.py:109-118`), `backend/worker/detection/types.py:12-24`.
- **Verification method:** hermetic unit probe (detector truth table) + live `run_detection` comparison, real production pipeline.
- **Evidence — detector truth table (`probe_unit.py` A4), all cases evaluated through production `looks_like_challenge_page`:**

  | wall shape | verdict |
  |---|---|
  | Cloudflare JS challenge (503) | CHALLENGE ✔ |
  | Cloudflare block (403 + cf-ray) | CHALLENGE ✔ |
  | Akamai Bot Manager deny (403, `server: AkamaiGHost`) | **passes as REAL PAGE** |
  | Akamai "Reference #18…" (403, `ak_bmsc` cookie) | **passes as REAL PAGE** |
  | DataDome block (403, `server: DataDome`, `datadome` cookie) | **passes as REAL PAGE** |
  | DataDome captcha page (**200 OK**) | **passes as REAL PAGE** |
  | PerimeterX / HUMAN "Press & Hold" (403, `_px` cookie) | **passes as REAL PAGE** |
  | AWS WAF block (403, `awsewaf` / `x-amzn-requestid`) | **passes as REAL PAGE** |
  | AWS WAF CAPTCHA (405) | **passes as REAL PAGE** |
  | Imperva / Incapsula (403, `x-iinfo`) | **passes as REAL PAGE** |
  | Sucuri (403, `server: Sucuri/Cloudproxy`) | **passes as REAL PAGE** |
  | 200-OK soft-block / paywall | **passes as REAL PAGE** |

  **End-to-end consequence (`probe_browser.py` B5) — real baseline vs each wall as the CURRENT page, through production `run_detection` + fusion:**

  | current page | layer1_hash | layer2_dom | layer8_semantics | **fusion risk** | changed | **flagged (≥0.40)** |
  |---|---|---|---|---|---|---|
  | DataDome 200 interstitial | 1.0 | 0.200 | 0.983 | **0.931** | True | **True** |
  | Akamai 403 deny | 1.0 | 0.100 | 0.967 | **0.917** | True | **True** |
  | AWS WAF 403 block | 1.0 | 0.100 | 1.000 | **0.927** | True | **True** |

  All three: `http_status` is carried into `PageData` and **no layer or gate reads it** (`fetch_page` never fails on a non-2xx; `_run_scan` never checks it). The DataDome 200 case additionally bypasses the baseline path's `>= 400` guard (`scan_tasks.py:109`), so a 200-OK interstitial **can be stored as a healthy current baseline** — after which every legitimate future scan of that site reads as a massive change.
- **Deeper analysis:**
  - This is the mechanism that most plausibly explains the Phase-13 below-target Cloudflare-family result (5/6) being attributed only to "discord 10 MB": the discord failure was logged as an HTML-size guard, but a same-shape WAF interstitial on any site is not detected at all, so it never even appears as a failure — it appears as a *flagged scan*.
  - The stress catalog's Tier B is explicitly Akamai / DataDome / PerimeterX / AWS WAF / Turnstile. Per Rule 18 those sites are destined to fail for this reason, and Phase 5A will otherwise mis-attribute it to per-site flakiness.
  - The baseline/scan asymmetry (`scan_tasks.py:109` gate vs none at `scan_tasks.py:263`) is the cheap first remedy: gate the scan path on `http_status`, and treat a wall-shaped 200 the same way.
- **Cross-subsystem interactions:** alerting (`Alert` rows created from `flagged` scans), the `changed` gate, baselines (200-OK poisoning), the health page's `capture_quality_summary` (a wall capture is labelled `full`), Phase 5A/5B stress attribution.
- **Proposed remedy category:** vendor-agnostic wall-page classification (status + header/cookie/title/script fingerprints for Akamai, DataDome, PerimeterX, Imperva, AWS WAF, plus 200-OK interstitial heuristics) evaluated as a *separate* gate from the Cloudflare challenge gate; an `http_status >= 400` gate on the scan path; a `capture_quality`/`blocked_page` label for detected walls. Keep `BOT_PROTECTION_ERROR`'s public message stable for Cloudflare and add a vendor-neutral sibling.

---

### [NEW] AUDIT-SA1-3 — `dismiss_banners` burns its entire 3 s budget on every capture of a banner-free page, and pays 30 `query_selector` round-trips per frame to do it
- **Original phase:** none (surfaced by Session A's performance pass).
- **Severity:** **Low** — a measured per-capture latency cost with no correctness consequence on its own. It becomes material only in aggregate (see *Opportunities*).
- **Subsystem / file(s):** `backend/worker/banner_dismiss.py:398-406` (`deadline` + `page.wait_for_selector(combined, timeout=remaining_ms)`), `:346-367` (`_find_and_click`, `attempts` incremented per frame × selector), `backend/worker/fetcher.py:626-628`.
- **Verification method:** measurement, 3 passes per measurement.
- **Evidence — `probe_perf.py` [A], real Chromium, page with no banner:**
  ```
  dismiss_banners (s, attempts, dismissed):
     (3.141, 30, False)
     (3.093, 30, False)
     (3.094, 30, False)         spread 0.048 s
  ```
  And on the deliberately-undismissable fixtures (`probe_browser.py` B1): 3.141 s / 3.39 s / 3.578 s. **The full `BANNER_DISMISS_TIMEOUT_MS` (3 000 ms) is spent every single time no selector matches**, on top of 30 CDP `query_selector` calls per frame (60 for two frames, 120 for four).
- **Deeper analysis:** against a measured end-to-end capture of the *same* banner-free page (`probe_mem.py`, 3 passes × 8 captures, **10.42–11.06 s per capture**), the 3.1 s banner budget is **~28 % of total capture wall clock** on a typical page — far more than the ~1 % it represents in the documented worst case. On a fleet of N sites without consent banners this is 3 s × every scan × every attempt. The wasted work is also invisible: `capture_evidence["attempts"]` is recorded but read by nothing.
- **Cross-subsystem interactions:** Celery soft-limit budget (`celery_app.py`), adaptive cadence, the `capture_wall_clock_ms` evidence key (write-only — see AUDIT-3-5).
- **Proposed remedy category:** make the late-banner wait event-driven (`page.wait_for_selector` on a *single* cheap probe, or a `MutationObserver`-driven hook) rather than a flat timeout; skip the wait entirely when the combined selector set is provably absent; consider scoping `attempts` to a sampled subset for pages with many frames.

---

### [NEW] AUDIT-SA1-4 — `apply_stealth` fails *open* only when the package is absent; a raising `playwright-stealth` escapes `fetch_page` entirely and strands the scan row in `running`
- **Original phase:** none. Distinct from the tests' coverage: `tests/test_stealth.py:98-111` proves only the **absent-package** path.
- **Severity:** **Medium** — an availability/observability defect with a real (not remote-attacker-controlled) trigger: a `playwright-stealth` API drift, which is a routine outcome of dependency bumps in this repo (the module is a thin wrapper around a third-party library's moving API).
- **Subsystem / file(s):** `backend/worker/stealth.py:232-243` (`apply_stealth` — the `try/except ImportError` at `:50-53` covers *import* only; there is **no** try around `Stealth(...)` / `apply_stealth_async`), `backend/worker/fetcher.py:529` (`await apply_stealth(context)` — unguarded), `backend/worker/fetcher.py:465-494` (`fetch_page`'s handlers: `_TransientNavError`, `_ChallengeUnsolvedError`, `FetchError`, `SSRFBlockedError`, `PlaywrightError`, `AddressValueError` — **no bare `Exception`**), `backend/worker/scan_tasks.py:263-272` (`except (FetchError, SSRFBlockedError)` only).
- **Verification method:** live probe for the propagation + code trace for the escape route.
- **Evidence — `probe_browser.py` B3:**
  ```
  apply_stealth PROPAGATED RuntimeError: simulated playwright-stealth API drift
  init scripts actually registered before the throw: ['library-partial']
  supplementary script added? False
  ```
  Two facts: (a) the exception escapes `apply_stealth`; (b) the state is **partially applied** — the library's own init scripts are already on the context while `stealth.py`'s supplementary script (webdriver deletion, `cdc_*` strip, Permissions.query, plugins/mimeTypes) never lands, leaving the page in a *less* stealthed state than either the "applied" or the "not applied" contract describes.
- **Deeper analysis:** `stealth_available()` (`stealth.py:246-252`) would still report `True`, so `capture_evidence["stealth_applied"]` would be a lie — except no evidence is produced, because the capture never completes. The exception then propagates `apply_stealth` → `_capture_attempt` (whose `finally: await browser.close()` at `fetcher.py:708-709` does clean the browser up) → `fetch_page`'s narrow except list → `_run_scan`'s narrow except list → the Celery task. The `Scan` row was committed as `running` at `scan_tasks.py:258-260` and is **never updated**; it sits in `running` until whatever stale-row recovery exists (Phase 4B territory) reclaims it. No `error` is recorded, no alert, no evidence — a silent stall.
- **Cross-subsystem interactions:** Celery task failure handling; the stale-inflight recovery sweep; the health page's scan-status display; `stealth_applied` honesty surface.
- **Proposed remedy category:** extend the fail-open contract to cover a *raising* library — wrap `Stealth(...)`/`apply_stealth_async` in try/except, log, and continue unhardened (the supplementary script should still be added, which strictly improves on the library alone); separately, give `fetch_page` a last-resort `except Exception` → `FetchError` so no capture failure can ever escape as an untyped exception; add a hermetic test for the raising case.

---

### [INVALIDATED] — two Session A hypotheses tested and rejected (recorded so they are not re-audited)
1. **IDN (non-ASCII) hostname breaks the whole consent-cookie batch.** `probe_browser.py` B4: `inject_consent_cookies(ctx, "https://bücher.example/")` → 13 names, **13 cookies present on the context**; the punycode form is likewise 13/13. Chromium accepts it. **No defect.** (By contrast, `materialize_consent_cookies` *does* silently strip userinfo from `https://user:pw@example.com/` → cookie url `https://example.com`, and preserves a trailing-dot FQDN (`https://example.com.`) which browsers treat as a distinct cookie host — both are unreachable through the real pipeline, because `assert_url_allowed` (`app/ssrf.py:85-86`) rejects credential-bearing URLs before any cookie is built. Logged as observations only.)
2. **The screenshot height cap can produce a corrupt PNG.** `probe_browser.py` B2: a 40,016 px page capped to 1366×**16384** with a valid `IEND` terminator (307 719 bytes); a raw uncapped `full_page=True` at 40,016 px also succeeded (1366×40016, 754 858 bytes). The cap behaves exactly as documented. **No defect.** (A *different* dimension gap does exist — see next entry.)

---

### [NEW] AUDIT-SA1-5 — The screenshot guard is dimension-asymmetric: it caps height only, and the evidence cannot express width
- **Original phase:** none (surfaced by the Session A screenshot-extremes pass).
- **Severity:** **Low** — a real gap in a guard whose stated rationale is a Chromium raster limit, which applies to **both** dimensions. I could not produce a failure on this headless software-rasterised host, so I am not claiming corruption.
- **Subsystem / file(s):** `backend/worker/fetcher.py:377-416` (`_take_screenshot`), `:403-412` (`if page_height > MAX_SCREENSHOT_HEIGHT`), `backend/worker/fetcher.py:395` (`evidence = {"screenshot_capped": False, "actual_height": 0}` — **no width key**), `backend/worker/stealth.py:92-99` (rationale comment names only height).
- **Verification method:** live probe, real Chromium, real production `_take_screenshot`.
- **Evidence — `probe_browser.py` B2:**
  | fixture | evidence | PNG |
  |---|---|---|
  | 40,016 px tall | `screenshot_capped: True, actual_height: 40016` | 1366×16384, IEND ok |
  | **20,008 px wide × 768 tall** | **`screenshot_capped: False, actual_height: 768`** | **20008×768, IEND ok** |
  | raw uncapped, ~40,016 px | — | 1366×40016, IEND ok |
- **Deeper analysis:** `MAX_SCREENSHOT_HEIGHT = 16_384` was chosen from Chromium's ~16 384 **texture/tile** limit, which is square, yet only the vertical axis is guarded. A page 20 000 px wide is exactly the shape the cap exists to prevent, and on a GPU-backed or differently-configured Chromium build it is where the documented failure (raster failure or corrupt image) would appear — with `screenshot_capped: False` and `capture_quality: "full"`, i.e. the failure would be *silent*. Because no `actual_width` is captured, the evidence cannot even express the condition after the fact. (Caveat stated honestly: no failure was produced here.)
- **Cross-subsystem interactions:** the visual-diff layer consumes the PNG; `capture_quality` would mislabel the capture.
- **Proposed remedy category:** probe and cap width symmetrically (`MAX_SCREENSHOT_WIDTH`, `actual_width` in evidence), or record both dimensions and classify as `degraded` when either exceeds the raster limit.

---

## Dead Code & Orphan Routines

Method: every module-level `def` / `async def` / `class` / `UPPER_CASE` constant in the 10 in-scope files was extracted (`deadcode_sweep.py`), then `rg -n -w <symbol>` was run repo-wide excluding `.venv/`, `node_modules/`, `Prompts/`. 89 symbols swept; full table saved at `…/capture/deadcode.out`.

| file:line | symbol | kind | proof (grep hits) |
|---|---|---|---|
| `backend/worker/probe.py:69` | `_name_attrs` | **orphan func (effectively dead)** | 3 hits, all in `probe.py`. Both call sites (`:129`, `:130`) sit behind `if peer:` — and `peer = ssl_obj.getpeercert()` returns `{}` under `verify_mode = CERT_NONE` (`:92`), so the guard is always falsy. Measured: `_name_attrs({}) == {}`. `cryptography==50.0.0` is a hard dep (`pyproject.toml:59`), so the enclosing `except` is itself near-unreachable. **Consequence: `subject`/`issuer` silently absent from every TLS record on a `cryptography` parse failure.** |
| `backend/worker/probe.py:128-131` | `if peer:` fallback block | **dead branch** | Reachable only when `cryptography` parse fails; `peer` is `{}` there, so lines 129–131 never execute. |
| `backend/worker/fetcher.py:640` | `auto_scroll_page(..., max_scroll_time_ms=MAX_SCROLL_TIME_MS)` | **obsolete param at the only production call site** | `page_prepare.py:65` default is already `MAX_SCROLL_TIME_MS`; repo grep shows the kwarg passed only with its own default value. The parameter is exercised only by `tests/test_page_prepare.py`. |
| `backend/worker/page_prepare.py:66` | `step_pause_ms` | **obsolete param** | No production caller passes it (`fetcher.py:639-641` passes only `max_scroll_time_ms`); test-only. |
| `backend/worker/page_prepare.py:142,143` | `wait_for_content_stable(timeout_ms=, poll_ms=)` | **obsolete params** | `fetcher.py:642` calls `wait_for_content_stable(page)` with both defaults; test-only overrides. |
| `backend/worker/fetcher.py:627` | `dismiss_banners(..., timeout_ms=BANNER_DISMISS_TIMEOUT_MS)` | **obsolete param at the only production call site** | `banner_dismiss.py:377` default is already `BANNER_DISMISS_TIMEOUT_MS`; production passes its own default. |
| `backend/worker/page_prepare.py:59` | `_CONTENT_LENGTH_JS` — `document.body ? … : 0` guard | **dead branch** | `body` is always non-null for a rendered document (Chromium creates `<body>` for any HTML/text document). Guard is harmless; noted only for completeness. |
| `capture_evidence["attempts"]` (banner) | key | **unused evidence key** | Written `banner_dismiss.py:348`; zero production readers (see AUDIT-3-5 table). |
| `capture_evidence["capture_wall_clock_ms"]` | key | **unused evidence key** | Written `fetcher.py:694`; **zero** production readers repo-wide. Added by Phase 7 specifically for triage. |
| `capture_evidence["retry_count"]` | key | **unused evidence key** | Written `fetcher.py:693`; **zero** production readers repo-wide. Added by Phase 6. |
| `capture_evidence["stealth_applied"]` | key | **unused evidence key** | Written `fetcher.py:687`; only `tests/test_stealth.py` asserts on it. |
| `capture_evidence` scroll/stability keys (`scroll_steps`, `initial_height`, `final_height`, `scroll_time_ms`, `capped`, `stable`, `polls`, `final_length`) | keys | **unused evidence keys** | Written `page_prepare.py`; only consumed inside `_classify_capture_quality` (`fetcher.py:366-372`) inside the same call, then persisted unread. |
| `capture_evidence["actual_height"]`, `["screenshot_capped"]` | keys | **unused evidence keys** (persist only) | Written `fetcher.py:395-411`; consumed only by `_classify_capture_quality` in the same call. |
| `capture_evidence["cloudflare_challenge_detected"/"_resolved"]` | keys | **unused evidence keys** | Written `fetcher.py:259,274-276`; zero production readers (the failing path raises and stores nothing). |
| `capture_evidence["dismissed"]`, `["selector"]` | keys | **unused evidence keys** | Written `banner_dismiss.py:363-364`; zero production readers. This is Audit Phase 1's O-2 ("nobody aggregates misses") confirmed. |

**Explicitly NOT dead** (checked and cleared, so nobody re-chases them): `NAV_TIMEOUT_MS`, `SCREENSHOT_TIMEOUT_MS`, `MAX_HTML_BYTES`, `_hostnames_differ`, `_latest_nav`, `_challenge_markers`, `_clickable_in_viewport`, `_frames`, `_find_and_click`, `_post_click_settle`, `_resolve_confined`, `SCROLL_STEP_FRACTION`, `_STABLE_STEPS_NEEDED`, `MAX_ROBOTS_BYTES`, `PROBE_TIMEOUT_S`, `MAX_RAW_BYTES`, `_is_forbidden_address`, `normalize_content`, `layer1_hash_diff`, `CAPTURE_METHOD_VERSION` — all have real production readers (grep counts in `deadcode.out`).

---

## Opportunities for Optimization

| proposal | target file(s) | measured / projected impact | risk |
|---|---|---|---|
| `service_workers="block"` on the capture context (closes AUDIT-SA1-1; the *only* armoured arm) | `worker/fetcher.py:518` | Closes 2 of 2 measured unguarded request paths. Q3/Q4: internal-server hits `['/secret']` → `[]`. Fidelity cost: sites relying on a service worker render their fallback state. | **Low** — a handful of PWAs would capture the no-SW shell. Needs a capture-evidence signal so the fidelity loss is observable. |
| Add `context.route("**/*", guard)` alongside `page.route` for popup coverage | `worker/fetcher.py:543` | Closes the `window.open` vector (measured: internal hit `['/secret?via=popup']`). **Must be paired with the SW block** — Q2 proved `context.route` alone still lets the SW request through. | **Low** — guard runs on more requests; the per-host verdict cache already amortises it. |
| Run `probe_site`'s 3 UA fetches concurrently (`asyncio.gather`) | `worker/probe.py:231-235` | Measured serial wall clock **1.766 / 1.609 / 1.625 s** (400 ms injected latency, 4 sequential requests). Parallel ≈ 0.8 s → **~2.0×** on this fixture; the log's "~3×" tail claim is plausible on real RTTs. `max_connections=4` already provisioned (`probe.py:198`). | **Low** — must keep `desktop_chrome`'s headers for layer 6 and preserve `ua_variants` ordering. |
| Make the late-banner wait event-driven instead of a flat 3 s timeout | `worker/banner_dismiss.py:398-406` | **3.09–3.14 s removed from every capture of a banner-free page** (measured, 3 passes, spread 0.05 s). Against a measured 10.42–11.06 s end-to-end capture of a banner-free page that is **~28 % of wall clock**. | **Low** — a `MutationObserver`/short-poll probe replaces the flat wait; keep the same total budget as an upper bound. |
| Scroll a consent-iframe control into view before the viewport test | `worker/banner_dismiss.py:314-334` | Converts I2 from `dismissed: False` (60 attempts, 3.14 s) to a real dismissal — measured on the below-the-fold fixture. Recovers both the overlay **and** the lazy-content load the overlay's scroll-lock was suppressing. | **Low** — one extra CDP call only on elements that already passed `is_visible()`. |
| Re-snapshot `page.frames` before the final dismissal pass | `worker/banner_dismiss.py:393,407` | Measured: late-attaching iframe case sees `attempts=30` (1 frame) while `len(page.frames)==2`. Fix recovers late CMP iframes. | **Low** — one property read per pass. |
| Extend the screenshot guard to width; add `actual_width` to evidence | `worker/fetcher.py:377-416`, `worker/stealth.py` | Measured: a 20,008 px-wide page is captured uncapped at `screenshot_capped: False` / `capture_quality: "full"`. Closes the symmetric half of the documented raster limit. | **Low** — one extra `evaluate` reusing `_PAGE_HEIGHT_JS`. |
| Reuse one browser across attempts instead of `async_playwright()` + `launch()` per attempt | `worker/fetcher.py:510-516` | **Validated non-issue for the leak question.** 3 passes × 8 sequential `fetch_page` calls in one process (24 captures, `probe_mem.py`): RSS 46.6 → 47.1 MB, delta-from-first **+0.0 MB (pass 3), +0.0→+0.1 MB (pass 2), +0.0→+1.2 MB then decaying (pass 1)** — a plateau, not growth. A second independent run at 4× the page height (`probe_perf.py`, 8 captures at ~31 s each) was likewise flat: 52.2 → 51.5 MB. Only the browser cold-start latency (~0.3–0.5 s of a 10.8 s capture) remains. | **Medium** — sharing a browser across Celery tasks invites cross-capture state bleed (cookies, service workers, cache). A worker-local cached browser plus a strict per-capture fresh context is the lower-risk shape. Do **not** do this without Phase 5A's concurrency evidence. |
| Include the port in the SSRF verdict-cache key | `worker/fetcher.py:312` | Correctness only: measured `https://cdn.example.com:8443/x` inherited the verdict recorded for `https://cdn.example.com:443/y`. No SSRF impact today (host-scoped policy). | **Very low** — one f-string. |
| Roll the 17 write-only `capture_evidence` keys into one compact `completeness` sub-struct, and *actually consume* it | `worker/fetcher.py:680-698`, `worker/scan_tasks.py:280-292`, `worker/detection/types.py` | Structural: 17/19 keys are persisted and never read. Collapsing them shrinks `scans.capture_evidence` and makes AUDIT-3-5's remediation a one-field change. | **Medium** — a stored-format change, so `CAPTURE_METHOD_VERSION` (`:18`) must be considered. |
| Raise/remove `JANITOR_MAX_REMOVALS_PER_RUN = 500` and add terminal-state + age scoping | `worker/beat_tasks.py:55,271-291` | Today the janitor only removes **row-absent** directories, and no code ever deletes `Scan`/`Baseline` rows — so retention is unbounded for every surviving row. A time-budgeted loop drains any backlog in one run. | **Low** — housekeeping, already wrapped in a never-crash-the-worker guard. |
| Add a per-host request budget / post-block cooldown for `probe_site` | `worker/probe.py`, `app/scanning.py:36` | Measured 4 sequential requests per scan, tightest cadence ≥5 min ⇒ ~48 requests/hour/site with no ceiling, plus a `googlebot` UA on every one. | **Low** — policy state in Redis; must not block legitimate first-visit probing. |

---

## Summary

### Counts by classification
| classification | count | IDs |
|---|---|---|
| **NEW** | 5 | AUDIT-SA1-1 (**Critical**), AUDIT-SA1-2 (**High**), AUDIT-SA1-3, AUDIT-SA1-4, AUDIT-SA1-5 |
| **DEEPENED** | 7 | AUDIT-3-1, AUDIT-3-2, AUDIT-3-3, AUDIT-3-4, AUDIT-3-5, AUDIT-3-6, AUDIT-3-7, AUDIT-3-8 → **8** |
| **CONFIRMED (unchanged severity)** | 0 | — |
| **INVALIDATED (hypotheses tested and rejected)** | 2 | IDN consent-cookie rejection; screenshot-cap corrupt PNG |

Correction: **DEEPENED = 8** (AUDIT-3-1 through AUDIT-3-8), NEW = 5, INVALIDATED = 2. Total evidenced findings = **13**. No existing finding was invalidated.

**Highest severities:** 1 × **Critical** (AUDIT-SA1-1, SSRF guard bypass via Service Workers + popups), 3 × **High** (AUDIT-SA1-2 bot-wall false alerts; AUDIT-3-1 wrong-page/challenge-gate defeat; AUDIT-3-4 partial artifact write = data corruption), the remainder Medium/Low.

### Severity changes vs the original log
- `AUDIT-3-1` Medium → **High** (challenge-gate defeat + stale `final_url` crossing into `detection/dom.py`, proven 3/3).
- `AUDIT-3-4` Low → split: **High** for the non-atomic-write data-corruption path, **Medium** for the retention/orphan paths. (Deliberate re-rating, not inflation — the two halves meet different §6.4 bands.)
- `AUDIT-3-2` Medium, unchanged — but the stated root cause is now **wrong/incomplete**: nesting is a red herring; the two real causes are snapshot staleness and the never-scrolled viewport test.
- `AUDIT-3-3` Medium, unchanged — but its rationale is corrected (Chromium's own DNS cache makes the same-host rebinding less exploitable than logged) and it is **subsumed** in practice by AUDIT-SA1-1.

### Test files added
**None committed to the repo.** Rule 5 forbids committing a red test, and every case below currently **fails** against production code. Recommended additions for the remediation prompt (each is hermetic, localhost-only, and deterministic):

| proposed file | what it would prove | current status |
|---|---|---|
| `backend/tests/test_capture_ssrf_request_paths.py` | A service worker and a `window.open()` popup cannot cause the "internal" fixture server to receive **any** request (server-side hit counter, not a browser-side error code) | **would FAIL** — reproduces AUDIT-SA1-1 |
| `backend/tests/test_capture_post_dismissal_navigation.py` | After `dismiss_banners`, `FetchResult.final_url` and `FetchResult.html` describe the same page; a click that navigates into a challenge page must raise `_ChallengeUnsolvedError` | **would FAIL** — reproduces AUDIT-3-1 arm C |
| `backend/tests/test_banner_frame_freshness.py` | A consent iframe attaching after `dismiss_banners` starts, and a consent iframe below the fold, are both dismissed | **would FAIL** — reproduces AUDIT-3-2 causes 1 & 2 |
| `backend/tests/test_stealth_library_failure.py` | A raising `playwright-stealth` degrades gracefully (supplementary script still installed) and never escapes `fetch_page` as a non-`FetchError` | **would FAIL** — reproduces AUDIT-SA1-4 |
| `backend/tests/test_bot_wall_pages.py` | Akamai / DataDome / PerimeterX / AWS WAF / Imperva wall pages are classified as blocked, not captured as content; a `>= 400` scan capture never reaches `run_detection` | **would FAIL** — reproduces AUDIT-SA1-2 |

All probe scripts live at `C:\Users\Ns8pc\AppData\Local\Temp\opencode\wardress-session-a\capture\` (Rule 10) with outputs `*.out` beside them. Suggested hermetic conversions of the *already-passing* characterisations: `probe_unit.py` A1 (cache key), A3 (`content_sha256` invariant), A4 (detector truth table) and `probe_browser.py` B2 (screenshot cap geometry) are safe to add as passing characterisation tests.

### Commands run
```
# dead-code sweep (89 symbols, repo-wide rg per symbol)
cd backend; .\.venv\Scripts\python.exe -u ...\capture\deadcode_sweep.py
  → deadcode.out: 89 symbols; only `_name_attrs` has no live reference

# SSRF request-path matrix (3 passes each)
.\.venv\Scripts\python.exe -u ...\capture\probe_sw_ssrf.py     # first attempt (policy not yet stubbed) — control refused 127.0.0.1
.\.venv\Scripts\python.exe -u ...\capture\probe_sw_ssrf2.py    # timing miss (SW not yet controlling)
.\.venv\Scripts\python.exe -u ...\capture\probe_sw_ssrf3.py    # first half (ARM-1, ARM-2); run exceeded a 300 s shell timeout
.\.venv\Scripts\python.exe -u ...\capture\probe_sw_ssrf4.py    # full matrix Q1..Q4 → sw4.out
    Q1 page.route + SW allow   : guard saw INTERNAL=False, INTERNAL HITS=['/secret']
    Q2 context.route + allow   : guard saw INTERNAL=True,  INTERNAL HITS=['/secret']  (abort ineffective)
    Q3 page.route + SW block   : SW never registers,      INTERNAL HITS=[]
    Q4 context.route + SW block: SW never registers,      INTERNAL HITS=[]
pwsh run_sw5.ps1 (3 passes of probe_sw_ssrf5.py) → sw5_3pass.out
    B1 ACAO:* internal  : BODY:INTERNAL-SECTOKEN-… ; guard saw INTERNAL=False ; HITS=['/secret'] ; in page.content()=True
    B2 CORS-strict      : BODY:INTERNAL-SECTOKEN-… ; guard saw INTERNAL=False ; HITS=['/secret'] ; in page.content()=True
    → 3/3 passes byte-identical
.\.venv\Scripts\python.exe -u ...\capture\probe_popup_ssrf.py
    context pages=2 ; guard saw ['http://127.0.0.1:9061/'] ; INTERNAL HITS ['/secret?via=popup'] → bypassed=True

# banner navigation (3 passes of probe_banner_nav2.py) → bn2.out
    A control: final_url=/ctl            ; html=REAL-CONTENT   ; cf_detected=False ; quality=full
    B         : final_url=/ctl-to-other  ; html=WRONG-PAGE    ; cf_detected=False ; quality=full   (stale final_url)
    C         : final_url=/ctl-to-challenge; html=CHALLENGE-PAGE ("Just a moment...") ; cf_detected=False ; quality=full
    → 3/3 identical; fetch_page never raised

# frame staleness + placement (probe_browser.py B1) + placement (probe_frame_place.py)
    late iframe 2.5s: frames 1→2, attempts=30, dismissed=False, 3.141 s
    3-level nested : frames=4,  attempts=120, dismissed=False, 3.578 s
    I1 iframe top of body : box y=78.4   clickable_in_viewport=True  → dismissed True (36 attempts)
    I2 iframe after 2500px: box y=2578.4 clickable_in_viewport=False → dismissed False (60 attempts)

# screenshot extremes (probe_browser.py B2)
    40,016 px tall → capped 1366x16384, IEND ok, 307,719 B, 0.98 s
    20,008 px wide → screenshot_capped=False, actual_height=768, PNG 20008x768, IEND ok
    raw uncapped 40,016 px → 1366x40016, IEND ok, 754,858 B

# unit-level (probe_unit.py)
    A1 10 routes → 3 assert_url_allowed calls; cache key omits the port
    A2 19 URL shapes; IDN accepted by Chromium (B4); userinfo stripped; trailing dot preserved
    A3 content_sha256(None/bytes/int) → AttributeError / TypeError / AttributeError
    A4 13 wall shapes → only the 2 Cloudflare ones detected
    A6 _name_attrs({}) == {} → probe.py:128-131 unreachable
    A5 probe_site (400 ms injected latency) 1.766 / 1.609 / 1.625 s for 4 sequential requests

# detection consequence (probe_browser.py B5, production run_detection + fusion)
    DataDome 200 interstitial : risk 0.931 changed=True flagged=True
    Akamai 403 deny           : risk 0.917 changed=True flagged=True
    AWS WAF 403 block         : risk 0.927 changed=True flagged=True

# memory / timing (probe_perf.py; probe_mem.py = 3 repeats x 8 sequential captures)
    dismiss_banners on a banner-free page: 3.141 / 3.093 / 3.094 s (30 attempts each)
    8 sequential fetch_page, 108,000px fixture (~31 s each): RSS 52.2 -> 51.5 MB (delta +0.1 then -0.7 MB)
    24 sequential fetch_page, 900px fixture, 3 passes (probe_mem.py):
      pass 1: 46.6 -> 47.0 MB, delta_from_first +0.0 .. +1.2 .. +0.4
      pass 2: 47.0 -> 47.1 MB, delta_from_first +0.0 .. +0.1
      pass 3: 47.1 -> 47.1 MB, delta_from_first +0.0 (flat, 8/8)
      capture wall clock 10.42 - 11.06 s per capture (of which 3.1 s is the banner budget)
      => no unbounded RSS growth across sequential captures; a plateau, not a leak
    probe_site on localhost: 0.125 / 0.015 / 0.000 s (local server too fast to be informative -> replaced by the latency-injected A5)
    incidental: probe_mem.py's first run had no server -> ERR_CONNECTION_REFUSED was classified transient,
    retried once, and surfaced as FetchError("Fetch failed: network error (...)") - the Phase-6 retry contract behaving as designed
```

**No production file was modified. No git command was run. No commit was made.** Verification of "the existing suite still passes" was not required because no repo file changed; the probe suite ran against unmodified production code throughout.

### Coverage honestly stated as NOT done
- No live-site / stress-catalog testing (Phase 5A owns it per the coordinator's instruction) — no finding here is asserted against a real vendor's live wall page; AUDIT-SA1-2 uses vendor-accurate synthetic wall shapes.
- No DB-backed verification (baseline/scan row transitions were code-traced against `scan_tasks.py`, not exercised against Postgres). The "Scan row stranded in `running`" claim in AUDIT-SA1-4 is a code trace, not an observed row.
- The AUDIT-3-4 non-atomic-write path was not *triggered* by an actual mid-write kill — it is a code-ordering proof, not a measurement.
- `probe_tls`'s unpinned rebinding window was confirmed by code read only; no exploit was built.
- Chromium here is headless software-rasterised; AUDIT-SA1-5's GPU-bound failure mode could not be provoked.
- The scroll-shrink path (AUDIT-3-8) was not triggered live; it remains a code-trace finding, as originally logged.
