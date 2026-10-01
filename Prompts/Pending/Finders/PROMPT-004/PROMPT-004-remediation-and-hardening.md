# PROMPT-004 — Full Remediation, Hardening & Closure (v1 — Autonomous Parallel-Subagent Edition)

**READ THIS ENTIRE FILE, START TO FINISH, BEFORE DOING OR WRITING ANYTHING.**
Do not skim. Do not jump to a phase. Do not begin work after reading only the phase list. This file defines rules that apply to *every* phase, and violating them invalidates the remediation. If you have already read it once earlier in this session, re-read it anyway — you cannot rely on a memory summary of your own instructions.

---

## 0. WHAT THIS IS

**The North Star:** To take every finding from the PROMPT-003 audit — **163 canonical findings** (13 Critical / 27 High / 79 Medium / 44 Low) across capture, detection, orchestration, API, frontend, AI integration, supply-chain, infrastructure, and operational scripts — and **fix every single one**, with engineering perfection, zero regressions, and a mathematically rigorous final verification that proves the system is genuinely hardened.

### 0.1 Context — Where We Are

PROMPT-002 (14 phases) was a capture-hardening and detection-accuracy effort. PROMPT-003 (17 audit phases across two sessions with parallel subagents) was a **read-only audit** that independently verified PROMPT-002's work, discovered everything it missed, stress-tested far harder than any prior effort, and produced a consolidated Findings Register with 163 deduplicated findings — each with a severity, reproduction, root cause, and proposed remedy category.

**PROMPT-003 diagnosed. PROMPT-004 repairs.**

The audit's own §8.1 identified the three priority clusters:
1. **The trust anchor is not trustworthy.** A 200-OK bot wall or paywall can be promoted as a healthy baseline, after which every scan either always-flags (risk 0.99999) or never-alerts-at-all (`clean` at 0.0063). Reproduced twice by independent methods.
2. **The SSRF boundary is breached.** Service Workers and `window.open()` popups bypass the Playwright route guard completely; three AI-provider code paths skip SSRF validation entirely; the favicon resolver and catalog fetcher use unpinned clients.
3. **Detection diverges on method, not on product.** Layer 3 has no element identity, layer 4 has no explanation channel, the fusion model is overfitted (34 of 323 benign rows exceed the flag threshold), and legitimate changes flag louder than paired attacks.

### 0.2 Architecture — How This Effort Works

This effort runs in **6 phases**, each in a **separate chat session with a fresh context window**. Each phase is orchestrated by a **coordinator agent** that spawns **3–4 parallel subagents** for the actual fix work, reviews their output, runs integration tests, and — if anything fails — **re-spawns the failing subagent with failure context until the phase is clean**.

**Dependency-chain ordering** ensures each phase builds on a stable foundation:
1. **Phase 1 — Foundation & Security** (DB schema, SSRF, supply-chain, CI)
2. **Phase 2 — Capture Pipeline** (stealth, fetcher, probe, banners, artifacts, wall detection)
3. **Phase 3 — Orchestration & Delivery** (Celery, scheduling, alerts, remediation, retention)
4. **Phase 4 — Detection Pipeline** (layers 1–9, normalization, suppression, fusion model refit)
5. **Phase 5 — API, Frontend & Operations** (routers, auth, rate-limiting, React, PowerShell scripts, docs)
6. **Phase 6 — Final Sign-Off & Closure** (full re-verification, stress tests, chaos, adversarial detection, closing report)

Each phase addresses findings from **ALL severity levels** within its subsystem — Critical, High, Medium, and Low together — because they share code, context, and test infrastructure.

### 0.3 Fully Autonomous Decision-Making

**This effort requires ZERO human input at any point.** Every design decision, security decision, and implementation choice is made autonomously:
- **Design decisions:** Choose the best-practice option.
- **Security decisions:** Choose the most conservative option.
- **Implementation choices:** Choose the most robust option.
- **Ambiguous findings:** Re-verify against current code, then choose the fix that eliminates the widest class of related bugs.
- **Conflicting audit claims:** The deduplication map in Phase 10 of the implementation log (§4 "Claims this audit invalidated") is authoritative. If two findings contradict each other, use the **later, measured** number.

### 0.4 The Paranoid Verification Principle

**Treat audit findings as leads, not ground truth.** They were produced by AI agents working under context-window pressure. Session A's deep verification found 8 claims invalidated outright, 8 corrected, 45 new findings the audit itself missed, and 6 severity escalations. Every subagent MUST:
1. **Re-verify** each assigned finding against the actual current code before implementing any fix.
2. **Adjust** if the finding is stale, the root cause is different, or the proposed remedy is insufficient.
3. **Hunt** for new issues in the same subsystem — findings are the floor, not the ceiling.
4. **Record** every deviation, discovery, and adjustment in the implementation log.

---

## 1. ABSOLUTE, NON-NEGOTIABLE RULES

1. **Red-Green-Refactor discipline is mandatory for every finding.** Before writing fix code: write (or identify) a test that **fails on current code**, proving the bug is real. Apply the fix. Confirm the test passes. Run the full regression suite. No exceptions.
2. **Scope discipline.** Fix only the findings assigned to the current phase's subagent scope (§4). If you notice something else wrong, log it under "New leads observed" and move on — unless it is in a file you are already editing AND fixing it is a one-line, zero-risk additive change. Even then, log it.
3. **Read before fixing, always.** Before writing "this is the fix," read the actual current file completely, trace every caller and callee, read every PROMPT-003 finding that touched it, and understand the full blast radius of your change.
4. **No regressions, ever.** The full existing test suite (backend `pytest`, frontend `vitest`, linters) must pass after every subagent completes. A fix that breaks something else must be redesigned, not shipped with a known regression.
5. **Package management:** `uv` exclusively for Python, `pnpm` exclusively for Node.
6. **One phase per session, fully, before stopping.** A phase does not end until every finding assigned to it is fixed, tested, and integrated — or explicitly deferred with justification logged.
7. **Every phase ends in exactly one git commit** per subagent (coordinator merges if needed): `fix(phase-N/sub-X): <summary> — closes: <finding IDs>`. Do not push. Do not amend prior commits.
8. **The SSRF policy (`app/ssrf.py`) is edited ONLY to fix its own findings (C1–C3).** All other SSRF-related fixes go in consumer code, not the policy module.
9. **No third-party runtime requests from the frontend.** `no-third-party-image-hosts.test.ts` stays unmodified and passing.
10. **Fresh Docker install available for testing.** If containers are not up, ASK the user to start them — do not run `scripts/install.ps1` or `scripts/uninstall.ps1` yourself.
11. **Backward compatibility with existing data.** Every fix must handle pre-existing rows in the database, pre-existing artifacts on disk, and pre-existing configuration in `.env` — migrations, not silent breakage.
12. **No dead code.** Every function, constant, import, and branch you write must have a caller and a test. Every function, constant, import, and branch you find dead in code you're editing — remove it if it's in scope, log it if it's not.
13. **Trust nothing you have not personally re-verified.** Do not take PROMPT-003 findings, PROMPT-002 log entries, code comments, docstrings, or passing tests at face value. Re-measure, re-trace, re-run. A disagreement between the audit's claim and reality is a discovery to log, not a reason to blindly implement the audit's suggestion.
14. **Every subagent gets maximum investigative liberty.** The findings list is the floor, not the ceiling. Subagents read, explore, understand, brainstorm, THEN implement. They are free to discover and fix additional bugs in their assigned files as long as they log everything.
15. **Context health is sacred.** No single subagent should be assigned more than ~25–30 findings. If a subsystem has more, split across multiple subagents with clear file-ownership boundaries (no two subagents edit the same file).
16. **The coordinator never fixes code directly.** The coordinator reads, reviews, integrates, runs tests, and re-spawns subagents. All code changes come from subagents.
17. **Optimisation is a first-class deliverable, not an afterthought.** The audit identified measured optimisation opportunities (batched MiniLM encoding: 1.76× speedup; process-scoped DB engine: 17.9× per-task; event-driven banner wait: −3.1 s per capture; parallel probe fetches: ~2×; route-level lazy loading: −809 kB). Implement every opportunity whose measured payoff exceeds 10% improvement in its metric, in the same phase as the subsystem it touches.
---

