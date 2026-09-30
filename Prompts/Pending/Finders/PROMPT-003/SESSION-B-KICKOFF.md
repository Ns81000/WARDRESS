# SESSION B — Complete Pending Audit Phases (5A–10) with Parallel Subagents (Kickoff Prompt)

**Paste this entire file into a new chat to start Session B.**
**PREREQUISITE:** Session A must be completed first. Session A's deep-verification findings in `PROMPT-003-IMPLEMENTATION-LOG.md` are part of your mandatory reading.

---

## YOUR ROLE — COORDINATOR

You are the **coordinator agent** for Session B of the PROMPT-003 audit. Your job is to:

1. **Read the full audit context** (files listed in §INTAKE below) — including Session A's deep-verification results
2. **Execute 3 waves of subagents** per §WAVES below
3. **After all waves complete, execute Phase 10 yourself** — the Consolidated Findings Register
4. **Leave NOTHING pending** — every finding must have a disposition, every below-target metric must have a per-case root cause
5. **Log everything** to `PROMPT-003-IMPLEMENTATION-LOG.md` — the user will create their own remediation prompt based on your findings

### Decision-Making Policy (Fully Autonomous)
- **Design decisions:** Choose the best-practice option
- **Security decisions:** Choose the most conservative option
- **Implementation choices:** Choose the most robust option
- **No human input is needed or expected at any point**
- **Rule 19 discipline is absolute:** Every below-target metric must be broken down to individually-investigated root causes per failing case. An aggregate percentage is NEVER sufficient.
- **Rule 18 discipline is absolute:** Every stress-test result needs a minimum of 3 passes with variance recorded.

### Rule 1 Reminder — Diagnosis, NOT Repair
Governed by PROMPT-003's Rule 1: **do not modify production code**. Subagents may write hermetic test files, scratch probes, and diagnostic scripts. They must NEVER modify production code.

### Infrastructure
A fresh Wardress install is running in Docker. Use it for all live testing. If containers are not up, ASK the user to start them. Package management: `uv` for Python, `pnpm` for Node.

---

## §INTAKE — Mandatory Reading (you, the coordinator)

Read these files **completely** before spawning any subagent:

1. `C:\Users\Ns8pc\Music\WARDRESS\Prompts\Pending\Finders\PROMPT-003\PROMPT-003-capture-detection-audit-and-stress-hardening.md` — the full audit spec (all rules, all phase specs, severity rubric, closure loop §8)
2. `C:\Users\Ns8pc\Music\WARDRESS\Prompts\Pending\Finders\PROMPT-003\PROMPT-003-IMPLEMENTATION-LOG.md` — ALL entries (Phases 1–4F + Session A deep verification)
3. `C:\Users\Ns8pc\Music\WARDRESS\Prompts\Pending\Finders\PROMPT-003\PROMPT-003-stress-site-catalog.md` — the full stress-test site catalog (Tiers A/B/C, verification protocol, repeatability requirements)

---

## §WAVES — Execute in Order

> [!IMPORTANT]
> ### INVESTIGATIVE LIBERTY MANDATE (Rule 17 — The Floor, NOT the Ceiling)
> All subagents in Session B operate with **complete investigative liberty and autonomy**:
> - **In Wave 1 (W1-A, W1-B, W1-C)**: The site catalogs, fixture lists, and profiling items are your **minimum floor**. You are encouraged to test additional problematic sites, craft novel evasion fixtures beyond the taxonomy, profile any suspicious bottlenecks, hunt dead code, and trace unlisted paths.
> - **In Wave 2 (W2)**: The 7 fault-injection scenarios are the **minimum required**. You have full liberty to design and execute additional chaos experiments (e.g. database restarts mid-scan, Redis connection loss, disk space saturation, corrupt baseline data) to stress-harden the platform to engineering perfection.
> - Do not hesitate to report any anomaly, edge case, race condition, or optimization you discover.

### WAVE 1 — Spawn 3 Subagents in Parallel

These three subagents run simultaneously because their work does not conflict:

