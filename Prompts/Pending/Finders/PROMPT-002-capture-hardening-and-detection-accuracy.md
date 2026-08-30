# PROMPT-002 — Capture Hardening & Detection Accuracy

**READ THIS ENTIRE FILE, START TO FINISH, BEFORE DOING OR WRITING ANYTHING.**
Do not skim. Do not jump to a phase. Do not begin work after reading only the phase list. This file defines rules that apply to *every* phase, and violating them invalidates the implementation. If you have already read it once earlier in this session, re-read it anyway — you cannot rely on a memory summary of your own instructions.

---

## 0. WHAT THIS IS

This is a multi-session, six-phase implementation effort against the Wardress codebase (a self-hosted website-defacement detection and automated-response platform: FastAPI/Python backend, Celery worker with Playwright-based capture, React/TypeScript frontend, PowerShell install/ops scripts). It addresses two interconnected problems:

1. **The capture mechanism is unreliable.** The current `fetcher.py` fails to capture many sites entirely (bot-protection blocks, JavaScript-heavy SPAs), and captures others incompletely (lazy-loaded content below the fold renders as blank, cookie/consent banners obscure content, the 2-second settle window is too short for modern sites). A monitoring tool that cannot see what real users see is blind — and every downstream detection layer inherits that blindness.

2. **The detection pipeline produces false positives on dynamic sites.** News headlines rotating, ad slots changing, timestamps updating, A/B test variants, nonce-varying CSP headers — all produce legitimate churn that the pipeline flags as "changed" with nonzero risk scores. Combined with capture inconsistency (different scroll positions, different banner states between baseline and scan), the noise-to-signal ratio undermines operator trust.

These two problems are causally linked: inconsistent captures (different scroll depth, different banner state, different JS execution timing) create artificial DOM/visual deltas that the detection pipeline cannot distinguish from real tampering. Fixing capture consistency will eliminate a large class of false positives before detection tuning even begins.

**This effort builds on the completed 44-phase fix effort** (see `WARDRESS_FIX_LOG.md`). That effort already:
- Refitted the fusion model with non-negative coefficients (Phases 8–10)
- Ungated layer 4 (visual diff) from the content hash (Phase 6)
- Added chroma-shift detection to layer 4 (Phase 36)
- Added degradation signaling (Phase 24)
- Added rule-based minimum-risk floors (Phase 7/10)
- Fixed every detection-layer weakness (Phases 20–24, 36)
- Built a 646-sample synthetic training dataset with anti-bias controls

This effort does NOT re-derive those fixes. It builds new capabilities on top of them.

Each phase happens in a **separate chat with a fresh context window**. This file is the only thing that persists your instructions across sessions. `Prompts\Done\Loogers\IMPLEMENTATION_LOG.md` is the only thing that persists your *progress and decisions* across sessions. Together they are the entire state of this effort.

This means: **if it isn't written into `IMPLEMENTATION_LOG.md`, it did not happen.**

---

## 1. ABSOLUTE, NON-NEGOTIABLE RULES

1. **Scope discipline.** You edit only the files required by the current phase's spec. No drive-by refactors, no "while I'm here" changes to unrelated subsystems. If you notice something else wrong, note it in your implementation log entry under "New leads observed" and move on.

2. **Read before edit, always.** Before modifying ANY file, read it completely. Before modifying a function, read every caller and every callee. Before adding an import, verify the package exists in the project's dependency list (`pyproject.toml` / `package.json`). Never edit blind — the codebase has 44 phases of careful fixes already in place; a careless edit can silently undo safety properties you didn't know were there.

3. **Proven, not asserted.** Every behavioral change must have an automated test that:
   - **Failed before** the change (or would fail against the old code path — document which)
   - **Passes after** the change
   - Covers every edge case you enumerated (see §2)
   If something genuinely cannot be tested automatically (e.g., visual rendering of a specific external site), perform and document a manual verification instead, and say explicitly why it isn't automated.

4. **No regressions, ever.** Before a phase ends, the *entire* existing test suite must pass:
   - Backend: `cd backend && uv run --frozen pytest -q` — at or above the recorded baseline (currently ~540+ passed)
   - Frontend: `cd frontend && pnpm test` — all green
   - Frontend type-check: `cd frontend && pnpm exec tsc -b --noEmit` — exit 0
   - Frontend lint: `cd frontend && pnpm exec oxlint src` — 0 errors, ≤12 warnings
   - Backend lint: `cd backend && uv run --frozen ruff check .` — clean
   If a failure is genuinely pre-existing and unrelated, verify it also fails on the pre-change commit, and note it explicitly — do not silently accept it.

5. **Package management:**
   - Python: `uv` exclusively. `pip install` is OS-blocked. Use `uv pip install` inside the project venv, or `uv add` for new dependencies in `pyproject.toml`.
   - Node: `pnpm` exclusively. `npm`/`yarn`/`bun` are OS-blocked. Use `pnpm add` for new deps, `pnpm dlx` for one-off executables.

6. **No third-party runtime requests from the frontend.** The test `no-third-party-image-hosts.test.ts` bans these literals anywhere under `frontend/src/**`: `google.com/s2/favicons`, `svgl.app`, `cdn.jsdelivr.net`, `cdn.simpleicons.org`, `api.iconify.design`, `models.dev/logos`. This test must remain unmodified and passing.

7. **One phase per session, fully, before stopping.** Do not do half a phase. Do not skip ahead. If a phase turns out larger than expected, finish a smaller, explicitly-scoped subset correctly and leave the tracker noting what remains, rather than rushing the whole thing shallowly.

8. **Every phase ends in exactly one git commit** (after the full regression suite is green):
   `feat(captureN): <short summary>` for capture phases, `feat(detectionN): <short summary>` for detection phases.
   Do not push — leave for the user to review. Do not amend prior commits.

9. **Scratch work outside the repo.** Probe scripts, test harnesses, temporary files go in `/tmp/` or a scratch directory outside the project tree. Delete them when done. Never commit scratch work.

10. **Backward compatibility with existing data.** The capture changes must not break existing baselines, scans, or artifacts already stored. New fields/columns get migrations. Old data without the new fields degrades gracefully (not crashes).

11. **The SSRF policy is sacred.** Every new outbound network request — whether from Playwright, httpx, or any new library — must honor the existing SSRF validation pipeline (`app/ssrf.py`, `assert_url_allowed`, `SSRFPinningTransport`). The stealth changes must not weaken, bypass, or remove any SSRF check. The route guard in `fetcher.py:48-101` must continue to validate every subresource request.

12. **Trust nothing you have not personally re-verified.** Before relying on any claim from this prompt about line numbers, function signatures, or behavior, verify it against the actual current code. The codebase may have changed since this prompt was written. If a claim is wrong, do the right thing and log the deviation.

