# Wardress — Final Audit Report (2026-07-18)

> Produced by the final paranoid audit-and-report pass. Findings are appended per wave.
> No behavioral fixes were made in this pass except provably-safe housekeeping (dead-file
> removal, pure formatting), each logged under "File inventory changes."

## Executive summary

*(written last — see end of report)*

## Methodology

- Ground truth established in the main session first: `WARDRESS_MASTER_PROMPT.md`,
  `DESIGN-resend.md`, and `PROGRESS.md` read in full; git log/status/remote verified
  (clean tree, `origin/main` = github.com/Ns81000/WARDRESS, 11 linear commits);
  full-history secret scan clean (no credential-format strings, no .env/key file ever
  committed); `.gitignore` verified to cover .env, venvs, node_modules, data, reference/,
  docs-cache/. `.env` state: GEMINI_API_KEY and TELEGRAM_BOT_TOKEN configured (verified by
  length only, values never read out); **SMTP not configured** — email-path verification
  is limited to the graceful-failure case in this audit.
- 188 tracked files inventoried via `git ls-files`; tree matches Master Prompt §12
  skeleton plus documented growth (docs/screenshots, email/report templates, routers).
- Waves A–F executed via narrow-scope subagents returning structured findings; all live
  verification and QA reasoning in the main session used neutral engineering framing;
  no live malformed traffic was sent at the running stack (that remains the user's
  manual step, §5 handoff at the end of this report).

*(subagent counts and live-verification log appended as waves complete)*

**Wave B (backend) — subagents:** earlier findings above were produced by the prior session's narrow-scope subagents (auth/RBAC, SSRF, detection layers, Celery/scheduler, audit/health/rate-limit/migrations sweeps). This session's continuation: 4 subagents launched (notifications, Telegram bot, LLM layer, bulk import) — all complete, findings folded above.

**Wave D (design fidelity) — 4 subagents (2026-07-18, max 2 concurrent per standing rules):** D1 token foundation + shadcn primitives + shell/login/sites; D2 SOC dashboard surfaces (site-detail, scan-detail, finding cards, slider, DOM tree, gauge, timeline, suppression); D3 admin/ops screens (settings, alerts, audit, health, remediation + users/api-keys/hooks cards); D4 responsive-breakpoint pass across all pages + generated-artifact design (PDF/report templates, alert emails, Telegram message strings). Every finding's cited location re-verified in-source in the main session before folding. Two transient API-429 subagent failures occurred (D3/D4 first attempts, D4 second attempt); each was relaunched and completed with no partial state written to this report. Wave D contributed 1 High + 20 Medium + 26 Low + 6 verified-clean... (exact: D1 1H/8M/9L+1VC incl. the needs-user-decision font-lane item, D2 2M/7L+1VC, D3 1H/3M/6L+1VC, D4 5H/7M/4L+2VC) and 20 pattern-level notes in the UI/UX audit notes section. D4 additionally re-confirmed the previously-filed nav-collapse High as still present and rated its mobile impact critical-leaning.

**Live verification (main session, 2026-07-18):** Migration round-trip on scratch DB: empty → f3c8d6a91b27 (head) → base → head, clean. PDF + Markdown report generation against scan `8bfd4a15`: valid PDF 1.7 (47KB, embedded image, valid EOF), well-formed Markdown with executive summary, per-layer findings, timeline. Gemini Settings test endpoint: `ok: True | Key works — gemini-flash-latest answered` (1 API call). Telegram Settings test endpoint: `ok: True | Test message sent`. File inventory: 188 tracked files, cross-referenced against all text content; 18 candidates flagged (all legitimate: .gitignore/.dockerignore, brand PNGs, screenshots, tsconfig/components.json scaffolding) — zero orphans.

## Findings

### [HIGH] Refresh-token rotation race defeats reuse detection
- **Area:** backend
- **Location:** `backend/app/routers/auth.py:97-140`
- **What's wrong:** Rotation is read-then-write with no row lock or atomic conditional update. Two concurrent requests presenting the same refresh cookie both read the record while `revoked_at IS NULL`, both pass the reuse check, both mint successors and commit — two live refresh tokens from one presented token, no reuse alarm. The reuse branch only fires on a third, later presentation.
- **Evidence:** Traced `db.scalar(select(...))` at line 98 → checks at 108/122 → commit at 140; no `FOR UPDATE`, no rowcount-gated conditional UPDATE.
- **Suggested fix direction:** `with_for_update()` on the token row or an atomic `UPDATE ... WHERE revoked_at IS NULL` whose rowcount gates rotation; add a concurrent-refresh regression test.
- **Status:** open

### [HIGH] Stored suppression regex runs with no backtracking guard — one pathological rule can stall the worker
- **Area:** backend
- **Location:** `backend/worker/detection/suppress.py:97,139-147`
- **What's wrong:** `build_suppression` only validates that a regex *compiles*. A pattern like `(a+)+$` compiles fine, then `_apply_to_html` runs `compiled.sub("")` on every DOM text node with stdlib `re` (no timeout). One stored rule + one long text node stalls the scan — exactly the "unusable rule must not break a scan" failure the module promises to prevent. The css_selector path has a runtime `except Exception`; the regex path has none.
- **Evidence:** suppress.py:97 (compile-only validation), :139-147 (unguarded substitution loop), contrasted with :134 (selector guard).
- **Suggested fix direction:** Use the `regex` module with `timeout=`, or wrap per-rule application in try + bounded input, recording the rule as `unusable`. Add a pathological-pattern test.
- **Status:** open

### [MEDIUM] "Family" revocation is user-wide; a replayed logout token kills all sessions
- **Area:** backend
- **Location:** `backend/app/routers/auth.py:108-120`, `backend/app/models.py:173`
- **What's wrong:** The reuse branch revokes every unrevoked token for the user, not the family chain (`replaced_by` stored but never traversed). Safe as a superset, but a logout-revoked token replayed once (browser retry, stale tab) trips the escalation and signs out every device.
- **Suggested fix direction:** Distinguish logout-revoked from rotation-revoked before escalating, or document user-wide semantics as intended.
- **Status:** open

### [MEDIUM] No absolute session lifetime — refresh TTL is sliding
- **Area:** backend
- **Location:** `backend/app/routers/auth.py:134`
- **What's wrong:** Every rotation issues a successor with a fresh 7-day TTL; a session refreshing weekly lives forever. "7-day refresh tokens" is per-token, not per-session.
- **Suggested fix direction:** Cap successor expiry at original-login time + max session age.
- **Status:** open

### [MEDIUM] ADMIN_RESET_PASSWORD doesn't revoke refresh tokens and silently reactivates
- **Area:** backend
- **Location:** `backend/app/seed_admin.py:55-59`
- **What's wrong:** The reset path rewrites `password_hash` and forces `is_active=True` but never revokes refresh tokens — old cookies keep working after an emergency password reset. Implicit reactivation is undocumented.
- **Evidence:** Contrast `users.py:123-125` (admin PATCH path revokes families).
- **Suggested fix direction:** Revoke token families in the reset branch; make reactivation explicit.
- **Status:** open

### [MEDIUM] Remediation-hook list readable by viewer while parallel admin surfaces are admin-gated
- **Area:** backend
- **Location:** `backend/app/routers/remediation.py:88-98`
- **What's wrong:** `GET /api/sites/{id}/remediation-hooks` uses `CurrentUser`, exposing hook names, action types, thresholds, and redacted webhook-URL hints (scheme+hostname) to viewers — inconsistent with the Phase 6 decision that made settings and notification-channel GETs admin-only.
- **Evidence:** `settings.py:363` (`GET /api/notification-channels` = admin) vs the hook list (CurrentUser); equivalent redacted infrastructure hints on both.
- **Suggested fix direction:** Gate the hook list admin (or analyst minimum), or document the exception.
- **Status:** open

### [MEDIUM] Master-prompt "sites they can see" scoping is not implemented — flat visibility
- **Area:** backend / docs
- **Location:** `backend/app/routers/sites.py:138`, `alerts.py:43`, `remediation.py:242`, artifacts, reports
- **What's wrong:** Master Prompt §6 specifies roles "scoped to sites they can see"; no per-site visibility scoping exists — every authenticated user sees every site, scan, alert, artifact, and execution. Single-tenant use mitigates, but no doc records the narrowing.
- **Suggested fix direction:** Implement site-membership scoping or amend docs to state flat visibility as the design.
- **Status:** needs-user-decision

### [MEDIUM] Fusion feature-vector build runs outside the fallback try — a malformed layer result kills the pipeline
- **Area:** backend
- **Location:** `backend/worker/detection/fusion.py:121`, `pipeline.py:158`
- **What's wrong:** `layer9_fusion` promises "never raises," but `build_feature_vector` executes before the `try`; a malformed layer result (non-numeric score) raises out, and the pipeline calls fusion with no isolation — `run_detection` fails entirely (rule-6 violation).
- **Suggested fix direction:** Move the vector build inside the try or wrap the fusion call in the pipeline; add a malformed-result test.
- **Status:** open

### [MEDIUM] NaN layer score silently clamps to 1.0
- **Area:** backend
- **Location:** `backend/worker/detection/types.py:48`
- **What's wrong:** `max(0.0, min(1.0, float(score)))` maps NaN to 1.0 (NaN comparisons are False), turning a numeric bug into a max-severity alarm with no evidence trail, feeding fusion and JSONB as a clean float.
- **Suggested fix direction:** Explicitly detect NaN/inf before clamping, record it in evidence; test it.
- **Status:** open

### [MEDIUM] probe_tls can raise despite its "never raises" contract
- **Area:** backend
- **Location:** `backend/worker/probe.py:95-97,126,176`
- **What's wrong:** `writer.get_extra_info("ssl_object")` can return None (transport teardown race); the ensuing AttributeError is not in the catch tuple, and `probe_site` calls `probe_tls` outside its outer try — the probe can raise into the scan task.
- **Suggested fix direction:** Broad except in probe_tls or move the call under the outer try.
- **Status:** open

### [MEDIUM] Layer 3 can lose the whole layer on a malformed final_url
- **Area:** backend
- **Location:** `backend/worker/detection/dom.py:238`
- **What's wrong:** `urlparse(current.final_url or baseline.final_url).hostname` raises ValueError on inputs like `http://[::1` (unclosed bracket — final_url is redirect-target-influenced). `_norm_ref` guards its own urlparse; this call doesn't, so layer 3 raises and is lost to the skip-with-error path.
- **Suggested fix direction:** try/except ValueError → empty host.
- **Status:** open

### [LOW] delete_cookie omits the flags used at set time
- **Area:** backend
- **Location:** `backend/app/routers/auth.py:165`
- **What's wrong:** `delete_cookie` omits httponly/secure/samesite; strict user agents may ignore the deletion.
- **Suggested fix direction:** Mirror the set-time flags (auth.py:40-50) on deletion.
- **Status:** open

### [LOW] No clock-skew leeway on JWT decode
- **Area:** backend
- **Location:** `backend/app/security.py:58-63`
- **What's wrong:** leeway=0; tokens fail at exact expiry boundaries under clock drift. Low at single-host scale.
- **Suggested fix direction:** ~30 s leeway.
- **Status:** open

### [LOW] DB failure mid-auth yields a raw 500 (no 503 mapping)
- **Area:** backend
- **Location:** `backend/app/db.py:32-35`, `backend/app/deps.py`
- **What's wrong:** An OperationalError during auth dependency queries propagates to Starlette's default 500 handler (plain body, no stack trace leaked — verified) instead of a 503.
- **Suggested fix direction:** Exception handler mapping DB connectivity errors to 503.
- **Status:** open

### [LOW] `password_needs_rehash` is dead code — no rehash-on-login
- **Area:** backend
- **Location:** `backend/app/security.py:37`
- **What's wrong:** Defined, never called; Argon2 parameter upgrades never re-hash existing passwords.
- **Suggested fix direction:** Call it on login success, or remove it.
- **Status:** open

### [LOW] Any role (incl. viewer) can create API keys
- **Area:** backend
- **Location:** `backend/app/routers/apikeys.py:29-59`
- **What's wrong:** Key management is session-gated with no role check. Bounded (keys inherit the owner's role) but the policy is implicit.
- **Suggested fix direction:** Decide and document; optionally restrict to analyst+.
- **Status:** needs-user-decision

### [LOW] API key can call GET /api/auth/me
- **Area:** backend
- **Location:** `backend/app/routers/auth.py:168-170`
- **What's wrong:** `/me` uses CurrentUser, not session-only auth. Read-only informational asymmetry with the "keys cannot manage credentials" boundary.
- **Suggested fix direction:** Gate session-only iff strict symmetry wanted.
- **Status:** open

### [LOW] Unknown charset in a UA fetch aborts remaining probe variants
- **Area:** backend
- **Location:** `backend/worker/probe.py:155,203`
- **What's wrong:** `body.decode(resp.encoding or "utf-8", ...)` raises LookupError on an unknown charset; uncaught per-fetch, it aborts remaining UA variants + robots capture.
- **Suggested fix direction:** Catch (LookupError, UnicodeError) per fetch or use `resp.text`.
- **Status:** open

### [LOW] Header-value "weakening" detection is direction-blind
- **Area:** backend
- **Location:** `backend/worker/detection/metadata.py:96-97`
- **What's wrong:** Any header value change (including a tightened CSP) scores 0.1 as "weakened"; genuine downgrades score the same as cosmetic churn.
- **Suggested fix direction:** Per-header downgrade heuristics (max-age decrease, `*` sources, `unsafe-inline`).
- **Status:** open

### [LOW] Expired-cert flag lost on the cryptography-fallback parse path
- **Area:** backend
- **Location:** `backend/worker/probe.py:119-124`, `metadata.py:68`
- **What's wrong:** If DER parsing fails, the fallback keeps `notAfter` but never sets `expired`; layer 6 only reads the boolean, so an expired cert on this path scores 0.
- **Suggested fix direction:** Compute `expired` from getpeercert dates in the fallback.
- **Status:** open

### [LOW] robots.txt fetch failure indistinguishable from deletion
- **Area:** backend
- **Location:** `backend/worker/detection/metadata.py:107-120`
- **What's wrong:** A transient robots fetch flake produces the same 0.15 "changed/current_missing" signal as deliberate deletion.
- **Suggested fix direction:** Distinguish fetch-failed (skip diff) from 404 (deletion evidence) in the probe.
- **Status:** open

### [LOW] Empty-body 200 reference vs contentful bot variant → cloaking score 1.0
- **Area:** backend
- **Location:** `backend/worker/detection/cloaking.py:34-36,88`
- **What's wrong:** JS-hydrated shells serving empty raw HTML to browser UAs but content to Googlebot false-positive maximally (Jaccard 0 → divergence 1.0).
- **Suggested fix direction:** Treat an empty/near-empty reference body as non-comparable.
- **Status:** open

### [LOW] Layer 1 and suppressed_copy run outside crash isolation
- **Area:** backend
- **Location:** `backend/worker/detection/pipeline.py:109,120-122`
- **What's wrong:** An exception in `layer1_hash_diff` or `suppressed_copy` kills the whole pipeline; rule-6 isolation doesn't cover them.
- **Suggested fix direction:** Extend the isolation wrapper.
- **Status:** open

### [LOW] MiniLM "no download at scan time" docstring is conditional, not guaranteed
- **Area:** backend
- **Location:** `backend/worker/detection/semantics.py:12,78-80`
- **What's wrong:** If the image bake failed and network is available, SentenceTransformer downloads at scan time, contradicting the documented guarantee.
- **Suggested fix direction:** `local_files_only=True` if the hard guarantee is intended.
- **Status:** open

### [LOW] Module-level PIL MAX_IMAGE_PIXELS mutation is process-wide
- **Area:** backend
- **Location:** `backend/worker/detection/visual.py:38`
- **What's wrong:** Raising the decompression-bomb ceiling at import time weakens the guard for every PIL consumer in the worker process; PIL only raises at 2× the limit (~268 MP), so a ~200 MP hostile PNG decodes (~200 MB in L mode).
- **Suggested fix direction:** Per-load bounded size check after `Image.open`, or document the process-wide effect.
- **Status:** open

### [LOW] Suppression regex/selector recompiled per page
- **Area:** performance
- **Location:** `backend/worker/detection/suppress.py:129,140`
- **What's wrong:** Compiled per side per scan on the hot path; correctness fine, wasted work.
- **Suggested fix direction:** Store compiled objects on the Suppression bundle.
- **Status:** open

### [LOW] `depth_delta` computed and surfaced but unused in layer-2 score
- **Area:** backend
- **Location:** `backend/worker/detection/dom.py:142,153`
- **What's wrong:** Dead scoring signal implying it matters.
- **Suggested fix direction:** Wire it into the score or drop it.
- **Status:** open

### [LOW] Empty-baseline text makes layer 5 treat the whole page as "new" with no evidence marker
- **Area:** backend
- **Location:** `backend/worker/detection/signatures.py:148-162`
- **What's wrong:** Defensible semantics, but evidence doesn't distinguish "new text = whole page because baseline text was empty"; untested path.
- **Suggested fix direction:** Add `baseline_text_chars` to evidence + a test.
- **Status:** open

### [LOW] RBAC enforcement largely untested per-endpoint
- **Area:** test-coverage
- **Location:** `backend/tests/test_phase5_rbac.py`
- **What's wrong:** Untested: viewer 403s on ack/explain/scan-now/rebaseline/site PATCH/suppression/remediation decisions/settings PUTs/channel mutations; analyst 403 on hook PATCH/DELETE and user PATCH/DELETE; positive viewer reads of artifacts/reports/executions; viewer-owned API key blocked from mutations.
- **Suggested fix direction:** Parameterized role-matrix sweep across the endpoint table.
- **Status:** open

### [LOW] Auth test-coverage gaps
- **Area:** test-coverage
- **Location:** `backend/tests/test_auth.py`, `test_security.py`
- **What's wrong:** No test asserts refresh-cookie attributes; no concurrent-refresh test (would catch the HIGH race); no integration test of a validly-signed JWT with non-string/non-UUID `sub`; no test that seed_admin reset revokes sessions.
- **Suggested fix direction:** Add alongside the auth fixes.
- **Status:** open

### [LOW] Detection test-coverage gaps (layers 1-9)
- **Area:** test-coverage
- **Location:** `backend/tests/test_detection_layers.py`, `test_detection_fusion_pipeline.py`, `test_probe.py`, `test_suppression.py`
- **What's wrong:** Untested: NaN/inf through layer_result and fusion; malformed layer-result dict into build_feature_vector; probe_tls with ssl_object=None; unknown charset in UA fetch; expired cert via the fallback parse; empty-body reference vs contentful bot variant; header value *tightened*; pathological suppression regex runtime; evidence caps (L2/L3/L5) never exercised; RGBA/palette/1-pixel/different-width images in L4; empty-baseline L5 path. Stale comment at test_detection_layers.py:192 ("white padding" — code crops).
- **Suggested fix direction:** Add targeted tests with the corresponding fixes.
- **Status:** open

### [VERIFIED CLEAN] Auth core: Argon2id, JWT pinning, timing equalization, token storage
- **Area:** backend
- **Evidence:** Argon2id confirmed (argon2-cffi defaults, RFC-9106-adequate, `$argon2id$` asserted in tests); JWT decode pins HS256, requires sub/exp/iat, enforces type=access; dummy-verify timing equalization on unknown emails; refresh tokens stored SHA-256-only; deactivated-user checks on all four auth paths; role/password/deactivation changes revoke refresh families; malformed Authorization headers → 401, no 500 path found.
- **Status:** verified clean

