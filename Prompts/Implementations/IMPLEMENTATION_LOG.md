# WARDRESS Implementation Log

> Companion log for the **feature/restoration implementation efforts** (as opposed to the
> completed defect-fix effort tracked in `../WARDRESS_FIX_LOG.md`). One entry per
> implementation prompt/run. Future implementation prompts live alongside this file;
> every run appends its entry here using the format below — this file is the only thing
> that persists what was done, why, and how it was proven across sessions.
>
> **If it isn't written here, it did not happen.**

## Entry Format (append below, newest last)

```
### [DONE / PARTIAL] <implementation title>

- **Prompt**: PROMPT-00N-<slug>.md (this folder)
- **Session date**: YYYY-MM-DD
- **Goal**: one paragraph — what this run set out to implement and why
- **Files changed**: path/to/file.tsx(:lines), ...
- **Key design decisions**: chosen approaches vs rejected alternatives, with reasons
- **Constraints honored**: privacy tripwires, lint baselines, test baselines, protocols
- **Edge cases handled**: the full list considered and how each is covered
- **Tests added**: file:test — what each proves (with failing-before proof notes)
- **Full regression results**: exact commands + pass/fail counts for every suite
- **Manual verification performed**: anything not automatable
- **Residual risk / follow-ups**: anything deferred, with justification
- **New leads observed**: issues spotted but out of scope, logged for future runs
- **Commit(s)**: <short hash> — <message>
```

---

### [DONE] PROMPT-001 — Restore Dashboard Imagery + Complete Audit Filter Coverage

- **Prompt**: PROMPT-001-dashboard-imagery-audit-filters.md (this folder)
- **Session date**: 2026-08-26
- **Goal**: Restore the dashboard imagery Phase 27 removed — the user's brand AI mark,
  full-color provider logos for the whole models.dev catalog, and an opt-in server-side
  site-favicon resolver — without reopening a single third-party runtime request, and
  complete the audit-log target-type filter coverage (three writable types were missing
  from the dropdown).
