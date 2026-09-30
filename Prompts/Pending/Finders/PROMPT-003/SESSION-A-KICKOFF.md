# SESSION A — Deep Verification of Completed Audit Phases (Kickoff Prompt)

**Paste this entire file into a new chat to start Session A.**

---

## YOUR ROLE — COORDINATOR

You are the **coordinator agent** for Session A of the PROMPT-003 audit. Your job is to:

1. **Read the full audit context** (files listed in §INTAKE below)
2. **Spawn 5 subagents in parallel** with the exact scopes defined in §SUBAGENTS
3. **Let them run with full liberty** — each subagent independently reads code, runs tests, writes probes, executes Docker commands, traces call paths, and hunts for every possible issue
4. **Collect their findings** — each subagent writes a structured report to a scratch file
5. **Deduplicate and consolidate** — read all 5 reports, merge findings, resolve cross-subsystem interactions
6. **Write the unified log entry** — append a single `[DONE] PROMPT-003 Session A — Deep Verification of Completed Phases` entry to `PROMPT-003-IMPLEMENTATION-LOG.md`
7. **Report the summary** — tell the user what was found, confirmed, and newly discovered

### Decision-Making Policy (Fully Autonomous)
- **Design decisions:** Choose the best-practice option
- **Security decisions:** Choose the most conservative option
- **Implementation choices:** Choose the most robust option
- **No human input is needed or expected at any point**

### Rule 1 Reminder — Diagnosis, NOT Repair
This is still governed by PROMPT-003's Rule 1: **do not modify production code**. Subagents may write hermetic test files, scratch probes, and diagnostic scripts. They must NEVER modify production code (`backend/app/**`, `backend/worker/**` non-test files, `frontend/src/**`, `docker-compose.yml`, `.env*`, `scripts/**`, `docs/**`).

### Infrastructure
A fresh Wardress install is running in Docker. Use it for anything requiring a real browser or real sites. If containers are not up, ASK the user to start them — do not run install/uninstall scripts yourself. Package management: `uv` for Python, `pnpm` for Node.

---

## §INTAKE — Mandatory Reading (you, the coordinator)

Read these files **completely** before spawning any subagent:

1. `C:\Users\Ns8pc\Music\WARDRESS\Prompts\Pending\Finders\PROMPT-003\PROMPT-003-capture-detection-audit-and-stress-hardening.md` — the full audit spec (§0–§10, all rules, severity rubric, closure loop)
2. `C:\Users\Ns8pc\Music\WARDRESS\Prompts\Pending\Finders\PROMPT-003\PROMPT-003-IMPLEMENTATION-LOG.md` — all 10 completed phase entries with their findings, verified-clean ledgers, opportunities, and regression results
3. `C:\Users\Ns8pc\Music\WARDRESS\Prompts\Pending\Finders\PROMPT-003\PROMPT-003-stress-site-catalog.md` — the stress-test site catalog (Tiers A/B/C)

---

## §SUBAGENTS — Spawn All 5 in Parallel

> [!IMPORTANT]
> ### INVESTIGATIVE LIBERTY MANDATE (Rule 17 — The Floor, NOT the Ceiling)
> Every subagent is granted **complete autonomy and investigative liberty**. The file lists, existing findings, and probe ideas below are your **minimum starting floor, NOT your ceiling**.
> - You are NOT restricted to the pre-listed bullets.
> - Cold-read and trace any file in your assigned subsystem.
> - Follow unexpected clues, explore dark corners, test strange edge cases, hunt for dead code, and investigate performance bottlenecks.
> - If you suspect an anomaly, race condition, data corruption path, or optimization opportunity anywhere in your subsystem, pursue it aggressively with code tracing and scratch probes.
> - Record everything you discover in your scratch report.

**Spawn all 5 subagents simultaneously.** Give each subagent its FULL task description below as its prompt. Each subagent operates independently with full liberty.

Each subagent MUST begin by reading:
1. `C:\Users\Ns8pc\Music\WARDRESS\Prompts\Pending\Finders\PROMPT-003\PROMPT-003-capture-detection-audit-and-stress-hardening.md` — full audit spec
2. `C:\Users\Ns8pc\Music\WARDRESS\Prompts\Pending\Finders\PROMPT-003\PROMPT-003-IMPLEMENTATION-LOG.md` — all completed phase entries
3. The specific source files listed in their scope