## 2. THE FIX GAUNTLET LOOP (mandatory for every subagent, every finding)

Every subagent follows this exact sequence for every finding in its scope. Do not skip steps.

**Step 1 — RE-VERIFY THE FINDING.** Read the finding's full entry in `PROMPT-003-IMPLEMENTATION-LOG.md`. Re-run the reproduction against the *current* code. If you cannot reproduce it, dig until you understand why. Log what you find.

**Step 2 — ROOT-CAUSE ANALYSIS.** Trace the actual mechanism end-to-end. Name the specific missing primitive.

**Step 3 — ENUMERATE EVERY EDGE CASE.** Before writing fix code, enumerate: concurrent access, empty/null/malformed input, Unicode/RTL/extreme lengths, partial failure mid-operation, retry/idempotency, auth/RBAC interaction, interaction with other findings already fixed, backward compatibility with existing data, performance at scale, what happens if the fix itself fails. If a category doesn't apply, note "N/A — reason."

**Step 4 — DESIGN THE FIX.** Consider at least two candidates. Weigh them. Prefer existing codebase patterns. If the audit's proposed remedy is incomplete or wrong, deviate and record why.

**Step 5 — WRITE THE FAILING TEST (Red).** Write a test that **fails on current unfixed code**, proving the bug is real.

**Step 6 — IMPLEMENT THE FIX (Green).** Minimal, scoped, idiomatic. Match surrounding code style.

**Step 7 — CONFIRM THE TEST PASSES.** Run the Step 5 test. If it doesn't pass, go back to Step 4.

**Step 8 — WRITE COMPREHENSIVE EDGE-CASE TESTS.** Every edge case from Step 3 that can be automated gets a test. Include concurrency, boundary, interaction, and malformed-input tests.

**Step 9 — RUN FULL REGRESSION SUITE.** Backend `pytest` (full), frontend `vitest`, linters. All green.

**Step 10 — LOG AND REPORT.** Write the fix-log entry to the subagent's scratch file. Report to coordinator.

**Step 11 — ITERATE ON FAILURE.** If Step 7 or 9 fails, go back to Step 2 or 4. No iteration cap. If not converging, leave the finding `PARTIAL` with full explanation rather than forcing false `FIXED`.

---

## 3. MANDATORY INTAKE READING

### 3.1 Coordinator intake (before spawning any subagent)

1. **This file** — completely.
2. **`PROMPT-004-IMPLEMENTATION-LOG.md`** — all prior phase entries.
3. **`PROMPT-003-IMPLEMENTATION-LOG.md`** — the full audit log. Focus on: Phase 10 Findings Register (§2), Deduplication Map (§3), Invalidated/Corrected claims (§4), Opportunities Register (§5), Coverage Gaps (§6).
4. **`PROMPT-003-stress-site-catalog.md`** — if this phase touches capture or detection.

### 3.2 Subagent intake (before starting any fix work)

1. **This file** — at minimum §0, §1, §2, and its own phase spec in §4.
2. **`PROMPT-003-IMPLEMENTATION-LOG.md`** — the finding entries for its assigned findings.
3. **`PROMPT-004-IMPLEMENTATION-LOG.md`** — all prior phase entries.
4. **Every source file in its assigned scope** — completely, tracing callers/callees.
5. **Every existing test file** for its assigned scope.

---

## 4. PHASE MAP (6 Phases — Dependency-Chain Order)

> [!IMPORTANT]
> **STRICT SEQUENTIAL EXECUTION.** Phases 1→6 must execute in order. Each phase's fixes depend on the prior phase's foundation being stable. A phase does not start until the prior phase's coordinator has confirmed all subagent work passes integration testing and is committed.

### PHASE 1 [Phase 1 of 6] — Foundation, Security & Supply-Chain

**Purpose:** Lay the infrastructure foundation that every subsequent phase depends on. Fix the SSRF boundary, harden authentication, update vulnerable dependencies, stabilize CI, and fix database schema issues. Nothing else can be reliably tested until this phase is clean.

**Coordinator spawns 4 subagents:**

#### SUBAGENT 1A — SSRF Boundary & Outbound-Fetch Factory

**Findings:** AUDIT-SA1-1 (C), AUDIT-SA1-2 (H — wall-detection gate only, not the capture-pipeline fix), AUDIT-4E-1 (C), AUDIT-4E-2 (C), AUDIT-4D-3 (M), AUDIT-4D-4 (M), AUDIT-3-3 (M — cache-key port omission)

**Target files:** `backend/app/ssrf.py`, `backend/app/ssrf_transport.py`, `backend/worker/fetcher.py` (context construction ONLY — service_workers + context.route), `backend/app/ai_catalog.py`, `backend/app/ai_ollama.py`, `backend/app/site_icons.py`, `backend/app/llm.py`

**Do:**
1. **C1 (AUDIT-SA1-1):** Add `service_workers="block"` to `browser.new_context(...)` in `fetcher.py`. Add `context.route("**/*", guard)` for popup coverage. Write a hermetic regression test asserting **server-side zero hits** on internal URLs. Correct the three docstrings that claim page-scoped routing covers "every request."
2. **C2/C3 (AUDIT-4E-1/4E-2):** Create a single `safe_async_client()` factory in `ssrf_transport.py` that always installs the pinning transport. Refactor `ai_catalog.py`, `ai_ollama.py`, `site_icons.py`, and `llm.py` to use it. Add a repo-wide test asserting no module builds a bare `httpx.AsyncClient`. Validate AI provider `base_url` at write-time (scheme, credential, SSRF check). Fix `ai_catalog.py`'s "never raises" contract against structurally wrong responses.
3. **M findings:** Fix the SSRF cache-key port omission (AUDIT-3-3). Implement size-capped streaming for the favicon resolver (AUDIT-4D-4 — 64.2 MiB heap peak). Pin the favicon httpx client to the SSRF transport (AUDIT-4D-3).
4. **Optimisation O-SA-1:** The one-factory design is itself the optimisation — "forgot the policy" becomes unrepresentable.

**Scratch output:** `scratch/phase-1-ssrf.md`

#### SUBAGENT 1B — Authentication, Rate-Limiting & Session Security

**Findings:** AUDIT-SA4-1 (M), AUDIT-SA4-2 (M), AUDIT-SA4-3 (M), AUDIT-SA4-4 (M), AUDIT-SA4-5 (M), AUDIT-SA5-1 (H), AUDIT-4E-8 (H), AUDIT-SA5-3 (M)

**Target files:** `backend/app/security.py`, `backend/app/deps.py`, `backend/app/ratelimit.py`, `backend/app/config.py`, `backend/app/crypto.py`, `backend/app/routers/auth.py`, `backend/app/routers/users.py`

