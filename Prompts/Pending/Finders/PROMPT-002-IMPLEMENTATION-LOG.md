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
- **Next phase kickoff prompt**: (the kickoff prompt for the next phase)
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
- **Commit**: (pending)
- **Next phase kickoff prompt**: (below)