### SUBAGENT 1 — Capture Pipeline Deep Verification

**Scope:** Audit Phases 1 (capture traceability) and 3 (capture fresh-eyes)

**Source files to read and verify:**
- `backend/worker/stealth.py`, `worker/fetcher.py`, `worker/probe.py`, `worker/page_prepare.py`, `worker/banner_dismiss.py`, `worker/artifacts.py`
- `backend/app/capture.py`, `backend/app/ssrf.py`, `backend/app/ssrf_transport.py`
- All capture test files: `test_stealth.py`, `test_fetcher_retry.py`, `test_page_prepare.py`, `test_screenshot_cap.py`, `test_capture_evidence.py`, `test_cloudflare_detection.py`, `test_banner_dismiss.py`, `test_probe_ua.py`

**Existing findings to verify STILL EXIST and dig deeper into:**
- **AUDIT-3-1** (banner click navigates away — silent wrong-page capture): Re-trace the full `dismiss_banners` → click → navigation path. Can you construct a concrete test case that triggers this? What happens with REAL banner selectors on live sites? Does the `nav_responses` tracking catch it?
- **AUDIT-3-2** (stale iframe/frame snapshot from `_wait_for_frame_loads`): Verify the frame-wait budget exhaustion path. What happens with deeply nested iframes? With frames that load but then immediately unload?
- **AUDIT-3-3** (SSRF rebinding window on the Playwright path): Verify the documented accepted-risk. Is the window practically exploitable? How large is the DNS TTL gap?
- **AUDIT-3-4** (artifact directory janitor gaps): Verify the janitor's sweep logic against the orphan-creation paths. Are there artifact directories that survive indefinitely?
- **AUDIT-3-5** (capture-completeness flags not flowing to detection): Verify the exact data loss point. What capture evidence is computed but never stored on the baseline?
- **AUDIT-3-6** (shrinking page height counted as stable): Can you construct a page that triggers this? What's the practical impact on real sites?

**Go deeper — hunt for things the original phases MISSED:**
- Memory profiling during sequential captures in one worker process — does memory grow unboundedly?
- What happens when `playwright-stealth` IS installed but throws during `apply_stealth`? Partial application?
- Race conditions between concurrent captures sharing a browser instance (if any)
- The consent cookie materialization for edge-case URL formats (data: URLs, blob: URLs, very long URLs)
- Screenshot capture under extreme viewport/page-height combinations
- The interaction between Cloudflare challenge detection and non-Cloudflare challenges (Akamai, DataDome)
- What if a page's height changes BETWEEN the scroll-to-bottom and return-to-top? Is the screenshot still valid?
- Can the SSRF route guard be bypassed via a redirect chain that starts external and ends internal?
- **Dead code analysis**: Find all unused helper functions, unreachable branches, obsolete parameters, dead imports, or orphan constants across `fetcher.py`, `stealth.py`, `page_prepare.py`, `banner_dismiss.py`, `probe.py`, `artifacts.py`.
- **Opportunities for optimization**: Profile and document specific capture speedups, context reuse opportunities, parallel probe fetches, and DOM walk optimizations.

**Write your findings to:** `C:\Users\Ns8pc\Music\WARDRESS\Prompts\Pending\Finders\PROMPT-003\scratch\session-a-capture.md`

**Output format for each finding:**
```
### [CONFIRMED / NEW / DEEPENED / INVALIDATED] Finding-ID — Title
- **Original phase:** (if confirming/deepening an existing finding)
- **Severity:** Critical / High / Medium / Low (justify against §6.4 of the audit spec)
- **Subsystem / file(s):**
- **Verification method:** (test, code-trace, live probe, measurement)
- **Evidence:** (exact steps, code lines, test output)
- **Deeper analysis:** (anything the original phase didn't cover)
- **Cross-subsystem interactions:** (how this finding affects detection, orchestration, etc.)
```

At the end of your report, include:
1. **Dead Code & Orphan Routines Section**: Complete table of dead code found with exact file/line numbers.
2. **Opportunities for Optimization Section**: Actionable speedup and resource-reduction proposals with expected impact.
3. **Summary Section** with counts of confirmed/new/deepened/invalidated findings.

