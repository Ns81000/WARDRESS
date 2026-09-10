# PROMPT-003 — Capture & Detection Audit — Implementation Log

> Dedicated progress log for the **PROMPT-003 audit-and-discovery effort**.
> One entry per audit phase. Each phase's agent appends its entry here after completing work.
> This file + `PROMPT-003-capture-detection-audit-and-stress-hardening.md` +
> `PROMPT-003-stress-site-catalog.md` are the entire state of this effort across sessions.
>
> **If it isn't written here, it did not happen.**
>
> Reminder (Rule 18/19 of the main file): every stress-test result needs a minimum of
> three passes with variance recorded, and every below-target metric needs an
> individually-investigated root cause per failing case — never an aggregate close-out.
> Reminder (§8 of the main file): this effort is not done until a Re-Audit & Sign-Off
> phase (inside whatever remediation prompt this effort spawns, if any) reaches a genuine
> Clean Bill of Health — a single "audit complete" entry below is not the finish line.

## Entry Format (each phase appends below, newest last)

```
### [DONE / PARTIAL] PROMPT-003 Audit Phase N — <phase title>

- **Prompt**: PROMPT-003-capture-detection-audit-and-stress-hardening.md
- **Session date**: YYYY-MM-DD
- **Assigned subsystem**: <per PROMPT-003 §4>
- **Traceability matrix rows** (Phases 1-2 only): full table — claim | Verified/Gap/Unverifiable/Deferred | evidence
- **Stress-test results** (Phases 5A/5B/5C/6/7/8 only): per-site or per-scenario table —
  pass 1 / pass 2 / pass 3 outcome, variance, and for every failure: individual root
  cause + Fix-candidate/Accepted-risk disposition (Rule 19 — no aggregate-only rows)
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
- **Next phase kickoff prompt**: (delivered in chat only — never written to this log)
```

---

*(Audit phase entries append below)*
### [DONE] PROMPT-003 Audit Phase 1 — Traceability Matrix: Capture Phases (PROMPT-002 Phases 1–7)

- **Prompt**: PROMPT-003-capture-detection-audit-and-stress-hardening.md
- **Session date**: 2026-09-10
- **Assigned subsystem**: §4 Audit Phase 1 — capture stack: `worker/stealth.py`, `worker/fetcher.py`, `worker/probe.py`, `worker/page_prepare.py`, `worker/banner_dismiss.py`, `worker/artifacts.py`, plus the persistence/surface seams they feed (`worker/scan_tasks.py`, `app/capture.py`, `app/models.py`, alembic `o9q1r2s3t4u5`, `app/routers/sites.py`, `app/routers/health.py`, frontend `health.tsx`/`site-detail.tsx` capture surfaces) and every test file named in the Phase 1–7 log entries.