### [VERIFIED CLEAN] RBAC wiring on every route
- **Area:** backend
- **Evidence:** Endpoint-by-endpoint sweep: no route missing an auth dependency except the six intentionally open (login/refresh/logout, health live/readiness); no viewer-reachable mutation; no analyst-reachable admin mutation; API keys resolve the owner's live DB role before every check; artifacts/reports CurrentUser per "viewer read-everywhere" design, DB-sourced root-confined paths.
- **Status:** verified clean

### [VERIFIED CLEAN] Detection layers 1-5 core semantics
- **Area:** backend
- **Evidence:** Hash normalization total (surrogates/5.5MB/CRLF tested); suppression never affects layer 1; lxml parse guarded, iterative traversal, no div-by-zero; evidence caps enforced (50/50/25/20); all 30 signature regexes audited linear-time-safe; script-flip edge cases covered; SSIM explicit data_range, min-height floor; bbox validation total; suppression applied symmetrically via shared per-side functions; no numpy types escape into evidence.
- **Status:** verified clean

### [VERIFIED CLEAN] Pipeline gating, isolation, fusion determinism, probe fail-safety
- **Area:** backend
- **Evidence:** Identical-hash gate skips exactly 2/3/4/5/8 with reason rows; 6/7 always run; isolation catches MemoryError, lets KeyboardInterrupt/SystemExit escape; degraded/Phase-1 baselines handled; layer 7 raw-vs-raw, bot-block scores zero; layer 8 CPU-pinned cached MiniLM, no in-layer network; fusion double-checked-lock prefork-safe, fixed feature order, fallback-max tested, calibration bands asserted; probe sub-probes individually fail-safe with per-hop SSRF guard.
- **Status:** verified clean

### [MEDIUM] Playwright subresource/JS-initiated requests are not SSRF-validated
- **Area:** backend
- **Location:** `backend/worker/fetcher.py:61,67-68`
- **What's wrong:** Only the top-level navigation URL and the final URL (and only when the hostname differs) are validated. No `page.route()` interception exists — page JS, `<img>`, `<iframe>`, `fetch()` can request internal addresses (e.g. 169.254.169.254) from the worker's network position, and responses can land in the DOM that gets stored as scan/baseline HTML. The `ssrf.py` docstring documents only the DNS-rebinding gap, not this one.
- **Suggested fix direction:** `page.route("**/*")` handler applying the address policy per request, and/or network egress isolation for the worker container; document whichever is chosen.
- **Status:** open

### [LOW] TLS probe connect is neither pinned nor re-validated
- **Area:** backend
- **Location:** `backend/worker/probe.py:90-93,170`
- **What's wrong:** `asyncio.open_connection(host, port)` does its own DNS resolution after the earlier URL validation — same check-time/connect-time window as Playwright, unpinned. Impact limited (only a ClientHello is sent; only peer-cert bytes read), but the module docstring ("All network work honors the site's SSRF policy") overstates.
- **Suggested fix direction:** Resolve+validate+connect to the pinned IP with `server_hostname=host`.
- **Status:** open

### [LOW] SSRFPinningTransport alone doesn't check userinfo/URL length on redirect hops
- **Area:** backend
- **Location:** `backend/app/ssrf_transport.py:49-93`
- **What's wrong:** The transport checks scheme/host/address only; both current users pair it with a response hook that closes credential-bearing and oversized redirect targets, but the transport is not safe standalone.
- **Suggested fix direction:** Add userinfo/length checks inside handle_async_request so the invariant is self-contained.
- **Status:** open

### [LOW] SSRF policy polish items
- **Area:** backend
- **Location:** `backend/app/ssrf.py:92-100,119-128`, `imports.py:115`, `probe.py:136,154`
- **What's wrong:** (a) `assert_url_allowed`'s inline `blocked` closure duplicates `_address_blocked` — drift risk; (b) sitemap/probe bodies fully buffered before size-cap slicing — resource-exhaustion edge; (c) no port restrictions anywhere — worth documenting as intentional; (d) `probe.py:136` calls blocking DNS on the event loop (worker-side, perf only); (e) operator-endpoint fetches (remediation webhooks, Apprise, LLM providers) are deliberately outside the SSRF policy — trust boundary not stated in code comments.
- **Suggested fix direction:** Deduplicate the closure; stream with byte caps; document the port + operator-endpoint trust decisions.
- **Status:** open

### [LOW] SSRF test-coverage gaps
- **Area:** test-coverage
- **Location:** `backend/tests/test_ssrf.py`, `test_phase5_ratelimit_ssrf.py`, `test_probe.py`
- **What's wrong:** Untested: IPv4-mapped IPv6 literals; decimal/hex/octal IP literals; trailing-dot and punycode hosts; end-to-end redirect-to-private through SSRFPinningTransport (only the event-hook guard is unit-tested); IPv6 pinned-URL formatting; credential-bearing redirect hop; fetcher final-URL re-validation path; a mock-transport assertion that the pinned IP is the actual connect target.
- **Suggested fix direction:** Add the enumerated matrix.
- **Status:** open

### [VERIFIED CLEAN] SSRF core policy and pinning transport
- **Area:** backend
- **Evidence:** Default-deny via `is_multicast or not is_global` covers RFC1918/loopback/link-local/ULA/CGNAT/reserved/0.0.0.0; IPv4-mapped IPv6 verified blocked on Python 3.12; scheme allowlist, credential refusal, and 2048-char cap enforced before address logic (opt-in never reaches them); `allow_private_networks` relaxes only address ranges, is create-time-only, and is read fresh per task; validation at create AND worker pre-fetch AND per bulk-import row; pinning transport resolves once, requires all addresses to pass, connects to the pinned IP with Host+SNI preserved, and re-validates every redirect hop; exotic IP literals fail closed through getaddrinfo.
- **Status:** verified clean

### [MEDIUM] Enqueue 503 strands a pending scan row that 409-blocks the site for up to 10 minutes
- **Area:** backend
- **Location:** `backend/app/routers/sites.py:302-313,348-351`
- **What's wrong:** The scan/baseline row is committed before `enqueue_scan`; on broker failure → 503, the pending row survives and every subsequent scan-now/rebaseline 409s until the 10-minute staleness recovery.
- **Suggested fix direction:** Catch the enqueue failure in the router, mark the just-created row failed ("could not enqueue"), then re-raise the 503.
- **Status:** open

### [MEDIUM] Check-then-insert race allows duplicate in-flight scans
- **Area:** backend
- **Location:** `backend/app/routers/sites.py:334-350`, `worker/beat_tasks.py:128-148`
- **What's wrong:** Both the API and the Beat dispatcher SELECT for in-flight scans then INSERT with no serialization; concurrent scan-now requests (or scan-now racing a beat tick) can both pass. Baselines have a partial-unique backstop; scans don't. Bounded consequence (each row is idempotent) but wastes workers and can double-alert.
- **Suggested fix direction:** Partial unique index on `scans(site_id) WHERE status IN ('pending','running')` + IntegrityError→409, or FOR UPDATE on the site row.
- **Status:** open

### [MEDIUM] Staleness measured from created_at, not started_at — a backlogged-then-running scan can be falsely failed
- **Area:** backend
- **Location:** `backend/app/scanning.py:14-20`, `worker/scan_tasks.py:301-305`
- **What's wrong:** A scan queued >4 min then legitimately running exceeds the 10-min cutoff mid-run; the API/Beat marks it failed and starts a replacement while the original still runs — the original's later commit overwrites failed→completed. Two concurrent scans of one site, status ping-pong.
- **Suggested fix direction:** Stale = created_at old AND (started_at null or old); and/or `expires=STALE_INFLIGHT` on the run_scan enqueue.
- **Status:** open

### [MEDIUM] Committed alert whose delivery enqueue was lost is never re-delivered
- **Area:** backend
- **Location:** `backend/worker/scan_tasks.py:332-339`
- **What's wrong:** If Redis is down at alert time the enqueue exception is correctly swallowed (scan survives), but no sweep ever re-enqueues delivery for alerts with zero delivery rows. Same shape for auto-remediation rows never fired.
- **Suggested fix direction:** Periodic Beat sweep for undelivered alerts / unfired queued executions older than N minutes.
- **Status:** open

### [LOW] Broker fail-fast covers refused connections, not hung ones
- **Area:** backend
- **Location:** `backend/app/tasks.py:29`, `worker/beat_tasks.py:64-65`
- **What's wrong:** Transport options bound retries but set no socket connect/read timeouts; a blackholed Redis hangs the API request at TCP level. The heartbeat sets connect timeout but no read timeout.
- **Suggested fix direction:** Add socket_connect_timeout + socket_timeout to both.
- **Status:** open

### [LOW] No path confinement on the artifact write path
- **Area:** backend
- **Location:** `backend/worker/artifacts.py:14-25`
- **What's wrong:** `store_artifacts` joins kind/record_id unchecked; reads are confined, writes are not. All current callers pass UUIDs — unexploitable today; asymmetric.
- **Suggested fix direction:** Same confinement (or `uuid.UUID(record_id)` assert) on write.
- **Status:** open

### [LOW] Celery/scheduler test-coverage gaps
- **Area:** test-coverage
- **Location:** `backend/tests/test_scan_tasks.py`, `test_scheduler.py`
- **What's wrong:** Untested: enqueue-503 stranding; concurrent duplicate-scan race; the catch-all's own DB write failing (stale-recovery handoff); SoftTimeLimitExceeded through the wrapper; dead-Redis-at-alert-time still committing the scan; janitor removal cap and mid-run DB outage; partial-delivery resume.
- **Suggested fix direction:** Add with the fixes.
- **Status:** open

### [VERIFIED CLEAN] Celery config, never-stuck guarantee, idempotency, Beat dispatcher, engine lifecycle, janitor
- **Area:** backend
- **Evidence:** acks_late + prefetch=1 + 300/360 limits < 10-min stale cutoff; beat tick expires=2 ticks; three-layer never-stuck traced end-to-end including SIGKILL and catch-all-write-fails degradation paths; findings delete+rewrite in one txn with unique (scan_id, layer); alert unique scan_id; next_scan_at advanced+committed before enqueue (lost enqueue delays one interval, never tight-loops); 50/tick cap; adaptive math boundaries sound (floor/cap/reset verified); fresh engine per task with dispose in finally, no cross-loop sharing; janitor only touches well-formed-UUID dirs, capped, never raises into scheduling.
- **Status:** verified clean

### [MEDIUM] Audit-log redaction stringifies nested structures wholesale — second line of defense is broken
- **Area:** backend
- **Location:** `backend/app/audit.py:28-30,58-62`
- **What's wrong:** Fragment matching runs only on top-level keys; any non-scalar value falls to `str(value)[:500]`. Leaking shapes: a nested dict under a benign key (`{"smtp": {"password": ...}}`); a list of dicts; a `url` value carrying basic-auth userinfo (url is deliberately unredacted). Fragment list misses `pass`, `credential`, `auth`, `private_key`, `bearer`. Every current call site passes curated flat dicts (all ~30 verified — no live leak today), but the defense fails the fresh-eyes test the audit demanded.
- **Suggested fix direction:** Recurse into dicts/lists; extend fragments; strip userinfo from URL-shaped values. Add adversarial-shape tests.
- **Status:** open

### [MEDIUM] Health Redis probes have connect timeout only — a wedged Redis hangs /details
- **Area:** backend
- **Location:** `backend/app/routers/health.py:79,95,111,126`
- **What's wrong:** `redis.from_url(..., socket_connect_timeout=2)` sets no socket_timeout; an accepting-but-unresponsive Redis blocks ping()/llen()/get() forever. The Celery control ping bounds the reply wait, not broker connection establishment. Threads keep the loop alive (no 500), but /details hangs and threads accumulate under polling.
- **Suggested fix direction:** socket_timeout=2 on all three from_url calls; connect timeout on the Celery client transport options.
- **Status:** open

### [LOW] Beat staleness never degrades health status — _BEAT_STALE is dead code
- **Area:** backend
- **Location:** `backend/app/routers/health.py:43,199-205`
- **What's wrong:** `last_dispatch_tick_at` is returned but never compared against the 5-min constant; a dead Beat reports status ok.
- **Suggested fix direction:** Degrade when the heartbeat is absent/stale.
- **Status:** open

### [LOW] DB race window can 500 /api/health/details
- **Area:** backend
- **Location:** `backend/app/routers/health.py:160-186`
- **What's wrong:** The stats queries after the `_db_ok` probe are unwrapped; the DB dying in between raises through to a 500.
- **Suggested fix direction:** Wrap the `if db_up:` block, downgrading `database` to down.
- **Status:** open

### [LOW] Remediation confirm audit row can outlive a reverted state
- **Area:** backend
- **Location:** `backend/app/routers/remediation.py:278-296`
- **What's wrong:** The audit row (status: queued) commits, then a failed enqueue reverts the execution to pending_confirm with no compensating row — the log misstates history.
- **Suggested fix direction:** Second audit row on revert, or audit after enqueue.
- **Status:** open

### [LOW] Unaudited mutations: scan-now, explain; no login audit trail
- **Area:** backend
- **Location:** `backend/app/routers/sites.py` (scan-now, explain), `routers/auth.py`
- **What's wrong:** scan-now and explain (writes to the scan row) carry no audit record; auth has no failed/successful-login trail. All other required surfaces verified covered.
- **Suggested fix direction:** Decide whether these belong in scope; add if so.
- **Status:** needs-user-decision

### [LOW] Rate-limiter/CORS polish
- **Area:** backend
- **Location:** `backend/app/main.py:39-62`, `routers/auth.py:65`, `ratelimit.py:1-18`
- **What's wrong:** (a) the rate-limit middleware runs outside CORSMiddleware — 429s lack CORS headers under a cross-origin config (irrelevant same-origin); (b) login brute-force bounded only by the generic 300/min/IP limit — no per-account counter; (c) fixed-window 2× boundary burst not documented.
- **Suggested fix direction:** Reorder middleware or add origin headers to 429s; tighter ip+email limiter on /api/auth/*; docstring line.
- **Status:** open

### [LOW] Missing minor indexes
- **Area:** performance
- **Location:** `backend/app/models.py:315,570`, health.py:186
- **What's wrong:** `remediation_executions.scan_id` FK has no standalone index (the composite unique doesn't serve scan-side lookups/cascades); `alerts.created_at` unindexed but is the feed's sort key; `scans.finished_at` unindexed (used in max() on health). Small tables today.
- **Suggested fix direction:** Add when data grows, or in the fix pass since migrations are cheap now.
- **Status:** open

### [LOW] OpenAPI "all described" is overstated; unhandled-exception body is text/plain
- **Area:** backend / docs
- **Location:** `backend/app/main.py`, routers
- **What's wrong:** Route count is exactly 62 and all 13 routers are tagged (claim verified), but several endpoints (list_users, get_smtp, channel list) lack docstrings/summaries. Unhandled exceptions return Starlette's plain-text "Internal Server Error" (no stack trace leaked — verified) rather than the JSON `{"detail":...}` shape clients expect.
- **Suggested fix direction:** Add summaries; optional JSON 500 handler.
- **Status:** open

### [LOW] Env vars not passed through compose (defaults-only)
- **Area:** infra
- **Location:** `docker-compose.yml`
- **What's wrong:** `ACCESS_TOKEN_TTL`, `REFRESH_TOKEN_TTL`, `ARTIFACTS_DIR` are read by config.py but absent from compose environment blocks — cannot be tuned from .env (defaults harmless; ARTIFACTS_DIR default matches the mount). The previously-fixed RATE_LIMIT_*/TRUST_PROXY_HEADERS/CORS_ALLOWED_ORIGINS/COOKIE_SECURE are verified still present, and GEMINI_MODEL is present in app+worker (but see the dead-knob finding).
- **Suggested fix direction:** Pass through or document as fixed defaults.
- **Status:** open

### [VERIFIED CLEAN] Audit coverage, health degradation shape, rate-limit/CORS core, models-vs-migrations
- **Area:** backend
- **Evidence:** Audit rows staged on the caller's session (atomic), record_audit never raises, all required mutation surfaces covered (sites/suppression/settings/channels/acks/users/apikeys/remediation/bulk/bot-mute); /live touches nothing, readiness returns 200-degraded on DB failure (compose healthcheck safe), every probe degrades to a labeled component; 429+Retry-After on both limiter paths, XFF only behind TRUST_PROXY_HEADERS, store memory bounded+swept, CORS default-off with exact origins and credentials never with `*`; all model columns present across the 5 migrations, enum values consistent, cascades consistent; SPA fallback preserves /api/* JSON 404s incl. the Windows separator branch (tested).
- **Status:** verified clean

### [LOW] SMTP "test gates save" is a frontend convention, not a backend invariant
- **Area:** backend
- **Location:** `backend/app/routers/settings.py:87-120`
- **What's wrong:** `PUT /api/settings/smtp` saves configuration with no linkage to a prior successful test; the test endpoint (`POST /smtp/test`, :123-151) is a separate route with no state connecting the two. The §8 "Send Test Email gates Save" requirement is enforced only by the frontend disabling the Save button. A direct API caller (or a future UI regression) can save untested credentials. Noting the Phase 4 decision documented the frontend gating as the design — this records that the backend does not independently enforce it.
- **Evidence:** settings.py:87 PUT handler proceeds directly to `save_setting(db, SMTP_KEY, value)` at :119 with no test-state check.
- **Suggested fix direction:** Either document test-before-save as a UI-only responsibility, or add a short-lived test-success token the PUT requires.
- **Status:** needs-user-decision

### [LOW] Alert email render uses bracket access on top_layers items
- **Area:** backend
- **Location:** `backend/app/alerting.py:81,86-95`, `backend/app/templates/email/alert.html:74-75`
- **What's wrong:** `build_alert_content` and the template access `layer["label"]`/`layer["score"]` without `.get()`; a malformed top_layers dict would raise KeyError and fail that delivery. The only current caller (`alert_tasks.py:54-57` `top_layers_from_scores`) always constructs well-formed dicts, so no live path triggers it — defense-in-depth gap only, and a failure would land as a failed delivery row, never affecting the scan.
- **Suggested fix direction:** `.get("label", "unknown")` / `.get("score", 0.0)` in the comprehension at alerting.py:93.
- **Status:** open

### [VERIFIED CLEAN] Alert delivery chain: fail-safety, per-channel commits, mute, idempotency, redaction
- **Area:** backend
- **Evidence:** Every delivery exception path degrades to `(False, detail)` (alerting.py:159-171 email, :194-211 apprise) or a logged "error" return (alert_tasks.py:179-188); scan-side alert creation wrapped (scan_tasks.py:340-341) — no notification failure can affect scan state. Per-channel commit inside the loop (alert_tasks.py:164-166) so one failing channel can't roll back or block another. Mute is delivery-time only: skipped rows recorded, Alert row and verdict unaffected. acks_late redelivery idempotent via the existing-delivery-row guard (alert_tasks.py:75-81) plus alert-row reuse (scan_tasks.py:332-338), test-pinned. Channel-creation Apprise validation uses the identical `apprise.Apprise().add(url)` call as delivery. No channel-config shape leaks a secret into a GET (`_target_hint` redacts; AlertDeliveryOut exposes no config). DecryptionError handled as "not configured" on all four read paths. No delivery/ack race: disjoint fields, idempotent first-ack-wins.
- **Status:** verified clean