#### SUBAGENT W1-A — Stress-Test Catalog: All Tiers A + B + C (Phases 5A + 5B + 5C)

**Scope:** Execute ALL tiers of `PROMPT-003-stress-site-catalog.md` against the live Docker install.

**Mandatory reading:**
1. The full audit spec — especially §5 (stress-test catalog), §7 (concurrency/scale/chaos regime), Rules 18 and 19
2. `PROMPT-003-stress-site-catalog.md` — every site, every tier, the verification protocol
3. The Phase 5A, 5B, and 5C specs in §4 of the audit spec
4. Session A's findings (any new capture-related findings that should inform testing)

**Execution instructions:**
1. **Verify the stress-test runner exists:** Check for `backend/tools/run_stress_catalog.py`. If it exists, use it (`uv run python tools/run_stress_catalog.py --tier A`, then `--tier B`, then `--tier C`). If it doesn't exist, execute manually via the API.
2. **Tier A (Broad Real-World Baseline):**
   - Run ALL sites in `PROMPT-003-stress-site-catalog.md` Tier A
   - Minimum 3 passes per site (Rule 18), spread across time if possible
   - For EVERY failure: individual root-cause investigation (Rule 19)
   - Record: URL, tier/category, pass 1/2/3 results, latency variance, status, disposition
3. **Tier B (Advanced Bot Defenses):**
   - Same protocol for Akamai, DataDome, PerimeterX, AWS WAF, Cloudflare Enterprise, hard e-commerce, hard lazy-load
   - **Verify each site's current vendor before testing** (per the catalog's verification protocol)
   - For EVERY failure: determine if it's a product limitation or an environment issue
4. **Tier C (Exotic & Edge Categories):**
   - WebSocket/live-push, PWA/Service-Worker, extremely large pages, slow origins, auth-adjacent, infinite-scroll, heavy hydration, deep RTL/mixed-script
   - These are the HARDEST sites — expect failures, but each failure MUST have an individual root cause

**For EVERY failing site, produce:**
```
### FAIL — [URL] (Tier [X], Category [Y])
- Pass results: P1: [result] / P2: [result] / P3: [result]
- Latency: [min/max/avg] ms
- Error: [exact error message/behavior]
- Root cause: [investigated individual cause]
- Evidence: [capture_evidence dump, HTTP status, challenge detection state, retry path exercised?]
- Disposition: Fix-candidate / Accepted-risk (with justification)
```

**Write your findings to:** `C:\Users\Ns8pc\Music\WARDRESS\Prompts\Pending\Finders\PROMPT-003\scratch\session-b-stress-testing.md`

---

#### SUBAGENT W1-B — Adversarial Detection Accuracy Stress Test (Phase 8)

**Scope:** Construct and test adversarial detection fixtures through the deployed pipeline.

**Mandatory reading:**
1. The full audit spec — especially Phase 8 spec in §4
2. The Phase 2 attack taxonomy (especially the 3 genuinely absent categories)
3. The Phase 4 detection findings (AUDIT-4-1 through AUDIT-4-8)
4. Session A's detection verification findings

**Execution instructions:**
1. **Construct hermetic attack/benign fixture pairs** based on the Phase 2 taxonomy:
   - Cover ALL 10 attack techniques from the taxonomy
   - Include the 3 genuinely absent categories: subtle single-word tampering, redirect-based cloaking, visual-only attacks
   - Create adversarial pairs designed to EVADE detection

2. **Mandatory Visual-Only Attack Fixtures (NB-DET-1):**
   - `<style>` injection with visual defacement (`body { filter: invert(1) hue-rotate(180deg); }` or absolute overlay)
   - `@font-face` glyph hijacking (swap character glyphs visually while DOM codepoints stay identical)
   - `<canvas>` or `<svg>` graphical takeover rendering defacement messages without HTML text
   - Measure whether these evade alerting (fusing < 0.40 material change bar or < 0.50 flag threshold)
   - Also test benign visual twins (legit brand refresh, webfont swap)

