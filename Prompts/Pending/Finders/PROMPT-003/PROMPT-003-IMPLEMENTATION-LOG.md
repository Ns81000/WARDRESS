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


### [DONE] PROMPT-003 Audit Phase 2 — Traceability Matrix: Detection Phases (PROMPT-002 Phases 8–14)

- **Prompt**: PROMPT-003-capture-detection-audit-and-stress-hardening.md
- **Session date**: 2026-09-10
- **Assigned subsystem**: §4 Audit Phase 2 — detection stack: `worker/detection/{pipeline,normalize,dom,metadata,fusion,suppress,cloaking,semantics,signatures,visual,types}.py`, `worker/hashing.py`, the verdict/changed gate in `worker/scan_tasks.py`, the meta-generators `backend/tools/build_regression_corpus.py` + `refit_fusion_model.py` (+ their shared parent `build_fusion_dataset.py`), the generated artifacts `worker/detection/training/{regression_corpus,fusion_model}.json`, and every test file named in the Phase 8–14 log entries. AUDIT-1-1 (verdict-gate Gap) is carried forward in the Phase-11 matrix row per the Phase-1 handoff — re-confirmed in current code, not re-discovered.

#### Directive 1 — Attack-technique taxonomy vs the 152-row regression corpus

Corpus composition re-verified from the artifact itself (`regression_corpus.json` meta): 152 rows = 12 attack axes × 8 (sig_strong_banner, sig_leet, sig_medium_weak, script_new_domain, form_action_swap, hidden_spam_inline, hidden_spam_stealth, cloaking_heavy, visual_banner_deface, laundering_padded, multi_vector_screamer, combined_subthreshold) + 7 benign-dynamic axes × 8 (rotating_ad, timestamp_counter, cache_busting_refs, minor_css_churn, mixed_noise_combo, editorial_update, nonnative_editorial). Row spot-checks performed with PowerShell over the JSON (counts, per-row features, fused risks) — the meta's `by_axis` matches the pinned constants exactly.