### [MEDIUM] Bot answers unauthorized chats with an existence-confirming refusal
- **Area:** backend
- **Location:** `backend/worker/telegram_bot.py:127-130,153`
- **What's wrong:** Commands from a non-captured chat get a "this bot is linked to a different chat" reply, and a second `/start` gets "already linked to another chat" — confirming to any chat that reaches the token that an active, configured Wardress instance exists behind it. Single-owner enforcement itself is correct (no command executes); this is an information-disclosure refinement for a monitoring tool. The refusal-reply behavior is documented as intended in the module comment, so this may be a deliberate trade-off.
- **Evidence:** `_guarded` refusal at :127-130; `/start` second-chat reply at :153.
- **Suggested fix direction:** Silent drop for unauthorized chats (with a log line), or a one-time setup token in `/start <token>` shown in the Settings UI.
- **Status:** needs-user-decision

### [LOW] Bot /scan enqueues without re-running URL validation
- **Area:** backend
- **Location:** `backend/worker/telegram_bot.py:259-306`
- **What's wrong:** `cmd_scan` creates the Scan row and enqueues `wardress.run_scan` without calling `assert_url_allowed`. Not a live gap — the URL was validated at site creation and the worker re-validates before every fetch — but the bot's enqueue path lacks the redundant check the API's scan-now path has, so a hypothetical out-of-band Site mutation would only be caught at fetch time.
- **Suggested fix direction:** Defense-in-depth `assert_url_allowed(site.url, allow_private_networks=...)` before enqueue.
- **Status:** open

### [LOW] Bot /ack duplicates the API's acknowledgement logic
- **Area:** backend
- **Location:** `backend/worker/telegram_bot.py:309-345` vs `backend/app/routers/alerts.py:80-103`
- **What's wrong:** Both paths independently set `acknowledged_at`/`acknowledged_via` and call `record_audit` with near-identical parameters; no shared helper. Currently behaviorally identical, but any future ack side-effect must be added twice or the surfaces silently diverge.
- **Suggested fix direction:** Extract a shared `acknowledge_alert(db, alert, via, actor, actor_label)` helper both call.
- **Status:** open

### [LOW] Bot /mute audit rows omit the before state
- **Area:** backend
- **Location:** `backend/worker/telegram_bot.py:382-406`
- **What's wrong:** `cmd_mute` (and unmute) records audit `after` only; the API's site PATCH records both `before` and `after` snapshots. Bot-initiated mute audit rows can't show what value was replaced.
- **Suggested fix direction:** Capture `site.muted_until` before mutating and pass it as `before=`.
- **Status:** open