**Do:**
1. **H (AUDIT-SA5-1):** Bump `pyjwt>=2.14.0`. Harden `decode_access_token` against non-`PyJWTError` exceptions so no future advisory becomes an unauthenticated 500.
2. **H (AUDIT-4E-8):** Value-aware redaction against the configured key set, not shape heuristics. Ensure no key leaks into `ScanFinding.evidence` or HTTP error bodies.
3. **M (AUDIT-SA4-1):** Add a `token_version` / `auth_version` column. Stamp into access tokens. Check on every decode. Revoke API keys on password change.
4. **M (AUDIT-SA4-2):** Take the rightmost untrusted hop in XFF (walk right-to-left against trusted-proxy count). Normalise IPv6 to /64. Document the overwrite requirement.
5. **M (AUDIT-SA4-3/4):** Cap total lockout duration. Add operator notification on lockout. Add single-admin recovery path. Normalise lockout timing to eliminate the user-enumeration oracle.
6. **M (AUDIT-SA4-5):** Reject `CORS_ALLOWED_ORIGINS=*` at config-parse time or downgrade to non-credentialed wildcard. Add a test asserting the safe default.
7. **M (AUDIT-SA5-3):** Implement a Fernet key ring with version prefix so rotation doesn't destroy stored credentials.

**Scratch output:** `scratch/phase-1-auth.md`

#### SUBAGENT 1C — Supply-Chain, CI & Dependency Hardening

**Findings:** AUDIT-4E-4 (C), AUDIT-4E-10 (H), AUDIT-4E-11 (M), AUDIT-4E-5 (M), AUDIT-SA5-4 (M), AUDIT-SA5-5 (L), AUDIT-SA5-6 (L), AUDIT-SA5-8 (L), AUDIT-2B-6 (L), AUDIT-4E-6 (L), AUDIT-4E-7 (L), AUDIT-4E-9 (L)

**Target files:** `backend/pyproject.toml`, `backend/uv.lock`, `frontend/package.json`, `pnpm-lock.yaml`, `Dockerfile.app`, `Dockerfile.worker`, `docker-compose.yml`, `.github/workflows/ci.yml`, `backend/tools/check_torch_osv.py`, `.dockerignore`

**Do:**
1. **C (AUDIT-4E-4):** Bump `weasyprint`, `pyjwt>=2.14.0` (coordinate with 1B), `oauthlib`. Run `uv lock` to update the lockfile.
2. **H (AUDIT-4E-10):** Bump `vitest>=4.1.11` in `frontend/package.json`. Add the same `pnpm audit` gate to `walkthrough/`.
3. **M (AUDIT-4E-11):** Fix `ruff check .` errors (9 errors at HEAD). Ensure CI gates are genuinely blocking.
4. **M (AUDIT-4E-5):** Pin runtime Docker images to digests. Pin MiniLM model weights to a specific revision with checksum verification (not `|| echo`).
5. **M (AUDIT-SA5-4):** Add Docker build steps to CI. Add audit/lint/typecheck gates for `walkthrough/`.
6. **L findings:** Fix `.dockerignore` (AUDIT-SA5-5), add `cap_drop`/`read_only`/`no-new-privileges` (AUDIT-SA5-6), pin GitHub Actions to commit SHAs (AUDIT-SA5-8), clean stale dependency declarations (AUDIT-2B-6), fix Ollama endpoint fallback chain (AUDIT-4E-6), add model-pull deadline (AUDIT-4E-7), clean dependency hygiene residue (AUDIT-4E-9).

**Scratch output:** `scratch/phase-1-supply-chain.md`

#### SUBAGENT 1D — Database Schema & Migration Safety

**Findings:** AUDIT-SA3-8 (M), AUDIT-SA3-10 (M), AUDIT-SA3-11 (M), AUDIT-SA3-12 (L), AUDIT-SA3-13 (L)

**Target files:** `backend/alembic/versions/`, `backend/app/models.py`, `backend/app/db.py`, `backend/worker/db.py`, `backend/worker/celery_app.py`, `docker-compose.yml` (Redis config only)

**Do:**
1. **M (AUDIT-SA3-8):** Run migrations at container start, not only from PowerShell scripts.
2. **M (AUDIT-SA3-10):** Ensure `missing-prereqs` sets a non-NULL verdict (or explicitly document the NULL contract).
3. **M (AUDIT-SA3-11):** Implement a process-scoped DB engine for Celery tasks. Make `pool_pre_ping=True` reachable. **(Optimisation O-SA-7: 95.06 → 5.32 ms per task, 17.9×).**
4. **L (AUDIT-SA3-12):** Remove orphan `wardress.ping` registration. Disable result storage for fire-and-forget tasks.
5. **L (AUDIT-SA3-13):** Configure Redis `maxmemory` with an eviction policy in `docker-compose.yml`.

**Scratch output:** `scratch/phase-1-schema.md`

**Phase 1 completion criteria:** All 4 subagent scratch files written. Coordinator runs integration tests across all changes. If any failure, re-spawn the failing subagent with context. Commit when clean: `fix(phase-1): foundation, security & supply-chain — closes: C1-C3, H-SA5-1, H-4E-8, H-4E-10, + 25 M/L findings`.

---

### PHASE 2 [Phase 2 of 6] — Capture Pipeline

**Purpose:** Fix every finding in the capture stack: stealth evasion, challenge detection, page preparation, screenshot capture, banner dismissal, artifact lifecycle, wall-page detection, and capture-completeness signaling. Depends on Phase 1's SSRF factory being in place.

**Coordinator spawns 3 subagents:**

#### SUBAGENT 2A — Stealth, Challenge Detection & Wall-Page Classifier

**Findings:** AUDIT-SA1-2 (H — capture-pipeline half: vendor-agnostic wall classifier + scan-path gate), AUDIT-SA1-4 (M), AUDIT-3-1 (H), AUDIT-5B-4 (M), AUDIT-5B-5 (M — catalog drift, log-only), AUDIT-5C-5 (M), AUDIT-6-6 (L)

**Target files:** `backend/worker/fetcher.py` (challenge/wall detection paths), `backend/worker/stealth.py`, `backend/worker/scan_tasks.py` (scan-path gate at :262-272)

**Do:**
1. **H (AUDIT-SA1-2 capture half):** Build a vendor-agnostic wall-page classifier that detects Akamai, DataDome, PerimeterX/HUMAN, AWS WAF, Imperva, Sucuri, and 200-OK interstitials — using status codes, response headers, cookie fingerprints, and DOM title/class markers. Add it as a separate gate in both the baseline path (extend the existing `>= 400` gate) and the scan path (currently has NO gate). Add a `blocked_page` capture-quality label.
2. **H (AUDIT-3-1):** Re-validate the challenge gate AFTER any banner click. If a click navigated away from the original page, detect and recover. Make the fallback banner selector specific rather than generic.
3. **M (AUDIT-SA1-4):** Extend the fail-open contract to a *raising* `playwright-stealth` library (log + continue unhardened). Give `fetch_page` a last-resort `except Exception → FetchError`.
4. **M (AUDIT-5B-4):** Classify `net::ERR_HTTP2_PROTOCOL_ERROR` correctly (permanent, not transient).
5. **M (AUDIT-5C-5):** Handle the case where a site returns 403 to the browser but 200 to the probe.
6. **L (AUDIT-6-6):** Fix Chrome Desktop UA / model-catalog task-naming drift.

**Scratch output:** `scratch/phase-2-stealth-wall.md`

#### SUBAGENT 2B — Page Preparation, Screenshots & Banner Dismissal

