# PROMPT-001 — Restore Dashboard Imagery + Complete Audit Filter Coverage

> **How to use:** paste everything below the divider into a fresh chat.

---

Before anything else, read these files COMPLETELY, start to finish, in this order — not
skimmed, not partially:

1. `C:\Users\Ns8pc\Music\WARDRESS\Prompts\WARDRESS_PARANOID_FIX_PROTOCOL.md` — its rules,
   Gauntlet Loop methodology (§2), and discipline standards apply to this effort even though
   this is a feature/restoration run, not a finding-fix run. Adapt, don't abandon.
2. `C:\Users\Ns8pc\Music\WARDRESS\Prompts\Implementations\IMPLEMENTATION_LOG.md` — the log
   you will append your entry to at the end.
3. Every file listed in "Files you must read before editing" below, plus anything else you
   touch.

There is no `WARDRESS_AUDIT_FINDINGS.md` for this run — the requirements are stated fully in
this prompt. This prompt is your findings file. If something here turns out to be wrong or
incomplete when re-verified against the actual code, do the right thing instead and record
the deviation in your log entry.

## Background — why this work exists

The completed fix effort (see `Prompts/WARDRESS_FIX_LOG.md`, Phase 27, commit `cd59310`)
removed all third-party imagery from the frontend because:
1. The sites pages sent every monitored hostname to `https://www.google.com/s2/favicons` on
   each render — watchlist exfiltration to a third party.
2. Provider logos fanned requests out to five CDNs per provider, including an unpinned
   `cdn.jsdelivr.net/.../thesvg@main/...` ref (silent content-drift / supply-chain channel).
3. Remote imagery breaks air-gapped installs.
4. A shipped test asserted the leaking URLs as correct behavior.

That removal was correct and this effort must NOT undo its privacy property: **zero runtime
third-party requests from the browser**. Everything we restore is bundled same-origin assets
or fetched by OUR OWN backend through our own SSRF-guarded, opt-in pipeline.

## Hard constraints (NON-NEGOTIABLE)

- `frontend/tests/no-third-party-image-hosts.test.ts` must pass UNMODIFIED. It bans these
  literals anywhere under `frontend/src/**`: `google.com/s2/favicons`, `svgl.app`,
  `cdn.jsdelivr.net`, `cdn.simpleicons.org`, `api.iconify.design`, `models.dev/logos`. Never
  reference any remote image URL from source code — not even in comments inside `src/`.
- Do not weaken `ai-provider-logo.test.tsx`, `site-avatar.test.tsx`, or any Phase 27/28 test;
  extend additively only.
- Baseline gates that must hold at the end: frontend vitest fully green; `pnpm type-check`
  exit 0; `pnpm exec oxlint src` exactly **0 errors / 12 warnings** (recorded baseline); 
  `pnpm build` succeeds; backend `pytest -q` green (fresh-install baseline — record the exact
  number on first run and never regress below it); `uv run --frozen ruff check .` and
  `ruff format --check .` clean; `alembic check` with no new drift.
- Tooling: pnpm exclusively (npm/yarn/bun OS-blocked). Python via uv / project venv only
  (pip blocked).
- No drive-by refactors. Touch only what these four workstreams need. Match existing style.
- Commit in the repo's conventional style, one commit per workstream plus one for docs:
  `feat(frontend): ...`, `feat(audit): ...`, `feat(settings): ...`, `docs: ...`.
  Do NOT push — leave commits for user review.

## Workstream A — AI sparkle icon (`assets/fabric-iq.svg`) in all 3 places

The user has supplied their brand sparkle SVG at `C:\Users\Ns8pc\Music\WARDRESS\assets\fabric-iq.svg`
(orange sparkle-plus, ~2KB, gradient fills).

1. Copy it into `frontend/src/assets/` as `fabric-iq.svg` (keep the original where it is too).
   Inspect it for `<img>`-context safety: explicit width/height or viewBox present (yes),
   no scripts, no external references. Gradient IDs inside an `<img>`-loaded SVG are fine.