### [VERIFIED CLEAN] Telegram bot: command set, single-owner guard, crash isolation, token lifecycle
- **Area:** backend
- **Evidence:** All six required commands (/status /sites /scan /ack /mute /help) plus /explain present. Every command routes through the `_guarded` wrapper verifying caller chat = captured chat before any work; every handler try/except-wrapped so an exception logs + replies user-safe and never kills the poller. 60 s DB settings re-read restarts polling on token change; missing token idles politely; `InvalidToken` logs a plain-language warning with 60 s backoff, no crash-loop. All messages plain text, no parse_mode (site names with special characters can't break rendering). /mute caps at 7 days matching the API schema; /ack audit-attributed "telegram-bot".
- **Status:** verified clean

### [MEDIUM] GEMINI_MODEL env var is displayed in Settings but never used at call time
- **Area:** backend
- **Location:** `backend/app/llm.py:35,90`, `backend/app/config.py:59`, `backend/app/routers/settings.py:231,236,255`
- **What's wrong:** The `GEMINI_MODEL` environment variable is read into `settings.gemini_model` and returned by `GET /api/settings/gemini`, but the actual Gemini API call at llm.py:90 uses the hardcoded module constant `GEMINI_MODEL = "gemini-flash-latest"` (line 35), not the env-configured value. Changing the env var changes what the UI displays but has zero effect on which model string is sent to the Gemini API — silent config-vs-runtime divergence.
- **Evidence:** llm.py:35 constant definition, :90 uses constant, settings.py:231/236/255 return `get_settings().gemini_model`, config.py:59 reads `GEMINI_MODEL` from env, docker-compose.yml:46,92 pass it through.
- **Suggested fix direction:** Replace the constant at llm.py:35 with `GEMINI_MODEL = get_settings().gemini_model` (read at module load or lazily per call) so the env var controls the actual API model string, or remove the env var from compose/config/schemas if the hardcoded constant is the intended design and document it as non-tunable.
- **Status:** open

### [MEDIUM] LLM daily budget spent on failed retry attempts
- **Area:** backend
- **Location:** `backend/app/llm.py:83,86,102-104`
- **What's wrong:** The 200-call/day budget is decremented (line 86 `_budget_spend()`) inside the 3-attempt retry loop (line 83 `for attempt in range(3):`), before the API call executes. An HTTP 429 that exhausts all retries consumes 3 budget slots even though zero calls succeeded. This is conservative (rate-limit-induced retries burn budget to discourage tight loops) but undocumented and wasteful — the budget depletes faster than the actual successful-call count. Boundary behavior is correct: exhaustion raises `LLMUnavailable` which all callers degrade gracefully.
- **Evidence:** Line 83 loop, line 86 inside the loop, line 102 `if _is_rate_limit(exc) and attempt < 2: continue`.
- **Suggested fix direction:** Move `_budget_spend()` after the successful `return text` at line 97, or refund on retry, or document the current spend-on-attempt semantics as intentional.
- **Status:** open

### [MEDIUM] LLM exception messages could leak API key fragments into logs and client responses
- **Area:** backend
- **Location:** `backend/app/llm.py:107,136,148`, `backend/app/routers/settings.py:278-279`
- **What's wrong:** Exception messages from the Gemini/Ollama SDK are logged verbatim (`logger.exception("Gemini call failed: %s", exc)` at :107) and returned to API clients (the test endpoint returns `gemini_test_call()` which can return `f"Gemini test failed: {exc}"` at :148). If the SDK includes API key fragments in exception text (unlikely but not impossible — depends on google.genai internals), they'd leak into logs and HTTP 200 responses. Stored keys are correctly redacted via `_hint()` in GET responses, but runtime exceptions bypass this.
- **Evidence:** llm.py:107,136 log `str(exc)`, :148 returns f-string with `{exc}`, settings.py:278 returns this to the client.
- **Suggested fix direction:** Sanitize exception strings (strip `AIza[A-Za-z0-9_-]{35}` patterns or other key-shaped substrings) before logging/returning, or replace `str(exc)` with `type(exc).__name__` in user-facing messages and keep full text only in logs.
- **Status:** open

### [LOW] Ollama has no rate limiter (by design — local model)
- **Area:** backend
- **Location:** `backend/app/llm.py:41,133`
- **What's wrong:** The aiolimiter (8 req/60s) wraps only Gemini calls (`gemini_generate()` at :85); Ollama calls (`ollama_generate()` at :133) have no rate limiting. This is by design (Ollama is a local model with no quota) and noted here for completeness — not a finding to fix, but a difference from Gemini that should be documented if users expect symmetry.
- **Status:** open (informational)

### [VERIFIED CLEAN] LLM layer: model-string sweep, escalation band, fail-safety, provider resolution, Ollama env vars
- **Area:** backend
- **Evidence:** Model-string sweep: zero `gemini-2.5-flash` references in project code (only in .venv vendor files); `gemini-flash-latest` confirmed in .env.example, compose (both containers), config.py, llm.py constant, schemas, test. Escalation band [0.35, 0.75) on changed-but-not-flagged scans verified correct (llm_escalation.py:37, scan_tasks.py:269); already-flagged/unchanged scans never escalate; benign classifications no-op; malicious with confidence >= 0.6 upgrades. `escalate_scan()` never raises (lines 52-71 catch-all, always returns status dict); every failure mode (no key, quota, network, malformed response) degrades gracefully and is test-pinned. HTTP 429 backoff: 3 attempts with exponential waits (2s, 4s), last-attempt degradation clean. Explain caching correct (force-regenerate bypasses); no-provider degradation → 503 with clean message. Provider resolution: Gemini preferred over Ollama when both enabled, consistent between escalation and explain. `ENABLE_OLLAMA` and `OLLAMA_BASE_URL` env vars actually consulted at runtime (llm.py:189-190,194), no dead knobs (Ollama model is DB-only, correctly).
- **Status:** verified clean

### [CRITICAL] Bulk import per-row DB error rolls back entire import
- **Area:** backend
- **Location:** `backend/app/routers/imports.py:239-254`, `backend/app/models.py:182`
- **What's wrong:** The per-row create loop has no try/except around `db.add(site)` / `await db.flush()`. A CSV-supplied `name` is stored unbounded into `Site.name` (VARCHAR 200); the derived name is capped at 200 (`_derive_name`) but a user-provided name is not. A row like `https://ok.example.com,<201+ chars>` raises DataError at flush, propagates out as a 500, and rolls back the shared session — every previously-flushed site in the import is lost. This is exactly the all-or-nothing failure the contract (§11 bulk-import spec, docstring :6-7) forbids. Any per-row DB error (IntegrityError from a concurrent create, DataError) has the same effect. Tests run on SQLite, which does not enforce VARCHAR lengths, so the suite cannot catch this.
- **Evidence:** imports.py:240 `name=(name or _derive_name(url))` with no length cap on `name`; no try around :239-253; single session, single commit at :278; models.py:182 `String(200)`.
- **Suggested fix direction:** Cap/truncate CSV names to 200 chars and validate per row, and wrap each row's add/flush in try/except with SAVEPOINT (`db.begin_nested()`) so a failing row becomes `status="error"` and the rest survive.
- **Status:** open

### [HIGH] Sitemap fetch buffers entire response before size cap is applied
- **Area:** backend
- **Location:** `backend/app/routers/imports.py:111-115`
- **What's wrong:** `_fetch_sitemap_bytes` does `resp.content[:SITEMAP_MAX_BYTES]` — `resp.content` fully buffers the response body in memory *before* the 5MB slice is applied. The cap is cosmetic: a malicious or misconfigured sitemap server streams an arbitrarily large body and the API process buffers all of it. This applies to the top-level sitemap and up to 5 child sitemaps per request (6 unbounded buffers). Combined with the per-read timeout (not total), one authorized analyst request can exhaust API memory.
- **Evidence:** `resp = await client.get(url)` (non-streaming, :112) → `.content` accessed at :115; no `stream=True` / `aiter_bytes` accounting anywhere in the file.
- **Suggested fix direction:** Use `client.stream("GET", url)` and accumulate chunks, aborting once the running total exceeds SITEMAP_MAX_BYTES; also check `Content-Length` up front when present.
- **Status:** open

### [HIGH] No request body-size limit anywhere in the API — unauthenticated oversized bodies fully buffered
- **Area:** backend
- **Location:** `backend/app/schemas.py:585-592`, `backend/app/main.py` (absent middleware)
- **What's wrong:** The "512KB cap" is not enforced before parsing. `csv_text` is capped by Pydantic `max_length=BULK_IMPORT_MAX_CSV_BYTES`, which (a) counts *characters*, not bytes — 512K chars of multi-byte UTF-8 can be ~2MB, so the constant's name is wrong — and (b) runs only after Starlette has read and JSON-decoded the entire request body. There is no body-size limit middleware anywhere in main.py, and FastAPI reads the body before resolving the auth dependency, so even an *unauthenticated* client can POST a multi-hundred-MB JSON body that is fully buffered and JSON-parsed before any 401/422. The per-IP rate limiter limits request count, not request size.
- **Evidence:** schemas.py:592 `max_length=BULK_IMPORT_MAX_CSV_BYTES` (str max_length = chars); main.py:28-77 has no Content-Length/body-size guard.
- **Suggested fix direction:** Add middleware (or reverse-proxy config documented as a requirement) rejecting bodies over ~1MB by Content-Length and by streamed count; keep the Pydantic cap as the second layer and fix its name/semantics if bytes are the real contract.
- **Status:** open

### [HIGH] Oversized CSV field crashes import with 500
- **Area:** backend
- **Location:** `backend/app/routers/imports.py:61-75`
- **What's wrong:** `_parse_csv_rows` does not catch `csv.Error`. Python's csv module raises `_csv.Error: field larger than field limit (131072)` for any single field over 128K chars — within the permitted 512K-char `csv_text`. One such row (e.g., a pasted multi-MB URL or garbage line) crashes the whole endpoint with a 500 instead of degrading to a per-row error, violating the per-row-degradation contract. Additionally, an unclosed quote makes csv.reader silently merge all subsequent physical lines into one record, so following rows vanish without any per-row error — the caller cannot see they were dropped.
- **Evidence:** `csv.reader(io.StringIO(text))` iterated at :66 with no try/except; no `csv.field_size_limit` adjustment.
- **Suggested fix direction:** Iterate the reader inside try/except csv.Error and convert to a per-row (or whole-parse 422) error; pre-split pathological inputs or set an explicit field size limit; consider `quoting=csv.QUOTE_NONE` given the spec is plain `url[,name]`.
- **Status:** open

### [MEDIUM] 500-row truncation is invisible to the caller
- **Area:** backend
- **Location:** `backend/app/routers/imports.py:202-203,162-171`
- **What's wrong:** The 500-row cap is truncate-and-continue (matching documented behavior) but truncation is invisible. `rows = rows[:BULK_IMPORT_MAX_ROWS]` drops rows silently; the response's `total_rows` equals `len(results)` (500), indistinguishable from an import of exactly 500 rows. Same for the sitemap path (`pages[:BULK_IMPORT_MAX_ROWS]` at :169) — an 800-URL sitemap reports 500 rows with no indication 300 were dropped.
- **Evidence:** No `truncated` field on `BulkImportResult` (schemas.py:615-620); no detail row or count of dropped rows at :202-203 or :169.
- **Suggested fix direction:** Add `truncated: bool` (or `rows_dropped: int`) to BulkImportResult and set it in both branches.
- **Status:** open

### [MEDIUM] Bulk import audit rows contain no URLs — cannot reconstruct which sites were created
- **Area:** backend
- **Location:** `backend/app/routers/imports.py:264-277`
- **What's wrong:** Audit coverage is aggregate-only: one `site.bulk_import` row with source + counts. Unlike single-site create (sites.py:114-122, which records name/URL per site), sites created via bulk import get no per-site audit entry and the aggregate row contains no URLs — there is no way to reconstruct from the audit log *which* sites an import created. The aggregate design means a huge import cannot produce an oversized audit row (and `_redact` caps values at 500 chars / 40 keys regardless), but it's an auditability gap.
- **Evidence:** `after={"source":…, "rows":…, "created":…, "skipped":…, "errors":…}` — no URL list, no site IDs; audit.py:44-45 caps confirm no oversize path.
- **Suggested fix direction:** Include created site IDs/URLs in bounded batches (e.g., first N plus count), or emit per-site `site.create` audit rows tagged with a batch ID.
- **Status:** open

### [MEDIUM] Post-commit baseline enqueue failure overwrites all created rows' status with error detail
- **Area:** backend
- **Location:** `backend/app/routers/imports.py:282-294`
- **What's wrong:** If any single `enqueue_baseline_capture` fails, the "could not be enqueued" detail is written onto *every* created row — including rows whose baselines were already enqueued successfully before the queue died. Only `HTTPException` is caught; `_send` (tasks.py:34-41) converts only `kombu OperationalError` to HTTPException, so any other broker exception propagates after commit → the client gets a 500 with zero results even though all sites were committed — the caller can't see what was created. Recovery for stranded pending baselines is manual-only (per-site Rebaseline); nothing sweeps them automatically.
- **Evidence:** Loop :283-287 catches only HTTPException; blanket detail overwrite :288-294 keyed on `r.status == "created"`, not on which IDs failed; comment at :280-281 confirms manual recovery.
- **Suggested fix direction:** Track failed baseline IDs and annotate only their rows; broaden the except to Exception around each enqueue; consider a periodic janitor that re-enqueues stale pending baselines.
- **Status:** open

### [MEDIUM] Duplicate site detection is load-then-check with no DB uniqueness backstop
- **Area:** backend
- **Location:** `backend/app/routers/imports.py:205,220-229`, `backend/app/models.py:220`
- **What's wrong:** Duplicate handling is load-then-check with no DB uniqueness backstop. `existing_urls` is a snapshot taken once; `sites.url` has a non-unique index (`unique=False` confirmed in migration). Two concurrent bulk imports (or an import racing a single-site create) both pass the check and create duplicate sites. Also, matching is exact-string only: `https://a.com`, `https://a.com/`, and `https://A.com` are treated as distinct, so trivially-varied duplicates import as separate sites. Within one request the created/skipped semantics are correct (first occurrence created, later duplicates `skipped`).
- **Evidence:** imports.py:205 single snapshot query; models.py:220 `Index("ix_sites_url", "url")` non-unique; migration 76f6f5dcf922 `unique=False`.
- **Suggested fix direction:** Normalize URLs (lowercase scheme/host, canonical trailing slash) before comparison and add a unique index on the normalized URL, downgrading IntegrityError to a per-row `skipped` (requires the CRITICAL per-row error isolation first).
- **Status:** open

### [MEDIUM] Analyst-level allow_private_networks flag turns sitemap crawl into an internal-network read oracle
- **Area:** backend
- **Location:** `backend/app/routers/imports.py:189-190,146,231-233`
- **What's wrong:** `allow_private_networks` is a single request-level flag settable by any analyst, and it does triple duty: it relaxes the SSRF policy for the sitemap fetch itself (including the pinning transport and every redirect hop), for every child-sitemap fetch, and for every created site's per-row check. An analyst can point `sitemap_url` at an internal host with `allow_private_networks=true` and have the server fetch internal HTTP resources, with any `<loc>` text from the response echoed back verbatim in the API response — a direct internal-network read oracle (more direct than the screenshot channel single-site create offers, which requires image rendering). Per-row checks themselves are correctly present: every CSV row and every sitemap-derived row runs `assert_url_allowed` (:231-233); no row can individually opt in — the flag is batch-wide, which also means one flag silently opts *all* rows into private ranges.
- **Evidence:** BulkImportRequest.allow_private_networks (schemas.py:595) → `_crawl_sitemap_impl` (:125-127, :146, :152-154) and the per-row check (:231-233); loc text propagated to `result.url` at :213.
- **Suggested fix direction:** If internal-sitemap crawling isn't a deliberate feature, restrict `allow_private_networks=true` bulk imports (or at least the sitemap-crawl variant) to admin, or require the flag per-row for CSV; at minimum document that this flag turns the crawler into an internal fetcher.
- **Status:** needs-user-decision

### [LOW] Sitemap fetch timeout is per-operation, not total deadline; relative HTTPS redirects break TLS after pinning
- **Area:** backend
- **Location:** `backend/app/routers/imports.py:47,139-148`
- **What's wrong:** `httpx.Timeout(SITEMAP_TIMEOUT_S)` sets 20s *per operation* (connect/read/write), not a total deadline. A slow-drip server emitting one byte every ~19s resets the read timeout indefinitely, holding the request (and, with the HIGH sitemap buffer finding, growing the buffer) far beyond 20s across up to 6 fetches and 5 redirects each. Also, after `SSRFPinningTransport` rewrites the URL to a pinned IP, a *relative* redirect is resolved against the IP-form URL, so the next hop's `sni_hostname` extension is not re-applied — HTTPS relative redirects will fail TLS verification (fails safe, but breaks legitimate sitemaps behind such redirects).
- **Evidence:** :142 single-value Timeout; ssrf_transport.py:81-93 rewrite + one-shot `sni_hostname`; httpx builds next_request from the rewritten URL.
- **Suggested fix direction:** Wrap each fetch in `asyncio.timeout(total)`; in the transport, preserve the original hostname for redirect resolution (or restore the URL host post-response).
- **Status:** open

### [LOW] CSV BOM and blank-line handling cause confusing errors; empty csv_text + sitemap silently ignores sitemap
- **Area:** backend
- **Location:** `backend/app/routers/imports.py:65-71`, `backend/app/schemas.py:599-601`, `imports.py:185`
- **What's wrong:** (a) BOM: a UTF-8-BOM CSV (the Excel default) yields a first cell of `﻿url`, which fails the header match and becomes a spurious per-row error; a BOM-prefixed first URL likewise fails the scheme check. Degrades per-row (correct fail-safety) but guarantees a confusing error on the most common real-world CSV. Header detection also only fires on physical line 1, so a blank line above the header defeats it. (b) `validate_source` uses truthiness: `csv_text=""` alongside a valid `sitemap_url` passes validation, then `body.csv_text is not None` selects the CSV branch and the sitemap is silently ignored → misleading "No importable rows" 422.
- **Evidence:** Header check at :71 (`line_no == 1`, exact strings); schemas.py:600 `bool(self.csv_text) == bool(self.sitemap_url)` vs imports.py:185 `is not None`.
- **Suggested fix direction:** `text.lstrip("﻿")` (or utf-8-sig client-side contract), match the header on the first *non-blank* row, and make source selection use `is not None` in both places (treat empty/whitespace csv_text as absent).
- **Status:** open

### [MEDIUM] Bulk-import test coverage is thin — misses every finding above
- **Area:** test-coverage
- **Location:** `backend/tests/test_phase5_bulk_import.py`
- **What's wrong:** Coverage is thin relative to the contract and misses every finding above. No tests for: the 500-row or 512KB caps and truncation visibility; malformed CSV (BOM, quoted fields, unclosed quotes, oversized fields → the HIGH crash); oversized CSV names (the CRITICAL — and it *cannot* fail on SQLite anyway); the real sitemap crawl path (`_crawl_sitemap_impl` is monkeypatched away, so `SSRFPinningTransport`, the redirect guard, child-sitemap capping, size caps, and lxml parser config are never executed by any test); entity-expansion/XXE documents; enqueue-failure annotation; and the empty-csv_text-plus-sitemap source-selection bug. The autouse `_stub_ssrf` fixture replaces `assert_url_allowed` module-wide, so even the per-row SSRF integration is only tested against a fake.
- **Evidence:** Fixtures at lines 10-30; six tests total; `monkeypatch.setattr(imports_router, "_crawl_sitemap_impl", fake_crawl)` at :111.
- **Suggested fix direction:** Add unit tests for `_parse_csv_rows` edge cases and `_extract_sitemap_urls` hostile docs (nested index, self-reference, entity bomb), a respx/mock-transport test exercising the real crawl including redirects and oversized bodies, and cap/truncation assertions on the endpoint.
- **Status:** open

### [VERIFIED CLEAN] Bulk import: lxml no_network + entity expansion mitigation, sitemap nesting bounded, SSRF pinning on every fetch, baseline-enqueue-after-commit
- **Area:** backend
- **Evidence:** lxml parser is `recover=True, resolve_entities=False, no_network=True` with `huge_tree` at safe default, so billion-laughs entity expansion and external-DTD fetches are mitigated. Sitemapindex nesting bounded to one level by construction — child docs' own `children` are discarded (`child_pages, _ =` at :155), so a self-referencing or deeply-nested index cannot recurse; child fetches capped at 5, each child URL independently `assert_url_allowed`-checked, all fetches go through `SSRFPinningTransport` (resolve-validate-connect same address per hop) with a redirect response-hook as a second guard, and the crawl breaks once 500 pages accumulate. Baselines enqueued strictly after `db.commit()` (:278 → :283) in both bulk and single-site paths. RBAC correct: bulk-import requires `AnalystUser` (admin or analyst), matching single-site create/mutating operations and the analyst-operational split documented in deps.py; viewer denial test-pinned.
- **Status:** verified clean

### [CRITICAL] Recharts not code-split despite lazy() wrappers — static imports bundle it into main chunk
- **Area:** frontend
- **Location:** `frontend/src/components/incident-timeline.tsx:1-11`, `risk-gauge.tsx:1`
- **What's wrong:** Both components statically import Recharts at the top level. The scan-detail and site-detail pages lazy-load these components (`scan-detail.tsx:25`, `site-detail.tsx:39`), but `React.lazy()` only defers the component module — static imports *inside* those modules are bundled immediately at parse time. Recharts (~90KB gzipped, ~250KB in the main bundle per typical tree-shaking) is loaded on initial page load regardless of whether any chart ever renders. The Phase 3 decision explicitly required code-split via lazy/Suspense to keep the main bundle small.
- **Evidence:** incident-timeline.tsx:1-11 and risk-gauge.tsx:1 both static-import Recharts symbols; page-level `lazy()` wrappers only defer the wrapper module, not its synchronous dependencies.
- **Suggested fix direction:** Dynamic import Recharts inside the component render (`const Recharts = await import("recharts")` or nested lazy subcomponent), or accept the bundle cost and document it.
- **Status:** open

### [HIGH] Visual diff slider missing aria-orientation on keyboard-accessible handle
- **Area:** frontend
- **Location:** `frontend/src/components/visual-diff-slider.tsx:294-314`
- **What's wrong:** Divider handle has `role="slider"` and arrow-key support (:307-310) but is missing `aria-orientation="horizontal"` — screen readers may announce it incorrectly or fail to convey the drag axis, confusing AT users about which keys to press.
- **Evidence:** Line 294 `role="slider"` with aria-valuemin/max/now but no aria-orientation; lines 308-309 handle ArrowLeft/ArrowRight (horizontal movement).
- **Suggested fix direction:** Add `aria-orientation="horizontal"` to the divider element at :294.
- **Status:** open

### [MEDIUM] DOM diff tree child truncation at 120 is silent — no "N more" UI
- **Area:** frontend
- **Location:** `frontend/src/components/dom-diff-tree.tsx:38,66-68,184-186`
- **What's wrong:** `CHILD_LIMIT` truncation breaks at 120 children per level (:66-68 `if (count++ >= CHILD_LIMIT) break`) but the render never indicates truncation occurred — the spec explicitly requires "N more children hidden" when lists are capped. Users cannot see whether overflow happened.
- **Evidence:** Line 66 truncates silently; line 186 renders all children in the `children` array with no overflow indicator.
- **Suggested fix direction:** Track truncation count in `subtree()` and `diffElements()`, store as a field on `DiffNode`. In `NodeRow` :185, after rendering all children, render a muted "… N more children hidden" row if count > 0.
- **Status:** open

### [MEDIUM] Suppression-panel delete-rule button aria-label not unique across multiple rules
- **Area:** frontend
- **Location:** `frontend/src/components/suppression-panel.tsx:259-267`
- **What's wrong:** Delete rule button (Trash2 icon-only) has `aria-label="Delete rule"` (:262) — static label. Multiple rules in the list produce identical labels, violating WCAG 2.5.3 (Label in Name) for users navigating by voice commands ("click Delete rule" is ambiguous).
- **Evidence:** Line 262 `aria-label="Delete rule"` is static; line 239 renders multiple rules in a loop, so all delete buttons share the same label text.
- **Suggested fix direction:** Change to `aria-label={`Delete ${describeRule(rule)} rule`}` to make each label unique and contextual.
- **Status:** open

### [MEDIUM] Remediation-hooks-panel delete button aria-label could fail on empty/special-char hook name
- **Area:** frontend
- **Location:** `frontend/src/components/remediation-hooks-panel.tsx:292-299`
- **What's wrong:** Delete hook button is icon-only (Trash2) with `aria-label={`Delete ${h.name}`}` (:293), assuming `h.name` is always a non-empty string. `createRemediationHook` (:82) sends `name` from state and the Input field at :169 has `required`, but client-side `required` doesn't prevent empty string if validation is pure HTML5 (no explicit trim check before mutate at :125).
- **Evidence:** Line 293 template interpolation assumes non-empty; Input :169 `required` is HTML5 only.
- **Suggested fix direction:** Add explicit `.trim()` check before `create.mutate()` at :125, or sanitize the aria-label: `aria-label={`Delete hook${h.name ? ` ${h.name}` : ""}`}`.
- **Status:** open

### [LOW] DOM diff auto-expand depth cap is undocumented magic number
- **Area:** frontend
- **Location:** `frontend/src/components/dom-diff-tree.tsx:145`
- **What's wrong:** Auto-expand depth cap is hardcoded to 12 with no rationale or documentation. The backend can send deeply nested HTML (100+ levels from a malformed injection), but `buildDomDiff`'s recursive walk has no defensive cap, so adversarial input could still produce pathological expansion.
- **Evidence:** Line 145 `useState(node.hasChanges && depth < 12)` — magic 12.
- **Suggested fix direction:** Document the constant at top of file; verify `buildDomDiff`'s pairing logic can't stack-overflow on adversarial input (DOMParser itself is safe, but the recursive walk isn't capped).
- **Status:** open

### [LOW] Finding-card expand/collapse button has no aria-label
- **Area:** frontend
- **Location:** `frontend/src/components/finding-card.tsx:528-542`
- **What's wrong:** Cards auto-expand when score >= 0.15 (correct), but the expand/collapse button at :537-542 has only ChevronDown/ChevronRight icons (aria-hidden) and no accessible label — screen reader users hear "button" with no indication of what it toggles. `aria-expanded={open}` is present but button purpose is unmarked.
- **Evidence:** Lines 537-542 button with icon only, no label; :541 `aria-expanded={open}` insufficient without label.
- **Suggested fix direction:** Add `aria-label={`${open ? "Collapse" : "Expand"} ${title} evidence`}` to the button at :537.
- **Status:** open

### [LOW] App-shell sign-out icon not aria-hidden, duplicates label
- **Area:** frontend
- **Location:** `frontend/src/components/app-shell.tsx:65-68`
- **What's wrong:** Sign-out button combines icon + text but the icon is not aria-hidden, so screen readers announce "Log Out graphic Sign out" (redundant).
- **Evidence:** Line 66 `<LogOut />` without aria-hidden; :67 "Sign out" text follows.
- **Suggested fix direction:** Add `aria-hidden="true"` to the LogOut icon: `<LogOut aria-hidden />`.
- **Status:** open

### [LOW] User role dropdown aria-label duplicates row context
- **Area:** frontend
- **Location:** `frontend/src/components/users-card.tsx:85`
- **What's wrong:** Role dropdown renders a native select with `aria-label={`Role for ${user.email}`}` when the email is already the row's primary text (:66) — inefficient for AT users tabbing through a long user list.
- **Evidence:** :85 label includes email; email already visible at :66.
- **Suggested fix direction:** Simplify to `aria-label="Role"` — screen readers already announce the row context.
- **Status:** open

### [LOW] Bulk-import dialog stale error persists on "Import more"
- **Area:** frontend
- **Location:** `frontend/src/components/bulk-import-dialog.tsx:80,168-170,209`
- **What's wrong:** Form error message has `role="alert"` (correct), but when the dialog reopens after a successful import (line 209 "Import more"), `formError` state isn't cleared — stale error text persists if the user clicks "Import more" after an error. Line 80 `setFormError(null)` only runs when the dialog closes entirely.
- **Evidence:** :80 clears only on close; :209 "Import more" calls `setResult(null)` but leaves formError untouched.
- **Suggested fix direction:** Add `setFormError(null)` at :209 when resetting to the form view.
- **Status:** open

### [LOW] Visual diff slider alt text inconsistent — current "Current capture", baseline empty
- **Area:** frontend
- **Location:** `frontend/src/components/visual-diff-slider.tsx:235,247`
- **What's wrong:** Current capture has `alt="Current capture"` (:235) while baseline has empty `alt=""` (:247). The baseline correctly hides from AT (images are decorative within the slider's labeled container), but "Current capture" should also be empty since the divider's aria-label already describes the comparison.
- **Evidence:** Line 235 vs :247 — inconsistent.
- **Suggested fix direction:** Change :235 to `alt=""` to match baseline.
- **Status:** open

### [LOW] Dialog close button has no title attribute for sighted keyboard users
- **Area:** frontend
- **Location:** `frontend/src/components/ui/dialog.tsx:71-76`
- **What's wrong:** Close button has sr-only "Close" text (:76) but the button itself has no visible label for sighted keyboard users — the X icon is only 16px and may be hard to identify at a glance on dark backgrounds. No tooltip, no title attribute.
- **Evidence:** Line 75 XIcon with sr-only text only.
- **Suggested fix direction:** Add `title="Close"` to the `DialogPrimitive.Close` element at :71 for a native browser tooltip.
- **Status:** open

### [LOW] Button focus ring contrast below WCAG 2.4.7 AA minimum
- **Area:** frontend
- **Location:** `frontend/src/components/ui/button.tsx:17`
- **What's wrong:** Focus ring uses `ring-ink/30` (rgba(252,253,255,0.3)) — on the true-black canvas this produces ~76 effective luminance, below WCAG 2.4.7 AA contrast requirement (3:1 for focus indicators).
- **Evidence:** Line 17 `focus-visible:ring-2 focus-visible:ring-ink/30` — ink is #fcfdff, 30% opacity on #000000 is ~2.0:1 contrast.
- **Suggested fix direction:** Increase to `ring-ink/50` or `ring-ink/60` to meet 3:1 minimum (50% = ~126 luminance = 3.1:1).
- **Status:** open

### [VERIFIED CLEAN] Frontend components: visual-diff altered-region detection, DOM diff pairing/states, risk-gauge 270° arc + tone thresholds, incident-timeline time-scaled + dashed threshold + click nav, suppression-panel RegionPicker Phase 3 fix, finding-card 9-layer renderers + GenericEvidence fallback, bulk-import per-row results, app-shell role-conditional nav, shadcn ui reskin
- **Area:** frontend
- **Evidence:** visual-diff-slider: client-side downsampled diff with greedy rectangle merge (:34-49), different-height handling (crop via samplePixels), suppressed-bbox overlay distinct (hatched vs translucent red); dom-diff-tree: pairing by signature, same/added/removed/modified states, auto-expand on changes (depth < 12); risk-gauge: 270° arc (startAngle 225 endAngle -45 :49-50), tone thresholds red >= threshold / orange >= 0.15 / green below (:17-20); incident-timeline: time-scaled LineChart, dashed threshold (:134-144), point-click via onPointClick (:164); suppression-panel: RegionPicker measures against contentRef (Phase 3 fix :66), bbox baseline-anchored; finding-card: purpose-built renderers for all 9 layers with GenericEvidence fallback (:516-526), cards auto-expand at >= 0.15; bulk-import: per-row results with clear created/skipped/error badges (:29-33, :183-204); app-shell: role-conditional nav (isAdmin filter :26); shadcn ui components: verified hairline borders not shadows, rounded-lg on cards, accent washes only, true-black canvas.
- **Status:** verified clean

### [HIGH] Raw API error messages can leak to the user
- **Area:** frontend
- **Location:** `frontend/src/lib/api.ts:28-38,88`
- **What's wrong:** `parseDetail` (:28-38) extracts `body.detail` directly from server responses and surfaces it through `ApiError.message`. Pages display this via `err.message` without sanitization (login.tsx:33, sites.tsx:99, settings.tsx:49). If the backend returns a stack trace, internal path, or Pydantic validation details in `detail`, the UI shows it verbatim.
- **Evidence:** api.ts:32 returns raw `body.detail`, :88 throws `ApiError(resp.status, await parseDetail(resp))`. All pages catch as `err instanceof ApiError ? err.message : "..."` with no scrubbing.
- **Suggested fix direction:** Add sanitization in `parseDetail` that strips patterns matching stack traces (`  File "`, `Traceback`, paths like `/app/...`) or replaces them with generic messages. Defense-in-depth: also ensure backend never includes internal details in 4xx/5xx `detail` fields.
- **Status:** open

### [MEDIUM] Alerts/health/remediation pages refetchInterval lacks self-documenting cleanup semantics
- **Area:** frontend
- **Location:** `frontend/src/pages/alerts.tsx:128`, `health.tsx:83`, `remediation.tsx:167`
- **What's wrong:** `refetchInterval` is static (30s alerts, 15s health/remediation) with no conditional. TanStack Query auto-stops polling when inactive (user navigates away), so behavior is correct, but the static pattern doesn't self-document cleanup. The charter asks "Do queries stop refetching on unmount?"—yes, but the code doesn't explicitly show this.
- **Evidence:** alerts:128 `refetchInterval: 30000` static; TanStack Query handles via inactivity, but code doesn't document.
- **Suggested fix direction:** Change to `refetchInterval: (query) => (query.state.data ? 30000 : false)` or add comment documenting auto-stop on unmount.
- **Status:** open

### [LOW] Site-detail has two overlapping scan-poll queries
- **Area:** frontend
- **Location:** `frontend/src/pages/site-detail.tsx:279-284,292-297`
- **What's wrong:** Table polls every 2s (20 scans), timeline every 5s (200 scans). With 5 running scans, backend sees ~0.7 req/sec for one page. Independent query keys, no deduplication. Intervals reasonable individually, but redundant.
- **Evidence:** :279-284 (2s), :292-297 (5s). Two queries, overlapping data.
- **Suggested fix direction:** Unify (fetch 200-scan timeline, derive table client-side), coordinate intervals, or accept trade-off.
- **Status:** open

### [LOW] Visual diff slider keyboard handle has no visible focus indicator
- **Area:** frontend
- **Location:** `frontend/src/components/visual-diff-slider.tsx:294-314`
- **What's wrong:** Handle has keyboard support, `role="slider"`, aria-*, but no `:focus-visible` style. Keyboard users can't see focus.
- **Evidence:** :293-314 `tabIndex={0}` but no focus styles.
- **Suggested fix direction:** Add `focus-visible:ring-2 focus-visible:ring-white/60 focus-visible:outline-none`.
- **Status:** open

### [LOW] Icon-only trash buttons have aria-label but no tooltip
- **Area:** frontend
- **Location:** `frontend/src/components/suppression-panel.tsx:260-267`, sites/settings similar
- **What's wrong:** Delete buttons have `aria-label` (WCAG compliant) but no `title` or Tooltip for sighted mouse users. UX polish gap, not compliance violation.
- **Evidence:** :260 `aria-label="Delete rule"` but no tooltip.
- **Suggested fix direction:** Add `title` attributes or Tooltip components.
- **Status:** open

### [LOW] SMTP save-gate re-locks on non-credential edits
- **Area:** frontend
- **Location:** `frontend/src/pages/settings.tsx:94-106,261`
- **What's wrong:** `edited<T>` wrapper applied to all fields; toggling `security` or editing `from_name` re-locks Save even if test covered it. Ultra-strict per Phase 4 design but may frustrate users.
- **Evidence:** :94-99 wrapper, :261 `disabled={!testedOk}`.
- **Suggested fix direction:** Document as intended, or refine lock to only credential fields.
- **Status:** open

### [LOW] Sites page baseline-capture polling has no hung-state affordance
- **Area:** frontend
- **Location:** `frontend/src/pages/sites.tsx:79-84`
- **What's wrong:** Polls every 3s while `capturing`. If hung server-side, polls indefinitely. Backend owns timeout, but UI could show warning after 2 min. UX polish, not bug.
- **Evidence:** :79-84 conditional poll.
- **Suggested fix direction:** Add heuristic or accept current.
- **Status:** open

### [LOW] Telegram settings polls indefinitely while waiting for /start
- **Area:** frontend
- **Location:** `frontend/src/pages/settings.tsx:281-282`
- **What's wrong:** Polls every 4s while `configured && !chat_id`. No timeout after 5 min.
- **Evidence:** :281-282 conditional poll.
- **Suggested fix direction:** Add timestamp check or accept current.
- **Status:** open

### [LOW] DOM diff auto-expand could render thousands of nodes on pathological pages
- **Area:** frontend
- **Location:** `frontend/src/components/dom-diff-tree.tsx:145`
- **What's wrong:** Auto-expands to depth 12. Pathological page could render 14,400 nodes. Tree scrolls, but initial render may be slow.
- **Evidence:** :145 `depth < 12`.
- **Suggested fix direction:** Lower to 6-8 or add node budget.
- **Status:** open

### [LOW] Login page shows form during silent refresh — no loading UI
- **Area:** frontend
- **Location:** `frontend/src/pages/login.tsx:23`
- **What's wrong:** Form renders immediately while `loading` (auth checking session), causing ~100-300ms flicker. Other pages have loading UIs.
- **Evidence:** :23 no loading branch when `loading === true`.
- **Suggested fix direction:** Add loading UI or accept current (fast refresh makes it acceptable).
- **Status:** open

### [VERIFIED CLEAN] Frontend pages: auth flows, CRUD, polling cleanup, role gates, artifact auth, loading/empty/error states, accessibility
- **Area:** frontend
- **Evidence:** Token refresh single-flight (api.ts:46-63 `refreshInFlight`), session expiry handling (:80-86 `onSessionExpired`), artifact fetch with Bearer (:385-397), visual diff bbox math verified (:62-72, :115-146), RegionPicker drag verified (suppression-panel:62-112), SMTP test-gates-save enforced (settings:261), empty states designed (all 9 pages), error states user-safe, role-gated UI (App.tsx:29-34, app-shell:19-27, settings:899-939), TanStack Query inactive-stop verified, mutations have onError, icon-only buttons have aria-label, images have alt, forms have Label htmlFor, contrast verified (ink/canvas 19.48:1 AAA, charcoal 5.56:1 AA, mute 3.32:1 acceptable for captions).
- **Status:** verified clean

### [MEDIUM] Clickable scan-table rows are not keyboard-focusable and have no focus-visible state
- **Area:** ui-ux
- **Location:** `frontend/src/pages/site-detail.tsx:505-511`
- **What's wrong:** Scan rows are click-navigable (`cursor-pointer` + `onClick`) but the `<TableRow>` has no `tabIndex`, no role, and no focus-visible treatment — a `<tr>` can never receive even the browser-default focus ring the design doc's Known Gaps sanctions. Keyboard users cannot reach the drilldown from the table at all.
- **Evidence:** `<TableRow key={scan.id} className="cursor-pointer" onClick={...}>` with no keyboard affordance; `ui/table.tsx` row styles define hover only. Verified in-source.
- **Suggested fix direction:** Make the row's primary cell a link/button (or add `tabIndex={0}` + key handling + a `focus-visible:bg-surface-elevated` treatment).
- **Status:** open

### [MEDIUM] Off-scale spacing values (14px, 20px, 40px) on core evidence surfaces
- **Area:** ui-ux
- **Location:** `frontend/src/components/finding-card.tsx:539,559`; `frontend/src/pages/scan-detail.tsx:113,243,252`; `frontend/src/components/suppression-panel.tsx:231`
- **What's wrong:** The spacing scale is 2/4/8/12/16/24/32/48. Actual: finding-card header `px-5 py-3.5` (20px/14px) and body `px-5 py-4` (20px); scan-detail in-flight banner `px-5 py-4`; scan-detail section rhythm `mb-10` (40px) where site-detail uses on-scale `mb-8` for the same role; suppression-panel `space-y-5` (20px) where site-detail's settings card uses `space-y-4`.
- **Evidence:** Tailwind scale resolution: `p-5`=20px, `py-3.5`=14px, `mb-10`=40px, `space-y-5`=20px — none map to a DESIGN-resend spacing token. All cited lines verified in-source.
- **Suggested fix direction:** Snap to scale neighbors (`px-4`/`px-6`, `py-3`/`py-4`, `mb-8`/`mb-12`, `space-y-4`), matching site-detail's rhythm.
- **Status:** open

### [LOW] Risk-gauge percentage is the only risk value not in the Geist Mono lane
- **Area:** ui-ux
- **Location:** `frontend/src/components/risk-gauge.tsx:62-64`
- **What's wrong:** Every other numeric risk rendering uses `text-code-md` (site-detail riskCell, finding-card score chip, fusion inputs); the gauge's center value uses `text-heading-md` (Inter 24/500), breaking the "risk numbers are mono" convention on a screen where gauge and finding cards co-exist.
- **Evidence:** `<span className="text-heading-md" style={{ color }}>{pct}%</span>` vs `text-code-md` on all sibling risk values. Verified in-source.
- **Suggested fix direction:** Move the gauge value to the mono lane at a larger size, or document heading-md as the one display-scale exception.
- **Status:** open

### [LOW] Timeline tick/label font sizes (11px, 10px) sit off the typography scale
- **Area:** ui-ux
- **Location:** `frontend/src/components/incident-timeline.tsx:122,129,139-144`
- **What's wrong:** The type ramp bottoms out at caption 12px; axis ticks use `fontSize: 11` and the threshold reference-line label `fontSize: 10` — two ad-hoc sizes below the smallest token. Family and fill are correctly tuned; only sizes deviate.
- **Evidence:** `tick={{ fill: MUTE, fontSize: 11 }}` on both axes; `label={{ ... fontSize: 10 }}` on the ReferenceLine. Verified in-source.
- **Suggested fix direction:** Lift both to 12px (caption size).
- **Status:** open

### [LOW] Inline-code chips use surface-deep instead of the spec's surface-card background
- **Area:** ui-ux
- **Location:** `frontend/src/components/finding-card.tsx:70`
- **What's wrong:** DESIGN-resend's Don't list: "even small inline code uses Geist Mono and a `{colors.surface-card}` background"; surface-deep (#06060a) is reserved for code-window shells (elevation 3). The shared `Mono` chip — every hash, URL, issuer, matched phrase — renders `bg-surface-deep`.
- **Evidence:** `"rounded-xs bg-surface-deep px-1.5 py-0.5 text-code-md break-all"` in `Mono`. Verified in-source.
- **Suggested fix direction:** Swap to `bg-surface-card` (chips sit on surface-card cards already, so a hairline border may be needed for separation).
- **Status:** open

### [LOW] Native unstyled checkbox breaks the reskin rule
- **Area:** ui-ux
- **Location:** `frontend/src/pages/site-detail.tsx:184-189`
- **What's wrong:** "Scheduled scans enabled" uses a raw `<input type="checkbox">` with only `size-4 accent-ink`; `accent-color` recolors the check but border/radius/surface remain browser chrome — the only form control not built from tokens.
- **Evidence:** `<input type="checkbox" ... className="size-4 accent-ink" />` — no token border, radius, or background. Verified in-source.
- **Suggested fix direction:** Reskinned switch/checkbox primitive (hairline-strong border, rounded-xs, surface-card fill) consistent with the other inputs.
- **Status:** open

### [LOW] Numeric evidence metrics rendered in the sans lane while sibling metrics are mono
- **Area:** ui-ux
- **Location:** `frontend/src/components/finding-card.tsx:98-105,250-258,427,456`
- **What's wrong:** Hashes/UAs/phrases correctly use `Mono` and risk scores `text-code-md`, but scalar metrics routed through `KV` (SSIM, pHash/dHash bit distances, semantic similarity, char counts) and the cloaking similarity value render in `text-body-sm` — same data class, two lanes, within one card stack.
- **Evidence:** `KV`'s value span is `text-body-sm text-body`; `VisualEvidence` passes raw numbers through it. Verified in-source.
- **Suggested fix direction:** Render numeric metric values in `text-code-md` (KV variant), keeping labels in caption sans.
- **Status:** open

### [LOW] Clickable timeline points have cursor affordance but no hover state
- **Area:** ui-ux
- **Location:** `frontend/src/components/incident-timeline.tsx:153-170`
- **What's wrong:** Dots are clickable (`onClick`, `cursor: pointer`) but `activeDot={false}` disables Recharts' hover enlargement and no substitute hover treatment exists — the only hover feedback is the shared tooltip.
- **Evidence:** Custom `dot` renderer sets cursor and nothing hover-reactive; `activeDot={false}`. Verified in-source.
- **Suggested fix direction:** Re-enable a token-styled `activeDot` (verdict-color fill, ink stroke, +1.5px radius).
- **Status:** open

### [LOW] Visual-diff divider handle has no hover state
- **Area:** ui-ux
- **Location:** `frontend/src/components/visual-diff-slider.tsx:300-314`
- **What's wrong:** The handle — the component's primary interactive element — renders a static `bg-surface-elevated` pill and never changes on hover; only the container-level `cursor-ew-resize` signals interactivity. (Focus-visible/aria-orientation already filed separately; hover is the residual gap.)
- **Evidence:** Handle pill `"... rounded-full border border-hairline-strong bg-surface-elevated"` — no `hover:` variant in the component. Verified in-source.
- **Suggested fix direction:** Add `hover:bg-surface-card hover:border-ink/40` or brighten the divider line on hover.
- **Status:** open

### [VERIFIED CLEAN] Wave D design-fidelity: SOC dashboard surfaces (site-detail, scan-detail, finding cards, slider, DOM tree, gauge, timeline, suppression panel)
- **Area:** ui-ux
- **Evidence:** Threat-state mapping (clean/green, pending-or-changed/orange, flagged/red) identical across badges, StatusDot, riskCell tones, finding-card scoreTone, gauge riskTone, timeline verdictColor; accent-red strictly local to flagged elements, no page-wide wash; zero shadow utilities in all eight files (tooltip/handle/overlays all hairline-on-token-surface); Recharts fully de-defaulted — every hex literal in gauge and timeline is an exact token value, no default grid/axis/tooltip/animation styling; visual-diff altered-region overlay exactly rgba(255,32,71,0.28)/0.55 per spec precedent with hatched suppressed regions clearly distinct; DOM diff tree exactly per the §4 addendum (accent/50 left borders + /[0.04] washes on surface-card, no saturated text); radius scale conformant throughout; hashes/URLs/UAs/selectors/regexes/phrases all in the mono lane; all icons semantic lucide; no emoji; suppression draft rectangle uses accent-blue translucently, correctly outside the threat vocabulary.
- **Status:** verified clean

### [HIGH] Nav bar has no responsive collapse — spec requires hamburger below 1024px
- **Area:** ui-ux
- **Location:** `frontend/src/components/app-shell.tsx:32-71`
- **What's wrong:** The DESIGN-resend responsive table specifies the top nav collapses to a hamburger at <1024px with the wordmark anchored. The shell renders a single flex row of six NavLinks plus user email and sign-out at all widths — no breakpoint handling, no hamburger, no hidden states. On tablet/mobile the 64px nav overflows or wraps, breaking the nav-bar spec on first mobile use.
- **Evidence:** Header markup has no `md:`/`lg:` visibility variants (verified: only container padding is responsive); index.css mobile rules touch only display type sizes and control heights.
- **Suggested fix direction:** Add a <1024px collapse (hamburger or reduced link set) per the responsive table.
- **Status:** open

### [MEDIUM] body-md/button-sm font-lane assignment contradicts Master Prompt §4's literal table — spec is self-contradictory
- **Area:** ui-ux / docs
- **Location:** `frontend/src/index.css:155-163,176-182`; `WARDRESS_MASTER_PROMPT.md` §4
- **What's wrong:** §4's substitution table reads "Instrument Sans for display-lg/subtitle roles, Inter for body-md/UI roles," but the implementation puts `text-body-md` and `text-button-sm` on Instrument Sans. The spec contradicts itself: body-md is an ABC Favorit token in DESIGN-resend, and §4's own "-0.5% tracking compensation on body sizes" note only makes sense if body-md rides the Favorit substitute — which is exactly what index.css implements (-0.88px = -0.8 + -0.5% of 16px), and what PROGRESS.md Phase 1 documented. The strict-lane rule makes this load-bearing either way.
- **Evidence:** index.css:158 `font-family: var(--font-display-sans)` inside `@utility text-body-md`; §4 table row vs its own compensation note; PROGRESS.md Phase 1 "Instrument Sans (display-lg/subtitle/body-md lane…)".
- **Suggested fix direction:** Rule which reading is authoritative; either move body-md/button-sm to Inter per the literal table, or amend §4 to codify the Instrument Sans reading (recommended — it matches DESIGN-resend's lane structure).
- **Status:** needs-user-decision

### [MEDIUM] Card component internal padding is 24px; feature-card spec is 32px
- **Area:** ui-ux
- **Location:** `frontend/src/components/ui/card.tsx:15,28,73`
- **What's wrong:** The feature-card/pricing-tier spec sets internal padding to 32px; the reskinned Card uses `py-6`/`px-6` (24px) throughout — one scale step under spec — while the file's own comment claims feature-card-bordered conformance. login.tsx hand-builds its card at the correct `p-8`. This is the root cause of the mixed 20/24/32px card interiors noted set-wide in the dashboard review.
- **Evidence:** card.tsx:15 `"...bg-surface-card py-6..."`, :28/:73 `px-6`; login.tsx:66 `p-8`. Verified in-source.
- **Suggested fix direction:** Move Card to 32px, or document Card as a deliberate denser dashboard container distinct from the marketing feature-card spec (one ruling, applied everywhere).
- **Status:** open

### [MEDIUM] Sonner's stock toast drop shadow is not neutralized
- **Area:** ui-ux
- **Location:** `frontend/src/components/ui/sonner.tsx:28-35`
- **What's wrong:** The elevation system has no drop-shadow language, but Sonner's own stylesheet applies a default `box-shadow` to `[data-sonner-toast]`. The reskin overrides only `--normal-bg/text/border` and `--border-radius`; nothing removes the shadow, so toasts render with default-library elevation.
- **Evidence:** Style object at :29-34 contains no shadow override; no `toastOptions` boxShadow reset; no toast CSS in index.css. Verified in-source.
- **Suggested fix direction:** `toastOptions={{ style: { boxShadow: "none" } }}` (or a CSS override) so hairline + surface step carries elevation.
- **Status:** open

### [MEDIUM] Login headline is off-token display type: ad-hoc 40px, wrong tracking ratio, no opsz/feature settings
- **Area:** ui-ux
- **Location:** `frontend/src/pages/login.tsx:55-57`
- **What's wrong:** The h1 uses `font-display text-[40px] leading-none tracking-tight`. 40px is not on the display ladder (96/76.8/56/44); `tracking-tight` is -0.025em = -1.0px at 40px vs the spec's -1% ratio (-0.4px); and bypassing the `text-display-*` utilities loses `font-variation-settings: "opsz" 144` and `font-feature-settings: "ss01","liga"` — both mandated by the §4 substitution rules for Fraunces.
- **Evidence:** login.tsx:55 verified; opsz/feature declarations exist only inside `@utility text-display-xxl/xl` (index.css:104-121).
- **Suggested fix direction:** Define this size as a proper display token variant (with -1% tracking, opsz 144, ss01/liga) or use an existing display utility with a clamp.
- **Status:** open

### [MEDIUM] Bulk-import mode toggles use an off-token border (white/40) and have no focus-visible treatment
- **Area:** ui-ux
- **Location:** `frontend/src/components/bulk-import-dialog.tsx:110-131`
- **What's wrong:** The CSV/Sitemap toggle buttons are raw `<button>`s. Active state uses `border-white/40` — rgba(255,255,255,0.4) is not a token (hairline 0.06, hairline-strong 0.14; the focus convention elsewhere is `border-ink`). No `focus-visible:` styles and no outline suppression, so keyboard focus shows the browser's stock ring beside fully reskinned controls in the same dialog.
- **Evidence:** :115/:126 `"border-white/40 text-ink"` for active; no focus-visible utilities in either className. Verified in-source.
- **Suggested fix direction:** `border-ink` (or hairline-strong + text state) for active; add the standard ink-based focus-visible treatment.
- **Status:** open

### [MEDIUM] Inline code rendered without the mandated code surface background (bulk-import dialog)
- **Area:** ui-ux
- **Location:** `frontend/src/components/bulk-import-dialog.tsx:101`
- **What's wrong:** DESIGN-resend Don'ts: even small inline code uses Geist Mono *and* a surface-card background. The `url,name` snippet gets `text-code-md text-body` — mono, but no background surface, radius, or padding.
- **Evidence:** `<span className="text-code-md text-body">url,name</span>`. Verified in-source.
- **Suggested fix direction:** Wrap inline code in the surface treatment (`rounded-xs bg-surface-card px-1.5 py-0.5`), consistent with finding-card's `Mono` chip (see also that chip's own surface-deep finding).
- **Status:** open

### [MEDIUM] Threat badge red text at 12px on red wash is ~3.5:1, below the 4.5:1 small-text threshold
- **Area:** ui-ux
- **Location:** `frontend/src/components/ui/badge.tsx:25` (all `threat` badge usages)
- **What's wrong:** `threat: "bg-glow-red text-accent-red"` sets #ff2047 caption text (12px/400) on rgba(255,32,71,0.34) composited over surface-card. Computed contrast ≈ 3.5:1 — under 4.5:1 for small text. This is accent-text-on-wash contrast not covered by the previously filed ink/charcoal/mute measurements. The orange `pending` variant computes ≈ 6:1 and green passes; only red fails.
- **Evidence:** Composite of rgba(255,32,71,0.34) over #0a0a0c ≈ rgb(93,18,32); relative luminance 0.229 vs 0.029 → 3.5:1 (math independently re-derived in the main session).
- **Suggested fix direction:** A dedicated higher-luminance on-wash red for badge text, or lower the wash opacity under lighter red text.
- **Status:** open

### [MEDIUM] Button size scale ships sub-36px desktop heights, off the "all buttons minimum 36px on desktop" spec
- **Area:** ui-ux
- **Location:** `frontend/src/components/ui/button.tsx:33-39`; consumers incl. `sites.tsx` (delete icon-sm 32px, bulk-import trigger sm 32px), `app-shell.tsx` (sign-out sm)
- **What's wrong:** DESIGN-resend touch targets: minimum 36px tall on desktop. The scale defines `sm` h-8 (32px), `xs` h-6 (24px), `icon-sm` size-8, `icon-xs` size-6 — all under minimum and in active use. index.css's mobile rule additionally exempts xs/icon-xs from the 44px mobile minimum (index.css:215-217).
- **Evidence:** Variant strings verified in-source (`sm: "h-8..."`, `xs: "h-6..."`, `"icon-sm": "size-8"`, `"icon-xs": "size-6"`).
- **Suggested fix direction:** Raise sm/icon-sm to 36px and reserve xs for documented exceptions, or amend the spec with an explicit dense-control tier (relates to the pattern note on the improvised density scale).
- **Status:** open

### [MEDIUM] Focus-visible treatment missing on all non-shadcn interactive elements (pattern across shell screens)
- **Area:** ui-ux
- **Location:** `app-shell.tsx:34,41-54` (wordmark + NavLinks); `sites.tsx:226-231` (site-name Link), `:176-181` (checkbox); `bulk-import-dialog.tsx:137-144` (file input)
- **What's wrong:** Reskinned shadcn components carry a deliberate ink-based focus treatment; every hand-rolled interactive element — nav links, wordmark, table site-name links, native checkbox, file input — has hover styling at most and falls back to browser-default focus chrome, splitting the focus language into two systems mid-screen.
- **Evidence:** NavLink callbacks emit only text/hover classes; `<Link … className="text-ink hover:underline">`; checkbox `size-4 accent-white`; file input styles only the `file:` button. Verified in-source.
- **Suggested fix direction:** One shared ink-based focus-visible utility applied to links and native controls, matching Button's.
- **Status:** open

### [LOW] Off-scale spacing: 20px gaps as default form/nav rhythm, 40px margin on login
- **Area:** ui-ux
- **Location:** `app-shell.tsx:39`, `sites.tsx:152`, `bulk-import-dialog.tsx:108`, `login.tsx:68` (all `gap-5`); `login.tsx:52` (`mb-10`)
- **What's wrong:** `gap-5` = 20px and `mb-10` = 40px are off the 2/4/8/12/16/24/32/48 scale; four files use the 20px gap as their default rhythm — systematic, not a one-off.
- **Evidence:** Tailwind default spacing unchanged by the @theme block. Verified in-source.
- **Suggested fix direction:** Normalize to `gap-4`/`gap-6` and `mb-8`/`mb-12` (same class as the dashboard-scope spacing finding).
- **Status:** open

### [LOW] Small button sizes drop below the 8px button radius
- **Area:** ui-ux
- **Location:** `frontend/src/components/ui/button.tsx:33,37` (`xs`/`icon-xs` rounded-sm 6px); `dialog.tsx:73` (close button rounded-xs 4px)
- **What's wrong:** The radius vocabulary fixes buttons at 8px; 6px is reserved for code tabs/chips, 4px for inline tags in code wells.
- **Evidence:** Class strings verified; @theme maps rounded-sm → 6px, rounded-xs → 4px.
- **Suggested fix direction:** Keep all button sizes at `rounded-md` unless the spec adds a chip-tier exception.
- **Status:** open

### [LOW] Bulk-import results list container at 8px radius instead of the 12px container radius
- **Area:** ui-ux
- **Location:** `frontend/src/components/bulk-import-dialog.tsx:190`
- **What's wrong:** Bordered containers use 12px; 8px is the button/input radius. The scrollable results list is a bordered container at `rounded-md`.
- **Evidence:** `"max-h-72 divide-y divide-hairline overflow-y-auto rounded-md border border-hairline"`. Verified in-source.
- **Suggested fix direction:** `rounded-lg`.
- **Status:** open

### [LOW] Primary button hover reuses the pressed-state color — hover and active indistinguishable
- **Area:** ui-ux
- **Location:** `frontend/src/components/ui/button.tsx:21`
- **What's wrong:** The spec defines surface-light (#f1f7fe) as button-primary's *pressed* background only; the default variant applies it to both `hover:` and `active:`, so pressed has no distinct feedback beyond hover.
- **Evidence:** `default: "bg-primary text-primary-foreground active:bg-surface-light hover:bg-surface-light"`. Verified in-source.
- **Suggested fix direction:** Lighter intermediate (or no change) on hover; reserve surface-light for active.
- **Status:** open

### [LOW] Dialog entry/exit motion is the stock shadcn tw-animate zoom/fade recipe
- **Area:** ui-ux
- **Location:** `frontend/src/components/ui/dialog.tsx:40,64`
- **What's wrong:** Overlay and content keep shadcn's factory `animate-in/out fade-*-0 zoom-*-95` motion from tw-animate-css. Colors/borders/radius are fully tokenized; the motion is an unexamined library default rather than an intentional Wardress transition — the last default-shadcn remnant in these components.
- **Evidence:** Animation class strings match shadcn's factory dialog verbatim.
- **Suggested fix direction:** Ratify this motion explicitly or replace with a deliberate (likely fade-only) treatment.
- **Status:** open

### [LOW] Typography coverage gaps: no caption-emph utility; no 76px display clamp step
- **Area:** ui-ux
- **Location:** `frontend/src/index.css:104-228`
- **What's wrong:** (a) `{typography.caption-emph}` (14px/600/1.0) has no `@utility`, so any future emphatic caption will be improvised. (b) The collapsing strategy names the hero ladder 96 → 76 → 56 → 44, but media queries jump 96 → 56 at 767px with no 76px step (the doc's own breakpoint table only names the 56/44 clamps — internally ambiguous, noted rather than asserted).
- **Evidence:** Utilities exist for every other typography token but not caption-emph; only two display media queries (767px, 425px).
- **Suggested fix direction:** Add text-caption-emph; decide and document where the 76px step applies.
- **Status:** open