**Findings:** AUDIT-3-2 (M), AUDIT-3-6 (L), AUDIT-3-8 (L), AUDIT-5C-2 (M), AUDIT-5C-3 (M), AUDIT-5C-4 (M), AUDIT-SA1-3 (L), AUDIT-SA1-5 (L), AUDIT-5A-8 (L)

**Target files:** `backend/worker/page_prepare.py`, `backend/worker/banner_dismiss.py`, `backend/worker/fetcher.py` (screenshot paths)

**Do:**
1. **M (AUDIT-3-2):** Take a second frame snapshot after the initial dismiss pass. Scroll consent-iframe controls into view before clicking (the `_clickable_in_viewport` fix). **(Optimisation O-SA-4: event-driven banner wait saves −3.1 s per banner-free capture.)**
2. **M (AUDIT-5C-2):** Add a width-based screenshot guard alongside the existing height guard. Cap width at a sane maximum (e.g., 4096 px).
3. **M (AUDIT-5C-3):** Detect pages whose scrollable content lives in an inner container. Capture the inner scroll height.
4. **M (AUDIT-5C-4):** Handle the scroll-shrink path (initial_height >> final_height). Do not report `full` when scroll walked backward.
5. **L (AUDIT-3-8):** Fix `auto_scroll_page` counting a shrinking height as stable.
6. **L (AUDIT-SA1-3):** Eliminate the ~3.1 s overhead on every banner-free capture (event-driven wait instead of timeout).
7. **L (AUDIT-SA1-5):** Add width to the screenshot dimension guard (currently height-only).
8. **L (AUDIT-5A-8):** Handle `archive.org`'s `noscript` fallback pattern.

**Scratch output:** `scratch/phase-2-page-banner.md`

#### SUBAGENT 2C — Artifacts, Probe & Capture Evidence

**Findings:** AUDIT-3-4 (H — write atomicity + retention), AUDIT-3-5 (M), AUDIT-3-7 (L), AUDIT-5A-5 (M — DNS failure as SSRFBlockedError), AUDIT-5A-6 (M — stress runner blind spot)

**Target files:** `backend/worker/artifacts.py`, `backend/worker/probe.py`, `backend/worker/scan_tasks.py` (evidence assembly paths), `backend/tools/run_stress_catalog.py`

**Do:**
1. **H (AUDIT-3-4 write path):** Implement atomic write-then-rename for artifact files. Move `store_artifacts` AFTER the DB commit so a kill mid-write can't leave truncated content behind a `completed` row.
2. **H (AUDIT-3-4 retention path):** Key the janitor on row *state* and *age*, not just row existence. A failed row's artifacts should be cleaned. Add a retention policy with a configurable horizon.
3. **M (AUDIT-3-5):** Flow capture-completeness facts into `ScanPageData` so detection layers can consume them. Add a `degraded` field to `ScanFinding`.
4. **M (AUDIT-5A-5):** Classify DNS failures correctly (not as `SSRFBlockedError`). Add a wall-clock deadline to the probe. **(Optimisation O-SA-5: parallel `probe_site` UA fetches via `asyncio.gather`, ~2× on the probe leg.)**
5. **M (AUDIT-5A-6):** Fix the stress runner to detect bot-wall captures as failures.
6. **L (AUDIT-3-7):** Fix `content_sha256(None)` crash. Remove the provably dead `getpeercert()` branch.

**Scratch output:** `scratch/phase-2-artifacts-probe.md`

**Phase 2 completion criteria:** All 3 subagent scratch files written. Coordinator runs integration tests. Re-spawn on failure. Commit when clean.
---

### PHASE 3 [Phase 3 of 6] — Orchestration & Delivery

**Purpose:** Fix every finding in the task orchestration, scheduling, alert delivery, remediation execution, and data-retention systems. Depends on Phase 1's DB engine fix and Phase 2's artifact lifecycle being in place.

**Coordinator spawns 3 subagents:**

#### SUBAGENT 3A — Celery Scheduling, Dispatcher & Beat

**Findings:** AUDIT-SA3-1 (H), AUDIT-SA3-2 (H — retention policy), AUDIT-SA3-3 (H — orphaned artifacts), AUDIT-SA3-4 (H — broker retry bound), AUDIT-4B-2 (M — overload amplification), AUDIT-4B-3 (M — cadence pinning), AUDIT-4B-5 (M — stale-row recovery + stuck baselines), AUDIT-4B-6 (M — heartbeat on success-path only), AUDIT-SA3-5 (M), AUDIT-SA3-6 (M), AUDIT-4B-7 (L — worker memory ceiling), AUDIT-4B-4 (L — accepted-risk, verify and close), AUDIT-9-14 (M — acknowledge-late claim is false), AUDIT-7-5 (M — SIGKILL leaves row running)

**Target files:** `backend/worker/beat_tasks.py`, `backend/worker/celery_app.py`, `backend/worker/scan_tasks.py` (scheduling/stale recovery paths)

**Do:**
1. **H (AUDIT-SA3-1):** On the publish-failure path, mark the freshly-inserted `pending` row as `failed` with an explicit enqueue-failure reason. Add a `lost_publish` stat counter.
2. **H (AUDIT-SA3-2):** Implement time-bounded retention policies per table (scans, findings, artifacts, alerts, deliveries, remediation executions, audit log) with a documented default horizon. Add a scheduled prune task with per-run budgets.
3. **H (AUDIT-SA3-3):** Key the janitor on row state and age, not existence alone. A `failed` row's artifact tree must be cleaned after the retention horizon.
4. **H (AUDIT-SA3-4):** Give the worker's publisher the same bounded retry policy as the API client (`max_retries=2, interval_start=0.1`). Or make publishing non-blocking with a retry queue.
5. **M (AUDIT-4B-2):** Fix the overload amplification trigger (age-based, not backlog-depth-based). Cap supersession at a sane rate.
6. **M (AUDIT-4B-3):** Make the adaptive cadence consume the degradation signal, not raw fused risk. Reduce the consecutive-clean-scan recovery requirement.
7. **M (AUDIT-4B-5):** Add a beat-side stale sweep for stuck `pending`/`capturing` baselines. Reduce worst-case stale-row recovery latency.
8. **M (AUDIT-4B-6):** Write the heartbeat on both the success and failure paths.
9. **M (AUDIT-SA3-5/6):** Fix `_schedule_next` silent failure. Add a stats bucket for the in-flight unique index.
10. **M (AUDIT-9-14):** Fix or correct the `acknowledge late` claim. Set `task_reject_on_worker_lost=True`.
11. **M (AUDIT-7-5):** Ensure SIGKILL leaves the scan row recoverable (stale sweep catches it).
12. **L (AUDIT-4B-7):** Document the memory ceiling. Consider `--max-memory-per-child` or cgroup limits.
13. **L (AUDIT-4B-4):** Verify accepted-risk is still correct. Close definitively.

**Scratch output:** `scratch/phase-3-scheduling.md`

#### SUBAGENT 3B — Alert & Remediation Delivery

**Findings:** AUDIT-4B-1 (H — lost alerts on worker death), AUDIT-4D-1 (H — mid-delivery crash orphans channels), AUDIT-4D-2 (M — check-then-act double-send), AUDIT-4C-1 (M — 503 partial-success on dead broker), AUDIT-2B-3 (M — remediation crash-after-claim), AUDIT-2B-4 (M — sync enqueue on event loop), AUDIT-SA5-6b (L — no delivery retry/circuit breaker), AUDIT-SA5-7b (L — webhook no auth/replay protection)

