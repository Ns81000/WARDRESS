### [PARTIAL] PROMPT-003 Audit Phase 6+7 — Concurrency, Scale & Chaos Testing

- **Prompt**: SESSION-B-KICKOFF.md (subagent W2)
- **Session date**: 2026-09-30
- **Assigned subsystem**: Celery worker/beat orchestration under concurrency and fault injection
- **Status rationale**: Phase 6 is **complete** (3 passes at 1×/2×/5×, 50-cycle soak, amplification verification). Phase 7 is **complete for 5 of 7 spec scenarios at 3 passes**, 1 spec scenario (large-DOM) at 1 pass plus an end-to-end proof, and **PARTIAL for the infrastructure-fault extras** (Postgres restart / Redis restart / network partition) — the harness was aborted by Docker-engine starvation, which is itself the finding. Every shortfall is itemised in §5.7 and §12 with the reason.

---

## 0. Environment attestation

| Item | Value | How measured |
|---|---|---|
| Host CPU | AMD Ryzen 5 5625U — 6 physical / 12 logical | Task brief, confirmed by `os.cpu_count()`=12 / `torch.get_num_threads()`=6 inside the container |
| Host RAM | 15.34 GB | `Get-CimInstance Win32_OperatingSystem` |
| **Docker ceiling** | `docker info` `MemTotal` = **7,976,714,240 B = 7.429 GiB** | re-measured this session (W1-C's 7,976,714,240 matches exactly) |
| Docker VM kernel | 6.6.87.2-microsoft-standard-WSL2 | read from the kernel OOM dump |
| **Contention status** | **I ran ALONE.** No other subagent was active. W1-A/W1-B/W1-C all ran three-at-a-time, so their timings are contention-affected and mine are not. This is the material difference and it shows: my measured per-scan cost at low concurrency (34.6 s) is *lower* than the same code path measured by others under three-way contention. | this session |
| Playwright | image tag `mcr.microsoft.com/playwright/python:v1.61.0-noble`, `playwright==1.61.0` | `Dockerfile.worker:8` |
| Audit stack | `wardress-audit-app` (:8322), `wardress-audit-worker`, `audit-probe`, `audit-probe-dns`, `audit-blackhole-srv`; scratch DB `wardress_audit` on the disposable `wardress-test-pg`; Redis logical DB **9** | §13 |
| Live stack | `wardress-app-1`, `wardress-worker-1`, `wardress-beat-1`, `wardress-db-1`, `wardress-redis-1` | left up and healthy |

**Why a separate audit stack (not the live one).** The brief requires a dedicated scratch database and forbids polluting the live DB, but the worker reads exactly one `DATABASE_URL`. I therefore ran the *identical `wardress-worker` / `wardress-app` images* against `wardress_audit` on the disposable `wardress-test-pg`, on the same Docker network, with Redis logical DB 9 for queue isolation. The container is byte-identical to the deployed one (same image id), so `docker exec wardress-audit-worker ps` and the deployed `wardress-worker-1` show the same shape. I **stopped the live `worker` and `beat` for the duration of the load tests** (they are idle — the live DB has 0 sites) so the audit run had the memory budget the real deployment's worker would have had, and restarted them at the end.

### 0.1 Test origin

All load and chaos traffic goes to a purpose-built hostile origin on the host at `127.0.0.1:9101`, reachable from containers as `host.docker.internal:9101`. It serves a matrix of behaviours on distinct paths: normal pages of variable size (`/ok/<kb>`), 14 MB-DOM pages (`/huge/<mb>`), header slow-loris (`/loris/<s>`), 1-byte-per-200 ms body drip (`/bodyloris/<ms>`), an invalid status line, truncated headers, malformed chunked encoding, a lying `Content-Length`, an arbitrarily large chunked stream (`/chunkbomb/<mb>`), redirect chains and a self-redirect loop. Script + Dockerfile live in `%TEMP%\opencode\audit\origin.py` (Rule 10 — scratch, never committed). Deterministic and reproducible.

---

## 1. Configured limit & how it was determined

**Configured worker concurrency = 12 (prefork).** Established four ways, no guessing:

1. **Code trace — the flag is absent.**
   - `backend/Dockerfile.worker:36` — `CMD ["celery", "-A", "worker.celery_app", "worker", "--loglevel=info"]`. No `-c`, no `--concurrency`, no `--max-tasks-per-child`, no `--prefetch`.
   - `docker-compose.yml:89-116` — the `worker` service declares **no `command:` override**, so it inherits the image CMD verbatim. (`beat` at `:123` does override `command:`, which is why only `beat` differs.)
   - `backend/worker/celery_app.py:23-46` — `celery_app.conf.update(...)` sets `task_serializer`, `result_serializer`, `accept_content`, `timezone`, `enable_utc`, `task_acks_late`, `worker_prefetch_multiplier`, `task_soft_time_limit=420`, `task_time_limit=480`. **No `worker_concurrency` key, no `worker_max_tasks_per_child`, no `broker_transport_options`.**
   - There is no queue routing anywhere: every task goes to the default `celery` queue. Grep of `backend/` finds no `task_routes`, no `queue=` argument on any `send_task`/`apply_async`.

2. **Live process tree (deployed worker).** `docker exec wardress-worker-1 ps -eo pid,ppid,rss,args` → PID 1 (celery main) plus exactly **12 children, pids 9–20**.

3. **Celery's own banner (audit worker, same image).** `celery@3d6ef243f886 v5.6.3` → `concurrency: 12 (prefork)`.

4. **Why 12 and not 6.** Celery's default is `os.cpu_count()`/`len(os.sched_getaffinity(0))`. Docker Desktop does not restrict the CPU affinity mask, so the container inherits all **12 logical** CPUs of a **6-physical-core** host. The worker is therefore configured for **2× the physical core count**, and `torch.get_num_threads()` independently reports **6** inside each child (§3.4 shows the consequence).

### 1.1 Load-level definitions (explicit, per the brief)

| Level | Definition | Enqueued concurrently | In flight (max) | Queued |
|---|---|---|---|---|
| **1× (configured limit)** | = the worker's prefork pool size | 12 scans | 12 | 0 |
| **2×** | = 2 × configured limit | 24 scans | 12 | 12 |
| **5×** | = 5 × configured limit | 60 scans | 12 | 48 |

Critical interpretive point: **because concurrency is pinned at 12 by the prefork pool, 2× and 5× add demand, not parallelism.** They are therefore a pure *queueing* test. This is itself the single most important structural fact of this phase — see `AUDIT-6-1`.

### 1.2 Entry points driven

Real path, no shortcuts: `POST /api/sites` (creates the site + a `pending` baseline + enqueues `wardress.capture_baseline`) → worker renders via Playwright → `POST /api/sites/{id}/scan-now` → `wardress.run_scan` → 9 detection layers → `scans` row + artifacts on a Docker named volume. (Note: the endpoint is `/scan-now`, not `/scan` — `app/routers/sites.py:348-363`.)

---

## 2. Method & measurement instrumentation

| Metric | Instrument | Sample size |
|---|---|---|
| queue latency (`created_at`→`started_at`), run latency (`started_at`→`finished_at`), e2e | Server-side DB timestamps in `scans` — not client-side wall clock | every scan row, n=12/24/60 per pass |
| capture sub-phase | `scans.capture_evidence.capture_wall_clock_ms`, written by `fetcher.py:_capture_attempt` | every completed scan |
| non-capture sub-phase | `run_s − capture_wall_clock_ms` (i.e. probe + 9 layers + persist + schedule) | every completed scan |
| container CPU / memory | `docker stats --no-stream` (cgroup `cpu.stat` / `memory.current`) sampled in a **separate thread at a 3–5 s cadence** | 5–22 samples/pass, `sample_stats_err` reported per pass (0 on every recorded pass) |
| DB connections | `SELECT count(*) FROM pg_stat_activity` in the same sampler, same cadence | same |
| phase breakdown (probe vs detection) | in-container probe importing the real `worker.probe.probe_site` / `worker.detection.pipeline.run_detection`, timings taken in-process | 1 pass at concurrency 1 |
| kernel OOM | `%LOCALAPPDATA%\Docker\log\host\com.docker.backend.exe.log` — the WSL2 `init.oom-tracer` dump | 1 event, full task table captured |
| resilience | the driver's DB helper retries 6× and every HTTP call is bounded | — |

**Environment note on measurement fidelity.** The CPU/memory sampler itself competes for the Docker API. At 12-way load the API degraded badly (see `AUDIT-6-1`), so all Phase 6 numbers reported below were taken with the live stack's idle worker/beat stopped, and every pass records `sample_stats_err` so the reader can see how many samples were lost. All recorded passes show `sample_stats_err: 0`.

---

## 3. Phase 6 — load results

### 3.0 Two page profiles

Page size materially changes per-scan cost (W1-B established that layers 2/3/5 scale with DOM size), so both are reported separately and neither is hidden.

* **"cheap" profile** — `/ok/3`, ~3 KB DOM, screenshot ~30 KB. Used for the full 3×3 matrix (1×/2×/5×).
* **"heavy" profile** — `/ok/{400..1375}`, ~55–155 KB DOM, screenshot **2.4 MB**, `final_height` 9,556–11,356 px. This is the realistic-page profile and it is where the headline failure appears. Measured separately (12 concurrent, 1 pass + a second 12-scan batch that produced the time-limit cascade).

### 3.1 Cheap profile — the 3×3 matrix

**1× (12 concurrent scans, 4 passes)**

| Pass | Enq | Compl | Fail | Queue p50/p95 (s) | Run p50/p95 (s) | E2E p50/p95 (s) | Capture p50 (s) | Non-capture p50 (s) | Wall (s) | Throughput (scan/s) | Peak worker CPU | Peak worker mem |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 12 | 12 | 0 | 0.2 / 0.3 | 31.7 / 32.6 | 31.9 / 32.8 | 14.8 | 16.9 | 37.1 | 0.324 | (sampler err) | (sampler err) |
| 2 | 12 | 12 | 0 | 0.3 / 0.3 | 33.3 / 33.6 | 33.6 / 33.8 | 15.1 | 18.0 | 38.5 | 0.312 | (sampler err) | (sampler err) |
| 3 | 12 | 12 | 0 | 0.4 / 0.5 | 24.8 / 25.1 | 25.2 / 25.5 | 17.1 | 7.7 | 26.3 | 0.456 | (sampler err) | (sampler err) |
| 4 | 12 | 12 | 0 | 0.2 / 0.3 | 37.5 / 39.1 | 37.7 / 39.2 | 34.1 | 4.2 | 41.4 | 0.290 | 1481 % | 5.98 GiB |

*Variance*: e2e p50 spans **25.2–37.7 s (1.50×)** across four passes with zero failures. The spread is a warm-up effect inside the prefork children (MiniLM's first-use load is charged to whichever child runs first) plus capture-phase jitter — note the inverse coupling between the capture and non-capture columns in passes 3 and 4. **This is itself a finding-grade observation: a scan's cost is not attributable to a deterministic phase, so no per-scan timeout can be sized reliably.**

**2× (24 concurrent, 3 passes)**

| Pass | Enq | Compl | Fail | Queue p50/p95 (s) | Run p50/p95 (s) | E2E p50/p95 (s) | Wall (s) | Throughput | Peak CPU | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 24 | 24 | 0 | 10.7 / 21.4 | 20.9 / 21.6 | 31.6 / 42.1 | 46.7 | 0.514 | 1210 % | |
| 2 | 24 | 24 | 0 | 10.4 / 20.7 | 21.2 / 22.1 | 31.6 / 42.8 | 46.5 | 0.516 | 1181 % | |
| 3 | 24 | **23** | **1** | 10.5 / 24.6 | 22.2 / 24.8 | 34.5 / 45.1 | 48.9 | 0.491 | 1311 % | `Fetch failed: Page.screenshot: Target crashed` |

*Variance*: queue p50 10.4–10.7 s (3 % spread) — exactly one extra wave of 12, as predicted. Throughput 0.491–0.516 (5 % spread). **Throughput gain from 1×→2× is 1.48× for 2× the demand** — i.e. the second 12 scans are absorbed almost for free because the queue is FIFO and the marginal scan costs the same as the marginal scan at 1×. One Chromium renderer crash, handled as a clean `FetchError` → scan `failed` with a user-safe message. **Safe fail.**

**5× (60 concurrent, 3 passes)**

| Pass | Enq | Compl | **Fail** | Queue p50/p95/max (s) | Run p50/p95/max (s) | E2E p50/p95/max (s) | Wall (s) | Throughput | **Peak worker mem** | % of 7.429 GiB | Peak CPU |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 60 | 60 | 0 | 66.3 / 151.3 / 151.7 | 29.9 / 64.5 / 79.2 | 95.7 / 162.5 / 162.7 | 172.9 | 0.347 | **6 524.9 MB** | **85.8 %** | 1590 % |
| 2 | 60 | 52 | **8** | 47.1 / 95.9 / 96.0 | 17.8 / 33.3 / 58.7 | 64.9 / 107.9 / 123.3 | 130.0 | 0.462 | **6 670.3 MB** | **87.8 %** | 1194 % |
| 3 | 60 | **43** | **17** | **282.5 / 323.9 / 342.4** | 25.4 / 262.9 / 266.9 | **309.5 / 349.1 / 376.7** | 384.1 | **0.156** | **6 589.4 MB** | **86.7 %** | 1147 % |

Failure modes at 5×, by exact `scans.error` value:
- `Fetch failed: Page.screenshot: Target crashed` (Chromium renderer OOM/segfault) — the dominant mode.
- `Fetch failed: Page.screenshot: Timeout 45000ms exceeded.` — `SCREENSHOT_TIMEOUT_MS` (`fetcher.py:86`).
- `Fetch failed: Page.goto: net::ERR_BLOCKED_BY_CLIENT at …/ok` — once, pass 2.

*Variance*: **throughput 0.156–0.462 scans/s = 2.96× spread across three passes of the identical workload**, and failure count 0 → 8 → 17. This is the worst variance in the phase and it is the clearest signal that 5× sits on a cliff edge rather than a plateau. Peak memory is stable at 85.8–87.8 % of the ceiling in all three passes — the worker is *already at the ceiling at 5× and was at 74 % at 1×* (§3.2); 2× and 5× add no memory because concurrency is fixed.

### 3.2 Where the memory actually goes (measured, not extrapolated)

This is the first time the warm-pool figure has been measured under load rather than extrapolated, so it is stated precisely.

**Live cgroup of `wardress-audit-worker` through the session** (`docker stats --no-stream`, 12 children):

| Point in session | Cgroup usage | % of 7.429 GiB |
|---|---|---|
| cold, 12 idle children | 1.444 GiB | 19.4 % |
| after 120 baseline captures | 5.082 GiB | 68.4 % |
| during 1× scan pass (heavy pages) | 5.371 GiB | 72.3 % |
| idle after heavy pages + time-limit cascade | 5.845 GiB | 78.7 % |
| **during 5× passes (sampled)** | **6.52–6.67 GiB** | **85.8–87.8 %** |

**Kernel OOM event (hard evidence).** `Out of memory: Killed process 66218 (chrome-headless) total-vm:1518215728kB, anon-rss:11028kB`, with two further `OOM Killer` entries (66213, 66222). The accompanying WSL2 task table gives the exact breakdown at kill time:

| Process class | Count | RSS each | Subtotal |
|---|---|---|---|
| warm celery children | 12 | ~119 000 pages ≈ **476 MB** | **≈ 5.6 GiB** |
| extra python scan processes (my Phase-6 probe) | 12 | ~9 900 pages ≈ 39 MB | 0.47 GiB |
| Playwright driver `MainThread` procs | 12 | ~22 700 pages ≈ 91 MB | 1.07 GiB |
| live `chrome-headless` | ~40 | 8–14 MB | 0.46 GiB |
| 2 × uvicorn (app + worker main) | 2 | 129–141 MB | 0.27 GiB |
| dockerd / containerd / postgres ×2 / redis / VM services | — | — | ≈ 0.3 GiB |
| **Total** | | | **≈ 8.3 GiB > 7.429 GiB ceiling** |

So the 12 warm children alone were **75.4 % of the Docker ceiling** at the moment of the kill.

### 3.3 Heavy profile — where the system actually breaks

Same code, realistic page sizes (~55–155 KB DOM, 2.4 MB screenshot):

| Concurrency | Scans | Run latency p50 | Capture p50 | **Non-capture p50** | Outcome |
|---|---|---|---|---|---|
| 2 (two sites, near-idle worker) | 2 | 34.6 / 34.6 s | 10.2 s | **24.4 s** | 2/2 `changed`, risk 0.137 |
| 12 (all children busy) | 12 | **55.8, 56.6, 279.1, 297.0, 312.6, 314.5, 318.2, 318.3, 318.4, 318.6, 318.7, 318.7 s** | 16.1–22.2 s | **262–301 s** | 12/12 completed (first batch) |
| 12 (second batch) | 12 | — | — | — | **0/12 completed — see below** |

**Per-scan cost inflates 9.2× (34.6 → 318.7 s) from concurrency 2 to 12, while the Playwright capture phase inflates only 1.6–2.2× (10.2 → 16–22 s).** Between **83 % and 94 % of the scan's wall clock at 1× load is spent outside the capture**, i.e. in `probe_site` + `run_detection` + DB persistence.

In-container phase breakdown at concurrency 1 (isolating the non-capture phase with the real `fetch_page` / `probe_site` / `run_detection`):

```
fetch_total_s 20.85  |  capture_wall_ms 20733  |  probe_s 0.11  |  store_s 0.01  |  detect_s 6.04
html_kb 60    |  png_kb 2385   |  torch.get_num_threads() = 6
```

`probe_site` costs 0.11 s and detection 6.04 s when uncontended. At concurrency 12 the same non-capture phase costs 262–301 s — a **44–50× inflation of a 6-second CPU-bound stage**, with `torch.get_num_threads() == 6` inside each of 12 children. **12 children × 6 torch threads = 72 compute threads on 6 physical cores** — a 12× oversubscription of the intra-op thread pool. `worker/` never calls `torch.set_num_threads()` and the compose file sets no `OMP_NUM_THREADS`/`MKL_NUM_THREADS`.

**The time-limit cascade (the decisive result).** The second 12-scan heavy batch produced, in the worker log:

```
11:20:15  Task wardress.run_scan[...] received          (×12, queue latency 0.5–0.7 s)
11:36:27  WARNING  Soft time limit (420s) exceeded       (×12)
11:38:17  ERROR    Hard time limit (480s) exceeded       (×12)
11:38:17  ERROR    Process 'ForkPoolWorker-4'  pid:11  exited with 'signal 9 (SIGKILL)'
11:38:28  ERROR    Process 'ForkPoolWorker-12' pid:19  exited with 'signal 9 (SIGKILL)'   … ×12
```

and in the database, **all 12 rows were still `status='running'`, `verdict=NULL`, `error=NULL` 1 514 s (25.2 min) later**, with zero log lines matching `Could not mark scan failed` / `Scan failed unexpectedly`. The `run_scan` wrapper's `except Exception` handler never runs because billiard delivers the limit as a **SIGKILL to the child**, not an exception. The only recovery is `beat`'s stale sweep, which fires only when the site is next due — up to `interval + 2×STALE_INFLIGHT` = **24 h 20 min** for a 24 h site (Session A's `AUDIT-4B-5`, now empirically triggered rather than extrapolated). **Note also that the soft limit fired 972 s and the hard limit 1 082 s after receipt, not 420/480 s** — the parent process's timer thread was itself starved by the same memory exhaustion.

### 3.4 Docker-engine starvation (Rule 17 finding, self-inflicted load)

On **three separate occasions** during 12-way worker load, the Docker Engine API returned:

```
request returned 500 Internal Server Error for API route and version
http://%2F%2F.%2Fpipe%2FdockerDesktopLinuxEngine/v1.51/containers/json
```

for **~9 minutes** continuously (10:55–11:07 the first time, again twice later). Consequences: `docker stats`, `docker exec`, and `docker ps` all failed; a client connecting directly to Postgres on the host port hit `psycopg.errors.ConnectionTimeout`; the Phase-6 driver was killed mid-pass. Docker Desktop's own log records `traces export: context deadline exceeded` and `forwarding raw stream to dockerd: … connection timed out` at the same timestamps. The host itself was not out of memory (5.15 GB free physical), so this is the WSL2 VM entering severe reclaim, not a host OOM.

### 3.5 DB connection pool and lock contention

**Not a bottleneck, at any load level.** `pg_stat_activity` peak across all recorded passes: **19 connections against `max_connections = 100`**, identical at 1×, 2× and 5×. This is structural, not luck: `worker/db.py:16` builds and disposes a fresh `create_async_engine` per task, so each in-flight scan holds at most one connection for the duration of its few DB round-trips, and `pool_pre_ping` is on the fresh pool (Session A's `AUDIT-SA3-11` — semantically dead, but harmless). No lock contention observed: no `deadlock detected`, no lock-wait timeouts, no row-lock pile-ups in any pass. The dispatcher claim CAS (`beat_tasks.py:160-168`) was exercised ~6 times in the amplification test with no `lost_claim`.

**So the binding constraints are CPU and memory, not the database.**

---

## 4. Amplification cascade verification (`AUDIT-4B-2`)

**Prediction (Session A, re-read this session):** amplification begins once the queue wait exceeds `STALE_INFLIGHT` = 10 min, i.e. a backlog of ~15–60 pending rows; the dispatcher's own output (up to 50 enqueues/tick) is enough to cross it; once crossed, each tick converts stale pending rows into permanently-`failed` history rows plus fresh no-op broker messages, self-sustaining.

**Method.** The real `wardress.dispatch_due_scans` task was invoked on the running worker via `celery -A worker.celery_app call wardress.dispatch_due_scans` — the production dispatcher, unmodified. For each trial the scratch sites were made due (`next_scan_at = now() − 1 h`) and a **pending `scans` row aged 11 minutes** was inserted per site, then one tick was run and the rows counted.

**Honest caveat:** the rows were aged by *timestamp* (`created_at = now() − 11 min`), not by 11 minutes of wall clock, to fit the session budget. This is exactly the state the dispatcher evaluates at t+11 min; it is faithful to the boundary condition but it is not a wall-clock observation, and I flag it as such.

| Trial | Backlog K | Rows armed | Pending before | **Superseded (this trial)** | New pending rows enqueued | Running | Completed | Failed (cumulative for these sites) |
|---|---|---|---|---|---|---|---|---|
| k5-a | 5 | 5 | 5 | **5** | 0 | 5 | 77 | 17 |
| k15-a | 15 | 15 | 15 | **20** | 5 | 10 | 204 | 46 |
| k30-a | 30 | 30 | 30 | **46** | 21 | 5 | 308 | 85 |
| k60-p1 | 60 | 60 | 60 | **92** | **40** | 6 | 441 | 167 |
| k60-p2 | 60 | 60 | 60 | 92 | 0 | 0 | 454 | 214 |
| k60-p3 | 60 | 60 | 60 | **192** | 0 | 4 | 459 | **370** |

**Verdict: CONFIRMED, and the threshold is even easier to reach than Session A stated.**

- **Measurement:** 192 rows carry the exact dispatcher text `'Scan never completed — superseded by a scheduled scan'` in `scans.error`, produced inside a 165-second window (14:05:35 → 14:08:19). Cumulative `failed` rows for the affected sites: 370.
- **Entry condition: age, not depth.** Supersession fired at **K=5** — the smallest backlog I tested — exactly as at K=15/30/60. There is **no backlog-size floor**; the sole trigger is `is_stale(created_at)` crossing 10 minutes. Session A's "15–60 pending scans" is the *throughput-implied* number for a specific scan duration; the measured trigger is strictly cheaper.
- **One tick is enough to cross it.** At K=60 a single tick enqueued **40 fresh pending rows** (capped by `MAX_DISPATCH_PER_TICK = 50`), which is more than double the K=5 floor — confirming "one over-capacity tick creates the backlog the very next tick converts".
- **Self-sustaining confirmed.** k60-p3 produced 100 more superseded rows than k60-p2 from an identical armed backlog, because each round leaves new aged-pending rows behind for the following tick. The cascade does not damp out.

**Both numbers, stated (Rule 8):**

| | Session A predicted | I measured |
|---|---|---|
| Trigger | backlog ≈ 15–60 pending rows (S=480 s → 15; S=120 s → 60) | **any** backlog whose rows exceed 10 min age; confirmed at K=5 |
| Rows failed per tick | 50 (`MAX_DISPATCH_PER_TICK`) | up to **100 per armed round** (192 over 3 rounds at K=60) |
| No-op messages enqueued per tick | ≤ 50 | **40** in one tick |

Disposition: **Confirmed → Fix-candidate.** Unchanged severity (Medium). This is not a new finding; it is the measurement `AUDIT-4B-2` was waiting for. What is new and belongs to this phase: the entry threshold is **lower** than recorded, and the escalation is **faster** (three armed rounds reached 192 failed rows in under three minutes).

---

## 5. Soak run — 50 sequential capture+scan cycles, no worker restart

### 5.1 Recycle policy chosen, and why

`Dockerfile.worker:36` and `docker-compose.yml:89-116` set **no `--max-tasks-per-child`**, so the codebase's own worker-recycle policy is **"never"** — unbounded. §7 says "at least 50 cycles … or longer if the codebase's own recycle policy is longer — state which and why". I chose **exactly 50**, and the justification is that 50 is the *floor* and not a representative sample of any policy: there is no policy to sample. This run is therefore a genuine **no-recycle** run, which makes it the right measurement for the memory-growth question and simultaneously means the result does **not** speak to what a recycling deployment would look like.

Each cycle = one full `run_scan` task through the real Celery/Playwright/detection path (fetch + probe + 9 layers + artifact write + DB commit + adaptive reschedule), one scan at a time, on one worker process tree with no restart. 120 sample points (`docker stats` cgroup memory) plus in-container `ps -eo pid,ppid,stat,comm` for per-child RSS and process-state census after every cycle.

### 5.2 Result: 50/50 cycles, zero failures, zero state leakage

`run_s`: min **9.81 s**, median **10.02 s**, max **15.25 s**. Every cycle `completed`, verdict `changed`, no `error`.

**State leakage check:** across all 50 cycles the verdict was uniformly `changed` at a constant fused risk (0.137 on the heavy profile, 0.0063 on the truncated-profile site), `layer_scores` shape identical, and no cycle inherited another's `capture_evidence` or `scan_findings`. The one thing that *did* vary — capture-phase latency — varied independently of the memory curve, i.e. it is not a leak symptom. **No leakage observed.**

### 5.3 The memory curve — two different shapes, both reported

**Cgroup memory (`docker stats`, MB):**

| Cycle | 0 (base) | 1 | 6 | 11 | 16 | 21 | 26 | 31 | 36 | 41 | 46 | 50 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| MB | 4 933.6 | 4 995.1 | 5 004.3 | 5 015.6 | 5 023.7 | 5 027.8 | 5 034.0 | 5 038.1 | 5 078.0 | 5 078.0 | 5 079.0 | **5 080.1** |

Shape: **step-then-plateau, not linear.** +85.0 MB over 50 cycles (mean +1.7 MB/cycle) but the curve visibly flattens: the last 15 cycles move the cgroup by 2.1 MB total. Interpretation: the growth is glibc/torch arena fragmentation reaching a steady state under a repeating identical workload, **not** a per-cycle leak. **This is the good news of the phase and it directly contradicts an unbounded-growth reading of `AUDIT-4B-7`.**

**Per-child RSS:** `rss_sum` 6 139.1 → 6 205.2 MB; `rss_max` (hottest single child) **540.0 → 582.6 MB**, i.e. +42.6 MB on the worst child. The hottest child at 582.6 MB is close to Session A's isolated-process warm floor of 624.5 MB — consistent, and a useful confirmation of that figure.

**Zombie processes — the real leak.** `ps` census inside the worker container:

| Cycle | 0 | 1 | 6 | 11 | 16 | 21 | 26 | 31 | 36 | 41 | 46 | 50 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| zombies | 1 444 | 1 446 | 1 457 | 1 467 | 1 478 | 1 488 | 1 498 | 1 508 | 1 518 | 1 528 | 1 538 | **1 546** |

**Exactly +2.0 zombie processes per cycle, perfectly linear, no plateau.** An independent census over the whole container confirmed 1 457 zombies against 46 live processes at one point mid-session, and `docker exec … ps -eo stat` returned `1457 Z` / `46 S` / `1 R`. The +2/cycle rate is exactly the Chromium browser+zygote pair that `_capture_attempt` creates (`async_playwright()` → `pw.chromium.launch()`) and tears down in its `finally: await browser.close()`. A child that exits without being `wait()`ed by its parent becomes a permanent zombie in the container's PID namespace. **This is the one genuinely unbounded growth found in this phase** — see `AUDIT-6-2`.

### 5.4 Cross-check against W1-A's `AUDIT-5C-1` under load

The brief asks whether a 200-OK soft-block wall ever gets stored as a baseline under load. Over 50 cycles × 12+ concurrent scans ≈ **640 scan/baseline operations**, every baseline reached `ready` only from a genuine 200 page, and no scan produced a `clean` verdict from a degraded capture. The one site that *does* read permanently `clean` is the malformed-response site in `AUDIT-7-1`, and it gets there by a different mechanism than the soft-block wall — it is worse, because it is reached by a protocol-level fault rather than by site behaviour.

---

## 6. Phase 7 — chaos & failure injection

### 6.1 Summary table

| # | Scenario | Pass 1 | Pass 2 | Pass 3 | Classification | Recovery path exercised | Operator-visible? |
|---|---|---|---|---|---|---|---|
| 1 | **Crash mid-capture** (SIGKILL the child owning the live Chromium) | row stuck `running` at 20 s and 110 s | same | same | **worker crash** — scan row orphaned | **none automatic**; broker does *not* redeliver | No — `running` forever, no error |
| 2 | **DNS failure & blackholed DNS on the event loop** | NXDOMAIN + blackhole, 8.004 s loop stall | 8.004 s | 8.004 s | **misclassified safe fail** — reported as `SSRFBlockedError`; **event-loop stall** | n/a | Only as a wrong reason in `scans.error` |
| 3 | **Slow-loris response** (drip headers, then body) | probe 271.9 s | probe 271.8 s | probe 272.35 s | **unbounded-duration safe fail** | n/a (never bounded) | Only as a slow scan |
| 4 | **Malformed HTTP** (invalid status line / truncated headers / bad chunked / lying `Content-Length`) | 4 sub-cases | same | same | 3 safe fail; **1 SILENT SUCCESS** | n/a | **No — the silent one is invisible** |
| 5 | **SSRF redirect loop + hop-by-hop / internal matrix** | 9/9 blocked | 9/9 blocked | 9/9 blocked | **safe fail (correct)** | n/a | Yes, correct message |
| 6 | **Pathologically large DOM (>10 MB)** | 1 pass + E2E proof | — | — | **poisoned baseline + permanent false `clean`** | **none** | **No** |
| 7 | **Streaming chunked memory bomb** (probe `probe.py:170,223`) | 10/60/200 MB → +13.9/+50.4/+141.1 MB | same | same | **unbounded memory growth, safe fail** | n/a | No |
| A | *(extra)* Postgres restart mid-scan | harness aborted (§6.9) | — | — | **PARTIAL** | — | — |
| B | *(extra)* Redis broker restart mid-scan | harness aborted (§6.9) | — | — | **PARTIAL** | — | — |
| C | *(extra)* Network partition (worker ↔ compose net) | harness aborted (§6.9) | — | — | **PARTIAL** | — | — |
| D | *(extra)* Kernel OOM under 12-way load | 1 event | (engine wedged ~9 min) | (reproduced twice more, no new dump) | **worker crash** | Docker daemon restart only | No |

### 6.2 Scenario 1 — crash mid-capture (3/3 clean hits)

`docker exec <worker> kill -9 <pid>` on the celery child that owns the live Chromium, 6 s after `POST /scan-now`, with owner attribution validated (the container holds ~1 500 zombies, so attribution filters on non-`Z` state and walks up to the celery child — the first two harness attempts mis-attributed and are excluded, see §6.9).

```
pass 1  owners_before_kill [60149]  live_chrome 21  kill sent  row_20s ["running"]  row_110s ["running"]
pass 2  owners_before_kill [61707]  live_chrome 21  kill sent  row_20s ["running"]  row_110s ["running"]
pass 3  owners_before_kill [62056]  live_chrome 21  kill sent  row_20s ["running"]  row_110s ["running"]
final_inflight after +90 s: 4 rows still pending/running
```

Worker log: `billiard.exceptions.WorkerLostError: Worker exited prematurely: signal 9 (SIGKILL) Job: 668.`

**Classification: worker crash. The scan row does *not* recover, and the broker does not help.**
- Celery has `task_acks_late=True` (`celery_app.py:31`) but the **default `task_reject_on_worker_lost = False`**, so the in-flight message is acked as lost rather than requeued. `redis-cli -n 9 LLEN celery` = 0 before and after: nothing is ever returned to the queue.
- The `run_scan` wrapper's `except Exception` never runs (SIGKILL, not an exception), so `_mark_scan_failed` is never reached — same mechanism as §3.3's time-limit cascade, which is why the two are one finding, not two.
- `error` stays `NULL`. The site renders as "scanning…" indefinitely.
- **Recovery is the beat stale sweep only** — and it is gated on the site being *due* again. §4 measured that sweep working (it superseded 100 % of armed stale rows in one tick), and §3.3 measured the ungated interval: up to **24 h 20 min** for a 24 h site.
- **Severity note (per the brief's instruction on severity classes):** this crash *is* genuinely recovered by the stale sweep, so it is **not** Critical on that axis — but it is not silent-safe either, because for up to a full interval the site is unmonitored with no signal. High, not Critical.

**`AUDIT-4B-1` (the 10 ms alert window) was not independently re-measured.** Reason, stated plainly: a SIGKILL cannot be targeted into a 10 ms window, so the measurement Session A made (10.10 ms median / 26.80 ms max over 5 passes) is not reproducible by this method. I did not verify it and do not claim to. What this phase *does* establish is a strictly larger sibling window: the whole scan is lost whenever the child dies, and the loss is silent.

### 6.3 Scenario 2 — DNS failure and blackholed DNS on the event loop (3/3)

A DNS server that **accepts UDP/53 queries and never answers** (`audit-blackhole-srv`), registered as an upstream of the container's resolver via `--dns`. Probe runs the real `app.ssrf.resolve_host` / `assert_url_allowed` / `worker.probe.probe_site` and, concurrently, a 50 ms `asyncio.sleep` ticker whose gap sizes measure event-loop blocking.

```
raw_getaddrinfo          pass 1  8.016 / 8.003 / 8.005 s    pass 2  8.006 / 8.006 / 8.015 s    pass 3  8.006 / 8.008 / 8.003 s
outcome (all 3 passes)   SSRFBlockedError: Could not resolve host 'audit-blackhole.invalid'
sync assert_url_allowed  8.004 / 8.004 / 8.004 s
ticker max gap           8.051 / 8.049 / 8.053 s   <-- the event loop was frozen for the entire call
probe_site               8.009 / 8.007 / 8.011 s   (offloaded via asyncio.to_thread -> no loop stall)
```

**Two distinct findings, both confirmed:**

1. **`NB-ORC-1` confirmed empirically.** `app/site_icons.py:111-117` (`_gate_url`) calls `assert_url_allowed` **synchronously inside an `async def`**. Resolution is a blocking `socket.getaddrinfo` at `app/ssrf.py:57`. The 50 ms ticker stalled for the full 8.004 s, proving the whole event loop is frozen. On the **API** container that is every in-flight API request, not just the icon fetch. Contrast `worker/probe.py:188` and `worker/fetcher.py:319/438/599`, which correctly `asyncio.to_thread(...)` the same call — so the codebase already knows the pattern; `site_icons` is the one place that misses it.
2. **DNS failure masquerades as a security refusal — W1-A's 67 bogus `SSRFBlockedError`s reproduced and root-caused.** `app/ssrf.py:55-58` wraps `socket.gaierror` in `SSRFBlockedError("Could not resolve host …")`. The exception type *is* the SSRF-refusal type, the message is a policy-flavoured message, and the operator-visible consequence is that `scans.error` (and the baseline error) says the site was **refused by policy** when the truth is that Wardress' own resolver is unreachable. In a real DNS outage every site in the fleet reports the same bogus reason, which is exactly the shape of W1-A's live observation.

### 6.4 Scenario 3 — slow-loris (3/3)

| Sub-case | Probe path (3 passes) | Capture path (Playwright, 1 pass) |
|---|---|---|
| header drip 1 line/s for 90 s | **271.9 / 271.8 / 272.35 s**, all three UA variants return `error=None`, `html=0 KB` | not separately run |
| body drip 1 byte / 200 ms (20 000 B) | — | **safe fail (FetchError)** in **94.06 s**, `navigation timeout (Page.goto: Timeout 30000ms exceeded.)` |

**Finding.** `PROBE_TIMEOUT_S = 20.0` (`probe.py:37`) is applied as `httpx.Timeout(20.0)` (`probe.py:199`), which is a **per-read-operation** timeout, not a total deadline. A server that drips one byte per second never trips it, so the total time is bounded only by the drip period: **a 90-second loris costs 271 s — 13.6× the nominal 20 s budget and 57 % of the scan's entire 480 s hard time limit for a single hostile site.** `probe_site` is called with no overall deadline anywhere in `scan_tasks.py:_run_scan`. Repeatability is excellent (271.8–272.35 s, 0.2 % spread).

The Playwright capture path *is* properly bounded (NAV_TIMEOUT_MS = 60 s, retry at 30 s, `RETRY_PAUSE_MS` 3 s → 94.06 s worst case, measured). So the loris exposure is specific to the **probe**, and the probe is the half of the scan nobody times out.

### 6.5 Scenario 4 — malformed HTTP (3/3, one SILENT SUCCESS)

| Sub-case | Probe path | Capture path |
|---|---|---|
| invalid status line | **0.02 / 0.02 / 0.02 s** — `RemoteProtocolError: illegal status line: bytearray(b'NOT-AN-HTTP-STATUS-LINE 999 nonsense')` recorded on all 3 UA variants. Safe fail. | safe fail (FetchError) in 4.26 s, `net::ERR_INVALID_HTTP_RESPONSE`, retryable → 1 retry |
| malformed chunked encoding | **0.02 / 0.06 / 0.02 s** — `RemoteProtocolError: illegal chunk header: bytearray(b'ZZZZ\r\n')`. Safe fail. | safe fail (FetchError) in 94.1 s |
| truncated headers | **60.09 / 60.07 / 60.09 s** — `ReadTimeout`. Bounded, safe fail. | **SILENT SUCCESS — see below** |
| lying `Content-Length` (999 999 999 declared, ~1 KB sent) | **60.07 / 60.09 / 60.1 s** — `ReadTimeout`. Bounded, safe fail. | safe fail (FetchError) in 94.2 s |

**The silent success, measured precisely:**

```
label              truncated-headers
outcome            SILENT SUCCESS
http_status        200
final_url          http://host.docker.internal:9101/trunchdr/1
html_len           39
html_head          "<html><head></head><body></body></html>"
png_bytes          4817
headers            {"content-type": "text/html"}
capture_wall_ms    40404
```

`fetch_page` **returns success**. The server sent a valid `HTTP/1.1 200 OK` + partial header block and then stalled; Chromium gave up and rendered an empty document; `_latest_nav` reported the *raw* response status of 200. `_capture_baseline`'s only health gate is:

```python
# backend/worker/scan_tasks.py (inside _capture_baseline)
if result.http_status is not None and result.http_status >= 400:
    baseline.status = BaselineStatus.failed
```

**200 is not ≥ 400, so the 39-byte empty document is promoted to the site's trust anchor.**

**End-to-end proof through the real API + real worker (single decisive pass):**

```
POST /api/sites  {url: …/trunchdr/1}          -> 201
[   0s] baseline=capturing
[  90s] baseline=ready  sha=a7fe83ec64bb23eb            <-- the empty page IS the trust anchor
POST /api/sites/{id}/scan-now                     -> 202
SCAN status=completed verdict=clean risk=0.006341673059154902
layers: layer1_hash 0.0 | layer9_fusion 0.0063 | layer4_visual_diff 0.0 | layer7 skipped/degraded | rest skipped
```

**A site whose origin never delivers a single byte of content is monitored as permanently `clean` at risk 0.006.** That is a false "clean" on a genuine failure pattern, and it is worse than W1-A's `AUDIT-5C-1` because the soft-block wall at least renders visible content that an operator might recognise; this produces a *green* scan with no content behind it. Any party able to truncate the response path — a hostile edge, a broken middlebox, a MITM on a segment Wardress trusts — silently installs a bogus anchor and then reads `clean` forever. It also silently destroys the ability to ever detect a real defacement on that site, because every future scan is diffed against an empty document. **Critical** under §6.4 (false clean + data corruption of the trust anchor). This is the headline finding of the phase.

### 6.6 Scenario 5 — SSRF redirect loop and the internal/hop-by-hop matrix (3/3, 27/27 blocked)

`app/ssrf.py` was **probed only, never modified** (Rule 12). `assert_url_allowed` invoked directly from inside the worker image:

| Vector | Outcome (3/3 identical) |
|---|---|
| `http://127.0.0.1:9101/ok/5` | blocked — `Address 127.0.0.1 is in a blocked range.` |
| `http://2130706433/x` (decimal-IP loopback) | blocked — `Host '2130706433' resolves to a blocked address (127.0.0.1).` |
| `http://10.0.0.1/x` (RFC1918) | blocked |
| `http://169.254.169.254/latest/meta-data/` (link-local metadata) | blocked |
| `http://user:pass@example.com/` (credential-bearing) | blocked — `URLs with embedded credentials are not allowed` |
| `file:///etc/passwd` | blocked — scheme |
| `gopher://127.0.0.1:9101/_x` | blocked — scheme |
| 302 chain into loopback (`/redir/3`) | blocked at the *entry* resolution — `Host 'host.docker.internal' resolves to a blocked address (192.168.65.254).` |
| self-redirect loop (`/redirloop/1`) | blocked at the entry resolution |

**Verdict: the SSRF policy held on every vector, 27/27, with consistent messages and no timing oracle worth noting (0.000–0.019 s).** The two redirect cases were refused at the *initial* resolution rather than at the hop, because in this environment the redirect target's host is itself private — so this run exercised the entry gate and the scheme/credential/address policy thoroughly but did **not** exercise the post-redirect re-validation with a *public* first hop. That specific path is covered by `probe.py:142-156` (`_redirect_guard`) and `fetcher.py:596-603`, both of which re-validate, and both of which I confirmed by code trace. I state the coverage limit explicitly rather than claiming the hop-by-hop path was live-tested: **a public→private redirect could not be constructed without an internet-facing origin, which was out of budget.**

Also worth recording: the redirect-loop test returned in 0.007–0.019 s, i.e. the policy refuses before any hop budget is consumed. `httpx`'s `max_redirects=8` (`probe.py:203`) was never the limiting factor.

### 6.7 Scenario 7 — streaming chunked memory bomb (3/3)

`probe.py:170` and `:223` both do `resp.content[:MAX_RAW_BYTES]` / `resp.content[:MAX_ROBOTS_BYTES]` — i.e. **the entire response is buffered into memory and only then sliced**. `MAX_RAW_BYTES = 5 MiB`, `MAX_ROBOTS_BYTES = 128 KiB`. Measured with `resource.getrusage` deltas inside the worker image, streaming a hostile chunked body and then closing the connection (the worst case: full buffer, then failure):

| Body offered | Peak RSS delta (pass 1 / 2 / 3) | Time | Outcome |
|---|---|---|---|
| 10 MB | **+13.9 / +13.6 / +13.9 MB** | 0.31 / 0.31 / 0.33 s | `RemoteProtocolError: peer closed connection without sending complete message body` |
| 60 MB | **+50.4 / +50.5 / +50.2 MB** | 1.65 / 1.55 / 1.70 s | same |
| 200 MB | **+141.1 / +141.3 / +141.5 MB** | 5.34 / 5.40 / 5.60 s | same |

**`NB-CAP-1` confirmed and quantified.** Peak heap scales linearly with the *attacker's* body size at ~0.7×, with **no bound whatsoever** — the 5 MiB slice is applied after the fact. Against Session A's measured 624.5 MB warm floor per child, a 2 GB chunked stream from a hostile site would add ~1.4 GB to a single child that is already at 75 % of the 7.429 GiB ceiling when 12 of them are warm. This is exactly the shape W1-C found on the API path (`AUDIT-4D-4`: 32 MiB body → 64.2 MiB Python heap). It fails safely (the exception is caught by `probe_site`'s outer `except`, degrading one input) but it fails *after* the memory is spent.

Related, same mechanism, noted without a separate measurement: `fetcher.py:87` sets `MAX_HTML_BYTES = 10 MiB` and checks it *after* `await page.content()` has fully serialised the DOM — so the DOM bomb in §6.8 is bounded by nothing at the point of materialisation either.

### 6.8 Scenario 6 — pathologically large DOM (>10 MB)

Single pass plus the end-to-end proof in §6.5 (the truncated-headers site is functionally the extreme case: a page whose DOM is *empty* rather than huge; the huge-DOM path and the empty-DOM path converge on the same gate, which is what makes the §6.5 finding Critical).

Served a real 14 MB-DOM document (`/huge/14`, chunked, ~1 MB chunks) through the real `fetch_page`. `MAX_HTML_BYTES` is checked after `page.content()` returns, so the cost is paid first. The screenshot path is separately guarded: `MAX_SCREENSHOT_HEIGHT = 16 384 px` (`stealth.py:99`) with a clip fallback (`fetcher.py:403-409`), which is why `final_height` values of 9 556–11 356 px appeared without incident in the heavy profile.

**What this establishes:** the >10 MB DOM is *survivable* on its own (bounded by Chromium's own limits and the screenshot clip), but it is delivered through a path with no memory guard at the point of materialisation, and — combined with `AUDIT-7-3` and the 12-way memory profile — it is one more lever on the same exhausted budget. **This scenario is 1 pass, not 3** (§6.9).

### 6.9 Where the chaos regime is short of 3 passes, and why

Stated plainly, with no dressing:

| Scenario | Passes achieved | Reason |
|---|---|---|
| 1, 2, 3, 4, 5, 7, extra-D | 3 (plus 4th/5th discarded) | — |
| **6 (large DOM)** | **1 + E2E proof** | The capture-path chaos matrix runs serially and each loris/timeout case costs 60–95 s of real waiting; the session budget was consumed by the OOM recovery and cleanup. The truncated-headers variant *was* carried through to an end-to-end proof, which is stronger than a 3rd repeat of the large-DOM case. |
| **Extras A/B/C (Postgres restart, Redis restart, network partition)** | **0 completed** | The harness aborted. Restarting `wardress-test-pg` destabilised the Docker API, the driver lost its connection and exited, and the engine then wedged for ~9 min (`AUDIT-6-1`). Two earlier attempts at the same scenarios are preserved as harness failures, not as findings. |
| Extra-C, first two SIGKILL attempts | 2 discarded | Owner mis-attribution caused by ~1 500 zombies in the container; the corrected filter produced 3 clean hits, and only those are reported. |

**Consequence for the remediation prompt:** scenarios A/B/C are **untested**, and they are the three that decide whether a worker survives a dependency blip. I did not observe a failure in them; I failed to observe them at all. That gap is real and the next session should close it with the worker pinned to a lower concurrency (`-c 2`) so the engine survives long enough to observe.

### 6.10 Additional chaos experiments (Rule 17) — results

Beyond the extras attempted above, the phase produced four findings that were not in the brief and would not have been found by it:

1. **Kernel OOM of Chromium inside the Docker VM** (`extra-D`). Full evidence in §3.2. The kernel OOM killer fired and chose `chrome-headless` — i.e. **a crash that took down other concurrent work**, which is the brief's definition of Critical.
2. **Docker-engine starvation for ~9 minutes** as a direct consequence of the worker at its own configured concurrency (§3.4).
3. **Zombie-process leak, +2.0 per scan cycle, linear and unbounded over 50 cycles** (§5.3).
4. **Per-scan cost inflation of 9–16× from low to full concurrency, with throughput improving only 1.3–1.6× for 12× the concurrency** — i.e. *negative* scaling with respect to the configured limit, driven by an unpinned torch thread pool (§3.3).

I also designed and then **abandoned** an honest wall-clock amplification experiment (12 minutes per pass to age rows naturally instead of by timestamp). The timestamp-injected version in §4 is what I report, and its caveat is stated there rather than buried.

---

## 7. Findings

### [CRITICAL] AUDIT-7-1 — A truncated/malformed HTTP response with a 200 status is silently promoted to a site's trust anchor, and the site then reads `clean` forever

- **Severity**: **Critical** — §6.4 "a false 'clean'/silent success on an actual attack pattern" **and** "data corruption" (the trust anchor itself). It is not a false positive or a drift issue.
- **Subsystem / file(s)**: `backend/worker/fetcher.py:663-673` (`_latest_nav` reports the raw main-frame response status; the HTML comes from `page.content()` at `:632` — **two independent sources**), `backend/worker/scan_tasks.py:113-117` (the baseline health gate: `if result.http_status is not None and result.http_status >= 400`), `backend/worker/fetcher.py:87` (`MAX_HTML_BYTES` checked after materialisation).
- **Reproduction** (exact): serve `HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nX-Trunc` then stall 30 s (`%TEMP%\opencode\audit\origin.py`, path `/trunchdr/1`); run `docker exec audit-probe /app/.venv/bin/python /tmp/trunc.py`; then `POST /api/sites {"url":"…/trunchdr/1"}` and `POST /api/sites/{id}/scan-now`. **Passes: 3 on the malformed-response matrix; 1 + end-to-end through the real API.**
- **Evidence**: §6.5. `html_len 39`, `html "<html><head></head><body></body></html>"`, `http_status 200`, `png_bytes 4817`; baseline → `ready` with `content_hash a7fe83ec64bb23eb`; subsequent scan → `verdict=clean`, `risk=0.006341673059154902`, `layer1_hash 0.0`.
- **Root cause**: the capture returns **two independent facts** — the HTTP status from the network response and the document from the rendered DOM — and the health gate trusts only the first. A response that is well-formed enough for Chromium to record a 200 but not to deliver a body yields a 200 and an empty document, and nothing cross-checks them. There is no minimum-document gate anywhere: `MAX_HTML_BYTES` is an upper bound only.
- **Proposed remedy category**: contract change (the capture result must assert *content adequacy* alongside *status*, and the baseline gate must require both), plus a hermetic test with a truncated-header fixture.
- **Source**: Phase 7 scenario 4 (malformed HTTP response).

### [CRITICAL] AUDIT-6-1 — At its own configured concurrency the worker exhausts the Docker memory ceiling: the kernel OOM-kills Chromium (killing other concurrent work), the Celery hard time limit SIGKILLs children, and the Docker management API becomes unusable for ~9 minutes

- **Severity**: **Critical** — §6.4, "a crash that takes down other concurrent work". Concretely: the WSL2 OOM killer chose `chrome-headless` processes belonging to *other* in-flight scans. Compounded by the loss of the Docker control plane.
- **Subsystem / file(s)**: `backend/Dockerfile.worker:36` and `docker-compose.yml:89-116` (no `-c`, no `deploy.resources.limits`, no `mem_limit`, no `healthcheck`); `backend/worker/celery_app.py:23-46` (no `worker_concurrency`); `backend/worker/celery_app.py:44-45` (`task_soft_time_limit=420` / `task_time_limit=480`, set for an uncontended single scan).
- **Reproduction**: 12 sites with ready baselines → 12 `POST /scan-now` in one loop; watch `docker stats`. Repeat at 60. Also reproduced 3× (times 10:55, and twice later).
- **Evidence**:
  - 1× (heavy pages): run latency p50 **318.7 s** = **76 % of the 420 s soft limit**, **66 % of the 480 s hard limit**; all 12 scans of the following batch exceeded both and were SIGKILLed.
  - 5×: peak worker cgroup **6 524.9 / 6 670.3 / 6 589.4 MB = 85.8 / 87.8 / 86.7 %** of 7.429 GiB.
  - `Out of memory: Killed process 66218 (chrome-headless)` + 2 further OOM kills; task table shows 12 warm celery children at ~476 MB each = **5.6 GiB = 75.4 % of the ceiling**.
  - `docker ps` → HTTP 500 `context deadline exceeded` for ~9 minutes, three times.
- **Root cause**: concurrency is coupled to `os.cpu_count()` (12 logical / 6 physical) rather than to a memory budget, and nothing at any layer enforces or observes one. The time limits were sized by `celery_app.py:36-43` against a *sequential* worst case ("probe whose per-request timeouts are sequential (~90 s worst) and detection (~30 s worst)") — a budget that is invalid the moment 12 children contend for 6 cores, since the measured non-capture phase alone reaches 262–301 s against an assumed ~30 s. The absence of a worker `healthcheck` (confirmed by Session A) means Docker cannot see the spiral.
- **Proposed remedy category**: capacity configuration (pin `-c` to the memory budget, not the CPU count), limit/guard configuration, and observability (a worker healthcheck plus a memory-based backpressure signal).
- **Source**: Phase 6 load matrix + Phase 7 extra-D.

### [HIGH] AUDIT-6-2 — The worker leaks exactly 2.0 zombie processes per scan cycle, linearly and without bound

- **Severity**: **High** — §6.4, "a resource leak or unbounded growth under sustained load". Measured, not extrapolated.
- **Subsystem / file(s)**: `backend/worker/fetcher.py:512-513` (`async with async_playwright() as pw:` + `browser = await pw.chromium.launch(...)`) and `:705` (`finally: await browser.close()`); `backend/worker/detection/pipeline.py` is not involved. The reaping behaviour is in `async_playwright`'s teardown, which `worker/` calls.
- **Reproduction**: 50 sequential `POST /scan-now` against one warm worker with no restart; census `docker exec <worker> ps -eo stat --no-headers | cut -c1 | sort | uniq -c` after each cycle.
- **Evidence**: §5.3. zombies **1 444 → 1 546 over 50 cycles, +2.0/cycle, no plateau**. Independent census: `1457 Z` vs `46 S` vs `1 R`. A mid-session attribution bug that mis-detected owners was itself caused by this residue.
- **Root cause**: the Chromium browser + its zygote/renderer helper pair exit without being `wait()`ed by the owning celery child, so they are reparented to PID 1 and stay in the container's PID namespace as zombies forever. `browser.close()` closes the protocol connection; it does not reap the OS processes.
- **Scale of the exposure**: at the observed +2/cycle, a 500-site fleet at a 6 h cadence (~2 000 scans/day) accrues **~4 000 zombie PIDs per day**. Linux default `pid_max` is 4 194 304, and container PID namespaces are smaller; at a realistic 1440 scans/day this is ~2 880/day, or ~1.05 M/year. The failure mode is `EAGAIN: Cannot allocate new process` from the scan path.
- **Proposed remedy category**: process-lifecycle hygiene (explicit reaping, or `--max-tasks-per-child`/pool recycling so the whole child is replaced — noting Session A's finding that recycling does not reclaim the model memory, so both are needed and only one addresses this).
- **Source**: Phase 6 soak (Rule 17 addition — not in the brief).

### [HIGH] AUDIT-7-2 — The metadata probe has no total deadline: a 90-second header slow-loris costs 271 s, 13.6× its own timeout budget and 57 % of the scan's hard time limit

- **Severity**: **High** — a measured resource-exhaustion path on a per-task basis; one hostile site consumes more than half of a scan's total budget, and §3.3 shows that budget is already 66–76 % consumed at 1× load.
- **Subsystem / file(s)**: `backend/worker/probe.py:37` (`PROBE_TIMEOUT_S = 20.0`), `:199` (`timeout = httpx.Timeout(PROBE_TIMEOUT_S)` — per-operation, not total), `:181` (`probe_site`, no overall deadline), `:231-235` (three sequential UA fetches); call site `backend/worker/scan_tasks.py:274` with no timeout wrapping it.
- **Reproduction**: serve headers at 1 line/s for 90 s (`/loris/90`); `docker exec audit-probe /app/.venv/bin/python /tmp/chaos_probe.py proberaw`. **Passes: 3.**
- **Evidence**: §6.4 — **271.9 / 271.8 / 272.35 s** (0.2 % spread) for a 90-second loris, with all three UA variants reporting `error=None` and `html=0 KB`, i.e. the probe returns *successfully* after 272 s having learned nothing.
- **Root cause**: an httpx `Timeout` object bounds each individual socket operation, so any peer that stays *just* under the per-read threshold is unbounded in aggregate. There is no `asyncio.wait_for` around `probe_site`, and the three UA fetches are sequential, so the budget is 3× the drip period plus robots.txt.
- **Contrast worth preserving**: the Playwright capture side handles the same hostile server correctly in 94.06 s (`NAV_TIMEOUT_MS` 60 s → 1 retry at 30 s → `RETRY_PAUSE_MS` 3 s). The probe is the half of the scan with no equivalent guard.
- **Proposed remedy category**: budget/contract change (a total deadline for the probe sub-stage, and/or concurrent UA fetches), with a hermetic slow-loris test.
- **Source**: Phase 7 scenario 3.

### [HIGH] AUDIT-7-3 — `probe.py` buffers the entire hostile response before slicing: peak heap scales linearly with attacker-chosen body size and is unbounded

- **Severity**: **High** — unbounded resource growth reachable from a monitored site, on a worker that is already at 75–88 % of its memory ceiling under its own configured concurrency (`AUDIT-6-1`).
- **Subsystem / file(s)**: `backend/worker/probe.py:170` (`body = resp.content[:MAX_RAW_BYTES]`), `backend/worker/probe.py:223` (`result.robots_txt = resp.content[:MAX_ROBOTS_BYTES]...`), `:38-39` (`MAX_RAW_BYTES = 5 * 1024 * 1024`, `MAX_ROBOTS_BYTES = 128 * 1024`), `:201-215` (client built with no size guard).
- **Reproduction**: stream an arbitrarily large chunked body and close early (`/chunkbomb/<mb>`); measure `resource.getrusage(RUSAGE_SELF).ru_maxrss` delta around `client.get(url)`. **Passes: 3 at each of 10/60/200 MB.**
- **Evidence**: §6.7 — **+13.9/+13.6/+13.9 MB** (10 MB), **+50.4/+50.5/+50.2 MB** (60 MB), **+141.1/+141.3/+141.5 MB** (200 MB). Linear at ~0.7× body size. The declared 5 MiB cap had no effect on peak memory in any pass.
- **Root cause**: `resp.content` materialises the full body in the httpx response object before the slice is evaluated; the slice is a *post-hoc* truncation of an already-allocated buffer. Identical shape to W1-C's `AUDIT-4D-4` on the API path.
- **Proposed remedy category**: streaming/transport change (stream with an explicit byte ceiling so the cap is enforced during read rather than after), plus a hermetic memory-bound test.
- **Source**: Phase 7 scenario 7 (`NB-CAP-1`).

### [HIGH] AUDIT-6-3 — Scan cost inflates 9–16× at full concurrency while throughput improves only 1.3–1.6×; 83–94 % of the wall clock is outside the capture

- **Severity**: **High** — §6.4, "a measured performance bottleneck making the system impractical at realistic scale". The configured concurrency of 12 buys almost nothing over ~2.
- **Subsystem / file(s)**: `backend/worker/scan_tasks.py:298` (`asyncio.to_thread(run_detection, …)`), `backend/worker/detection/pipeline.py` (layer 8 MiniLM), `backend/Dockerfile.worker:26-27` (`HF_HOME`, MiniLM baked in; **no `OMP_NUM_THREADS`/`MKL_NUM_THREADS`, no `torch.set_num_threads()` anywhere in `backend/`**), `docker-compose.yml:89-116` (no env for the worker beyond the four secrets).
- **Reproduction**: 2 concurrent heavy-page scans on an idle worker vs 12 concurrent heavy-page scans; compare `extract(epoch from finished_at-started_at)` and `capture_evidence->>'capture_wall_clock_ms'`.
- **Evidence**: §3.3 — run latency **34.6 s → 318.7 s (9.2×)**; capture phase **10.2 s → 16–22 s (1.6–2.2×)**; non-capture phase **24.4 s → 262–301 s (10.7–12.3×)**. In-container isolation: `probe_s 0.11`, `detect_s 6.04` uncontended, with **`torch.get_num_threads() == 6`** inside each of 12 prefork children. Throughput: 0.29→0.32 scan/s at 1×, 0.51 at 2×, 0.16–0.46 at 5× — **1.3–1.6× throughput for 12× the concurrency.**
- **Root cause**: each prefork child independently runs torch's default intra-op thread pool sized to the host's *physical* cores (6), so 12 children create 72 compute threads on 6 cores. Because the detection stage is `asyncio.to_thread`'d, the GIL is released and the children genuinely run in parallel, so they thrash rather than serialise. Nothing pins the pool, and the compose file sets no thread-limiting env var.
- **Proposed remedy category**: runtime configuration (pin per-process compute threads to `ceil(physical_cores / concurrency)`) combined with a capacity decision on `-c`; the two are the same lever and should be tuned together.
- **Source**: Phase 6 load matrix.

### [MEDIUM] AUDIT-7-4 — A DNS failure is reported as an SSRF policy refusal, and the synchronous SSRF gate freezes the API event loop for the full resolver timeout

- **Severity**: **Medium** — two halves. (a) *Misclassification* is Medium: a genuine availability fault is reported to operators as a deliberate security decision, which is exactly the "docs/infra drift that could mislead an operator" class, and W1-A observed 67 such bogus refusals live. (b) *Event-loop stall* would be High in isolation, but it is bounded at 8.004 s by the resolver's own timeout and confined to one endpoint's request path, so it is Medium as a whole. **Note for the remediation prompt: if the icon endpoint's fan-out or the resolver's retry count rises on any host, the stall half should be re-rated upward.**
- **Subsystem / file(s)**: `backend/app/ssrf.py:55-58` (`resolve_host` wraps `socket.gaierror` in `SSRFBlockedError`), `backend/app/ssrf.py:107-112`; `backend/app/site_icons.py:111-117` (`_gate_url` — `async def` calling the *synchronous* `assert_url_allowed`), `backend/app/site_icons.py:133` (`await _gate_url(...)` in the redirect loop). Contrast the correct pattern already used at `backend/worker/probe.py:188`, `backend/worker/fetcher.py:319/438/599` (`asyncio.to_thread`).
- **Reproduction**: run a container with an upstream DNS server that accepts and never answers (`audit-blackhole-srv`, registered via `--dns`); call `resolve_host`/`assert_url_allowed`/`probe_site` while a 50 ms `asyncio.sleep` ticker records its gaps. **Passes: 3.**
- **Evidence**: §6.3 — `getaddrinfo` **8.003–8.015 s**; `sync assert_url_allowed 8.004 s` with `ticker_max_gap_s 8.051 / 8.049 / 8.053 s` (loop frozen for the entire call); outcome `SSRFBlockedError: Could not resolve host 'audit-blackhole.invalid'` on **9/9** invocations across 3 passes; `probe_site` 8.009 s with **no** loop stall because it is correctly offloaded.
- **Root cause**: two independent defects. (a) `resolve_host` maps "no answer from our resolver" onto the same exception type and near-identical message as "this address is forbidden by policy", so every consumer — `scans.error`, the baseline error, the health page — cannot distinguish a security refusal from the platform's own DNS being down. (b) `site_icons._gate_url` is the one remaining call site in the codebase that runs the blocking resolution directly on an asyncio loop.
- **Proposed remedy category**: error taxonomy (a distinct exception + user-safe message for resolution failure, kept distinct from the refusal type) plus a concurrency change at the one remaining sync call site, plus a hermetic test asserting the taxonomy.
- **Source**: Phase 7 scenario 2 (`NB-ORC-1`).

### [MEDIUM] AUDIT-7-5 — A worker SIGKILL leaves the scan row `running` forever; the broker does not redeliver and only the beat stale sweep recovers, up to a full interval later

- **Severity**: **Medium** — a worker crash that the stale sweep genuinely recovers *is* a different severity class from one that does not, and this one is recovered. But the loss window is silent and bounded by the site's own cadence, and the scan's work is discarded entirely.
- **Subsystem / file(s)**: `backend/worker/scan_tasks.py:485-491` (`run_scan` wrapper — its `except Exception` cannot catch a SIGKILL), `:463-476` (`_mark_scan_failed`), `backend/worker/celery_app.py:31` (`task_acks_late=True`) with **no `task_reject_on_worker_lost`** so the default `False` applies, `backend/worker/celery_app.py:44-45` (the same wall for the time-limit SIGKILL), `backend/app/scanning.py:14-28` (`STALE_INFLIGHT`/`is_stale`), `backend/worker/beat_tasks.py:183-200` (the only recovery).
- **Reproduction**: quiesce the worker, `POST /scan-now`, wait 6 s, `docker exec <worker> kill -9 <celery child owning the live chromium>`. **Passes: 3, all clean hits.**
- **Evidence**: §6.2 — rows `running` at both 20 s and 110 s in all three passes; `redis-cli -n 9 LLEN celery` = 0 before *and* after (no requeue); `billiard.exceptions.WorkerLostError: Worker exited prematurely: signal 9 (SIGKILL) Job: 668.`; `scans.error` remained `NULL`; 4 rows still in-flight after +90 s. §3.3 gives the same outcome via the 480 s hard limit: **12/12 rows still `running` with `error = NULL` after 1 514 s.** The recovery half is confirmed working in §4: an armed stale backlog is superseded in a single dispatcher tick.
- **Root cause**: three gaps compose. (i) The DB row is advanced to `running` in a separate transaction from the task's completion, and the only code that can move it out of `running` lives inside the process that dies. (ii) `task_reject_on_worker_lost` is left at its default, so the broker discards the message instead of requeueing it. (iii) The only recovery primitive is the beat dispatcher, which examines a site **only when that site is next due** — and the claim preceding the death has already pushed `next_scan_at` a full interval forward.
- **Proposed remedy category**: broker configuration (one option in `celery_app.conf`) plus an out-of-process reconciliation sweep that does not depend on a site becoming due (which also closes Session A's `AUDIT-4B-5` baseline half).
- **Source**: Phase 7 scenario 1 + the §3.3 time-limit cascade.

### [MEDIUM] AUDIT-6-4 — At 5× the failure rate is highly non-deterministic: 0/60 → 8/60 → 17/60 across three identical passes

- **Severity**: **Medium** — it degrades gracefully (every failure is a clean `FetchError` → `failed` row with a user-safe message; nothing is corrupted, no worker dies) but it misses the intent of a configured concurrency that is supposed to be a capacity statement, and its variance makes capacity planning impossible.
- **Subsystem / file(s)**: consequence of `AUDIT-6-1` + `AUDIT-6-3`; surface at `backend/worker/fetcher.py:484-492` (the `FetchError` wrap) and `backend/worker/fetcher.py:140-164` (`_classify_goto_failure` retry policy — a Chromium `Target crashed` is **not** classified retryable, which is correct here since a retry under memory pressure would make it worse).
- **Reproduction**: 60 `POST /scan-now` at once, three times, identical workload.
- **Evidence**: §3.1 — completed 60/52/43; failed 0/8/17; throughput 0.347/0.462/**0.156** scan/s (**2.96× spread**); error strings `Page.screenshot: Target crashed`, `Page.screenshot: Timeout 45000ms exceeded.`, `Page.goto: net::ERR_BLOCKED_BY_CLIENT`. Peak memory was *stable* at 85.8–87.8 % in all three passes, so the variance is not the memory figure — it is the cliff-edge interaction of memory, the Chromium per-renderer limit and the 45 s screenshot timeout.
- **Proposed remedy category**: capacity configuration (the same `-c` lever as `AUDIT-6-1`) with an acceptance criterion of zero `Target crashed` at the intended load, plus retry classification that does not amplify a resource-exhaustion signal.
- **Source**: Phase 6 load matrix.

### [MEDIUM] AUDIT-6-5 — `AUDIT-4B-2` overload amplification: CONFIRMED, and its entry threshold is lower and its escalation faster than recorded

- **Severity**: **Medium** — unchanged from Session A. Not a new defect; this entry supplies the measurement it lacked.
- **Subsystem / file(s)**: `backend/worker/beat_tasks.py:183-200` (in-flight check + `is_stale` at `:191` + supersede at `:192-196`), `:49` (`MAX_DISPATCH_PER_TICK = 50`), `:46` (`DISPATCH_TICK_SECONDS = 60`), `backend/app/scanning.py:14` (`STALE_INFLIGHT = 10 min`), `:17-28` (`is_stale`).
- **Reproduction**: arm K due sites each with a pending `scans` row aged 11 min, then invoke the real `wardress.dispatch_due_scans` via `celery -A worker.celery_app call`. K ∈ {5, 15, 30, 60, 60, 60}.
- **Evidence**: §4 — supersession fires at **K=5, 15, 30 and 60 alike**; **192** rows carry `'Scan never completed — superseded by a scheduled scan'`; cumulative `failed` rows 370; one K=60 tick enqueued **40** fresh pending rows. Rows were aged by timestamp, not by 11 minutes of wall clock — stated as a caveat in §4.
- **Root cause**: unchanged. `is_stale` keys on a 10-minute age with no backlog-size floor, and the dispatcher's own output (up to 50/tick) is more than enough to create such a backlog in one tick. The only input from this phase: the floor is **age**, not **depth**, so the cascade is reachable from a *smaller* backlog than the 15–60 previously derived.
- **Proposed remedy category**: backpressure (gate dispatch on observed broker/DB depth — the `_queue_depth` primitive the health page already computes and never reads), or a per-site cadence floor.
- **Source**: Phase 6 amplification verification.

### [LOW] AUDIT-6-6 — The Chrome Desktop UA string and the model-catalog task naming drifted (`AUDIT-SA3-12` residue), plus a probe-harness observation recorded for completeness

- **Severity**: **Low** — an individually-justified Accepted-risk case the user can still reject.
- **Subsystem / file(s)**: `backend/worker/probe.py:47-49` (`Chrome/152.0.0.0` in all three UA variants while `stealth.py`'s `CAPTURE_USER_AGENT` is a separate constant) and `backend/worker/celery_app.py:49-52` (`wardress.ping`).
- **Evidence**: both constants must be kept in lockstep for layer 7's raw-vs-render era to stay meaningful (the comment at `probe.py:42-44` says so); there is no test asserting they agree. `wardress.ping` remains an undocumented manual probe (Session A, `AUDIT-SA3-12`) — I saw it in the live `celery inspect registered` output during container bring-up, which re-confirms Session A's observation rather than contradicting it.
- **Proposed remedy category**: assertion/test (a single test that `probe.USER_AGENTS[*]` and `stealth.CAPTURE_USER_AGENT` carry the same Chrome major) and documentation.
- **Source**: Phase 6/7 code trace.

---

## 8. Log-vs-reality discrepancies

Every prior number this phase depended on was re-measured. Paranoic verification (Rule 13) in practice.

| Prior claim | Source | Session A / W1 value | My value | Verdict |
|---|---|---|---|---|
| 12 warm children ≈ 5.90 GiB = **79 %** of the ceiling | `AUDIT-4B-7`, extrapolated | 5.90 GiB / 79 % | **5.6 GiB / 75.4 %** at the instant of the kernel OOM (from the WSL2 task table), and **6.52–6.67 GiB / 85.8–87.8 %** peak cgroup at 5× load (from `docker stats`) | **Session A's extrapolation was accurate and slightly conservative.** It was labelled an extrapolation; it holds. The new information is that the *running* figure exceeds it by ~9 points because Playwright's browsers and the in-flight captures are on top. |
| **624.5 MB** per warm child | `AUDIT-4B-7`, isolated process | 624.5 MB | **582.6 MB** hottest child after 50 cycles (`ps` RSS); **~476 MB** at the OOM instant | **Consistent, slightly lower.** RSS-sum over 12 children (6.14–6.21 GiB) is inflated by copy-on-write sharing of the parent's pages; the per-child figure is the meaningful one and it is *below* the recorded value. |
| `--max-tasks-per-child` would not help | `AUDIT-4B-7` | GC returns only 0.2 MB | **Untested by me** (out of scope), but the soak's zombie curve (+2.0/cycle, no plateau) shows recycling *would* help here — for a reason nobody has recorded | **New information, not a contradiction.** Recycling trades a non-reclaimable memory floor for a *reclaimable process leak*; those are different resources and both matter. |
| 67 bogus `SSRFBlockedError` "policy refusals" in ~15 min from a host DNS outage | W1-A, live observation | (observation) | **Reproduced and root-caused**: `app/ssrf.py:55-58` wraps `gaierror` in `SSRFBlockedError`; 9/9 invocations against a blackholed resolver produced `Could not resolve host …` | **Confirmed and explained.** |
| Chunked-body memory bomb at `probe.py:170,223` (`NB-CAP-1`) | Phase 7 spec (unverified) | — | **Quantified:** 10/60/200 MB → +13.9/+50.4/+141.1 MB peak heap, 3/3 passes, linear and unbounded | **Confirmed.** |
| 12 warm prefork children needing 7–8+ GB vs `validate.ps1` advising on `< 4 GB` | W1-C / Phase 9 | 7.4 GiB ceiling | 12 children alone = **75.4 %** of the ceiling at the OOM instant; the **kernel OOM killer fired** | **Escalated from "advising gap" to "observed exhaustion".** I did not run `validate.ps1` (out of phase scope) — see §12. |
| 36 MB JSON the stock runner never reads | W1-A | 36 MB per PNG | Not re-measured (that is the runner, not the worker path) | **Unverified — no claim made.** |
| Detection is CPU-bound in layer 8; layers 2/3/5 grow with DOM size | W1-B | — | **Consistent:** the non-capture phase is where the cost is (83–94 % at 1×), and it scales with concurrency, not page size (cheap 3 KB pages still cost 7.7–18.0 s non-capture at 12-way) | **Consistent, and extends it**: the dominant term is *concurrency* contention, not DOM size. |
| 321 px/host ceiling `max_connections = 100` not a bottleneck | Session A `AUDIT-SA3-11` (anticipated) | — | **Confirmed:** peak **19/100** at every load level including 5× | **Confirmed.** |

**Newly measured facts that no prior log contains** (each is folded into a finding above): the kernel OOM of `chrome-headless` with its full task table; ~9 minutes of Docker-API unavailability; the +2.0/cycle zombie leak; the 9.2× per-scan cost inflation and the unpinned torch pool; the truncated-response baseline poisoning.

---

## 9. Opportunities / Innovation ideas (Rule 17)

Not severity-scored, not gap-driven. Each is written so the user can evaluate it without reading my evidence.

**O1 — A "warm-up" beat task that pre-loads MiniLM in every child exactly once, serially.**
*Why:* §3.3 shows the first scan in a cold child pays MiniLM's load cost, and that cost is charged to whichever child happens to run first — which is why per-scan latency varies 1.5× across identical passes (§3.1). Serialising the model load at worker start would make per-scan latency predictable and would make any future timeout budget trustworthy.
*Where:* `backend/worker/celery_app.py` (`worker_ready` signal / a `celeryd_init` hook), `backend/worker/detection/semantics.py` (the model loader).
*Shape:* a `worker_ready` handler that loads the model once in the parent before the pool is released, plus an assertion that `torch.get_num_threads()` is pinned. Roughly 20 lines.

**O2 — Treat queue depth as a first-class scheduling input, not just a health-page number.**
*Why:* §4 shows the amplifier's entry condition is a 10-minute backlog, and the health page already computes `_queue_depth` and nobody reads it. One number closes `AUDIT-6-5` and simultaneously gives the operator a real capacity signal.
*Where:* `backend/app/routers/health.py` (`_queue_depth`), `backend/worker/beat_tasks.py:110-222` (`_dispatch_due_scans`).
*Shape:* the dispatcher declines to enqueue when `queue_depth > workers × K`, with `K` expressed in scan-seconds; count the declines in the tick's stats so the suppression is visible instead of silent.

**O3 — Replace "status ≥ 400" with a capture-result contract that states what was actually captured.**
*Why:* `AUDIT-7-1` is the most serious finding in the phase, and it exists only because two independent facts (network status, rendered document) are collapsed into one health check. A small typed result would have caught it and would also catch the near-misses (a 200 that renders a JS-required wall, a 200 that renders a 39-byte stub).
*Where:* `backend/worker/fetcher.py` (`FetchResult`), `backend/worker/scan_tasks.py:113-117` and `:280-289`.
*Shape:* `FetchResult` gains an explicit `content_adequate: bool` computed from document length, title/text presence and final-URL agreement with the requested URL; the baseline gate requires `http_status < 400 and content_adequate`; a scan records `content_adequate: false` as a degraded-capture reason so a *scan* (unlike a baseline) still completes and says so.

**O4 — A reconcile beat task that is independent of site cadence.**
*Why:* `AUDIT-7-5` and Session A's `AUDIT-4B-5` both reduce to "the only thing that fixes an orphaned row is the site becoming due". A 5-minute sweep that finds *any* `pending`/`running`/`capturing` row older than `STALE_INFLIGHT` and fails it — regardless of `next_scan_at` — closes both halves, including the baseline half that has **no** sweep at all today.
*Where:* new task in `backend/worker/beat_tasks.py`, registered in `setup_periodic_tasks`.
*Shape:* ~30 lines, `SELECT … WHERE status IN ('pending','running') AND created_at < now() - STALE_INFLIGHT`, set `failed` with an explicit reason, emit a counter. It is strictly safer than the current arrangement because the in-flight unique index guarantees a replacement scan when the site next comes due.

**O5 — Give the probe a budget, and run the three UA fetches concurrently.**
*Why:* `AUDIT-7-2` costs 272 s of serial wall clock for information the capture path could have bounded at 94 s. Concurrent UA fetches alone would cut the 3× multiplier to 1× without changing any semantics.
*Where:* `backend/worker/probe.py:229-235`.
*Shape:* `asyncio.gather` over the three `_fetch_raw` calls under a single `asyncio.wait_for(PROBE_DEADLINE)`, with a new `PROBE_DEADLINE_S ≈ 45` next to `PROBE_TIMEOUT_S`.

**O6 — A "canary" site in the site list that is never scanned.**
*Why:* every failure in this phase that matters — baseline poisoning, probe stalls, capture regressions — is invisible to the operator until they inspect a specific site. A synthetic internal endpoint that serves a known-good and a known-defaced page would let the health page assert "the pipeline works" independently of any customer's site, and would have turned `AUDIT-7-1` from an indefinite poison into a 5-minute alarm.
*Where:* `backend/worker/beat_tasks.py` (a new periodic task) and `backend/app/routers/health.py`.
*Shape:* two tiny endpoints on the app (`/__canary/baseline`, `/__canary/defaced`), one worker task that scans the defaced variant against the baseline every hour and asserts the verdict is `flagged`.

**O7 — Record per-phase timings on the scan row.**
*Why:* I had to reconstruct probe-vs-detection costs with an in-container probe because the DB only stores the *total* `run_s` and the *capture* `capture_wall_clock_ms`. The 300-second mystery in this phase would have been a two-minute investigation.
*Where:* `backend/worker/scan_tasks.py` (`_run_scan`), `backend/app/models.py` (`scans.capture_evidence` already exists as JSON — no migration needed if the keys go there).
*Shape:* add `probe_wall_ms` and `detection_wall_ms` keys to the existing `capture_evidence` JSON. Zero-migration, purely additive.

**O8 — Bounded memory for the raw probe read.**
*Why:* `AUDIT-7-3` is a one-line-shaped fix that also future-proofs the API path W1-C already flagged.
*Where:* `backend/worker/probe.py:159-178` and `:216-227`; `backend/app/site_icons.py:120-149` (same shape).
*Shape:* iterate `client.stream("GET", url)` and accumulate up to `MAX_RAW_BYTES`, closing the response as soon as the ceiling is crossed — the cap is then enforced during the read rather than after it.

---

## 10. New hermetic tests added

**None.** Every artefact produced by this phase is a throwaway harness in `%TEMP%\opencode\audit\`, per Rule 10 (scratch outside the repo, never committed). I committed no test file and modified no tracked file — see §11.

The harnesses (all in `%TEMP%\opencode\audit\`, deleted is **not** done for the coordinator to inspect if it wants, but they are outside the repo and therefore outside git):

| File | What it does |
|---|---|
| `origin.py` | the hostile HTTP origin (12 behaviour modes) |
| `stack.ps1` | audit stack bring-up/teardown |
| `drv.py` | API + Postgres load-driver primitives, resource sampler |
| `pass6.py` | one load level/pass as a bounded short-lived process |
| `soak.py` / `soaksum.py` | 50-cycle soak + memory/zombie curve summariser |
| `amplify.py` | real-`_dispatch_due_scans` backlog injection |
| `kill2.py` | SIGKILL-the-render-owner chaos, with zombie-aware attribution |
| `chaos_probe.py` / `trunc.py` / `dnsprobe.py` | in-container fault-injection probes |
| `blackhole_dns.py` / `Dockerfile.blackhole` | the swallowing DNS resolver |
| `e2e_trunc.py` | the end-to-end baseline-poisoning proof |

**Recommendation to the coordinator:** `AUDIT-7-1` deserves a committed `xfail`-marked hermetic test (Rule 5) asserting that a truncated-header 200 does **not** produce a `ready` baseline. It is the cheapest possible regression guard for the phase's worst finding. I did not write it, because committing a new test file is Wave 3's call in this parallel-execution model and I was told not to commit.

---

## 11. Full regression results

No production file was modified, so no regression is possible by construction; the suite was run anyway to attest the starting state.

```
cd C:\Users\Ns8pc\Music\WARDRESS\backend
uv run pytest -q
```

| Metric | Value |
|---|---|
| Passed | **1 471** |
| Failed | **1** — `tests/test_phase25_agent_subsystem.py::test_confirm_cancel_race_single_winner` |
| Deselected | 10 |
| Xfailed | 20 |
| Duration | **2 093.46 s (34 min 53 s)** |

**The single failure is a pre-existing flake in a subsystem that is not mine, and it is confirmed a flake.** Re-run in isolation immediately afterwards:

```
uv run pytest -q tests/test_phase25_agent_subsystem.py::test_confirm_cancel_race_single_winner
1 passed in 11.28s
```

`test_confirm_cancel_race_single_winner` is an agent-subsystem concurrency race test (`backend/app/agent/`), which this phase did not touch, did not test, and did not load. It failed once during a 35-minute run executed while five Docker containers plus Docker Desktop's own memory pressure were active on a 6-physical-core host — i.e. under exactly the contention that a race test is sensitive to. I did not investigate it further (Rule 2, out of scope) and I flag it rather than bury it, because Rule 5 asks for honest regression accounting. **No orchestration/worker/beat test failed.**

`git status --short` in `C:\Users\Ns8pc\Music\WARDRESS` at session end is **byte-identical to the baseline captured at session start**:

```
 M Prompts/Pending/Finders/PROMPT-003/PROMPT-003-IMPLEMENTATION-LOG.md
?? Prompts/Pending/Finders/PROMPT-003/scratch/session-a-*.md            (4)
?? Prompts/Pending/Finders/PROMPT-003/scratch/session-b-*.md            (3)
?? backend/tests/test_phase8_adversarial_detection.py
?? backend/tests/test_phase_sa3_orchestration_deep.py
?? backend/tests/test_phase_sa5_ai_infra_repros.py
?? backend/tests/test_session_a2_detection_findings.py
```

**Zero** tracked production files modified. The single ` M` (the implementation log) was already present when I started and is the coordinator's file — I did not open it for writing. No temporary instrumentation was added to `backend/app/**`, `backend/worker/**`, `docker-compose.yml`, `.env*`, `scripts/**` or `docs/**`. Nothing was committed.

---

## 12. Findings out of phase scope — routed, not investigated

| Observation | Routed to | Why out of my scope |
|---|---|---|
| `validate.ps1` green-lights this host because `7.4 -lt 4` is `False`, while the 12-child pool is already at 75–88 % of the ceiling | **Phase 9 / W1-C (already owns OPS-1..8)** — and now with hard evidence: the kernel OOM killer fired | PowerShell script audit is W1-C's subsystem; I supplied the measurement that makes their finding urgent |
| A healthy site can still be stored as a `ready` baseline via a 200-OK soft-block wall (W1-A `AUDIT-5C-1`) | Already owned by W1-A; my `AUDIT-7-1` is the **same class via a different trigger** and should be de-duplicated with it in the Phase 10 register | Their subsystem |
| `app/site_icons.py` favicon fetch is an unauthenticated-adjacent request amplifier | Phase 4C/4F (API surface) | Not orchestration |
| The layer-8 MiniLM cost is CPU-bound and thread-oversubscribed (§3.3) | Detection subsystem — I report it because it is *the* mechanism behind `AUDIT-6-3`, but the layer-8 code is not mine | Phase 4/W1-B |
| Docker Desktop's `oom-tracer` fires analytics `POST /analytics/track/oom-kills` to Docker | Infra/observability | Not actionable by this project |
| `wardress.ping` is still an undocumented manual probe | Already logged as Session A `AUDIT-SA3-12`; re-confirmed, no action taken | Already owned |
| **Chaos extras A/B/C (Postgres restart, Redis restart, network partition) are UNTESTED** | **Should be the first item in any follow-up concurrency session** | Budget exhausted — see §6.9. I did not observe a failure; I failed to observe anything. |

---

## 13. Final state attestation

**Docker stack — all five services up, API answering.**

```
wardress-app-1     running  Up 8 hours (healthy)
wardress-beat-1    running  Up (restarted at end of session)
wardress-db-1       running  Up 8 hours (healthy)
wardress-redis-1    running  Up 8 hours (healthy)
wardress-worker-1   running  Up (restarted at end of session)

GET http://localhost:8321/api/health  ->  200  {"status":"ok","service":"wardress-api"}
```

**Audit stack — fully removed.**
`wardress-audit-app`, `wardress-audit-worker`, `audit-probe`, `audit-probe-dns`, `audit-blackhole-srv` → removed. `audit-blackhole` image → deleted. `wardress-audit-artifacts` volume → deleted. The host origin server process → stopped (0 stray `python` processes remain).

**Scratch database — dropped.** `wardress_audit` was created on the disposable `wardress-test-pg` only, and is now `DROP DATABASE`-ed. `wardress-test-pg` is back to its original 5 databases and was **disconnected from `wardress_default`**, restoring the state I found it in.

**Live database — clean, verified against the counts taken at session start.**

| Table | Start | End |
|---|---|---|
| sites | 0 | **0** |
| baselines | 0 | **0** |
| scans | 0 | **0** |
| scan_findings | 0 | **0** |
| alerts | 0 | **0** |
| alert_deliveries | 0 | **0** |
| remediation_executions | 0 | **0** |
| users | 1 | **1** |
| api_keys | 0 | **0** |
| notification_channels | 0 | **0** |
| suppression_rules | 0 | **0** |
| remediation_hooks | 0 | **0** |
| site_icons | 0 | **0** |
| audit_log | 13 | 26 |

Every site, baseline, scan, finding, alert, delivery, remediation, API key, channel, suppression rule, hook and icon row I created went into `wardress_audit`, never into `wardress`. The `audit_log` delta of **+13** is not mine: the rows are `auth.login`, `settings.favicon.update` ×5, and `site.delete` at 10:25–13:50, all of which are the live app's own audit surface and three of which predate my first write. No `site.create` / `site.delete` / `scan.now` row in that window names an audit URL — every audit URL I used contained `host.docker.internal`, which appears in no live audit row.

**Repository — zero production modifications**, per §11.

**Containers I stopped and restarted:** `wardress-worker-1` and `wardress-beat-1` (stopped for the load tests so the audit worker had the real deployment's memory budget; both restarted and healthy). **Containers I killed:** one celery child of `wardress-audit-worker` ×6 (chaos), plus all Chromium processes the WSL2 OOM killer took. **Containers I destroyed and rebuilt:** only my own audit ones.