| # | Technique | Verdict in the 152-row corpus | Evidence |
|---|---|---|---|
| 1 | Defacement (banner/takeover) | **Represented** | `sig_strong_banner`/`sig_leet`/`sig_medium_weak` axes (+ heavy variants `multi_vector_screamer`, `laundering_padded`); mutators `build_fusion_dataset.py:639-667`; end-to-end flag pinned by `test_detection_e2e.py::test_injected_defacement_signature_flags_risk_above_0_5` (:426) |
| 2 | Asset-swap (server-side, DOM untouched) | **Represented** | `visual_banner_deface` has a 50% pure asset-swap branch (`build_fusion_dataset.py:818-825`: `Outcome(html, …)` unchanged HTML + `shot_banner=True`); verified in corpus rows: visual_banner_deface-0000/0001/0002/0006 all have `layer1_hash=0.0` (hash-identical DOM) with `layer4≈0.66` and fused risk 1.0 — the hash-gate-removal contract (Fix Phase 6) is exercised, not just asserted |
| 3 | SEO-spam link farm | **Represented** | `hidden_spam_inline`/`hidden_spam_stealth` axes (mutators :702-729, incl. opacity/font-size/offscreen/stylesheet variants); e2e `test_hidden_seo_spam_link_farm_detected_by_layers_2_and_3` (:470) |
| 4 | Script-injection | **Represented** | `script_new_domain` axis (mutator :681-684); layer-3 rule floor (`fusion.py:185`, new-sensitive-infrastructure → 0.40) is axis-covered |
| 5 | Non-Latin takeover | **Assumed-covered-by-similarity in the corpus; Represented one layer out** | The 152-row corpus contains only the BENIGN `nonnative_editorial` axis; the attack-side axes `nonnative_full_rewrite`/`nonnative_partial_inject` exist in the 646-row fusion dataset but were dropped from the corpus as "channel-adjacent duplicates" (Phase-12 log + meta notes). The script-flip/inflow channels are pinned by `test_detection_e2e.py::test_non_latin_defacement_rewrite_flags_via_script_flip` (:490) and layer-5 tests — but no standing corpus row guards non-Latin takeover specifically |
| 6 | Credential-phishing overlay | **Assumed-covered-by-similarity (form-target slice) / Genuinely absent (visual-overlay slice)** | `form_action_swap` (mutator :696-699: `action="/login"` → evil domain) covers form-target hijack via layer 3's 1.0-weight form_action channel; but no axis models an injected fake-login OVERLAY (positioned/fake UI harvesting credentials) — that shape exists only insofar as its `<form>`/hidden-element fragments trip layers 2/3 |
| 7 | Subtle single-word tampering | **Genuinely absent** | No axis mutates a single word of existing content; `sig_medium_weak` (:664-667) is still signature-shaped. Structural consequence (verified against the deployed model): a single-word content edit that trips no signature/lexicon leaves layers 2/3/5/8 ≈ 0 and fuses an l1-only profile to ≈0.14 (`sigmoid(4.408 − 6.247)` with the artifact's coefficients) — verdict "changed", never flagged, never escalated (< 0.40) |
| 8 | Image-only tamper with unchanged DOM | **Represented** | Same `visual_banner_deface` pure-swap rows as #2 (l1=0, l4≈0.66, risk 1.0); e2e `test_asset_swap_same_html_different_screenshot_layer4_nonzero` (:450) |
| 9 | Redirect-based cloaking | **Genuinely absent** | Zero `http-equiv`/meta-refresh handling anywhere in the backend (repo-wide search: no matches). Layer 7 compares raw no-JS fetch TEXT between UAs (`cloaking.py` design comment :16-17 + implementation :121-188); `probe.py:202` follows HTTP 3xx redirects only, and a served meta-refresh/JS redirect is never executed by the probe. Layer 3's ref audit (`dom.py:641-676`) collects only script/a/link/iframe/form — a `<meta http-equiv="refresh" content="0;url=…">` injection is invisible to every ref channel and scores only generic layer-2 tag churn. A UA-conditional client-side redirect cloak (identical raw HTML to all UAs, redirect target chosen client-side) reads 0.0 on layer 7 |
| 10 | Staged/time-delayed payloads | **Genuinely absent (client-side delayed-render slice)** | No time-window mechanism exists in any layer or mutator (single-pair baseline→scan comparison). Server-side staged payloads ARE caught generically once materialized (they become ordinary content deltas); the uncovered slice is payload rendering that stays client-side/timed past the capture settle window |

#### Directive-carry — Traceability matrix rows (claim | Verdict | evidence)

**Phase 8 — Dynamic Content Normalization (text patterns)**

| Claim (spec §PHASE 8) | Verdict | Evidence |
|---|---|---|
| New `worker/detection/normalize.py` normalizing volatile text before layers 2/3/5/8 | Verified | Module exists (~310 lines); conservative pattern set (ISO 8601 + date stamps, UUIDs, cache-bust query values with value-shape guard, UUID-shaped values in any query param, token-named attributes/inputs/metas); fixed word placeholders keep idempotence by construction |
| Applied to BOTH sides, content layers only; layers 1/4/6/7 raw | Verified | `pipeline.py:142-150` — suppression first, then `normalized_copy` on both sides of the same pair; gated off entirely when hash identical or baseline HTML missing; spy test `test_detection_normalize.py::test_non_content_layers_receive_raw_pages` (:364) |
| Suppression runs before normalization (user regexes match raw text) | Verified | `pipeline.py:145-149` order; pinned by `test_user_suppression_regex_runs_before_normalization` (:347) |
| Idempotence; no HTML corruption; fail-open; evidence counts | Verified | `normalize_html` returns original untouched when no matches/parse failure/oversize (`_MAX_HTML_CHARS` :69); `test_idempotence` (:220), `test_empty_and_unparseable_fail_open` (:192), `test_oversized_document_skipped` (:205), summary/merge (:231); `normalization_applied` attached per content layer (`pipeline.py:174-175`) |
| Documented decisions AGAINST normalizing headlines/image-URLs/ad-slots | Verified | Module docstring (:20-36) + `test_attack_evidence_around_volatile_tokens_survives` (:92), `test_script_and_style_text_untouched` (:102), `test_style_attribute_never_touched` (:179) |
| 31 new tests, failing-before proof | Verified | Exactly 31 `test_` defs counted in `test_detection_normalize.py`; suite green in this session's unit batch |

**Phase 9 — CSP & Header Normalization**

| Claim | Verdict | Evidence |
|---|---|---|
| Verify Phase-36 comparator first; add normalization only if needed | Verified | The verify-branch applied: `_csp_directives` already collapsed nonces; the genuine gap found was case-sensitivity — fixed with `re.IGNORECASE` on `_CSP_NONCE_RE` (`metadata.py:44`, comment :45-48) |
| Nonce-only CSP change → score 0.0; directive change still scores; direction untouched | Verified | `_NORMALIZED_NONCE = "'nonce-'"` (:49); scoring `min(0.8, 0.3*removed + 0.1*weakened)` (:255); 22 tests in `test_csp_nonce_normalization.py` (counted) covering every spec edge case: multi-directive nonce-only (:71), uppercase prefix (:101,:108), removal beside nonce churn (:123,:140,:154), addition (:172), wildcard (:191), hashes never collapsed (:205), quoting recorded-not-normalized (:255), CSP↔Report-Only switch (:274,:284,:292), formatting noise (:235,:247,:314-328), hardening beside churn (:337), HSTS downgrade (:360) |
| E2E pin: nonce churn fully silent in a scan | Verified | `test_detection_e2e.py::test_csp_nonce_only_change_scores_zero_in_layer_6` (:382) — 0.0 AND all five directional buckets empty |

**Phase 10 — DOM Churn Scoring Refinement**

| Claim | Verdict | Evidence |
|---|---|---|
| Content-type-aware churn: content-only churn weighs less; infrastructure unchanged | Verified | `dom.py:45-95` (`_CONTENT_CHURN_TAGS` closed whitelist + decision comments), classification + binary weight at :552-560, `score = max(churn*weight, sensitive)` :572 |
| Wrapped script still boosts (not gameable) | Verified | Sensitive boost from `script/iframe/hidden` counts :564-568; `test_wrapped_script_still_boosts_sensitive_score` (:166) |
| Guard tests: content reduced, infra same-or-higher, mixed not weakened, no-churn unchanged | Verified | `test_dom_content_churn.py` 9 tests (counted): :70,:85,:95,:119,:135,:151 plus unknown-tags (:183) and hidden content farm (:194) beyond spec |

**Phase 11 — Verdict Noise Floor & Cadence** — **carries AUDIT-1-1**

| Claim | Verdict | Evidence |
|---|---|---|
| `NOISE_FLOOR = 0.02` on the `changed` rule; verdict-only | Verified as spec'd | `scan_tasks.py:44-59` (comment documents floor semantics), gate :304-308 strict `>` |
| Floor never affects fused risk, `flagged`, or rule floors | Verified | Risk from raw scores via `layer9_fusion`; `flagged = risk >= site.flag_threshold` :309 checked first; floors compose in fusion (`_RULE_FLOORS` `fusion.py:182-186`); pins: `test_noise_floor.py` 8 tests (counted) :164,:189,:205,:217,:230,:242,:254 + docs pin :276 |
| MATERIAL_CHANGE_RISK stays 0.40, decision documented with measured data | Verified | `scanning.py:58` + refreshed comment; Phase-11 re-measurement recorded in log (benign churn 0.137-0.153, editorial ≤0.298, A/B hero max 0.4393 documented as accepted 3/646) |
| **CARried GAP — AUDIT-1-1 (re-confirmed in current code, per Phase-1 handoff)** | **Gap** | The `changed` rule iterates ALL non-skipped layers including `layer1_hash`, whose raw score is a byte-flip 1.0 for ANY byte difference — normalization/suppression neutralize churn in every content layer but the byte-hash channel's verdict contribution survives untouched, so benign live churn reads "changed" (never "clean") at fused ≈0.30 (Phase-14 deviation-2 measured; l1-only profile fuses ≈0.14-0.30 depending on layer-7 degradation). Remedy design (gate on normalization-aware evidence or exclude raw byte-hash when all content layers sub-noise, PLUS a live-churn end-to-end `clean` regression gate) belongs to the future remediation prompt — carried, not re-diagnosed |

**Phase 12 — Detector Regression Harness (meta-verification of the generator — directive 4a)**

| Claim | Verdict | Evidence |
|---|---|---|
| Corpus reuses `build_fusion_dataset.py` builders; zero duplicated scenario logic | Verified (generator sound) | `build_regression_corpus.py:76-94` imports `measure_sample`, `SEED`, `LANGS`, `FEATURE_KEYS`, axis tables; subset assertions :127-129 fail the import if tables drift apart |
| 152 rows = strict subset; per-axis counts pinned; `ROWS_PER_AXIS=8` constant | Verified (generator sound) | Pinned constants :96-125; artifact meta re-verified against the constants via PowerShell JSON parse (`by_axis` exact match; 96 attack / 56 benign) |
| Deterministic rebuilds (fixed seed, per-axis language plan) | Verified (generator sound) | `measure_sample` reseeds `random.Random(f"{SEED}|{axis}|{idx}")` per row (build_fusion_dataset.py:1145); language plan `_plan_language` (:167-176); determinism pinned by `test_detection_regression.py::test_two_rebuilds_are_identical` (:268) + `test_committed_artifact_matches_a_fresh_rebuild` (:273) |
| Fused risk computed from ROUNDED features through the deployed `layer9_fusion` — exactly self-consistent | Verified (generator sound) | `_reconstructed_results`/`_fused_risk` (:179-194) rebuild skip-state skip results so degradation math cannot fire; exact-equality pin `test_stored_fused_risk_reproduces_from_stored_features` (:244) |
| Build-time validation refuses a regressed corpus | Verified (generator sound) | `validate()` :212-247 — duplicate ids, axis-count divergence, skipped-nonzero, attack content peak ≤ NOISE_FLOOR, benign ≥ MATERIAL_CHANGE_RISK all raise before write; evidence recorded in artifact meta (`validation` block re-verified in the artifact) |
| Atomic write (tmp + `os.replace`) | Verified (generator sound) | :322-327 |
| Content peak excludes `layer1_hash` + skips | Verified (generator sound) | `_content_peak` :197-208; convention documented in meta notes |
| **Generator finding — sub-invariant density (meta-verified consequence)** | **Note (no bug)** | Per-row `validate()` guarantees attack peak > NOISE_FLOOR per row, but the ROW is the unit: `combined_subthreshold` rows measured in this session span peak 0.0400-0.7534 and fused 0.0078-1.0 — subthreshold is genuinely heterogeneous (row -0002: l1=0,l4=0.0534,fused 0.0078 would fail the changed-invariant were its peak the corpus rule). The documented axis-level exception is the correct mechanism; no generator bug — but the axis-level strength floor is the only guard above the noise floor, which is exactly the overfitting note below |

**Phase 13 — End-to-End Capture Validation (verified for its detection-side contracts only)**

| Claim | Verdict | Evidence |
|---|---|---|
| `network` marker + `addopts = "-m 'not network'"` hermetic default | Verified | `pyproject.toml` (10 network tests deselected structurally; Phase-1 log re-verified addopts present) |
| Below-target categories root-caused individually (Rule 19) | Verified (prior-art confirmation) | Phase-13 log carries per-site causes (unsplash 401, shutterstock/dreamstime 403, ebay/etsy WARP DNS, walmart WAF timeout, discord 10MB guard, rfc-editor detected block, tagesschau wedged-transition kill); deferred to Audit 5A/5C per AUDIT-1-2 — out of scope here |

**Phase 14 — End-to-End Detection Validation (meta-verification of refit generator — directive 4b — + the corpus re-pin)**

| Claim | Verdict | Evidence |
|---|---|---|
| `refit_fusion_model.py` produces the deployed model with box constraints ≥ 0, deterministic, fail-loud gates | Verified (generator sound) | `build()` :365-408: negative-coefficient escape check :385, monotonicity sweep :328-339 + gate :387-389, quality gates :402-408 (val AUC ≥ 0.80, brier ≤ 0.25, ece ≤ 0.20, train accuracy band 0.70-0.98), degenerate-sanity check :395-400, atomic write with `newline="\n"` :468-473; dataset binding by line-ending-insensitive sha256 (:424-427) — artifact re-verified: lambda 0.01, val AUC 0.9047, val ECE 0.1638, 646 = 454/96/96 |
| Split discipline train/val/test; test untouched | Verified (generator sound) | `load_dataset` :150-195 validates splits non-empty/single-class-free; `assign_splits` (build_fusion_dataset.py:1363-1402) budgeted stratified 15%/15% per label; sanity rows forced train (:1371-1373) |
| 152-row corpus re-pinned through deployed fusion in e2e | Verified | `test_detection_e2e.py::test_fusion_training_dataset_attack_vectors_still_score_appropriately` (:559, fast JSON path; deep rebuild/drift pin stays in test_detection_regression.py) |
| Deviations honestly logged (Rule 12) — incl. benign-churn "clean" unachievable by design | Verified | Phase-14 log deviations 1-4: file name, the l1-byte-flip "changed-not-clean" deviation (measured ≈0.30, THE AUDIT-1-1 root), full silence vs nonce-value evidence, corpus shape — all re-confirmed against current code this session |
| Backward compat with Phase-1-era baselines | Verified | `test_phase1_era_baseline_still_scans` (:604); `capture_meta` migration gate `capture_method_version` with CAPTURE_METHOD_VERSION fallback (scan_tasks.py:139-156) |

#### Directive 2 — Re-verify both Phase-14 leads in current code + operator-facing impact

**Lead 1 — `ScanFinding` rows do not carry the degraded flag**

| Verdict | Evidence |
|---|---|
| **Confirmed in current code** — `ScanFinding` (`app/models.py:519-548`) has fields `layer`, `layer_key`, `score`, `skipped`, `evidence`, `created_at`; NO `degraded` column. Only the parent `Scan.layer_scores` JSON summary (:470-474) carries per-layer `degraded`. The e2e backward-compat pins (:604) store findings without it | `models.py:527-540` exact field list; `scan_tasks.py` finding-Writer writes only score/skipped/evidence |
| **Operator-facing impact: Medium.** The `scan_findings` rows are what UI drill-down and API consumers read per layer; a degraded layer (lost screenshot, dead probe) appears there as `score=None, skipped=True, evidence.reason=…` — degradation is discoverable only by reading the evidence dict's free-text reason, not by a structured flag. Aggregators that key on the scan's `layer_scores` see it; any consumer reading only findings rows cannot distinguish "dark channel" from "gated skip". No PII/alert path is affected; it is a signal-shape gap, not a correctness break | audit reasoning over the two tables |

**Lead 2 — stored `baseline.capture_meta["headers"]` is unused by detection**

| Verdict | Evidence |
|---|---|
| **Confirmed in current code** — `capture_meta["headers"]` is stored by the baseline capture (`scan_tasks.py:142`), but `_baseline_page_data` builds layer-6 input from `probe_headers`/probe_store only (`scan_tasks.py:197`), never reading `capture_meta["headers"]`. Detection compares `probe_headers` against the scan's fresh probe | `scan_tasks.py:139-156` (capture_meta write) vs :197 (baseline PageData headers=probe-store); `metadata.py` consumes `PageData.headers` only |
| **Operator-facing impact: Low.** `capture_meta` is the fetcher's CURATED subset selected for debugging (`fetcher.py:677` comment: "Debugging metadata only — nothing in …"); layer 6 deliberately diffs the prober's independent full header map, not reuses the fetcher's. Storing one redundant header map costs one JSONB column. No detection or verdict behavior depends on it | `fetcher.py:677`; `metadata.py:303-306` uses probe headers |

#### Directive 3 — Do `MATERIAL_CHANGE_RISK` / `NOISE_FLOOR` have tests proving generalization beyond their derivation fixtures? **(overfitting risk)**

**Verdict: NO — both constants are verified only against the exact generating family that calibrated them. Overfitting risk is real and structural, not hypothetical.**

Evidence chain (each link verified this session):

1. `NOISE_FLOOR = 0.02` and the `changed` gate are pinned by `test_noise_floor.py` (8 tests) — every one builds a `Site`/`Baseline` row and monkeypatches `run_detection` to return hand-picked layer-score dicts (verified: the 8 tests at :164/:189/:205/:217/:230/:242/:254/:276 do not import or instantiate any real page/capture). The constant is therefore proven ONLY against the fixture author's chosen dict shapes — same fixture family, no independent generator.
2. `MATERIAL_CHANGE_RISK = 0.40`'s only standing guard is `test_benign_dynamic_rows_stay_below_the_material_change_band` (`test_detection_regression.py:232`), which asserts < 0.40 on the committed 152 rows — and those rows are the SAME `build_fusion_dataset.py` scenarios that produced the 646-row corpus whose measurements set 0.40 in the first place (Phase-11 documented derivation: "measured 0.137-0.153 … editorial ≤0.298 … A/B hero max 0.4393"). The guard circularly re-checks the calibration data.
3. The one independent-ish real-world probe, Phase 14's hermetic churn pair (`test_detection_e2e.py:333,528`), pins only "≤ MATERIAL_CHANGE_RISK", never a generalization bound on unmodeled shapes; and its own "benign clean" assertion was re-specified as "changed" (deviation 2) because the raw byte-hash defeats it — a symptom, not a guard.
4. No test anywhere draws an input from outside the `build_fusion_dataset.py` procedural family (no captured real-site pair, no ad-hoc adversarial HTML) and asserts a constant bound. The Phase-13 live network gate (the only real-world inputs) touched no detection constant.

What that means: a hypothetical benign churn shape outside the 20-25 mutator axes — e.g. a stock ticker re-rendering its canvas, a reCAPTCHA iframe rotating its src, a lazy-loaded infinite-scroll div — could fuse ≥ 0.40 and permanently tighten cadence, or land between the floor and material bar and read "changed" forever, and NO standing test would fail. The benign invariants are both in-distribution by construction.

#### Findings (each per §6.4 rubric; diagnosis only, no production edit — Rule 1)

**AUDIT-2-1 — Stand-in corpora do not exercise the ten-technique taxonomy: 4 of 10 attack shapes have no standing corpus row**
- **Severity**: Medium (per §6.4 — detection is not wrong on the covered vectors, but the Contract says the corpus shall be the standing re-measure; absent rows mean a regression in those channels fails silently)
- **Subsystem / file(s)**: `tools/build_fusion_dataset.py` (mutators), `tools/build_regression_corpus.py` (axis selection constants), `worker/detection/training/regression_corpus.json`
- **Reproduction**: enumerate the corpus `by_axis` (artifact meta) vs the 10-technique taxonomy; `nonnative_full_rewrite`, `nonnative_partial_inject`, `seo_spam_early`, `laundering_padded` (visual-overlay slice), and every staged/redirect shape have no 8-row axis
- **Root cause**: Phase-12 axis selection deliberately trimmed "channel-adjacent duplicates" and made the corpus a strict subset of the fusion dataset's axes; the four attack-side missing shapes are those trims. The overfit stems from validating only in-distribution generator axes
- **Proposed remedy category**: corpus-axis expansion (add non-Latin attack, visual-overlay, single-word, redirect, staged axes + forward their `build_time` validation as standing per-axis pins)
- **Source**: this phase's taxonomy audit (directive 1)

**AUDIT-2-2 — Credential-phishing overlay and subtle single-word tampering are genuinely absent from the corpus**
- **Severity**: High per §6.4 — a documented, plausible, real attack family with NO corpus row and NO end-to-end pin; the one adjacent pin (`form_action_swap`) covers the form-target slice, not a phishing overlay
- **Subsystem / file(s)**: corpus artifact + `test_detection_e2e.py` (+ any future remediation)
- **Reproduction**: search the corpus for an axis containing the shape; none exists; single-word edits fuse only via l1 (≈0.14-0.30, changed-not-flagged) with no standing assertion
- **Root cause**: same Phase-12 subset trimming + no attack family modeled as a visual-only/positioned overlay or single-token content mutation
- **Proposed remedy category**: corpus-axis + e2e fixture addition (phishing overlay, single-word mutation), with a generalization bound on benign single-word edits
- **Source**: taxonomy audit (directive 1)

**AUDIT-2-3 — Redirect-based cloaking and staged/time-delayed payloads are genuinely absent (no mechanism)**
- **Severity**: Medium (cloaking: layer 7 reads raw non-JS text; a client-side redirect cloak is 0.0 — real blind spot. Staged payloads: server-side ones are caught once materialized, so Medium)
- **Subsystem / file(s)**: `worker/detection/cloaking.py`, `worker/probe.py`, `worker/detection/dom.py` (+ corpus)
- **Reproduction**: repo search finds zero `http-equiv`/meta-refresh handling; `probe.py:202` follows HTTP 3xx only; layer 3's ref audit (`dom.py:641-676`) omits meta-refresh targets; a `<meta http-equiv="refresh" content="0;url=evil">` injected to selected UAs reads 0.0 on layer 7
- **Root cause**: no mechanism to detect client-side/redirect-based delivery; the taxonomy's design assumes server-side content divergence
- **Proposed remedy category**: detection-capability addition (meta-refresh parsing + redirect-loop detection in layer 3/7, or document as accepted-risk)
- **Source**: taxonomy audit (directive 1)

**AUDIT-2-4 — NOISE_FLOOR / MATERIAL_CHANGE_RISK have no generalization test (overfitting risk)**
- **Severity**: High per §6.4 — a not-necessarily-wrong but unproven generalization bound; a benign out-of-family churn shape that fuses ≥ 0.40 would tighten cadence with no standing test failing
- **Subsystem / file(s)**: `test_noise_floor.py` (definition fixtures), `test_detection_regression.py:232` (in-distribution only), `test_detection_e2e.py:333,528` (single pair)
- **Reproduction**: read the three guards; none draws inputs outside `build_fusion_dataset.py`'s procedural axes
- **Root cause**: constants calibrated on the generator family and verified only against the same family's outputs (circular guard)
- **Proposed remedy category**: add generalization tests — ad-hoc adversarial benign HTML pairs (canvas/iframe/ticker) + at least one captured real-site pair asserting the constants hold out-of-distribution
- **Source**: directive 3

**AUDIT-2-5 — `ScanFinding` rows lack the degraded flag (Phase-14 lead 1, re-verified)**
- **Severity**: Medium — confirmed in code; operator-facing signal-shape gap (findings-only consumers can't distinguish dark channels from gated skips)
- **Subsystem / file(s)**: `app/models.py:519-548`
- **Proposed remedy category**: schema addition (findings.degraded) + migration + writer + consumers — future remediation only (Rule 1)

**AUDIT-2-6 — stored `capture_meta["headers"]` unused by detection (Phase-14 lead 2, re-verified)**
- **Severity**: Low — confirmed in code; debugging-only curated subset, no detection/verdict impact
- **Subsystem / file(s)**: `worker/scan_tasks.py:142` vs `_baseline_page_data:197`
- **Proposed remedy category**: either document as intended (preferred) or drop the redundant write — decision for the remediation phase
- **Source**: directive 2

#### Log-vs-reality discrepancies (Rule 12 — PROMPT-002 claims this phase could not reproduce)

None material. The Phase-14 log's deviation-2 measurement (benign churn pair fuses ≈0.30, verdict "changed" per the byte-hash design) was re-derived independently this session from the deployed model coefficients (`combine: sigmoid(4.408 − 6.247·w_ratio)` gives ≈0.14-0.30) — matches the logged number. No PROMPT-002 numeric claim (1278 passed / 133 frontend / val AUC 0.9047 / corpus 152 rows / 646=454/96/96) was contradicted by any file read or suite run this phase.

#### New hermetic tests added this phase

None committed (Rule 5/10) — this is a diagnosis phase; no production file was edited (Rule 1). Verification was performed by running the EXISTING committed suites in two batches (see below) plus read-only spot-checks of the artifacts.

#### Full regression results

- **Unit batch** (hermetic, no DB): `pytest tests/test_fusion_refit.py tests/test_detection_fusion_pipeline.py tests/test_dom_content_churn.py tests/test_detection_normalize.py tests/test_csp_nonce_normalization.py -q` → **110 passed in 33.69s**, 0 failed, 0 skipped.
- **DB batch** (live `wardress-test-pg` on 127.0.0.1:5433): `pytest tests/test_noise_floor.py tests/test_detection_e2e.py tests/test_detection_regression.py -q` → **29 passed in 182.90s**, 0 failed, 0 skipped.
- Both runs used the committed artifacts (`regression_corpus.json`/`fusion_model.json`); `test_detection_regression` exercised the in-suite rebuild drift check in-process.
- The 8 named test files: 10+11+8+22+9+51+31+10 = all present and counted in the batches above.

#### Opportunities / Innovation ideas observed (Rule 17 — not severity-scored)

- **Idea O-4 — "Corpus completeness" standing report**: extend `test_detection_regression.py` with a meta-test that maps the ten-technique taxonomy to corpus axes and FAILS when a Represented-axis lacks ≥8 rows (making AUDIT-2-1 a standing red signal instead of a one-time finding).
  - **Why**: the taxonomy gaps are exactly as dangerous when they silently reappear as when they were first shipped; a report gate keeps the corpus honest.
  - **Where**: `tools/build_regression_corpus.py` axis constants + `test_detection_regression.py`.
  - **Rough shape**: metadata table `TAXONOMY_AXIS_MAP`; a test asserts every taxonomy-tech has a mapped axis (or an explicit `accepted_gap` entry).

- **Idea O-5 — Real-site churn capture into the corpus**: seed the benign invariants with 1-2 actual high-churn site pairs (e.g. a news homepage captured twice, Phase-13 style) pushed through `run_detection`, asserted < 0.40.
  - **Why**: closes AUDIT-2-4's out-of-distribution hole with zero new machinery; the capture already exists.
  - **Where**: `test_detection_e2e.py` / a new small scratch fixture; `build_regression_corpus.py` mutator reuse.
  - **Rough shape**: a `real_churn_pairs/` fixture dir + one test asserting the fused-risk bound.

- **Idea O-6 — `ScanFinding.degraded` + a findings-only health read**: fold AUDIT-2-5's flag into the same migration that adds findings rows (schema addition), then have the health aggregate read findings-only degradation.
  - **Why**: makes dark channels first-class for consumers without touching PDF/alert paths.
  - **Where**: `app/models.py`, `app/routers/health.py`, frontend site-detail.

#### Findings out of phase scope (logged for the correct future phase, not investigated here)

- AUDIT-2-1/2/3's **taxonomy axis-expansion** and AUDIT-2-4's **generalization tests** → Audit Phase 3 (fresh-eyes detection audit) is where the detailed gap-closure design belongs; implementation only in a future remediation prompt.
- AUDIT-2-5 (findings degraded flag) → schema change; implementation only in remediation.
- AUDIT-2-6 (capture_meta headers) → decision (document-as-intended vs drop write) in remediation.
- AUDIT-1-2 (Phase-13 per-site root causes) remains with Audit Phases 5A/5C (stress catalog tiers A/B re-run those exact categories).

#### Commit

`11a5e54` — audit(prompt-003): phase 2 detection traceability matrix + taxonomy/overfitting findings (log-file-only change)

<!-- AUDIT2-CONT -->

### [DONE] PROMPT-003 Audit Phase 2B — Full Codebase Inventory, Blast-Radius Mapping & Prior-History Sweep

- **Prompt**: PROMPT-003-capture-detection-audit-and-stress-hardening.md
- **Session date**: 2026-09-11
- **Assigned subsystem**: §4 Audit Phase 2B — entire repository for classification, plus targeted grep (never full reads) of `Prompts/Done/Loogers/WARDRESS_AUDIT_FINDINGS.md` (268KB) and `WARDRESS_FIX_LOG.md` (790KB).

#### Method (Rule 13 — empirical, not doc-trusted)

- Repo walk via `git ls-files` (587 tracked files; working tree clean at `167c152`). Grouped per directory; ambiguous files classified by reading their module docstrings/head lines directly (e.g. `worker/hashing.py`, `app/reporting.py`, `app/explain.py`, `app/tasks.py`), not by name inference.
- **PROMPT-002 touched-file set**: derived empirically by full-text grep of `PROMPT-002-IMPLEMENTATION-LOG.md` for both full paths (`backend/...py`, `frontend/src/...`) and bare module names (`visual\.py`, `hashing\.py`, `alerting\.py`, ...). Hit counts distinguish "named/targeted" from "merely mentioned in passing". This set is log-derived (a self-reported claim) — used only to *prioritize* fresh-eyes reads, never to *excuse* a file from audit (§3.6: this Phase 2B inventory, not PROMPT-002's own lists, is the authoritative target source).
- **Prior-history sweep**: `Select-String` targeted grep for the six mandated terms; hit counts + line-context reads only, no full reads of the 790KB/268KB files. Counts: `TODO` 0/0, `deferred` 1/5, `not implemented` 1/3, `residual` 2/149, `known issue` 0/0, `unresolved` 0/1 (FINDINGS/FIXLOG). ~120 of the 149 FIXLOG "residual" hits are per-phase `Residual risk / follow-ups` headers inside `[FIXED]` entries (disclosed hand-offs), not open defects; the ones intersecting the blast radius are dispositioned below.

#### 1. Repository inventory & blast-radius mapping (grouped, per §4 formatting discipline)

| # | Bucket | Files (count) | Classification |
|---|---|---|---|
| 1 | **Capture/detection core** (Audit Phases 1, 3, 4 targets) | 29 | `worker/`: `stealth.py`, `fetcher.py`, `probe.py`, `page_prepare.py`, `banner_dismiss.py`, `artifacts.py`, `hashing.py` (7); `app/capture.py`, `app/scanning.py` (2); `worker/detection/`: `__init__.py`, `types.py`, `normalize.py`, `dom.py`, `signatures.py`, `visual.py`, `metadata.py`, `cloaking.py`, `semantics.py`, `suppress.py`, `fusion.py`, `pipeline.py` (12) + `training/fusion_dataset.json`, `training/fusion_model.json`, `training/regression_corpus.json` (3 deployed/training artifacts); `tools/`: `build_fusion_dataset.py`, `build_regression_corpus.py`, `refit_fusion_model.py` (3) + `run_stress_catalog.py` (1, Phase-5A/5B harness) |
| 2 | **Orchestration, data & scheduling** (Phase 4B/4D) | 30 | `worker/scan_tasks.py`, `remediation_tasks.py`, `alert_tasks.py`, `beat_tasks.py`, `celery_app.py`, `worker/db.py` (6); `app/models.py`, `schemas.py`, `db.py`, `tasks.py`, `services.py`, `config.py`, `settings_store.py`, `main.py` (8); `alembic/` 16 version migrations + `alembic.ini`, `env.py`, `script.py.mako`, `README` |
| 3 | **API routers, auth & RBAC** (Phase 4C) | 19 | `app/routers/*.py` 13 in-scope (of 14; `agent.py` excluded, bucket 8): `alerts`, `apikeys`, `artifacts`, `audit`, `auth`, `health`, `imports`, `remediation`, `reports`, `settings`, `sites`, `users`, `__init__`; plus `app/deps.py`, `ratelimit.py`, `security.py`, `apikeys.py`, `audit.py`, `seed_admin.py` |
| 4 | **Alert & remediation delivery** (Phase 4D) | 7 | `app/alerting.py`, `remediation.py`, `explain.py`, `reporting.py`; `app/templates/email/alert.html`, `templates/email/test.html`, `templates/report/report.html` |
| 5 | **AI provider integration** (Phase 4E) | 9 | `app/llm.py`, `ai_config.py`, `ai_catalog.py`, `ai_ollama.py`, `ai_startup.py`, `ai_migration.py`; `worker/llm_escalation.py` (in scope per §0 — detection's second-opinion mechanism); `app/crypto.py` (Fernet-at-rest for AI keys); `app/data/models_dev_catalog.json` |
| 6 | **Frontend capture/detection surfaces** (Phase 4F) | 34 src + 21 tests | pages: `health.tsx`, `site-detail.tsx`, `scan-detail.tsx`, `alerts.tsx`, `remediation.tsx`, `sites.tsx`, `settings.tsx`, `audit.tsx`, `login.tsx`, `assistant.tsx`, `App.tsx`, `main.tsx` (12); components: `finding-card`, `dom-diff-tree`, `risk-gauge`, `incident-timeline`, `visual-diff-slider`, `suppression-panel`, `remediation-hooks-panel`, `status-dot`, `ai-settings-card`, `api-keys-card`, `users-card`, `favicon-card`, `bulk-import-dialog`, `app-shell`, `site-avatar`, `site-favicon`, `spark-icon`, `markdown-message`, `wardress-mark` + `ui/` (10 shadcn primitives); lib: `api.ts`, `auth.tsx`, `use-artifact.ts`, `use-site-icon.ts`, `use-reduced-motion.ts`, `site-icon-state.ts`, `site-avatar.ts`, `ai-task-assignment.ts`, `bbox.ts`, `listbox-keys.ts`, `numeric-inputs.ts`, `provider-logos.ts`, `utils.ts` (13); `frontend/tests/` 21 files |
| 7 | **Dependencies / config / supply-chain** (Phase 4E, 9) | 24 | `backend/pyproject.toml`, `uv.lock`, `Dockerfile.app`, `Dockerfile.worker`, `tools/check_torch_osv.py`; `frontend/package.json`, `pnpm-lock.yaml`, `vite.config.ts`, `tsconfig*.json` (3), `.oxlintrc.json`, `components.json`, `index.html`; repo root: `docker-compose.yml`, `.env.example`, `.dockerignore`; `.github/workflows/ci.yml`, `static.yml`; `scripts/` 7 (install/uninstall/validate/update/diagnostics/`lib.ps1`, `generate_structure.py`) |
| 8 | **Excluded operations agent** (per §0 exception) | 8 | `app/agent/{__init__,context,engine,guard,tools}.py` (5), `routers/agent.py`, `docs/agent.mdx`, `docs/agent-skill.mdx` + `worker/telegram_bot.py` (boundary check in §2 below) |
| 9 | **Out of blast radius** | ~290 | `landing/` (26), `walkthrough/` (18), `assets/` (18), `frontend/src/assets/providers/` (160 static provider-logo SVGs, integrity-pinned by `svg-path-integrity.test.ts`), `docs/` non-agent docs + images/screenshots (38 — read for drift in Phase 9, not runtime), `Prompts/` (14, this effort's own state), `README.md` (Phase-9 docs-drift scope), `frontend/src/index.css`, `public/favicon.svg`, `frontend/src/assets/fabric-iq.svg`, `.gitignore`/`.gitattributes`, `frontend/.gitignore` |

#### 2. `telegram_bot.py` scope determination (the §4-mandated crucial check) — **OUT of blast radius (interactive ops transport, NOT an alert channel)**

Verified cold, not from its docstring alone:

- **It does not deliver scan alerts.** `app/alerting.py:10-12` routes telegram alert pushes through Apprise `tgram://` built from the stored bot token + chat id (`alerting.py:177-180, 235-245`); `telegram_bot.py:7` states this and the code confirms it — the bot has no Apprise/sending path for alert content beyond replies to its own command chat.
- **What it actually is**: dedicated optional container (`docker-compose.yml:136-142`, profile `telegram`, `python -m worker.telegram_bot`) running pull-commands `/start /status /sites /scan /ack /mute /help`. It reads `Scan`/`Alert`/`Site` via `worker.db.task_session` directly (:221-278) and triggers scans via `trigger_scan_now(db, site, actor=None, actor_label="telegram-bot", via="telegram")` (:313) — the same service layer the routers use.
- **One narrow coupling to the in-scope alert path**: `/start` captures the chat id that `alerting.py:241` then *requires* for the telegram channel ("send /start to your bot"). The bot therefore provisions, but never delivers, the alert channel. Logged as a boundary note, not an escalation.
- **Verdict**: excluded subsystem (ops-agent/interactive transport), consistent with the `app/agent/` exclusion. Its alert-channel provisioning dependency and direct-DB access are noted for Phase 4D's awareness without pulling the bot itself into scope.

#### 3. Operations-agent data-access boundary check (escalation criterion: direct DB/scan-data access bypassing API/RBAC) — **no escalation fired**

- `app/agent/tools.py` imports `Baseline`, `Scan`, `ScanFinding` directly from `app.models` (:36-42) and runs direct DB selects (e.g. `select(Site)` :205-212) — it touches scan/finding data *outside the HTTP API*.
- But it does not bypass RBAC: tools carry `tier` (TIER_READ/SAFE/HIGH_IMPACT/DESTRUCTIVE, :67-70) and `min_role` floors (`_ROLE_RANK` :63-64; `tools_for_role` :169-174; `can_call` :177-178); tier ≥ 2 calls are frozen and re-checked by `guard.py` (confirm-before-execute, RBAC/ownership re-verified at confirm, :5-9); module docstring states executors call the same service code paths as routers (:6-10). This is the by-design architecture §0 already scoped out — **agent stays excluded**; each individual tool's account-scoping remains a legitimate cold-read target if Phase 4C wants one extra pass over `tools.py` reads (out of this phase's mandate to expand).

#### 4. Highest-priority fresh-eyes targets: in-radius files NEVER touched by PROMPT-002

Derived from the PROMPT-002 log full-text grep (×0 = never named in any PROMPT-002 phase). These have had no targeted remediation pass in either effort:

**Capture/detection core — Phase 3/4 priorities (most important of the entire inventory):**
- `worker/hashing.py` (×0) — layer-1 building block, never named by PROMPT-002 despite phases 8-14 overhauling detection.
- `worker/detection/visual.py` (×0), `signatures.py` (×0), `semantics.py` (×0), `cloaking.py` (×0), `types.py` (×0) — **five of the twelve detection modules were never named in PROMPT-002's log at all**; only `dom/metadata/normalize/pipeline` were directly edited, with `suppress.py` (×2) and `fusion.py` (×1) mentioned in passing. The five ×0 modules carry layers 3/4/5/7/8's rule logic — exactly where rule floors and false-negative risk live.
- `worker/artifacts.py` (×0) — capture artifact persistence.
- The three `training/*.json` artifacts + `build_fusion_dataset.py`/`build_regression_corpus.py`/`refit_fusion_model.py` — generators were touched (Phases 11-14) but a fresh-eyes read of the deployed JSONs' binding/derivation metadata is warranted (Phase 2 already re-verified refit gates).

**Everything else (Phase 4B-4F priorities):**
- Orchestration: `remediation_tasks.py` (×0), `alert_tasks.py` (×0), `beat_tasks.py` (×0), `worker/db.py` (×0), `app/db.py` (×0), `config.py` (×0), `settings_store.py` (×0), `main.py` (×0), `services.py` (×0) — **the entire scheduling/alert/orchestration spine except `scan_tasks.py` and `celery_app.py` was never touched by PROMPT-002**, plus 15 of 16 alembic migrations (only `o9q1r2s3t4u5` capture_meta was a Phase 1 target).
- API/RBAC: all routers except `sites.py` and `health.py` (×0): `alerts`, `apikeys`, `artifacts`, `audit`, `auth`, `imports`, `remediation`, `reports`, `settings`, `users` — plus `deps.py`, `ratelimit.py`, `security.py`, `apikeys.py`, `audit.py`, `seed_admin.py` (all ×0).
- Alert delivery: `alerting.py` (×0), `remediation.py` (×0), `reporting.py` (×0), all 3 templates (×0). (`explain.py` ×3 mentions only.)
- AI integration: every file in bucket 5 (×0) — `llm.py`, all `ai_*.py`, `llm_escalation.py`, `crypto.py`, catalog JSON.
- Frontend: every page/component/lib file except `health.tsx` and `lib/api.ts` — notably `scan-detail.tsx`, `finding-card.tsx`, `dom-diff-tree.tsx`, `risk-gauge.tsx`, `incident-timeline.tsx`, `visual-diff-slider.tsx`, `alerts.tsx`, `remediation.tsx` (all ×0), and `auth.tsx`.

This confirms PROMPT-003 §0's premise empirically: PROMPT-002's footprint was confined to capture + detection-normalization/fusion; the orchestration, alerting, RBAC, AI, and most frontend layers have had **zero** independent scrutiny in both efforts.

#### 5. Prior-History Sweep — cross-checked dispositions (each re-verified against CURRENT code today, Rule 13)

**CLOSED — verified fixed (no action):**
- `[Low]` logout auth invariant missing (FINDINGS:458) → `[FIXED]` FIXLOG:1729.
- `[Medium]` README "separate Celery queue" claim (FINDINGS:4480) → `[FIXED]` FIXLOG:1600 (docs corrected, no queue split shipped).
- `[Low]` frontend type-check vacuously succeeding (FINDINGS:4621) → `[FIXED]` FIXLOG:2495 (`pnpm type-check` now real).
- `[Low]` torch invisible to pip-audit (FIXLOG:198 "Phase 40's to close") → **closed today**: `.github/workflows/ci.yml:67-70` runs `tools/check_torch_osv.py` against the OSV endpoint; `pyproject.toml:121-123` bandits-scans it (S310 exemption).

**STILL OPEN TODAY — confirmed on current code (become Findings AUDIT-2B-1 … AUDIT-2B-6 below).**

- **AUDIT-2B-1 — External stylesheet bytes are never captured: stylesheet-hidden content (linked CSS only) is invisible to the DOM detection layers**
  - **Severity**: Medium (a real hiding technique — content/links hidden purely by rules in a *linked* stylesheet — passes every DOM-based layer; not a regression, a documented coverage boundary left open)
  - **Subsystem / file(s)**: `worker/detection/dom.py` (:13-17 comment discloses it), `worker/fetcher.py`, `worker/page_prepare.py`
  - **Reproduction**: code inspection — no stylesheet fetch exists anywhere in `worker/` (grep: only `dom.py`'s inline `<style>` parsing `_stylesheet_rules` :278-290 and the conservative resolver :167-174, which operate on inline CSS text within the captured DOM string)
  - **Root cause**: the capture contract stores only the rendered DOM string + artifacts; external stylesheet bytes were never added to `PageData` (first surfaced in FIXLOG:1027; PROMPT-002 never mentions "stylesheet" — 0 hits)
  - **Proposed remedy category**: detection-coverage extension (fetch linked same-origin CSS through the SSRF-safe transport into `PageData`, extend `dom.py`'s hidden-content rules to sheet bytes) — or an explicitly re-documented accepted boundary
  - **Source**: prior-history sweep (FIXLOG:1027) + cold re-verification
- **AUDIT-2B-2 — Detection sub-threshold emission gaps persist and their corpus rows were dropped, so no standing guard covers them**
  - **Severity**: Medium
  - **Subsystem / file(s)**: `worker/detection/{signatures,semantics,visual}.py`, `tools/build_regression_corpus.py`
  - **Reproduction**: PROMPT-002 log :1893-1896 — corpus axes `visual_hue_recolor`, `seo_spam_beyond_cap` (and one of `nonnative_*`) dropped as "channel-adjacent duplicates"; PROMPT-002 log and current code show no emission improvement for hue-only recolors, beyond-cap SEO spam, or partial non-Latin text
  - **Root cause**: pre-PROMPT-002 documented emission gaps (FIXLOG:474, :595) were never closed; PROMPT-002's corpus re-pin *removed* their last standing representation instead of adding one
  - **Proposed remedy category**: either emission-side detection work or explicit `accepted_gap` corpus entries (per O-4's standing report idea)
  - **Source**: prior-history sweep + PROMPT-002 log line evidence
- **AUDIT-2B-3 — Remediation claim "crash-after-claim" window: a won claim commits before execution; an executor crash leaves a terminal `confirmed` row that is never re-runnable (caller sees 409 forever)**
  - **Severity**: Medium
  - **Subsystem / file(s)**: `app/remediation.py`, `worker/remediation_tasks.py`, `app/routers/remediation.py`
  - **Reproduction**: code-path reading (FIXLOG:1079 disclosed it as residual); PROMPT-002 has 0 hits for claim-race/crash-after-claim — untouched by both prior efforts
  - **Root cause**: claim-wins-then-execute ordering with no terminal-row recovery/timeout path
  - **Proposed remedy category**: recovery semantics (lease/timeout reclaim, or a surfaced terminal-state remediation action)
  - **Source**: prior-history sweep

- **AUDIT-2B-4 — `imports.py` still enqueues baseline captures synchronously on the event loop (blocking broker `send_task` per created baseline; `services.py:180` wraps the identical call in `asyncio.to_thread`)**
  - **Severity**: Low (latency-bounded; no correctness defect at realistic scale — the old log's own disposition, re-confirmed today)
  - **Subsystem / file(s)**: `app/routers/imports.py:404-410` vs `app/services.py:180`
  - **Root cause**: inconsistency left from the service-layer deduplication phase (FIXLOG:226)
  - **Proposed remedy category**: mechanical consistency fix for the remediation prompt
  - **Source**: prior-history sweep + cold re-verification
- **AUDIT-2B-5 — `risk-gauge.tsx:19` inline comment still asserts "the scheduler's material-change band"; the material-change band is 0.40 (`scanning.py:58`), the gauge threshold is 0.15**
  - **Severity**: Low (comment/label drift that misleads an operator reading the component; flagged in FIXLOG:2745 and never fixed)
  - **Proposed remedy category**: one-line comment fix + a Phase-9 docs-drift sweep item
  - **Source**: prior-history sweep + cold re-verification
- **AUDIT-2B-6 — Stale/unused dependency declarations: `aiosqlite==0.22.1` (pyproject:70) unused since the Postgres harness; `scikit-learn==1.9.0` runtime pin unused by runtime code (build-time only, pyproject:35)**
  - **Severity**: Low (lockfile churn deferred twice; comment staleness)
  - **Subsystem / file(s)**: `backend/pyproject.toml`, `backend/uv.lock`
  - **Proposed remedy category**: dependency hygiene (regen `uv.lock`) in the Phase-4E supply-chain pass
  - **Source**: prior-history sweep (FIXLOG:166, :458) + cold re-verification

**Open-by-design residuals (re-confirmed, documented, not defects — surfaced for user accept/reject only):** case-variant URL dedup (`http://x` vs `http://x/` distinct); unbounded site-list (no pagination); agent cross-turn injection persistence (out-of-blast-radius subsystem); committed admin seed on air-gapped image builds; no Renovate/SHA-bump automation.

#### Findings out of phase scope (logged for the correct future phase, not investigated here)

- AUDIT-2B-1 → Audit Phase 4 (detection), with the capture-side fetch touching Phase 3's `PageData` contract.
- AUDIT-2B-2 → Audit Phase 4 (+ Phase 8 adversarial fixtures should include one hue-recolor and one beyond-cap-SEO pair to measure the real miss rate).
- AUDIT-2B-3, AUDIT-2B-4 → Audit Phase 4D (orchestration/delivery).
- AUDIT-2B-5 → Audit Phase 4F (frontend) + Phase 9 docs sweep.
- AUDIT-2B-6 → Audit Phase 4E (supply chain).
- telegram-bot chat-id provisioning coupling → noted for Phase 4D's alert-idempotency read only.
- Agent `tools.py` per-tool account-scoping cold pass → optional Phase 4C add-on.

#### Opportunities / Innovation ideas observed (Rule 17 — not severity-scored)

- **Idea O-7 — Machine-readable blast-radius manifest**: have Audit Phase 10 (or a CI step) emit this Phase 2B inventory as a machine-readable `subsystem → files` map (JSON/YAML) kept in the repo; future audits diff scope changes automatically instead of re-walking 587 files, and PR review gains a "what subsystem does this touch?" check.
  - **Why**: PROMPT-002's blind spot was structural (scoping inherited from a previous effort); a manifest makes scope drift visible mechanically.
  - **Where**: `Prompts/` tooling or `backend/tools/`; consumed by audit phases.
  - **Rough shape**: static manifest + one test asserting manifest paths all exist.
- **Idea O-8 — "Comment-asserts-constant" drift spot-check**: the `risk-gauge.tsx:19` stale band comment suggests a small Phase-9 script that greps comments for hardcoded numeric constants and cross-checks them against the named constant's current value; drift becomes a standing report instead of per-audit luck.
  - **Why**: cheap; comment drift is exactly the class Rule 13 keeps re-finding.
  - **Where**: Phase 9 infra/docs pass; `frontend/src/components/risk-gauge.tsx`, `app/scanning.py`.
  - **Rough shape**: read-only checker script; no runtime coupling.

#### Full regression results

No test files or code were added or modified this phase (log-file-only change), so per Rule 5 no suite re-run was required; the last recorded baselines stand (Phase 2, this log: unit batch 110 passed / DB batch 29 passed). Working tree verified clean before and after the log edit; the commit below contains only this log file.

#### Findings out of phase scope — none beyond those routed above.

#### Commit

5d7ac7f — docs(audit-2b): full repository inventory, blast-radius mapping and prior-history sweep

### [DONE] PROMPT-003 Audit Phase 3 — Capture Fresh-Eyes Audit (code-cold, diagnosis only)

- **Prompt**: PROMPT-003-capture-detection-audit-and-stress-hardening.md
- **Session date**: 2026-09-11
- **Assigned subsystem**: §4 Audit Phase 3 — capture stack read cold: `worker/hashing.py` (never independently reviewed — the layer-1 building block), `worker/stealth.py`, `worker/fetcher.py`, `worker/probe.py`, `worker/page_prepare.py`, `worker/banner_dismiss.py`, `worker/artifacts.py`, `app/capture.py`, `app/scanning.py` (lifecycle), `app/models.py` + alembic `o9q1r2s3t4u5` (capture columns only), the seams (`worker/scan_tasks.py` capture paths, `app/tasks.py`, `worker/celery_app.py` queue/retry config, `worker/beat_tasks.py` dispatcher/janitor as capture-adjacent), and every test suite those modules own (intent only, never evidence of correctness).

- **Method note (§3 fresh-eyes protocol)**: every suspicious claim was probed empirically before logging — four scratch probes under `Prompts/Pending/Finders/PROMPT-003/scratch/` (real Chromium via the local pinned Playwright install; no production file touched), one live end-to-end capture through the running Docker worker (`docker exec wardress-worker-1` → `fetch_page('https://example.com')`: evidence matched this reading exactly — 30 selector attempts on a one-frame page, `capture_quality=full`, 10.6 s wall clock), and a 12-pass green run of `tests/test_hashing.py` as the spot baseline for the never-reviewed module.

- **Findings**:

    - **ID**: AUDIT-3-1
    - **Title**: Banner dismissal can store the WRONG page: a generic fallback selector clicks a non-banner control, the click navigates the main frame, and nothing after the click re-validates what is being captured
    - **Severity**: Medium
    - **Subsystem / file(s)**: `worker/banner_dismiss.py:227-236` (generic fallbacks: `button[aria-label*='Accept'/'accept'/'Agree']`, `.cookie-accept`, `.js-cookie-accept`, `#accept-cookies`, …) and `:342-367` (`_find_and_click`); capture ordering in `worker/fetcher.py:592-649` (challenge gate and final-URL SSRF recheck both run BEFORE the click; scroll → stability → `page.content()` all run after)
    - **Reproduction**: `scratch/probe_banner_click_navigation.py` (real Chromium, production `dismiss_banners` unmodified): a content-management dialog button with `aria-label="Accept changes"` and an `onclick` navigation is clicked via `button[aria-label*='Accept']` (evidence `{dismissed: True, selector: "button[aria-label*='Accept']", attempts: 23}`); one second later `page.content()` contains the policy page and no longer the real content — exactly what the capture pipeline would persist as site HTML
    - **Root cause**: `_find_and_click` clicks the first visible element matching the selector list in any frame, with no verification that the element is a consent control; the pipeline treats "clicked something" as safe and never re-checks page identity (URL / challenge state / navigation) after dismissal. A post-click navigation also makes the 250 ms settle + scroll pass race the navigation, so the stored DOM is nondeterministically old-page or new-page
    - **Proposed remedy category**: capture verification — post-dismissal main-frame check (URL + navigation counter + challenge re-probe); if a click navigated, discard the click (re-navigate to the pre-click final URL or mark the capture degraded and skip banner use); optionally narrow the generic fallback selectors to consent-context containers
    - **Source**: fresh-eyes hunt list (banner false-dismiss), scratch probe 2

    - **ID**: AUDIT-3-2
    - **Title**: Late-attaching consent IFRAME banners are never dismissed: `dismiss_banners` snapshots the frame list once before its late-banner wait, and the combined wait is frame-blind
    - **Severity**: Medium
    - **Subsystem / file(s)**: `worker/banner_dismiss.py:393` (frames snapshotted once at entry), `:404` (page-level `wait_for_selector` — main frame only by Playwright semantics), `:407` (final pass reuses the stale snapshot)
    - **Reproduction**: `scratch/probe_frame_wait_budget.py` (real Chromium): control with an iframe banner visible from load → 2 frames at first pass, banner clicked (Phase 5's tested shape). Late variant (iframe revealed 2.5 s after load): `page.wait_for_selector(combined)` times out (3000 ms, frame-blind), and the final `_find_and_click` pass records 60 attempts = 30 selectors × 2 passes × 1 frame while `len(page.frames)` is 2 — banner never clicked, full 3 s budget burned
    - **Root cause**: `_frames(page)` is computed once before the bounded wait; a CMP iframe that attaches during the 3 s budget is invisible to both the wait and the final pass. For such sites the overlay stays up (frequently with a body scroll-lock that no-ops `scrollBy`, so the scroll pass loads no lazy content) while the capture can still be labeled `full`
    - **Proposed remedy category**: local fix — re-snapshot frames before the final pass and/or wait frame-aware (per-frame selector wait, or wait for frame attach)
    - **Source**: fresh-eyes hunt list (banner/scroll interplay under slow origins), scratch probes 3/3b

    - **ID**: AUDIT-3-3
    - **Title**: The browser capture path still has an open DNS-rebinding window — the route guard's per-host verdict cache widens it page-wide, and `probe_tls` resolves independently of the pinning transport
    - **Severity**: Medium
    - **Subsystem / file(s)**: `worker/fetcher.py:287-340` (`_make_ssrf_route_guard`: verdict cache keyed `scheme://host` per fetch; `route.continue_()` lets Chromium resolve DNS independently at connect); `app/ssrf.py:11-20` (docstring concedes the class for "Playwright navigation" only); `worker/probe.py:93-94` (`asyncio.open_connection(host, …)` — raw-socket TLS probe never pinned; `SSRFPinningTransport` covers only the httpx probe client)
    - **Reproduction**: `scratch/probe_ssrf_verdict_cache.py` (production guard, counting stub): 5 requests to the same host → exactly 1 `assert_url_allowed` invocation; the cache never re-validates and is never invalidated for the life of the fetch. Code trace: nothing pins the address Chromium connects to, so validation and connection are separate resolutions; `probe_tls` is a third, unpinned network path (validated in `probe_site`, connected in `probe_tls`)
    - **Root cause**: the guard delivers *validation*, not *pinning*; Phase 5 closed the rebinding window for the httpx probe path only. The verdict cache (documented as an optimization) extends the unvalidated window from one request to the whole page load — every subresource from a once-allowed host is trusted for the page's lifetime although each is resolved afresh by Chromium
    - **Proposed remedy category**: architectural — extend DNS pinning to the browser path (proxy subresource fetches through an `SSRFPinningTransport`-backed fulfiller, or pre-resolve and connect by validated literal IP), and pin `probe_tls` to a pre-validated address
    - **Source**: fresh-eyes hunt list (capture→network contract); the *class* is documented, but the subresource-cache widening and the unpinned TLS-probe path are not

    - **ID**: AUDIT-3-4
    - **Title**: Artifacts of failed/aborted captures are never cleaned, and concurrent duplicate execution can overwrite a committed scan's artifacts (non-atomic writes, no fencing)
    - **Severity**: Low
    - **Subsystem / file(s)**: `worker/scan_tasks.py` (`store_artifacts` runs before the DB commit; `_run_scan`'s running-status guard deliberately permits re-execution under acks_late redelivery); `worker/artifacts.py:21-24` (direct `write_text`/`write_bytes`, no tmp+rename); `worker/beat_tasks.py:271-291` (janitor removes dirs only when the DB row is GONE)
    - **Reproduction**: code-trace (no probe needed): a soft-time-limit kill after `store_artifacts` leaves the row failed-but-present → the janitor skips it forever; a broker-redelivery duplicate (connection loss while the original still runs) has two writers to `scans/<id>/page.html` — the loser can overwrite artifacts after the winner's commit, breaking the row's artifact ↔ `content_hash` correspondence
    - **Root cause**: artifact lifecycle is tied to row existence, not row state/age; writes are non-atomic and unfenced
    - **Proposed remedy category**: retention/lifecycle — state- and age-aware janitor scope; atomic artifact writes (tmp+rename); optional capture fencing (generation token) for the duplicate window
    - **Source**: fresh-eyes hunt list (partial-write/crash-consistency, stale reuse)

    - **ID**: AUDIT-3-5
    - **Title**: Capture-completeness facts never reach detection: a silently truncated capture (scroll time-cap, screenshot cap, unstable DOM) is compared against the baseline as if complete
    - **Severity**: Medium
    - **Subsystem / file(s)**: `worker/scan_tasks.py:339` (`capture_evidence` stored on the scan row only); `worker/detection/types.py:12-24` (`PageData` has html/screenshot/headers/tls/robots/hash — no completeness flags); `worker/page_prepare.py` (20 s scroll cap, 5 s stability cap); `worker/fetcher.py:377-416` (16 384 px screenshot cap)
    - **Reproduction**: code-trace: `run_detection(baseline_page, current_page)` receives none of `capped` / `stable` / `screenshot_capped` / `capture_quality`; a baseline captured full vs a scan capped at 20 s on an infinite-scroll site produces a text/structure/visual diff of the truncation, not of the site (and truncation can hide below-fold injected content — a miss path)
    - **Root cause**: `capture_evidence` was designed "debugging metadata only" (Phase 4/7) and no later consumer bridges capture completeness into the detection inputs; the layers' only degradation knowledge is empty-artifact presence
    - **Proposed remedy category**: contract extension — carry capture-quality flags in `ScanPageData`/`PageData` (capture half); how layers weight them is Phase 4's detection half. Same axis as AUDIT-2B-1 (absent stylesheet bytes): both are things the capture promises detection nothing about
    - **Source**: fresh-eyes hunt list (capture→detection contract)

    - **ID**: AUDIT-3-6
    - **Title**: Per-scan request multiplication × adaptive cadence = a WAF-escalation feedback loop with no per-host request budget
    - **Severity**: Low
    - **Subsystem / file(s)**: `worker/probe.py:216-235` (robots + 3 sequential raw UA fetches per capture, including a `googlebot` UA from a non-Google IP — a classic WAF tripwire); `worker/fetcher.py` (1-2 Playwright loads via the Phase-6 retry); `app/scanning.py:36` (change → cadence base/4, min 5 min); `worker/celery_app.py:37-45` (limits sized for the composition)
    - **Reproduction**: arithmetic trace: one scan ≈ 1-2 browser loads + 4 raw fetches + TLS handshake ≈ 6-7 requests; on a WAF-protected site a detected (or false) change tightens cadence to ≥ every 5 min → ~6-7 requests/5 min → rising block probability → challenge-failed scans → operator noise; the fixed 3 s single retry (no jitter/backoff) re-hits a soft block at full rate
    - **Root cause**: a request budget per site per time is nowhere capped or cooled down; the UA rotation is deliberately unstealthed (design) but its WAF-escalation interaction with the tightened cadence was never examined
    - **Proposed remedy category**: operational policy — per-host request budget/cooldown after repeated bot-protection failures; consider gating the `googlebot` UA variant
    - **Source**: fresh-eyes hunt list (WAF-block escalation through repeated probes)

    - **ID**: AUDIT-3-7
    - **Title**: `hashing.py` (never independently reviewed): sound — with one latent hardening note
    - **Severity**: Low
    - **Subsystem / file(s)**: `worker/hashing.py`
    - **Reproduction**: `scratch/probe_hashing_edges.py`: normalization is deterministic and conservative exactly as documented — CRLF/CR equal to LF, trailing NBSP/narrow-NBSP/tab stripped (Unicode whitespace), interior NBSP preserved as content, blank-line strip exact, lone-surrogate encode stable across runs (errors="replace"), hash = sha256(normalized UTF-8) verified against a manual computation; `tests/test_hashing.py` 12/12 green
    - **Root cause (of the note)**: `content_sha256(None)` raises `AttributeError` (`'NoneType' object has no attribute 'replace'`). Current callers always pass `str`, so this is latent, not live
    - **Proposed remedy category**: hardening — guard or assert the `str` invariant at the one shared entry point so a future degraded path cannot turn a capture gap into a task crash
    - **Source**: fresh-eyes cold read of the never-touched layer-1 module (hunt list)

    - **ID**: AUDIT-3-8
    - **Title**: `auto_scroll_page` counts a SHRINKING page height as "stable" and can end the walk early
    - **Severity**: Low
    - **Subsystem / file(s)**: `worker/page_prepare.py:119` (`stable_steps = stable_steps + 1 if height <= last_height else 0`)
    - **Reproduction**: code-trace: two consecutive steps with a shrinking height (lazy placeholders collapsing, dynamic sections unloading) plus `at_bottom` satisfy the break condition while below-fold lazy content may still be pending; the capture is not flagged partial (`capture_quality` only flags `capped`/unstable/screenshot-cap)
    - **Root cause**: "stopped growing" was implemented as `<=`, conflating shrink with settle
    - **Proposed remedy category**: local heuristic fix — treat shrink beyond an epsilon as churn (reset `stable_steps`) or require strictly non-shrinking stability
    - **Source**: fresh-eyes hunt list (infinite-scroll kill criteria)


- **Log-vs-reality discrepancies**: none. The live Docker capture's evidence dict matched the documented Phase-7 assembly key-for-key; no PROMPT-002 log claim was re-verified (out of scope for this phase — that was Audit Phase 1).

- **New hermetic tests added this phase**: none committed. Four scratch probes live under `Prompts/Pending/Finders/PROMPT-003/scratch/` (documented-as-scratch per Rule 5/10): `probe_hashing_edges.py`, `probe_banner_click_navigation.py`, `probe_frame_wait_budget.py` (plus the HTML fixtures it writes), `probe_ssrf_verdict_cache.py`. None assert against changed production behavior (Rule 1 — diagnosis only); the remedy phases for AUDIT-3-1/3-2/3-3 should convert the relevant probes into hermetic FAILED-before tests.

- **Opportunities / Innovation ideas observed** (Rule 17):
    - **Idea**: record the main-frame navigation count during the dismissal window in `capture_evidence` (the `nav_responses` list already tracks it) — a one-line invariant signal that a banner click navigated, making AUDIT-3-1's failure mode visible in evidence even before any fix.
    - **Why it would help**: turns a silent wrong-page capture into an observable capture-health event.
    - **Where it touches**: `worker/fetcher.py` (evidence assembly), `worker/banner_dismiss.py` (return shape).
    - **Rough shape of the change**: pass the `nav_responses` length in/out of `dismiss_banners`; add `main_frame_navigations_during_dismissal` to banner evidence.
    - **Idea**: run `probe_site`'s three raw UA fetches concurrently (bounded by the existing `max_connections=4`).
    - **Why it would help**: cuts the documented ~90 s worst-case probe tail roughly 3×, shrinking the capture wall clock the Celery soft-limit budget and the stale-inflight margin must absorb.
    - **Where it touches**: `worker/probe.py` (`probe_site`'s loop over `USER_AGENTS`).
    - **Rough shape of the change**: `asyncio.gather` over `_fetch_raw`, with the desktop-Chrome reference's headers still assigned to `result.headers`.
    - **Idea**: inventory captured CSS assets now (`link[rel=stylesheet]` URLs + sha256 of their bytes, recorded in `capture_evidence`) as a cheap, detection-free first step toward AUDIT-2B-1's capture half.
    - **Why it would help**: defacements increasingly live in linked stylesheets; the inventory creates the data axis without touching any layer.
    - **Where it touches**: `worker/fetcher.py` (response hook filtering `text/css`), `capture_evidence` schema, `CAPTURE_METHOD_VERSION` bump consideration.
    - **Rough shape of the change**: a response listener keyed on main-frame stylesheet requests; hashes into evidence (bytes storage can follow in the remediation phase).

- **Full regression results**: no production code was edited (Rule 1), so no full regression was owed; spot check: `backend\.venv\Scripts\python.exe -m pytest tests/test_hashing.py -q` → **12 passed** (the never-reviewed module's own suite, confirming the green baseline my probes measured against). Docker stack healthy throughout (app/worker/beat/db/redis up; live `fetch_page('https://example.com')` through the worker container returned a complete evidence dict).

- **Findings out of phase scope**: the detection half of AUDIT-3-5 (how layers weight capture-completeness flags) → Phase 4; the detection half of AUDIT-2B-1 (stylesheet bytes) → Phase 4; the API artifacts-surface implications of AUDIT-3-4 → Phase 4C; orchestration/scheduling depth (stale-supersede arbitration and beat claim mechanics were read and verified sound, not re-audited) → Phase 4B.

- **Commit**: 5b0a884 — docs(audit-3): capture fresh-eyes audit — wrong-page banner clicks, stale frame snapshot, rebinding-window widening, artifact janitor gaps
- **Next phase kickoff prompt**: (delivered in chat only — never written to this log)



### [DONE] PROMPT-003 Audit Phase 4 — Detection-Pipeline Fresh-Eyes Audit (layers 1-9 + suppress + normalize + fusion + llm_escalation)

- **Prompt**: PROMPT-003-capture-detection-audit-and-stress-hardening.md
- **Session date**: 2026-09-11
- **Assigned subsystem**: §4 Audit Phase 4 — detection pipeline: `worker/detection/*` (pipeline, types, suppress, normalize, dom, signatures, semantics, metadata, cloaking, visual, fusion, training artifacts), `worker/llm_escalation.py`, `worker/hashing.py` as layer-1 input contract (built on AUDIT-3-7, not re-derived), the `scan_tasks.py` capture→detection seam, and the detection-owned test files (read for intent, never treated as evidence).

## Method

Every layer module was read end-to-end cold (caller/callee traced through `pipeline.run_detection` → `scan_tasks._run_scan` → verdict/escalation/scheduling), then every suspicious claim was verified empirically in the running Docker install (`wardress-worker-1`): 12 hermetic probes + a committed characterization suite. No production code was touched (Rule 1).

## Findings

- **ID**: AUDIT-4-1
- **Title**: `_new_text` granularity collapses for unpunctuated pages — the "new-text-only" lexicons silently become whole-page lexicons, and a benign edit FLAGGED at risk ≈0.86
- **Severity**: Critical
- **Subsystem / file(s)**: `worker/detection/signatures.py:197-211` (`_new_text` piece splitter), consumed by `worker/detection/semantics.py:120-123` (`_new_visible_text`); feeds `layer5_signatures` (:248-334) and `layer8_semantics` (:235-303); verdict path `worker/scan_tasks.py:309` (`flagged = risk >= site.flag_threshold`, default 0.5)
- **Reproduction** (all verified live in `wardress-worker-1` + pinned in `backend/tests/test_phase4_fresh_eyes_finding_repros.py::TestAUDIT4x1NewTextGranularity`):
  1. `extract_visible_text` returns one joined line; `_new_text` splits it into pieces by lines ∪ sentence boundaries (`(?<=[.!?])\s+`). A page without `[.!?]` is ONE piece, so any edit anywhere makes the ENTIRE current text "new" (probe: `new_text == extract_visible_text(current)` verbatim).
  2. Unpunctuated page containing the word "fuck" in its baseline nav; benign edit elsewhere ("ship quality" → "ship premium quality"): `layer5_signatures` scores 0.25 (profanity that was ALWAYS there), `layer8` same shape with aggression lexicon (0.568 from "corruption"/"regime"/"war on" — all baseline-present).
  3. Full `run_detection`: fused risk **0.857** → verdict `flagged` at the default threshold → alert + remediation created. Punctuated control of the same page: layer5 0.0.
- **Root cause**: the piece-set subtraction is only as fine-grained as the sentence-boundary density of the page. Layer 5's and layer 8's core FP defense ("run on new text only, so pages that always contained a term don't flag") has an unstated precondition — pages must punctuate. `test_phase20_semantics_drift.py::test_lexicon_stays_new_text_only` pins the claim only on an identical-html fixture, so the unguarded shape never surfaced.
- **Proposed remedy category**: detection-pipeline semantics change — make `_new_text` granularity boundary-independent (e.g. token/shingle set subtraction, or line-window fallback when a piece exceeds a length bound), PLUS a regression gate on unpunctuated pages carrying baseline-present lexicon vocabulary end-to-end asserting `clean`. Implementation in a remediation prompt.
- **Source**: fresh-eyes hunt list (text/semantic layers — new-text extraction failure modes)

- **ID**: AUDIT-4-2
- **Title**: Layer 6 reads CURRENT-side probe transients as measured evidence-of-change (inverse of the degraded-channel design): a TLS probe failure scores 0.6, pushing a benign scan into the LLM escalation band and MATERIAL_CHANGE_RISK
- **Severity**: High
- **Subsystem / file(s)**: `worker/detection/metadata.py:178-182` (`_tls_diff`: baseline-TLS-present + current-None → 0.6, measured, never degraded); `worker/detection/metadata.py:265-278` (`_robots_diff`: baseline None + current content → 0.15 on every scan after a baseline-side robots probe transient); `worker/probe.py:78-139` (`probe_tls` returns None for BOTH "plain http" and ANY handshake failure — indistinguishable); `worker/detection/training/fusion_model.json` (layer6 coefficient 2.588)
- **Reproduction** (live + pinned `::TestAUDIT4x2MetadataProbeTransient`): unchanged site, `baseline.tls` set, scan's `probe_tls` transiently fails (timeout/handshake error — indistinguishable from a scheme change): `layer6` = 0.6, `degraded` absent. Fused with ordinary byte churn (layer1 = 1.0, content layers normalized-silent): risk **0.429** → `should_escalate` True (LLM second opinion) AND ≥ MATERIAL_CHANGE_RISK 0.40 → cadence tightened on a healthy site. Verdict is at minimum `changed`. Asymmetric: the reverse transient (baseline-side TLS probe failed, every scan has TLS) scores 0.0 forever ("newly available").
- **Root cause**: `probe_tls`'s contract collapses three different facts (plain-HTTP site, handshake failed, transport torn down) into one `None`, and layer 6 then treats the single most failure-prone probe channel as a certificate-change observation. Layer 6 is the only content-independent layer without a probe-failure degraded path for this case (layer 4 degrades on unreadable screenshots; layer 7 degrades on a dead reference fetch; fusion's unmeasured machinery never engages because 0.6 is a *measured* score).
- **Proposed remedy category**: probe-contract extension (structured absence reason on `tls`/`robots_txt`: scheme-absent vs probe-failed) + layer 6 semantics change (degrade on probe-failed reasons; keep 0.6 only for genuine scheme/absence observations; make the baseline/current asymmetry symmetric). Implementation in a remediation prompt.
- **Source**: fresh-eyes hunt list (dark channels read as trusted/attack values; capture-completeness flags)

- **ID**: AUDIT-4-3
- **Title**: A statically expired certificate scores 0.5 on layer 6 on EVERY scan — a permanent `changed` verdict for a static property
- **Severity**: Medium
- **Subsystem / file(s)**: `worker/detection/metadata.py:209-211` (`_tls_diff`: `current_tls["expired"]` → `max(score, 0.5)` with no baseline comparison)
- **Reproduction** (live + pinned): identical unchanged pair, both sides `expired=True`: layer6 = 0.5 on every scan → verdict `changed` every scan, forever (risk stays ~0.01 — no alert — but the site never reads `clean` again and `layer_scores` shows a phantom delta on every row).
- **Root cause**: expiry is treated as a per-scan change event although it is a persistent state; the layer's own compare-baseline-vs-current semantics are abandoned for this one field.
- **Proposed remedy category**: layer 6 semantics change — score the *transition* into expired (baseline not-expired → current expired), or emit expiry as structured static-condition evidence rather than score. Implementation in a remediation prompt.
- **Source**: fresh-eyes hunt list (layer-by-layer promise vs emission)

- **ID**: AUDIT-4-4
- **Title**: A regex suppression rule that times out mid-document is applied to a DIFFERENT element range on each side — the suppression itself manufactures the delta it was meant to silence (and the scan pays up to the full per-call timeout budget per text node)
- **Severity**: Medium
- **Subsystem / file(s)**: `worker/detection/suppress.py:143-163` (`_apply_to_html`: `TimeoutError` aborts the element loop at whatever node the side happened to reach; per-call `timeout=_REGEX_TIMEOUT_SECONDS` (2.0 s) bounds one `sub()`, not the rule; `supp.unusable` accumulates one duplicate entry per side)
- **Reproduction** (live + pinned `::TestAUDIT4x4SuppressionTimeoutAsymmetry`): rule `(a|aa)+b|Session id: \d+` (a genuine `regex`-module time-bomb — `(a+)+b`-class patterns are optimized away, this one is not), page pair where the pathological node sits FIRST on baseline and LAST on current: baseline's loop times out on node 1 → NO substitution anywhere ("Session id: 12345" kept); current's loop applies node 1 then times out on node 2 ("Session id: 12345" removed). Full pipeline on the pair: layer8 similarity drops to 0.773 → drift 0.354, fused risk **0.417** → LLM escalation band + MATERIAL_CHANGE_RISK cadence tightening, from a user rule whose entire purpose was silence. Evidence records `unusable_rules` twice (once per side) — the audit trail shows the timeout but not the asymmetry it caused.
- **Root cause**: partial application is accepted per side independently; nothing requires the two sides to receive the SAME subset of rewrites, and the 2 s budget is per `sub()` call so a rule that times out only on long nodes can burn nodes×2 s before its first timeout (and its first-timeout abort point is document-order-dependent, which is exactly what differs between sides).
- **Proposed remedy category**: suppress.py semantics change — all-or-nothing per rule (pre-flight the rule over both sides' text nodes; if ANY side times out, apply on NEITHER and record unusable once), plus a per-rule total time budget. Implementation in a remediation prompt.
- **Source**: fresh-eyes hunt list (suppression interplay — can a suppression rule manufacture/mask attack evidence)

- **ID**: AUDIT-4-5
- **Title**: An unparseable/empty side is a MEASURED 1.0 in layer 2 (and layer 5/8/3 silently degrade their text inputs) — the current-side equivalent of `baseline_html_missing` has no guard
- **Severity**: Medium
- **Subsystem / file(s)**: `worker/detection/dom.py:528-541` (`layer2_dom_structure` parse-differential branch); `worker/detection/pipeline.py:129-166` (the degraded guard exists for the BASELINE side only; `current.html` empty from a "successful" fetch diffed as real page content); `worker/fetcher.py:649-655` (no lower bound on captured html)
- **Reproduction** (live + pinned `::TestAUDIT4x5EmptyCurrentCapture`): baseline real, current `""`: layer2 returns score **1.0** ("one side failed to parse as HTML"), no `degraded` flag — a full structural-annihilation reading from a capture accident, treated by fusion as measured evidence. Mirror case (both sides unparseable) returns a measured 0.0 — the same "trusted zero from measurement failure" shape the degraded_result design was built to prevent.
- **Root cause**: the pipeline's degraded-input guard is asymmetric (baseline side only), and layer 2 collapses "no DOM on one side" (a capture/parse fact) with "the page's structure changed" (a content fact) into one measured score.
- **Proposed remedy category**: pipeline/layer semantics change — emit `degraded_result` when either side is unparseable-empty (or, for the both-unparseable case, degrade rather than measured-zero), with a fetcher lower-bound guard as defense in depth. Implementation in a remediation prompt.
- **Source**: fresh-eyes hunt list (silent None/empty field assumptions)

- **ID**: AUDIT-4-6
- **Title**: Layer 3 is blind to removal-only reference changes — an attacker stripping the page's scripts/links/forms reads as a measured 0.0
- **Severity**: Medium
- **Subsystem / file(s)**: `worker/detection/dom.py:704-730` (`layer3_link_audit`: `weights` and `churn_score` are computed over ADDED refs only; `removed` is evidence-only)
- **Reproduction** (live + pinned `::TestAUDIT4x6Layer3RemovalBlind`): baseline with `<script src="https://cdn.vendor.com/x.js">`, current without: layer3 = 0.0, `removed_count: 1` in evidence. Removal-only defacement (vandalism-by-deletion, ripping out a site's own scripts/forms) scores nothing on the one layer whose job is reference sets (layer 6 scores robots deletion; layer 3 doesn't score reference deletion).
- **Root cause**: the score model was built for the injection signal class (new external domains) and never weighted the removal direction; a measured 0.0 is indistinguishable from "references unchanged" downstream.
- **Proposed remedy category**: layer 3 semantics change — weight sensitive-kind removals (scripts/iframes/forms) at a conservative fraction of the additive weights so removal-only tampering is visible without punishing legitimate cleanups into alerts. Implementation in a remediation prompt.
- **Source**: fresh-eyes hunt list (layer-by-layer promise vs emission)

- **ID**: AUDIT-4-7
- **Title**: Detection half of AUDIT-3-5 (owned per Phase 3 handoff): how layers should consume capture-completeness flags — specification
- **Severity**: Medium (same axis as the Phase 3 capture-half finding)
- **Subsystem / file(s)**: `worker/scan_tasks.py:139-156` (baseline `capture_meta` stores NO completeness facts — not even `screenshot_capped`/`capture_quality`, which existed on `FetchResult` at capture time and were dropped except `capture_method_version`); `worker/scan_tasks.py:334-339` (scan-side `capture_evidence` stored on the scan row, explicitly unread by detection); `worker/detection/types.py:12-43` (`PageData`/`ScanPageData` carry no completeness flags); `worker/detection/visual.py` (compares screenshots as if complete)
- **Detection-half specification** (what the remediation prompt should implement once the capture half delivers the flags into both sides of `PageData`): (1) layer 4 must read `screenshot_capped` from EITHER side and, when exactly one side was capped, crop both to the capped extent (preferred — the compared region becomes "top N pixels"); when both capped, mask/annotate the below-cap region as unmeasured rather than diffing pHash/dHash across different page tails; (2) unstable-DOM / scroll-incomplete captures should flow into fusion as a partial-confidence input (a content-completeness scalar, not the full `_UNMEASURED_RISK_CEIL` path), so a silently truncated capture cannot read as a complete diff in either direction; (3) the BASELINE side is the critical gap: a baseline captured capped/unstable permanently poisons every future visual diff against it, and nothing can ever know — `capture_meta` must record the same facts at baseline capture time.
- **Reproduction**: code-trace, verified: `run_detection(baseline_page, current_page)` receives none of `screenshot_capped`/`stable`/`scroll_completed`/`capture_quality`; a capped-vs-uncapped screenshot pair is today compared via `_common_size` top-crop (SSIM) while pHash/dHash see different tails (`visual.py:162-172` computes hashes on the WHOLE images).
- **Proposed remedy category**: contract extension (capture half per AUDIT-3-5) + layer-4/fusion weighting change (this specification). Implementation in a remediation prompt.
- **Source**: Phase 3 handoff obligation (AUDIT-3-5 detection half) + fresh-eyes verification

- **ID**: AUDIT-4-8
- **Title**: Detection half of AUDIT-2B-1 (owned per Phase 3 handoff): which layers consume linked-stylesheet bytes and how — specification
- **Severity**: Medium (same axis as the Phase 2B capture-half finding)
- **Subsystem / file(s)**: `worker/detection/dom.py:13-14` (disclosure: only embedded `<style>` resolvable), `worker/detection/dom.py:163-263` (`_HiddenContext` resolver — the consumer), `worker/detection/signatures.py:110-126` (`extract_visible_text` — adjacent consumer, see Opportunities)
- **Detection-half specification**: (1) primary consumer is layer 2's `_HiddenContext`: once the capture half (AUDIT-2B-1) fetches linked same-origin CSS through the SSRF-safe transport and stores it on `PageData` (e.g. `stylesheets: list[str]`), the resolver's existing conservative subject machinery (last-compound selectors, skip pseudo-classes/@-blocks, document-order cascade, inline overrides) should run over the concatenated sheet bytes exactly as it does over inline `<style>` text, with a per-sheet size cap mirroring `_STYLE_TEXT_CAP`; (2) hidden-state resolution must run on BOTH sides symmetrically so a site that moves rules from inline to linked stylesheets mid-stream does not manufacture a hidden-count delta (today an inline→external refactor silently drops the hidden count on the current side — same fact class as AUDIT-2B-1 itself); (3) `stylesheet_chars` evidence should report per-source counts (inline vs linked) so coverage is auditable.
- **Reproduction**: code-trace (verified against AUDIT-2B-1): no stylesheet fetch exists anywhere in `worker/`; `_stylesheet_rules` runs only on `<style>` inner text; content hidden purely by linked-CSS rules passes the hidden-count channel.
- **Proposed remedy category**: contract extension (capture half per AUDIT-2B-1) + `dom.py` resolver extension (this specification), or an explicitly re-documented accepted boundary. Implementation in a remediation prompt.
- **Source**: Phase 3 handoff obligation (AUDIT-2B-1 detection half) + fresh-eyes verification

## Log-vs-reality discrepancies

- `backend/tests/test_phase20_semantics_drift.py::test_lexicon_stays_new_text_only` — its docstring claims "a page that ALWAYS contained the phrases must not flag", but its fixture runs layer 8 on an *identical* html pair (new_text = ∅ by construction), so the claim is only pinned for identical text, not for "always contained + any edit". The Phase 4 probe (AUDIT-4-1 repro 2) shows the claim's stated scope does not hold on unpunctuated pages. Both behaviors stated: identical-html → 0.0 (as the test asserts); edited unpunctuated html → 0.568 with all three phrases in the baseline (as the probe measured).
- No PROMPT-002/PROMPT-003-log detection claims were contradicted in this phase's scope; the Phase 2B/3 findings I built on (AUDIT-2B-1, AUDIT-3-5, AUDIT-3-7) re-verified as described.

## New hermetic tests added this phase

- `backend/tests/test_phase4_fresh_eyes_finding_repros.py` — 10 tests across 5 classes (AUDIT-4-1, -4-2, -4-3, -4-4, -4-5, -4-6 repros). Characterization tests: they assert the CURRENT (finding) behavior deterministically so the remediation prompt can flip each assertion after fixing. **Committed-passing** (10/10 in 18.4 s). The two heavier ones run the full pipeline/MiniLM (already required by test_phase20/test_phase22 in the same suite). Scratch probe scripts used during verification were removed after their results were recorded here.

## Opportunities / Innovation ideas observed (Rule 17)

- **Idea**: boundary-independent new-text diffing (char-shingle / token-set subtraction with a length-capped piece fallback).
  **Why it would help**: removes the unpunctuated-page cliff (AUDIT-4-1) at the root instead of patching lexicon weights, and makes `_new_text` robust to any future extraction change.
  **Where it touches**: `worker/detection/signatures.py` (`_new_text`), shared by `semantics.py` and `scan_tasks._escalation_new_text`.
  **Rough shape**: subtract multisets of bounded-length shingles/tokens instead of sentence pieces; keep a span-reconstruction step so evidence quotes stay verbatim.

- **Idea**: hidden-aware visible-text extraction.
  **Why it would help**: `extract_visible_text` currently scores text hidden by CSS (inline or, per AUDIT-2B-1, linked sheets) as visible; a hidden-state-aware extractor (consuming `_HiddenContext`) would make layers 5/7/8's token sets match what a visitor actually sees, and give the sheet-bytes work a second consumer.
  **Where it touches**: `worker/detection/signatures.py` (`extract_visible_text`), `worker/detection/dom.py` (`_HiddenContext`), `worker/detection/cloaking.py`.
  **Rough shape**: reuse the hidden reasons layer 2 already computes; exclude hidden-subtree text from 5/8 while keeping a separate evidence counter for "hidden text changed" so hiding cannot become a masking vector.

- **Idea**: structured absence reasons for all probe channels (tls/robots/headers/ua_variants).
  **Why it would help**: one contract change fixes the whole AUDIT-4-2/AUDIT-4-3 class — every layer could then distinguish "observed absent" from "probe failed" and degrade honestly instead of scoring transients.
  **Where it touches**: `worker/probe.py`, `worker/detection/types.py` (`PageData` probe fields), `worker/detection/metadata.py`.
  **Rough shape**: `{"value": ..., "absence": "http-scheme" | "probe-failed(<detail>)"}` wrappers (or a parallel `probe_status` dict) carried on `PageData`.

- **Idea**: layer 7's added/removed tie-break uses the more sensitive additive ramp.
  **Why it would help**: `added == removed > grace` currently routes to the additive channel (ramp from 0.15) even though the pair is balanced — a conservative tie-break (removal ramp) would lower churn noise by a hair without losing injection sensitivity (additive still wins whenever added > removed).
  **Where it touches**: `worker/detection/cloaking.py:117`.
  **Rough shape**: `score = s_removed if added <= removed else s_added` plus a regression pin.

## Full regression results (commands + counts)

All run with `backend/.venv` (`python -m pytest -q -p no:cacheprovider`), production code untouched (test/log files only), so deep rebuild pins (`test_detection_regression.py`, `test_detection_e2e.py` corpus rebuild) were not re-executed:

| Suite | Result |
|---|---|
| `test_phase4_fresh_eyes_finding_repros.py` (new) | 10 passed (18.40 s) |
| `test_rule_floors.py` + `test_csp_nonce_normalization.py` | 48 passed (16.50 s) |
| `test_dom_content_churn.py` + `test_pipeline_visual_gate.py` | 14 passed (1.13 s) |
| `test_suppression.py` + `test_detection_normalize.py` | 45 passed (19.15 s) |
| `test_noise_floor.py` + `test_llm_keypool.py` | 19 passed (16.77 s) |
| `test_fusion_integration.py` + `test_fusion_refit.py` + `test_detection_fusion_pipeline.py` | 65 passed (18.92 s) |
| `test_phase21_cloaking_grade.py` + `test_phase22_signatures_coverage.py` + `test_phase23_dom_hidden.py` + `test_phase36_detection_low.py` | 115 passed (18.91 s) |
| `test_phase24_degradation_signaling.py` + `test_phase20_semantics_drift.py` | 51 passed (18.17 s) |
| **Total** | **367 passed, 0 failed** |

## Findings out of phase scope

- AUDIT-4-2's root cause lives partly in `probe.py` (shared with the Phase 3 capture-fresh-eyes subsystem, which already logged probe-side findings); only the layer-6 consumption half is specified here.
- Escalation-prompt new-text quality (`scan_tasks.py:66-75` passes RAW un-suppressed/un-normalized html to `_escalation_new_text`, so the LLM prompt can contain volatile timestamps the layers already normalized away) — cosmetic, noted as an opportunity-adjacent observation for the remediation prompt; no severity scored.
- Orchestration/scheduling mechanics (`_schedule_next`, beat dispatch, stale-inflight) untouched here — Phase 4B.

## Commit

2928507 — test(audit-4): detection fresh-eyes audit — finding repros + Phase 4 log entry (recorded post-commit; not pushed)

---

### [DONE] PROMPT-003 Audit Phase 4B — Orchestration & Scheduling Fresh-Eyes Audit (Celery app config, beat dispatcher, task enqueue/claim/dedup, retry-ack idempotency, adaptive cadence coupling)

- **Prompt**: PROMPT-003-capture-detection-audit-and-stress-hardening.md
- **Session date**: 2026-09-11
- **Assigned subsystem** (per kickoff; the main file's §4 map labels 4B "API surface" — per §3.6 the kickoff + Phase 2B inventory govern, and 4C will take the API surface): `backend/worker/celery_app.py`, `worker/scan_tasks.py`, `worker/beat_tasks.py`, `worker/db.py`, `worker/alert_tasks.py`, `worker/remediation_tasks.py`, `app/scanning.py`, `app/tasks.py`, the claim/supersede paths of `app/services.py`, the enqueue sites in `app/routers/*`, the in-flight arbiters in `app/models.py` + migrations `g1h2i3j4k5l6`/`k5l6m7n8p9q1`, `docker-compose.yml` (app/worker/beat/redis) and `Dockerfile.worker`. Detection layers NOT re-audited (Phase 4); build on AUDIT-4-* as upstream inputs only.

- **Environment attestation (Rule 13, live-stack parity)**: the running Docker stack is NOT built from a single commit — container files hash-match HEAD for `celery_app.py`, `beat_tasks.py`, `models.py`, `services.py`, `tasks.py`, `alert_tasks.py`, `remediation_tasks.py`, but the deployed `scan_tasks.py` predates PROMPT-002 Phase 11 (NO `NOISE_FLOOR`; verdict `changed` fires on ANY nonzero score) and the deployed `scanning.py` differs comment-only (MATERIAL_CHANGE_RISK=0.40 identical, code identical). Consequence: live probes below attest HEAD orchestration mechanics exactly; verdict-path observations differ from HEAD only in `changed` semantics, which the cadence coupling does NOT consume (scheduling `changed` = `flagged or risk >= MATERIAL_CHANGE_RISK`, independent of the verdict noise floor). Recorded as AUDIT-4B-8 for the remediation prompt (rebuild before remediation-phase verification). The user-reported image commit `1eeea6b` is an ancestor of HEAD but is not what the containers actually contain (mixed build) — the hash diff above is the authoritative parity statement.

- **Findings**:

    - **ID**: AUDIT-4B-1
    - **Title**: Alert/Remediation creation is unreachable on the redelivery path — a worker death in the post-commit handoff window silently and permanently loses the alert (and remediations) for a flagged scan
    - **Severity**: High — justified: detection→notification is the system's core output; the loss is silent (no operator-visible trace, no retry, no recovery sweep covers it), and reaches beyond kill scenarios (a DB hiccup or SoftTimeLimitExceeded inside `_create_alert`'s commit propagates, the wrapper's `_mark_scan_failed` no-ops on the completed row, the task returns "error" and is ACKED — no redelivery). The window is small (sub-second typically) but non-zero on every flagged scan.
    - **Subsystem / file(s)**: `worker/scan_tasks.py` `_run_scan` terminal flow (terminal `db.commit()` → `_create_alert` → `_create_remediations` → `_schedule_next`; `_create_alert` around :371-380; early idempotent return near :206-210). Sole creation sites proven by grep: `Alert(` only at `scan_tasks.py:380`, `RemediationExecution(` only at `app/remediation.py:144`. `worker/beat_tasks.py` `resweep_undelivered` (re-enqueues deliveries for EXISTING alerts with zero AlertDelivery rows and EXISTING queued executions — cannot create missing rows). Idempotency backstops `alerts.scan_id` UNIQUE and `uq_remediation_executions_hook_scan` (models.py:706 / migration f3c8d6a91b27) guard double-creation, not non-creation.
    - **Reproduction**: hermetic, committed-passing: `tests/test_phase4b_orchestration_repros.py::test_flagged_scan_redelivery_cannot_recover_missing_alert` — completed flagged scan (risk 0.9) with no alert row; `_run_scan` returns `"scan-already-completed"` without creating one; `_resweep_undelivered()` reports `alerts_reenqueued == 0` and still none exists. Contrast positive control `test_resweep_recovers_stranded_alert_enqueue` (alert exists → re-enqueued, send captured).
    - **Root cause**: PROMPT-002 Phase 4's terminal-commit idempotency property (findings cleared-and-rewritten) was applied to the write-side but not the creation-side handoffs: alert/remediation rows are separate transactions AFTER the terminal commit, and no recovery primitive re-derives them from the persisted scan.
    - **Proposed remedy category**: recovery-from-persisted-state — either fold Alert/RemediationExecution creation into the scan's terminal transaction, or extend `resweep_undelivered` to create missing Alert/RemediationExecution rows for completed flagged scans (fully derivable from the scan row + site/hook config, guarded by the existing unique indexes). Not implemented here (Rule 1).
    - **Source**: kickoff hunt list "alert/remediation enqueue after commit vs crash windows"; Phase 4's cleared-and-rewritten observation generalized.







    - **ID**: AUDIT-4B-2
    - **Title**: Stale-inflight sweep treats legitimately-backlogged PENDING scans as lost enqueues; under sustained overload each tick replaces stale pending rows with fresh messages while the old messages stay queued — amplification, not load shedding
    - **Severity**: Medium — justified: needs sustained overload (dispatch rate > drain rate; reachable when many sites tighten toward MIN cadence at once — which AUDIT-4B-3 makes more likely), but the mode is self-reinforcing: failed-scan history churn ("superseded" rows that were merely queued), unbounded no-op message growth (each supersede leaves the original broker message in place to be dequeued and no-op'd later), and no backpressure anywhere on the path.
    - **Subsystem / file(s)**: `app/scanning.py` `is_stale` (:17-28; pending anchor = `created_at`), `worker/beat_tasks.py` supersede block ("Scan never completed — superseded by a scheduled scan"), `MAX_DISPATCH_PER_TICK = 50`/60 s (:46-49), `Dockerfile.worker` CMD (prefork; concurrency 12 verified live; per-scan hard limit 480 s → worst-case drain 12 scans/8 min vs enqueue up to 50/60 s).
    - **Reproduction**: hermetic, committed-passing: `test_backlogged_pending_scan_superseded_by_dispatch_tick` — pending row aged 15 min is failed+superseded and a fresh scan enqueued; the old row's own redelivery no-ops (`"scan-already-failed"`). A live overload soak was deliberately NOT run (would saturate the shared stack for tens of minutes); the supersede path itself was verified live (AUDIT-4B-5 scenario).
    - **Root cause**: DB state cannot distinguish "message lost" from "message queued behind a slow worker"; the sweep optimizes for the former and pays the latter. No queue-depth signal gates dispatch (the health router's `_queue_depth` exists but scheduling never reads it).
    - **Proposed remedy category**: capacity-aware dispatch gating — bound enqueues per tick by observed queue depth / worker capacity (e.g., skip dispatch when broker queue depth exceeds workers × in-flight budget), and/or anchor pending-staleness to due-time rather than a fixed 10 min. Not implemented here.
    - **Source**: resource/convoy hunt item; "pending rows whose task message was lost" timer/lifecycle item.




    - **ID**: AUDIT-4B-3
    - **Title**: Adaptive cadence consumes raw fused risk without the capture-degradation signal — AUDIT-4-2 transients pin a site at base/4 cadence while they recur, and every extra scan feeds AUDIT-4B-2's amplification
    - **Severity**: Medium — justified: chronic over-scanning of noisy/flaky sites (interval pinned at base/4..base/3 for any transient period shorter than the relax ladder; base 24 h → 6 h indefinitely under alternating transients), plus "changed"-verdict history noise (worse on the deployed pre-Phase-11 build — see AUDIT-4B-8). No false-alert impact: the alert path is `flagged`-gated and untouched by cadence.
    - **Subsystem / file(s)**: `worker/scan_tasks.py` `_schedule_next` (`changed = flagged or risk >= MATERIAL_CHANGE_RISK`, never consults `layer_scores[*].degraded`), `app/scanning.py` `next_interval_after_scan` (:65-74; tighten = `base // TIGHTEN_DIVISOR` regardless of current; relax = ×1.5 capped at base; boundary behavior otherwise verified clean: MIN/MAX clamps, shrink-base cap, round-half-even monotonicity harmless).
    - **Reproduction**: hermetic, committed-passing: `test_repeated_material_risk_transients_hold_cadence_at_base_quarter` — alternating changed/clean from base 1440 yields 360,540,360,540,… (never returns to base); clean-only ladder = [360, 540, 810, 1215] → 1440 (four clean scans to recover). Risk-band numbers from AUDIT-4-2 (probe-side transients fuse ≥ 0.40), NOT re-derived per scope.
    - **Root cause**: the scheduling input is a single fused scalar; the per-layer `degraded` flag (Phase 24; Audit Phase 4 Lead 1) sits in `layer_scores` one dict lookup away but the one consumer that converts a transient into repeated work ignores it.
    - **Proposed remedy category**: signal-gating — skip the tighten (or require N consecutive material scans) when the triggering scan's `layer_scores` contain a degraded channel; alternative: tighten on a last-K-scans material-rate instead of a single scan. Not implemented here.

    - **ID**: AUDIT-4B-4
    - **Title**: Re-baseline does not arbitrate in-flight scans — a rebaseline is accepted while a scan is running, and the scan completes against the anchor it captured at start (demoted mid-flight)
    - **Severity**: Low — justified: the scan row records its `baseline_id`, so the anchor is always traceable and the verdict is internally honest; impact is bounded to confusing history (a scan whose verdict references a no-longer-current trust anchor, no marker tying it to the replacement). No correctness break: `_run_scan` reads its bound baseline at task start and the promote is atomic (single transaction, `uq_baselines_one_inflight_per_site` backstops concurrent captures).
    - **Subsystem / file(s)**: `app/services.py` `rebaseline_site` (409s on in-flight BASELINES only — `is_stale` on `created_at` — no scan-side arbitration), `worker/scan_tasks.py` `_capture_baseline` (demote-previous/promote-this single transaction).
    - **Reproduction**: live — with scan `276eedc7` running on the example site, `POST /api/sites/{id}/rebaseline` → **HTTP 202**; capture `b7de1bf4` promoted at 00:30:17.720, 30 ms after the scan completed against the old anchor `ff54c418`; had the capture finished earlier the scan would have completed against a demoted baseline.
    - **Root cause**: the in-flight arbitration contract was written per-resource (baseline-vs-baseline, scan-vs-scan, both with unique-index arbiters) with no cross-resource rule for "trust anchor being replaced while a scan that reads it is in flight".
    - **Proposed remedy category**: contract choice — either document the anchor-at-enqueue semantics explicitly (cheap; `scans.baseline_id` already preserves it), or 409/supersede in-flight scans when a rebaseline starts (expensive; kills useful concurrent work). Not implemented here.
    - **Source**: kickoff hunt list "claim/supersede arbitration (a re-baseline superseding an in-flight scan)".

    - **Source**: kickoff's explicit "what repeated AUDIT-4-2 transients do to a site's cadence over days" question.


    - **ID**: AUDIT-4B-5
    - **Title**: Stale-row recovery latency is bounded by the site's `next_scan_at`, not by the 10-minute staleness window — a killed scan leaves a "running" row that can sit for a full interval before anything recovers it, and the recovery only fires on a due tick
    - **Severity**: Low — justified: no work is lost (the site is scanned at its next due tick anyway; "delay by one interval" is the documented contract and holds), but the interim state lies to operators: the scan history shows a scan "running" for e.g. 59 minutes, then failed with "superseded". Recovery-by-usr-action exists (trigger/rebaseline check `is_stale` opportunistically), so only unattended waits are affected.
    - **Subsystem / file(s)**: `worker/beat_tasks.py` (stale check only inside the per-site due path), `app/scanning.py` `STALE_INFLIGHT` vs `celery_app.py` hard limit 480 s (margin verified sound: 480 < 600).
    - **Reproduction**: live end-to-end — scan `6f8422c2` SIGKILLed at 00:31:28 mid-run (`docker kill wardress-worker-1` while status running, Redis `unacked`=1); message purged from `unacked`/`unacked_index` (simulating total loss); tick 00:35:57 logged `skipped_inflight: 1` (fresh) and advanced the schedule; after `next_scan_at` was manually made due, tick 00:42:57 logged `recovered_stale: 1`, row failed "Scan never completed — superseded by a scheduled scan", replacement scan `8a07e4d4` enqueued and completed. Without the manual due-nudge the row would have been recovered at the site's natural next due tick (~01:30).
    - **Root cause**: by design — staleness is evaluated only when the site is already due. The gap is the misleading interim row presentation, not the mechanics.
    - **Proposed remedy category**: presentation/state-taxonomy — distinguish "superseded (bookkeeping)" from detection-failure rows in the history surface, or add an independent low-frequency stale-row sweep that also covers non-due sites (and baselines, which today have NO beat-side stale sweep at all — a stuck pending/capturing baseline recovers only via operator action).
    - **Source**: timer/lifecycle hunt item "stale-inflight sweep vs the 480s hard time limit".


    - **ID**: AUDIT-4B-6
    - **Title**: The beat heartbeat measures worker tick EXECUTION, not beat liveness — under worker saturation the health page reports scheduling as stalled even while the beat container publishes fine (and conversely, tick `expires=120` silently drops ticks from a backlogged queue, which also starves the heartbeat)
    - **Severity**: Low — justified: the signal is arguably honest (scans genuinely aren't draining) and the code comment (`beat_tasks.py` ~:76-80, "the tick runs on a worker") acknowledges the coupling; but the operator-facing semantics ("Beat" indicator) do not match the mechanism, and the `expires=120` drop is invisible (no counter, no log).
    - **Subsystem / file(s)**: `worker/beat_tasks.py` heartbeat write (best-effort, per-tick), `app/routers/health.py` `_BEAT_STALE = 5 min` heuristic, `setup_periodic_tasks` `expires` values.
    - **Reproduction**: code-trace + live configuration observation (worker prefork concurrency 12 confirmed via `celery inspect stats`; heartbeat key written by the tick task execution, not by the beat process). The saturation scenario was not soaked live (would require saturating the shared stack).
    - **Root cause**: one signal (tick execution) is asked to answer two questions (is beat alive? is the worker draining?) because the tick task is the only periodic thing the system has.
    - **Proposed remedy category**: signal separation — have the beat process write its own lightweight liveness key directly (it already runs inside the app image and can reach Redis), and report tick-execution lag as a separate degraded-scheduling signal; optionally count expired ticks. Not implemented here.
    - **Source**: kickoff hunt list "the beat/dispatch module(s)"; resource/convoy item.


    - **ID**: AUDIT-4B-7
    - **Title**: Worker memory ceiling scales with concurrency × per-child model footprint and children are never recycled — 12 prefork children each lazily load torch+MiniLM+Playwright and retain them, with no `--max-tasks-per-child`; full warm concurrency extrapolates past the observed 7.4 GiB host ceiling
    - **Severity**: Low — justified: an OOM-killed child is RECOVERED by design (WorkerLostError → row stuck running → stale sweep at 10 min; recovery path verified sound), so the blast radius is lost work + failed-scan noise, not a hang; but on small hosts (the observed one has 7.4 GiB) 12 warm children can plausibly OOM-spiral, and every OOM feeds the AUDIT-4B-5 misleading-row presentation.
    - **Subsystem / file(s)**: `Dockerfile.worker` CMD (default prefork concurrency = host CPU count; `max-tasks-per-child: N/A` verified live via `celery inspect stats`), per-child MiniLM load in `worker/detection`; live docker stats: idle 1.34 GiB → 1.84 GiB with 2 concurrent scans (retained after).
    - **Reproduction**: live partial (2-scan concurrency probe with docker stats sampling); the 12-child warm state was NOT soaked (would risk OOM on the shared host) — the extrapolation is labeled as such, per Rule 12 honesty.
    - **Root cause**: default concurrency (CPU count) is uncoupled from memory budget; per-process model retention is a deliberate latency win with an uncosted memory multiplier.
    - **Proposed remedy category**: capacity configuration — pin `-c` (and/or `--max-tasks-per-child`) in the worker CMD to a documented memory budget, or document host-RAM-per-concurrent-scan in the install docs. Not implemented here.
    - **Source**: resource/convoy hunt item "MiniLM/SSIM CPU contention between concurrent scans".


    - **ID**: AUDIT-4B-8
    - **Title**: Deployment drift: the running stack predates PROMPT-002 Phases 8-11 in two files (deployed `scan_tasks.py` has NO `NOISE_FLOOR` — verdict `changed` fires on ANY nonzero layer score; deployed `scanning.py` differs comment-only); also the beat schedule file lives in the container FS, not on a volume
    - **Severity**: Low (for this phase's scope) — the orchestration mechanics audited here are identical between container and HEAD, so every other finding attests the deployed system too; the drift is a detection-semantics mismatch (AUDIT-4's territory, recorded here because it was discovered via Rule 13 parity hashing and because it amplifies AUDIT-4B-3's history-noise impact). The beat schedule file (`/app/celerybeat-schedule.db`, PersistentScheduler, verified live) is lost on container recreate — benign by construction (CAS claims + idempotent janitors make every periodic task safe to fire-on-restart) but undocumented.
    - **Subsystem / file(s)**: deployed `worker/scan_tasks.py` vs HEAD (git hash-object comparison: `d5d74f1d…` vs `a6878b37…`; the diff is exactly the Phase-11 NOISE_FLOOR block), deployed vs HEAD `scanning.py` (comment-only), `docker-compose.yml` beat service (no volume for the schedule file).
    - **Reproduction**: `docker cp` + `git hash-object` parity check across 9 orchestration files (7 match HEAD exactly); `git diff --no-index` of the 2 mismatching files shows precisely the Phase-11 delta and a comment block.
    - **Root cause**: the image was built from a mixed working-tree state (neither 1eeea6b nor HEAD); no build pins the commit. The schedule file location is a default, never a decision.
    - **Proposed remedy category**: deployment hygiene — rebuild the stack from HEAD before any remediation-phase verification (hard requirement: remediation proofs must run against the code they claim to fix), and consider baking a build-commit marker; optionally volume-mount or relocate the beat schedule file and document its restart semantics. Not implemented here.

- **Verified-clean ledger (fresh-eyes, evidence per item)**:
    - Beat CAS claim: live — the tick's conditional `UPDATE ... WHERE next_scan_at == seen` advanced the schedule atomically on every observed dispatch (`due/enqueued/lost_claim` counters consistent across ~25 ticks); two-tick overlap pinned by `test_phase37` `test_overlapping_ticks_both_complete_single_scan_per_site`.
    - Advance-before-enqueue: live — `next_scan_at` moved to `now+interval` at claim time, before the task existed.
    - Duplicate suppress: live — scan-now during a running scan → HTTP 409 "A scan of audit4b-example is already in progress"; `ix_scans_one_inflight_per_site` / `uq_baselines_one_inflight_per_site` declared in models AND migrations (no metadata↔schema drift for the two in-flight arbiters).
    - Fresh in-flight skip: live — tick logged `skipped_inflight: 1` for a 4.5-min-old running row.
    - Stale recovery: live — `recovered_stale: 1` at 00:42:57 for the 11.5-min-old killed row; supersede + replacement scan atomically written (single transaction, supersede and INSERT commit together).
    - Kill-while-pending: live — worker SIGKILLed with the message undelivered (`unacked`=0): after restart the scan ran normally pending→running→completed (pending loss is harmless; only the unacked mid-flight case matters).
    - acks_late redelivery idempotency: hermetic — `_run_scan`/`_capture_baseline` early-return `"scan-already-{status}"`/`"baseline-already-{status}"` before any side effect; also proven live indirectly (the superseded row's own message, if redelivered, no-ops). Concurrent double-execution of one scan row is unreachable: visibility timeout (kombu default 3600 s, `broker_transport_options={}` verified live) ≫ 480 s hard limit, and `task_reject_on_worker_lost` default False acks WorkerLostError'd messages (row recovered by the DB sweep instead — consistent).
    - `deliver_alert` idempotency: live — existing-delivery guard → `"already-delivered"`; resweep positive control live (`alerts_reenqueued: 1` → `deliver_alert` → `'no-channels'`, no crash).
    - `fire_remediation` claim: code-trace — conditional UPDATE with rowcount arbiter + `executed_at` stamp + reclaim predicate (status queued AND stamp stale) + `uq_remediation_executions_hook_scan`; per-attempt terminal-state guarantee (a crash marks failed, never stuck queued).
    - `_schedule_next` boundaries: hermetic (existing scheduler tests + new transient test); swallow-all wrapper verified (scheduling can never fail a scan).
    - Re-baseline hint gate: live + code-trace — `_rebaseline_hint` reads `capture_meta["capture_method_version"]` (exact key written by the capture, evidence-preferred with `CAPTURE_METHOD_VERSION` fallback); fresh-site response showed `baseline_capture_method_version: null`, `needs_rebaseline: false` (absence = unknown, not old — as documented).
    - Site/baseline deletion mid-flight: code-trace — scan early-returns `"missing-prereqs"`/`"scan-row-missing"`; artifacts orphaned → daily janitor (UUID-gated, tests green).
    - Enqueue degradation: `app/tasks.py` broker-only client (backend=None), OperationalError/RuntimeError → 503 → routers mark committed rows failed — pinned by `test_tasks_enqueue.py` (5 passed).

    - **Source**: Rule 13 environment attestation; the user's report that the image "is from commit 1eeea6b" (verified not exactly true — ancestor, not the build).


- **Log-vs-reality discrepancies**:
    - `celery_app.py` docstring ("acknowledge late so a crashed worker never silently drops a scan") vs reality: the broker does NOT promptly redeliver a kill-orphaned message — live-verified that kombu performs no unacked restore at worker startup and the message sat in Redis `unacked` for the full visibility timeout (default 3600 s; `broker_transport_options={}` confirmed). What actually recovers a killed scan is the DB stale-inflight sweep on the next due tick. The claim's spirit (nothing is silently lost) holds; its mechanism description (redelivery) does not. Worth a docstring correction in the remediation pass.
    - `beat_tasks.py` module docstring ("even a lost enqueue can only delay a site by one interval, never duplicate it") — verified TRUE live and by trace, including the harder corollary (the lost message ALSO delays the stuck row's recovery until the next due tick — AUDIT-4B-5).
    - PROMPT-003 main file §4 labels Audit Phase 4B "Data Model, Schema & Migrations" and 4D "task orchestration" — the actual execution order (per kickoffs + Phase 2B inventory) makes 4B orchestration/scheduling; noted so future readers don't hunt for a schema audit under this heading (schema coverage happened in Phase 2B + here for the two in-flight arbiters).


- **New hermetic tests added this phase**: `backend/tests/test_phase4b_orchestration_repros.py` — 5 tests, ALL committed-passing (each characterizes CURRENT behavior per Rule 1; none is a tautology — each asserts observable DB/task outcomes):
    - `test_flagged_scan_redelivery_cannot_recover_missing_alert` — pins AUDIT-4B-1 (alert loss unrecoverable by redelivery AND resweep).
    - `test_resweep_recovers_stranded_alert_enqueue` — positive control: resweep works when the alert row exists (send captured).
    - `test_backlogged_pending_scan_superseded_by_dispatch_tick` — pins AUDIT-4B-2 (15-min pending row superseded; old message's redelivery no-ops).
    - `test_inflight_skip_still_advances_next_scan_at` — pins the advance-then-check ordering (skip pushes schedule out one interval).
    - `test_repeated_material_risk_transients_hold_cadence_at_base_quarter` — pins AUDIT-4B-3 (alternating transients never return to base; clean ladder [360,540,810,1215]→base).

- **Opportunities / Innovation ideas observed** (Rule 17 — not severity-scored, not gap-driven):
    - **Idea**: adaptive dispatch budget — reuse the health router's `_queue_depth` primitive to scale `MAX_DISPATCH_PER_TICK` (or gate dispatch entirely) by broker depth.
    - **Why it would help**: converts the fixed 50/tick ceiling into a self-limiting system that keeps scan START latency bounded during bursts (bulk import, mass tightened cadence) and removes the AUDIT-4B-2 amplification precondition without new infrastructure.
    - **Where it touches**: `worker/beat_tasks.py` (dispatch tick), `app/routers/health.py` `_queue_depth` (extract to a shared module).
    - **Rough shape of the change**: read Redis LLEN at tick start; skip/shrink the due-batch when depth exceeds workers × K; emit the decision in the tick stats dict. Sketch only.
    - **Idea**: supersede-as-taxonomy — render "superseded by a scheduled scan" rows as a distinct bookkeeping category (UI filter + count) instead of generic failed scans.
    - **Why it would help**: operator trust: today a killed/backlogged scan and a genuine detection failure are indistinguishable in history; the error string already encodes the distinction.
    - **Where it touches**: frontend scan history (`site-detail.tsx`), optionally `ScanDetailOut`.
    - **Rough shape of the change**: match on the supersede error marker (or better, persist a dedicated `superseded` flag/reason enum at write time) and badge the row. Sketch only.



- **Full regression results** (Rule 13: every count from an actual run this session; backend `.venv`, real-PostgreSQL harness `wardress-test-pg`):
    - `python -m pytest tests/test_phase4b_orchestration_repros.py -q` → **5 passed** (4.3 s)
    - `python -m pytest tests/test_phase4b_orchestration_repros.py tests/test_scheduler.py -q` → **25 passed** (21.5 s)
    - `python -m pytest tests/test_scheduler.py -q` → **20 passed** (13.6 s; first combined run showed a transient ERROR from a prior interrupted run's shared-DB state — isolated re-run of that test passed, combined re-run 25 passed — documented, not hidden)
    - `python -m pytest tests/test_scan_tasks.py -q` → **24 passed** (16.1 s)
    - `python -m pytest tests/test_tasks_enqueue.py -q` → **5 passed** (19.0 s)
    - `python -m pytest tests/test_phase37_scheduling_agent_remediation.py -q` → **12 passed** (14.7 s)
    - `python -m pytest tests/test_phase18_concurrency_races.py -q` → **8 passed** (16.0 s)

- **Findings out of phase scope** (logged for the correct future phase, not investigated here):
    - Live-observed capture failures on rfc-editor.org and datatracker.ietf.org (screenshot timeout / capture failure chains) → belongs to Phase 3's remediation prompt (build on AUDIT-3-*) and stress Phases 5A/5C.
    - Deployed pre-Phase-11 verdict semantics (NOISE_FLOOR absent) → detection-layer remediation territory (AUDIT-4 scope); recorded here only as the AUDIT-4B-8 rebuild requirement.
    - API-surface behaviors touched en passant (scan-now/rebaseline 409/202 shapes, health page semantics, mute) → Audit Phase 4C.
    - Ops agent + Telegram surfaces consume the shared `services.py` claim paths; those surfaces themselves remain excluded per §0.

- **Commit**: ef5eb8c — test(audit-4b): orchestration & scheduling fresh-eyes audit — finding repros + Phase 4B log entry (recorded post-commit; not pushed)


    - TOTAL: 74 tests across the six subsystem-adjacent suites, 0 failures. (The full ~725-test suite was not repeated this phase — the session's command runner caps at 30 s per invocation; the six suites above cover every file the phase touched plus direct callers/callees. No production file was modified — zero production-edit risk by construction.)

### [DONE] PROMPT-003 Audit Phase 4C — API-Surface & Dependency-Chain Fresh-Eyes Audit

- **Prompt**: PROMPT-003-capture-detection-audit-and-stress-hardening.md
- **Session date**: 2026-09-11
- **Assigned subsystem**: §4 Audit Phase 4C — the entire HTTP surface: `app/routers/*` (13 routers: sites, auth, users, apikeys, audit, imports, remediation, artifacts, alerts, settings+channels+ai, reports, agent, health), `app/schemas.py`, the auth/dependency chain (`app/deps.py`, `app/security.py`, `app/apikeys.py`, `app/ratelimit.py`), the audit-write seam (`app/audit.py`), the surface side of `app/services.py` (ServiceError → HTTPException translation; claim mechanics belong to 4B), `app/tasks.py` (503 enqueue contract), `app/explain.py`, `app/reporting.py` + `routers/reports.py`, `app/site_icons.py`, `app/ssrf.py`, `app/db.py`, `app/config.py`, `app/crypto.py`, `Dockerfile.app`, `docker-compose.yml` healthcheck, and `app/main.py` middleware/exception-handler stack. Built on, not re-derived: AUDIT-4B-4/-5/-6 scheduling semantics and AUDIT-4's verdict-path constants (NOISE_FLOOR, flagged/changed, escalation band 0.40-0.75, MATERIAL_CHANGE_RISK=0.40 consumed at the surface but not re-audited).



- **Method & parity note (§3 fresh-eyes protocol)**:
  - All 31 audited API files (16 app modules + 13 routers + routers/`__init__.py`) verified **container-vs-HEAD MATCH** via `docker cp` + `git hash-object` (the 4B protocol; no API-surface drift — unlike 4B's 7/9 orchestration files). Every live assertion below is therefore HEAD-valid.
  - Live battery against the running stack (`wardress-app-1`, healthy): script preserved at `Prompts/Pending/Finders/PROMPT-003/scratch/audit4c_live_probe.ps1`. Two throwaway users (analyst/viewer) created and removed; one real site created → baseline captured ready → scan-now → completed `clean` → explain probed → site deleted. Login-limiter burst used a nonexistent account only. Stack left clean (no leftover sites/users; probe audit rows remain, which is correct audit behavior).
  - Every code-read hypothesis was tested before logging: one candidate finding ("UserCreate accepts non-email strings") was **falsified live** — POST /api/users with `definitely-not-an-email` → 422 "a valid email address is required" (the schema carries a validator beyond the Field constraint the truncated code read missed). Not logged as a finding (Rule 13).

- **Live-verified surface behavior (all as coded, no surprises)**: 401 + `WWW-Authenticate: Bearer` with generic detail on missing/garbage/expired/`wk_`-prefixed-bogus credentials; 403 messages name the required role; API keys cannot manage credentials (key creation & logout via key → 403); foreign agent conversations 404 (no existence leak); NaN/Infinity bodies → 422 "Request body is not valid JSON" before pydantic; 2 MB body → 413 before parsing; non-UUID path params → standard 422 `uuid_parsing`; missing resource → 404 with user-safe detail; DELETE replay → 404; bulk import per-row outcomes live (`created` / `skipped duplicate` / `error: Could not resolve host 'a---4c.test'`); sitemap+`allow_private_networks` as analyst → 403 admin gate; scan-now without ready baseline → 409 naming the site; rebaseline during in-flight capture → 409; explain on a completed scan with no AI provider → 503 user-safe; login lockout + dedicated per-IP login limiter → 429 with `Retry-After` (8 of 35 burst requests); favicon OFF → 404 with zero outbound work; no rate-limit headers on 2xx (only 429 carries `Retry-After`) — noted, acceptable.

- **Findings**:

  - **ID**: AUDIT-4C-1
  - **Title**: Single-site create with a dead broker answers 503 "try again shortly" after the site is already committed; the invited retry 409s with "A site with this URL already exists"
  - **Severity**: Medium — operator-facing contract dishonesty exactly during the outage scenario the codebase otherwise handles carefully; not a security break, no data loss, self-heals via 409, but the response actively misleads the retry.
  - **Subsystem / file(s)**: `backend/app/services.py` (`create_site` commits site+baseline, then `_enqueue_or_fail` re-commits the baseline as failed and raises `QueueUnavailableError`), `backend/app/routers/sites.py` (`_http_from_service` → 503). Contrast: `routers/imports.py` handles the identical outage per-row with "created — baseline capture could not be enqueued … use Rebaseline once it is back".
  - **Reproduction**: hermetic, committed-passing — `backend/tests/test_phase4c_api_surface_repros.py::test_create_site_dead_broker_commits_site_then_503s` (dead-broker Celery client; asserts QueueUnavailableError with "try again", then the site row EXISTS, baseline failed, and an immediate retry raises ConflictError "already exists").
  - **Root cause**: `create_site` commits before enqueue (correct for row-safety) but the failure surface speaks only "queue down, retry" — it cannot tell the client the site half-succeeded, and the message's imperative contradicts the committed state. Bulk import solved the same problem with a per-row degraded-success shape; single create never got the parity pass.
  - **Proposed remedy category**: surface-contract fix — give create-site the bulk-import degradation shape (201 + degraded detail pointing at Rebaseline) or a 503 whose message states the site was created and should not be re-created.
  - **Source**: fresh-eyes hunt list ("503 enqueue-degradation surfacing to every caller") + cross-surface parity read of imports.py vs sites.py.

  - **ID**: AUDIT-4C-2
  - **Title**: `/docs`, `/redoc`, `/openapi.json` served unauthenticated and outside the rate-limit middleware — full API schema (92.5 KB) public on a security-monitoring product
  - **Severity**: Medium — unauthenticated disclosure of the entire attack surface: every route, parameter bound, error model, and design commentary (e.g. the `wk_` key prefix, role semantics, lockout behavior in descriptions). Not Critical: no secrets or data in the schema; single-host self-hosted deployment; cheap to close.
  - **Subsystem / file(s)**: `backend/app/main.py` (FastAPI ctor never sets `docs_url`/`redoc_url`/`openapi_url` — grep confirms zero occurrences; rate-limit middleware meters only paths starting `/api/`).
  - **Reproduction**: live — `GET /openapi.json` → 200 (92500 bytes), `GET /docs` → 200, `GET /redoc` → 200, no credentials, no rate budget consumed. Also pinned hermetically: `test_phase4c_api_surface_repros.py::test_openapi_docs_redoc_public_unauthenticated` (committed-passing, ASGI transport).
  - **Root cause**: FastAPI defaults left enabled; the §9 hardening pass metered "the API surface" as `/api/*` and never revisited the doc surface that ships alongside it by default.
  - **Proposed remedy category**: config/gating change — disable docs/redoc/openapi in production builds (ctor args, optionally env-gated for dev) or route them behind auth.
  - **Source**: fresh-eyes hunt list (authn completeness per route); Rule 13 probe.



  - **ID**: AUDIT-4C-3
  - **Title**: Site mute exists as two implementations: REST `PATCH /api/sites/{id}` inline vs shared `services.mute_site` (bot/agent) — with divergent audit snapshots (REST omits the `via` field)
  - **Severity**: Low — semantics are currently equivalent (same 7-day clamp via schema bound vs `MUTE_CAP_MINUTES`, same `site.mute` action, same snapshot keys), so nothing misbehaves today; the finding is the standing drift risk on exactly the drift class `services.py`'s module docstring says it exists to eliminate, plus a non-uniform audit trail for the same action across surfaces.
  - **Subsystem / file(s)**: `backend/app/routers/sites.py` (inline mute inside `update_site`) vs `backend/app/services.py` `mute_site` (called by `app/agent/tools.py` and `worker/telegram_bot.py`; records `after={**snapshot, "via": via}`).
  - **Reproduction**: hermetic, committed-passing — `test_phase4c_api_surface_repros.py::test_rest_mute_audit_shape_diverges_from_services_mute` (PATCH → audit `after_json` has no `via`; `services.mute_site(via="telegram")` → `after_json["via"] == "telegram"`).
  - **Root cause**: mute was folded into the site-PATCH handler instead of delegating to the shared action; the shared service's contract list claims mute as one of its core actions but REST never calls it.
  - **Proposed remedy category**: refactor — route the REST mute path through `services.mute_site` so audit shape and clamping live once.
  - **Source**: fresh-eyes hunt list (cross-surface parity: REST vs the shared services.py call sites).

  - **ID**: AUDIT-4C-4
  - **Title**: `DELETE /api/sites/{id}` has no in-flight guard and discloses no cascade scope — a site whose baseline capture is mid-flight deletes with 204, and the operator is never told what disappears
  - **Severity**: Low — the destructive action is analyst-gated and audited (before-snapshot preserved), artifact dirs are reaped by the beat janitor's daily orphan-dir sweep (`worker/beat_tasks.py`), and in-flight worker writes land on missing rows handled worker-side; the harm is operator surprise (irreversible loss of scan/alert/suppression/remediation history) and asymmetry with the rest of the surface.
  - **Subsystem / file(s)**: `backend/app/routers/sites.py` `delete_site` (no guard, 204 empty body, comment defers artifact cleanup "to a later phase" — that janitor has since landed in beat_tasks); FK cascade map in `app/models.py` (baselines/scans/suppression_rules/alerts+deliveries/per-site notification channels/remediation hooks+executions all `ondelete=CASCADE`).
  - **Reproduction**: live — created a site, observed `baseline_status=pending`, `DELETE` → 204 while capture ran; replay → 404. No 409, no body. (Contrast: create/scan-now/rebaseline all 409 on in-flight work.)
  - **Root cause**: delete implemented as a bare cascade with no in-flight arbitration and no response contract enumerating the destruction.
  - **Proposed remedy category**: surface-contract fix — either 409 while a capture/scan is in flight (consistent with the surface's own convention) or an endpoint description + response summary of destroyed row counts.
  - **Source**: fresh-eyes hunt list (idempotency/safety at the surface: DELETE cascade visibility).

  - **ID**: AUDIT-4C-5
  - **Title**: health.py readiness docstring cites a compose healthcheck that no longer exists in that form — the stack's healthcheck curls `/api/health/live`, not `/api/health`
  - **Severity**: Low — comment-only drift (Rule 13 target); behavior is fine. Residual note: `GET /api/health` remains an unauthenticated DB-reachability oracle returning "database unreachable" detail; acceptable for the self-hosted model but should be a stated decision, not an accident of a stale justification.
  - **Subsystem / file(s)**: `backend/app/routers/health.py` readiness route ("Backward-compatible with the Phase 0 compose healthcheck, which curls /api/health") vs `docker-compose.yml` and `docker inspect wardress-app-1` healthcheck = `curl -sf http://localhost:8000/api/health/live` (verified both).
  - **Reproduction**: docker inspect + compose file read; no runtime probe needed.
  - **Root cause**: the healthcheck target was later moved to `/live` without updating the readiness route's justification comment.
  - **Proposed remedy category**: doc-only fix (re-anchor the readiness route's reason, or re-point the route if no consumer remains).
  - **Source**: fresh-eyes hunt list (Dockerfile/healthcheck contract).


  - **ID**: AUDIT-4C-6
  - **Title**: Three routes double-charge the per-user rate limit: the auth dependency already meters every authenticated request, then icon/validate/pull call `enforce_user_rate_limit` again
  - **Severity**: Low — a burst-heavy dashboard (favicon loads) or admin loop (AI validate / Ollama pull) consumes 2 of the 240/min budget per request; consistent (the same three routes do it), deliberate-looking, but undocumented — the effective budget halves with no statement of intent.
  - **Subsystem / file(s)**: `backend/app/deps.py` (per-user charge in `get_auth_context`) × `backend/app/routers/sites.py` (`icon`), `backend/app/routers/settings.py` (`validate_ai_provider`, `pull_ollama_model`).
  - **Reproduction**: code-read (all sites charge the same `user:{id}` bucket); not separately stress-tested (below Rule 18 threshold — deterministic, not variance-prone).
  - **Root cause**: explicit per-route charges predate/ignore the dependency-level limiter; "rate-limited per user since images load in bursts" (icon docstring) is true twice over without saying so.
  - **Proposed remedy category**: decide-and-document — either declare the double-charge as intentional burst weighting in each docstring, or drop the redundant calls.
  - **Source**: fresh-eyes hunt list (rate-limit coverage and whether the gaps matter).

  - **ID**: AUDIT-4C-7
  - **Title**: `DELETE /api/users/{id}` hard-deletes any non-self user regardless of usage — destroying their API keys and agent chat history (FK CASCADE) with no surface disclosure; module docstring claims the opposite intent
  - **Severity**: Low — admin-gated, audited (before-snapshot keeps email; audit rows survive via `actor_id SET NULL` + denormalized `actor_email`, verified live: the deleted viewer's audit rows remain attributable), refresh tokens/API keys are credentials (clean to destroy); the surprise is irreversible loss of the user's agent conversations and the doc/behavior gap.
  - **Subsystem / file(s)**: `backend/app/routers/users.py` `delete_user` (docstring "Hard delete exists for cleanup of never-used accounts" — no such precondition is enforced) and the `app/models.py` FK map (`api_keys.user_id`, `agent_conversations.user_id` CASCADE; `audit_log.actor_id`, `sites.created_by`, `suppression_rules.created_by`, `alerts.acknowledged_by`, `remediation_*.created_by/confirmed_by` SET NULL — history-preserving, correct).
  - **Reproduction**: live — created viewer, exercised it (agent conversation created), `DELETE` → 204, user gone from list, login 401, audit rows still attributable via denormalized email.
  - **Root cause**: hard delete shipped as a plain cascade; the docstring's stated scope was never wired as a precondition.
  - **Proposed remedy category**: contract/doc fix — enforce the "never-used account" precondition the docstring promises, or correct the docstring and disclose the cascade scope in the endpoint description.
  - **Source**: fresh-eyes hunt list (contract honesty: docstrings are hypotheses; DELETE cascade visibility).

- **Log-vs-reality discrepancies**: none against PROMPT-002 logs (out of scope this phase). Intra-repo comment-vs-reality captured as AUDIT-4C-5 (health docstring) and inside AUDIT-4C-4 (sites.py janitor comment: "cleaned by a janitor task in a later phase" — the janitor now exists in `worker/beat_tasks.py`; cleanup is covered, the comment is stale). One self-falsified candidate (UserCreate email validation) noted in Method.

- **New hermetic tests added this phase**: `backend/tests/test_phase4c_api_surface_repros.py` — three tests, all **committed-passing** (3/3 green): dead-broker create-site 503 partial-success repro (AUDIT-4C-1); unauthenticated docs/openapi exposure pin (AUDIT-4C-2); REST-vs-services mute audit-shape divergence repro (AUDIT-4C-3). Live probe script preserved (not a pytest): `Prompts/Pending/Finders/PROMPT-003/scratch/audit4c_live_probe.ps1`.

- **Opportunities / Innovation ideas observed** (Rule 17):
  - **Idea**: paginate `GET /api/sites` (or cap its eager baseline-summary join).
  - **Why it would help**: bulk import admits 500 sites per call and the list endpoint returns all sites + two baseline queries with no bound; dashboards degrade gracefully today only because installs are small.
  - **Where it touches**: `backend/app/routers/sites.py` `list_sites`; frontend sites page.
  - **Rough shape of the change**: offset/limit + total like the alerts/scans/audit pages already have (their pagination contract is the in-repo pattern to copy).
  - **Idea**: escape LIKE metacharacters in the audit-log `actor` filter.
  - **Why it would help**: `AuditLog.actor_email.ilike(f"%{actor}%")` treats `%`/`_` in the query as wildcards; searching for a literal address containing them silently over-matches (admin-only read filter — correctness nit, not security).
  - **Where it touches**: `backend/app/routers/audit.py` actor filter.
  - **Rough shape of the change**: escape `%`/`_`/`\` before interpolation, or exact-match plus an explicit "contains" mode.
  - **Idea**: record failed explain attempts.
  - **Why it would help**: `record_audit` for `scan.explain` is staged on the same session the 503 path rolls back, so only successful explains leave an audit trace; repeated forced regenerations (cost/quota events) are invisible when they fail.
  - **Where it touches**: `backend/app/routers/sites.py` explain route; `app/explain.py`.
  - **Rough shape of the change**: commit the audit row on its own session (or before the LLM call) so attempts, not just successes, are auditable.
  - **Idea**: shared SiteDetailOut assembler (carried lead).
  - **Why it would help**: four separate `SiteDetailOut(...)` construction sites in `routers/sites.py` still risk drifting (PROMPT-002 Phase 7 lead (b), re-confirmed present in current code).
  - **Where it touches**: `backend/app/routers/sites.py`.
  - **Rough shape of the change**: one helper taking (site, baseline, degraded_count) → SiteDetailOut.

- **Full regression results**:
  - New repro file: `uv run pytest tests/test_phase4c_api_surface_repros.py` → **3 passed**.
  - API-surface suites (18 files: test_phase4_api, test_auth, test_phase5_rbac, test_phase5_users_apikeys, test_phase4_alerting, test_sites_router_integrity, test_phase17_auth_audit, test_phase5_health, test_phase5_bulk_import, test_phase5_ratelimit_ssrf, test_tasks_enqueue, test_services, test_phase5_audit, test_main, test_security, test_sites, test_artifacts, test_phase5_remediation): first batched run reported **3 failed / 10 errors / 237 passed** — all failures localized to `test_phase4_api.py` and root-caused to **my own accidental double-launch** of pytest against the single-contract test database (two sessions collided; both were killed mid-run). Isolated re-run: `uv run pytest tests/test_phase4_api.py` → **31 passed** (clean). Combined honest count: 237 + 31 = 268 passed, 0 genuine failures.
  - No production file was modified (Rule 1). Live-stack side effects cleaned up (throwaway users/sites deleted).

- **Findings out of phase scope**: none new — the remaining AI-config SSRF posture nuance (legacy `PUT /api/settings/ollama` `validate_url=False` save path vs use-time validation in `ai_config.py`) is logged for Audit Phase 4E's awareness, not investigated here; the scheduler mechanics the delete-with-in-flight-capture case exercises belong to 4B's territory (4C-4 records the surface side only).

- **Commit**: fedfbf7 — PROMPT-003 Audit Phase 4C: API-surface repro tests + live probe script (diagnosis only); this log entry is committed immediately after, referencing that hash (not pushed).
- **Next phase kickoff prompt**: delivered in chat only — never written to this log.

### [DONE] PROMPT-003 Audit Phase 4D — Fresh-Eyes Code Audit: Task Orchestration, Alert & Remediation Delivery

- **Prompt**: PROMPT-003-capture-detection-audit-and-stress-hardening.md
- **Session date**: 2026-09-19
- **Assigned subsystem**: §4 Audit Phase 4D — `backend/worker/scan_tasks.py`, `worker/remediation_tasks.py`, `worker/alert_tasks.py`, `worker/beat_tasks.py`, `worker/celery_app.py`, `app/alerting.py`, `app/remediation.py`, `app/explain.py`, `app/site_icons.py`, templates (`email/alert.html`, `email/test.html`, `report/report.html`). Caller/callee seams traced: `worker/db.py` (fresh engine per task), `app/scanning.py` (STALE_INFLIGHT, adaptive cadence), `app/tasks.py`, `app/ssrf.py` + `app/ssrf_transport.py`, `app/routers/remediation.py` (confirm/dismiss claims), `app/routers/alerts.py`, `app/reporting.py` + `app/routers/reports.py` (report.html renderer), `app/models.py` (Alert/AlertDelivery/RemediationExecution/RemediationHook), and the delivery-path suites.

- **Cold-read verification of the phase's named hunt areas**:

| Hunt area | Verdict | Evidence |
|---|---|---|
| Scan/baseline crash mid-write consistency | Verified within its documented limits | `capture_baseline`/`run_scan` wrappers contain every unexpected error and land the row terminal-failed (`_mark_baseline_failed`/`_mark_scan_failed`, no-op-safe on completed rows); soft/hard limits 420/480 (`celery_app.py:44-45`) sit under STALE_INFLIGHT (10 min); baseline promotion is demote+promote in one transaction. Residual non-atomic artifact writes / no fencing / janitor-state mismatch already logged as AUDIT-3-4 (Low) — cross-referenced, not re-found. |
| Alert row creation unreachability on worker death (AUDIT-4B-1) | CONFIRMED — still open | Cold re-read: terminal commit → `_create_alert` (separate commit; sole `Alert(` creation site, `scan_tasks.py:366-381`) → `_create_remediations` → `_schedule_next`; `_run_scan` redelivery early-returns `scan-already-completed` before all three; `resweep_undelivered` only re-enqueues deliveries for alerts that EXIST. 4B's committed repro `test_phase4b_orchestration_repros.py` re-ran green this session. No duplicate finding logged — AUDIT-4B-1 stands as canonical. |
| Alert delivery idempotency and retry backpressure | Gaps found | AUDIT-4D-1 (any-row guard orphans later channels after a mid-loop crash), AUDIT-4D-2 (check-then-act guard double-sends under concurrency), AUDIT-4D-6 (channel-less alerts re-swept forever). Positive: failures are rows (visible), no Celery retry storms (wrapper returns "error", message acked), muted sites write skipped rows (terminating the sweep). |
| Human-approval gating on remediation webhooks | Verified solid, one Low edge | Default `requires_manual_confirm=True` → `pending_confirm`; only the analyst/admin confirm endpoint's conditional-UPDATE claim moves a row to `queued`; auto hooks are explicit opt-ins cooldown-downgraded into the confirm queue; `fire_remediation` fires ONLY queued rows; dismissed rows never fire; hook deletion cascades queued executions (test-pinned). Edge logged as AUDIT-4D-7 (queued auto firings survive a mid-flight flip of the hook to manual-confirm). |
| Remediation crash-after-claim windows (AUDIT-2B-3) | PARTIALLY CLOSED — verified with residue | 2B-3's "terminal `confirmed` row, 409 forever" no longer exists: `_fire` claims via conditional UPDATE stamping `executed_at` while the row stays `queued` under a STALE_INFLIGHT lease (`remediation_tasks.py:55-70`); the resweep re-enqueues queued rows past a 5-min grace; the router's stale re-confirm path reclaims confirmed-but-unenqueued rows after STALE_INFLIGHT; `test_remediation_claim_race.py` (10 tests) green. Residue inherent to the remedy: reclaim after lease expiry re-POSTs without knowing whether the first POST landed — at-least-once firing semantics (pinned one-way by `test_fresh_claim_blocks_retry_until_stale_window_passes`: fresh claim blocks, stale claim re-POSTs). Payload carries `scan_id` for receiver-side dedupe. Logged as accepted-by-design residue under 2B-3, not a new finding. |
| Beat interval shortening starvation | No new finding | Dispatcher claims oldest-due-first with per-site error isolation and a CAS claim (`Site.next_scan_at == seen_next_scan_at`); overlapping ticks arbitrate safely (loser skips); MAX_DISPATCH_PER_TICK bounds each tick. Overload amplification (AUDIT-4B-2) and cadence pinning (AUDIT-4-2) are already logged; no individual-site starvation path found beyond those. |
| SSRF redirect validation in site_icons.py | Gaps found | Redirect-to-internal IS closed (manual hops, scheme check, per-hop re-gate; `test_redirect_chain_hop_validation_rejects_internal_landing` green). But the fetch rides an unpinned `httpx.AsyncClient`: AUDIT-4D-3 (check-vs-connect rebinding window the raw-httpx stack elsewhere closes with `SSRFPinningTransport`) and AUDIT-4D-4 (the "size-capped so a hostile server cannot exhaust memory" docstring claim is not delivered — `client.get` buffers the full body before truncation). |
- **Findings**:

    - **ID**: AUDIT-4D-1
    - **Title**: A mid-delivery crash permanently orphans every channel after the crash point — the "any delivery row exists" guard and the zero-rows resweep predicate can never re-arm a partially-delivered alert
    - **Severity**: High — justified per §6.4 ("a documented spec requirement simply not met — a true Gap"): alert_tasks.py's module contract states "Delivery failures become alert_deliveries rows with status=failed and a user-safe detail, visible in the dashboard" — after a mid-loop crash the later channels have NO rows: no failure record, nothing visible, no retry path ever. The window is real and WIDER than AUDIT-4B-1's: per-channel commits span the whole delivery loop (SMTP/Apprise timeouts are 20-40 s each), and the identical loss is produced by a DB hiccup on any per-channel commit (exception propagates, wrapper returns "error", message is acked — no redelivery). Detection→notification is the system's core output (same justification standard as 4B-1's High).
    - **Subsystem / file(s)**: `worker/alert_tasks.py` (`_deliver_alert` any-row guard :77-81, per-channel commit :162-166), `worker/beat_tasks.py` (`_resweep_undelivered` zero-rows predicate :326-346)
    - **Reproduction**: hermetic, committed-passing: `tests/test_phase4d_delivery_repros.py::test_crash_mid_delivery_orphans_remaining_channels_permanently` — two channels; the second channel's send raises; the first row is committed; the re-run returns "already-delivered"; `_resweep_undelivered()` reports `alerts_reenqueued == 0`; the second channel has no delivery row and none ever appears.
    - **Root cause**: the idempotence guard is wrong-grained (ANY delivery row ⇒ "delivered") while commits are per-channel; recovery keys on the same coarse predicate (zero rows), so the two mechanisms meet exactly nowhere for the partial case.
    - **Proposed remedy category**: idempotence-granularity change — guard/resweep keyed per (alert_id, channel_id) instead of any-row, or a per-channel claim row written before each send (the repo's conditional-UPDATE primitive), plus a sweep pass that re-enqueues alerts having channels without delivery rows.
    - **Source**: kickoff hunt list "alert delivery idempotency and retry backpressure"; fresh-eyes crash-window analysis of `_deliver_alert`.

    - **ID**: AUDIT-4D-2
    - **Title**: Alert delivery's idempotence guard is check-then-act, not an atomic claim — concurrent invocations double-send every channel
    - **Severity**: Medium — a real concurrency-invariant violation (the repo's own standard elsewhere: remediation's claim primitive exists precisely because "duplicate queue messages" are treated as possible), but reaching it requires a concurrent duplicate delivery (resweep re-enqueue while the original is still mid-delivery past the 5-min grace, or a broker duplicate); harm is duplicate notifications, not data corruption.
    - **Subsystem / file(s)**: `worker/alert_tasks.py:77-81` (plain SELECT guard) vs `worker/remediation_tasks.py:49-70` (the claim primitive this same codebase uses for exactly this hazard)
    - **Reproduction**: hermetic, committed-passing: `tests/test_phase4d_delivery_repros.py::test_concurrent_delivery_invocations_double_send` — two concurrent `_deliver_alert` calls with a 0.1 s window inside the send; both return "sent=1"; two AlertDelivery rows exist for the one channel.
    - **Root cause**: the guard is a plain SELECT with no arbitration between check and first commit; two sessions both observe zero rows.
    - **Proposed remedy category**: atomic claim — per-(alert, channel) claim row via conditional UPDATE (rowcount arbitrates) before sending, mirroring remediation's `executed_at` lease.
    - **ID**: AUDIT-4D-3
    - **Title**: The favicon resolver fetches through an unpinned httpx client — the check-vs-connect DNS rebinding window that the rest of the raw-httpx stack closes is open on this path
    - **Severity**: Medium — justified: this is the same SSRF hardening class the codebase treats as must-close on every other raw-httpx outbound fetch (worker/probe.py's httpx client and app/remediation.py's webhook POST both ride `SSRFPinningTransport`); here validation resolves DNS at gate time and lets httpx resolve again at connect. Not Critical: `app/ssrf.py` itself is untouched (Rule 12's auto-Critical applies to the policy file, not to consumers); the feature is default-OFF opt-in; the hostname comes from the stored site URL; redirect-to-internal IS closed; and the same residual class is documented-and-accepted for the Playwright path (ssrf.py docstring; AUDIT-3-3). Secondary, same root: `assert_url_allowed`'s blocking `socket.getaddrinfo` runs directly on the event loop for every hop (probe.py/remediation avoid this; site_icons does not).
    - **Subsystem / file(s)**: `app/site_icons.py` (`_fetch_with_gates` :105-140, `attempt_favicon_fetch` :171-223); contrast `app/ssrf_transport.py`, `app/remediation.py:182-185`
    - **Reproduction**: hermetic, committed-passing: `tests/test_phase4d_delivery_repros.py::test_favicon_fetch_builds_unpinned_httpx_client` — instruments `httpx.AsyncClient` construction and proves no `transport` kwarg (no pinning transport) on any client the resolver builds. The rebinding flip itself needs live DNS control (out of hermetic scope) — construction proof plus code-trace.
    - **Root cause**: the resolver pre-dates/discards the pinning discipline; each hop is re-gated at check time only.
    - **Proposed remedy category**: transport parity — route the icon client through `SSRFPinningTransport(allow_private_networks=site.allow_private_networks)`; move any remaining per-hop gate's blocking DNS off the event loop (or drop the now-redundant gate in favour of the transport's per-request validation).
    - **Source**: kickoff hunt list "SSRF redirect validation in site_icons.py"; same class as AUDIT-3-3's unpinned-network-path finding.

    - **ID**: AUDIT-4D-4
    - **Title**: "Downloads are size-capped (64 KiB) so a hostile server cannot exhaust memory" is not delivered — the body is fully buffered into RAM before the cap truncates
    - **Severity**: Medium — justified: a partial implementation that does not meet the stated intent (§6.4). A hostile monitored site — the exact adversary this system exists to watch — can stream an arbitrarily large body to any dashboard client that triggers an icon fetch, multiplied by concurrent loads, bounded only by the attacker's goodwill.
    - **Subsystem / file(s)**: `app/site_icons.py` (`_fetch_with_gates` :136-139: `resp.content[: max_bytes + 1]` after a plain `client.get`; same shape for the 256 KiB homepage cap; docstring claim :21-22)
    - **Reproduction**: code-trace: `httpx.AsyncClient.get()` reads the entire response body into memory before returning; the slice applies afterwards. `test_site_icons.py::test_oversize_payload_aborts` pins the TRUNCATION contract (payload over the cap is refused) but cannot observe the buffering, because its fake fetcher never exercises real transport buffering.
    - **Root cause**: the cap is implemented as post-hoc truncation instead of a streaming byte budget.
    - **Proposed remedy category**: streaming read — `client.stream(...)` with an incremental byte budget that aborts past max_bytes+1, applied to both the icon and homepage fetches.
    - **Source**: kickoff hunt list (SSRF/validation in site_icons.py); docstring-vs-reality check (Rule 13).


    - **Source**: kickoff hunt list "alert delivery idempotency"; contrast with the remediation path's discipline.


    - **ID**: AUDIT-4D-5
    - **Title**: The auto-fire cooldown is anchored to execution `created_at`, not `executed_at` — a firing delayed by queue backlog lands outside the intended cooldown window
    - **Severity**: Low — bounded harm (at most one extra unattended firing per boundary case) and the conservative direction is preserved (the brake still downgrades to the confirm queue; manual-confirm hooks are never affected).
    - **Subsystem / file(s)**: `app/remediation.py:124-138` (`func.max(RemediationExecution.created_at)` over queued/succeeded/failed rows)
    - **Reproduction**: hermetic, committed-passing: `tests/test_phase4d_delivery_repros.py::test_auto_fire_cooldown_anchors_on_created_at_not_executed_at` — a prior execution created 40 min ago but actually POSTed 5 min ago; a fresh flagged scan's auto firing is queued for unattended execution instead of being parked in the confirm queue.
    - **Root cause**: the cooldown proxy uses row-creation time because rows exist before they fire; `executed_at` (the actual outbound stamp) is never consulted.
    - **Proposed remedy category**: anchor the window on `max(executed_at)` with a `created_at` fallback for never-fired rows — noting that pending_confirm→queued→fired lifecycle means "held" rows must keep counting from creation.
    - **Source**: kickoff hunt list (human-approval gating / flap control); fresh-eyes read of the cooldown query.

    - **ID**: AUDIT-4D-6
    - **Title**: Alerts that can never be delivered (no active channels) are re-enqueued by the re-delivery sweep on every run, forever
    - **Severity**: Low — pure churn (one SELECT plus one send_task attempt every 5 min per stranded alert, capped at 200/run), no incorrect behavior; but it is unbounded-over-time work for a permanently-undeliverable state, with no operator signal that the alert went nowhere.
    - **Subsystem / file(s)**: `worker/alert_tasks.py:99-104` (the "no-channels" early return writes nothing), `worker/beat_tasks.py:326-346` (zero-rows predicate)
    - **Reproduction**: hermetic, committed-passing: `tests/test_phase4d_delivery_repros.py::test_no_channel_alert_resweep_reenqueues_forever` — an aged alert with no channels: the sweep re-enqueues it (count 1), delivery returns "no-channels" with zero rows, and the next sweep matches it again (count 1).
    - **Root cause**: the sweep's recovery predicate (zero delivery rows) cannot distinguish "enqueue lost" from "delivery structurally impossible"; the no-channels path never writes a row, so the predicate never clears.
    - **Proposed remedy category**: terminal-state marker — a `skipped` delivery row ("no channels configured") or an alert-level state so the sweep's predicate terminates, surfaced in the dashboard either way.
    - **Source**: kickoff hunt list "retry backpressure"; fresh-eyes trace of the resweep predicate.

    - **ID**: AUDIT-4D-7
    - **Title**: Flipping a hook to `requires_manual_confirm=True` does not recall already-queued auto firings — human-approval gating is not retroactive
    - **Severity**: Low — narrow window (a queued execution fires within one worker pickup, or is reclaimed after the 10-min stale lease and fires then); the operator's policy change has no effect on executions already past the approval gate. Bounded, timing-dependent, and arguably the documented design (rows are only ever claimed by an explicit confirm OR by the explicit auto opt-in at creation).
    - **Subsystem / file(s)**: `app/routers/remediation.py` (`update_hook` flips `requires_manual_confirm`; no UPDATE touches existing `queued` executions), `worker/remediation_tasks.py` (`_fire` fires any queued row within its lease)
    - **Reproduction**: code-trace: an auto hook created a queued execution awaiting a worker → the admin sets `requires_manual_confirm=True` → the queued row still fires on the next pickup (or on stale-lease reclaim). No test pins or prevents this.
    - **Root cause**: the manual-confirm gate is evaluated at execution-creation time only; there is no recall/hold primitive for already-queued rows.
    - **Proposed remedy category**: policy-surface decision — either document the boundary explicitly (approval gating is evaluated per firing creation) or add a sweep that downgrades queued rows of hooks whose `requires_manual_confirm` is currently True back to `pending_confirm`.
    - **Source**: kickoff hunt list "human-approval gating on remediation webhooks".

    - **ID**: AUDIT-4D-8
    - **Title**: Concurrent "explain this incident" requests race past the cache check and both pay the LLM call
    - **Severity**: Low — wasted provider cost and a benign last-write-wins on the cached explanation; no correctness or security impact (both writes are valid text).
    - **Subsystem / file(s)**: `app/explain.py:146-184` (cache check → generate → write, with no claim in between)
    - **Reproduction**: code-trace: two concurrent requests for the same unexplained scan both observe `scan.explanation is None`, both call `task.generate`, both commit; the second overwrites the first.
    - **Root cause**: cache-fill has no single-flight primitive (contrast the repo's conditional-UPDATE claim pattern used by site_icons/remediation).
    - **Proposed remedy category**: single-flight — conditional `UPDATE scans ... WHERE id = :id AND explanation IS NULL` (or a claim column) so only the first generator's bill is paid; losers read the winner's row.
    - **Source**: fresh-eyes read of `explain_scan` (in-scope target file).


- **Log-vs-reality discrepancies**: none. Every Phase 1-7-era claim touching these files reproduced: `test_phase4_alerting.py`'s delivery/idempotence/muted/undecryptable suite (20 tests), `test_remediation_claim_race.py` (10 claim-race proofs incl. the fresh-vs-stale lease window), `test_phase31_critical_paths.py` (firing-path + wrapper contracts), `test_phase4b_orchestration_repros.py` (4B-1/4B-2 repros), `test_phase26_remediation_hooks.py`, `test_phase5_remediation.py`, `test_phase37_scheduling_agent_remediation.py`, `test_scheduler.py`, `test_site_icons.py` — all green before and after my additions. One documentation-vs-reality divergence found and logged as AUDIT-4D-4 (the site_icons docstring's memory-exhaustion claim), and one contract-vs-reality divergence logged as AUDIT-4D-1 (the alert_tasks module docstring's "failures become ... rows ... visible in the dashboard" promise).

- **New hermetic tests added this phase**: `backend/tests/test_phase4d_delivery_repros.py` — 5 tests, all committed-passing (Rule 5/10):
  - `test_crash_mid_delivery_orphans_remaining_channels_permanently` — AUDIT-4D-1: partial delivery is permanently orphaned; sweep cannot re-arm it.
  - `test_concurrent_delivery_invocations_double_send` — AUDIT-4D-2: the guard is check-then-act; one channel POSTed twice.
  - `test_no_channel_alert_resweep_reenqueues_forever` — AUDIT-4D-6: the zero-rows predicate re-matches a permanently undeliverable alert on every run.
  - `test_auto_fire_cooldown_anchors_on_created_at_not_executed_at` — AUDIT-4D-5: cooldown keyed on creation, not the outbound POST stamp.
  - `test_favicon_fetch_builds_unpinned_httpx_client` — AUDIT-4D-3: no pinning transport on any client the favicon resolver builds.
  - Hermeticity notes: `celery_app.send_task` is stubbed at module level (the real Redis result backend retry-connects for ~20 s per call, which would stall the suite); `task_session` is pointed at the real disposable Postgres via the suite's alembic-migrated schema. No production file was touched (Rule 1).

- **Opportunities / Innovation ideas observed** (Rule 17 — not severity-scored, not gap-driven):

    - **Idea**: O-4D-1 — fleet delivery-health rollup on the health page
    - **Why it would help**: the delivery path's failure modes are per-row today; a rollup (alerts with any failed delivery in the last 24 h, per-channel failure rates, channel-less alerts, partial-delivery alerts) would turn a silent delivery outage into one number an operator sees immediately.
    - **Where it touches**: `app/routers/health.py` (summary query), `frontend/src/pages/health.tsx`
    - **Rough shape of the change**: aggregate `alert_deliveries` by channel_type/status over a window + count alerts whose delivery count < active channel count; render as a small table.

    - **Idea**: O-4D-2 — structured delivery outcome enum instead of free-text `detail`
    - **Why it would help**: `detail` strings ("SMTP authentication failed", "webhook returned HTTP 500") are human-only today; a small `reason_code` alongside the text would let the UI group failures, let alerting-on-alerting work, and let the resweep's decisions be data-driven rather than predicate-guessing.
    - **Where it touches**: `app/models.py` (AlertDelivery, RemediationExecution), `worker/alert_tasks.py`, `app/remediation.py`, delivery test fixtures
    - **Rough shape of the change**: add a nullable code column + a constant map; populate at each failure branch; no behavior change.

    - **Idea**: O-4D-3 — idempotency-key header on remediation webhooks
    - **Why it would help**: the lease-reclaim path is at-least-once by design (2B-3 residue) and the payload's `scan.id` is the only dedupe handle a receiver has; an explicit `Idempotency-Key: <hook_id>:<scan_id>` header (plus documenting the retry semantics) would let receivers dedupe without reaching into the body.
    - **Where it touches**: `app/remediation.py::post_webhook` (headers), docs
    - **Rough shape of the change**: one header dict built from the hook/execution ids already in scope; no contract change to the body.

- **Full regression results** (Windows host, Docker stack up — wardress-app/worker/beat/db/redis + disposable wardress-test-pg on 127.0.0.1:5433; every run against the alembic-migrated production-dialect schema, one pytest session per database):
  - New repro file: `cd backend && uv run --frozen pytest tests/test_phase4d_delivery_repros.py -q` → **5 passed in 4.36s** (0 failed, 0 skipped).
  - Delivery-subsystem batch: `uv run --frozen pytest tests/test_phase4_alerting.py tests/test_phase4b_orchestration_repros.py tests/test_remediation_claim_race.py tests/test_phase31_critical_paths.py tests/test_site_icons.py tests/test_scheduler.py tests/test_phase4_scan_integration.py tests/test_phase19_alert_ack_race.py tests/test_phase26_remediation_hooks.py tests/test_phase5_remediation.py tests/test_phase37_scheduling_agent_remediation.py tests/test_phase4d_delivery_repros.py -q` → **146 passed in 109.74s** — 0 failed, 0 skipped.
  - Lint: `uv run --frozen ruff check tests/test_phase4d_delivery_repros.py` → **All checks passed!**
  - No production file was modified this phase (Rule 1); the live stack was used read-only (containers inspected, no probes issued).

- **Findings out of phase scope** (logged for the correct future phase, not investigated here):
  - The unpinned-network-path class on the browser (Playwright) and raw-socket TLS-probe paths is AUDIT-3-3's territory (capture pipeline) — AUDIT-4D-3 records only the favicon-path instance, cross-referencing rather than re-deriving it.
  - `app/routers/reports.py`'s WeasyPrint rendering internals (worker-thread offload, error mapping) sit in 4C's API-surface scope; only the `report/report.html` template's rendering contract (autoescape, no `|safe`) was checked here.
  - `worker/telegram_bot.py`'s alert-channel duties were verified only as a caller of the shared alerting helpers; its own transport/parse surface belongs to the ops-agent boundary (§0) and is out of scope.

- **Commit**: `1e0f7d8` — feat(audit-4d): alert/remediation delivery repro tests (diagnosis only); this log entry is committed immediately after, referencing that hash (not pushed).
- **Next phase kickoff prompt**: delivered in chat only — never written to this log.

