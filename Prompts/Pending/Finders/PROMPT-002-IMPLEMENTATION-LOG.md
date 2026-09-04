# PROMPT-002 — Capture Hardening & Detection Accuracy — Implementation Log

> Dedicated progress log for the **PROMPT-002 fourteen-phase implementation effort**.
> One entry per phase. Each phase's agent appends its entry here after completing work.
> This file + `PROMPT-002-capture-hardening-and-detection-accuracy-v2.md` are the
> entire state of this effort across sessions.
>
> **If it isn't written here, it did not happen.**

> **Baseline (Phase 1 must fill this in — do NOT invent numbers):** record the pre-Phase-1 full-suite result here — exact command (e.g. `cd backend && uv run --frozen pytest -q`), pass/fail/skip counts, and wall time — before making ANY code change. The suite requires the live Postgres test database (`backend/tests/db_harness.py`; default `postgresql+asyncpg://wardress:wardress@127.0.0.1:5433/wardress_test` — if it is not already running, start the disposable container with the `docker run` command that module prints on failure). This recorded baseline is the Rule-4 "at or above baseline" reference for every phase.

## Entry Format (each phase appends below, newest last)

```
### [DONE / PARTIAL] PROMPT-002 Phase N — <phase title>

- **Prompt**: PROMPT-002-capture-hardening-and-detection-accuracy-v2.md
- **Session date**: YYYY-MM-DD
- **Goal**: one paragraph — what this phase set out to do
- **Files changed**: path/to/file.py(:lines), ...
- **Key design decisions**: chosen approaches vs rejected alternatives, with reasons
- **Constraints honored**: SSRF policy, privacy tripwires, lint baselines, test baselines
- **Edge cases handled**: the full list from Gauntlet Step 3, each with disposition
- **Tests added**: file:test_name — what each proves (with failing-before proof notes)
- **Full regression results**: exact commands + pass/fail counts for every suite
- **Manual verification performed**: anything not automatable (e.g., live site captures)
- **Residual risk / follow-ups**: anything deferred, with justification
- **New leads observed**: issues spotted but out of scope
- **Commit**: <short hash> — <message>
- **Next phase kickoff prompt**: (delivered in chat only — never written to this log)
```

---

### Baseline (recorded pre-Phase-1, before ANY code change)

- **Command**: `cd backend && uv run --frozen pytest -q`
- **Result**: **1087 passed, 1 warning in 925.24s (0:15:25)**. The single warning is the pre-existing
  `apprise/utils/pgp.py:48 DeprecationWarning: 'imghdr' is deprecated` (Python 3.12) — not ours, not touched.
- **Backend lint baseline**: `cd backend && uv run --frozen ruff check .` → "All checks passed!" (exit 0).
- **Frontend baseline** (Rule 4, no frontend files touched in Phase 1): `pnpm test` → **20 files / 129 passed**
  (43.36s); `pnpm exec tsc -b --noEmit` → exit 0, no output; `pnpm exec oxlint src` → **0 errors, 12 warnings**
  (matches the ≤12-warning baseline in Rule 4).
- **Test-DB note**: the disposable Postgres for the suite was started from the already-local `postgres:16`
  image (`docker run -d --name wardress-test-pg ... -p 127.0.0.1:5433:5432 postgres:16`) instead of
  `postgres:16-alpine`, because pulling the alpine tag timed out repeatedly in this session. Functionally
  identical for the harness (same engine major, same port/credentials); noted per Rule 12 rather than
  silently substituted.

*Prompt-prose deviation (Rule 12)*: Rule 4 says the backend baseline is "currently ~540+ passed" — the
actual measured baseline is **1087 passed**. The suite has grown since the prompt was written; the
measured number above is the reference for every later phase.


*(Phase entries append below)*

### [DONE] PROMPT-002 Phase 1 — Stealth & Anti-Bot-Detection Hardening

- **Prompt**: PROMPT-002-capture-hardening-and-detection-accuracy-v2.md
- **Session date**: 2026-09-03
- **Goal**: Make Playwright captures indistinguishable from a real Chrome browser to naive
  WAF/bot-detection: unbranded current-Chrome UA, real context shape (locale/timezone/scheme/
  laptop viewport), `--disable-blink-features=AutomationControlled` at launch, playwright-stealth
  evasions plus supplementary init scripts — without touching the SSRF policy or the detection
  pipeline.
- **Files changed**:
  - `backend/pyproject.toml` — `playwright-stealth==2.0.3` added to `[project.dependencies]`
    (detection-engine section, with rationale comment); verified compatible with the pinned
    `playwright==1.61.0` and Python 3.12.
  - `backend/uv.lock` — relocked via `uv add` (single new package, 171 resolved).
  - `backend/worker/stealth.py` — NEW: `BROWSER_LAUNCH_ARGS`, `CAPTURE_USER_AGENT`
    (Chrome/152.0.0.0, current stable verified against endoflife.date 2026-09),
    `CONTEXT_LOCALE/TIMEZONE_ID/COLOR_SCHEME/VIEWPORT`, `apply_stealth(context)` =
    `Stealth(navigator_languages_override=("en-US","en")).apply_stealth_async(context)` +
    supplementary init script (navigator.webdriver full removal, `window.cdc_*` stripping,
    Permissions.query notifications patch, plugins/mimeTypes normalization when still empty).
    Graceful degradation: `Stealth is None` → warning log + no-op (dev environments).
  - `backend/worker/fetcher.py:111-141` — launch with `BROWSER_LAUNCH_ARGS`; context created with
    the stealth-module shape (`CAPTURE_USER_AGENT`, locale en-US, tz America/New_York, light,
    1366×768, `ignore_https_errors=False` KEPT); `apply_stealth(context)` called BEFORE
    `new_page()` and BEFORE `page.route("**/*", _make_ssrf_route_guard(...))`. Old
    `USER_AGENT = "...Wardress/0.1 SiteMonitor"` constant deleted (no other referencers existed).
  - `backend/tests/test_stealth.py` — NEW, 8 tests (see below).
  - `Prompts/Pending/Finders/PROMPT-002-IMPLEMENTATION-LOG.md` — baseline + this entry.
- **Key design decisions**:
  - Chose `playwright-stealth==2.0.3` (context-level `apply_stealth_async`) over Camoufox
    (breaks Chromium pipeline), nodriver (abandons Playwright API), and DIY-only init scripts
    (maintenance burden) — exactly as the spec's chosen approach.
  - Supplementary patches are individually try/catch-guarded and conditional (plugins only
    normalized when still empty) so they can never break page JS nor conflict with the library's
    own plugin patch.
  - Guard ordering kept literal: stealth (init scripts) → `new_page()` → route guard, so the
    guard remains the last word on every request (rule 11 / §4.1).
  - No `--no-sandbox`: the spec says not to assume; the container smoke-check proved the new
    launch args work in the mcr playwright image without it.