13. **Infrastructure and ops files must stay in sync.** When a phase adds a new dependency, changes a timeout, introduces a new environment variable, or alters any runtime behavior, the following files MUST be updated to reflect the change:
    - **`docker-compose.yml`** — if a new service, volume, environment variable, or build argument is needed (e.g., Playwright browser cache volume, new stealth-related env vars)
    - **`.env` / `.env.example`** — if any new environment variable is introduced (even optional ones), add it with a sensible default and a comment explaining what it controls
    - **`scripts/`** — if install/update/diagnostics scripts need to know about new dependencies, new browser installs, or changed timeout budgets (e.g., `install.ps1` may need to run `playwright install chromium` with new args, `diagnostics.ps1` may need to check stealth health)
    - **`docs/`** — if any user-facing behavior changes: new capture capabilities, changed timeout defaults, new scan evidence fields, new verdict logic. Update the relevant `.mdx` files in `docs/` to document the new behavior accurately. Follow the verifiable-copy discipline from Phase 34/43 of the fix effort: no absolutes, no constants pinned in prose, no claims that can silently drift from the code.
    - Every such change must be included in the SAME phase commit — infrastructure drift (code changes without matching config/docs) is a defect, not a follow-up.

14. **Fresh Docker install available for testing.** The user will provide a fresh Wardress install running in Docker before this effort begins. You have full access to test against it: run captures against real sites, execute the detection pipeline end-to-end, verify scan results in the database, inspect screenshots and artifacts. Use it aggressively — especially in Phase 6 (E2E validation) but also in earlier phases to smoke-test stealth/scrolling/banner changes against live sites before committing. **Do not run `scripts/install.ps1` or `scripts/uninstall.ps1` yourself** — the user manages the Docker deployment. If containers are not up when you need them, ASK the user to start them.

---

## 2. THE GAUNTLET LOOP (mandatory for every change, every phase)

This is the actual sequence of work. Do not skip steps. Do not collapse steps 2–4 into "I already know the fix."

**Step 1 — UNDERSTAND THE CURRENT STATE.**
Read every file you will modify, plus its callers, callees, and tests. Read the relevant `WARDRESS_FIX_LOG.md` entries for any prior fix touching the same subsystem. Understand why the code looks the way it does — many seemingly odd patterns are deliberate safety properties from the 44-phase fix effort.

**Step 2 — ROOT-CAUSE ANALYSIS.**
For each problem this phase addresses, trace the actual mechanism end to end. Not "screenshots are incomplete" but *why* they're incomplete: `page.screenshot(full_page=True)` captures the full document height, but IntersectionObserver-gated content hasn't loaded because no scroll event fired, so the page height is correct but the below-fold pixels are blank/placeholder.

**Step 3 — ENUMERATE EVERY EDGE CASE.** Before writing any code, write down the full set of conditions the change must handle:
- **Site categories**: static HTML sites, SPAs (React/Angular/Vue with client-side routing), infinite-scroll sites, sites with sticky headers/footers, sites with full-page overlays (modals, interstitials), sites that redirect to mobile versions, AMP pages, sites behind basic auth, sites that return soft-404s
- **Bot protection tiers**: no protection, Cloudflare Free (JS challenge), Cloudflare Pro/Enterprise (Turnstile), Akamai Bot Manager, DataDome, PerimeterX, Imperva, AWS WAF, custom WAFs
- **Content loading patterns**: eager loading, IntersectionObserver lazy loading, scroll-event lazy loading, infinite scroll (new content appended on scroll), progressive image loading (placeholder → full), CSS animation-triggered loading
- **Consent/banner patterns**: OneTrust, Cookiebot, CookieYes, Quantcast Choice, Google CMP, GDPR custom implementations, full-page blocking modals vs. bottom banners vs. top bars, sites that redirect to a consent page
- **Failure modes**: Chromium crash, OOM on huge pages, screenshot timeout on very tall pages, DNS resolution failure, TLS handshake failure, HTTP 403/429/503, redirect loops, content-encoding errors
- **Concurrency**: multiple scans of different sites running simultaneously in the same worker, shared browser pool vs. per-task browser
- **Backward compatibility**: existing baselines captured with the OLD method vs. new scans captured with the NEW method — will the detection pipeline produce false deltas from the capture-method change itself?
- **Performance**: capture time budget per site, memory usage, worker slot occupancy

If a category genuinely doesn't apply to this phase, write "N/A — <reason>," don't silently omit it.

**Step 4 — DESIGN THE SOLUTION.**
Consider at least two approaches. Prefer the codebase's existing patterns. Document why the chosen approach wins on correctness, performance, and consistency.

**Step 5 — IMPLEMENT.**
Minimal, scoped, idiomatic. Match the surrounding code's style.

**Step 6 — WRITE / EXTEND TESTS.**
Every edge case from Step 3 that is plausible to exercise gets a test. Tests must be hermetic (no live network in CI). Use mocking/fixture strategies consistent with the existing test suite.

**Step 7 — RUN THE FULL SUITE.**
All suites listed in Rule 4. Every one green.

**Step 8 — ITERATE ON FAILURE.**
If tests fail, go back to Step 2 or 4. Do not patch around failures.

**Step 9 — LOG AND COMMIT.**
Append the implementation log entry (format in §5), commit (Rule 8), stop.

---

## 3. MANDATORY INTAKE READING (before ANY work in ANY phase)

Before starting any phase, read completely — not skimmed:

1. **This file** — every rule applies.
2. **`Prompts\Done\Finders\WARDRESS_PARANOID_FIX_PROTOCOL.md`** — the discipline standards. Your work follows its spirit (Gauntlet rigor, proven-not-asserted, no regressions) adapted for implementation rather than finding-fixes.
3. **`Prompts\Done\Loogers\IMPLEMENTATION_LOG.md`** — prior implementation decisions and residual risks.
4. **`Prompts\Done\Loogers\WARDRESS_FIX_LOG.md`** — search it (grep) for every entry touching your phase's files and subsystems. Read those entries in full. The privacy tripwires, lint baselines, and test suites it established are permanent constraints.
5. **Every file you will edit** — completely, plus its callers and tests. Trace symbols to definitions. Verify claims against the tree.

**There is no findings file for implementation runs.** This prompt is the spec. If any claim in it proves wrong against the real tree, do the right thing instead and log the deviation in your implementation log entry.

---

## 4. THE SIX PHASES

### 4.0 Ordering Principles

1. **Capture first, detection after.** A robust capture mechanism is the foundation — detection accuracy is only as good as the data it receives.
2. **Stealth before scrolling.** If the browser is blocked by a WAF before it even loads, scrolling improvements are moot.
3. **Within capture phases**: anti-detection → content completeness → reliability/retry.
4. **Within detection phases**: dynamic content normalization → pipeline tuning → end-to-end validation.
5. **Testing is continuous** — every phase includes its own test obligations, but the final phase (6) runs the full cross-cutting validation.

---

### PHASE 1 — Stealth & Anti-Bot-Detection Hardening