**Target files:** `backend/worker/scan_tasks.py` (alert creation paths), `backend/worker/alert_tasks.py`, `backend/app/routers/sites.py` (single-create broker error path), `backend/app/imports.py`

**Do:**
1. **H (AUDIT-4B-1):** Create the alert row inside the terminal transaction, not after the commit. Add a recovery sweep for completed-and-alertless scans.
2. **H (AUDIT-4D-1):** Create per-channel delivery rows up front. Fix the resweep predicate to include zero-row partials. Sanitise site names to reject CR/LF.
3. **M (AUDIT-4D-2):** Replace the check-then-act idempotence guard with an atomic claim (DB-level `SELECT ... FOR UPDATE` or partial unique index).
4. **M (AUDIT-4C-1):** On single-site create, roll back or return 503 with a clear message when the broker is dead (don't leave a committed site with no baseline enqueued).
5. **M (AUDIT-2B-3):** Fix the remediation executor's crash-after-claim window.
6. **M (AUDIT-2B-4):** Make `imports.py` enqueue baseline captures asynchronously instead of blocking the event loop.
7. **L (AUDIT-SA5-6b):** Add retry with exponential backoff and circuit breaker for alert delivery.
8. **L (AUDIT-SA5-7b):** Add HMAC signatures and timestamp-based replay protection to remediation webhook payloads.

**Scratch output:** `scratch/phase-3-alert-delivery.md`

#### SUBAGENT 3C — Probe Resilience & Worker Health

**Findings:** AUDIT-7-2 (H — probe no total deadline), AUDIT-7-3 (H — probe buffers entire response), AUDIT-6-2 (H — zombie process leak), AUDIT-6-3 (H — scan cost inflation), AUDIT-4E-3 (M — hung provider stalls 30s), AUDIT-6-4 (M — non-deterministic failure rate), AUDIT-6-5 (M — merged into 4B-2)

**Target files:** `backend/worker/probe.py`, `backend/worker/celery_app.py` (worker config), `backend/worker/detection/semantics.py` (torch thread count)

**Do:**
1. **H (AUDIT-7-2):** Add a wall-clock deadline across the whole probe, not per-operation. A 90 s slow-loris should never cost 271.9 s.
2. **H (AUDIT-7-3):** Stream with an incremental cap. Abort past the limit. Do not buffer the entire response before slicing.
3. **H (AUDIT-6-2):** Reap zombie child processes. Verify the soak-visible process table growth stops.
4. **H (AUDIT-6-3):** Set `torch.set_num_threads(1)` per child. **(Optimisation O-6-1: eliminates 83–94% thread contention overhead.)** **(Optimisation O-SA-2: batched MiniLM encoding, 1.76× / −261.7 ms per scan.)**
5. **M (AUDIT-4E-3):** Add a per-provider circuit breaker so a hung provider doesn't stall other providers.
6. **M (AUDIT-6-4):** Root cause is the OOM cascade (C13 = AUDIT-6-1). Fix the zombie leak and thread contention to stabilise.

**Scratch output:** `scratch/phase-3-probe-worker.md`

**Phase 3 completion criteria:** All 3 subagent scratch files written. Coordinator runs integration tests. Re-spawn on failure. Commit when clean.

---

### PHASE 4 [Phase 4 of 6] — Detection Pipeline

**Purpose:** Fix every finding in the 9-layer detection pipeline, normalization, suppression, and the fusion model. This is the largest and most complex phase — it includes the fusion model refit. Depends on Phase 2's capture-completeness signaling and Phase 3's degradation signal being in place.

**Coordinator spawns 4 subagents:**

#### SUBAGENT 4A — Layers 1–4 (Hash, Structure, DOM References, Visual)

**Findings:** AUDIT-4-1 (C — `_new_text` granularity collapse), AUDIT-SA2-2 (C — false `clean` on security-header downgrades), AUDIT-SA2-3 (C — scale-blind layer 7), AUDIT-8-5 (C — bidirectional-diff defect: removal + un-hiding blindness), AUDIT-1-1 (M — "changed not clean" on benign content), AUDIT-4-3 (M — static expired cert scores 0.5 forever), AUDIT-4-5 (H — empty/unparseable capture), AUDIT-4-6 (M — layer 3 removal-blind), AUDIT-4-2 (H — probe transients as evidence), AUDIT-2-5 (M — no `degraded` column), AUDIT-2B-1 (M — stylesheet bytes never captured), AUDIT-2B-2 (M — sub-threshold emission gaps)

**Target files:** `backend/worker/detection/content.py`, `backend/worker/detection/dom.py`, `backend/worker/detection/visual.py`, `backend/worker/detection/metadata.py`, `backend/worker/detection/hashing.py`, `backend/worker/detection/cloaking.py`

**Do:**
1. **C (AUDIT-4-1):** Fix `_new_text` to use a proper diff rather than treating all current-side text as "new." The granularity collapse (100% of page = "new text") must not occur on unpunctuated, emoji-only, numbers-only, mixed-script, or CJK pages.
2. **C (AUDIT-SA2-2):** Add a directional classifier to layer 6 so it distinguishes security-header strengthening from weakening. A CSP addition should score differently from a CSP removal. Fix the false `clean` on HSTS removal.
3. **C (AUDIT-SA2-3):** Fix layer 7's scale-blindness. It should not be a step function of page size. Add an absolute-mass channel. **(Optimisation O-8-5.)**
4. **C (AUDIT-8-5):** Make DOM-based layers bidirectional. Removals must score. Un-hiding (dropping `opacity:0`) must be visible.
5. **H (AUDIT-4-5):** Add content-type and parseability guards. Refuse the `clean` verdict on an empty pair. Binary junk should not produce `risk 0.9833`.
6. **H (AUDIT-4-2):** Treat current-side probe failure as a degraded channel, not evidence of change. Do not fuse a TLS failure into 0.5502.
7. **M findings:** Fix static expired cert scoring (AUDIT-4-3). Make layer 3 bidirectional (AUDIT-4-6). Add `degraded` column to `ScanFinding` (AUDIT-2-5). Capture stylesheet bytes (AUDIT-2B-1). Re-add dropped sub-threshold corpus rows (AUDIT-2B-2). Implement the "changed not clean" remedy correctly (AUDIT-1-1 — gate on content-layer peak excluding l1 and generic churn).

**Scratch output:** `scratch/phase-4-layers-1-4.md`

#### SUBAGENT 4B — Layers 5, 8 & Normalization/Suppression

**Findings:** AUDIT-4-4 (H — over-broad suppression blinds layers), AUDIT-SA2-1 (H — no element identity in layer 3), AUDIT-8-8 (H — `<base href>` invisible to layer 3), AUDIT-8-9 (M — `<noscript>` and `title=` invisible), AUDIT-8-13 (H — legitimate changes flag), AUDIT-8-14 (H — layer 4 no explanation channel), AUDIT-9-6 (M — every `<link>` scores 0.6), AUDIT-9-8 (M — ReDoS guarantee absent for normaliser), AUDIT-2-1 (M — 3 absent attack families), AUDIT-2-3 (M — redirect/time-delayed), AUDIT-9-7 (M — stale code comments)

**Target files:** `backend/worker/detection/dom.py` (element-identity rewrite), `backend/worker/detection/suppress.py`, `backend/worker/detection/normalize.py`, `backend/worker/detection/semantics.py`, `backend/worker/detection/visual.py` (explanation channel), `backend/worker/detection/signatures.py`

**Do:**
1. **H (AUDIT-4-4):** Emit a per-rule coverage fraction in evidence and the UI. Scope/limit `bbox` rules. A suppression rule that times out must not manufacture a delta. **(Optimisation O-8-3: suppression-coverage meter.)**
2. **H (AUDIT-SA2-1):** Implement element-identity-aware ref diff, keyed on `tag+position+stable-attr`. Classify `src` rotation as a value change, not element addition. Recalibrate additive weights. **(Optimisation O-8-7: typography/base/event-handler reference surface.)**
3. **H (AUDIT-8-8):** Resolve refs against the document `<base href>`, not `PageData.final_url`. Add `on*`-target collectors.
4. **H (AUDIT-8-13):** Gate `changed` verdict on the content-layer peak excluding l1 and the generic churn term. Consider a third verdict state.
5. **H (AUDIT-8-14):** Add a `capture_context` channel on `PageData` (viewport, device class, colour scheme, font stack) that fusion treats as explanation. **(Optimisation O-8-1.)**
6. **M findings:** Fix every `<link>` scoring 0.6 regardless of `rel` (AUDIT-9-6). Add ReDoS protection to the normaliser (AUDIT-9-8). Add the 3 absent attack families to the corpus (AUDIT-2-1). Fix redirect detection (AUDIT-2-3). Fix stale code comments (AUDIT-9-7). Handle `<noscript>` and `title=` visibility (AUDIT-8-9).

**Scratch output:** `scratch/phase-4-layers-5-8-suppress.md`

#### SUBAGENT 4C — Fusion Model Refit (Dedicated — The Fusion Arc)

**Findings:** AUDIT-2-4 (H — overfitting), AUDIT-SA2-4 (M — `sanity_benign_quiet` fuses to 0.6583), AUDIT-4F-5 (L — stale constant assertion)

**Target files:** `backend/worker/detection/fusion.py`, `backend/worker/detection/training/fusion_dataset.json`, `backend/tools/build_regression_corpus.py`

**This subagent runs the 3-part fusion arc:**

**Part A — Synthetic Dataset Construction:**
1. Read the current `fusion_dataset.json` (646 rows, 14 axes — but 7 benign axes omitted from the corpus guard).
2. Construct a new dataset with **ALL benign axes** represented (minimum 8 rows per axis).
3. Add the missing evasion axes: `nonnative_full_rewrite`, `nonnative_partial_inject`, `partial_cloaking_small_payload`.
4. **Anti-bias controls (all mandatory):**
   - Balanced classes (not a 95/5 skew)
   - Stratified across every evasion axis and language
   - Genuine train/validation/held-out-test split with zero leakage
   - Sanity-check rows: trivially-obvious attacks AND trivially-obvious benign cases
   - Document the full generation methodology

**Part B — Refit & Calibration:**
1. Refit the logistic regression against the new dataset.
2. Validate **monotonicity** (more evidence never lowers risk score).
3. Validate calibration (ROC curves, calibration plots).
4. Cross-validate.
5. Document every coefficient's justification.
6. Confirm `sanity_benign_quiet` no longer crosses 0.40.
7. Confirm `vendor_script_added` (benign) no longer averages 0.7538.

**Part C — Integration & Validation:**
1. Integrate the refit model into the pipeline.
2. Re-run all adversarial detection tests from Subagents 4A and 4B.
3. Confirm no regression on a held-out benign-dynamic-content test set.
4. Update `NOISE_FLOOR`, `MATERIAL_CHANGE_RISK`, and all derived constants.
5. Fix the stale constant assertion at `fusion.py:40` and `:192` (AUDIT-4F-5).
6. **(Optimisation O-8-8 / O-SA-12):** Add a standing benign-population gate that fails the build — every benign axis needs ≥8 corpus rows, and `validate()` asserts maximum fused risk per benign axis.

**Scratch output:** `scratch/phase-4-fusion-arc.md`

#### SUBAGENT 4D — Detection Edge Cases & Live-Site Accuracy

**Findings:** AUDIT-5C-1 (C — merged with AUDIT-9-1), AUDIT-7-1 (C — opposite direction: false clean), AUDIT-4-7 (M — layer completeness spec), AUDIT-4-8 (M — stylesheet consumption spec), AUDIT-5A-9 (L — runner budget), AUDIT-2-6 (L — unused capture_meta headers)

**Target files:** `backend/worker/detection/types.py`, `backend/worker/scan_tasks.py` (detection invocation paths), various detection modules for edge-case fixes

**Do:**
1. **C (AUDIT-5C-1 / AUDIT-9-1):** The "poisoned anchor" content-shape gate at baseline promotion. **(Optimisation O-9A: refuse or flag `suspect` a candidate baseline whose document is implausibly small, below a visible-text floor, or in the bottom percentile for that site. Vendor-independent. Three arithmetic checks on data the capture already produces.)** This is the single highest-value remediation item in the entire audit.
2. **C (AUDIT-7-1):** Fix the opposite direction — a legitimate healthy page captured after a poisoned baseline reads as `clean` because the poisoned baseline's noise is the same noise. The O-9A gate prevents this by refusing the poisoned baseline in the first place.
3. **M (AUDIT-4-7/4-8):** Implement the layer completeness and stylesheet consumption specifications as documented in the audit.
4. **L findings:** Handle runner budget exhaustion (AUDIT-5A-9). Remove unused `capture_meta["headers"]` (AUDIT-2-6).

**Scratch output:** `scratch/phase-4-edge-cases.md`

**Phase 4 completion criteria:** All 4 subagent scratch files written. Coordinator runs integration tests, including the full adversarial detection accuracy suite. If any false-positive or false-negative rates exceed the refit model's validation thresholds, re-spawn. Commit when clean.

---

### PHASE 5 [Phase 5 of 6] — API, Frontend & Operations

**Purpose:** Fix every remaining finding in the API routers, authentication edge cases, React frontend, PowerShell operational scripts, documentation, and test quality. Depends on all prior phases' backend fixes being stable.

**Coordinator spawns 4 subagents:**

#### SUBAGENT 5A — API Routers, Health & Configuration

**Findings:** AUDIT-4C-2 (M — public docs/schema), AUDIT-4C-3 (L — two mute implementations), AUDIT-4C-4 (L — DELETE no guard), AUDIT-4C-5 (L — dead healthcheck docstring), AUDIT-4C-6 (L — double-charge rate limit), AUDIT-4C-7 (L — DELETE hard-deletes users), AUDIT-SA4-8 (M — unbounded GET /api/sites), AUDIT-SA4-9 (M — health returns 200 on DB-down), AUDIT-SA4-10 (L — 12 dead client functions), AUDIT-SA4-12 (L — audit-log LIKE wildcards), AUDIT-SA4-13 (L — 4 dead symbols), AUDIT-SA5-2 (M — litellm plaintext logging), AUDIT-SA5-7 (L — LOGIN_RATE_LIMIT undocumented)

**Target files:** `backend/app/routers/health.py`, `backend/app/routers/sites.py`, `backend/app/routers/users.py`, `backend/app/routers/settings.py`, `backend/app/routers/audit.py`, `backend/app/main.py`

**Do:**
1. **M (AUDIT-4C-2):** Gate `/docs`, `/redoc`, `/openapi.json`, `/docs/oauth2-redirect` behind authentication or a config flag. Default: off in production.
2. **M (AUDIT-SA4-8):** Add offset/limit + total to `GET /api/sites`.
3. **M (AUDIT-SA4-9):** Return 503 on the degraded health branch.
4. **M (AUDIT-SA5-2):** Set `turn_off_message_logging=True` for litellm. Ensure no LLM prompt/response reaches plaintext logs at any level.
5. **L findings:** Fix all remaining Low API findings: dead code removal, double-charge rate-limit fix, LIKE wildcard escaping, healthcheck docstring, DELETE guards, mute implementation consolidation, undocumented rate-limit variable.

**Scratch output:** `scratch/phase-5-api.md`

#### SUBAGENT 5B — React Frontend

**Findings:** AUDIT-4F-2 (M — degraded renders as Clean/0%), AUDIT-4F-3 (M — blank dashboard on malformed payload), AUDIT-SA4-6 (M — zero aria-live/role=status), AUDIT-SA4-7 (M — keyboard inaccessible), AUDIT-1-2 (M — aggregate attributions), AUDIT-4F-1 (L — test flake), AUDIT-4F-4 (L — severity colour 8 ways), AUDIT-4F-6 (L — bidi isolation), AUDIT-4F-7 (L — unnamed role=application), AUDIT-4F-8 (L — unconditional-red unmeasured chip), AUDIT-4F-9 (L — duplicate scan-list fetch), AUDIT-SA4-11 (L — 1077 kB initial payload), AUDIT-2B-5 (L — stale gauge comment)

**Target files:** `frontend/src/` (all relevant components)

**Do:**
1. **M (AUDIT-4F-2):** Show a "degraded" indicator distinct from "Clean / 0%" when detection channels went dark.
2. **M (AUDIT-4F-3):** Add defensive guards at the 3 unguarded expressions across 4 routes. No malformed payload should blank the dashboard.
3. **M (AUDIT-SA4-6/7):** Add `aria-live` regions for polling state changes. Fix keyboard accessibility on bulk-import CSV control. Add labels and table captions.
4. **L findings:** Fix test flake (AUDIT-4F-1 — explicit waitFor timeout). Consolidate severity colours (AUDIT-4F-4). Add bidi isolation (AUDIT-4F-6). Fix unnamed role=application (AUDIT-4F-7). Fix unconditional-red chip (AUDIT-4F-8). Deduplicate scan-list fetch (AUDIT-4F-9). Fix stale gauge comment (AUDIT-2B-5).
5. **(Optimisation O-SA-6: route-level `lazy()` — 1077 kB → 268 kB raw, −809 kB.)**

**Scratch output:** `scratch/phase-5-frontend.md`

#### SUBAGENT 5C — PowerShell Operational Scripts

**Findings:** AUDIT-9-2 (H — update.ps1 no .env reconciliation), AUDIT-9-3 (H — validate.ps1 wrong memory check), AUDIT-9-4 (H — diagnostics.ps1 leaks API keys), AUDIT-9-5 (H — restore silently downgrades schema), AUDIT-9-10 (L — 3 dead entry points), AUDIT-9-16 (L — argument quoting bug), AUDIT-9-17 (L — undocumented beat schedule file), AUDIT-SA3-7 (L — beat no depends_on:db)

**Target files:** `scripts/install.ps1`, `scripts/update.ps1`, `scripts/validate.ps1`, `scripts/diagnostics.ps1`, `scripts/uninstall.ps1`, `scripts/lib.ps1`, `docker-compose.yml`

**Do:**
1. **H (AUDIT-9-2):** **(Optimisation O-9C):** Create a shared `Get-WardressEnv` primitive in `lib.ps1` with `Get-RequiredKey`/`Get-MissingKeys -Against .env.example`. Use it in update.ps1 to reconcile `.env` against `.env.example`.
2. **H (AUDIT-9-3):** Check Docker's `MemTotal` (not the host's). Add disk and port preflight checks.
3. **H (AUDIT-9-4):** **(Optimisation O-9F):** Extract the diagnostics scrubber rule table into a tested module. Add a hostile-corpus test asserting zero escapes. Cover `wk_` keys, JWTs, Fernet keys, Apprise URLs.
4. **H (AUDIT-9-5):** Pin the Alembic schema revision in the backup. Verify-and-fail on a partial restore.
5. **L findings:** Remove dead entry points (AUDIT-9-10). Fix argument quoting (AUDIT-9-16). Document beat schedule file (AUDIT-9-17). Add `depends_on: db` for beat (AUDIT-SA3-7).