### [LOW] Nav status dot is hardcoded to "clean" — a semantic indicator that reflects nothing
- **Area:** ui-ux
- **Location:** `frontend/src/components/app-shell.tsx:59`
- **What's wrong:** `<StatusDot state="clean" />` renders an unconditional green dot beside the user email. It reads as live system/session health but is a literal — a green dot that can never turn orange or red is decoration, colliding with the "no decorative icons without semantic meaning" rule.
- **Evidence:** The `state` prop is a literal; no health/query data feeds it. Verified in-source.
- **Suggested fix direction:** Bind to real health state (e.g. the /api/health summary) or remove.
- **Status:** open

### [LOW] Checkbox accent color is #ffffff, not the ink token
- **Area:** ui-ux
- **Location:** `frontend/src/pages/sites.tsx:180`
- **What's wrong:** `accent-white` sets accent-color #fff; the system's white is ink #fcfdff. Trivial delta, but token discipline is "verbatim values" — and this checkbox plus site-detail's (filed separately) are the only unreskinned form controls found.
- **Evidence:** `className="size-4 accent-white"`. Verified in-source.
- **Suggested fix direction:** `accent-ink`, or fold into the shared reskinned-checkbox fix.
- **Status:** open

### [LOW] Sites empty state shows stale "Phase 1 — manual scans only" copy
- **Area:** ui-ux / docs
- **Location:** `frontend/src/pages/sites.tsx:279`
- **What's wrong:** The empty state still describes Phase 1 behavior while Phase 5 features (bulk import, RBAC) ship on the same screen — user-visible on first run of a fresh install.
- **Evidence:** Literal string at the cited line.
- **Suggested fix direction:** Rewrite the empty-state copy to current behavior (scheduled scans, bulk import).
- **Status:** open