---

### SUBAGENT 2 — Detection Pipeline Deep Verification

**Scope:** Audit Phases 2 (detection traceability) and 4 (detection fresh-eyes)

**Source files to read and verify:**
- `backend/worker/detection/pipeline.py`, `normalize.py`, `dom.py`, `metadata.py`, `fusion.py`, `suppress.py`, `cloaking.py`, `semantics.py`, `signatures.py`, `visual.py`, `types.py`
- `backend/worker/hashing.py`, `worker/llm_escalation.py`
- `backend/worker/detection/training/regression_corpus.json`, `fusion_model.json`
- `backend/tools/build_regression_corpus.py`, `refit_fusion_model.py`, `build_fusion_dataset.py`
- All detection test files

**Existing findings to verify STILL EXIST and dig deeper into:**
- **AUDIT-1-1** (changed-not-clean verdict on benign dynamic content): Can you quantify how many real-world sites this affects? What's the exact fused-risk distribution for benign churn?
- **AUDIT-4-1** (unpunctuated text → false positive): Test with more adversarial content. Pages with ONLY emoji? ONLY numbers? Mixed script without Latin punctuation? CJK without sentence-ending markers?
- **AUDIT-4-2** (probe transients → false high risk): Measure real-world TLS probe failure frequency. What's the blast radius across a fleet?
- **AUDIT-4-3** (expired cert → permanent changed): How many real sites have expired certs? What's the dashboard noise?
- **AUDIT-4-4** (suppression timeout asymmetry): Can you find a REAL user regex pattern that triggers this? Realistic patterns like overly broad URL matchers?
- **AUDIT-4-5** (empty current capture → measured 1.0): Trace EVERY path that produces empty HTML. How often does this happen?
- **AUDIT-4-6** (layer 3 removal-blind): Realistic attack surface assessment — does removal-only defacement actually happen?
- **Attack taxonomy gaps** from Phase 2: Verify the 3 genuinely absent categories (subtle single-word tampering, redirect-based cloaking, time-delayed payloads). Construct concrete evasion scenarios.