2. Create a small typed wrapper component (e.g. `frontend/src/components/spark-icon.tsx`)
   that imports the asset (`import fabricIcon from "@/assets/fabric-iq.svg"`) and renders a
   plain `<img src={fabricIcon} alt="" aria-hidden="true">`, accepting a `className` prop so
   callers control size/color-context exactly as the lucide icons did. Check how existing
   code imports `.svg` assets (see `ai-settings-card.tsx` provider-logo imports) and follow
   that pattern exactly; if a TS declaration for `*.svg` imports is needed, match what
   exists already.
3. Replace the lucide `Sparkles` usages in these EXACT three spots:
   - `frontend/src/pages/scan-detail.tsx` line ~131 (inline explanation header icon,
     `size-5 text-accent-orange animate-pulse`) — keep the pulse animation on the new img.
   - `frontend/src/pages/scan-detail.tsx` line ~154 (empty-state hero icon, `size-14 ... mb-4`)
     — keep sizing/margins identical.
   - `frontend/src/pages/scan-detail.tsx` line ~166 ("Explain this incident" button icon,
     `mr-2 size-4 shrink-0`) — keep alignment inside the button pixel-stable.
   - `frontend/src/components/ai-settings-card.tsx` line ~807 (the settings-header sparkle)
     is ALSO a lucide Sparkles today — the user wants their brand mark wherever the AI
     sparkle appears; replace it too, sized to match what's there.
4. Remove the now-unused `Sparkles` imports so oxlint stays clean. Verify no other Sparkles
   usage remains that should have been replaced (grep the whole `src/`; replace every AI-
   sparkle occurrence, but leave genuinely different icons like `Server`, `Cloud` alone).

## Workstream B — ALL ~172 provider brand logos, bundled locally

Goal: every catalog provider shows its real brand mark from a same-origin bundled SVG. The
letter avatar survives ONLY as a fallback for anything genuinely unsourced.

1. The authoritative id list is `backend/app/data/models_dev_catalog.json`
   (`providers[].id`, 172 entries) — this is exactly what the Add-provider dialog renders.
   Extract the full list programmatically; do not hand-transcribe.
2. Also cover the legacy ids that existed before Phase 27's removal even if not in today's
   catalog (cross-check against git history if trivially possible; at minimum ensure:
   ollama✓(bundled), openai✓, openai_compatible✓, anthropic✓, google✓, groq✓, mistral✓,
   deepseek✓, xai✓ — these 8 files already exist in `frontend/src/assets/providers/`).
3. Source every remaining provider's SVG at BUILD TIME (now, during this session) from
   public brand-SVG libraries — Simple Icons (simpleicons), SVGL, thesvg — the same public
   sources Phase 27's own 8 marks came from. Practical method: fetch simpleicons' slugs/
   registry over the network NOW (your tooling may), download each SVG, normalize, vendor
   into `frontend/src/assets/providers/<id>.svg`. For providers without a simpleicons slug,
   try SVGL then thesvg then models.dev's static logo files fetched NOW and vendored. If a
   provider genuinely has no obtainable mark after honest attempts across all three
   sources, leave it unmapped (letter-avatar fallback) and list it explicitly in your log
   entry — do not fabricate icons.
4. Normalize every vendored SVG for `<img>` context:
   - Replace `currentColor` with an explicit hex fill (xAI precedent).
   - Fix white-on-transparent fills that vanish on light/dark surfaces (anthropic
     `fill="#ffff"` precedent — ink or a neutral dark).
   - Strip script tags, event handlers, external hrefs if any slip in.
   - Reasonable file size (simple-icons monochrome variants acceptable where full-color
     marks aren't reliably available — consistency beats colorfulness; prefer full-color
     where the source library provides it, matching pre-removal appearance).