**Scratch output:** `scratch/phase-5-ops-scripts.md`

#### SUBAGENT 5D — Documentation & Test Quality

**Findings:** All remaining documentation findings and test-quality findings not covered by detection phases.

**Documentation (log-only or content-fix):** All doc-correction findings from the audit's register that haven't been closed by prior phases' code changes. This includes README detection-assurance claims, fusion doc claims, RBAC tables, semantics doc, layer-6 doc, usage doc, link-audit diagram.

**Test quality:** AUDIT-SA3-9 (L — `via` accepted and discarded), AUDIT-4C-3 (L — divergent audit snapshots), plus any test-quality improvements needed to bring coverage up to the level the fixed codebase deserves.

**Target files:** `README.md`, `docs/`, test files across `backend/tests/`, `frontend/src/**/*.test.*`

**Do:**
1. Re-read every doc-correction finding. Verify each claim against the NOW-FIXED codebase (not the audit's pre-fix measurements). Write the correct, honest claim.
2. Clean up any remaining dead code, stale comments, or test-quality issues logged by prior phases' "New leads observed."
3. Run a final documentation consistency pass: every numeric claim in README/docs should cite the test or measurement that proves it.

**Scratch output:** `scratch/phase-5-docs-tests.md`

**Phase 5 completion criteria:** All 4 subagent scratch files written. Coordinator runs integration tests including frontend `vitest`, `pnpm exec tsc --noEmit`, and a11y checks. Re-spawn on failure. Commit when clean.

---

### PHASE 6 [Phase 6 of 6] — Final Sign-Off & Closure

**Purpose:** Full adversarial re-verification of the entire fixed codebase. This phase proves the fixes work — it does NOT trust any prior phase's self-reported success. If anything fails, it spawns fix subagents, re-tests, and loops until clean.

**Coordinator spawns 4 subagents:**

#### SUBAGENT 6A — Full Regression & Stress Testing

1. Run the complete backend `pytest` suite (full, not subset).
2. Run the complete frontend `vitest` suite.
3. Run `pnpm exec tsc --noEmit` and all linters.
4. Run the PROMPT-003 stress-test catalog (all Tiers A/B/C from `PROMPT-003-stress-site-catalog.md`).
5. Record pass/fail/skip counts for every suite.
6. If ANY failure: report to coordinator with full context. The coordinator spawns a fix subagent targeting the specific failure.

**Scratch output:** `scratch/phase-6-regression.md`

#### SUBAGENT 6B — Chaos & Fault Injection

1. Run all 7 chaos scenarios from the audit's coverage gaps (§6):
   - Postgres restart mid-scan (3 passes)
   - Redis connection loss (3 passes)
   - Network partition (3 passes)
   - Broker outage during dispatch (3 passes)
   - Worker SIGKILL during scan (3 passes)
   - Worker OOM during detection (3 passes)
   - Concurrent re-baseline during active scan (3 passes)
2. Verify that every chaos scenario either recovers cleanly or fails with an explicit, operator-visible error — never silently loses data or orphans rows.
3. Run the backup → restore end-to-end replay that the audit could not run (§6 gap #3).

**Scratch output:** `scratch/phase-6-chaos.md`

#### SUBAGENT 6C — Adversarial Detection Accuracy

1. Run the full adversarial detection accuracy suite against the refit fusion model:
   - All attack scenarios from the audit (single-vector, multi-vector, evasion variants)
   - All benign scenarios (ads rotating, timestamps, cache-busting, A/B tests, font swaps, responsive breakpoints)
   - All edge cases (empty pages, binary junk, unpunctuated text, CJK, emoji-only)
2. Verify false-positive rate < 5% on the benign population.
3. Verify false-negative rate < 5% on the attack population.
4. Verify the poisoned-anchor gate (O-9A) correctly rejects all bot-wall/paywall captures.
5. Verify the wall-page classifier correctly identifies all vendor WAFs.
6. Record every measurement with ≥3 passes per scenario.

**Scratch output:** `scratch/phase-6-detection-accuracy.md`

#### SUBAGENT 6D — Finding-by-Finding Spot-Check

1. Take the full 163-finding register from PROMPT-003.
2. For every Critical and High finding (40 total): re-run the exact reproduction steps from the audit. Verify the finding is genuinely fixed. If ANY reproduction succeeds (the bug is still present), report to coordinator.
3. For Medium and Low findings: spot-check 30% (randomly selected, reproducible). Verify.
4. Check for NEW issues introduced by the fixes: regressions, new dead code, new performance problems.

**Scratch output:** `scratch/phase-6-spot-check.md`

**Phase 6 completion criteria:** All 4 subagent scratch files written and clean. If any subagent reports a failure, the coordinator spawns a targeted fix subagent, applies the fix, then re-runs the failing subagent. This loop repeats until all 4 subagents report clean. Then:

1. Update `PROMPT-004-IMPLEMENTATION-LOG.md` with the final closing report.
2. Record total findings fixed, any findings deliberately left open with justification, and overall confidence.
3. Produce the **Final Findings Register** showing disposition of all 163 findings.
4. Commit: `fix(phase-6): final sign-off — all 163 findings verified closed`.

---

## 5. FIX-LOG ENTRY FORMAT (one per finding, appended to PROMPT-004-IMPLEMENTATION-LOG.md)

```
### [FIXED] <finding ID> — <finding title fragment>

- **Original severity**: Critical / High / Medium / Low
- **Phase / Subagent**: N / Sub-X
- **Files changed**: path/to/file.py:120-145, path/to/other.tsx:40-60
- **Re-verification (Step 1)**: How confirmed the finding still reproduces on current code
- **Root cause (Step 2)**: The actual lowest-level mechanism
- **Edge cases (Step 3)**: Full enumeration, each with disposition
- **Fix design (Step 4)**: Candidates weighed, winner justified
- **Failing test (Step 5)**: test_file.py::test_name — confirmed fails pre-fix
- **Fix applied (Step 6)**: Concrete description of what was actually done
- **Test passes (Step 7)**: Confirmed
- **Edge-case tests (Step 8)**: test_file.py::test_name_1, test_name_2, ...
- **Regression result (Step 9)**: Exact pass/fail/skip counts
- **Interactions with prior fixes**: Confirmation no conflicts
- **Residual risk / follow-ups**: Anything not fully closed
```

For findings that turn out to be already fixed by a prior phase or invalidated:
```
### [ALREADY-FIXED] <finding ID> — <finding title fragment>

- **Disposition**: Fixed by Phase N / Sub-X as a side-effect of <related finding>
- **Verification**: How confirmed it's genuinely fixed

### [INVALIDATED] <finding ID> — <finding title fragment>

- **Disposition**: Finding no longer reproduces because <specific reason>
- **Verification**: What was checked to confirm
```

---

## 6. THE PHASE 1 KICKOFF PROMPT (paste into a fresh chat to start)

```
READ EVERY FILE LISTED BELOW COMPLETELY, START TO FINISH, BEFORE DOING ANYTHING ELSE.
Do not skim. Do not begin work after reading only part of a file.

1. C:\Users\Ns8pc\Music\WARDRESS\Prompts\Pending\Finders\PROMPT-004\PROMPT-004-remediation-and-hardening.md
   — The master protocol. Every rule applies. Read §0, §1, §2, §3, and PHASE 1 in §4.

2. C:\Users\Ns8pc\Music\WARDRESS\Prompts\Pending\Finders\PROMPT-003\PROMPT-003-IMPLEMENTATION-LOG.md
   — The complete audit findings. Read in full. Focus on: Phase 10 Consolidated Findings
   Register (§2), Deduplication Map (§3), Invalidated/Corrected claims (§4).

3. C:\Users\Ns8pc\Music\WARDRESS\Prompts\Pending\Finders\PROMPT-004\PROMPT-004-IMPLEMENTATION-LOG.md
   — The implementation log. If this is Phase 1, it will be empty/template. If a later phase,
   read all prior entries.

You are the COORDINATOR for Phase 1 — Foundation, Security & Supply-Chain.

Your job:
1. Confirm Docker is running and the Wardress deployment is up.
2. Run the full existing test suite and record baseline pass/fail/skip counts.
3. Spawn 4 subagents (1A, 1B, 1C, 1D) per this file's Phase 1 spec.
4. Each subagent follows the Fix Gauntlet Loop (§2) for every finding in its scope.
5. After all subagents complete, run integration tests across all changes.
6. If ANY failure, re-spawn the failing subagent with the failure context.
7. When all clean: update PROMPT-004-IMPLEMENTATION-LOG.md, commit (do not push).
8. Output the Phase 2 kickoff prompt for me to paste into a fresh chat.

For any decision, ALWAYS choose the best option autonomously. Do not wait for my input.
Do not ask questions. Do not propose alternatives. Just execute.
```

---

## 7. FILE PATHS

All files referenced by this protocol:

| File | Purpose |
|---|---|
| `C:\Users\Ns8pc\Music\WARDRESS\Prompts\Pending\Finders\PROMPT-004\PROMPT-004-remediation-and-hardening.md` | This file — the master protocol |
| `C:\Users\Ns8pc\Music\WARDRESS\Prompts\Pending\Finders\PROMPT-004\PROMPT-004-IMPLEMENTATION-LOG.md` | Implementation log — tracks progress and fix entries |
| `C:\Users\Ns8pc\Music\WARDRESS\Prompts\Pending\Finders\PROMPT-003\PROMPT-003-IMPLEMENTATION-LOG.md` | Audit findings — read-only source of truth for what's wrong |
| `C:\Users\Ns8pc\Music\WARDRESS\Prompts\Pending\Finders\PROMPT-003\PROMPT-003-stress-site-catalog.md` | Stress-test site catalog — used by Phases 2, 4, 6 |
| `C:\Users\Ns8pc\Music\WARDRESS\` | The Wardress codebase root |

---

## 8. A NOTE ON DISCIPLINE

The single biggest failure mode for a remediation effort of this scale is declaring victory early: patching the symptom the audit described, watching one reproduction case go green, and moving on without ever enumerating the edge cases that made the original bug possible. A race condition fixed for two concurrent actors but not three; a validation fix that handles empty strings but not whitespace-only ones; a fusion-model refit validated only on the audit's own literal examples instead of a genuinely independent held-out set — these are not fixes. They are the same bug wearing a disguise.

The Gauntlet Loop in §2 exists specifically to make that shortcut structurally harder to take. The 6-phase structure exists so that depth never has to compete with a shrinking context window. The parallel subagent architecture exists so that speed never has to compete with thoroughness. And the Phase 6 adversarial re-verification exists so that no prior phase's self-reported success is trusted without independent proof.

**163 findings. Zero regressions. Every fix proven. Let's go.**