### [VERIFIED CLEAN] Wave D design-fidelity: token foundation, shadcn reskin, shell screens (index.css, ui primitives, app-shell, login, sites, bulk-import)
- **Area:** ui-ux
- **Evidence:** Every hex/rgba in the @theme block matches DESIGN-resend verbatim (all four glow alphas, hairline 0.06/0.14, divider 0.04, on-light-mute, surface steps #0a0a0c/#101012/#06060a); true-black canvas via html/body + bg-canvas, no near-black; no shadow utility survives on button/card/dialog/input/badge/table (Sonner's library default is the sole exception, filed); radius remap correct (rounded-md=8px, rounded-lg=12px resolve to spec); Input matches the text-input spec exactly (h-10, 14/10px padding, surface-card, hairline-strong, focus→border-ink); Button primary/outline/secondary match component specs at h-9=36px with destructive as accent-red *text* on canvas (never solid accent fills); badge-pill spec exact; display utilities carry 96/76.8px, weight 400, lh 1.0, -1% tracking, opsz 144, ss01/liga per the substitution note, and body-md tracking -0.88px is the correctly computed compensation; nav-bar h-16 with single hairline bottom border on canvas at 1200px max; login's single accent-blue radial glow anchored top with ~600px falloff (one glow per section); threat-state badge mapping per §4 as washes + accent text; shadcn semantic variables fully remapped (ring→ink, no oklch defaults, no light-mode block); no emoji anywhere in frontend/src (Unicode-range grep); lucide icons at consistent size-4/default stroke; mobile touch targets 44px buttons / 48px inputs at ≤767px via min-height.
- **Status:** verified clean

### [HIGH] Health stat values use undefined type token `text-heading-lg` — render at browser default
- **Area:** ui-ux
- **Location:** `frontend/src/pages/health.tsx:65`
- **What's wrong:** The four headline stat values (uptime, queue depth, DB size, scans/24h) are classed `text-heading-lg`, but index.css defines only `text-heading-md` and `text-heading-sm`. The utility doesn't exist, so no size/weight/family rule applies and the page's most important numbers render at inherited 16px/400 — no token at all.
- **Evidence:** `<p className="mt-1 text-heading-lg text-ink">{value}</p>`; grep of index.css for `heading-lg` returns nothing. Verified in-source.
- **Suggested fix direction:** Replace with `text-heading-md`, or define the token deliberately if a larger stat size is wanted.
- **Status:** open

### [MEDIUM] Off-token border colors white/25 (focus) and white/40 (active) on hand-rolled selects and chip buttons
- **Area:** ui-ux
- **Location:** `settings.tsx:179,719,732,743,807`; `audit.tsx:129`; `users-card.tsx:84,205`; `remediation-hooks-panel.tsx:179`
- **What's wrong:** Every hand-rolled `<select>` uses `focus:border-white/25` and the channel-preset chips use `border-white/40` for active — neither alpha exists in the token set (hairline 6%, hairline-strong 14%, or ink; the text-input spec says focus thickens the border to ink). Same off-token white/40 already filed on the bulk-import toggles; this extends it across the settings surface.
- **Evidence:** `"...border-hairline-strong ... outline-none focus:border-white/25"` on selects; chip active branch `"border-white/40 text-ink"`. Verified in-source.
- **Suggested fix direction:** `focus-visible:border-ink` per the text-input spec; on-token active treatment for selected chips (`border-ink` or hairline-strong + surface-elevated).
- **Status:** open

### [MEDIUM] Hand-rolled selects deviate from the text-input spec (height, background) and from each other
- **Area:** ui-ux
- **Location:** `settings.tsx:175-184,803-815`; `audit.tsx:123-136`; `users-card.tsx:80-90` (h-8) and `:201-210` (h-9); `remediation-hooks-panel.tsx:175-186`
- **What's wrong:** text-input spec: surface-card background, 40px height, 10x14px padding. The six selects use `bg-surface-elevated` and `h-9` (36px); the users-list role select alone is `h-8` (32px) — a third control height on one page. All use `outline-none` + `focus:` instead of `focus-visible:`.
- **Evidence:** Shared recipe `h-9 rounded-md border border-hairline-strong bg-surface-elevated px-3`; users-card.tsx:84 `h-8 ... px-2`. Verified in-source.
- **Suggested fix direction:** One shared Select primitive on the text-input spec (surface-card, 40px desktop / min-h 48px mobile like `[data-slot="input"]`) used in all six places.
- **Status:** open

### [MEDIUM] Risk percentage rendered in solid accent-red on every row regardless of state — red not local/sparing
- **Area:** ui-ux
- **Location:** `frontend/src/pages/alerts.tsx:74`; `frontend/src/pages/remediation.tsx:113`
- **What's wrong:** §4 reserves red for confirmed-threat context, local and sparing. `<span className="text-code-md text-accent-red">{riskPct}</span>` is unconditional on all rows — including acknowledged alerts (whose dot is already downgraded to idle) and succeeded/dismissed executions. A 25-row list shows a column of red on rows whose own status vocabulary says resolved.
- **Evidence:** riskPct span unconditional in both row components while StatusDot/Badge on the same rows are state-conditional. Verified in-source.
- **Suggested fix direction:** Condition the red on unacknowledged/pending state; `text-charcoal`/`text-mute` on resolved rows.
- **Status:** open

### [LOW] Audit-log timestamps set in Geist Mono — mono used for non-code prose, inconsistent with sibling screens
- **Area:** ui-ux
- **Location:** `frontend/src/pages/audit.tsx:50-52`
- **What's wrong:** `toLocaleString()` timestamps wrapped in `text-code-md text-charcoal`; alerts, remediation, api-keys, and users render the same timestamp class in `text-caption` (Inter). Mono's lane is keys/URLs/hashes/JSON.
- **Evidence:** audit.tsx is the only in-scope file placing a locale timestamp in mono. Verified in-source.
- **Suggested fix direction:** `text-caption text-mute`/`text-charcoal` like the sibling screens (or tabular-nums Inter if column alignment was the goal).
- **Status:** open

### [LOW] Code-like hint strings (token/key/URL hints) not in mono while the API-key prefix is
- **Area:** ui-ux
- **Location:** `settings.tsx:344,464,851`; `remediation-hooks-panel.tsx:265`
- **What's wrong:** Token/key/URL fragments — the exact content class assigned to Geist Mono — render in Inter caption/body, while the directly comparable `key_prefix` in api-keys-card.tsx:188 correctly uses `text-code-md`. Same data class, two treatments on one page.
- **Evidence:** `<p className="text-caption text-mute">Token {s.token_hint}</p>` vs `<span className="text-code-md text-mute">{k.key_prefix}…</span>`. Verified in-source.
- **Suggested fix direction:** Wrap hint fragments in `text-code-md` to match the key-prefix treatment.
- **Status:** open

### [LOW] Inline code spans on admin screens lack the spec'd surface background
- **Area:** ui-ux
- **Location:** `settings.tsx:323,324,329,331,552`; `api-keys-card.tsx:93`
- **What's wrong:** Inline `/newbot`, `docker compose ...`, `/start`, and `Authorization: Bearer wk_...` spans are `text-code-md` with no background/padding — the same deviation already filed on the bulk-import dialog, extended here (spec: inline code gets a surface-card background).
- **Evidence:** `<span className="text-code-md text-body">docker compose --profile telegram up -d</span>` — no bg class. Verified in-source.
- **Suggested fix direction:** Shared InlineCode component (`rounded-xs bg-surface-card px-1`), one fix for all occurrences incl. the bulk-import one.
- **Status:** open

### [LOW] Inline wells use 8px radius + soft hairline instead of the 12px/hairline-strong well spec
- **Area:** ui-ux
- **Location:** `settings.tsx:337` (Telegram status well); `audit.tsx:36` (Before/After JSON pre); `api-keys-card.tsx:148` (revealed-key block)
- **What's wrong:** Wells are spec'd rounded-lg (12px) with hairline-strong; code wells sit on surface-deep. These three hand-built wells use `rounded-md` (button radius) + `border-hairline` (divider tint) on surface-elevated.
- **Evidence:** `<pre className="overflow-x-auto rounded-md border border-hairline bg-surface-elevated p-3 text-code-md text-body">` and same recipe on the other two. Verified in-source.
- **Suggested fix direction:** `rounded-lg border-hairline-strong`; JSON/key code wells to `bg-surface-deep` per the code-window spec.
- **Status:** open

### [LOW] New off-scale spacing kind: 6px (`space-y-1.5`, `py-1.5`) as the standard form-stack gap
- **Area:** ui-ux
- **Location:** `settings.tsx` — 11 `space-y-1.5` occurrences (153-235,349,488,532) + `py-1.5` on chips (717,730,741); also the bulk-import toggles (`py-1.5`)
- **What's wrong:** 6px is not on the spacing scale and is distinct from the already-filed 20/14/40px pattern. It is the label-to-input gap in every SMTP/Telegram/AI form group and the chip vertical padding.
- **Evidence:** `grep -c "space-y-1.5"` on settings.tsx → 11. Verified in-source.
- **Suggested fix direction:** `space-y-2` (8px) for label gaps — matching the dialogs which already use gap-2 — and `py-1`/`py-2` on chips.
- **Status:** open

### [LOW] Badge component used as inline prose decoration rather than a status pill
- **Area:** ui-ux
- **Location:** `remediation-hooks-panel.tsx:310-312`; `settings.tsx:932-934`
- **What's wrong:** `<Badge variant="secondary">Remediation</Badge>` sits mid-sentence as a page-name reference, and `<Badge>Fernet / AES-128-CBC + HMAC</Badge>` decorates a card description — the badge-pill spec is a status/tag chip, and everywhere else in the app badges carry state. The crypto string is also code-like content that belongs in mono.
- **Evidence:** Both badges embedded inside running text with `align-middle`. Verified in-source.
- **Suggested fix direction:** Plain link/emphasis for the page reference; `text-code-md` span for the algorithm string.
- **Status:** open

### [VERIFIED CLEAN] Wave D design-fidelity: admin/ops screens (settings, alerts, audit, health, remediation, users/api-keys/hooks cards)
- **Area:** ui-ux
- **Evidence:** Zero shadow utilities across all eight files; no emoji (typographic `·`/`—`/`…` separators only); one-white-surface rule holds — all on-page card actions are outline/ghost and the only white primary buttons live inside dialogs (at most one visible per viewport); threat-state mapping fully consistent (sent/ok/succeeded/active→clean, failed/down→threat, degraded/queued/pending→pending, skipped/revoked/deactivated/acknowledged→idle) mirrored across dots and badges; icons all semantic lucide at size-4; no Fraunces misuse — every h1 is the text-display-lg utility; no 600+ weight bumps anywhere; list containers rounded-lg, interactive elements rounded-md; alerts/audit/remediation empty states are designed placeholder blocks consistent across the three list pages; loading/error lines all token-colored.
- **Status:** verified clean

### [HIGH] Native select elements have sub-44px touch targets on mobile
- **Area:** ui-ux
- **Location:** `pages/settings.tsx:175`; `pages/audit.tsx:123`; `components/remediation-hooks-panel.tsx:175`; `components/users-card.tsx:80`
- **What's wrong:** Native `<select>` elements use `h-9` (36px desktop) with no `data-slot` attribute, so index.css mobile min-height rule (line 215-217: `[data-slot="input"]` → 48px at ≤767px) doesn't apply. Spec requires 44px minimum touch target on mobile.
- **Evidence:** settings.tsx:175 `className="h-9 w-full rounded-md border..."` — no `data-slot`, no mobile breakpoint override; index.css:215 only targets `[data-slot="input"]`. Verified in-source.
- **Suggested fix direction:** Add `data-slot="select"` to all native selects and extend index.css mobile rule to cover `[data-slot="select"]` with min-height 48px at ≤767px.
- **Status:** open

### [HIGH] Native checkbox inputs have sub-44px touch targets on mobile
- **Area:** ui-ux
- **Location:** `pages/site-detail.tsx:183-190`; `pages/alerts.tsx:144`; `pages/remediation.tsx:183`
- **What's wrong:** Native checkbox `<input type="checkbox">` elements use `size-4` (16px) with no touch-area expansion at mobile widths. Spec requires 44px minimum.
- **Evidence:** site-detail.tsx:185 `<input type="checkbox" ... className="size-4 accent-ink" />` — no padding wrapper, no breakpoint increase. Verified in-source.
- **Suggested fix direction:** Wrap checkboxes in a tap-area wrapper (`min-w-11 min-h-11 flex items-center justify-center` at ≤767px) or replace with a Checkbox component implementing mobile touch-target expansion.
- **Status:** open

### [HIGH] Incident timeline chart dots are 3-4.5px radius with no touch-area expansion
- **Area:** ui-ux
- **Location:** `frontend/src/components/incident-timeline.tsx:157-164`
- **What's wrong:** Chart dots render at `r={payload.verdict === "flagged" ? 4.5 : 3}` (9px/6px diameter) with `onClick` handler but no invisible touch-area overlay. At mobile this falls well below 44px tap target.
- **Evidence:** Line 159 `r={... ? 4.5 : 3}`; line 164 `onClick={() => onPointClick?.(payload.id)}` with cursor pointer but no expanded hit area. Verified in-source.
- **Suggested fix direction:** Wrap each dot in an invisible `<circle>` with `r={22}` (44px diameter) at ≤767px, or use Recharts' `activeDot` with a larger mobile `r` and pointer-events handling.
- **Status:** open

### [HIGH] Visual diff slider handle is 8px wide with no mobile expansion
- **Area:** ui-ux
- **Location:** `frontend/src/components/visual-diff-slider.tsx:300-313`
- **What's wrong:** Slider handle div has `className="...w-4"` (16px tap area) with an inner visible pill at `h-8 w-2` (8px). No mobile breakpoint increases this. Spec requires 44px minimum.
- **Evidence:** Line 300 `w-4` = 16px; inner pill line 313 `w-2` = 8px; no `sm:`/`md:` width increase. Verified in-source.
- **Suggested fix direction:** Increase handle wrapper to `w-11` (44px) at ≤767px via `md:w-4 w-11` or similar responsive class.
- **Status:** open

### [HIGH] Settings page flex rows with min-w-64 inputs may overflow at 375px mobile width
- **Area:** ui-ux
- **Location:** `pages/settings.tsx:152-153,186,212,349,488,532`
- **What's wrong:** Grid layouts use `grid-cols-1 sm:grid-cols-2` or `sm:grid-cols-3`, collapsing to 1-up below 640px, but flex rows with `min-w-64` (256px) inputs don't wrap until the min-width forces it. At 375px viewport, a 256px input + button + gaps may overflow or crush adjacent content.
- **Evidence:** Line 349 `<div className="min-w-64 flex-1 space-y-1.5">` inside a `flex items-end gap-2` row — no `flex-wrap` or `flex-col` breakpoint.
- **Suggested fix direction:** Add `flex-wrap` or change flex rows to `flex-col sm:flex-row` to stack input + button vertically at mobile widths.
- **Status:** open

### [MEDIUM] App shell user email truncates without breakpoint handling
- **Area:** ui-ux
- **Location:** `frontend/src/components/app-shell.tsx:58-63`
- **What's wrong:** User email renders in a `<span className="flex items-center gap-2 text-caption text-charcoal">` with no `truncate`, `max-w` constraint, or hiding. Long emails (e.g., `analyst@subdomain.example.com`) will overflow the nav bar at ≤768px.
- **Evidence:** Lines 58-63 show no `truncate`, `max-w`, or `hidden sm:inline`. Verified in-source.
- **Suggested fix direction:** Add `truncate max-w-32 sm:max-w-none` to the email span or hide the email entirely below a breakpoint (`hidden md:flex`).
- **Status:** open

### [MEDIUM] Table horizontal scroll wrapper has no touch-friendly scroll hint
- **Area:** ui-ux
- **Location:** `frontend/src/components/ui/table.tsx:14`
- **What's wrong:** Table container uses `overflow-x-auto` but provides no visual hint that content is scrollable at mobile widths, and no `touch-action` optimization.
- **Evidence:** Line 14 `className="relative w-full overflow-x-auto"` — no fade gradient, shadow, or `touch-action: pan-x`. Verified in-source.
- **Suggested fix direction:** Add `touch-action: pan-x` via inline style or Tailwind class, and consider a subtle fade-out gradient on the right edge at mobile to signal scrollability.
- **Status:** open

### [MEDIUM] Dialog content max-width uses calc with fixed 2rem margin, may be tight at 375px
- **Area:** ui-ux
- **Location:** `frontend/src/components/ui/dialog.tsx:64`
- **What's wrong:** Dialog content has `max-w-[calc(100%-2rem)]` (32px total margin) leaving 343px for content at 375px viewport. With 24px internal padding (p-6), usable width is ~295px — tighter than typical mobile design (320px min).
- **Evidence:** Line 64 `max-w-[calc(100%-2rem)]` and `p-6`. Verified in-source.
- **Suggested fix direction:** Reduce internal padding to `p-4` at ≤767px or use `max-w-[calc(100%-1rem)]` for more breathing room.
- **Status:** open

### [MEDIUM] Long mono strings in audit log evidence lack break-all or max-width constraint
- **Area:** ui-ux
- **Location:** `pages/audit.tsx:36`
- **What's wrong:** Audit log evidence uses `<pre className="overflow-x-auto...">` (line 36) without `max-w` constraint inside a table cell, which can push table cells wider than viewport at mobile.
- **Evidence:** Line 36 `overflow-x-auto rounded-md border border-hairline bg-surface-elevated p-3 text-code-md text-body` inside a table cell with no max-width. Verified in-source.
- **Suggested fix direction:** Add `max-w-[80vw] sm:max-w-none` to audit log evidence cells or wrap long values with `break-all` at mobile widths.
- **Status:** open

### [MEDIUM] Suppression panel screenshot container has no aspect-ratio preservation check
- **Area:** ui-ux
- **Location:** `frontend/src/components/suppression-panel.tsx:90`
- **What's wrong:** Container is `max-h-[420px] overflow-y-auto` with `cursor-crosshair` — tall portrait screenshots will be clipped vertically, and the drawn bbox fractions assume the image stays full-size, but small viewports may force the image narrower, breaking the aspect-ratio assumption the bbox rendering depends on.
- **Evidence:** Line 90 `max-h-[420px]` with no aspect-ratio CSS; line 118 `<img ... className="block w-full" />` — `w-full` scales width but height follows aspect, which can exceed 420px.
- **Suggested fix direction:** Add explicit aspect-ratio handling or clamp image: `className="block max-w-full max-h-[420px] object-contain"`.
- **Status:** open

### [MEDIUM] Visual diff slider has no mobile aspect-ratio constraint for wide screenshots
- **Area:** ui-ux
- **Location:** `frontend/src/components/visual-diff-slider.tsx:235-250`
- **What's wrong:** Images render `block w-full` with no max-width or aspect constraint — ultra-wide screenshots (e.g., 3840×1080) will render at full 375px mobile width with ~98px height, making altered regions nearly invisible.
- **Evidence:** Line 235 `<img src={current.url} alt="Current capture" className="block w-full" />` — no `max-w` or `aspect-ratio` CSS.
- **Suggested fix direction:** Add `max-w-2xl mx-auto` to center and constrain slider at mobile, or add min-height to prevent ultra-wide images from collapsing vertically.
- **Status:** open

### [MEDIUM] Bulk import dialog preview list has no count indicator at mobile
- **Area:** ui-ux
- **Location:** `frontend/src/components/bulk-import-dialog.tsx:190`
- **What's wrong:** Preview list uses `max-h-72 overflow-y-auto` with no "showing N of M" indicator — at mobile, users may not realize the list scrolls if they upload 50+ URLs.
- **Evidence:** Line 190 `<ul className="max-h-72 divide-y divide-hairline overflow-y-auto rounded-md border border-hairline">` with no count displayed above the list.
- **Suggested fix direction:** Add a count line above the list ("Showing {Math.min(results.length, 20)} of {results.length} results") or reduce max-height at mobile to make scroll boundary more obvious.
- **Status:** open

### [LOW] Finding-card grids use sm:grid-cols-4 at 640px — breakpoint misalignment with spec's Mobile Large boundary
- **Area:** ui-ux
- **Location:** `frontend/src/components/finding-card.tsx:152,249,443`
- **What's wrong:** Grids switch from 2-up to 4-up at `sm:` (640px) — at 640-767px viewport, four 14px labels with 24px gaps may wrap unevenly. Spec defines "Mobile Large 426-767"; the 640px trigger sits mid-range.
- **Evidence:** Line 152 `grid-cols-2 gap-x-6 sm:grid-cols-4` — breakpoint is Tailwind `sm:` (640px) not the spec's "Tablet 768-1023".
- **Suggested fix direction:** Adjust to `grid-cols-2 md:grid-cols-3 lg:grid-cols-4` to match the spec's breakpoint ladder more precisely.
- **Status:** open

### [LOW] Scan detail page grid uses xl:grid-cols-2 at 1280px instead of spec's XL boundary (1440px)
- **Area:** ui-ux
- **Location:** `pages/scan-detail.tsx:254`
- **What's wrong:** Grid is `grid-cols-1 gap-6 xl:grid-cols-2` — Tailwind `xl:` = 1280px, but spec defines "Desktop XL ≥ 1440px". Code-story splits should stay stacked until 1440px per DESIGN-resend.md.
- **Evidence:** Line 254 `xl:grid-cols-2` triggers at 1280px. Verified in-source.
- **Suggested fix direction:** Add custom breakpoint for 1440px in Tailwind config or use a min-width media query wrapper.
- **Status:** open

### [LOW] Login page atmospheric glow has pointer-events-none but no explicit z-index
- **Area:** ui-ux
- **Location:** `pages/login.tsx:44-50`
- **What's wrong:** Glow div is `pointer-events-none absolute` — correct for a decorative gradient, but the `absolute` positioning with no explicit z-index may stack above the form if future changes add content.
- **Evidence:** Line 44 `className="pointer-events-none absolute inset-x-0 top-0 h-[600px]"`.
- **Suggested fix direction:** Add explicit `z-[-1]` or `z-0` to ensure glow stays behind interactive content.
- **Status:** open

### [LOW] DOM diff tree node text uses truncate without tooltip fallback for long values
- **Area:** ui-ux
- **Location:** `frontend/src/components/dom-diff-tree.tsx:170-171`
- **What's wrong:** Node attrs and text are `truncate` with no title attribute or tooltip — users can't see full long values at mobile widths.
- **Evidence:** Line 170 `<span className="truncate text-mute">{node.attrs}</span>` with no title prop.
- **Suggested fix direction:** Add `title={node.attrs}` and `title={node.text}` to show full value on hover/long-press.
- **Status:** open

### [VERIFIED CLEAN] Wave D design-fidelity: responsive behavior across all pages
- **Area:** ui-ux
- **Evidence:** All multi-column grids collapse to 1-up at mobile (sites/site-detail/scan-detail/settings/health cards all use `grid-cols-1` as base with responsive prefixes); tables in overflow-x wrappers (ui/table.tsx:14 `overflow-x-auto` handles all table-heavy pages); dialogs responsive (max-w calc at line 64 reduces from 560px to viewport-minus-2rem); login single-column card (max-w-sm) stacks vertically at all widths; app shell max-w 1200px constraint at lines 33/73 (nav collapse issue notwithstanding).
- **Status:** verified clean

### [VERIFIED CLEAN] Wave D design-fidelity: generated artifacts (PDF, email, markdown, Telegram) — structure, tokens, no-emoji rule
- **Area:** ui-ux / docs
- **Evidence:** **PDF report** (backend/app/templates/report/report.html) — cover page with true-black #000000 (line 54), serif headline Georgia fallback (line 64-66), hairline borders rgba(255,255,255,0.14) (line 75), executive summary (line 169), per-layer findings (lines 208-229), timeline chart (lines 204-205), CSS Paged Media running headers/page counters (lines 14-32), no emoji detected; **Email templates** (alert.html, test.html) — inline CSS premailer-ready (lines 7-58 alert.html), dark canvas #000000 (line 11), card surface #0a0a0c (line 14), hairline rgba 0.14 (line 15), white CTA #fcfdff on #000000 (line 49), no CSS variables/radial-gradients/custom fonts, table-based layout, no emoji; **Markdown export** (backend/app/reporting.py:126-177) — H1/H2/H3 hierarchy, pipe tables (lines 153-158), evidence capping at 300 chars (line 33), neutral language ("Wardress incident report", "Executive summary", "Per-layer findings"), no emoji; **Telegram bot** (backend/worker/telegram_bot.py) — plain-text verdict marks (lines 54-59: OK/CHANGED/FLAGGED/ERROR, no emoji symbols), help text (lines 171-179), status/sites/scan/ack/mute/explain messages all neutral phrasing, no markdown-parse hazards, no emoji (scan clean, line 110 comment "no emoji (product rule)").
- **Status:** verified clean

### [MEDIUM] install.ps1 does not force-recreate a running telegram-bot after an image rebuild — leaves it on stale code
- **Area:** infra
- **Location:** `scripts/install.ps1:227` vs `scripts/update.ps1:136-148`
- **What's wrong:** install.ps1 advertises "safe to re-run at any time" but its final restart is `up -d --no-build app worker beat` — it never force-recreates the telegram-bot. update.ps1 explicitly force-recreates the bot (and documents why: the bot shares the worker image, and `docker compose up -d` does not recreate a running container whose own config is unchanged, so after a rebuild it silently keeps the OLD code). Re-running install.ps1 after a code change, with the bot running, leaves the bot on stale code — the exact failure update.ps1 guards against. Same reasoning that makes beat's force-recreate necessary applies to the bot.
- **Evidence:** install.ps1:227 `Invoke-Compose @("up","-d","--no-build","app","worker","beat")` — bot absent; update.ps1:139-148 force-recreates telegram-bot when running. Confirmed live this session: after `install.ps1`, `docker compose ps` showed the bot "Up 2 minutes" while app/worker/beat were "Up About a minute" (bot not recreated).
- **Suggested fix direction:** Mirror update.ps1's conditional bot force-recreate in install.ps1, or document that install.ps1 is first-run-oriented and update.ps1 is the re-run path.
- **Status:** open

### [MEDIUM] Containers run as root — no USER directive in either Dockerfile
- **Area:** infra
- **Location:** `backend/Dockerfile.app`, `backend/Dockerfile.worker`
- **What's wrong:** Neither image sets a non-root `USER`, so app, worker, beat, and telegram-bot all run as root inside their containers. A code-execution bug (e.g. via the Playwright-rendered untrusted page content the worker handles, or a deserialization flaw) executes as root in-container. Defense-in-depth gap; the containers are single-host and not privileged, but least-privilege is a standard hardening baseline for a service that fetches and renders untrusted remote content.
- **Evidence:** Read both Dockerfiles end-to-end — no `USER` line; final `CMD` runs as the base image's default (root for both python:3.12-slim and the Playwright image).
- **Suggested fix direction:** Add a non-root user in each image and `USER` before `CMD`; ensure the artifacts volume mount and MiniLM cache remain writable by that UID.
- **Status:** open

### [LOW] ollama image pinned to `:latest` — violates the project's version-pinning rule
- **Area:** infra
- **Location:** `docker-compose.yml:143`
- **What's wrong:** `image: ollama/ollama:latest` — Master Prompt Rule 2 requires pinned, verified versions everywhere; every other image is pinned (postgres:16, redis:8-alpine, the Playwright and uv images by tag+digest). `:latest` means an `ollama` profile start can silently pull a breaking change.
- **Evidence:** compose:143 `image: ollama/ollama:latest`; contrast db/redis/app/worker pins. Verified in-source.
- **Suggested fix direction:** Pin ollama to a specific tag (optional feature, so low urgency, but the rule is absolute).
- **Status:** open

### [LOW] worker, beat, and telegram-bot services have no healthcheck
- **Area:** infra
- **Location:** `docker-compose.yml:77-138`
- **What's wrong:** Only db, redis, and app define healthchecks. worker/beat/telegram-bot have none, so `docker compose ps` cannot report their health and nothing can gate on their readiness. Not a correctness bug today (no service `depends_on` them by health), but a wedged worker/beat surfaces only via logs or the app's /health/details probes, not via compose status.
- **Evidence:** compose blocks for worker (77-101), beat (103-116), telegram-bot (121-138) — no `healthcheck:` key. Verified in-source.
- **Suggested fix direction:** Add lightweight healthchecks (e.g. `celery inspect ping` for worker; a heartbeat-file check for beat), or document their liveness as intentionally observed via /api/health/details.
- **Status:** open

### [LOW] WARDRESS_ENV is defined in .env.example but read nowhere in the app
- **Area:** infra / docs
- **Location:** `.env.example:10`
- **What's wrong:** `WARDRESS_ENV=production` is set in .env.example but no application code reads it (grep of `backend/app` for `WARDRESS_ENV`/`wardress_env` returns nothing), and it isn't passed through in docker-compose.yml either — a dead knob that implies an environment-mode switch that doesn't exist.
- **Evidence:** `.env.example:10`; `grep -rn "WARDRESS_ENV" backend/app --include=*.py` → no matches. Verified in-source.
- **Suggested fix direction:** Wire it (e.g. gate `/docs` exposure or logging verbosity on it) or remove it from .env.example.
- **Status:** open

### [LOW] WeasyPrint native libraries baked into the worker image but PDFs render in the API process
- **Area:** infra
- **Location:** `backend/Dockerfile.worker:15-23`
- **What's wrong:** The worker Dockerfile installs Pango/Cairo/GDK-PixBuf "for PDF report rendering (Phase 4)", but per PROGRESS.md and reports-router design, WeasyPrint renders in the API (app) process, not the worker. If no worker/beat task generates PDFs, these native libs are dead weight in the worker/beat image (which is already the largest). Needs confirmation that no Celery task path calls WeasyPrint.
- **Evidence:** Dockerfile.worker:16-23 installs the WeasyPrint libs with that comment; Dockerfile.app:44-52 also installs them (correct — reports render there). Verified both in-source.
- **Suggested fix direction:** Confirm whether any worker task renders PDFs; if not, drop the WeasyPrint libs from Dockerfile.worker and update the comment.
- **Status:** needs-user-decision

### [LOW] install/update .env parser captures trailing CR on a CRLF-edited .env
- **Area:** infra
- **Location:** `scripts/install.ps1:194-198`, `scripts/update.ps1:155-157`
- **What's wrong:** The port/email/value extraction uses `^([A-Za-z_][A-Za-z0-9_]*)=(.*)$` and `Get-Content` line-by-line. The installer writes .env as LF, but a user who edits .env in a CRLF editor leaves `\r` at line end; `(.*)` then captures a trailing carriage return into the value (e.g. `WARDRESS_HTTP_PORT` → `8321\r`), producing a malformed dashboard URL in the summary/health-wait. Cosmetic-to-functional depending on the value.
- **Evidence:** update.ps1:156 `if ($line -match "^WARDRESS_HTTP_PORT=(.+)$") { $port = $Matches[1].Trim() }` — this one Trims; install.ps1:195 `$envMap[$Matches[1]] = $Matches[2]` does not Trim. Verified in-source.
- **Suggested fix direction:** `.Trim()` the captured value in install.ps1's envMap population (update.ps1 already trims the port).
- **Status:** open

### [MEDIUM] README's nine-layer table misnumbers the engine, invents a layer, and omits cloaking
- **Area:** docs
- **Location:** `README.md:27-37` vs `backend/worker/detection/*.py`
- **What's wrong:** The user-facing detection table does not match the implemented layers. Actual code (verified by function names): L1 hash, L2 DOM structure, L3 link/script audit, L4 visual diff, L5 signatures/defacement vocabulary, L6 security metadata (TLS/headers/robots), **L7 cloaking (UA-rotation divergence)**, L8 semantics (MiniLM), L9 fusion. The README table renumbers these (its "3. Visual diff" is code L4, "4. Text semantics" is code L8, "6. Resource integrity" is code L3, "7. Metadata" is code L6), invents **"8. Error/parked heuristics"** — no such discrete layer exists — and entirely omits the real **layer 7, cloaking**. A reader cannot map the table to the drilldown UI, reports, or evidence, all of which use the real layer numbers.
- **Evidence:** README.md:29-37 table; `grep "def layer" backend/worker/detection/*.py` → layer2_dom_structure, layer3_link_audit, layer4_visual_diff, layer5_signatures, layer6_security_metadata, layer7_cloaking, layer8_semantics, layer9_fusion (plus layer1 hash in the pipeline). No "error/parked" function exists. Verified in-source.
- **Suggested fix direction:** Rewrite the table to the nine real layers in code order, including cloaking, and drop the invented error/parked row (error-page handling is a baseline-refusal behavior, not a scored layer).
- **Status:** open

### [VERIFIED CLEAN] README "383 tests" count is accurate (Wave F resolved the Wave E flag)
- **Area:** docs / test-coverage
- **Evidence:** Wave E flagged the "# 383 tests" annotation (README.md:212) as possibly stale (only 359 `def test_` definitions). Wave F settled it authoritatively in the dev env: `uv run pytest --collect-only -q` → **383 tests collected**, and `uv run pytest -q` → **383 passed** in 70s (the 359 defs plus parametrized expansion reach exactly 383). README count is correct; no fix needed.
- **Status:** verified clean

### [VERIFIED CLEAN] Installer/updater live behavior, compose secret-guards, config-vs-docs consistency
- **Area:** infra / docs
- **Evidence:** **Live runs this session** — `update.ps1` completed the full flow (git ff-only "Already up to date", base-image pull, serial rebuild of app/worker/beat from cache, `alembic upgrade head` with no pending migrations, restart with beat + telegram-bot force-recreated, dashboard healthy inside 120s, data/.env preserved); `install.ps1` run twice against the existing .env left it **byte-identical** (`cmp` clean), admin seed idempotent ("already exists"), shortcut created, all six services healthy, `/api/health/live` → `{"status":"ok"}`. **Prerequisites (governing-audit ask):** README's host requirements are accurate — only Docker Desktop (and git, for update.ps1's optional guarded pull) are needed on the Windows host; Python/uv/Node/pnpm exist only inside the Docker build stages (app image builds the frontend in a node stage and backend deps via uv; worker via uv), never on the host — the Development-section tooling is for contributors only; the ~6GB figure is defensible (Playwright worker image + torch-cpu + baked MiniLM dominate). **Consistency:** `gemini-flash-latest` is the model string in config.py:59, llm.py:35, schemas.py:420, settings.py, .env.example:36, and both compose blocks — zero `gemini-2.5-flash` in product code (only in .venv vendor test fixtures); JWT_SECRET and CREDENTIALS_ENCRYPTION_KEY ≥32-byte validation enforced at startup (config.py:28-38, matches README); admin password ≥12 chars (seed_admin.py:22 MIN_PASSWORD_LENGTH=12, matches README); bulk-import 500-row cap (schemas.py:586 BULK_IMPORT_MAX_ROWS=500, matches README "up to 500"); lint is oxlint not eslint (package.json, matches README dev command); rate-limit defaults 300/240/60 match .env.example and the compose fallbacks; the README .env config table's vars and defaults match .env.example; New-RandomSecret rejection sampling is correct (limit=248=floor(256/62)*62, uniform over the 62-char alphabet); the CHANGE_ME survival guard and DATABASE_URL password-sync are sound; `docker compose down -v` removes all four named volumes (db-data/redis-data/scan-artifacts/ollama-data, all declared in compose).
- **Status:** verified clean

