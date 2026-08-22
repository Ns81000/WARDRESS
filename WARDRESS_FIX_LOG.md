# Wardress Fix Log — Implementation Progress

Source of truth for *what's wrong*: WARDRESS_AUDIT_FINDINGS.md (read-only, never edited here).
Source of truth for *how it's being fixed*: this file.

## Progress Tracker

| Phase | Name | Status | Session Date | Commit |
|---|---|---|---|---|
| 0 | Fix-Effort Ground Truth Recon | Complete | 2026-08-22 | fix(phase0) |
| 1 | Postgres Test-Harness Migration | Complete | 2026-08-22 | fix(phase1) |
| 2 | CI Pipeline Stabilization | Complete | 2026-08-22 | fix(phase2) |
| 3 | Redis Outage Enqueue-Degradation Fix | Complete | 2026-08-22 | fix(phase3) |
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

Session date: 2026-08-22.

**Branch/checkout sanity (confirmed before any work):**
- Branch `main`, up to date with `origin/main`, HEAD `c3052cc` ("feat: add assistant chat page…").
- `WARDRESS_FIX_LOG.md` did not exist → this is the first-ever run of the fix effort (Phase 0).
- Working tree was not fully clean; disposition agreed with the user:
  - `scripts/lib.ps1` modified (3-line `$process.Handle` cache in `Build-Service`) — **user declared intentional**, predates the effort, left untouched, NOT part of any phase commit.
  - Untracked files `WARDRESS_AUDIT_FINDINGS.md`, `WARDRESS_PARANOID_AUDIT_PROTOCOL.md`,
    `WARDRESS_PARANOID_FIX_PROTOCOL.md`, `project_structure.txt`, `scripts/generate_structure.py` —
    artifacts of the audit effort / recon tooling, left untracked by agreement (none are gitignored).

**Fresh baseline test results (re-run this session, per Phase 0 scope):**

| Suite | Command | Result |
|---|---|---|
| Backend pytest | `backend: .venv\Scripts\python.exe -m pytest -q --tb=no` | **503 passed, 1 failed, 1 warning** (~286 s) |
| Frontend vitest | `frontend: pnpm test` | **7 files / 40 passed, 0 failed** (~35 s) |
| Frontend type-check | `pnpm type-check` (`tsc -b --noEmit`) | clean (exit 0) |
| Frontend lint | `pnpm exec oxlint src` | 0 errors, 12 warnings |
| Backend lint | `uv run --frozen ruff check .` | **2 errors**: `app/agent/tools.py:18 I001`, `app/routers/settings.py:869 S110` |
| Backend format | `uv run --frozen ruff format --check .` | **17 files would be reformatted** |

The single backend failure is `tests/test_ai_migration.py::test_ollama_cloud_key_flows_into_deployment`
re-raised with traceback this session:
`app.ai_config.ProviderConfigError: Host 'ollama.com' resolves to a blocked address (64:ff9b::2224:850f)`
— exactly Finding 0.1's DNS64/NAT64 mechanism (this host's resolver returns a `64:ff9b::/96` AAAA).
Environment-triggered, pre-existing, matches the audit's own Phase 0 baseline (503/1). Not caused by
any fix work (none has happened yet); its root fix belongs to the NAT64/DNS64 SSRF finding (Phase 16),
its hermeticity aspect to Finding "Non-hermetic unit test makes live external DNS queries" (Phase 30).

