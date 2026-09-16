# PROMPT-003 — Capture & Detection Audit, Gap-Closure Discovery, and Stress Hardening (v2 — Closure-Loop Edition)

**READ THIS ENTIRE FILE, START TO FINISH, BEFORE DOING OR WRITING ANYTHING.**
Do not skim. Do not jump to a phase. Do not begin work after reading only the phase list. This file defines rules that apply to *every* phase, and violating them invalidates the audit. If you have already read it once earlier in this session, re-read it anyway — you cannot rely on a memory summary of your own instructions.

---

## 0. WHAT THIS IS

**The North Star of this entire effort:** To elevate **Site Capturing** and all **Nine Detection Layers** to the standard of **engineering perfection** — bulletproof, highly robust capture (immune to WAF blocks, stealth detection, banner overlays, infinite scroll wedging, or slow origins) and mathematically rigorous, flawless detection (zero false alerts on benign dynamic churn, zero missed real-world attacks, ReDoS immunity, and reliable second-opinion escalation).

PROMPT-002 (`capture-hardening-and-detection-accuracy-v2.md`, 14 phases) is **complete**. Every phase is logged `[DONE]` in `PROMPT-002-IMPLEMENTATION-LOG.md`. That log is not a rubric stamp — it is the claim of an agent about its own work, phase by phase, often written near the end of a long context window. **This effort exists to independently verify that claim, find everything it missed, stress the result far harder than it was stressed before, and either close every gap it finds or hand the user a fully-scoped remediation prompt for anything that doesn't hold up.**

This is **not** a re-run of PROMPT-002. It does not re-implement, re-derive, or second-guess design decisions that were made deliberately and documented with reasoning. It is a **verification and discovery** effort with five jobs, in this order:

**A note on scope before the list below: this effort is not limited to the files PROMPT-002 happened to touch.** PROMPT-002 was scoped to the specific mechanisms it was fixing (stealth, scrolling, banners, retries, normalization, fusion, etc.), and its own target-file lists were necessarily narrow — that was correct discipline for a fix effort, but it means whole adjacent subsystems that the capture-and-detection dataflow actually depends on (task orchestration, the database schema/migrations, the API routes that expose scan/baseline/finding data, alert/webhook delivery, Celery configuration, frontend components that render capture health and verdicts, and the project's own dependency tree) were never independently looked at by anyone in either effort. §4's Audit Phase 2B exists specifically to build a full inventory of the repository and pull every in-scope file — not just the ones already named — into this audit's blast radius before the fresh-eyes phases begin. **One explicit exception:** the chat-driven operations agent (`backend/app/agent/`) and its Telegram interface are a separate feature built for a different purpose (interactive ops queries, not site capture or detection) and are out of scope for this effort by design — except for `llm_escalation.py`, which is genuinely part of the detection pipeline's own "second opinion on ambiguous verdicts" mechanism and stays in scope on that basis alone. Phase 2B makes this split explicit and carries a narrow escalation path back into scope if later phases find the agent touching capture/detection data outside the boundary Phase 4C already audits.

1. **Traceability audit.** Cross-reference every rule, phase spec, edge case, and test obligation in PROMPT-002 against what was *actually* delivered — not what the log says was delivered. Find anything skipped, partially done, silently narrowed in scope, or where a "Rule 12 deviation" quietly softened the original intent instead of honestly meeting it.
2. **Full-repository inventory.** Before assuming the fresh-eyes audit's target-file lists are complete, walk the *entire* repository and classify every file by whether it sits in, or materially supports, the capture→detection→verdict→alert dataflow — regardless of whether any PROMPT-002 phase ever named it. This is what stops the audit from silently inheriting PROMPT-002's own scoping boundaries as if they were the boundaries of the system.
3. **Fresh-eyes code audit.** Read the actual current code — the PROMPT-002-named files *and* everything Job 2 pulled in — as if neither effort had happened. Find bugs, race conditions, resource leaks, incorrect assumptions, and engineering weaknesses that a phase-by-phase implementation process is structurally prone to missing.
4. **Stress testing far beyond the original scope.** PROMPT-002's own validation (Phase 13) used a curated 74-site list and hit 87.8%, with three categories explicitly left below target and *accepted in aggregate*. This effort tests against a much larger, harder, more adversarial catalog (see the companion file `PROMPT-003-stress-site-catalog.md`), runs every stress category more than once for repeatability, and adds concurrency/scale/chaos regimes no PROMPT-002 phase was scoped to cover.
5. **Close the loop — do not let this end the way PROMPT-002 ended.** PROMPT-002 finished with an aggregate-accepted shortfall (87.8% vs. a 90% target, three whole categories left below bar with no individually-investigated root cause) and one unresolved spec deviation quietly logged and left open. **That is not acceptable as a final state for this effort or anything it spawns.** See §0.1.

### 0.1 Why this effort must not end in an aggregate "good enough"

Every below-target metric produced anywhere in this effort — a capture success rate, a detection accuracy rate, a latency percentile — must be broken down to **individual, per-case root cause**, never reported and closed as a bare aggregate number. Each individual failing case gets one of exactly two dispositions:
- **Fix-candidate**: logged as a Finding (§6) for the remediation prompt to close.
- **Accepted-risk**: only when a case is genuinely unfixable given a real external constraint (e.g., a site that requires authentication Wardress is not meant to bypass) — and only with an explicit, individually-argued justification that is surfaced to the user for their own accept/reject decision. "It's a small percentage of the aggregate, moving on" is never, by itself, a valid disposition.

This effort is explicitly permitted — required — to **keep looping** (audit → remediate → re-audit) until it reaches a real Clean Bill of Health, not a single declared "done." See §8 (The Closure Loop) for the exact mechanism. Diagnosis and repair are still separated (Rule 1) — this file only diagnoses and, where warranted, authors the next remediation prompt — but that next prompt is contractually required to end in a re-verification pass, not a commit message.

Each phase happens in a **separate chat with a fresh context window**, exactly as PROMPT-002 did — this is deliberate and non-negotiable: it is what keeps every phase's work deep and hallucination-free instead of a rushed pass through a shrinking context window (see §0.2). This file is the only thing that persists your instructions across sessions. `PROMPT-003-IMPLEMENTATION-LOG.md` is the only thing that persists your *progress and findings* across sessions. Together with the companion `PROMPT-003-stress-site-catalog.md`, they are the entire state of this effort.

**If it isn't written into `PROMPT-003-IMPLEMENTATION-LOG.md`, it did not happen.**

### 0.2 Streamlined Phase Architecture

Every phase in the map below is sized to fit in one context window doing one subsystem thoroughly, preserving the non-negotiable rule of **one phase per session in a fresh context window**. To maximize efficiency without cutting corners, closely related discovery tasks (Repository Inventory + Prior History Sweep), secondary infrastructure audits (AI Integration + Supply Chain), and stress testing with the automated runner tool (`backend/tools/run_stress_catalog.py`) are consolidated into cohesive, high-impact sessions. This reduces total sessions while maintaining 100% test rigor and zero hallucination risk. If a phase turns out bigger than expected anyway, Rule 8 still applies: finish a smaller, explicitly-scoped subset correctly and say so, rather than rushing the whole thing shallowly.

---

## 1. ABSOLUTE, NON-NEGOTIABLE RULES

1. **This is diagnosis, not repair.** Audit phases may add *new, isolated test files* (hermetic, non-production) to probe behavior. They must **never** modify production code (`backend/app/**`, `backend/worker/**` non-test files, `frontend/src/**`, `docker-compose.yml`, `.env*`, `scripts/**`, `docs/**`) to "fix" something you find. If you are certain a fix is a one-line, zero-risk change, do **not** apply it — log it as a candidate for the remediation prompt instead. The one exception: a genuinely trivial, purely-additive diagnostic aid (e.g., a temporary debug log line) needed to investigate must be reverted before the phase ends — diagnosis leaves no production trace.
2. **Scope discipline.** Investigate only the subsystem assigned to the current audit phase (§4). If you notice something else wrong, log it under "Findings — out of phase scope" and move on.
3. **Read before judging, always.** Before writing "this is broken" or "this is missing," read the actual current file completely, trace every caller and callee, and re-read every PROMPT-002 log entry that touched it.
4. **Proven, not asserted — in both directions.** Every finding must be reproduced: a failing test, a captured stack trace, a measured metric that misses its target, or a concrete counter-example. Do not mark something "confirmed working" without a test or measurement backing it.
5. **No regressions, ever, even during an audit.** Any new test file must not break the existing suite. Backend/frontend/lint suites must stay at or above the last recorded baseline. A test *proving a gap exists* must be marked `xfail`/skipped-with-reason if committed, or kept uncommitted in scratch (Rule 10) — a red CI is never an acceptable end-of-phase state for committed code.
6. **Package management:** `uv` exclusively for Python, `pnpm` exclusively for Node — exactly as PROMPT-002 Rule 5.
7. **No third-party runtime requests from the frontend.** `no-third-party-image-hosts.test.ts` stays unmodified and passing.
8. **One phase per session, fully, before stopping.** If a phase's assigned subsystem is bigger than expected, finish a smaller, explicitly-scoped subset thoroughly and leave the tracker noting exactly what remains.
9. **Every phase ends in exactly one git commit** covering only committed artifacts (new hermetic test files, the audit log entry, additions to the site catalog file). `feat(audit-N): <summary>` or `docs(audit-N): findings log` if no test file was added. Do not push. Do not amend prior commits.
10. **Scratch work outside the repo,** exactly as PROMPT-002 Rule 9 — probes that proved a failure and aren't meant to ship go in `/tmp/`, described in the log with exact repro steps, never committed.
11. **Backward compatibility is a read, not a write, concern here** — you are checking whether PROMPT-002's claims hold, not migrating anything.
12. **The SSRF policy is sacred and untouched.** You may write tests that *probe* it; `app/ssrf.py` is never edited in this effort. Any finding here is automatically Critical.
13. **Paranoid Verification Principle — trust nothing you have not personally re-verified.** Do not take documentation claims (`README.md`, `docs/*.mdx`, `docs.json`), code comments, docstrings, or even existing passing tests at face value. Systems and documentation drift; old tests frequently test what the developer *assumed* rather than how the system actually behaves under adversarial conditions. Every number in `PROMPT-002-IMPLEMENTATION-LOG.md` is a self-reported claim — re-measure it before citing it as ground truth. Inspect the live data flow, check the database and memory, run tests cold, and demand empirical proof. A disagreement between docs/tests and reality is itself a finding.
14. **Infrastructure and docs are read for drift, not written to.** Drift found here (including any PowerShell script or documentation inaccuracies) is a finding for the remediation prompt, not something to quietly correct now.
15. **Fresh Docker install available for testing**, exactly as PROMPT-002 Rule 14. **Do not run `scripts/install.ps1` or `scripts/uninstall.ps1` yourself.** If containers are not up, ASK the user to start them.
16. **Severity discipline.** Every finding gets exactly one severity, chosen honestly against §6.4 — do not inflate, do not deflate.
60. 17. **Liberty to brainstorm beyond the log — mandatory, not optional.** The traceability matrix and log-derived leads are your *floor*, not your *ceiling*. In every phase, think past "does this meet what PROMPT-002 said" and ask "what would make this subsystem genuinely better, more capable, or more resilient — including things neither PROMPT-002 nor its log ever imagined?" Capture these in the separate **Opportunities / Innovation Ideas** log field (§6.1) — not severity-scored, not required to trigger anything on their own, but every one written down with enough reasoning that the user can evaluate it later. Do not silently filter an idea out because it seems out of scope; log it and let the user decide. The only constraint is Rule 1 — brainstorm and log freely, never implement against production code during an audit phase.
61: 18. **No single-pass proof of reliability.** A stress-test result (a site capture, a concurrency run, a chaos-injection scenario) observed exactly once is a data point, not a finding of "works" or "doesn't work." Every site in the stress-test catalog, every concurrency load level, and every chaos scenario must be run a **minimum of three total passes**, ideally spread across more than one session/time-of-day so transient network/vendor-side conditions don't masquerade as your system's behavior. Record the outcome of every pass and the variance across them — "3/3 succeeded, consistent 18-22s capture time" is a finding; "succeeded once" is not.
62: 19. **No aggregate acceptance of below-target results.** Per §0.1: every below-target metric must be broken down to individually-investigated root causes per failing case, each with an explicit Fix-candidate or Accepted-risk disposition. An aggregate percentage with no per-case breakdown is an incomplete phase, not a finding.
63: 20. **Strict Monotonic Phase Sequence & Zero-Skip Invariant.** Every phase in this audit has an explicit sequence identifier `[Phase N of 17]` listed in §4. An agent is **strictly prohibited from skipping or reordering any phase**. An agent completing Phase `N` must output the kickoff prompt for Phase `N+1` exclusively. Skipping code-audit phases (e.g., jumping from Phase 4C to Phase 5A and bypassing 4D, 4E, or 4F) is a catastrophic protocol violation that invalidates the audit handoff. Every kickoff prompt MUST explicitly state: `Executing ONLY Audit Phase <Name> [Phase N of 17]`.
64: 
65: ---
66: 
67: ## 2. THE AUDIT GAUNTLET LOOP (mandatory for every phase)
68: 
69: **Step 1 — INTAKE.** Read this entire file. Read `PROMPT-003-IMPLEMENTATION-LOG.md` completely (all prior audit-phase entries). Read the companion `PROMPT-003-stress-site-catalog.md` if this phase touches capture/stress testing. Read the specific PROMPT-002 phase spec(s) and log entries relevant to this phase's assigned subsystem (§4).
70: 
71: **Step 2 — REBUILD THE TRACEABILITY MATRIX ROW BY ROW** (traceability phases) or **EXECUTE THE ASSIGNED STRESS/AUDIT WORK** (all other phases), per §4's per-phase instructions.
72: 
73: **Step 3 — READ THE LIVE CODE COLD** where applicable — set prior claims aside and read the actual current files as if PROMPT-002 never happened, tracing every function, caller, exception path, and cross-phase interaction.
74: 
75: **Step 4 — ENUMERATE NEW EDGE CASES, HARDER THAN BEFORE.** Do not just re-check PROMPT-002's list. Add adversarial cases it didn't consider.
76: 
77: **Step 5 — TEST, WITH REPEATABILITY (Rule 18).** Write hermetic tests where automatable; use the live Docker install for anything requiring a real browser or real sites; run every stress scenario the minimum number of passes Rule 18 requires; document manual verification honestly where automation isn't possible.
78: 
79: **Step 6 — CLASSIFY AND LOG, WITH NO AGGREGATE SHORTCUTS (Rule 19).** Every finding gets a severity (§6.4), a precise reproduction, a root-cause explanation, file/line(s), and a proposed remedy sketch. Every below-target metric gets the per-case breakdown Rule 19 requires. Append to `PROMPT-003-IMPLEMENTATION-LOG.md` per §6.1.
80: 
81: **Step 7 — REGRESSION CHECK.** Confirm new test files did not regress the existing suites (Rule 5).
82: 
83: **Step 8 — COMMIT AND HANDOFF.** Commit per Rule 9. Look up §4's Phase Map and verify the exact `[Phase N+1 of 17]` target. Verify against `PROMPT-003-IMPLEMENTATION-LOG.md` that all prior phases (1 through N) are marked `[DONE]`. Output the kickoff prompt strictly for Phase `N+1`, referencing its assigned scope, then stop.

---

## 3. MANDATORY INTAKE READING (every phase)

1. This file, completely.
2. `PROMPT-003-IMPLEMENTATION-LOG.md` — read previous findings (IDs, severity, root cause), active gaps, out-of-scope items, and the Phase 2B inventory. For completed Phase 1 and 2 entries, you do NOT need to re-read the settled historical traceability tables line-by-line; focus on the findings, leads, and active state to preserve context.
3. `PROMPT-003-stress-site-catalog.md`, when the phase touches capture or stress testing (Audit Phases 5A/5B/5C, 6, 7, 8).
4. `PROMPT-002-capture-hardening-and-detection-accuracy-v2.md` in `Prompts/Pending/Finders/PROMPT--002/` — only if relevant to the subsystem being checked (Phases 3 and 4+ fresh-eyes phases cold-read code directly and ignore PROMPT-002).
5. `PROMPT-002-IMPLEMENTATION-LOG.md` in `Prompts/Pending/Finders/PROMPT--002/` — only when verifying specific historical leads.
6. **For Phases 3, 4, 4B–4G: the Audit Phase 2B inventory entry in `PROMPT-003-IMPLEMENTATION-LOG.md`.** That inventory — not the fixed file lists written into §4 of this document when it was authored — is the authoritative target-file source. If Phase 2B hasn't run yet, do not substitute your own guess at scope; that is what Phase 2B exists to prevent.
7. Every current source file in the assigned subsystem, completely, tracing callers/callees.

---

## 4. AUDIT PHASE MAP (17 phases — Strict Monotonic Sequence)

> [!IMPORTANT]
> **RULE 20 SEQUENCE LOCK**: Phases must be executed in strictly ascending sequential order (`Phase 01` through `Phase 17`).
> Skipping any phase (e.g. attempting to start Phase 5A before 4D, 4E, and 4F are complete) is an automatic protocol violation.
> Each phase's kickoff prompt MUST state its exact index `[Phase N of 17]`.

### AUDIT PHASE 1 [Phase 01 of 17] — Traceability Matrix: Capture Phases (PROMPT-002 Phases 1–7)
- **Status**: `DONE` (Commit `084bd6c` / `f1a8a4e`)
- **Mandatory Next Phase**: AUDIT PHASE 2 [Phase 02 of 17]

### AUDIT PHASE 2 [Phase 02 of 17] — Traceability Matrix: Detection Phases (PROMPT-002 Phases 8–14)
- **Status**: `DONE` (Commit `11a5e54` / `a692b73`)
- **Mandatory Next Phase**: AUDIT PHASE 2B [Phase 03 of 17]

### AUDIT PHASE 2B [Phase 03 of 17] — Full Codebase Inventory, Blast-Radius Mapping & Prior-History Sweep
- **Status**: `DONE` (Commit `5d7ac7f` / `7536fc6`)
- **Mandatory Next Phase**: AUDIT PHASE 3 [Phase 04 of 17]
**Target:** The entire repository for classification, plus `Prompts/Done/Loogers/WARDRESS_AUDIT_FINDINGS.md` (268KB) and `WARDRESS_FIX_LOG.md` (790KB) via targeted search.
**Do:**
1. **Repository Inventory & Blast-Radius Mapping:** Walk `backend/`, `frontend/`, `docs/`, `scripts/`, and repo root. Group and classify files into the blast-radius buckets:
   - *Capture/detection core:* target files named in Phases 1–4.
   - *Orchestration, data & scheduling:* `scan_tasks.py`, `remediation_tasks.py`, `beat_tasks.py`, `celery_app.py`, `models.py`, `schemas.py`, alembic migrations.
   - *API routers, auth & RBAC:* `routers/*.py` (except `agent.py`), `deps.py`, `ratelimit.py`, `security.py`.
   - *Alert & remediation delivery:* `alerting.py`, `remediation.py`, `explain.py`, templates. **Confirm `telegram_bot.py`**: alert channel (in-scope) or ops-agent chat transport (excluded)?
   - *AI provider integration:* `ai_*.py`, `llm.py`, `llm_escalation.py`.
   - *Frontend surfaces:* React components/hooks rendering capture health, scan results, verdicts.
   - *Supply chain & config:* `pyproject.toml`, `package.json`, Dockerfiles, `ci.yml`, `check_torch_osv.py`.
   - *Excluded operations agent:* `app/agent/`, `routers/agent.py`, `docs/agent*.mdx`. Escalate ONLY if it touches database/scan data directly bypassing API/RBAC.
   - *Out of blast radius:* `landing/`, `walkthrough/`.
   - Highlight any in-radius file never touched in PROMPT-002 as highest priority for fresh-eyes phases.
2. **Prior-History Sweep:** Use targeted grep (never full reads) against `Prompts/Done/Loogers/` for "TODO", "deferred", "not implemented", "residual", "known issue", "unresolved". Cross-check if closed by PROMPT-002 or still open today.
**Output & Formatting Discipline:** Append the grouped inventory table (by directory/subsystem with file counts, not 590 separate lines) and any prior-history gaps to the audit log following §6.1.

### AUDIT PHASE 3 [Phase 04 of 17] — Fresh-Eyes Code Audit: Capture Pipeline
- **Status**: `DONE` (Commit `5b0a884` / `25ffae0`)
- **Mandatory Next Phase**: AUDIT PHASE 4 [Phase 05 of 17]
**Target files:** the capture-core files named in Phase 1, **plus** whatever Phase 2B's inventory added to this bucket — cold read, ignore PROMPT-002/log this session.
**Do:** Full Step 3. Hunt for: resource leaks on every exception path; state leakage across retry attempts; Cloudflare wait-and-retry racing navigation timeout; height cap interacting with scroll-to-bottom-then-top; "silent lie" patterns; memory growth across sequential captures in one worker.

### AUDIT PHASE 4 [Phase 05 of 17] — Fresh-Eyes Code Audit: Detection Pipeline
- **Status**: `DONE` (Commit `2928507` / `9721166`)
- **Mandatory Next Phase**: AUDIT PHASE 4B [Phase 06 of 17]
**Target files:** the detection-core files named in Phase 2, **plus** whatever Phase 2B's inventory added to this bucket — cold read, ignore PROMPT-002/log.
**Do:** Full Step 3. Hunt for: ways to defeat unconditional layer contracts; rule-floor boundary behavior (0.849 vs 0.851); over-normalization letting real attacks slip through; numerical stability on malformed/huge diffs.

### AUDIT PHASE 4B [Phase 06 of 17] — Fresh-Eyes Code Audit: Orchestration, Scheduling & Data Models
- **Status**: `DONE` (Commit `ef5eb8c` / `125e31e`)
- **Mandatory Next Phase**: AUDIT PHASE 4C [Phase 07 of 17]
**Target files:** `backend/worker/celery_app.py`, `worker/scan_tasks.py`, `worker/beat_tasks.py`, `worker/db.py`, `app/scanning.py`, `app/tasks.py`, `app/services.py`, `app/models.py`, `schemas.py`, alembic migrations.
**Do:** Full Step 3, cold. Hunt for: beat claim/advance CAS races; in-flight scan/baseline arbitration; stale pending/running row recovery; worker prefork memory scaling; Celery late-ack and idempotency contracts.

### AUDIT PHASE 4C [Phase 07 of 17] — Fresh-Eyes Code Audit: API Routers, RBAC & Rate Limiting
- **Status**: `DONE` (Commit `fedfbf7` / `ed7f5af`)
- **Mandatory Next Phase**: AUDIT PHASE 4D [Phase 08 of 17]
**Target files:** `backend/app/routers/` (all 13 in-scope routers, except `agent.py`), `deps.py`, `ratelimit.py`, `security.py`, `apikeys.py`, `audit.py`.
**Do:** Full Step 3, cold. Hunt for: tenant/account data leakage across routes; Admin/Analyst/Viewer RBAC boundary enforcement; rate-limit bypass paths; session/token invalidation and edge cases; unauthenticated route exposure (`/docs`, `/openapi.json`).

### AUDIT PHASE 4D [Phase 08 of 17] — Fresh-Eyes Code Audit: Task Orchestration, Alert & Remediation Delivery
- **Status**: `PENDING — NEXT UP`
- **Mandatory Next Phase**: AUDIT PHASE 4E [Phase 09 of 17]
**Target files:** `backend/worker/scan_tasks.py`, `remediation_tasks.py`, `alert_tasks.py`, `beat_tasks.py`, `celery_app.py`, `app/alerting.py`, `app/remediation.py`, `app/explain.py`, templates (`alert.html`, `test.html`, `report.html`), `app/site_icons.py`.
**Do:** Full Step 3, cold. Hunt for: scan/baseline crash mid-write consistency; alert row creation unreachability on worker death (`AUDIT-4B-1`); alert delivery idempotency and retry backpressure; human-approval gating on remediation webhooks; remediation crash-after-claim windows (`AUDIT-2B-3`); beat interval shortening starvation; SSRF redirect validation in `site_icons.py`.

### AUDIT PHASE 4E [Phase 09 of 17] — AI Provider Integration, Supply-Chain & Infrastructure Configuration
- **Status**: `PENDING`
- **Mandatory Next Phase**: AUDIT PHASE 4F [Phase 10 of 17]
**Target files:** `backend/app/ai_*.py`, `llm.py`, `backend/worker/llm_escalation.py`, `backend/pyproject.toml`, `backend/uv.lock`, `frontend/package.json`, `pnpm-lock.yaml`, Dockerfiles, `docker-compose.yml`, `.env.example`, `.github/workflows/ci.yml`, `backend/tools/check_torch_osv.py`.
**Do:** Full Step 3, cold.
1. AI Integration: Graceful degradation when AI provider fails/hangs, Fernet encryption of keys on all write paths, auto-provisioned Ollama fallback, SSRF safety on custom provider endpoints.
2. Supply-Chain & Config: Vulnerability sweep on dependencies, confirm `check_torch_osv.py` runs in CI, check secrets handling, default credentials, image pinning in Dockerfiles.

### AUDIT PHASE 4F [Phase 10 of 17] — Fresh-Eyes Code Audit: Frontend Capture & Detection Surfaces
- **Status**: `PENDING`
- **Mandatory Next Phase**: AUDIT PHASE 5A [Phase 11 of 17]
**Target files:** React components/hooks rendering capture health, scan results, verdicts, or alert history, and API-client code.
**Do:** Full Step 3, cold. Root-cause the `capture-health.test.tsx` flake; check verdict/severity color clarity (degraded vs measured); stale-data races during in-flight scans; accessibility and mixed-script rendering; comment/constant drift (`AUDIT-2B-5`).

### AUDIT PHASE 5A [Phase 11 of 17] — Stress-Test Catalog: Broad Real-World Baseline (Tier A)
- **Status**: `PENDING`
- **Mandatory Next Phase**: AUDIT PHASE 5B [Phase 12 of 17]
**Do not touch code.** Execute Tier A of `PROMPT-003-stress-site-catalog.md` against the live Docker install using the automated runner `backend/tools/run_stress_catalog.py` (`uv run python tools/run_stress_catalog.py --tier A`).
- Enforces Rule 18 (minimum 3 passes per site), measures latency and variance, and outputs the markdown table directly.
- For every failure, log individual root cause and Fix-candidate/Accepted-risk disposition per Rule 19.

### AUDIT PHASE 5B [Phase 12 of 17] — Stress-Test Catalog: Advanced Bot Defenses & Exotic Edge Categories (Tiers B & C)
- **Status**: `PENDING`
- **Mandatory Next Phase**: AUDIT PHASE 6 [Phase 13 of 17]
**Do not touch code.** Execute Tiers B and C of `PROMPT-003-stress-site-catalog.md` (Akamai, DataDome, PerimeterX, AWS WAF, Turnstile, hard e-commerce, WebSockets, infinite scroll, heavy hydration, extreme DOMs) using `backend/tools/run_stress_catalog.py` (`--tier B` and `--tier C`).
- Same Rule 18 repeatability and Rule 19 individual root-cause discipline.

### AUDIT PHASE 6 [Phase 13 of 17] — Concurrency & Scale Stress Testing
- **Status**: `PENDING`
- **Mandatory Next Phase**: AUDIT PHASE 7 [Phase 14 of 17]
**Do not touch code.** Execute concurrency test regime per §7: load levels (1x, 2x, 5x) run 3 times each; 50-cycle soak run; measure queueing, CPU/memory, connection pool and lock contention.

### AUDIT PHASE 7 [Phase 14 of 17] — Chaos & Failure-Injection Testing
- **Status**: `PENDING`
- **Mandatory Next Phase**: AUDIT PHASE 8 [Phase 15 of 17]
**Do not touch code.** Execute 6 fault-injection scenarios per §7 (crash mid-capture, DNS/TLS failure, slow-loris response, malformed HTTP response, SSRF redirect loop, pathologically large DOM), run 3 times each. Classify as safe fail vs silent success vs worker crash.

### AUDIT PHASE 8 [Phase 15 of 17] — Adversarial Detection Accuracy Stress Test
- **Status**: `PENDING`
- **Mandatory Next Phase**: AUDIT PHASE 9 [Phase 16 of 17]
**Do not touch code.** Construct new hermetic attack/benign fixture pairs based on the Phase 2 taxonomy and test through deployed detection pipeline 3 times each. Measure false-negative rate on attacks and false-positive rate on live benign churn.

### AUDIT PHASE 9 [Phase 16 of 17] — Performance Profiling, Infrastructure & Operational Consistency Audit
- **Status**: `PENDING`
- **Mandatory Next Phase**: AUDIT PHASE 10 [Phase 17 of 17]
**Do not touch code.**
1. **Profiling:** Profile capture and detection pipelines under single and batch load. Identify concrete bottlenecks with measured costs (cold-start embedding, fusion reload, regex, missing DB indexes).
2. **Infrastructure & Docs:** Verify `docker-compose.yml`, `.env.example`, `scripts/*.ps1`, docs, and `SKILL.md` against audited runtime behavior. Verify documented safety guarantees (SSRF gating, human approval on remediations, ReDoS timeout, Fernet encryption, RBAC).

### AUDIT PHASE 10 [Phase 17 of 17] — Consolidated Findings Register, Opportunities Register & Decision Gate
- **Status**: `PENDING`
- **Mandatory Next Phase**: DECISION GATE (Author PROMPT-004 Remediation Prompt OR Clean Bill of Health)
**Do not touch code.** Read all prior audit entries. Produce:
1. Master **Findings Register** with anchor links back to original phase entries.
2. Severity summary table.
3. Opportunities / Innovation Register.
4. The **decision** per §8: Author `PROMPT-004` (if any Critical/High or qualifying Medium clusters exist) or issue the Clean Bill of Health.

---

## 5. THE STRESS-TEST SITE CATALOG

The full categorized site list — the user's curated real-world catalog (Tier A) plus the harder bot-protection and exotic/edge categories (Tiers B and C) this audit adds specifically because Phase 13 of PROMPT-002 left them below target or untried — lives in the companion file **`PROMPT-003-stress-site-catalog.md`**. Audit Phases 5A/5B/5C consume it directly; do not duplicate the list inline here where it would drift out of sync with the maintained catalog file. That file also carries the verification protocol (re-confirm vendor/liveness before use — bot-protection deployments and site structures change over time) and the repeatability logging format (Rule 18).

---

## 6. LOG & SEVERITY RUBRIC

### 6.1 Implementation log entry format

Append to `PROMPT-003-IMPLEMENTATION-LOG.md` after each phase:

```
### [DONE / PARTIAL] PROMPT-003 Audit Phase N — <phase title>

- **Prompt**: PROMPT-003-capture-detection-audit-and-stress-hardening.md
- **Session date**: YYYY-MM-DD
- **Assigned subsystem**: <per §4>
- **Traceability matrix rows** (Phases 1-2 only): full table — claim | Verified/Gap/Unverifiable/Deferred | evidence
- **Stress-test results** (Phases 5A/5B/5C/6/7/8 only): Use a dense markdown summary table:
  `| URL | Tier/Category | Pass 1 | Pass 2 | Pass 3 | Variance | Status | Notes / Disposition |`
  Passing sites (3/3) must take only **one single line** in the table. Detailed Finding blocks (per Rule 19) are authored **only for failing sites** below the table with individual root cause + Fix-candidate/Accepted-risk disposition (no aggregate-only rows).
- **Findings**: one block per finding —
    - **ID**: AUDIT-<phase>-<n>
    - **Title**:
    - **Severity**: Critical / High / Medium / Low (per §6.4, justified)
    - **Subsystem / file(s)**:
    - **Reproduction**: exact steps, test name if automated, pass count if a stress finding
    - **Root cause**:
    - **Proposed remedy category**: (not an implementation)
    - **Source**: which Gauntlet step / which stress category surfaced it
- **Log-vs-reality discrepancies**: any PROMPT-002 log claim you could not reproduce, with both numbers/behaviors stated
- **New hermetic tests added this phase**: file:test_name — what it proves, and whether it's committed-passing or documented-as-scratch (Rule 5/10)
- **Opportunities / Innovation ideas observed** (Rule 17 — not severity-scored, not gap-driven): one block per idea —
    - **Idea**:
    - **Why it would help**:
    - **Where it touches**: file(s)/subsystem
    - **Rough shape of the change**: (sketch only, no implementation)
- **Full regression results**: exact commands + counts for every suite
- **Findings out of phase scope**: logged for the correct future phase, not investigated here
- **Commit**: <short hash> — <message>
- **Next phase kickoff prompt**: (see §9)
```

### 6.2 Findings Register format (Audit Phase 11 only)

A single consolidated master table, deduplicated across all phases, sorted by severity then subsystem:
`| ID | Title | Severity | Subsystem | Source Phase | Proposed Remedy | Target Prompt |`
Use markdown anchor links back to the original finding entry in the log (e.g., `[AUDIT-1-1](#audit-1-1)`), rather than copying and pasting full paragraphs of reproduction and root-cause text. This prevents redundant bloat while maintaining 100% technical traceability.

### 6.3 Clean Bill of Health format (Audit Phase 11, only if the Closure Loop, §8, reaches a genuine end-state)

States explicitly: total findings by severity (should be zero Critical/High), every remaining Low individually justified and presented for accept/reject, what was tested and at what scale (site count per tier, passes per site, concurrency levels, fault-injection scenarios, attack fixture count), what was *not* tested and why (be honest about coverage gaps even in a clean report), and the exact regression suite counts at sign-off.

### 6.4 Severity rubric

- **Critical**: SSRF/security boundary weakness; data corruption; a false "clean"/"silent success" on an actual attack pattern; a crash that takes down other concurrent work; any regression against an existing passing test.
- **High**: a documented spec requirement simply not met (a true Gap, not Deferred-by-design); a resource leak or unbounded growth under sustained/concurrent load; a false positive that would alert operators on legitimate, common site behavior; a measured performance bottleneck making the system impractical at realistic scale.
- **Medium**: a partial implementation that degrades gracefully but doesn't meet the original intent; a below-target stress-test result *that has been individually root-caused per Rule 19* and disposed as Fix-candidate; a docs/infra drift that could mislead an operator but doesn't cause incorrect system behavior.
- **Low**: cosmetic issues, unused-but-harmless stored fields, minor log-message inaccuracies, an individually-justified Accepted-risk case (Rule 19) that the user still gets to see and can reject.

---

## 7. THE CONCURRENCY/SCALE/CHAOS TEST REGIME (mandatory minimums, Audit Phases 6–7)

- Minimum three load levels for concurrency testing (configured limit, 2×, 5×), each run a minimum of three times (Rule 18).
- Minimum soak duration: at least 50 sequential capture+scan cycles on one worker without restart, or longer if the codebase's own worker-recycle policy is longer — state which and why.
- Minimum six distinct fault-injection scenarios, each run a minimum of three times.
- Every number reported with the measurement method stated (profiler used, sample size, environment) — a single unrepeated observation is not a measurement.

---

## 8. THE DECISION GATE AND THE CLOSURE LOOP

### 8.1 When PROMPT-004 is authored (Zero-Regression & First-Pass Resolution Standard)

At Audit Phase 10, author `PROMPT-004-<short-name>.md` (plus its seeded log file and Phase 1 kickoff prompt) **if and only if**:
- Any Critical finding exists, or
- Any High finding exists, or
- Three or more Medium findings exist within the same subsystem.

**PROMPT-004 Charter & Engineering Perfection Mandate:**
PROMPT-004 must be engineered to resolve all confirmed issues in a **single, flawless pass** so that the need for a PROMPT-005 is eliminated:
- **Pre-Engineered Fix Blueprints:** For every finding, Phase 10 must specify the exact target files, exact contract logic (e.g. byte-hash exclusion rule), and exact test criteria so the implementing agent executes a proven blueprint without guessing.
- **Mandatory Red-Green-Refactor Flow:** Every phase in PROMPT-004 must: (1) prove the bug reproduces with a failing test on current code, (2) apply the surgical fix, (3) prove the test now passes, and (4) run full regression suites to guarantee zero side effects.
- **Documentation & Scripts Remediation:** PROMPT-004 is contractually mandated to resolve all documentation drift (`docs/*.mdx`, `docs.json`, `README.md`) and repair all PowerShell scripts (`scripts/validate.ps1`, `install.ps1`, `diagnostics.ps1`, `update.ps1`) discovered in Audit Phase 9, ensuring the entire product matches reality.
- **Automated Stress Re-Verification:** PROMPT-004's final sign-off phase must execute `backend/tools/run_stress_catalog.py` against all previously failing sites (3 passes each) to achieve 100% clean passes.
- **Preserve Prior Art:** Preserve every "Prior Art" constraint from PROMPT-002 §4 (SSRF policy, hash-gate contract, rule floors, degradation signaling) as permanent, non-negotiable constraints.
- **Order phases by dependency:** Database schemas and models first, capture and detection logic second, API routers and tasks third, frontend surfaces fourth, and final Re-Audit sign-off last.
- **Rule 19 discipline:** Every finding closed must be verified by reproduction of the original finding's repro steps.

### 8.2 The Closure Loop — mandatory final phase of every remediation prompt

**This is the mechanism that prevents this effort from ending the way PROMPT-002 ended.** Every remediation prompt this effort authors (PROMPT-004, and any PROMPT-005+ it in turn spawns) must include, as its final mandatory phase, a **Re-Audit & Sign-Off phase** that:
1. Re-runs the full Rule-5-equivalent regression suite.
2. Re-executes the full three-tier stress-test catalog at least once in full, plus a minimum of two additional passes specifically on every site/scenario that previously failed (Rule 18's repeatability standard, applied to the fix).
3. Re-verifies every specific finding this remediation round claimed to fix, using the *exact original reproduction* that first surfaced it — not a new, looser test that happens to pass.
4. Explicitly checks for regressions the fix itself may have introduced elsewhere (a capture fix reintroducing a detection false positive, a detection threshold change reintroducing a capture-side inconsistency, etc.) — this is exactly the kind of cross-subsystem interaction a single narrowly-scoped remediation phase is structurally prone to missing.
5. Produces its own Findings Register using this file's severity rubric (§6.4) and applies this file's Decision Gate (§8.1) to itself.

**If that Re-Audit & Sign-Off phase surfaces any Critical/High finding, or a repeated/reintroduced Medium cluster, it must author the next remediation prompt (PROMPT-005, then PROMPT-006, and so on) using this identical §8 mechanism, and the loop continues.** The loop terminates only when a Re-Audit & Sign-Off phase produces a genuine Clean Bill of Health per §6.3: zero Critical/High findings, and every remaining Low finding individually justified and explicitly presented to the user for their own accept/reject decision — never a quiet aggregate close-out.

### 8.3 When no remediation prompt is warranted at all

If Audit Phase 10 finds nothing meeting the §8.1 bar, produce the Clean Bill of Health report directly (§6.3) and explicitly recommend re-running this same PROMPT-003 audit again after a stated interval or after the next significant codebase change — external site behavior, bot-protection vendors, and load patterns all drift, so "clean today" is not "clean forever."

---

## 9. KICKOFF PROMPTS

### First kickoff (paste into a new chat to start Audit Phase 1)

```
Before anything else: read C:\Users\Ns8pc\Music\WARDRESS\Prompts\Pending\Finders\PROMPT-003\PROMPT-003-capture-detection-audit-and-stress-hardening.md COMPLETELY, start to finish — every rule, every audit phase spec, the severity rubric, the closure-loop mechanism in §8. Do not skim. Do not jump to a section.

Then read C:\Users\Ns8pc\Music\WARDRESS\Prompts\Pending\Finders\PROMPT-003\PROMPT-003-IMPLEMENTATION-LOG.md COMPLETELY (it may be empty except the entry-format header if this is the first session — that's expected).

Then read C:\Users\Ns8pc\Music\WARDRESS\Prompts\Pending\Finders\PROMPT--002\PROMPT-002-capture-hardening-and-detection-accuracy-v2.md — at minimum Phases 1–7 and §0, §1, §4 (the Prior Art constraints), since Audit Phase 1 verifies those phases.

Then read C:\Users\Ns8pc\Music\WARDRESS\Prompts\Pending\Finders\PROMPT--002\PROMPT-002-IMPLEMENTATION-LOG.md — the Phase 1 through Phase 7 entries in full, including every "Key design decision," "Residual risk / follow-ups," and "New leads observed" — these are your starting leads, not footnotes.

Then read the ACTUAL current code, cold, tracing every caller/callee:
- backend/worker/stealth.py
- backend/worker/fetcher.py
- backend/worker/probe.py
- backend/worker/page_prepare.py
- backend/worker/banner_dismiss.py
- backend/worker/artifacts.py
- every test file named in the Phase 1-7 log entries

IMPORTANT: A fresh Wardress install is running in Docker and available for you to test against. Use it for anything requiring a real browser or real sites. If containers are not up, ASK me to start them — do not run install/uninstall scripts yourself.

Remember Rule 1: this is diagnosis, not repair. Do not modify production code to fix anything you find — log it as a finding with a proposed remedy category. Remember Rule 19: any below-target result needs an individually-investigated root cause per case, never an aggregate close-out.

Execute Audit Phase 1 now: build the full traceability matrix for capture Phases 1-7, per §2 and §4 of PROMPT-003. Pay specific attention to the two named open questions in the Phase 1 spec (the "changed vs clean" deviation, and the individually-investigated-or-aggregate root causes for the three below-target capture categories).

When done: append your audit log entry per §6.1, commit (test-file/log changes only, do not push), then output the kickoff prompt for Audit Phase 2, then stop.
```

### Subsequent kickoffs

> [!CAUTION]
> **ZERO-SKIP KICKOFF ENFORCEMENT (Rule 20)**:
> An agent completing Phase `N` is **strictly prohibited from skipping or guessing the next phase**.
> Before generating any kickoff prompt, the agent MUST:
> 1. Verify that the current phase is committed and logged as `[DONE]` in `PROMPT-003-IMPLEMENTATION-LOG.md`.
> 2. Consult §4's Phase Map and look up the exact `Mandatory Next Phase:` line for `[Phase N+1 of 17]`.
> 3. Verify that the next phase header contains the sequential tag `[Phase N+1 of 17]`.
> 4. Ensure the kickoff prompt explicitly starts with: `You are executing ONLY Audit Phase <Name> [Phase N+1 of 17]`.
> Any kickoff prompt that jumps ahead (such as jumping from Phase 4C to 5A, skipping 4D, 4E, or 4F) is an automatic protocol violation.

The standard pattern for every kickoff prompt is:
read PROMPT-003 fully → read PROMPT-003-IMPLEMENTATION-LOG.md fully → read `PROMPT-003-stress-site-catalog.md` if the next phase is 5A/5B/5C/6/7/8 → read the specific PROMPT-002 sections + code files this phase targets, per §4 → execute this phase per §2, honoring Rule 18 (repeatability) and Rule 19 (no aggregate acceptance) wherever they apply → generate the next phase's kickoff prompt strictly for `Phase N+1` when done.

**Audit Phase 10 [Phase 17 of 17]'s kickoff-prompt output is different**: per §8, it either hands the user the ready-to-paste PROMPT-004 Phase 1 kickoff prompt (if warranted), or the Clean Bill of Health report with a recommended re-audit interval. If a later remediation prompt's own Re-Audit & Sign-Off phase (§8.2) in turn spawns PROMPT-005+, that phase's kickoff-prompt output follows the identical pattern one level up.

---

## 10. A NOTE ON DISCIPLINE

PROMPT-002 was built on the premise that depth beats speed when the thing being built is a security-relevant monitoring system, and it delivered real, tested capability. But it also closed with an aggregate-accepted shortfall and an unresolved deviation quietly logged as a footnote — a reasonable place for a single 14-phase effort to stop, but not a reasonable place for the *project* to stop. This effort's entire purpose is to be the outside eye that checks whether "the tests are green" actually means "the system does what it was supposed to do" against the real, hostile, ever-changing world — and, via the Closure Loop in §8, to keep that check running until the answer is genuinely yes, not until someone declares it yes. Be rigorous, be honest about severity in both directions, hold every below-target number to its individual root cause, and never let "good enough in aggregate" be the last word.