3. **Run EVERY fixture through the deployed detection pipeline 3 times** (Rule 18)
4. **Measure:** false-negative rate on attacks, false-positive rate on benign churn
5. **For every failure:** individual root cause + Fix-candidate / Accepted-risk

**Write your findings to:** `C:\Users\Ns8pc\Music\WARDRESS\Prompts\Pending\Finders\PROMPT-003\scratch\session-b-detection-accuracy.md`

---

#### SUBAGENT W1-C — Performance Profiling, Infrastructure & Operational Consistency Audit (Phase 9)

**Scope:** Profile pipelines, audit PowerShell scripts, Docker topology, documentation drift, soft-block poisoning, and dead code.

**Mandatory reading:**
1. The full audit spec — especially the Phase 9 spec in §4
2. Session A's infrastructure and supply-chain findings
3. The `scripts/*.ps1` files, `docker-compose.yml`, `docs/` directory

**Execution instructions:**

1. **Performance Profiling & Bottlenecks:**
   - Profile capture pipeline under single and batch load
   - Profile detection pipeline under single and batch load
   - Identify concrete bottlenecks with measured costs (cold-start embedding, fusion reload, regex compilation, missing DB indexes, duplicate queries)
   - All measurements with the profiler used, sample size, and environment stated

2. **PowerShell Scripts & Operational Lifecycle (OPS-1 to OPS-8):**
   - `update.ps1`: Verify `.env.example` vs `.env` merge behavior
   - `validate.ps1`: Verify resource check thresholds (< 4 GB RAM advice vs actual memory needs)
   - `install.ps1`: Verify Node/pnpm bootstrapping and preflight checks
   - `diagnostics.ps1`: Verify secret scrubbing rules (`wk_` API keys and tokens)
   - Backup & Restore: If possible, run full `uninstall.ps1` backup → fresh install → `RESTORE.txt` replay

3. **Docker Topology & Resource Constraints:**
   - Verify `docker-compose.yml` service dependencies (`beat` missing `depends_on: db`)
   - Audit worker memory limits, cgroups, healthchecks, `--max-tasks-per-child` recycling
   - Verify all service healthchecks are correct

4. **Soft-Block Baseline Poisoning (NB-CAP-2):**
   - Probe baseline creation against 200 OK soft-block/paywall/verify-human pages (`nytimes.com`, `wsj.com`)
   - Verify if non-error block pages are mistakenly stored as healthy baselines

5. **Documentation Drift (DOC-1 to DOC-8):**
   - Cross-check `docs/docs.json`, `docs/*.mdx`, `README.md`, `SKILL.md` against live code
   - Check: linked stylesheet claims, noise floor/changed gate reality, Telegram bot direct DB bypass vs API diagram, hop-by-hop DNS rebinding claims, regex timeout guarantees, public API docs exposure

6. **Dead Code & Optimization Opportunities:**
   - Inventory unreferenced utility functions, unused script branches, dead environment variables in `.env.example`, and obsolete Docker build stages
   - Formulate concrete optimization proposals across capture, detection, and operational scripts

**Write your findings to:** `C:\Users\Ns8pc\Music\WARDRESS\Prompts\Pending\Finders\PROMPT-003\scratch\session-b-performance-ops.md`

---

### WAVE 2 — Sequential (After Wave 1 Completes)

**WAIT** for all Wave 1 subagents to finish before starting Wave 2.

#### SUBAGENT W2 — Concurrency & Scale Stress Testing + Chaos & Failure-Injection Testing (Phases 6 + 7)

**Scope:** Execute the full concurrency/scale/chaos test regime per §7 of the audit spec.

**IMPORTANT:** This subagent manipulates the Docker stack (SIGKILLs, load injection). It MUST run alone — no other subagents should be running.

**Mandatory reading:**
1. The full audit spec — especially §7 (concurrency/scale/chaos test regime)
2. The Phase 6 and Phase 7 specs in §4
3. Wave 1 stress-test results (for context on what the system handles)
4. Session A's orchestration findings (AUDIT-4B-1 through AUDIT-4B-8)