### [LOW] Missing indexes confirmed (Wave B flag re-verified in Wave F)
- **Area:** performance
- **Location:** `backend/app/models.py:322` (alerts.created_at), `:570` (remediation_executions.scan_id), `:427` (scans.finished_at)
- **What's wrong:** Wave F re-verified the three indexes Wave B flagged against the current model: `alerts.created_at` has no `index=True` yet it is the alerts-feed sort key (paginated `ORDER BY created_at DESC`); `remediation_executions.scan_id` carries the FK but only a composite `(hook_id, scan_id)` unique index — which does not serve scan-side lookups or the FK cascade; `scans.finished_at` is unindexed but is used in a `max()` on the health page. All three tables are small today, so the impact is latent, not current.
- **Evidence:** Confirmed in-source: models.py:570 `scan_id: ... ForeignKey(...)` with no `index=True`, only the composite at :590; alerts `created_at` at :322 has no index; scans `finished_at` at :427 has no index. Contrast the many `index=True` columns elsewhere.
- **Suggested fix direction:** Add the three indexes in one Alembic migration (cheap now while tables are small); this is the concrete action behind the earlier Wave B "add when data grows" note.
- **Status:** open

### [LOW] apprise pulls a Python-3.13-incompatible import (`imghdr`) — latent, not live on 3.12
- **Area:** backend / performance
- **Location:** `apprise/utils/pgp.py:48` (third-party); surfaced by `backend/tests/test_phase4_api.py::test_channel_crud_and_redaction`
- **What's wrong:** The test suite emits one DeprecationWarning: apprise imports the stdlib `imghdr` module, which is removed in Python 3.13. Wardress runs Python 3.12.13 in-container (verified live), so this is latent — but a future base-image bump to 3.13 would break apprise's import at that path, and apprise is the alerting spine (email/Telegram/100+ services). Not our code; a dependency-forward-compat flag.
- **Evidence:** `uv run pytest` warnings summary → `apprise/utils/pgp.py:48: DeprecationWarning: 'imghdr' is deprecated and slated for removal in Python 3.13`; `docker compose exec app python --version` → Python 3.12.13.
- **Suggested fix direction:** Pin/track apprise for a 3.13-compatible release before any Python 3.13 base-image upgrade; keep the base image on 3.12 until apprise drops `imghdr`. Note it in the maintenance checklist.
- **Status:** open

