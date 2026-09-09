# PROMPT-003 — Capture & Detection Audit, Gap-Closure Discovery, and Stress Hardening (v2 — Closure-Loop Edition)

**READ THIS ENTIRE FILE, START TO FINISH, BEFORE DOING OR WRITING ANYTHING.**
Do not skim. Do not jump to a phase. Do not begin work after reading only the phase list. This file defines rules that apply to *every* phase, and violating them invalidates the audit. If you have already read it once earlier in this session, re-read it anyway — you cannot rely on a memory summary of your own instructions.

---

## 0. WHAT THIS IS

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

### 0.2 Why twenty-one phases, and why they must stay small

Exactly the reasoning PROMPT-002 gave for going from 6 phases to 14 (its own §0): the moment a session tries to do too much — read the spec, read the log, read the code, enumerate edge cases, run tests, *and* write a comprehensive findings entry — context runs out before the last of those gets full attention, and output quality degrades in a way that looks like completion but isn't. The same logic drives this file's phase count well past a first-draft thirteen once the real codebase size became clear (592 files, ~121K lines, per the project structure inventory this file's authoring was checked against): a single "fresh-eyes code audit" phase covering capture, detection, data model/migrations, API routers, task orchestration/alert delivery, AI provider integration, *and* frontend surfaces all at once would repeat that exact mistake on a much larger scale, so those are seven separate phases (3, 4, 4B–4G) instead of one or two. The stress-test catalog is similarly split into three tiers across three separate phases (§4, Audit Phases 5A/5B/5C) for the same reason. Every phase in the map below is sized to fit in one context window doing one thing thoroughly. If a phase turns out bigger than expected anyway, Rule 8 still applies: finish a smaller, explicitly-scoped subset correctly and say so, rather than rushing the whole thing shallowly.

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
13. **Trust nothing you have not personally re-verified.** Every number in `PROMPT-002-IMPLEMENTATION-LOG.md` is a self-reported claim — re-measure it before citing it as ground truth. A disagreement between the log and reality is itself a finding.
14. **Infrastructure and docs are read for drift, not written to.** Drift found here is a finding for the remediation prompt, not something to quietly correct now.
15. **Fresh Docker install available for testing**, exactly as PROMPT-002 Rule 14. **Do not run `scripts/install.ps1` or `scripts/uninstall.ps1` yourself.** If containers are not up, ASK the user to start them.
16. **Severity discipline.** Every finding gets exactly one severity, chosen honestly against §6.4 — do not inflate, do not deflate.
17. **Liberty to brainstorm beyond the log — mandatory, not optional.** The traceability matrix and log-derived leads are your *floor*, not your *ceiling*. In every phase, think past "does this meet what PROMPT-002 said" and ask "what would make this subsystem genuinely better, more capable, or more resilient — including things neither PROMPT-002 nor its log ever imagined?" Capture these in the separate **Opportunities / Innovation Ideas** log field (§6.1) — not severity-scored, not required to trigger anything on their own, but every one written down with enough reasoning that the user can evaluate it later. Do not silently filter an idea out because it seems out of scope; log it and let the user decide. The only constraint is Rule 1 — brainstorm and log freely, never implement against production code during an audit phase.
18. **No single-pass proof of reliability.** A stress-test result (a site capture, a concurrency run, a chaos-injection scenario) observed exactly once is a data point, not a finding of "works" or "doesn't work." Every site in the stress-test catalog, every concurrency load level, and every chaos scenario must be run a **minimum of three total passes**, ideally spread across more than one session/time-of-day so transient network/vendor-side conditions don't masquerade as your system's behavior. Record the outcome of every pass and the variance across them — "3/3 succeeded, consistent 18-22s capture time" is a finding; "succeeded once" is not.
19. **No aggregate acceptance of below-target results.** Per §0.1: every below-target metric must be broken down to individually-investigated root causes per failing case, each with an explicit Fix-candidate or Accepted-risk disposition. An aggregate percentage with no per-case breakdown is an incomplete phase, not a finding.

---

## 2. THE AUDIT GAUNTLET LOOP (mandatory for every phase)

**Step 1 — INTAKE.** Read this entire file. Read `PROMPT-003-IMPLEMENTATION-LOG.md` completely (all prior audit-phase entries). Read the companion `PROMPT-003-stress-site-catalog.md` if this phase touches capture/stress testing. Read the specific PROMPT-002 phase spec(s) and log entries relevant to this phase's assigned subsystem (§4).

**Step 2 — REBUILD THE TRACEABILITY MATRIX ROW BY ROW** (traceability phases) or **EXECUTE THE ASSIGNED STRESS/AUDIT WORK** (all other phases), per §4's per-phase instructions.

**Step 3 — READ THE LIVE CODE COLD** where applicable — set prior claims aside and read the actual current files as if PROMPT-002 never happened, tracing every function, caller, exception path, and cross-phase interaction.

**Step 4 — ENUMERATE NEW EDGE CASES, HARDER THAN BEFORE.** Do not just re-check PROMPT-002's list. Add adversarial cases it didn't consider.

**Step 5 — TEST, WITH REPEATABILITY (Rule 18).** Write hermetic tests where automatable; use the live Docker install for anything requiring a real browser or real sites; run every stress scenario the minimum number of passes Rule 18 requires; document manual verification honestly where automation isn't possible.

**Step 6 — CLASSIFY AND LOG, WITH NO AGGREGATE SHORTCUTS (Rule 19).** Every finding gets a severity (§6.4), a precise reproduction, a root-cause explanation, file/line(s), and a proposed remedy sketch. Every below-target metric gets the per-case breakdown Rule 19 requires. Append to `PROMPT-003-IMPLEMENTATION-LOG.md` per §6.1.

**Step 7 — REGRESSION CHECK.** Confirm new test files did not regress the existing suites (Rule 5).

**Step 8 — COMMIT AND HANDOFF.** Commit per Rule 9, output the next phase's kickoff prompt, stop.

---

## 3. MANDATORY INTAKE READING (every phase)

1. This file, completely.
2. `PROMPT-003-IMPLEMENTATION-LOG.md`, completely — every prior audit finding, especially anything flagged "reopen candidate" by a later phase.
3. `PROMPT-003-stress-site-catalog.md`, when the phase touches capture or stress testing (Audit Phases 5A/5B/5C, 6, 7, 8).
4. `PROMPT-002-capture-hardening-and-detection-accuracy-v2.md` — at minimum the phase(s) this audit phase verifies, but skim the whole thing at least once across the effort since cross-phase interactions are exactly what individual PROMPT-002 sessions couldn't see.
5. `PROMPT-002-IMPLEMENTATION-LOG.md` — the specific phase entries you're verifying, in full, including "Key design decisions," "Residual risk / follow-ups," and "New leads observed" — your highest-value starting leads.
6. **For Phases 3, 4, 4B–4G: the Audit Phase 2B inventory entry in `PROMPT-003-IMPLEMENTATION-LOG.md`.** That inventory — not the fixed file lists written into §4 of this document when it was authored — is the authoritative target-file source. If Phase 2B hasn't run yet, do not substitute your own guess at scope; that is what Phase 2B exists to prevent.
7. Every current source file in the assigned subsystem, completely, tracing callers/callees.

---

## 4. AUDIT PHASE MAP (21 phases)

Ordering: traceability first, then a prior-history sweep and a full-repository inventory (so nothing outside PROMPT-002's own scope, or older than it, gets silently excluded), then fresh-eyes code audits — capture, detection, and the five additional subsystems the inventory phase pulls in (data model/migrations, API routers/RBAC, task orchestration/alert delivery, AI provider integration, and frontend surfaces — deliberately excluding the separate operations-agent subsystem, per explicit scoping) — then the three-tier stress-test catalog, then concurrency/chaos, then adversarial detection, then performance, then infra/docs, then final consolidation and the closure decision.

### AUDIT PHASE 1 — Traceability Matrix: Capture Phases (PROMPT-002 Phases 1–7)
**Target files:** `backend/worker/stealth.py`, `backend/worker/fetcher.py`, `backend/worker/probe.py`, `backend/worker/page_prepare.py`, `backend/worker/banner_dismiss.py`, `backend/worker/artifacts.py`, every test file named in Phases 1–7's log entries (including `test_banner_dismiss.py`, `test_capture_evidence.py`, `test_cloudflare_detection.py`, `test_fetcher_retry.py`, `test_page_prepare.py`).
**Do:** Full traceability matrix for Phases 1–7 (§2 Step 2). Specifically:
- Confirm whether the Phase-14-flagged "changed, not clean" deviation on benign dynamic content is resolved anywhere, or still open — if open, it is a Gap, not a footnote.
- Demand individually-investigated, per-site root causes for every one of the below-target Phase-13 categories (Cloudflare 5/6, Lazy 8/11, E-commerce 3/6). An aggregate "3 sites failed" with no per-site cause is itself a Gap under Rule 19.
- Verify every "Never raises" contract (`auto_scroll_page`, `wait_for_content_stable`, banner dismissal) against the actual exception-handling code.

### AUDIT PHASE 2 — Traceability Matrix: Detection Phases (PROMPT-002 Phases 8–14)
**Target files:** `backend/worker/detection/*.py` (`cloaking.py`, `dom.py`, `fusion.py`, `metadata.py`, `normalize.py`, `pipeline.py`, `semantics.py`, `signatures.py`, `suppress.py`, `visual.py`, `types.py`), `backend/worker/hashing.py`, `backend/tools/build_regression_corpus.py`, `backend/tools/refit_fusion_model.py`, `backend/worker/detection/training/regression_corpus.json` and `fusion_model.json` (the data these tools generate), `backend/tests/test_detection_regression.py`, `backend/tests/test_detection_e2e.py`, `backend/tests/test_noise_floor.py`, every other test file named in Phases 8–14's log entries (including `test_csp_nonce_normalization.py`, `test_dom_content_churn.py`, `test_detection_fusion_pipeline.py`, `test_detection_normalize.py`, `test_fusion_refit.py`).
**Do:** Full traceability matrix for Phases 8–14. Specifically:
- Build an attack-technique taxonomy (defacement, asset-swap, SEO-spam link farm, script-injection, non-Latin takeover, credential-phishing overlay, subtle single-word tampering, image-only tamper with unchanged DOM, redirect-based cloaking, staged/time-delayed payloads) and mark each as Represented / Assumed-covered-by-similarity / Genuinely absent in the 152-row regression corpus.
- Re-verify current-code status of both Phase 14 "new leads observed" (`ScanFinding` rows not carrying the degraded flag; unused stored `capture_meta["headers"]`) and assess real operator-facing impact.
- Check whether `MATERIAL_CHANGE_RISK`/`NOISE_FLOOR` have any test proving generalization beyond the specific fixtures used to derive them (an overfitting risk).
- Check `backend/tools/build_regression_corpus.py` and `refit_fusion_model.py` for correctness — these two scripts *generate* the 152-row corpus and the fusion thresholds that everything else is validated against. A bug here would make the downstream validation self-consistent but wrong. This is meta-verification: don't just trust that the generator ran once and produced sane output.

### AUDIT PHASE 2B — Full Codebase Inventory & Blast-Radius Mapping
**Target: the entire repository, not a fixed file list — this phase's job is to produce that list for everything after it.**
**Do:** Walk `backend/`, `frontend/`, `docs/`, `scripts/`, and the repo root completely (directory listing, then per-file classification — do not skip a directory because its name sounds unrelated; confirm, don't assume). For every file, assign exactly one classification:
- **In blast radius — capture/detection core**: already named in Phases 1–4's target lists.
- **In blast radius — orchestration, data & scheduling**: `backend/worker/scan_tasks.py`, `remediation_tasks.py`, `alert_tasks.py`, `beat_tasks.py`, `celery_app.py`, `db.py`; `backend/app/models.py`, `schemas.py`, `capture.py`, `scanning.py`, `db.py`; every file under `backend/alembic/versions/`.
- **In blast radius — API routers, auth & RBAC**: every file in `backend/app/routers/` except `agent.py` (see the explicit exclusion below) — `alerts.py`, `apikeys.py`, `artifacts.py`, `audit.py`, `auth.py`, `health.py`, `imports.py`, `remediation.py`, `reports.py`, `settings.py`, `sites.py`, `users.py` — plus `backend/app/deps.py`, `ratelimit.py`, `security.py`, `audit.py`, `apikeys.py`.
- **In blast radius — alert & remediation delivery**: `backend/app/alerting.py`, `remediation.py`, `explain.py`, `reporting.py`, `site_icons.py`, `backend/app/templates/email/*.html`, `templates/report/report.html`. **`backend/worker/telegram_bot.py` is conditional, not automatic** — the README describes its `.env` token as being "for interactive system queries," which points to it being the ops-agent's chat transport rather than an alert-delivery channel, but confirm this by reading the file rather than assuming either way. If it delivers scan/finding/alert notifications to operators, it belongs here. If its only role is the interactive agent chat, it belongs in the excluded ops-agent bucket below.
- **In blast radius — AI provider integration**: `backend/app/ai_catalog.py`, `ai_config.py`, `ai_migration.py`, `ai_ollama.py`, `ai_startup.py`, `llm.py`; `backend/worker/llm_escalation.py`. This is in scope specifically because `llm_escalation.py` matches the README's "request a second opinion from a configured AI model" on ambiguous verdicts — it is part of the detection/verdict pipeline, not the ops-agent. The AI-provider config files (`ai_catalog.py` etc.) are shared infrastructure that both the escalation path and the (excluded) ops-agent draw from; audit them only for what `llm_escalation.py` needs from them, not for how the ops-agent happens to use them.
- **Excluded — operations agent & its interactive Telegram transport (separate project, not in scope for this effort):** `backend/app/agent/context.py`, `engine.py`, `guard.py`, `tools.py`; `backend/app/routers/agent.py`; `docs/.mintlify/skills/wardress-operations/SKILL.md` and `references/REFERENCE.md`; `docs/agent.mdx`, `agent-skill.mdx`; and `telegram_bot.py` unless the check above puts it in the alert-delivery bucket instead. **This exclusion has one explicit escalation path**: if, in the course of any other phase, you find that this subsystem reads or writes capture/scan/baseline/finding data through a path that bypasses the routers and RBAC boundary Phase 4C already audits — e.g., a tool in `tools.py` that talks to the database directly instead of going through the normal API layer — log that as a Finding under whichever phase found it (most likely 4C or 4B) and note in the log that it surfaced from agent code, so Phase 11 can decide whether a dedicated follow-up phase is warranted. Do not proactively audit the agent's own prompting, reasoning, or conversational logic — only escalate if it demonstrably touches the capture/detection dataflow in a way not already covered.
- **In blast radius — frontend surfaces**: React components/hooks that render capture health, scan results, verdicts, or alert history, plus the API-client code that fetches this data for them (the `capture-health.test.tsx` flake noted in PROMPT-002 Phase 14's log lives in this bucket — flag it for revisit).
- **In blast radius — dependencies/config/supply-chain**: `backend/pyproject.toml`/`uv.lock`, `frontend/package.json`/`pnpm-lock.yaml`, `backend/Dockerfile.app`, `Dockerfile.worker`, `docker-compose.yml`, `.env.example`, `.github/workflows/ci.yml`, `static.yml`, `backend/tools/check_torch_osv.py` (confirm it's actually wired into CI, not dead code).
- **Out of blast radius, pending confirmation**: `landing/` (static marketing site) and `walkthrough/` (standalone Mermaid pipeline-explainer app) look unrelated to the live monitoring dataflow — confirm this rather than assume it, and if confirmed, still flag `walkthrough/`'s diagrams for a Low-priority docs-drift check in Phase 10 (a pipeline explainer that quietly goes stale is exactly the kind of thing an operator trusts without re-checking).
For every file landing in any "in blast radius" bucket that was **never a target file in any PROMPT-002 phase (1–14)** — which is most of the list above — flag it explicitly as **highest priority** for the fresh-eyes phases below, since nobody in either effort has looked at it yet.
**Output:** append the full classified inventory to the audit log as this phase's primary artifact, including the resolved Telegram-bot classification with your reasoning. This inventory — not the fixed lists written into §4 of this file when it was authored — is the authoritative target-file source for every fresh-eyes phase (3, 4, 4B–4G). If the inventory surfaces an in-radius file this document didn't anticipate a phase for, note which phase should absorb it (or that a further split is needed) rather than silently leaving it unassigned.

### AUDIT PHASE 2C — Prior-History Sweep (Pre-PROMPT-002 Audit Findings)
**Do not read these files in full — they are enormous (790KB / 268KB) and doing so will exhaust the context window before this phase can do anything else.**
**Target:** `Prompts/Done/Finders/WARDRESS_PARANOID_AUDIT_PROTOCOL.md`, `WARDRESS_PARANOID_FIX_PROTOCOL.md`, `Prompts/Done/Finders/PROMPT-001-restore-imagery-and-audit-filters.md`, and their logs `Prompts/Done/Loogers/WARDRESS_AUDIT_FINDINGS.md` (268KB) and `WARDRESS_FIX_LOG.md` (790KB) — an earlier fix effort that predates PROMPT-002 entirely.
**Do:** Use targeted search (grep-style, not full reads) against the log files for language indicating something was left open: "TODO", "deferred", "not implemented", "residual", "known issue", "out of scope", "follow-up", "unresolved", "does not fully". For every hit, read only the surrounding context (a few dozen lines), determine whether it was later closed by PROMPT-002 (cross-check against the PROMPT-002 log) or is still open today. Anything still open and still relevant to capture/detection is a Gap for this audit, sourced from before either of the two efforts you already know about — treat it with the same rigor as anything found fresh. This phase exists because "read PROMPT-002" is not the same as "read everything that led up to PROMPT-002," and a prior effort's unresolved item is exactly the kind of thing that falls through the cracks between two large, separately-scoped fix efforts.

### AUDIT PHASE 3 — Fresh-Eyes Code Audit: Capture Pipeline
**Target files:** the capture-core files named in Phase 1, **plus** whatever Phase 2B's inventory added to this bucket — cold read, ignore PROMPT-002/log this session.
**Do:** Full Step 3. Hunt for: resource leaks on every exception path; state leakage across retry attempts (Phase 6 retrying Phase 3/5's scroll+banner state); the Cloudflare wait-and-retry (Phase 2) racing the overall navigation timeout; the height cap (Phase 4) interacting with scroll-to-bottom-then-top (Phase 3); any "silent lie" pattern (caught exception, logged, function still returns success); memory growth across many sequential captures in one worker process.

### AUDIT PHASE 4 — Fresh-Eyes Code Audit: Detection Pipeline
**Target files:** the detection-core files named in Phase 2, **plus** whatever Phase 2B's inventory added to this bucket — cold read, ignore PROMPT-002/log.
**Do:** Full Step 3. Hunt for: ways to defeat the "layer 4 always runs unconditionally" contract via missing/malformed inputs; rule-floor boundary behavior at exact trigger thresholds (0.849 vs 0.851, etc.); over-normalization letting a real attack that happens to resemble a normalized pattern slip through; numerical stability on malformed-but-plausible attacker input (huge diffs, non-UTF8, extremely long minified lines).

### AUDIT PHASE 4B — Fresh-Eyes Code Audit: Data Model, Schema & Migrations
**Target files:** `backend/app/models.py` (904 lines), `schemas.py` (1015 lines), `capture.py`, `scanning.py`, `db.py`, and every file under `backend/alembic/versions/` — 15 migrations, most recently `o9q1r2s3t4u5_scans_capture_evidence.py` (the capture-evidence migration, directly tied to PROMPT-002's work) and `k5l6m7n8p9q1_baselines_inflight_unique_index.py` (an in-flight-baseline uniqueness constraint — cross-reference against Phase 6's concurrency findings).
**Do:** Full Step 3, cold. Hunt for: a migration that doesn't correctly backfill/default a new column for pre-existing rows (cross-check every recent migration against PROMPT-002's own backward-compatibility claims — Rule 11 of this file makes this a read, but a migration bug is exactly the kind of thing that silently breaks that claim); a model/schema mismatch that would let invalid data reach the database or leak more than the API contract intends; whether the in-flight-baseline unique index actually prevents the race it was named for, under real concurrent load (feed this into Phase 6).

### AUDIT PHASE 4C — Fresh-Eyes Code Audit: API Routers, RBAC & Rate Limiting
**Target files:** every file in `backend/app/routers/` **except `agent.py`** (excluded per Phase 2B — the ops-agent is out of scope) — `alerts.py`, `apikeys.py`, `artifacts.py`, `audit.py`, `auth.py`, `health.py`, `imports.py`, `remediation.py`, `reports.py`, `settings.py` — 1107 lines, `sites.py` — 583 lines, `users.py` — plus `backend/app/deps.py`, `ratelimit.py`, `security.py`, `audit.py`, `apikeys.py`.
**Do:** Full Step 3, cold. Hunt for: any scan/finding/alert/remediation route returning data without checking it belongs to the requesting account/site; any route not correctly enforcing the Admin/Analyst/Viewer boundary from the README's access table (test each route against all three roles, not just Admin); rate-limit bypass paths (a route that forgets the dependency, or a limiter keyed wrong under concurrent requests from one client); auth/session edge cases (`auth.py` is 353 lines — token refresh, lockout, session invalidation deserve the same "never raises incorrectly" scrutiny capture code got in PROMPT-002). **Note for §8's escalation path:** because RBAC here governs every caller equally, confirming it's airtight here is what actually matters for the excluded agent too — you don't need to read agent code to know whether it can bypass authorization, since if these routes are correctly enforced, nothing calling through them can bypass anything.

### AUDIT PHASE 4D — Fresh-Eyes Code Audit: Task Orchestration, Alert & Remediation Delivery
**Target files:** `backend/worker/scan_tasks.py` (491 lines, end to end — not just the two functions PROMPT-002 named), `remediation_tasks.py`, `alert_tasks.py`, `beat_tasks.py` (447 lines — the Celery Beat scheduler that actually drives "significant changes shorten the scan interval," per the README), `celery_app.py`; `backend/app/alerting.py`, `remediation.py`, `explain.py`, `reporting.py`, `site_icons.py`; `backend/app/routers/remediation.py`; `templates/email/*.html`; **and `telegram_bot.py` only if Phase 2B classified it as an alert-delivery channel rather than the ops-agent's chat transport.**
**Do:** Full Step 3, cold. Hunt for: a scan/baseline row left inconsistent by a crash mid-write; an alert enqueued but never confirmed delivered, or delivered twice; whether the remediation webhook can fire without the human-approval step the README guarantees end-to-end — this spans `routers/remediation.py` + `app/remediation.py` + `worker/remediation_tasks.py`, so trace the full call chain, not just one file, since a cross-file contract like this is exactly what a single-file review misses; whether `beat_tasks.py`'s interval-shortening logic can starve or double-schedule a site under load; whether `explain.py`'s human-readable explanations can misrepresent the actual detection evidence (a wrong explanation is its own kind of false signal, even if the underlying verdict is correct); whether `site_icons.py`'s SSRF re-validation actually covers every redirect hop, as the README claims; Celery task retry/idempotency — does a re-queued task re-run side effects (re-sending an alert) that shouldn't repeat?

### AUDIT PHASE 4E — Fresh-Eyes Code Audit: AI Provider Integration & Second-Opinion Path
**Target files:** `backend/app/ai_catalog.py`, `ai_config.py`, `ai_migration.py`, `ai_ollama.py`, `ai_startup.py`, `llm.py` (504 lines); `backend/worker/llm_escalation.py`; the AI-provider portion of `routers/settings.py`. **This phase exists because `llm_escalation.py` is part of the detection/verdict pipeline, not because the ops-agent needs auditing — the ops-agent is explicitly out of scope per Phase 2B.** Audit these shared AI-provider files only for what the escalation path needs from them.
**Do:** Full Step 3, cold. Hunt for: whether a stuck or failing AI provider blocks the scan pipeline instead of degrading gracefully (this is the "second opinion on ambiguous verdicts" path the README describes — a hang here could silently delay every ambiguous-verdict scan behind it); whether Fernet encryption of provider API keys is actually applied on every write path, not just the common one; correctness of `ai_migration.py`'s provider-migration logic; whether the auto-provisioned local Ollama provider on fresh install actually degrades safely if Ollama isn't running yet (the README notes it must be started manually).

### AUDIT PHASE 4F — Fresh-Eyes Code Audit: Frontend Capture & Detection Surfaces
**Target files:** Phase 2B's "frontend surfaces" bucket — every component/hook rendering capture health, scan results, verdicts, or alert history, and the API-client code feeding them.
**Do:** Full Step 3, cold. Specifically revisit the timing-sensitive `capture-health.test.tsx` flake noted in PROMPT-002 Phase 14's log (root-cause it properly rather than re-noting it) and check for: a verdict/severity color or label that could mislead an operator about degraded-vs-measured state (tying back to Phase 2's "does `ScanFinding` carry the degraded flag" finding — if the backend fix lands in a later remediation prompt, does the frontend actually have a place to render it?); stale-data races (a component showing a cached prior verdict while a new scan is in flight); accessibility/i18n issues that would matter for an operator scanning non-Latin-script target sites.

### AUDIT PHASE 4G — Dependency, Configuration & Supply-Chain Audit
**Target files:** `backend/pyproject.toml` + `backend/uv.lock`, `frontend/package.json` + `pnpm-lock.yaml`, `backend/Dockerfile.app`, `Dockerfile.worker`, `docker-compose.yml`, `.env.example`, `.github/workflows/ci.yml`, `static.yml`, `backend/tools/check_torch_osv.py`.
**Do:** Check every dependency the capture/detection dataflow relies on (Playwright, playwright-stealth, FastAPI, Celery, the embedding/model library, and their frontend equivalents) against currently known vulnerabilities and available stable versions — flag anything meaningfully behind or with a disclosed CVE. Confirm `check_torch_osv.py` is actually invoked in `ci.yml`, not dead code sitting in `tools/`. Check configuration for secrets handled insecurely, default/sample credentials left active, debug flags that could be enabled in production, and image-pinning discipline (floating `latest` tags vs. pinned versions) in Docker artifacts.

### AUDIT PHASE 5A — Stress-Test Catalog, Tier A: Broad Real-World Baseline
**Do not touch code.** Execute Tier A of `PROMPT-003-stress-site-catalog.md` (the full curated real-world list — news, entertainment, government, reference, developer/tech sites) against the live Docker install, per Rule 18's repeatability requirement (minimum 3 passes per site). This tier exists to catch surprises at breadth/scale that a smaller validation set (Phase 13's 74 sites) could miss purely by not including enough real, popular, actively-maintained sites. Record success/fail, capture time, failure mode per pass, and variance across passes.

### AUDIT PHASE 5B — Stress-Test Catalog, Tier B: Advanced Bot-Protection & Hard Categories
**Do not touch code.** Execute Tier B of the catalog (Akamai Bot Manager, DataDome, PerimeterX/HUMAN, AWS WAF challenge, Cloudflare Enterprise/Turnstile beyond the free JS-challenge tier, harder e-commerce, harder lazy-load) — the categories PROMPT-002 Phase 13 explicitly could not or did not push into. Same repeatability requirement. For every failure, apply Rule 19: individual root cause, not an aggregate rate.

### AUDIT PHASE 5C — Stress-Test Catalog, Tier C: Exotic & Edge Categories
**Do not touch code.** Execute Tier C of the catalog (WebSocket/live-push content, PWA/service-worker sites, extremely large pages, slow/high-latency origins, auth-adjacent soft-blocked pages, infinite-scroll feeds, heavy-hydration frameworks, deep RTL/mixed-script pages). Same repeatability requirement and Rule 19 discipline.

### AUDIT PHASE 6 — Concurrency & Scale Stress Testing
**Do not touch code.** Per §7's mandatory minimums: at least three load levels (configured limit, 2×, 5×), each run at least three times (Rule 18); a soak run of at least 50 sequential capture+scan cycles (or longer if the worker-recycle policy demands it — state which); measure queueing behavior, memory/CPU under load, DB connection-pool/lock-contention behavior under concurrent scan writes. Every reported bottleneck gets a number, a measurement method, and a sample size.

### AUDIT PHASE 7 — Chaos & Failure-Injection Testing
**Do not touch code.** Minimum six distinct hermetic fault-injection scenarios (mid-capture crash, DNS/TLS failure, slow-loris-style non-terminating response, malformed/oversized HTTP response, redirect loop crossing the SSRF boundary mid-chain, pathologically large DOM/page), each run at least three times (Rule 18). Classify each as: fails loudly and correctly categorized (good), fails silently as if it succeeded (Critical), or crashes the worker/takes down other concurrent work (Critical).

### AUDIT PHASE 8 — Adversarial Detection Accuracy Stress Test
**Do not touch code.** Using Phase 2's attack taxonomy, construct new hermetic attack/benign fixture pairs (techniques not already in the 152-row corpus) and run them through the real deployed pipeline (`run_detection` + `_run_scan`) at least three times each. Measure false-negative rate on harder attack techniques and false-positive rate on harder benign churn (live sports/stock widgets, personalization frameworks rewriting large DOM subtrees, WebSocket-pushed content, multiple simultaneous benign-churn types layered together as a realistic news site would exhibit).

### AUDIT PHASE 9 — Performance & Scalability Profiling
**Do not touch code.** Profile capture and detection pipelines independently and combined under realistic single-scan and batch conditions, using an actual profiler (not guesses). Identify concrete bottlenecks with measured cost (cold-start embedding load, fusion-artifact reload-per-scan, catastrophic regex on pathological input, missing DB index at realistic row counts) and a proposed remedy category for each.

### AUDIT PHASE 10 — Infrastructure, Docs & Cross-File Consistency Audit
**Do not touch code.** Verify `docker-compose.yml`, `.env.example`, `scripts/*.ps1`, every relevant `docs/*.mdx` file, and `docs/.mintlify/skills/wardress-operations/SKILL.md` against the **actual current runtime behavior** audited in Phases 1–9 — not against what PROMPT-002 claimed or what the README asserts. Every new environment variable across Phases 1–14 documented with an accurate default; every timeout/budget value in docs matches the code constant; install/diagnostics scripts actually exercise the new capabilities in a way that would surface a regression. Specifically re-verify, against Phase 4B's findings, every safety guarantee the README and SKILL.md make in prose (SSRF gating on the favicon resolver, "remediations require explicit human approval," "rebaseline requires operator consent," RBAC boundaries, ReDoS timeout, Fernet encryption at rest, hashed API keys, audit-log redaction) — a documented guarantee that Phase 4B found doesn't fully hold in code is a High-severity finding by definition (§6.4), not a docs nit.

### AUDIT PHASE 11 — Consolidated Findings Register, Opportunities Register & Decision Gate
**Do not touch code.** Read every prior audit-phase log entry in full — Phases 1, 2, 2B, 2C, 3, 4, 4B, 4C, 4D, 4E, 4F, 4G, 5A, 5B, 5C, 6, 7, 8, 9, 10. Produce:
1. A single **Findings Register** — every finding from all twenty prior phases, deduplicated, each with ID/title/severity/subsystem/reproduction/root cause/proposed remedy/source phase.
2. A **severity summary table**.
3. An **Opportunities / Innovation Register** — every Rule 17 idea across all phases, deduplicated, grouped by subsystem.
4. The **decision** per §8. If PROMPT-004 is warranted, author it (and its seeded log file) here, plus its Phase 1 kickoff prompt. If not, produce the Clean Bill of Health report.

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
- **Stress-test results** (Phases 5A/5B/5C/6/7/8 only): per-site or per-scenario table — pass 1 / pass 2 / pass 3 outcome, variance, and for every failure: individual root cause + Fix-candidate/Accepted-risk disposition (Rule 19; no aggregate-only rows)
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

A single consolidated table/list, every finding deduplicated across all phases, sorted by severity then subsystem.

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

### 8.1 When PROMPT-004 is authored

At Audit Phase 11, author `PROMPT-004-<short-name>.md` (plus its seeded log file and Phase 1 kickoff prompt) **if and only if**:
- Any Critical finding exists, or
- Any High finding exists, or
- Three or more Medium findings exist within the same subsystem.

PROMPT-004 must:
- Cover only confirmed findings (Critical/High, plus qualifying Medium clusters) — not a wishlist, not a re-litigation of PROMPT-002's design decisions.
- Preserve every "Prior Art" constraint from PROMPT-002 §4 (SSRF policy, hash-gate contract, rule floors, degradation signaling) as permanent, non-negotiable constraints in its own equivalent section, plus every constraint this file's Rules establish.
- Use the same Gauntlet Loop discipline, one-phase-per-session sizing philosophy (§0.2), log-format convention, and kickoff-prompt-per-phase relay mechanism.
- Order phases by dependency and blast radius.
- Apply Rule 19's no-aggregate-acceptance discipline to its own work: every finding it closes must be closed for real, verified by reproduction of the *original* finding's repro steps, not merely "tests added and green."

### 8.2 The Closure Loop — mandatory final phase of every remediation prompt

**This is the mechanism that prevents this effort from ending the way PROMPT-002 ended.** Every remediation prompt this effort authors (PROMPT-004, and any PROMPT-005+ it in turn spawns) must include, as its final mandatory phase, a **Re-Audit & Sign-Off phase** that:
1. Re-runs the full Rule-5-equivalent regression suite.
2. Re-executes the full three-tier stress-test catalog at least once in full, plus a minimum of two additional passes specifically on every site/scenario that previously failed (Rule 18's repeatability standard, applied to the fix).
3. Re-verifies every specific finding this remediation round claimed to fix, using the *exact original reproduction* that first surfaced it — not a new, looser test that happens to pass.
4. Explicitly checks for regressions the fix itself may have introduced elsewhere (a capture fix reintroducing a detection false positive, a detection threshold change reintroducing a capture-side inconsistency, etc.) — this is exactly the kind of cross-subsystem interaction a single narrowly-scoped remediation phase is structurally prone to missing.
5. Produces its own Findings Register using this file's severity rubric (§6.4) and applies this file's Decision Gate (§8.1) to itself.

**If that Re-Audit & Sign-Off phase surfaces any Critical/High finding, or a repeated/reintroduced Medium cluster, it must author the next remediation prompt (PROMPT-005, then PROMPT-006, and so on) using this identical §8 mechanism, and the loop continues.** The loop terminates only when a Re-Audit & Sign-Off phase produces a genuine Clean Bill of Health per §6.3: zero Critical/High findings, and every remaining Low finding individually justified and explicitly presented to the user for their own accept/reject decision — never a quiet aggregate close-out.

### 8.3 When no remediation prompt is warranted at all

If Audit Phase 11 finds nothing meeting the §8.1 bar, produce the Clean Bill of Health report directly (§6.3) and explicitly recommend re-running this same PROMPT-003 audit again after a stated interval or after the next significant codebase change — external site behavior, bot-protection vendors, and load patterns all drift, so "clean today" is not "clean forever."

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

The previous audit phase generates the next phase's kickoff prompt as part of its own log entry: read PROMPT-003 fully → read PROMPT-003-IMPLEMENTATION-LOG.md fully → read `PROMPT-003-stress-site-catalog.md` if the next phase is 5A/5B/5C/6/7/8 → read the specific PROMPT-002 sections + code files this phase targets, per §4 → execute this phase per §2, honoring Rule 18 (repeatability) and Rule 19 (no aggregate acceptance) wherever they apply → generate the next phase's kickoff prompt when done.

**Audit Phase 11's kickoff-prompt output is different**: per §8, it either hands the user the ready-to-paste PROMPT-004 Phase 1 kickoff prompt (if warranted), or the Clean Bill of Health report with a recommended re-audit interval. If a later remediation prompt's own Re-Audit & Sign-Off phase (§8.2) in turn spawns PROMPT-005+, that phase's kickoff-prompt output follows the identical pattern one level up.

---

## 10. A NOTE ON DISCIPLINE

PROMPT-002 was built on the premise that depth beats speed when the thing being built is a security-relevant monitoring system, and it delivered real, tested capability. But it also closed with an aggregate-accepted shortfall and an unresolved deviation quietly logged as a footnote — a reasonable place for a single 14-phase effort to stop, but not a reasonable place for the *project* to stop. This effort's entire purpose is to be the outside eye that checks whether "the tests are green" actually means "the system does what it was supposed to do" against the real, hostile, ever-changing world — and, via the Closure Loop in §8, to keep that check running until the answer is genuinely yes, not until someone declares it yes. Be rigorous, be honest about severity in both directions, hold every below-target number to its individual root cause, and never let "good enough in aggregate" be the last word.