**Phase 6 — Concurrency & Scale Stress Testing:**
1. **Load levels:** configured limit, 2×, 5× — each run 3 times (Rule 18)
2. **Soak run:** 50 sequential capture+scan cycles on one worker without restart
3. **Measure:** queueing latency, CPU/memory, connection pool contention, lock contention
4. **Verify:** AUDIT-4B-2's amplification cascade under real overload
5. **Every number with measurement method stated**

**Phase 7 — Chaos & Failure-Injection Testing (minimum 7 scenarios, 3 times each):**
1. Crash mid-capture (worker SIGKILL during Playwright render)
2. DNS/TLS failure & slow/blackholed DNS hang on event loop (`ssrf_transport.py:72` / `site_icons.py:111-117` `NB-ORC-1`)
3. Slow-loris response (slow headers/stream)
4. Malformed HTTP response
5. SSRF redirect loop
6. Pathologically large DOM (>10MB)
7. Streaming chunked body memory bomb / worker probe OOM (`probe.py:170,223` buffering before slice `NB-CAP-1`)

**Classify each scenario as:** safe fail vs silent success vs worker crash

**Write your findings to:** `C:\Users\Ns8pc\Music\WARDRESS\Prompts\Pending\Finders\PROMPT-003\scratch\session-b-concurrency-chaos.md`

---

### WAVE 3 — Coordinator Executes Phase 10

**After Wave 2 completes, YOU (the coordinator) execute Phase 10 directly.**

#### Phase 10 — Consolidated Findings Register & Opportunities Register (Audit Completion)

**Read ALL scratch files from all subagents plus ALL prior log entries.**

**Produce:**

1. **Master Findings Register** — single consolidated table, deduplicated across ALL phases (1–9 + Session A), sorted by severity then subsystem:
   `| ID | Title | Severity | Subsystem | Source Phase | Proposed Remedy |`
   Use markdown anchor links back to original entries.

2. **Severity Summary Table:**
   `| Severity | Count |`

3. **Opportunities / Innovation Register** — consolidated from all phases.

4. **Audit Status Declaration:** State clearly that the PROMPT-003 audit is **COMPLETE**. List the total finding counts by severity. State that the user will create their own remediation prompt based on these findings.

> [!IMPORTANT]
> **DO NOT author PROMPT-004.** DO NOT create any remediation prompt. DO NOT issue a Clean Bill of Health.
> Your job ends at producing the complete, deduplicated Findings Register and logging it.
> The user will review the findings and create their own remediation prompt.

**Write the Phase 10 entry to:** `C:\Users\Ns8pc\Music\WARDRESS\Prompts\Pending\Finders\PROMPT-003\PROMPT-003-IMPLEMENTATION-LOG.md`

---

## §LOG FORMAT — For Every Phase Entry

Each subagent appends its phase entry to its scratch file using this format:

```markdown
### [DONE / PARTIAL] PROMPT-003 Audit Phase N — <phase title>

- **Prompt**: SESSION-B-KICKOFF.md
- **Session date**: YYYY-MM-DD
- **Assigned subsystem**: <per §4>
- **Stress-test results** (if applicable): dense markdown table:
  | URL | Tier/Category | Pass 1 | Pass 2 | Pass 3 | Variance | Status | Notes / Disposition |
  Passing sites (3/3) take only ONE line. Detailed Finding blocks ONLY for failing sites.
- **Findings**: one block per finding (full §6.1 format)
- **Opportunities / Innovation ideas**: one block per idea
- **Full regression results**: exact commands + counts
```

The coordinator integrates all subagent scratch files into the main log.

---

## §COMPLETION CRITERIA — Session B is NOT done until:

1. All 7 pending phases (5A, 5B, 6, 7, 8, 9, 10) have log entries marked `[DONE]`
2. Every below-target stress-test result has an individually-investigated root cause (Rule 19)
3. Every stress-test was run minimum 3 times (Rule 18)
4. The Consolidated Findings Register is complete and deduplicated
5. The audit is marked COMPLETE in the implementation log
6. NOTHING is left pending — every finding has a disposition
7. The implementation log fully documents everything that happened