- **Traceability matrix rows** (claim | Verified/Gap/Unverifiable/Deferred | evidence):

  **Phase 1 — Stealth**
  | Claim | Status | Evidence |
  |---|---|---|
  | Capture UA is realistic current-Chrome, unbranded | Verified | `stealth.py:64-67` (Chrome/152); `test_stealth.py::test_fetch_page_with_stealth_captures_local_site` asserts sent UA == `CAPTURE_USER_AGENT` and `"Wardress" not in ua` |
  | `BROWSER_LAUNCH_ARGS` = `--disable-blink-features=AutomationControlled` | Verified | `stealth.py:57-59`; webdriver-True (plain) vs webdriver-None (stealthed) side-by-side test |
  | playwright-stealth evasion + `navigator_languages_override` | Verified | `stealth.py:240-241` |
  | Supplementary init scripts (Permissions.query, plugins/mimeTypes normalization when the library patch did not land) | Verified | `stealth.py` `_SUPPLEMENTARY_INIT_JS`; fail-open try/catch per patch |
  | Context shape: locale en-US, tz America/New_York, light, 1366×768 | Verified | `stealth.py:69-72`; applied in `_capture_attempt` context construction |
  | `apply_stealth` BEFORE `new_page()` and BEFORE the SSRF route guard; guard is last word | Verified | order verified in `_capture_attempt` (stealth → context → `page.route(_make_ssrf_route_guard)`); `test_ssrf_route_guard_still_blocks_internal_after_stealth` proves the guard still blocks loopback post-stealth, allows under opt-in |
  | Graceful degradation when playwright-stealth absent (warn + no-op) | Verified | `stealth.py:232-238` + `stealth_available()`; `test_apply_stealth_missing_package_degrades_gracefully` (dummy context untouched) |
  | Probe keeps its OWN UA rotation, deliberately not stealthed (layer 7 raw-vs-render) | Verified | `probe.py:41-58` (desktop_chrome reference at Chrome/152, era-matched to capture UA); `test_probe_ua.py` era + rotation-contract tests |
  | Spec obligation "test_stealth.py: webdriver suppressed, UA unbranded, args applied, guard intact, e2e capture" | Verified | all present; re-executed green this session (see regression results) |
  | UA freshness is a one-time pin (no ongoing freshness mechanism) | Verified (observation, not a Gap) | lower-bound-only test (`capture_major >= 130`); carried as Rule-17 opportunity O-1 — no spec/log claim asserts ongoing freshness |

  **Phase 2 — Cloudflare challenge detection + probe UA refresh**
  | Claim | Status | Evidence |
  |---|---|---|
  | Challenge HTML never stored as content; persistent challenge = hard fail with user-safe `BOT_PROTECTION_ERROR` | Verified | `is_challenge_title`/`looks_like_challenge_page`/`_ChallengeUnsolvedError`; `test_fetch_page_raises_on_persistent_challenge` asserts the exact message through real `fetch_page` |
  | Indicator paths: canonical titles, challenge DOM classes, 403+`cf-ray` | Verified | unit tests per path + `test_fetch_page_raises_on_403_cf_ray_block_page` |
  | Bounded wait-and-recheck; solvable challenges auto-resolve into a real capture | Verified | `_wait_out_challenge` (deadline from remaining nav budget); `test_fetch_page_waits_out_auto_solving_challenge` (3200 ms scripted solve) |
  | LATEST main-frame response recorded (challenge reload makes goto's 403 stale) | Verified | `nav_responses` tracking; `fetcher.py:657-668` uses `nav_responses[-1]`; auto-solve test asserts 200 + real content |
  | No false positives on pages that merely mention markers in body text | Verified | `SIMILAR_TEXT_HTML` test (title/element-class-only indicators) |
  | Detection independent of stealth status | Verified | `test_challenge_detection_works_without_stealth` |
  | Probe UA strings refreshed Chrome/126→152, era-consistent; rotation keys pinned | Verified | `probe.py:41-58`; `test_ua_chrome_variants_match_the_capture_era`, `test_ua_keys_are_exactly_the_layer7_rotation` |
  | Phase-2→6 deviation: challenge-retry wait extends the FULL longer window (not the original nav budget) | Verified (documented deviation, honestly implemented) | deadline extension in retry path; pinned by `test_fetch_page_retries_unsolved_challenge_with_longer_wait` |

  **Phase 3 — Page preparation (scroll + stability)**
  | Claim | Status | Evidence |
  |---|---|---|
  | `auto_scroll_page`: 80%-viewport overlapping steps, growth/stall detection, hard 20 s cap, return-to-top | Verified | `page_prepare.py:62-136`; ScriptedPage unit tests + real-browser short/tall test (`scrollY == 0` after) |
  | `wait_for_content_stable`: innerHTML-length polling, 2-consecutive-polls stability, 5 s cap | Verified | `page_prepare.py:139-171`; unit tests |
  | Timing constants centralized in `stealth.py` (5 s settle, 20 s scroll cap, 300 ms step pause, 5 s/500 ms stability) | Verified | constants block; imported by fetcher/page_prepare |
  | Below-fold lazy content actually captured | Verified | `test_fetch_page_captures_lazy_below_fold_content` (marker exists in DOM only after a real scroll event) |
  | Evidence-dict key contracts stable (scroll 5 keys; stability 3 keys) | Verified | `test_page_prepare_evidence_keys_unchanged` + ScriptedPage assertions |
  | "Never raises" contracts (`auto_scroll_page`, `wait_for_content_stable`) — Audit Phase 1 directive | Verified | whole-body `try/except Exception` at `page_prepare.py:126` and `:169`; every path returns its evidence dict. Scope note: `except Exception` deliberately does not catch `BaseException` (`asyncio.CancelledError`) — cancellation correctly propagates to fail the task; no Exception-subclass path escapes |
  | Log deviation: height probe reads `documentElement` in addition to `body` (spec named body only) | Verified (documented Rule-12 deviation) | `_HEIGHT_PROBE_JS`/`_PAGE_HEIGHT_JS` use `Math.max(body.scrollHeight, documentElement.scrollHeight)`; logged with reasoning in the Phase 3 entry |

  **Phase 4 — Screenshot height cap + capture evidence**
  | Claim | Status | Evidence |
  |---|---|---|
  | `MAX_SCREENSHOT_HEIGHT = 16_384`; taller pages rasterize as a top-clip, still-valid PNG | Verified | `stealth.py:100`; `fetcher._take_screenshot`; real-browser PNG IHDR-dimension tests assert exactly 1366×16384 capped / full-height uncapped |
  | Rule-12 deviation: cap via `full_page=True` + page-coordinate clip (spec's literal `full_page=False`+clip clamps to viewport under pinned Playwright 1.61) | Verified (honestly met — empirically probed live, spec retro-corrected, test-pinned) | deviation note in `test_screenshot_cap.py` header; scripted-double test asserts exact kwargs `{"full_page": True, "clip": {..., "height": MAX_SCREENSHOT_HEIGHT}, "type": "png", "timeout": 45_000}` |
  | `FetchResult.capture_evidence` optional, defaults `None`, backward compatible | Verified | `test_fetch_result_capture_evidence_defaults_to_none`, `test_fetch_result_accepts_and_stores_capture_evidence` |
  | `capture_quality` classification (full/partial/degraded; informational only) | Verified | `_classify_capture_quality` unit tests (scroll-capped / unstable / screenshot-capped → partial; unmeasurable height → degraded); grep-verified NOTHING in `worker/detection/` reads `capture_quality` or `capture_evidence` — only `routers/health.py` summary + tests consume it |
  | `scans.capture_evidence` nullable JSONB migration, reversible | Verified | alembic `o9q1r2s3t4u5` (upgrade adds / downgrade drops); `models.py` nullable column carrying the "do NOT reuse layer_scores" contract comment |
  | Evidence persisted on the scan row; `layer_scores` per-layer contract untouched | Verified | `scan_tasks.py:329-339`; `_summarize_layer_scores` separate; persistence tests re-executed green this session |
  | Height probe fail-safe (probe failure → uncapped capture, quality `degraded`) | Verified | scripted `probe_fails` test; never fails the capture |

  **Phase 5 — Consent/cookie banner dismissal**
  | Claim | Status | Evidence |
  |---|---|---|
  | Two-phase design: pre-nav consent-cookie injection + post-load click dismissal | Verified | `inject_consent_cookies` before `goto`; `dismiss_banners` after the challenge gate and before `auto_scroll_page` (order verified: settle → challenge gate → dismiss → scroll → stability → html/screenshot) |
  | 13 curated CMP cookies; runtime materialization; scheme-aware `url=…` (never bare `domain:""`) | Verified | `materialize_consent_cookies` + `test_materialize_https_cookies_are_scheme_aware_without_bare_domain` (len == 13, names[0] == OptanonAlertBoxClosed) |
  | Secure-flagged cookies only on https; ports preserved; IPv6 bracketed; unusable URLs → `[]` | Verified | `test_materialize_sets_secure_cookies_only_on_https`, `test_materialize_preserves_explicit_port`, `test_materialize_brackets_ipv6_literals`, `test_materialize_rejects_unusable_urls` + real-browser `test_injected_cookies_carry_no_secure_flag_on_http` |
  | Curated selector list; main frame + consent iframes; shadow-DOM piercing | Verified | `DISMISS_SELECTORS` + `_frames` (main first, then children); real-browser banner / hidden-banner / iframe tests |
  | Bounded budget (`BANNER_DISMISS_TIMEOUT_MS` = 3 s); first pass instant, then ONE combined-selector wait for late banners | Verified | `dismiss_banners` deadline logic; bounded late-banner wait tests |
  | Evidence `{dismissed, selector, attempts}`; never raises; banner facts do NOT affect `capture_quality` | Verified | `dismissed=True` with `capture_quality == "full"` asserted in real-browser tests |
  | Cookie injection is per-attempt (retry gets a fresh context + fresh consent cookies) | Verified | injection inside `_capture_attempt`; `cookie-echo` e2e test proves cookies readable by the page |

  **Phase 6 — Transient-failure retry**
  | Claim | Status | Evidence |
  |---|---|---|
  | ONE retry, cap 2 total attempts; fresh browser/context/page per attempt; only `retry_count` survives | Verified | retry loop (attempts 1..2); `test_fetch_page_never_exceeds_two_total_attempts` (hang on every request → exactly 2 requests) |
  | Transient classifier: goto timeout / CONN_REFUSED / NAME_NOT_RESOLVED / CONN_RESET retry; BLOCKED_BY_CLIENT and unknown shapes permanent | Verified | `_classify_goto_failure` unit tests, both directions |
  | SSRF refusals never retried (decisions, not transient errors) | Verified | top-level gate before the loop; `except SSRFBlockedError: raise` pass-through; `test_fetch_page_still_refuses_blocked_urls` |
  | Reduced retry nav timeout + pause; challenge retry uses the LONGER wait (15 s > 10 s) | Verified | `test_retry_constants_shape` + `fast_retry_env` integration shapes |
  | `retry_count` rides in `capture_evidence` (exact key name per Phase-7 assembly) | Verified | `retry_count == 1` asserted in both the transient-timeout and challenge-retry e2e tests |

  **Phase 7 — Final evidence assembly + capture-health surfaces**
  | Claim | Status | Evidence |
  |---|---|---|
  | `capture_method_version` migration gate (positive int, only moves forward) in `app/capture.py` | Verified | `test_capture_method_version_is_a_positive_int`; stamped into every capture's evidence |
  | `stealth_applied` honestly DERIVED from `stealth_available()` (not hardcoded) | Verified | `stealth.py:246-252`; Phase-7 derivation test in `test_stealth.py` |
  | Evidence carries challenge detected/resolved booleans; a PERSISTENT challenge raises → no row ever stores resolved=False challenge state | Verified | `test_wait_out_challenge_*` triple (negative / resolved / raises-and-stores-nothing) |
  | `capture_wall_clock_ms` per attempt | Verified | evidence assembly in `fetcher.py`; asserted in the e2e evidence test |
  | Baselines stamp `capture_meta.capture_method_version` (evidence wins; constant = honest fallback for predating evidence) | Verified | `scan_tasks.py:139-156`; predating-evidence test in `test_scan_tasks.py` |
  | Re-baseline hint on site detail (absence = unknown, never old; strictly-below version hints) | Verified | `routers/sites.py::_rebaseline_hint` + 4 API tests incl. pre-versioning baseline |
  | Fleet `capture_quality_summary` (rows predating evidence uncounted, never zeroed into a bucket) | Verified | `routers/health.py:213-229` (counts scans, before latest-per-site dedup); API test + frontend `capture-health.test.tsx` (re-executed green this session: 4 passed) |
  | Frontend renders exactly the API's buckets (no invented zeros); re-baseline hint visible on site detail | Verified | `frontend/tests/capture-health.test.tsx` payload shapes + assertions |

  **The two named open questions (Audit Phase 1 spec directives)**
  | Directive | Status | Evidence |
  |---|---|---|
  | Phase-14-flagged "changed, not clean" deviation on benign dynamic content — resolved anywhere, or still open? | **Gap — still open** | AUDIT-1-1 below |
  | Individually-investigated per-site root causes for every below-target Phase-13 category (Cloudflare 5/6, Lazy 8/11, E-commerce 3/6)? | **Gap — aggregate close-out** | AUDIT-1-2 below |

- **Findings**:

    - **ID**: AUDIT-1-1
    - **Title**: Phase-14 "changed, not clean" deviation on benign dynamic content is STILL OPEN and is structurally embedded in the current verdict gate
    - **Severity**: High — per §6.4, a documented spec requirement simply not met (PROMPT-002 problem statement #2 and the Phase-14 entry's own flagged deviation). Not Critical because "changed" is not an alerting verdict (`flagged` drives alerts; `changed` does not page anyone) — the harm is operator-trust erosion and dashboard noise, and it directly contradicts the Phase-14 entry's promise that benign dynamic sites come out clean.
    - **Subsystem / file(s)**: `backend/worker/scan_tasks.py:304-309` (the `changed` gate), `backend/worker/detection/*` (layer scoring), `backend/tests/test_scan_tasks.py` (the deviation's footprint in the suite)
    - **Reproduction**: `scan_tasks.py`: `changed = any((r.get("score") or 0.0) > NOISE_FLOOR for k, r in results.items() if k != "layer9_fusion" and not r.get("skipped"))` — the raw-bytes layer (`layer1_hash`) participates in this gate. In `test_scan_tasks.py::test_scan_applies_stored_suppression_rules`, `layer1_hash` scores **1.0** (bytes differ) while every content layer scores 0.0 under suppression — and the test's own assertion is `verdict in ("clean", "changed")`, i.e. the suite explicitly tolerates "changed" on a benign counter-bump. The Phase-13 gate proved capture CONSISTENCY (theguardian skeleton similarity 0.9988) but no test anywhere drives the nine-layer pipeline over two real captures of a benign dynamic site and asserts `verdict == clean`. Deviation flagged in the Phase-14 log entry; no Phase 8–14 code resolves it; it is visible in the shipped assertion itself.
    - **Root cause**: the verdict gate treats "any non-fusion layer above NOISE_FLOOR" as "changed", and the byte-hash layer's raw score survives byte-level churn that normalization and suppression fully neutralize in every content layer. Clean-vs-changed on live benign churn therefore depends on which churn shapes normalize to zero — unpinned by any test, so real sites land on "changed".
    - **Proposed remedy category**: detection-pipeline semantics change (gate `changed` on normalization-aware layer evidence, or exclude the raw byte-hash layer from the `changed` trigger when all content layers are sub-noise), PLUS a regression gate that drives benign live-churn captures end-to-end and asserts `clean`. Diagnosis/design belongs to Audit Phases 2/3; implementation only in a future remediation prompt.
    - **Source**: PROMPT-003 Audit Phase 1 spec directive (Phase-14-flagged deviation); surfaced from matrix-row verification against current code.

    - **ID**: AUDIT-1-2
    - **Title**: The below-target Phase-13 capture categories were closed with aggregate-level attributions, not the individually-investigated per-site root causes Rule 19 demands
    - **Severity**: Medium — a real audit-process Gap with bounded, discoverable scope (9 failing sites across 5 categories); not High because the shipped code honestly FAILED its own gate (no threshold weakening, no relabeling) and the product contracts are intact — the Gap is in the evidence behind the close-out, not a shipped defect.
    - **Subsystem / file(s)**: `backend/tests/test_capture_e2e.py` (the Phase-13 gate), PROMPT-002-IMPLEMENTATION-LOG.md Phase-13 entry (reporting table + honesty note)
    - **Reproduction**: reading the Phase-13 entry: Lazy 8/11 (unsplash 401; shutterstock/dreamstime 403), Cloudflare 5/6 (discord 10 MB HTML guard), E-commerce 3/6 (ebay/etsy "WARP DNS"; walmart "WAF timeout"), Cookie Banner 11/12 (tagesschau wedged), Static Control 9/10 (rfc-editor detected block). The per-site notes are one-line attributions; the honesty note then aggregates ("anti-bot 401/403 tiers beyond the simple-CF evasion playwright-stealth provides, WARP DNS flakiness…"). No per-site capture_evidence analysis exists: unsplash — bare 401 vs an undetected challenge page? shutterstock/dreamstime — which anti-bot tier, did the challenge gate even evaluate? walmart — was the Phase-6 retry exercised and exhausted, or misclassified permanent? ebay/etsy — WARP DNS is the agent-environment VPN, not product behavior, unverified on the product's own network. discord — is the >10 MB HTML the site's real size (permanently uncapturable under `MAX_HTML_BYTES`) → accepted-risk candidate?
    - **Root cause**: the Phase-13 session spent its budget building the gate and root-caused at category level; Rule-19-grade per-site investigation (per-site evidence extraction, retry-path verification, environment-vs-product attribution) was never done.
    - **Proposed remedy category**: per-site investigation with disposition inside Audit Phases 5A/5C (which re-run these exact categories against the stress catalog): for each failing site, extract `capture_evidence` + error classification, attribute environment-vs-product, verify the Phase-6 retry path, and record an explicit Fix-candidate or Accepted-risk disposition per site. No aggregate acceptance permitted.
    - **Source**: PROMPT-003 Audit Phase 1 spec directive (Rule 19); surfaced from the Phase-13 reporting table.

- **Log-vs-reality discrepancies**: none that change conclusions. All re-executed suites match the Phase 1–7 log claims exactly (backend 120 passed / 0 failed / 0 skipped; frontend capture-health 4 passed). One accounting nuance verified and found CONSISTENT, not discrepant: the Phase-13 table counts rfc-editor (BOT_PROTECTION detected block) as a Static-Control "Failed" row — correct under Static Control's clean-capture contract (the detected-block-counts-as-PASS honesty rule is scoped to the Cloudflare category, where 5/6 = 83% clean-or-detected is separately reported). Also verified: the Phase-13 honesty math 65/74 = 87.8% is arithmetically correct, and every Rule-12 deviation claimed in Phases 1–7 (clip shape, documentElement probe, challenge-retry deadline, 88-vs-89 seed count) is real, reasoned, and test-pinned or count-verified.

- **New hermetic tests added this phase**: none. Diagnosis phase (Rule 1) — the existing Phase 1–7 suites were re-executed as-is (all green); no test or production code was modified.

- **Opportunities / Innovation ideas observed** (Rule 17 — not severity-scored, not gap-driven):

    - **Idea**: O-1 — UA-era freshness signal in capture evidence
    - **Why it would help**: `CAPTURE_USER_AGENT` is a one-time pin; WAFs flag stale-Chrome UAs long before any test's `>= 130` lower bound would fire. A periodic informational check (Chrome major vs a fetched endoflife.date feed) surfaced in `capture_evidence` (`ua_era_stale: true`) would let operators see staleness before sites do.
    - **Where it touches**: `worker/stealth.py`, `worker/fetcher.py` evidence assembly, optional startup/beat task
    - **Rough shape of the change**: compare the UA's Chrome major against a cached feed value on worker start; stamp a boolean into evidence; never affects verdicts.

    - **Idea**: O-2 — fleet-level "banners we could not dismiss" aggregation
    - **Why it would help**: `capture_evidence` already records `{dismissed, selector}` per scan, but nobody aggregates misses. A health-details rollup of the most common non-dismissed banner hosts/selectors would tell you exactly which CMP selectors to add next, from data already in the DB.
    - **Where it touches**: `app/routers/health.py` (summary query over `scans.capture_evidence`), frontend health page
    - **Rough shape of the change**: extend the existing `capture_quality_summary` pass with a top-N miss counter keyed on `final_url` host; render as a small table.

    - **Idea**: O-3 — record challenge-gate wait duration in evidence
    - **Why it would help**: the gate records detected/resolved booleans only; Audit Phases 5A/5C per-site root-causing (AUDIT-1-2) would be much cheaper with `challenge_wait_ms` and the final marker state, distinguishing "waited and solved" from "waited the whole budget" per site.
    - **Where it touches**: `worker/fetcher.py::_wait_out_challenge` evidence dict
    - **Rough shape of the change**: add `challenge_wait_ms` (elapsed) and optionally the last observed title/marker to the evidence keys already persisted.

- **Full regression results** (Windows host, Docker stack up — wardress-app/worker/beat/db/redis + disposable wardress-test-pg on 127.0.0.1:5433):
  - `cd backend && uv run --frozen pytest tests/test_probe_ua.py tests/test_cloudflare_detection.py tests/test_banner_dismiss.py tests/test_fetcher_retry.py tests/test_page_prepare.py tests/test_screenshot_cap.py tests/test_capture_evidence.py tests/test_stealth.py -q` → **87 passed in 408.68s (0:06:48)** — 0 failed, 0 skipped (the real-Chromium integration tests all ran on the host; no browser-skip markers fired).
  - `cd backend && uv run --frozen pytest tests/test_scan_tasks.py tests/test_capture_health.py -q` → **33 passed in 47.24s** — 0 failed (against the live disposable Postgres harness).
  - `cd frontend && pnpm exec vitest run tests/capture-health.test.tsx` → **1 file, 4 tests passed**.
  - Backend capture total: **120 passed / 0 failed / 0 skipped**. No production or test code was changed this phase (Rule 1), so no lint drift is possible; `ruff` baseline untouched.

- **Findings out of phase scope** (logged for the correct future phase, not investigated here):
  - AUDIT-1-1's remedy design → Audit Phase 2 (detection traceability matrix: Phases 8–14 own `scan_tasks`' verdict gate context, NOISE_FLOOR semantics, and the detection layers' normalization contracts) and Audit Phase 3 (fresh-eyes detection audit). Audit Phase 2 must carry this Gap forward in its matrix rather than re-discovering it.
  - AUDIT-1-2's per-site investigations → Audit Phases 5A/5C (stress-test catalog tiers A/B re-run these exact categories; per-site evidence + disposition is the deliverable there).
  - O-3 (challenge-wait duration in evidence) would materially cheapen AUDIT-1-2's per-site work; flagged for Audit Phase 5A's attention in the catalog's logging format discussion.
  - PROMPT-002 Phase 13's `_capture_child_impl.py` subprocess isolation and `test_capture_e2e.py`'s 10 network-marked tests are structural (hermetic default deselects them — verified in `pyproject.toml` addopts) — no action, recorded as prior-art confirmation for Audit Phase 2B's inventory.

- **Commit**: 084bd6c — audit(prompt-003): phase 1 capture traceability matrix (hash recorded in the follow-up one-line commit; both are log-only changes)

- **Next phase kickoff prompt**: (delivered in chat only — never written to this log)


<!-- AUDIT1-CONT -->