- **Constraints honored**:
  - SSRF policy untouched (`app/ssrf.py` unmodified); top-level check and final-URL recheck
    unchanged (test_phase35's offload-seam test still passes); route guard installed after
    stealth and proven to still block loopback subresources post-stealth.
  - Privacy: no new outbound requests introduced; stealth adds no network activity.
  - Lint baselines: `uv run --frozen ruff check .` clean; frontend untouched.
  - Backward compat: `FetchResult`, artifacts, and schema unchanged; probe deliberately NOT
    stealthed (layer 7 design); docs unaffected (nothing in docs pins capture UA/headless
    behavior — layer-7 doc explicitly excludes the rendered DOM from UA comparison).
- **Edge cases handled (Gauntlet Step 3)**:
  - Site categories: N/A — stealth is site-agnostic; no navigation/scroll logic changed.
  - Bot protection tiers: naive detection covered (webdriver, chrome.runtime, codecs, WebGL,
    plugins, languages, cdc_*); advanced (Cloudflare Turnstile, DataDome, PerimeterX) explicitly
    NOT claimed — Phase 2 adds challenge detection, Phase 13 validates honestly.
  - Content loading patterns: N/A — Phases 3–4 scope.
  - Consent/banner patterns: N/A — Phase 5 scope.
  - Failure modes: stealth init scripts individually guarded so a browser change degrades the
    patch, never the page; missing-package path degrades with warning; container launch proven
    (no sandbox flag needed); screenshot/HTML paths unchanged.
  - Concurrency: `Stealth()` instantiated per `apply_stealth` call — stateless, per-context, no
    shared capture state; SSRF verdict-cache semantics untouched.
  - Backward compatibility: capture-method change may cause a ONE-TIME delta on first scan after
    deploy for UA/render-sensitive sites (different UA/viewport than old captures) — accepted;
    detection still runs normally over it (see residual risk).
  - Performance: <1KB of init scripts, per-context, no added network round-trips; capture time
    unchanged (2s settle retained).
- **Tests added** (`backend/tests/test_stealth.py`, all hermetic — local ThreadingHTTPServer on
  127.0.0.1, real Chromium skipped-with-reason if absent):
  - `test_apply_stealth_missing_package_degrades_gracefully` — missing-package path logs warning,
    returns, never touches the context (would fail before: function didn't exist).
  - `test_capture_user_agent_no_longer_self_identifies` — no branded UA anywhere in fetcher
    source; UA is valid unbranded desktop Chrome (FAILED-before: `fetcher.USER_AGENT` was
    `Wardress/0.1 SiteMonitor`).
  - `test_fetch_page_applies_stealth_before_route_guard` — source-order contract
    (apply_stealth < route guard) + launch args referenced (Phase-35-style seam check).
  - `test_apply_stealth_fresh_context_does_not_crash` — stealthed context still loads pages,
    evaluates JS, extracts content (patch doesn't break Playwright functionality).
  - `test_navigator_webdriver_undefined_after_stealth` — old-path proof embedded: arg-less
    launch reports `navigator.webdriver === true`; capture path reports `undefined`.
  - `test_ssrf_route_guard_still_blocks_internal_after_stealth` — loopback navigation aborted
    (ERR_BLOCKED_BY_CLIENT, zero server hits) under default policy post-stealth; same guard
    passes under `allow_private_networks=True` (proves the block was the guard, not the browser).
  - `test_fetch_page_with_stealth_captures_local_site` — end-to-end fetch_page: HTML marker,
    PNG screenshot, 200, and the request arrived with the unbranded Chrome UA.
  - `test_fetch_page_still_refuses_blocked_urls` — top-level SSRF refusal unchanged.
  - Standalone run: 8/8 pass in ~6.6s.
- **Full regression results**:
  - Baseline (pre-change): `cd backend && uv run --frozen pytest -q` → **1087 passed, 1 warning
    in 925.24s (0:15:25)** (see Baseline block above).
  - Post-change: same command → **1095 passed, 1 warning in 914.31s (0:15:14)** (1087 + 8 new;
    warning = pre-existing apprise `imghdr` DeprecationWarning). At/above baseline: PASS.
  - `uv run --frozen ruff check .` → All checks passed (exit 0).
  - Frontend (unchanged this phase; baseline run): `pnpm test` 20 files / 129 passed;
    `tsc -b --noEmit` exit 0; `oxlint src` 0 errors / 12 warnings — all green.
- **Manual verification performed (Rule 14 container smoke-check)**: rebuilt the worker image
  from the new lockfile (`docker compose build worker`; the RUNNING stack was NOT restarted) and
  ran a smoke script in a temporary container (`docker compose run --rm --no-deps worker python
  /tmp/smoke.py`): playwright-stealth importable in-image; launch args + context shape work in
  the container without `--no-sandbox`; `navigator.webdriver` → undefined; live capture of
  https://example.com via the full `fetch_page` path → HTTP 200, valid HTML, PNG screenshot with
  the Chrome/152 UA. Scratch script deleted; temp container auto-removed.
- **Residual risk / follow-ups**:
  - playwright-stealth only defeats naive detection; hard WAFs still block (accepted by spec;
    Phase 2 makes persistent challenges a hard, operator-visible failure; Phase 13 validates).
  - One-time post-deploy delta risk on UA/viewport-sensitive sites (first scan after the new
    capture deploys may flag a change that is really the capture-method change; single event).
  - The running Docker stack still runs the OLD image until the user rebuilds/restarts
    (update.ps1) — user-managed per rule 14.
- **New leads observed**:
  - probe.py UAs still `Chrome/126.0.0.0` — Phase 2 scope.
  - The capture's browser/context shape now lives in `worker/stealth.py`; later capture phases
    (scroll, settle, banners) should extend stealth.py rather than re-inline constants.
- **Prompt-claim deviations (Rule 12)**:
  1. Phase 1's test obligations list "Test Cloudflare challenge detection logic" — that code is
     Phase 2's deliverable and does not exist yet; the challenge-detection tests belong to
     Phase 2 and were deferred there (not skipped).
  2. Rule 4 prose says baseline is "~540+ passed"; the measured baseline is 1087. Recorded.
  3. playwright-stealth 2.0.3 sets `navigator.webdriver` to `false`, not `undefined`; the spec's
     obligation ("undefined (not true)") is met by a supplementary init script that removes the
     property entirely — stronger than the library default, matching the spec letter.
  4. Spec mandates `viewport={"width": 1366, "height": 768}`; old code used 900 height — the
     change is intentional per spec and noted under residual risk.
- **Commit**: 7ae0bf9 — feat(capture1): stealth & anti-bot-detection hardening for captures
- **Next phase kickoff prompt**: (delivered in chat only — not persisted in this log)

### [DONE] PROMPT-002 Phase 2 — Probe UA Refresh & Cloudflare Challenge Detection

- **Prompt**: PROMPT-002-capture-hardening-and-detection-accuracy-v2.md
- **Session date**: 2026-09-04
- **Goal**: Update the probe's rotated User-Agents to the current Chrome era (they said
  Chrome/126.0.0.0, ~2 years stale, and no longer matched Phase 1's capture UA), and make
  bot-protection challenges an operator-visible hard failure: detect Cloudflare challenge/block
  pages after capture settle, wait a bounded window for the JS challenge to auto-solve, and
  fail the capture with a user-safe error if it persists — never store challenge HTML as site
  content. Write the challenge-detection tests that Phase 1 explicitly deferred, and document
  the operator-visible change in docs/usage.mdx (Rule 13).
- **Files changed**: backend/worker/probe.py(:41–56 — USER_AGENTS refresh); backend/worker/fetcher.py
  (module docstring; challenge constants + pure helpers `is_challenge_title`,
  `looks_like_challenge_page` + `_challenge_markers`/`_latest_nav`/`_wait_out_challenge`;
  fetch_page integration: main-frame response tracking, challenge deadline, post-settle
  `_wait_out_challenge` call, latest-response status/headers for FetchResult);
  backend/tests/test_probe_ua.py (new, 4 tests); backend/tests/test_cloudflare_detection.py
  (new, 9 tests); docs/usage.mdx (new "Capture Failures & Bot Protection" subsection).
- **Key design decisions**:
  - UA refresh: desktop_chrome + googlebot → Chrome/152.0.0.0 — verified against the
    endoflife.date Chrome API (generated 2026-09-03: major 152 released 2026-08-25 is the
    current stable), matching Phase 1's CAPTURE_USER_AGENT so layer 7's raw-vs-render
    comparison stays era-consistent. mobile_safari → iPhone OS 26_0 / Safari 26.0 (current
    Apple era; it carries no Chrome token by design). Rejected: keeping 126 (stale UAs are a
    bot-detection gift) and inventing newer-than-stable versions.
  - Challenge detection lives in fetcher.py as pure, browser-free helper functions (unit-
    testable) plus one async wait loop; no new module — the spec's Phase-2 target-file list
    names only probe.py and fetcher.py.
  - Indicators OR-combined per spec: canonical challenge title markers ("just a moment",
    "attention required" — TITLE only, never body text), Cloudflare-specific element CLASSES
    via `document.querySelector('.cf-challenge-running, .cf-error-details')` (a blog post
    *writing about* these class names cannot false-positive), and HTTP 403 + cf-ray header.
  - Wait-and-recheck: poll every CHALLENGE_POLL_MS (1s) up to CHALLENGE_WAIT_MS (10s), with
    the whole window bounded by the REMAINING navigation budget (deadline captured before
    goto) — a challenged capture never exceeds NAV_TIMEOUT_MS + SETTLE_MS wall clock, and an
    exhausted budget fails immediately. Production constants are spec values; tests patch
    them for speed.
  - Main-frame response tracking (`page.on("response")` filtered to main-frame navigation
    requests): a challenge that auto-solves RELOADS the page, so the goto response (the
    challenge's 403) goes stale. Without this, a successfully-solved challenge would still
    fail `_capture_baseline`'s http_status ≥ 400 trust gate — defeating the entire feature.
    FetchResult now records the LATEST main-frame response's status/headers.
  - Every re-check combines current DOM markers with the LATEST tracked response. The first
    implementation re-checked DOM-only; the 403+cf-ray integration test caught that a
    calm-DOM block page would be wrongly treated as "cleared" on the first poll — fixed and
    locked in by a regression test.
- **Constraints honored**: SSRF policy untouched — the route guard still runs after stealth
  and before anything else; challenge logic runs only AFTER the final-URL SSRF re-validation
  (the security check is never delayed); `app/ssrf.py` unread/unchanged. The probe stays
  intentionally un-stealthed (layer 7 raw-vs-raw contract preserved). No detection-layer
  files touched. Lint baseline: `ruff check .` exit 0. Test baselines at/above (1108 vs 1095).
  Rule 13 sync: docker-compose.yml, .env/.env.example and scripts/ verified to need NO
  change this phase (no new env vars, dependencies, services, or install steps —
  playwright-stealth and the Chromium base image date to Phase 1); docs/usage.mdx updated
  with the operator-visible behavior change using no constants pinned in prose.
- **Edge cases handled** (Gauntlet step 3, each verified):
  - No bot protection (static site, SPA): behavior unchanged — one cheap `page.evaluate`
    plus one monotonic clock read; proven by the similar-text test and the container smoke
    capture of example.com.
  - Cloudflare JS challenge (title + cf-challenge-running): bounded wait-and-recheck, then
    real-page capture (auto-solve fixture flips at 3.2s, after the 2s settle, so the poll
    loop is what observes the solve).
  - Managed block page (403 + cf-ray, calm DOM): hard FetchError via the status/header path
    through the real stack.
  - Challenge auto-solves via reload: latest-response tracking records the real page's
    status/headers (no stale-403 false failure).
  - Body text merely mentioning the markers: no false positive (title/class-only indicators).
  - `page.evaluate` failing mid-check (page closed/navigating): `_challenge_markers`
    degrades to not-a-challenge — ambiguous detection never fails a capture.
  - Navigation budget exhausted while waiting: immediate FetchError, no extra wall clock.
  - Non-Cloudflare WAFs (Akamai/DataDome/PX/Imperva/AWS WAF): NOT detected — capture
    proceeds exactly as before (Phase-2 scope is Cloudflare; logged below).
  - Stealth absent (dev environments): detection still fires (independent of stealth).
  - Baseline vs scan failure semantics: no scan_tasks change needed — FetchError from
    fetch_page already maps to BaselineStatus.failed (`_capture_baseline`) and
    ScanStatus.failed + ScanVerdict.error (`_run_scan`) with the user-safe message.
  - Redirect-then-challenge: final-URL SSRF re-validation still runs before challenge logic.
- **Tests added** (all with failing-before proofs):
  - tests/test_probe_ua.py::test_ua_chrome_variants_match_the_capture_era — FAILED-before:
    probe said Chrome/126 while the capture said Chrome/152; locks era-consistency + a
    ≥130 staleness tripwire.
  - test_ua_strings_are_syntactically_valid — canonical token shape (Mozilla/5.0,
    AppleWebKit, KHTML-like-Gecko, trailing Safari token, four-part Chrome versions).
  - test_ua_keys_are_exactly_the_layer7_rotation — the reference/crawler/mobile key set is
    the layer-7 contract; renaming a key would silently change what layer 7 compares.
  - test_probe_site_sends_each_rotated_ua — end-to-end rotation still works (MockTransport;
    per-variant UA header observed, all variants healthy).
  - tests/test_cloudflare_detection.py::test_fetch_page_raises_when_challenge_persists —
    FAILED-before: pre-Phase-2 fetch_page returned the challenge HTML as a successful
    FetchResult; now raises FetchError with the exact user-safe message.
  - test_fetch_page_raises_on_403_cf_ray_block_page — FAILED-before vs the first cut:
    exposed the DOM-only re-check flaw; a calm-DOM 403 block page now hard-fails.
  - test_fetch_page_waits_out_auto_solving_challenge — in-place solve observed by the poll
    loop; real page captured (200, PNG, marker element gone).
  - test_fetch_page_does_not_false_positive_on_similar_text — body-text mentions never
    trigger (title/class-only design).
  - test_challenge_detection_works_without_stealth — detection is stealth-independent.
  - test_challenge_probe_js_reads_title_and_classes — the exact DOM probe fetch_page uses,
    on a stealthed context, reports a normal page cleanly.
  - Unit tests: test_is_challenge_title_matches_only_canonical_markers,
    test_looks_like_challenge_page_indicator_paths,
    test_looks_like_challenge_page_negative_paths (incl. CF-Ray case normalization and
    200-with-cf-ray NOT being an indicator).
  - Standalone run: `uv run --frozen pytest tests/test_cloudflare_detection.py
    tests/test_probe_ua.py tests/test_probe.py -v` → 24 passed in 147.98s (browser tests
    are slow on this host: ~30s each, mostly Chromium launch).
- **Full regression results**:
  - Backend: `cd backend && uv run --frozen pytest -q` → **1108 passed, 1 warning in
    1094.92s (0:18:14)** (baseline 1095 + exactly the 13 new tests; the single warning is
    the pre-existing apprise `imghdr` DeprecationWarning). At/above baseline: PASS.
  - `uv run --frozen ruff check .` → All checks passed (exit 0).
  - Frontend (no frontend files touched; Rule 4 baseline re-run): `pnpm test` → **129
    passed** (38.82s); `pnpm exec tsc -b --noEmit` → exit 0; `pnpm exec oxlint src` →
    **0 errors, 12 warnings** (matches the ≤12-warning baseline). All green.
- **Manual verification performed (Rule 14)**: rebuilt the worker image from the working
  tree (`docker compose build worker` — the RUNNING stack was not restarted or disturbed)
  and ran a scratch smoke script in a temporary container (`docker compose run --rm
  --no-deps -v ... worker python /tmp/smoke.py`): Chrome/152 UAs live in-image for capture
  and all three probe variants; live `fetch_page("https://example.com/")` → HTTP 200, valid
  HTML, PNG screenshot; `probe_site("https://example.com/")` → all three UA variants HTTP
  200, no errors; example.com does not trip challenge detection. Scratch script deleted
  (it lived outside the repo per rule 9); temp container auto-removed.
- **Residual risk / follow-ups**:
  - Title-substring detection is a spec-chosen tradeoff: a non-Cloudflare page deliberately
    TITLED "Just a moment…" would be misdetected after the wait window. Real Cloudflare
    pages also carry the marker classes, so requiring title+class conjunction is a possible
    future hardening (Phase 13 validation candidate).
  - Only Cloudflare challenges are detected; Akamai/DataDome/PerimeterX/Imperva/AWS WAF
    block pages still capture as content (pre-existing behavior; possible future phase).
  - One-time post-deploy delta risk from the UA refresh: layer 7 is intra-scan
    (raw-vs-raw), so no baseline-vs-scan delta class is introduced; sites that cloak by
    Chrome version may show a one-time layer-7 score shift on the first post-deploy scan.
  - Event-timing race: if a challenge reload's response event has not been dispatched by a
    poll instant, the stale fallback status can extend the wait by one poll interval
    (self-healing — the next poll re-checks the fresh response).
  - The running Docker stack still runs the OLD image until the user rebuilds/restarts
    (update.ps1) — user-managed per rule 14 (this phase rebuilt the image for smoke
    testing only).
- **New leads observed**:
  - Cloudflare Turnstile "Verify you are human" interstitials sometimes need interaction,
    not just waiting; if operators report timeouts on those, a future phase could detect
    the turnstile iframe explicitly (Phase 5's click machinery may be reusable).
  - fetcher's 2s settle window is untouched — Phase 3 scope.
  - docs/layers/7-cloaking.mdx names no UA versions — nothing to sync there (verified).
- **Prompt-claim deviations (Rule 12)**:
  1. No Phase-2 line-number/signature claims existed to verify wrong; every checked claim
     (probe UAs at Chrome/126.0.0.0, un-stealthed probe, layer 7 raw-vs-raw, FetchError →
     hard failed row) matched the tree.
  2. "The challenge wait must respect the overall navigation timeout budget" does not
     define the budget — implemented as: challenge wait bounded by the remaining
     NAV_TIMEOUT_MS window (deadline captured before goto), so total capture wall clock is
     NAV_TIMEOUT_MS + SETTLE_MS at most. Recorded here as the concrete interpretation.
  3. The spec's exact FetchError message is implemented verbatim (module constant
     BOT_PROTECTION_ERROR) — no drift.
  4. "update all three UA strings … match real Chrome versions": mobile_safari is an
     iOS/Safari UA by design (forcing a Chrome token there would be wrong); updated to
     iOS 26.0/Safari 26.0. desktop_chrome and googlebot carry Chrome/152.0.0.0 (current
     stable per the endoflife.date Chrome API, generated 2026-09-03).
  5. Rule 13 prose mentions syncing docker-compose.yml/.env — verified nothing needs
     syncing this phase (no operator-configurable surface added); only docs/usage.mdx
     changed, as the spec requires for the operator-visible behavior change.
- **Commit**: 55a1ff0 — feat(capture2): probe UA refresh + Cloudflare challenge detection
- **Next phase kickoff prompt**: (delivered in chat only — not persisted in this log)

*(Phase 3 appends below.)*

### [DONE] PROMPT-002 Phase 3 — Smart Scrolling & Lazy-Content Capture

- **Prompt**: PROMPT-002-capture-hardening-and-detection-accuracy-v2.md
- **Session date**: 2026-09-04
- **Goal**: Make full-page captures actually see the whole page: incremental
  auto-scroll top-to-bottom so IntersectionObserver/scroll-event lazy content
  loads before capture, a content-stability wait after scrolling, the 2s settle
  raised to 5s, and nav/screenshot timeouts raised to match — all composed with
  Phase 2's challenge flow and without touching SSRF, detection, or scan_tasks.
- **Files changed**:
  - `backend/worker/page_prepare.py` — NEW: `auto_scroll_page(page, *,
    max_scroll_time_ms, step_pause_ms)` and `wait_for_content_stable(page, *,
    timeout_ms, poll_ms)`; both never raise, both return evidence dicts
    (`scroll_steps/initial_height/final_height/capped/scroll_time_ms` and
    `stable/polls/final_length`).
  - `backend/worker/stealth.py` — extended (per the Phase-1 carry-over note)
    with the capture page-preparation timing family: `SETTLE_MS=5_000` (moved
    from fetcher.py, was 2_000), `MAX_SCROLL_TIME_MS=20_000`,
    `SCROLL_STEP_PAUSE_MS=300`, `CONTENT_STABLE_TIMEOUT_MS=5_000`,
    `CONTENT_STABLE_POLL_MS=500`; module docstring updated to name the timing
    shape as part of this module's charter.
  - `backend/worker/fetcher.py` — `NAV_TIMEOUT_MS` 45_000→60_000,
    `SCREENSHOT_TIMEOUT_MS` 30_000→45_000; `SETTLE_MS` now imported from
    stealth; scroll+stability sequence inserted into `fetch_page` AFTER
    `_wait_out_challenge` and BEFORE `page.content()`/screenshot, with
    debug-level evidence logging.
  - `backend/tests/test_page_prepare.py` — NEW, 11 tests (8 mock-page unit
    tests + 3 hermetic real-browser tests; see below).
  - `docs/usage.mdx` — new "Scrolling & Lazy Content" subsection (auto-scroll
    behavior + one-time post-upgrade delta warning), next to the Phase-2
    "Capture Failures & Bot Protection" subsection whose style it follows.
- **Key design decisions**:
  - Scroll runs AFTER `_wait_out_challenge`, not before (the spec's Phase-3
    flow snippet predates Phase 2): challenge re-checks must see the settled
    DOM, a challenge page must never be scrolled (scrolling could interfere
    with the solving JS), a persistent challenge fails before any scroll time
    is spent, and a challenge that auto-solves via reload leaves a fresh page
    for the scroll pass. Rule-12 deviation recorded below.
  - Stop condition strengthened beyond the spec's literal "height stops
    growing for 2 consecutive steps": that alone would stop a STATIC tall page
    mid-scroll (height never grows, so the check fires immediately), leaving
    below-fold lazy content unloaded. The loop stops when at the bottom (or
    provably unable to scroll — inner-scroll-container SPAs) AND height stable
    for 2 consecutive steps, or at the 20s hard cap.
  - Scroll step = `window.innerHeight * 0.8` with a 300ms pause per step
    (spec values), so consecutive steps overlap and IntersectionObserver fires
    reliably; single jump-to-bottom and force-load-JS approaches rejected per
    the spec's design note.
  - Timing constants centralized in `worker/stealth.py` per the Phase-1
    carry-over note ("later capture phases (scroll, settle, banners) should
    extend stealth.py rather than re-inline constants") — `SETTLE_MS` moved out
    of fetcher.py (no external referencers existed; verified by search).
  - Height probe uses `max(body.scrollHeight, documentElement.scrollHeight)`
    — SPA pages sometimes report body scrollHeight 0 with scrolling on the
    document element; spec named only body.
  - Evidence is debug-logged in fetcher this phase; `FetchResult` stays
    unchanged — Phase 4 owns `capture_evidence` storage and the screenshot
    height cap.
- **Constraints honored**:
  - SSRF: `app/ssrf.py` untouched; the route guard stays installed throughout
    scrolling (lazy-load subresources flow through it exactly like any other
    page request); scrolling only calls scrollBy/scrollTo — it never navigates,
    so no new navigation/redirect surfaces exist to validate; the final-URL
    SSRF recheck still runs before any of the new work.
  - `worker/scan_tasks.py`, `worker/detection/`, `worker/probe.py` untouched;
    `auto_scroll_page`/`wait_for_content_stable` never raise, so
    `_capture_baseline`/`_run_scan` failure semantics are bit-identical.
  - Privacy: no new outbound request categories (lazy-load requests are the
    site's own, and were always fetchable); no capture content leaves the
    pipeline.
  - Lint: `uv run --frozen ruff check .` → exit 0. Frontend untouched (Rule 4
    baseline re-run, all green — see regression results).
  - Rule 13: `docker-compose.yml`, `.env.example`, `scripts/`, and
    `pyproject.toml` verified to need NO change (no new deps, env vars,
    services, or install steps); `docs/usage.mdx` updated for the
    operator-visible behavior changes.
  - Celery budget re-verified: `task_soft_time_limit=300` (celery_app.py);
    worst-case capture 60+5+(≤10 challenge)+20+5+45 = ≤145s, plus ~20s probe —
    well under the soft limit (spec's 135s arithmetic, plus the challenge
    window it did not count).
- **Edge cases handled** (Gauntlet step 3, each verified):
  - Static short page (height ≤ viewport): zero scroll steps, no waits
    (unit + real-browser test).
  - Static tall page: walks fully to the bottom, then returns to top
    (real-browser test).
  - Lazy-growing page: walk continues past the initial height until the grown
    bottom is stable (unit test with scripted growth).
  - Infinite-scroll page: hard 20s cap trips, `capped=True`, capture proceeds
    at reached height (unit test).
  - Inner-scroll-container SPAs where body never scrolls: stall guard (scroll
    position AND height unchanged 2 consecutive steps) breaks the loop instead
    of burning the full cap.
  - Page JS crashes mid-probe (evaluate raises at height probe, at scroll
    step, or at content probe): all caught, evidence returns partial, capture
    continues (unit tests; never-raise contract).
  - Churning DOM (timestamps/tickers): stability wait exhausts its 5s budget,
    reports `stable=False`, capture proceeds (unit test).
  - Challenge pages: never scrolled (challenge wait precedes scroll);
    challenge that auto-solves via reload is scrolled as the real page.
  - Sticky headers/footers: unchanged — full_page screenshot handles them
    natively (spec note).
  - iframes: unchanged limitation — top-frame serialization only.
  - Backward compatibility: FetchResult/artifacts/schema unchanged; the
    ONE-TIME baseline-vs-scan delta from newly-visible below-fold content is
    documented for operators in docs/usage.mdx (self-heals after rebaseline).
  - Concurrency: no shared state — per-capture page objects and evidence
    dicts only.
- **Tests added** (`backend/tests/test_page_prepare.py`; standalone run:
  **11 passed in ~12s**):
  - Mock-page unit tests (scripted `evaluate`/`wait_for_timeout` double):
    - `test_auto_scroll_walks_growing_page_to_the_bottom` — walk continues
      through two lazy-growth bursts, stops at the grown bottom, returns to
      top, records initial/final heights and one 300ms pause per step.
    - `test_auto_scroll_time_caps_infinite_page` — capped=True at the hard
      cap; the loop can never hang the capture.
    - `test_auto_scroll_survives_js_errors` — never-raise contract for both
      the initial probe and the scroll step; partial evidence returned.
    - `test_auto_scroll_skips_unscrollable_page` — height ≤ viewport: zero
      steps, zero waits.
    - `test_auto_scroll_step_overlaps_viewport` — step is exactly 0.8×
      viewport (IntersectionObserver overlap), not a full jump.
    - `test_wait_for_content_stable_stabilizes_after_three_polls` — constant
      DOM ⇒ stable at exactly 3 polls (baseline + 2 unchanged).
    - `test_wait_for_content_stable_times_out_on_churning_page` — growth
      every poll ⇒ stable=False with the last observed length.
    - `test_wait_for_content_stable_survives_probe_failure` — probe failure ⇒
      unstable, never raises.
  - Hermetic real-browser tests (local ThreadingHTTPServer; skip-with-reason
    when Chromium is absent):
    - `test_fetch_page_captures_lazy_below_fold_content` — FAILED-before
      proof: with the Phase-3 helpers patched to no-ops (scratch script,
      outside the repo, deleted after), the lazy page's below-fold marker
      element was ABSENT from the capture; through the real Phase-3
      `fetch_page` it is present. The fixture builds the marker text by JS
      string concatenation so the literal exists only in the DOM after a real
      scroll — the assertion proves scrolling happened (the Phase-2 log hit
      the same script-source false-positive trap).
    - `test_auto_scroll_page_real_browser_short_and_tall_pages` — short page:
      0 steps; tall static page: walked to bottom, returned to top.
    - `test_fetch_page_static_page_still_captures` — static capture unchanged
      through the new sequence (same FetchResult shape).
- **Full regression results**:
  - Backend: `cd backend && uv run --frozen pytest -q` → **1119 passed, 1
    warning in 1097.06s (0:18:17)** (baseline 1108 + exactly the 11 new tests;
    the single warning is the pre-existing apprise `imghdr`
    DeprecationWarning). At/above baseline: PASS.
  - `cd backend && uv run --frozen ruff check .` → All checks passed (exit 0).
  - Frontend (no frontend files touched; Rule 4 baseline re-run): `pnpm test`
    → **20 files / 129 passed**; `pnpm exec tsc -b --noEmit` → exit 0, no
    output; `pnpm exec oxlint src` → **0 errors, 12 warnings** (matches the
    ≤12-warning baseline). All green.
- **Manual verification performed (Rule 14)**: rebuilt the worker image from
  the working tree (`docker compose build worker` — the RUNNING stack was not
  restarted or disturbed) and ran a scratch smoke script in a temporary
  container (`docker compose run --rm --no-deps -v ... worker python
  /tmp/smoke.py`): full `fetch_page` path (stealth + guard + 5s settle +
  challenge check + auto-scroll + stability wait + capture) against
  `https://example.com/` → HTTP 200, PNG, 8.2s wall, title "Example Domain";
  `https://news.ycombinator.com/` → HTTP 200, PNG, 10.1s wall, 34 KB HTML,
  title "Hacker News". Scratch script deleted; temp container auto-removed.
- **Residual risk / follow-ups**:
  - One-time post-deploy delta: baselines captured before this phase lack
    below-fold content; the first scan after deploy may flag it. Documented in
    docs/usage.mdx; self-heals after the next rebaseline (user-managed
    deploy timing per rule 14).
  - Infinite-scroll sites now consume the full 20s scroll cap every capture
    (by design — best-effort completeness); heavy feeds also grow the
    full-page screenshot. Phase 4's height cap bounds the screenshot side.
  - The stability wait keys on `body.innerHTML.length`, which can stay
    constant while content *swaps* (same-length churn); accepted per spec —
    it is a heuristic backstop to the scroll pass, not a correctness gate.
  - Phase-2's stale-response edge interacts benignly: the challenge wait's
    one-poll-extended fallback can only occur before scrolling starts.
  - The running Docker stack still runs the OLD image until the user
    rebuilds/restarts (update.ps1) — user-managed per rule 14.
- **New leads observed**:
  - Banner/consent overlays (Phase 5) can still cover content; Phase 5's
    dismissal will slot in cleanly between the challenge wait and
    auto_scroll_page (programmatic scrollBy is unaffected by modal overlays
    that only swallow user input, but banner DOM churn remains).
  - Sites that lazy-load via IntersectionObserver on a scroll container other
    than the window are not triggered by window scrolling (rare; noted).
- **Prompt-claim deviations (Rule 12)**:
  1. The Phase-3 "new flow" snippet shows the scroll sequence directly after
     the settle, but Phase 2 (already implemented) inserts `_wait_out_challenge`
     at that point; scroll is therefore placed AFTER the challenge wait — the
     composition that satisfies both phases (challenge re-checks see the
     settled DOM; challenge pages are never scrolled). Recorded here as the
     concrete interpretation.
  2. The spec's stop rule ("height stops growing for 2 consecutive steps ⇒
     fully loaded") is implemented as stable-height AND at-bottom (or
     provably-unscrollable); the literal rule alone stops static tall pages
     mid-scroll, contradicting the phase's own goal. Recorded as a spec bug
     fix, not a behavior drop.
  3. The spec says the timing constants live in `fetcher.py`; the Phase-1
     carry-over note (repeated in this phase's briefing) says scroll/settle
     timing extends `worker/stealth.py`. `SETTLE_MS` moved to stealth.py and
     the new timing constants were added there; `NAV_TIMEOUT_MS`/
     `SCREENSHOT_TIMEOUT_MS` (capture-pipeline budgets, not page-prep timing)
     stayed in fetcher.py as the spec requires. No behavior difference.
  4. Height probe uses `max(body.scrollHeight, documentElement.scrollHeight)`
     where the spec names only `document.body.scrollHeight` (SPA robustness).
  5. Worst-case budget: spec says 135s (60+5+20+5+45) and does not count the
     Phase-2 challenge wait; the real worst case is ≤145s (challenge wait is
     bounded by the nav budget it shares), still far under the verified 300s
     Celery soft limit.
  6. Prompt-prose check: spec's "the 2-second `SETTLE_MS`" matched the tree
     exactly (`fetcher.py:39` pre-change); flow line numbers drifted slightly
     with Phase 2's additions — verified against the tree, not the prose.
- **Commit**: 10ca2d2 — feat(capture3): smart scrolling & lazy-content capture
- **Next phase kickoff prompt**: (delivered in chat only — not persisted in this log)

### [DONE] PROMPT-002 Phase 4 — Screenshot Height Cap & Capture Evidence Storage

- **Prompt**: PROMPT-002-capture-hardening-and-detection-accuracy-v2.md
- **Session date**: 2026-09-04
- **Goal**: Add a safety cap on full-page screenshot height (very tall pages —
  infinite-scroll walks that hit the scroll time cap — can rasterize 50,000+ px,
  OOM/corrupt-PNG territory on many GPUs), and create the structured
  `capture_evidence` pipeline: `FetchResult.capture_evidence` (default `None`)
  merging Phase 3's scroll/stability evidence dicts with the screenshot-cap
  decision and an informational `capture_quality` label, persisted on a new
  nullable `scans.capture_evidence` JSONB column.
- **Files changed**: `backend/worker/stealth.py:66-91` (MAX_SCREENSHOT_HEIGHT
  constant + docstring bullet), `backend/worker/fetcher.py` (module docstring,
  FetchResult field :75, Phase-4 section :260-333 — `_PAGE_HEIGHT_JS`,
  `_classify_capture_quality`, `_take_screenshot` — and the `fetch_page`
  assembly :439-473), `backend/app/models.py:475-479` (Scan.capture_evidence),
  `backend/alembic/versions/o9q1r2s3t4u5_scans_capture_evidence.py` (new,
  reversible), `backend/worker/scan_tasks.py:305-310` (persistence point),
  `backend/tests/test_screenshot_cap.py` (new), `backend/tests/test_capture_evidence.py`
  (new), `backend/tests/test_scan_tasks.py:15,329-376` (+2 persistence tests).
- **Key design decisions**:
  - **Clip path deviation (Rule 12, empirically proven)**: the spec's literal
    `page.screenshot(full_page=False, clip={"x":0,"y":0,"width":viewport_width,
    "height":MAX_SCREENSHOT_HEIGHT})` does NOT do what the spec intends under
    the pinned Playwright 1.61.0 — probed live in the running worker container,
    `full_page=False` + clip silently clamps the PNG to the current viewport
    (1366×768), while `full_page=True` + clip yields exactly 1366×16384 (clip
    coordinates are PAGE coordinates under full_page=True). Implemented the
    `full_page=True` clip; "must still produce a valid PNG for the visual-diff
    layer" is satisfied and pinned by real-browser tests parsing the PNG IHDR.
  - `capture_quality` is computed in fetcher.py (where the evidence is
    assembled) by a pure function and carried INSIDE the capture_evidence dict —
    matching Phase 7's final-assembly shape; scan_tasks.py persists the dict
    wholesale. Informational only: no detection code reads it.
  - Classification semantics: `full` = scrolled, stable, uncaptured-capped,
    height measurable. `partial` = scroll time-capped OR content unstable OR
    screenshot height-capped (spec pins "full" to "screenshot not capped";
    partial is the successful-but-incomplete bucket — interpretation logged).
    `degraded` = a critical step failed but the capture completed — in Phase 4's
    flow that is exactly the unmeasurable-page-height case (probe failure →
    actual_height 0 → cap decision unknown; capture still completes uncapped).
  - New nullable `scans.capture_evidence` JSONB column mirroring the
    `baselines.capture_meta` JSON/JSONB-variant idiom; `scan.layer_scores`
    untouched (its documented per-layer contract is pinned by a new test).
  - `_take_screenshot` keeps screenshot failures as hard capture failures
    (unchanged semantics) but never lets evidence-gathering fail a capture.
- **Constraints honored**: SSRF policy untouched — the height probe is a
  read-only `page.evaluate`, the clip is local rasterization; zero new request
  paths. `worker/detection/` untouched. `apply_stealth` untouched. Challenge
  detection and Phase 3 scroll/stability compose exactly as before (the Phase-4
  step slots in after the stability wait, replacing only the bare screenshot
  call). Worst-case timing unchanged (+one sub-ms evaluate). Migration is
  reversible and passes the CI migrations gate (upgrade → downgrade -1 →
  upgrade → `alembic check` → "No new upgrade operations detected."). Frontend
  untouched; no-third-party rule untouched.
- **Edge cases handled (Gauntlet Step 3)**:
  - *Site categories*: cap logic is height-driven and category-agnostic;
    height is probed AFTER the Phase-3 scroll+stability pass, so
    lazy-grown/SPA heights are measured post-load; short/static/AMP pages
    take the unchanged uncapped path (pinned by tests).
  - *Bot protection tiers*: N/A — a persistent challenge raises FetchError
    in Phase 2's `_wait_out_challenge` before any scroll/screenshot; a
    solved challenge re-enters the flow on the fresh page exactly as before.
  - *Content loading patterns*: infinite-scroll (scroll time cap hit) is
    exactly the case the screenshot cap exists for — 20000px fixture proven
    capped to a valid 1366×16384 PNG.
  - *Consent/banner patterns*: N/A this phase (Phase 5 dismissal will insert
    BEFORE scrolling; the height probe runs after, so no interference).
  - *Failure modes*: dead height probe → degraded evidence + uncapped
    capture (never fails the capture, pinned); screenshot timeout/corrupt
    still fails the capture (unchanged); OOM on huge pages mitigated by the
    cap itself; `alembic check`/round-trip gate green.
  - *Concurrency*: helpers are stateless and per-page; evidence dicts are
    per-capture locals; no shared mutable state.
  - *Backward compatibility*: `FetchResult.capture_evidence` defaults to
    `None` (all pre-existing construction sites and test doubles keep
    working — pinned); pre-existing scan rows read NULL; `layer_scores`
    shape unchanged; baselines/capture_meta untouched.
  - *Performance*: one extra evaluate (sub-ms); the cap bounds worst-case
    raster memory/time on runaway pages.
- **Tests added**:
  - `tests/test_screenshot_cap.py` (7) — unit: uncapped short path records
    the exact unclipped call; tall page records `full_page=True` + clip at
    exactly MAX_SCREENSHOT_HEIGHT; dead probe → uncapped + actual_height 0
    (never fails); missing viewport_size falls back to CONTEXT_VIEWPORT
    width. Real-browser (hermetic local server, Chromium-skip pattern):
    short page PNG is exactly 1366×2000; 20000px page PNG is exactly
    1366×16384 and a valid PNG (IHDR-parsed — the visual-diff-layer
    requirement); fetch_page e2e with a shrunk cap (600) produces the
    capped PNG + `screenshot_capped`/`actual_height`/quality "partial";
    uncapped short page never fires the cap. FAILED-before: the pre-Phase-4
    capture took an uncapped full-page raster and FetchResult had no
    capture_evidence field at all.
  - `tests/test_capture_evidence.py` (9) — FetchResult defaults to None and
    accepts/stores a dict (backward-compat contract); classification matrix
    (full / scroll-capped partial / unstable partial / screenshot-capped
    partial / degraded ×3 shapes); real fetch_page assembles the exact
    merged key set with quality "full" on a static page; page_prepare
    scroll-evidence key set guarded unchanged.
  - `tests/test_scan_tasks.py` (+2) — `_run_scan` persists the evidence
    dict on the scan row and `layer_scores` keeps its exact per-layer key
    set; a pre-field FetchResult persists SQL NULL (persistence-level
    backward compat).
- **Full regression results**:
  - Backend: `cd backend && uv run --frozen pytest -q` → **1137 passed, 1
    warning in 1110.80s (0:18:30)** (baseline 1119 + exactly the 18 new
    tests; the single warning is the pre-existing apprise `imghdr`
    DeprecationWarning). At/above baseline: PASS.
  - *Integrity note (Rule 12)*: an earlier suite run overlapping the Docker
    image rebuild + container smoke flaked 4 CPU-timing-sensitive tests in
    `test_phase5_audit/bulk_import/rbac` (missing audit rows / dedupe
    timing). All 43 tests in those files pass in isolation (28.09s) and the
    clean non-overlapped re-run above is fully green — contention artifact,
    not a code failure; recorded rather than silently dismissed.
  - `cd backend && uv run --frozen ruff check .` → All checks passed (exit 0).
  - Migration gate (mirrors CI): `alembic upgrade head` → `downgrade -1` →
    `upgrade head` → `alembic check` → "No new upgrade operations detected."
  - Frontend (no frontend files touched; Rule 4 baseline re-run): `pnpm test`
    → **20 files / 129 passed**; `pnpm exec tsc -b --noEmit` → exit 0;
    `pnpm exec oxlint src` → **0 errors, 12 warnings** (≤12 baseline). Green.
- **Manual verification performed (Rule 14)**: pre-implementation, probed
  both clip variants in the running worker container (Playwright 1.61:
  `full_page=False`+clip → 1366×768; `full_page=True`+clip → 1366×16384) —
  the basis for the logged deviation. Post-implementation: rebuilt the
  worker image from the working tree (`docker compose build worker`; the
  RUNNING stack was not restarted or disturbed) and ran a scratch smoke
  script in a temporary container (`docker compose run --rm --no-deps
  -v ... worker python /scratch/smoke_phase4.py`): local short page → HTTP
  200, PNG 1366×768, evidence quality "full"; local 20000px page → HTTP
  200, PNG exactly 1366×16384, `screenshot_capped: true`,
  `actual_height: 20000`, 32 scroll steps, quality "partial" (full stealth +
  SSRF-guard + challenge-check + scroll + stability + cap composition);
  live `https://example.com` → HTTP 200, quality "full". Scratch script and
  probe deleted; temp container auto-removed; stack untouched.
- **Rule 13 disposition**: no new env vars/compose/script surface —
  MAX_SCREENSHOT_HEIGHT is a code constant per spec, nothing is env-tunable;
  `capture_evidence`/`capture_quality` are not exposed through the API
  schema or frontend yet, so nothing is operator-visible and `docs/usage.mdx`
  is intentionally NOT touched (its capture sections remain accurate). The
  height-cap sentence belongs in "Scrolling & Lazy Content" at Phase 7's
  docs-sync pass; `capture_quality` surfaces only if a later phase exposes it.
- **Residual risk / follow-ups**:
  - One-time visual delta if a baseline page exceeds 16384px (rare): the
    first capped scan compares a truncated screenshot against the taller
    baseline — self-heals on rebaseline; Phase 7's capture_method_version
    signal will cover the class of problem.
  - The capped clip's width is the viewport width: a document wider than
    1366px with horizontal overflow loses its right edge ONLY on the capped
    path (the uncapped path captures full scrollable width). Accepted — the
    visual layer rescales to COMPARE_WIDTH anyway; noted for Phase 7 docs.
  - `actual_height` usually duplicates `final_height` (kept: it is the
    explicit cap-decision input and differs when the probe degrades).
- **New leads observed**: the `test_phase5_*` API tests' CPU-load
  sensitivity (audit-row/bulk-import assertions tightened to synchronous
  timing under heavy parallel load) — candidates for deadline/async-write
  hardening; out of scope here. Also: pytest output under stdout redirection
  is block-buffered, making long-suite progress opaque to tooling (cosmetic).
- **Commit**: 609b13c — feat(capture4): screenshot height cap & capture evidence storage
- **Next phase kickoff prompt**: (delivered in chat only — not persisted in this log)

---

### [DONE] PROMPT-002 Phase 5 — Cookie/Consent Banner Dismissal

- **Prompt**: PROMPT-002-capture-hardening-and-detection-accuracy-v2.md
- **Session date**: 2026-09-04
- **Goal**: Stop first-visit consent banners from poisoning captures: inject the
  common CMP consent cookies on the fresh context BEFORE navigation so banners
  that check cookies first never render, and after the page is confirmed real
  (challenge gate passed) but BEFORE scrolling, click the first visible
  accept/dismiss control from a curated selector list — with banner facts riding
  in `capture_evidence`, both helpers never raising, and no SSRF/detection
  surface touched.
- **Files changed**:
  - `backend/worker/banner_dismiss.py` — NEW: `CONSENT_COOKIES` (13 top-CMP
    entries: OneTrust ×2, Cookiebot, CookieYes ×2, IAB TCF v2, Didomi, Cookie
    Script, Klaro, Complianz, Borlabs, Osano, tarteaucitron),
    `materialize_consent_cookies(url)` (scheme-aware `url=f"{scheme}://{host}"`
    runtime materialization, explicit ports preserved, IPv6 literals bracketed,
    Secure flags only on https targets, never a bare `"domain": ""`),
    `inject_consent_cookies(context, url) -> list[str]` (one batched
    `add_cookies` call, never raises), `DISMISS_SELECTORS` (30 curated
    selectors, CMP-specific first, generic aria/ID/class fallbacks),
    `dismiss_banners(page, *, timeout_ms) -> dict` (first visible in-viewport
    match across main frame + all consent iframes, bounded late-banner wait,
    returns `{"dismissed", "selector", "attempts"}`, never raises).
  - `backend/worker/stealth.py:97-107` — `BANNER_DISMISS_TIMEOUT_MS = 3_000`
    constant + docstring bullet (constants home per the spec; `apply_stealth`
    untouched).
  - `backend/worker/fetcher.py` — module docstring Phase-5 paragraph;
    `inject_consent_cookies(context, url)` between `apply_stealth(context)` and
    `context.new_page()`; `dismiss_banners(page, timeout_ms=
    BANNER_DISMISS_TIMEOUT_MS)` AFTER `_wait_out_challenge` and BEFORE
    `auto_scroll_page`; `**banner_evidence` merged into the `capture_evidence`
    assembly (fetcher.py:~490).
  - `backend/tests/test_banner_dismiss.py` — NEW, 23 tests (see below).
  - `docs/usage.mdx` — new "Consent & Cookie Banners" subsection (style-matched
    to "Capture Failures & Bot Protection" / "Scrolling & Lazy Content", no
    constants pinned in prose, one-time-delta note for operators).
- **Key design decisions**:
  - **Dismissal placement: AFTER `_wait_out_challenge`, BEFORE
    `auto_scroll_page`.** The spec's flow sketch (written before the Phase-2
    challenge gate existed) shows `dismiss_banners` immediately after settle;
    taken literally it would click buttons on challenge pages, which the
    spec's own edge case forbids ("a challenge page must not have its buttons
    clicked"). The challenge gate either returns with a confirmed-real page or
    hard-fails the capture, and a challenge that auto-solves via reload leaves
    the real page in place before dismissal runs — so the gate-first ordering
    satisfies both the "after the page loads but BEFORE scrolling" wording and
    the never-click-a-challenge-page invariant.
  - **Banner evidence does NOT affect `capture_quality`.** The Phase-4 label
    grades capture mechanics (scroll/stability/screenshot); a banner Wardress
    could not dismiss is the site's own presentation, not a capture failure.
    `_classify_capture_quality`'s input dict is unchanged; `**banner_evidence`
    merges alongside it. Phase-4 semantics stay pinned by their tests.
  - **Bounded two-phase dismissal.** Banners are almost always in the DOM after
    the 5s settle, so pass 1 is an instant `query_selector` sweep over main
    frame + all child frames; only when nothing matched does ONE
    `wait_for_selector` over the comma-joined selector list consume the
    remaining `timeout_ms` budget before a final sweep. This avoids the naive
    per-selector wait shape (30 selectors × 3 s = 90 s worst case); total
    dismissal time is bounded by `BANNER_DISMISS_TIMEOUT_MS`.
  - **Click safety**: click only the first visible match whose bounding box
    intersects the viewport (Playwright's actionability checks handle the
    rest); a failed click (element detached mid-animation) falls through to
    the next selector; 1 s per-click timeout; 250 ms guarded post-click settle
    so the banner removal starts landing before the scroll pass measures the
    page. Curated CMP selectors come first so the broad generic
    `button[aria-label*='Accept']` patterns only ever fire as fallback.
  - **Cookie materialization at runtime** (never a static `"domain": ""`
    literal): scheme-aware `url=` per cookie, explicit ports preserved, IPv6
    literals bracketed, `Secure` set only for `secure_when_https` entries on
    https targets (Chromium refuses Secure on http:). OneTrust
    `OptanonAlertBoxClosed` and the Cookiebot stamp get runtime-generated
    dismissal timestamps.
  - **Shadow-DOM coverage for free**: Playwright's CSS engine pierces open
    shadow roots, so the Usercentrics host
    (`#usercentrics-root button[data-testid='uc-accept-all-button']`) needs no
    extra piercing logic; consent iframes (Quantcast/Sourcepoint) are covered
    by iterating `page.frames()`.
- **Constraints honored**:
  - SSRF: `app/ssrf.py` untouched; no new request paths — injection is
    context-level state and dismissal is page-level interaction, so every
    request the page makes during dismissal still flows through the route
    guard installed after stealth (unchanged ordering: stealth → cookies →
    new_page → route guard).
  - `worker/page_prepare.py`, `worker/scan_tasks.py`, `worker/detection/`,
    `worker/probe.py` untouched; the evidence dict grows keys only —
    `scan_tasks.py` stores `capture_evidence` as-is, no persistence change
    needed.
  - No new dependencies (`pyproject.toml` unchanged — pure Playwright APIs);
    `docker-compose.yml`, `.env.example`, `scripts/` verified to need NO
    change (no new env vars, services, volumes, or install steps); Celery
    budget re-verified: worst case 60+5+10+3+20+5+45 = 148 s + ~20 s probe,
    well under the 300 s soft limit.
  - Lint: `uv run --frozen ruff check .` exit 0. Frontend untouched (Rule 4
    baseline re-run, all green — see regression results).
- **Edge cases handled** (Gauntlet step 3, each with disposition):
  - Sites checking cookies first: pre-navigation injection prevents the
    banner entirely (unit + live-verified: injected cookies readable by
    page JS through the real `fetch_page`).
  - Challenge pages: never clicked — dismissal strictly after the challenge
    gate (see design decision); Phase-2 tests still pass (challenge captures
    hard-fail before dismissal ever runs).
  - http vs https targets: Secure-flagged consent cookies only on https
    (unit matrix + real-browser test asserting zero Secure cookies on an
    http context).
  - Explicit ports / IPv6 literals: materialized into the cookie `url`
    (unit tests for `:8443` and `[::1]:8080`).
  - Unparseable/non-http(s) targets: materialization returns [], injection
    no-ops, never raises (unit tests).
  - Banner inside a consent iframe: child-frame sweep finds and clicks it
    (unit test; live smoke runs showed the frame walk on real sites, e.g.
    270 attempts = 30 selectors × 9 frames on speedtest.net).
  - Banner in an open shadow root (Usercentrics): covered by Playwright's
    selector engine (selector in list; piercing is engine-native).
  - Banner present but invisible / off-viewport: skipped, `dismissed=False`
    (unit + real-browser hidden-banner test).
  - Click failure (element detached mid-animation): falls through to the
    next selector (unit test).
  - Late-rendering banner: one bounded combined-selector wait, then a final
    sweep; an expired budget yields `dismissed=False` and the capture
    proceeds (unit tests; "never re-waits" assertion included).
  - Broken page/frame mid-dismissal (evaluate/query raises, page closed):
    caught, evidence returned partial, capture continues — never-raise
    contract (unit tests).
  - Consent INTERSTITIALS (full-page walls replacing the document): out of
    scope for selector clicks — noted as residual risk.
  - Infinite-scroll sites: unaffected (dismissal precedes the scroll pass;
    Reddit smoke run hit the scroll cap exactly as in Phase 3, quality
    "partial", no interaction with banner logic).
  - Concurrency: no shared state — per-capture context/page + local evidence
    dicts.
  - Backward compatibility: `FetchResult`/schema unchanged; existing
    `capture_evidence` consumers see added keys only; old rows unaffected.
- **Tests added** (`backend/tests/test_banner_dismiss.py`, 23 tests;
  standalone run: **23 passed in 18.31s**):
  - Cookie materialization (no browser): scheme-aware urls without any bare
    `"domain"` key (https), explicit-port preservation, IPv6 bracketing,
    Secure-only-on-https matrix (FAILED-before: pre-Phase-5 nothing existed),
    unusable-URL rejection, batched injection returning injected names,
    skip-unusable-targets, never-raises-on-context-failure.
  - Dismissal doubles (no browser): first-visible-match click with exact
    `attempts` accounting, no-banner graceful evidence + single combined
    wait (`state="visible"`, remaining budget), invisible-banner skip,
    off-screen-button skip, click-failure fallthrough, consent-iframe
    discovery, late-banner reveal via the bounded wait, timeout bounding
    (never re-waits), never-raises on broken page AND broken frame.
  - Real-browser (hermetic local server, Chromium-skip pattern): visible
    banner clicked and overlay provably removed
    (`getComputedStyle(...).display == "none"`), hidden banner ignored, no
    Secure cookies on http contexts, and through the real `fetch_page`:
    banner dismissed with evidence + `capture_quality` still "full" +
    consent cookies readable by page JS (FAILED-before: the pre-Phase-5
    capture stored the banner overlay obscuring the content), plus a
    banner-free page keeping the pre-Phase-5 behavior and evidence shape.
- **Full regression results**:
  - Backend: `cd backend && uv run --frozen pytest -q` → **1160 passed, 1
    warning in 1162.44s (0:19:22)** (baseline 1137 + exactly the 23 new
    tests; the single warning is the pre-existing apprise `imghdr`
    DeprecationWarning). At/above baseline: PASS.
  - `cd backend && uv run --frozen ruff check .` → All checks passed (exit 0).
  - Frontend (no frontend files touched; Rule 4 baseline re-run): `pnpm test`
    → **20 files / 129 passed**; `pnpm exec tsc -b --noEmit` → exit 0, no
    output; `pnpm exec oxlint src` → **0 errors, 12 warnings** (matches the
    ≤12-warning baseline). All green.
- **Manual verification performed (Rule 14)**: rebuilt the worker image from
  the working tree (`docker compose build worker` — the RUNNING stack was not
  restarted or disturbed) and ran a scratch smoke script in temporary
  containers (`docker compose run --rm --no-deps -v ... worker python
  /tmp/smoke.py`) against 8 live sites through the full real `fetch_page`
  path: cnn.com (200, 5.9 MB PNG, 12 scroll steps), bbc.com (200, 20 steps),
  news.ycombinator.com (200, control), example.com (200, control),
  speedtest.net (200, 9 frames walked), healthline.com (200, 7 frames),
  reddit.com (200, quality "partial" — infinite feed hit the 20 s scroll cap,
  exactly the designed Phase-3 behavior), dailymail.co.uk (403 anti-bot block
  — captured as-is, out of Phase-5 scope). All captures completed with
  quality "full" except Reddit's designed "partial"; the frame-walking
  dismissal sweep ran on every site (attempts scaled exactly with frame
  count) with zero false clicks and zero capture failures. No live consent
  banner was encountered: every candidate site geo-gates its consent banner
  and this host's IP is served none — the click path itself is proven by the
  real-browser hermetic tests above. Scratch script deleted; temp containers
  auto-removed (`--rm`).
- **Residual risk / follow-ups**:
  - Geo-dependent coverage: live banner suppression could not be exercised
    end-to-end from this host's IP (no site served a banner); CMP selector
    drift is the standing risk — the curated list is best-effort by design
    and a missed banner degrades to the pre-Phase-5 capture, never a failure.
  - Consent interstitials (full-page consent walls that replace the document)
    are not handled by selector clicks and would still be captured as-is.
  - Cookie values are plausible CMP shapes, not byte-exact records: CMPs that
    parse-and-validate (rather than presence-check) may still show a banner;
    the click pass is the backstop.
  - Broad generic selectors (`button[aria-label*='Accept']` etc.) could in
    principle match a non-banner control; mitigated by CMP-specific selector
    ordering and the first-visible-match-only rule; accepted per spec.
  - The running Docker stack still runs the OLD image until the user
    rebuilds/restarts (update.ps1) — user-managed per rule 14.
- **New leads observed**:
  - Reddit captured at quality "partial" on every capture (infinite feed
    always exhausts the scroll cap) — candidate for a per-site scroll budget
    or feed-height heuristic later in this effort.
  - OneTrust's CCPA variant (`onetrust-consent-sdk` "Do Not Sell" banner for
    US-state IPs) has no dedicated selector in the curated list yet.
  - pytest stdout block-buffering under redirection remains cosmetic-only
    (carried from Phase 4's notes).
- **Process change (user directive)**: all kickoff prompts previously embedded
  in this log were removed this session, and the entry-format template now
  reads "delivered in chat only — never written to this log". Future phases
  output the next phase's kickoff prompt in chat only and must NOT append it
  here (user-requested deviation from the prompt's §6 format; this note is
  the standing record of that decision).
- **Commit**: e595f7d — feat(capture5): consent-cookie injection & banner click-dismissal
- **Next phase kickoff prompt**: (delivered in chat only — never written to this log)

### [DONE] PROMPT-002 Phase 6 — Capture Retry Logic

- **Prompt**: PROMPT-002-capture-hardening-and-detection-accuracy-v2.md
- **Session date**: 2026-09-04
- **Goal**: Wrap the capture flow in a bounded retry for TRANSIENT failures
  only — a `goto` timeout / network-level error gets ONE retry after a
  3s pause at a reduced nav timeout (`RETRY_NAV_TIMEOUT_MS=30_000`), an
  unsolved Cloudflare challenge gets ONE retry with a longer wait
  (15s), max 2 total attempts — while SSRF refusals and permanent
  FetchErrors fail immediately. Retries logged at WARNING with the
  reason; the retry count stored in `FetchResult.capture_evidence`.
- **Files changed**: `backend/worker/stealth.py` (docstring bullet +
  new "Capture retry" section with `RETRY_NAV_TIMEOUT_MS`,
  `RETRY_PAUSE_MS`, and the authoritative worst-case budget comment;
  stale "well under the 300s soft limit" comments in the Phase-3/5
  sections rewritten to defer to it), `backend/worker/fetcher.py`
  (module docstring Phase-6 paragraph; imports
  `PlaywrightTimeoutError`/`RETRY_*`; `CHALLENGE_RETRY_WAIT_MS=15_000`
  beside the Phase-2 challenge constants; new `_ChallengeUnsolvedError`
  (is-a FetchError, BOT_PROTECTION_ERROR message — public contract
  unchanged) and `_TransientNavError`; `_classify_goto_failure()`;
  `_wait_out_challenge()` gained a `wait_ms` keyword and raises the
  typed subclass; `fetch_page` split into the retry loop +
  `_capture_attempt` (attempt-local browser/context/page/stealth/
  cookies/PER-PAGE route guard/evidence — nothing shared to
  double-count); goto wrapped to classify failures BEFORE the generic
  PlaywrightError→FetchError boundary; challenge deadline extended
  only on the challenge retry so the full longer wait is guaranteed
  even if goto ate most of the reduced budget; evidence gains
  `"retry_count"`), `backend/worker/celery_app.py` (soft/hard
  300/360 → 420/480 + budget comment), `backend/app/scanning.py:6`
  (stale "360 s" mention synced), `docs/usage.mdx` (retry paragraph in
  "Capture Failures & Bot Protection", no constants pinned in prose),
  `backend/tests/test_fetcher_retry.py` (new),
  `backend/tests/test_stealth.py` + `backend/tests/test_phase35_backend_correctness.py`
  (seam tests updated to inspect fetch_page + _capture_attempt sources
  — the contracts themselves unchanged),
  `Prompts/Pending/Finders/PROMPT-002-...-v2.md` (§8: standing
  session-ops rule against repeated identical polling commands —
  user-requested after the loop-guard aborted this session).
- **Key design decisions**:
  - **Retry classification is explicit, not blanket**: only
    `playwright.TimeoutError` and `net::ERR_*` goto failures are
    transient. `net::ERR_BLOCKED_BY_CLIENT` is EXCLUDED — it is the SSRF
    route guard's denial surfacing as a goto error, i.e. a policy
    decision, and the spec forbids retrying those. Unclassifiable goto
    errors stay permanent (retrying an unknown failure shape doubles the
    cost of permanent breakage for no expected gain).
  - **`_ChallengeUnsolvedError` subclasses FetchError** instead of
    string-matching BOT_PROTECTION_ERROR in the retry loop: precise,
    and `pytest.raises(FetchError)` / `str(exc) == BOT_PROTECTION_ERROR`
    in test_cloudflare_detection.py still hold (public contract
    untouched).
  - **Challenge retry wait is GUARANTEED, not best-effort**: Phase 2
    bounds the wait by the remaining nav budget; on the retry, with the
    reduced 30s budget, a slow goto could have starved the "longer
    wait" below the first attempt's 10s. The deadline is extended
    (max(nav_deadline, now + challenge_wait)) ONLY when
    challenge_wait_ms > CHALLENGE_WAIT_MS — the first attempt keeps the
    Phase-2 shape byte-for-byte.
  - **RETRY_NAV_TIMEOUT_MS applies to every retry attempt** (goto- and
    challenge-triggered alike): the spec's budget math requires the
    reduced timeout, and applying it uniformly keeps the challenge-
    retry worst case at ~264s instead of ~299s (too close to the old
    300s soft limit).
  - **State isolation by construction**: each attempt rebuilds
    browser/context/page, applies stealth, re-injects consent cookies
    (Phase 5 contract: fresh context is cookie-empty), installs a FRESH
    per-page SSRF route guard (guard is per-page; the retried page gets
    its own), and builds fresh evidence dicts — the only cross-attempt
    state is the loop's `retry_count`. No double-counting is possible.
  - **Celery limits RAISED 300/360 → 420/480 (spec's escape hatch
    exercised)**: honest trace of `_run_scan` — worst fetch with retry
    ~264s, then `probe_site`'s per-request 20s timeouts are SEQUENTIAL
    (TLS + robots.txt + 3 UA fetches ⇒ ~90s worst, probe.py:216-233),
    plus detection ~30s worst ⇒ ~384s > 300s. 420/480 covers it with
    margin and stays under the 600s STALE_INFLIGHT cutoff
    (app/scanning.py), whose docstring was synced. No test pinned the
    old limits.
  - `CHALLENGE_RETRY_WAIT_MS` lives in fetcher.py beside
    CHALLENGE_WAIT_MS (the Phase-2 challenge-timing family predates
    stealth.py's timing home); `RETRY_*` live in stealth.py per the
    spec/task note. Logged per Rule 12.
- **Constraints honored**: SSRF policy untouched and re-verified — the
  top-level gate still runs before ANY browser work and is never
  retried; the fresh page on every attempt gets its own route guard;
  the final-URL recheck still raises SSRFBlockedError (never retried).
  `apply_stealth`, `worker/page_prepare.py` (contracts pinned by
  tests), `worker/banner_dismiss.py` (contracts unchanged — merely
  re-triggered on the fresh attempt), `probe.py`, and
  `worker/detection/` untouched. The `full_page=True` + clip screenshot
  shape untouched. Banner evidence still does not feed capture_quality.
- **Edge cases handled** (Gauntlet Step 3):
  - *Retry must not double-count the capture* → attempt-local state;
    disposition: structurally impossible (fresh everything per attempt).
  - *Route guard must survive across retries* → per-page guard re-built
    on the fresh page each attempt; seam re-pinned by updated
    test_stealth ordering test.
  - *Soft-limit budget (DECIDED constraint)* → traced `_run_scan`
    end-to-end; worst case EXCEEDED 300s (see decision above); limits
    raised + celery_app/scanning comments + docs synced per Rule 13.
  - *Concurrent retries* → no shared retry state; each task's loop is
    call-stack-local.
  - *SSRF blocks not retried* → top-level gate before any attempt; the
    route-guard-abort goto shape (ERR_BLOCKED_BY_CLIENT) explicitly
    classified non-transient; final-URL recheck refusal propagates.
  - *Permanent FetchErrors not retried* → explicit `except FetchError:
    raise` branch; only the typed challenge subclass retries.
  - *Both retry reasons in sequence* → attempt 2 is final whatever it
    raises (transient → user-safe FetchError with the classified
    reason; challenge → BOT_PROTECTION_ERROR).
  - *Challenge-retry wait starved by a slow goto* → deadline extension
    (decision above).
  - *Test-suite seam rot* → two source-inspection tests pointed at
    fetch_page's monolith; updated to span the new split (contracts
    intact, both green).
- **Tests added** (`backend/tests/test_fetcher_retry.py`, 14 tests):
  - Unit, no browser: `test_retry_constants_shape`;
    `test_classify_goto_failure_transient_paths` (timeout, REFUSED,
    NAME_NOT_RESOLVED, RESET); `test_classify_goto_failure_permanent_paths`
    (ERR_BLOCKED_BY_CLIENT → None; unknown → None);
    `test_ssrf_block_is_never_retried` (exactly 1 attempt, refusal
    propagates); `test_permanent_fetch_error_is_never_retried` (1
    attempt); `test_transient_nav_error_retries_once_then_fails`
    ([60s, 30s] nav budgets, retry_count [0, 1], user-safe final
    FetchError); `test_transient_nav_error_recovers_on_second_attempt`
    (retry params + evidence retry_count=1);
    `test_unsolved_challenge_retries_with_longer_wait` (attempt 2 gets
    CHALLENGE_RETRY_WAIT_MS + reduced nav timeout);
    `test_unsolved_challenge_on_both_attempts_fails_after_two` (2
    attempts, BOT_PROTECTION_ERROR);
    `test_retry_logs_warning_with_reason` (WARNING carries the reason).
  - Real-browser (scripted local server + real-Chromium-skip pattern):
    `test_fetch_page_retries_transient_timeout_and_succeeds`,
    `test_fetch_page_first_attempt_success_records_zero_retries`,
    `test_fetch_page_retries_unsolved_challenge_with_longer_wait`,
    `test_fetch_page_never_exceeds_two_total_attempts` (exactly 2
    requests end-to-end, then the user-safe FetchError).
  - Failing-before proof: the file was run BEFORE implementation —
    collection ImportError (retry symbols absent), i.e. the behavior
    did not exist.
- **Full regression results**:
  - `cd backend && uv run --frozen ruff check .` → "All checks passed!"
    (exit 0).
  - `cd backend && uv run --frozen pytest -q` → **1174 passed, 1
    warning**, 1308.98s (0:21:48) — run once mid-session with 2 seam
    failures (see edge cases), which were fixed and re-proven green in
    a 44/44 three-file re-run (test_stealth + test_phase35 +
    test_fetcher_retry). Final tally **1174 passed, 1 warning** =
    baseline 1160 + 14 new; the single warning is the pre-existing
    apprise `imghdr` DeprecationWarning.
  - Frontend (untouched, Rule 4 record): `pnpm test` → 20 files / **129
    passed** (14.08s); `pnpm exec tsc -b --noEmit` → clean (no output);
    `pnpm exec oxlint src` → 0 errors, **12 warnings** (baseline).
- **Manual verification performed** (fresh Docker install; worker image
  rebuilt `docker compose build worker beat` + `up -d worker beat` so
  the containers run this phase's code):
  - *Transient-timeout retry in the real container*: in-container
    `fetch_page` (constants shortened for speed: nav 4s → retry 2.5s,
    pause 1s) against `http://10.255.255.1/` (policy-allowed,
    non-routable): attempt 1 goto timeout → WARNING "Capture attempt
    1/2 ... failed (transient navigation failure (navigation timeout
    (Page.goto: Timeout 4000ms exceeded.))); retrying once after 1s
    pause" → attempt 2 timeout → `FetchError("Fetch failed: navigation
    timeout (Page.goto: Timeout 2500ms exceeded.)")` in 9.5s total.
  - *Happy path in the real container*: `https://example.com/` → 200,
    retry_count=0, capture_quality=full, valid PNG (10.2s).
  - *Real Cloudflare-protected site*: nowsecure.nl returned a clean 200
    (no challenge fired this session) — capture succeeded, retry_count
    0. The challenge-retry path is proven end-to-end by the hermetic
    tests instead.
- **Residual risk / follow-ups**:
  - The budget arithmetic (fetch ~264s + probe ~90s + detection ~30s ≈
    384s < 420s) is analytic; a real worst-case stack (hanging server
    on EVERY probe request after a retried capture) was not reproduced
    live. The hard limit at 480s and the 600s stale cutoff remain the
    backstops; Phase 7 re-verifies the budget as part of its spec.
  - `dismiss_banners`' late-banner wait (3s) runs on every attempt; a
    banner-heavy site pays it twice when a retry fires — accepted
    (bounded), noted for Phase 7's wall-clock evidence.
  - Frontend never surfaces `retry_count` — deliberately deferred to
    Phase 7/8 (evidence surfacing phases).
- **New leads observed**:
  - `probe_site`'s four httpx requests are strictly sequential with a
    20s timeout EACH — a half-open server burns ~90s there; a shared
    probe budget would tighten the scan worst case materially. Out of
    scope here (probe is DO-NOT-DISTURB this phase); candidate for
    Phase 7's budget pass or a later hardening phase.
  - `wait_for_content_stable`/`auto_scroll_page` bind their timing
    defaults at import, so monkeypatching their module constants does
    not shorten integration tests (left at production values — ~1s per
    attempt). Cosmetic test-speed lead only.
- **Commit**: 6b0cf0e — feat(capture6): transient-failure retry & longer challenge wait
- **Next phase kickoff prompt**: (delivered in chat only — never written to this log)
