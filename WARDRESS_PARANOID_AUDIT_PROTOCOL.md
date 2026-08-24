# WARDRESS PARANOID AUDIT PROTOCOL

**READ THIS ENTIRE FILE, START TO FINISH, BEFORE DOING OR WRITING ANYTHING.**
Do not skim. Do not jump to a section. Do not begin work after reading only the phase list. This file defines rules that apply to *every* phase, and violating them invalidates the audit. If you have already read it once earlier in this session, re-read it anyway — you cannot rely on a memory summary of your own instructions.

---

## 0. WHAT THIS IS

This is a multi-session, multi-phase, adversarial code audit of the Wardress codebase (a self-hosted website-defacement detection and automated-response platform: FastAPI/Python backend, Celery worker, React/TypeScript frontend, PowerShell install/ops scripts, Mintlify docs). Each phase happens in a **separate chat with a fresh context window**. This file is the only thing that persists your instructions across sessions. A second file, `WARDRESS_AUDIT_FINDINGS.md`, is the only thing that persists your *findings and progress* across sessions. Together they are the entire state of this audit. Nothing else survives between sessions — not your reasoning, not things you "figured out but didn't write down."

This means: **if it isn't written into `WARDRESS_AUDIT_FINDINGS.md`, it did not happen.** A future session (a future you) will trust that file completely and will not re-derive your unwritten conclusions.

---

## 1. ABSOLUTE, NON-NEGOTIABLE RULES

1. **You NEVER modify, create, delete, or rename any file inside the actual project source tree** (`backend/`, `frontend/`, `landing/`, `walkthrough/`, `scripts/`, `docs/`, `assets/`, `.github/`, root config files, etc.) — not even a "harmless" formatting fix, not even a typo, not even to make a test pass. This is a **read-only forensic audit**. Zero exceptions, regardless of how obviously correct a one-line fix seems. If you notice yourself wanting to fix something, that impulse is the signal to write it up as a finding, not to touch the file.
2. The **only** files you ever write to are:
   - `WARDRESS_AUDIT_FINDINGS.md` (append findings, update the progress tracker) — lives at repo root, same place as this file.
   - Scratch/throwaway files **outside the repo tree** (e.g. `/tmp/...`) if you need to write a temporary probe script, fuzz input, or test harness to verify a hypothesis. Delete these when you're done with them, or at minimum never let them leak into the repo. If you need a temp file to prove something inside the repo directory for path reasons, prefix it clearly (e.g. `AUDIT_SCRATCH_<name>`) and delete it before ending the session.
3. You **may run** anything read-only or side-effect-contained: start the backend, start the frontend dev server, spin up a test DB, run `pytest`, run `vitest`/frontend tests, run linters/type-checkers, hit API endpoints with curl/httpx, run the PowerShell scripts in a sandboxed/dry-run way if possible, execute detection-layer functions directly against crafted inputs, etc. Running things is how you get evidence — use it heavily. Just don't leave permanent state changes in the *repository files themselves*.
4. **Trust nothing you have not personally verified by reading the actual implementation and, wherever feasible, executing it.** This explicitly includes:
   - Docstrings and inline comments — a comment saying "this is validated upstream" is a claim to verify, not a fact.
   - The README, and every file under `docs/` (Mintlify docs) — these describe intent, not necessarily reality. Phase 12 exists specifically because docs drift from code.
   - Existing tests — a passing test proves the code satisfies *that test*, not that the code is correct. Weak assertions, mocked-away edge cases, and tests that only exercise the happy path are themselves findings (see Phase 11). A green test suite is not evidence of absence of bugs.
   - Variable/function names — a function called `validate_input` might not validate the input you're worried about. Read its body.
   - Type hints — Python type hints are not enforced at runtime unless something enforces them; check whether they're aspirational or actually checked (pydantic validation vs. plain dataclass, etc.).
