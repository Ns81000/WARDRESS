# PROMPT-003 — Session A / Subagent 3 — Orchestration & Scheduling Deep Verification

**Subsystem:** Audit Phase 2B inventory bucket 2 (orchestration, data & scheduling) + Phase 4B fresh-eyes re-verification
**Session date:** 2026-09-30
**Working dir:** `C:\Users\Ns8pc\Music\WARDRESS`

**Rule 1 attestation:** No production file was modified. The only repository change is one NEW hermetic test file (`backend/tests/test_phase_sa3_orchestration_deep.py`). No `git add` / `git commit` / reformat was performed. All probes live in `C:\Users\Ns8pc\AppData\Local\Temp\opencode\wardress-session-a\orchestration\`.

**Live-stack etiquette:** the shared stack (`wardress-app-1`, `-worker-1`, `-beat-1`, `-db-1`, `-redis-1`) was inspected **read-only** only (`docker logs`, `docker stats --no-stream`, `docker exec … celery inspect …`, SQL SELECTs, `docker cp`). No container was killed, stopped, restarted, or composed. Phase 4B's SIGKILL experiment was **not** repeated. One **throwaway** container (`wardress-probe-redis`, redis:8-alpine on host port 6399) was created solely to make the broker-failure path measurable from the Windows host (the shared Redis is not host-reachable); it was removed at the end and the shared stack was verified still up. One throwaway memory-probe container (`wardress-sa3-memprobe`, `--rm`) ran the per-child footprint measurement from the same `wardress-worker` image.

---

## 0. Method summary and environment attestation

| Item | Value |
|---|---|
| Dedicated test database | `wardress_sa_orch_test` on `wardress-test-pg` `127.0.0.1:5433` (created by this session; `DROP … WITH (FORCE)` + `CREATE` used to reset) |
| Live DB | `wardress-db-1` — **0 sites, 0 scans, 0 baselines, 0 alerts** (a fresh install), so no historical scan-duration data existed |
| HEAD | `701552e`, working tree clean at session start (verified `git status --porcelain` → 0 lines) |
| Worker pool | prefork, `max-concurrency: 12`, `max-tasks-per-child: N/A` (live `celery inspect stats`); `os.cpu_count()=12` in-container |
| Docker VM memory ceiling | 7.429 GiB (from `docker stats` denominator); host total 15.34 GiB, 4.67 GiB free at probe time |
| Beat tick interval (live) | **mean 64.18 s, min 60.0 s, max 66.1 s** over 17 ticks (not the nominal 60 s) |
| Postgres `max_connections` | 100 (7 in use at rest) |
| Redis | `appendonly: no`, `save "3600 1 300 100 60 10000"`, `maxmemory: 0` (unlimited), `maxmemory-policy: noeviction`, `mem_fragmentation_ratio 10.79`, `used_memory 2.00 MiB`, `used_memory_peak 2.03 MiB` |

Every number in this report is either a **measurement** (labelled, with pass count and variance) or a **code-trace** (with file:line). Nothing is asserted from a docstring or an existing test.

---

## 1. Findings

### [DEEPENED] AUDIT-4B-1 — Lost alerts on worker death: the unrecoverable window is 10 ms, not "sub-second", and it also fires on a DB blip
- **Original phase:** Audit Phase 4B (High). Re-confirmed still open by Phase 4D.
- **Severity:** High — unchanged from 4B and justified on the same grounds: detection→notification is the system's core output; the loss is silent (no row, no log at error level, no retry, no recovery primitive), and the trigger is not limited to a worker kill (a DB error at the same seam produces the identical permanent loss, now measured below).
- **Subsystem / file(s):** `backend/worker/scan_tasks.py:351` (scan terminal `db.commit()`), `:353-357` (`if flagged:` → `await _create_alert(db, scan)`), `:371-387` (`_create_alert`: `:378` SELECT, `:382` `db.commit()`, `:385` `send_task`, `:386-387` `except Exception` → `logger.exception` only), `:390-404` (`_create_remediations`), `:485-491` (`run_scan` wrapper). Recovery primitive: `backend/worker/beat_tasks.py:327-376` (`_resweep_undelivered`, zero-delivery-rows predicate `:340-350`).
- **Verification method:** (a) hermetic test, (b) **measurement** with 5 passes against real Postgres, (c) DB-unreachable trace probe with a broken connection, (d) scratch DB-blip blast-radius arithmetic.
- **Evidence:**
  - Test: `backend/tests/test_phase_sa3_orchestration_deep.py::test_4b1_unrecoverable_alert_window_is_measured_and_bounded` — **PASSING**. Drives the real `_create_alert` 5× against a live Postgres and times the handoff:
    ```
    4B-1 window (SELECT + INSERT/COMMIT + redis publish), ms:
    [8.67, 8.72, 9.27, 10.1, 14.44] | steady median 10.10 ms | first-call 8.67 ms
    ```
  - Component breakdown (5 passes, separate run): `SELECT Alert` median **3.86 ms** (min 3.51, max 9.58, σ 2.34); `INSERT Alert`+`COMMIT` median **6.99 ms** (min 6.16, max 17.22, σ 4.19); Redis publish median **1.86 ms** steady (first publish in a fresh process 213.9 ms — result-backend connection setup). Reference `SELECT 1` = 0.96 ms median.
  - **The unrecoverable span is the SELECT + INSERT/COMMIT = 10.85 ms median, 26.80 ms max.** The Redis publish is *outside* it: the Alert row is already committed when `send_task` runs, so `resweep_undelivered` can recover that part.
  - DB-unreachable trace (`probe_db_unreachable.py` SEAM 1), real `DbDown` raised on the create commit:
    ```
    Could not create/enqueue alert for scan f6c76bcd-...
    SEAM 1: alert rows after the DB died at the create commit: 0
      resweep_undelivered -> {'alerts_reenqueued': 0, 'remediations_reenqueued': 0}
    ```
  - Blast-radius arithmetic (scratch): loss probability per flagged scan = P(worker death **or** DB error in an 11 ms span). For a 200-site fleet at 24 h cadence with a 1 % flag rate (2 flagged scans/day) and a cumulative 10 s/day of DB unavailability, expected lost alerts = 2 × (10/86 400) ≈ **0.00023/day** — negligible under normal load. The exposure concentrates in **correlated** events: a mass compromise flagging 200 sites inside 60 s turns a 1 s DB blip into ~3 lost alerts, and a worker restart during a flag storm loses every alert whose terminal commit lands in the restart's 11 ms × N gap.
- **Deeper analysis:** 4B called the window "small (sub-second typically)" without measuring it. Measured, it is **~10 ms** — two orders of magnitude narrower. That *lowers* the per-scan probability (good news 4B did not have) but does not close the gap, and it reveals the more important point 4B stated but did not quantify: **the DB-hiccup variant is unbounded.** During a 5-second database stall every flagged scan whose terminal commit lands in the stall loses its alert with probability 1, because the same `except Exception` swallows the DB error exactly as it swallows a worker death. The window does not scale down with DB health; it becomes the full stall duration. 4B's remedy (fold Alert creation into the scan's terminal transaction, or extend the resweep to create missing rows) is unchanged and remains unimplemented.
- **Cross-subsystem interactions:** Detection (a flagged scan is the only trigger); Delivery (the operator is never paged — invisible to `alerts`, `alert_deliveries`, and the health page); API/frontend (`site-detail.tsx` shows a `flagged` scan with no `alerts` row — the operator sees the flag and no notification, with no indication the notification was lost); Remediation (`_create_remediations` at `:362` is a *separate* transaction after `_create_alert`, so a crash in the same window also orphans the executions — but those ARE recoverable, since the `RemediationExecution` rows are committed before their publish and `resweep_undelivered:358-375` re-enqueues `queued` rows).

---

### [DEEPENED] AUDIT-4B-2 — Overload amplification: the trigger threshold is a backlog of ~60 pending scans, and one over-capacity tick is enough to create it
- **Original phase:** Audit Phase 4B (Medium). 4B correctly declined to soak the shared stack and labelled the extrapolation as such.
- **Severity:** Medium — unchanged. The mode requires sustained overload (demand > supply) to enter, and once entered it is self-sustaining rather than merely noisy; there is no backpressure anywhere on the path, and each entry produces 50 permanently-failed history rows per minute plus one no-op broker message each.
- **Subsystem / file(s):** `backend/app/scanning.py:14` (`STALE_INFLIGHT = 10 min`), `:17-28` (`is_stale` — anchor is `created_at` for a **pending** row, `started_at` for a running one); `backend/worker/beat_tasks.py:183-200` (in-flight check, `is_stale` at `:191`, supersede at `:192-196`, skip at `:198-200`), `:49` (`MAX_DISPATCH_PER_TICK = 50`), `:46` (`DISPATCH_TICK_SECONDS = 60`).
- **Verification method:** 30-day fleet simulation (analytic + code-trace against the real `is_stale`/`next_interval_after_scan`), plus 4B's committed hermetic repro re-executed green, plus a direct measurement of the tick's cost curve.
- **Evidence:**
  - 4B's repro re-ran green: `test_phase4b_orchestration_repros.py::test_backlogged_pending_scan_superseded_by_dispatch_tick`.
  - Measured tick cost vs due sites (3 passes each, real Postgres, `send_task` stubbed): `n=0` 73.8 ms, `n=10` 457.8 ms, `n=50` **1 378.6 ms** (min 1 340, max 1 506), `n=100/200/500` all ≈ 1 300 ms (capped at 50). Per claimed site ≈ **26 ms** (7 sequential DB round trips).
  - **Supply/demand arithmetic (the numbers 4B did not give).** Supply = `concurrency × 86400 / scan_wall_clock`:

    | scan wall clock | supply (scans/day) |
    |---|---|
    | 60 s (fast site) | 17 280 |
    | 120 s (typical) | 8 640 |
    | 480 s (the hard time limit — worst case) | **2 160** |

    Demand = `fleet × 1440 / interval`:

    | configuration | demand (scans/day) |
    |---|---|
    | 200 sites @ 24 h | 200 (0.9 % of the 60 s supply) |
    | 200 sites @ 6 h (base/4 — what AUDIT-4B-3 pins them at) | 800 |
    | 500 sites @ 6 h | 2 000 = **93 % of the worst-case supply** |
    | 500 sites @ 60 min | 12 000 = **5.6× the worst-case supply** |
    | **7–8 sites @ the 5-min `MIN_INTERVAL_MINUTES`** | 2 016 ≈ worst-case supply |

  - **Saturation point: ~2 160 sites at base cadence, ~500 sites at base/4, or just 7–8 sites if they all tighten to the 5-minute floor.** Any one of these saturates the pool when scans run long.
  - **Amplification entry threshold (the sharp new number).** The sweep starts superseding once a PENDING row's `created_at` is older than 10 min, i.e. once the queue wait exceeds 10 minutes. Backlog threshold = `supply_per_minute × 10` = `(12 × 60 / S) × 10`:
    - S = 480 s → **15 pending scans**
    - S = 120 s → **60 pending scans**
    - S = 60 s → 120 pending scans

    A single tick can enqueue 50. **One over-capacity tick therefore creates a backlog the very next tick converts into 50 failed "superseded" rows plus 50 no-op broker messages** — and the no-op messages themselves occupy worker slots, extending the wait that sustains the condition. Self-sustaining after one tick of overshoot.
  - 30-day simulation state at every configuration tested (fleet 50–2000, scan 8–20 min, all sites at the 5-min floor): `state = AMPLIFY` in all cases, `failed(super) = 50` per tick, `wasted msgs = 1 200/day`.
- **Deeper analysis:** 4B described the cascade qualitatively ("each tick replaces stale pending rows with fresh messages while the old messages stay queued"). What was missing is the **entry condition**, and it is far closer than 4B implied: 15–60 pending rows, i.e. one to two ticks of overshoot, not a sustained overload. The critical structural point is that the dispatcher's *own* output (up to 50 enqueues/tick) is enough to cross the threshold. The remedy 4B proposed (gate dispatch on broker depth via the already-existing `_queue_depth` primitive) is correct and now has a number attached: gating at `queue_depth > workers × K` with K ≈ 1 scan-duration would keep the backlog below the 10-minute staleness window. The alternative 4B also named — anchoring pending-staleness to due-time rather than a fixed 10 min — is strictly worse, because a backlogged site would then never be recovered at all.
- **Cross-subsystem interactions:** Detection (a superseded scan produces a `failed` row with `verdict=error` and no findings, polluting the same history surface a real detection failure uses); API/frontend (`site-detail.tsx` shows the site as "scanned X ago" with `next_scan_at` advanced, so the gap is invisible; the health page's `queue_depth` field exists and is never read by scheduling); Delivery (no alerts are lost here — the scans never run).

---

### [DEEPENED] AUDIT-4B-3 — Cadence pinning: a *daily* transient pins the site for 30 days, and 0/500 sites ever return to base
- **Original phase:** Audit Phase 4B (Medium). 4B proved the alternating-transient pinning hermetically.
- **Severity:** Medium — unchanged. Chronic 4× over-scanning of exactly the flaky/noisy sites, plus the load amplification that feeds AUDIT-4B-2. No false-alert impact (the alert path is `flagged`-gated and never consumes the cadence).
- **Subsystem / file(s):** `backend/worker/scan_tasks.py:367` (`changed=flagged or risk >= MATERIAL_CHANGE_RISK`, `scan_tasks.py:59` `NOISE_FLOOR`, `:304-308` the verdict gate), `:407-420` (`_schedule_next` — **never** consults `layer_scores[*].degraded`); `backend/app/scanning.py:58` (`MATERIAL_CHANGE_RISK = 0.40`), `:65-74` (`next_interval_after_scan`), `:36` (`TIGHTEN_DIVISOR = 4`), `:37` (`RELAX_FACTOR = 1.5`).
- **Verification method:** 30-day fleet simulation over 7 transient patterns × 500 sites, driving the **real** `next_interval_after_scan`; plus 4B's committed repro re-executed green; plus a source-level proof that no de-bounce exists.
- **Evidence:**
  - 4B's repro re-ran green: `test_phase4b_orchestration_repros.py::test_repeated_material_risk_transients_hold_cadence_at_base_quarter`.
  - **30-day simulation (500 sites, base 1440 min, one scan per current interval):**

    | transient pattern | scans/30d per site | sites back at base | sites tightened | sites pinned | median final interval |
    |---|---|---|---|---|---|
    | none (all clean) | 30.0 | **500/500** | 0 | 0 | 1440 min |
    | rare (1 per 30 d) | 36.0 | **500/500** | 0 | 0 | 1440 min |
    | clustered (3 of 30 days) | 32.0 | **500/500** | 0 | 0 | 1440 min |
    | nightly (1/day) | **120.0** | **0/500** | 500 | 500 | **360 min (base/4)** |
    | nightly + 1 clean | 73.0 | **0/500** | 500 | 500 | **360 min (base/4)** |
    | every 6th scan | 44.0 | **0/500** | 500 | 500 | 810 min |
    | alternating (every scan) | 64.0 | **0/500** | 500 | 500 | 810 min |

  - **The exact recovery condition, which 4B did not state as a threshold: four consecutive clean scans.** Measured ladder from a single material scan at base 1440: `[360, 540, 810, 1215] → 1440`. At base/4 (360 min) that is **24 hours of consecutive clean scans**. A site with a *daily* transient therefore provably never recovers — which is exactly what the simulation shows (0/500).
  - **Worst-case amplification of the schedule itself:** a site pinned at base/4 for 30 days runs 120 scans instead of 30 = **4× the configured scan load on precisely the least reliable sites**, and those are the sites whose scans are slowest, so they contribute disproportionately to AUDIT-4B-2's supply deficit.
  - Source proof of the missing de-bounce: `test_phase_sa3_orchestration_deep.py::test_cadence_tighten_ignores_degraded_channels_and_has_no_floor` — **PASSING**. Asserts `inspect.getsource(scan_tasks._schedule_next)` contains no `degraded`, and that the floor itself is reachable (`next_interval_after_scan(20, None, changed=True) == MIN_INTERVAL_MINUTES == 5`), i.e. a 20-minute-base site is scanned 288×/day with no upper bound other than the floor.
- **Deeper analysis:** 4B correctly identified that `_schedule_next` ignores the per-layer `degraded` flag that sits one dict lookup away in `layer_scores`. The simulation adds the *frequency* dimension: the pinning is not caused by any single transient, it is caused by transients arriving more often than the 4-clean-scan recovery ladder can absorb, and the ladder's wall-clock length is itself a function of the tightened interval — so the tighter the site gets, the longer recovery takes, which is a positive feedback loop. The remedy 4B proposed (skip the tighten, or require N consecutive material scans, when a degraded channel is present) is the right one and now has a testable acceptance criterion: with a degraded-channel gate, the "nightly" pattern above must leave ≥ 400/500 sites at base.
- **Cross-subsystem interactions:** Capture (the sites that transient most are the ones being captured worst — so the cadence is inversely proportional to capture quality); Detection (a `changed` verdict on every scan pollutes scan history, compounding the same noise); API/frontend (an operator who sets a 24 h cadence sees scans every 6 h with no explanation); API/load (4× the scan count is 4× the DB rows, the artifact bytes, and the MiniLM CPU).

---

### [CONFIRMED] AUDIT-4B-4 — Re-baseline does not arbitrate in-flight scans
- **Original phase:** Audit Phase 4B (Low).
- **Severity:** Low — unchanged. The anchor is always traceable (`scans.baseline_id`), the promote is atomic, and the two in-flight arbiters backstop concurrent captures. The impact is bounded to confusing history.
- **Subsystem / file(s):** `backend/app/services.py:376-450` (`rebaseline_site` — 409s on in-flight **baselines** only, `is_stale(in_flight.created_at)` at `:402`, no scan-side arbitration anywhere), `backend/worker/scan_tasks.py:239-251` (`_run_scan` reads its bound baseline at task start), `:131-161` (demote-previous + promote-this in one transaction), `backend/app/models.py:433-448` (`uq_baselines_one_current_per_site`, `uq_baselines_one_inflight_per_site`).
- **Verification method:** code-trace + hermetic test.
- **Evidence:** `test_phase_sa3_orchestration_deep.py::test_stuck_pending_baseline_is_never_touched_by_any_beat_task` re-verifies the arbitration boundary from the other side (a *fresh* in-flight capture 409s; a *stale* one is reclaimed only by the explicit operator call). `test_phase18_concurrency_races.py` (8 tests) re-ran green, covering `test_concurrent_rebaselines_single_winner_single_capture` and `test_concurrent_rebaselines_stale_supersede_single_winner`.
- **Deeper analysis:** Is "accepted-risk" the right call? **Yes for the current design, and this session's evidence strengthens that answer** — because a *scan-side* arbitration rule would have to kill a running scan, and the asymmetry is now measurable: a rebaseline takes one capture (~30–60 s typical) while a scan takes fetch + probe + 9 layers (~60–480 s), so a rebaseline that 409'd on an in-flight scan would block the operator for up to 8 minutes. The honest resolution is not arbitration but **labeling**: the scan row records `baseline_id`, so the data is honest, but nothing surfaces that the anchor was replaced mid-flight. That is exactly 4B's "contract choice" remedy, and it remains the cheapest correct answer. The genuinely new observation is in AUDIT-SA3-9: `rebaseline_site` accepts a `via` that it then discards, so the audit row for the anchor replacement records no surface and no tie to the superseded scan.
- **Cross-subsystem interactions:** Detection (a verdict computed against a demoted anchor is internally consistent but no longer comparable to later verdicts); API/frontend (site detail shows the new baseline with no marker on the in-flight scan); Delivery (unchanged).

---

### [DEEPENED] AUDIT-4B-5 — Stale-row recovery: recovery latency is the interval, and baselines have **no** beat-side stale sweep at all
- **Original phase:** Audit Phase 4B (Low), with a residue note that stuck baselines have no sweep.
- **Severity:** Low for the scan-side half (unchanged, no work is lost). **Medium for the baseline half** — escalated from 4B's parenthetical, because this session measured the concrete consequence: a site whose baseline-capture enqueue is lost is **permanently inert**, and the beat tick reports it as a benign `skipped_no_baseline` forever with no error, no counter, and no operator signal.
- **Subsystem / file(s):** `backend/worker/beat_tasks.py:183-200` (the stale check is inside the **per-site due path only** — a non-due site is never examined), `:171-181` (`skipped_no_baseline` `continue`s *after* the claim commit at `:168`); `backend/app/scanning.py:14,17-28`; `backend/app/services.py:395-418` (`rebaseline_site` — the *only* reader of a stuck baseline, and it requires an operator action).
- **Verification method:** hermetic tests + code-trace + measurement.
- **Evidence:**
  - **Scan-side, re-confirmed and quantified.** Recovery fires only when the site is next due, so a 24 h-interval site's killed scan sits "running" for up to 24 h. Worst case = `scan_interval_minutes` (up to `MAX_INTERVAL_MINUTES` = 1440) **plus** `STALE_INFLIGHT` = 10 min, i.e. **up to 1 450 min = 24 h 10 min** before the row is even *examined*, then 10 more minutes before the supersede branch fires (the supersede needs the row to be both due *and* stale). Total worst case ≈ **24 h 20 min**. 4B said "up to a full interval"; the true figure is interval + 2×STALE_INFLIGHT.
  - **Baseline-side, proven for the first time.** `test_stuck_pending_baseline_is_never_touched_by_any_beat_task` — **PASSING**: 30-minute-old `pending` and `capturing` baselines (on separate sites, since the in-flight arbiter correctly forbids two on one) are run through `_dispatch_due_scans()`, `_resweep_undelivered()`, `_cleanup_orphan_artifacts()` and `expire_stale()`; all four leave them **unchanged with `error is None`**. Nothing in the system writes a recovery note. The only recovery is `rebaseline_site` — a human click.
  - **New: the `skipped_no_baseline` skip also burns a full interval.** `test_no_baseline_skip_advances_the_schedule_so_a_late_baseline_waits_an_interval` — **PASSING**: a due site with no ready baseline reports `skipped_no_baseline: 1`, has `next_scan_at` advanced by the full 1 440 minutes, and adding a ready baseline immediately afterwards does **not** dispatch (the next tick reports `due: 0`).
  - **The inert-site chain, now fully specified.** `services.create_site:257-278` sets `next_scan_at = now + interval` and creates a `pending` baseline; if that enqueue is lost, nothing ever runs the capture. The site's `is_current` baseline does not exist, so `trigger_scan_now:302-304` 409s forever ("no ready baseline yet"), the beat tick reports `skipped_no_baseline` forever, and only a re-baseline click recovers it. The site is in the sites list, active, auto-scan enabled, and completely non-functional.
- **Deeper analysis:** 4B correctly stated the mechanism for scans. Two things it did not cover: (1) the **double-STALE_INFLIGHT** addition to the recovery latency (the row must be due *and* stale, and the due time was already pushed a full interval forward by the claim that preceded the death); (2) the **baseline gap is categorically different from the scan gap** — the scan gap delays work that would have happened anyway, whereas the baseline gap blocks a site that never had a trust anchor at all, and unlike the scan case there is no "next interval" fallback because there is nothing to compare against. The fix 4B named (an independent low-frequency stale sweep covering non-due sites *and* baselines) is correct and should also cover the `skipped_no_baseline` case by re-dueing the site on a short retry cadence rather than a full interval.
- **Cross-subsystem interactions:** Capture (a lost baseline enqueue means the site is never captured again — its trust anchor never exists); Detection (no baseline ⇒ no scans ⇒ no detection at all for that site, silently); API/frontend (the site renders as a normal active site; the operator must notice that nothing ever happens to it); Delivery (no alerts, because nothing is ever scanned).

---

### [DEEPENED] AUDIT-4B-6 — The heartbeat measures tick execution: it is skipped on **any** dispatcher error, and every periodic task's `expires` equals its own interval
- **Original phase:** Audit Phase 4B (Low).
- **Severity:** Medium — escalated from 4B's Low, on one specific new mechanism: the heartbeat is skipped not only under worker saturation (4B's scenario) but on **any** dispatcher failure, including a plain database outage, which is both common and entirely outside the "worker is busy" story the code comment tells. An operator's only scheduling signal goes red during a DB blip even though beat is publishing perfectly and the worker is idle. The harm is a false "Beat stalled" on the health page, so it is not Critical; but it is a *measurement* failure on the single page an operator uses to decide whether monitoring is alive, which is more than cosmetic.
- **Subsystem / file(s):** `backend/worker/beat_tasks.py:225-237` (`dispatch_due_scans`: `:228` `asyncio.run(_dispatch_due_scans())`, `:231` `_write_heartbeat()` **on the success path only**, `:233-237` `except Exception` → `logger.exception` + `return {"error": True}` with **no** heartbeat); `:85-103` (`_write_heartbeat`, best-effort, `socket_connect_timeout=2`); `:414-447` (`setup_periodic_tasks`, the five `expires=` values); `backend/app/routers/health.py:43` (`_BEAT_STALE = 5 min`), `:123-134` (`_dispatch_heartbeat`).
- **Verification method:** hermetic test + code-trace against Celery's own drop site + live measurement of the tick interval.
- **Evidence:**
  - **New mechanism proven:** `test_dispatch_heartbeat_is_skipped_whenever_the_tick_body_raises` — **PASSING**. With `_dispatch_due_scans` raising `RuntimeError("could not connect to server")`, `dispatch_due_scans()` returns `{"error": True}` and `_write_heartbeat` is called **zero** times; the positive control (a healthy tick) writes it exactly once.
  - **`expires` accounting — all five periodic tasks.** Celery treats `expires` as an absolute age from send time and drops the message past it at `celery/worker/strategy.py:162` (`if (req.expires or req.id in revoked_tasks) and req.revoked(): return` — a **bare return, no log line at any level**), decided by `Request.maybe_expire` (`if now > self.expires`).

    | task | interval | `expires` | headroom |
    |---|---|---|---|
    | `dispatch_due_scans` | 60 s | **120 s** | 2× |
    | `resweep_undelivered` | 300 s | **300 s** | **1×** |
    | `expire_agent_actions` | 300 s | **300 s** | **1×** |
    | `cleanup_orphan_artifacts` | 86 400 s | **86 400 s** | **1×** |
    | `sync_model_catalog` | 43 200 s | **43 200 s** | **1×** |

    Four of five have **zero** margin: a tick delayed past exactly one interval is discarded rather than run late, silently. `test_every_periodic_task_expires_exactly_at_its_own_interval` — **PASSING** — pins this and asserts against Celery's own source that the drop is silent.
  - **Live tick interval, measured (the drift 4B did not quantify):** 17 consecutive beat "Sending due task" events → intervals `65.1, 64.6, 64.5, 60.0, 64.3, 64.3, 64.4, 65.6, 60.7, 64.5, 63.8, 66.1, 65.1, 62.9, 65.5, 65.5` → **mean 64.18 s, min 60.0, max 66.1** — a **+7 % drift** on the nominal 60 s, so the dispatch tick's real headroom is 120/64.18 = **1.87×**, not 2×.
  - **The real saturation threshold:** a tick queued behind even **one** full-length scan (up to the 480 s hard limit) is 3× past `expires=120` and is dropped. So under full worker saturation the dispatcher does not delay — it **stops**, with no log line.
  - **Support: the heartbeat TTL is not the binding constraint.** `HEARTBEAT_TTL_SECONDS = 600` vs `_BEAT_STALE = 300 s` (`test_heartbeat_ttl_exceeds_the_health_pages_stale_threshold` — PASSING). The write *frequency* is the constraint.
  - **The only correctly-bounded broker call in the codebase is the heartbeat writer** (`socket_connect_timeout=2` + swallow). That inconsistency is itself the finding — see AUDIT-SA3-4.
- **Deeper analysis:** 4B's remedy (have the beat *process* write its own liveness key, report tick lag separately, count expired ticks) is right and is now backed by two additional requirements this session found: (a) the success-path-only heartbeat write must also write on the error path with a *different* signal, otherwise a DB outage and a dead beat are indistinguishable; (b) the expired-tick counter does not just need to exist, it needs to be **surfaced**, because the drop is invisible at every level. The `expires == interval` coupling is a separate defect from the heartbeat semantics and deserves its own remedy: either `expires = 2 × interval` (matching the dispatcher's choice) or, better, `expires = None` with idempotent tasks — every periodic task in this system is already idempotent by design, so the drop policy buys nothing.
- **Cross-subsystem interactions:** API/frontend (the health page's Beat indicator; `health.tsx` renders it); Detection (a dropped dispatch tick means the site is not scanned at all for that interval); Delivery (a dropped `resweep_undelivered` tick means a stranded alert waits another 5 min — harmless; a dropped dispatch tick is not).

---

### [DEEPENED] AUDIT-4B-7 — Worker memory: re-measured, and the warm footprint is a **non-reclaimable** 624.5 MB per child
- **Original phase:** Audit Phase 4B (Low), which measured 2 concurrent scans and labelled the 12-child extrapolation as unsoaked.
- **Severity:** Low — unchanged, and the honest extrapolation now lands at ~79 % of the VM ceiling rather than "past" it. An OOM-killed child is recovered by design (WorkerLostError → stuck `running` row → the 10-minute stale sweep), so the blast radius is lost work plus failed-scan noise, not a hang. It is not Medium because nothing is unbounded (a killed child is replaced) and the OOM path is recoverable.
- **Subsystem / file(s):** `backend/Dockerfile.worker:36` (CMD `celery -A worker.celery_app worker --loglevel=info` — **no `-c`, no `--max-tasks-per-child`**, so concurrency defaults to the container's CPU count); `backend/docker-compose.yml:89-116` (worker service: **no `healthcheck`**, no `deploy.resources.limits`); live cgroup `memory.max = "max"` (unlimited).
- **Verification method:** **measurement** (live `docker stats` + `docker exec ps` for the cold pool; a throwaway container from the same image for the warm incremental footprint), 3+ passes.
- **Evidence:**
  - **Cold 12-child pool, live:** `docker stats` → `wardress-worker-1  1.308 GiB / 7.429 GiB (17.60 %)`; cgroup `memory.current = 1 413 013 504` (1.32 GiB). `ps -eo pid,rss,comm`: parent 266 404 KiB, children 218 592–250 096 KiB each (12 children, pids 8–19, matching `max-concurrency: 12`). Host total 15.34 GiB, 4.67 GiB free.
  - **Warm incremental footprint, measured** (`docker run --rm` on the same image, RSS from `/proc/self/statm`):

    | step | RSS | delta |
    |---|---|---|
    | R0 bare interpreter | 9.1 MB | — |
    | R1 + `worker.celery_app` | 30.6 MB | +21.5 |
    | R2 + `worker.scan_tasks` (pulls the whole detection stack incl. torch) | 234.6 MB | +204.0 |
    | R3 + MiniLM loaded | 624.5 MB | +389.9 |
    | R4 + one `encode()` (first torch kernels) | **676.9 MB** (high-water) | +52.4 |
    | R5 after `del model` + `gc.collect()` | **624.7 MB** | −0.2 |

    - **MiniLM marginal cost: 30.9 MB to load, but 389.9 MB to bring the process to R3** (torch's allocator arenas + tokenizer + the module graph). Peak 676.9 MB.
    - **The new and important fact: 624.7 MB is a non-reclaimable floor.** Freeing the model returns 0.2 MB, not 389.9 MB.
  - **Honest extrapolation (stated as extrapolation, per Rule 12).** Children are forked, so the parent's ~235 MB is copy-on-write shared and the cgroup counts shared pages once — which is exactly why the live 12-child pool is 1.32 GiB and not 12 × 624.5 MB. The *marginal* private cost of warming one child is therefore ≈ 624.5 − 234.6 = **390 MB**:
    - 12 fully warm children ≈ 1.32 GiB + 12 × 390 MB ≈ **5.90 GiB** against a **7.429 GiB** ceiling → **~79 % utilisation, ~1.5 GiB headroom** for Postgres, Redis, the app, beat and Docker overhead.
    - The naive upper bound (RSS sum) is 7.32 GiB, i.e. *at* the ceiling — 4B's "can plausibly OOM-spiral" is confirmed but the realistic figure is tight rather than fatal.
    - **4B's own 2-scan measurement gives a lower marginal cost (0.25 GiB/child) than the isolated-process figure (0.39 GiB/child)**; 4B's number is the more trustworthy one for the real prefork topology because a forked child inherits torch's already-allocated arenas. Both are reported.
  - **Consequence for 4B's proposed remedy.** `--max-tasks-per-child` would **not** help: a recycled child re-imports and re-loads the model and lands back on the same 624.7 MB floor (R5 proves the memory is not returned by GC, so a recycle re-acquires it). The only effective lever is pinning `-c`.
  - **New compose-level fact:** the worker has **no `healthcheck`** (only `db`, `redis`, `app` do — `docker-compose.yml:17,28,82`), and no memory limit, so a worker that is OOM-looping looks perfectly healthy to Docker and to `docker compose ps`.
- **Deeper analysis:** 4B's structural claim — default concurrency uncoupled from a memory budget — is confirmed and now has a number. The additional finding is that 4B's own suggested remedy (`--max-tasks-per-child`) is measurably ineffective against this specific memory profile, which is worth recording so the remediation prompt does not reach for it. The genuinely new operational fact is the absent healthcheck: the failure mode 4B describes (OOM-spiral) is the one failure the stack currently cannot observe at all.
- **Cross-subsystem interactions:** Capture (each child holds a Playwright browser process for the duration of a scan — a third consumer of the same budget, unmeasured here); Detection (MiniLM is layers 8/9's second opinion — pinning `-c` trades detection throughput for memory); API/frontend (the health page's worker signal comes from the DB heartbeat, not from Docker's view, so an OOM-looping worker still reports "beat recent"); Delivery (alerts enqueued by a dead worker's scan sit in Redis until the stale sweep).

---

### [INVALIDATED] AUDIT-4B-8 — Deployment drift: **resolved**. The running stack is byte-identical to HEAD on all 20 audited files
- **Original phase:** Audit Phase 4B (Low). Phase 4F recorded that the user rebuilt from HEAD.
- **Severity:** n/a — the finding's premise no longer holds. The residual half (the beat schedule file lives in the container FS, not on a volume) survives as a **Low** operational note and is restated below.
- **Subsystem / file(s):** deployed `wardress-worker-1:/app/**` vs `HEAD:backend/**`; `backend/docker-compose.yml:118-131` (beat service has **no volume mount** — `docker inspect` confirms `"Mounts": []`).
- **Verification method:** `docker cp` + `git hash-object` on both sides, CRLF-normalised so a line-ending difference cannot produce a false DIFF.
- **Evidence:** full parity table in **§3** below. **20/20 MATCH**, including the two files 4B reported as DIFFERING: `worker/scan_tasks.py` is now `a6878b37…` in the container — byte-identical to the HEAD value 4B itself recorded — and `app/scanning.py` is `fa3f5898…` on both sides. `git rev-parse --short HEAD` = `701552e`; `git status --porcelain` = 0 lines.
- **Deeper analysis:** This is a clean INVALIDATION and it materially changes the evidentiary basis of the whole 4B finding set: 4B had to caveat every live probe with "the deployed `scan_tasks.py` predates Phase 11". **That caveat no longer applies** — every 4B finding is now attested against the code it describes, with no mixed-build discount. Two consequences for the remediation prompt: (a) the "rebuild from HEAD before remediation-phase verification" hard requirement in 4B's remedy is **already satisfied** and can be dropped; (b) a **build-commit marker is still absent** — nothing records which commit an image was built from, which is how the drift went undetected in the first place; that half of 4B's remedy stands. The schedule-file half is re-confirmed: `/app/celerybeat-schedule.db` (12 288 bytes, `PersistentScheduler`) lives in the beat container's writable layer with no volume, so it is lost on container recreate — benign by construction, since every periodic task is idempotent, but undocumented.
- **Cross-subsystem interactions:** n/a (this finding is about the deployment pipeline, not the dataflow).

---

### [NEW] AUDIT-SA3-1 — The dispatcher's schedule claim is never released: a single broker blip converts into a silent one-interval scan gap
- **Severity:** High — per §6.4, "a resource leak or unbounded growth under sustained/concurrent load" is High, and this is the mechanism by which a transient infrastructure fault (a broker blip, a DNS wobble, a Redis restart) causes **permanently lost monitoring coverage for a whole interval** with no operator-visible trace. Not Critical: no corruption, no false clean, and the site is scanned at the next interval; the in-flight unique index guarantees the replacement scan, when it comes, is the only one.
- **Subsystem / file(s):** `backend/worker/beat_tasks.py:160-168` (the claim: conditional `UPDATE ... WHERE next_scan_at == seen` then `await db.commit()` — **committed before any scan row exists**), `:202-204` (the Scan `INSERT` + commit), `:207-213` (the publish, wrapped in a bare `except Exception` that only logs), `:214-221` (the per-site `except Exception` → `rollback()` + `logger.exception`, which does **not** restore the claim).
- **Verification method:** hermetic test + DB-unreachable trace probe.
- **Evidence:**
  - `test_dispatch_claim_survives_a_failed_enqueue_and_silently_skips_the_site` — **PASSING**. With `celery_app.send_task` raising, the tick returns `{'due': 1, 'enqueued': 0, 'skipped_inflight': 0, 'skipped_no_baseline': 0, 'recovered_stale': 0, 'lost_claim': 0}`. The test asserts the *complete* stats key set contains **no** error / fail / lost-publish bucket. The Scan row survives as `pending` with no message anywhere.
  - `test_pending_row_from_a_lost_publish_only_recovers_after_a_full_interval` — **PASSING**. The orphan's `next_scan_at` is 1 430+ minutes out; the orphan is not yet stale; only when the site becomes due again **and** the row has aged past `STALE_INFLIGHT` does the supersede fire (`recovered_stale: 1`, `enqueued: 1`, old row → `failed` / "superseded").
  - DB-unreachable trace (SEAM 4), real broken connection on the second commit of the tick:
    ```
    SEAM 4: tick stats -> {'due': 1, 'enqueued': 0, 'skipped_inflight': 0,
                           'skipped_no_baseline': 0, 'recovered_stale': 0, 'lost_claim': 0}
      messages published: 0
      scan rows created: 0;  next_scan_at advanced by the claim: True
    ```
- **Deeper analysis:** 4B's "advance-before-enqueue" was verified live and recorded as *verified-clean*. This session shows the other side of the same design decision: **the claim is a schedule mutation, not an intent log.** There is no rollback, no "un-claim", and no way for any later process to distinguish "this site was claimed and successfully enqueued" from "this site was claimed and then the publish died". The advance-before-enqueue ordering is still correct for its stated purpose (a lost enqueue must delay, never duplicate) — but it makes *every* post-claim failure a silent gap, and the recovery is one full interval. The fix is small and local: the publish failure path should mark the freshly-inserted `pending` row `failed` with an explicit "enqueue failed" reason (it is provably never going to run, since the message was never created), which converts the one-interval silent gap into a same-tick visible failure and lets the *next* tick dispatch normally. A `lost_publish` stat counter is the minimum viable version.
- **Cross-subsystem interactions:** Detection (the site is unmonitored for the interval — a coverage gap in the system's core promise); API/frontend (the site's last-scan timestamp simply stops advancing; nothing is flagged); API (a concurrent `scan-now` during the gap hits the in-flight index and 409s against a `pending` row that will never run — the API's own stale-recovery at `services.py:314-338` rescues it after 10 min, so scan-now is *self-healing* while beat dispatch is not, an inconsistency between the two paths); Delivery (n/a).

---

### [NEW] AUDIT-SA3-2 — No retention policy exists for scans, scan findings, artifacts, alerts, deliveries, remediation executions, or the audit log
- **Severity:** High — per §6.4, "a resource leak or unbounded growth under sustained/concurrent load" is High. This is monotonic growth of both the database and a mounted volume, on a self-hosted product whose entire operational premise is running unattended for months.
- **Subsystem / file(s):** absence of a deletion path. Repo-wide grep over `backend/app/**`, `backend/worker/**`, `backend/alembic/**`, `backend/tools/**` for `retention|prune|purge|delete(Scan)|older_than|max_scans|keep_last|TRUNCATE` returns **zero** hits in any orchestration module. The only artifact deleter is `backend/worker/beat_tasks.py:240-291` (`_cleanup_orphan_artifacts`), which removes a tree **only when its owning row is gone** (`:271-277`), and `backend/app/models.py:582-612` (`AuditLog`) whose docstring states immutability by design.
- **Verification method:** repo-wide grep + hermetic test + arithmetic projection.
- **Evidence:**
  - `test_no_retention_policy_exists_for_scans_findings_or_artifacts` — **PASSING**. It asserts, by source inspection of `beat_tasks`, `alert_tasks` and `remediation_tasks`, that no module contains `delete(Scan)` or the string `ScanFinding`, then prints the projection (test output):
    ```
    200 sites @ 1440 min -> 200 scans/day, 1800 scan_findings/day, 0 removed
    500 sites @ 1440 min -> 500 scans/day, 4500 scan_findings/day, 0 removed
    500 sites @   60 min -> 12000 scans/day, 108000 scan_findings/day, 0 removed
    ```
  - The growth is not just row counts. Each scan stores `layer_scores` (9 keys) + `capture_evidence` JSONB on the row **and** writes an artifact tree (`worker/artifacts.py:14-25`: `page.html` up to `MAX_HTML_BYTES` plus a full-page `screenshot.png` up to `MAX_SCREENSHOT_HEIGHT` = 16 384 px). Nothing deletes either. The 500-sites-at-60-min case is 12 000 scans/day ≈ **9.6 GB/day** of artifacts at an 800 KB/scan estimate, against a Docker named volume with no quota.
  - Live table sizes today are tiny (the install is fresh: `model_catalog` 8 323 rows / 1 992 kB is the only non-trivial table; everything else 0 rows), so this is a growth-rate finding, not a current-overload finding — which is exactly why nobody has hit it yet.
- **Deeper analysis:** This is the largest single gap found in the subsystem, and it is invisible to every existing test because every test truncates between cases. The compounding factor is AUDIT-4B-3: a fleet with daily transients is already 4× over-scanning, so the growth rate is 4× the configured one. Note the deliberate exception that *does* bound itself: `site_icons` is one row per site (PK on `site_id`) with a `retry_after` negative cache, so it is inherently bounded — evidence that the codebase can bound a table when it thinks about it. The remedy should be a retention beat task (e.g. daily, keep N days of scans plus all `flagged`/acknowledged ones forever, delete `scan_findings` by cascade, and delete the matching artifact trees in the same sweep) — and it must be built to preserve the "site delete cascades artifacts" invariant that `_cleanup_orphan_artifacts` already depends on.
- **Cross-subsystem interactions:** Capture (artifacts are the capture's only durable output — deleting them removes the ability to re-verify an old verdict); Detection (findings rows are the per-layer evidence the UI drill-down reads; deleting them removes the audit trail of a verdict); API/frontend (unbounded table growth degrades every list endpoint and the health aggregates); Delivery (alerts and deliveries also grow unbounded — a 1 % flag rate at 500 sites/day is 5 alerts/day with N delivery rows each, forever).

---

### [NEW] AUDIT-SA3-3 — A failed capture orphans its artifacts permanently: the janitor keys on row existence, and a `failed` row still exists
- **Severity:** High — per §6.4, unbounded growth under sustained load, and this is the *unrecoverable* subset of AUDIT-SA3-2's artifact growth: it accumulates on exactly the sites that are failing, so the volume grows fastest where the operator is already in trouble.
- **Subsystem / file(s):** `backend/worker/scan_tasks.py:125-127` (`store_artifacts` runs **before** the promote transaction at `:131-161`), `:457-471` (the `capture_baseline` wrapper's `_mark_baseline_failed` recovery), `backend/worker/beat_tasks.py:271-277` (the janitor's `existing` set: `select(model.id).where(model.id.in_(chunk))` — **row existence only, no status filter**), `backend/worker/artifacts.py:14-25`.
- **Verification method:** hermetic test with a real temp artifacts root + DB-unreachable trace probe.
- **Evidence:**
  - `test_failed_capture_artifacts_are_orphaned_forever` — **PASSING**. A `failed` baseline whose `html_path`/`screenshot_path` point at real on-disk files (keyed to the row's own uuid, as production does): the janitor reports `{'checked': 1, 'removed': 0}` and both files survive. The positive control in the same test — a tree whose row *is* gone — is removed (`removed == 1`), proving the janitor works and that the failure is specifically the missing status filter.
  - DB-unreachable trace (SEAM 2), broken connection on the promote commit, with both sub-cases traced:
    ```
    SEAM 2: _capture_baseline -> 'raised DbDown'
      artifacts already on disk: ['page.html', 'screenshot.png']
      SUB-CASE A (DB still down, wrapper's recovery commit also fails): row status = 'capturing' -> stuck capturing FOREVER
      SUB-CASE B (DB recovered): row status = 'failed'
      artifact janitor -> {'checked': 1, 'removed': 0, 'errors': 0}
      artifacts dir after the janitor: ['baselines\\8fc40deb-…\\page.html', 'baselines\\8fc40deb-…\\screenshot.png']
    ```
- **Deeper analysis:** Two independent defects compose here. (1) The write order is inverted relative to the promote transaction: artifacts land on the volume first, and nothing rolls them back if the transaction never commits. (2) The janitor's predicate is "the row is gone", so it can only reclaim storage after the row is *deleted* — which for a `failed` baseline only happens when the operator re-baselines enough times, or never. Sub-case A is worse still: if the DB is still down when the wrapper's recovery commit runs, the row stays `capturing` **forever** (no beat-side baseline sweep — AUDIT-4B-5), so the site is inert *and* its artifact bytes are stranded. The minimal fix is a one-line predicate change — the janitor should treat a `failed`/`superseded` row as reclaimable, since a failed capture's artifacts are never read by anything (`_baseline_page_data` only ever reads `is_current` + `ready` rows). Note this composes with AUDIT-SA3-2: a retention sweep would also need to handle the artifact half, so the two should be designed together.
- **Cross-subsystem interactions:** Capture (the stranded bytes are the capture's only output for that attempt); Detection (a `capturing` row blocks the site's trust anchor — see the AUDIT-4B-5 inert-site chain); API/frontend (the site renders "capturing" indefinitely in sub-case A); infra (the volume is a Docker named volume with no quota — `docker-compose.yml:111`).

---

### [NEW] AUDIT-SA3-4 — The worker's broker publish has no fail-fast bound: 10.7 s on the first failure, 63.8 s on every subsequent one
- **Severity:** High — per §6.4, this is a measured performance/resource defect on the task-enqueue path that, under the exact condition the recovery primitives exist to handle, converts a broker outage into worker-slot starvation and silently truncates the dispatcher's work. The asymmetry is the defect: `app/tasks.py:34-39` configures the API's client to "Fail fast when Redis is unreachable instead of hanging the request" — and the worker, which makes the same call 50×/tick and up to 400×/sweep, is configured the opposite way.
- **Subsystem / file(s):** `backend/worker/celery_app.py:11-21` (`backend=REDIS_URL` — the worker has a result backend, unlike the API), `:23-46` (config: **no `broker_transport_options`**); the three publish sites `backend/worker/beat_tasks.py:208,353,372` and `backend/worker/scan_tasks.py:385,400`; contrast `backend/app/tasks.py:33-39`.
- **Verification method:** **measurement** — 12 healthy publishes, then 6 publishes against a stopped broker, then 4 after restart, against a throwaway Redis (the shared Redis is not host-reachable). 3 independent sessions; the "down" figure was stable across 5 consecutive passes.
- **Evidence:**
  ```
  conf.broker_transport_options = {}          conf.broker_connection_max_retries = 100
  conf.broker_connection_retry = True         conf.result_backend_transport_options = {}
  --- broker UP: steady-state publish cost, 12 passes ---
    up#1:  OK  216.1 ms     up#2..12: OK  1.2–1.7 ms
    steady-state median = 1.34 ms, mean = 1.36 ms (3+ passes; sigma ~ 0.2 ms)
  --- broker DOWN: repeated publish cost (does it grow?) ---
    down#1: OperationalError  10728 ms
    down#2: RuntimeError      63751 ms
    down#3: RuntimeError      63802 ms
    down#4: RuntimeError      63888 ms
    down#5: RuntimeError      63884 ms
    down#6: RuntimeError      63947 ms
  --- broker back UP, same process ---
    recovered#1: OK 17.6 ms   recovered#2..4: OK 1.3–1.5 ms
  ```
  The cost is **bounded but large**: ~63.8 s (σ ≈ 0.1 s over 5 passes), not growing, and **the app is not permanently poisoned** — the first publish after the broker returns succeeds in 17.6 ms. I hypothesised permanent poisoning from the error text ("The Celery application must be restarted") and **that hypothesis was wrong**; the measured behaviour is a bounded 63.8 s tax per call, which is still the finding.
  - **Consequence 1 — the dispatch tick dies mid-list.** With a down broker, site 1 costs 10.7 s and each subsequent site costs 63.8 s. The 420 s soft limit is reached at **site ~7**, so a 50-site tick loses ~43 sites *after their claims were already committed* (AUDIT-SA3-1) — the tick becomes a claim-eater rather than a dispatcher.
  - **Consequence 2 — the recovery primitive is the first casualty.** `resweep_undelivered` publishes up to `2 × REDELIVERY_MAX_PER_RUN = 400` messages in one 480 s hard-limited task. At 63.8 s each, 400 publishes = 25 520 s ≫ 480 s, so the sweep is SIGKILLed mid-loop — silently, since a hard timeout ACKs the message and writes no row.
  - **Consequence 3 — the scan task.** `_create_alert` blocks 10.7–63.8 s; `_create_remediations` blocks again per queued execution. With 8 queued executions the 480 s hard limit is reached *after* the scan's terminal commit — the scan survives, the alert and remediation rows are already committed so `resweep_undelivered` recovers them, and the loss is only the wasted worker slot.
  - `test_worker_publish_has_no_fail_fast_bound_while_the_api_client_does` — **PASSING**: pins `broker_transport_options == {}` and `broker_connection_max_retries == 100` on the worker against `{'max_retries': 2, 'interval_start': 0.1}` on the API, and confirms the heartbeat writer is the one place that *is* bounded (`socket_connect_timeout=2`).
- **Deeper analysis:** The root cause is the result backend. `celery_app` sets `backend=REDIS_URL` (`:14`), and Celery's redis backend drives the result-consumer pubsub machinery on **every** `send_task` (`celery/app/base.py:968` → `backends/redis.py:402 on_task_call` → `:135 start` → `:164 _consume_from`), which is exactly the retry-connects-then-raises-`RuntimeError` path that `app/tasks.py:28-32` documented and worked around with `backend=None`. The worker never got the same treatment. The healthy-path cost of this machinery is real too: the **first** publish in a process costs 216 ms versus 1.34 ms steady, i.e. ~215 ms of result-consumer setup on every worker restart, and every task completion writes a `celery-task-meta-*` key (measured live: 22 keys in the first 16 minutes ≈ 1 340/day of ticks alone, each 182–281 bytes, `result_expires` = Celery's 1-day default — bounded, so not a finding on its own, but entirely wasted). The fix is two-part and cheap: give the worker's publish path a `broker_transport_options` bound matching the API's, and consider `task_ignore_result=True` for the periodic tasks (nobody consumes results — the API client is `backend=None`).
- **Cross-subsystem interactions:** Capture (a blocked publish delays the scan task's own completion, holding a worker slot); Detection (a truncated tick means the site is unmonitored — see AUDIT-SA3-1); Delivery (the alert/remediation publishes are the ones that block, though their rows are recoverable); infra (a Redis restart — which AUDIT-SA3-13 makes *likely*, since there is no AOF — triggers exactly this path).

---

### [NEW] AUDIT-SA3-5 — A failing `_schedule_next` silently converts a site into a once-per-tick scan loop
- **Severity:** Medium — a partial degradation that replaces the operator's configured cadence with the beat period, with no counter, no error, and no operator-visible signal. Not High because the failure requires a *persistently* failing schedule write (a transient DB blip self-heals on the next scan, since the site stays due and is re-dispatched), and the amplification is bounded by the in-flight index to roughly one scan per tick.
- **Subsystem / file(s):** `backend/worker/scan_tasks.py:407-420` (`_schedule_next` — `try:` wraps everything, `except Exception: logger.exception(...)`, **no counter, no metric, no return value**; and it is the *only* writer of `next_scan_at` for a completed scan), `:367` (the call site), `backend/worker/beat_tasks.py:126-140` (the due-site query finds it again immediately).
- **Verification method:** hermetic test (the real swallow-all wrapper, with the cadence computation made to raise, exactly as a failed commit would).
- **Evidence:** `test_failing_schedule_next_leaves_the_site_due_and_rescans_every_tick` — **PASSING**. `_run_scan` returns `"failed"` (the scan itself is unaffected — 4B's "scheduling can never fail a scan" is re-confirmed), but afterwards `next_scan_at` is still in the past and `current_interval_minutes` is still `None` ("the adaptive ladder never ran"). The **very next tick** then reports `{'enqueued': 1}` and publishes a fresh scan. The test also asserts the complete stats key set contains no bucket distinguishing this from a normal dispatch.
  Contrast (proving the wrapper is genuinely sound, not a test artifact): `test_schedule_next_swallow_never_fails_a_scan_but_leaves_interval_unchanged` — **PASSING** — calls the real `_schedule_next` with a session object whose *first attribute access* raises, and asserts no exception escapes and no state changes.
- **Deeper analysis:** What `_schedule_next`'s swallow-all hides, precisely: a `next_scan_at` that does not move. Because the dispatcher re-duees on `next_scan_at <= now`, the site is claimed on the very next tick — measured live at **64.18 s mean**, so a persistently-failing schedule turns a 24 h cadence into a **~1-minute** cadence. The in-flight unique index caps concurrent rows at one, so the harm is *scan rate*, not duplicate work: ~1 350 scans/day instead of 1, and each one loads MiniLM, so the CPU cost is AUDIT-4B-7's memory budget multiplied. Two compounding factors: (a) the failure is invisible in the tick's stats **and** invisible in the health page, because the tick *succeeds*; (b) nothing resets the condition except a scan that manages to write the schedule. The minimal fix is a return value from `_schedule_next` surfaced into a counter (e.g. `scheduling_failed`), and/or a guard in the dispatcher that refuses to claim a site whose `next_scan_at` is more than one interval in the past. 4B recorded "the swallow-all wrapper verified (scheduling can never fail a scan)" as a clean ledger item — that is true, and this finding is the other half of that trade: the swap is a *silent cadence collapse*, not a no-op.
- **Cross-subsystem interactions:** Detection (the site is scanned far more often, so a benign dynamic site accrues more `changed` history — the same noise as AUDIT-4B-3, amplified); Capture (4×–1000× the Playwright load on one host); API/frontend (nothing surfaces it; the site just looks "well-monitored"); infra (worker CPU and memory, per AUDIT-4B-7).

---

### [NEW] AUDIT-SA3-6 — The in-flight unique index firing inside the dispatcher is absorbed into no stats bucket at all
- **Severity:** Medium — a real observability gap on the race the brief asked to try to break, on the path the whole concurrency contract is built around. The *arbiter* works perfectly (no duplicate scan is ever created); what is missing is any signal that it fired.
- **Subsystem / file(s):** `backend/worker/beat_tasks.py:183-188` (in-flight SELECT), `:202-204` (the `Scan` INSERT that can violate `ix_scans_one_inflight_per_site`), `:214-221` (the `except Exception` that absorbs it), `backend/app/services.py:122-126` (`scans_inflight_unique_violation` — the API path *does* translate it to a 409; the dispatcher does not use this helper at all), `backend/app/models.py:504-512` + migration `g1h2i3j4k5l6` (the index).
- **Verification method:** hermetic test that **wins the race deterministically** (a second session commits a fresh pending Scan inside the window between the dispatcher's SELECT and its INSERT, injected via a commit hook), plus a positive control that the arbiter is genuinely the partial unique index.
- **Evidence:**
  - `test_dispatcher_inflight_index_violation_is_absorbed_into_no_stat_bucket` — **PASSING**: `state['inserted'] is True` (the race was really staged), `sent == []` (nothing published), exactly one Scan row exists (the racing one), `stats['lost_claim'] == 0` and `enqueued == 0` — the only bucket that moved is invisible to a reader of the tick's return value.
  - `test_the_raw_index_violation_itself_is_what_the_dispatcher_swallows` — **PASSING**: inserting a second `pending` row raises `IntegrityError` naming the index, while a `completed` row correctly does not consume the slot.
  - **The API side is verified clean.** DB-unreachable trace (SEAM 5): second `scan-now` → `ConflictError(409): A scan of dbt is already in progress`; second `rebaseline` → `ConflictError(409): A baseline capture is already in progress for dbt`. **`IntegrityError` never escapes to the request path** — `services.py:244-254`, `:345-351`, `:422-433` all catch and translate, and `test_phase18_concurrency_races.py`'s eight tests re-ran green. The brief's "what happens on `IntegrityError` escaping to the request path" question is answered: **it does not**, on any of the three service entry points.
- **Deeper analysis:** The asymmetry is the finding. The API path has a purpose-built translation layer with three named predicates (`sites_url_unique_violation`, `scans_inflight_unique_violation`, `baselines_inflight_unique_violation`) plus a `concurrent_write_aborted` 40P01/40001 handler. The dispatcher, which races the same index against the *same* API call, has none of it — its `except Exception` catches the IntegrityError, rolls back, and reduces a lost-race arbitration to a log line. So a *scan-now storm* against due sites is invisible on the scheduling side while being perfectly visible (as 409s) on the API side. The minimal fix: route the dispatcher's IntegrityError through the same `services.scans_inflight_unique_violation` predicate and count it as `skipped_inflight` (or a new `lost_race` bucket) rather than letting it fall into the generic handler. Note the correct outcome is already guaranteed — this is purely a signal, which is why it is Medium and not High.
- **Cross-subsystem interactions:** API (`scan-now` returns 409 correctly and is visible to the caller; the dispatcher's identical outcome is not); Detection (no double scan, so no verdict duplication); Frontend (nothing to render, because nothing is recorded); infra (`celery inspect`/`docker logs` are the only place the race is visible, and only at ERROR level in a log nobody reads by default).

---

### [NEW] AUDIT-SA3-7 — `beat` declares no `depends_on: db` and neither `worker` nor `beat` has a healthcheck
- **Severity:** Medium — a documented-composition defect that produces two concrete, reproducible failure modes: a cold `docker compose up` can have beat publishing ticks before Postgres is ready, and an OOM-looping worker is indistinguishable from a healthy one to Docker, to `docker compose ps`, and to any restart policy.
- **Subsystem / file(s):** `backend/docker-compose.yml:118-131` (beat: `depends_on` = redis only, **no db**), `:89-116` (worker: `depends_on` = db + redis, **no healthcheck**), `:17,28,82` (the only three healthchecks in the file: db, redis, app); `backend/Dockerfile.worker:36`.
- **Verification method:** code-trace against the compose file + live `docker inspect` + a source-trace of what the beat tasks actually need.
- **Evidence:**
  - `docker inspect wardress-beat-1 --format '{{json .Mounts}}'` → `[]` (also re-confirms AUDIT-4B-8's schedule-file note: no volume).
  - `docker-compose.yml` healthcheck blocks are at lines 17 (db), 28 (redis), 82 (app) — **no healthcheck for `worker`, `beat`, `telegram-bot`, or `ollama`**.
  - Four of the five beat tasks require the database: `_dispatch_due_scans` (SELECT sites, UPDATE sites, INSERT scans), `_resweep_undelivered` (SELECT alerts/remediation_executions), `_cleanup_orphan_artifacts` (SELECT baselines/scans), `expire_agent_actions` (`expire_stale(db)`), `sync_model_catalog` (upsert 8 000+ catalog rows). Only the publish step needs Redis. So on a cold start, beat's first ticks can fire before Postgres accepts connections, and — per AUDIT-4B-6 — **those failing ticks write no heartbeat and their recovery is the next tick, up to 64 s later**; and per AUDIT-SA3-1, any tick that fails *after* a claim leaves a silent gap.
  - `beat_max_loop_interval = 0` and `beat_scheduler = 'celery.beat:PersistentScheduler'` (live conf dump) — no retry acceleration on failure.
- **Deeper analysis:** Phase 9 already flagged "beat missing `depends_on: db`" in its scope list; this session confirms it empirically and adds the second half (absent healthchecks) plus the consequence chain into this subsystem's own findings. The healthcheck gap is the more consequential of the two: the single failure mode this subsystem cannot currently observe is the one AUDIT-4B-7 describes (worker OOM-spiral), and because `restart: unless-stopped` only restarts a container that *exits*, an OOM-looping-but-alive worker is never restarted either. A worker healthcheck that pings Redis (which the health page already effectively does) plus a `beat` `depends_on: db: condition: service_healthy` are both one-line compose changes — no code.
- **Cross-subsystem interactions:** Delivery (beat's resweep is the alert-delivery recovery primitive); Detection (a dropped dispatch tick is unmonitored coverage — AUDIT-4B-6); infra (this is the compose layer the whole stack's startup ordering depends on).

---

### [NEW] AUDIT-SA3-8 — Migrations run only from `install.ps1` / `update.ps1`, never at container start
- **Severity:** Medium — an operational gap that produces a silent schema/code mismatch. `docker compose up -d --build` on a new commit starts the app against an un-migrated database.
- **Subsystem / file(s):** `backend/Dockerfile.app` (CMD `uvicorn app.main:app`, no migration step), `backend/Dockerfile.worker:36` (no migration step), `backend/app/main.py:40-50` (lifespan runs `bootstrap_migration()` — the **legacy AI-settings** migration — and `bootstrap_catalog()`, **not** Alembic), `scripts/install.ps1:305-306`, `scripts/update.ps1:159-160` (the only two places `alembic upgrade head` appears anywhere outside tests).
- **Verification method:** repo-wide grep for `alembic.*upgrade|upgrade head` across the whole repository excluding `Prompts/**` and `*.lock`.
- **Evidence:** the only production call sites are `scripts/install.ps1:306` and `scripts/update.ps1:160`, both `Invoke-Compose @("run", "--rm", "app", "alembic", "upgrade", "head")`. `app/main.py`'s lifespan (`:41-49`) contains no Alembic call. So the migration gate is the PowerShell scripts, which PROMPT-003 §1 Rule 14 forbids the audit from running, and which an operator who rebuilds with plain `docker compose` never invokes.
- **Deeper analysis:** This is the mechanism that would make AUDIT-4B-8's drift recur and, unlike the drift itself, **fail silently**: the app would start, serve, and return empty lists / 500s on any query touching a new column, with no migration error anywhere. It is also why the migration-downgrade sweep in §2 is valuable beyond its own sake — because the moment someone does add a start-up migration, the reversibility of all 16 revisions becomes load-bearing rather than merely tidy. Recommended shape: a `depends_on`-gated one-shot `migrate` service in compose that `app`/`worker`/`beat` depend on, with `alembic upgrade head` as its command (composing on the existing, verified-reversible chain, not replacing the scripts). **Out of phase scope for implementation** — recorded for the remediation prompt and for Phase 9's operational-lifecycle pass, which already owns the scripts.
- **Cross-subsystem interactions:** every subsystem (a missing column breaks the dispatcher, the scan writer, the alert path, and the API equally); infra (this is the compose/scripts layer).

---

### [NEW] AUDIT-SA3-9 — `via` is accepted and silently discarded by the three orchestration service functions
- **Severity:** Low — a dead parameter in three functions and an audit-completeness gap: the audit log records which surface acknowledged an alert and muted a site, but **not** which surface created a site, triggered a scan, or replaced a trust anchor.
- **Subsystem / file(s):** `backend/app/services.py:198` (`create_site(via: str, ...)`), `:290` (`trigger_scan_now(via: str, ...)`), `:381` (`rebaseline_site(via: str, ...)`) — each is the **only** occurrence of `via` in its function body. Their `record_audit` calls (`:262-271`, `:352-360`, `:434-442`) pass `after=site_snapshot(site)` / no `after` / no `after`, and **no** `via`. Contrast the three siblings that *do* use it: `:482` (`acknowledged_via=via`), `:497` (`after={"risk_score": …, "via": via}`), `:531` (`after={**site_snapshot(site), "via": via}`), `:597` (`after={…, "via": via}`).
- **Verification method:** repo-wide grep (`\bvia\b` in `app/services.py` shows the parameter lines and the four *use* sites in the sibling functions, and nothing inside the three orchestration bodies) + `ruff --select ARG001` over `app/` (which independently reports `Unused function argument: via` three times) + a search of the call sites.
- **Evidence:** **9 production call sites bother to pass a surface** — `app/routers/sites.py:123,342,360,495` (`via="dashboard"`, `via="rest"`), `app/agent/tools.py:476,531,542,563` (`via=ctx.surface`, i.e. `"web"` or `"telegram"`), `worker/telegram_bot.py` — and it is dropped at every one of them. The `AuditLog` model (`backend/app/models.py:582-612`) has no surface column at all, so the information is unrecoverable, not merely unwritten. The `via="telegram"` vs `via="dashboard"` distinction that `acknowledge_alert` and `mute_site` *do* preserve is therefore unavailable for exactly the three actions an operator would most want to attribute: who added the site, who forced the scan, who replaced the trust anchor.
- **Deeper analysis:** This is a small, unambiguous instance of the drift class Phase 2B's O-8 idea targets (comment/constant drift) applied to *parameter* drift: a signature that grew a field, three of six implementations adopted it, and the other three were never revisited. The remediation is mechanical — fold `via` into the `after` dict exactly as `mute_site:531` already does. It is Low because nothing breaks; it is not a no-op because the audit log is the product's answer to "who did this", and for the three orchestration actions the honest answer today is "someone".
- **Cross-subsystem interactions:** API (the audit-log view on `audit.tsx` shows a `site.create` / `scan.now` / `site.rebaseline` row with no surface attribution while adjacent rows have one); Delivery (n/a); Capture (n/a).

---

### [NEW] AUDIT-SA3-10 — `missing-prereqs` is the only scan-failure path that leaves `verdict` NULL
- **Severity:** Low — one failed row in the table is shaped differently from every other failed row, which is a data-consistency wart in the history surface, not a behavioural defect (the row is `status=failed` with an explicit `error` string, and nothing reads `verdict` for a failed scan).
- **Subsystem / file(s):** `backend/worker/scan_tasks.py:251-256` (the `missing-prereqs` branch sets `status = ScanStatus.failed`, `error = "Site or its baseline disappeared before the scan ran"`, `finished_at` — **and never sets `verdict`**). Every sibling failure path does: `:265-269` (`fetch_page` failure → `verdict = ScanVerdict.error`), `:440-445` (`_mark_scan_failed` → `verdict = ScanVerdict.error`), `backend/worker/beat_tasks.py:192-196` (the dispatch supersede → `verdict = ScanVerdict.error`), `backend/app/services.py:322-332` (the API's stale recovery → `verdict = ScanVerdict.error`).
- **Verification method:** hermetic test with a positive control.
- **Evidence:** `test_concurrent_site_delete_during_scan_completion_is_clean` — **PASSING**. It deletes a `Baseline` out from under a `running` scan; `_run_scan` returns `"missing-prereqs"`, the row ends `status=failed` with `"disappeared" in error` and — the assertion that found this — **`verdict is None`**. The positive control in the same test then drives an ordinary fetch failure and asserts `verdict == ScanVerdict.error`. The same test also **closes the FK-cascade question** the brief asked about: ordering A (scan commits, then the site is deleted) leaves no dangling scan and no dangling baseline; ordering B (site deleted first) returns `"scan-row-missing"`; and a baseline deleted under a running scan returns `"missing-prereqs"` with no exception escaping to the caller in any of the three orderings.
- **Deeper analysis:** I found this while trying to prove the `missing-prereqs` branch was well-formed, and asserted `verdict == ScanVerdict.error` — the test failed and the real behaviour is `NULL`. The practical consequence is narrow but real: a consumer filtering `WHERE verdict IS NULL AND status = 'failed'` (the natural "failed but never evaluated" query) will pick up these rows, and a consumer that renders the verdict will show a blank where every other failure shows "error". `scan_tasks.py:252-255` is the only place in the file that writes a terminal `status` without a terminal `verdict`, which suggests it was written before the verdict column was considered, not deliberately. One-line fix; flagged for the remediation prompt.
- **Cross-subsystem interactions:** API/frontend (the scan-history list renders a blank verdict for these rows); Detection (none — the scan produced no verdict by construction); Delivery (none).

---

### [NEW] AUDIT-SA3-11 — `pool_pre_ping=True` in `worker/db.py` is unreachable, and every Celery task pays ~88 ms to build and tear down an engine
- **Severity:** Low — a dead configuration plus a measured inefficiency. Not a correctness bug: the per-invocation engine is *safe* by construction (that is exactly why `pool_pre_ping` is unnecessary), and the cost is small in absolute terms. It is logged because the setting implies a protection the code does not have, and because the optimisation has a real, measured payoff.
- **Subsystem / file(s):** `backend/worker/db.py:14-22` (`create_async_engine(get_settings().database_url, pool_pre_ping=True)` inside `task_session()`, `await engine.dispose()` in the `finally`), `backend/app/db.py:18-22` (the API's module-level singleton engine, `pool_pre_ping=True` and **no `pool_recycle`**).
- **Verification method:** hermetic test (engine identity + pool introspection + timing) + **measurement** (3+ passes).
- **Evidence:**
  - `test_task_session_builds_a_fresh_engine_per_call_making_pre_ping_a_noop` — **PASSING**. Two `task_session()` calls produce two *distinct* engine objects; the pool reports `pre_ping=True` and `recycle == -1` (SQLAlchemy's "no recycle"). SQLAlchemy only pings and recycles a connection it is **reusing** from a pool; a brand-new pool's first checkout is a fresh connect, so `pool_pre_ping` can never fire here.
  - **Timing (measured, loopback Postgres):** fresh engine + connect + `SELECT 1` + dispose = **87.98 ms median** (min 68.12, max 98.88, 5 passes); a warm pooled connection doing the same = **6.59 ms median** (min 5.69, 20 samples). **A 13× penalty, ~81 ms of pure overhead per Celery task.** The test prints both numbers.
  - **Pool-exhaustion arithmetic (the brief's question), computed and verified clean:** `AsyncAdaptedQueuePool size=5 max_overflow=10 timeout=30.0` (live introspection). Worst case: 12 worker children × **1** connection each (an `AsyncSession` holds at most one connection for a task's duration) = 12; the API's singleton = 5 + 10 = **15**; beat = **0** (it executes no tasks). Total **27 of Postgres's 100 `max_connections`**, 7 in use at rest. **No exhaustion is reachable in the current design** — and `pool_pre_ping` on the API's long-lived pool *is* the correct protection against the documented stale-connection-after-a-DB-restart class, which is the case that actually needs it. So the setting is in the wrong file.
- **Deeper analysis:** The docstring at `worker/db.py:1-5` is correct and the design is right — `asyncio.run()` per task genuinely forbids sharing an engine across loops. But the *pool* is a separate concern from the *event loop*: a module-level engine created lazily **inside the child** (after fork, on first use) would never cross an event loop, and prefork makes the parent-side creation impossible to leak. The catch, and it is the important caveat, is pool sizing: `size=5, max_overflow=10` per child × 12 children = **180 connections > `max_connections=100`**, so any such optimisation **must** pin `pool_size=1, max_overflow=0` per child, and the tuning belongs in the memory/capacity discussion of AUDIT-4B-7. In absolute terms the win is small — ~2 400 tasks/day × 81 ms ≈ 195 s/day, dominated by the 1 440 dispatch ticks — so this is an opportunity, not a defect. The `pool_recycle` absence is a non-issue in `worker/db.py` for the same structural reason and a genuine (if low) gap in `app/db.py`, where a pooled idle connection *can* go stale; `pool_pre_ping` covers that case, so no action is needed there either.
- **Cross-subsystem interactions:** infra (Postgres connection budget is the shared resource; this is what makes the 27/100 figure safe); API (the singleton engine's 15-connection ceiling is the term that would matter if request concurrency ever rose); Detection (the 88 ms is inside the scan's 480 s budget, so it is noise there — it matters for the 1 440 short ticks/day, where it is 20 % of a tick's total 74 ms idle cost).

---

### [NEW] AUDIT-SA3-12 — `wardress.ping` is an orphan task registration, and every task result is stored in Redis for 24 hours for a consumer that does not exist
- **Severity:** Low — pure waste and one unused registration; zero behavioural impact.
- **Subsystem / file(s):** `backend/worker/celery_app.py:49-52` (`@celery_app.task(name="wardress.ping")`, "Connectivity self-test used by Phase 0 stack verification"), `:14` (`backend=REDIS_URL`), `:23-46` (no `task_ignore_result`).
- **Verification method:** repo-wide grep + live config dump + live Redis inspection.
- **Evidence:**
  - `wardress.ping` appears in **exactly three places in the entire repository**: its own definition (`celery_app.py:49`), and `backend/tests/test_smoke.py:28` (`assert "wardress.ping" in celery_app.tasks`). **No production code ever sends it.** It does appear in the live worker's `celery inspect registered` output (10 tasks), so it occupies a slot in the operational task list with no consumer.
  - Live config dump: `result_expires = datetime.timedelta(days=1)`, `task_ignore_result = False`, `result_backend = 'redis://…/0'`. Live Redis: 22 `celery-task-meta-*` keys after 16 minutes of uptime, **TTLs 85 412–86 374 s** (i.e. the 86 400 s = 24 h default, decaying correctly), values 182–281 bytes.
  - Arithmetic: the dispatch tick alone publishes 1 440/day, plus 288 resweeps, 288 agent janitors, 2 artifact janitors, 2 catalog refreshes ≈ **2 020 results/day × ~250 B ≈ 500 KB/day** of Redis keys — bounded and self-clearing, so **not** a growth finding. The waste is the per-task `SETEX` round trip on completion and the ~215 ms first-publish result-consumer setup measured in AUDIT-SA3-4.
  - Contrast that makes it clearly a misconfiguration rather than a design choice: the **API** client sets `backend=None` with the comment "the API never consumes task results" (`app/tasks.py:27-33`). The worker has the same consumer population — none — and keeps the backend anyway.
- **Deeper analysis:** Both halves are the same root cause as AUDIT-SA3-4: the worker's `backend=REDIS_URL` was kept for Phase 0's connectivity self-test and never revisited once results turned out to be unconsumed. The two fixes are independent and both one-liners: mark the periodic tasks `ignore_result=True` (or globally, if nothing ever reads `AsyncResult`), and either delete `wardress.ping` or document it as the manual `celery call` probe it is. Keeping it is defensible — an operator having a documented `celery -A worker.celery_app call wardress.ping` diagnostic is genuinely useful — but it should be *documented* as an operator tool rather than sitting in the registry looking like a live task, and it should be checked against `scripts/validate.ps1` before anyone removes it.
- **Cross-subsystem interactions:** infra (Redis memory and per-task round trips); Delivery (none); Detection (none).

---

### [NEW] AUDIT-SA3-13 — Redis runs with no AOF and no `maxmemory`: a restart loses in-flight queue messages, and growth is unbounded
- **Severity:** Low — the blast radius is a delayed scan (recovered by the beat stale sweep), not lost work, and the volume in question is tiny. It is nonetheless a genuine durability gap for the one component that is the system's queue.
- **Subsystem / file(s):** `backend/docker-compose.yml:23-32` (the redis service: `image: redis:8-alpine`, a `redis-data` volume, **no `command:`** — so every durability/limit setting is the image default).
- **Verification method:** live read-only probe of the running container's configuration.
- **Evidence:** `redis-cli CONFIG GET` against `wardress-redis-1`:
  ```
  appendonly        -> no
  save              -> "3600 1 300 100 60 10000"
  maxmemory         -> 0            (unlimited)
  maxmemory-policy  -> noeviction
  mem_fragmentation_ratio -> 10.79
  used_memory_human -> 2.00M   used_memory_peak_human -> 2.03M
  ```
  `/data` contains only `dump.rdb` (7 248 bytes). Consequences: (1) with `appendonly no` and RDB snapshots at 60 s (≥10 000 keys changed) / 300 s (≥100) / 3 600 s (≥1), **a Redis restart loses up to 300 s of queue mutations** — both enqueued messages and acked-and-completed state. With `task_acks_late=True` + `task_acks_on_failure_or_timeout=True` (live: `task_reject_on_worker_lost = None`, i.e. the default False), a message acked after the last snapshot and before a crash is **gone**, and its scan row is only recovered by the beat stale sweep up to one interval later (AUDIT-4B-5, up to 24 h 20 min). (2) `maxmemory 0` + `noeviction` means Redis grows until the **host** OOMs rather than shedding; for a broker, `noeviction` is the correct policy (never drop a message), which makes the missing `maxmemory` more consequential, not less. (3) `mem_fragmentation_ratio 10.79` is an artifact of the 2 MiB dataset and not itself actionable.
  Honest sizing: the *current* growth is bounded and small (≈500 KB/day of result keys with a 24 h TTL, per AUDIT-SA3-12; the queue is empty — `LLEN celery 0`, `ZCARD unacked 0`). So this is a durability-and-future-growth finding, not a present-overload one.
- **Deeper analysis:** The `unacked` behaviour 4B verified (kombu performs no unacked restore at worker startup, so a killed scan's message sat in Redis for the full 3 600 s visibility timeout) means the broker's `unacked` set is itself a place where a message can be stranded. Combined with no AOF, a Redis restart at the wrong moment loses work that the DB sweep will eventually clean up — the system is *self-healing* here by design, which is why this is Low. The minimal fixes are compose-level: `command: redis-server --appendonly yes --appendfsync everysec` (costs ~1 % throughput, buys durability) and an explicit `--maxmemory` with a documented value so the host OOM killer is not the enforcement mechanism. The `docker-compose.yml` beat-schedule-file finding from AUDIT-4B-8 is the same class: an undecided default in a compose file where every other decision is explicit.
- **Cross-subsystem interactions:** Delivery (a lost `deliver_alert` message leaves an alert with zero delivery rows — which `resweep_undelivered` *does* recover, so this is the benign case); Detection (a lost `run_scan` message leaves a `pending`/`running` row — recovered only at the next due tick, i.e. up to 24 h 20 min); infra (the compose layer).


---

## 2. Extra deliverable — Alembic Downgrade Verification

**Method.** `DATABASE_URL` pointed at `wardress_sa_orch_test` **only** (never `wardress-db-1`). Two independent sweeps:
- **Sweep A (empty database):** `alembic upgrade head`, then 16 successive `alembic downgrade <rev>` steps, then `alembic downgrade base`; after `base`, enumerated every remaining table, index, sequence, and enum type in `public`.
- **Sweep B (fully populated):** seeded **1 row into each of all 23 tables** through the ORM (users, refresh_tokens, sites ×2, suppression_rules, notification_channels, app_settings, alerts, alert_deliveries, baselines, scans ×2, scan_findings, site_icons, audit_log, api_keys, remediation_hooks, remediation_executions, agent_conversations/messages/pending_actions, model_catalog_providers, model_catalog, ai_providers, ai_task_assignments), then repeated the full 16-step downgrade, then `upgrade head` again and re-counted.

| revision | downgrade result (empty) | downgrade result (populated) | residue / notes |
|---|---|---|---|
| `o9q1r2s3t4u5` (scans.capture_evidence) | PASS (exit 0) | PASS (exit 0) | Drops the JSONB column; the captured_evidence data is destroyed (documented, expected) |
| `n8p9q1r2s3t4` (site_icons favicon cache) | PASS | PASS | Drops the table + its FK to sites; data destroyed (expected) |
| `m7n8p9q1r2s3` (model_catalog_providers.env json→jsonb) | PASS | PASS | `ALTER … TYPE JSON USING env::JSON` is lossy only in jsonb's key-order/dedup normalisation, which the migration docstring states; the app reads a deserialised dict, so no behavioural loss |
| `l6m7n8p9q1r2` (remediation_hooks.allow_private_networks) | PASS | PASS | Column dropped; default False is restored by the model's own default on re-upgrade — **behavioural change is silent but safe** (the conservative direction) |
| `k5l6m7n8p9q1` (baselines in-flight unique index) | PASS | PASS | Index dropped; rows the *upgrade* marked `failed` stay failed (docstring: "history is not rewritten backwards") — correct |
| `j4k5l6m7n8p9` (users login lockout) | PASS | PASS | Columns dropped; the counter/lockout state is destroyed, so a downgrade silently re-enables brute-force attempts until the next failed login — **worth a docstring note** |
| `i3j4k5l6m7n8` (sites.url unique index) | PASS | PASS | Drops `uq_sites_url`, restores non-unique `ix_sites_url`. The *upgrade* is the destructive one (it DELETEs duplicate sites and cascades their history) — documented in the docstring, **not** surfaced to an operator anywhere |
| `h2i3j4k5l6m7` (unified AI layer) | PASS | PASS | Drops 4 tables; the next `sync_catalog`/`bootstrap_catalog` repopulates `model_catalog*`. `ai_providers`/`ai_task_assignments` are **operator configuration** (Fernet-encrypted keys) — a downgrade destroys them irrecoverably. Expected for a downgrade, but the most destructive step in the chain |
| `g1h2i3j4k5l6` (correctness indexes) | PASS | PASS | Drops `ix_scans_one_inflight_per_site` + perf indexes. **This is the important one:** during the window between this downgrade and `k5l6m7n8p9q1`'s re-upgrade, the scans in-flight arbiter does not exist, so concurrent `scan-now`s can both create a scan |
| `a7c2e9f31d55` (agent tables) | PASS | PASS | Drops 3 tables; chat history destroyed (expected) |
| `0a6bd482fe1f` (session_started_at) | PASS | PASS | Column dropped; sessions lose their absolute-lifetime anchor, so a downgrade silently extends `max_session_ttl` enforcement until the next login rotation — **security-relevant, undocumented in the migration** |
| `f3c8d6a91b27` (audit / api keys / remediation) | PASS | PASS | Drops 4 tables; audit history destroyed (expected) |
| `e9a2b7c15f04` (channels / settings / alerts / deliveries) | PASS | PASS | Drops 4 tables; **encrypted SMTP/telegram credentials** destroyed (expected) |
| `d7e3a1c40f88` (suppression_rules) | PASS | PASS | Drops the table; per-site suppression rules destroyed (expected) |
| `b41c7a9e2d05` (scan_findings / risk_score / scheduling) | PASS | PASS | Drops the table and the scheduling columns; the site history degrades to a bare scan list |
| `76f6f5dcf922` (phase 1: users/sites/baselines/scans) | PASS | PASS | Drops the 4 core tables; **total data loss** (expected for `base`) |
| `→ base` | **PASS, exit 0** | **PASS, exit 0** | **Zero residue**: only `alembic_version` (empty) + `alembic_version_pkc` remain. 0 tables, 0 non-system indexes, 0 sequences, 0 user enum types. |
| `upgrade head` (round-trip) | PASS | PASS | All 16 upgrades re-apply cleanly from `base`; row counts after the round-trip are 0 (the data was dropped by design) |
| **`alembic check`** | — | — | **"No new upgrade operations detected."** — no model/migration drift. Identical result before the sweep and after the round-trip. |

**Verdict: the migration set is fully reversible. No migration fails, fails partially, or leaves residue, on either an empty or a fully populated database.** This **invalidates** any assumption of downgrade fragility and is the single most positive result in this report.

Three *data*-destructive (not failure) observations worth carrying into the remediation prompt's docs work: `0a6bd482fe1f` silently disables the absolute session-lifetime anchor on downgrade, `j4k5l6m7n8p9` silently resets login-lockout state, and `i3j4k5l6m7n8`'s **upgrade** deletes duplicate sites (with cascade) without an operator-facing warning — the last one is the only one whose destructiveness is on the *forward* path.

---

## 3. Extra deliverable — Deployment Parity (AUDIT-4B-8 re-verification)

`docker cp wardress-worker-1:/app/<file>` → CRLF-normalise → `git hash-object` on both sides. 20 files: the 6 worker modules, the 8 app modules, 3 alembic migrations, and 3 more in-scope files. **HEAD = `701552e`; working tree clean (0 porcelain lines).**

| file | container hash-object | HEAD hash-object | verdict |
|---|---|---|---|
| `worker/celery_app.py` | `ce392754830abdb15d8e83769c18dd77fdbf4623` | `ce392754830abdb15d8e83769c18dd77fdbf4623` | **MATCH** |
| `worker/scan_tasks.py` | `a6878b371b143bb0156502ce37d488aca88daf13` | `a6878b371b143bb0156502ce37d488aca88daf13` | **MATCH** |
| `worker/beat_tasks.py` | `f11b6fce7f493e5f27ff15fe3e1babd388d2ae21` | `f11b6fce7f493e5f27ff15fe3e1babd388d2ae21` | **MATCH** |
| `worker/db.py` | `961e60d6360659b15606c6f962f000c38070bad1` | `961e60d6360659b15606c6f962f000c38070bad1` | **MATCH** |
| `worker/alert_tasks.py` | `d846e9a9ceac04f60c2196f9b189086dce072de8` | `d846e9a9ceac04f60c2196f9b189086dce072de8` | **MATCH** |
| `worker/remediation_tasks.py` | `ca5ae786c47b18315197f254b700f25eca8c223a` | `ca5ae786c47b18315197f254b700f25eca8c223a` | **MATCH** |
| `app/scanning.py` | `fa3f58982967f8ab5e427e3fa76a8ccb25fbd32b` | `fa3f58982967f8ab5e427e3fa76a8ccb25fbd32b` | **MATCH** |
| `app/tasks.py` | `29abb3ec4cc0be13bb3e7a33577b8f5f848e082b` | `29abb3ec4cc0be13bb3e7a33577b8f5f848e082b` | **MATCH** |
| `app/services.py` | `8cddcf03c19f7fe3e56fe117537246d6c8cf7b26` | `8cddcf03c19f7fe3e56fe117537246d6c8cf7b26` | **MATCH** |
| `app/models.py` | `7c4d84248f5a23fa0401f346498535fbe0b0d2e2` | `7c4d84248f5a23fa0401f346498535fbe0b0d2e2` | **MATCH** |
| `app/schemas.py` | `f813f312a1de9d63d16c9cbc5e43b75617506892` | `f813f312a1de9d63d16c9cbc5e43b75617506892` | **MATCH** |
| `app/db.py` | `6035356568e2f9a114fa740c1045d8e7fe5f1a0f` | `6035356568e2f9a114fa740c1045d8e7fe5f1a0f` | **MATCH** |
| `app/config.py` | `2705b158a476b3cfbea50ad42cd9d9d89206ac00` | `2705b158a476b3cfbea50ad42cd9d9d89206ac00` | **MATCH** |
| `app/main.py` | `3bdc48d69db998005989e008541f53ff7aefb9da` | `3bdc48d69db998005989e008541f53ff7aefb9da` | **MATCH** |
| `app/alerting.py` | `7153c563afc4339446de3e964b5744ee020dd907` | `7153c563afc4339446de3e964b5744ee020dd907` | **MATCH** |
| `app/remediation.py` | `2cbb9c6adf06e14bca81236181cc445e291997ed` | `2cbb9c6adf06e14bca81236181cc445e291997ed` | **MATCH** |
| `app/capture.py` | `d43ce924ca2ee850d651ea8fcce51220cb9192dc` | `d43ce924ca2ee850d651ea8fcce51220cb9192dc` | **MATCH** |
| `alembic/versions/o9q1r2s3t4u5_scans_capture_evidence.py` | `7c15c5f74292375fa343e1dd7c389c35d124740e` | `7c15c5f74292375fa343e1dd7c389c35d124740e` | **MATCH** |
| `alembic/versions/g1h2i3j4k5l6_correctness_indexes.py` | `abdd0af75cbcbacede603fd19a109dcf060caa31` | `abdd0af75cbcbacede603fd19a109dcf060caa31` | **MATCH** |
| `alembic/versions/k5l6m7n8p9q1_baselines_inflight_unique_index.py` | `f1feb8e15ab855d7d1a180ec7f27846b42d73e62` | `f1feb8e15ab855d7d1a180ec7f27846b42d73e62` | **MATCH** |

**Parity verdict: 20/20 MATCH — full parity. AUDIT-4B-8's file-drift claim is INVALIDATED.** The residual (no build-commit marker; beat schedule file in the container FS) is recorded in §1. Note especially that `worker/scan_tasks.py`'s container hash `a6878b37…` is *exactly* the value Phase 4B recorded as HEAD's — so the container is now byte-identical to the file 4B was auditing, and 4B's "deployed `scan_tasks.py` predates Phase 11" caveat no longer applies to any finding in its set.

---

## 4. Extra deliverable — Dead Code & Orphan Routines

**Method.** A repo-wide `\b<symbol>\b` grep across `backend/app`, `backend/worker`, `backend/tests`, `backend/tools`, `backend/alembic`, `scripts`, `docs`, `frontend/src` for 100 symbols in the orchestration spine, plus `ruff --select F401,F811,F841,ARG,B,SIM,RET,C901` over the 14 in-scope production files (read-only). A symbol with ≤ 2 hits is reviewed by hand.

| file:line | symbol | kind | proof (grep hits) |
|---|---|---|---|
| `worker/celery_app.py:49-52` | `wardress.ping` | **orphan task registration** | 3 hits repo-wide: its own definition, `tests/test_smoke.py:28`. **No production sender.** Appears in the live `celery inspect registered` list. → AUDIT-SA3-12 |
| `app/services.py:198` | `create_site(via)` | **dead parameter** | `via` appears only on the signature line inside the function; `record_audit` at `:262-271` passes no `via`. 4 call sites pass a value (`sites.py:123` `"dashboard"`, `tools.py:531` `ctx.surface`, …). Independently confirmed by `ruff ARG001`. → AUDIT-SA3-9 |
| `app/services.py:290` | `trigger_scan_now(via)` | **dead parameter** | same as above; `record_audit` at `:352-360`; 3 call sites (`sites.py:360`, `tools.py:476`, `telegram_bot.py:313`). `ruff ARG001`. → AUDIT-SA3-9 |
| `app/services.py:381` | `rebaseline_site(via)` | **dead parameter** | same as above; `record_audit` at `:434-442`; 3 call sites (`sites.py:342`, `tools.py:542`, tests). `ruff ARG001`. → AUDIT-SA3-9 |
| `worker/db.py:16` | `pool_pre_ping=True` | **unreachable config** | Semantically dead: a fresh engine's first checkout is a new connect, which SQLAlchemy never pings. Proved by test (`pool._pre_ping is True`, `pool._recycle == -1`, two distinct engines per call). → AUDIT-SA3-11 |
| `worker/celery_app.py:14` | `backend=REDIS_URL` on the worker | **unused subsystem** | `app/tasks.py:33` sets `backend=None` with the comment "the API never consumes task results"; no consumer of `AsyncResult` exists anywhere. Costs a 215 ms first-publish setup + a `SETEX` per task + ~500 KB/day of 24 h-TTL keys. → AUDIT-SA3-4, AUDIT-SA3-12 |
| `worker/beat_tasks.py:71` | `REDELIVERY_MAX_PER_RUN` | **untested constant** | 3 hits, all inside `beat_tasks.py` (`:71`, `:348`, `:367`). No test anywhere references it, so the 200-per-run cap has never been exercised or asserted. |
| `app/scanning.py:37` | `RELAX_FACTOR` | single-use constant | 2 hits, both in `scanning.py` (definition + `next_interval_after_scan:74`). Not dead; documented here only because the 1.5 factor is the *entire* recovery-ladder length that AUDIT-4B-3's 4-clean-scan threshold depends on — worth a named test. |
| `app/db.py:18-22` | `get_engine()` | private accessor | 2 hits, both in `db.py`. Called only by `get_session_factory`. Correctly private; not a finding. |
| `worker/beat_tasks.py:409-411` | `_run_with_session(fn)` | 2-call helper | 3 hits, all in `beat_tasks.py` (used by `expire_agent_actions` and `sync_model_catalog`). Not dead. |
| `worker/scan_tasks.py:66-75` | `_escalation_new_text` | single-use helper | 2 hits, both in `scan_tasks.py`. Used once at `:321`. Not dead, and it *is* covered (`test_llm_*`). |
| `worker/scan_tasks.py:224-235` | `_load_suppression` | single-use helper | 2 hits. Used once at `:297`. Not dead; covered by `test_suppression.py`. |
| `worker/scan_tasks.py:390-404` | `_create_remediations` | single-use helper | 2 hits. Used once at `:362`. Not dead; covered by `test_phase4_alerting.py`. |
| `worker/alert_tasks.py:47` | `TOP_SIGNALS` | single-use constant | 2 hits (`alert_tasks.py:47`, `:60`). Correctly pins the alert body's "top 4 signals". |
| `worker/alert_tasks.py:63-66` | `_channel_config` | single-use helper | 2 hits. Used once at `:138`. Not dead. |
| `app/main.py:41` | `lifespan(app)` | unused argument | `ruff ARG001`. FastAPI lifespan signature — **not a finding**. |
| `worker/beat_tasks.py:414-415` | `setup_periodic_tasks(sender, **kwargs)` | unused `kwargs` | `ruff ARG001`. Celery `on_after_finalize` signal signature — **not a finding**. |
| `worker/beat_tasks.py:240-291` | `_cleanup_orphan_artifacts` | **incomplete predicate** | `ruff C901` complexity 13 (highest in the subsystem). Not dead code, but the complexity is where the AUDIT-SA3-3 defect lives: the `existing` set at `:271-277` has no status filter. |

**Summary: no genuinely unreachable function, unused import, or orphan branch was found in the orchestration spine.** All 100 symbols resolve to at least one real use. The orphans are *configurations* and *parameters*, not routines: one unused task registration, one unused result backend, one unreachable pool setting, and three dead `via` parameters. `ruff` found no `F401` (unused import), `F841` (unused variable), or `B` (bugbear) issues in any of the 14 in-scope production files. The only `C901` complexity outliers are `_cleanup_orphan_artifacts` (13), `create_site` (12), `_run_scan` (11), and one `__call__` (11) — all at or just over the threshold of 10, and all already documented by their own inline comments.

---

## 5. Extra deliverable — Opportunities for Optimization

| # | proposal | target file(s) | measured / projected impact | risk |
|---|---|---|---|---|
| 1 | **Do NOT add an index for the dispatcher's due-site query — the existing one is already optimal.** Verified with `EXPLAIN (ANALYZE, BUFFERS)`, 3 passes per size, `ANALYZE` run first: `Index Scan using ix_sites_next_scan_at` (no Sort node), 4–5 shared buffers hit. | `app/models.py:245`, `beat_tasks.py:128-140` | **100 sites:** Seq Scan 0.10–0.18 ms (correctly chosen, 2 buffers) · **1 000:** Index Scan 0.066–0.134 ms · **5 000:** 0.086–0.101 ms · **20 000:** 0.085–0.127 ms. A hypothetical partial index `ON sites(next_scan_at) WHERE is_active AND auto_scan_enabled` gave **0.076–0.197 ms — statistically indistinguishable**. **This optimisation is INVALIDATED by measurement.** | none — do not do it |
| 2 | **Batch the dispatcher's per-site work**: one `UPDATE … WHERE id IN (…) AND next_scan_at = ANY(seen)` for all 50 claims, one bulk baseline `SELECT … WHERE site_id IN (…) AND is_current AND status='ready'`, one bulk in-flight `SELECT … WHERE site_id IN (…) AND status IN (pending,running)`, one bulk `INSERT … RETURNING id`. | `worker/beat_tasks.py:155-221` | Collapses ~7 sequential round trips/site into ~4 round trips total. Measured per-site cost is **26.1 ms** (1 378.6 ms ÷ (50 − overhead)) at the 50-site cap; batching projects **1 380 ms → ~120 ms** (≈ 11×). Not needed for correctness (the 420 s soft limit is 300× away) but it removes the tick as a scaling consideration entirely and makes a much higher `MAX_DISPATCH_PER_TICK` safe. | **Medium.** The per-site CAS claim and its per-site error isolation are load-bearing (4B verified overlapping-tick arbitration live, `test_phase37` pins it). Batching must preserve: (a) per-site `rowcount` arbitration — needs a `RETURNING` clause, (b) per-site error isolation — a batched statement has no per-site isolation, (c) the `plan`-before-write discipline at `:146-153` that the comment at `:143-145` documents as essential to avoid touching expired ORM instances. Recommend as a **follow-on**, not a first change. |
| 3 | **Give the worker's publish path a fail-fast bound** matching `app/tasks.py`: `broker_transport_options={"max_retries": 2, "interval_start": 0.1}` (or `broker_connection_max_retries` reduced). | `worker/celery_app.py:23-46` | **Measured**: removes a **10.7 s → 63.8 s per-call** blocking tax on every publish while the broker is down. Directly de-fuses the AUDIT-SA3-4 consequences (the tick dying at site ~7; the 400-message resweep being SIGKILLed). | **Low** — the same options the API already uses in production. |
| 4 | **Drop the worker's unused result backend** (`backend=None` + `task_ignore_result=True`), mirroring `app/tasks.py:33`. | `worker/celery_app.py:14`, `:23-46` | **Measured**: removes the ~215 ms first-publish result-consumer setup, the per-completion `SETEX`, and ~500 KB/day of 24 h-TTL keys. Also removes the source of the `RuntimeError("must be restarted")` confusion. | **Medium** — must first confirm nothing reads `AsyncResult` (grep found none) and that `scripts/validate.ps1`'s use of `wardress.ping`, if any, does not depend on a result. |
| 5 | **Pool the worker's engine per child**: module-level lazily-created engine (safe post-fork), pinned `pool_size=1, max_overflow=0`. | `worker/db.py:14-22` | **Measured**: 87.98 ms → 6.59 ms per task (13×), ≈ 81 ms × ~2 400 tasks/day ≈ **195 s/day**. | **Medium** — the `pool_size` pin is **mandatory**: the default `5 + 10` per child × 12 children = 180 > `max_connections=100`. The current 27/100 arithmetic is only safe *because* each task uses exactly one connection on a disposable pool. |
| 6 | **Cap `expires` at ≥ 2× interval for the four 1× tasks** (or set `expires=None`, which is free here because every periodic task is idempotent by design). | `worker/beat_tasks.py:414-447` | Removes the silent drop of a single delayed tick for `resweep_undelivered`, `expire_agent_actions`, `cleanup_orphan_artifacts`, `sync_model_catalog`. `expires` at 1× interval means a tick delayed by one interval is discarded with **no log line at any level** (Celery `worker/strategy.py:162`). | **Low** — `expires=None` is the semantically right answer for idempotent sweeps, but it would let a stale janitor fire hours late; prefer `expires = 2 × interval` for a mechanical fix. |
| 7 | **Fix the artifact janitor's predicate to reclaim `failed` rows' trees.** | `worker/beat_tasks.py:271-277` | Reclaims 100 % of AUDIT-SA3-3's stranded bytes. Measured: the janitor already works perfectly for genuinely-orphaned trees (`removed == 1` in the test's positive control); only the status filter is missing. | **Low** — one predicate change. Verify no reader consumes a failed row's `html_path`/`screenshot_path` (grep: `_baseline_page_data` only reads `is_current` + `ready` rows). |
| 8 | **Add a retention beat task** (daily): prune `scans` older than N days except `flagged`/acknowledged, cascade `scan_findings`, and delete the matching artifact trees in the same sweep. | new `worker/beat_tasks.py` task + an `alembic` revision if a `superseded`/`reason` column is added | Projects ~9.6 GB/day of artifact growth to a bounded steady state at 500 sites/60 min. Must be composed with #7 so the two sweeps agree on what "reclaimable" means. | **Medium** — deleting artifacts removes the ability to re-verify an old verdict, so the retention window and the "never delete a flagged scan" rule are product decisions, not engineering ones. Surface for the user. |
| 9 | **Release (or mark) the dispatcher's claim when the publish fails.** | `worker/beat_tasks.py:202-213` | Converts AUDIT-SA3-1's silent one-interval gap into a same-tick visible failure, and lets the next tick dispatch normally. Marking the provably-dead `pending` row `failed` with an explicit reason is the minimal form. | **Low** — the row provably never ran (the message was never created), so failing it is strictly correct. |
| 10 | **Route the dispatcher's `IntegrityError` through `services.scans_inflight_unique_violation`** and count it as `skipped_inflight` (or a new `lost_race` bucket). | `worker/beat_tasks.py:214-221`, `app/services.py:122-126` | Makes the lost-race arbitration visible in the tick's return value and on the health page, matching the API's existing 409 behaviour. | **Low** — the arbiter already works; this adds a signal. |
| 11 | **Write the dispatch heartbeat on the error path too**, with a distinct key, and have the health page report "beat alive" and "tick executing" separately. | `worker/beat_tasks.py:225-237`, `app/routers/health.py:123-134` | Fixes the false "Beat stalled" during DB outages (AUDIT-4B-6's new mechanism) and lets the beat container write its own liveness key (4B's original remedy, still not shipped). | **Low** — additive; the existing key's semantics stay intact. |
| 12 | **Pin `-c` on the worker CMD** and document host RAM per concurrent scan. | `backend/Dockerfile.worker:36`, `docker-compose.yml:89-116` | **Measured**: a fully warm child is a **non-reclaimable** 624.5 MB (390 MB marginal over the forked parent); 12 warm children ≈ **5.90 GiB against a 7.429 GiB ceiling (79 %)**. `-c 4` would cap that at ~2.9 GiB. | **Low** — trades scan throughput for memory headroom; the right value is a capacity decision, and the number is now available to make it with. **Note: `--max-tasks-per-child` does NOT help** (the memory is not returned by GC — measured), so it should not be reached for. |
| 13 | **Add a `worker` healthcheck and `beat: depends_on: db: service_healthy`; add `--appendonly yes` and an explicit `--maxmemory` to redis.** | `docker-compose.yml:23-32, 89-131` | Makes the OOM-spiral failure mode observable (currently invisible to Docker, `compose ps`, and the restart policy), fixes the cold-start tick-before-DB race, and bounds Redis growth deterministically instead of via the host OOM killer. | **Low** — compose-only, no code. |
| 14 | **Fold `via` into the three orchestration `record_audit` `after` dicts**, exactly as `mute_site:531` already does. | `app/services.py:262-271, 352-360, 434-442` | Restores surface attribution for `site.create` / `scan.now` / `site.rebaseline` in the audit log. | **Low** — mechanical. |
| 15 | **Set `verdict = ScanVerdict.error` on the `missing-prereqs` branch.** | `worker/scan_tasks.py:252-255` | One line; removes the only failed scan row with a NULL verdict. | **Low** — one line. |
| 16 | **Add a `migrate` one-shot compose service** that `app`/`worker`/`beat` depend on, running `alembic upgrade head`. | `docker-compose.yml`, `Dockerfile.app` | Closes AUDIT-SA3-8. Safe to build on, because **all 16 revisions are verified reversible** (§2) — the round-trip is tested. | **Low–Medium** — changes startup ordering for the whole stack; the scripts' behaviour must stay idempotent with it. |

---

## 6. Verified-clean ledger (things the brief asked me to check that turned out NOT to be problems)

These are Rule-4 "proven, not asserted" results too. They are not findings; they are the negative half of the audit and they are what makes the findings above credible.

| Area checked | Verdict | Evidence |
|---|---|---|
| **Alembic downgrade of every migration** | **All 16 PASS, zero residue, `alembic check` clean** — on empty *and* fully populated databases | §2 |
| **Deployment parity** | **20/20 files byte-identical to HEAD** | §3 |
| **DB connection-pool exhaustion** | **Not reachable.** 12 worker connections (1/task, disposable pool) + 15 app (`size=5`+`max_overflow=10`) + 0 beat = **27 of `max_connections=100`**; 7 in use at rest. `pool_pre_ping` on the API's long-lived pool *is* the correct protection against the stale-connection-after-restart class. | `docker exec wardress-db-1 psql "SHOW max_connections"`; live pool introspection (`AsyncAdaptedQueuePool size=5 max_overflow=10 timeout=30.0`) |
| **Visibility timeout vs hard limit vs STALE_INFLIGHT, for EVERY task** | **`480 < 600 < 3600` holds for all 10 registered tasks.** `broker_visibility_timeout` is unset → kombu's redis `Channel.visibility_timeout = 3600` (7.5× the hard limit), so **no task can be redelivered while running** — the duplicate-execution concern is unreachable. `broker_transport_options == {}` confirms nothing shortens it. | live `celery inspect stats`; `celery_conf_dump.py`; `kombu/transport/redis.py:644`; `test_blanket_time_limit_bounds_every_task_including_the_daily_janitor` (PASSING) |
| **What happens if a task legitimately exceeds the visibility timeout** | **It cannot** — `task_time_limit=480` is enforced by a `SIGKILL` to the child, well under 3 600 s. And `task_acks_on_failure_or_timeout=True` + `task_reject_on_worker_lost=None` (default False) mean a hard-killed task is **ACKed, never redelivered** — the DB stale sweep is the sole recovery, consistently, for every task. | live conf dump (`task_acks_on_failure_or_timeout = True`) |
| **Dispatcher due-site query index coverage** | **Already optimal — no index gap.** Index Scan, no Sort, 4–5 buffers, 0.066–0.134 ms from 1 000 to 20 000 sites; a partial index is indistinguishable. **This proposed optimisation is INVALIDATED.** | §5 #1 |
| **Celery result-backend retention** | **Bounded.** `result_expires = 1 day` (Celery default), verified live: 22 keys with TTLs 85 412–86 374 s decaying correctly, 182–281 B each, ~500 KB/day. Not a growth finding (the *waste* is — AUDIT-SA3-12). | live `redis-cli TTL`/`STRLEN` over all 22 keys |
| **Redis unacked / queue depth** | **Empty at rest** — `LLEN celery 0`, `ZCARD unacked 0`, `ZCARD unacked_index 0`, `DBSIZE 26`. No stranded messages. | live `redis-cli` |
| **`IntegrityError` escaping to the request path** | **It does not**, on any of the three service entry points. Second `scan-now` → 409, second `rebaseline` → 409, `create_site` → 409, all via the named predicates at `services.py:115-139`. The **dispatcher** is the only path that swallows it unreported (AUDIT-SA3-6). | SEAM 5 probe; `test_phase18_concurrency_races.py` 8 tests green |
| **FK cascade during concurrent site deletion + scan completion** | **Clean in all three orderings** — scan-first (cascade removes both, no dangling), site-first (`scan-row-missing`), baseline-deleted-under-a-running-scan (`missing-prereqs`, no exception escapes). | `test_concurrent_site_delete_during_scan_completion_is_clean` (PASSING) |
| **`_schedule_next` swallow-all never fails a scan** | **Confirmed.** Called with a session whose *first attribute access* raises: no exception escapes, no state change. (And the swap is a silent cadence collapse, not a no-op — AUDIT-SA3-5.) | `test_schedule_next_swallow_never_fails_a_scan_but_leaves_interval_unchanged` (PASSING) |
| **Beat tick jitter / missed-tick behaviour under load** | **Quantified, not soaked.** Measured live mean **64.18 s** vs nominal 60 s (+7 % drift) over 17 ticks. The healthy-path cost is bounded at **1.38 s** for a full 50-site tick (3 passes: 1.215 / 1.310 / 1.399 s) versus a 420 s soft limit — so the tick's *own* work can never hit the limit with a healthy DB. The saturation exposure is the 63.8 s broker block (AUDIT-SA3-4), a different failure mode. | §1 AUDIT-4B-2/4B-6; `test_beat_tick_at_the_50_site_cap_is_far_below_the_soft_time_limit` (PASSING) |
| **Idempotency of every beat task on restart** | **Confirmed for all five.** `dispatch_due_scans` (CAS claim + advance-before-enqueue + per-site error isolation), `cleanup_orphan_artifacts` (row-existence keyed, so re-running is a no-op), `expire_agent_actions` (`expire_stale` is a pure TTL predicate), `resweep_undelivered` (downstream tasks are idempotent by design), `sync_model_catalog` (upsert). The beat schedule file being lost on container recreate is therefore benign — as 4B noted. | code-trace + `test_scheduler.py` green + `test_phase4b_orchestration_repros.py` green |
| **`MAX_DISPATCH_PER_TICK = 50` vs real worker throughput** | **Ample headroom, quantified.** Supply = `12 × 86400 / S` scans/day: 17 280 at S=60 s, 8 640 at S=120 s, **2 160 at the 480 s hard limit**. Demand = `fleet × 1440 / interval`. The cap of 50/tick = 3 000 enqueues/minute, which is ~25× the 120 s-supply figure. The cap only binds at ~2 160+ sites, and even then the binding constraint is the stale-sweep, not the cap. | §1 AUDIT-4B-2 arithmetic |
| **Redis memory growth over time** | **Bounded and small today** (2.00 MiB used, 2.03 MiB peak, 24 h-TTL result keys, empty queue). The *future* risk is unbounded, but via the **`noeviction` + `maxmemory 0`** combination rather than via a leak — AUDIT-SA3-13. | live `redis-cli INFO memory` |
| **Unbounded table growth** | **FOUND — AUDIT-SA3-2** (High). Not in Redis, in Postgres + the artifacts volume: `scans`, `scan_findings`, artifacts, `alerts`, `alert_deliveries`, `remediation_executions`, `audit_log` all grow monotonically with no retention anywhere in the repository. | §1 AUDIT-SA3-2 |


---

## 7. Summary

### 7.1 Counts by classification

| Classification | Count | IDs |
|---|---|---|
| **CONFIRMED** | 1 | AUDIT-4B-4 |
| **DEEPENED** | 6 | AUDIT-4B-1, AUDIT-4B-2, AUDIT-4B-3, AUDIT-4B-5, AUDIT-4B-6, AUDIT-4B-7 |
| **NEW** | 13 | AUDIT-SA3-1 … AUDIT-SA3-13 |
| **INVALIDATED** | 1 | AUDIT-4B-8 (file drift; residual schedule-file note retained as Low) |
| **Total findings** | **21** | |

### 7.2 Severity distribution (exactly one severity each, per §6.4)

| Severity | Count | IDs |
|---|---|---|
| **Critical** | **0** | — |
| **High** | **5** | AUDIT-4B-1 (unchanged from 4B); AUDIT-SA3-1, AUDIT-SA3-2, AUDIT-SA3-3, AUDIT-SA3-4 (new) |
| **Medium** | **8** | AUDIT-4B-2 (4B), AUDIT-4B-3 (4B), AUDIT-4B-5 (escalated; scan half was 4B's Low), AUDIT-4B-6 (escalated from 4B's Low); AUDIT-SA3-5, AUDIT-SA3-6, AUDIT-SA3-7, AUDIT-SA3-8 (new) |
| **Low** | **8** | AUDIT-4B-4 (4B), AUDIT-4B-7 (4B), AUDIT-4B-8 residual; AUDIT-SA3-9, AUDIT-SA3-10, AUDIT-SA3-11, AUDIT-SA3-12, AUDIT-SA3-13 (new) |

5 + 8 + 8 = 21 = the total finding count.

**Severity changes vs the original phases** (both escalations argued in their finding blocks; nothing was deflated):
- **AUDIT-4B-5 Low → Medium** for the baseline half: a lost baseline-capture enqueue renders a site permanently inert, and the tick reports it as a benign `skipped_no_baseline` forever.
- **AUDIT-4B-6 Low → Medium**: the heartbeat is skipped on *any* dispatcher failure (not only worker saturation), so a plain database outage makes the operator's only scheduling signal go red while the stack is otherwise healthy.

### 7.3 New test files added

**`backend/tests/test_phase_sa3_orchestration_deep.py`** — **22 tests, ALL committed-passing: 0 failed, 0 skipped, 0 xfail.** Fully deterministic and hermetic — every test uses the suite's real-Postgres alembic-migrated harness, stubs `celery_app.send_task` at module level, and none touches the network or a real broker.

| # | test | proves |
|---|---|---|
| 1 | `test_4b1_unrecoverable_alert_window_is_measured_and_bounded` | AUDIT-4B-1: 5-pass measurement of the post-terminal-commit handoff (steady median 10.10 ms) + positive control that 5 alerts were created |
| 2 | `test_dispatch_claim_survives_a_failed_enqueue_and_silently_skips_the_site` | **AUDIT-SA3-1**: a failed publish leaves the claim advanced, the Scan row `pending`, and **no** stats bucket for the loss |
| 3 | `test_pending_row_from_a_lost_publish_only_recovers_after_a_full_interval` | **AUDIT-SA3-1**: the orphan recovers only after a full interval *and* `STALE_INFLIGHT` |
| 4 | `test_failing_schedule_next_leaves_the_site_due_and_rescans_every_tick` | **AUDIT-SA3-5**: the scan is unaffected, the schedule is untouched, the next tick re-dispatches |
| 5 | `test_schedule_next_swallow_never_fails_a_scan_but_leaves_interval_unchanged` | the swallow-all wrapper cannot raise, and hides the state change (4B's clean-ledger claim, re-proven) |
| 6 | `test_dispatcher_inflight_index_violation_is_absorbed_into_no_stat_bucket` | **AUDIT-SA3-6**: a deterministically-won `IntegrityError` race, absorbed into `lost_claim=0` |
| 7 | `test_the_raw_index_violation_itself_is_what_the_dispatcher_swallows` | the arbiter is the partial unique index; a `completed` row does not consume the slot |
| 8 | `test_stuck_pending_baseline_is_never_touched_by_any_beat_task` | **AUDIT-4B-5 (baseline half)**: 30-min `pending`+`capturing` survive all four periodic tasks; a fresh one 409s; a stale one needs an operator |
| 9 | `test_no_baseline_skip_advances_the_schedule_so_a_late_baseline_waits_an_interval` | **AUDIT-4B-5**: `skipped_no_baseline` burns a full interval and is reported as benign |
| 10 | `test_dispatch_heartbeat_is_skipped_whenever_the_tick_body_raises` | **AUDIT-4B-6**: the heartbeat is written on the success path only; a DB-level failure writes nothing |
| 11 | `test_heartbeat_ttl_exceeds_the_health_pages_stale_threshold` | AUDIT-4B-6 support: TTL 600 s > `_BEAT_STALE` 300 s, so frequency is the constraint |
| 12 | `test_every_periodic_task_expires_exactly_at_its_own_interval` | **AUDIT-4B-6**: 4 of 5 periodic tasks have `expires == interval`; pinned against Celery's own silent drop site (`worker/strategy.py:162`, `Request.maybe_expire`) |
| 13 | `test_redelivery_grace_equals_the_redelivery_sweep_period` | the `REDELIVERY_GRACE == REDELIVERY_SWEEP_SECONDS == 300 s` coupling with no margin |
| 14 | `test_blanket_time_limit_bounds_every_task_including_the_daily_janitor` | `480 < 3600` for every registered task; no task overrides the limits; the 24 h janitor and 12 h catalog refresh are bounded to 480 s too |
| 15 | `test_worker_publish_has_no_fail_fast_bound_while_the_api_client_does` | **AUDIT-SA3-4**: worker has `broker_transport_options={}` + `max_retries=100`; API has `max_retries=2, interval_start=0.1` |
| 16 | `test_task_session_builds_a_fresh_engine_per_call_making_pre_ping_a_noop` | **AUDIT-SA3-11**: distinct engine per call, `pre_ping` unreachable, `recycle=-1`, and fresh 87.4 ms vs pooled 6.9 ms |
| 17 | `test_no_retention_policy_exists_for_scans_findings_or_artifacts` | **AUDIT-SA3-2**: no module deletes `Scan`/`ScanFinding`; prints the 30-day growth projection |
| 18 | `test_failed_capture_artifacts_are_orphaned_forever` | **AUDIT-SA3-3**: a `failed` row's artifact tree survives the janitor; a row-less tree is removed (positive control) |
| 19 | `test_concurrent_site_delete_during_scan_completion_is_clean` | **AUDIT-SA3-10** (`verdict is None`) + the FK-cascade question in all three orderings |
| 20 | `test_beat_tick_at_the_50_site_cap_is_far_below_the_soft_time_limit` | 3 passes at the 50-site cap: 1.215 / 1.310 / 1.399 s vs a 420 s soft limit |
| 21 | `test_cadence_tighten_ignores_degraded_channels_and_has_no_floor` | **AUDIT-4B-3**: `_schedule_next` never reads `degraded`; the 5-minute floor is reachable |
| 22 | `test_queue_depth_primitive_exists_but_scheduling_never_reads_it` | AUDIT-4B-2/4B-6 support: `_queue_depth` exists in the health router and is never read by the dispatcher |

### 7.4 Full regression results (Rule 5)

Every run used `$env:WARDRESS_TEST_DATABASE_URL = "postgresql+asyncpg://wardress:wardress@127.0.0.1:5433/wardress_sa_orch_test"`. No bare `pytest` was ever invoked.

| command | result |
|---|---|
| `uv run --frozen alembic heads` | `o9q1r2s3t4u5 (head)` |
| `uv run --frozen alembic history` | 16 revisions, single head, linear chain `<base> -> 76f6f5dcf922 -> … -> o9q1r2s3t4u5` |
| `uv run --frozen alembic check` (pre-sweep) | `No new upgrade operations detected.` |
| `alembic_sweep.ps1` (16 stepwise downgrades, empty DB) | all 16 `exit=0`; `NOW_AT` matched the target revision every step |
| `alembic_base_residue.ps1` (`downgrade base` + residue enumeration) | `exit=0`; residue = `alembic_version` + `alembic_version_pkc` only; 0 tables / 0 indexes / 0 sequences / 0 user enums |
| `alembic_data_probe.py seed` | 1 row in each of all 23 tables |
| `alembic_populated_sweep.ps1` (16 stepwise downgrades, populated DB) | all 16 `exit=0`, every `NOW_AT` correct |
| `alembic_populated_sweep.ps1` (`upgrade head` round-trip) | all 16 upgrades re-applied cleanly; row counts 0 (data dropped by design) |
| `alembic check` (post-round-trip) | `No new upgrade operations detected.` |
| `uv run --frozen pytest tests/test_phase_sa3_orchestration_deep.py -q -s` | **22 passed** in 26.96 s |
| `uv run --frozen pytest tests/test_phase_sa3_orchestration_deep.py tests/test_scheduler.py tests/test_scan_tasks.py tests/test_tasks_enqueue.py tests/test_phase4b_orchestration_repros.py tests/test_phase18_concurrency_races.py tests/test_phase37_scheduling_agent_remediation.py tests/test_noise_floor.py tests/test_remediation_claim_race.py tests/test_phase19_alert_ack_race.py tests/test_phase4d_delivery_repros.py tests/test_phase4_alerting.py tests/test_services.py -q` | **157 passed in 212.42 s** — 0 failed |
| `uv run --frozen pytest -q -p no:warnings` (FULL suite) | **1 457 passed, 10 deselected, 6 errors in 1 866.84 s (31:06)** |
| `uv run --frozen ruff check tests/test_phase_sa3_orchestration_deep.py` | `All checks passed!` (after fixing 6 self-introduced lint issues: 2 unused imports, 3 unused locals, 1 unused loop var) |
| `uv run --frozen ruff check --select F401,F811,F841,ARG,B,SIM,RET,C901 --no-cache <14 in-scope production files>` | 9 pre-existing hits, all reviewed: 3 × `ARG001` unused `via` (→ AUDIT-SA3-9), 2 × `C901` complexity, 2 × `ARG001` framework signatures, 1 × `C901`, 1 × `ARG001 kwargs`. **No `F401`, no `F841`, no bugbear findings in production code.** |
| `docker stats --no-stream` (before and after all probes) | `wardress-app-1`, `-worker-1`, `-beat-1`, `-db-1`, `-redis-1` all `Up`; worker 1.308 GiB before and after → **the shared stack was not perturbed** |

**Honest note on the 6 full-suite errors (Rule 16):** all 6 are in `backend/tests/test_session_a2_detection_findings.py` — a **concurrent sibling subagent's** file, written during this same session (mtime 09:46). The errors are a Windows-specific pytest-teardown limit, not an orchestration issue and not a regression from my work: pytest's `_update_current_test_var` writes the test's parametrized ID into the `PYTEST_CURRENT_TEST` environment variable, and that subagent's `test_normalize_html_never_raises[huge_attribute_value-…]` / `[deeply_nested_divs-…]` / `[iso_bomb-…]` IDs embed multi-kilobyte HTML strings, so the value exceeds Windows' 32 767-character environment-variable ceiling and `os.environ[...] = value` raises `ValueError` in teardown. The assertions themselves all passed (the failure is in the teardown hook, `_pytest/runner.py:198`). My file contributes 22 passing tests and, in the 13-file orchestration batch, the suite is 157/157 green. **Flagged to the coordinator as a cross-session interaction, not claimed as mine and not counted against my subsystem.**

### 7.5 Scratch probes written (Rule 10 — outside the repo, never committed)

All under `C:\Users\Ns8pc\AppData\Local\Temp\opencode\wardress-session-a\orchestration\`:

| file | what it proves |
|---|---|
| `alembic_sweep.ps1` | 16 stepwise downgrades on an empty DB |
| `alembic_base_residue.ps1` | `downgrade base` + full residue enumeration |
| `alembic_data_probe.py` | seeds 1 row in all 23 tables; `seed`/`verify` modes |
| `alembic_populated_sweep.ps1` | 16 stepwise downgrades on a populated DB + `upgrade head` round-trip |
| `parity.ps1` | `docker cp` + `git hash-object` parity for 20 files (AUDIT-4B-8) |
| `celery_conf_dump.py` | the full effective Celery conf + per-task time limits |
| `measure_orchestration.py` | 4B-1 window (5 passes), tick cost curve (3 passes/size), `EXPLAIN`, engine-churn timing |
| `measure_query_plan.py` | `EXPLAIN (ANALYZE, BUFFERS)` at 100/1 000/5 000/20 000 sites, with and without a hypothetical partial index (3 passes each) |
| `probe_broker_poisoning.py` | broker outage: does the app get permanently poisoned? (answer: no) |
| `probe_broker_blocking.py` | broker outage: the per-call blocking cost (6 passes down, 4 up) |
| `probe_db_unreachable.py` | 5 seams: alert creation, mid-baseline (both sub-cases), mid-alert-publish, mid-dispatch-claim, IntegrityError → request path |
| `measure_child_memory.py` | per-child warm footprint, run in a throwaway container from the same image |
| `simulate_fleet.py` | 30-day fleet simulations for AUDIT-4B-2 and AUDIT-4B-3 |
| `deadcode.py` | repo-wide reference counts for 100 spine symbols |

### 7.6 Findings routed out of phase scope (for the correct later phase, not investigated here)

- **`agent_messages` / `agent_conversations` have no retention either** — the same class as AUDIT-SA3-2, but the agent subsystem is out of blast radius per §0. Noted for completeness.
- **`i3j4k5l6m7n8`'s *upgrade* deletes duplicate `sites` rows (and cascades their baselines/scans/alerts)** with no operator-facing warning — an Alembic finding (mine), but the operator-communication side belongs to Phase 9's docs/ops drift sweep.
- **`scripts/validate.ps1` and the other PowerShell lifecycle scripts** (resource thresholds vs a 12-child pool, secret scrubbing, the `wardress.ping` question in AUDIT-SA3-12) — Phase 9 owns OPS-1..OPS-8; this session only supplied the memory number it needs.
- **`docs/*.mdx` drift** for the orchestration surface (the `celery_app.py` docstring's "acknowledge late so a crashed worker never silently drops a scan" mechanism claim, which 4B already found false) — Phase 9's DOC-1..DOC-8 sweep.
- **The `beat` schedule file in the container FS** — an operator-documentation item (AUDIT-4B-8 residual), Phase 9's compose-lifecycle scope.

### 7.7 Opportunities / Innovation ideas observed (Rule 17 — not severity-scored)

Beyond the 16 optimisation proposals in §5, three structural ideas this subsystem's shape suggests:

- **O-SA3-A — a scheduling-intent log.** The dispatcher already writes a `Scan` row before publishing (a good instinct), but the row records *what will be scanned*, not *what was claimed*. A `sites.dispatch_claim` audit (site_id, seen_next_scan_at, claimed_at, enqueued_at) would make every AUDIT-SA3-1 gap and every AUDIT-SA3-6 lost race reconstructable after the fact, and would let a future sweep release claims whose `enqueued_at` is NULL — turning the claim from a silent schedule mutation into a recoverable intent. It is the single change that closes both SA3-1 and the residual half of SA3-5, and it costs one table and one write.
- **O-SA3-B — a "coverage gap" surface.** Between AUDIT-4B-2 (a scan can be skipped for a full interval), AUDIT-4B-5 (up to 24 h 20 min before a stuck row is even examined), AUDIT-SA3-1 (a broker blip burns a full interval) and AUDIT-SA3-5 (a failed reschedule makes the site scan *more* often), the system can silently under- or over-scan a site in several unrelated ways. A single per-site "expected vs actual scan count over the last 24 h" number on the health page would make all four visible with one query, and needs no change to any of them.
- **O-SA3-C — make the beat container the liveness authority.** The beat process already runs in the app image, can reach Redis, and knows whether it published each tick. Having it write `wardress:heartbeat:beat` on every scheduler loop (independent of whether a worker executes anything) and having the tick write `wardress:heartbeat:tick` on completion would split the single overloaded signal into its two honest components, cost ~10 lines, and is the natural home for an expired-tick counter. 4B proposed the first half; the second half (the counter, which is what makes the silent `expires` drop visible) is the part that was missing.
