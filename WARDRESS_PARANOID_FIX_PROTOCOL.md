# WARDRESS PARANOID FIX PROTOCOL

**READ THIS ENTIRE FILE, START TO FINISH, BEFORE DOING OR WRITING ANYTHING.**
Do not skim. Do not jump to the phase list. Do not begin work after reading only the phase table. This file defines rules that apply to *every* phase, and violating them invalidates the fix. If you have already read it once earlier in this session, re-read it anyway — you cannot rely on a memory summary of your own instructions.

---

## 0. WHAT THIS IS

This is a multi-session, multi-phase, adversarial **fix-implementation** effort against the Wardress codebase, driven entirely by `WARDRESS_AUDIT_FINDINGS.md` — the completed 80-finding audit (0 Critical, 12 High, 35 Medium, 33 Low) produced by `WARDRESS_PARANOID_AUDIT_PROTOCOL.md`. That earlier effort was **read-only** — it never touched the source tree. This effort is the opposite: its entire job is to correctly, safely, and verifiably eliminate every one of those 80 findings, one small paranoid session at a time, without introducing a single new defect.

Each phase happens in a **separate chat with a fresh context window**, against the **same deployment installed once, fresh, at the very start of this whole effort** — see Rule 10. This file is the only thing that persists your instructions across sessions. A second file, `WARDRESS_FIX_LOG.md`, is the only thing that persists your *implementation progress and decisions* across sessions. The original `WARDRESS_AUDIT_FINDINGS.md` remains the read-only source of truth for *what is wrong*; you never edit it. Together, these three files are the entire state of this effort. Nothing else survives between sessions.

This means: **if it isn't written into `WARDRESS_FIX_LOG.md`, it did not happen.** A future session (a future you) will trust that file completely and will not re-read the entire codebase to rediscover what you already fixed, why, and how you proved it.

**The suggested fix direction in `WARDRESS_AUDIT_FINDINGS.md` is a starting hint, not an instruction to follow blindly.** Every finding's "Suggested fix direction" field is deliberately terse ("direction only"). Your job in this effort is to independently re-derive the best actual fix — considering every edge case, every concurrent-access pattern, every malformed-input path, every interaction with other findings already fixed — and implement *that*, even if it differs from or goes further than the one-sentence hint. If the hint is wrong or incomplete, say so in the fix log and do the right thing instead.

---

## 1. ABSOLUTE, NON-NEGOTIABLE RULES

1. **You edit the source tree now — but only inside the scope of the finding(s) you are actively fixing in this phase.** No drive-by refactors, no unrelated cleanup, no "while I'm here" changes to files outside the current phase's target, even if you notice something else wrong. If you notice something else wrong that isn't already in `WARDRESS_AUDIT_FINDINGS.md`, note it in `WARDRESS_FIX_LOG.md` under "New leads observed (not yet in scope)" and move on. This mirrors the audit's own no-scope-creep discipline.
2. **No feature additions.** You are here to make what already exists correct, robust, and honest about what it does — never to add new capabilities beyond what a finding's fix genuinely requires (e.g., adding a DB lock to fix a race condition is in scope; adding a new API endpoint is not).
3. **The only files you write to, outside the specific finding's target files, are:**
   - `WARDRESS_FIX_LOG.md` (append fix entries, update the progress tracker) — lives at repo root, same place as this file.
   - New test files / test additions, which are a **required deliverable of every phase**, not optional scratch work.
   - Scratch/throwaway files **outside the repo tree** (e.g. `/tmp/...`) for probe scripts or fuzz harnesses used to verify a hypothesis before committing to a fix. Delete these when done, or at minimum never let them leak into a commit.
4. **Never touch `WARDRESS_AUDIT_FINDINGS.md`.** It is permanently read-only, the historical record of the original audit. Corrections to what it found (if a finding turns out to be a misread during re-verification) go in `WARDRESS_FIX_LOG.md` as a note, not as an edit to the audit file.
5. **Every fix must be independently re-verified before it is trusted**, per the Gauntlet Loop in §2. Do not implement the audit's one-line suggested direction verbatim without first re-deriving why it's right and whether it's actually sufficient.
6. **Every fix must be proven, not asserted.** "Proven" means: a test that failed before the fix and passes after it, for every edge case you identified — plus the full existing test suite still green. If something genuinely cannot be tested (e.g., a Windows-only interactive prompt), say so explicitly in the fix log and explain the manual verification you performed instead.
7. **No regressions, ever.** Before a phase is allowed to end, the *entire* pre-existing test suite (backend `pytest`, frontend `vitest`, linters, type-checkers) must pass, not just the new tests written this phase. If a phase's fix breaks something else, that break must be resolved (or the fix redesigned) before the phase ends — it cannot be logged as a known issue and deferred.
8. **One phase per session, fully, before stopping.** Do not do half a phase and call it done. Do not skip ahead to a later phase because it looks more interesting. Do not silently merge two phases together, and do not silently split a listed phase into two sessions without recording that split explicitly in the tracker's notes column. If a phase turns out to be larger than expected once you're inside it, it is better to finish a *smaller, explicitly-scoped subset* of it correctly than to rush the whole thing shallowly — but you must then leave the tracker in `In progress (partial — see notes)` and record exactly what remains, rather than marking it Complete.
9. **Every phase ends in exactly one git commit** (after the full regression suite is green), with a message of the form:
   `fix(phaseN): <short summary> — closes: <finding title fragment(s)>`
   Do not push automatically — leave the commit for the user to review and push. Do not amend or rebase prior phases' commits.