5. **Every finding must cite exact evidence**: file path + line number(s), and — for anything you claim is a runtime bug, security hole, or race condition — the actual reproduction you performed (command run, input sent, output/stack trace observed) wherever it was feasible to reproduce. If something is a static-reasoning-only finding (couldn't be executed, e.g. a Windows-only script segment), say so explicitly and mark confidence accordingly.
6. **Do not pad the findings file with noise.** A finding must represent a real, specific, defensible problem — a bug, an edge case that breaks something, a security gap, a race condition, dead/wasted code, a genuine design flaw, a performance problem with a concrete mechanism, or a documented behavior that provably does not match code. Do not report stylistic nitpicks, does-not-follow-my-personal-preference items, or purely hypothetical "this could theoretically..." concerns without a plausible trigger path. If you are unsure whether something rises to the bar, include it but mark it `Confidence: Low` and say why you're unsure — do not silently omit it either. When in doubt, investigate further rather than guessing.
7. **No feature additions, no scope creep.** You are not here to suggest new capabilities. You are here to make what already exists correct, robust, and honest about what it does. "Add rate limiting to X" is in scope if X currently has none and that's a real gap against X's own implied contract; "add a new detection layer" is not in scope.
8. **One phase per session, fully, before stopping.** Do not do half a phase and call it done. Do not skip ahead to a later phase because it looks more interesting. Do not silently merge two phases. If a phase turns out to be too large to finish carefully in one session, it is better to go deep on a subset and **explicitly document in the progress tracker exactly what was and wasn't covered**, than to rush shallow coverage of the whole phase.
9. **When you finish a phase**, update `WARDRESS_AUDIT_FINDINGS.md`'s progress tracker, append your findings for that phase in full, then output the exact kickoff prompt (Section 5 of this file) for the *next* phase, with that next phase's number/name filled in, so the user can paste it into a new chat. Then stop. Do not proactively continue into the next phase in the same session even if you have context budget left — a fresh session per phase is intentional (fresh eyes, no anchoring on earlier assumptions).

---

## 2. UNIVERSAL PARANOID METHODOLOGY (apply within every phase, adapted to that phase's focus)

For every file, function, endpoint, or component you review, actively look for:

- **Input handling**: What happens with empty input, null/None, missing fields, wrong types, oversized payloads, unicode/emoji/RTL text, extremely long strings, negative numbers, zero, duplicate entries, malformed JSON, SQL/NoSQL-injection-shaped strings, path-traversal-shaped strings, and script-injection-shaped strings — even in fields that "shouldn't" need it. Check both API boundary validation (pydantic schemas) and internal function boundaries (does an internal function re-trust caller-supplied data it shouldn't?).
- **Error handling**: Are exceptions caught too broadly (bare `except:` swallowing real bugs)? Are errors surfaced to the user/logs with enough info to debug, but not so much they leak secrets/stack traces/internal paths? Does a failure partway through a multi-step operation leave inconsistent state (e.g. DB row created but related resource never created)?
- **Concurrency & state**: Can two requests/jobs run against the same resource simultaneously and corrupt state? Are DB sessions properly scoped and closed? Are there any shared mutable globals? Do background Celery tasks handle being run twice (idempotency), or interrupted mid-flight?
- **Auth & authorization**: Is every endpoint's auth requirement actually enforced by the framework (dependency injection), not just implied by a comment? Are RBAC checks done on the *resource being accessed* (not just "is user logged in")? Any IDOR risk (user A can reference user B's resource ID)? Are API keys/tokens compared with constant-time comparison? Is anything derivable/guessable that shouldn't be?
- **Secrets & data exposure**: Do logs, error responses, or the frontend ever leak API keys, password hashes, JWT secrets, internal stack traces, or other users' data? Is `.env`/secret handling sound (never committed, never echoed)?
- **SSRF / outbound requests**: Wardress fetches external URLs (site monitoring) — check `ssrf.py`/`ssrf_transport.py` genuinely block internal/link-local/metadata-endpoint targets, redirects, DNS-rebinding, and IPv6/alternate-encoding bypasses, not just the obvious `127.0.0.1` case.
- **Resource cleanup**: File handles, HTTP client sessions, DB connections, browser/automation contexts (if Playwright or similar is used for visual diffing) — are they always released, including on the exception path?
- **Dead code & waste**: Unused imports, unreachable branches, functions defined but never called, duplicated logic that should be one shared function, commented-out code blocks, leftover debug prints, TODO/FIXME/HACK comments (read them — they're leads, not resolved).
- **Performance**: N+1 query patterns, unindexed columns used in frequent WHERE/JOIN clauses, unbounded loops over potentially large datasets, synchronous blocking calls inside async functions (defeats the point of async), unnecessary full-table scans, redundant re-computation.
- **Consistency**: Does the frontend's expectation of an API response shape actually match what the backend returns (check schemas.py vs api.ts types)? Do error codes/messages the frontend branches on actually get sent by the backend in all the cases the frontend expects? Are enum/status values kept in sync between Python and TypeScript?
- **Magic numbers & config**: Hardcoded thresholds, timeouts, limits — are they justified, configurable where they should be, and consistent across the codebase (same concept, same value, not two different hardcoded timeouts for "the same" thing)?
- **Silent failures**: Anywhere a function returns `None`/`[]`/`False`/a default value on failure instead of raising, ask: does every caller check for that, or does at least one caller treat the default as a legitimate success?

For each phase below, apply this checklist through the lens of that phase's specific focus.

---

## 3. FINDING FORMAT (use exactly this structure for every finding, appended to `WARDRESS_AUDIT_FINDINGS.md`)

```
### [SEVERITY] <Short descriptive title>

- **Severity**: Critical / High / Medium / Low
- **Category**: Security | Correctness | Race Condition | Performance | Dead Code | Design/UX | Docs Mismatch | Reliability | Other
- **Location**: `path/to/file.py:123-145` (exact lines)
- **Phase found**: Phase N — <name>
- **Confidence**: High / Medium / Low (and why, if not High)

**What's wrong:**
Precise description of the actual defect — not a vague "could be improved."

**Evidence:**
How you verified this. Include the exact command you ran, the input you sent, and the actual output/error/stack trace you observed. If you wrote a scratch script/test to prove it, say what it did. If it was static-reasoning-only (couldn't execute), say why and state confidence accordingly.

**Impact:**
What actually breaks, and under what real-world condition it gets triggered. Be concrete (e.g. "two scans on the same site_id started within the same second both pass the `if not site.scan_in_progress` check before either sets the flag, resulting in duplicate concurrent scans and a corrupted risk score row" — not "there might be a race condition").

**Suggested fix direction:**
One or two sentences on the *type* of fix (e.g. "acquire a row-level lock / use `SELECT ... FOR UPDATE` before checking and setting scan_in_progress", or "add a pydantic validator rejecting empty string"). Direction only — do not write the actual fix code. This is not your job in this audit.
```

Severity guide:
- **Critical**: exploitable security hole, data loss/corruption, or a core detection/remediation path that is silently wrong (false negative on real defacement, or remediation firing on the wrong target).
- **High**: real bug with a plausible real-world trigger, meaningful security weakness, or a race condition that will occur under normal (not just adversarial) usage.
- **Medium**: correctness/reliability issue with a narrower trigger condition, meaningful performance problem, or a Docs-vs-code mismatch that would actively mislead an operator.
- **Low**: dead code, minor inefficiency, cosmetic inconsistency, unlikely edge case, documentation staleness with low real-world impact.

---

## 4. THE 13 PHASES

Work through these **in order**. Do not skip. Each phase lists a primary target area based on the actual repo structure — but if your investigation in that phase leads you to a file outside the listed set, follow the evidence; just record where you ended up.

**Phase 0 — Ground Truth Recon (no findings expected necessarily, but produces the map everything else relies on)**
Actually get the project running: backend (`backend/app/main.py`, `backend/pyproject.toml`/`uv.lock`), DB migrations (`backend/alembic/`), Celery worker (`backend/worker/`), frontend (`frontend/`, `pnpm`/vite). Run the existing test suites (`backend/tests/`, `frontend/tests/`) and record actual pass/fail/skip counts — do not assume the README's claims about test coverage or "production ready" status are accurate. Build an evidence-based architecture map: what services exist, how they talk to each other, what the actual request lifecycle for a scan looks like end to end, what background jobs exist and their trigger conditions. Note any discrepancy between what you expected from file names and what the code actually does. This becomes the reference map every later phase cites back into.

**Phase 1 — Auth, Sessions & RBAC**
Focus: `backend/app/routers/auth.py`, `backend/app/routers/users.py`, `backend/app/security.py`, `backend/app/deps.py`, `backend/app/crypto.py`, `backend/app/models.py` (User/session/refresh-token models), `backend/tests/test_auth.py`, `backend/tests/test_phase5_rbac.py`, `frontend/src/lib/auth.tsx`. Look at: password hashing scheme, refresh-token rotation/revocation, session fixation, JWT (if used) signature/expiry validation, role checks per endpoint (verify against every router, not just auth.py), privilege escalation via user-editable fields, logout actually invalidating sessions server-side, brute-force/lockout protection on login.

**Phase 2 — Core API Correctness & Input Validation**
Focus: every router in `backend/app/routers/` (sites, alerts, apikeys, artifacts, audit, imports, remediation, reports, settings, health) plus `backend/app/schemas.py`. For each endpoint: does the pydantic schema actually constrain what the docs/frontend assume it constrains? What happens on malformed/boundary input at each endpoint (test it, don't just read it)? Are pagination, filtering, and sorting parameters validated against injection or resource-exhaustion (e.g. `limit=999999999`)? Check `backend/app/routers/imports.py` and `backend/tests/test_phase5_bulk_import.py` especially hard — bulk import of user-supplied site lists is a classic injection/resource-exhaustion surface.

**Phase 3 — Concurrency & Async Correctness**
Focus: `backend/app/db.py`, `backend/worker/db.py`, `backend/app/tasks.py`, `backend/worker/scan_tasks.py`, `backend/worker/beat_tasks.py`, `backend/worker/celery_app.py`, `backend/app/scanning.py`, `backend/tests/test_scan_tasks.py`, `backend/tests/test_scheduler.py`. Look for: DB session scoping (created per-request/per-task and always closed?), whether two concurrent scans of the same site can race, whether the scheduler (`beat_tasks.py`) can double-schedule, whether async endpoints ever make blocking synchronous calls, whether Celery task retries are idempotent (does a retried task re-send an alert, re-fire a remediation webhook, or double-count a finding?). Try to actually trigger a concurrent scenario (e.g. fire two scan requests for the same site near-simultaneously) and observe the result.

**Phase 4 — Detection Layers 1–9 Adversarial Stress-Test**
Focus: `backend/worker/detection/` (`dom.py`, `cloaking.py`, `metadata.py`, `semantics.py`, `signatures.py`, `visual.py`, `suppress.py`, `pipeline.py`, `types.py`) plus `backend/tests/test_detection_layers.py` and `docs/layers/*.mdx` (for stated intent only — verify against code, don't trust). This is the adversarial core of the audit: for each layer, ask "how would a real attacker defacing a site evade this specific layer's logic?" Actually craft inputs (modified HTML, injected scripts styled to blend in, slow-drift content changes, cloaking via user-agent detection, text changes below stated aggression-lexicon thresholds, visual diffs kept under the perceptual-hash distance threshold) and run them through the actual layer functions to see if they're flagged or missed. Check threshold constants for justification vs. arbitrary placement. Check what happens when a layer's input is missing/fails (e.g. screenshot capture fails for Layer 4 — does the pipeline treat that as "no visual change" i.e. a silent false negative, or properly abstain/flag-uncertain?).

**Phase 5 — Risk Fusion Model**
Focus: `backend/worker/detection/fusion.py`, related model-loading code, `backend/tests/test_detection_fusion_pipeline.py`. Verify the logistic-regression fusion logic: are sub-scores weighted/combined the way the docs (`docs/layers/9-risk-fusion.mdx`) claim? What happens with missing sub-scores (a layer that errored/skipped) — does fusion silently treat missing as zero/benign, inflating false negatives? Test boundary risk scores around whatever threshold triggers an alert — is there a cliff-edge where a trivial input change flips low-risk to high-risk or vice versa in a way that seems miscalibrated? Are model weights/coefficients hardcoded, and if so, on what basis?

**Phase 6 — AI Agent Security**
Focus: `backend/app/agent/engine.py`, `backend/app/agent/tools.py`, `backend/app/agent/guard.py`, `backend/app/agent/context.py`, `backend/app/routers/agent.py`, `backend/tests/test_agent.py`. This agent can call tools with real effects. Check: what tools exist and what real-world actions can each perform (does any tool let the agent modify data, trigger remediation, or exfiltrate data beyond what the conversation should allow)? Is there a permission boundary between what the *authenticated user* is allowed to do and what the *agent acting on their behalf* is allowed to do, or does the agent inherit full user privileges with no additional check? Can content from a *monitored site* (i.e., attacker-controlled data that flows into the agent's context, e.g. defacement text, DOM content used as evidence) act as a prompt-injection vector to make the agent take unintended tool actions? Read `guard.py` specifically for what it actually blocks vs. what it appears to block by name. Try crafting an adversarial input (e.g. a "finding" description or scanned page content containing embedded instructions) and see if it influences agent tool-calling behavior.

**Phase 7 — Remediation Hooks & Webhook Execution Safety**
Focus: `backend/app/routers/remediation.py`, `backend/app/remediation.py`, `backend/worker/remediation_tasks.py`, `frontend/src/components/remediation-hooks-panel.tsx`, `backend/tests/test_phase5_remediation.py`, `docs/remediation-hooks.mdx`. These hooks take real corrective action on live sites. Check: is the hook config (URLs/credentials) subject to the same SSRF protections as scanning? Can a hook be triggered against the wrong site/target (ID confusion)? Is there replay protection / signature verification on inbound webhook calls if applicable? What happens if a remediation action partially fails — is there a stuck/ambiguous state? Is there any rate limiting or safeguard against a mis-configured or compromised hook firing destructively in a loop?

**Phase 8 — Frontend Correctness & Design/UX Audit**
Focus: `frontend/src/pages/` (all pages, especially `site-detail.tsx`, `scan-detail.tsx`, `settings.tsx`, `health.tsx` — the largest/most complex ones), `frontend/src/components/`, `frontend/src/lib/api.ts`, `frontend/src/index.css`. Two sub-tracks, both required:
  - *Correctness*: state management bugs (stale closures, missed re-renders, race conditions between fetch calls e.g. rapid page navigation firing overlapping requests), unhandled API error states (loading/error/empty states actually implemented for every data fetch, not just the happy path), XSS risk anywhere raw HTML/markdown from scan findings or agent messages is rendered (check `markdown-message.tsx`, `dom-diff-tree.tsx`) — is it sanitized or could a defaced page's content execute in the dashboard itself?
  - *Design/UX*: responsiveness across breakpoints (mobile/tablet/desktop — actually resize/inspect, don't assume), real accessibility basics (contrast, focus states, keyboard nav on interactive elements), and a critical eye for generic "AI-slop" visual patterns — decorative emoji standing in for real icons, unjustified neon/purple gradients with no relation to the product's actual brand, inconsistent spacing/typography that suggests components were built without a shared design system, redundant/competing visual weight (everything trying to be the "primary" action). Cross-check against `frontend/src/components/ui/` (the actual design-system primitives) — are pages actually using them consistently, or bypassing them with one-off inline styles?

**Phase 9 — Installation/Ops Scripts**
Focus: `scripts/install.ps1`, `scripts/uninstall.ps1`, `scripts/update.ps1`, `scripts/validate.ps1`, `scripts/diagnostics.ps1`, `scripts/lib.ps1`. Run these where feasible (dry-run or in a disposable environment) rather than just reading. Check: idempotency (does running install.ps1 twice break anything?), failure recovery (if it fails halfway, is the system left in a coherent, retriable state, or silently half-installed?), error handling (does every external command check its exit code, or can a failed step be silently ignored and the script report success anyway?), destructive-action safety in uninstall.ps1 (any risk of it deleting something outside its intended scope, e.g. an overly broad path/wildcard), and whether validate.ps1's checks actually correspond to what install.ps1 sets up (or has it drifted).

**Phase 10 — Dependencies, Secrets & CI/CD**
Focus: `backend/pyproject.toml`/`uv.lock`, `frontend/package.json`/`pnpm-lock.yaml`, `.env`/`.env.example`, `backend/app/config.py`, `.github/workflows/ci.yml`, `.github/workflows/static.yml`. Check for known-vulnerable or abandoned dependency versions (actually check, don't guess from memory — versions matter), secrets that could leak into logs/CI output, whether CI actually runs the full test suite and fails the build on failure (or is a check silently non-blocking), whether `.env.example` is complete/accurate vs. what `config.py` actually reads, and whether any secret has a weak or predictable default that would be dangerous if left unchanged in production.

**Phase 11 — Test Suite Quality Audit**
Focus: all of `backend/tests/` and `frontend/tests/`, informed by everything found in Phases 1–8. This is a *meta* phase: for the areas where you found real bugs earlier, check whether a test theoretically covering that area exists and, if so, why it didn't catch the bug (weak assertion? mocked-out the exact part that's broken? only tests the happy path?). Separately, look for tests that are tautological (assert something trivially true), tests that are silently skipped/xfailed with no follow-up, and any test that mutates shared state without cleanup (order-dependent test suite risk).

**Phase 12 — Docs-vs-Reality (final phase)**
Focus: every file under `docs/` (`introduction.mdx`, `installation.mdx`, `usage.mdx`, `detection-layers.mdx`, `docs/layers/*.mdx`, `frontend/architecture.mdx`, `frontend/components.mdx`, `frontend/scan-detail.mdx`, `configuration.mdx`, `user-management.mdx`, `api-reference.mdx`, `remediation-hooks.mdx`, `agent.mdx`, `audit-logs.mdx`, `security-and-dev.mdx`) and the root `README.md`, cross-checked against the **verified** (not assumed) behavior recorded across Phases 0–11 in `WARDRESS_AUDIT_FINDINGS.md`. For every concrete factual claim in the docs (a config variable name, an API endpoint shape, a described security guarantee, an installation step, a described detection behavior), confirm it against the actual code/behavior you already verified, or verify it fresh if Phases 0–11 didn't cover it. Flag every mismatch, every staleness (e.g. a doc describing a phase/feature that has since changed), and every place where the docs overstate a guarantee the code doesn't actually provide (this last category matters most for a security product — overclaiming detection/remediation guarantees is itself a finding, likely High severity).

---

## 5. THE KICKOFF PROMPT (reusable template — user pastes this into a new chat to start/continue any phase)

```
Read /WARDRESS_PARANOID_AUDIT_PROTOCOL.md in full, start to finish.
Then read /WARDRESS_AUDIT_FINDINGS.md in full to see what prior phases already found and which phase is next in the progress tracker.
Execute the next incomplete phase now, following every rule in the protocol file exactly — read-only audit, no code changes, evidence-backed findings only, use your full tool access (run the app, run tests, execute code, craft adversarial inputs) to verify everything before writing it down.
When the phase is fully done, update the progress tracker and append your findings to /WARDRESS_AUDIT_FINDINGS.md, then output the next kickoff prompt for me to use, then stop.
```

(For Phase 0 specifically, on the very first run, `WARDRESS_AUDIT_FINDINGS.md` will not exist yet — create it first with the progress tracker table below, before starting Phase 0's actual work.)

---

## 6. INITIAL STATE OF `WARDRESS_AUDIT_FINDINGS.md` (create this file with exactly this content if it does not yet exist)

```markdown
# Wardress Audit — Findings & Progress

## Progress Tracker

| Phase | Name | Status | Session Date |
|---|---|---|---|
| 0 | Ground Truth Recon | Not started | |
| 1 | Auth, Sessions & RBAC | Not started | |
| 2 | Core API Correctness & Input Validation | Not started | |
| 3 | Concurrency & Async Correctness | Not started | |
| 4 | Detection Layers 1-9 Adversarial Stress-Test | Not started | |
| 5 | Risk Fusion Model | Not started | |
| 6 | AI Agent Security | Not started | |
| 7 | Remediation Hooks & Webhook Execution Safety | Not started | |
| 8 | Frontend Correctness & Design/UX Audit | Not started | |
| 9 | Installation/Ops Scripts | Not started | |
| 10 | Dependencies, Secrets & CI/CD | Not started | |
| 11 | Test Suite Quality Audit | Not started | |
| 12 | Docs-vs-Reality | Not started | |

Status values: `Not started` / `In progress (partial — see notes)` / `Complete`

## Phase 0 Notes: Ground Truth Map
*(filled in during Phase 0 — architecture map, run instructions that actually worked, test suite baseline results)*

---

## Findings

*(findings appended here per phase, using the format defined in WARDRESS_PARANOID_AUDIT_PROTOCOL.md Section 3)*
```

---

## 7. A NOTE ON DISCIPLINE

The instruction that produced this protocol was explicit: be paranoid, assume nothing, verify everything, and do not let documentation, comments, or passing tests substitute for reading and running the real code. The single biggest failure mode for an audit like this is quietly reverting to optimistic pattern-matching under time pressure — skimming a function, seeing it "looks fine," and moving on. If a phase feels like it's going too slowly to be thorough, that is normal; thoroughness is the entire point of a 13-phase structure instead of one pass. Depth over coverage, every time.