**Go deeper — hunt for things the original phases MISSED:**
- Numerical stability of fusion with extreme layer scores (all 1.0, all 0.0, mixed NaN/Inf, negative scores)
- Regression corpus coverage gaps — realistic attack shapes not represented?
- Layer interaction effects — can two sub-threshold layers combine into a false positive?
- Normalization behavior on adversarially crafted HTML (deeply nested tags, huge attribute values, malformed entities, null bytes)
- Edge cases in sigmoid mapping near the decision boundary (0.49 vs 0.51)
- Can suppression rules be weaponized to MASK a real attack (adversary knows the user's suppression patterns)?
- What happens if the MiniLM embedding model produces unexpected output (NaN, zero vector, wrong dimensionality)?
- Layer 7 cloaking detection against sophisticated UA-dependent content (CDN edge-case behaviors)
- **Dead code analysis**: Find all dead functions, uncalled helper methods, redundant branches, obsolete dictionary keys, and unused imports across all 11 detection modules.
- **Opportunities for optimization**: Algorithmic speedups in DOM parsing/diffing, regex pre-compilation, vector similarity caching, fast-path skip optimizations for identical DOM subtrees.

**Write your findings to:** `C:\Users\Ns8pc\Music\WARDRESS\Prompts\Pending\Finders\PROMPT-003\scratch\session-a-detection.md`

At the end of your report, include:
1. **Dead Code & Orphan Routines Section**: Complete table of dead code found with exact file/line numbers.
2. **Opportunities for Optimization Section**: Actionable speedup and resource-reduction proposals with expected impact.
3. **Summary Section** with counts of confirmed/new/deepened/invalidated findings.

---

### SUBAGENT 3 — Orchestration & Scheduling Deep Verification

**Scope:** Audit Phases 2B (full inventory) and 4B (orchestration fresh-eyes)

**Source files to read and verify:**
- `backend/worker/celery_app.py`, `worker/scan_tasks.py`, `worker/beat_tasks.py`, `worker/db.py`
- `backend/app/scanning.py`, `app/tasks.py`, `app/services.py`, `app/models.py`
- Alembic migrations under `backend/alembic/versions/`
- `docker-compose.yml`, `Dockerfile.worker`
- All orchestration test files: `test_scheduler.py`, `test_scan_tasks.py`, `test_tasks_enqueue.py`, `test_phase4b_orchestration_repros.py`, `test_phase18_concurrency_races.py`, `test_phase37_scheduling_agent_remediation.py`

**Existing findings to verify STILL EXIST and dig deeper into:**
- **AUDIT-4B-1** (lost alerts on worker death): Verify exact window size. Measure time between terminal commit and `_create_alert`. Probability under normal load?
- **AUDIT-4B-2** (overload amplification): Model cascade behavior. At what fleet size does amplification become dangerous?
- **AUDIT-4B-3** (cadence pinning from transients): Simulate a 30-day fleet with mixed transient patterns. What fraction of sites get stuck at base/4?
- **AUDIT-4B-4** (rebaseline arbitration gap): Is accepted-risk correct? Operator impact?
- **AUDIT-4B-5** (stale row recovery latency): Worst case for a 24h-interval site?
- **AUDIT-4B-8** (deployment drift): Has the stack been rebuilt since this finding? Verify current state.

**Go deeper — hunt for things the original phases MISSED:**
- Database connection pool exhaustion under concurrent scan load
- Redis memory growth patterns over time (unacked messages, celerybeat schedule)
- Worker prefork memory scaling with all 12 children warm (extrapolate from 2-child measurement)
- Celery visibility timeout vs task hard limit vs STALE_INFLIGHT interactions under edge conditions
- Beat tick jitter and missed-tick behavior under high worker load
- Alembic migration safety (can EVERY migration be rolled back cleanly? Test `downgrade` paths)
- What happens when the DB is temporarily unreachable mid-scan? Mid-baseline? Mid-alert-creation?
- FK cascade behavior during concurrent site deletion + scan completion
- The `MAX_DISPATCH_PER_TICK = 50` vs actual worker throughput — what's the headroom?

**Write your findings to:** `C:\Users\Ns8pc\Music\WARDRESS\Prompts\Pending\Finders\PROMPT-003\scratch\session-a-orchestration.md`

---

### SUBAGENT 4 — API, Auth & Frontend Deep Verification

**Scope:** Audit Phases 4C (API surface) and 4F (frontend)

**Source files to read and verify:**
- `backend/app/routers/` (all 13 in-scope routers), `app/deps.py`, `app/security.py`, `app/apikeys.py`, `app/ratelimit.py`, `app/audit.py`, `app/schemas.py`
- `frontend/src/` (all pages, components, lib), `frontend/tests/`
- All API and frontend test files

**Existing findings to verify STILL EXIST and dig deeper into:**
- **AUDIT-4C-1** (503 partial-success on dead broker): Test retry behavior end-to-end
- **AUDIT-4C-2** (public docs/openapi): What data is exposed? Sensitive patterns?
- **AUDIT-4C-3** to **AUDIT-4C-7**: All Low findings — verify current state
- **AUDIT-4F-1** (capture-health flake): Reproduce under load. Minimum triggering delay?
- **AUDIT-4F-2** (degraded-as-clean rendering): Verify with live frontend
- **AUDIT-4F-3** (blank dashboard on shape mismatch): Test more malformed payloads
- **AUDIT-4F-4** to **AUDIT-4F-9**: All frontend findings — verify current state

**Go deeper — hunt for things the original phases MISSED:**
- CSRF protection completeness
- Rate-limit bypass via API key rotation or parallel sessions
- XSS vectors in user-supplied site URLs, suppression rules, or AI explanations
- Frontend bundle size and lazy-loading efficiency
- Accessibility compliance beyond existing findings
- API pagination edge cases (negative offset, huge limit, concurrent page changes)
- Session/token invalidation during password change
- CORS configuration correctness
- Content-Type validation on all endpoints
- Error message information leakage

**Write your findings to:** `C:\Users\Ns8pc\Music\WARDRESS\Prompts\Pending\Finders\PROMPT-003\scratch\session-a-api-frontend.md`

---

### SUBAGENT 5 — AI Integration, Supply-Chain & Infrastructure Deep Verification

**Scope:** Audit Phases 4E (AI/supply-chain) and 4D (alert/remediation delivery)

**Source files to read and verify:**
- `backend/app/ai_config.py`, `ai_catalog.py`, `ai_ollama.py`, `ai_startup.py`, `ai_migration.py`, `app/llm.py`, `app/crypto.py`
- `backend/worker/llm_escalation.py`, `worker/alert_tasks.py`, `worker/remediation_tasks.py`
- `backend/app/alerting.py`, `app/remediation.py`, `app/explain.py`, `app/site_icons.py`
- `backend/pyproject.toml`, `backend/uv.lock`, `frontend/package.json`
- Dockerfiles, `docker-compose.yml`, `.env.example`, `.github/workflows/ci.yml`
- All AI, delivery, and supply-chain test files

**Existing findings to verify STILL EXIST and dig deeper into:**
- **AUDIT-4E-1** (SSRF policy skipped for AI providers): Verify ALL code paths. Any new ones since audit?
- **AUDIT-4E-2** (catalog fetch outside SSRF policy): Comprehensive verification
- **AUDIT-4E-3** (hung provider stalling): Re-measure with current code
- **AUDIT-4E-4** (weasyprint CVE): Check if bumped. Check for NEW advisories
- **AUDIT-4E-5** to **AUDIT-4E-11**: All remaining findings — verify current state
- **AUDIT-4D-1** (mid-delivery crash orphans channels): Model probability. Real window width?
- **AUDIT-4D-2** (check-then-act double-send): Can this happen in production?
- **AUDIT-4D-3** to **AUDIT-4D-8**: All delivery findings — verify current state

**Go deeper — hunt for things the original phases MISSED:**
- Fernet key rotation behavior — old values unreadable after rotation?
- LiteLLM security posture — telemetry, secret logging?
- Transitive dependency issues beyond direct dependencies
- Docker image attack surface (unnecessary packages)
- `.env.example` completeness vs actual code usage
- CI/CD pipeline security (PR secret extraction)
- Email template injection vectors
- Webhook payload integrity (can an attacker predict or forge remediation webhook payloads?)
- Alert delivery retry storms under provider outage

**Write your findings to:** `C:\Users\Ns8pc\Music\WARDRESS\Prompts\Pending\Finders\PROMPT-003\scratch\session-a-ai-infra.md`

---

## §COORDINATION — After All Subagents Complete

Once all 5 subagents have written their scratch files:

1. **Read all 5 scratch files completely**
2. **Deduplicate:** If multiple subagents found the same issue, merge into one finding
3. **Identify cross-subsystem interactions:** Findings that span multiple subagents' scopes
4. **Classify all findings:**
   - `CONFIRMED` — existing finding verified to still exist
   - `NEW` — finding the original phases completely missed
   - `INVALIDATED` — existing finding that no longer applies
   - `DEEPENED` — existing finding with new edge cases, wider blast radius, or refined severity
5. **Write the unified log entry** to `C:\Users\Ns8pc\Music\WARDRESS\Prompts\Pending\Finders\PROMPT-003\PROMPT-003-IMPLEMENTATION-LOG.md` using this format:

```markdown
### [DONE] PROMPT-003 Session A — Deep Verification of Completed Phases (1–4F)

- **Prompt**: SESSION-A-KICKOFF.md
- **Session date**: YYYY-MM-DD
- **Scope**: Independent deep verification of all 10 completed audit phases using 5 parallel subagents
- **Subagent reports**: scratch/session-a-{capture,detection,orchestration,api-frontend,ai-infra}.md

#### Summary
- Findings confirmed: N
- Findings deepened (new edge cases/wider blast radius): N
- New findings discovered: N
- Findings invalidated: N
- Cross-subsystem interactions identified: N

#### Confirmed Findings (verified still present)
[list with any deepened analysis]

#### New Findings
[full finding blocks per §6.1 of the audit spec]

#### Invalidated Findings
[list with reasoning]

#### Cross-Subsystem Interactions
[findings that span multiple subsystems]

#### Updated Opportunities Register
[any new opportunities discovered]

#### Regression Results
[aggregated test results from all subagents]
```

6. **Tell the user:** Session A is complete. Start Session B using `SESSION-B-KICKOFF.md`.