- **Files changed**:
  - WS-A (AI mark): `frontend/src/assets/fabric-iq.svg` (new, copied from `assets/`),
    `frontend/src/components/spark-icon.tsx` (new wrapper), `frontend/src/pages/scan-detail.tsx`
    (3 Sparkles sites), `frontend/src/components/ai-settings-card.tsx` (header sparkle);
    unused `Sparkles` imports removed.
  - WS-B (provider logos): `frontend/src/assets/providers/*` (153 new vendored SVG/PNG
    assets; 161 total with Phase 27's 8), `frontend/src/lib/provider-logos.ts` (new map),
    `frontend/src/components/ai-settings-card.tsx` (map moved to lib; ProviderLogo reads it),
    `frontend/tests/ai-provider-logo.test.tsx` (extended additively with full-map integrity pins).
  - WS-C backend: `backend/app/site_icons.py` (new resolver module), `backend/app/models.py`
    (`SiteIcon` ORM), `backend/alembic/versions/n8p9q1r2s3t4_site_icons_favicon_cache.py`
    (reversible migration), `backend/app/routers/sites.py` (`GET /api/sites/{id}/icon`),
    `backend/app/routers/settings.py` + `backend/app/settings_store.py` + `backend/app/schemas.py`
    (`favicon` setting, GET/PUT `/api/settings/favicon`, `settings.favicon.update` audit action),
    `backend/tests/test_site_icons.py` (15 hermetic tests).
  - WS-C frontend: `frontend/src/components/site-favicon.tsx`, `frontend/src/lib/use-site-icon.ts`,
    `frontend/src/lib/site-icon-state.ts`, `frontend/src/lib/api.ts` (fetchSiteIconObjectURL via
    artifactFetch), `frontend/src/pages/sites.tsx` + `site-detail.tsx` (both substitution sites;
    Phase 28 stretched-link markup untouched), `frontend/src/components/favicon-card.tsx`
    (Settings toggle), `frontend/src/pages/settings.tsx` (card mounted),
    `frontend/tests/site-favicon.test.tsx` (8 tests).
  - WS-D: `frontend/src/pages/audit.tsx` (TARGET_TYPES + `scan`, `ai_provider`, `ai_task`;
    dedicated lucide-vocabulary icons), `frontend/tests/audit-target-types.test.tsx` (3 tests),
    `backend/tests/test_audit_target_types.py` (3 parametrized tests).
  - Docs: `README.md` (overview privacy paragraph + Security Features entries),
    `docs/introduction.mdx` (Self-Hosted card), `docs/api-reference.mdx` (2 endpoint rows),
    `docs/audit-logs.mdx` (target_type enumeration), `backend/tests/test_phase43_docs_sync.py`
    (docs-contract pin updated to the new truthful copy).
- **Key design decisions**:
  - *Icon sourcing*: the user directed (twice, explicitly) that the icons be exactly those
    commit c3052cc used — Google s2 favicons → svgl.app → jsdelivr thesvg → simpleicons CDN →
    iconify logos — downloaded at BUILD TIME and vendored, never re-adding c3052cc's runtime
    `<img>` candidate chain (those six hosts are precisely what
    `no-third-party-image-hosts.test.ts` bans and Phase 27 existed to remove). models.dev's
    colorless marks were excluded at the user's instruction. 153 of 166 catalog ids obtained
    full-color marks; 13 genuinely-unfindable micro-brands keep the letter avatar.
  - *Globe-fallback hygiene*: Google favicon responses that were byte-identical across ≥3
    unrelated brands were identified as generic placeholder images (vision-checked one:
    MiniMax's "favicon" was an unrelated waveform app icon) and deleted rather than shipped —
    14 such files dropped; later passes recovered real marks for most of those ids from other
    sources/domains.
  - *SVG rejection in the resolver* (documented in app/site_icons.py): only magic-byte-sniffed
    rasters (PNG/JPEG/GIF/WebP/ICO) are stored/served; SVG is refused. Serving attacker-
    controlled markup as image/svg+xml via `<img>` is XSS-safe but adds nothing over rasters,
    and refusing keeps every stored byte provably a bitmap. The served Content-Type always
    comes from the sniff, never the remote header (servers lie).
  - *Concurrency primitive*: conditional UPDATE on `claimed_at IS NULL → now()` with rowcount
    arbitration (the repo's remediation-confirm/alert-ack primitive) plus unique-site_id-PK
    insert racing for first-ever rows; losers poll ≤8s then 404 gracefully into the letter
    avatar (cosmetic by design). A subtle Postgres snapshot bug was found during testing:
    polling SELECTs inside the loser's open transaction never observe the winner's commit —
    fixed by committing before each poll to end the stale snapshot (root cause, not symptom).
  - *RBAC*: icon reads use CurrentUser (mirrors sites reads exactly); toggle uses AdminUser
    (mirrors sibling settings); per-user rate limit enforced (images burst on render).
  - *Negative cache*: failed rows get retry_after = now+24h so dead sites aren't refetched on
    every dashboard load; ok rows refresh after 30 days. Both windows are clock-injected in
    tests (no sleeps).
- **Constraints honored**:
  - `frontend/tests/no-third-party-image-hosts.test.ts` passed UNMODIFIED at every gate run;
    no banned host literal appears anywhere under `src/` (the vendorer ran outside the repo
    tree in %TEMP% and was deleted afterwards; scratch scripts never entered a commit).
  - oxlint held at exactly **0 errors / 12 warnings** (baseline); type-check exit 0; build
    succeeds (pre-existing chunk-size advisory only).
  - Backend baseline recorded FIRST on a fresh disposable Postgres (dedicated container
    `wardress-test-pg` per db_harness contract): **1069 passed / 1 warning** — matching the
    Phase-44 closing report exactly; final suite adds 18 tests on top (1087) with zero
    regressions. The environment-sensitive DNS64 migration tests passed throughout (no stash
    proof needed).
  - `alembic upgrade head` / `downgrade -1` / `upgrade head` round-trip clean; `alembic check`
    reports no drift (SiteIcon declared in ORM metadata).
  - pnpm exclusively; uv/project venv only.
  - No drive-by refactors: ProviderLogo's fallback logic, SiteAvatar, lib/site-avatar.ts all
    untouched apart from the map source; sites-row z-order/stretched-link markup byte-preserved.
- **Edge cases handled (WS-C Gauntlet §2 Step 3)**:
  - Concurrency: N simultaneous first-loads → exactly one fetch (real asyncio.gather against
    harness Postgres; proven failing-before by construction — removing the claim makes call
    count > 1); coherent 200s or graceful 404s, never 500s; dead-site variant all-404 test.
  - Malformed/oversized: >64 KiB aborted/cut (enforced both in fetch and at cache boundary);
    HTML error pages masquerading as images rejected via magic-byte sniff; empty bodies
    rejected; SVG rejected per documented decision.
  - Unicode/IDN: hostname derives from the stored URL (validated HttpUrl at creation);
    unresolvable hosts raise SSRFBlockedError → safe failed row.
  - Partial failure mid-fetch: any httpx/OSError/ValueError becomes a failed row + negative
    cache; resolver exceptions caught at the endpoint → 404, never a 500 on a cosmetic image.
  - Retry/idempotency: negative-cache window prevents refetch storms; expiry re-allows
    (clock-injected test proves refetch happens exactly once more).
  - Auth/RBAC: unauthenticated 401; viewer can read (matches sites-read surface); admin-only
    toggle with before/after audit rows.
  - Prior fixes: SSRF gate applied to EVERY outbound URL incl. each manual redirect hop
    (redirect-to-internal test proves the landing host is gated and refused); failure details
    are type-name-level only — URLs/credentials never stored or echoed (Phase 26 discipline);
    OFF-by-default preserves Phase 27's property byte-for-byte (letter avatars, zero requests);
    Phase 28 stretched links untouched.
  - Backward compat: new table only; existing rows/data untouched; migration reversible.
  - Performance: ≤2 outbound requests per attempt; cached bytes served with private 1-day
    Cache-Control; rate-limited per user.
  - Fix-failure mode: winner crash between claim and store leaves claimed_at set — documented
    residual (see Residual risk); losers time out to a cosmetic 404.
- **Tests added**:
  - `backend/tests/test_site_icons.py` (15): off→404-fetcher-never-called; unknown-site 404
    when enabled; toggle round-trip incl. two audit rows with correct before/after; happy path
    (200, PNG content-type from sniff, Cache-Control header, ok row w/ provenance, second call
    serves from cache with fetcher called once); negative cache (failed row + retry_after,
    immediate retry does NOT refetch, clock-injection past retry_after DOES); HTML-as-image
    rejected; SVG sniff-rejected; oversize rejected; SSRF loopback gate raises; redirect chain
    hop-validation refuses internal landing (proves both hops gated); N=3 concurrent single-
    fetch coherence (failing-before vs claim removal); concurrent dead-site graceful 404s;
    unauthenticated 401; viewer allowed; site delete cascades icon row.
  - `backend/tests/test_audit_target_types.py` (3×parametrized): ai_provider/ai_task/scan rows
    retrievable via `?target_type=` with decoy-type isolation — pins the contract the dropdown
    now relies on.
  - `frontend/tests/site-favicon.test.tsx` (8): loading shows avatar fallback (no broken-image
    flash); 200 → blob img + Authorization header asserted on the mock call args; 404 →
    fallback no-img; network error → fallback; unmount revokes object URL; StrictMode-style
    double mount = exactly 2 owned fetches and zero unreleased URLs; identical reserved box in
    both states (no layout shift); FaviconCard renders off-by-default and PUTs {enabled:true}
    through a stateful mock (invalidation refetch reflects saved state).
  - `frontend/tests/audit-target-types.test.tsx` (3): dropdown lists ALL 12 backend-written
    target_types; selecting ai_provider issues `target_type=ai_provider`; scan and ai_task
    selections reach the API with raw values.
  - `frontend/tests/ai-provider-logo.test.tsx` (+5, additive): full-map non-empty; every mapped
    id resolves to bundled same-origin asset (path or data:-inlined form) never remote;
    on-disk file behind every mapped entry (map↔file drift tripwire); sample catalog ids
    render imgs not inlined-SVG; deliberately-unmapped ids keep letter-avatar fallback.
  - Failing-before proofs: absence-of-feature collection failures accepted for brand-new
    modules (Phase 8 precedent) for the endpoint-behavior tests; the concurrency single-fetch
    test demonstrably encodes behavior (stash the claim → multiple fetch invocations → assert
    fails); the setting-off test encodes behavior (enable the setting → fetcher provably runs).
- **Full regression results**:
  - Baseline BEFORE changes: backend `.venv/Scripts/python.exe -m pytest -q --tb=short` →
    **1069 passed / 1 warning** (fresh-install record; matches Phase-44 closing report);
    frontend `pnpm test` → **18 files / 113 tests passed**.
  - Final gates AFTER changes: frontend `pnpm test` → **20 files / 129 tests passed**
    (incl. UNMODIFIED no-third-party tripwire); `pnpm type-check` → exit 0;
    `pnpm exec oxlint src` → exit 0, **0 errors / 12 warnings** (= baseline);
    `pnpm build` → success (pre-existing chunk-size advisory only); backend final full suite →
    **1087 passed / 1 pre-existing warning** (baseline 1069 + 18 new; the concurrency race was
    additionally soak-run 14+ times green after fixing the snapshot-staleness root cause);
    `uv run --frozen ruff check .` → "All checks passed!"; `uv run --frozen ruff format
    --check .` → "162 files already formatted"; fresh-DB `alembic upgrade head` → clean,
    `downgrade -1` → `upgrade head` round-trip → clean, `alembic check` → no new drift.
  - Vendored-asset audits: no external refs outside w3.org namespaces in any SVG; no script
    tags/event handlers; currentColor occurrences rewritten to explicit hex (xAI precedent);
    duplicate-content globe placeholders detected by cross-file hashing and removed.
- **Manual verification performed**: browser smoke was SKIPPED at the user's explicit
  request ("jst skip the browser test i will do it"); a Vite dev server on :5199 was briefly
  booted to confirm the SPA serves (HTTP 200) and login page renders, then torn down.
  Operator-performed checklist remains: (a) OFF → pixel-identical letter tiles + zero image
  requests in devtools; (b) ON → favicons appear/persist/fall back silently; (c) sparkle sizes;
  (d) add-provider scroll shows ~real marks (13 letter-avatar exceptions listed above);
  (e) audit filters filter.
- **Deliberate deviations from the prompt** (recorded per its instruction):
  1. Icon sources follow commit c3052cc's exact chain (Google favicons/SVGL/thesvg/
     simpleicons/iconify) per the user's mid-run correction, replacing the prompt's
     simpleicons-slugs-first ordering; models.dev excluded entirely per the user.
  2. fabric-iq.svg is a green/teal layered-diamond mark, not the "orange sparkle-plus" the
     prompt described — shipped verbatim as supplied.
  3. `openai_compatible.png` was downloaded then deleted as redundant (the map aliases
     openai_compatible → openai.svg per the prompt's own mapping requirement).
  4. Docs-sync test `test_introduction_self_hosted_card_matches_local_imagery` updated to pin
     the NEW truthful copy (its old anchor string no longer exists by design); deviation noted
     because the prompt said docs tests should otherwise stay untouched.
- **Residual risk / follow-ups**:
  - If a resolver crash lands between claim and store, `claimed_at` stays set and subsequent
    requests 404 until process restart (no claim-expiry sweeper — bounded impact: cosmetic,
    per-site, requires a crash window of <5s; noted as a future hardening lead).
  - 13 catalog ids have no obtainable mark (lucidquery, blueclaw, llmtr, stepfun-ai-step-plan,
    stepfun-step-plan, dinference, inceptron, bailing, mixlayer, model-oracle-ai, drun,
    kuae-cloud-coding-plan, cloudferro-sherlock) — letter avatars, fully functional; revisit if
    brands publish assets.
  - Vendored PNGs came from Google's favicon pipeline at sz=128; quality varies by site. A
    future pass could re-source from official press kits.
  - The vendorer itself is throwaway (deleted scratch in %TEMP%), per protocol; re-running the
    sourcing for a refreshed catalog would need it re-created (documented here, not committed).
- **New leads observed**: none outside scope beyond the claim-expiry note above.
- **Commit(s)**: see the four commits following this entry (feat(frontend), feat(audit),
  feat(settings), docs) — hashes recorded in git log; not pushed, left for user review.

*(format reference retained above; newest entries append below)*