10. **The deployment is installed once, fresh, at the very start of this whole effort — before Phase 0 begins — and is not torn down or reinstalled again between subsequent phases/sessions.** The same working checkout persists for the entire multi-phase effort, accumulating every phase's commits in place. This has one consequence you must guard against, but only as a lightweight sanity check, since the repo (both the local checkout and its GitHub remote) is entirely yours — there is no separate upstream anyone else controls, so there's no "wrong repo" to accidentally pull from:

    > **If the checkout at the start of a phase is somehow missing commits that `WARDRESS_FIX_LOG.md`'s tracker claims are already done, something outside this protocol reset or corrupted the working tree, and that phase's work would silently be building on the wrong base.**

    At the start of Phase 0 specifically, before doing anything else: confirm you're on the correct branch and the checkout is otherwise as expected (clean working tree, no stray uncommitted changes from something else). For every phase *after* Phase 0, confirm `git log --oneline` shows every commit `WARDRESS_FIX_LOG.md`'s tracker claims is done. If anything is missing or looks wrong, STOP and flag this to the user immediately — do not proceed or silently re-do already-completed work.
11. **Trust nothing you have not personally re-verified**, including your own prior sessions' fix-log entries about *other* findings, if this phase's fix touches code near them. A fix log entry says a fix was made and tested at the time — always confirm it's still true (a later phase could theoretically have altered nearby behavior), don't just cite it.

---

## 2. THE GAUNTLET LOOP (mandatory methodology for every finding, every phase)

This is not a checklist to skim — it is the actual sequence of work for every finding you fix. Do not skip steps. Do not collapse steps 2–4 into "I already know the fix" just because the audit's suggested direction seems obvious — obvious-looking fixes are exactly where a missed edge case does the most damage.

**Step 1 — RE-VERIFY THE FINDING.**
Open `WARDRESS_AUDIT_FINDINGS.md`, locate the exact finding by its title fragment, read the full entry (Evidence, Impact, Confidence). Re-run whatever reproduction the audit describes against the *current* code (things may have already shifted slightly between the audit and now). If you cannot reproduce it, do not assume the audit was wrong — dig until you understand why the reproduction path is different now, and only then decide whether the finding is stale, and say so explicitly in the fix log before proceeding differently than planned.

**Step 2 — ROOT-CAUSE ANALYSIS.**
Trace the actual mechanism end to end. Do not stop at the first plausible cause — ask "why does this happen" until you hit the true, lowest-level cause (e.g., not "the check-then-set isn't atomic" but *why* it isn't atomic: no row lock, no unique constraint, no compare-and-swap, wrong isolation level — name the specific missing primitive).

**Step 3 — ENUMERATE EVERY EDGE CASE.** Before writing any fix code, write down (in your working notes, then condensed into the fix log) the full set of conditions the fix must hold under, drawing on the same checklist the audit used:
- Concurrent/simultaneous access (two, and where relevant N, actors racing the same operation)
- Empty / null / missing / wrong-type / oversized / malformed input
- Unicode, RTL, non-English text, extreme lengths, boundary numeric values (0, negative, NaN/Infinity, max-int)
- Partial failure mid-operation (crash/timeout after step 1 of N but before step N)
- Retry / idempotency (does a retried operation double-apply the effect?)
- Auth/RBAC interaction (does the fix change who can trigger this path, intentionally or not?)
- Interaction with **other findings already fixed** in earlier phases — check `WARDRESS_FIX_LOG.md` for anything touching the same subsystem
- Backward compatibility with existing data already in the DB/filesystem from before the fix
- Performance impact at realistic scale, not just the reproduction's toy scale
- What happens if the fix itself fails or times out

If a category genuinely doesn't apply, write "N/A — <one-line reason>," don't silently omit it.

**Step 4 — DESIGN THE FIX.**
For anything non-trivial, consider at least two candidate approaches and briefly weigh them (correctness, performance, consistency with existing codebase idioms, blast radius) before picking one. Prefer the codebase's existing patterns (e.g., if other race conditions in this codebase are fixed with a Postgres partial unique index + `SELECT ... FOR UPDATE`, use that same primitive here unless there's a specific reason not to — and if so, say why). If the audit's suggested direction is incomplete or wrong given your Step 3 enumeration, deviate and record why.