The backend ruff failures are the pre-existing state described by audit Finding 10.1 ("CI is red on
main at three independent gates") — recorded here as baseline ground truth; fixing them is Phase 2's
scope, not silently accepted beyond it. Frontend suites/lint/type-check are green at baseline.

**Environment confirmation (per Phase 0 scope):**
- Docker engine 28.3.2 + Compose v2.39.1 — both working.
- Fresh Wardress install is up (installed once by the user before this phase, per protocol Rule 10;
  `scripts/install.ps1` was NOT run by the session): containers `wardress-app-1` (healthy),
  `wardress-worker-1`, `wardress-beat-1`, `wardress-db-1` (healthy), `wardress-redis-1` (healthy).
- Windows/pwsh available: PowerShell 7.6.0; backend venv and frontend `node_modules` present.
- No code changes were made in this phase (Phase 0 is recon-only).

## New Leads Observed (Not Yet In Scope)
*(anything spotted during a phase that isn't already a finding in WARDRESS_AUDIT_FINDINGS.md — logged here, not acted on, until a future phase is explicitly planned for it)*

- **Phase 2**: `.github/workflows/ci.yml:62` — the pip-audit step's comment says a known vulnerability "must be triaged in PROGRESS.md", but no `PROGRESS.md` exists anywhere in the repo (the effort's log is the untracked-by-agreement `WARDRESS_FIX_LOG.md`). Stale in-repo comment only; no behavioral effect. Candidate for a docs/CI hygiene sweep (e.g. Phase 40) rather than its own fix.
- **Phase 3**: `backend/app/routers/imports.py:350-354` — the bulk-import enqueue loop calls `enqueue_baseline_capture` directly on the event loop, unlike every services-layer caller which offloads via `asyncio.to_thread` (services.py:132). Latency-bounded today (publish is fast when Redis is up; failures now fail fast), but it is an inconsistency with the codebase's own async-hygiene discipline. Noted, not acted on (no observable defect at realistic scale).

---

## Fix Entries

*(fix-log entries appended here per phase, using the exact format defined in WARDRESS_PARANOID_FIX_PROTOCOL.md Section 3)*

### [FIXED] The entire suite runs on SQLite while production runs Postgres: migration-only unique indexes are absent from model metadata and VARCHAR widths are unenforced

- **Original severity**: High
- **Phase**: 1 — Postgres Test-Harness Migration
- **Files changed**: `backend/tests/conftest.py` (rewritten — Postgres fixtures), `backend/tests/db_harness.py` (new — harness mechanics), `backend/tests/test_test_harness.py` (new — 11 self-tests), `backend/tests/test_scan_tasks.py:219-231` (one test updated to enforced-FK semantics), `.github/workflows/ci.yml` (backend job gains a postgres service + env; stale "not the SQLite the unit suite uses" comment corrected), `README.md` ("Backend Development" section rewritten)
- **Re-verification (Step 1)**: Confirmed still true on current code, by execution (scratch probe outside the repo, deleted afterwards): (a) model metadata does not declare `ix_scans_one_inflight_per_site` (full index-name enumeration printed; absent), so any `create_all` schema lacks it; (b) SQLite stored a 400-char string into `VARCHAR(256)` `audit_log.target_label` and reported length 400; (c) two simultaneous `pending` scans for one site were stored under the old harness schema. Also re-read `conftest.py` (`sqlite+aiosqlite://` + `Base.metadata.create_all`, function-scoped engine per test), `alembic/versions/g1h2i3j4k5l6_correctness_indexes.py` (partial index created for postgres dialect only, migration-only), `models.py:392` (`Baseline.site_id` FK `ondelete="CASCADE"`), and confirmed no test builds its own engine (the SQLite coupling is entirely inside conftest).
- **Root cause (Step 2)**: The harness derived the test schema from ORM metadata (`create_all`) on an ephemeral dialect instead of applying the production migration chain on the production dialect. Two structural consequences: schema objects declared only in Alembic revisions never exist in tests, and SQLite's type affinity ignores VARCHAR widths. The missing primitive is exactly what this phase adds: a disposable Postgres database whose schema is built by `alembic upgrade head`.
- **Edge cases enumerated (Step 3)**:
  - *Concurrent access*: two pytest sessions sharing one database would interleave truncations → addressed by an explicit single-session-per-database contract (conftest docstring + README); xdist is not used by this repo and remains unsupported by design.
  - *Missing/unreachable Postgres* → session fixture fails fast (~2 s measured against a dead port) with a readable HarnessError naming host/port and the exact disposable `docker run` command.
  - *Malformed URL config* → wrapped into HarnessError (both SQLAlchemy `ArgumentError` and plain `ValueError` from bad-port parsing are caught).
  - *Wrong-type/non-test target* → safety guard: scheme must be `postgresql+asyncpg` and database name must contain "test"; deliberate override via `WARDRESS_TEST_DB_UNSAFE_ALLOW=1`. This prevents the harness from ever truncating an operator's real database via a stray `DATABASE_URL`.
  - *Partial failure mid-suite / crash residue* → truncation runs BEFORE each test (setup, not teardown), so leftover rows from a killed run cannot contaminate the next session's first test.
  - *Retry/idempotency* → proven empirically: the full suite ran twice consecutively against the same database (first run 514+1fail pre-test-fix, second run fully green).
  - *Auth/RBAC interaction*: N/A — harness-level change only; fixtures and dependency overrides unchanged.
  - *Interaction with prior fixes*: none yet (Phase 0 made no code changes).
  - *Backward compatibility of test expectations vs Postgres semantics* → the full-suite run surfaced exactly one failure (`test_capture_site_deleted_before_start`), root-caused below and fixed. JSONB becomes active in tests (models' `JSON().with_variant(JSONB())`) — no failures; aware datetimes already normalized by models' `ensure_utc`; native PG enums exercised — no failures.
  - *Performance at scale* → per-test overhead is one TRUNCATE over ~20 tables plus pool setup; full suite wall time 262–257 s vs ~286 s SQLite baseline (not slower despite real network I/O).
  - *Fix-failure mode (lock contention)* → cleanup runs `SET LOCAL lock_timeout = '10s'`, converting a hypothetical leaked-transaction deadlock into a loud error naming the likely cause.
  - *Sequences/identity* → `TRUNCATE … RESTART IDENTITY CASCADE`; `alembic_version` excluded so migrations stay at head.
- **Fix design considered (Step 4)**: (A) One session-scoped migrated database + per-test `TRUNCATE … RESTART IDENTITY CASCADE`, function-scoped engine per test disposed before the next truncate — chosen: minimal fixture-shape change, ms-scale per-test cost, real migrations enforced once per session. (B) Fresh database + `alembic upgrade head` per test — airtight isolation but 500×~1 s+ migration runtime is prohibitive. (C) Transaction/savepoint rollback per test — incompatible with the app committing its own sessions across pooled connections (tests deliberately exercise commit semantics, e.g. conditional-UPDATE refresh rotation). Migration application runs as a subprocess (`sys.executable -m alembic upgrade head`) rather than in-process alembic API because `alembic/env.py` itself calls `asyncio.run`, which cannot nest inside pytest-asyncio's loop.
- **Fix applied (Step 5)**: New `tests/db_harness.py`: URL resolution with the safety guard described above (`WARDRESS_TEST_DATABASE_URL`, default `postgresql+asyncpg://wardress:wardress@127.0.0.1:5433/wardress_test`), database auto-creation via asyncpg against the maintenance db (tolerates a concurrent-create race), subprocess-based `alembic upgrade head` with captured output surfaced on failure, and `truncate_all_tables` (dynamic table list from `pg_tables`, quoted identifiers, `SET LOCAL lock_timeout`). `conftest.py`: session-scoped `_migrated_postgres` fixture (ensure-db + migrate once), `engine` fixture now creates/disposes a real asyncpg engine per test and truncates all tables before each test; all other fixtures unchanged. CI: backend job gained a `postgres:16-alpine` service on port 5433 and `WARDRESS_TEST_DATABASE_URL` env (CI exercises the create-if-missing path since the service only provides the maintenance db). README documents the operator contract including the guard and override. In passing, the rewritten conftest comment now cites the real file `test_phase5_ratelimit_ssrf.py` (the old comment referenced nonexistent `test_ratelimit.py` — rot noted by the audit's Phase 11).
- **Tests added/modified (Step 6)**: All in `tests/test_test_harness.py` (11 tests, all passing): schema-at-head (alembic_version == script head); migration-only partial index exists in `pg_indexes` with a WHERE predicate while absent from ORM metadata; second pending scan for one site rejected by IntegrityError (SAVEPOINT pattern) while a completed sibling is allowed (partial predicate, not blanket uniqueness); VARCHAR(256) width enforced on `target_label` (400 chars → DBAPIError "value too long"); two-step isolation pair proving inter-test wipe; five guard unit tests (non-test name refused, non-asyncpg scheme refused, malformed URL reported, escape hatch works, default satisfies guard). Pre-fix failure proof: the old harness could not represent these assertions at all — the Step-1 probe executed their equivalents against it and demonstrated the opposite outcomes (400-char value stored; two in-flight scans stored). Additionally `test_scan_tasks.py::test_capture_site_deleted_before_start` FAILED against the new harness as shipped (asserted `'baseline-row-missing' == 'site-missing'`) — direct evidence it had codified SQLite's unenforced-FK orphan state; updated to production semantics: after site deletion the baseline row is cascade-deleted, `_capture_baseline` returns `"baseline-row-missing"`, row gone, no fetch. The task's literal `"site-missing"` branch survives only inside an unobservable mid-race window (site+baseline deleted between the task's two SELECTs) and can no longer be reached from any persisted state under enforced FKs.
- **Full regression result (Step 7)**: Backend: `backend\.venv\Scripts\python.exe -m pytest -q --tb=line` → **515 passed, 0 failed, 1 warning** (~257 s; warning = pre-existing apprise/imghdr DeprecationWarning). Frontend: `pnpm test` → **7 files / 40 passed**; `pnpm type-check` (tsc -b --noEmit) → clean; `pnpm exec oxlint src` → 0 errors / 12 warnings (= Phase 0 baseline). Backend ruff: my four touched files pass `ruff check` + `ruff format --check`; repo-wide results identical to recorded baseline (`app/agent/tools.py:18 I001`, `app/routers/settings.py:869 S110`, 17-file format drift) — all Finding 10.1 scope, Phase 2's to fix. The previously environment-flaky DNS64-dependent test (`test_ai_migration.py::test_ollama_cloud_key_flows_into_deployment`) passed this run because the host resolver currently returns A-only records; it remains live-DNS dependent until its own phase.
- **Interactions with prior fixes**: Phase 0 was recon-only (no code changes) — nothing to interact with. Every concurrency/race phase after this one now has the DB-level backstop available in tests (this was the phase's stated leverage).
- **Residual risk / follow-ups**: (1) `aiosqlite` dev dependency is now unused by the suite and its pyproject comment is stale — left untouched this phase (outside the finding's declared file set; removal requires a uv.lock regen). (2) Concurrent pytest sessions/xdist need distinct databases (documented contract). (3) The disposable local container `wardress-test-pg` (port 5433) is intentionally left running on this machine as the documented dev database; CI provisions its own service. (4) Scratch probe script lived in %TEMP%\opencode and was deleted; repo tree contains only intended changes.
- **Commit**: fix(phase1) — postgres-backed test harness: alembic-migrated Postgres replaces in-memory SQLite

### [FIXED] CI is red on main at three independent gates — lint and both dependency audits fail on the committed tree

- **Original severity**: High
- **Phase**: 2 — CI Pipeline Stabilization
- **Files changed**: `backend/app/agent/tools.py:25` (import sort), `backend/app/routers/settings.py:10,75,870-875` (logger + observable except), `backend/pyproject.toml:54` (cryptography pin), `backend/uv.lock` (re-resolved), one formatter pass over 15 further drifted files (`alembic/versions/g1h2i3j4k5l6_correctness_indexes.py`, `alembic/versions/h2i3j4k5l6m7_unified_ai_layer.py`, `app/agent/engine.py`, `app/ai_config.py`, `app/llm.py`, `app/models.py`, `app/schemas.py`, `app/services.py`, `tests/test_ai_catalog.py`, `tests/test_correctness_batch.py`, `tests/test_llm_keypool.py`, `tests/test_services.py`, `worker/detection/dom.py`, `worker/fetcher.py`, `worker/telegram_bot.py`), `frontend/package.json:28` + `frontend/pnpm-lock.yaml` (in-range security refresh)
- **Re-verification (Step 1)**: all three gates re-executed against the current tree and all reproduced exactly as filed: (1) `uv run --frozen ruff check .` → exit 1 with `app\agent\tools.py:18 I001` + `app\routers\settings.py:869 S110`; `ruff format --check .` → "17 files would be reformatted" (full list captured; identical set to the audit's). (2) `uv run --frozen pip-audit --skip-editable` → exit 1: cryptography 49.0.0 PYSEC-2026-3552 + pip 26.1.2 PYSEC-2026-3721 (torch skip row unchanged). (3) `pnpm audit --audit-level high` → exit 1, "8 vulnerabilities found … 3 high" (react-router GHSA-qwww-vcr4-c8h2 via direct dep; nanoid GHSA-2v37-7h3g-55p8 via vite>postcss; undici GHSA-4cwx-7wf7-3272 et al. via jsdom — paths confirmed with `pnpm why`). Blocking-ness confirmed per protocol before closing: ci.yml contains zero `continue-on-error`/`|| true` (each gate a plain step that fails its job on nonzero exit; the file's own comment states this), gate steps precede Tests/Build in both jobs, and each command was demonstrated flipping exit 1 → 0 by the fixes below.
- **Root cause (Step 2)**: four independent roots feeding three gates. (a) I001/S110/format drift: formatting and import-ordering were never applied after edits landed (no local enforcement); S110 specifically = a deliberate-but-unobserved fallback in `pull_ollama_model` implemented as a blanket silent `except Exception: pass`. (b) cryptography: exact pin `==49.0.0` predates advisory PYSEC-2026-3552 (Bleichenbacher oracle in pkcs7 EnvelopedData APIs, fixed 50.0.0) — the vulnerable version is what the lockfile ships to every install. (c) pip: locked transitively via pip-audit itself (uv.lock declares it, so CI's synced venv has it too — not local-only as "(only present in dev venvs)" might suggest); its pin predated PYSEC-2026-3721 (fixed 26.2). (d) frontend: lockfile resolution dates predate three advisories; all fix versions sit inside the already-declared semver ranges.
- **Edge cases enumerated (Step 3)**:
  - *S110 exception surface* (what can that try block actually raise?): HTTPException(404) for malformed/dangling provider_id (`_require_provider` converts ValueError/AttributeError → 404 internally, so no raw ValueError escapes today); anything from `provider_api_keys()`/attribute access on a corrupt provider row (e.g. decryption failures); unexpected DB driver errors from the lookup query. Design must keep all of these non-fatal to the SSE endpoint while making them visible.
  - *Sensitive-data-in-logs*: the new log line carries only `body.provider_id` (admin-supplied opaque id) — never base_url/api_key material; exc_info traceback stays server-side. Admin-only endpoint (AdminUser guard unchanged).
  - *Behavior preservation*: log-and-continue keeps byte-identical control flow vs the old pass (fallback to body.base_url proceeds) — verified by full suite; no test asserted the old silence (endpoint had zero coverage, consistent with audit Phase 11).
  - *cryptography bump compatibility*: repo's entire usage surface is `Fernet`+`InvalidToken` (crypto.py read in full) — stable API across 49→50; the CVE'd pkcs7 APIs are imported nowhere (grep). Transitive dependents (python-telegram-bot, apprise, litellm, weasyprint) resolved unchanged except cryptography itself in the fresh lock. Fernet tokens produced under 49.0.0 decrypt identically under 50.0.0 (format unchanged) — existing encrypted-at-rest data compatible; suite's encryption round-trip tests exercise this.
  - *pip bump scope*: `--upgrade-package pip` moves only pip inside its resolver constraints; nothing else re-resolved (681 ms no-op otherwise).
  - *Frontend update blast radius*: react-router 8.2.0→8.3.0 is a minor within ^8.2.0 (SPA uses BrowserRouter; advisory affects RSC-mode only — not exploitable here, bumped anyway because the gate is version-based); undici/nanoid/postcss are dev/build-path transitives (jsdom/vite); all moved strictly within existing ranges — no package.json range loosened, no major jumps.
  - *Manifest/lockfile consistency*: pnpm 11 rewrote the direct dep floor to `^8.3.0` (its documented update behavior) — kept, since it documents the security floor and `pnpm install --frozen-lockfile` remains satisfied (lockfile ⊆ range).
  - *Formatter pass risk*: ruff format is AST-preserving; alembic migration files reformatted cannot change DDL metadata (string/whitespace-only deltas), so the migrations job's `alembic check` is unaffected — additionally proven by the schema-at-head + partial-index harness tests passing in the regression run.
  - *Interaction with prior fixes (Rule 11)*: Phase 1 touched conftest/db_harness/test files/ci.yml/README — none of this phase's files overlap its diffs except none; the harness self-tests re-ran green inside the 515.
  - *Concurrent access / unicode / boundary inputs*: N/A — no runtime behavior introduced beyond a log emission; dependency bumps carry no input-parsing surface change.
  - *Fix-failure mode*: if a future advisory lands again the gate goes red by design (that is the contract); triage flow now documented by this log's existence rather than a nonexistent "PROGRESS.md".
- **Fix design considered (Step 4)**:
  - *S110*: (A) narrow catch to HTTPException and continue — rejected: silently changing which exceptions propagate alters endpoint behavior beyond lint scope and belongs to the ollama-pull finding's own fix (Phase 16 decides fallback-vs-404 semantics with tests). (B) delete the fallback entirely / surface 404 — rejected: same reason, that IS Phase 16's declared behavioral change. (C) keep broad catch, add module logger + `logger.warning(..., exc_info=True)` — chosen: eliminates the *silent* aspect (the lint rule's root complaint and the audit's criticism "swallows everything") with zero semantic delta, matching sibling routers' logging idiom (auth/health/reports each carry a module logger).
  - *Format drift*: single `ruff format .` application (formatter-as-source-of-truth) vs hand-editing 17 files — chosen formatter; deterministic and exactly reproduces CI's checker.
  - *cryptography*: exact-pin bump to the audited fixed version (`==50.0.0`, matching the repo's exact-pin convention and uv's resolution of latest 50.x) vs range-relaxation — chosen exact pin for consistency with every other dependency line.
  - *pip*: targeted `uv lock --upgrade-package pip` vs global `uv lock --upgrade` — chosen targeted to keep the diff minimal and reviewable (global upgrade would churn ~169 resolutions).
  - *frontend*: named `pnpm update react-router undici nanoid postcss` (in-range re-resolution) vs pnpm overrides hardening pins — chosen update; overrides add permanent manifest machinery unnecessary once advisories are cleared, and ranges were already sound.
- **Fix applied (Step 5)**: (1) `tools.py`: sqlalchemy import members reordered to ruff-isort order (`String, cast, func, select`). (2) `settings.py`: added `import logging` (:10) and module `logger` (:75); replaced the bare `except Exception: pass` with an except block emitting `logger.warning("ollama pull: provider %s could not be resolved; falling back to raw base_url", body.provider_id, exc_info=True)` then continuing identically (:870-875). (3) `pyproject.toml`: `"cryptography==49.0.0"` → `"cryptography==50.0.0"`; `uv lock` (→ cryptography 50.0.0) then `uv lock --upgrade-package pip` (→ pip 26.2.1); `uv sync --frozen` picked both into the local venv automatically. (4) `ruff format .` → 17 files reformatted, 100 already clean. (5) `pnpm update react-router undici nanoid postcss` → react-router 8.3.0 (manifest floor `^8.3.0`), undici 7.29.0, nanoid 3.3.18, postcss 8.5.26 — all within prior ranges.
- **Tests added/modified (Step 6)**: none added, deliberately — recorded per Rule 6's explicit escape hatch. Every fixed property here is owned by an automated check outside pytest, and each was executed failing (Step 1) and passing (post-fix): `ruff check .` (exit 1→0), `ruff format --check .` (exit 1→0), `pip-audit --skip-editable` ("2 known vulnerabilities"→"No known vulnerabilities found", exit 1→0), `pnpm audit --audit-level high` (exit 1→0). Shelling these out of pytest would duplicate CI's own gates inside the unit suite (slower, dual maintenance, no repo precedent). Behavior preservation of the touched pull-endpoint path is covered by the full 515-test suite; a semantics-pinning test for its fallback was consciously NOT written because the endpoint currently has zero coverage and its fallback-on-bad-provider_id behavior is itself flagged defective (Finding: ollama-pull unvalidated base_url) — blessing it in a test would recreate the "tests codify defective behavior" class (audit Phase 11) and the test would be rewritten anyway when Phase 16 changes the semantics.
- **Full regression result (Step 7)**: Backend: `.venv\Scripts\python.exe -m pytest -q --tb=short` → **515 passed, 0 failed, 1 warning** (~308 s; the same warning as baseline — apprise/imghdr DeprecationWarning; count identical to Phase 1's post-fix total). Frontend: `pnpm test` → **7 files / 40 passed**; `pnpm type-check` (tsc -b --noEmit) → exit 0; `pnpm exec oxlint src` → 0 errors / 12 warnings (= baseline); `pnpm build` (tsc -b && vite build) → success (pre-existing chunk-size advisory only). Gates: `uv run --frozen ruff check .` → "All checks passed!"; `ruff format --check .` → "117 files already formatted"; `uv run --frozen pip-audit --skip-editable` → "No known vulnerabilities found"; `pnpm audit --audit-level high` → "No known vulnerabilities found". All four green simultaneously for the first time since the advisories landed.
- **Interactions with prior fixes**: Phase 1's harness/ci.yml/README work untouched and still green (its 11 harness self-tests ran inside the 515, including schema-at-head and the partial-index/VARCHAR assertions that depend on migrations-vs-models alignment — confirming the models.py reformat changed nothing structurally). No earlier phase touched tools.py/settings.py/pyproject/lockfiles.
- **Residual risk / follow-ups**: (1) torch (2.13.0+cpu) remains structurally invisible to pip-audit (CPU-index skip row) — that is the separate Low finding "The dependency-audit gate cannot see torch", Phase 40's to close. (2) The ollama-pull finding's substantive fixes (SSRF validation of body.base_url, rate limiting, surfacing 404 instead of silent fallback) remain untouched for Phase 16; this phase only made the existing fallback observable. The five moderate advisories cleared themselves alongside the highs (undici/postcss paths) — no separate action taken. (3) New lead logged below: ci.yml:62 comment references a nonexistent "PROGRESS.md". (4) Session hygiene note: two 0-byte scratch artifacts (`backend/50`, `backend/26.2`) were briefly created by a mangled shell probe during root-causing; inspected (empty), deleted, and never staged — final tree contains only intended changes plus the pre-existing dispositioned items (`scripts/lib.ps1` user-intentional edit, untracked audit files).
- **Commit**: fix(phase2) — green all three red CI gates at root cause

### [FIXED] Redis outage breaks the designed enqueue-degradation contract: first enqueue per outage hangs ~64 s then returns 500 *after* committing rows, leaving baselines stuck pending

- **Original severity**: High
- **Phase**: 3 — Redis Outage Enqueue-Degradation Fix
- **Files changed**: `backend/app/tasks.py` (imports/logger, `_celery_client` backend removal, `_send` containment), `backend/tests/test_tasks_enqueue.py` (new — 5 tests)
- **Re-verification (Step 1)**: reproduced live this session against current code with a disposable Redis container on 127.0.0.1:6399 and the project venv (scratch probe outside the repo, deleted afterwards). Sequence: one successful `send_task` (starts the result consumer) → `docker stop redis` → measured subsequent calls through the real `tasks._send`. Outage-onset call raised `kombu.exceptions.OperationalError` after 10.7 s (caught, would map to 503); every following call in the episode raised `RuntimeError: Retry limit exceeded while trying to reconnect to the Celery result store backend. The Celery application must be restarted.` after ~63.7 s/63.8 s, from `celery/backends/redis.py:402 on_task_call → result_consumer.consume_from → _consume_from → asynchronous.py:355 reconnect_on_error`. Static read confirmed the escape path end to end: `_send` catches only `OperationalError`; `_enqueue_or_fail` catches only `HTTPException` (its docstring even says "Any non-503 enqueue error propagates unchanged"), so its `_fail()` recovery is unreachable for RuntimeError; imports.py's bulk-import loop likewise catches only `HTTPException`. Finding fully reproduces; no staleness.
- **Root cause (Step 2)**: two layers. (1) The API-side producer configured a result backend it never consumes (`tasks.py:24` `backend=settings.redis_url`; repo-wide grep shows zero AsyncResult/result consumers anywhere in the API). Celery's `send_task` invokes `backend.on_task_call()` *before every publish* (celery/app/base.py:968), and the Redis backend's implementation drives its ResultConsumer pubsub machinery — during an outage that machinery runs its own internal retry loop (~60 s of redis-py reconnect attempts inside `reconnect_on_error`) and terminates by raising `RuntimeError(E_RETRY_LIMIT_EXCEEDED)`, a class outside both the tasks-layer translation (`except OperationalError`) and the service-layer recovery (`except HTTPException`). The poisoned state persists per process until restart (Celery's own message says so). (2) Secondary root: the degradation contract was keyed to specific exception types instead of "the publish did not succeed", so any unexpected escapee class bypasses row-failure recovery entirely and surfaces as a post-commit unhandled 500.
- **Edge cases enumerated (Step 3)**:
  - *Concurrent access*: each API process owns its client; during an outage every in-flight create-site/scan-now/rebaseline/bulk-import now independently fails fast to 503 + row-marked-failed. Previously each process could additionally be left permanently broken mid-episode (the RuntimeError state survives until restart).
  - *Cold-start first call with broker already down*: no consumer state exists → straight publish failure → OperationalError → designed 503 (verified live post-fix, attempt [2]).
  - *Missing/malformed REDIS_URL*: transport failures wrap into kombu `OperationalError` on the publish path (verified in captured traceback via kombu's `_reraise_as_library_errors`) → same 503 path.
  - *Malformed args / EncodeError-class failures*: deliberately NOT translated to 503 — those are programming errors that must stay loud 500s; disguising them as queue-unavailable would spuriously mark rows failed and misdirect operators.
  - *Partial failure mid-operation*: row commits before publish (by design); on enqueue failure `on_fail()` marks it failed and re-commits — unchanged contract. If that recovery commit itself fails (DB outage), SQLAlchemy error surfaces as 500: pre-existing shape, different outage class, out of scope.
  - *Retry/idempotency*: post-503 the failed row no longer blocks (status=failed), so operator retry proceeds cleanly. Duplicate-site-on-retry remains possible — pre-existing gap owned by the sites.url-uniqueness finding (Phase 15), untouched here.
  - *Unicode/malformed input, boundary numerics*: N/A — no parsing surface changed; task args remain UUID strings over JSON.
  - *Auth/RBAC interaction*: N/A — no dependency or guard changes on any touched path.
  - *Interaction with prior fixes*: Phase 1 harness — new tests run against real Postgres via `db_factory` under alembic schema (and pass in CI without any Redis service: the dead-broker client targets 127.0.0.1:1, refusal is instant). Phase 2 conventions followed (module-level logger idiom as in settings.py; ruff format clean). `health.py:_worker_component` shares `_celery_client` but only uses `control.ping(timeout=2.0)` (broker transport; no backend involvement) inside `except Exception` — unaffected.
  - *Backward compatibility*: worker untouched (separate app/config in worker/celery_app.py); rows stranded pending by past episodes still recover via the existing 10-minute stale-supersede paths; no schema/data migration.
  - *Performance at scale*: steady-state slightly improves (no per-send_task pubsub channel subscription churn); dead-broker latency bounded ~4 s steady-state / ~11 s episode-onset first call (existing deliberate `max_retries=2` budget kept — one cheap retry still rescues brief blips).
  - *Fix-failure mode*: if Redis returns mid-retry the publish succeeds normally (verified live: recovery attempt OK 0.0 s); the defensive branch logs at warning with exc_info before translating, keeping any future trigger diagnosable.
- **Fix design considered (Step 4)**: (A) remove the result backend only — treats the root but leaves the contract keyed to exception classes (a future escapee reintroduces the 500); (B) broaden catches only — keeps the ~60 s hang, violating "fails fast"; rejected; (C) both: make the producer broker-only (`backend=None` → DisabledBackend, whose `on_task_call` is a no-op, so the reconnect machinery never runs) AND add a defensive `except RuntimeError` translation in `_send` to the identical HTTPException 503 — chosen. A broad `except Exception` was rejected on purpose: EncodeError-class bugs must stay loud rather than be laundered into "queue unavailable".
- **Fix applied (Step 5)**: `tasks.py`: `_celery_client` constructs `Celery("wardress-api", broker=..., backend=None)` with a comment recording why; `_send` gains `except RuntimeError` emitting `logger.warning("enqueue %s failed: ...", exc_info=True)` then raising the identical 503 HTTPException ("Task queue is unavailable — try again shortly"). services.py `_enqueue_or_fail`, routers, and imports.py intentionally unchanged — their HTTPException-based contracts are correct once the single chokepoint translates every outage-class failure.
- **Tests added/modified (Step 6)**: new `tests/test_tasks_enqueue.py` (5 tests): (1) `test_api_producer_client_has_no_result_backend` pins `conf.result_backend is None` + `DisabledBackend` — **FAILED pre-fix** (`'redis://redis:6379/0' is None` assertion failure), passes post-fix; (2) `test_send_translates_unexpected_enqueue_failure_to_503` feeds the verbatim historical RuntimeError through a stubbed client — **FAILED pre-fix** (bare RuntimeError propagated), passes post-fix; (3) `test_send_dead_broker_maps_to_503_fast` proves a real dead-broker publish maps to 503 in <20 s (observed ~4 s) with the exact detail string; (4) `test_rebaseline_with_dead_broker_marks_row_failed_not_pending` proves the end-to-end recovery against real Postgres: QueueUnavailableError raised, new baseline row status=failed with the queue-unavailable error, nothing stranded pending, ready trust anchor untouched; (5) `test_bulk_import_dead_broker_reports_enqueue_failure_per_row` proves the router yields the designed 200-with-per-row-details instead of a post-commit 500. Tests 3–5 also pass pre-fix by design — they exercise the designed path which was correct but unreachable once the result-store machinery poisoned the episode; tests 1–2 are the failing-before proofs. Manual verification (not automatable hermetically — requires Docker container lifecycle; documented per Rule 6): full outage episode re-run post-fix through `tasks._send` = OK 0.3 s / HTTP 503 10.8 s / 503 4.1 s / 503 4.1 s / recovery-after-restart OK 0.0 s — zero RuntimeErrors, zero >20 s latencies (same episode pre-fix: escaped RuntimeErrors at 63.7 s and 63.8 s).
- **Full regression result (Step 7)**: Backend `.venv\Scripts\python.exe -m pytest -q --tb=short` → **520 passed, 0 failed, 1 warning** (~381 s; warning = pre-existing apprise/imghdr DeprecationWarning; 515 prior + 5 new). Frontend `pnpm test` → **7 files / 40 passed**; `pnpm type-check` (tsc -b --noEmit) → clean; `pnpm exec oxlint src` → 0 errors / 12 warnings (= baseline). Backend `uv run --frozen ruff check .` → All checks passed; `ruff format --check .` → 118 files formatted.
- **Interactions with prior fixes**: Phase 1's harness self-tests re-ran green inside the 520 (schema-at-head, partial-index, VARCHAR-width assertions unaffected — no models/migrations touched). conftest's `stub_all_enqueues` patches service symbols above the fixed chokepoint — semantics unchanged. Phase 2's logging/format conventions matched. No earlier phase modified `app/tasks.py`.
- **Residual risk / follow-ups**: (1) New lead logged above: imports.py enqueues inline on the event loop (no `asyncio.to_thread`), inconsistent with services.py:132 — latency-bounded today, no defect at realistic scale. (2) Duplicate-site-on-retry-after-503 remains possible (sites.url uniqueness — Phase 15 scope). (3) The defensive RuntimeError branch has no natural live trigger anymore; unit test (2) stands guard. (4) Worker-side enqueue paths (beat dispatcher, scan_tasks inter-task sends) keep their own resilience semantics — separate subsystem, outside this finding's API-side contract.
- **Commit**: fix(phase3) — broker-only producer: Redis outage fails fast through the designed 503 path