**Goal:** Make Playwright captures indistinguishable from a real Chrome browser to WAFs and bot-detection systems. Sites that currently return 403/challenge pages should return their real content.

**Target files:**
- `backend/worker/fetcher.py` — primary capture function
- `backend/worker/probe.py` — metadata prober (UA rotation)
- `backend/pyproject.toml` — new dependency
- New file: `backend/worker/stealth.py` — stealth configuration module

**Root cause:** The current fetcher:
1. Uses `pw.chromium.launch(headless=True)` with default args — Chromium's headless mode exposes `navigator.webdriver=true`, missing `window.chrome` object, missing codec support, WebGL fingerprint anomalies, and other automation signals
2. Uses a custom `Wardress/0.1 SiteMonitor` User-Agent — instantly flags any WAF
3. Does not set locale, timezone, WebGL vendor, or platform overrides — the default Playwright context looks nothing like a real browser
4. Does not disable Chromium's blink automation features flag

**Design (chosen approach):**
Use `playwright-stealth` (Python package) as the base stealth layer, supplemented with custom `page.addInitScript()` patches for edge cases. This approach was chosen over:
- **Camoufox** (rejected: requires switching from Chromium to Firefox, would break the existing Playwright Chromium pipeline and any Chromium-specific behavior the detection layers depend on)
- **nodriver/CDP-direct** (rejected: requires abandoning Playwright's API entirely, massive blast radius)
- **DIY init scripts only** (rejected: maintenance burden too high, `playwright-stealth` covers 20+ detection vectors we'd have to maintain ourselves)

**Spec:**

1. **Add `playwright-stealth` dependency** to `backend/pyproject.toml`:
   ```
   uv add playwright-stealth
   ```
   Verify the package is compatible with the project's pinned Playwright version. If incompatible, fall back to vendoring the stealth JS scripts directly via `page.addInitScript()`.

2. **Create `backend/worker/stealth.py`** — a focused module that:
   - Exports an `async def apply_stealth(context)` function that applies all stealth patches to a Playwright browser context
   - Applies `playwright-stealth`'s standard patches (navigator.webdriver, chrome.runtime, codecs, permissions, WebGL, etc.)
   - Adds supplementary init scripts for:
     - Removing `window.cdc_*` properties (ChromeDriver detection)
     - Normalizing `navigator.plugins` and `navigator.mimeTypes` arrays
     - Patching `Permissions.query` to return "prompt" for notifications
     - Overriding `navigator.languages` to match the context locale
   - Sets browser launch args: `--disable-blink-features=AutomationControlled`
   - **DOES NOT** weaken any SSRF check — the route guard (`_make_ssrf_route_guard`) must still be applied AFTER stealth patches

3. **Modify `fetcher.py:fetch_page()`**:
   - Add `--disable-blink-features=AutomationControlled` to `pw.chromium.launch()` args
   - Replace the `Wardress/0.1 SiteMonitor` User-Agent with a realistic, current Chrome UA string for the context (not for the probe — the probe's UA rotation is separate and intentional)
   - Set realistic context properties: `locale="en-US"`, `timezone_id="America/New_York"`, `color_scheme="light"`, `viewport={"width": 1366, "height": 768}` (standard laptop resolution)
   - Call `apply_stealth(context)` before creating the page
   - The SSRF route guard (`page.route("**/*", ...)`) must be applied AFTER stealth initialization — stealth scripts must never override or interfere with the guard
   - **Keep** the existing `ignore_https_errors=False` — TLS errors should fail the capture (layer 6 uses `probe.py` for cert observation, not the fetcher)

4. **Modify `probe.py`** — the probe's `USER_AGENTS` dictionary for UA rotation (layer 7 cloaking detection):
   - Update all three UA strings to current-year versions (the current ones say `Chrome/126.0.0.0` — update to the latest stable Chrome version at time of implementation)
   - The probe is intentionally NOT stealthed — it uses raw httpx, and layer 7 compares raw-UA responses against the Playwright-rendered response. Stealth applies only to the Playwright capture.

5. **Cloudflare challenge page detection** — add a post-navigation check in `fetch_page()`:
   After the page loads and settles, check if the page is a Cloudflare challenge/block page by looking for known indicators:
   - Title contains "Just a moment" or "Attention Required"
   - Body contains `cf-challenge-running` or `cf-error-details` classes
   - HTTP status is 403 with `cf-ray` header present
   If detected: wait up to 10 seconds for the challenge to auto-solve (Cloudflare JS challenges often auto-complete for real browsers), then re-check. If still blocked after retry, raise `FetchError("Site is behind bot protection that could not be bypassed (Cloudflare challenge detected)")` — a clear, user-safe error that tells the operator what happened, not a generic timeout.

**Edge cases to handle:**
- Stealth patches must not break legitimate Playwright functionality (screenshots, page.content(), route interception)
- Stealth patches must not interfere with the SSRF route guard (test explicitly)
- Browser launch args must not conflict with Docker/container environment (headless mode in containers)
- The stealth module must degrade gracefully if `playwright-stealth` is not installed (log warning, continue without stealth) — for dev environments that don't install it
- Memory: stealth init scripts add negligible overhead (<1KB JS)
- Concurrency: stealth is stateless and per-context, no shared state between captures

**Test obligations:**
- `tests/test_stealth.py`:
  - Test that `apply_stealth()` doesn't crash on a fresh context
  - Test that `navigator.webdriver` is `undefined` (not `true`) after stealth
  - Test that the SSRF route guard still blocks internal addresses after stealth is applied
  - Test that `fetch_page()` with stealth produces valid HTML and screenshots
  - Test Cloudflare challenge detection logic (mock a challenge page HTML, verify detection and wait behavior)
- All existing `tests/test_fetcher*.py` and `tests/test_scan_tasks.py` must still pass

**DO NOT DISTURB:**
- `worker/detection/` — no detection layer changes in this phase
- `worker/probe.py`'s `_redirect_guard` and SSRF transport — these are separate from the fetcher's stealth
- `app/ssrf.py` — the SSRF policy is sacred, never modify it
- The `FetchResult` dataclass — no new fields needed for stealth

---

### PHASE 2 — Smart Scrolling & Lazy-Content Capture

**Goal:** Ensure `full_page=True` screenshots and `page.content()` capture ALL visible content, including IntersectionObserver-gated lazy-loaded images, below-fold content, and dynamically loaded sections.

**Target files:**
- `backend/worker/fetcher.py` — add scrolling logic
- New file: `backend/worker/page_prepare.py` — page preparation utilities (scrolling, waiting)

**Root cause:** Playwright's `page.screenshot(full_page=True)` renders the document at its full height, but:
1. `IntersectionObserver` callbacks only fire when elements enter the viewport via scroll events — without scrolling, lazy-loaded images remain as placeholder `<img>` tags with `loading="lazy"` or data-src attributes
2. Scroll-event-triggered lazy loading (older pattern) similarly requires actual scroll events
3. The 2-second `SETTLE_MS` is insufficient for heavy JS sites where `DOMContentLoaded` fires early but rendering continues for 5-10+ seconds
4. Sticky headers/footers and floating elements can obscure content in viewport-based captures

**Design (chosen approach):**
Implement an incremental auto-scroll function that scrolls the page from top to bottom in viewport-sized steps, pausing at each step to let lazy content load. This was chosen over:
- **Single scroll-to-bottom** (rejected: doesn't trigger IntersectionObserver reliably — the observer needs the element to enter the viewport gradually, not just exist below it)
- **Inject JS to force all lazy images to load** (rejected: would need to handle every lazy-loading library's API; scrolling is universal)
- **Network-idle waiting only** (rejected: Playwright docs explicitly discourage `networkidle` — pages with analytics/beacons/long-polling never go idle)

**Spec:**

1. **Create `backend/worker/page_prepare.py`** with:

   ```python
   async def auto_scroll_page(page, *, max_scroll_time_ms: int = 20_000, step_pause_ms: int = 300) -> dict:
   ```

   The function:
   - Scrolls the page from current position to the bottom in steps of `window.innerHeight * 0.8` (80% viewport height — ensures overlap for IntersectionObserver trigger)
   - At each step: `window.scrollBy(0, step)`, then wait `step_pause_ms` for lazy content to trigger
   - Monitors `document.body.scrollHeight` — if it stops growing for 2 consecutive steps, the page has fully loaded
   - **Hard time cap**: stops after `max_scroll_time_ms` regardless (protects against infinite-scroll sites that never stop growing)
   - After reaching bottom, scrolls back to top (`window.scrollTo(0, 0)`) — the screenshot should capture from the top
   - Returns evidence dict: `{"scroll_steps": N, "initial_height": H0, "final_height": H1, "capped": bool, "scroll_time_ms": T}`
   - **Never raises** — any failure during scrolling (JS error, page crash) is caught, logged, and the capture continues with whatever content is available. A failed scroll is better than a failed capture.

   ```python
   async def wait_for_content_stable(page, *, timeout_ms: int = 5_000, poll_ms: int = 500) -> dict:
   ```

   The function:
   - After scrolling, waits for the DOM to stabilize: polls `document.body.innerHTML.length` every `poll_ms`; when the length stops changing for 2 consecutive polls, content is stable
   - Hard timeout at `timeout_ms`
   - Returns evidence dict: `{"stable": bool, "polls": N, "final_length": L}`
   - **Never raises.**

2. **Modify `fetcher.py:fetch_page()`** — insert the scrolling sequence between navigation and capture:

   Current flow:
   ```
   response = await page.goto(url, ...)
   await page.wait_for_timeout(SETTLE_MS)
   html = await page.content()
   screenshot = await page.screenshot(...)
   ```

   New flow:
   ```
   response = await page.goto(url, ...)
   await page.wait_for_timeout(SETTLE_MS)          # initial settle (now 5s)
   scroll_evidence = await auto_scroll_page(page, max_scroll_time_ms=20_000)
   stability_evidence = await wait_for_content_stable(page, timeout_ms=5_000)
   html = await page.content()
   screenshot = await page.screenshot(...)
   ```

3. **Update timeout constants** in `fetcher.py`:
   - `NAV_TIMEOUT_MS`: 45_000 → **60_000** (60s navigation timeout)
   - `SCREENSHOT_TIMEOUT_MS`: 30_000 → **45_000** (45s screenshot — very tall pages after scrolling take longer)
   - `SETTLE_MS`: 2_000 → **5_000** (5s initial settle — gives heavy JS sites more time before scrolling starts)
   - **New**: `MAX_SCROLL_TIME_MS = 20_000` — hard cap on scroll time
   - Verify the total worst-case time budget: 60s nav + 5s settle + 20s scroll + 5s stability + 45s screenshot = 135s. The Celery soft limit is 300s with probe work at ~20s, so 135+20 = 155s — well within budget.

4. **Screenshot height cap** — add a safety limit on screenshot height:
   - After scrolling, very tall pages (infinite scroll that hit the time cap) could be 50,000+ pixels tall
   - Cap screenshot height at `MAX_SCREENSHOT_HEIGHT = 16_384` pixels (16K — well beyond any reasonable page, but prevents OOM on truly infinite pages)
   - If the page is taller, use `page.screenshot(full_page=False, clip={"x": 0, "y": 0, "width": viewport_width, "height": MAX_SCREENSHOT_HEIGHT})` instead
   - Record this in the evidence: `"screenshot_capped": true, "actual_height": H`

5. **Store scroll/stability evidence** — add the evidence to `FetchResult`:
   - Add an optional `capture_evidence: dict | None` field to `FetchResult` (default `None` for backward compatibility)
   - Populate it with `{**scroll_evidence, **stability_evidence}`
   - The scan task stores this in `scan.layer_scores` or a new `scan.capture_evidence` JSON column (if adding a column, add a migration) — this metadata is invaluable for debugging capture issues

**Edge cases:**
- **Infinite scroll sites** (Twitter, Reddit, etc.): the `max_scroll_time_ms` cap prevents infinite scrolling; the page is captured at whatever height was reached
- **Sites that crash on scroll** (JS errors): auto_scroll_page catches all exceptions and continues
- **Sites with no scrollable content**: the function detects `scrollHeight <= viewportHeight` immediately and returns without scrolling
- **Sticky headers/footers**: Playwright's `full_page=True` handles these natively (captures the full document, not the viewport)
- **iframes**: Playwright's `page.content()` serializes the top frame only (same as before); iframe content is cross-origin and not capturable (same limitation as before, documented in audit finding 4.1)
- **Backward compatibility**: existing baselines were captured without scrolling. The first scan after this change will see a DOM/screenshot difference from the new below-fold content loading. This is a ONE-TIME false positive that will self-heal after the next rebaseline. Document this in the release notes / migration guide.

**Test obligations:**
- `tests/test_page_prepare.py`:
  - Test `auto_scroll_page` with a mock page that reports increasing `scrollHeight`
  - Test `auto_scroll_page` with a mock page that never stops growing (time cap triggers)
  - Test `auto_scroll_page` with a mock page where scrolling raises JS error (graceful degradation)
  - Test `wait_for_content_stable` with a page whose length stabilizes after 3 polls
  - Test `wait_for_content_stable` with a page that never stabilizes (timeout triggers)
- All existing fetcher/scan tests must still pass (the new scrolling is additive)

**DO NOT DISTURB:**
- The SSRF route guard — it must remain active during scrolling
- `probe.py` — the probe does raw httpx fetches, not Playwright renders; scrolling doesn't apply
- `worker/detection/` — no detection changes in this phase
- `worker/scan_tasks.py` — only touch if adding the `capture_evidence` column

---

### PHASE 3 — Cookie/Consent Banner Dismissal & Capture Reliability

**Goal:** Auto-dismiss common cookie/consent banners before capture, implement retry-with-backoff for transient failures, and add a "capture health" signal that operators can monitor.

**Target files:**
- `backend/worker/fetcher.py` — banner dismissal, retry logic
- New file: `backend/worker/banner_dismiss.py` — banner dismissal module
- `backend/worker/scan_tasks.py` — capture health metadata

**Root cause:** Every capture uses a fresh browser context (no persisted cookies), so every capture hits first-visit consent banners. These banners:
1. Obscure page content in screenshots (visual layer sees the banner, not the page)
2. Block interaction (full-page modal overlays prevent scroll-based lazy loading)
3. Add DOM elements that change between captures (different banner text/buttons each time — DOM churn noise)

**Design:** Use a two-phase banner dismissal approach:
1. **Pre-navigation cookie injection**: Set common consent cookies (`OptanonAlertBoxClosed`, `CookieConsent`, `cookieyes-consent`, etc.) via `context.add_cookies()` BEFORE navigating — this prevents banners from appearing at all on sites that check cookies first
2. **Post-navigation click dismissal**: After the page loads but BEFORE scrolling, attempt to click known consent buttons using a curated selector list — catches banners that appear regardless of cookies

**Spec:**

1. **Create `backend/worker/banner_dismiss.py`**:

   ```python
   # Common consent cookies to inject pre-navigation.
   # These prevent banner display on sites that check cookies before rendering.
   CONSENT_COOKIES: list[dict] = [
       {"name": "OptanonAlertBoxClosed", "value": "<current_iso_time>", "domain": ""},  # OneTrust
       {"name": "CookieConsent", "value": "{stamp:%27-1%27,necessary:true,...}", "domain": ""},  # Cookiebot
       {"name": "cookieyes-consent", "value": "{...accepted categories...}", "domain": ""},  # CookieYes
       {"name": "euconsent-v2", "value": "...", "domain": ""},  # IAB TCF v2
       # ... (research and add the top 10-15 most common CMP cookies)
   ]

   # Post-load click targets, tried in priority order. Each is a CSS selector
   # for an "accept all" or "close" button. The first match wins.
   DISMISS_SELECTORS: list[str] = [
       "#onetrust-accept-btn-handler",                          # OneTrust
       "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll", # Cookiebot
       ".cc-accept-all", ".cc-btn.cc-dismiss",                  # CookieConsent (generic)
       "[data-testid='cookie-policy-dialog-accept-button']",    # Various
       "button[aria-label*='Accept']",                          # Accessible banners
       "button[aria-label*='accept']",
       "button[aria-label*='Agree']",
       ".cmp-accept-all",                                       # Generic CMP
       "#accept-cookies", "#acceptCookies",                     # Common IDs
       ".js-cookie-accept", ".cookie-accept",                   # Common classes
       # Add 20-30 more selectors based on research of top CMPs
   ]
   ```

   ```python
   async def inject_consent_cookies(context, url: str) -> list[str]:
       """Inject consent cookies for the target domain before navigation.
       Returns list of cookie names injected. Never raises."""

   async def dismiss_banners(page, *, timeout_ms: int = 3_000) -> dict:
       """Attempt to click dismiss/accept buttons on cookie banners.
       Tries each selector; clicks the first visible match.
       Returns evidence: {"dismissed": bool, "selector": str|None, "attempts": int}.
       Never raises — a failed dismissal is not a capture failure."""
   ```

2. **Integrate into `fetcher.py:fetch_page()`** — the new flow becomes:
   ```
   context = await browser.new_context(...)
   apply_stealth(context)                              # Phase 1
   inject_consent_cookies(context, url)                 # Phase 3 (this phase)
   page = await context.new_page()
   page.route("**/*", ssrf_guard)                       # SSRF — always last before nav
   response = await page.goto(url, ...)
   await page.wait_for_timeout(SETTLE_MS)
   banner_evidence = await dismiss_banners(page)        # Phase 3
   scroll_evidence = await auto_scroll_page(page, ...)  # Phase 2
   stability = await wait_for_content_stable(page, ...) # Phase 2
   html = await page.content()
   screenshot = await page.screenshot(...)
   ```

3. **Retry logic** — add retry-with-backoff for transient capture failures:
   - If `page.goto()` fails with a timeout or network error (not SSRF block, not FetchError), retry ONCE after a 3-second pause
   - If the Cloudflare challenge detection (Phase 1) fires but the challenge doesn't auto-solve, retry ONCE with a longer wait (15s instead of 10s)
   - Maximum 2 total attempts (1 original + 1 retry) — never retry indefinitely
   - Log retries at WARNING level with the reason
   - Store retry count in `FetchResult.capture_evidence`

4. **Capture health signal** — add fields to scan output:
   - `scan.capture_evidence` JSON: merge banner_evidence, scroll_evidence, stability_evidence, retry count, stealth status, total capture wall-clock time
   - This field is informational — it does NOT affect detection scores or verdicts
   - Operators can filter/sort by capture issues in the scan history
   - Add a simple health indicator to the scan summary: `capture_quality: "full" | "partial" | "degraded"` based on:
     - "full": no retries, banner dismissed or none present, scroll completed, content stable
     - "partial": retry succeeded, or scroll capped, or banner not dismissed
     - "degraded": retry failed, or critical capture step failed (but capture still completed)

**Edge cases:**
- **Consent cookie injection must use the correct domain** — parse the URL's domain and set cookies for it, not a wildcard. `context.add_cookies()` requires a domain or URL.
- **Banner dismissal click must be safe** — only click if the element is visible and within the viewport. Never click elements that might navigate away from the page.
- **Some banners use iframes** — the dismiss selectors should also check `page.frames()` for common consent iframe patterns (e.g., Quantcast's iframe)
- **Retry must not double-count the capture** — on retry, clear the previous attempt's partial state
- **The SSRF route guard must survive across retries** — it's per-page, so a new page on retry gets its own guard

**Test obligations:**
- `tests/test_banner_dismiss.py`:
  - Test cookie injection for various URL formats (https, http, with/without www, with port)
  - Test dismiss_banners with mock pages containing known banner selectors (should find and click)
  - Test dismiss_banners with a page containing no banners (should return gracefully)
  - Test dismiss_banners with a page where the banner selector exists but is not visible (should skip)
- `tests/test_fetcher_retry.py`:
  - Test retry on transient timeout (should succeed on second attempt)
  - Test no retry on SSRF block (should fail immediately)
  - Test no retry on permanent FetchError (should fail immediately)
  - Test retry count cap (should never attempt more than 2 total)

**DO NOT DISTURB:**
- The SSRF route guard — must remain active on every attempt
- `probe.py` — the probe is a separate, intentionally un-stealthed path
- Detection layers — no changes

---

### PHASE 4 — Dynamic Content Normalization for Detection

**Goal:** Reduce false positives from legitimate dynamic content (timestamps, rotating headlines, ad slots, A/B variants, nonce-varying headers) by normalizing known-volatile content before detection comparison.

**Target files:**
- New file: `backend/worker/detection/normalize.py` — content normalization module
- `backend/worker/detection/pipeline.py` — integrate normalization
- `backend/worker/detection/dom.py` — adjust churn scoring for normalized content
- `backend/worker/detection/metadata.py` — header normalization (nonce-CSP)

**Root cause:** The detection pipeline compares baseline and current page content literally. Any legitimate change — no matter how expected or routine — produces nonzero layer scores, which contribute to fused risk. The fusion model (post-refit) correctly assigns low individual weight to each noise source, but when multiple noise sources compound (timestamp + ad slot + headline + CSP nonce), the cumulative effect can push risk above the material-change threshold and produce a "changed" verdict with elevated cadence.

**Design:** Add a **pre-comparison normalization pass** that strips known-volatile patterns from BOTH sides before layers 2/3/5/8 see them. This is structurally identical to the existing suppression mechanism (`worker/detection/suppress.py`) but is AUTOMATIC (no per-site configuration needed) and operates on patterns that are universally noise, not site-specific exclusions.

Key principle: **normalization must be conservative.** A pattern is only normalized if it is essentially impossible for it to be attack evidence. Timestamps, UUIDs, and nonce values are safe to normalize. Headline text is NOT safe (a defaced headline IS an attack). When in doubt, leave it for the detection layers to score.

**Spec:**

1. **Create `backend/worker/detection/normalize.py`**:

   Content normalization module that strips known-volatile patterns from BOTH sides of a comparison before content layers see them. Normalization is CONSERVATIVE: only universally-noise patterns are stripped. Anything that COULD be attack evidence is left untouched.

   The normalized copy is used only by content layers (2/3/5/8); layer 1 (hash) always sees the original (it's a tamper-evidence anchor), and layer 4 (visual) compares screenshots, not text.

   Every normalization is recorded in evidence so operators can see exactly what was stripped and why.

   **Patterns to normalize:**
   - ISO 8601 timestamps (2026-08-30T12:00:00Z, etc.)
   - Unix timestamps (10-13 digits in common epoch range)
   - Common human-readable date formats (Aug 30, 2026 / 30/08/2026 etc.)
   - UUIDs (v4 and others)
   - Cache-busting query parameters (?v=xxx, ?_=xxx, ?cb=xxx, ?t=xxx)
   - CSP nonces ('nonce-abc123...')
   - CSRF tokens in form hidden fields
   - All replacements use a fixed `[[NORMALIZED]]` placeholder string
   - Return both the normalized HTML and an evidence dict mapping pattern_name → count

2. **Modify `pipeline.py:run_detection()`** — apply normalization:
   - After the suppression step and before the content layers run, apply `normalize_html()` to BOTH sides
   - Normalization applies only to content layers (layers 2/3/5/8), NOT to:
     - Layer 1 (hash) — always uses the original (tamper-evidence anchor)
     - Layer 4 (visual) — compares screenshots, not text
     - Layer 6 (metadata) — has its own header comparison logic
     - Layer 7 (cloaking) — compares raw UA-variant HTML directly
   - Record normalization evidence in affected layers' evidence dicts

3. **Modify `metadata.py`** — CSP nonce normalization:
   - In the security header comparison logic, strip CSP nonces from BOTH sides before comparing
   - A CSP policy that differs ONLY in nonces should produce score 0.0 (same policy, different nonces = no security change)
   - A CSP policy that changes directives (not just nonces) should still score as before

4. **Consider but explicitly decide against** normalizing:
   - **Headline text** — a changed headline could be a defacement. Leave for layer 5 signatures and layer 8 semantics to evaluate.
   - **Image URLs** — a changed image URL could be an asset-swap defacement. Leave for layers 3/4.
   - **Ad slot content** — too variable to pattern-match reliably. Leave for per-site suppression rules.
   - Document these decisions in the implementation log.

**Edge cases:**
- **Normalization must be applied identically to BOTH sides** — applying it to one side only would create artificial differences
- **Pattern matching must not corrupt HTML structure** — replacing a timestamp inside an attribute value must not break the tag. Using a fixed placeholder string is safe.
- **Very aggressive normalization could mask real attacks** — e.g., an attacker injecting a Unix timestamp as a C2 beacon URL would have the timestamp normalized away. This is acceptable because the URL itself (the real signal) is NOT normalized, only the timestamp portion.
- **Performance** — regex-based normalization on very large HTML could be slow. Profile and optimize if needed (compile patterns once at module level, use early-exit when no matches).

**Test obligations:**
- `tests/test_normalize.py`:
  - Test each pattern individually (ISO timestamp, Unix timestamp, UUID, etc.)
  - Test that normalization is idempotent (normalizing already-normalized text produces the same result)
  - Test that normalization doesn't corrupt HTML structure
  - Test that normalization doesn't strip legitimate content (headlines, body text without timestamps)
  - Test the evidence dict counts
  - Test with empty HTML, very large HTML, non-ASCII HTML
- `tests/test_pipeline_normalization.py`:
  - Integration test: baseline and scan HTML that differ ONLY in timestamps should produce near-zero content-layer scores
  - Integration test: baseline and scan HTML that differ in timestamps AND have real injection should still flag

**DO NOT DISTURB:**
- `worker/detection/suppress.py` — suppression is per-site user-configured; normalization is automatic. They compose (suppression runs first, then normalization on the suppressed copy).
- `worker/hashing.py` — layer 1 hash always uses the original, unnormalized content
- The fusion model artifact (`training/fusion_model.json`) — no refit needed; normalization reduces noise inputs, it doesn't change what the model was trained on

---

### PHASE 5 — Detection Pipeline Tuning & Noise Reduction

**Goal:** Tune detection layer thresholds and scoring to reduce false positive verdicts on naturally dynamic sites, without weakening detection of real attacks. The fusion model itself is NOT retrained — the tuning is in the layers that feed it.

**Target files:**
- `backend/worker/detection/dom.py` — churn scoring refinement
- `backend/worker/detection/metadata.py` — header diff refinement
- `backend/worker/detection/semantics.py` — drift scoring refinement
- `backend/worker/detection/cloaking.py` — threshold adjustment
- `backend/worker/scan_tasks.py` — verdict logic refinement

**Root cause of remaining false positive patterns** (after Phases 1-4 have landed):

1. **Layer 2 (DOM)**: legitimate redesigns/deploys can produce churn scores of 0.4-0.6, which the positive-coefficient fusion model weighs as mild attack evidence.

2. **Layer 6 (metadata)**: even after CSP nonce normalization (Phase 4), legitimate header changes (HSTS max-age bump, new CSP directive for a real feature) score as "weakened" because the comparison is direction-blind.

3. **Verdict logic**: the `changed` verdict triggers on ANY nonzero layer score from a non-skipped layer (`scan_tasks.py:275-279`). This means a site with timestamp churn + CSP nonce = "changed" on every scan, even with risk near zero. Operators lose trust when every scan says "changed" but risk is 0.03.

**Spec:**

1. **Refine the `changed` verdict threshold** in `scan_tasks.py`:
   - Currently: `changed = any((r.get("score") or 0.0) > 0.0 for k, r in results.items() if ...)`
   - Proposed: introduce a `NOISE_FLOOR = 0.02` — layer scores below this are treated as measurement noise, not change signal
   - New: `changed = any((r.get("score") or 0.0) > NOISE_FLOOR for k, r in results.items() if ...)`
   - This means a site where all layers score ≤0.02 gets verdict "clean" instead of "changed"
   - **This is safe because**: the fusion model already produces near-zero risk for these vectors, and the rule-based floors (layer 5 ≥ 0.85 → floor 0.90, layer 7 ≥ 0.85 → floor 0.90) guarantee that real attacks with strong signals bypass this floor entirely
   - The noise floor must NEVER affect the `flagged` verdict — that's driven by `risk >= site.flag_threshold`, independent of `changed`

2. **Add direction-aware header scoring** to `metadata.py`:
   - Currently: any header value change → score increment (direction-blind)
   - Proposed: parse CSP directives semantically — more restrictive = 0.0 (improvement), less restrictive = score increment (weakening), directive removed = higher score
   - For HSTS: longer max-age or added includeSubDomains/preload = 0.0 (improvement), shorter max-age or removed flags = score increment
   - For other headers: keep current scoring (direction inference is too complex for arbitrary headers)
   - **Conservative principle**: if direction cannot be determined, treat as weakening (fail-safe)

3. **Refine layer 2 churn scoring** in `dom.py`:
   - Add a **content-type awareness**: if the added elements are primarily `<article>`, `<p>`, `<li>`, `<div>` (content containers) and NOT `<script>`, `<iframe>`, `<form>`, `<link>` (sensitive infrastructure), reduce the churn contribution by applying a reduced multiplier for "content-only churn"
   - This distinguishes "site added 5 news articles" (content churn, low risk) from "site added 5 scripts" (infrastructure change, high risk)
   - The sensitive_score boost already handles the infrastructure case — this refinement reduces the score for the benign case

4. **Adjust adaptive cadence sensitivity** in `scan_tasks.py`:
   - Currently: `MATERIAL_CHANGE_RISK = 0.15` triggers cadence tightening
   - Verify this is appropriate after Phases 1-4. If the noise floor is working correctly, most benign-dynamic sites should score below 0.15 consistently
   - If testing shows that dynamic sites still hover around 0.10-0.14, consider raising to 0.20
   - **Document the decision** either way with measured data

**Edge cases:**
- **The noise floor must NOT hide a real attack** — verify against the measured attack vectors from the fusion training dataset: every scenario there scored well above 0.02 on at least one layer
- **CSP direction parsing must handle edge cases**: CSP policies with multiple directives, CSP-Report-Only vs CSP, policies with wildcards, policies with hashes/nonces
- **Content-type awareness in layer 2 must not be gameable** — an attacker wrapping a malicious `<script>` inside a `<div>` must still trigger the sensitive_score boost (because the `<script>` is still detected by existing sensitive-tag logic)

**Test obligations:**
- `tests/test_noise_floor.py`:
  - Test that a scan with all layer scores ≤ 0.02 produces verdict "clean"
  - Test that a scan with layer 5 = 0.90 (signature match) still produces verdict "flagged" regardless of noise floor
  - Test that the noise floor does NOT affect risk score or flagging
- `tests/test_metadata_direction.py`:
  - Test CSP tightening → score 0.0
  - Test CSP weakening → positive score
  - Test CSP removal → higher score
  - Test HSTS improvement → score 0.0
  - Test HSTS weakening → positive score
  - Test nonce-only CSP change → score 0.0 (already handled by Phase 4)
- `tests/test_dom_content_churn.py`:
  - Test adding content elements (article, p, li) → reduced score vs baseline
  - Test adding infrastructure elements (script, iframe) → same or higher score than baseline
- Rerun ALL existing detection tests — they must all still pass

**DO NOT DISTURB:**
- The fusion model artifact — no refit
- Rule-based floors in `fusion.py` — they are model-independent safety nets
- Layer 5 (signatures) — its scoring is already well-calibrated
- Layer 4 (visual) — its scoring is separate from text-based noise
- The suppression mechanism — it's per-site, orthogonal to this

---

### PHASE 6 — End-to-End Validation & Hardened Test Suite

**Goal:** Validate all five prior phases end-to-end against a comprehensive real-world test site list. Produce a hardened test suite that catches regressions in capture and detection behavior. This is the validation gate — all prior work is proven here.

**Target files:**
- New file: `backend/tests/test_capture_e2e.py` — end-to-end capture tests
- New file: `backend/tests/test_detection_e2e.py` — end-to-end detection tests
- New file: `backend/tests/test_sites_comprehensive.txt` — expanded test site list
- `backend/tests/conftest.py` — shared fixtures for e2e tests

**Spec:**

1. **Build the comprehensive test site list** (`test_sites_comprehensive.txt`):

   Start with the existing `wardress-test-sites (1).txt` (112 URLs) and ADD 30-40 sites specifically chosen to stress every failure mode. Categorize each site:

   The categories must include AT LEAST:
   - 10 SPA/heavy-JS sites (React, Angular, Vue, SvelteKit, Next.js sites)
   - 5 Cloudflare-protected sites (Discord, Medium, Cloudflare.com, etc.)
   - 10 lazy-loading sites (image galleries, Pinterest, Unsplash, etc.)
   - 10 cookie-banner sites (BBC, Guardian, German/French news sites)
   - 5 non-Latin sites (Arabic, Japanese, Chinese, Russian, Bengali)
   - 5 government/high-security sites (gov.uk, whitehouse.gov, canada.ca)
   - 5 static control sites (example.com, w3.org, ietf.org)
   - 5 e-commerce/high-churn sites (Amazon, eBay, Etsy)

2. **End-to-end capture validation** (`test_capture_e2e.py`):

   > **IMPORTANT: These tests require LIVE NETWORK ACCESS and must be marked with `@pytest.mark.network` so CI can skip them.** They are NOT run in CI — they are run manually as a validation gate.

   For each category in the test list:
   - Capture the site using the new `fetch_page()` (with stealth, scrolling, banner dismissal)
   - Assert: HTML is non-empty and contains expected structural elements
   - Assert: screenshot is a valid PNG with reasonable dimensions (width ~1366, height > viewport height for scrollable sites)
   - Assert: `capture_evidence` shows scroll completed (not capped) for finite sites
   - Assert: for cookie-banner sites, banner evidence shows dismissal attempted
   - Assert: for Cloudflare-protected sites, the response is NOT a challenge page
   - Assert: HTTP status is 200 (not 403/429/503)
   - Record per-category success rates and capture times

   **Expected results**: ≥90% of sites in each category should capture successfully. Document any persistent failures with root-cause analysis.

3. **End-to-end detection validation** (`test_detection_e2e.py`):

   > **These are HERMETIC tests (no live network).** They use captured fixture data.

   Build test fixtures from representative capture pairs:
   - **Benign dynamic content**: capture pair where only timestamps/nonces changed. Assert: verdict is "clean", risk < 0.10.
   - **Benign with CSP nonce change**: same page, different CSP nonce. Assert: layer 6 score = 0.0 after normalization.
   - **Real defacement**: injected defacement signature. Assert: verdict is "flagged", risk > 0.5.
   - **Asset-swap defacement**: same HTML, different screenshot. Assert: layer 4 produces nonzero score.
   - **SEO spam injection**: hidden links injected. Assert: layers 2+3 detect them.
   - **False positive regression**: verify the known attack vectors from the fusion training dataset still produce appropriate scores.

4. **Capture consistency test** — the most critical test:
   - Capture the SAME site TWICE in succession (1 minute apart)
   - Run detection on the pair (first capture = baseline, second = scan)
   - Assert: verdict is "clean" for static sites, risk < 0.05
   - Assert: for dynamic sites, verdict is at most "changed" with risk < 0.15
   - This directly measures capture-induced false positives

5. **Performance regression test**:
   - Time the capture of 5 representative sites (1 static, 1 SPA, 1 lazy-load, 1 Cloudflare, 1 cookie-banner)
   - Assert: median capture time < 30 seconds
   - Assert: P95 capture time < 60 seconds
   - Compare with baseline pre-change capture times (record both)

6. **Reporting** — produce a summary table:

   ```
   | Category        | Sites | Captured | Failed | Avg Time | Notes           |
   |-----------------|-------|----------|--------|----------|-----------------|
   | SPA/JS Heavy    | 10    | ?        | ?      | ?        |                 |
   | Cloudflare      | 5     | ?        | ?      | ?        |                 |
   | Lazy Loading    | 10    | ?        | ?      | ?        |                 |
   | Cookie Banner   | 10    | ?        | ?      | ?        |                 |
   | Non-Latin       | 5     | ?        | ?      | ?        |                 |
   | Gov/Security    | 5     | ?        | ?      | ?        |                 |
   | Static Control  | 5     | ?        | ?      | ?        |                 |
   | E-commerce      | 5     | ?        | ?      | ?        |                 |
   | TOTAL           | 55+   | ?        | ?      | ?        | Target: ≥90%    |
   ```

   Record this table in the implementation log entry for this phase.

---

## 5. IMPLEMENTATION LOG ENTRY FORMAT

After each phase, append an entry to `Prompts\Done\Loogers\IMPLEMENTATION_LOG.md`:

```
### [DONE / PARTIAL] PROMPT-002 Phase N — <phase title>

- **Prompt**: PROMPT-002-capture-hardening-and-detection-accuracy.md
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
```

---

## 6. THE KICKOFF PROMPT (paste into a new chat to start/continue any phase)

```
Before anything else: read C:\Users\Ns8pc\Music\WARDRESS\Prompts\Pending\Finders\PROMPT-002-capture-hardening-and-detection-accuracy.md COMPLETELY, start to finish — every rule, every phase spec. Do not skim. Do not jump to a section. Read every line from §0 through §7 before doing anything else.

Then read these files COMPLETELY, in order:
1. C:\Users\Ns8pc\Music\WARDRESS\Prompts\Done\Finders\WARDRESS_PARANOID_FIX_PROTOCOL.md — its Gauntlet Loop discipline (§2) applies to your work. Read the full file, not just the phase list.
2. C:\Users\Ns8pc\Music\WARDRESS\Prompts\Done\Loogers\IMPLEMENTATION_LOG.md — every prior implementation entry, including design decisions and residual risks.
3. C:\Users\Ns8pc\Music\WARDRESS\Prompts\Done\Loogers\WARDRESS_FIX_LOG.md — grep for every entry touching fetcher.py, probe.py, stealth, ssrf, detection/pipeline.py, scan_tasks.py, and the detection layers. Read those entries IN FULL. Pay special attention to Phase 6 (hash gate fix), Phase 16 (SSRF fixes), Phase 24 (degradation signaling), and Phase 36 (layer 4 chroma shift).

Then read the ACTUAL current code for every file this phase targets — with read_file, tracing symbols to definitions and callers:
- backend/worker/fetcher.py (the entire file, plus every caller of fetch_page)
- backend/worker/probe.py (the entire file)
- backend/worker/scan_tasks.py (at minimum the _capture_baseline and _run_scan functions)
- backend/worker/detection/pipeline.py (understand the layer flow)
- backend/app/ssrf.py (understand the SSRF policy you must never weaken)
- backend/pyproject.toml (check existing dependencies)
- docker-compose.yml (understand current service definitions and env vars)
- .env / .env.example (understand current environment configuration)
- scripts/ directory (understand install/update/diagnostics scripts)
- docs/ directory (understand current documentation claims)
- backend/tests/ — find every existing test file for fetcher, scan_tasks, and SSRF

Verify every claim in the prompt against the real tree. If any line number, function signature, or behavior described in the prompt is wrong, do the right thing instead and log the deviation.

IMPORTANT: A fresh Wardress install is running in Docker and available for you to test against. Use it to smoke-test captures against real sites, run the detection pipeline end-to-end, and verify results. If the containers are not up when you need them, ASK me to start them — do not run install/uninstall scripts yourself.

Execute the next incomplete phase now, following every rule in §1 (including Rule 13: keep docker-compose.yml, .env, scripts/, and docs/ in sync with your changes) and the full Gauntlet Loop in §2 exactly. No scope creep. Full existing test suite must be green before you're done.

When done: append your implementation log entry, commit (do not push), then stop.
```

---

## 7. A NOTE ON DISCIPLINE

The capture mechanism is the foundation of everything Wardress does. A monitoring tool that cannot reliably see the sites it monitors is worse than no monitoring tool at all — it provides false confidence. Every shortcut in this implementation — a stealth patch that breaks the SSRF guard, a scroll function that crashes on edge cases, a normalization pattern that masks real attacks — directly undermines the product's core promise.

The detection pipeline has already survived a 44-phase adversarial audit and fix effort. The fusion model was refitted with 646 measured samples and constrained non-negative coefficients. The rule-based floors guarantee that conclusive evidence always surfaces. Do not undo this work by introducing normalization that is too aggressive, thresholds that are too forgiving, or verdicts that hide genuine change. When in doubt, err on the side of alerting — a false positive wastes an operator's time; a false negative costs a breach.

Depth over speed, every phase, every change. The six-phase structure exists so that depth never has to compete with a shrinking context window.