5. Wire them up: move/extend the `PROVIDER_LOGOS` map out of `ai-settings-card.tsx` into
   `frontend/src/lib/provider-logos.ts` (repo lib-helper convention — see how Phase 27
   split `site-avatar.ts` out to dodge a fast-refresh lint warning; oxlint MUST stay at
   exactly 12 warnings, so verify this move doesn't add one). Import all assets there,
   export `PROVIDER_LOGOS: Record<string, string>` keyed by catalog id EXACTLY as spelled
   in the catalog (e.g. `fireworks-ai`, `zhipuai`, `tencent-tokenhub`), keep
   `openai_compatible → openai` mapping, and keep `ProviderLogo`'s lookup + letter-avatar
   fallback logic unchanged apart from reading the map from the lib module. Handle the
   dialog's `ollama-cloud`/`ollama_cloud → ollama` normalization as it exists today.
6. Extend `frontend/tests/ai-provider-logo.test.tsx` ADDITIVELY: derive the expected set of
   mapped ids FROM the map/lib module itself and assert (a) every mapped id resolves to a
   `/src/assets/providers/` URL (same-origin assertion), (b) the bundled asset files actually
   exist on disk (a node:fs existence check like `no-third-party-image-hosts.test.ts` uses —
   this catches map↔file drift forever), (c) unknown ids still render the letter avatar with
   no `<img>`. All existing assertions stay green.

## Workstream C — Site favicons: opt-in server-side resolver (both places)

This is the path Phase 27's residual-risk note itself sanctions ("an opt-in server-side
resolver designed as its own feature"). Default OFF; OFF is byte-identical to today
(letter avatars, zero network). Apply the FULL Gauntlet Loop to this workstream — it is the
one piece with real backend surface, concurrency, and security considerations.

### Backend

1. New app setting `favicon_resolution_enabled` (boolean, default False):
   - Follow the existing settings-store patterns (`app/settings_store.py`,
     `routers/settings.py`) end to end: storage, GET/PATCH exposure, validation,
     audit-logging the toggle change (`action="settings.favicon.update"`,
     `target_type="settings"`) consistent with sibling settings actions.
   - Expose it to the frontend in whatever settings summary endpoint/pattern the other
     boolean toggles use (find how e.g. scheduled-scan or telegram booleans reach the UI
     and mirror that exactly).
2. New table `site_icons` via alembic migration (follow repo migration conventions exactly —
   naming style of `alembic/versions/`, declared in `app/models.py` ORM metadata so CI's
   `alembic check` stays green, JSONB-with-variant convention if needed):
   - `site_id` FK→sites (CASCADE), unique — one icon row per site.
   - `content_type` (str), `data` (LargeBinary), `source_url` (provenance), 
     `status` (enum-like str: "ok"/"failed"), `detail` (failure reason, type-name level —
     NEVER echo the URL's credentials; Phase 26 precedent), `fetched_at` (UTC), 
     `retry_after` (UTC, negative-cache deadline for failed rows).
   - Migration must be reversible (`downgrade` implemented and tested).
3. Endpoint in the sites router area: `GET /api/sites/{site_id}/icon`, guarded by the
   standard auth dependency used by sites reads (check whether sites reads are
   CurrentUser/Analyst and mirror that RBAC exactly — do not widen access).
   Behavior:
   - Setting OFF (default) → return 404 immediately, zero outbound work. Document WHY in the
     docstring (Phase 27 privacy rationale: target confidentiality is the default).
   - Setting ON:
     a. Valid cache row `status="ok"` → serve bytes with stored content type and
        `Cache-Control: private, max-age=86400`. No refetch.
     b. Failed row with `retry_after > now` → 404 (negative cache; prevents refetch storms
        against dead sites on every dashboard load).
     c. No row, expired failure, or stale-ok beyond a refresh window (e.g. 30 days) →
        attempt ONE fetch now.
   - Fetch rules (the security core — get every one right):
     * Derive hostname from the stored site URL (never from request input beyond site_id).
     * Route through the repo's established SSRF gate — find `assert_url_allowed` /
       scanning.py's policy including the NAT64/DNS64 handling from Phase 16 — applied to
       EVERY outbound URL before and after any redirect resolution (fetch favicon.ico AND,
       if used, the homepage link-discovery absolute URL; both gated).
     * httpx async client, timeout ~5s total, `follow_redirects=True` BUT re-validate the
       final resolved host through the same gate before using bytes (redirect-to-internal
       is the classic bypass — close it; if the client can't be made to re-validate
       mid-chain, disable redirects and follow manually with a small cap, gating each hop).
     * Max size ~64KB enforced while streaming (abort past cap); content-type must be
       `image/*` OR magic-byte sniff PNG/JPEG/WebP/GIF/ICO/SVG — reject HTML error pages
       masquerading as images. Decide deliberately whether to allow SVG: serving as
       `image/svg+xml` via `<img>` is XSS-safe (Phase 27's own property), but rejecting SVG
       keeps only raster formats — pick one, justify in the log, and enforce consistently
       in both sniffing and served Content-Type.
     * Fetch order: `https://<host>/favicon.ico` first; if that fails/404s/non-image, ONE
       homepage GET to discover `<link rel="icon|shortcut icon|apple-touch-icon">` and
       resolve it against the base URL (absolute-URL resolution, scheme-relative handled),
       then gate+fetch that resolved URL. Total outbound requests ≤2 per attempt. Honor
       robots? No — favicon fetching is standard browser behavior; note the decision.
     * On success: store row (upsert), serve bytes. On failure: store/update failed row
       with `retry_after = now + 24h` and a safe detail string, return 404.
   - Concurrency (think hard here — real race surface):
     * Two operators loading the dashboard simultaneously for the same never-fetched site
       must NOT double-fetch (thundering herd). Use the repo's established atomic-claim
       primitive pattern (Phases 4+5: conditional UPDATE with rowcount arbitration, or a
       Postgres advisory lock keyed on site_id — study which fits the codebase idioms and
       justify). Losers of the claim either wait briefly for the winner's row or 404
       gracefully into letter-avatar fallback — a 404 here is cosmetic, never an error
       surfaced to users.
     * Upsert path must be race-safe (unique constraint on site_id + ON CONFLICT update).
   - Rate limiting: reuse the limiter idioms from Phases 16/17 (`request: Request` +
     explicit limiter call) — modest per-user bucket (e.g. 60/min) since images load in
     bursts on dashboard render.
   - Stale-ok refresh and negative-cache expiry paths must be tested with injected clocks
     (monkeypatch time/freezegun-style), never sleeps.
4. Backend tests (pytest, real Postgres harness — study `tests/db_harness.py`,
   `tests/test_sites_router_integrity.py`, `conftest.py` conventions; NO live network in
   CI — monkeypatch the fetcher everywhere; hermeticity is mandatory, see Phase 30's
   non-hermetic-test finding):
   - Setting off → 404 instantly, fetcher provably never called.
   - Toggle round-trip via the settings API incl. audit row written.
   - Happy path: fake fetcher returns PNG bytes → 200, correct content-type, cache-control
     header, DB row ok with provenance source_url; second call serves from cache (fetcher
     called exactly once).
   - Negative cache: fetcher raises/404 → 404 to client, failed row with retry_after;
     immediate second call does NOT invoke the fetcher again; after retry_after passes
     (clock injection) it does.
   - Oversize stream aborted; wrong content-type (HTML page) rejected; magic-byte mismatch
     rejected; SVG accepted-or-rejected per your documented decision.
   - SSRF: hostname resolving to private/loopback/NAT64-wrapped address → refused, failed
     row, safe detail; redirect chain landing on internal host → refused (test the hop
     validation directly if the client is stubbed).
   - Concurrency: N concurrent first-loads for one site → exactly one fetch invocation
     (real asyncio gather against the harness DB, barrier/shim pattern like
     `test_remediation_claim_race.py`), all clients get coherent responses (200 or graceful
     404-fallback, no 500s).
   - RBAC: unauthenticated 401; role matrix matches the sites-read surface.
   - Site deleted → cascade removes the icon row (FK semantics pinned).
   - Failing-before proof per protocol: for the endpoint-behavior tests, absence-of-feature
     collection failure is acceptable for brand-new modules (Phase 8 precedent), but the
     concurrency single-fetch test and the setting-off test must demonstrably encode
     behavior (state clearly what fails if the claim primitive is removed — e.g. stash the
     claim and watch double-fetch).

### Frontend

5. New component `frontend/src/components/site-favicon.tsx` + hook logic in
   `frontend/src/lib/use-site-icon.ts` (lib-helper convention again — keep pure logic out
   of component files):
   - Props: `siteId: string`, `url: string` (for fallback avatar), optional className.
   - On mount: `fetch(\`/api/sites/${siteId}/icon\`)` WITH the Authorization header — copy
     the token-handling pattern of `useArtifact` in `lib/api.ts` (token lives in module
     memory; a bare `<img src>` CANNOT authenticate — fetch+blob is mandatory, not a style
     choice). Consider exporting a small `fetchSiteIcon(siteId)` helper from `lib/api.ts`
     instead of raw fetch in the hook, keeping API access centralized — match how api.ts
     structures things.
   - 200 image response → `URL.createObjectURL(blob)` → render `<img>`; revoke the object
     URL on unmount AND on replacement (leak-free; test cleanup).
   - 404/network failure/while-loading → render the existing `SiteAvatar` (import it — it
     remains the permanent fallback AND the default-off UI; `lib/site-avatar.ts` untouched).
   - Reserve IDENTICAL box dimensions in both states (no layout shift when the favicon
     pops in) — match SiteAvatar's sizing contract, allow className override.
   - Handle rapid unmount/remount and React strict-mode double-effect safely (guard object
     URL lifecycle; stale-response guard so a slow fetch after unmount doesn't set state).
6. Use it in BOTH places:
   - `frontend/src/pages/sites.tsx` table rows (SiteOut payload includes `id: uuid.UUID` —
     verified available; confirm in `lib/api.ts` types).
   - `frontend/src/pages/site-detail.tsx` page header (same substitution where SiteAvatar
     sits today).
   - CRITICAL: do NOT disturb Phase 28's stretched-link overlay/z-order markup in sites
     rows (delete-button-above-overlay, `relative z-10` cell) — the favicon cell must stay
     visually and interactively identical apart from the image swap.
7. Settings UI toggle: place it in the appropriate settings card following existing card
   patterns (near the AI/privacy surfaces; look at how other boolean saves + success toasts
   work, e.g. SmtpCard/TelegramCard save flows). Label it plainly with a one-line honesty
   note: Off (default) = favicons stay local letter tiles, nothing leaves your deployment;
   On = your server fetches each monitored site's favicon once and caches it locally.
8. Frontend tests (`frontend/tests/site-favicon.test.tsx` or similar):
   - 404 → SiteAvatar fallback rendered, no img.
   - 200 blob → img rendered with object URL; Authorization header was present on the
     fetch call (assert the mock's call args).
   - Loading state shows fallback (no flash of broken image).
   - Unmount revokes the object URL (assert URL.revokeObjectURL called).
   - Strict-mode double-mount doesn't double-fetch or leak (mock fetch call count).
   - Settings toggle renders and PATCHes correctly (mirror existing toggle test patterns if
     any exist — check how other settings cards are tested).
   - Existing suites stay green untouched.

## Workstream D — Audit filter completeness (target-type dropdown)

Verified current state (re-verify yourself anyway):

- The dropdown `TARGET_TYPES` in `frontend/src/pages/audit.tsx:22` offers: "" (All), `site`,
  `suppression_rule`, `settings`, `notification_channel`, `alert`, `user`, `api_key`,
  `remediation_hook`, `remediation_execution`.
- The backend writes `target_type` values (grep `record_audit(` across `backend/app/**`):
  `site`, `suppression_rule`, `settings`, `notification_channel`, `alert`, `user`,
  `api_key`, `remediation_hook`, `remediation_execution`, **`ai_provider`** (5 writes),
  **`ai_task`** (1 write), **`scan`** (1 write).

So THREE filterable values are missing from the dropdown: `ai_provider`, `ai_task`, `scan`.

1. First, re-derive the complete value set yourself (don't trust this list): grep every
   `record_audit(` call site under `backend/` (including `agent/tools.py` and worker code)
   and extract both `target_type=` and `action=` literals; also check whether any audit
   rows are written with dynamic target_type values (variable rather than literal) — if any
   call site passes a variable, trace its possible values and include them.
2. Add every missing value to `TARGET_TYPES` in `audit.tsx`. The dropdown label rendering
   (`targetType.replaceAll("_", " ")`) handles display automatically.
3. Check `getTargetIcon(entry.target_type, action, label)` (audit.tsx ~line 213) handles
   each newly-filterable type sensibly — extend its mapping if a type falls into a generic
   bucket where a specific icon would be better (match the existing icon vocabulary;
   lucide icons only).
4. While you're in this file ONLY because the task requires it, also verify the Action
   text-input filter (backend prefix-matches `AuditLog.action.startswith`) has no
   discoverability problem worth a minimal fix — the user finds free-text filtering
   acceptable, so NO change is required unless you find the input actively broken. Do not
   turn it into a dropdown unless something is defective; note your reasoning in the log.
5. Backend: no changes expected (filtering is equality on target_type, works for any value).
   Add ONE pytest asserting each of `ai_provider`, `ai_task`, `scan` rows are retrievable
   via `GET /api/audit?target_type=...` (seed rows through `record_audit` against the
   harness DB) — pinning the contract the frontend dropdown now relies on.
6. Frontend tests: extend the existing audit tests (find them; `a11y-navigation.test.tsx`
   covers the expander/filter area) to assert the dropdown lists every expected option and
   selecting `ai_provider` filters the query correctly (query-string or mock assertion).

## Docs & honesty (small, surgical)

- Update the privacy disclosure sentences introduced by Phase 14/43 (`README.md` overview
  privacy wording, `docs/introduction.mdx` self-hosted card) to state the NEW truth:
  favicons are local letter tiles by default; an opt-in server-side resolver exists and is
  OFF by default; provider logos and the AI mark are bundled same-origin. Follow Phase 43's
  verifiable-copy discipline: no absolutes, no constants pinned in prose, every clause true
  on its own.
- Surgical edits only. No doc regeneration.

## Verification gate (ALL must pass before you claim done)

Record exact commands and counts in your log entry:

- `cd frontend && pnpm test` — all green incl. UNMODIFIED `no-third-party-image-hosts.test.ts`
- `pnpm type-check` — exit 0
- `pnpm exec oxlint src` — exactly 0 errors / 12 warnings
- `pnpm build` — success (pre-existing chunk-size advisory fine)
- `cd ../backend && .venv\Scripts\python.exe -m pytest -q --tb=short` — green; record the
  baseline count FIRST (fresh install), then show yours adds on top. If the known
  environment-sensitive DNS64 migration test flips, prove it pre-exists by stashing your
  changes and rerunning, then record that.
- `uv run --frozen ruff check .` + `uv run --frozen ruff format --check .` — clean
- Fresh disposable DB: `alembic upgrade head` clean, `downgrade -1` → `upgrade head`
  round-trip, `alembic check` — no new drift
- Manual smoke (the stack should be freshly installed per the user; if containers aren't
  up, ask the user to start them rather than running install yourself):
  (a) favicon setting OFF → sites pages pixel-equivalent to letter avatars, devtools
      Network tab shows ZERO requests to any image host anywhere in the app;
  (b) setting ON → real favicons appear in both places after first load, persist across
      reload (cache), unreachable sites fall back to letter tiles with no console errors;
  (c) all three fabric-iq sparkle placements render at correct sizes;
  (d) Add-provider dialog: scroll the full ~172-provider list — every entry shows a real
      brand mark (list any exceptions);
  (e) audit dropdown: select each new filter value and confirm filtered results render.

## Rules of engagement

- Read every file before editing it. Trace symbols to definitions. No invented APIs.
- Full edge-case enumeration BEFORE implementing Workstream C's fetcher (protocol §2 Step 3
  categories: concurrency, malformed/oversized input, unicode/IDN hostnames, partial
  failure mid-fetch, retry/idempotency, auth/RBAC, interaction with prior fixes — esp.
  Phases 16/26/27/28 — backward compat, performance, fix-failure mode). Write N/A with a
  reason where a category doesn't apply.
- Scratch probes outside the repo tree, deleted afterwards; nothing stray committed.
- When fully done: append your entry to
  `C:\Users\Ns8pc\Music\WARDRESS\Prompts\Implementations\IMPLEMENTATION_LOG.md` using that
  file's entry format (fill EVERY field honestly — including residual risk and leads), make
  the commits, do not push, then report a concise summary of what shipped, every gate's
  actual result, and any deliberate deviations from this prompt.