**Step 5 — IMPLEMENT.**
Minimal, scoped, idiomatic. Match the surrounding code's style. No unrelated changes (Rule 1).

**Step 6 — WRITE / EXTEND TESTS.**
Every edge case from Step 3 that is plausible to exercise automatically gets an automated test. At minimum:
- A test that would have **failed against the pre-fix code** (proves you're testing the real bug, not a strawman)
- A test for each concurrency scenario identified (using real concurrent execution — threads/async tasks/multiple processes hitting a real test-Postgres instance — not a mocked-away version that can't actually race)
- Tests for the boundary/malformed-input cases identified
- If a case genuinely can't be automated (e.g., a Windows GUI prompt), perform and document a manual verification instead, and say explicitly why it isn't automated

**Step 7 — RUN THE FULL EXISTING SUITE.**
Backend `pytest` (full, not just the new file), frontend `vitest`, `pnpm exec tsc --noEmit`, `pnpm exec oxlint src`, and any backend linter/type-checker the project uses. Every one of these must be green, not just "mostly passing" or "the failures are pre-existing" — if a failure is genuinely pre-existing and unrelated, verify that by checking it also fails on the pre-fix commit, and note it in the fix log rather than silently accepting it.

**Step 8 — ITERATE ON FAILURE.**
If step 6 or 7 turns up a problem, go back to Step 2 or 4 — do not patch around a test failure with a narrower test or a special-cased fix that doesn't address the root cause. There is no fixed iteration cap — keep going as long as each iteration produces new information and narrows the problem. If you reach a point where iteration is no longer converging (you're re-trying the same fix shape without new evidence), stop, write up exactly what you tried, why it didn't work, and what you believe the real blocker is, and leave the phase `In progress (partial — see notes)` rather than forcing a false "Complete."

**Step 9 — LOG AND COMMIT.**
Append the fix-log entry (format in §3), update the progress tracker table, commit (Rule 9), then stop per Rule 8 — do not continue into the next phase in the same session.

---

## 3. FIX LOG ENTRY FORMAT (append to `WARDRESS_FIX_LOG.md`, one per finding)

```
### [FIXED] <finding title fragment, copied verbatim from WARDRESS_AUDIT_FINDINGS.md>

- **Original severity**: Critical / High / Medium / Low
- **Phase**: N — <phase name>
- **Files changed**: path/to/file.py:120-145, path/to/other.tsx:40-60
- **Re-verification (Step 1)**: how you confirmed the finding still reproduces on current code; if it didn't, what changed and why
- **Root cause (Step 2)**: the actual lowest-level mechanism, not the symptom
- **Edge cases enumerated (Step 3)**: the full list from your analysis, each with how it's addressed or why N/A
- **Fix design considered (Step 4)**: candidate approaches weighed, and why the chosen one won
- **Fix applied (Step 5)**: concrete description of the real change made (unlike the audit file, this is not "direction only" — describe what you actually did)
- **Tests added/modified (Step 6)**: file:test_name — what each one proves, and confirmation that at least one failed pre-fix
- **Full regression result (Step 7)**: exact commands run and pass/fail/skip counts for every suite
- **Interactions with prior fixes**: anything in this subsystem touched by an earlier phase, and confirmation it's still correct
- **Residual risk / follow-ups**: anything not fully closed, deferred with justification, or a new lead spotted outside this phase's scope
- **Commit**: <short hash> — <message>
```

---

## 4. THE PHASE PLAN

### 4.0 Ordering principles

1. **Foundational infrastructure first.** Two High findings block reliable verification of almost everything else (a Postgres-only test harness, and a broken CI pipeline). These are Phases 1–2, before any other fix.
2. **Severity order after that**: all remaining High findings, then Medium, then Low.
3. **Within High**, findings are sequenced so that the risk-fusion model fix (which requires constructing a new training dataset from scratch — see §4.2 fusion arc) sits after the detection-layer High findings it depends on understanding, and the docs-correction High finding sits last, so it can describe *actually-fixed* behavior instead of needing a second pass.
4. **Within Medium and Low**, findings are pre-clustered into phases by *subsystem*, 1–4 findings per phase depending on coupling and risk (never more than 4; high-risk clusters like concurrency get 1–2). These clusters are a **starting plan, not gospel** — at the start of each Medium/Low phase, read the full text of every finding assigned to it before finalizing scope; if two "clustered" findings turn out to be more entangled or more independent than assumed, split or merge them and note the deviation in the tracker.
5. **Docs-correction findings are deliberately scheduled last** within their severity band (and the true doc-sync sweep is its own final phase) — no point correcting documentation before the behavior it describes has stopped changing.
6. **Final phases** re-run a compressed version of the original audit's own methodology against the *fixed* codebase, to catch anything the phase-by-phase approach missed, then do one last full docs/README sync, then close out.

Use this exact locator convention: to find a finding's full entry, `grep -n "<first 8–10 words of the title fragment>" WARDRESS_AUDIT_FINDINGS.md` — the fragments below are copied verbatim from the audit file's own headers for exactly this purpose.

---

### 4.1 Foundational phases (must run first, in order)

| Phase | Name | Scope |
|---|---|---|
| 0 | Fix-Effort Ground Truth Recon | No code changes. The user has already provided a fresh Wardress install in Docker before this phase begins (per Rule 10) — do not run `scripts/install.ps1` yourself. Confirm you're on the correct branch and the checkout is otherwise as expected (clean working tree, no stray uncommitted changes). Re-run the full existing test suite and record the baseline pass/fail counts fresh (they may have drifted since the audit). Create `WARDRESS_FIX_LOG.md` with the initial content in §6 if it doesn't exist yet. Confirm Docker, Postgres/Redis containers, and (separately) Windows/pwsh are all actually available as expected before phase 1 begins. |
| 1 | Postgres Test-Harness Migration | Finding: *"The entire suite runs on SQLite while production runs Postgres: migration-only unique indexes are absent from model metadata and VARCHAR widths are unenforced"* (High). Point the backend test suite at a real, disposable Postgres instance (Docker) instead of in-memory SQLite/aiosqlite — via `alembic upgrade head` against it, not `Base.metadata.create_all`, so migration-only constraints (unique indexes, VARCHAR widths, partial indexes) are actually enforced in tests. Update `conftest.py`, CI config, and `README.md`'s "Backend Development" instructions together (they currently describe the SQLite path). This is the single highest-leverage phase — every concurrency/race fix after it depends on tests that can actually observe Postgres-only constraints. |
| 2 | CI Pipeline Stabilization | Finding: *"CI is red on main at three independent gates — lint and both dependency audits fail on the committed tree"* (High). Fix each failing gate at its root cause (not by silencing/skipping the check). Confirm the pipeline is genuinely blocking (a failing gate fails the build, not just prints a warning) before closing. |

---

### 4.2 High-severity phases (Phases 3–14, in order)

| Phase | Finding title fragment (grep this) | Notes |
|---|---|---|
| 3 | `Redis outage breaks the designed enqueue-degradation contract` | Baselines get stuck `pending`; fix the enqueue/degradation contract so a Redis outage fails fast and cleanly instead of hanging then leaving inconsistent DB state. |
| 4 | `Concurrent confirms of one remediation execution all succeed and each enqueues a webhook fire` | Needs an atomic claim (DB-level), not an application check-then-set. Write real concurrent tests against Postgres (Phase 1 dependency). |
| 5 | `Concurrent confirm+dismiss of one remediation execution both return success and last-writer-wins` | Same family as Phase 4 — do both together only if, after reading both finding bodies, they share one atomic-claim mechanism; otherwise keep separate per Rule 4.0.4. |
| 6 | `Layer-1 hash gate permanently disables the visual layer for defacements that don't alter the serialized DOM` | Core detection-efficacy bug. Fix the gating logic; add adversarial tests using server-side asset swaps that don't touch the DOM. |
| 7 | `Realistic single-vector defacements fuse far below the default flag threshold` | Depends on understanding the fusion arc (Phases 8–10) — implement whatever non-fusion-model part of the fix belongs here (e.g., per-layer threshold/weighting bugs), and explicitly hand off anything that's actually a fusion-coefficient problem to Phase 8. |
| 8 | `Fusion coefficients are sign-inverted for DOM-churn and security-metadata evidence` | **Fusion Arc, Part A — dataset construction.** See detailed sub-plan below. No original training data exists; build a new synthetic dataset from scratch with explicit anti-bias controls. |
| 9 | *(continuation, no new finding — Fusion Arc Part B)* | Refit the logistic regression against the Phase 8 dataset; validate monotonicity, calibration, and cross-validation; document every coefficient's justification. |
| 10 | *(continuation, no new finding — Fusion Arc Part C)* | Integrate the refit model into the pipeline; re-run Phase 6/7's adversarial tests to confirm they now pass without the original model's false negatives; confirm no regression on a held-out benign-dynamic-content test set (ads rotating, timestamps, cache-busting params, A/B tests). |
| 11 | `Monitored-site text reaches the agent's model context through explain_incident and can steer auto-executing tier-1 tools` | Prompt-injection containment fix in `app/agent/guard.py` / `engine.py`. Build a real adversarial test corpus of injected instructions inside scanned-page evidence text, not just the one example from the audit. |
| 12 | `Zero end-to-end flagging coverage for realistic attacks` | Run this **after** Phases 6, 7, and 8–10 land, since it requires writing integration tests that exercise the now-fixed detection/fusion behavior end to end — verify the specific gaps named in the finding (escalation-band monkeypatch, suite-wide mocked embeddings) are gone, not just added-to. |
| 13 | `uninstall.ps1 deletes all data volumes even when the backup partially failed` | Windows/pwsh available per your setup — actually execute this script against a **separate, disposable throwaway install** (not the main working deployment from Rule 10), including forced backup-failure scenarios, not just read it. This disposable install/uninstall cycle is scoped to verifying this one script and does not reset or replace the persistent working checkout the rest of the effort runs against. |
| 14 | `Headline detection-assurance claims in README/introduction contradict the audit's measured detection behavior` | Run last among High findings — by now the actual detection behavior has changed from what the audit measured; re-verify current behavior fresh before rewriting the claims, don't just copy the audit's old numbers. |

**Fusion Arc detail (Phases 8–10) — synthetic dataset construction, per your instruction to avoid bias:**
- Generate labeled samples programmatically across **both** classes and **all known evasion axes** found in the detection-layer findings: single-vector attacks, leetspeak variants, non-English/script-mixed defacements, hue-only recoloring, sub-threshold combined attacks, and multiple independent benign-drift scenarios (rotating ads, timestamps, A/B test variants, minor CSS/asset churn, cache-busting query params).
- **Explicit anti-bias controls, all mandatory and all logged in the fix log:**
  - Balanced classes (not a 95/5 skew toward benign, which would trivially minimize loss by underweighting attacks)
  - Stratified across every evasion axis and language, not concentrated on the exact literal examples from the audit findings (using only those would be overfitting to the test, not fixing the model)
  - A genuine train/validation/held-out-test split with **zero leakage** (no sample or near-duplicate appears in more than one split)
  - Sanity-check rows: trivially-obvious attacks and trivially-obvious benign cases, to catch a degenerate model early
  - Document the full generation methodology (not just the resulting dataset) in the fix log, so a future session can audit the dataset's construction, not just trust the numbers
- After refitting: report ROC/calibration curves, confirm **monotonicity** in attack evidence (more evidence never lowers risk score — the exact property Finding 5.1 showed was violated), and confirm the refit model is not simply saturated (the exact failure mode of the original, per the Medium finding on the "calibrated" claim).

---

### 4.3 Medium-severity phases (Phases 15–34)

| Phase | Cluster | Finding title fragments (grep each) |
|---|---|---|
| 15 | Sites/bulk-import router integrity & perf | `No uniqueness on sites.url`; `GET /api/sites runs 1+2N queries`; `Bulk-import CSV parser uses QUOTE_NONE` |
| 16 | Outbound-fetch / SSRF-adjacent | `NAT64/DNS64 addresses: relaxed SSRF policy`; `/api/settings/ai/ollama/pull fetches an arbitrary unvalidated base_url` |
| 17 | Auth & audit-log robustness | `No brute-force defense on login`; `Audit target_label overflows its VARCHAR(256)` |
| 18 | Scan/baseline concurrency races | `Concurrent scan-now through the stale-supersede path loses the race`; `Baselines have no in-flight uniqueness backstop` |
| 19 | Alert-ack concurrency race | `Concurrent alert acknowledgements produce duplicate audit rows` |
| 20 | Detection Layer 8 weakness | `Layer 8 semantic drift is blind past a 5,000-char cap` |
| 21 | Detection Layer 7 weakness | `Layer 7 cloaking soft knee admits up to ~50% divergent crawler-facing content` |
| 22 | Detection Layer 5 weakness | `Layer 5 misses common leetspeak variants` |
| 23 | Detection Layer 2 weakness | `Layer 2 hidden-element counting only recognizes inline styles` |
| 24 | Detection degradation-signaling gap | `Capture/probe degradation is indistinguishable from "no change"` |
| 25 | Agent subsystem | `Concurrent confirms of one pending agent action double-execute`; `Agent tool list_remediation_hooks exposes admin-only remediation-hook configuration` |
| 26 | Remediation-hook safety | `Remediation hook URLs bypass the codebase's entire SSRF discipline`; `Schema-valid but unfetchable webhook URL leaves the execution stuck queued forever` |
| 27 | Frontend data-honesty & third-party leakage | `Health page presents hardcoded, fabricated telemetry`; `Dashboard leaks monitored hostnames to Google's favicon service` |
| 28 | Frontend accessibility | `Core navigation rows, expanders, tabs and dropdowns are keyboard-inaccessible and ARIA-bare` |
| 29 | Ops/scripts robustness | `Database backup/restore silently destroys all non-ASCII content`; `Every entry-point script hangs forever when the Docker CLI wedges`; `ADMIN_RESET_PASSWORD emergency-recovery knob is unreachable` |
| 30 | Test-quality (mechanical) | `Tautological and vacuous assertions sit on safety-critical surfaces`; `Non-hermetic unit test makes live external DNS queries` |
| 31 | Test-quality (new coverage) | `Two safety-critical code paths have zero test coverage` (remediation webhook firing path + agent engine turn loop — write real, non-mocked coverage for both) |
| 32 | Test-quality (post-fix rewrite) | `Tests codify defective behavior as expected` — **run only after** Phases 6 (hash-gating), 24 (degradation-as-zero), 27 (favicon leak), and the Low-severity unauthenticated-logout fix (Low sweep 1) have all landed, since this finding is about tests that currently assert the *old, broken* behavior as correct. |
| 33 | Docs sweep A (ops/remediation) | `Docs claim operators can approve remediations via the Telegram Bot`; `README claims remediation executions run "in a separate Celery queue"`; `Uninstall documentation promises a backup-then-delete safety contract` |
| 34 | Docs sweep B (detection/agent) | `Three separate docs assert that an identical content hash guarantees identical rendered pixels`; `agent.mdx overstates agent safety` — plus the fusion-arc's own `"calibrated"` doc claim from Phase 8–10 if not already closed there |

---

### 4.4 Low-severity sweep phases (Phases 35–41)

Low findings are batched more aggressively (they are independent, narrow-blast-radius items) but every single one still goes through the full Gauntlet Loop — "Low severity" describes impact, not the rigor owed to it.

| Phase | Sweep | Finding title fragments (grep each) |
|---|---|---|
| 35 | Backend correctness sweep | `logout requires an interactive JWT session and rejects API keys" is not implemented`; `NaN/Infinity in any float field returns 500`; `Whitespace-only names pass PATCH validation`; `Duplicate field definition acting_user_email`; `Worker calls DNS-resolving assert_url_allowed synchronously inside async functions` |
| 36 | Detection-layer low-severity code fixes | `Layer 3 URL normalization diverges from browser (WHATWG) URL parsing`; `Layer 4 compares grayscale only`; `Layer 6 header diff scores any value change as "weakening"` |
| 37 | Scheduling / agent / remediation low-severity | `Overlapping Beat dispatcher ticks abort mid-loop with IntegrityError`; `Agent conversation creation is uncapped`; `No firing cap or cooldown on auto-execute hooks` |
| 38 | Frontend UX/a11y sweep | `No prefers-reduced-motion support anywhere`; `Sites empty-state tells operators the product does "manual scans only"`; `Malformed arc flag in the topology scheduler icon's SVG path`; `Numeric config inputs silently coerce garbage to defaults`; `Assistant conversation deletion has no confirmation`; `Assistant retry-after-error duplicates the user's message bubble` |
| 39 | Ops/scripts & config sweep | `Failed image builds leave build log litter in the repo root`; `Installer/updater console-output integrity`; `diagnostics.ps1 writes its bundle into the repo root`; `Six Settings fields are env-overridable in code but forwarded by neither compose nor .env.example`; `Successful catalog syncs rewrite a tracked source-tree file at runtime` |
| 40 | CI & test-quality low-severity sweep | `All GitHub Actions are pinned to mutable major tags`; `The dependency-audit gate cannot see torch`; `Process-env mutation in test_auth.py cleans up outside try/finally`; `Frontend behavioral coverage is near-zero for the actual pages` |
| 41 | Final docs sweep (all remaining doc-only findings) | `Docs instruct admins to "edit the hook and disable requires_manual_confirm"`; `The documented frontend type-check command compiles zero files`; `RBAC tables grant viewers API-key management, but key creation is analyst+`; `Semantics doc claims MiniLM embeds the "full" visible text`; `Layer-6 header diff is documented as scoring "weakening"/"downgrades"`; `Usage doc claims login rate limits exist "to prevent brute-force attacks"`; `Link-audit diagram contradicts its own table and the code` |

---

### 4.5 Final phases (Phases 42–44)

| Phase | Name | Scope |
|---|---|---|
| 42 | Compressed Re-Audit | Re-run a condensed version of the *original* audit's adversarial methodology (§2 of `WARDRESS_PARANOID_AUDIT_PROTOCOL.md`) against the now-fixed codebase — spot-check every subsystem that received a fix, specifically hunting for regressions or incomplete fixes the phase-by-phase approach might have missed, plus fresh adversarial input on the areas with the heaviest changes (fusion model, concurrency primitives). This phase may re-open a "finding" if something is still broken — if so, do **not** patch it inline; log it in `WARDRESS_FIX_LOG.md` as a new finding needing its own future phase, following the audit's own finding format from §3 of the audit protocol. |
| 43 | Final Docs/README Sync | One last full pass reconciling `README.md` and every `docs/` file against the fully-fixed, fully-re-audited codebase — not against what any individual phase's notes claimed, but against direct fresh verification. |
| 44 | Closing Report | Full test suite run one final time, full pass/fail counts recorded, `WARDRESS_FIX_LOG.md` progress tracker marked fully Complete, and a short closing summary written into the log: total findings closed, any findings deliberately left open with justification, and overall confidence assessment. |

---

## 5. THE KICKOFF PROMPT (reusable template — paste into a new chat to start/continue any phase)

```
Before anything else: check whether C:\Users\Ns8pc\Music\WARDRESS\WARDRESS_FIX_LOG.md exists yet.

- If it does NOT exist yet (this is the very first-ever run of this effort, i.e. Phase 0):
  confirm you're on the correct branch and the checkout is otherwise as expected (clean working
  tree, no stray uncommitted changes from something else). If anything looks wrong, STOP and tell
  me immediately. Otherwise, proceed straight to "read the three files."
- If it DOES exist: confirm via `git log --oneline` that every commit WARDRESS_FIX_LOG.md's
  progress tracker claims as done is actually present in this checkout (this is the same
  deployment installed once at the start of the whole effort — it has not been reinstalled since,
  so nothing should be missing). If any commits are missing, STOP and tell me immediately — do not
  proceed or re-do work silently.

Once that check passes, read these files COMPLETELY, start to finish, not skimmed and not partial
— each one in full before moving to the next:
1. C:\Users\Ns8pc\Music\WARDRESS\WARDRESS_PARANOID_FIX_PROTOCOL.md — every rule applies to this
   phase, not just the ones that seem relevant at a glance.
2. C:\Users\Ns8pc\Music\WARDRESS\WARDRESS_AUDIT_FINDINGS.md — the full file, not just the
   section for this phase's finding(s). Findings reference and interact with each other, and you
   need the whole picture, not a fragment.
3. C:\Users\Ns8pc\Music\WARDRESS\WARDRESS_FIX_LOG.md, if it exists — the full history of what
   every prior phase already fixed, why, and how it was proven, plus the progress tracker showing
   which phase is next. If it does not exist yet, this is Phase 0 and you will create it per §6.

Execute the next incomplete phase now, following every rule in the protocol file exactly — the full
Gauntlet Loop (re-verify, root-cause, enumerate every edge case, design, implement, test, full
regression, iterate, log) for every finding in scope. No scope creep. No feature additions. Full
existing test suite must be green before you're done, not just your new tests.

When the phase is fully done: update the progress tracker and append your fix-log entry/entries to
C:\Users\Ns8pc\Music\WARDRESS\WARDRESS_FIX_LOG.md, commit (do not push), then output the next
kickoff prompt for me to use, then stop.
```

(For Phase 0 specifically, on the very first-ever run: after the branch/clean-tree check above passes, create `WARDRESS_FIX_LOG.md` with the initial content in §6 before starting Phase 0's actual work — it won't exist yet, and Phase 0 itself is what brings it into existence.)

---

## 6. INITIAL STATE OF `WARDRESS_FIX_LOG.md` (create with exactly this content if it does not yet exist)

```markdown
# Wardress Fix Log — Implementation Progress

Source of truth for *what's wrong*: WARDRESS_AUDIT_FINDINGS.md (read-only, never edited here).
Source of truth for *how it's being fixed*: this file.

## Progress Tracker

| Phase | Name | Status | Session Date | Commit |
|---|---|---|---|---|
| 0 | Fix-Effort Ground Truth Recon | Not started | | |
| 1 | Postgres Test-Harness Migration | Not started | | |
| 2 | CI Pipeline Stabilization | Not started | | |
| 3 | Redis Outage Enqueue-Degradation Fix | Not started | | |
| 4 | Remediation Confirm Race (double-fire) | Not started | | |
| 5 | Remediation Confirm+Dismiss Race | Not started | | |
| 6 | Layer-1 Hash Gate Visual-Layer Bypass | Not started | | |
| 7 | Single-Vector Defacement Fusion Miss (non-model part) | Not started | | |
| 8 | Fusion Arc Part A — Synthetic Dataset Construction | Not started | | |
| 9 | Fusion Arc Part B — Refit & Calibration | Not started | | |
| 10 | Fusion Arc Part C — Integration & Validation | Not started | | |
| 11 | Agent Prompt-Injection Containment | Not started | | |
| 12 | End-to-End Flagging Coverage | Not started | | |
| 13 | uninstall.ps1 Backup-Failure Safety | Not started | | |
| 14 | README Detection-Assurance Claims Sync | Not started | | |
| 15 | Sites/Bulk-Import Router Integrity & Perf | Not started | | |
| 16 | Outbound-Fetch / SSRF-Adjacent Medium Fixes | Not started | | |
| 17 | Auth & Audit-Log Robustness | Not started | | |
| 18 | Scan/Baseline Concurrency Races (Medium) | Not started | | |
| 19 | Alert-Ack Concurrency Race | Not started | | |
| 20 | Detection Layer 8 Weakness | Not started | | |
| 21 | Detection Layer 7 Weakness | Not started | | |
| 22 | Detection Layer 5 Weakness | Not started | | |
| 23 | Detection Layer 2 Weakness | Not started | | |
| 24 | Detection Degradation-Signaling Gap | Not started | | |
| 25 | Agent Subsystem Medium Fixes | Not started | | |
| 26 | Remediation-Hook Safety Medium Fixes | Not started | | |
| 27 | Frontend Data-Honesty & Third-Party Leakage | Not started | | |
| 28 | Frontend Accessibility | Not started | | |
| 29 | Ops/Scripts Robustness (Medium) | Not started | | |
| 30 | Test-Quality Mechanical Fixes | Not started | | |
| 31 | Test-Quality New Coverage (webhook + agent loop) | Not started | | |
| 32 | Test-Quality Post-Fix Rewrite | Not started | | |
| 33 | Docs Sweep A (ops/remediation) | Not started | | |
| 34 | Docs Sweep B (detection/agent) | Not started | | |
| 35 | Low Sweep — Backend Correctness | Not started | | |
| 36 | Low Sweep — Detection-Layer Code | Not started | | |
| 37 | Low Sweep — Scheduling/Agent/Remediation | Not started | | |
| 38 | Low Sweep — Frontend UX/A11y | Not started | | |
| 39 | Low Sweep — Ops/Scripts & Config | Not started | | |
| 40 | Low Sweep — CI & Test-Quality | Not started | | |
| 41 | Low Sweep — Final Docs | Not started | | |
| 42 | Compressed Re-Audit | Not started | | |
| 43 | Final Docs/README Sync | Not started | | |
| 44 | Closing Report | Not started | | |

Status values: `Not started` / `In progress (partial — see notes)` / `Complete`

## Phase 0 Notes
*(filled in during Phase 0 — fresh baseline test results, environment confirmation, branch/checkout sanity confirmed)*

## New Leads Observed (Not Yet In Scope)
*(anything spotted during a phase that isn't already a finding in WARDRESS_AUDIT_FINDINGS.md — logged here, not acted on, until a future phase is explicitly planned for it)*

---

## Fix Entries

*(fix-log entries appended here per phase, using the exact format defined in WARDRESS_PARANOID_FIX_PROTOCOL.md Section 3)*
```

---

## 7. A NOTE ON DISCIPLINE

The single biggest failure mode for a fix effort like this is declaring victory early: patching the symptom the audit described, watching the one obvious reproduction case go green, and moving on without ever enumerating the edge cases that made the original bug possible in the first place. A race condition fixed for two concurrent actors but not three, a validation fix that handles empty strings but not whitespace-only ones, a fusion-model refit validated only on the audit's own literal examples instead of a genuinely independent held-out set — these are not fixes, they are the same bug wearing a disguise that will resurface the next time someone runs an adversarial pass. The Gauntlet Loop in §2 exists specifically to make that shortcut structurally harder to take. Depth over speed, every phase, every finding — the 45-phase structure exists so that depth never has to compete with a shrinking context window.
