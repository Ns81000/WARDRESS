# Wardress Fix Log — Implementation Progress

Source of truth for *what's wrong*: WARDRESS_AUDIT_FINDINGS.md (read-only, never edited here).
Source of truth for *how it's being fixed*: this file.

## Progress Tracker

| Phase | Name | Status | Session Date | Commit |
|---|---|---|---|---|
| 0 | Fix-Effort Ground Truth Recon | Complete | 2026-08-22 | fix(phase0) |
| 1 | Postgres Test-Harness Migration | Complete | 2026-08-22 | fix(phase1) |
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