### [VERIFIED CLEAN] Cross-cutting: dependency audits, dead code, blocking-I/O, lint/type, full suite
- **Area:** performance / test-coverage
- **Evidence:** Fresh this session — `pip-audit` (via uv): **no known vulnerabilities** (torch+cpu and the local `wardress-backend` package skipped as not-on-PyPI, expected); `pnpm audit --prod`: **no known vulnerabilities**. Dead code: `ruff check --select F401,F811,F841` on app + worker → **all checks passed** (no unused imports, redefinitions, or unused locals). Blocking-I/O-in-async heuristic (`time.sleep`/`requests`/`urllib`/`.read()` in async paths, excluding tests) → **no matches** (the codebase uses httpx-async, `asyncio.to_thread` for CPU-bound detection, and broker-only Celery dispatch, consistent with the Wave B verified-clean entries). Frontend `tsc --noEmit` → clean (exit 0); `oxlint src` → 5 `only-export-components` fast-refresh warnings only (the standing accepted shadcn-layout class, no errors). Backend suite: **383 passed** in 70s; frontend suite count 26 (`it`/`test`). No new N+1 patterns found beyond the indexes above; the per-scan hot paths (findings upsert, layer gating) were already traced clean in Wave B.
- **Status:** verified clean

## File inventory changes

- **Files deleted this pass:** none from the tracked tree. Two untracked temporary
  files created during this pass's own live verification (`report-test.pdf`,
  `report-test.md`) were removed after inspection.
- **Orphan check result:** all 188 tracked files cross-referenced against every
  tracked text file's content; the 18 files whose names appear nowhere are all
  self-justifying (`.gitignore`/`.dockerignore`/`.gitattributes`, `.gitkeep`
  placeholders required by the §12 skeleton, brand PNG exports referenced by the
  install script's shortcut logic via the `.ico`, README screenshots referenced by
  relative links, `tsconfig.json`/`components.json` consumed by tooling). **Zero
  orphaned files; nothing deleted, nothing flagged for a decision.**

## UI/UX audit notes

Pattern-level design-review observations from Wave D (set-level consistency, not single-line bugs):

1. **Two competing added/removed color conventions coexist on the scan-detail page.** The DOM
   diff tree follows the §4 addendum's diff semantics (added = green, removed = red), but the
   layer-2 evidence badges directly below it color "Tags added" as threat-red and "Tags removed"
   as neutral, and the link-audit list marks added URLs with red dots (new content = suspicious);
   security headers and robots.txt flip back to diff semantics (added = green). Each choice is
   locally defensible, but "added" means green in one panel and red in the adjacent one. Needs a
   deliberate ruling (e.g. structural/content additions = threat-toned, hardening additions =
   green) and possibly a legend note on the DOM tree.
2. **Card padding register runs at 24px set-wide, not the 32px feature-card spec.** The shared
   `Card` primitive uses `px-6/py-6` (24px) and hand-built cards follow (`p-6` on ExplainCard),
   while others use `p-8` (32px placeholders) — 20/24/32px card interiors mixed on one screen
   across scan-detail and site-detail. Root cause is `ui/card.tsx`; a single ruling (24 or 32)
   should be applied everywhere.
3. **Hover-wash opacities drift:** `hover:bg-surface-elevated/40` (finding-card header) vs `/60`
   (DOM tree rows, table rows) — same interaction, two strengths; pick one.
4. **Expander chevrons differ in size on the same screen:** `size-4` in finding cards vs `size-3`
   in the DOM tree — same semantic control twice on scan-detail.
5. **"Error" states borrow the orange pending wash everywhere** (badge and dot both map error →
   pending styling). Consistent, but it overloads "investigating" semantics with "scan failed"
   semantics — the §4 addendum defines no failure color, so this is a spec gap to ratify rather
   than a bug.
6. **Minor token override:** ExplainCard applies `leading-relaxed` (1.625) over `text-body-md`'s
   token line-height 1.5 (scan-detail.tsx:134) — the only typography-token line-height override
   found in the dashboard scope.

Pattern-level observations from the foundation/shell scope:

7. **Two focus-treatment systems coexist** (also filed as a Medium finding): reskinned shadcn
   components carry a deliberate ink-based focus language; every hand-rolled interactive element
   falls back to browser defaults — keyboard traversal visually switches design systems
   mid-screen. The single biggest set-level inconsistency found in Wave D.
8. **One-white-surface rule under dialogs was never consciously applied.** Opening Add-site or
   Bulk-import puts the dialog's primary button on screen while the page's primary trigger
   remains visible beneath the 70%-black overlay. Arguably suppressed by the overlay, but the
   spec's escape hatch ("drop one to ghost") was never invoked — worth a ruling, since every
   page-with-dialog inherits the pattern.
9. **Mono type doubles as data typography without a named convention.** `text-code-md` styles
   URLs (sites table) and row numbers (bulk-import results) without the code-surface treatment
   the spec ties to code rendering. Either name a `text-data-mono` convention or apply the
   surface — as-is, the code-window rule is ambiguous at every call site.
10. **A parallel density scale has grown inside button.tsx.** The spec knows one button height
    (36px desktop); the implementation has five heights and four radii across sizes. Individual
    deviations are filed, but the root cause is that the dense-UI tier the dashboard genuinely
    needs was never added to the design doc, so each component improvises it.

Pattern-level observations from the admin/ops scope:

11. **The admin/ops set reads as one system** — shared grammar of display-lg h1 + body-md
    charcoal subtitle, rounded-lg surface-card list container, StatusDot + Badge row anatomy,
    ghost-icon pagination. The deviations cluster at the "hand-rolled control" layer (selects,
    chips, checkboxes, inline wells): the efficient fix is a small set of shared primitives
    (Select, InlineCode, Well, Checkbox) rather than per-file patches.
12. **An undocumented micro-label style** — `text-caption uppercase tracking-wide text-mute` —
    is used consistently as an eyebrow/dt style (audit.tsx:35; health.tsx:64,187,193,199). Not
    in the typography ramp (caption is spec'd 0 tracking, no case transform). Applied
    consistently and it works; promote it to a named utility or normalize it away — don't leave
    it as an ad-hoc recipe.
13. **Mono discipline frays in both directions at the edges** — prose-ish content in mono
    (audit timestamps) and code-ish content out of mono (token/key/URL hints). One "what counts
    as code" rule closes four Low findings at once (relates to observation 9's `text-data-mono`
    suggestion).
14. **Health page header mixes copy registers:** `ok` maps to the sentence "All systems normal"
    while degraded/down render the raw lowercase status string (health.tsx:100-103) — small
    vocabulary inconsistency on the most operator-visible status surface.
15. **Systemic-pattern occurrence lists from this scope** (for the fix pass): off-scale-20px —
    settings.tsx:321,514,706; alerts.tsx:63; audit.tsx:48; health.tsx:61; remediation.tsx:94;
    users-card.tsx:174; api-keys-card.tsx:114; remediation-hooks-panel.tsx:162. Missing
    focus-visible — selects at settings.tsx:175,803, audit.tsx:123, users-card.tsx:80,201,
    remediation-hooks-panel.tsx:175; chip buttons at settings.tsx:710,727,738; native checkboxes
    at alerts.tsx:145, remediation.tsx:184, remediation-hooks-panel.tsx:217; hover-only links at
    alerts.tsx:68-72, remediation.tsx:106-111.

Pattern-level observations from the responsive/generated-artifacts scope:

16. **Mobile touch-target gap is systemic:** native form controls (select, checkbox) and custom
    interactive elements (chart dots, slider handle) all lack the mobile min-height expansion
    that buttons and text inputs receive via index.css's `[data-slot]` rules — ~8 distinct
    interaction surfaces affected. Individually filed as High findings; one shared mechanism
    (extending the data-slot convention) fixes all of them.
17. **Responsive breakpoints mostly align with the spec, with two deviations:** scan-detail's
    2-up grid triggers at Tailwind xl (1280px) instead of the spec's 1440px Desktop XL boundary;
    finding-card grids expand at sm (640px) mid-way through the spec's Mobile Large range.
18. **Table overflow strategy is horizontal scroll everywhere** (no column-hiding or
    responsive-card pattern) — acceptable per modern practice, but there's no scroll
    affordance/hint at mobile widths (filed as Medium).
19. **Long-text handling is mixed:** URLs in tables use `truncate` consistently; audit-log
    evidence `<pre>` can overflow its cell; DOM diff tree truncates without a title fallback.
20. **Generated artifacts are design-complete and emoji-free** — PDF, email, markdown, and
    Telegram surfaces all conform to §4/§8 (verified-clean entries filed); the PDF's
    Helvetica/Georgia system-font fallbacks (OFL fonts not embedded) are acceptable per spec
    but worth noting as a deliberate divergence from the web UI's Fraunces/Inter stack.

Per-page responsive summary (Wave D4): login → ok; sites → ok (scroll-hint nice-to-have);
site-detail → issue (checkbox touch target); scan-detail → issue (xl breakpoint mismatch,
slider aspect); alerts → issue (checkbox); audit → issue (select + long mono overflow);
health → ok; remediation → issue (checkbox); settings → issue (flex-row overflow at 375px +
selects); app-shell → critical (no hamburger — previously filed) + email overflow.

*(End of Wave D notes.)*

## Migration round-trip verification log

Run live 2026-07-18 (main session, app container against a scratch database
`audit_migration_check`, production data untouched):
- `alembic upgrade head` from empty → `f3c8d6a91b27 (head)` — clean.
- `alembic downgrade base` → empty — clean (all tables and Postgres enum types dropped).
- `alembic upgrade head` again → `f3c8d6a91b27 (head)` — clean.
Additionally a single-revision downgrade/upgrade cycle was run on the production DB
(`f3c8d6a91b27` → `e9a2b7c15f04` → `f3c8d6a91b27`) — clean. Scratch DB dropped after.

## Installer/updater verification log

Run live 2026-07-18 (main session) against the running production stack (`.env` present,
GEMINI + Telegram keys configured, six services up):

- **`scripts/update.ps1`** — full flow succeeded end to end: Docker checks; `git pull
  --ff-only` → "Already up to date"; base-image pull (db, redis); serial rebuild of app,
  worker, beat (all layers CACHED — no source change); `docker compose run --rm app alembic
  upgrade head` → no pending migrations (already at head); `up -d --no-build app worker`
  (recreated); beat force-recreated; telegram-bot force-recreated (it was running); health
  poll passed inside 120s → "Wardress updated and running." Data, artifacts, `.env`
  preserved.
- **`scripts/install.ps1`** — run TWICE against the existing `.env`. Both runs: detected the
  existing `.env` and printed "keeping it untouched"; rebuilt images (cached); migrated (at
  head); restarted app/worker/beat; health "Dashboard is up."; admin seed idempotent
  ("User admin@wardress.local already exists"); Desktop shortcut created at
  `C:\Users\Ns8pc\Desktop\Wardress.lnk`; summary printed "Existing install detected:
  credentials were not changed" (no secrets printed on a re-run). After both runs, `cmp .env
  .env.backup` → **byte-identical** (idempotency confirmed), all six services healthy,
  `/api/health/live` → `{"status":"ok"}`.
- **Finding surfaced live:** install.ps1's final restart omits the telegram-bot, so after the
  run the bot showed a different uptime than app/worker/beat (not force-recreated) — filed as
  the install-vs-update bot-recreate asymmetry (MEDIUM) above.
- **Subagent note:** the deeper static review of scripts/compose/Dockerfiles (E1) and docs
  accuracy (E2) was completed in the MAIN SESSION after four subagent launches failed to
  transient API errors (429, malformed-HTTP-200 gateway, 405) — every file in both scopes had
  already been read in the main session and both scripts live-run, so no coverage was lost;
  findings above were verified against real source lines directly.

## Prerequisites verified for README

Traced this session — what a user genuinely needs on the Windows HOST before `install.ps1`:
- **Docker Desktop** (WSL 2 backend), running — the only hard prerequisite; verify with
  `docker --version` and `docker compose version` (the installer checks both).
- **git** — only if updating via `update.ps1`'s default `git pull` path (skippable with
  `-NoGitPull`, and irrelevant if the user downloaded a source zip); verify with `git --version`.
- **PowerShell 5.1+** — ships with Windows 10/11; the scripts are 5.1-compatible.
- **NOT required on the host:** Python, uv, Node, pnpm — all live only inside the Docker build
  stages (app image builds the frontend in a `node:22-alpine` stage and installs backend deps
  via the `uv` image; worker installs via `uv`). The README's Development-section tooling is
  for contributors building outside Docker, not for the install path. README's requirements
  section is accurate on this point; the ~6 GB disk figure is defensible (Playwright worker
  image + torch-cpu + baked MiniLM dominate).

## Wave F cross-cutting verification log

Run live 2026-07-18 (main session — subagents skipped this wave per instability):

- **Backend tests:** `uv run pytest --collect-only -q` → **383 collected**; `uv run pytest -q`
  → **383 passed, 1 warning** in 70.35s. The single warning is third-party (apprise imports
  stdlib `imghdr`, removed in Py3.13; container is Py3.12.13 — filed LOW).
- **Frontend:** `pnpm exec tsc --noEmit` → exit 0 (clean); `pnpm exec oxlint src` → 5
  `only-export-components` fast-refresh warnings, 0 errors; `it`/`test` count → 26.
- **Dependency audits:** `pip-audit` (uv) → no known vulnerabilities (torch+cpu and the local
  package skipped as not-on-PyPI); `pnpm audit --prod` → no known vulnerabilities.
- **Dead code:** `ruff check --select F401,F811,F841 app worker` → all checks passed.
- **Blocking-I/O-in-async heuristic:** no `time.sleep`/`requests`/`urllib`/`.read()` in async
  paths (excluding tests).
- **Indexes:** re-verified the three Wave B missing-index claims against models.py — all three
  confirmed still missing (alerts.created_at:322, remediation_executions.scan_id:570,
  scans.finished_at:427); consolidated into one performance finding.

## Report generation verification log

Run live 2026-07-18 against scan `8bfd4a15-1918-42cd-a461-dd14b7982dcb`
("Example Org", verdict clean, risk 4%):
- `GET /api/reports/{scan_id}/pdf` → valid `%PDF-1.7`, 47,815 bytes, embedded
  screenshot image, valid `%%EOF` terminator.
- `GET /api/reports/{scan_id}/markdown` → 3,254 bytes, well-formed: executive
  summary block, all nine per-layer sections (gate-skipped layers correctly noted
  with the skip reason), scan-history timeline table, tagline footer. No emoji.
- Caveat: the live DB currently holds only clean scans of example.org/example.net,
  so the multi-page flagged-scan PDF (page breaks around evidence tables and
  side-by-side screenshots) could not be re-exercised against real hostile-looking
  data this session. The Phase 4/6 QA passes did verify a 7-page flagged-scan PDF
  visually; this session re-proved the render path end-to-end on live data.

## Live LLM/Telegram verification log

Run 2026-07-18, deliberately economical (one call each):
- `POST /api/settings/gemini/test` → `ok: true, "Key works — gemini-flash-latest
  answered"` — real round-trip through the stored encrypted key.
- `POST /api/settings/telegram/test` → `ok: true, "Test message sent"` — real
  message delivered to the captured owner chat.
- Note: the bot container's long-poll loop shows intermittent
  `httpx.ConnectError: No address associated with hostname` entries in its logs
  (DNS resolution flakes from inside the container). The test endpoint delivered
  successfully through the app container, and the bot's error handling absorbed
  the failures without crash-looping — behavior correct; noted as an environment
  observation, not a product finding.

